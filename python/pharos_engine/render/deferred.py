"""Deferred renderer + G-buffer skeleton (Nova3D pillar 2, DDD4).

This module lands the *plumbing* for the deferred pipeline the Nova3D
integration report calls out at ``docs/nova3d_integration_plan_2026_07_19.md``
pillar 2. Full parity with Nova3D's ``DeferredRenderer.hpp`` is a
4-5 sprint effort; this file is the skeleton DDD5's material graph can
target and DDD6's cluster-shaded lighting can grow into.

Design summary
--------------
* Python owns the wgpu device, textures, and pipeline objects. Every
  wgpu import goes through the module-level ``_wgpu`` alias so tests
  can skip cleanly when the driver stack is unavailable.
* Rust ``_core.deferred_cluster`` (see ``src/deferred_cluster.rs``)
  bins lights into a 16x9x24 froxel grid on the CPU. Python calls it
  once per frame; the returned table is uploaded as a UBO/SSBO before
  the lighting pass. The Rust kernel is a naive O(N*M) stub — the
  perf win comes from vectorised bin math, not algorithmic tricks.
* WGSL shader source lives next to this file under
  ``render/shaders/deferred/``. The three shaders are:

    - ``gbuffer_write.wgsl``  — vertex + fragment writing 3 MRT targets
    - ``lighting_pass.wgsl``  — fullscreen fragment reading G-buffer +
      lights → HDR output
    - ``tonemap.wgsl``        — fullscreen ACES tonemap + gamma

G-buffer layout
---------------

+-----------------------+---------------+-------------------------------+
| Attachment            | Format        | Contents                      |
+=======================+===============+===============================+
| ``albedo``            | rgba8unorm    | RGB albedo + A material_mask  |
+-----------------------+---------------+-------------------------------+
| ``normal_roughness``  | rgba16float   | XY octahedral normal, Z rough,|
|                       |               | W reserved                    |
+-----------------------+---------------+-------------------------------+
| ``position_metallic`` | rgba16float   | XYZ world position + metallic |
+-----------------------+---------------+-------------------------------+
| ``depth``             | depth24plus   | depth attachment              |
+-----------------------+---------------+-------------------------------+

Total: 4 bytes + 8 bytes + 8 bytes + depth = 20 B / pixel colour + 4 B
depth. At 1920x1080 that's ~50 MiB of VRAM which is the accepted cost
of the deferred trade-off.

Public API
----------

.. autosummary::

   GBuffer
   DeferredRenderer
   load_shader_source

Usage
-----

::

    from pharos_engine.render.deferred import DeferredRenderer

    dr = DeferredRenderer(device, queue, resolution=(1280, 720))
    dr.render(scene, target_view)  # geometry -> lighting -> tonemap
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


# ---------------------------------------------------------------------------
# wgpu soft-import — every wgpu reference in this module goes through the
# module-level alias so tests can monkeypatch ``_wgpu`` to ``None`` and
# assert on the placeholder path.
# ---------------------------------------------------------------------------
try:  # pragma: no cover — optional dep
    import wgpu as _wgpu  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    _wgpu = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Shader source loading
# ---------------------------------------------------------------------------

_SHADER_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "shaders",
    "deferred",
)

# Public constant names so callers (tests, DDD5 material graph) can
# resolve shader paths without knowing the layout.
GBUFFER_WRITE_WGSL_PATH = os.path.join(_SHADER_DIR, "gbuffer_write.wgsl")
LIGHTING_PASS_WGSL_PATH = os.path.join(_SHADER_DIR, "lighting_pass.wgsl")
TONEMAP_WGSL_PATH = os.path.join(_SHADER_DIR, "tonemap.wgsl")


def load_shader_source(name: str) -> str:
    """Return the WGSL source for one of the deferred pipeline shaders.

    Parameters
    ----------
    name:
        One of ``"gbuffer_write"``, ``"lighting_pass"``, ``"tonemap"``.

    Raises
    ------
    ValueError
        If *name* is not a known deferred shader.
    FileNotFoundError
        If the WGSL file is missing from the on-disk package layout.
    """
    table = {
        "gbuffer_write": GBUFFER_WRITE_WGSL_PATH,
        "lighting_pass": LIGHTING_PASS_WGSL_PATH,
        "tonemap":       TONEMAP_WGSL_PATH,
    }
    try:
        path = table[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown deferred shader {name!r}; "
            f"expected one of {sorted(table)}"
        ) from exc
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# G-buffer
# ---------------------------------------------------------------------------

# Format strings kept as plain lowercase names so tests can compare
# without dragging in the wgpu enum. The runtime resolves these via
# ``_resolve_format`` when building actual textures.
ALBEDO_FORMAT = "rgba8unorm"
NORMAL_ROUGHNESS_FORMAT = "rgba16float"
POSITION_METALLIC_FORMAT = "rgba16float"
DEPTH_FORMAT = "depth24plus"

# Light-accumulation buffer (output of the lighting pass, input of the
# tonemap pass). rgba16float so we keep HDR range and negative overshoot
# from tonemapping headroom.
HDR_FORMAT = "rgba16float"


def _resolve_format(name: str) -> Any:
    """Return the wgpu ``TextureFormat`` enum member for *name*.

    Falls back to the raw string when wgpu isn't installed — the string
    is only used for equality tests in that case.
    """
    if _wgpu is None:
        return name
    return getattr(_wgpu.TextureFormat, name)


def _color_target_usage() -> Any:
    if _wgpu is None:
        return "render_attachment|texture_binding|copy_src"
    return (
        _wgpu.TextureUsage.RENDER_ATTACHMENT
        | _wgpu.TextureUsage.TEXTURE_BINDING
        | _wgpu.TextureUsage.COPY_SRC
    )


def _depth_target_usage() -> Any:
    if _wgpu is None:
        return "render_attachment"
    return _wgpu.TextureUsage.RENDER_ATTACHMENT | _wgpu.TextureUsage.TEXTURE_BINDING


@dataclass
class GBuffer:
    """Owns the four textures that make up a deferred G-buffer.

    Attributes
    ----------
    width, height:
        Render target size in pixels.
    albedo:
        rgba8unorm — RGB albedo + A material_mask.
    normal_roughness:
        rgba16float — XY octahedral normal, Z roughness, W reserved.
    position_metallic:
        rgba16float — XYZ world position + W metallic.
    depth:
        depth24plus — depth attachment.
    formats:
        Tuple of format-name strings in the same order as the fields
        above. Handy for tests and for validating pipeline creation.

    Notes
    -----
    * When wgpu isn't installed the four texture fields hold ``None``
      and the class still exposes the format strings via
      :attr:`formats` + :meth:`format_table`. Callers can rely on the
      layout regardless of the driver state.
    * The lighting pass reads all three colour targets bound as
      ``texture_2d<f32>`` in ``lighting_pass.wgsl``.
    """

    width: int
    height: int
    device: Any = None
    albedo: Any = None
    normal_roughness: Any = None
    position_metallic: Any = None
    depth: Any = None
    formats: tuple[str, str, str, str] = field(
        default=(
            ALBEDO_FORMAT,
            NORMAL_ROUGHNESS_FORMAT,
            POSITION_METALLIC_FORMAT,
            DEPTH_FORMAT,
        )
    )

    def __post_init__(self) -> None:
        if self.device is None or _wgpu is None:
            return
        self.albedo = self._create_colour(ALBEDO_FORMAT)
        self.normal_roughness = self._create_colour(NORMAL_ROUGHNESS_FORMAT)
        self.position_metallic = self._create_colour(POSITION_METALLIC_FORMAT)
        self.depth = self._create_depth(DEPTH_FORMAT)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _create_colour(self, fmt_name: str) -> Any:
        assert _wgpu is not None
        return self.device.create_texture(
            size=(self.width, self.height, 1),
            format=_resolve_format(fmt_name),
            usage=_color_target_usage(),
        )

    def _create_depth(self, fmt_name: str) -> Any:
        assert _wgpu is not None
        return self.device.create_texture(
            size=(self.width, self.height, 1),
            format=_resolve_format(fmt_name),
            usage=_depth_target_usage(),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format_table(self) -> tuple[tuple[str, str], ...]:
        """Return ``((name, format), …)`` for docs + tests."""
        return (
            ("albedo",            ALBEDO_FORMAT),
            ("normal_roughness",  NORMAL_ROUGHNESS_FORMAT),
            ("position_metallic", POSITION_METALLIC_FORMAT),
            ("depth",             DEPTH_FORMAT),
        )

    def views(self) -> tuple[Any, Any, Any, Any]:
        """Return ``(albedo_view, normal_view, position_view, depth_view)``.

        When wgpu isn't installed this returns four ``None`` values so
        tests can still exercise the shape without the driver.
        """
        if _wgpu is None or self.albedo is None:
            return (None, None, None, None)
        return (
            self.albedo.create_view(),
            self.normal_roughness.create_view(),
            self.position_metallic.create_view(),
            self.depth.create_view(),
        )


# ---------------------------------------------------------------------------
# DeferredRenderer
# ---------------------------------------------------------------------------

class DeferredRenderer:
    """Skeleton deferred renderer + light-accumulation buffer.

    The renderer owns:

    * a :class:`GBuffer` at ``resolution``
    * a single light-accumulation HDR texture (``rgba16float``)
    * three shader modules compiled once at ``__init__`` (or lazily on
      first use — see :meth:`_ensure_shaders`)
    * a Rust cluster-lights kernel handle (``_core.deferred_cluster``)
      when the ``_core`` extension is importable

    Parameters
    ----------
    device:
        wgpu device (``wgpu.GPUDevice``). ``None`` in headless tests.
    queue:
        wgpu queue. When *device* is ``None`` this may also be ``None``.
    resolution:
        ``(width, height)`` render target size.
    max_lights:
        Upper bound for the light buffer / cluster table. Matches
        Nova3D's default of 256; must match ``lights_pass.wgsl``'s
        ``array<Light, 256>``.

    Notes
    -----
    * The lighting-pass sampler is a linear/clamp default. DDD5's
      material graph will feed the sampler+per-material bind group.
    * Cluster resolution is fixed at ``16 x 9 x 24`` matching the
      report — 3,456 froxels covering the frustum.
    * ``render()`` is a scaffold: it dispatches geometry then lighting
      then tonemap, but each sub-pass is a no-op when wgpu isn't up.
      This keeps CI green while still exercising the plumbing.
    """

    CLUSTER_X = 16
    CLUSTER_Y = 9
    CLUSTER_Z = 24

    def __init__(
        self,
        device: Any,
        queue: Any,
        resolution: tuple[int, int] = (1280, 720),
        max_lights: int = 256,
    ) -> None:
        w, h = resolution
        self.width = int(w)
        self.height = int(h)
        self.device = device
        self.queue = queue
        self.max_lights = int(max_lights)

        # G-buffer + HDR accumulation buffer.
        self.gbuffer = GBuffer(self.width, self.height, device=device)
        self.hdr_texture: Any = None
        if device is not None and _wgpu is not None:
            self.hdr_texture = device.create_texture(
                size=(self.width, self.height, 1),
                format=_resolve_format(HDR_FORMAT),
                usage=_color_target_usage(),
            )

        # Shader modules are compiled lazily so unit tests can construct
        # the renderer without waiting on the driver.
        self._shader_modules: dict[str, Any] = {}
        # Frame counter — the tests assert we can spin many frames
        # without crashing.
        self.frames_rendered: int = 0

        # Optional Rust cluster kernel.
        self._core: Any = None
        try:  # pragma: no cover — extension is optional
            from pharos_engine import _core  # type: ignore[import-not-found]
            self._core = getattr(_core, "deferred_cluster", None)
        except Exception:
            self._core = None

    # ------------------------------------------------------------------
    # Shader compilation
    # ------------------------------------------------------------------

    def _ensure_shaders(self) -> None:
        """Compile the three WGSL shader modules if not already cached.

        No-op when wgpu is unavailable or the device is ``None``. Called
        from :meth:`render` so tests that only construct the renderer
        never touch the driver.
        """
        if _wgpu is None or self.device is None:
            return
        for name in ("gbuffer_write", "lighting_pass", "tonemap"):
            if name in self._shader_modules:
                continue
            src = load_shader_source(name)
            self._shader_modules[name] = self.device.create_shader_module(code=src)

    # ------------------------------------------------------------------
    # Pass drivers — each is deliberately minimal. DDD5 (material graph)
    # + DDD6 (clustered lighting) will grow these into full parity.
    # ------------------------------------------------------------------

    def render_geometry_pass(
        self,
        meshes: Sequence[Any],
        camera: Any,
    ) -> None:
        """Encode a single MRT pass writing every mesh into the G-buffer.

        When wgpu is available this opens a render pass with the three
        colour attachments + depth, iterates the meshes, and issues one
        draw per mesh. When wgpu is missing the method updates the
        frame counter and returns so callers still get a stable API.
        """
        self._ensure_shaders()
        if _wgpu is None or self.device is None or self.queue is None:
            return
        views = self.gbuffer.views()
        albedo_v, normal_v, position_v, depth_v = views
        encoder = self.device.create_command_encoder()
        rpass = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": albedo_v,
                    "clear_value": (0.0, 0.0, 0.0, 0.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
                {
                    "view": normal_v,
                    "clear_value": (0.5, 0.5, 0.0, 0.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
                {
                    "view": position_v,
                    "clear_value": (0.0, 0.0, 0.0, 0.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
            ],
            depth_stencil_attachment={
                "view": depth_v,
                "depth_clear_value": 1.0,
                "depth_load_op": _wgpu.LoadOp.clear,
                "depth_store_op": _wgpu.StoreOp.store,
            },
        )
        # DDD5 material graph fills the geometry pipeline. For now the
        # skeleton relies on the mesh objects exposing a ``.draw(rpass)``
        # convention if they wire themselves in; otherwise we simply
        # clear the G-buffer to establish that the pass is live.
        for m in meshes:
            drawer = getattr(m, "draw", None)
            if callable(drawer):
                try:
                    drawer(rpass, camera=camera)
                except Exception:
                    # Skeleton pass — never crash on a bad mesh; log
                    # would be nice but we stay silent for now.
                    pass
        rpass.end()
        self.queue.submit([encoder.finish()])

    def render_lighting_pass(
        self,
        lights: Sequence[Any],
        camera: Any = None,
    ) -> None:
        """Fullscreen pass reading G-buffer + lights → HDR output.

        Skeleton: encodes a clear-to-mid-grey pass into the HDR texture
        so downstream tonemap sees a valid image even when the
        material graph hasn't landed. DDD5+DDD6 replace the clear with
        the real ACES-lighting shader from ``lighting_pass.wgsl``.
        """
        self._ensure_shaders()
        if _wgpu is None or self.device is None or self.queue is None:
            return
        # Optionally cluster lights via the Rust kernel; result is
        # stashed on the instance for the tests and DDD6 consumers.
        self.last_cluster_table = self.cluster_lights(lights, camera)
        hdr_view = self.hdr_texture.create_view()
        encoder = self.device.create_command_encoder()
        rpass = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": hdr_view,
                    "clear_value": (0.12, 0.12, 0.14, 1.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
            ],
        )
        rpass.end()
        self.queue.submit([encoder.finish()])

    def render_tonemap_pass(self, target_view: Any) -> None:
        """Fullscreen ACES tonemap + gamma pass onto *target_view*.

        Skeleton: clear-to-sky-blue so callers can eyeball whether the
        pipeline ran end-to-end. The real ACES fragment lives in
        ``tonemap.wgsl`` and DDD5 wires it in.
        """
        self._ensure_shaders()
        if _wgpu is None or self.device is None or self.queue is None or target_view is None:
            return
        encoder = self.device.create_command_encoder()
        rpass = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": target_view,
                    "clear_value": (0.14, 0.16, 0.20, 1.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
            ],
        )
        rpass.end()
        self.queue.submit([encoder.finish()])

    # ------------------------------------------------------------------
    # Rust light clustering — thin wrapper around _core.deferred_cluster
    # ------------------------------------------------------------------

    def cluster_lights(
        self,
        lights: Sequence[Any],
        camera: Any,
    ) -> Any:
        """Bin *lights* into a ``16 x 9 x 24`` cluster table via Rust.

        Returns whatever the Rust kernel produced (a list-of-lists,
        typically). If the extension is unavailable, returns an empty
        Python-side placeholder table so callers can iterate safely.
        """
        if self._core is None:
            return _naive_python_cluster(
                lights,
                self.CLUSTER_X,
                self.CLUSTER_Y,
                self.CLUSTER_Z,
            )
        try:
            return self._core.cluster_lights(
                list(lights),
                camera,
                (self.width, self.height),
                (self.CLUSTER_X, self.CLUSTER_Y, self.CLUSTER_Z),
            )
        except Exception:
            return _naive_python_cluster(
                lights,
                self.CLUSTER_X,
                self.CLUSTER_Y,
                self.CLUSTER_Z,
            )

    # ------------------------------------------------------------------
    # Frame entrypoint
    # ------------------------------------------------------------------

    def render(self, scene: Any, target_view: Any) -> None:
        """Orchestrate one frame: geometry -> lighting -> tonemap.

        *scene* is duck-typed. The renderer looks for ``.meshes``,
        ``.lights``, and ``.camera`` attributes; each falls back to an
        empty iterable when absent. This keeps the skeleton usable
        against the CCC1 stub scene, the DDD5 material graph, and any
        DDD6 clustered-shading scene.
        """
        meshes = _get_iter(scene, "meshes")
        lights = _get_iter(scene, "lights")
        camera = getattr(scene, "camera", None)
        self.render_geometry_pass(meshes, camera)
        self.render_lighting_pass(lights, camera)
        self.render_tonemap_pass(target_view)
        self.frames_rendered += 1


# ---------------------------------------------------------------------------
# Fallback Python cluster (used when _core.deferred_cluster is missing)
# ---------------------------------------------------------------------------

def _naive_python_cluster(
    lights: Sequence[Any],
    cx: int,
    cy: int,
    cz: int,
) -> list[list[int]]:
    """Return a ``cx*cy*cz`` list-of-lists, every cluster empty.

    This is a *safety net* — if ``_core.deferred_cluster`` isn't
    available the caller still gets a well-shaped table so downstream
    consumers don't need to guard for ``None``.
    """
    return [[] for _ in range(cx * cy * cz)]


def _get_iter(obj: Any, name: str) -> Iterable[Any]:
    attr = getattr(obj, name, None)
    if attr is None:
        return ()
    try:
        return tuple(attr)
    except TypeError:
        return ()


__all__ = [
    "ALBEDO_FORMAT",
    "DEPTH_FORMAT",
    "DeferredRenderer",
    "GBuffer",
    "GBUFFER_WRITE_WGSL_PATH",
    "HDR_FORMAT",
    "LIGHTING_PASS_WGSL_PATH",
    "NORMAL_ROUGHNESS_FORMAT",
    "POSITION_METALLIC_FORMAT",
    "TONEMAP_WGSL_PATH",
    "load_shader_source",
]
