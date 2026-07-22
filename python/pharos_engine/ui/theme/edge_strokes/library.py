"""Edge-stroke shader library — hand-drawn panel border styles.

Each entry in :data:`EDGE_STROKES` is an :class:`EdgeStrokeStyle`
describing how to render the hand-drawn border that wraps a panel's
perimeter. The style carries three things:

* A **canonical thickness** in pixels — how thick the stroke reads at
  1x DPI. Themes may override at render time, but the canonical value
  is what the style was authored for.
* A **canonical alpha** in ``[0, 1]`` — the *average* opacity of the
  stroke. Highlighter reads at ~0.3; sharpie at ~1.0.
* A short **WGSL fragment shader** (``<= 1000 bytes``) that fills a
  border strip. The shader treats its input as a 1-D pattern that
  repeats along the perimeter — the renderer stamps it onto four
  strips (top / right / bottom / left) to form the full border.

The library ships **15 styles** spanning dry media (pencil, chalk,
charcoal, crayon, colored pencil), wet media (ballpoint pen, gel pen,
fountain pen, quill, marker, sharpie, highlighter, watercolor brush,
ink wash), and mixed (chalk-with-smudge). Each style has both a WGSL
source and a numpy fallback so headless tests / no-GPU CI still
exercise the full surface.

Uniform contract
----------------
Every shader is authored against the same tiny uniform slot:

* ``u_size: vec2<f32>`` — strip width/height in pixels.
* ``u_theme_color_1: vec4<f32>`` — ink / stroke colour.
* ``u_theme_color_2: vec4<f32>`` — highlight / paper colour used for
  interior variation.

The renderer packs both colours from the active theme's semantic
tokens (typically ``primary`` / ``surface``) before dispatch. Themes
that supply neither fall back to the theme border colour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_float,
    validate_unit_float,
)


# ---------------------------------------------------------------------------
# EdgeStrokeStyle dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeStrokeStyle:
    """One entry in :data:`EDGE_STROKES`.

    Parameters
    ----------
    style_id:
        The registry key (matches the :data:`EDGE_STROKES` dict key).
    thickness_px:
        Canonical stroke thickness at 1x DPI in pixels. Must be > 0.
    alpha:
        Canonical average opacity in ``[0, 1]``. Highlighter ~ 0.3;
        pencil ~ 0.85; sharpie ~ 1.0.
    wgsl_source:
        The WGSL fragment-shader source. Entry point is ``fs_main``.
        Must be non-empty and ``<= 1000`` bytes.
    entry_point:
        Fragment entry point name. Defaults to ``"fs_main"``.
    description:
        One-sentence human-readable description used by
        :func:`list_strokes` and the docs table.
    tags:
        Optional string tags. Useful for filtering ("dry", "wet",
        "translucent", "textured", "smooth").
    """

    style_id: str
    thickness_px: float
    alpha: float
    wgsl_source: str
    entry_point: str = "fs_main"
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    # Hard limit per constraint: each WGSL source must be small.
    MAX_WGSL_BYTES: int = 1000

    def __post_init__(self) -> None:
        fn = "EdgeStrokeStyle"
        object.__setattr__(
            self, "style_id", validate_non_empty_str("style_id", fn, self.style_id)
        )
        object.__setattr__(
            self,
            "thickness_px",
            float(validate_positive_float("thickness_px", fn, self.thickness_px)),
        )
        object.__setattr__(
            self, "alpha", float(validate_unit_float("alpha", fn, self.alpha))
        )
        object.__setattr__(
            self,
            "wgsl_source",
            validate_non_empty_str("wgsl_source", fn, self.wgsl_source),
        )
        object.__setattr__(
            self,
            "entry_point",
            validate_non_empty_str("entry_point", fn, self.entry_point),
        )
        if not isinstance(self.description, str):
            raise TypeError(
                f"{fn}: description must be str; "
                f"got {type(self.description).__name__}"
            )
        if not isinstance(self.tags, tuple):
            if isinstance(self.tags, list):
                object.__setattr__(self, "tags", tuple(self.tags))
            else:
                raise TypeError(
                    f"{fn}: tags must be a tuple; got {type(self.tags).__name__}"
                )
        for tag in self.tags:
            if not isinstance(tag, str) or not tag:
                raise TypeError(f"{fn}: tags entries must be non-empty str")
        if len(self.wgsl_source.encode("utf-8")) > self.MAX_WGSL_BYTES:
            raise ValueError(
                f"{fn}: wgsl_source for {self.style_id!r} exceeds "
                f"{self.MAX_WGSL_BYTES}-byte limit "
                f"({len(self.wgsl_source.encode('utf-8'))} bytes)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a YAML/JSON-safe dict."""
        return {
            "style_id": self.style_id,
            "thickness_px": self.thickness_px,
            "alpha": self.alpha,
            "wgsl_source": self.wgsl_source,
            "entry_point": self.entry_point,
            "description": self.description,
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# WGSL source strings
# ---------------------------------------------------------------------------
#
# Every source declares its own uniform block so it stays standalone
# and portable. Uniforms are:
#
#   struct Uniforms {
#     u_size: vec2<f32>,
#     u_theme_color_1: vec4<f32>,   // ink / stroke colour
#     u_theme_color_2: vec4<f32>,   // highlight / paper colour
#   }
#
# The renderer supplies the two colours from the active theme.


_UNIFORM_BLOCK = """struct Uniforms {
  u_size: vec2<f32>,
  u_theme_color_1: vec4<f32>,
  u_theme_color_2: vec4<f32>,
}
@group(0) @binding(0) var<uniform> u: Uniforms;
"""


def _wrap(body: str) -> str:
    """Prepend the shared uniform block to a shader body."""
    return (_UNIFORM_BLOCK + body).strip()


# --- Dry media --------------------------------------------------------------

_BALLPOINT_PEN = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let jitter = fract(sin(t * 87.13) * 4571.31) * 0.08;
  let a = clamp(0.9 + jitter, 0.0, 1.0);
  return vec4<f32>(u.u_theme_color_1.rgb, a);
}
"""
)

_GEL_PEN = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let wobble = sin(t * 12.0) * 0.05;
  let a = 0.94 + wobble;
  return vec4<f32>(u.u_theme_color_1.rgb, clamp(a, 0.0, 1.0));
}
"""
)

