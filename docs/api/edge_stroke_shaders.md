# Edge-stroke shaders

Hand-drawn WGSL border styles for UI panels.

`pharos_editor.ui.theme.edge_strokes` ships a library of 15 short WGSL
fragment shaders — each one replaces the flat `border_color` line
around a DPG panel with a textured, hand-drawn stroke (pencil, pen,
marker, brush, chalk, charcoal, …).

Every style has:

* A short WGSL source (bounded to 1000 bytes per shader).
* A matching numpy fallback so the renderer keeps working with no GPU.
* A canonical thickness and alpha authored to read at 1x DPI.

## Quick start

```python
from pharos_editor.ui.theme import (
    FrameStyle,
    get_edge_stroke,
    render_stroke_border,
    bake_stroke_texture,
)

# 1. Attach a stroke to a panel frame:
pencil = get_edge_stroke("pencil_2b")
frame = FrameStyle(edge_stroke=pencil)

# 2. Bake border strips (top / right / bottom / left):
strips = render_stroke_border("pencil_2b", panel_bounds=(320, 200))
top_rgba = strips["top"]        # (thickness, width, 4) uint8

# 3. Or bake a whole-panel preview:
tex = bake_stroke_texture("marker_thick", panel_bounds=(320, 200))
# tex.shape == (200, 320, 4)
```

## Style library

The table below lists every registered style, its canonical
thickness / alpha, tags, and a WGSL snippet you can adapt.

| Style | Thickness | Alpha | Tags | Use |
| --- | --- | --- | --- | --- |
| `ballpoint_pen` | 1.5 px | 0.92 | wet, smooth | Data-entry inputs, small dialogs |
| `gel_pen` | 2.0 px | 0.95 | wet, smooth | Confirmation modals |
| `pencil_2b` | 2.0 px | 0.85 | dry, textured | Sketch / draft panels |
| `pencil_hb` | 1.5 px | 0.90 | dry, textured | Wireframe / grid panels |
| `marker_thick` | 4.0 px | 0.98 | wet, smooth | Section headers, tool palettes |
| `highlighter` | 8.0 px | 0.32 | wet, translucent | Attention callouts, notes |
| `brush_watercolor` | 6.0 px | 0.70 | wet, translucent, textured | Editorial / diary panels |
| `chalk` | 3.0 px | 0.55 | dry, textured | Blackboard theme sections |
| `charcoal` | 3.5 px | 0.75 | dry, textured | Sketch-heavy tool panels |
| `crayon` | 3.0 px | 0.80 | dry, textured | Whimsical / notebook themes |
| `ink_wash` | 5.0 px | 0.60 | wet, translucent | Sumi-e themed backgrounds |
| `sharpie` | 3.0 px | 1.00 | wet, smooth | High-contrast solid outline |
| `colored_pencil` | 2.0 px | 0.85 | dry, textured | Illustration-adjacent panels |
| `fountain_pen` | 2.5 px | 0.90 | wet, smooth | Calligraphy / journal themes |
| `quill` | 2.5 px | 0.78 | wet, textured | Historical / RPG UIs |

## WGSL uniform contract

Every shader is authored against the same tiny uniform block:

```wgsl
struct Uniforms {
  u_size: vec2<f32>,           // strip width/height in pixels
  u_theme_color_1: vec4<f32>,  // ink / stroke colour
  u_theme_color_2: vec4<f32>,  // highlight / paper colour
}
@group(0) @binding(0) var<uniform> u: Uniforms;
```

The renderer sources the two colours from the active theme's semantic
tokens (typically `primary` / `surface`). Themes that supply neither
fall back to the theme border colour.

## Representative shaders

### pencil_2b — soft graphite with noise

```wgsl
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let n = fract(sin(t * 100.0) * 43758.5453);
  let s = 0.7 + n * 0.3;
  let c = mix(u.u_theme_color_1.rgb, u.u_theme_color_2.rgb, n * 0.3);
  return vec4<f32>(c, s);
}
```

### highlighter — translucent band with slight bleed

```wgsl
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let bleed = 0.05 * sin(t * 7.0);
  return vec4<f32>(u.u_theme_color_1.rgb, 0.32 + bleed);
}
```

### chalk — crumbly gap-filled dry stroke

