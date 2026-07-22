"""Library of WGSL page-lining shader styles.

Each entry describes a **tileable paper-stock pattern** intended to be
baked into an RGBA texture that becomes the panel background of a
:class:`~pharos_engine.ui.theme.theme_spec.ThemeSpec`.

Every :class:`LiningStyle` bundles:

* ``source`` — a WGSL fragment shader (≤ 1000 bytes) with entry
  ``fs_main`` that samples ``@builtin(position)`` and paints a paper
  colour + line colour blend. Two vec4 uniforms are conventionally
  available (``u_theme_color_1`` = paper, ``u_theme_color_2`` = ink).
* ``tile_size`` — the vertical + horizontal period of the pattern in
  pixels. Adjacent tiles at this size wrap seamlessly.
* ``default_paper``, ``default_ink`` — RGB anchor colours used by the
  numpy fallback if the caller supplies no explicit colours.
* ``description`` — one-line human-readable summary; used by the docs
  generator and by the editor's pattern picker preview.

The design goal is that :func:`render_lining` produces a texture whose
last row matches its first row (± 1 pixel) and whose last column matches
its first column at ``tile_size`` periods. See
``test_page_lining_shaders.py`` for the enforced continuity contract.

Bounded surfaces
----------------
The library is a plain ``dict[str, LiningStyle]``; helpers
:func:`get_lining` + :func:`list_linings` are the recommended access
pattern so callers get a KeyError raised with a clear failure message
rather than a bare ``dict[...]`` miss.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


@dataclass(frozen=True)
class LiningStyle:
    """A single paper-lining style descriptor.

    Parameters
    ----------
    style_id:
        Stable string id (matches the dict key in :data:`PAGE_LININGS`).
    source:
        WGSL fragment source string; must contain a ``fs_main`` entry
        and stay ≤ 1000 bytes so it stays cheap to bake.
    tile_size:
        ``(width, height)`` period in pixels at which the shader tiles.
    default_paper:
        RGB anchor for the paper colour (used by numpy fallback if the
        caller passes ``paper_color=None``).
    default_ink:
        RGB anchor for the line colour (used by numpy fallback if the
        caller passes ``line_color=None``).
    description:
        One-line human summary of the visual.
    """

    style_id: str
    source: str
    tile_size: tuple[int, int]
    default_paper: tuple[int, int, int]
    default_ink: tuple[int, int, int]
    description: str


# ---------------------------------------------------------------------------
# AAA-quality preset — controls how much post-process paper realism the
# numpy fallbacks bake into each rendered lining texture.
# ---------------------------------------------------------------------------


class _QualityTier(str, Enum):
    """Marker for the three AAA quality tiers."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class AAAShaderQualityPreset:
    """Bundle of post-process knobs applied per-preset by the renderer.

    Three factory presets ship as module-level constants (also exposed as
    ``AAAShaderQualityPreset.LOW`` / ``.MEDIUM`` / ``.HIGH`` after class
    definition):

    * ``LOW`` — flat, deterministic. Matches pre-BBB5 behaviour so
      legacy screenshots keep byte-for-byte parity.
    * ``MEDIUM`` — grain + line anti-aliasing. Cheap uplift.
    * ``HIGH`` — grain + AA + subtle line jitter + warm sun-lit tint.
      New default for the editor's pattern picker.

    Fields
    ------
    tier:
        Human-readable tier name; used by docs generator + tests.
    grain_intensity:
        Perlin-ish luma noise amplitude in ``[0, 1]``. ``0.015`` is the
        AAA sweet spot — ±3-4 luma variance, breaks flatness without
        looking noisy.
    line_aa_px:
        Anti-alias half-width in pixels for every ruled / grid line.
        ``0.0`` = crisp 1-pixel line. ``1.5`` = soft AAA line.
    jitter_px:
        Row-wobble amplitude for ruled lines in pixels ``[0, 4]``. Mimics
        real ruled-paper printing tolerance.
    warm_tint:
        Warm sun-lit gradient strength in ``[0, 1]``. Adds a subtle
        top-left warm / bottom-right cool bias to the paper colour.
    dot_alpha_variance:
        Per-dot alpha jitter for dot-grid patterns in ``[0, 1]``. ``0.12``
        gives ±30 of 255-range variance for organic-feeling dots.
    ink_bleed:
        Gaussian-ish ink spread strength for graph-paper style patterns
        in ``[0, 1]``. Simulates slight blue-ink bleed into paper fibres.
    """

    tier: str
    grain_intensity: float
    line_aa_px: float
    jitter_px: float
    warm_tint: float
    dot_alpha_variance: float
    ink_bleed: float


