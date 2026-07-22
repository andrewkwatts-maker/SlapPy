# UI Nesting + Window-Separation Audit (2026-06-07)

Read-only audit of the Nova3D legacy editor patterns still preserved
under `python/pharos_engine/ui/editor/*.py` (the pre-notebook shell,
toolbar, outliner, inspector, gizmos, code mode, spawn menu, material
editor). Produces an ADOPT / ADAPT / SKIP recommendation table for the
Sprint T7 usability sweep and is a companion to
[`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md).

Cross-references:

* [`docs/sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) — Sprint
  1 (Notebook theme) already landed; this doc feeds Sprint T7
  usability polish.
* [`docs/theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) — T1 diary-shell,
  T2 panel-decor, T4 declarative-theme sprints.
* [`docs/notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md) — user-facing
  behaviour manual (source of truth for shipped behaviour).
* [`docs/master_review_2026_06_07.md`](master_review_2026_06_07.md) —
  overall v0.4 refactor plan.

Sources read (all under `python/pharos_engine/ui/editor/`):

* `toolbar.py` — 4-button horizontal tool strip + snap + 2D/3D toggle.
* `scene_outliner.py` — collapsing header + entity rows + dynamics
  tree; hosts the `+ Add` popup.
* `property_inspector.py` — Transform / Properties / References
  three-section auto-reflection.
* `gizmo_overlay.py` — front-side viewport drawlist for 2D + 3D
  transform gizmos.
* `shell.py` — legacy 5-row layout (custom titlebar, toolbar, main
  split, bottom content browser, status bar).
* `code_mode_panel.py` — split Prompt / Code editor.
* `spawn_menu.py` — modal + `SPAWN_ACTIONS` table.
* `material_editor.py` — kind-discriminator dispatch.

Sibling notebook implementations
(`notebook_toolbar.py`, `notebook_outliner.py`, `notebook_hotkeys.py`,
etc.) are treated as the "SlapPy currently ships" baseline.

---

## 1. Pattern catalog — 18 Nova3D UI patterns

### 1.1 Horizontal-group tool strip

**Nova3D.** `EditorToolbar.build()` opens a single
`dpg.group(horizontal=True)` inside the supplied `parent_tag` and drops
four buttons + separators + snap toggle + mode buttons directly into
it. No nested child window, no title, no dedicated frame — the group
inherits the parent's background and only rounding.

```
[parent_tag] {group horizontal=True}
    [S Select] [T Move] [R Rotate] [Sc Scale]  |  [Snap OFF]  |  [2D][3D]
```

**SlapPy today.** `NotebookToolbar` mounts inside a
`MovablePanelWindow` wrapper (a first-class `dpg.window`) that owns its
own frame, title bar, and washi-tape decoration. The toolbar itself is
still a horizontal group but tools are rendered as `StickerButton`
widgets with SVG glyphs.

**Recommendation. ADOPT** — the horizontal-group idiom is right;
SlapPy already inherits it. Keep the movable-window wrapper (net UX
win: users can dock the toolbar to any edge).

**Effort.** none — already shipped.

---

### 1.2 Bottomless panel — no explicit height

**Nova3D.** Panels never declare their own height. `PropertyInspector`
uses `child_window(height=-1, autosize_x=True)`; the outliner nests
inside a `collapsing_header` and lets DPG size it. The parent (`shell`)
decides.

**SlapPy today.** Same idiom — plus `MovablePanelWindow.set_pos_size`
lets the shell push per-preset dimensions in.

**Recommendation. ADOPT** — retain autosize; preset-driven size
is the correct extension.

**Effort.** none.

---

### 1.3 `collapsing_header` as the primary sectioning primitive

**Nova3D.** `PropertyInspector` renders exactly three
`collapsing_header`s — Transform, Properties, References. `MaterialEditor`
uses one per `MaterialDef`. `SceneOutliner` uses one as its outer
frame. All default to open except References.

