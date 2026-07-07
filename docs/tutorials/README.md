# Tutorials — `hello_*` Demo TOC

Curated table of contents for every runnable `hello_*` demo shipped
under `SlapPyEngineExamples/examples/`. Each row links to the demo
source, its smoke-test tripwire, and the primary design / API doc(s)
the demo exercises. All tripwires must remain green in CI.

Regenerate this table when a new `hello_*` demo lands. This file is
indexed by `docs/sprint_5_doc_inventory.md`; the doc-inventory tripwire
(`SlapPyEngineTests/tests/test_docs_inventory.py`) enforces coverage.

## Flagship demos

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_full_lifecycle` | [`../../SlapPyEngineExamples/examples/hello_full_lifecycle.py`](../../SlapPyEngineExamples/examples/hello_full_lifecycle.py) | [`test_demo_hello_full_lifecycle.py`](../../SlapPyEngineTests/tests/test_demo_hello_full_lifecycle.py) | Flagship combined demo — App lifecycle + physics3 + HUD + diagnostics + capture in one script. Pairs with [`lifecycle_contract.md`](../lifecycle_contract.md). |
| `hello_showcase_v3` | [`../../SlapPyEngineExamples/examples/hello_showcase_v3.py`](../../SlapPyEngineExamples/examples/hello_showcase_v3.py) | [`test_demo_hello_showcase_v3.py`](../../SlapPyEngineTests/tests/test_demo_hello_showcase_v3.py) | Round-3 showcase — post-parity rollup demo. |
| `hello_v2_showcase` | [`../../SlapPyEngineExamples/examples/hello_v2_showcase.py`](../../SlapPyEngineExamples/examples/hello_v2_showcase.py) | [`test_demo_hello_v2_showcase.py`](../../SlapPyEngineTests/tests/test_demo_hello_v2_showcase.py) | v0.2 rollup showcase demo. |
| `hello_downstream_pattern` | [`../../SlapPyEngineExamples/examples/hello_downstream_pattern.py`](../../SlapPyEngineExamples/examples/hello_downstream_pattern.py) | [`test_demo_hello_downstream_pattern.py`](../../SlapPyEngineTests/tests/test_demo_hello_downstream_pattern.py) | VV5 downstream-game multi-inherit pattern — extends `App` with custom step hooks the Ochema / Bullet Strata pattern relies on. |

## Rendering / HUD / capture

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_render` | [`../../SlapPyEngineExamples/examples/hello_render.py`](../../SlapPyEngineExamples/examples/hello_render.py) | [`test_demo_hello_render.py`](../../SlapPyEngineTests/tests/test_demo_hello_render.py) | 2-line render pattern — smallest possible headless renderer boot. |
| `hello_render_real` | [`../../SlapPyEngineExamples/examples/hello_render_real.py`](../../SlapPyEngineExamples/examples/hello_render_real.py) | [`test_demo_hello_render_real.py`](../../SlapPyEngineTests/tests/test_demo_hello_render_real.py) | Procedural bunny + real render pipeline. |
| `hello_render_real_hud` | [`../../SlapPyEngineExamples/examples/hello_render_real_hud.py`](../../SlapPyEngineExamples/examples/hello_render_real_hud.py) | [`test_demo_hello_render_real_hud.py`](../../SlapPyEngineTests/tests/test_demo_hello_render_real_hud.py) | Bunny + HUD combined — pairs with [`api/hud_overlay.md`](../api/hud_overlay.md). |
| `hello_hud` | [`../../SlapPyEngineExamples/examples/hello_hud.py`](../../SlapPyEngineExamples/examples/hello_hud.py) | [`test_demo_hello_hud.py`](../../SlapPyEngineTests/tests/test_demo_hello_hud.py) | Minimum HUD overlay boot — pairs with [`api/hud_overlay.md`](../api/hud_overlay.md). |
| `hello_diagnostics_hud` | [`../../SlapPyEngineExamples/examples/hello_diagnostics_hud.py`](../../SlapPyEngineExamples/examples/hello_diagnostics_hud.py) | [`test_demo_hello_diagnostics_hud.py`](../../SlapPyEngineTests/tests/test_demo_hello_diagnostics_hud.py) | Diagnostics collector + HUD showcase — pairs with [`api/diagnostics.md`](../api/diagnostics.md). |
| `hello_lighting` | [`../../SlapPyEngineExamples/examples/hello_lighting.py`](../../SlapPyEngineExamples/examples/hello_lighting.py) | [`test_demo_hello_lighting.py`](../../SlapPyEngineTests/tests/test_demo_hello_lighting.py) | Post-process lighting chain — pairs with [`lighting_presets.md`](../lighting_presets.md). |
| `hello_gi` | [`../../SlapPyEngineExamples/examples/hello_gi.py`](../../SlapPyEngineExamples/examples/hello_gi.py) | [`test_demo_hello_gi.py`](../../SlapPyEngineTests/tests/test_demo_hello_gi.py) | Radiance cascades + ReSTIR + SVGF — pairs with [`gi_design.md`](../gi_design.md) and [`api/gi.md`](../api/gi.md). |
| `hello_pixel` | [`../../SlapPyEngineExamples/examples/hello_pixel.py`](../../SlapPyEngineExamples/examples/hello_pixel.py) | [`test_demo_hello_pixel.py`](../../SlapPyEngineTests/tests/test_demo_hello_pixel.py) | Per-pixel sim boot. |
| `hello_3d_layer` | [`../../SlapPyEngineExamples/examples/hello_3d_layer.py`](../../SlapPyEngineExamples/examples/hello_3d_layer.py) | [`test_demo_hello_3d_layer.py`](../../SlapPyEngineTests/tests/test_demo_hello_3d_layer.py) | 3D layer over 2D physics. |
| `hello_bake` | [`../../SlapPyEngineExamples/examples/hello_bake.py`](../../SlapPyEngineExamples/examples/hello_bake.py) | [`test_demo_hello_bake.py`](../../SlapPyEngineTests/tests/test_demo_hello_bake.py) | Prefab preview bake — pairs with [`api/prefabs.md`](../api/prefabs.md). |
| `hello_export_cli` | [`../../SlapPyEngineExamples/examples/hello_export_cli.py`](../../SlapPyEngineExamples/examples/hello_export_cli.py) | [`test_demo_hello_export_cli.py`](../../SlapPyEngineTests/tests/test_demo_hello_export_cli.py) | `slap export` CLI usage — pairs with [`api/exporter.md`](../api/exporter.md). |

