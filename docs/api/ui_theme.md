<!-- handauthored: do not regenerate -->
# slappyengine.ui.theme — API Reference

> Hand-written reference for the **PRIMITIVE infrastructure** that any
> SlapPyEngine UI theme builds on. Owns the nine-slice texture renderer,
> the tiny SVG icon rasteriser, the procedural background / effect
> texture helpers, and the declarative `ThemeSpec` data model + registry.
> The companion theme *content* (e.g. the upcoming "TeenGirl Notebook"
> pack) lives in a sibling module and imports from here. For the editor
> shell that consumes these primitives at runtime see
> [`ui_editor.md`](ui_editor.md).

## Overview

The theme subpackage solves three problems with three primitive shapes:

| Need | Primitive | Why |
|---|---|---|
| Borders / panels that scale to any size | **Nine-slice** | Small fixed source pattern → crisp corners + tiled edges at any DPI. |
| Icons | **SVG** | Vector authoring → zero asset-size cost at any DPI; rasterised on demand to RGBA ndarrays. |
| Backgrounds + effects | **Procedural / shader-bake** | No PNG bake at all — every surface is a `numpy` array generated at startup. |

The whole subpackage is **GPU-free**: every primitive produces a
``(H, W, 4)`` ``uint8`` RGBA ndarray that the consumer hands to whatever
renderer the host editor uses (DPG texture registry, PIL canvas,
``wgpu`` texture upload, browser ``<canvas>``).

On-disk asset budget target: **< 100 KB** total per theme. The
primitives themselves ship no reference textures — they synthesise
everything at runtime.

## Public surface

```python
from slappyengine.ui.theme import (
    # data classes
    Color, Font, NineSlice, Palette, ShaderEffect, SVGIcon, ThemeSpec,
    # registry
    apply_theme, get_active_theme, list_registered_themes, register_theme,
    # procedural effects
    highlighter_stroke, noise_glitter, paper_shadow, ruled_paper,
)
```

`__all__` is alphabetised. Every public function performs input
validation through the shared ``slappyengine._validation`` helpers per
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Classes

### `Color`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

An sRGB colour with 8-bit per-channel `r`/`g`/`b` (`[0, 255]`) plus a
unit-float alpha (`[0.0, 1.0]`). Two accessors:

- `as_rgba_tuple() -> (int, int, int, int)` — alpha rescaled to 0..255.
- `as_float_tuple() -> (float, float, float, float)` — every channel in
  `[0, 1]` for shader uniforms / wgpu upload.

### `Palette`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

A named bag of `Color` entries keyed by semantic role
(`"primary"`, `"surface"`, `"accent"`, …). Validation refuses
non-`Color` entries so palette typos surface at construction time
rather than at render time.

### `Font`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

A `(family, size, weight)` record. No rasterisation is implied — fonts
are *named* and resolved by the host renderer.

### `NineSlice`

_dataclass — defined in `slappyengine.ui.theme.nine_slice`_

Nine-slice texture renderer.

```python
NineSlice(
    source: Path | bytes | np.ndarray | None,
    insets: tuple[int, int, int, int],   # (top, right, bottom, left)
)
```

#### Methods

- `render(target_size: tuple[int, int]) -> np.ndarray` — load the
  source, copy four corners verbatim, tile the four edges along their
  long axis, tile the centre block in both directions. Returns
  ``(H, W, 4)`` ``uint8``. Raises ``ValueError`` if `target_size` is
  smaller than the inset sum.
- `render_procedural(size, color, pattern_fn=None) -> np.ndarray` —
  synthesise the border using *color* and either solid-fill the centre
  or call `pattern_fn(width, height) -> ndarray` to build it. This is
  the zero-asset path the SlapPyEngine theme system prefers.

The `to_dict` / `from_dict` round-trip intentionally drops the source
array — bytes do not survive YAML. Callers re-attach the source on
deserialise if needed.

### `SVGIcon`

_dataclass — defined in `slappyengine.ui.theme.svg_icon`_

Minimal SVG rasteriser. Parses a useful subset of SVG without pulling
in `cairosvg` / `pyrsvg` / a Qt runtime:

| Element | Attributes parsed |
|---|---|
| `<rect>` | `x`, `y`, `width`, `height`, `fill`, `stroke`, `stroke-width` |
| `<circle>` | `cx`, `cy`, `r`, `fill` |
| `<line>` | `x1`, `y1`, `x2`, `y2`, `stroke`, `stroke-width` |
| `<polygon>` | `points`, `fill` |
| `<path>` | `d` (subset: `M`, `L`, `Z`, `H`, `V`, lowercase variants), `fill`, `stroke` |

Colour parsing covers `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(r,g,b)`,
`none`, and the primary named colours.

#### Methods

- `rasterize() -> np.ndarray` — rasterise into a square
  ``(size, size, 4)`` ``uint8`` buffer; cached by `(svg_hash, size)` so
  identical XML / size pairs share storage.
