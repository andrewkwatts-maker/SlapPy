<!-- handauthored: do not regenerate -->
# pharos_engine.ui.editor — API Reference

> Hand-written reference for the optional Dear PyGui editor shell
> (``pip install pharos-engine[editor]``).
> Covers the dataclass-reflection inspector, the spawn-menu factory
> registry, the multi-kind material editor, the scene outliner, and
> the top-level shell that wires them together. For the underlying
> material data model see [`material.md`](material.md).

## Canonical surface — the Notebook panel family

As of 2026-06-03 the shipping editor wires the **Notebook** panel
family exclusively. ``EditorShell.setup()`` constructs
``NotebookToolbar`` / ``NotebookOutliner`` / ``NotebookInspector`` /
``NotebookGizmoOverlay`` (via the headless-safe
``setup_notebook_panels`` helper) and applies the active diary-family
theme through the notebook theme registry — **not** the Nova3D
``theme.apply_editor_theme`` dark glass path. The legacy Nova3D
panel modules (``toolbar.py``, ``scene_outliner.py``,
``property_inspector.py``, ``gizmo_overlay.py``, ``theme.py``) remain
on disk as **reference only**; they are no longer imported by the
shell and are kept solely as study material — Nova3D is a separate
project worth learning from. See
``docs/ui_pattern_audit_2026_06_03.md`` for the contract audit and
the rationale behind the swap.


The subpackage is **lazy-loaded** and **fully optional**. Every
`dearpygui` import is deferred to runtime so the rest of
`pharos_engine` (the engine, the studio API, the rebuild physics
stack) imports cleanly without the `[editor]` extra installed; a
missing dearpygui surfaces as an `ImportError` only when
`EditorShell.setup()` is actually called.

## Design context — Phase A directive

This subpackage is the implementation of **Phase A** of the
`reactive-valley` plan
(`C:\Users\Andrew\.claude\plans\ok-we-were-working-reactive-valley.md`).
That plan calls for a single explicit posture:

> _"reuse the existing `property_inspector.py` reflection machinery
> and `material_editor.py` pattern — not to stand up a fleet of new
> panels."_

Every class below follows that directive:

- `PropertyInspector` is the universal dataclass reflector. The
  spawn-menu modal (Sprint 1) and the material editor's softbody /
  fluid kinds (Sprint 2F) both **re-use** it — they do not duplicate
  widget code.
- `MaterialEditor` carries a `kind=` discriminator (Sprint 2F)
  exactly as the plan specifies, so MaterialMap / softbody.Material /
  fluid.FluidMaterial all share one panel.
- `SpawnMenu` is the **only** new authoring surface introduced in
  Phase A; ragdoll / IK / rope / humanoid spawning all flow through
  the same modal + reflection pipeline.

## Public surface (`__all__`)

- `EditorShell` — top-level shell (`shell.py`).
- `ViewportPanel`, `LayerPanel`, `LayerLightingPanel`,
  `MeshInspector` — viewport-side panels.
- `PropertyInspector` — dataclass reflection
  (`property_inspector.py`).
- `MaterialEditor` — color-range / softbody-Material /
  fluid-FluidMaterial editor (`material_editor.py`).
- `NodeGraphPanel`, `AnimGraphPanel`, `BehaviorPanel`, `TagPainter` —
  domain-specific authoring panels.

Not in `__all__` but documented here because they are first-class
Phase A surfaces:

- `SceneOutliner` (`scene_outliner.py`) — entity hierarchy +
  `+ Add` spawn-menu host.
- `SpawnMenu` module (`spawn_menu.py`) — `SPAWN_ACTIONS` registry
  + `open_spawn_modal`.

## Classes

### `PropertyInspector`

_class — defined in `pharos_engine.ui.editor.property_inspector`_

Auto-generates DPG widgets for every primitive field of an arbitrary
Python object. The **single source of truth** for object reflection
in the editor; every other panel that needs to edit a dataclass
delegates here rather than building its own widget tree.