```
[collapsing_header "Transform"        default_open=True ]
    (pos, rot, scale, z_height, z_order)
[collapsing_header "Properties"       default_open=True ]
    (bool / int / float / str / tuple)
[collapsing_header "References"       default_open=False]
    (name: TypeName [?])
```

**SlapPy today.** `NotebookInspector` retains the three-section split
but styles the headers as washi-tape strips. `NotebookOutliner`
replaces the collapsing header with a dedicated section frame.

**Recommendation. ADOPT** — the three-section split scales well;
covers the "load-bearing tail expandable" case (References defaults
collapsed).

**Effort.** none.

---

### 1.4 `tree_node` grouping in the outliner

**Nova3D.** `SceneOutliner._build_dynamics_tree` uses nested
`tree_node`s for `World → Bodies (N) → body`,
`Joints (N) → Distance (n) → joint`, `Humanoids (N) → humanoid`.
Joint kind order is fixed
(`distance, spring, weld, ball, hinge, motor, prismatic`).

**SlapPy today.** `NotebookOutliner` renders a flat list with badges;
no dynamics-world tree.

**Recommendation. ADAPT** — SlapPy needs the tree back for the
dynamics story (bodies + joints + humanoids). Keep the fixed kind order.
Wrap each `tree_node` label in a notebook-themed ribbon divider so it
reads as "flip-page tabs" rather than raw ImGui triangles.

**Effort.** small (~40 lines; `iter_dynamics_rows` is already stable
in the legacy file and can be lifted verbatim).

---

### 1.5 `+ Add` popup off a header button

**Nova3D.** The outliner's `+ Add` button carries a `dpg.popup(...,
mousebutton=0)` populated from the `SPAWN_ACTIONS` table. Left-click
opens the popup; each row is a `menu_item` that fires
`open_spawn_modal(action, scene)`.

**SlapPy today.** `NotebookSpawnMenu` opens a large modal directly
(no intermediate popup). Users see the full card grid immediately.

**Recommendation. SKIP the popup layer** — SlapPy's direct-to-modal
is friendlier. **ADOPT the `SPAWN_ACTIONS` table shape**
(label / dotted-factory / spec) — the modal already does this and it
lets subsystems ship new spawnables without touching the editor.

**Effort.** none (already the shipping design).

---

### 1.6 Modal reusing `PropertyInspector` for reflection

**Nova3D.** `open_spawn_modal` builds a fresh `PropertyInspector`
inside the modal, binds it to a dataclass spec instance, and calls
`factory(world, **spec_to_kwargs(spec_instance))` on Spawn. No widget
code is duplicated.

**SlapPy today.** Same idiom via `NotebookInspector` — the field
reflection is shared between the inspector panel and the spawn modal.

**Recommendation. ADOPT** — this is the single best pattern
lifted from the audit. Every new "authoring dialog" should reuse the
inspector reflection instead of hand-rolling widgets.

**Effort.** none.

---

### 1.7 Two-pass field categorisation

**Nova3D.** `PropertyInspector._refresh` walks fields once to classify
them (`TRANSFORM_FIELDS` / primitive / engine-object) and once to
render into the right section. This keeps ordering deterministic even
when subsequent fields would otherwise appear in the wrong bucket.

**Recommendation. ADOPT** — trivial to preserve. The notebook
inspector should keep this two-pass invariant so `dynamics.JointSpec`
etc. always render the same way regardless of dataclass field order.

**Effort.** none.

---

### 1.8 Front-side viewport drawlist for gizmos

**Nova3D.** `GizmoOverlay.build()` creates a single
`dpg.add_viewport_drawlist(front=True, tag=...)` and every frame
clears it, hit-tests the mouse, and re-emits primitives. The overlay
draws over the wgpu viewport image, NOT over the notebook panels.

**SlapPy today.** `NotebookGizmoOverlay` extends this with pencil-jitter
strokes and creature overlays but keeps the single-drawlist idiom.

**Recommendation. ADOPT** — the "one drawlist per overlay class"
pattern is load-bearing. The `WoodlandScheduler` (idle animation
system) shares this drawlist per the 2026-06-03 audit; do not fragment.

**Effort.** none.

---

### 1.9 Nested `child_window(border=True)` sections in split editors

**Nova3D.** `CodeModePanel.build` creates two side-by-side
`child_window`s (prompt pane + code pane), each with `border=True`,
each sized `530 x 460 px`. The parent group is
`dpg.group(horizontal=True)` inside the tab body.

```
[tab_body: Code Mode]
    [group horizontal=True]
        [child_window border=True 530x460] Prompt
        [spacer w=4]
        [child_window border=True 530x460] Code
    [separator]
    [text "diff summary"]
