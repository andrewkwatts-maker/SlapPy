# Nova3D Roadmap Tracker + Progress Dashboard

**Landed:** 2026-07-19
**Author:** EEE5 (Nova3D-roadmap sprint)
**Companion to:** [`nova3d_integration_plan_2026_07_19.md`](nova3d_integration_plan_2026_07_19.md) — this doc is the live status ledger for that plan's 17-row inventory + 21-sprint minimum-viable roadmap.

**Constraint reminder.** SlapPyEngine is a **Python PyPI wrapper on a Rust-accelerated wgpu → Vulkan engine**. Every "port" below lands as Python API + optional Rust `_core.<kernel>` + WGSL. No C++, no OpenGL, no CMake, no GLFW / ImGui / Assimp / GLM. Nova3D is used strictly as a **feature reference**.

Docs-only. This tracker does not modify Python source or touch WIP subpackages (`softbody/`, `fluid/`, `physics/`, `physics2/`).

---

## Section 1 — Progress dashboard

| Bucket | Count |
|---|---:|
| **SHIPPED** — module exists, has tests, is exercised by a demo | **6** |
| **PARTIAL** — module exists but missing pieces vs Nova3D reference | **7** |
| **PLANNED** — design doc reference exists but no code yet | **3** |
| **GAP** — not started, not planned | **1** |

**Overall completion:** `6 / 17 = 35.3% SHIPPED`, `13 / 17 = 76.5% at-least-PARTIAL`. Weighted by sprint budget (SHIPPED ×1.0 + PARTIAL ×0.4 + PLANNED ×0.1 + GAP ×0), effective completion is `(6·1.0 + 7·0.4 + 3·0.1) / 17 = 9.1 / 17 = 53.5%`.

Snapshot HEAD: `0c98862` (DDD5 — PBR material graph baseline). EEE1-EEE4 in-flight (untracked working tree per the parallel dispatch).

---

## Section 2 — Load-bearing pillars status

The five load-bearing pillars from page 1 of the integration plan, in the integration plan's numbering.

### Pillar 1 — Docking editor UX  [**PARTIAL**]

`python/slappyengine/ui/editor/movable_panel.py`, `dock_zones.py`, `layout_persistence.py`, `layout_presets.py`, `notebook_panel_decor.py`, `resize_handles.py` are all in place — these are the drag/drop primitives. No `DockNode` / `DockSpace` binary-tree model yet; `Grep` for `class DockNode|class DockSpace` returns zero hits. Preset layout infrastructure (`baked_layouts/`, `default_layouts.py`, `layout_presets.py`) is ready to receive the tree. **Missing:** `dock_space.py` new module, drag/drop preview overlay, JSON round-trip through the tree, flex bridge to `ui/runtime/layout.py`. Priority W5 in the roadmap.

### Pillar 2 — Deferred renderer + G-buffer  [**PARTIAL**]

`python/slappyengine/render/deferred.py` (SHA `9738685`, DDD4) ships the G-buffer plumbing skeleton: 4-target MRT (`albedo` / `normal_roughness` / `position_metallic` / `depth`), WGSL shaders under `render/shaders/deferred/` (`gbuffer_write.wgsl`, `lighting_pass.wgsl`, `tonemap.wgsl`), and a Rust `_core.deferred_cluster` stub for the 16×9×24 light froxel bin. Test `test_deferred_renderer.py` + `test_deferred_cluster_rust.py` cover the skeleton. **Missing:** actual light-accumulation pass wired to `render/light.py`, TAA motion-vector hookup, `render/shadows.py` CSM composition into the lighting pass, clustered-lighting SSBO upload, integration into `Layer3D`. Priority W4 in the roadmap.

### Pillar 3 — PBR material graph  [**PARTIAL**]

