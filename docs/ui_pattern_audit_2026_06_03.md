# UI Pattern Audit — Nova3D → Woodland/Notebook (2026-06-03)

A formal contract audit of every panel under
`python/pharos_engine/ui/editor/` plus a translation map from the current
Nova3D-derived dark-glassmorphism theme to the proposed playful
woodland/notebook overhaul. Read-only audit; no source edits accompany
this document.

Audit scope: 10 modules (one removed — `deform_panel.py` raises
ImportError per Phase D step 6).

---

## 1. Per-panel contracts

### 1.1 `theme.py` — Glassmorphism theme application

**Responsibility.** Single entry point (`apply_editor_theme`) that
binds a `dpg.theme()` to the global DPG context. Defines the entire
colour palette as module-level constants and exposes three reusable
per-item themes: accent button, default button, opaque viewport.
Also wraps the Windows DWM Acrylic blur-behind FFI
(`apply_dwm_glass`).

**Owned state.** Two cached per-item theme handles
(`_accent_button_theme`, `_viewport_opaque_theme`). All palette
constants are module-level and immutable at import time.

**Engine reads.** None — theme is pure presentation.

**Events published.** None.

**Keyboard shortcuts.** None.

**Layout / size policy.** Sets global style vars:
`WindowRounding=14`, `ChildRounding=12`, `FrameRounding=8`,
`TabRounding=10`, `FramePadding=(6,4)`, `ItemSpacing=(8,5)`,
`WindowPadding=(10,10)`. Window and child backgrounds use alpha
(200/180) for glassmorphism layering against the DWM Acrylic blur.

**Woodland/notebook translation.** Replace `_GLASS_*` palette with
`_PAPER_*`: warm off-white (245, 240, 225), pencil-grey ink
(60, 55, 50), forest accent (95, 130, 85), berry accent (165, 85, 100).
Drop alpha-blend (no DWM glass) — paper is opaque. Rounding values
stay (rounded corners read as "notebook corner radius" rather than
"frosted glass"). Add a subtle paper-grain texture as a per-window
backdrop image (sample <1KB tiled PNG). `apply_dwm_glass` becomes a
no-op stub but kept for API parity.

---

### 1.2 `toolbar.py` — Select / Move / Rotate / Scale tool group

**Responsibility.** Horizontal strip with four tool buttons
(Select / Translate / Rotate / Scale), a snap-toggle, and a 2D/3D
mode toggle. Manages "exactly one tool active" state via per-item
accent theme.

**Owned state.** `active_tool` (str), `snap_enabled` (bool),
`_mode` (`"2D"` / `"3D"`), four cached theme handles, button-tag
dict.

**Engine reads.** None.

**Events published.** Two callbacks: `_on_tool_change(tool)` and
`_on_mode_change(mode)`. Not yet wired through `event_bus`; today
the shell hooks them directly.

**Keyboard shortcuts.** Button prefixes hint `[S]`, `[T]`, `[R]`,
`[Sc]` — actual keypress handling lives in `shell.run()` (none of
these four are bound today; this is a tracked gap).

**Layout / size policy.** Button size `80×28 px`, snap button
`90×28`, mode toggles `40×28`. Active tool gets the global accent
theme (`get_accent_button_theme`); inactive buttons restore the
default theme. Snap toggle uses a success-green tint when ON;
mode buttons use a distinct blue tint.

**Woodland/notebook translation.** Tools become "stamps in a
stationery tray": each button frames a tiny PNG of a wax-seal
stamp (arrow / hand / circular-arrow / loupe). The accent
highlight becomes a "pressed ink" effect — a darker outline plus
a barely-visible ink splotch under the active stamp. Snap toggle
becomes a "ruler clip" icon (clipped = snapping on).

---

### 1.3 `scene_outliner.py` — Entity hierarchy + dynamics tree

**Responsibility.** Tree view rendering (a) the flat `scene.entities`
list and (b) a structured `World` → `Bodies` / `Joints` (grouped by
kind) / `Humanoids` tree. Each entity row exposes visibility
checkbox, lock button, name button (selection), and a type badge.
Hosts the `+ Add` popup that opens `spawn_menu` modals.

**Owned state.** `_scene`, `_dynamics_world`, `_selected_entity`,
`_on_select` callback, row/dynamics group tags, accent/default
theme handles.

