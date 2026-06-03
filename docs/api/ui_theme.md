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
    Color, Font, Gradient, NineSlice, Palette, ShaderEffect, SVGIcon,
    SemanticTokens, SpacingScale, RadiusScale, TransitionScale, ZIndexScale,
    ThemeSpec,
    # registry
    apply_theme, get_active_theme, list_registered_themes, register_theme,
    # procedural effects
    dot_grid, frosted_panel, glass_blur, highlighter_stroke,
    noise_glitter, paper_shadow, parchment, ruled_paper,
    watercolor_wash,
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

### `Gradient`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

A two-stop linear gradient (`start: Color`, `end: Color`, `angle_deg:
float = 135.0`). `135°` matches the EyesOfAzrael `--theme-gradient`
convention (top-left to bottom-right sweep).

- `sample(t: float) -> Color` — interpolate per-channel in sRGB. `t=0`
  returns `start`, `t=1` returns `end`, `t=0.5` is the midpoint.
  Raises `ValueError` if `t` is outside `[0, 1]`.

### `SemanticTokens`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

A **named contract** above the raw palette. Widget code should read
from this layer so swapping themes only requires rebinding the token
surface, not editing widgets. Field names track the EyesOfAzrael
`--theme-*` / `--glass-*` custom-property vocabulary.

```python
@dataclass
class SemanticTokens:
    primary: Color
    primary_gradient: Gradient
    secondary: Color
    accent: Color
    background: Color
    surface: Color           # raised cards / panels
    surface_hover: Color
    border: Color
    text_primary: Color
    text_secondary: Color
    text_disabled: Color
    success: Color
    warning: Color
    error: Color
    info: Color
    focus_ring: Color
    glass_bg: Color          # translucent panel base (glassmorphism)
    glass_blur_px: float     # backdrop-blur sigma, px
```

`to_dict` / `from_dict` are YAML/JSON safe.

### `SpacingScale`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

Six-step spacing scale in DPG pixels: `xs=4`, `sm=8`, `md=16`, `lg=24`,
`xl=32`, `xxl=48`. Each field must be a non-negative finite number.
Tracks EyesOfAzrael's `--spacing-*` token family.

### `RadiusScale`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

Five-step border-radius scale in DPG pixels: `sm=4`, `md=8`, `lg=12`,
`xl=16`, `pill=999`. `pill` is intentionally over-sized so it can be
applied directly as `border-radius: 9999px`-style "fully rounded".

### `TransitionScale`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

Three-step transition-duration scale in seconds: `fast=0.15`,
`normal=0.25`, `slow=0.5`. Each field must be a *positive* finite
number (a zero-duration transition is rejected).

### `ZIndexScale`

_frozen dataclass — defined in `slappyengine.ui.theme.theme_spec`_

Four-tier z-index scale: `base=1`, `dropdown=100`, `modal=1000`,
`toast=2000`. Tiers must rise monotonically; a typo that would push a
toast under a modal raises `ValueError` at construction.

### `ThemeSpec`

_dataclass — defined in `slappyengine.ui.theme.theme_spec`_

The top-level declarative theme:

```python
@dataclass
class ThemeSpec:
    name: str
    semantic: SemanticTokens             # REQUIRED — named contract
    palette: dict[str, Color]            # raw colour bag (backwards compat)
    spacing: SpacingScale = SpacingScale()
    radius: RadiusScale = RadiusScale()
    transitions: TransitionScale = TransitionScale()
    z_index: ZIndexScale = ZIndexScale()
    fonts: dict[str, Font]
    nine_slices: dict[str, NineSlice]
    icons: dict[str, SVGIcon]
    background_shader: ShaderEffect | None
    metadata: dict[str, str]
```

`semantic` is a **required** field — constructing a `ThemeSpec` without
it raises `TypeError: missing 1 required positional argument: 'semantic'`.
The `palette` dict remains for backwards compatibility — existing code
that reads `theme.palette["primary"]` keeps working.

Round-tripping methods:

- `to_dict() -> dict` / `from_dict(data) -> ThemeSpec` — YAML/JSON-safe
  payload (`NineSlice` source bytes are intentionally dropped; icons
  serialise their full SVG markup; semantic tokens + every scale
  serialise via their own `to_dict`).
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

