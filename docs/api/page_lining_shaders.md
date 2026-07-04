<!-- handauthored: do not regenerate -->
# slappyengine.ui.theme.page_linings — API Reference

> Library of **WGSL page-lining shaders** — the background patterns
> that make each theme feel like a real paper stock (ruled notebook,
> dot-grid bullet journal, aged parchment, kraft, linen, cottagecore
> polka, kawaii starfield, and more). Each style is a small
> tileable fragment shader plus a matching numpy fallback so headless
> test runs still get pixel-accurate output.

## Overview

A page lining is a **paper background pattern** that ships with a
theme. Every style is expressed twice:

1. **WGSL fragment shader** (≤ 1 KB) with a `fs_main` entry that
   samples `@builtin(position)` and mixes a `paper` colour with an
   `ink` colour according to the pattern rule (horizontal rules, dots,
   staff lines, etc.).
2. **Numpy fallback** in `renderer.py` that paints the same pattern
   from pure numpy. Runs when `wgpu` isn't installed or when no live
   GPU context is registered.

Every style declares a **tile size** so callers can compose the pattern
seamlessly at any panel dimension. Adjacent tile edges match within a
small tolerance (≤ 8 / 255 per channel), enforced by
`test_page_lining_shaders.py`.

## Public surface

```python
from slappyengine.ui.theme.page_linings import (
    # data
    LiningStyle, PAGE_LININGS,
    # access
    get_lining, list_linings, iter_linings,
    # render
    render_lining, bake_lining_texture, has_wgpu,
)
```

### `LiningStyle`

Frozen dataclass. Fields:

| Field | Type | Purpose |
|---|---|---|
| `style_id` | `str` | Stable registry key |
| `source` | `str` | WGSL fragment source (`fs_main` entry) |
| `tile_size` | `(int, int)` | `(width, height)` seamless-tile period |
| `default_paper` | `(int, int, int)` | Paper anchor RGB (0..255) |
| `default_ink` | `(int, int, int)` | Line/ink anchor RGB (0..255) |
| `description` | `str` | Human-readable one-liner |

### `render_lining(style_id, size, paper_color=None, line_color=None, *, force_fallback=False) -> np.ndarray`

Bake a style to an `(H, W, 4)` uint8 RGBA array. `paper_color` and
`line_color` are optional 3-tuple overrides; when omitted the style's
`default_paper` / `default_ink` anchor colours are used. Alpha is
always 255 (paper is opaque).

### `bake_lining_texture(style_id, size, **uniforms) -> np.ndarray`

Convenience wrapper accepting a named uniform bag. Recognised keys:
`paper_color`, `line_color`, `force_fallback`. Unknown keys are logged
at debug level and skipped so callers can pass a shared uniform bag
across multiple bakes.

### ThemeSpec integration

```python
theme = ThemeSpec(
    name="tg-notebook",
    semantic=semantic_tokens,
    background_shader="ruled_paper",   # or "dot_grid", etc.
)
```

`ThemeSpec.background_shader` accepts either a `ShaderEffect` (numpy
recipe), a `WGSLShaderSpec` (freeform WGSL background), or a
**page-lining id string** validated against `PAGE_LININGS`. When a
lining id is provided, the theme resolver calls `render_lining` to
bake a 2×-tile texture that becomes the panel background.

## Uniform contract

Shaders that need theme colours reference two vec4 uniforms:

```wgsl
@group(0) @binding(0) var<uniform> u_theme_color_1: vec4<f32>;  // paper
@group(0) @binding(1) var<uniform> u_theme_color_2: vec4<f32>;  // ink
```

The shipping shaders inline their palette anchors as constants for
maximum portability (so they compile without a uniform bag). The
`render_lining` API supplies runtime overrides through the numpy
fallback path today; the GPU path binds the uniforms once dispatch is
wired up in the follow-up compute-pipeline commit.

## Catalogue

Fifteen styles ship out of the box.

### `ruled_paper`
Horizontal blue rules every 24 px + red vertical margin at x=32.
Tile: **64 × 24**. Anchor: cream paper / soft blue ink.

```wgsl
let line = step(23.0, (fp.y % 24.0));
let margin = step(32.0, fp.x) * step(fp.x, 33.0);
```

### `dot_grid`
Bullet-journal dots on a 24 × 24 lattice, soft ink.
Tile: **24 × 24**. Anchor: cream / muted indigo.

```wgsl
let s: f32 = 24.0; let r: f32 = 1.5;
let c = vec2<f32>(fp.x % s, fp.y % s) - vec2<f32>(s * 0.5);
let dot = 1.0 - smoothstep(r, r + 0.5, sqrt(c.x*c.x + c.y*c.y));
```

### `graph_grid`
1 mm-style graph paper — 10 px squares, mint ink.
Tile: **10 × 10**. Anchor: mint-tinted white / soft green.