> Sprint 2F's expanded contract: a dataclass instance binds through
> `set_object(obj)`; the panel walks `dataclasses.fields(obj)` (or
> `vars(obj)` for non-dataclass objects) and dispatches on the
> field's _value_ type, not its annotation. This is the reflection
> machinery the Phase A plan tells every spawn / material panel to
> reuse.

#### Panel protocol

```python
build(parent_tag: str | int) -> None
```

Must be called once after `dpg.create_context()` and before the
first frame. Subsequent `set_object` calls repopulate the container
without rebuilding it.

#### Three-section layout

`_refresh()` categorises every field into one of three collapsing
headers, in this order:

1. **Transform** _(default-open)_ — fields named `position`,
   `rotation`, `scale`, `z_height`, `z_order`. Always rendered with
   drag widgets (`add_drag_float`, `add_drag_floatx`) at
   `speed=0.5`.
2. **Properties** _(default-open)_ — every other field that
   `_is_primitive()` accepts (bool, int, float, str, float-tuple
   length 2/3/4, list[str], list[int]).
3. **References** _(default-collapsed)_ — fields that
   `_is_engine_object()` flags as complex (instances from
   `pharos_engine.*` modules that are not dataclasses, or lists
   containing non-primitive items). Rendered as
   `<name>: TypeName [?]` with a popup button that opens a modal
   with the full `repr()`.

#### Widget dispatch table

| Field value type | Widget |
|---|---|
| `bool` | `add_checkbox` |
| `int` | `add_input_int` |
| `float` (transform name) | `add_drag_float` (speed=0.5) |
| `float` (other) | `add_input_float` |
| `str` | `add_input_text` |
| `tuple[float\|int]` len 2 (transform) | `add_drag_floatx` size=2 |
| `tuple[float\|int]` len 2 (other) | `add_input_floatx` size=2 |
| `tuple[float\|int]` len 3 | `add_input_floatx` size=3 |
| `tuple[float\|int]` len 4 | `add_color_edit` (treated as RGBA) |
| `list[str]` | `add_listbox` (up to 4 visible) |
| `list[int]` | `add_input_text` with CSV parse-back |
| `dict[str, primitive]` | inline key/value rows |

#### Dict-bag handling

`_render_dict_field` inlines a `dict[str, primitive]` field as a
section with one widget per key. Used for the kind-specific `params`
bag shared by the dynamics spec dataclasses (`JointSpec.params`,
`MotorSpec.params`, `SpringSpec.params`, `RopeSpec.params`,
`IKChainSpec.params`). Empty dicts render a `"(params bag, empty)"`
placeholder. Write-back path:
`self._obj.<attr>[<key>] = app_data`, with float-tuple results
coerced back via `as_tuple=True` so dicts round-trip byte-for-byte.

#### Write-back

`_make_callback(attr_name)` returns a DPG callback that calls
`setattr(self._obj, attr_name, app_data)` wrapped in a
`try/except (AttributeError, TypeError)` guard. The list-of-int
parser swallows `ValueError` so users can type invalid CSV without
crashing the editor.

### `SpawnMenu` (module)

_module — defined in `pharos_engine.ui.editor.spawn_menu`_

The `+ Add` action table. Not a class — the module exposes a list of
action dicts plus an `open_spawn_modal` callable that the
`SceneOutliner` popup walks.

#### `SPAWN_ACTIONS`

_list[dict]_ — nine entries, one per spawnable body kind:

- **Sprint 1 originals** (softbody + fluid):
  `Add SoftBody Lattice`, `Add Layered Creature`, `Add Vehicle`,
  `Add Fluid Pool`, `Add Sand Pile`. Each entry resolves a factory
  in `pharos_engine.softbody.body_builders` /
  `pharos_engine.softbody.vehicle` / `pharos_engine.fluid.world` at
  **click time** so missing softbody / fluid backends do not break
  editor import.