**Engine reads.** `scene.entities` (list), `world.bodies`,
`world.joints`. Per-entity: `name`, `visible`, `locked`. Per-body:
`kind`, `label`, `parameters["humanoid"]`. Per-joint: `kind`,
`node_a`, `node_b`.

**Events published.** `_on_select(entity_or_ref)`. Mutates
`entity.visible` / `entity.locked` in place; mutates
`scene.entities.remove()` on delete.

**Keyboard shortcuts.** None on the outliner itself; `Delete`
shell-level shortcut calls `_delete_selected` on the outliner.

**Layout / size policy.** Row height `22 px`, name button width
`-120` (fills remaining space minus badge). Joint kind order
fixed: `distance, spring, weld, ball, hinge, motor, prismatic`.

**Woodland/notebook translation.** Tree becomes a "bestiary /
list of pressed flowers": entity name rendered in a serif italic
display font, lock icon is a hand-drawn padlock sketch, visibility
checkbox becomes a tiny eye glyph (open / closed). Joint-kind
sublists become coloured ribbon tabs. Type badge becomes a small
hand-drawn Latin binomial annotation (`[Lattice softbodyensis]`).
Humanoids section gets a "this page reserved for sapiens" cartouche
header.

---

### 1.4 `gizmo_overlay.py` — 2D/3D transform gizmos via viewport drawlist

**Responsibility.** Front-side viewport drawlist that renders
gizmos for the four tool modes plus a 3D-mode axis triad. Performs
hit-testing and applies drag deltas to the bound entity.

**Owned state.** `_entity`, `_camera`, `_tool`, `_vp_w/_vp_h`,
`_dragging` (handle key), `_drag_start_*` (mouse / pos / rot /
scale snapshots), `_mouse`, `_mode_3d` flag.

**Engine reads.** `entity.position`, `.rotation`, `.scale`,
`.size`/`.bounds`. `camera.position`, `.zoom`. Live mouse via
`dpg.get_mouse_pos(local=False)`.

**Events published.** None via bus; mutates entity attrs directly.

**Keyboard shortcuts.** None.

**Layout / size policy.** Handle radii: `HANDLE_RADIUS=8`,
`ARROW_LEN=50`, `ROTATE_RADIUS=45`, `SCALE_HANDLE_SIZE=10`.
Colour table: X=red, Y=green, Z=blue, centre=yellow,
rotate=purple, arc-sweep=amber. 3D mode draws three rings
(X=horizontal ellipse, Y=vertical ellipse, Z=full circle) plus
filled-triangle arrowheads.

**Woodland/notebook translation.** Arrows become "doodled
measurement arrows in coloured pencil" — replace `draw_arrow` with
a custom `draw_pencil_arrow` that overlays two slightly offset
strokes of low alpha (sketch jitter). Rotate ring becomes a
half-finished compass-traced arc. Scale handles become tiny
"corner brackets" like the crop marks on a photo print. Hover
state shows a sketchy underline / arrow callout.

---

### 1.5 `shell.py` — Editor layout + run loop

**Responsibility.** Single primary window with a five-row layout:
custom titlebar / toolbar (`y≈28..59`) / main split / bottom
content browser / status bar. Owns the DPG context lifecycle,
keyboard-shortcut router, custom title-bar drag, and play-mode
toggle.

**Owned state.** Layout constants `TOOLBAR_H=36`, `BOTTOM_H=220`,
`LEFT_W=200`, `RIGHT_W=300`; the panel registry list; sub-component
handles (`_toolbar`, `_scene_outliner`, `_content_browser`,
`_viewport_panel`, `_code_mode_panel`, `_gizmo_overlay`);
`_play_mode` flag; window-drag state.

**Engine reads.** `engine._project_manager.save()` for Ctrl+S;
`engine._undo_manager.undo()` for Ctrl+Z; `engine.scene` for
delete; `engine.run` / `engine.stop` for F5 play-mode.

**Events published.** Wires toolbar tool-change → gizmo,
outliner select → gizmo entity. No bus today.

**Keyboard shortcuts (live).**
`Ctrl+S` save · `Ctrl+Z` undo · `Delete` remove selected ·
`F5` toggle play. Tool-letter shortcuts (S/T/R/Sc) are *not*
yet bound — gap.

