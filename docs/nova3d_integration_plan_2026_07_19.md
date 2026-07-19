# Nova3D Integration Plan — 4-page feature audit + 2D+3D layer merge story

**Landed:** 2026-07-19
**Author:** Nova3D-integration research agent (read-only walk of both codebases)
**Nova3D HEAD walked:** `H:/Github/Nova3D/` (C++20 / OpenGL 4.6 / GLFW 3.4 / ImGui docking / Assimp / GLM)
**SlapPy HEAD walked:** `H:/Github/SlapPyEngine/` master (Python 3.13 + Rust `_core` PyO3 extension, wgpu-based 3D bridge, 2D-first `Layer` system)

**Scope.** Nova3D is the reference AAA-grade 3D engine written in C++ with a full deferred renderer, SDF pipeline, radiance-cascade global illumination, ImGui docking editor, glTF/FBX import via Assimp, PBR material graph, cascaded shadow maps, TAA, GTAO, GPU particles, and a 100-file editor panel suite. SlapPy today is a 2D pixel-layer engine with a partial 3D bridge (`render/scene_walker.py`, `render/bvh_3d.py`, `asset_import/gltf_importer.py`, `render/shadows.py`, `render/skybox.py`, `render/instanced.py`, `animation/skeleton_runtime.py`). This report enumerates every Nova3D subsystem, maps each to a SlapPy equivalent (or `GAP`), estimates integration cost, and closes with a concrete **`Layer3D`** design that lets 2D and 3D layers coexist in a single `Scene`.

**Constraint.** Nova3D remains read-only. No SlapPy source is modified — docs only.

---

## Page 1 — Executive summary + subsystem inventory

### Executive summary

Nova3D contains **~44 top-level `engine/` subsystems** and ~200 files just under `engine/graphics/`. The bulk of the value we can port for SlapPy is concentrated in **five load-bearing pillars**:

1. **Docking editor UX** (`engine/ui/DockingSystem.hpp:142-793` + `engine/editor/EditorLayoutManager.hpp`) — SlapPy already has a `notebook_*` panel constellation and dockable widgets but no true tree-based dock model with drag-drop, split ratios, tabs, and JSON round-trip. Nova3D's `DockSpace` is a self-contained ~2.7 kloc reference implementation.
2. **Deferred renderer + G-buffer** (`engine/graphics/DeferredRenderer.hpp`, `engine/graphics/GBuffer.hpp`, `engine/graphics/Renderer.hpp`) — SlapPy's `render/pipeline.py` is forward-only; porting the G-buffer + light accumulation split unlocks clustered lighting, CSM, TAA, SSAO, and every technique already listed in `project_nova3d_additions.md`.
3. **PBR material graph** (`engine/materials/*.hpp`, `engine/graphics/Material.hpp`) — SlapPy has `render/material.py::PbrMaterial` as a struct only; Nova3D ships a full node graph (`MaterialGraphEditor.hpp:1-359`, ~30 node types under `engine/materials/`) with hot-swappable evaluation.
4. **Asset browser + import pipeline** (`engine/editor/AssetBrowser.hpp:1220` lines + `engine/import/ModelImporter.hpp`, `TextureImporter.hpp`, `AnimationImporter.hpp`) — SlapPy has `asset_import/gltf_importer.py` and `notebook_content_browser.py` but no thumbnail cache, no async import outcome, no drag-drop-to-scene.
5. **Prefab + scene graph** (`engine/editor/PrefabSystem.hpp:1155` lines, `engine/scene/SceneNode.hpp:298`, `engine/entity/Entity.hpp:213`) — SlapPy has `Entity` and `Scene` (`python/slappyengine/scene.py:14-90`) but flat, no scene-graph node parenting with transform inheritance, no prefab overrides / variants / hot-reload.

The rest of Nova3D ships useful individual techniques (radiance cascades, SVGF, RTX path tracer, spectral renderer, SDF sculpting, procedural terrain, NavMesh, RTS systems) but these are either already ported (per `project_nova3d_additions.md`) or out-of-scope for a 2D-first engine.

### Subsystem inventory (17 rows)