```wgsl
let gx = step((fp.x % 10.0), 1.0);
let gy = step((fp.y % 10.0), 1.0);
let line = min(gx + gy, 1.0);
```

### `isometric_grid`
30-60-90 triangular grid for isometric sketches.
Tile: **48 × 42**. Anchor: cream / lavender-blue.

Three intersecting line families (horizontal + two diagonals at ±60°)
give the classic isometric drafting grid.

### `hex_grid`
Honeycomb hexagonal grid, boardgame-map style.
Tile: **35 × 60**. Anchor: warm cream / amber.

Uses `abs(sin(x * kx) * sin(y * ky))` to sketch a hex silhouette
cheaply — an approximation that reads correctly at panel scales.

### `music_staff`
Repeating 5-line music staff, 48 px period.
Tile: **64 × 48**. Anchor: cream / near-black ink.

Five horizontal rules 8 px apart per staff, staves stacked every 48 px.

### `blank_cream`
Solid cream paper with subtle high-frequency noise.
Tile: **64 × 64**. Anchor: cream / cream.

Perlin-free hash noise gives the paper a soft "not quite flat" look
without introducing visible banding.

### `parchment_aged`
Aged parchment with brown edge stains + fibre noise.
Tile: **128 × 128**. Anchor: sepia / tan.

Radial `smoothstep(0.6, 1.05, d)` stain around each tile centre plus a
low-amplitude noise term for fibre grain.

### `kraft_paper`
Brown kraft paper with irregular short fibres.
Tile: **32 × 32**. Anchor: kraft brown / darker kraft.

Uses `floor(x * 0.5)` + `floor(y)` hash to place fibre stripes on a
half-step lattice — mimics unaligned fibres without a lookup table.

### `watercolor_paper`
Rough watercolour paper — fine bump texture, no lines.
Tile: **4 × 4**. Anchor: off-white / dust.

Every pixel gets a deterministic bump value from a hashed position;
`smoothstep(0.4, 0.9, bump)` gives high-contrast dimples without a
mipmap.

### `graph_engineering`
Engineering graph paper — 5 × 5 minor grid + 25 px major grid.
Tile: **25 × 25**. Anchor: pale green / engineering green.

Minor grid at 25 % opacity, major grid at 65 % — matches the two-tone
weight you get from real 4-quadrant engineering pads.

### `polka_dot_soft`
Soft pink polka dots on 32 × 32 lattice, kawaii feel.
Tile: **32 × 32**. Anchor: blush / pink.

```wgsl
let r: f32 = 4.0;
let dot = 1.0 - smoothstep(r, r + 1.5, distance);
```

### `star_scatter`
Kawaii night sky — scattered stars, dark violet ground.
Tile: **32 × 32**. Anchor: deep violet / warm white.

Hash `floor(fp.xy / 32.0)` per-cell decides whether a star sits at the
cell centre, gated with `step(0.65, sparkle)` so ~35 % of cells carry
a star.

### `linen_woven`
Woven linen fabric — cottagecore cross-hatch weave.
Tile: **8 × 8**. Anchor: linen / rope tan.

`abs(sin(x * 0.7854))` on both axes gives a fine cross-hatch. Amplitude
0.35 × so the weave sits over the paper rather than replacing it.

### `notebook_college`
College-ruled notebook — narrow 16 px rules + wide margin at x=48.
Tile: **64 × 16**. Anchor: warm white / periwinkle.

Same shape as `ruled_paper` but with a tighter rule period + wider
left margin, matching a US college-ruled pad.

## Tile continuity contract

`test_page_lining_shaders.py` enforces:

* Row 0 vs row `tile_size[1]` differs by ≤ 8/255 per channel.
* Column 0 vs column `tile_size[0]` differs by ≤ 8/255 per channel.

This lets the renderer sample the baked texture with `repeat` wrap and
get seamless output on any panel size.

## Design notes

* **Why 1 KB per shader?** Themes ship to end users through the PyPI
  wheel. Sixty procedural backgrounds at 1 KB each is 60 KB —
  comfortable against the sub-100 KB per-theme asset target.
* **Why bake instead of drawing live?** Backgrounds refresh at theme
  switch only; per-frame WGSL dispatch is reserved for the animated
  shader path (`wgsl_backgrounds.WGSLBackgroundTicker`, 10 Hz cap).
* **Why colour anchors as constants?** Keeps the shipping shaders
  compilable without a uniform binding, so they slot into the
  numpy-only test harness that ships in CI.

## See also

* [`ui_theme.md`](ui_theme.md) — Parent theme subpackage overview.
* [`ui_editor.md`](ui_editor.md) — Editor shell that consumes baked backgrounds.
* `slappyengine.ui.theme.wgsl_backgrounds` — Freeform WGSL background
  hook that shares the same soft-import / numpy-fallback pattern.
* `slappyengine.ui.theme.shader_effects` — Numpy-only recipe helpers
  (ruled_paper, dot_grid, highlighter_stroke, paper_shadow, ...).