**Layout / size policy.** Toolbar strip is the `toolbar_row`
child window at `y = 28 (titlebar) + 0 → 36 px`, ending at
roughly `y=59` after `WindowPadding(10)` — matches the audit
description. Centre tabs are `Viewport` and `Code Mode`. Right
tabs are `Scene` and `Details`.

**Woodland/notebook translation.** Tabs become "notebook
dividers" with hand-cut tab shapes (tabbed binder spine).
Custom titlebar becomes a "marbled-paper" header strip with the
title hand-written. Status bar becomes a "margin note" at the
bottom.

---

### 1.6 `property_inspector.py` — Transform / Properties / References

**Responsibility.** Three-section auto-reflected widget tree for
any Python object: Transform (drag-floats for pos/rot/scale),
Properties (primitive fields with the right widget per type),
References (complex objects rendered as `name: TypeName [?]` with
a popup repr). Includes a dict-of-primitives inline renderer for
`JointSpec.params` and friends.

**Owned state.** `_obj` (current target), `_panel_tag`,
`_widget_map` (attr → DPG tag).

**Engine reads.** `dataclasses.fields(obj)` or `vars(obj)`;
`type(obj).__module__` for "is this an engine object" detection.

**Events published.** Direct attribute writes via
`setattr(self._obj, name, value)`; no bus.

**Keyboard shortcuts.** None.

**Layout / size policy.** Three `collapsing_header`s; Transform
and Properties default-open, References collapsed. Drag widgets
use `speed=0.5`. Float tuple length 4 → `add_color_edit`,
length 3 → `add_input_floatx`, length 2 → drag/input floatx.

**Woodland/notebook translation.** Inspector becomes a "field
journal entry with sketches": each section gets a hand-drawn
section-divider doodle (Transform = compass rose, Properties =
quill, References = magnifying glass). Drag floats become
"slider rulers with tick marks". The `[?]` button becomes a
fountain-pen ink-blot icon; the popup is styled as a torn-edge
note-card.

---

### 1.7 `code_mode_panel.py` — Bidirectional AI prompt↔code sync

**Responsibility.** Split prompt (left, plain English) / code
(right, Python) panel with manual sync buttons (`Prompt → Code`,
`Code → Prompt`) and an `Auto-sync` checkbox. Drives the Ollama
LLM client and a background `CodeSyncWatcher`. Handles the
first-run AI opt-in modal and the model-pull progress modal.

**Owned state.** `_prompt_text`, `_code_text`, `_prompt_mtime`,
`_code_mtime`, `_status`, `_ai_busy`, `_script_path`, `_llm`,
`_watcher`, setup-flow flags (`_pending_setup`, `_setup_running`).

**Engine reads.** `~/.SlapPyEngine/ai_settings.json` via
`load_ai_settings`. Reads the active script `.py` from disk and
the `.prompt` sidecar.

**Events published.** Writes back to disk: `script_path.write_text`
and `prompt_path_for(script_path).write_text`. No bus.

**Keyboard shortcuts.** None (tab-input enabled in the code pane).