- **Sprint 3G dynamics primitives** (rope / ragdoll / IK):
  `Add Rope`, `Add Ragdoll`, `Add IK Chain`. Adapter factories
  (`_spawn_rope`, `_spawn_ragdoll`, `_spawn_ik_chain`) live at module
  scope and translate the flattened authoring spec into the real
  `RopeSpec` / `RagdollSpec` / `IKChainSpec` plus the extra
  positional arguments (anchor points, target points, root pin
  flags) the underlying dynamics builders require.

- **Sprint 6 humanoid action**: `Add Humanoid` invokes
  `_spawn_humanoid`, which builds a 15-node humanoid skeleton via
  `pharos_engine.dynamics.humanoid.make_humanoid` (pelvis + neck +
  head + 2×[shoulder, elbow, wrist] + 2×[hip, knee, ankle]). The
  adapter mirrors `make_humanoid`'s keyword arguments as primitive
  fields on `HumanoidSpawnSpec` so PropertyInspector reflection
  draws each one as a plain widget. Unlike rope / ragdoll which
  target the slim XPBD `World`, the humanoid factory expects a
  softbody-style world that exposes the `.nodes` / `.beams` SoA
  arrays — the adapter passes `world` through unchanged so authors
  get a clear `TypeError` immediately if the world doesn't match.

#### Spec dataclasses

One per `SPAWN_ACTIONS` entry: `LatticeSpec`, `CreatureSpec`,
`VehicleSpec`, `PoolSpec`, `SandSpec`, `RopeSpawnSpec`,
`RagdollSpawnSpec`, `IKChainSpawnSpec`, `HumanoidSpawnSpec`. Pure
dataclasses with primitive fields so `PropertyInspector` reflects
each one for free — **no widget code is duplicated**.

`IKChainSpawnSpec.node_indices_csv` is a CSV string deliberately
typed `str` rather than `list[int]` so the inspector can edit it as
a plain text field; the adapter parses it back to `list[int]` before
constructing the real `IKChainSpec`.

#### Functions

- `open_spawn_modal(action: dict, world: Any) -> None` — opens a
  DPG modal for *action* and calls `action["factory"](world,
  **spec_fields)` on confirm. The body of the modal is a
  `PropertyInspector` bound to a fresh spec instance — **the same
  reflection used everywhere else**. Silent no-op if dearpygui is
  not installed.

- `_resolve_factory(dotted: str) -> Callable` — `importlib`-based
  factory resolution. Tries the dotted path verbatim first, then
  falls back to `pharos_engine.<dotted>` for legacy entries.

### `MaterialEditor`

_class — defined in `pharos_engine.ui.editor.material_editor`_

Visual material editor with a Sprint 2F `kind=` discriminator that
lets one panel handle three target shapes:

| `kind` constant | Target | Renderer |
|---|---|---|
| `KIND_MATERIAL_MAP` | `pharos_engine.material.map.MaterialMap` | Legacy per-`MaterialDef` collapsing header with R/G/B drag-int sliders, alpha-meaning combo, behaviors text field, delete button, + `Add Material` button. |
| `KIND_SOFTBODY` | `softbody.Material` dataclass | `PropertyInspector` reflection. |
| `KIND_FLUID` | `fluid.FluidMaterial` dataclass | `PropertyInspector` reflection. |

#### Kind detection

`_detect_kind(target)` decides automatically (most-specific first):

1. Object exposes `_materials: list` → `material_map`.
2. Type module starts with `pharos_engine.fluid` → `fluid`.
3. Type module starts with `pharos_engine.softbody` → `softbody`.
4. Any other dataclass → falls back to `softbody` so it still gets
   rendered through the dataclass-reflection path.
5. Anything else → `material_map` (the legacy default).

Callers can override via `set_target(target, kind="...")`.

#### Reflection delegation

The softbody / fluid paths build a child `PropertyInspector`
(`inspector._panel_tag = f"{self._panel_tag}_reflect"`),
assign the target to `inspector._obj`, and call `inspector._refresh()`.
**No widget code is duplicated.** A `_reflect_inspector` attribute
is stashed on the editor so callers can introspect what was built.

#### Public API

