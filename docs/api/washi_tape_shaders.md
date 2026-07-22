# Washi-Tape Shader Library

`pharos_editor.ui.theme.washi_tape` ships a library of fifteen
procedural WGSL fragment shaders that render pastel washi-tape swatches
for the panel-decor system (T2). Every style is a **short WGSL source
string** (<= 800 bytes) plus a numpy fallback so tape swatches bake
cleanly on both GPU and headless CI.

## Quick start

```python
from pharos_editor.ui.theme.washi_tape import (
    WASHI_TAPES, WashiTapeStyle, bake_tape_texture, get_tape, list_tapes,
    render_tape,
)

# Enumerate every built-in style id.
print(list_tapes())

# Render a 64x24 pink-polka swatch with themed colours.
rgba = render_tape(
    "tape_pink_dots",
    size=(64, 24),
    theme_color_1=(255, 181, 197),
    theme_color_2=(255, 255, 255),
)
# rgba is a uint8 (24, 64, 4) array ready to blit onto a panel corner.
```

`bake_tape_texture()` is the same call but accepts kwargs so themes can
stay declarative:

```python
img = bake_tape_texture(
    "tape_sparkle_animated",
    theme_color_1=(220, 200, 250),
    theme_color_2=(255, 255, 255),
    time=0.35,
)
```

## Uniform contract

Every WGSL shader references the same uniform block:

```wgsl
struct U {
    u_time: f32,
    _pad0: f32,
    u_size: vec2<f32>,
    u_theme_color_1: vec4<f32>,
    u_theme_color_2: vec4<f32>,
};
@group(0) @binding(0) var<uniform> u: U;
```

Static shaders ignore `u_time`; animated shaders (only
`tape_sparkle_animated` today) reference it inside `fs_main` and are
re-baked on the panel-decor ticker.

## Style catalogue

| ID | Display name | Animated | Example use case |
| --- | --- | :-: | --- |
| `tape_pink_solid` | Pink Solid | | Kawaii dashboard headers |
| `tape_pink_dots` | Pink Polka Dots | | Diary window corners |
| `tape_blue_stripes` | Blue Stripes | | Coastal / marine themes |
| `tape_yellow_gingham` | Yellow Gingham | | Sunshine-planner corners |
| `tape_mint_polka` | Mint Polka Mix | | Cottagecore tooltips |
| `tape_lavender_floral` | Lavender Floral | | Florist / botanical themes |
| `tape_watercolor_wash` | Watercolour Wash | | Watercolour scrapbook |
| `tape_gold_foil` | Gold Foil | | Premium / achievement dialogs |
| `tape_ripped_edge` | Ripped Edge | | Raw-torn ephemera |
| `tape_lace_border` | Lace Border | | Wedding / bridal themes |
| `tape_star_confetti` | Star Confetti | | Celebration / party themes |
| `tape_kraft_paper` | Kraft Paper | | Rustic notebook themes |
| `tape_rainbow_gradient` | Rainbow Gradient | | Pride month, celebration |
| `tape_sparkle_animated` | Animated Sparkle | Y | Level-up / focus modes |
| `tape_music_notes` | Music Notes | | Audio panels, playlists |

## Example WGSL snippet

Every style follows the same template. Here is `tape_pink_dots`:

```wgsl
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
```

Points to notice:

* `uv = p.xy / u.u_size` matches the numpy fallback's UV grid.
* `edge` is the shared torn-paper alpha ramp — every style ends the
  fragment with `vec4<f32>(color, alpha * edge)` so callers can blit
  the swatch without a separate mask.
* Themes pick colours by binding `u_theme_color_1` / `u_theme_color_2`
  to the appropriate `SemanticTokens` field — typically `primary` and
  `accent`.

## Animated example

`tape_sparkle_animated` twinkles a scattering of glitter cells over the
base tape:

```wgsl
let cell = floor(uv * vec2<f32>(16.0, 4.0));
let seed = fract(sin(dot(cell, vec2<f32>(12.0, 78.0))) * 43758.0);
let tw   = 0.5 + 0.5 * sin(u.u_time * 4.0 + seed * 6.28);
let sp   = step(0.85, seed) * tw;
let color = mix(base, u.u_theme_color_2.rgb, sp);
```

At a 10 Hz re-bake budget this stays under 1 % CPU on integrated GPUs
and is essentially free when the GPU path is enabled.

## Numpy fallback

Every style also has a pure-numpy fallback registered in
`pharos_editor.ui.theme.washi_tape.renderer._FALLBACKS`. These are used
whenever `wgpu` is not importable (all headless CI, all our unit
tests). They reproduce the WGSL output up to floating-point rounding
so themes look identical between the two backends.

You never call the fallback directly — `render_tape` dispatches
automatically.

## T2 integration

`pharos_editor.ui.editor.panel_decor.WashiCornerSpec` now carries an
optional `tape_style_id: str | None` field. Setting it to a valid
`WashiTapeStyle.id` opts a theme into the shader library:

```python
from pharos_editor.ui.editor.panel_decor import WashiCornerSpec, WashiCornerStyle

WashiCornerSpec(
    corner="TL",
    style=WashiCornerStyle.TAPE_PINK,
    tape_style_id="tape_pink_dots",  # NEW - references WASHI_TAPES
)
```

* `tape_style_id=None` (the default) keeps the legacy pigment path so
  themes authored before the shader library keep working unchanged.
* Passing a `tape_style_id` that is **not** in `WASHI_TAPES` raises
  `ValueError` at construction time — this eliminates the typo class
  of "silently falls back to pink" bugs.

## Error handling

* `get_tape("bogus")` -> `KeyError` with the list of known ids in the
  message.
* `render_tape("tape_pink_dots", (0, 12))` -> `ValueError` (size must
  be positive ints).
* `bake_tape_texture("tape_pink_dots", size=(64, 24), typo=True)` ->
  `TypeError` (only `theme_color_1`, `theme_color_2`, `time`, and
  `use_gpu` are accepted).
* Constructing a `WashiTapeStyle` with a source over 800 bytes ->
  `ValueError` (byte budget is enforced at authoring time).

## Files

* `python/pharos_engine/ui/theme/washi_tape/__init__.py` — public surface.
* `python/pharos_engine/ui/theme/washi_tape/library.py` — 15 style
  records + WGSL sources + `get_tape` / `list_tapes` helpers.
* `python/pharos_engine/ui/theme/washi_tape/renderer.py` —
  `render_tape` + `bake_tape_texture` + per-style numpy fallbacks.
* `PharosEngineTests/tests/test_washi_tape_shaders.py` — 77 tests
  (registry sanity, WGSL contract, numpy fallback per style, colour
  propagation, animation, `WashiCornerSpec` integration).
