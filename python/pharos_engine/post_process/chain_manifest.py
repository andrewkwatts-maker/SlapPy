"""Declarative post-process chain manifest — sprint X5.

A :class:`ChainManifest` describes the *ordered* post-process pipeline —
``bloom -> taa -> tonemap -> dither`` by default — as a YAML-friendly
dataclass so scene files, editor tooling, and offline previews can all
drive the executor's pass graph without hand-coding Python.

Design goals:

* Round-trip via YAML with no lossy fields.
* Support ``depends_on`` topological ordering, matching the round-8
  ``RenderPass.depends_on`` convention already used by
  :mod:`preset_chains`.
* Provide a CPU dispatcher (:func:`apply_manifest`) so tests and
  headless tools can walk the chain without a GPU.
* Stay tolerant of arbitrary future ``kind`` values via
  :func:`register_pass_handler`.

The default four-stage pipeline mirrors the WGSL executor's expected
order:

    1. ``bloom``    (Lottes smooth-knee -> Karis pyramid composite)
    2. ``taa``      (temporal blend + YCoCg variance clip)
    3. ``tonemap``  (ACES / Reinhard + colour grading)
    4. ``dither``   (Bayer 8x8 quantisation-noise smear)

Existing :class:`~.chain.PostProcessChain` builders are unaffected; the
manifest is a *sibling* description that consumers can adopt piecewise.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import yaml


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChainManifestError(ValueError):
    """Raised when a :class:`ChainManifest` is structurally invalid.

    Subclasses :class:`ValueError` so callers that already handle
    ``ValueError`` (config loaders, editor validators) keep working.
    """


# ---------------------------------------------------------------------------
# Known pass kinds
# ---------------------------------------------------------------------------


#: The four kinds the default chain composes.  ``custom`` is the
#: extensibility hook — any pass whose ``kind == "custom"`` must have a
#: handler registered via :func:`register_pass_handler` (keyed by the
#: pass's ``name`` OR by a per-instance ``params["handler"]`` key) before
#: :func:`apply_manifest` will run it.
KNOWN_KINDS: tuple[str, ...] = ("bloom", "taa", "tonemap", "dither", "custom")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PassSpec:
    """A single declarative post-process pass entry.

    Parameters
    ----------
    name
        Human-readable identifier.  Must be unique within a manifest.
    kind
        One of :data:`KNOWN_KINDS`.  ``custom`` requires a matching
        handler registration.
    enabled
        Disabled entries are skipped by :func:`apply_manifest` but stay
        in :meth:`ChainManifest.topological_order` so downstream tools
        can render them greyed-out.
    params
        Arbitrary keyword payload forwarded to the pass handler.  For
        the built-in kinds the field names mirror the CPU helpers
        (e.g. ``bloom`` accepts ``strength``, ``threshold``, ``knee``,
        ``mip_count``).
    depends_on
        Names of other passes that must run before this one.  An empty
        list preserves insertion-order semantics.
    """

    name: str
    kind: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation for YAML emission."""
        return {
            "name": str(self.name),
            "kind": str(self.kind),
            "enabled": bool(self.enabled),
            "params": copy.deepcopy(dict(self.params)),
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PassSpec":
        """Build a :class:`PassSpec` from a plain dict.

        Missing optional fields fall back to their dataclass defaults so
        legacy manifests without ``enabled`` / ``depends_on`` still load.
        """
        if not isinstance(raw, dict):
            raise ChainManifestError(
                f"PassSpec.from_dict expects a mapping; got {type(raw).__name__}"
            )
        if "name" not in raw or "kind" not in raw:
            raise ChainManifestError(
                "PassSpec.from_dict: 'name' and 'kind' are required fields"
            )
        return cls(
            name=str(raw["name"]),
            kind=str(raw["kind"]),
            enabled=bool(raw.get("enabled", True)),
            params=dict(raw.get("params") or {}),
            depends_on=list(raw.get("depends_on") or []),
        )


@dataclass
class ChainManifest:
    """Ordered collection of :class:`PassSpec` entries with topo validation.

    The ``passes`` list is the *canonical* order (insertion order); the
    :meth:`topological_order` method returns a re-ordered copy that
    respects ``depends_on`` while preserving insertion order as a
    tie-breaker.  This mirrors the behaviour of ``iso_strategy_chain`` in
    :mod:`preset_chains`.
    """

    passes: list[PassSpec] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`ChainManifestError` on structural problems.

        Checks:
            * Duplicate ``name`` values.
            * ``depends_on`` references to names not in the manifest.
            * Cycles in the dependency graph.
            * Unknown ``kind`` values (only ``KNOWN_KINDS`` are accepted).
        """
        # Duplicate names.
        seen: set[str] = set()
        for p in self.passes:
            if p.name in seen:
                raise ChainManifestError(
                    f"duplicate pass name in manifest: {p.name!r}"
                )
            seen.add(p.name)

        # Unknown kinds.
        for p in self.passes:
            if p.kind not in KNOWN_KINDS:
                raise ChainManifestError(
                    f"unknown pass kind {p.kind!r} on pass {p.name!r}; "
                    f"expected one of {KNOWN_KINDS!r}"
                )

        # Unknown deps + self-loops.
        names = {p.name for p in self.passes}
        for p in self.passes:
            for dep in p.depends_on:
                if dep == p.name:
                    raise ChainManifestError(
                        f"pass {p.name!r} depends on itself"
                    )
                if dep not in names:
                    raise ChainManifestError(
                        f"pass {p.name!r} depends on unknown pass {dep!r}"
                    )

        # Cycle detection (Kahn's algorithm — if we can't drain the graph,
        # there's a cycle).
        indeg: dict[str, int] = {p.name: 0 for p in self.passes}
        adj: dict[str, list[str]] = {p.name: [] for p in self.passes}
        for p in self.passes:
            for dep in p.depends_on:
                # dep -> p.name edge.
                adj[dep].append(p.name)
                indeg[p.name] += 1

        ready = [name for name, d in indeg.items() if d == 0]
        drained = 0
        while ready:
            n = ready.pop()
            drained += 1
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)

        if drained != len(self.passes):
            offenders = [name for name, d in indeg.items() if d > 0]
            raise ChainManifestError(
                f"dependency cycle detected in manifest; passes involved: "
                f"{sorted(offenders)!r}"
            )

    # ------------------------------------------------------------------
    # Topological order
    # ------------------------------------------------------------------

    def topological_order(self) -> list[PassSpec]:
        """Return a topo-sorted copy of :attr:`passes`.

        Insertion order is preserved as the tie-breaker so a manifest
        with no ``depends_on`` edges yields the same list as
        :attr:`passes` — the historical behaviour of
        :attr:`PostProcessChain.passes`.
        """
        self.validate()

        indeg: dict[str, int] = {p.name: 0 for p in self.passes}
        adj: dict[str, list[str]] = {p.name: [] for p in self.passes}
        for p in self.passes:
            for dep in p.depends_on:
                adj[dep].append(p.name)
                indeg[p.name] += 1

        # Priority queue by insertion index — preserves stable order.
        index: dict[str, int] = {p.name: i for i, p in enumerate(self.passes)}
        by_name: dict[str, PassSpec] = {p.name: p for p in self.passes}

        ready = sorted(
            [name for name, d in indeg.items() if d == 0],
            key=lambda n: index[n],
        )
        out: list[PassSpec] = []
        while ready:
            n = ready.pop(0)
            out.append(by_name[n])
            new_ready: list[str] = []
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    new_ready.append(m)
            if new_ready:
                # Merge preserving overall insertion order.
                merged = ready + new_ready
                merged.sort(key=lambda x: index[x])
                ready = merged
        return out

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialise the manifest to YAML text.

        The output is a mapping with a single ``passes`` key so future
        top-level metadata (versioning, comments) has a place to live
        without breaking backwards compatibility.
        """
        payload = {"passes": [p.to_dict() for p in self.passes]}
        return yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    @classmethod
    def from_yaml(cls, text: str) -> "ChainManifest":
        """Parse a YAML string into a :class:`ChainManifest`.

        Accepts either the top-level ``{passes: [...]}`` map or a bare
        list of pass entries so hand-written manifests can skip the
        wrapper.  Runs :meth:`validate` before returning so the caller
        never receives a structurally broken manifest.
        """
        raw = yaml.safe_load(text)
        if raw is None:
            return cls(passes=[])
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = raw.get("passes") or []
        else:
            raise ChainManifestError(
                f"ChainManifest.from_yaml: expected mapping or list at top level; "
                f"got {type(raw).__name__}"
            )
        if not isinstance(entries, list):
            raise ChainManifestError(
                f"ChainManifest.from_yaml: 'passes' must be a list; "
                f"got {type(entries).__name__}"
            )
        manifest = cls(passes=[PassSpec.from_dict(e) for e in entries])
        manifest.validate()
        return manifest


# ---------------------------------------------------------------------------
# Default chain factory
# ---------------------------------------------------------------------------


def _default_chain() -> ChainManifest:
    """Return the standard bloom -> taa -> tonemap -> dither manifest.

    Called at module import time to populate :data:`DEFAULT_CHAIN`; also
    re-exported so tests can build a fresh copy without mutating the
    module-level singleton.
    """
    return ChainManifest(
        passes=[
            PassSpec(
                name="bloom",
                kind="bloom",
                params={
                    "strength": 1.0,
                    "threshold": 1.0,
                    "knee": 0.2,
                    "mip_count": 6,
                },
            ),
            PassSpec(
                name="taa",
                kind="taa",
                params={"alpha": 0.1},
                depends_on=["bloom"],
            ),
            PassSpec(
                name="tonemap",
                kind="tonemap",
                params={"exposure_ev": 0.0, "mode": 0},
                depends_on=["taa"],
            ),
            PassSpec(
                name="dither",
                kind="dither",
                params={"strength": 1.0 / 255.0},
                depends_on=["tonemap"],
            ),
        ]
    )


DEFAULT_CHAIN: ChainManifest = _default_chain()


# ---------------------------------------------------------------------------
# Handler registry + built-in kinds
# ---------------------------------------------------------------------------


PassHandler = Callable[[np.ndarray, "PassSpec", dict[str, Any]], np.ndarray]


_CUSTOM_HANDLERS: dict[str, PassHandler] = {}


def register_pass_handler(kind: str, handler: PassHandler) -> None:
    """Register a handler for a custom pass ``kind`` or name.

    The dispatcher looks up handlers in three places, in order:

    1. Built-in kinds (``bloom``, ``taa``, ``tonemap``, ``dither``).
    2. ``params["handler"]`` — allows the same ``custom`` kind to route
       to different handlers by naming them in the pass params.
    3. The pass's ``name`` — the fallback used by the tests.

    Passing an already-registered ``kind`` overwrites the previous entry.
    """
    if not isinstance(kind, str) or not kind:
        raise ChainManifestError(
            f"register_pass_handler: kind must be a non-empty string; "
            f"got {kind!r}"
        )
    if not callable(handler):
        raise ChainManifestError(
            f"register_pass_handler: handler for {kind!r} must be callable"
        )
    _CUSTOM_HANDLERS[kind] = handler


def _clear_custom_handlers() -> None:
    """Test-only: wipe the custom handler registry.

    Not part of the public API — tests use this to keep runs isolated.
    """
    _CUSTOM_HANDLERS.clear()


def _handle_bloom(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any]
) -> np.ndarray:
    """Bloom dispatch — routes to :func:`~.bloom.apply_bloom`."""
    from .bloom import apply_bloom

    p = spec.params
    return apply_bloom(
        image,
        strength=float(p.get("strength", 1.0)),
        threshold=float(p.get("threshold", 1.0)),
        knee=float(p.get("knee", 0.2)),
        mip_count=int(p.get("mip_count", 6)),
    )