| # | Nova3D subsystem | Source path | SlapPy equivalent | Complexity | Sprint budget |
|---|---|---|---|---|---|
| 1 | **DockSpace / panel docking** | `engine/ui/DockingSystem.hpp:142-793` (`DockNode`, `DockSpace`, `DockDragInfo`, `DockLayout`) + `.cpp:1-1872` | Partial: `python/slappyengine/ui/editor/movable_panel.py`, `dock_zones.py`, `layout_persistence.py`, `layout_presets.py`, `notebook_panel_decor.py` — no tree model | **LARGE** | 3-4 sprints |
| 2 | **Deferred renderer + G-buffer** | `engine/graphics/DeferredRenderer.hpp:1-707`, `GBuffer.hpp:1-290`, `Renderer.hpp:1-921` | `python/slappyengine/render/pipeline.py`, `render/renderer.py`, `render/passes.py` — forward-only | **LARGE** | 4-5 sprints |
| 3 | **PBR material graph** | `engine/graphics/Material.hpp:1-744`, `engine/materials/AdvancedMaterial.hpp:1-305`, `MaterialGraphEditor.hpp:1-359`, `PbrSurfaceNodes.cpp`, `NoiseNodes.cpp`, `TriplanarNodes.cpp` | `python/slappyengine/render/material.py::PbrMaterial` (struct only); notebook stub `notebook_material_editor.py`, `material_editor.py` | **LARGE** | 3-4 sprints |
| 4 | **Asset browser + thumbnails** | `engine/editor/AssetBrowser.hpp:1-1220`, `AssetThumbnailCache.hpp`, `AssetRegistry.hpp`, `AssetTypeRegistry.hpp` | `python/slappyengine/ui/editor/notebook_content_browser.py`, `content_browser.py` — no thumbnail cache | **MEDIUM** | 2 sprints |
| 5 | **Import pipeline** (`gltf`/`fbx`/`obj`) | `engine/import/ModelImporter.hpp:1-534`, `TextureImporter.hpp:1-533`, `AnimationImporter.hpp:1-461`, `AssetProcessor.hpp` | `python/slappyengine/asset_import/gltf_importer.py`, `obj_importer.py`, `texture_importer.py`, `skinned_mesh.py` — no FBX | **MEDIUM** | 2 sprints |
| 6 | **Prefab system + variants** | `engine/editor/PrefabSystem.hpp:1-1155` (nested prefabs, overrides, hot-reload) | `python/slappyengine/ui/editor/notebook_prefab_menu.py` — spawn menu only, no overrides | **MEDIUM** | 2-3 sprints |
| 7 | **Scene graph (SceneNode)** | `engine/scene/SceneNode.hpp:1-298`, `Scene.hpp:1-240` (hierarchical transforms) | `python/slappyengine/scene.py::Scene` (flat entity dict at line 17); `python/slappyengine/entity.py` | **MEDIUM** | 2 sprints |
| 8 | **Transform gizmo (3D)** | `engine/editor/TransformGizmo.hpp:1-860`, `ViewportPanel.hpp:1-268` | `python/slappyengine/ui/editor/gizmo_overlay.py`, `notebook_gizmos.py` — 2D screen-space only | **MEDIUM** | 1-2 sprints |
| 9 | **Shader hot-reload** | `engine/graphics/ShaderHotReload.hpp:1-99` (`ShaderWatchEntry`, mtime polling ~1 Hz) | None — SlapPy has `shader_gen.py`, `shader_binding.py`, `shader_stock.py`; hot-reload is manual | **SMALL** | 0.5 sprint |
| 10 | **Texture manager + streaming** | `engine/graphics/TextureManager.hpp:1-99`, `TextureAtlas.hpp`, `engine/streaming/StreamingManager.hpp` | `python/slappyengine/asset_import/texture_importer.py` (no residency mgr) | **MEDIUM** | 1-2 sprints |
| 11 | **Cascaded shadow maps + TAA** | `engine/graphics/CascadedShadowMaps.hpp:1-256`, `TAA.hpp:1-258` | Already partially ported per `project_nova3d_additions.md`; `python/slappyengine/render/shadows.py` | **DONE (SMALL polish)** | 0.5 sprint |
| 12 | **Debug draw (wireframe/normals/frustum)** | `engine/graphics/debug/DebugDraw.hpp:1-270`, `DebugShapes.cpp`, `LightGizmoBillboards.cpp`, `engine/debug/BVHVisualizer.hpp` | `python/slappyengine/ui/debug_overlay.py`, `render/bvh_3d.py` visualiser | **SMALL** | 0.5 sprint |
| 13 | **Reflection / property system** | `engine/reflection/NovaReflect.hpp`, `TypeRegistry.hpp`, `Property.cpp`, `Observable.hpp` (~14 headers) | `python/slappyengine/data_component.py`, `struct_registry.py`, notebook `property_inspector.py` | **MEDIUM** | 2 sprints |
| 14 | **AssetDatabase + JSON asset serialiser** | `engine/assets/AssetDatabase.hpp:1-288`, `JsonAssetSerializer.hpp`, `AssetPaths.hpp` | `python/slappyengine/asset_manifest.py`, `project_registry.py`, residency `slap_format.py` | **MEDIUM** | 2 sprints |
| 15 | **Editor menu system + command history** | `engine/editor/EditorMenuSystem.hpp`, `EditorCommand.hpp`, `CommandHistory.hpp` | `python/slappyengine/ui/editor/notebook_menu_bar.py`, `editor_undo.py`, `tool_router.py` | **SMALL** | 1 sprint |
| 16 | **Skeletal animation + blend trees** | `engine/animation/Animation.hpp`, `AnimationBlendTree.hpp`, `AnimationStateMachine.hpp`, `SkeletalAnimator.hpp` | `python/slappyengine/animation/skeleton_runtime.py`, `animation/` subpackage | **MEDIUM (extend existing)** | 1-2 sprints |
| 17 | **Window management (`Window.hpp`)** | `engine/core/Window.hpp:1-213`, `engine/platform/windows/WindowsPlatform.cpp` | `python/slappyengine/app.py`, `engine.py` — GLFW-less | **SMALL** | 0.5 sprint |

