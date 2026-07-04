"""Library of procedural washi-tape shader styles.

Every :class:`WashiTapeStyle` bundles a WGSL fragment-shader source
string with a display name, default swatch size, and metadata. Fifteen
built-in styles live in :data:`WASHI_TAPES` — from the plain
``tape_pink_solid`` to the animated ``tape_sparkle_animated`` — and the
panel-decor system (T2) references them by :attr:`WashiTapeStyle.id`.

Uniform contract
----------------

Every shader may reference the following ``@group(0)`` uniforms::

    struct Uniforms {
        u_time: f32,
        u_size: vec2<f32>,
        u_theme_color_1: vec4<f32>,
        u_theme_color_2: vec4<f32>,
    };

Shaders that omit ``u_time`` are treated as static; the renderer keeps a
single bake in the texture cache. Shaders whose :attr:`animated` flag is
set are re-baked on demand by the panel-decor ticker.

Design constraints
------------------

* Every WGSL source is capped at **1000 bytes** so the entire built-in
  library fits comfortably in a single embedded resource. Animated
  variants use the extra headroom for time-driven expressions.
* All shaders declare their outputs as sRGB fragments — the fallback
  numpy renderer keeps its numeric range in ``[0, 1]`` for parity.
* The alpha channel encodes the tape's torn-paper transparency so
  callers can blit the swatch straight onto a panel corner without
  a separate mask.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# WashiTapeStyle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WashiTapeStyle:
    """One procedural washi-tape style.

    Parameters
    ----------
    id:
        Stable identifier (e.g. ``"tape_pink_dots"``). Referenced by
        :class:`slappyengine.ui.editor.panel_decor.WashiCornerSpec` via
        its ``tape_style_id`` field.
    display_name:
        Human-facing label (e.g. ``"Pink Polka Dots"``).
    wgsl_source:
        The WGSL fragment-shader source. Must be non-empty and <= 800
        bytes.
    default_size:
        Swatch pixel size ``(width, height)`` used when the caller does
        not supply one. Defaults to ``(64, 24)`` to match the panel
        corner geometry.
    animated:
        ``True`` iff the shader depends on ``u_time``.
    description:
        Short prose describing the style, surfaced by the theme picker.
    frame_period_ms:
        Requested re-bake cadence for animated styles, in milliseconds.
        Must be one of ``{200, 300, 500}`` when :attr:`animated` is
        ``True``. For static styles the value is stored but unused (the
        renderer skips re-bakes). The panel-decor ticker clamps this to
        the 10 Hz cap defined in :mod:`.wgsl_backgrounds`.
    """

    id: str
    display_name: str
    wgsl_source: str
    default_size: tuple[int, int] = (64, 24)
    animated: bool = False
    description: str = ""
    frame_period_ms: int = 500

    def __post_init__(self) -> None:
        fn = "WashiTapeStyle"
        if not isinstance(self.id, str) or not self.id:
            raise ValueError(f"{fn}: id must be a non-empty str; got {self.id!r}")
        if not isinstance(self.display_name, str) or not self.display_name:
            raise ValueError(
                f"{fn}: display_name must be a non-empty str; "
                f"got {self.display_name!r}"
            )
        if not isinstance(self.wgsl_source, str) or not self.wgsl_source:
            raise ValueError(
                f"{fn}: wgsl_source must be a non-empty str; "
                f"got {type(self.wgsl_source).__name__}"
            )
        if len(self.wgsl_source.encode("utf-8")) > 1000:
            raise ValueError(
                f"{fn}: wgsl_source for {self.id!r} exceeds the 1000-byte "
                f"budget ({len(self.wgsl_source.encode('utf-8'))} bytes)"
            )
        if (
            not isinstance(self.default_size, tuple)
            or len(self.default_size) != 2
            or not all(isinstance(v, int) and v > 0 for v in self.default_size)
        ):
            raise ValueError(
                f"{fn}: default_size must be a 2-tuple of positive ints; "
                f"got {self.default_size!r}"
            )
        if not isinstance(self.animated, bool):
            raise TypeError(
                f"{fn}: animated must be bool; "
                f"got {type(self.animated).__name__}"
            )
        if not isinstance(self.description, str):
            raise TypeError(
                f"{fn}: description must be str; "
                f"got {type(self.description).__name__}"
            )
        if not isinstance(self.frame_period_ms, int) or isinstance(
            self.frame_period_ms, bool
        ):
            raise TypeError(
                f"{fn}: frame_period_ms must be int; "
                f"got {type(self.frame_period_ms).__name__}"
            )
        if self.animated and self.frame_period_ms not in (200, 300, 500):
            raise ValueError(
                f"{fn}: frame_period_ms for animated style {self.id!r} "
                f"must be one of {{200, 300, 500}}; "
                f"got {self.frame_period_ms}"
            )
        if self.frame_period_ms <= 0:
            raise ValueError(
                f"{fn}: frame_period_ms must be positive; "
                f"got {self.frame_period_ms}"
            )


# ---------------------------------------------------------------------------
# Shared WGSL preamble (uniform block + entry point)
# ---------------------------------------------------------------------------


_WGSL_PREAMBLE = """struct U {
    u_time: f32,
    _pad0: f32,
    u_size: vec2<f32>,
    u_theme_color_1: vec4<f32>,
    u_theme_color_2: vec4<f32>,
};
@group(0) @binding(0) var<uniform> u: U;
"""


def _shader(body: str) -> str:
    """Concatenate the shared preamble with a body snippet.

    Each style provides only the ``fs_main`` function body; this helper
    prepends the uniform block so the finished source is a self-contained
    WGSL module.
    """
    src = _WGSL_PREAMBLE + body
    return src


# ---------------------------------------------------------------------------
# Individual style bodies (fs_main functions)
# ---------------------------------------------------------------------------


_TAPE_PINK_SOLID = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let edge = smoothstep(0.0, 0.06, uv.y) * smoothstep(1.0, 0.94, uv.y);
    let noise = fract(sin(uv.x * 43.0) * 91.0) * 0.05;
    return vec4<f32>(base - noise, 0.85 * edge);
}
""")