def _handle_taa(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any]
) -> np.ndarray:
    """TAA dispatch — resolves against a caller-provided history.

    The context dict may carry ``history`` (previous frame) and
    ``motion_uv`` (per-pixel NDC motion).  When either is missing, the
    current frame stands in as its own history — that yields the
    identity blend the tests rely on for the pipeline-equivalence check.
    """
    from .taa import TAAPass

    p = spec.params
    taa = TAAPass(
        alpha=float(p.get("alpha", 0.1)),
        variance_clip_gamma=float(p.get("variance_clip_gamma", 1.0)),
        motion_weight=float(p.get("motion_weight", 1.0)),
        karis_weight=bool(p.get("karis_weight", False)),
        tight_variance_clip=bool(p.get("tight_variance_clip", True)),
        sharpening=float(p.get("sharpening", 0.0)),
        reject_on_depth_disocclusion=bool(
            p.get("reject_on_depth_disocclusion", False)
        ),
        depth_disocclusion_threshold=float(
            p.get("depth_disocclusion_threshold", 0.1)
        ),
        reject_on_normal_disocclusion=bool(
            p.get("reject_on_normal_disocclusion", False)
        ),
        normal_disocclusion_threshold=float(
            p.get("normal_disocclusion_threshold", 0.9)
        ),
    )
    history = ctx.get("history", image)
    motion_uv = ctx.get("motion_uv")
    return taa.resolve_numpy(image, history, motion_uv=motion_uv)