**Grand total sprint budget:** ~28-34 sprints to reach Nova3D parity for the 3D pipeline surface. Prioritised rollout below.

---

## Page 2 — Deep dives on top 5 integration priorities

### Priority 1 — DockSpace (windowing, nesting, populating)

**Files.** `engine/ui/DockingSystem.hpp:1-808` + `DockingSystem.cpp:1-1872`. Core types:

- `DockRect` (`DockingSystem.hpp:71-129`) — rectangle math with `Shrink`/`Expand`/`GetLeftHalf`/`GetRightHalf`/`GetTopHalf`/`GetBottomHalf` helpers.
- `DockNode` (`.hpp:142-293`) — binary tree node holding either two children + `splitDirection` + `splitRatio`, **or** a leaf with a `std::vector<EditorPanel*> panels` + `activeTabIndex`. Every node has `bounds` (`DockRect`), a `parent` weak-ref, and `isFloating` + `floatingPos`/`floatingSize` for undocked windows.
- `DockDragInfo` (`.hpp:316-324`) — full drag state machine (`Dragging`, `PreviewLeft/Right/Top/Bottom/Center/Floating`, `hoveredZone`, `detached`).
- `DockLayout::NodeLayout` (`.hpp:333-353`) — serialisable per-node record with **`flexBasis` + `flexGrow`** (SP1-A03-W2 note in source) so a saved layout restores to exactly the same proportions on reload.
- `DockSpace` (`.hpp:375-792`) — the manager. Notable API: `AddPanel(panel, DockPosition, relativeTo)`, `SplitNode(node, direction, ratio=0.5)`, `BeginDrag/UpdateDrag/EndDrag`, `IsOverSplitter`, `SaveLayout/LoadLayout`, `ToLayoutTree`/`SolveAndApplyLayout` (flex bridge), `ToJson`/`FromJson`, and three preset layouts `CreateDefaultLayout`, `CreateCompactLayout`, `CreateWideLayout`.

**Docking algorithm** (from the `.hpp` contract):
1. Panels live only in **leaf** `DockNode`s. Splits are pure structural nodes with a ratio.
2. Drop zones are computed each drag frame (`CollectDropZones` → `FindBestDropZone`). Zones live at each leaf's four edges + centre + a floating catch-all.
3. On drop, `DockPanelToNode(panel, target, position)` either **inserts a tab** (if `Center`) or **splits the target** in the requested direction using the parent's existing split axis when possible.
4. On panel removal, `RemoveEmptyNodes` + `CollapseEmptyNode` walk up and merge single-child splits back into their parent so the tree stays canonical.
5. Layout persistence: `SaveLayout` writes the tree as flat `NodeLayout` records keyed by `id` + `parentId`; `LoadLayout` re-links via a `panelMap` (id → `EditorPanel*`) and silently drops unregistered panels.
6. Callbacks: `OnLayoutChanged`, `OnPanelDocked`, `OnPanelUndocked`, `OnPanelClosed` fire from inside `DockSpace` so panel-side listeners can rewire.

**SlapPy port target.** New module `python/slappyengine/ui/editor/dock_space.py` mirroring `DockNode`/`DockSpace` in pure Python. SlapPy already has `movable_panel.py`, `dock_zones.py`, `layout_persistence.py` — those become the drag/drop primitives; the tree model is new. The `flexBasis`/`flexGrow` layout bridge maps directly onto `python/slappyengine/ui/runtime/layout.py`.

**Complexity: LARGE, 3-4 sprints.** Split as W1: `DockNode`+`DockSpace` tree + `AddPanel`/`RemovePanel`/`SplitNode`; W2: drag/drop + preview overlay; W3: JSON round-trip + preset layouts; W4: flex bridge + resize handles.

### Priority 2 — Deferred renderer + G-buffer

**Files.** `engine/graphics/DeferredRenderer.hpp:1-707`, `GBuffer.hpp:1-290`, `Renderer.hpp:1-921`.

Nova3D's G-buffer layout is standard 4-target MRT: albedo+roughness (RGBA8), normal+metallic (RGB10A2 or RGBA16F), motion+material-id (RG16F+RG8), depth (D32F). The lighting pass reads all four, applies clustered lighting (`ClusteredLighting.hpp`, `ClusteredLightingExpanded.hpp`), reads CSM shadows (`CascadedShadowMaps.hpp:1-256`), then runs post-process (`engine/postprocess/PostProcess.hpp`). `Light` struct at `DeferredRenderer.hpp:39-118` is GPU-friendly SSBO layout with `LightType::{Directional, Point, Spot, Area}`, `castsShadows`, `shadowMapIndex`, and factory helpers `CreateDirectional`/`CreatePoint`/`CreateSpot`.