### `glass_blur(source, blur_radius=10, opacity=0.1, tint=None)`

Glassmorphism backdrop blur — mirrors EyesOfAzrael's `--glass-bg` /
`--glass-blur` CSS contract. *source* is the underlying viewport region
(an ``(H, W, 4)`` uint8 RGBA ndarray); a separable Gaussian blur of
standard deviation `blur_radius` is applied, then a translucent white
(or `tint`) overlay at `opacity` is alpha-composited on top. Returns
the composited ndarray at the same dimensions as *source*. Pure numpy;
no GPU dispatch.

### `frosted_panel(width, height, blur_radius=10, opacity=0.1, border_color=None)`

Standalone frosted-glass panel texture — no backdrop required. Builds
the frosted look from blurred chroma noise under a translucent white
overlay so a panel can sit anywhere without an underlying viewport
sample. `border_color` optionally strokes a 1-pixel border around the
panel for a window-chrome look.

### `dot_grid(width, height, dot_color, dot_radius=1, spacing=8, bg_color=None)`

Bullet-journal style dot pattern. Dots are placed on a regular
``spacing`` × ``spacing`` lattice; for a canvas whose dimensions divide
evenly by `spacing` the total dot count is exactly ``(width/spacing) *
(height/spacing)``. `bg_color` defaults to fully transparent so the
pattern overlays cleanly on top of `parchment` or `ruled_paper`.

### `parchment(width, height, base_color, edge_dark=0.85, noise_amount=0.05)`

Cozy-diary parchment background. Fills the canvas with `base_color`,
darkens the four corners through a radial vignette by the multiplier
`edge_dark`, and adds light per-pixel noise of strength `noise_amount`
so the surface reads as paper rather than flat fill.

### `watercolor_wash(width, height, color_palette, wash_count=3, opacity=0.3, seed=314159)`

Scrapbook-summer style soft watercolor washes. Draws `wash_count`
soft-edged elliptical splats sampled from `color_palette`, each at the
given `opacity`, and blends them additively over a transparent canvas.
`seed` makes the pattern reproducible across runs.

## Starter themes

The first concrete theme content built on the primitives ships in the
`slappyengine.ui.theme.themes` subpackage. Three `ThemeSpec` constants
demonstrate the diary-family contract documented under
[`docs/theme_diary_family_2026_06_03.md`](../theme_diary_family_2026_06_03.md)
and the base brief at
[`docs/theme_teengirl_notebook_2026_06_03.md`](../theme_teengirl_notebook_2026_06_03.md).

```python
from slappyengine.ui.theme import apply_theme
from slappyengine.ui.theme.themes import (
    BULLET_JOURNAL, COZY_DIARY, TEENGIRL_NOTEBOOK,
    register_starter_themes,
)

register_starter_themes()
apply_theme("teengirl_notebook")
```

| Constant | Theme name | Source file | Vibe | Background shader | Roster |
|---|---|---|---|---|---|
| `TEENGIRL_NOTEBOOK` | `teengirl_notebook` | `python/slappyengine/ui/theme/themes/teengirl_notebook.py` | Lined-paper + washi tape, bubblegum-pink + lilac | `ruled_paper` (lilac rules, pink margin) | `fox_01`, `butterfly_01` |
| `COZY_DIARY` | `cozy_diary` | `python/slappyengine/ui/theme/themes/cozy_diary.py` | Warm autumn / leather-journal, sepia ink | `ruled_paper` parametrised as parchment | `red_panda_01`, `fox_01`, `leaf_01` |
| `BULLET_JOURNAL` | `bullet_journal` | `python/slappyengine/ui/theme/themes/bullet_journal.py` | Minimal grid + pastel highlights, no script | `dot_grid` (1 px every 8 px) | `hedgehog_01`, `porcupine_01` |

Each constant carries a full `SemanticTokens` block plus a populated
`palette`, `fonts`, `nine_slices` (procedural — no PNGs), `icons`
(three inline SVGs ≤ 500 bytes each), `background_shader`, and a
`metadata` bag that records the creature roster, seasonal flavour, tape
colour, variant, and source-doc backlink. YAML round-trip works
out-of-the-box.

`register_starter_themes()` is a convenience helper that calls
`register_theme()` for each constant in one shot; it returns the list
of registered theme names so callers can chain a follow-up
`apply_theme(name)`.