# Populate the three factory presets after the dataclass is defined and
# expose them both as module constants and as class-level attributes.
_LOW_PRESET = AAAShaderQualityPreset(
    tier=_QualityTier.LOW.value,
    grain_intensity=0.0,
    line_aa_px=0.0,
    jitter_px=0.0,
    warm_tint=0.0,
    dot_alpha_variance=0.0,
    ink_bleed=0.0,
)
_MEDIUM_PRESET = AAAShaderQualityPreset(
    tier=_QualityTier.MEDIUM.value,
    grain_intensity=0.012,
    line_aa_px=1.0,
    jitter_px=0.0,
    warm_tint=0.0,
    dot_alpha_variance=0.08,
    ink_bleed=0.15,
)
_HIGH_PRESET = AAAShaderQualityPreset(
    tier=_QualityTier.HIGH.value,
    grain_intensity=0.017,
    line_aa_px=1.4,
    jitter_px=0.45,
    warm_tint=0.045,
    dot_alpha_variance=0.12,
    ink_bleed=0.22,
)

# Attach the three tiers to the class for `AAAShaderQualityPreset.HIGH` sugar.
# (frozen=True only guards instance mutation, not class attribute assignment.)
AAAShaderQualityPreset.LOW = _LOW_PRESET  # type: ignore[attr-defined]
AAAShaderQualityPreset.MEDIUM = _MEDIUM_PRESET  # type: ignore[attr-defined]
AAAShaderQualityPreset.HIGH = _HIGH_PRESET  # type: ignore[attr-defined]


DEFAULT_AAA_PRESET: AAAShaderQualityPreset = _HIGH_PRESET


# ---------------------------------------------------------------------------
# 15 WGSL page-lining shaders.
#
# WGSL uniform contract (used by the shaders that reference them):
#   @group(0) @binding(0) var<uniform> u_theme_color_1: vec4<f32>;  paper
#   @group(0) @binding(1) var<uniform> u_theme_color_2: vec4<f32>;  ink
# The numpy fallback in renderer.py mirrors each shader's *intent* so
# headless test runs still see the same visual pattern.
# ---------------------------------------------------------------------------


_RULED_PAPER = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.98, 0.97, 0.92);
    let ink = vec3<f32>(0.62, 0.71, 0.85);
    let red = vec3<f32>(1.0, 0.44, 0.71);
    let line = step(23.0, (fp.y % 24.0));
    let margin = step(32.0, fp.x) * step(fp.x, 33.0);
    return vec4<f32>(mix(mix(paper, ink, line), red, margin), 1.0);
}
""".strip()

_DOT_GRID = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.98, 0.97, 0.92);
    let ink = vec3<f32>(0.42, 0.51, 0.65);
    let s: f32 = 24.0;
    let r: f32 = 1.5;
    let c = vec2<f32>(fp.x % s, fp.y % s) - vec2<f32>(s * 0.5);
    let d = sqrt(c.x * c.x + c.y * c.y);
    let dot = 1.0 - smoothstep(r, r + 0.5, d);
    return vec4<f32>(mix(paper, ink, dot * 0.6), 1.0);
}
""".strip()

_GRAPH_GRID = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.96, 0.98, 0.95);
    let ink = vec3<f32>(0.55, 0.75, 0.60);
    let s: f32 = 10.0;
    let gx = step((fp.x % s), 1.0);
    let gy = step((fp.y % s), 1.0);
    let line = min(gx + gy, 1.0);
    return vec4<f32>(mix(paper, ink, line * 0.5), 1.0);
}
""".strip()

_ISOMETRIC_GRID = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.97, 0.96, 0.93);
    let ink = vec3<f32>(0.5, 0.55, 0.7);
    let s: f32 = 24.0;
    let h = s * 0.8660254;
    let a = fp.y % s;
    let b = (fp.y + fp.x * 1.7320508) % (2.0 * h);
    let c = (fp.y - fp.x * 1.7320508 + 4096.0) % (2.0 * h);
    let l = min(min(step(a, 1.0), 1.0), 1.0);
    let m = step(b, 1.0) + step(c, 1.0) + l;
    let ln = clamp(m, 0.0, 1.0);
    return vec4<f32>(mix(paper, ink, ln * 0.4), 1.0);
}
""".strip()