_TAPE_PINK_DOTS = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let dot_uv = fract(uv * vec2<f32>(8.0, 3.0));
    let d = distance(dot_uv, vec2<f32>(0.5, 0.5));
    let dot_mask = 1.0 - smoothstep(0.15, 0.25, d);
    let color = mix(base, u.u_theme_color_2.rgb, dot_mask);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


_TAPE_BLUE_STRIPES = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let s = step(0.5, fract(uv.x * 6.0));
    let color = mix(base, u.u_theme_color_2.rgb, s * 0.7);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_YELLOW_GINGHAM = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let a = step(0.5, fract(uv.x * 8.0));
    let b = step(0.5, fract(uv.y * 3.0));
    let g = (a + b) * 0.5;
    let color = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, g);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_MINT_POLKA = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let big = fract(uv * vec2<f32>(4.0, 1.5));
    let sm = fract(uv * vec2<f32>(8.0, 3.0) + vec2<f32>(0.25, 0.5));
    let d1 = 1.0 - smoothstep(0.18, 0.3, distance(big, vec2<f32>(0.5, 0.5)));
    let d2 = 1.0 - smoothstep(0.10, 0.18, distance(sm, vec2<f32>(0.5, 0.5)));
    let m = max(d1, d2 * 0.6);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


_TAPE_LAVENDER_FLORAL = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let cell = fract(uv * vec2<f32>(5.0, 2.0)) - vec2<f32>(0.5, 0.5);
    let r = length(cell);
    let a = atan2(cell.y, cell.x);
    let petal = 0.28 + 0.14 * cos(a * 5.0);
    let m = 1.0 - smoothstep(petal - 0.03, petal + 0.03, r);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


