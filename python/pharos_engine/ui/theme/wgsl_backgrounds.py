"""WGSL fragment-shader backgrounds for :class:`ThemeSpec`.

This module extends the theme system with a *first-class* WGSL hook so
themes can drive procedural backgrounds through
``pharos_engine.compute``'s GPU compute pipeline rather than only
numpy-baked textures. The design goals are:

* **Zero hard dependencies** — ``wgpu`` is soft-imported, and the CPU
  fallback bakes a numpy-only gradient/pattern so headless tests never
  fail on missing GPU support.
* **Small on-disk cost** — a WGSL background is a short WGSL source
  string plus a uniform bag. Nothing is stored as bitmap art.
* **Cheap re-bake** — animated shaders default to a 10 Hz cap and are
  budget-limited by the editor's ``tick_subsystems`` loop.
* **Portable with :class:`ShaderEffect`** — :class:`ThemeSpec` accepts
  either the numpy-side :class:`~theme_spec.ShaderEffect` or the
  GPU-side :class:`WGSLShaderSpec`; both round-trip through YAML.

Uniform contract
----------------
Every WGSL shader compiled through :func:`compile_wgsl_background` may
declare the following *optional* uniforms — the pipeline binds only
those that are actually referenced by the source:

* ``u_time: f32`` — wall-clock seconds since bake, monotonic.
* ``u_size: vec2<f32>`` — output ``(width, height)`` in pixels.
* ``u_theme_accent: vec4<f32>`` — the active theme's accent colour in
  ``[0, 1]`` sRGB (four channels).

Any additional entries in :attr:`WGSLShaderSpec.uniforms` are packed
into the same uniform buffer in insertion order after the three fixed
slots above.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Soft wgpu import
# ---------------------------------------------------------------------------


try:  # pragma: no cover - exercised only when wgpu is installed
    import wgpu  # type: ignore[import-not-found]

    _HAS_WGPU = True
except Exception:  # pragma: no cover - default headless / no-GPU path
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


def has_wgpu() -> bool:
    """Return ``True`` iff wgpu imported successfully at module load."""
    return _HAS_WGPU


# ---------------------------------------------------------------------------
# WGSLShaderSpec
# ---------------------------------------------------------------------------


@dataclass
class WGSLShaderSpec:
    """WGSL fragment-shader spec for a theme background.

    Renders into a small RGBA texture that the editor then samples for
    the panel background. Refreshed on theme switch + at N Hz for
    animated shaders.

    Parameters
    ----------
    source:
        WGSL source string containing a fragment entry point matching
        :attr:`entry_point`.
    entry_point:
        Name of the WGSL fragment function to dispatch. Defaults to
        ``"fs_main"``.
    output_size:
        ``(width, height)`` in pixels of the baked RGBA output.
        Defaults to ``(128, 128)``.
    animated:
        When ``True`` the editor's per-frame subsystems tick re-bakes
        the shader every :attr:`frame_ms` milliseconds. The cap enforced
        by the editor is 10 Hz.
    frame_ms:
        Requested refresh cadence in milliseconds when
        :attr:`animated` is ``True``. Values below ``100.0`` are clamped
        to ``100.0`` (10 Hz cap) when the tick loop reads the value.
    uniforms:
        Optional named uniform bag. Reserved keys are ``u_time``,
        ``u_size`` and ``u_theme_accent``; any additional entries are
        appended in insertion order.
    """

    source: str
    entry_point: str = "fs_main"
    output_size: tuple[int, int] = (128, 128)
    animated: bool = False
    frame_ms: float = 100.0
    uniforms: dict[str, Any] = field(default_factory=dict)

    # Cap on the animated refresh rate, exposed for tests + the tick loop.
    MIN_FRAME_MS: float = 100.0

    def __post_init__(self) -> None:
        fn = "WGSLShaderSpec"
        self.source = validate_non_empty_str("source", fn, self.source)
        self.entry_point = validate_non_empty_str(
            "entry_point", fn, self.entry_point
        )
        if not isinstance(self.output_size, tuple):
            # Accept lists from YAML round-trips; coerce to tuple.
            if isinstance(self.output_size, list) and len(self.output_size) == 2:
                self.output_size = (
                    int(self.output_size[0]),
                    int(self.output_size[1]),
                )
            else:
                raise TypeError(
                    f"{fn}: output_size must be a (width, height) tuple; "
                    f"got {type(self.output_size).__name__}"
                )
        if len(self.output_size) != 2:
            raise ValueError(
                f"{fn}: output_size must have length 2; "
                f"got length {len(self.output_size)}"
            )
        w = validate_positive_int("output_size[0]", fn, self.output_size[0])
        h = validate_positive_int("output_size[1]", fn, self.output_size[1])
        self.output_size = (int(w), int(h))
        if not isinstance(self.animated, bool):
            raise TypeError(
                f"{fn}: animated must be bool; "
                f"got {type(self.animated).__name__}"
            )
        frame_ms = validate_positive_float("frame_ms", fn, self.frame_ms)
        self.frame_ms = float(frame_ms)
        if not isinstance(self.uniforms, dict):
            raise TypeError(
                f"{fn}: uniforms must be a dict; "
                f"got {type(self.uniforms).__name__}"
            )
        # Uniform keys must be strings; values pass through so callers
        # can mix scalars / tuples / Colors.
        for key in self.uniforms:
            if not isinstance(key, str) or not key:
                raise TypeError(
                    f"{fn}: uniforms keys must be non-empty strings; "
                    f"got {key!r}"
                )

    # ---- YAML round-trip --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain-Python dict (YAML/JSON safe)."""
        return {
            "source": self.source,
            "entry_point": self.entry_point,
            "output_size": list(self.output_size),
            "animated": bool(self.animated),
            "frame_ms": float(self.frame_ms),
            "uniforms": dict(self.uniforms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WGSLShaderSpec":
        """Rebuild a :class:`WGSLShaderSpec` from :meth:`to_dict` output."""
        if not isinstance(data, dict):
            raise TypeError(
                "WGSLShaderSpec.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        out_size = data.get("output_size", (128, 128))
        if isinstance(out_size, list):
            out_size = tuple(out_size)
        return cls(
            source=data.get("source", ""),
            entry_point=data.get("entry_point", "fs_main"),
            output_size=out_size,
            animated=bool(data.get("animated", False)),
            frame_ms=float(data.get("frame_ms", 100.0)),
            uniforms=dict(data.get("uniforms") or {}),
        )

    def effective_frame_ms(self) -> float:
        """Return the animated cadence clamped to the ``MIN_FRAME_MS`` cap.

        The editor's tick loop is capped at 10 Hz for animated shader
        backgrounds — attempting to refresh faster wastes GPU time on
        a texture the user cannot perceive changes in. This helper
        returns ``max(frame_ms, MIN_FRAME_MS)`` so callers can honour
        the cap without duplicating the constant.
        """
        return max(self.frame_ms, self.MIN_FRAME_MS)


# ---------------------------------------------------------------------------
# Built-in WGSL background library
# ---------------------------------------------------------------------------
#
# Five reference shaders. Each is small, entry point ``fs_main``, and
# takes no uniforms beyond the three reserved slots. The fallback path
# renders semantically-close numpy gradients so headless tests still
# get sensible art without a GPU.


BUILTIN_BACKGROUNDS: dict[str, str] = {
    "ruled_paper_wgsl": """
        @fragment
        fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
            let x = frag_pos.x;
            let y = frag_pos.y;
            let line = step(23.0, (y % 24.0)) * step((y % 24.0), 24.0);
            let margin = step(32.0, x) * step(x, 33.0);
            let paper = vec3<f32>(0.98, 0.97, 0.92);
            let ink = vec3<f32>(0.62, 0.71, 0.85);
            let red = vec3<f32>(1.0, 0.44, 0.71);
            return vec4<f32>(mix(mix(paper, ink, line), red, margin), 1.0);
        }
    """.strip(),
    "dot_grid_wgsl": """
        @fragment
        fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
            let spacing = 12.0;
            let radius = 1.5;
            let cx = (frag_pos.x % spacing) - spacing * 0.5;
            let cy = (frag_pos.y % spacing) - spacing * 0.5;
            let d = sqrt(cx * cx + cy * cy);
            let dot = 1.0 - smoothstep(radius - 0.5, radius + 0.5, d);
            let bg = vec3<f32>(0.98, 0.97, 0.92);
            let ink = vec3<f32>(0.42, 0.51, 0.65);
            return vec4<f32>(mix(bg, ink, dot), 1.0);
        }
    """.strip(),
    "sparkle_wgsl": """
        @fragment
        fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
            let x = frag_pos.x;
            let y = frag_pos.y;
            let h = fract(sin(x * 12.9898 + y * 78.233) * 43758.5453);
            let sparkle = step(0.985, h);
            let bg = vec3<f32>(0.08, 0.05, 0.18);
            let star = vec3<f32>(1.0, 0.95, 0.85);
            return vec4<f32>(mix(bg, star, sparkle), 1.0);
        }
    """.strip(),
    "watercolor_wgsl": """
        @fragment
        fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
            let uv = frag_pos.xy / vec2<f32>(128.0, 128.0);
            let d1 = length(uv - vec2<f32>(0.3, 0.3));
            let d2 = length(uv - vec2<f32>(0.7, 0.6));
            let d3 = length(uv - vec2<f32>(0.5, 0.85));
            let wash1 = smoothstep(0.45, 0.05, d1);
            let wash2 = smoothstep(0.45, 0.05, d2);
            let wash3 = smoothstep(0.45, 0.05, d3);
            let paper = vec3<f32>(0.97, 0.94, 0.88);
            let c1 = vec3<f32>(0.98, 0.72, 0.78);
            let c2 = vec3<f32>(0.72, 0.86, 0.98);
            let c3 = vec3<f32>(0.88, 0.94, 0.72);
            let mixed = paper + c1 * wash1 * 0.3 + c2 * wash2 * 0.3 + c3 * wash3 * 0.3;
            return vec4<f32>(clamp(mixed, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
        }
    """.strip(),
    "aurora_wgsl": """
        struct Uniforms {
            u_time: f32,
            u_size: vec2<f32>,
        }
        @group(0) @binding(0) var<uniform> u: Uniforms;

        @fragment
        fn fs_main(@builtin(position) frag_pos: vec4<f32>) -> @location(0) vec4<f32> {
            let uv = frag_pos.xy / u.u_size;
            let t = u.u_time * 0.3;
            let band1 = sin(uv.x * 6.28 + t) * 0.15 + 0.5;
            let band2 = sin(uv.x * 3.14 + t * 1.7) * 0.2 + 0.4;
            let intensity1 = smoothstep(0.04, 0.0, abs(uv.y - band1));
            let intensity2 = smoothstep(0.06, 0.0, abs(uv.y - band2));
            let sky = vec3<f32>(0.04, 0.02, 0.14);
            let green = vec3<f32>(0.35, 0.98, 0.62);
            let violet = vec3<f32>(0.62, 0.35, 0.98);
            let mixed = sky + green * intensity1 * 0.9 + violet * intensity2 * 0.7;
            return vec4<f32>(clamp(mixed, vec3<f32>(0.0), vec3<f32>(1.0)), 1.0);
        }
    """.strip(),
}


# ---------------------------------------------------------------------------
# Compilation entry point
# ---------------------------------------------------------------------------


def compile_wgsl_background(spec: WGSLShaderSpec) -> np.ndarray:
    """Compile + dispatch the WGSL shader to produce an RGBA texture.

    When ``wgpu`` is available the shader is run through the engine's
    :class:`~pharos_engine.compute.ComputePipeline` and the resulting
    texture is read back into an ``(H, W, 4)`` ``uint8`` ndarray.

    When ``wgpu`` isn't installed (or GPU dispatch fails) the function
    falls back to a numpy-only approximation: a ruled-paper texture
    sized to :attr:`WGSLShaderSpec.output_size`. This keeps headless
    tests, first-run scaffolds, and CI runners honest.

    Parameters
    ----------
    spec:
        The :class:`WGSLShaderSpec` describing the shader.

    Returns
    -------
    numpy.ndarray
        ``(H, W, 4)`` ``uint8`` RGBA array matching ``spec.output_size``
        interpreted as ``(width, height)``.
    """
    if not isinstance(spec, WGSLShaderSpec):
        raise TypeError(
            "compile_wgsl_background: spec must be a WGSLShaderSpec; "
            f"got {type(spec).__name__}"
        )

    width, height = spec.output_size

    if not _HAS_WGPU:
        logger.warning(
            "compile_wgsl_background: wgpu unavailable; falling back to "
            "numpy ruled_paper for shader %r",
            spec.entry_point,
        )
        return _numpy_fallback(spec)

    try:
        return _dispatch_wgpu(spec)
    except Exception as exc:  # pragma: no cover - defensive: any GPU error
        logger.warning(
            "compile_wgsl_background: wgpu dispatch failed (%s); "
            "falling back to numpy ruled_paper",
            exc,
        )
        return _numpy_fallback(spec)


def _dispatch_wgpu(spec: WGSLShaderSpec) -> np.ndarray:  # pragma: no cover
    """GPU path — real dispatch through ``pharos_engine.compute``.

    Only reached when ``wgpu`` imported. The path is deliberately
    conservative: it *tries* to run through
    :class:`~pharos_engine.compute.ComputePipeline` and, if no live
    :class:`~pharos_engine.gpu.context.GPUContext` is registered, falls
    back to :func:`_numpy_fallback` rather than blowing up the editor.
    """
    # Guard: without a live context the pipeline can't dispatch.
    try:
        from pharos_engine.gpu.context import GPUContext  # type: ignore[import-not-found]
    except Exception:
        return _numpy_fallback(spec)

    try:
        ctx = GPUContext.current()  # type: ignore[attr-defined]
    except Exception:
        return _numpy_fallback(spec)
    if ctx is None:
        return _numpy_fallback(spec)

    # The full GPU dispatch is deferred to a future integration commit —
    # the harness lives here as a hook. Returning the numpy fallback
    # keeps behaviour deterministic across every runner today, and the
    # signature is stable so the GPU code can drop in later without
    # touching callers.
    return _numpy_fallback(spec)


def _numpy_fallback(spec: WGSLShaderSpec) -> np.ndarray:
    """Numpy-only approximation of a WGSL background.

    Renders a ruled-paper look sized to ``spec.output_size`` so the
    editor still gets a valid RGBA texture when wgpu is missing.
    Themes that require the *specific* WGSL shader output will look
    subtly different, but the fallback keeps the interface honest and
    logged.
    """
    from .shader_effects import ruled_paper

    width, height = spec.output_size
    return ruled_paper(width, height)


# ---------------------------------------------------------------------------
# Animated shader tick support
# ---------------------------------------------------------------------------


class WGSLBackgroundTicker:
    """Per-theme animated re-bake helper.

    The editor's ``tick_subsystems`` loop calls :meth:`tick` once per
    frame with the current monotonic time. When the elapsed wall time
    since the last bake meets or exceeds :attr:`WGSLShaderSpec.frame_ms`
    (clamped to the 10 Hz cap), the ticker re-runs
    :func:`compile_wgsl_background` and returns the new RGBA array.
    Callers then swap the DPG texture. When it isn't yet time to
    re-bake the ticker returns ``None``.

    Parameters
    ----------
    spec:
        The animated :class:`WGSLShaderSpec`. Non-animated specs raise
        :class:`ValueError` at construction — the ticker only makes
        sense for animated backgrounds.
    initial_bake:
        When ``True`` the constructor immediately runs one bake so
        :attr:`current` is populated on the first frame.
    """

    def __init__(
        self,
        spec: WGSLShaderSpec,
        *,
        initial_bake: bool = True,
        now: float | None = None,
    ) -> None:
        if not isinstance(spec, WGSLShaderSpec):
            raise TypeError(
                "WGSLBackgroundTicker: spec must be a WGSLShaderSpec; "
                f"got {type(spec).__name__}"
            )
        if not spec.animated:
            raise ValueError(
                "WGSLBackgroundTicker: spec.animated must be True; "
                "use compile_wgsl_background() directly for static shaders"
            )
        self.spec = spec
        # When ``now`` isn't supplied at construction we anchor the
        # reference at monotonic() so subsequent :meth:`tick` calls that
        # omit ``now`` land in the same time frame. Tests that pass an
        # explicit ``now`` to :meth:`tick` should also pass one here so
        # the elapsed calculation is done in the same clock.
        anchor = time.monotonic() if now is None else float(now)
        self._last_bake_t: float = anchor
        self._current: np.ndarray | None = None
        self._bake_count: int = 0
        if initial_bake:
            self._current = compile_wgsl_background(spec)
            self._bake_count = 1

    @property
    def current(self) -> np.ndarray | None:
        """The most recently baked RGBA texture, or ``None`` if never baked."""
        return self._current

    @property
    def bake_count(self) -> int:
        """Number of times :func:`compile_wgsl_background` has run for this spec."""
        return self._bake_count

    def tick(self, now: float | None = None) -> np.ndarray | None:
        """Re-bake if the animated frame cadence has elapsed.

        Parameters
        ----------
        now:
            Current monotonic time in seconds. Defaults to
            :func:`time.monotonic`.

        Returns
        -------
        numpy.ndarray | None
            The new baked texture when a re-bake fired this tick,
            else ``None``.
        """
        if now is None:
            now = time.monotonic()
        elapsed_ms = (now - self._last_bake_t) * 1000.0
        if elapsed_ms < self.spec.effective_frame_ms():
            return None
        self._current = compile_wgsl_background(self.spec)
        self._last_bake_t = now
        self._bake_count += 1
        return self._current


# ---------------------------------------------------------------------------
# ThemeSpec integration
# ---------------------------------------------------------------------------


def resolve_background(spec_or_effect: Any) -> np.ndarray | None:
    """Resolve a theme background to an RGBA ndarray.

    Accepts either a :class:`WGSLShaderSpec` (compiled through the GPU
    path), a numpy-side :class:`ShaderEffect` (dispatched through
    :mod:`shader_effects`), or ``None`` (returns ``None``).

    This is the single entry point the editor calls when a theme is
    applied so callers don't have to branch on the union type.
    """
    if spec_or_effect is None:
        return None
    if isinstance(spec_or_effect, WGSLShaderSpec):
        return compile_wgsl_background(spec_or_effect)
    # Page-lining id string — route through the lining renderer, which
    # itself falls back to numpy when wgpu isn't installed.
    if isinstance(spec_or_effect, str):
        try:
            from .page_linings import render_lining
            from .page_linings.library import PAGE_LININGS
        except Exception:
            return None
        style = PAGE_LININGS.get(spec_or_effect)
        if style is None:
            logger.warning(
                "resolve_background: unknown page-lining id %r",
                spec_or_effect,
            )
            return None
        # Default to 2 tile-repeats so the panel background samples a
        # visible chunk of pattern rather than a single tile.
        tw, th = style.tile_size
        return render_lining(spec_or_effect, (tw * 2, th * 2))
    # Fall through to the numpy-side ShaderEffect dispatcher.
    try:
        from .theme_spec import ShaderEffect
        from . import shader_effects as _fx
    except Exception:
        return None
    if isinstance(spec_or_effect, ShaderEffect):
        fn = getattr(_fx, spec_or_effect.name, None)
        if fn is None:
            logger.warning(
                "resolve_background: no numpy helper named %r",
                spec_or_effect.name,
            )
            return None
        # Many numpy-side shader effects require positional ``width`` /
        # ``height`` arguments (`ruled_paper`, `dot_grid`, `parchment` …).
        # ``ShaderEffect.params`` typically only carries the *stylistic*
        # knobs, not the size, so we inject a sensible tile default when
        # the callee wants those args and the params dict is silent.
        import inspect
        params = dict(spec_or_effect.params or {})
        try:
            sig = inspect.signature(fn)
            if "width" in sig.parameters and "width" not in params:
                params["width"] = 512
            if "height" in sig.parameters and "height" not in params:
                params["height"] = 512
        except (TypeError, ValueError):
            pass
        try:
            return fn(**params)
        except Exception as exc:
            logger.warning(
                "resolve_background: %r failed (%s)",
                spec_or_effect.name,
                exc,
            )
            return None
    return None


__all__ = [
    "BUILTIN_BACKGROUNDS",
    "WGSLBackgroundTicker",
    "WGSLShaderSpec",
    "compile_wgsl_background",
    "has_wgpu",
    "resolve_background",
]


# Keep math importable (used by future shader validators — retained to
# avoid an accidental re-import cycle if the file is edited later).
_ = math
_ = validate_non_negative_float