_HEX_GRID = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.98, 0.96, 0.90);
    let ink = vec3<f32>(0.6, 0.5, 0.35);
    let s: f32 = 20.0;
    let x = fp.x % (s * 1.732);
    let y = fp.y % (s * 3.0);
    let edge = abs(sin(x * 0.1815) * sin(y * 0.1047));
    let line = smoothstep(0.95, 1.0, edge);
    return vec4<f32>(mix(paper, ink, line * 0.35), 1.0);
}
""".strip()

_MUSIC_STAFF = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.99, 0.98, 0.95);
    let ink = vec3<f32>(0.15, 0.12, 0.10);
    let s: f32 = 48.0;
    let y = fp.y % s;
    let l1 = step(y, 1.0);
    let l2 = step(8.0, y) * step(y, 9.0);
    let l3 = step(16.0, y) * step(y, 17.0);
    let l4 = step(24.0, y) * step(y, 25.0);
    let l5 = step(32.0, y) * step(y, 33.0);
    let line = clamp(l1 + l2 + l3 + l4 + l5, 0.0, 1.0);
    return vec4<f32>(mix(paper, ink, line * 0.9), 1.0);
}
""".strip()

_BLANK_CREAM = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.97, 0.95, 0.88);
    let n = fract(sin(fp.x * 12.9898 + fp.y * 78.233) * 43758.5453);
    let noise = (n - 0.5) * 0.02;
    return vec4<f32>(paper + vec3<f32>(noise), 1.0);
}
""".strip()

_PARCHMENT_AGED = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.92, 0.85, 0.68);
    let tan = vec3<f32>(0.65, 0.48, 0.28);
    let s: f32 = 128.0;
    let x = fp.x % s;
    let y = fp.y % s;
    let cx = x - s * 0.5;
    let cy = y - s * 0.5;
    let d = sqrt(cx * cx + cy * cy) / (s * 0.5);
    let stain = smoothstep(0.6, 1.05, d) * 0.25;
    let n = fract(sin(fp.x * 3.1 + fp.y * 5.7) * 91.31) * 0.04;
    return vec4<f32>(mix(paper, tan, stain) + vec3<f32>(n - 0.02), 1.0);
}
""".strip()

_KRAFT_PAPER = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.68, 0.52, 0.34);
    let fibre = vec3<f32>(0.48, 0.36, 0.22);
    let s: f32 = 32.0;
    let x = fp.x % s;
    let y = fp.y % s;
    let f = fract(sin(floor(x * 0.5) * 3.7 + floor(y) * 7.1) * 12.9);
    let stripe = step(0.88, f);
    return vec4<f32>(mix(paper, fibre, stripe * 0.5), 1.0);
}
""".strip()

_WATERCOLOR_PAPER = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.96, 0.94, 0.90);
    let shade = vec3<f32>(0.80, 0.78, 0.72);
    let s: f32 = 4.0;
    let x = fp.x % s;
    let y = fp.y % s;
    let bump = fract(sin(floor(x) * 12.9 + floor(y) * 78.2) * 43758.5);
    let rough = smoothstep(0.4, 0.9, bump) * 0.25;
    return vec4<f32>(mix(paper, shade, rough), 1.0);
}
""".strip()