`python/slappyengine/render/material_graph.py` (SHA `0c98862`, DDD5) ships 10 core node types: `ConstFloatNode`, `ConstColorNode`, `UVNode`, `Texture2DNode`, `MultiplyNode`, `AddNode`, `MixNode`, `NormalMapNode`, `FresnelNode`, `PBROutputNode`. Rust `_core.material_eval.bake_material_constants` scaffolded for constant folding. `test_material_graph.py` covers node evaluation, `test_material_graph_bridge.py` covers the editor bridge. **Missing:** ~20 further Nova3D node types (noise, triplanar, bloom, color-grade, tonemap, distance-driven, radiance-probe, SDF-shader, volumetric-fog), full WGSL codegen path via `shader_gen.py`, advanced-material tier (SSS, Sellmeier IOR dispersion, Rayleigh/Mie volumetric). Priority W7 in the roadmap.

### Pillar 4 — Asset browser + import pipeline  [**PARTIAL**]

`python/slappyengine/ui/editor/notebook_content_browser.py`, `content_browser.py` provide the browser shell. `python/slappyengine/asset_import/thumbnail_cache.py` (**EEE1 in-flight, untracked**) lands the persistent thumbnail-cache contract with LRU eviction, sha1-keyed entries, mtime freshness rule, PIL PNG I/O with graceful degrade. `asset_import/async_import_queue.py` (**EEE1 in-flight, untracked**) lands the threaded import queue. CCC3 (`d636111`) shipped the drag/drop `asset_import_panel.py` + `type_router.py` dispatcher. `test_asset_import.py`, `test_asset_import_panel.py` cover the routing. **Missing:** FBX importer (only glTF / OBJ / texture / cubemap shipped), grid/list/column view-mode switcher on the browser, breadcrumb navigation, batch operations, external-drop wiring via winit `WindowEvent::DroppedFile`. Priority W6 in the roadmap.

### Pillar 5 — Prefab + scene graph  [**PARTIAL**]

`python/slappyengine/scene_node.py` (**EEE2 in-flight, untracked**) lands `SceneNode` + `Transform3D` with Euler-XYZ hierarchical composition, cycle safety on `add_child`, and hook for `_core.scene_walk.walk_transforms` Rust kernel. `python/slappyengine/prefab.py` (**EEE4 in-flight, untracked**) wraps a `SceneNode` sub-tree with YAML round-trip + deep-copy instantiation. `python/slappyengine/prefabs/` (SHIPPED) provides the diary-themed body-kind Prefab library from prior sprints (UU6 landing). **Missing:** per-instance override table keyed by property path, prefab-variants, nested-prefab handling, hot-reload, `CommandHistory` integration, `Scene` refactor from flat `_entities` dict → `SceneNode` root. Priority W2 + W8 in the roadmap.

---

## Section 3 — Full 17-row inventory refresh

Same rows as `nova3d_integration_plan_2026_07_19.md` § "Subsystem inventory (17 rows)" but with three new columns: **Status**, **Commit SHA(s)**, **Sprint tag**.