**SlapPy port target.** New `python/slappyengine/render/deferred.py` + WGSL shaders. `PbrMaterial` already exists (`render/material.py`) and `render/light.py` has a light struct — extend for GPU-friendly packing. `render/shadows.py` already ports CSM per `project_nova3d_additions.md`, so the deferred pipeline just consumes it. Split as W1: G-buffer creation + geometry pass; W2: light accumulation; W3: motion vectors + TAA hookup; W4: clustered lighting SSBO port; W5: material-ID debug view + integration into `Layer3D`.

**Complexity: LARGE, 4-5 sprints.**

### Priority 3 — PBR material graph

**Files.** `engine/materials/` (52 files). Key nodes: `PbrSurfaceNodes.cpp`, `NoiseNodes.cpp`, `TriplanarNodes.cpp`, `BloomNodes.cpp`, `ColorGradeNodes.cpp`, `TonemapNodes.cpp`, `DistanceDrivenNodes.cpp`, `RadianceProbeNodes.cpp`, `SDFShaderNodes.cpp`, `VolumetricFogNodes.cpp`. Editor UI: `MaterialGraphEditor.hpp:1-359` + `engine/editor/MaterialEditor.hpp`, `MaterialEditorAdvanced.hpp`, `MaterialAssetEditor.hpp`. Advanced-material struct (`AdvancedMaterial.hpp:1-305`) covers Sellmeier IOR dispersion, subsurface scattering, volumetric (Rayleigh/Mie).

**SlapPy port target.** Extend `python/slappyengine/render/material.py::PbrMaterial` into a graph model in a new `python/slappyengine/render/material_graph.py`. SlapPy already has a `notebook_node_editor.py` and `node_graph_panel.py` — the node inventory maps directly. WGSL generation goes through the existing `shader_gen.py` pipeline. Ship the graph in three tiers: (1) surface (albedo/normal/roughness/metallic + emissive), (2) procedural (noise/triplanar/gradients), (3) advanced (SSS, dispersion, volumetric).

**Complexity: LARGE, 3-4 sprints.**

### Priority 4 — Asset browser + thumbnail cache

**Files.** `engine/editor/AssetBrowser.hpp:1-1220`. Key features from the header preamble:
- View modes: Grid / List / Column
- Folder tree navigation with breadcrumbs
- Drag-and-drop for moving files **and** instantiating in scene (via `Window::Callbacks::onFileDrop` at `Window.hpp:39-42` for OS-level Explorer drops)
- Multi-selection + batch operations
- Async thumbnail generation with caching (`AssetThumbnailCache.hpp`)
- Search / filter by name / type
- Context menus for file operations
- `AssetType` enum: `Unknown, Folder, SDFModel, Mesh, Texture, Material, Animation, Audio, ...`

**SlapPy port target.** Expand `python/slappyengine/ui/editor/notebook_content_browser.py` into a real asset browser. Thumbnail cache = new `python/slappyengine/asset_import/thumbnail_cache.py` that uses `PIL` for image formats and `render/renderer.py` off-screen for meshes. Async pipeline = threaded via existing `python/slappyengine/telemetry/` infra.

**Complexity: MEDIUM, 2 sprints.**

### Priority 5 — Prefab system with overrides + variants

**Files.** `engine/editor/PrefabSystem.hpp:1-1155`. Features: prefab creation, instantiation, per-instance overrides, prefab variants, nested prefabs, hot-reload, undo/redo integration via `CommandHistory`.

**SlapPy port target.** New `python/slappyengine/prefab.py` + editor panel `python/slappyengine/ui/editor/prefab_panel.py`. Under the hood, a prefab is a serialised `Entity` subtree; instantiation copies + records an override table keyed by property path (`transform.position`, `mesh_material.albedo`, etc.). SlapPy's `serialize.py` + `slap_format.py` (residency) already provide the on-disk format.

**Complexity: MEDIUM, 2-3 sprints.**

---

## Page 3 — Window management + editor UX lessons from Nova3D

### 3.1 Window layer (`engine/core/Window.hpp:1-213`)

Nova3D wraps GLFW behind a thin `Window` class that exposes a `Callbacks` struct (line 32-43): `onResize`, `onFocus`, `onClose`, and — critical for asset workflow — `onFileDrop(std::vector<std::string>)`. The OS-level drag-drop from Explorer/Finder flows into `AssetBrowser::HandleExternalFileDrop`. `CreateParams` (line 44+) defaults to 1920×1080 with a plain string title.