_GRAPH_ENGINEERING = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.94, 0.99, 0.92);
    let ink = vec3<f32>(0.30, 0.55, 0.35);
    let sm: f32 = 5.0;
    let bg: f32 = 25.0;
    let mx = step((fp.x % sm), 1.0);
    let my = step((fp.y % sm), 1.0);
    let mn = min(mx + my, 1.0);
    let bx = step((fp.x % bg), 1.0);
    let by = step((fp.y % bg), 1.0);
    let mj = min(bx + by, 1.0);
    let line = max(mn * 0.25, mj * 0.65);
    return vec4<f32>(mix(paper, ink, line), 1.0);
}
""".strip()

_POLKA_DOT_SOFT = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.99, 0.93, 0.94);
    let ink = vec3<f32>(0.98, 0.72, 0.80);
    let s: f32 = 32.0;
    let r: f32 = 4.0;
    let c = vec2<f32>(fp.x % s, fp.y % s) - vec2<f32>(s * 0.5);
    let d = sqrt(c.x * c.x + c.y * c.y);
    let dot = 1.0 - smoothstep(r, r + 1.5, d);
    return vec4<f32>(mix(paper, ink, dot * 0.7), 1.0);
}
""".strip()

_STAR_SCATTER = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.10, 0.08, 0.22);
    let star = vec3<f32>(1.0, 0.95, 0.80);
    let s: f32 = 32.0;
    let x = fp.x % s;
    let y = fp.y % s;
    let cx = x - s * 0.5;
    let cy = y - s * 0.5;
    let d = sqrt(cx * cx + cy * cy);
    let sparkle = fract(sin(floor(fp.x / s) * 12.9 + floor(fp.y / s) * 78.2) * 43758.5);
    let dot = (1.0 - smoothstep(1.0, 2.0, d)) * step(0.65, sparkle);
    return vec4<f32>(mix(paper, star, dot), 1.0);
}
""".strip()

_LINEN_WOVEN = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.92, 0.88, 0.76);
    let weft = vec3<f32>(0.75, 0.68, 0.52);
    let s: f32 = 8.0;
    let x = fp.x % s;
    let y = fp.y % s;
    let vx = abs(sin(fp.x * 0.7854));
    let vy = abs(sin(fp.y * 0.7854));
    let weave = (vx + vy) * 0.5;
    return vec4<f32>(mix(paper, weft, weave * 0.35), 1.0);
}
""".strip()

_NOTEBOOK_COLLEGE = """
@fragment
fn fs_main(@builtin(position) fp: vec4<f32>) -> @location(0) vec4<f32> {
    let paper = vec3<f32>(0.99, 0.98, 0.96);
    let ink = vec3<f32>(0.55, 0.65, 0.82);
    let red = vec3<f32>(0.90, 0.45, 0.55);
    let line = step(15.0, (fp.y % 16.0));
    let margin = step(48.0, fp.x) * step(fp.x, 49.0);
    return vec4<f32>(mix(mix(paper, ink, line * 0.85), red, margin * 0.9), 1.0);
}
""".strip()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