- `set_material_map(mat_map)` — legacy shim; equivalent to
  `set_target(mat_map, kind=KIND_MATERIAL_MAP)`.
- `set_target(target, kind=None)` — kind defaults to
  `_detect_kind(target)` when omitted.
- `build(parent_tag)` — wire the entry group + Add button under
  *parent_tag*.

The `Add Material` button is rendered regardless of kind but is a
no-op for the dataclass kinds (those represent one material per
panel; nothing to add).

### `SceneOutliner`

_class — defined in `pharos_engine.ui.editor.scene_outliner`_

Scene entity hierarchy panel with per-row visibility / lock /
selection controls, plus the **host for the `+ Add` spawn-menu
popup**. Implements the standard panel protocol
`build(parent_tag: str | int) -> None`.

#### Row layout

Each entity row contains:

- Visibility checkbox (writes back through `entity.visible`).
- Lock button (toggles `entity.locked`; tinted green/red at build
  time).
- Name button (selection — accent theme applied to the current
  selection, default theme to the rest).
- Right-aligned type-name badge (`[ClassName]`).

#### Selection callback

`set_on_select(cb)` registers a callable invoked on every selection
change. The `EditorShell` wires this into the gizmo overlay
(`set_on_select(gizmo_overlay.set_entity)`) so manipulator handles
follow the outliner.

#### Spawn-menu wiring

The `+ Add` button has a popup attached (`mousebutton=0`) populated
from `pharos_engine.ui.editor.spawn_menu.SPAWN_ACTIONS`. Each menu
item binds the action at default-arg time so the closure does not
capture the loop variable, then calls
`open_spawn_modal(action, self._scene)`. Missing spawn module is
caught with a broad `except Exception` so an unloadable spawn menu
just hides the popup rather than breaking the outliner.

### `EditorShell`

_class — defined in `pharos_engine.ui.editor.shell`_

Top-level Dear PyGui shell that orchestrates every panel under a
single primary window.

```python
EditorShell(
    engine: Engine,
    title: str = "SlapPyEngine Editor",
    width: int = 1400,
    height: int = 900,
) -> None
```

#### Lifecycle

- `setup()` — create the DPG context, build the viewport, wire
  every panel into the layout. Raises `ImportError` with a clear
  `pip install SlapPyEngine[editor]` hint if dearpygui is missing.
- `run()` — enter the render loop (blocks until viewport close or
  `stop()`). Polls keyboard shortcuts (Ctrl+S save, Ctrl+Z undo,
  Delete remove-selected, F5 toggle play), drives the gizmo overlay
  update, and pumps the custom title-bar drag handler.
- `stop()` — flip the internal running flag; actual loop termination
  is driven by `dpg.is_dearpygui_running()`.

#### Layout

A single primary window (`editor_root`) with a vertical stack:

1. Custom title bar (28 px) — replaces the OS window chrome with a
   text label + minimize / close buttons; drag handler moves the
   viewport.
2. Toolbar row (`TOOLBAR_H = 36`).
3. Main horizontal area — left tools panel (`LEFT_W = 200`) | centre
   `Viewport`/`Code Mode` tab pair | right `Scene`/`Details` tab
   pair (`RIGHT_W = 300`).
4. Content browser (`BOTTOM_H = 220`).
5. Status bar (single `add_text` row).

#### Panel registration

- `register_panel(panel)` — append any object implementing
  `build(parent_tag) -> None` to the Details sidebar.
- `_toolbar`, `_scene_outliner`, `_content_browser` are auto-wired
  during `setup()` if not pre-set.
- `_spawn_menu` is attached as an instance attribute so plugin
  layers can extend `SPAWN_ACTIONS` before the outliner is built.

#### 2D / 3D mode

`_on_editor_mode_change(mode)` is fired by the toolbar mode toggle.
`"2D"` hides the 3D-only panel tags (`_mesh_inspector_tag`,
`_layer_lighting_tag`); `"3D"` shows them. The change is forwarded
to the viewport (`viewport_panel.set_mode(mode)`) and the gizmo
overlay (`gizmo_overlay.set_mode(mode)`). All panel tags are
guarded with `dpg.does_item_exist` so the method is safe to call
before the 3D panels have been built.