**SlapPy lesson.** `python/slappyengine/app.py` has an App class but no OS drop callback surface. Adding an `on_file_drop` hook (SlapPy runs on wgpu + winit under the hood via wheels) lets the asset browser accept native drops. Small dependency: expose the winit `WindowEvent::DroppedFile` variant through the Rust `_core` extension.

### 3.2 EditorApplication as central coordinator

`engine/editor/EditorApplication.hpp:1-1622` is a **1600-line orchestrator**. From the doc comment (lines 1-16) it manages:
- Panel registration and lifecycle
- Menu bar + toolbar rendering
- Project + scene management
- Selection + command systems (`EditorSelectionManager.hpp`, `CommandHistory.hpp`)
- Settings + preferences (`EditorSettings.hpp`, `PreferencesPanel.hpp`)
- Notifications + status display

**SlapPy analogue.** `python/slappyengine/ui/editor/shell.py` (~"shell" is the entry point) plus `notebook_menu_bar.py`, `toolbar.py`, `editor_undo.py`, `scene_outliner.py`, `property_inspector.py`. These are already reasonably good; the missing piece is a **single `EditorApplication` class** that owns them all and exposes lifecycle hooks (`Init`, `Update`, `Render`, `Shutdown`) — currently SlapPy's editor is a bag of loose panels bound by `tool_router.py`.

### 3.3 Docking primitive re-cap

See Page 2 § Priority 1 for the tree model. The key take-aways for editor UX beyond docking mechanics:

- **Three preset layouts ship out of the box** (`CreateDefaultLayout`, `CreateCompactLayout`, `CreateWideLayout` at `DockingSystem.hpp:699-712`). SlapPy has `baked_layouts/` and `default_layouts.py`, `layout_presets.py` — the preset infrastructure is there; what's missing is a coherent default layout with left=Hierarchy, right=Inspector, bottom=Console/Assets, centre=Viewport.
- **Tabs are first-class** (`DockNode.panels` is a `vector`; `activeTabIndex` tracks selection). SlapPy has `notebook_tab.py` widget but no dock-integrated tab-bar rendering.
- **Splitters expose reset** (`ResetSplitter(node)` at `DockingSystem.hpp:561`). A right-click on a splitter reverts it to `0.5`. Simple UX detail worth stealing.

### 3.4 Viewport panel + gizmo integration

`engine/editor/ViewportPanel.hpp:1-268` renders the scene into an offscreen framebuffer, presents it as an `ImGui::Image` inside a normal `EditorPanel`, and integrates `ViewportControls` (Maya-style orbit/pan/zoom), `TransformGizmo`, and `RayPicker`. `RenderMode` enum (line 51+) has debug views for **shadow maps (directional / point / spot)**, **normals**, **wireframe**, **unlit**, **SDF**, plus `kFirstDebugMode` for full-screen internal-buffer visualisation — a lightweight in-editor renderdoc.

**SlapPy lesson.** `python/slappyengine/ui/editor/viewport_panel.py` exists but is 2D-oriented. A `Viewport3DPanel` that owns a `MeshRenderer` (from `python/slappyengine/gpu/mesh_renderer.py`) and mirrors Nova3D's `RenderMode` enum would be the fastest way to give SlapPy real 3D editing.

### 3.5 Transform gizmo mechanics

`engine/editor/TransformGizmo.hpp:1-860`. `GizmoMode::{Translate, Rotate, Scale}`, `GizmoSpace::{World, Local}`, `GizmoAxis` bitmask (`X=1, Y=2, Z=4`, XY=X|Y, etc.). Screen-space sizing keeps handles at constant visual size irrespective of camera distance. Snapping is built in.

**SlapPy analogue.** `notebook_gizmos.py` + `gizmo_overlay.py` — 2D screen-space only. Port the `GizmoAxis` bitmask + screen-space sizing math; the render side reuses `DebugDraw`.

### 3.6 Right-click contextual menus + spawn

`engine/editor/EditorMenuSystem.hpp` centralises menu registration. `engine/editor/AssetCreationDialog.hpp` handles right-click "Create → …". `engine/editor/PrefabSystem` "Instantiate here" flows through the same menu system. SlapPy's `python/slappyengine/ui/editor/spawn_menu.py` + `notebook_spawn_menu.py` + `notebook_spawn_menu_svgs.py` already cover 90% of this — the remaining work is unifying the entry points so the same registration flows both to menu bar and to context menu.

### 3.7 Keyboard nav + command palette

`engine/editor/EditorCommand.hpp` + `CommandHistory.hpp` implement a typed command pattern (each user action is a `Command` object that captures its undo state). SlapPy has `python/slappyengine/ui/editor/notebook_command_palette.py` + `editor_undo.py` — the palette is command-driven but only bridges to `tool_router.py`; a proper `Command` base class with `Do`/`Undo` methods would tighten it.

### 3.8 Panel layout persistence