_TAPE_WATERCOLOR_WASH = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let n = fract(sin(dot(uv, vec2<f32>(12.7, 78.2))) * 43758.0);
    let blot = 0.5 + 0.5 * sin(uv.x * 7.0 + n * 2.0);
    let color = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, blot);
    let edge = smoothstep(0.0, 0.08, uv.y) * smoothstep(1.0, 0.92, uv.y);
    return vec4<f32>(color, 0.78 * edge);
}
""")


_TAPE_GOLD_FOIL = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let shimmer = 0.5 + 0.5 * sin(uv.x * 40.0 + uv.y * 8.0);
    let hi = pow(shimmer, 4.0);
    let color = mix(base, u.u_theme_color_2.rgb, hi * 0.75);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_RIPPED_EDGE = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let tear_top = 0.05 + 0.04 * sin(uv.x * 60.0) * fract(sin(uv.x * 17.0) * 51.0);
    let tear_bot = 0.95 - 0.04 * sin(uv.x * 55.0 + 1.0) * fract(sin(uv.x * 23.0) * 71.0);
    let m = step(tear_top, uv.y) * step(uv.y, tear_bot);
    let color = mix(base, u.u_theme_color_2.rgb, 0.15);
    return vec4<f32>(color, 0.9 * m);
}
""")


_TAPE_LACE_BORDER = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let band = step(0.75, uv.y) + step(uv.y, 0.25);
    let scallop = 0.5 + 0.5 * cos(uv.x * 24.0);
    let mask = band * step(0.4, scallop);
    let color = mix(base, u.u_theme_color_2.rgb, mask);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


_TAPE_STAR_CONFETTI = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let g = fract(uv * vec2<f32>(6.0, 2.0)) - vec2<f32>(0.5, 0.5);
    let a = abs(atan2(g.y, g.x));
    let r = length(g);
    let star = 0.24 + 0.08 * cos(a * 5.0);
    let m = 1.0 - smoothstep(star - 0.02, star + 0.02, r);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


_TAPE_KRAFT_PAPER = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let f = fract(sin(dot(uv, vec2<f32>(91.0, 27.0))) * 43758.0);
    let g = f * 0.15;
    let color = base * (0.85 + g);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.92 * edge);
}
""")


_TAPE_RAINBOW_GRADIENT = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let h = uv.x;
    let r = 0.5 + 0.5 * cos(6.28 * (h + 0.0));
    let g = 0.5 + 0.5 * cos(6.28 * (h + 0.33));
    let b = 0.5 + 0.5 * cos(6.28 * (h + 0.67));
    let tint = mix(u.u_theme_color_1.rgb, vec3<f32>(r, g, b), 0.7);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(tint, 0.85 * edge);
}
""")


_TAPE_SPARKLE_ANIMATED = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let cell = floor(uv * vec2<f32>(16.0, 4.0));
    let seed = fract(sin(dot(cell, vec2<f32>(12.0, 78.0))) * 43758.0);
    let tw = 0.5 + 0.5 * sin(u.u_time * 4.0 + seed * 6.28);
    let sp = step(0.85, seed) * tw;
    let color = mix(base, u.u_theme_color_2.rgb, sp);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_MUSIC_NOTES = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let staff = step(0.98, 1.0 - abs(fract(uv.y * 5.0) - 0.5) * 2.0) * 0.4;
    let g = fract(uv * vec2<f32>(6.0, 1.0)) - vec2<f32>(0.5, 0.5);
    let head = 1.0 - smoothstep(0.10, 0.14, length(g * vec2<f32>(1.0, 1.6)));
    let m = max(staff, head);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


# ---------------------------------------------------------------------------
# Animated variants (V7) — sample u_time for shimmer / drift / scroll.
# Every body still fits inside the 1000-byte WashiTapeStyle budget.
# ---------------------------------------------------------------------------