```

**SlapPy today.** `NotebookCodePanel` inherits the same split but each
pane is themed as a "diary page" (T1 sprint).

**Recommendation. ADOPT the nested-child-window shape**;
**ADAPT the hardcoded 530×460**. Modern DPG supports
`get_item_rect_size(parent)`; feed that back into pane widths on
resize. The Nova3D file itself flags this: *"DPG does not expose parent
width easily at build time."*

**Effort.** small (~15 LOC; one `dpg.set_item_width` on the resize
handler event).

---

### 1.10 Static row + dynamic row group

**Nova3D.** `SceneOutliner.build` creates a fixed action bar (Add /
Delete), a column header, and then a **named group** (`_row_group_tag`)
whose children are wiped and rebuilt on every `refresh()`. This keeps
the static chrome (button IDs) stable while entity rows come and go.

```
[collapsing_header "Scene Outliner"]
    [group horizontal=True] Add | Delete                # STATIC
    [text "V L Name"]                                   # STATIC
    [separator]
    [group tag=_row_group_tag]                          # DYNAMIC
        [entity_row 0]
        [entity_row 1]
        ...
    [separator]
    [group tag=_dyn_group_tag]                          # DYNAMIC
        [tree_node "World"] ...
```

**Recommendation. ADOPT** — the "static chrome + named dynamic
group" split is the correct DPG idiom for a list that mutates.
Applying to the content browser (breadcrumbs static, files dynamic)
solves the "flicker on refresh" complaint filed in T2.

**Effort.** trivial when applied to the content browser (~10 LOC).

---

### 1.11 `viewport_drawlist(front=True)` for overlays vs `child_window` for widgets

**Nova3D.** Two rendering surfaces coexist without conflict:
`viewport_drawlist(front=True)` for gizmos (drawn *above* everything)
and normal `child_window`s for panels. There is no `back=True`
drawlist and no manual z-ordering — DPG's compositor handles it.

**Recommendation. ADOPT** — do not introduce a `back=True` drawlist
for the paper-grain background; instead theme the child_window's
`mvThemeCol_ChildBg` with a static texture (already the T4 declarative-
theme plan).

**Effort.** none — this is a "don't regress" recommendation.

---

### 1.12 Per-item theme handles cached on the panel instance

**Nova3D.** `EditorToolbar._accent_theme`, `_default_theme`,
`_snap_active_theme`, `_mode_active_theme` are cached once on the
instance during `build()` (guarded by `if self._accent_theme is
None`). Every button binding reuses those handles rather than
constructing a fresh theme.

**Recommendation. ADOPT** — the notebook toolbar already caches
theme handles similarly. Extend the pattern to `NotebookOutliner`
row-highlight, `NotebookInspector` section headers, etc. Consequence:
theme-switch invalidation must clear these handles (already tracked
in T4).

**Effort.** trivial.

---

### 1.13 `dpg.popup(parent=btn_tag, mousebutton=-1)` for [?] repr popups

**Nova3D.** `PropertyInspector._render_complex_field` binds a popup
to the `[?]` button; the popup shows the object's `repr()` wrapped at
400 px. Popup content is built once, visibility is toggled.

```
[group horizontal=True]
    [text "field_name: TypeName"]
    [button "?" small=True]
        [popup]
            [text repr(value) wrap=400]