YAML location: each theme serialises through `ThemeSpec.to_yaml()`
without on-disk content. The source-of-truth Python files live under
`python/slappyengine/ui/theme/themes/` per the table above; users who
want YAML can dump on demand:

```python
from pathlib import Path
from slappyengine.ui.theme.themes import TEENGIRL_NOTEBOOK
Path("teengirl_notebook.yml").write_text(TEENGIRL_NOTEBOOK.to_yaml())
```

## Inner modules

- `slappyengine.ui.theme.theme_spec` — `Color`, `Font`, `Gradient`,
  `Palette`, `SemanticTokens`, `SpacingScale`, `RadiusScale`,
  `TransitionScale`, `ZIndexScale`, `ShaderEffect`, `ThemeSpec`
  dataclasses + YAML round-trip.
- `slappyengine.ui.theme.nine_slice` — image-backed +
  procedural nine-slice renderer.
- `slappyengine.ui.theme.svg_icon` — SVG parser, rasteriser,
  DPG texture bridge, module-global rasterised-texture cache.
- `slappyengine.ui.theme.shader_effects` — pure-numpy procedural
  texture helpers (`ruled_paper`, `highlighter_stroke`,
  `paper_shadow`, `noise_glitter`, `glass_blur`, `frosted_panel`,
  `dot_grid`, `parchment`, `watercolor_wash`).
- `slappyengine.ui.theme.themes` — three starter `ThemeSpec` constants
  (`TEENGIRL_NOTEBOOK`, `COZY_DIARY`, `BULLET_JOURNAL`) +
  `register_starter_themes()`.

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

## Creatures

The optional `slappyengine.ui.theme.creatures` subpackage layers the
**woodland-creature animation system** on top of the primitives above.
A theme may register zero or more `Creature` records and the
`CreatureScheduler` drives their per-frame state machine — idle
animations cooled-down between firings, trigger animations played on
explicit calls, a master `set_enabled(False)` switch that turns the
whole layer off, and a reduced-motion mode that limits idle activity
to `blink` curves only.

The subsystem carries **no DPG hard dependency**. Render fns receive an
opaque ``draw_list`` parameter; production wires it to a Dear PyGui
drawlist handle, the test suite passes a recording mock.

### Public surface

```python
from slappyengine.ui.theme.creatures import (
    AnimationCurve, Keyframe,
    Creature, DrawList, RenderFn,
    CreatureScheduler,
    SlotPolicy, SlotRegion,
    # module-level singleton wrappers
    register_creature, trigger, tick, set_enabled, set_reduced_motion,
)
from slappyengine.ui.theme.creatures.builtin import (
    register_builtins,
    fox_01, fox_01_slot,
    butterfly_01, butterfly_01_slot,
    sparkle, sparkle_slot,
)
```

`__all__` is alphabetised.

### `AnimationCurve` + `Keyframe`

Keyframe-driven scalar curves over a fixed wall-clock duration.

```python
@dataclass(frozen=True)
class Keyframe:
    t: float       # normalised time in [0, 1]
    value: float

@dataclass
class AnimationCurve:
    keyframes: list[Keyframe]
    duration_s: float
    loop: bool = False

    def sample(self, t: float) -> float    # linear interp; clamps at edges
    def is_done(self, t: float) -> bool    # True once t >= duration_s
```

Keyframes are sorted on construction so callers may author in any
order. `sample` runs in O(log n) via `bisect_right`. Looping curves
wrap `t` modulo `duration_s` and `is_done` always returns `False`.

### `SlotPolicy` + `SlotRegion`

Where a creature lives and how often it may animate.

```python
@dataclass(frozen=True)
class SlotRegion:
    x: int; y: int        # top-left in DPG screen-space pixels
    w: int; h: int        # size in pixels
    parent_panel: str | None = None

@dataclass
class SlotPolicy:
    region: SlotRegion
    idle_cooldown_s: tuple[float, float] = (3.0, 7.0)  # (min, max)
    max_concurrent: int = 1            # max overlapping trigger anims
    reduced_motion_idle_ok: bool = True
```

`max_concurrent` enforces the §3.3 contract from the design spec: extra
trigger calls **drop** (not queue) and increment
`CreatureScheduler.dropped_trigger_count`.

### `Creature`