_PENCIL_2B = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let n = fract(sin(t * 100.0) * 43758.5453);
  let s = 0.7 + n * 0.3;
  let c = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, n * 0.3);
  return vec4<f32>(c, s);
}
"""
)

_PENCIL_HB = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let n = fract(sin(t * 73.31) * 12345.678);
  let s = 0.82 + n * 0.15;
  return vec4<f32>(u.u_theme_color_1.rgb, s);
}
"""
)

_CHALK = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let g = fract(sin(t * 51.7 + 3.1) * 91731.0);
  let crumb = step(0.18, g);
  let a = 0.55 * crumb + 0.15;
  let c = mix(u.u_theme_color_2.rgb, u.u_theme_color_1.rgb, crumb);
  return vec4<f32>(c, a);
}
"""
)

_CHARCOAL = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let n1 = fract(sin(t * 41.7) * 21713.0);
  let n2 = fract(sin(t * 11.3 + 1.0) * 6577.0);
  let smudge = 0.4 + 0.5 * n1 * n2;
  let dark = u.u_theme_color_1.rgb * 0.55;
  return vec4<f32>(dark, smudge);
}
"""
)

_CRAYON = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let waxy = fract(sin(t * 27.0) * 511.0);
  let a = 0.65 + 0.25 * waxy;
  let c = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, waxy * 0.2);
  return vec4<f32>(c, a);
}
"""
)

_COLORED_PENCIL = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let n = fract(sin(t * 63.9 + 0.7) * 7317.0);
  let layer = 0.75 + n * 0.2;
  let c = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, 0.15 + n * 0.2);
  return vec4<f32>(c, layer);
}
"""
)

# --- Wet media --------------------------------------------------------------

_MARKER_THICK = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  return vec4<f32>(u.u_theme_color_1.rgb, 0.98);
}
"""
)

_HIGHLIGHTER = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let bleed = 0.05 * sin(t * 7.0);
  return vec4<f32>(u.u_theme_color_1.rgb, 0.32 + bleed);
}
"""
)

_BRUSH_WATERCOLOR = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let wash = fract(sin(t * 8.7) * 13.7);
  let a = 0.5 + 0.35 * wash;
  let c = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, wash * 0.5);
  return vec4<f32>(c, a);
}
"""
)

_INK_WASH = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let flow = 0.35 + 0.55 * sin(t * 3.14159);
  let dark = u.u_theme_color_1.rgb * 0.35;
  return vec4<f32>(dark, flow);
}
"""
)

_SHARPIE = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  return vec4<f32>(u.u_theme_color_1.rgb, 1.0);
}
"""
)

_FOUNTAIN_PEN = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let width = 0.6 + 0.35 * (sin(t * 4.0) * 0.5 + 0.5);
  return vec4<f32>(u.u_theme_color_1.rgb, width);
}
"""
)

