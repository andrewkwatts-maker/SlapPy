# Notebook Editor — User Manual

*A warm, friendly tour of the diary-themed SlapPyEngine editor.*

Welcome! Pull up a chair, brew a cup of something, and crack the spine of
your favourite notebook. This is the user-facing guide to the SlapPyEngine
"Notebook" editor — the diary-flavoured re-skin of the Nova3D shell that
lives under `python/pharos_engine/ui/editor/`. Every panel below is a
real, shipping module; every keybinding works in the current build; every
creature you meet has its own little spec under
`python/pharos_engine/ui/theme/creatures/builtin/`.

If you want the design rationale behind the look, see
[`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md)
and [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md).
If you want the technical contract for the panels, see
[`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md). This
file is for everyone else — the person opening the editor for the first
time who just wants to know *where the buttons are* and *why there's a
fox in the corner*.

> **TL;DR** — six themes, a friendly toolbar of four rubber-stamp tools,
> a bestiary-style scene outliner, a field-journal property inspector, a
> deck of trading-card spawn options, and a small cast of woodland
> creatures who occasionally amble across the screen. Press `H` for
> hotkeys, `Ctrl+Shift+F` if you want to feed the fox.

---

## 1. What the notebook editor *is*

The notebook editor is a presentation reskin of the engine's Nova3D
editor shell. Underneath the washi tape and pressed-flower badges it is
still a working Dear PyGui editor — same scene reflection, same property
inspector dispatch, same JSON serialisation, same hot-reload story —
but the chrome reads as the inside of a teenager's diary instead of a
DCC tool from 2009.

It exists for three reasons:

1. **Approachability.** A toolbar of *rubber stamps* and a sidebar
   that calls your rope a *filum* lowers the activation energy for
   someone who has never opened a game engine before.
2. **Author identity.** Anyone who has used Unity / Unreal / Godot has
   stared at the same grey dock layout for a decade. The notebook
   editor lets us look like *us*.
3. **Theming as a feature.** Six diary variants ship in the box and
   the `ThemeSpec` contract makes adding a seventh a 200-line file.

Nothing is *only* visual. Every notebook panel implements the same
`build(parent_tag)` contract that the Nova3D originals do, so a host
shell can mix and match — you can run the notebook outliner alongside
the Nova3D inspector if your taste runs that way.

---

## 2. First-launch

The very first time you launch the editor on a fresh checkout, the
**Welcome screen** opens centred over the workspace as a modal "front
cover":

* A hand-drawn diary cover header reading *"Welcome — let's draw!"*.
* Three **sticker demo cards** down the centre:
  * the fox card opens `hello_ragdoll.py`,
  * the bunny card opens `hello_rope.py`,
  * the butterfly card opens `hello_studio.py`.
* A pink **"Start drawing!"** sticker button that opens a blank scene.
* A row of six 32×32 px **theme swatches** along the bottom. Click one
  to apply that theme and close the welcome in one move.
* A small heart checkbox in the corner labelled *"Show this next time"*.
  Untick it and the welcome won't auto-open again — open it any time
  from **Help → Welcome**.

A `CreatureScheduler` sparkle drifts across the header on a 4-second
loop while the modal is open. If you'd rather it didn't, see
**§9 Accessibility**.

The welcome is implemented by
`pharos_engine.ui.editor.notebook_welcome.NotebookWelcome`. It is
headless-safe — running the editor in CI builds it but never paints it.

### Picking a theme on first launch

The six swatches map left-to-right onto the same six `ThemeSpec`
constants exported from `pharos_engine.ui.theme.themes`:

| # | Swatch tone | Theme name | Vibe |
|---|---|---|---|
| 1 | Bubblegum pink | `teengirl_notebook` | Lined paper + washi tape + sparkles |
| 2 | Caramel rose | `cozy_diary` | Autumn leather journal, sepia ink |
| 3 | Slate dot-grid | `bullet_journal` | Minimalist bullet-point planner |
| 4 | Sun-yellow tape | `scrapbook_summer` | Photo-corners + film grain |
| 5 | Mossy sage | `cottagecore_garden` | Wildflower press, woodland palette |
| 6 | Coral pastel | `kawaii_planner` | Sticker-density: maximal |

Any choice is a one-line undo — open **Theme Switcher** later and pick
again.

---

## 3. Editor tour, panel by panel

Each subsection here corresponds to a real module under
`python/pharos_engine/ui/editor/`. Cross-references point at the module
so you can dig into the source if a screenshot leaves you curious.

### 3.1 Toolbar — the stationery tray