def _handle_tonemap(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any]
) -> np.ndarray:
    """Tonemap dispatch — CPU-only ACES / Reinhard approximation.

    We keep this dispatcher self-contained (rather than reaching into
    the WGSL executor) so :func:`apply_manifest` works without a GPU.
    Mirrors the ``mode`` semantics of ``tonemap.wgsl``: ``0`` = ACES,
    ``1`` = Reinhard.
    """
    p = spec.params
    exposure = 2.0 ** float(p.get("exposure_ev", 0.0))
    mode = int(p.get("mode", 0))
    out = np.asarray(image, dtype=np.float32) * exposure
    if mode == 1:
        out = out / (1.0 + out)
    else:
        # ACES fit — Krzysztof Narkowicz 2015.
        a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
        out = np.clip((out * (a * out + b)) / (out * (c * out + d) + e), 0.0, 1.0)
    gamma = float(p.get("gamma", 1.0))
    if gamma not in (0.0, 1.0):
        out = np.power(np.clip(out, 0.0, None), 1.0 / gamma)
    return out.astype(np.float32)


def _handle_dither(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any]
) -> np.ndarray:
    """8x8 Bayer dither dispatch — pure-numpy CPU reference.

    The offset table is the classic ordered dither matrix normalised to
    ``[-0.5, 0.5]`` and then scaled by ``strength``.  Default strength
    is ``1/255`` — one LDR quantisation step — which is imperceptibly
    small but breaks up banding on smooth gradients.
    """
    p = spec.params
    strength = float(p.get("strength", 1.0 / 255.0))
    if strength == 0.0:
        return np.asarray(image, dtype=np.float32).copy()
    bayer8 = np.array(
        [
            [0, 32, 8, 40, 2, 34, 10, 42],
            [48, 16, 56, 24, 50, 18, 58, 26],
            [12, 44, 4, 36, 14, 46, 6, 38],
            [60, 28, 52, 20, 62, 30, 54, 22],
            [3, 35, 11, 43, 1, 33, 9, 41],
            [51, 19, 59, 27, 49, 17, 57, 25],
            [15, 47, 7, 39, 13, 45, 5, 37],
            [63, 31, 55, 23, 61, 29, 53, 21],
        ],
        dtype=np.float32,
    )
    normalised = bayer8 / 64.0 - 0.5  # in [-0.5, 0.5]
    arr = np.asarray(image, dtype=np.float32)
    h, w = arr.shape[:2]
    # Tile the pattern to cover the image.
    tiles_y = (h + 7) // 8
    tiles_x = (w + 7) // 8
    tiled = np.tile(normalised, (tiles_y, tiles_x))[:h, :w]
    if arr.ndim == 3:
        tiled = tiled[..., None]
    return (arr + tiled * strength).astype(np.float32)