## Physics / dynamics

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_physics` | [`../../SlapPyEngineExamples/examples/hello_physics.py`](../../SlapPyEngineExamples/examples/hello_physics.py) | [`test_demo_hello_physics.py`](../../SlapPyEngineTests/tests/test_demo_hello_physics.py) | Baseline physics boot. |
| `hello_ragdoll` | [`../../SlapPyEngineExamples/examples/hello_ragdoll.py`](../../SlapPyEngineExamples/examples/hello_ragdoll.py) | [`test_demo_hello_ragdoll.py`](../../SlapPyEngineTests/tests/test_demo_hello_ragdoll.py) | XPBD ragdoll — pairs with [`dynamics_design.md`](../dynamics_design.md). |
| `hello_rope` | [`../../SlapPyEngineExamples/examples/hello_rope.py`](../../SlapPyEngineExamples/examples/hello_rope.py) | [`test_demo_hello_rope.py`](../../SlapPyEngineTests/tests/test_demo_hello_rope.py) | XPBD rope — pairs with [`dynamics_design.md`](../dynamics_design.md). |
| `hello_joint` | [`../../SlapPyEngineExamples/examples/hello_joint.py`](../../SlapPyEngineExamples/examples/hello_joint.py) | [`test_demo_hello_joint.py`](../../SlapPyEngineTests/tests/test_demo_hello_joint.py) | JointSpec kinds. |
| `hello_ik_chain` | [`../../SlapPyEngineExamples/examples/hello_ik_chain.py`](../../SlapPyEngineExamples/examples/hello_ik_chain.py) | [`test_demo_hello_ik_chain.py`](../../SlapPyEngineTests/tests/test_demo_hello_ik_chain.py) | IK chain solver. |
| `hello_motor` | [`../../SlapPyEngineExamples/examples/hello_motor.py`](../../SlapPyEngineExamples/examples/hello_motor.py) | [`test_demo_hello_motor.py`](../../SlapPyEngineTests/tests/test_demo_hello_motor.py) | Motor / drivetrain joint. |
| `hello_spring` | [`../../SlapPyEngineExamples/examples/hello_spring.py`](../../SlapPyEngineExamples/examples/hello_spring.py) | [`test_demo_hello_spring.py`](../../SlapPyEngineTests/tests/test_demo_hello_spring.py) | Spring / suspension joint. |
| `hello_composite` | [`../../SlapPyEngineExamples/examples/hello_composite.py`](../../SlapPyEngineExamples/examples/hello_composite.py) | [`test_demo_hello_composite.py`](../../SlapPyEngineTests/tests/test_demo_hello_composite.py) | Composite rigid body. |
| `hello_dynamics_serialize` | [`../../SlapPyEngineExamples/examples/hello_dynamics_serialize.py`](../../SlapPyEngineExamples/examples/hello_dynamics_serialize.py) | [`test_demo_hello_dynamics_serialize.py`](../../SlapPyEngineTests/tests/test_demo_hello_dynamics_serialize.py) | `save_world` / `load_world` round-trip. |
| `hello_studio` | [`../../SlapPyEngineExamples/examples/hello_studio.py`](../../SlapPyEngineExamples/examples/hello_studio.py) | [`test_demo_hello_studio.py`](../../SlapPyEngineTests/tests/test_demo_hello_studio.py) | Stage + record() — pairs with [`studio_quickstart.md`](../studio_quickstart.md). |

## Subsystem primers

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_world` | [`../../SlapPyEngineExamples/examples/hello_world.py`](../../SlapPyEngineExamples/examples/hello_world.py) | [`test_demo_hello_world.py`](../../SlapPyEngineTests/tests/test_demo_hello_world.py) | Smallest engine boot. |
| `hello_audio` | [`../../SlapPyEngineExamples/examples/hello_audio.py`](../../SlapPyEngineExamples/examples/hello_audio.py) | [`test_demo_hello_audio.py`](../../SlapPyEngineTests/tests/test_demo_hello_audio.py) | 2D audio runtime — pairs with [`api/audio_runtime.md`](../api/audio_runtime.md). |
| `hello_positional_audio` | [`../../SlapPyEngineExamples/examples/hello_positional_audio.py`](../../SlapPyEngineExamples/examples/hello_positional_audio.py) | [`test_demo_hello_positional_audio.py`](../../SlapPyEngineTests/tests/test_demo_hello_positional_audio.py) | 3D positional audio — pairs with [`api/audio_3d.md`](../api/audio_3d.md). |
| `hello_thermal` | [`../../SlapPyEngineExamples/examples/hello_thermal.py`](../../SlapPyEngineExamples/examples/hello_thermal.py) | [`test_demo_hello_thermal.py`](../../SlapPyEngineTests/tests/test_demo_hello_thermal.py) | Heat field — pairs with [`api/thermal.md`](../api/thermal.md). |
| `hello_iso` | [`../../SlapPyEngineExamples/examples/hello_iso.py`](../../SlapPyEngineExamples/examples/hello_iso.py) | [`test_demo_hello_iso.py`](../../SlapPyEngineTests/tests/test_demo_hello_iso.py) | Iso grid + camera — pairs with [`api/iso.md`](../api/iso.md). |
| `hello_zone` | [`../../SlapPyEngineExamples/examples/hello_zone.py`](../../SlapPyEngineExamples/examples/hello_zone.py) | [`test_demo_hello_zone.py`](../../SlapPyEngineTests/tests/test_demo_hello_zone.py) | Zone enter/exit callbacks — pairs with [`api/zones.md`](../api/zones.md). |
| `hello_telemetry` | [`../../SlapPyEngineExamples/examples/hello_telemetry.py`](../../SlapPyEngineExamples/examples/hello_telemetry.py) | [`test_demo_hello_telemetry.py`](../../SlapPyEngineTests/tests/test_demo_hello_telemetry.py) | Event emission — pairs with [`api/telemetry.md`](../api/telemetry.md). |
| `hello_topology` | [`../../SlapPyEngineExamples/examples/hello_topology.py`](../../SlapPyEngineExamples/examples/hello_topology.py) | [`test_demo_hello_topology.py`](../../SlapPyEngineTests/tests/test_demo_hello_topology.py) | Connected components — pairs with [`api/topology.md`](../api/topology.md). |
| `hello_numerics` | [`../../SlapPyEngineExamples/examples/hello_numerics.py`](../../SlapPyEngineExamples/examples/hello_numerics.py) | [`test_demo_hello_numerics.py`](../../SlapPyEngineTests/tests/test_demo_hello_numerics.py) | Poisson multigrid — pairs with [`api/numerics.md`](../api/numerics.md). |
| `hello_material_graph` | [`../../SlapPyEngineExamples/examples/hello_material_graph.py`](../../SlapPyEngineExamples/examples/hello_material_graph.py) | [`test_demo_hello_material_graph.py`](../../SlapPyEngineTests/tests/test_demo_hello_material_graph.py) | NodeMaterial authoring — pairs with [`api/material.md`](../api/material.md). |
| `hello_scene_reg` | [`../../SlapPyEngineExamples/examples/hello_scene_reg.py`](../../SlapPyEngineExamples/examples/hello_scene_reg.py) | [`test_demo_hello_scene_reg.py`](../../SlapPyEngineTests/tests/test_demo_hello_scene_reg.py) | Scene registration. |
| `hello_prefab` | [`../../SlapPyEngineExamples/examples/hello_prefab.py`](../../SlapPyEngineExamples/examples/hello_prefab.py) | [`test_demo_hello_prefab.py`](../../SlapPyEngineTests/tests/test_demo_hello_prefab.py) | PrefabLibrary spawn — pairs with [`api/prefabs.md`](../api/prefabs.md). |
| `hello_autosave` | [`../../SlapPyEngineExamples/examples/hello_autosave.py`](../../SlapPyEngineExamples/examples/hello_autosave.py) | [`test_demo_hello_autosave.py`](../../SlapPyEngineTests/tests/test_demo_hello_autosave.py) | Autosave subsystem. |
| `hello_full_editor` | [`../../SlapPyEngineExamples/examples/hello_full_editor.py`](../../SlapPyEngineExamples/examples/hello_full_editor.py) | [`test_demo_hello_full_editor.py`](../../SlapPyEngineTests/tests/test_demo_hello_full_editor.py) | Full notebook-editor boot. |
| `hello_integrated_notebook` | [`../../SlapPyEngineExamples/examples/hello_integrated_notebook.py`](../../SlapPyEngineExamples/examples/hello_integrated_notebook.py) | [`test_demo_hello_integrated_notebook.py`](../../SlapPyEngineTests/tests/test_demo_hello_integrated_notebook.py) | Notebook-editor + engine integration. |
| `hello_toast_animation` | [`../../SlapPyEngineExamples/examples/hello_toast_animation.py`](../../SlapPyEngineExamples/examples/hello_toast_animation.py) | [`test_demo_hello_toast_animation.py`](../../SlapPyEngineTests/tests/test_demo_hello_toast_animation.py) | Toast-notification animation. |
| `hello_gltf_character` | [`../../SlapPyEngineExamples/examples/hello_gltf_character.py`](../../SlapPyEngineExamples/examples/hello_gltf_character.py) | [`test_demo_hello_gltf_character.py`](../../SlapPyEngineTests/tests/test_demo_hello_gltf_character.py) | Skinned glTF character — pairs with [`api/animation_skeleton.md`](../api/animation_skeleton.md). |
| `hello_rust_bypass` | [`../../SlapPyEngineExamples/examples/hello_rust_bypass.py`](../../SlapPyEngineExamples/examples/hello_rust_bypass.py) | [`test_demo_hello_rust_bypass.py`](../../SlapPyEngineTests/tests/test_demo_hello_rust_bypass.py) | Direct `_core` PyO3 call — pairs with [`rust_bypass_2026_07_05.md`](../rust_bypass_2026_07_05.md). |

## Cross-references

- Written tutorials with in-line snippets: [`../tutorial_build_a_game.md`](../tutorial_build_a_game.md), [`../getting_started.md`](../getting_started.md), [`../quickstart.md`](../quickstart.md), [`../dynamics_quickstart.md`](../dynamics_quickstart.md), [`../studio_quickstart.md`](../studio_quickstart.md).
- Cinematic gallery: [`../demo_gallery.md`](../demo_gallery.md).
- Design references: see the `*_design.md` docs indexed in [`../sprint_5_doc_inventory.md`](../sprint_5_doc_inventory.md).