_TAPE_HEART_PULSE = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let s = 1.0 + 0.1 * sin(u.u_time * 12.566);
    let g = (fract(uv * vec2<f32>(5.0, 2.0)) - vec2<f32>(0.5, 0.5)) / s;
    let x = g.x;
    let y = -g.y;
    let a = x * x + y * y - 0.09;
    let heart = a * a * a - x * x * y * y * y;
    let m = 1.0 - smoothstep(-0.002, 0.004, heart);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_SPARKLE_SHIMMER = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let shift = vec2<f32>(u.u_time * 0.15, u.u_time * 0.05);
    let cell = floor((uv + shift) * vec2<f32>(14.0, 4.0));
    let h = fract(sin(dot(cell, vec2<f32>(12.9, 78.2))) * 43758.0);
    let phase = fract(u.u_time * 3.0 + h);
    let sp = smoothstep(0.3, 1.0, phase) * step(0.7, h);
    let color = mix(base, u.u_theme_color_2.rgb, sp);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_RAINBOW_FLOW = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let h = uv.x + u.u_time * 0.1667;
    let r = 0.5 + 0.5 * cos(6.28 * (h + 0.0));
    let g = 0.5 + 0.5 * cos(6.28 * (h + 0.33));
    let b = 0.5 + 0.5 * cos(6.28 * (h + 0.67));
    let tint = mix(u.u_theme_color_1.rgb, vec3<f32>(r, g, b), 0.7);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(tint, 0.85 * edge);
}
""")


_TAPE_MARCHING_DOTS = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let shift = u.u_time * 20.0 / u.u_size.x;
    let du = fract((uv.x + shift) * 8.0);
    let dv = fract(uv.y * 3.0);
    let d = distance(vec2<f32>(du, dv), vec2<f32>(0.5, 0.5));
    let m = 1.0 - smoothstep(0.15, 0.25, d);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_WAVE_SHIFT = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let wave = 0.05 * sin(uv.x * 12.0 + u.u_time * 2.0);
    let shift = u.u_time * 15.0 / u.u_size.y;
    let vy = fract(uv.y - shift + wave);
    let band = step(0.5, vy);
    let color = mix(base, u.u_theme_color_2.rgb, band * 0.55);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_DASHED_SCROLL = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let shift = u.u_time * 30.0 / u.u_size.x;
    let dash = step(0.5, fract((uv.x + shift) * 10.0));
    let band = step(0.35, uv.y) * step(uv.y, 0.65);
    let m = dash * band;
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_STARS_TWINKLE = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let cell = floor(uv * vec2<f32>(6.0, 2.0));
    let h = fract(sin(dot(cell, vec2<f32>(12.0, 78.0))) * 43758.0);
    let phase = h * 6.283;
    let tw = 0.5 + 0.5 * sin(u.u_time * 3.0 + phase);
    let g = fract(uv * vec2<f32>(6.0, 2.0)) - vec2<f32>(0.5, 0.5);
    let r = length(g);
    let a = abs(atan2(g.y, g.x));
    let star = 0.24 + 0.08 * cos(a * 5.0);
    let m = (1.0 - smoothstep(star - 0.02, star + 0.02, r)) * tw;
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.9 * edge);
}
""")


_TAPE_MUSIC_NOTES_FLOW = _shader("""
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let uv = p.xy / u.u_size;
    let base = u.u_theme_color_1.rgb;
    let staff = step(0.98, 1.0 - abs(fract(uv.y * 5.0) - 0.5) * 2.0) * 0.4;
    let shift = u.u_time * 25.0 / u.u_size.x;
    let g = fract((uv + vec2<f32>(shift, 0.0)) * vec2<f32>(6.0, 1.0)) - vec2<f32>(0.5, 0.5);
    let head = 1.0 - smoothstep(0.10, 0.14, length(g * vec2<f32>(1.0, 1.6)));
    let m = max(staff, head);
    let color = mix(base, u.u_theme_color_2.rgb, m);
    let edge = smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);
    return vec4<f32>(color, 0.85 * edge);
}
""")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