```

**Recommendation. ADAPT** — the popup shape is fine but hide behind
a right-click menu instead of a `[?]` button so the field row doesn't
grow horizontally. Right-click on the row → "Show repr". This
matches Blender / Unity conventions where advanced info lives behind
context menus.

**Effort.** small (~20 LOC; DPG supports `mousebutton=1` on `popup`).

---

### 1.14 Kind-discriminator dispatch pattern

**Nova3D.** `MaterialEditor._detect_kind(target)` walks a fixed
precedence table (`_materials` attr → module prefix → dataclass →
default) and dispatches to one of two rendering paths
(MaterialMap-legacy vs dataclass-reflection). Adding a third kind is
one new constant + one new precedence rule.

**Recommendation. ADOPT** — apply the same discriminator to the
future ECS component inspector: given a `Component` instance, pick the
right renderer from `(dataclass? → protocol? → fallback)`.
Documented in `docs/master_review_2026_06_07.md` §11.

**Effort.** none as a pattern; small when applied to ECS
(~50 LOC dispatch table).

---

### 1.15 Custom titlebar via primary-window `no_title_bar=True`

**Nova3D.** `shell.py` mounts the primary window with `no_title_bar=True`
and paints its own titlebar strip (`y=0..28`) that owns the drag
handle. `_dragging_window` / `_drag_start_mouse` / `_drag_start_vp`
are the drag state.

**SlapPy today.** Same — the notebook shell keeps the custom titlebar
and paints "SlapPy Notebook" hand-written font.

**Recommendation. ADOPT** — required for the marbled-paper header
strip (T1). Do NOT try to reintroduce OS chrome.

**Effort.** none.

---

### 1.16 Panel protocol — `build(parent_tag)` everywhere

**Nova3D.** Every panel implements exactly one method:
`build(parent_tag: str | int) -> None`. `EditorShell.register_panel`
takes any object satisfying this protocol. No `__init__` args beyond
plain construction (data is set via `set_target` / `set_scene` / etc.).

**Recommendation. ADOPT** — the shipping notebook panels already
follow this. Enforce via a typing.Protocol declared in
`pharos_engine.ui.editor.panel_protocol` so linters catch drift.

**Effort.** small (~10 LOC to add the Protocol).

---

### 1.17 Two-pass drag handling in the gizmo overlay

**Nova3D.** `GizmoOverlay.update()` calls `_handle_mouse` **before**
drawing so drag deltas are applied to the entity before the frame's
gizmo primitives are emitted from the freshly-mutated entity position.
This eliminates one-frame lag.

**Recommendation. ADOPT** — non-obvious ordering; the notebook
overlay already inherits it. Callout in the T7 sprint as
"invariant: mutate before draw" so future refactors don't break it.

**Effort.** none.

---

### 1.18 Dict-of-primitives inline renderer

**Nova3D.** `PropertyInspector._render_dict_field` renders a
`dict[str, primitive]` bag (used by `JointSpec.params`,
`MotorSpec.params`, `RopeSpec.params`, ...) as inline key-value rows
with the right widget per value type. Empty dicts show `"(params bag,
empty)"`. No opaque `[?]` popup for known-shape dicts.

**Recommendation. ADOPT** — extend to any known-shape dict (e.g.
`.attrs`, `.metadata`, `.userdata`). Not general — the field name
must be in an allow-list to avoid rendering arbitrary user dicts as
widget explosions.

**Effort.** small (~30 LOC + allow-list config in
`config/editor.yml`).

---

## 2. Nesting rules — nested-child vs top-level window

### 2.1 The rule of thumb

> Content that always co-exists → **nested `child_window`** inside a
> single top-level window.
>
> Content that a user might want to move, hide, or dock somewhere else
> → **separate top-level `dpg.window`** wrapped in a
> `MovablePanelWindow`.

### 2.2 Applied to SlapPy panels