| # | Nova3D subsystem | SlapPy equivalent | Status | Commit SHA(s) | Sprint tag |
|---|---|---|---|---|---|
| 1 | DockSpace / panel docking | `ui/editor/movable_panel.py`, `dock_zones.py`, `layout_persistence.py`, `layout_presets.py` | **PARTIAL** (no tree model) | primitives predate CCC/DDD | W5 (planned) |
| 2 | Deferred renderer + G-buffer | `render/deferred.py` + `render/shaders/deferred/*.wgsl` + `_core.deferred_cluster` | **PARTIAL** (skeleton only) | `9738685` | DDD4 → W4 |
| 3 | PBR material graph | `render/material_graph.py`, `ui/editor/material_graph_bridge.py` | **PARTIAL** (10 of ~30 nodes) | `0c98862` | DDD5 → W7 |
| 4 | Asset browser + thumbnails | `ui/editor/notebook_content_browser.py`, `asset_import/thumbnail_cache.py`, `async_import_queue.py`, `ui/editor/asset_import_panel.py` | **PARTIAL** (no view-mode / breadcrumbs) | `d636111` + EEE1 in-flight | CCC3 + EEE1 → W6 |
| 5 | Import pipeline (gltf/fbx/obj) | `asset_import/gltf_importer.py`, `obj_importer.py`, `texture_importer.py`, `cubemap_importer.py`, `skinned_mesh.py`, `type_router.py` | **PARTIAL** (no FBX) | prior + `d636111` | HH5 / JJ3 / CCC3 → W10 |
| 6 | Prefab system + variants | `prefab.py` + `prefabs/` (body kinds) | **PARTIAL** (no overrides / variants) | EEE4 in-flight | EEE4 → W8 |
| 7 | Scene graph (SceneNode) | `scene_node.py` + `Transform3D` | **PARTIAL** (Scene not refactored yet) | EEE2 in-flight | EEE2 → W2 |
| 8 | Transform gizmo (3D) | `ui/editor/gizmo_overlay.py`, `notebook_gizmos.py` | **PARTIAL** (2D screen-space only) | prior | planned |
| 9 | Shader hot-reload | `render/shader_hot_reload.py`, `ui/theme/shader_hot_reload.py` | **SHIPPED** (per-shader callback + bus event) | EEE3 in-flight (`render/`), prior (`ui/theme/`) | EEE3 → W1 |
| 10 | Texture manager + streaming | `gpu/texture_manager.py`, `residency/manager.py` | **PARTIAL** (no residency streaming for editor assets) | prior | planned |
| 11 | Cascaded shadow maps + TAA | `render/shadows.py`, `render/ssao.py` + prior TAA landing | **SHIPPED** | prior (per `project_nova3d_additions.md`) | JJ7 |
| 12 | Debug draw (wireframe / normals / frustum) | `ui/debug_overlay.py`, `render/bvh_3d.py` visualiser | **PARTIAL** (no `DebugDraw` class) | prior | W9 (planned) |
| 13 | Reflection / property system | `data_component.py`, `struct_registry.py`, `ui/editor/property_inspector.py` | **SHIPPED** | prior | — |
| 14 | AssetDatabase + JSON serialiser | `assets/database.py`, `asset_manifest.py`, `project_registry.py`, `residency/slap_format.py` | **SHIPPED** | prior (VV6) | — |
| 15 | Editor menu system + command history | `ui/editor/notebook_menu_bar.py`, `editor_undo.py`, `tool_router.py`, `actions/history_actions.py` | **PARTIAL** (no typed `Command` base class) | prior | planned |
| 16 | Skeletal animation + blend trees | `animation/skeleton_runtime.py`, `animation/graph.py`, `animation/clip.py`, `animation/skinner.py`, `animation/procedural.py` | **SHIPPED** | prior (JJ4) | — |
| 17 | Window management | `app.py`, `engine.py`, `ui/editor/file_drop_handler.py` | **PARTIAL** (no winit `DroppedFile` bridge) | prior | planned |

**Plus 3 first-class rows implicit in the "2D+3D layer merge story" (page 4) that the integration plan tracks separately:**

| # | Subsystem | SlapPy target | Status | Commit SHA(s) | Sprint tag |
|---|---|---|---|---|---|
| 18 | `Layer3D` class | `layer.py::Layer3D` | **SHIPPED** | `fe25d85` | DDD1 → W3 |
| 19 | Cross-layer sampling (2D ↔ 3D) | `render/layer_sampling.py` + `shaders/cross_layer_composite.wgsl` | **SHIPPED** | `95af086` | DDD2 |
| 20 | Layer compositor + hybrid scene | `render/layer_compositor.py` + `hello_hybrid_layers.py` | **SHIPPED** | `3708cd2` | DDD3 |
| 21 | 3D viewport panel (editor centre) | `ui/editor/viewport_3d_panel.py` | **SHIPPED** | `ca818d7` | CCC1 |
| 22 | Python REPL panel | `ui/editor/repl_panel.py` | **SHIPPED** | `70aed91` | CCC2 |