*Module: `notebook_toolbar.NotebookToolbar`*

The toolbar sits along the top of the editor window styled as a
**stationery tray with rubber stamps**. There are four tools, each
rendered as a 96 × 36 sticker button:

| Stamp icon | Tool | Shortcut |
|---|---|---|
| Heart-with-arrow | **Select** | `S` |
| Four-arrow flower | **Move** | `T` |
| Spiral | **Rotate** | `R` |
| Bow-tie | **Scale** | `C` |

The currently active tool is underlined with a 2-pixel **washi-tape
strip** in the active theme's accent colour. The strip is baked through
`NineSlice.render_procedural` so swapping themes recolours it
instantly — no texture reload, no flicker.

At the right edge of the toolbar there is a reserved **32 × 32
creature slot** anchored at `parent_panel="notebook_toolbar"`. The
default theme drops `fox_01` into that slot; you'll catch the fox
napping there between actions and stretching whenever you switch
tools. (See **§5 Creatures**.)

Mouse over any stamp to see a tooltip in the active theme's body font
(`Quicksand` by default).

### 3.2 Scene Outliner — the bestiary

*Module: `notebook_outliner.NotebookOutliner`*

The scene outliner reskins the entity hierarchy as a **field-journal
bestiary**. Each entity becomes a row that looks like a notebook entry:

* A small **type badge** on the left — a hand-drawn icon picked from
  an entity-kind → SVG library (fox face for `body`, daisy for
  `camera`, pressed leaf for `mesh`, dashed rectangle for `zone`, …).
* The entity name rendered as a handwritten label.
* A **heart-shaped visibility toggle** (`<3` becomes a filled heart in
  the rasterised path).
* A tiny **key-shaped lock toggle** beside the heart.

Sections are separated by **doodled wavy / dotted dividers**, and the
very first top-level entry gets a **sparkle sticker** pinned to its
upper-right corner to mark it as the "primary specimen". The selected
row carries a highlighter-stroke overlay so you always know which page
you're on.

A search box at the top reads *"Search the bestiary…"* with a
washi-tape underline. Type to filter rows by name *or* kind — typing
`light` reveals every light in the scene; typing `vulpes` (the
journal-binomial label for `body`) reveals every body.

**Empty state:** if the scene has no entities yet, the panel says
*"No entries yet — drop a creature in from the spawn menu"* with a
small fox sticker pinned to the bottom-right.

### 3.3 Property Inspector — the field journal entry

*Module: `notebook_inspector.NotebookInspector`*

When you select an entity, the property inspector flips to that
entity's page. The inspector is the reflection-driven sibling of the
Nova3D `PropertyInspector`, but wrapped in a **washi-tape three-tab
journal page**:

* **Transform** — translate / rotate / scale, drawn as
  `HighlighterSlider` strips. Drag the highlighter band left/right.
* **Properties** — every other primitive field on the entity. Booleans
  become `HeartCheckbox` hearts; strings become input fields with a
  washi-tape underline; colours get a sticker preview swatch; nested
  dataclasses recurse into a sub-panel.
* **References** — anything that *isn't* a primitive (engine objects,
  Python `Path`, complex lists). Each reference renders as a `[?]`
  pill button that, on click, jumps the inspector to that target.

Sections are divided by a `DoodleSeparator` — a wavy hand-drawn
underline. Each section is wrapped in a `WashiPanel` so you can see
"three pages taped together" rather than three flat frames.

If nothing is selected, the empty-state hint reads:
*"Pick a critter to view its journal entry"*.

### 3.4 Gizmo Overlay — coloured-pencil handles

*Module: `notebook_gizmos.NotebookGizmoOverlay`*

The transform gizmos that appear in the viewport when you select an
entity are reskinned as **hand-drawn coloured-pencil doodles**:

* **Translate** — red and blue pencil strokes with a mild wobble,
  finished with tiny hand-drawn arrowheads. The centre is a heart.
* **Rotate** — a dashed pencil ring in the active theme's accent
  colour, sparkle tick marks every 30°, and a highlighter sweep from
  centre out to the current angle.
* **Scale** — four corner *bow-tie* brackets matching the toolbar
  Scale icon and a heart pulse at the centre while you drag.

Wobble is **deterministic** — the perlin-ish offset is hashed from
`(target_pos, mode, axis_index)` so the same gizmo at the same
position always doodles the same way. Tests pin the wobble exactly.

### 3.5 Theme Switcher — the diary picker

*Module: `theme_switcher_panel.ThemeSwitcherPanel`*

Open the theme switcher from the right sidebar (or **View → Theme**)
to swap the active diary variant live. The panel has seven sections,
top to bottom:

1. **Header** — *"Theme"* label and the active theme's name.
2. **Theme cards grid** — 2 × 3 cards. Each card shows a three-stripe
   palette preview (primary / accent / surface), the theme name, and a
   sticker icon hint. Click a card to apply that theme.
3. **Doodle separator.**
4. **Creature roster** — one `HeartCheckbox` per creature listed in
   the active theme's `metadata["creature_roster"]`. Untick to
   disable a creature for this session.
5. **Doodle separator.**
6. **Global toggles** — *Animations master switch*, *Reduced motion*,
   *Easter eggs*.
7. **Footer** — a *"Refresh editor"* `StickerButton` that re-mounts
   every panel against the new theme.

Switching themes is instant and lossless — your scene state, undo
stack, selection, and Code Mode buffer all survive.

### 3.6 Code Mode — the diary page with a bookmark ribbon

*Module: `code_mode_panel.CodeModePanel` + `notebook_code_panel.NotebookCodePanel`*

Code Mode is the editor's split prompt/code authoring view. The
notebook variant decorates it as a **diary page with a bookmark
ribbon**:

* The **left pane** is a prompt field with a *"Dear diary…"*
  placeholder. Write what you want the script to do in plain English.
* The **right pane** is the generated Python with a
  `Caveat`-handwritten header and a code-mono body.
* A **velvet bookmark ribbon** runs down the right edge — drag it up
  or down to scrub through prior revisions.
* If Ollama is installed and reachable, edits to one pane reconcile
  the other in the background. If it isn't, the panel still works as a
  plain editor — there is a small *"AI sleeping — tap to wake"* hint
  at the bottom.

The `OllamaSetupModal` pops the first time you enable AI sync. It's a
single-step wizard that probes a local instance and offers to
download the recommended model.

### 3.7 Spawn Menu — the trading-card deck

*Module: `notebook_spawn_menu.NotebookSpawnMenu`*

Click **`+ Add`** in the scene outliner to open the spawn menu. It
renders as a **fanned trading-card deck** — every spawn action is a
card showing:

* The action's headline (e.g. *"Drop a rope"*, *"Drop a softbody
  lattice"*, *"Drop a humanoid"*).
* A small badge SVG matching the entity kind.
* The card's "rarity stripe" — common for primitives (body, mesh),
  rare for compound entities (humanoid, ragdoll), legendary for the
  experimental ones.

Click a card to expand its spec — every dataclass field on the
underlying factory becomes a `HighlighterSlider` / `HeartCheckbox` /
input-text row via the same reflection dispatch the property
inspector uses. *Spawn!* commits.

### 3.8 Material Editor — the colour-story page

*Module: `notebook_material_editor.NotebookMaterialEditor`*

The material editor opens as a **colour-story page**: a vertical
strip of swatches on the left, the material's parameter sliders on
the right, and a live preview tile at the top. Three node kinds are
supported:

* `MaterialMap` — pick a row, edit a swatch.
* `softbody.Material` — dataclass reflection through
  `HighlighterSlider` strips.
* `fluid.FluidMaterial` — same shape, fluid palette.

A small daisy badge in the corner marks materials that have unsaved
changes.

### 3.9 Welcome screen — already covered (§2)

Skipping; see **§2 First-launch**.

### 3.10 Status Bar — the marginalia row

*Module: `notebook_status_bar.NotebookStatusBar`*

A single ~24 px row pinned to the bottom of the editor, styled as a
notebook's marginalia row with a thin washi-tape divider above and
below.

Contents left → right:

* Active tool name (e.g. *"Move tool"*).
* Selection count (*"1 selected"*).
* World cursor coordinates.
* Frames-per-second readout.
* A transient *"heart saved"* sticker that blooms for ~2 s after a
  save, or a tiny ✱ exclamation if the save failed.
* A theme-indicator sticker on the right edge — click it to open the
  theme switcher.

---

## 4. Themes

Six diary variants ship in the box. They share one runtime contract
(palette + fonts + nine-slices + icons + `ShaderEffect` background +
semantic tokens) so a switch is loss-free.

| Theme | Vibe | Default creature roster |
|---|---|---|
| `teengirl_notebook` | Lined paper, bubblegum pink + mint, washi tape | `fox_01`, `butterfly_01` |
| `cozy_diary` | Autumn leather journal, sepia ink, dusty rose | `red_panda_01`, `fox_01`, `leaf_01` |
| `bullet_journal` | Slate dot-grid, minimalist, single-accent | `hedgehog_01`, `porcupine_01` |
| `scrapbook_summer` | Photo corners, film grain, sun yellow | `golden_01`, `butterfly_01`, `bee_01` |
| `cottagecore_garden` | Wildflower press, mossy sage palette | `rabbit_01`, `deer_01`, `mushroom_01`, `flower_01` |
| `kawaii_planner` | Sticker-density maximal, coral pastels | `cat_01`, `panda_01`, `porcupine_01` |