| Panel | Today | Recommendation | Rationale |
|---|---|---|---|
| Toolbar | Movable window | **Keep separate** | Users dock left/right; some hide it entirely (Wide Code preset). |
| Scene Outliner | Movable window | **Nest inside "Scene" panel** | Always paired with Inspector. Single window = fewer clicks to hide/show. |
| Inspector | Movable window | **Nest inside "Scene" panel** | Ditto — outliner + inspector are one workflow. Split via vertical splitter inside the Scene window. |
| Content Browser | Bottom docked | **Keep separate** | Layout Presets already toggle it independently. |
| Viewport | Always visible, `no_close=True` | **Keep separate + no_close** | Load-bearing; the wgpu image target lives here. |
| Code Mode | Tab in centre | **Keep separate window** (currently a tab) | Users switch between viewport and code; needing to tab through both is friction. |
| Status Bar | Bottom bar | **Keep separate + docked bottom** | Present in every layout preset. |
| Theme Switcher | Modal-ish popup | **Nest inside a Settings panel** | Rarely used; can be reached via Ctrl+T menu without a dedicated window. |
| Welcome / Project Picker | Modal at startup | **Keep modal** | One-shot flow; no reason to persist. |
| Telemetry / Post-Process / Animation panels | Optional windows | **Keep separate** | Each is a workflow of its own; user opens 0 or 1 at a time. |

### 2.3 New Scene panel proposal (T7 deliverable)

```
[Scene window]
    [child_window "outliner" h=60% border=False]
        [collapsing_header "Scene Outliner"]
            [add / delete row]
            [entity rows]
            [dynamics tree]
    [invisible_button splitter (drag to resize)]
    [child_window "inspector" h=40% border=False]
        [Transform / Properties / References sections]
```

Consequence: `Ctrl+\` toggles the whole Scene panel; the split ratio
is persisted in `layout.yaml` per preset.

### 2.4 When NOT to nest

Do NOT nest inside a single window when:

* Panels have very different **update cadences** (viewport = per-frame,
  status bar = event-driven). DPG relayout costs scale with children.
* Panels have very different **z-order** requirements (the gizmo
  overlay MUST be `front=True` — separate drawlist, not a nested
  child).
* Panels have **conflicting keyboard focus** claims (Code Mode
  captures Tab; nesting inside Scene would swallow Tab there too).

---

## 3. Tool depth — secondary options per tool

Nova3D's toolbar already ships snap + snap-size hints on the Move
tool but only exposes the toggle, not the parameter. Blender / Unity /
Godot expose per-tool options in a **secondary strip** underneath the
main tool row. Applied to `NotebookToolbar`:

### 3.1 Select tool (`S`)

* **Rectangle-select** toggle (default off). Drag empty space =
  rubber-band select vs pan-camera.
* **Selection modifier hint** — small label showing "Shift = add,
  Ctrl = remove, Alt = intersect" (no widget; label only).
* **Marquee opacity** slider (visual polish only).

### 3.2 Move tool (`T`)

* **Grid snap** toggle (currently exists).
* **Snap size** — `input_int` default 8 (world units).
* **Axis lock** — three tiny toggles X / Y / Z (Z only in 3D mode).
* **Relative / Absolute** combo — snap to nearest grid vs snap to
  origin-relative grid.

### 3.3 Rotate tool (`R`)

* **Snap angle** — `input_float` default 15°.
* **Pivot mode** — combo of `Entity Origin` / `Selection Median` /
  `Cursor` (matches Blender terminology).
* **Wrap 360** toggle — rotation values wrap or accumulate.

### 3.4 Scale tool (`C`)

* **Uniform scale** toggle (default on). Off = independent XY (Z in
  3D).
* **Pivot mode** — same combo as Rotate.
* **Scale from 1** toggle — start scale relative to current vs relative
  to 1.

### 3.5 Layout

The options strip sits directly under the main toolbar, height 24 px,
theme-matched to a lighter washi-tape stripe. Contents change based
on `active_tool`:

```
[toolbar row]      [S][T][R][C] | [Snap] | [2D][3D]
[options row]      [Rect-select] [Modifier hint: Shift=+, Ctrl=-]
    ^ contents swap when active_tool changes