**Layout / size policy.** Each pane fixed `530 × 460 px` — minor
hardcoded layout debt flagged in the source comment ("DPG does
not expose parent width at build time"). Toolbar row holds the
two sync buttons + Open File + Auto-sync checkbox.

**Woodland/notebook translation.** Becomes a "diary page with
bookmark ribbon": prompt pane is the left "thoughts" page
(serif italic), code pane is the right "spell" page (monospace).
The sync buttons become ribbon bookmarks (red ribbon for
prompt→code, blue for code→prompt). The auto-sync checkbox
becomes a paperclip glyph. Status line becomes a margin
annotation.

---

### 1.8 `spawn_menu.py` — `+ Add` modal pattern

**Responsibility.** Module-level `SPAWN_ACTIONS` table mapping
labels to (dotted-path factory, spec dataclass). The `open_spawn_modal`
entry point builds a modal containing a fresh `PropertyInspector`
bound to a spec instance plus Spawn / Cancel buttons. On Spawn,
resolves the factory lazily and calls `factory(world, **spec_fields)`.

**Owned state.** None at module level beyond the static action
table. Per-modal: the spec instance and its inspector handle.

**Engine reads.** Lazily imports
`pharos_engine.softbody.body_builders.*`,
`pharos_engine.fluid.world.*`,
`pharos_engine.dynamics.{rope,ragdoll,ik,humanoid}` adapters.

**Events published.** Calls the factory which appends to the
target world; no bus emission.

**Keyboard shortcuts.** None.

**Layout / size policy.** Modal size `360 × 420`. Spawn / Cancel
buttons each `120 px` wide. Inspector child window fills
`width=-1, height=-50`.

**Woodland/notebook translation.** `+ Add` menu becomes a
"trading card deck": each spawn action is a flippable creature
card with a sketched portrait + Latin binomial. The modal becomes
a "summoning circle" — card on the left, parameter inkwell on the
right. Spawn button becomes a wax-seal-press; Cancel becomes a
torn corner.

---

### 1.9 `material_editor.py` — Kind-discriminated material editor

**Responsibility.** Auto-detects whether the target is a
`MaterialMap`, a softbody `Material`, or a fluid `FluidMaterial`,
and dispatches to either (a) the legacy per-`MaterialDef`
collapsing-header layout with R/G/B drag-int min/max, alpha
meaning combo, behaviours list, delete button, or (b) full
dataclass reflection via a reused `PropertyInspector`.

**Owned state.** `_material_map`, `_target`, `_kind` (one of
three constants), `_panel_tag`, `_reflect_inspector` (stashed
nested inspector handle).

**Engine reads.** `target._materials` to discriminate
material-map kind; `type(target).__module__` to discriminate
softbody vs fluid; `mat.color_range.{r,g,b}` tuples;
`mat.alpha_meaning`, `mat.behaviors`.

**Events published.** Mutates `mat.name`, `mat.color_range.*`,
`mat.alpha_meaning`, `mat.behaviors` in place; appends/removes
from `_material_map._materials`.

**Keyboard shortcuts.** None.

**Layout / size policy.** Each `MaterialDef` is one
`collapsing_header`; six `drag_int` rows for RGB min/max, one
`combo` for alpha meaning, one `input_text` for behaviours, one
Delete button. Module-level `Add Material` button.

**Woodland/notebook translation.** Becomes "pigment recipe
cards": each material is an index card with a colour-swatch
square (instead of six drag-ints — show the actual swatch and
let the colour-edit replace the rgb-range pickers). Alpha
meaning becomes a tiny illustrated badge. Behaviours list
becomes a tag-strip of fabric labels.

---

### 1.10 `deform_panel.py` — REMOVED (Phase D step 6)

Module raises `ImportError` on import. No surface. The
replacement is the property inspector bound against
`softbody.Body` and `pharos_engine.zones`. No translation
required.

---

## 2. Animation timing budget

The woodland creatures are pure presentation — they must never
delay a frame. Targets (assuming a 60 fps editor → 16.66 ms
budget):

| Animation class      | Per-frame budget | Concurrency  | Notes |
|----------------------|------------------|--------------|-------|
| Idle creature (fox sleeping, butterfly hover) | ≤ 1.0 ms | one at a time | Pre-bake to an 8-frame strip; draw on `viewport_drawlist` via `dpg.draw_image`. Step a single `int frame_idx` per editor tick. |
| Transient one-shot (butterfly flutter on save, owl hoot on error) | ≤ 5.0 ms total amortised across its lifetime | at most two concurrent | Each one-shot owns a `start_time` and a max `duration_s`; runs on the same drawlist as the gizmo overlay. Drop the animation if `dpg.get_frame_count()` advance ≥ 2 per tick. |
| On-build confetti / acorn shower | ≤ 8.0 ms one-shot peak frame | unique | Cap at 80 particles; budget gate kills it after 2 s. |
| Easter egg (Ctrl+Shift+F "feed the fox") | ≤ 5.0 ms one-shot | unique | Cached sprite, no procedural sim. |

Implementation note: every animation MUST live in a single
shared `viewport_drawlist` that we clear-and-rebuild each frame
(same pattern as `GizmoOverlay`). A central `WoodlandScheduler`
owns the list and exposes
`schedule(animation, expected_ms, max_concurrent=1)`. If the
caller's budget is busted on the previous frame, the scheduler
rejects new one-shots silently (no error, no console spam).

---

## 3. Pattern catalog — DPG → Notebook widget map

| DPG primitive                  | Today's role                              | Notebook translation                  | Implementation sketch |
|--------------------------------|-------------------------------------------|---------------------------------------|-----------------------|
| `add_button`                   | Tool / action / spawn                     | Wax-seal stamp                        | `add_image_button` with a tiny PNG; per-item theme strips the frame |
| `add_checkbox`                 | Snap, visibility, auto-sync               | Drawn eye glyph / paperclip           | Custom image with two states |
| `add_collapsing_header`        | Inspector sections, material defs         | Section divider with hand-drawn doodle | Wrap with an `add_image` header strip |
| `add_drag_float`/`floatx`      | Transform fields                          | Ruler slider with tick marks          | Inject a per-item theme that hides the bar fill and overlays an image |
| `add_input_text` (multiline)   | Code Mode panes                           | Paper page with ink lines             | Background image bound via `mvThemeCol_FrameBg` (rgba=0) + child window with image |
| `add_listbox`                  | `list[str]` fields                        | List of pressed-flower labels         | Custom row painter via drawlist |
| `add_color_edit`               | RGBA tuples                               | Pigment swatch with brush             | Keep the picker; theme the swatch frame |
| `add_combo`                    | Alpha meaning, drivetrain kind            | Pull-tab tag                          | Default DPG combo with brown text on cream |
| `add_tab_bar` / `add_tab`      | Viewport/Code, Scene/Details              | Notebook binder dividers              | Theme `mvThemeCol_Tab*` with paper-grain bitmap |
| `add_tree_node`                | Dynamics tree                             | Pressed-bestiary indentation          | Inject a custom arrow glyph via theme |
| `viewport_drawlist`            | Gizmo overlays                            | Coloured-pencil overlay layer + woodland creatures | Shared with `WoodlandScheduler` |
| `popup` / `modal`              | Spawn modal, [?] reference popup          | Note-card / torn-page                 | Background bitmap |
| `child_window` (border=True)   | Left tools / centre tabs / right details  | Notebook page boundaries              | Tile a paper-grain bitmap behind the ChildBg |

---

## 4. Keyboard shortcut map

Preserve every Nova3D shortcut already wired in `shell.run()`.
Add the tool-letter shortcuts that are documented on the toolbar
button prefixes but not actually bound today. Add a small set of
playful no-op easter eggs that trigger woodland animations only.

| Shortcut         | Action                                | Status today | After overhaul |
|------------------|---------------------------------------|--------------|----------------|
| `Ctrl+S`         | Save project                          | Live         | Unchanged; butterfly flutter on success |
| `Ctrl+Z`         | Undo                                  | Live         | Unchanged |
| `Delete`         | Delete selected entity                | Live         | Unchanged |
| `F5`             | Toggle play mode                      | Live         | Unchanged; deer pokes head in on enter |
| `S`              | Select tool                           | Documented, **not bound**  | Bind in `shell.run()` |
| `T`              | Translate (Move) tool                 | Documented, **not bound**  | Bind in `shell.run()` |
| `R`              | Rotate tool                           | Documented, **not bound**  | Bind in `shell.run()` |
| `E` (Scale)      | Scale tool                            | Not bound                  | Bind (replaces `[Sc]` button hint) |
| `Ctrl+Shift+F`   | Feed the fox (idle creature animation) | n/a         | New easter egg — purely visual |
| `Ctrl+Shift+B`   | Spawn butterfly across viewport       | n/a         | New easter egg |
| `Ctrl+Shift+O`   | Owl hoot (test the error path)        | n/a         | New easter egg |

All shortcuts route through the existing `shell.run()`
key-pressed checks; no new key-handler infrastructure required.

---

## 5. Fun-animation slot recommendations

Ranked by intrusion cost (lowest first) and per-frame budget
headroom:

1. **Toolbar margin idle (fox sleeping).** The toolbar row has
   `~20 px` of horizontal spacing between the snap toggle and
   the mode toggles; that's free real-estate for a 32-px sleeping
   fox sprite that breathes (2-frame loop, 1 fps). Cost: ~0.2 ms.
   Zero conflict with any active widget.
2. **On-save butterfly flutter.** Already gated on `Ctrl+S` which
   has a discrete success path (`_save_project` sets status
   "Saved"). Add a single `Butterfly.flutter_across(viewport)`
   call in that branch. Sprite path: top-left → top-right over
   1.5 s. Cost: ~3 ms during the animation, 0 otherwise.
3. **On-build acorn shower.** Wire to whatever build-success
   hook exists (TBD — `engine.build_gen` likely candidate). 80
   particles, gravity-only, 2 s lifetime.
4. **On-startup deer cameo.** Fires once during
   `EditorShell.setup` completion. The deer pokes its head in
   from the right sidebar over 0.8 s, blinks, retreats. Cost:
   one-shot, ~4 ms peak.
5. **On-error owl.** When `_save_project` / `_undo` / `_delete_selected`
   hit their exception branch (today they set status messages like
   "Save failed: …"), an owl appears at the status bar with a
   small "?!" speech bubble for 1.5 s. Cost: ~3 ms one-shot.

Shader / paper-edge layering opportunities (must not reduce
readability):

- A subtle per-tick paper-grain animation on `child_window`
  backgrounds (very low-amplitude UV offset of a tiled grain
  texture). Imperceptible per frame; gives the editor a "living
  page" feel.
- A "fountain-pen ink trail" effect when dragging a slider —
  short particle trail off the grab handle.
- A "pencil shimmer" on the gizmo overlay when the mouse first
  touches a handle (one-frame radial gradient).

---

## 6. Nova3D → Woodland translation summary

| Nova3D pattern (today)                  | Woodland/notebook translation     |
|-----------------------------------------|-----------------------------------|
| Toolbar tool buttons                    | Stamps in a stationery tray       |
| Scene outliner tree                     | List of pressed flowers / bestiary |
| Property inspector                      | Field journal entry with sketches |
| Gizmo overlay                           | Doodled measurement arrows in coloured pencil |
| Code Mode (Prompt / Code panes)         | Diary page with bookmark ribbon   |
| Spawn `+ Add` menu / modal              | Trading card deck of creatures to summon |
| Material editor                         | Pigment recipe cards              |
| Tab bar (Viewport/Code, Scene/Details)  | Notebook binder dividers          |
| Custom titlebar                         | Marbled-paper header strip        |
| Status bar                              | Margin annotation in italic       |
| Glassmorphism DWM blur                  | Opaque paper backdrop (no DWM)    |
| Accent button theme                     | Pressed-ink wax-seal effect       |

---

## 7. Migration considerations (for the implementation sprint)

- **Single global theme.** `apply_editor_theme` is the only
  place the palette is defined; switching to the paper palette
  is a one-file change. The per-item theme cache
  (`_accent_button_theme`, `_viewport_opaque_theme`) needs to
  invalidate alongside.
- **Per-item theme handles** are widely cached on the panel
  instances (`SceneOutliner._accent_theme`, `EditorToolbar._accent_theme`,
  etc.). The overhaul should keep the `theme.get_accent_button_theme()`
  /  `get_default_button_theme()` API stable; only the colours change.
- **Sprite + texture loading** needs a one-time path:
  `pharos_engine/ui/editor/assets/woodland/` with small PNGs
  (≤ 4 KB each). Load via `dpg.add_image_registry` + cached
  `dpg.add_static_texture` handles at `apply_editor_theme` time.
- **No engine surface change.** Every panel keeps its current
  `build(parent_tag)` protocol — `EditorShell.register_panel`
  contract is preserved.
- **Visual regression.** Capture `examples/editor_demo.py`
  screenshot into `tests/data/visual_baselines/editor_woodland.png`
  before merge.

---

## 8. Summary

10 panels audited; 9 live, 1 retired (`deform_panel`). The
Nova3D contract is uniform: every panel implements
`build(parent_tag)`, owns its own DPG tags, reads engine state
directly (no bus), and mutates engine state via direct
attribute writes. This makes the theme overhaul a presentation-
only change — no public surface or engine-state change is
required. The opportunity space for woodland creatures is
generous: idle toolbar fox, save-time butterfly, error-time
owl, startup deer, build-time acorn shower. All five fit
inside a sub-5 ms one-shot budget on a 60 fps editor.