WASHI_TAPES: dict[str, WashiTapeStyle] = {
    style.id: style for style in [
        WashiTapeStyle(
            id="tape_pink_solid",
            display_name="Pink Solid",
            wgsl_source=_TAPE_PINK_SOLID,
            description="Plain pastel pink washi tape with subtle paper grain.",
        ),
        WashiTapeStyle(
            id="tape_pink_dots",
            display_name="Pink Polka Dots",
            wgsl_source=_TAPE_PINK_DOTS,
            description="Pink tape with contrasting polka dots.",
        ),
        WashiTapeStyle(
            id="tape_blue_stripes",
            display_name="Blue Stripes",
            wgsl_source=_TAPE_BLUE_STRIPES,
            description="Blue tape with vertical candy stripes.",
        ),
        WashiTapeStyle(
            id="tape_yellow_gingham",
            display_name="Yellow Gingham",
            wgsl_source=_TAPE_YELLOW_GINGHAM,
            description="Yellow gingham checkerboard tape.",
        ),
        WashiTapeStyle(
            id="tape_mint_polka",
            display_name="Mint Polka Mix",
            wgsl_source=_TAPE_MINT_POLKA,
            description="Mint tape with mixed big / small polka dots.",
        ),
        WashiTapeStyle(
            id="tape_lavender_floral",
            display_name="Lavender Floral",
            wgsl_source=_TAPE_LAVENDER_FLORAL,
            description="Lavender tape with five-petal flowers.",
        ),
        WashiTapeStyle(
            id="tape_watercolor_wash",
            display_name="Watercolour Wash",
            wgsl_source=_TAPE_WATERCOLOR_WASH,
            description="Soft two-tone watercolour gradient.",
        ),
        WashiTapeStyle(
            id="tape_gold_foil",
            display_name="Gold Foil",
            wgsl_source=_TAPE_GOLD_FOIL,
            description="Metallic foil tape with sharp specular streaks.",
        ),
        WashiTapeStyle(
            id="tape_ripped_edge",
            display_name="Ripped Edge",
            wgsl_source=_TAPE_RIPPED_EDGE,
            description="Torn paper tape with jagged top and bottom edges.",
        ),
        WashiTapeStyle(
            id="tape_lace_border",
            display_name="Lace Border",
            wgsl_source=_TAPE_LACE_BORDER,
            description="Tape with scalloped lace borders top and bottom.",
        ),
        WashiTapeStyle(
            id="tape_star_confetti",
            display_name="Star Confetti",
            wgsl_source=_TAPE_STAR_CONFETTI,
            description="Tape sprinkled with five-point stars.",
        ),
        WashiTapeStyle(
            id="tape_kraft_paper",
            display_name="Kraft Paper",
            wgsl_source=_TAPE_KRAFT_PAPER,
            description="Brown kraft paper tape with grainy fibres.",
        ),
        WashiTapeStyle(
            id="tape_rainbow_gradient",
            display_name="Rainbow Gradient",
            wgsl_source=_TAPE_RAINBOW_GRADIENT,
            description="Full-spectrum rainbow gradient tape.",
        ),
        WashiTapeStyle(
            id="tape_sparkle_animated",
            display_name="Animated Sparkle",
            wgsl_source=_TAPE_SPARKLE_ANIMATED,
            animated=True,
            frame_period_ms=500,
            description="Tape with twinkling glitter cells driven by u_time.",
        ),
        WashiTapeStyle(
            id="tape_music_notes",
            display_name="Music Notes",
            wgsl_source=_TAPE_MUSIC_NOTES,
            description="Tape with a five-line music staff and note heads.",
        ),
        WashiTapeStyle(
            id="tape_heart_pulse",
            display_name="Heart Pulse",
            wgsl_source=_TAPE_HEART_PULSE,
            animated=True,
            frame_period_ms=200,
            description="Tape of hearts that scale gently with a 2 Hz pulse.",
        ),
        WashiTapeStyle(
            id="tape_sparkle_shimmer",
            display_name="Sparkle Shimmer",
            wgsl_source=_TAPE_SPARKLE_SHIMMER,
            animated=True,
            frame_period_ms=200,
            description="Sparkles that drift and brighten via smoothstep envelopes.",
        ),
        WashiTapeStyle(
            id="tape_rainbow_flow",
            display_name="Rainbow Flow",
            wgsl_source=_TAPE_RAINBOW_FLOW,
            animated=True,
            frame_period_ms=300,
            description="Rainbow gradient whose hue rotates 60 degrees per second.",
        ),
        WashiTapeStyle(
            id="tape_marching_dots",
            display_name="Marching Dots",
            wgsl_source=_TAPE_MARCHING_DOTS,
            animated=True,
            frame_period_ms=300,
            description="Row of polka dots scrolling horizontally at 20 px/s.",
        ),
        WashiTapeStyle(
            id="tape_wave_shift",
            display_name="Wave Shift",
            wgsl_source=_TAPE_WAVE_SHIFT,
            animated=True,
            frame_period_ms=300,
            description="Sinusoidal bands that ripple upward at 15 px/s.",
        ),
        WashiTapeStyle(
            id="tape_dashed_scroll",
            display_name="Dashed Scroll",
            wgsl_source=_TAPE_DASHED_SCROLL,
            animated=True,
            frame_period_ms=300,
            description="Dashed centre band scrolling horizontally at 30 px/s.",
        ),
        WashiTapeStyle(
            id="tape_stars_twinkle",
            display_name="Stars Twinkle",
            wgsl_source=_TAPE_STARS_TWINKLE,
            animated=True,
            frame_period_ms=500,
            description="Five-point stars that twinkle at independent phases.",
        ),
        WashiTapeStyle(
            id="tape_music_notes_flow",
            display_name="Music Notes Flow",
            wgsl_source=_TAPE_MUSIC_NOTES_FLOW,
            animated=True,
            frame_period_ms=300,
            description="Music notes drifting left to right at 25 px/s.",
        ),
    ]
}