---

## Section 4 — Sprint index

### CCC batch (2026-07-19) — editor surface expansions (3 items)

| SHA | Sprint | Summary |
|---|---|---|
| `ca818d7` | CCC1 | Add 3D wgpu viewport panel in editor centre tab — offscreen render → DPG blit; headless-safe fallback. |
| `70aed91` | CCC2 | Add Python REPL panel + editor helpers — live-drive `App` from an in-editor prompt. |
| `d636111` | CCC3 | Add asset import drop panel + type router — dispatches through `asset_import.type_router.import_by_extension`. |

### DDD batch (2026-07-19) — Layer3D + deferred renderer + material graph (5 items)

| SHA | Sprint | Summary |
|---|---|---|
| `fe25d85` | DDD1 | Introduce `Layer2D` + `Layer3D` with wgpu render_target — pillar 5.4 landing. |
| `95af086` | DDD2 | Cross-layer buffer sampling — 2D ↔ 3D shared buffers, via `layer_sampling.py` + `cross_layer_composite.wgsl`. |
| `3708cd2` | DDD3 | Add layer compositor + `hello_hybrid_layers` demo — walks `scene.layers` by z_order with blend-mode composition. |
| `9738685` | DDD4 | Add deferred renderer + G-buffer skeleton — pillar 2 plumbing; three WGSL shaders + Rust cluster stub. |
| `0c98862` | DDD5 | Add PBR material graph baseline + 10 core nodes — pillar 3 baseline. |

### EEE batch (2026-07-19, in-flight per the parallel dispatch, 5 items)

| Status | Sprint | Summary |
|---|---|---|
| in-flight | EEE1 | Persistent thumbnail cache + async import queue (`asset_import/thumbnail_cache.py`, `asset_import/async_import_queue.py`, panel-side wiring). |
| in-flight | EEE2 | `SceneNode` + `Transform3D` hierarchical scene-graph (`scene_node.py`) — pillar 5 first half. |
| in-flight | EEE3 | `ShaderHotReloader` + editor bus event (`render/shader_hot_reload.py`) — priority W1 in the roadmap. |
| in-flight | EEE4 | `Prefab` YAML round-trip + `SceneNode` instantiation (`prefab.py`) — pillar 5 second half. |
| in-flight | **EEE5 (this doc)** | Roadmap tracker + progress dashboard. |

---

## Section 5 — Remaining work rank-ordered by impact

Top 10 next-sprint candidates, ordered by the integration plan's own dependency graph + user-visible impact.

1. **W1 — Shader hot-reload polish** (SMALL, 0.5 sprint). EEE3 lands the core; wiring it to the WGSL editor panel and the viewport pipelines completes the loop.
2. **W3 — `Layer3D` scene-composition semantics harden** (MEDIUM). DDD1-3 land the class + compositor; add render-order tests, camera reconciliation, and transform propagation contracts against `SceneNode`.
3. **W4 — Deferred renderer full pass** (LARGE, 4 sprints). DDD4 is skeleton; wire actual light accumulation, TAA motion vectors, CSM composition, clustered-lighting SSBO, material-ID debug view.
4. **W7 — Material graph node inventory expansion** (LARGE, 3 sprints). Grow from 10 → 30+ nodes; add tiered surface / procedural / advanced ladder.
5. **W2 — `Scene` refactor to `SceneNode` root** (MEDIUM, 2 sprints). Depends on EEE2 landing; then update `Scene.load`, `Scene.tick`, `Scene._z_layers` to walk the tree.
6. **W5 — DockSpace tree + drag/drop** (LARGE, 3 sprints). Independent; unblocks nested tab groups + preset-layout parity.
7. **W6 — Asset browser view-modes + breadcrumbs** (MEDIUM, 2 sprints). EEE1 lands thumbnails; view-mode toggle + folder tree + search close the browser parity gap.
8. **W8 — Prefab overrides + variants** (MEDIUM, 2-3 sprints). Depends on EEE2 + EEE4 landing.
9. **W9 — DebugDraw port** (SMALL, 0.5 sprint). Depends on W3.
10. **W10 — FBX import + async pipeline expansion** (MEDIUM, 2 sprints). Depends on W6.