`engine/editor/EditorLayoutManager.hpp:1-374` defines `LayoutPreset` (name, description, `iniData` blob, `isBuiltIn`, `isDefault`) and `PanelState` for per-panel state persistence. SlapPy has `layout_persistence.py`, `layout_baker.py`, `baked_layouts/`, `layout_presets.py` — most of the storage layer is here; wiring it to the new `DockSpace` is the port target.

### 3.9 Icons

**How Nova3D handles them.** No Emoji fallback anywhere in the tree. Icons are (a) rendered thumbnails cached by `AssetThumbnailCache` for asset-browser entries, (b) `LightGizmoBillboards.cpp` for in-scene light icons (billboarded quads with alpha-cut textures), (c) toolbar icons are baked PNGs bundled with the editor. `tools/asset_media_renderer/` regenerates them from source with the same C++ pipeline (per `CLAUDE.md:52-58`).

**SlapPy lesson.** SlapPy uses SVG icons (`notebook_spawn_menu_svgs.py`) — this already beats Nova3D's PNG approach for scaling. Keep SVG; add a **thumbnail cache** that renders 3D assets through `render/renderer.py` off-screen.

---

## Page 4 — 2D + 3D layer merging architecture

### 4.1 Current state of SlapPy `Layer`

`python/slappyengine/layer.py:65-278`. Key observations:

- `Layer.__init__` (line 66) accepts `mode: str = "2D"` — 3D is already a first-class variant.
- `Layer.mesh_geometry` (line 101) is a `GpuMesh | None` and `Layer.mesh_material` (line 102) is a `PbrMaterial | None`. **The 3D scaffolding is already in the `Layer` class.**
- `Layer._renderer` (line 108) holds a `MeshRenderer` set by the engine when 3D draw begins.
- Cross-layer baking already exists: `bake_to_2d` (line 157) renders a 3D layer to a texture; `apply_heightmap` (line 188), `apply_normal_map` (line 233), `apply_albedo` (line 258) go the other direction (2D → 3D material inputs).
- `Layer2D` subclass exists (line 280) but there is **no explicit `Layer3D`** — `mode="3D"` on the base class is the current pathway.

`python/slappyengine/scene.py::Scene` (line 14-90) holds a flat `_entities: dict[str, Entity]`, a `Camera`, `_z_layers: list[ZLayer]` sorted by z ascending (line 71-73), and calls `entity.tick(dt)` in a loop. **Layers today are held on the entity side** (via `entity.layers`), not on `Scene` directly.

### 4.2 Design decision: subclass `Layer` for `Layer3D`

**Recommendation.** Introduce `Layer3D(Layer)` as a **sibling to `Layer2D`** rather than a separate root class. Rationale:

1. `Layer.mesh_geometry` + `mesh_material` + `bake_to_2d` already assume `mode="3D"` is a valid Layer state. Formalising it as `Layer3D` documents intent + gates the 3D-only APIs behind a type check.
2. Existing `Layer` methods (blend mode, opacity, visible, `attach_script`, scripts) all remain useful for 3D layers — a 2D HUD painted over a 3D scene wants the same `blend_mode="add"` semantics.
3. `Entity.add_layer(Layer)` doesn't care about the concrete subclass — no API breakage.

### 4.3 API sketch

```python
# python/slappyengine/layer.py (new subclass, alongside Layer2D)
class Layer3D(Layer):
    """3D layer holding a mesh + material + world-space transform.

    Renders through the deferred pipeline into the layer's own render target,
    then composites back into the parent Scene's frame using the layer's
    blend_mode + opacity — identical to how Layer2D pixels composite.
    """

    def __init__(
        self,
        name: str = "layer3d",
        mesh: "GpuMesh | None" = None,
        material: "PbrMaterial | None" = None,
        transform: "Transform3D | None" = None,
        camera: "Camera3D | None" = None,
    ):
        super().__init__(name=name, mode="3D")
        self.mesh_geometry = mesh
        self.mesh_material = material
        self.transform = transform or Transform3D()   # 6-DOF (pos, rot, scale)
        self.camera = camera                          # None -> inherit scene camera
        self._render_target: "wgpu.Texture | None" = None

    @classmethod
    def from_gltf(cls, path: str | Path, name: str | None = None) -> "Layer3D":
        from slappyengine.asset_import.gltf_importer import import_gltf
        result = import_gltf(path)
        return cls(name=name or Path(path).stem,
                   mesh=result.mesh, material=result.material)

    def render(self, ctx) -> "wgpu.Texture":
        """Render this 3D layer to its render target and return the texture."""
        if self._render_target is None:
            self._render_target = ctx.create_target(*self.size)
        # ... deferred pipeline pass ...
        return self._render_target
```

### 4.4 Scene composition — render order

**Semantics.** Every `Layer` (2D or 3D) becomes an **image** that composites into the final frame. The composition order is `entity.z_order` (existing SlapPy semantic — see `Scene.load` at `scene.py:116`). Within an entity, layers stack by declaration order. This means:

- A `Layer2D` HUD layer with `z_order=100` naturally overlays a `Layer3D` world layer at `z_order=0`.
- Multiple `Layer3D`s at the same `z_order` composite by declaration order — useful for e.g. a foreground character layer over a background environment layer, both 3D.
- The **existing 2D compositor stays authoritative**: `Layer3D.render()` produces a wgpu texture, which the 2D compositor treats identically to a `Layer2D`'s `visual_texture`.

This is the simplest and least invasive path. Alternative approach (**interleave by world-space z**) is rejected because it forces every 3D layer to share the same camera + coordinate space, which defeats the "layer is a self-contained render unit" invariant that makes SlapPy's Layer system predictable.

### 4.5 Camera reconciliation

Two options per layer:
- **`Layer3D.camera = None`** — inherit the `Scene`'s camera. When the scene camera is a `Camera` (2D ortho), we build a synthetic `Camera3D` with the same viewport, ortho projection, and the scene's world-XY plane as the view frustum. This lets a top-down 2D game insert a 3D building layer without changing the scene camera.
- **`Layer3D.camera = <Camera3D>`** — layer supplies its own. Useful for a 3D minimap in the corner of a 2D game, or for a 3D character sheet rendered into a HUD.

The 2D compositor already handles the case where a layer's texture doesn't match the scene resolution (`Layer.bake_to_2d(size, camera)`); we reuse that pathway.

### 4.6 Transform propagation

- **`Layer2D`**: 3-DOF transform lives on the parent `Entity` (`position: (x, y)`, `rotation: float`, `scale: (sx, sy)`). Unchanged.
- **`Layer3D`**: adds a `Transform3D` object with `position: vec3`, `rotation: quat`, `scale: vec3`. When the parent `Entity` moves in 2D, we lift the `(x, y)` to `(x, y, 0)` and apply as a translation on top of `Layer3D.transform`. Rotation about entity Z becomes rotation about layer Z.

For **deep hierarchies** (e.g. a 3D turret sitting on a 3D tank on a 2D world), users can nest `Layer3D`s via `Entity` parenting — SceneNode-style hierarchy is a **future** improvement (Priority 7 in the inventory) but not required for the first `Layer3D` MVP.

### 4.7 Migration plan for existing 2D users

1. **v0.4.x**: land `Layer3D` behind a feature flag. Existing `Layer(mode="3D")` continues to work identically — `Layer3D` is an ergonomic subclass, not a replacement. Zero break.
2. **v0.5.0**: deprecate direct `Layer(mode="3D")` construction (soft warning); recommend `Layer3D(...)` in docs.
3. **v0.6.0**: `mode="3D"` on the base class emits a `DeprecationWarning`.
4. **v1.0.0**: `Layer3D` is the only supported form. `Layer` becomes an abstract base with two concrete subclasses `Layer2D` and `Layer3D`.

This mirrors the graceful deprecation cadence already established in `docs/api_stability_2026_07_07.md`.

### 4.8 What this enables

Once `Layer3D` is a first-class citizen:

- **Mixed 2D+3D games** — a top-down 2D shooter can drop 3D vehicles as `Layer3D` entities without rewriting the scene camera.
- **HUD-over-3D** — a 3D world with 2D UI layers on top uses the standard `blend_mode="normal"` compositor.
- **3D-in-2D-widgets** — an editor panel can host a `Layer3D` mesh preview by asking the layer for its render target texture.
- **Cross-layer baking** already supports 2D → 3D (heightmap, normal, albedo) and 3D → 2D (`bake_to_2d`) — extending these becomes trivial with the type distinction.

---

## Appendix — Source-file reference for follow-up sprints

### Nova3D reference files (read-only)