Declarative cast member — pure data, no rendering state.

```python
@dataclass
class Creature:
    id: str
    render_fn: Callable[[DrawList, int, int, float], None]
    idle_animations: dict[str, AnimationCurve]
    trigger_animations: dict[str, AnimationCurve]
    personality_color: Color
    budget_ms: float = 1.0
    metadata: dict[str, str] = field(default_factory=dict)
```

The render-fn signature is `(draw_list, x, y, anim_t) -> None` where
`anim_t` is the normalised phase in `[0, 1]`.

### `CreatureScheduler`

Owns the active set, drives cooldowns, dispatches to render fns.

| Method | Purpose |
|---|---|
| `register(creature, slot)` | Add a creature under its `id`. Raises if `id` is already registered. |
| `unregister(creature_id)` | Remove a creature. Unknown ids are silently ignored. |
| `tick(dt)` | Advance state by `dt` seconds. No-op when disabled. |
| `trigger(creature_id, anim_name) -> bool` | Fire a one-shot. Returns `False` and drops on slot saturation. |
| `render(draw_list)` | Call every registered creature's render fn. |
| `set_enabled(enabled)` | Master switch — `False` makes `tick`/`trigger`/`render` no-ops. |
| `set_reduced_motion(reduced)` | When `True`, only `blink` idle animations may fire; trigger anims play with phase pinned at `1.0`. |

Diagnostic properties: `active_count`, `total_budget_ms`,
`registered_ids`, `dropped_trigger_count`, `is_enabled`,
`is_reduced_motion`.

### Module-level wrappers

`register_creature`, `trigger`, `tick`, `set_enabled`, and
`set_reduced_motion` operate on a lazily-created module-level singleton
— convenient for the editor host that owns exactly one scheduler.
Tests use `CreatureScheduler` directly.

### Built-in roster

The `creatures.builtin` subpackage ships three first-class definitions:

| Creature | Personality colour | Render strategy | Idle / trigger animations |
|---|---|---|---|
| `fox_01` | `#E5853B` warm orange | procedural ellipses + `noise_glitter` fur swatch | blink / stretch / yawn — wake_up |
| `butterfly_01` | `#FF6FB5` bubblegum pink | inline SVG wings + body | wing_idle (looped) — flutter / land |
| `sparkle` | `#FFF0C8` lemon-cream | 4-point star SVG + sparkle shader swatch | twinkle (looped) — _(decoration only)_ |

`register_builtins(scheduler)` wires all three onto a scheduler in one
call. Each `*_slot()` returns a default `SlotPolicy` matched to the
catalog's slot-assignment table (toolbar / status bar / panel corner).

## Event bindings

The `slappyengine.ui.theme.creatures` subpackage wires engine events to
woodland-creature animations. The integration is opt-in — instantiate
:class:`CreatureBusAdapter` against a scheduler + bus, call
:meth:`install`, and engine events start lighting up creatures.

### Public surface

```python
from slappyengine.ui.theme.creatures import (
    CreatureBusAdapter,
    EVENT_TO_CREATURE_ANIMS,
    IdleEventEmitter,
)
```

### `EVENT_TO_CREATURE_ANIMS`

Declarative `dict[str, list[tuple[str, str]]]` mapping each engine event
type to a list of `(creature_id, anim_name)` pairs. Source-of-truth for
the binding set — adding an entry here extends the roster without
touching adapter code. Keys correspond 1:1 to
[`idle_animation_system_2026_06_03.md`](../idle_animation_system_2026_06_03.md)
§2. Highlights:

| Event | Bindings |
|---|---|
| `engine.save` | `butterfly_01.flutter` |
| `engine.build_success` | `bee_01.dive`, `acorn_01.confetti` |
| `engine.build_failure` | `owl_01.hoot` |
| `engine.error` | `owl_01.hoot`, `porcupine_01.ball_up` |
| `engine.scene_loaded` / `engine.scene_closed` | `deer_01.peek_in` / `deer_01.peek_out` |
| `engine.test_pass` | `acorn_01.drop` |
| `engine.idle_60s` / `engine.idle_120s` | `fox_01.stretch` / `frog_01.hop` |
| `engine.first_run` | `rabbit_01.spawn`, `butterfly_01.flutter` |
| `engine.progress_start` / `engine.progress_end` | `rabbit_01.run` / `rabbit_01.sit` |
| `engine.loading_start` / `engine.loading_cancel` | `snail_01.crawl` / `snail_01.hide` |
| `ui.scene_outliner.select_root` | `flower_01.bloom` |
| `ui.code_mode.bookmark_add` | `pinecone_01.drop` |
| `ui.click_on_mushroom_decoration` | `mushroom_01.spore_puff` |

