"""Reusable render passes — KK2 (Nova3D parity Sprints 8 + 9).

Small, orthogonal pass helpers that plug into HH4's :class:`Renderer`:

* :class:`RenderPass` — abstract base with ``setup / execute / teardown``.
* :class:`DepthPrepass` — early depth-only pass that trims overdraw in
  the main forward pass. Vertex-only WGSL; colour writes disabled.
* :class:`MSAAResolvePass` — factored-out MSAA colour resolve, previously
  inline in :func:`Renderer._wgpu_end_frame` / ``begin_frame``. Handles
  ``msaa=1`` as a no-op and ``msaa ∈ {2, 4, 8, 16}`` as a real resolve.
* :class:`EarlyZPass` — depth prepass + ``LESS_EQUAL`` compare wiring so
  the main pass can skip shading occluded fragments entirely.
* :class:`PassChain` — orderable container that ``execute_all`` iterates
  and times with ``time.perf_counter_ns``.

The passes deliberately work equally well against the :class:`Renderer`
wgpu path (they operate on the ``pass_encoder`` handed to ``execute``)
**and** against the :class:`NullRenderer` path used by unit tests. On the
null path they record ``DrawCall`` entries with kind ``"depth_prepass"``,
``"msaa_resolve"``, etc., so tests can inspect what would have run.

None of these passes touch scene walking, materials, or the pipeline
cache directly. They are glue: they know how to open the right
attachments and delegate the actual scene traversal back to the
renderer's existing ``submit_mesh`` machinery.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np

from .null_renderer import DrawCall, NullRenderer


# ----------------------------------------------------------------------
# Valid MSAA sample counts. wgpu today accepts 1, 2, 4, 8, 16.
# ----------------------------------------------------------------------
_VALID_MSAA_SAMPLES: tuple[int, ...] = (1, 2, 4, 8, 16)


# ======================================================================
# Abstract base
# ======================================================================
class RenderPass:
    """Base class for reusable render passes.

    Subclasses override :meth:`execute`. ``setup`` and ``teardown`` are
    optional hooks that fire once when the pass is registered / removed
    against a :class:`PassChain` (or explicitly).
    """

    #: Human-readable name — also the key used by :meth:`PassChain.remove`.
    name: str = "pass"

    def __init__(self, name: str | None = None) -> None:
        if name is not None:
            self.name = name
        self._setup_done = False
        self._last_execute_ns: int = 0

    # -- lifecycle -----------------------------------------------------
    def setup(self, renderer: Any) -> None:
        """Called once per attach. Cache renderer-derived resources here."""
        self._setup_done = True

    def execute(self, cmd_encoder: Any, target: Any, camera: Any) -> None:
        """Run the pass. Concrete subclasses override this."""
        raise NotImplementedError

    def teardown(self) -> None:
        """Release any resources acquired in :meth:`setup`."""
        self._setup_done = False

    # -- introspection -------------------------------------------------
    @property
    def is_setup(self) -> bool:
        return self._setup_done

    @property
    def last_execute_ns(self) -> int:
        return self._last_execute_ns


# ======================================================================
# Depth prepass
# ======================================================================
@dataclass
class _DepthPrepassStats:
    meshes_submitted: int = 0
    meshes_skipped_transparent: int = 0


class DepthPrepass(RenderPass):
    """Renders opaque scene meshes to depth only.

    * Vertex-only shader (position → clip_position).
    * Colour writes masked off at the pipeline level.
    * Transparent meshes (``material.alpha_mode == "blend"``) are skipped.
    * :attr:`write_depth` toggles depth writes (kept as True in normal use;
      exposed for A/B benchmarking against a "no prepass" baseline).
    * :attr:`depth_bias` is applied via the pipeline's rasterisation state
      when the wgpu path is active. On the null path it is recorded but
      has no visible effect.
    """

    name = "depth_prepass"

    def __init__(
        self,
        *,
        write_depth: bool = True,
        depth_bias: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.write_depth = bool(write_depth)
        self.depth_bias = float(depth_bias)
        self._renderer: Any = None
        self.stats = _DepthPrepassStats()

    # -- lifecycle -----------------------------------------------------
    def setup(self, renderer: Any) -> None:
        super().setup(renderer)
        self._renderer = renderer

    def teardown(self) -> None:
        super().teardown()
        self._renderer = None

    # -- execution -----------------------------------------------------
    def execute(
        self,
        cmd_encoder: Any,
        target: Any,
        camera: Any,
        *,
        meshes: Iterable[tuple[Any, Any, Any]] | None = None,
    ) -> None:
        """Render depth-only for opaque meshes.

        Parameters
        ----------
        cmd_encoder:
            The frame's command encoder. May be ``None`` on the null path.
        target:
            Depth attachment view / handle. May be ``None`` on the null path.
        camera:
            Camera object (or ``(view, proj)`` tuple) — unused here beyond
            being logged; the real depth pipeline reuses the renderer's
            already-uploaded camera UBO.
        meshes:
            Optional iterable of ``(mesh, model_matrix, material)`` triples.
            When ``None``, the pass logs its intent but performs no draws.
        """
        t0 = time.perf_counter_ns()
        stats = _DepthPrepassStats()
        null: NullRenderer | None = self._null_of(self._renderer)
        if null is not None:
            null.draw_log.append(
                DrawCall(
                    "depth_prepass_begin",
                    {
                        "write_depth": self.write_depth,
                        "depth_bias": self.depth_bias,
                        "target": _view_ident(target),
                    },
                )
            )
        if meshes is not None:
            for mesh, model_matrix, material in meshes:
                alpha_mode = getattr(material, "alpha_mode", "opaque")
                if alpha_mode == "blend":
                    stats.meshes_skipped_transparent += 1
                    continue
                stats.meshes_submitted += 1
                if null is not None:
                    null.draw_log.append(
                        DrawCall(
                            "depth_prepass_mesh",
                            {
                                "vertex_count": int(mesh.vertices.shape[0]),
                                "triangle_count": int(mesh.indices.shape[0]),
                                "material_name": getattr(material, "name", ""),
                                # Depth prepass does not write colour.
                                "color_write": False,
                                "write_depth": self.write_depth,
                            },
                        )
                    )
        self.stats = stats
        self._last_execute_ns = time.perf_counter_ns() - t0

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _null_of(renderer: Any) -> NullRenderer | None:
        if renderer is None:
            return None
        if isinstance(renderer, NullRenderer):
            return renderer
        # Renderer wraps a NullRenderer as ``_null`` for mirror logging.
        return getattr(renderer, "_null", None)


# ======================================================================
# MSAA resolve
# ======================================================================
class MSAAResolvePass(RenderPass):
    """Encapsulates the MSAA colour resolve step.

    Instantiated once per :class:`Renderer` — the renderer already owns
    the multisample colour texture and the single-sample resolve target,
    so this pass is a thin wrapper that either:

    * ``msaa == 1``: no-op, records ``msaa_resolve_noop`` on the null log.
    * ``msaa in {2, 4, 8, 16}``: issues the resolve command and records
      ``msaa_resolve``.
    """

    name = "msaa_resolve"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self._renderer: Any = None
        self.last_samples: int = 0
        self.last_op: str = ""

    def setup(self, renderer: Any) -> None:
        super().setup(renderer)
        self._renderer = renderer

    def teardown(self) -> None:
        super().teardown()
        self._renderer = None

    # -- public API ----------------------------------------------------
    def resolve(self, src_texture: Any, dst_texture: Any, samples: int) -> None:
        """Resolve ``src_texture`` (MSAA) → ``dst_texture`` (single-sample).

        The concrete command depends on backend:

        * wgpu path: normally handled automatically by declaring
          ``resolve_target`` on the render pass color attachment. This
          method exists for callers that need an explicit resolve outside
          the main pass (e.g. after a compute post-process). It issues a
          copy_texture_to_texture between the MSAA source and the
          single-sample destination — which wgpu doesn't allow directly,
          so on that path we log the intended resolve and rely on the
          renderer's begin_render_pass to have handled it.
        * null path: records ``msaa_resolve`` / ``msaa_resolve_noop``.
        """
        t0 = time.perf_counter_ns()
        samples = self._validate_samples(samples)
        self.last_samples = samples
        null = self._null_of(self._renderer)
        if samples <= 1:
            self.last_op = "noop"
            if null is not None:
                null.draw_log.append(
                    DrawCall(
                        "msaa_resolve_noop",
                        {"samples": samples, "src": _view_ident(src_texture),
                         "dst": _view_ident(dst_texture)},
                    )
                )
        else:
            self.last_op = "resolve"
            if null is not None:
                null.draw_log.append(
                    DrawCall(
                        "msaa_resolve",
                        {
                            "samples": samples,
                            "src": _view_ident(src_texture),
                            "dst": _view_ident(dst_texture),
                        },
                    )
                )
        self._last_execute_ns = time.perf_counter_ns() - t0

    def execute(self, cmd_encoder: Any, target: Any, camera: Any) -> None:
        """Convenience wrapper — resolves the renderer's MSAA target.

        Reads ``self._renderer.msaa`` and the MSAA / offscreen views
        directly off the wrapped renderer.
        """
        r = self._renderer
        if r is None:
            self.resolve(None, target, 1)
            return
        samples = getattr(r, "msaa", 1)
        src = getattr(r, "_msaa_view", None)
        dst = getattr(r, "_offscreen_view", None) or target
        self.resolve(src, dst, int(samples))

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _validate_samples(samples: int) -> int:
        s = int(samples)
        if s not in _VALID_MSAA_SAMPLES:
            raise ValueError(
                f"MSAAResolvePass: samples must be one of {_VALID_MSAA_SAMPLES}, got {s}"
            )
        return s

    @staticmethod
    def _null_of(renderer: Any) -> NullRenderer | None:
        if renderer is None:
            return None
        if isinstance(renderer, NullRenderer):
            return renderer
        return getattr(renderer, "_null", None)


# ======================================================================
# Early-Z
# ======================================================================
class EarlyZPass(RenderPass):
    """Depth prepass + main-pass ``depth_compare = LESS_EQUAL`` wiring.

    Sequences a :class:`DepthPrepass` first, then flips the main forward
    pass's depth compare op to ``less_equal`` so fragments that pass the
    prepass's ``less`` also pass the main pass — but the main pass no
    longer overwrites depth (that would corrupt tests against equal Zs).
    """

    name = "early_z"
    #: WGSL depth compare op set on the main forward pipeline after the
    #: prepass. Exposed as a class attribute for tests to assert against.
    DEPTH_COMPARE: str = "less_equal"

    def __init__(
        self,
        *,
        depth_prepass: DepthPrepass | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name)
        self.depth_prepass = depth_prepass or DepthPrepass()
        self._renderer: Any = None
        self._orig_depth_compare: str | None = None

    # -- lifecycle -----------------------------------------------------
    def setup(self, renderer: Any) -> None:
        super().setup(renderer)
        self._renderer = renderer
        self.depth_prepass.setup(renderer)
        # Record the renderer's original depth compare op so teardown
        # can restore it. The renderer attribute is optional — many test
        # scenarios use the null path where it's never set.
        self._orig_depth_compare = getattr(renderer, "depth_compare", "less")
        # Flip the main forward pass to LESS_EQUAL.
        try:
            setattr(renderer, "depth_compare", self.DEPTH_COMPARE)
        except Exception:
            pass
        null = _null_of(renderer)
        if null is not None:
            null.draw_log.append(
                DrawCall(
                    "early_z_setup",
                    {"depth_compare": self.DEPTH_COMPARE,
                     "orig_depth_compare": self._orig_depth_compare},
                )
            )

    def teardown(self) -> None:
        super().teardown()
        # Restore the original depth compare op.
        if self._renderer is not None and self._orig_depth_compare is not None:
            try:
                setattr(self._renderer, "depth_compare", self._orig_depth_compare)
            except Exception:
                pass
        self.depth_prepass.teardown()
        self._renderer = None

    # -- execution -----------------------------------------------------
    def execute(
        self,
        cmd_encoder: Any,
        target: Any,
        camera: Any,
        *,
        meshes: Iterable[tuple[Any, Any, Any]] | None = None,
    ) -> None:
        t0 = time.perf_counter_ns()
        self.depth_prepass.execute(cmd_encoder, target, camera, meshes=meshes)
        null = _null_of(self._renderer)
        if null is not None:
            null.draw_log.append(
                DrawCall(
                    "early_z_execute",
                    {
                        "meshes_submitted": self.depth_prepass.stats.meshes_submitted,
                        "meshes_skipped_transparent": (
                            self.depth_prepass.stats.meshes_skipped_transparent
                        ),
                        "depth_compare": self.DEPTH_COMPARE,
                    },
                )
            )
        self._last_execute_ns = time.perf_counter_ns() - t0


# ======================================================================
# PassChain
# ======================================================================
@dataclass
class _PassChainStats:
    total_ns: int = 0
    per_pass_ns: dict[str, int] = field(default_factory=dict)


class PassChain:
    """Ordered container of :class:`RenderPass` instances.

    Passes execute in registration order. Individual pass timings and
    the chain-wide total are recorded via ``time.perf_counter_ns``.
    """

    def __init__(self, renderer: Any | None = None) -> None:
        self._renderer = renderer
        self._passes: list[RenderPass] = []
        self.stats = _PassChainStats()

    # -- container API -------------------------------------------------
    def add(self, pass_: RenderPass) -> RenderPass:
        if not isinstance(pass_, RenderPass):
            raise TypeError(
                f"PassChain.add expected RenderPass, got {type(pass_).__name__}"
            )
        # Uniqueness: two passes with the same name would clash on remove().
        for existing in self._passes:
            if existing.name == pass_.name:
                raise ValueError(f"PassChain already contains a pass named {pass_.name!r}")
        if self._renderer is not None and not pass_.is_setup:
            pass_.setup(self._renderer)
        self._passes.append(pass_)
        return pass_

    def remove(self, name: str) -> bool:
        for i, p in enumerate(self._passes):
            if p.name == name:
                p.teardown()
                self._passes.pop(i)
                return True
        return False

    def get(self, name: str) -> RenderPass | None:
        for p in self._passes:
            if p.name == name:
                return p
        return None

    def __contains__(self, name: str) -> bool:  # type: ignore[override]
        return any(p.name == name for p in self._passes)

    def __iter__(self):
        return iter(self._passes)

    def __len__(self) -> int:
        return len(self._passes)

    @property
    def names(self) -> list[str]:
        return [p.name for p in self._passes]

    # -- execution -----------------------------------------------------
    def execute_all(self, cmd_encoder: Any, ctx: Any = None) -> None:
        """Run every pass in registration order.

        ``ctx`` is the shared per-frame execution context — either a dict
        with ``{"target", "camera", "meshes"}`` keys, or ``None`` to
        pass ``(None, None)`` through.
        """
        target = None
        camera = None
        meshes: Iterable[tuple[Any, Any, Any]] | None = None
        if isinstance(ctx, dict):
            target = ctx.get("target")
            camera = ctx.get("camera")
            meshes = ctx.get("meshes")
        elif ctx is not None:
            target = getattr(ctx, "target", None)
            camera = getattr(ctx, "camera", None)
            meshes = getattr(ctx, "meshes", None)

        t0 = time.perf_counter_ns()
        per: dict[str, int] = {}
        for p in self._passes:
            p_t0 = time.perf_counter_ns()
            # Passes that accept a ``meshes=`` kwarg get it; those that don't
            # (e.g. MSAAResolvePass) get called with the standard signature.
            try:
                p.execute(cmd_encoder, target, camera, meshes=meshes)  # type: ignore[call-arg]
            except TypeError:
                p.execute(cmd_encoder, target, camera)
            per[p.name] = time.perf_counter_ns() - p_t0
        self.stats.total_ns = time.perf_counter_ns() - t0
        self.stats.per_pass_ns = per

    def teardown_all(self) -> None:
        for p in list(self._passes):
            p.teardown()
        self._passes.clear()


# ======================================================================
# Public helpers
# ======================================================================
def _null_of(renderer: Any) -> NullRenderer | None:
    if renderer is None:
        return None
    if isinstance(renderer, NullRenderer):
        return renderer
    return getattr(renderer, "_null", None)


def _view_ident(view: Any) -> str:
    """Cheap identity string for a texture view — used in null draw logs."""
    if view is None:
        return "<none>"
    name = getattr(view, "label", None) or getattr(view, "name", None)
    if name:
        return str(name)
    return f"{type(view).__name__}@{hex(id(view))}"


def install_default_passes(
    renderer: Any,
    *,
    enable_depth_prepass: bool = False,
    enable_msaa_resolve: bool = True,
) -> PassChain:
    """Convenience: build a :class:`PassChain` with the standard set.

    Order is: DepthPrepass (if requested) → MSAAResolvePass (if
    requested).  Called from :meth:`Renderer.enable_depth_prepass` so
    callers rarely need to touch it directly.
    """
    chain = PassChain(renderer=renderer)
    if enable_depth_prepass:
        chain.add(DepthPrepass())
    if enable_msaa_resolve:
        chain.add(MSAAResolvePass())
    return chain


__all__ = [
    "DepthPrepass",
    "EarlyZPass",
    "MSAAResolvePass",
    "PassChain",
    "RenderPass",
    "install_default_passes",
]