| Concern | Path |
|---|---|
| Docking tree + drag/drop | `H:/Github/Nova3D/engine/ui/DockingSystem.hpp`, `.cpp` |
| Editor coordinator | `H:/Github/Nova3D/engine/editor/EditorApplication.hpp` (1622 lines) |
| Layout persistence | `H:/Github/Nova3D/engine/editor/EditorLayoutManager.hpp` |
| Asset browser | `H:/Github/Nova3D/engine/editor/AssetBrowser.hpp` (1220 lines) |
| Asset thumbnail cache | `H:/Github/Nova3D/engine/editor/AssetThumbnailCache.hpp` |
| Viewport panel | `H:/Github/Nova3D/engine/editor/ViewportPanel.hpp` |
| Transform gizmo | `H:/Github/Nova3D/engine/editor/TransformGizmo.hpp` (860 lines) |
| Prefab system | `H:/Github/Nova3D/engine/editor/PrefabSystem.hpp` (1155 lines) |
| Scene outliner | `H:/Github/Nova3D/engine/editor/SceneOutliner.hpp` |
| Scene graph | `H:/Github/Nova3D/engine/scene/Scene.hpp`, `SceneNode.hpp` |
| Deferred renderer | `H:/Github/Nova3D/engine/graphics/DeferredRenderer.hpp` (707 lines) |
| G-buffer | `H:/Github/Nova3D/engine/graphics/GBuffer.hpp` |
| PBR material | `H:/Github/Nova3D/engine/graphics/Material.hpp` (744 lines) |
| Advanced material (SSS, dispersion) | `H:/Github/Nova3D/engine/materials/AdvancedMaterial.hpp` |
| Material graph editor | `H:/Github/Nova3D/engine/materials/MaterialGraphEditor.hpp` |
| Shader hot-reload | `H:/Github/Nova3D/engine/graphics/ShaderHotReload.hpp` |
| Texture manager | `H:/Github/Nova3D/engine/graphics/TextureManager.hpp` |
| Cascaded shadow maps | `H:/Github/Nova3D/engine/graphics/CascadedShadowMaps.hpp` |
| TAA | `H:/Github/Nova3D/engine/graphics/TAA.hpp` |
| Debug draw | `H:/Github/Nova3D/engine/graphics/debug/DebugDraw.hpp` |
| Model importer | `H:/Github/Nova3D/engine/import/ModelImporter.hpp` |
| Texture importer | `H:/Github/Nova3D/engine/import/TextureImporter.hpp` |
| Animation importer | `H:/Github/Nova3D/engine/import/AnimationImporter.hpp` |
| Entity | `H:/Github/Nova3D/engine/entity/Entity.hpp` |
| Window | `H:/Github/Nova3D/engine/core/Window.hpp` |
| Engine | `H:/Github/Nova3D/engine/core/Engine.hpp` |
| Asset database | `H:/Github/Nova3D/engine/assets/AssetDatabase.hpp` |

### SlapPy touchpoints (docs only — no code changes in this landing)

| Concern | Path |
|---|---|
| Layer base + subclasses | `H:/Github/SlapPyEngine/python/slappyengine/layer.py` |
| Scene | `H:/Github/SlapPyEngine/python/slappyengine/scene.py` |
| Entity | `H:/Github/SlapPyEngine/python/slappyengine/entity.py` |
| Render pipeline | `H:/Github/SlapPyEngine/python/slappyengine/render/pipeline.py` |
| PBR material | `H:/Github/SlapPyEngine/python/slappyengine/render/material.py` |
| 3D scene walker | `H:/Github/SlapPyEngine/python/slappyengine/render/scene_walker.py` |
| Shadows | `H:/Github/SlapPyEngine/python/slappyengine/render/shadows.py` |
| glTF importer | `H:/Github/SlapPyEngine/python/slappyengine/asset_import/gltf_importer.py` |
| Editor shell | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/shell.py` |
| Dock zones + movable panel | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/dock_zones.py`, `movable_panel.py` |
| Layout persistence | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/layout_persistence.py`, `layout_baker.py`, `layout_presets.py` |
| Content browser | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/notebook_content_browser.py` |
| Property inspector | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/property_inspector.py` |
| Gizmos | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/notebook_gizmos.py`, `gizmo_overlay.py` |
| Material editor stub | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/notebook_material_editor.py`, `material_editor.py` |
| Node graph editor | `H:/Github/SlapPyEngine/python/slappyengine/ui/editor/notebook_node_editor.py`, `node_graph_panel.py` |

### Ranked integration roadmap (dependency-ordered)

1. **W1 (SMALL, 0.5 sprint)** — Shader hot-reload (`ShaderHotReload.hpp` → `render/shader_hot_reload.py`). No prereqs. Unlocks the material-graph iteration loop.
2. **W2 (MEDIUM, 2 sprints)** — SceneNode + hierarchical transforms (`SceneNode.hpp` → `scene_node.py`). Prereq for `Layer3D`, prefabs.
3. **W3 (MEDIUM, 2 sprints)** — `Layer3D` class + Scene composition semantics. Depends on W2.
4. **W4 (LARGE, 4 sprints)** — Deferred renderer + G-buffer. Depends on W3.
5. **W5 (LARGE, 3 sprints)** — Docking tree + drag/drop. Independent; can run parallel.
6. **W6 (MEDIUM, 2 sprints)** — Asset browser + thumbnail cache. Depends on W5.
7. **W7 (LARGE, 3 sprints)** — Material graph. Depends on W1, W4.
8. **W8 (MEDIUM, 2 sprints)** — Prefab system. Depends on W2.
9. **W9 (SMALL, 0.5 sprint)** — Debug draw port. Depends on W3.
10. **W10 (MEDIUM, 2 sprints)** — Import pipeline expansion (FBX + async). Depends on W6.

**Total:** ~21 sprints to reach a coherent "Nova3D-parity 3D pipeline inside SlapPy" milestone. The 28-34 sprint figure in the executive summary is the full parity ceiling; the 21-sprint figure is the minimum viable integration.