_QUILL = _wrap(
    """
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let taper = 0.4 + 0.55 * abs(sin(t * 2.7));
  let ink = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, 0.1);
  return vec4<f32>(ink, taper);
}
"""
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


EDGE_STROKES: dict[str, EdgeStrokeStyle] = {
    "ballpoint_pen": EdgeStrokeStyle(
        style_id="ballpoint_pen",
        thickness_px=1.5,
        alpha=0.92,
        wgsl_source=_BALLPOINT_PEN,
        description="Smooth ballpoint ink with slight pressure jitter.",
        tags=("wet", "smooth"),
    ),
    "gel_pen": EdgeStrokeStyle(
        style_id="gel_pen",
        thickness_px=2.0,
        alpha=0.95,
        wgsl_source=_GEL_PEN,
        description="Thicker gel-pen line with subtle wobble.",
        tags=("wet", "smooth"),
    ),
    "pencil_2b": EdgeStrokeStyle(
        style_id="pencil_2b",
        thickness_px=2.0,
        alpha=0.85,
        wgsl_source=_PENCIL_2B,
        description="Soft graphite 2B with noisy variation.",
        tags=("dry", "textured"),
    ),
    "pencil_hb": EdgeStrokeStyle(
        style_id="pencil_hb",
        thickness_px=1.5,
        alpha=0.9,
        wgsl_source=_PENCIL_HB,
        description="Crisp HB graphite with fine grain.",
        tags=("dry", "textured"),
    ),
    "marker_thick": EdgeStrokeStyle(
        style_id="marker_thick",
        thickness_px=4.0,
        alpha=0.98,
        wgsl_source=_MARKER_THICK,
        description="Solid thick permanent-marker stroke.",
        tags=("wet", "smooth"),
    ),
    "highlighter": EdgeStrokeStyle(
        style_id="highlighter",
        thickness_px=8.0,
        alpha=0.32,
        wgsl_source=_HIGHLIGHTER,
        description="Wide translucent highlighter band.",
        tags=("wet", "translucent"),
    ),
    "brush_watercolor": EdgeStrokeStyle(
        style_id="brush_watercolor",
        thickness_px=6.0,
        alpha=0.7,
        wgsl_source=_BRUSH_WATERCOLOR,
        description="Wet watercolor brush with edge bleed.",
        tags=("wet", "translucent", "textured"),
    ),
    "chalk": EdgeStrokeStyle(
        style_id="chalk",
        thickness_px=3.0,
        alpha=0.55,
        wgsl_source=_CHALK,
        description="Crumbly chalk texture with gaps.",
        tags=("dry", "textured"),
    ),
    "charcoal": EdgeStrokeStyle(
        style_id="charcoal",
        thickness_px=3.5,
        alpha=0.75,
        wgsl_source=_CHARCOAL,
        description="Dark smudged charcoal.",
        tags=("dry", "textured"),
    ),
    "crayon": EdgeStrokeStyle(
        style_id="crayon",
        thickness_px=3.0,
        alpha=0.8,
        wgsl_source=_CRAYON,
        description="Waxy crayon with paper-tooth variation.",
        tags=("dry", "textured"),
    ),
    "ink_wash": EdgeStrokeStyle(
        style_id="ink_wash",
        thickness_px=5.0,
        alpha=0.6,
        wgsl_source=_INK_WASH,
        description="Sumi-e style ink wash with flow variation.",
        tags=("wet", "translucent"),
    ),
    "sharpie": EdgeStrokeStyle(
        style_id="sharpie",
        thickness_px=3.0,
        alpha=1.0,
        wgsl_source=_SHARPIE,
        description="Solid felt-tip permanent marker.",
        tags=("wet", "smooth"),
    ),
    "colored_pencil": EdgeStrokeStyle(
        style_id="colored_pencil",
        thickness_px=2.0,
        alpha=0.85,
        wgsl_source=_COLORED_PENCIL,
        description="Layered colored pencil with paper grain.",
        tags=("dry", "textured"),
    ),
    "fountain_pen": EdgeStrokeStyle(
        style_id="fountain_pen",
        thickness_px=2.5,
        alpha=0.9,
        wgsl_source=_FOUNTAIN_PEN,
        description="Thick-thin fountain-pen calligraphic stroke.",
        tags=("wet", "smooth"),
    ),
    "quill": EdgeStrokeStyle(
        style_id="quill",
        thickness_px=2.5,
        alpha=0.78,
        wgsl_source=_QUILL,
        description="Variable-width quill with tapered ends.",
        tags=("wet", "textured"),
    ),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_stroke(style_id: str) -> EdgeStrokeStyle:
    """Return the :class:`EdgeStrokeStyle` for *style_id*.

    Raises :class:`KeyError` with a helpful message when the style is
    not registered.
    """
    validate_non_empty_str("style_id", "get_stroke", style_id)
    try:
        return EDGE_STROKES[style_id]
    except KeyError as exc:
        available = ", ".join(sorted(EDGE_STROKES)) or "(none)"
        raise KeyError(
            f"get_stroke: no edge stroke {style_id!r}; available: {available}"
        ) from exc


def list_strokes() -> list[str]:
    """Return a sorted list of registered edge-stroke style IDs."""
    return sorted(EDGE_STROKES)


__all__ = [
    "EdgeStrokeStyle",
    "EDGE_STROKES",
    "get_stroke",
    "list_strokes",
]