PAGE_LININGS: dict[str, LiningStyle] = {
    "ruled_paper": LiningStyle(
        style_id="ruled_paper",
        source=_RULED_PAPER,
        tile_size=(64, 24),
        default_paper=(250, 247, 235),
        default_ink=(158, 181, 217),
        description="Horizontal blue rules every 24px + red vertical margin at x=32",
    ),
    "dot_grid": LiningStyle(
        style_id="dot_grid",
        source=_DOT_GRID,
        tile_size=(24, 24),
        default_paper=(250, 247, 235),
        default_ink=(107, 130, 166),
        description="Bullet-journal dots on a 24x24 lattice, soft ink",
    ),
    "graph_grid": LiningStyle(
        style_id="graph_grid",
        source=_GRAPH_GRID,
        tile_size=(10, 10),
        default_paper=(245, 250, 242),
        default_ink=(140, 191, 153),
        description="1mm-style graph paper — 10px squares, mint ink",
    ),
    "isometric_grid": LiningStyle(
        style_id="isometric_grid",
        source=_ISOMETRIC_GRID,
        tile_size=(48, 42),
        default_paper=(247, 245, 237),
        default_ink=(128, 140, 178),
        description="30-60-90 triangular grid for isometric sketches",
    ),
    "hex_grid": LiningStyle(
        style_id="hex_grid",
        source=_HEX_GRID,
        tile_size=(35, 60),
        default_paper=(250, 245, 230),
        default_ink=(153, 128, 90),
        description="Honeycomb hexagonal grid, boardgame-map style",
    ),
    "music_staff": LiningStyle(
        style_id="music_staff",
        source=_MUSIC_STAFF,
        tile_size=(64, 48),
        default_paper=(252, 250, 242),
        default_ink=(38, 31, 26),
        description="Repeating 5-line music staff, 48px period",
    ),
    "blank_cream": LiningStyle(
        style_id="blank_cream",
        source=_BLANK_CREAM,
        tile_size=(64, 64),
        default_paper=(247, 242, 224),
        default_ink=(247, 242, 224),
        description="Solid cream paper with subtle high-freq noise",
    ),
    "parchment_aged": LiningStyle(
        style_id="parchment_aged",
        source=_PARCHMENT_AGED,
        tile_size=(128, 128),
        default_paper=(235, 217, 173),
        default_ink=(166, 122, 71),
        description="Aged parchment with brown edge stains + fibre noise",
    ),
    "kraft_paper": LiningStyle(
        style_id="kraft_paper",
        source=_KRAFT_PAPER,
        tile_size=(32, 32),
        default_paper=(173, 133, 87),
        default_ink=(122, 92, 56),
        description="Brown kraft paper with irregular short fibres",
    ),
    "watercolor_paper": LiningStyle(
        style_id="watercolor_paper",
        source=_WATERCOLOR_PAPER,
        tile_size=(4, 4),
        default_paper=(245, 240, 230),
        default_ink=(204, 199, 184),
        description="Rough watercolour paper — fine bump texture, no lines",
    ),
    "graph_engineering": LiningStyle(
        style_id="graph_engineering",
        source=_GRAPH_ENGINEERING,
        tile_size=(25, 25),
        default_paper=(240, 252, 235),
        default_ink=(77, 140, 89),
        description="Engineering graph paper — 5x5 minor grid + 25px major grid",
    ),
    "polka_dot_soft": LiningStyle(
        style_id="polka_dot_soft",
        source=_POLKA_DOT_SOFT,
        tile_size=(32, 32),
        default_paper=(252, 237, 240),
        default_ink=(250, 184, 204),
        description="Soft pink polka dots on 32x32 lattice, kawaii feel",
    ),
    "star_scatter": LiningStyle(
        style_id="star_scatter",
        source=_STAR_SCATTER,
        tile_size=(32, 32),
        default_paper=(26, 20, 56),
        default_ink=(255, 242, 204),
        description="Kawaii night sky — scattered stars, dark violet ground",
    ),
    "linen_woven": LiningStyle(
        style_id="linen_woven",
        source=_LINEN_WOVEN,
        tile_size=(8, 8),
        default_paper=(235, 225, 194),
        default_ink=(191, 173, 133),
        description="Woven linen fabric — cottagecore cross-hatch weave",
    ),
    "notebook_college": LiningStyle(
        style_id="notebook_college",
        source=_NOTEBOOK_COLLEGE,
        tile_size=(64, 16),
        default_paper=(252, 250, 245),
        default_ink=(140, 166, 209),
        description="College-ruled notebook — narrow 16px rules + wide margin at x=48",
    ),
}


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------


def get_lining(style_id: str) -> LiningStyle:
    """Look up a :class:`LiningStyle` by id.

    Parameters
    ----------
    style_id:
        The registered id (see :func:`list_linings`).

    Raises
    ------
    TypeError
        If ``style_id`` isn't a str.
    KeyError
        If ``style_id`` isn't registered — the exception message lists
        the available ids so callers can recover.
    """
    if not isinstance(style_id, str):
        raise TypeError(
            f"get_lining: style_id must be str; got {type(style_id).__name__}"
        )
    try:
        return PAGE_LININGS[style_id]
    except KeyError as exc:
        known = ", ".join(sorted(PAGE_LININGS.keys()))
        raise KeyError(
            f"get_lining: unknown style_id {style_id!r}; known styles: {known}"
        ) from exc


def list_linings() -> list[str]:
    """Return the sorted list of registered style ids."""
    return sorted(PAGE_LININGS.keys())


def iter_linings() -> Iterable[LiningStyle]:
    """Iterate every registered :class:`LiningStyle` in id-sorted order."""
    for key in list_linings():
        yield PAGE_LININGS[key]


__all__ = [
    "AAAShaderQualityPreset",
    "DEFAULT_AAA_PRESET",
    "LiningStyle",
    "PAGE_LININGS",
    "get_lining",
    "iter_linings",
    "list_linings",
]