# ---------------------------------------------------------------------------
# Convenience: enumerate the animated V7 subset.
# ---------------------------------------------------------------------------


ANIMATED_V7_STYLE_IDS: tuple[str, ...] = (
    "tape_heart_pulse",
    "tape_sparkle_shimmer",
    "tape_rainbow_flow",
    "tape_marching_dots",
    "tape_wave_shift",
    "tape_dashed_scroll",
    "tape_stars_twinkle",
    "tape_music_notes_flow",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def list_tapes() -> list[str]:
    """Return the sorted list of built-in tape style ids."""
    return sorted(WASHI_TAPES.keys())


def get_tape(style_id: str) -> WashiTapeStyle:
    """Look up a :class:`WashiTapeStyle` by id.

    Parameters
    ----------
    style_id:
        Identifier of the built-in style (see :data:`WASHI_TAPES`).

    Raises
    ------
    KeyError
        If *style_id* is not a registered style — the message lists the
        available ids so the caller can spot typos.
    """
    if not isinstance(style_id, str) or not style_id:
        raise KeyError(
            f"get_tape: style_id must be a non-empty str; got {style_id!r}"
        )
    if style_id not in WASHI_TAPES:
        raise KeyError(
            f"get_tape: unknown washi tape style {style_id!r}; "
            f"known: {list_tapes()}"
        )
    return WASHI_TAPES[style_id]


__all__ = [
    "ANIMATED_V7_STYLE_IDS",
    "WashiTapeStyle",
    "WASHI_TAPES",
    "get_tape",
    "list_tapes",
]