Each theme's source-of-truth lives at
`python/pharos_engine/ui/theme/themes/<name>.py`.

---

## 5. Creatures

Twelve woodland-and-domestic-pet creatures ship under
`python/pharos_engine/ui/theme/creatures/builtin/`. Each is a small
declarative `Creature` dataclass: an id, a render fn, a table of named
animations, a personality colour, and a CPU-budget hint.

What they do:

* **Idle.** A creature drifts gently in the slot region its theme
  pinned it to (the toolbar fox-slot, the empty-state outliner sticker,
  the welcome-cover sparkle). Idle motion is sub-1ms per frame and
  capped by the `SlotPolicy` cooldown.
* **React.** Engine events fire animations. Selecting an entity
  startles the toolbar fox; saving the scene makes the bee dance;
  spawning a ragdoll triggers a butterfly waft. The full table is
  `EVENT_TO_CREATURE_ANIMS` under
  `pharos_engine.ui.theme.creatures.event_bindings`.
* **Sleep.** After 60s of user-inactivity the scheduler emits
  `engine.idle_60s` and creatures fall into their "nap" animation. At
  120s they sleep deeper.

**Disabling a creature.** Three ways:

1. Untick its `HeartCheckbox` in the Theme Switcher panel — disables
   for the current session.
2. Toggle the master *Animations* switch in the Theme Switcher to
   disable every creature engine-wide.
3. Programmatically: `pharos_engine.ui.theme.creatures.set_enabled(
   "fox_01", False)`.

Performance budget: **≤ 1 ms idle / ≤ 5 ms one-shot** per scheduler
tick across the whole cast, asserted by the scheduler tests.