### `CreatureBusAdapter`

```python
CreatureBusAdapter(scheduler, bus, *, debounce_ms=500.0)
```

Subscribes a `CreatureScheduler` (or any object exposing
`trigger(creature_id, anim_name)`) to every key in
`EVENT_TO_CREATURE_ANIMS`.

- `install()` — subscribe to every event type (idempotent).
- `uninstall()` — drop every subscription and reset debounce state.
- `trigger_for_event(event_name) -> int` — manually fire the bindings
  for *event_name*; returns the number of animations actually fired
  (debounce filters are subtracted).
- `installed` / `subscribed_events` — introspection accessors.

Tolerant by design:

- Missing creatures (`KeyError` / `LookupError` from `scheduler.trigger`)
  log at `WARNING` and continue.
- Same `(event, creature_id, anim)` binding cannot refire within
  `debounce_ms` (default 500 ms).
- The bus already swallows handler exceptions; the adapter additionally
  logs at `ERROR` with the traceback for any non-lookup exception.

### `IdleEventEmitter`

```python
IdleEventEmitter(bus, intervals=[("engine.idle_60s", 60.0),
                                 ("engine.idle_120s", 120.0)])
```

Publishes synthetic idle-pulse events when the user has been inactive
long enough. The editor host calls `tick(dt)` each frame and
`reset_activity()` on any real user input. Each threshold publishes
exactly once per idle window — calling `reset_activity()` reopens every
window.

Accessors: `idle_seconds` (current accumulator), `has_fired(event)`
(per-window flag).

## Design provenance

The semantic-token layer (`SemanticTokens`) and the four design-system
scales (`SpacingScale`, `RadiusScale`, `TransitionScale`, `ZIndexScale`)
are direct ports of the architecture in the **EyesOfAzrael** project's
`css/firebase-themes.css`. That stylesheet treats raw palette hex
colours as *implementation* and a stable named token surface
(`--theme-primary`, `--glass-bg`, `--radius-md`, `--transition-fast` …)
as the *contract* every component renders against. Hot-swapping a
theme is therefore a single rebind of the token surface rather than a
search-and-replace through widget code.

SlapPyEngine adopts the same split:

| EyesOfAzrael CSS | SlapPyEngine equivalent |
|---|---|
| `--theme-primary`, `--theme-gradient` | `SemanticTokens.primary`, `SemanticTokens.primary_gradient` |
| `--glass-bg`, `--glass-blur` | `SemanticTokens.glass_bg`, `SemanticTokens.glass_blur_px` |
| `--spacing-{xs,sm,md,lg,xl,2xl}` | `SpacingScale.{xs,sm,md,lg,xl,xxl}` |
| `--radius-{sm,md,lg,xl}` | `RadiusScale.{sm,md,lg,xl}` + `pill` |
| `--transition-{fast,normal,slow}` | `TransitionScale.{fast,normal,slow}` |
| `--z-{base,dropdown,modal,toast}` | `ZIndexScale.{base,dropdown,modal,toast}` |
| `[data-theme="X"] { --theme-primary: … }` overrides | `register_theme(ThemeSpec(...))` + `apply_theme("X")` |

The `Gradient` primitive maps to CSS `linear-gradient(135deg, …)` and
its `sample(t)` helper produces the same per-channel sRGB
interpolation a browser performs when shading the gradient. The
`135°` default is deliberately the EyesOfAzrael convention so themes
ported in either direction line up without manual angle conversion.

## See also

- [`ui_editor.md`](ui_editor.md) — the optional Dear PyGui editor
  shell that ultimately consumes these primitives.
- [`material.md`](material.md) — for material *graph* theming inside
  the editor; unrelated to UI chrome theming.
- [`../idle_animation_system_2026_06_03.md`](../idle_animation_system_2026_06_03.md) —
  full design spec for the woodland-creature subsystem (this section
  documents only the event-bus seam).