#### Theme

The shell applies the active diary-family theme through
``setup_theme_subsystem`` (which calls
``pharos_engine.ui.theme.apply_theme``) — the notebook theme registry
owns the entire editor look. The Nova3D ``apply_editor_theme`` /
``apply_dwm_glass`` / ``get_viewport_opaque_theme`` helpers in
``pharos_engine.ui.editor.theme`` are **reference only** and are not
invoked by ``setup()``.

## Inner modules

- `shell` — `EditorShell`.
- `property_inspector` — `PropertyInspector`, `TRANSFORM_FIELDS`,
  `DRAG_FLOAT_NAMES`, primitive-detection helpers.
- `material_editor` — `MaterialEditor`, `KIND_*` constants,
  `_detect_kind`.
- `scene_outliner` — `SceneOutliner`.
- `spawn_menu` — `SPAWN_ACTIONS`, `open_spawn_modal`, the nine spec
  dataclasses, the four dynamics adapter factories.
- `toolbar`, `viewport_panel`, `layer_panel`, `node_graph_panel`,
  `tag_painter`, `anim_graph_panel`, `behavior_panel`,
  `mesh_inspector`, `layer_lighting_panel`, `content_browser`,
  `code_mode_panel`, `script_binding_panel`, `deform_panel`,
  `ollama_setup_modal`, `gizmo_overlay`, `theme` — Sprint-2 / Sprint-4
  domain-specific panels that follow the same `build(parent_tag)`
  protocol.

## Conventions

- **Lazy import.** `__init__.py` resolves names through a `_LAZY_MAP`
  + `__getattr__` so `import pharos_engine.ui` (or
  `import pharos_engine.ui.editor`) never imports `dearpygui` until a
  concrete class is referenced.
- **Optional extra.** Every dearpygui import is **deferred to method
  bodies**. A missing dearpygui surfaces as `ImportError` only at
  `setup()` / `run()` time, with a clear `pip install
  SlapPyEngine[editor]` message.
- **Reuse the reflection machinery.** Per the Phase A plan, every
  new authoring surface that needs to edit a dataclass binds a
  `PropertyInspector` rather than building its own widget tree.
  Today this covers (a) the spawn modal body, (b) the
  softbody / fluid kinds of `MaterialEditor`, and (c) every panel
  in the Details sidebar.
- **Panel protocol.** Every object handed to `register_panel` or
  invoked from `setup()` implements
  `build(parent_tag: str | int) -> None`. The shell calls this
  once during `setup()`; the panel owns its own refresh logic
  thereafter.
- **No game code coupling.** `EditorShell` only touches
  `engine.scene`, `engine._project_manager`, and `engine._undo_manager`
  via `getattr(..., None)` guards; the editor is fully usable against
  a bare-minimum Engine without breaking on missing managers.

## Design notes

No separate `ui_editor_design.md` ships — the "Phase A directive"
prose at the top of this doc already serves as the design statement
(the `PropertyInspector`-as-single-source-of-reflection mandate, the
`MaterialEditor.kind=` discriminator, the `SpawnMenu` as the only new
authoring surface). The full Phase A plan lives in
`C:\Users\Andrew\.claude\plans\ok-we-were-working-reactive-valley.md`
for additional context.

If a future Phase B adds a node-graph editor, an inline shader
editor, or a multi-document-interface tab layout, promote that
material to a dedicated `ui_editor_design.md` and link both ways.

## See also

- [`material.md`](material.md) — `MaterialEditor` targets this
  authoring surface; the kind discriminator routes through
  `PropertyInspector` for softbody / fluid.
- [`../material_design.md`](../material_design.md) — the material
  authoring substrate the editor sits on top of.
- [`animation.md`](animation.md) — `AnimGraphPanel` and `BehaviorPanel`
  sit alongside this surface.