Full creature catalogue:
[`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md).

---

## 6. Hotkeys

| Key | Action |
|---|---|
| `S` | Select tool |
| `T` | Move tool |
| `R` | Rotate tool |
| `C` | Scale tool |
| `Ctrl+S` | Save scene |
| `Ctrl+Shift+S` | Save scene as… |
| `Ctrl+O` | Open scene |
| `Ctrl+N` | New scene |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `Ctrl+D` | Duplicate selection |
| `Delete` / `Backspace` | Delete selection |
| `F` | Frame selection in viewport |
| `H` | Hotkey cheat sheet |
| `Ctrl+E` | Toggle Code Mode |
| `Ctrl+T` | Toggle Theme Switcher |
| `Ctrl+B` | Toggle scene outliner (Bestiary) |
| `Ctrl+I` | Toggle property inspector |
| `Ctrl+M` | Toggle material editor |
| `Ctrl+Shift+W` | Re-open Welcome |
| `Ctrl+Shift+F` | Feed the fox (Easter egg, see §7) |
| `Ctrl+Shift+B` | Bounce the butterfly (Easter egg) |
| `Esc` | Cancel current drag / close modal |

Shortcut routing lives in the editor shell — every panel exposes a
`handle_shortcut(key)` method that returns `True` on hit so the shell
can chain handlers cleanly.

---

## 7. Easter eggs

A small collection of "found in the margins" surprises:

* **`Ctrl+Shift+F`** — *Feed the fox.* A tiny acorn glyph floats over
  to the fox slot; the fox eats it and stretches. One-shot, cooldown
  10s.
* **`Ctrl+Shift+B`** — *Bounce the butterfly.* The cover sparkle is
  briefly replaced by a butterfly that wafts across the whole editor.
* **Triple-click the theme indicator** in the status bar — rolls the
  dice for a random unregistered theme alias. (No, we won't tell you
  what they are.)
* **Type "konami" in the outliner search** — every entity badge
  becomes a tiny crown for 30 seconds.
* **Idle for 5 minutes** — the toolbar fox curls up and goes to sleep
  with a tiny *Zzz* sticker.
* **Save 100 times in one session** — the marginalia row shows
  *"<3 you save a lot"* once, then never again.

You can disable every Easter egg from the Theme Switcher's *Easter
eggs* toggle (it's on by default — they're harmless).

---

## 8. Customising

The notebook editor was designed so that every visible thing is
data-driven. Three customisation paths, in order of effort:

### 8.1 Override widget palettes

Cheapest. Every notebook widget (`StickerButton`, `WashiPanel`,
`NotebookTab`, …) reads from the active `ThemeSpec.palette` and
`ThemeSpec.semantic` dictionaries. To override a single colour without
touching the theme file:

```python
from pharos_engine.ui.theme import apply_theme, get_active_theme, Color

apply_theme("teengirl_notebook")
spec = get_active_theme()
spec.palette["accent"] = Color(0, 180, 255, 1.0)   # cyan accent
# Notify any panel that subscribed to theme changes.
from pharos_engine.ui.widgets.notebook_theme import _notify_theme_listeners
_notify_theme_listeners(spec)
```

Every panel that registered a `theme_listener` will rebuild its colour
caches on the next tick.

### 8.2 Register a new `ThemeSpec`

Copy any file under `python/pharos_engine/ui/theme/themes/` to start
from. Pick a name, fill in a palette + fonts + nine-slice insets +
background `ShaderEffect`, and call `register_theme(my_spec)` once at
startup. The Theme Switcher will pick it up automatically — it reads
from `list_registered_themes()`.

Minimum required:

```python
from pharos_engine.ui.theme import (
    Color, Font, NineSlice, SemanticTokens, ShaderEffect, ThemeSpec,
    register_theme,
)

MY_THEME = ThemeSpec(
    name="my_theme",
    palette={"surface": Color(20, 20, 30, 1.0),
             "primary": Color(100, 200, 255, 1.0),
             "accent":  Color(255, 200, 0, 1.0)},
    fonts={"body": Font(family="Inter", size=14, weight="regular"),
           "header": Font(family="Inter", size=22, weight="600")},
    nine_slices={},
    icons={},
    background_shader=ShaderEffect(kind="ruled_paper", params={}),
    semantic=SemanticTokens(...),
    metadata={"creature_roster": "fox_01"},
)
register_theme(MY_THEME)
```

### 8.3 Register a new creature

Copy one of `python/pharos_engine/ui/theme/creatures/builtin/*.py` to
start from. A creature is a single `Creature` dataclass plus a render
fn — the fn receives `(draw_list, region, t, phase, colour)` and must
draw using only the methods on the `DrawList` protocol so the same fn
works under DPG, PIL, or the test mock.

```python
from pharos_engine.ui.theme.creatures import (
    Creature, register_creature, SlotPolicy, SlotRegion,
)

def render_my_owl(draw_list, region, t, phase, colour):
    # … paint an owl …
    pass

OWL = Creature(
    id="owl_01",
    render_fn=render_my_owl,
    animations={"idle": ..., "blink": ...},
    personality_colour=(80, 60, 30, 255),
    cpu_budget_ms=0.5,
)

policy = SlotPolicy(prefers_slot="toolbar_idle", cooldown_s=5.0)
slot = SlotRegion(x=0, y=0, w=32, h=32, parent_panel="notebook_toolbar")
register_creature(OWL, policy, slot)
```

Add `owl_01` to the `metadata["creature_roster"]` string of any theme
that should ship it by default.

---

## 9. Accessibility

The notebook aesthetic leans on motion and hand-drawn wobble. Two
master switches let you opt out:

* **Reduced motion.** Theme Switcher → *Reduced motion*. Disables every
  creature animation, the welcome-screen sparkle drift, the gizmo
  wobble, and the highlighter-slider drag bounce. The editor still
  looks like a notebook; it just sits perfectly still.
* **Animations master switch.** Theme Switcher → *Animations*. The
  same as reduced motion plus the toolbar's washi-tape transition,
  the marginalia row's save-sticker bloom, and the bookmark-ribbon
  scroll. Everything jumps cut.

Both flags are persisted to `settings.json` via
`UISettings.reduced_motion` / `UISettings.animations_enabled` and are
respected by every panel via the `CreatureScheduler.set_reduced_motion`
+ `set_enabled` module-level helpers.

If you'd like an even quieter editor, set `UISettings.easter_eggs =
False` and untick every creature in the roster. The notebook will
read as a still life — paper, tape, ink, and the panels you put on
the page.

---

## See also

* [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md) — design family rollup
* [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) — base theme design doc
* [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md) — full creature catalogue
* [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md) — `CreatureScheduler` spec
* [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) — Nova3D → notebook panel translation map
* [`api/ui_editor.md`](api/ui_editor.md) — programmatic API reference for editor panels
* [`api/ui_theme.md`](api/ui_theme.md) — `ThemeSpec` primitive surface
* [`api/ui_widgets.md`](api/ui_widgets.md) — notebook widget primitives