_BUILTIN_HANDLERS: dict[str, PassHandler] = {
    "bloom": _handle_bloom,
    "taa": _handle_taa,
    "tonemap": _handle_tonemap,
    "dither": _handle_dither,
}


def _resolve_handler(spec: PassSpec) -> Optional[PassHandler]:
    """Look up the handler for ``spec`` in the built-in and custom tables.

    Custom passes ("kind == custom") consult
    ``spec.params["handler"]`` first (so one custom kind can multiplex
    into many handlers) and fall back to ``spec.name``.  For any other
    kind we honour a custom registration keyed by that kind (letting
    callers override the built-in behaviour, useful for tests) before
    falling back to the built-in handler.
    """
    if spec.kind == "custom":
        key = spec.params.get("handler") or spec.name
        return _CUSTOM_HANDLERS.get(str(key))
    if spec.kind in _CUSTOM_HANDLERS:
        return _CUSTOM_HANDLERS[spec.kind]
    return _BUILTIN_HANDLERS.get(spec.kind)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def apply_manifest(
    image: np.ndarray,
    manifest: ChainManifest,
    ctx: Optional[dict[str, Any]] = None,
) -> np.ndarray:
    """Run the manifest against a CPU image.

    Walks :meth:`ChainManifest.topological_order` and dispatches each
    enabled pass to its handler.  ``ctx`` is a mutable dict shared by
    every handler — TAA reads ``history`` / ``motion_uv`` from it, and
    custom handlers may stash intermediate state there without
    polluting the manifest.

    Parameters
    ----------
    image
        ``(H, W, 3)`` float image.  Passed through unchanged when the
        manifest is empty or every pass is disabled.
    manifest
        A validated :class:`ChainManifest`.  Validation is re-run here
        so callers can hand in freshly-mutated manifests.
    ctx
        Optional per-frame side-channel dict.  Handlers may read *and*
        write; :func:`apply_manifest` never inspects the contents.

    Returns
    -------
    np.ndarray
        The final image after all enabled passes have run.  Always a
        distinct ``float32`` array (never an alias of ``image``).
    """
    if ctx is None:
        ctx = {}
    working = np.asarray(image, dtype=np.float32).copy()
    order = manifest.topological_order()
    for spec in order:
        if not spec.enabled:
            continue
        handler = _resolve_handler(spec)
        if handler is None:
            raise ChainManifestError(
                f"apply_manifest: no handler registered for pass "
                f"{spec.name!r} (kind={spec.kind!r})"
            )
        result = handler(working, spec, ctx)
        working = np.asarray(result, dtype=np.float32)
    return working


__all__ = [
    "ChainManifest",
    "ChainManifestError",
    "DEFAULT_CHAIN",
    "KNOWN_KINDS",
    "PassHandler",
    "PassSpec",
    "apply_manifest",
    "register_pass_handler",
]