```

Wire via `NotebookToolbar.set_on_tool_change` → rebuild the options
row. **Persist per-tool options** in `~/.pharos_engine/tool_options.yaml`
so users don't reset snap-size every session.

**Effort.** ~150 LOC — one options-row widget + tool-specific
builders + YAML round-trip.

---

## 4. Usability upgrades for Sprint T7

Ordered by user-facing impact.

### 4.1 Tooltip on every button (hover 500 ms)

* Every `StickerButton`, `add_button`, `add_checkbox`, `add_combo`
  gets a `dpg.tooltip` with a 500 ms delay via
  `dpg.configure_item(tooltip_tag, delay=0.5)`.
* Tooltip text sourced from a central `TOOLTIPS` table so i18n
  (Sprint 7 in the master plan) can swap strings without touching
  panel code.
* Include the keyboard shortcut on the same line: `"Save  (Ctrl+S)"`.

**Effort.** medium (~200 LOC — one tooltip helper + one string
table).

### 4.2 Right-click context menus in outliner

Nova3D has none. Add:

* Rename (in-place inline `input_text` swap)
* Delete
* Duplicate (`copy.deepcopy(entity)`, offset position by 8 units)
* Group (wrap N entities into a parent group, indent children)
* Isolate (temporarily hide all other entities)
* Copy transform / Paste transform (position + rotation + scale)
* Frame (centre camera on selection)

Implement via `dpg.popup(parent=name_button_tag, mousebutton=1)` — one
popup shared across all rows, populated from the currently-hovered
row's context.

**Effort.** medium (~250 LOC — popup builder + 7 action handlers).

### 4.3 Copy/paste entities via Ctrl+C / Ctrl+V

Start minimal:

* Clipboard is a single global slot: `dict[str, Any]` with keys
  `name`, `type`, `position`, `rotation`, `scale`, plus a subset of
  dataclass fields serialised via
  `dataclasses.asdict(entity)`.
* Ctrl+C serialises the currently-selected entity into the slot and
  pushes a status toast `"Copied {name}"`.
* Ctrl+V deserialises the slot into a new entity, offsets position
  by `(8, 8)`, appends to the scene, selects it.
* JSON round-trip (not pickle) so paste can go across editor
  sessions via a `~/.pharos_engine/clipboard.json` cache.

Later (T8): multi-entity clipboard, cross-project paste, prompt
inheritance.

**Effort.** medium (~180 LOC — clipboard state + Ctrl+C/V hotkeys +
JSON encoder).

### 4.4 Multi-select via Ctrl+click / Shift+click

Nova3D's outliner is strictly single-select. Add:

* `NotebookOutliner._selected` becomes `list[Any]` (default `[]`).
* Plain click → replace selection.
* Ctrl+click → toggle entity in / out of selection.
* Shift+click → range-select from last-clicked entity.
* Inspector shows shared fields only, greys out fields that differ.
* Gizmo overlay draws bbox around each selected entity + a combined
  bbox for the selection.

Constraint: Transform edits apply to all selected entities. Use the
"selection median" as the pivot per §3.3.

**Effort.** large (~400 LOC — outliner state migration + inspector
"shared fields" mode + gizmo combined bbox).

### 4.5 Breadcrumb bar in content browser

Currently, the content browser lists files in one flat pane. Add:

```
[Home] / assets / textures / grass /
[< back] [> forward] [^ up]                 [search: ______]
[file grid]
```

Breadcrumb items are clickable buttons. Home button always jumps to
project root.

**Effort.** small (~100 LOC in `notebook_content_browser.py`).

### 4.6 Recently-used spawn cards per project

`NotebookSpawnMenu` today shows all cards in a fixed order. Add a
"Recently used" section at the top of the modal, populated from
`~/.pharos_engine/<project>/spawn_history.json`:

* Track the last 5 successfully-spawned actions.
* Order by recency, most-recent-first.
* If empty, hide the section.

Consequence: users doing rapid iteration (spawn rope, tweak, delete,
spawn rope, ...) get one-click access.

**Effort.** small (~80 LOC — history buffer + JSON round-trip).

### 4.7 Undo/redo semantics — clarify

Nova3D wired only `Ctrl+Z` and only to `engine._undo_manager.undo()`,
which is a stub. Sprint T7 must:

* Land a real undo stack. Command pattern: each mutation (spawn,
  delete, transform, rename, property change) pushes a
  `Command(name, do, undo, snapshot)` onto `UndoManager._stack`.
* Ctrl+Z = pop + call `undo()`. Ctrl+Y = pop from redo stack + call
  `do()`.
* Bound stack depth to 128 commands; drop oldest when full.
* Status toast on undo/redo: `"Undo: rename fox_01 → fox"`.

**Effort.** large (~450 LOC — command base class, 8 concrete command
subclasses, integration with mutation sites).

---

## 5. Cross-references to concurrent sprints

### 5.1 T1 — Diary-shell (already landed)

* Titlebar drag, marbled-paper header, custom fonts, status bar as
  margin note.
* This audit's §4.1 (tooltips) and §4.5 (breadcrumbs) sit on top of
  the shell chrome — no conflicts.

### 5.2 T2 — Panel-decor (in flight)

* Washi-tape borders, sticker corners, section-divider doodles.
* §3.5 (options-row washi stripe) reuses the same nine-slice pattern
  T2 ships. Ensure `NineSlice.render_procedural` is called from
  `NotebookToolbar._build_options_row` once T2 lands.

### 5.3 T4 — Declarative theme (in flight)

* Panel-level theme handles migrate from per-panel caches to a
  central `ThemeCatalog` lookup.
* §1.12 (cached theme handles) needs to route through
  `ThemeCatalog.get_button_accent(theme_id)` after T4. This audit's
  recommendation is compatible — cache the handle *from the catalog*
  instead of constructing it locally.

### 5.4 T7 — Usability polish (this doc's target)

Ships §4.1 - §4.7 together with an integration test suite:

* `test_tooltip_registry.py` — every registered widget resolves a
  tooltip string.
* `test_outliner_context_menu.py` — 7 actions round-trip.
* `test_clipboard_json.py` — copy → serialise → deserialise → paste
  produces identical entity.
* `test_multi_select.py` — Ctrl+click / Shift+click semantics.
* `test_content_browser_breadcrumbs.py` — click Home resets path.
* `test_spawn_history.py` — history JSON round-trip.
* `test_undo_stack.py` — 8 command types round-trip.

Sprint T7 acceptance = all seven tests green + a manual walk-through
matches `docs/notebook_editor_manual_2026_06_03.md` §5 (Usability).

---

## 6. Summary

| Category | Count |
|---|---|
| Patterns catalogued | 18 |
| ADOPT | 12 |
| ADAPT | 3 |
| SKIP | 1 |
| Not applicable / already shipped | 2 |
| Tool-depth options added | 4 tools × ~3 options = 12 new controls |
| Sprint T7 usability wins | 7 |

Top-3 usability wins (biggest impact per LOC):

1. **Right-click context menu in outliner** (§4.2) — closes the
   #1 papercut in the notebook manual usability feedback (rename +
   duplicate + delete need three separate click paths today).
2. **Tooltip on every button** (§4.1) — one commit, unlocks
   discoverability of every keyboard shortcut and per-tool option.
3. **Multi-select via Ctrl+click / Shift+click** (§4.4) — required
   before the material-graph and animation-graph sprints because
   both authoring surfaces are inherently multi-object.

All ADOPT items are already in flight in the notebook siblings; this
audit's job is to make sure the T7 sprint does not accidentally
regress them while adding the usability upgrades from §4.