```wgsl
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let g = fract(sin(t * 51.7 + 3.1) * 91731.0);
  let crumb = step(0.18, g);
  let a = 0.55 * crumb + 0.15;
  let c = mix(u.u_theme_color_2.rgb, u.u_theme_color_1.rgb, crumb);
  return vec4<f32>(c, a);
}
```

### sharpie — solid opaque felt-tip

```wgsl
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  return vec4<f32>(u.u_theme_color_1.rgb, 1.0);
}
```

### fountain_pen — thick-thin calligraphic variation

```wgsl
@fragment
fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  let t = p.x / u.u_size.x;
  let width = 0.6 + 0.35 * (sin(t * 4.0) * 0.5 + 0.5);
  return vec4<f32>(u.u_theme_color_1.rgb, width);
}
```

## API reference

### `EdgeStrokeStyle`

Frozen dataclass. Fields:

| Field | Type | Notes |
| --- | --- | --- |
| `style_id` | `str` | Registry key. Matches `EDGE_STROKES` dict key. |
| `thickness_px` | `float` | Canonical stroke thickness at 1x DPI. > 0. |
| `alpha` | `float` | Canonical average opacity in `[0, 1]`. |
| `wgsl_source` | `str` | Fragment-shader source. Entry point `fs_main`. |
| `entry_point` | `str` | Defaults to `"fs_main"`. |
| `description` | `str` | Human-readable summary. |
| `tags` | `tuple[str, ...]` | Filterable classifier tags. |

Constructor raises `ValueError` if `wgsl_source` exceeds 1000 bytes.

### `EDGE_STROKES`

`dict[str, EdgeStrokeStyle]`. All 15 registered styles.

### `get_stroke(style_id) -> EdgeStrokeStyle`

Registry lookup. Raises `KeyError` (with the available list) on
unknown IDs.

### `list_strokes() -> list[str]`

Sorted list of every registered style ID.

### `render_stroke_border(style_id, panel_bounds, width_px=None, *, color_1=None, color_2=None) -> dict[str, np.ndarray]`

Renders the four border strips.

| Parameter | Type | Notes |
| --- | --- | --- |
| `style_id` | `str` | Registry key. |
| `panel_bounds` | `(int, int)` | Panel `(width, height)` in pixels. |
| `width_px` | `float \| None` | Stroke thickness. Falls back to the style's canonical thickness. |
| `color_1` | `Color \| tuple \| None` | Ink colour. Defaults to opaque black. |
| `color_2` | `Color \| tuple \| None` | Highlight / paper colour. Defaults to warm off-white. |

Returns a dict with keys `"top"`, `"right"`, `"bottom"`, `"left"`.

* `"top"` / `"bottom"` shape: `(thickness, width, 4)` uint8.
* `"left"` / `"right"` shape: `(height, thickness, 4)` uint8.

### `bake_stroke_texture(style_id, panel_bounds, ...) -> np.ndarray`

Composites the four strips into a single `(height, width, 4)` uint8
texture with a transparent interior. Convenient for previews /
snapshots / tests.

### `has_wgpu() -> bool`

Reports whether wgpu imported successfully at module load. When
`False` every call goes through the numpy fallback.

## Theme integration

`FrameStyle.edge_stroke` accepts an `EdgeStrokeStyle` (or `None`).
When set, the DPG bridge replaces the flat `border_color` line with a
rendered stroke texture. Per-panel-kind overrides work through the
existing `PanelFrameSet.for_panel(kind)` lookup — one theme can give
toolbars a `sharpie` frame and dialogs a `pencil_2b` frame.

```python
from pharos_editor.ui.theme import (
    FrameStyle, PanelFrameSet, get_edge_stroke,
)

frames = PanelFrameSet(
    default=FrameStyle(edge_stroke=get_edge_stroke("pencil_2b")),
    toolbar=FrameStyle(edge_stroke=get_edge_stroke("sharpie")),
    modal=FrameStyle(edge_stroke=get_edge_stroke("marker_thick")),
)
```

## Testing

`SlapPyEngineTests/tests/test_edge_stroke_shaders.py` exercises the
full surface — registry integrity, per-style WGSL validity, renderer
shape / dtype / thickness, per-style alpha character, numpy fallback,
theme colour propagation, `FrameStyle` integration, and validation
errors. 39 tests total, all headless, all GPU-free.

Run the suite:

```bash
PYTHONPATH=python python -m pytest \
    SlapPyEngineTests/tests/test_edge_stroke_shaders.py --no-header -q
```