- `to_dpg_texture(registry) -> int` — upload the rasterised buffer to
  a Dear PyGui texture registry. The returned texture id is cached on
  the icon so repeat calls do not re-upload. Raises `ImportError` with
  the standard `pip install SlapPyEngine[editor]` hint if dearpygui is
  not installed.

Texture cache is shared module-globally; call
`slappyengine.ui.theme.svg_icon.clear_cache()` between tests.

### `ShaderEffect`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

A *named* procedural-texture recipe: an effect name + a kwargs bag.
Pure data — the registry-side dispatcher (typically one of the helpers
in `shader_effects`) resolves the name to a generator.

### `ThemeSpec`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

The top-level declarative theme:

```python
@dataclass
class ThemeSpec:
    name: str
    palette: dict[str, Color]
    fonts: dict[str, Font]
    nine_slices: dict[str, NineSlice]
    icons: dict[str, SVGIcon]
    background_shader: ShaderEffect | None
    metadata: dict[str, str]
```

Round-tripping methods:

- `to_dict() -> dict` / `from_dict(data) -> ThemeSpec` — YAML/JSON-safe
  payload (`NineSlice` source bytes are intentionally dropped; icons
  serialise their full SVG markup).
- `to_yaml() -> str` / `from_yaml(text) -> ThemeSpec` — convenience
  wrappers over PyYAML; raise `ImportError` if PyYAML is not installed.

## Functions

### `register_theme(theme: ThemeSpec) -> None`

Register *theme* under its name. Re-registering the same name
overwrites the previous entry.

Raises:
- `TypeError` — if *theme* is not a `ThemeSpec`.

### `apply_theme(theme_name: str) -> ThemeSpec`

Swap the active theme. Returns the resolved spec so callers can chain a
follow-up render call inline.

Raises:
- `LookupError` — if no theme of that name has been registered.

### `get_active_theme() -> ThemeSpec`

Return the active spec.

Raises:
- `LookupError` — if `apply_theme` has not been called yet.

### `list_registered_themes() -> list[str]`

Sorted list of every registered theme name. Cheap inspection helper.

### `ruled_paper(width, height, line_color, line_spacing=24, margin_color, margin_x=32, paper_color)`

Generate a ruled-notebook background texture. Returns
``(H, W, 4)`` ``uint8`` RGBA. Most pixels are `paper_color`; horizontal
rules at every multiple of `line_spacing` carry `line_color`; an
optional left margin rule at `margin_x` carries `margin_color`. Set
the alpha of `margin_color` to 0 (or `margin_x < 0`) to disable.

### `highlighter_stroke(width, height, color, wobble=0.5, seed=1234)`

Translucent horizontal pen stroke with edge jitter. Alpha peaks at the
band centre and falls off through a linear envelope so the stroke
blends naturally over `ruled_paper`. *wobble* in `[0, 1]` controls
edge jitter strength; *seed* makes the pattern reproducible.

### `paper_shadow(width, height, blur_radius=8, color)`

Soft drop-shadow texture — a Gaussian alpha envelope around `color`.
`blur_radius` is the Gaussian standard deviation in pixels.

### `noise_glitter(width, height, density=0.1, color, seed=7)`

Sparse sparkle pattern. `density` ∈ `[0, 1]` controls the fraction of
pixels lit; lit pixels carry `color`; the rest is fully transparent.

## Inner modules

- `slappyengine.ui.theme.theme_spec` — `Color`, `Font`, `Palette`,
  `ShaderEffect`, `ThemeSpec` dataclasses + YAML round-trip.
- `slappyengine.ui.theme.nine_slice` — image-backed +
  procedural nine-slice renderer.
- `slappyengine.ui.theme.svg_icon` — SVG parser, rasteriser,
  DPG texture bridge, module-global rasterised-texture cache.
- `slappyengine.ui.theme.shader_effects` — pure-numpy procedural
  texture helpers (`ruled_paper`, `highlighter_stroke`,
  `paper_shadow`, `noise_glitter`).

## Conventions

- **Lazy import.** The parent `slappyengine.ui` package resolves
  `theme` through its `__getattr__` so importing `slappyengine.ui`
  alone does not eagerly load this subpackage.
- **Validation.** Every public boundary calls the shared
  `slappyengine._validation` helpers per `CONTRIBUTING.md` — no
  duplicate `_theme_validation.py` module.
- **No GPU dependency.** Every primitive returns ``np.uint8`` RGBA
  ndarrays. The DPG bridge (`SVGIcon.to_dpg_texture`) lives in
  `svg_icon.py` and defers the `dearpygui` import to call time so
  CPU-only test runs do not require the optional `[editor]` extra.
- **Asset-size budget.** No reference textures ship with this
  subpackage. Procedural helpers + SVG markup keep the on-disk theme
  footprint under 100 KB.

## See also

- [`ui_editor.md`](ui_editor.md) — the optional Dear PyGui editor
  shell that ultimately consumes these primitives.
- [`material.md`](material.md) — for material *graph* theming inside
  the editor; unrelated to UI chrome theming.