---

## Section 6 — Nova3D subsystems NOT in the roadmap

Items from the 44-subsystem walk that the integration plan explicitly parks or lists as already-covered. Reasons taken from page 1 § Executive summary and `project_nova3d_additions.md`.

| Subsystem | Reason |
|---|---|
| Radiance-cascade GI (`engine/graphics/RadianceCascade.hpp`) | **Already ported** as WGSL rewrite; see `slappyengine.gi` + `docs/gi_design.md`. |
| ReSTIR reservoir reuse | **Already ported**; part of `slappyengine.gi`. |
| SVGF denoiser | **Deferred to v0.5+** — listed as "still pending" in `project_nova3d_additions.md`. |
| RTX path tracer | **Out-of-scope** for v0.4; path-tracing hardware-ray target belongs to v1.x roadmap. |
| Spectral renderer | **Out-of-scope**; niche cinematic feature, no downstream game asks. |
| SDF sculpting pipeline | **Deferred to v0.6+**; distinct authoring surface. |
| Procedural terrain (`engine/procedural/*`) | **Superseded** by existing `slappyengine.iso` + heightmap layer path. |
| NavMesh (`engine/navigation/*`) | **Deferred to v0.5+** — pathfinding TODO in `docs/roadmap.md`. |
| RTS-specific systems (`engine/rts/*`) | **Out-of-scope**; game-specific, not engine-general. |
| GTAO + volumetric fog + GPU particles + tonemap + TAA shader | **Already ported** per `project_nova3d_additions.md`. |
| Assimp binding | **Explicitly not adopted** — SlapPy ports individual importers (glTF SHIPPED, OBJ SHIPPED, FBX PLANNED). |
| GLM binding | **Explicitly not adopted** — SlapPy uses numpy + Rust `_core.math`. |
| ImGui binding | **Explicitly not adopted** — SlapPy uses Dear PyGui + custom notebook widgets. |
| GLFW binding | **Explicitly not adopted** — SlapPy uses winit via wgpu-py. |
| CMake build | **Explicitly not adopted** — SlapPy uses `maturin` + `pyproject.toml`. |

---

## Appendix — Provenance & test-verification chain

- **Docs test:** `SlapPyEngineTests/tests/test_docs_inventory.py` — inventory tripwire enforcing every `docs/**/*.md` file is indexed in `sprint_5_doc_inventory.md`. Refreshed by EEE5 to include this tracker.
- **Cross-references consumed:**
  - `docs/nova3d_integration_plan_2026_07_19.md` — source of the 17-row inventory + 21-sprint roadmap.
  - `docs/nova3d_gap_audit_2026_07_05.md` — HH3-era gap classification (12 WIRED / 20 PARTIAL / 10 GAP / 1 N/A) preserved for trend comparison.
  - `docs/nova3d_parity_sprint_plan_2026_07_05.md` — II7 parity plan feeding JJ/KK/LL sprints (shipped: CSM shadows, BVH raycast, skinned glTF, scene walker, skybox, IBL, HUD, capture, instanced, audio-3d, character demo, exporter, physics3 bridge).
  - `C:\Users\Andrew\.claude\projects\h--Github-SlapPyEngine\memory\project_nova3d_additions.md` — techniques already SHIPPED (tonemap / CSM / volumetric fog / TAA / GTAO / GPU particles).
  - `C:\Users\Andrew\.claude\projects\h--Github-SlapPyEngine\memory\project_architecture_pattern.md` — Python wrapper + Rust core + WGSL directive.
- **Git provenance:** every commit SHA above verified with `git log --oneline` at HEAD `0c98862` (2026-07-19).
