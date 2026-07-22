# Tutorials — `hello_*` Demo TOC

Curated table of contents for every runnable `hello_*` demo shipped
under `PharosEngineExamples/examples/`. Each row links to the demo
source, its smoke-test tripwire, and the primary design / API doc(s)
the demo exercises. All tripwires must remain green in CI.

Regenerate this table when a new `hello_*` demo lands. This file is
indexed by `docs/sprint_5_doc_inventory.md`; the doc-inventory tripwire
(`PharosEngineTests/tests/test_docs_inventory.py`) enforces coverage.

## Flagship demos

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_full_lifecycle` | [`../../PharosEngineExamples/examples/hello_full_lifecycle.py`](../../PharosEngineExamples/examples/hello_full_lifecycle.py) | [`test_demo_hello_full_lifecycle.py`](../../PharosEngineTests/tests/test_demo_hello_full_lifecycle.py) | Flagship combined demo — App lifecycle + physics3 + HUD + diagnostics + capture in one script. Pairs with [`lifecycle_contract.md`](../lifecycle_contract.md). |
| `hello_showcase_v3` | [`../../PharosEngineExamples/examples/hello_showcase_v3.py`](../../PharosEngineExamples/examples/hello_showcase_v3.py) | [`test_demo_hello_showcase_v3.py`](../../PharosEngineTests/tests/test_demo_hello_showcase_v3.py) | Round-3 showcase — post-parity rollup demo. |
| `hello_v2_showcase` | [`../../PharosEngineExamples/examples/hello_v2_showcase.py`](../../PharosEngineExamples/examples/hello_v2_showcase.py) | [`test_demo_hello_v2_showcase.py`](../../PharosEngineTests/tests/test_demo_hello_v2_showcase.py) | v0.2 rollup showcase demo. |
| `hello_downstream_pattern` | [`../../PharosEngineExamples/examples/hello_downstream_pattern.py`](../../PharosEngineExamples/examples/hello_downstream_pattern.py) | [`test_demo_hello_downstream_pattern.py`](../../PharosEngineTests/tests/test_demo_hello_downstream_pattern.py) | VV5 downstream-game multi-inherit pattern — extends `App` with custom step hooks the Ochema / Bullet Strata pattern relies on. |

## Rendering / HUD / capture

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_render` | [`../../PharosEngineExamples/examples/hello_render.py`](../../PharosEngineExamples/examples/hello_render.py) | [`test_demo_hello_render.py`](../../PharosEngineTests/tests/test_demo_hello_render.py) | 2-line render pattern — smallest possible headless renderer boot. |
| `hello_render_real` | [`../../PharosEngineExamples/examples/hello_render_real.py`](../../PharosEngineExamples/examples/hello_render_real.py) | [`test_demo_hello_render_real.py`](../../PharosEngineTests/tests/test_demo_hello_render_real.py) | Procedural bunny + real render pipeline. |
| `hello_render_real_hud` | [`../../PharosEngineExamples/examples/hello_render_real_hud.py`](../../PharosEngineExamples/examples/hello_render_real_hud.py) | [`test_demo_hello_render_real_hud.py`](../../PharosEngineTests/tests/test_demo_hello_render_real_hud.py) | Bunny + HUD combined — pairs with [`api/hud_overlay.md`](../api/hud_overlay.md). |
| `hello_hud` | [`../../PharosEngineExamples/examples/hello_hud.py`](../../PharosEngineExamples/examples/hello_hud.py) | [`test_demo_hello_hud.py`](../../PharosEngineTests/tests/test_demo_hello_hud.py) | Minimum HUD overlay boot — pairs with [`api/hud_overlay.md`](../api/hud_overlay.md). |
| `hello_diagnostics_hud` | [`../../PharosEngineExamples/examples/hello_diagnostics_hud.py`](../../PharosEngineExamples/examples/hello_diagnostics_hud.py) | [`test_demo_hello_diagnostics_hud.py`](../../PharosEngineTests/tests/test_demo_hello_diagnostics_hud.py) | Diagnostics collector + HUD showcase — pairs with [`api/diagnostics.md`](../api/diagnostics.md). |
| `hello_lighting` | [`../../PharosEngineExamples/examples/hello_lighting.py`](../../PharosEngineExamples/examples/hello_lighting.py) | [`test_demo_hello_lighting.py`](../../PharosEngineTests/tests/test_demo_hello_lighting.py) | Post-process lighting chain — pairs with [`lighting_presets.md`](../lighting_presets.md). |
| `hello_gi` | [`../../PharosEngineExamples/examples/hello_gi.py`](../../PharosEngineExamples/examples/hello_gi.py) | [`test_demo_hello_gi.py`](../../PharosEngineTests/tests/test_demo_hello_gi.py) | Radiance cascades + ReSTIR + SVGF — pairs with [`gi_design.md`](../gi_design.md) and [`api/gi.md`](../api/gi.md). |
| `hello_pixel` | [`../../PharosEngineExamples/examples/hello_pixel.py`](../../PharosEngineExamples/examples/hello_pixel.py) | [`test_demo_hello_pixel.py`](../../PharosEngineTests/tests/test_demo_hello_pixel.py) | Per-pixel sim boot. |
| `hello_3d_layer` | [`../../PharosEngineExamples/examples/hello_3d_layer.py`](../../PharosEngineExamples/examples/hello_3d_layer.py) | [`test_demo_hello_3d_layer.py`](../../PharosEngineTests/tests/test_demo_hello_3d_layer.py) | 3D layer over 2D physics. |
| `hello_bake` | [`../../PharosEngineExamples/examples/hello_bake.py`](../../PharosEngineExamples/examples/hello_bake.py) | [`test_demo_hello_bake.py`](../../PharosEngineTests/tests/test_demo_hello_bake.py) | Prefab preview bake — pairs with [`api/prefabs.md`](../api/prefabs.md). |
| `hello_export_cli` | [`../../PharosEngineExamples/examples/hello_export_cli.py`](../../PharosEngineExamples/examples/hello_export_cli.py) | [`test_demo_hello_export_cli.py`](../../PharosEngineTests/tests/test_demo_hello_export_cli.py) | `slap export` CLI usage — pairs with [`api/exporter.md`](../api/exporter.md). |

## Physics / dynamics

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_physics` | [`../../PharosEngineExamples/examples/hello_physics.py`](../../PharosEngineExamples/examples/hello_physics.py) | [`test_demo_hello_physics.py`](../../PharosEngineTests/tests/test_demo_hello_physics.py) | Baseline physics boot. |
| `hello_ragdoll` | [`../../PharosEngineExamples/examples/hello_ragdoll.py`](../../PharosEngineExamples/examples/hello_ragdoll.py) | [`test_demo_hello_ragdoll.py`](../../PharosEngineTests/tests/test_demo_hello_ragdoll.py) | XPBD ragdoll — pairs with [`dynamics_design.md`](../dynamics_design.md). |
| `hello_rope` | [`../../PharosEngineExamples/examples/hello_rope.py`](../../PharosEngineExamples/examples/hello_rope.py) | [`test_demo_hello_rope.py`](../../PharosEngineTests/tests/test_demo_hello_rope.py) | XPBD rope — pairs with [`dynamics_design.md`](../dynamics_design.md). |
| `hello_joint` | [`../../PharosEngineExamples/examples/hello_joint.py`](../../PharosEngineExamples/examples/hello_joint.py) | [`test_demo_hello_joint.py`](../../PharosEngineTests/tests/test_demo_hello_joint.py) | JointSpec kinds. |
| `hello_ik_chain` | [`../../PharosEngineExamples/examples/hello_ik_chain.py`](../../PharosEngineExamples/examples/hello_ik_chain.py) | [`test_demo_hello_ik_chain.py`](../../PharosEngineTests/tests/test_demo_hello_ik_chain.py) | IK chain solver. |
| `hello_motor` | [`../../PharosEngineExamples/examples/hello_motor.py`](../../PharosEngineExamples/examples/hello_motor.py) | [`test_demo_hello_motor.py`](../../PharosEngineTests/tests/test_demo_hello_motor.py) | Motor / drivetrain joint. |
| `hello_spring` | [`../../PharosEngineExamples/examples/hello_spring.py`](../../PharosEngineExamples/examples/hello_spring.py) | [`test_demo_hello_spring.py`](../../PharosEngineTests/tests/test_demo_hello_spring.py) | Spring / suspension joint. |
| `hello_composite` | [`../../PharosEngineExamples/examples/hello_composite.py`](../../PharosEngineExamples/examples/hello_composite.py) | [`test_demo_hello_composite.py`](../../PharosEngineTests/tests/test_demo_hello_composite.py) | Composite rigid body. |
| `hello_dynamics_serialize` | [`../../PharosEngineExamples/examples/hello_dynamics_serialize.py`](../../PharosEngineExamples/examples/hello_dynamics_serialize.py) | [`test_demo_hello_dynamics_serialize.py`](../../PharosEngineTests/tests/test_demo_hello_dynamics_serialize.py) | `save_world` / `load_world` round-trip. |
| `hello_studio` | [`../../PharosEngineExamples/examples/hello_studio.py`](../../PharosEngineExamples/examples/hello_studio.py) | [`test_demo_hello_studio.py`](../../PharosEngineTests/tests/test_demo_hello_studio.py) | Stage + record() — pairs with [`studio_quickstart.md`](../studio_quickstart.md). |

## Subsystem primers

| Demo | Source | Test | Notes |
|---|---|---|---|
| `hello_world` | [`../../PharosEngineExamples/examples/hello_world.py`](../../PharosEngineExamples/examples/hello_world.py) | [`test_demo_hello_world.py`](../../PharosEngineTests/tests/test_demo_hello_world.py) | Smallest engine boot. |
| `hello_audio` | [`../../PharosEngineExamples/examples/hello_audio.py`](../../PharosEngineExamples/examples/hello_audio.py) | [`test_demo_hello_audio.py`](../../PharosEngineTests/tests/test_demo_hello_audio.py) | 2D audio runtime — pairs with [`api/audio_runtime.md`](../api/audio_runtime.md). |
| `hello_positional_audio` | [`../../PharosEngineExamples/examples/hello_positional_audio.py`](../../PharosEngineExamples/examples/hello_positional_audio.py) | [`test_demo_hello_positional_audio.py`](../../PharosEngineTests/tests/test_demo_hello_positional_audio.py) | 3D positional audio — pairs with [`api/audio_3d.md`](../api/audio_3d.md). |
| `hello_thermal` | [`../../PharosEngineExamples/examples/hello_thermal.py`](../../PharosEngineExamples/examples/hello_thermal.py) | [`test_demo_hello_thermal.py`](../../PharosEngineTests/tests/test_demo_hello_thermal.py) | Heat field — pairs with [`api/thermal.md`](../api/thermal.md). |
| `hello_iso` | [`../../PharosEngineExamples/examples/hello_iso.py`](../../PharosEngineExamples/examples/hello_iso.py) | [`test_demo_hello_iso.py`](../../PharosEngineTests/tests/test_demo_hello_iso.py) | Iso grid + camera — pairs with [`api/iso.md`](../api/iso.md). |
| `hello_zone` | [`../../PharosEngineExamples/examples/hello_zone.py`](../../PharosEngineExamples/examples/hello_zone.py) | [`test_demo_hello_zone.py`](../../PharosEngineTests/tests/test_demo_hello_zone.py) | Zone enter/exit callbacks — pairs with [`api/zones.md`](../api/zones.md). |
| `hello_telemetry` | [`../../PharosEngineExamples/examples/hello_telemetry.py`](../../PharosEngineExamples/examples/hello_telemetry.py) | [`test_demo_hello_telemetry.py`](../../PharosEngineTests/tests/test_demo_hello_telemetry.py) | Event emission — pairs with [`api/telemetry.md`](../api/telemetry.md). |
| `hello_topology` | [`../../PharosEngineExamples/examples/hello_topology.py`](../../PharosEngineExamples/examples/hello_topology.py) | [`test_demo_hello_topology.py`](../../PharosEngineTests/tests/test_demo_hello_topology.py) | Connected components — pairs with [`api/topology.md`](../api/topology.md). |
| `hello_numerics` | [`../../PharosEngineExamples/examples/hello_numerics.py`](../../PharosEngineExamples/examples/hello_numerics.py) | [`test_demo_hello_numerics.py`](../../PharosEngineTests/tests/test_demo_hello_numerics.py) | Poisson multigrid — pairs with [`api/numerics.md`](../api/numerics.md). |
| `hello_material_graph` | [`../../PharosEngineExamples/examples/hello_material_graph.py`](../../PharosEngineExamples/examples/hello_material_graph.py) | [`test_demo_hello_material_graph.py`](../../PharosEngineTests/tests/test_demo_hello_material_graph.py) | NodeMaterial authoring — pairs with [`api/material.md`](../api/material.md). |
| `hello_scene_reg` | [`../../PharosEngineExamples/examples/hello_scene_reg.py`](../../PharosEngineExamples/examples/hello_scene_reg.py) | [`test_demo_hello_scene_reg.py`](../../PharosEngineTests/tests/test_demo_hello_scene_reg.py) | Scene registration. |
| `hello_prefab` | [`../../PharosEngineExamples/examples/hello_prefab.py`](../../PharosEngineExamples/examples/hello_prefab.py) | [`test_demo_hello_prefab.py`](../../PharosEngineTests/tests/test_demo_hello_prefab.py) | PrefabLibrary spawn — pairs with [`api/prefabs.md`](../api/prefabs.md). |
| `hello_autosave` | [`../../PharosEngineExamples/examples/hello_autosave.py`](../../PharosEngineExamples/examples/hello_autosave.py) | [`test_demo_hello_autosave.py`](../../PharosEngineTests/tests/test_demo_hello_autosave.py) | Autosave subsystem. |
| `hello_full_editor` | [`../../PharosEngineExamples/examples/hello_full_editor.py`](../../PharosEngineExamples/examples/hello_full_editor.py) | [`test_demo_hello_full_editor.py`](../../PharosEngineTests/tests/test_demo_hello_full_editor.py) | Full notebook-editor boot. |
| `hello_integrated_notebook` | [`../../PharosEngineExamples/examples/hello_integrated_notebook.py`](../../PharosEngineExamples/examples/hello_integrated_notebook.py) | [`test_demo_hello_integrated_notebook.py`](../../PharosEngineTests/tests/test_demo_hello_integrated_notebook.py) | Notebook-editor + engine integration. |
| `hello_toast_animation` | [`../../PharosEngineExamples/examples/hello_toast_animation.py`](../../PharosEngineExamples/examples/hello_toast_animation.py) | [`test_demo_hello_toast_animation.py`](../../PharosEngineTests/tests/test_demo_hello_toast_animation.py) | Toast-notification animation. |
| `hello_gltf_character` | [`../../PharosEngineExamples/examples/hello_gltf_character.py`](../../PharosEngineExamples/examples/hello_gltf_character.py) | [`test_demo_hello_gltf_character.py`](../../PharosEngineTests/tests/test_demo_hello_gltf_character.py) | Skinned glTF character — pairs with [`api/animation_skeleton.md`](../api/animation_skeleton.md). |
| `hello_rust_bypass` | [`../../PharosEngineExamples/examples/hello_rust_bypass.py`](../../PharosEngineExamples/examples/hello_rust_bypass.py) | [`test_demo_hello_rust_bypass.py`](../../PharosEngineTests/tests/test_demo_hello_rust_bypass.py) | Direct `_core` PyO3 call — pairs with [`rust_bypass_2026_07_05.md`](../rust_bypass_2026_07_05.md). |

## Cross-references

- Written tutorials with in-line snippets: [`../tutorial_build_a_game.md`](../tutorial_build_a_game.md), [`../getting_started.md`](../getting_started.md), [`../quickstart.md`](../quickstart.md), [`../dynamics_quickstart.md`](../dynamics_quickstart.md), [`../studio_quickstart.md`](../studio_quickstart.md).
- Cinematic gallery: [`../demo_gallery.md`](../demo_gallery.md).
- Design references: see the `*_design.md` docs indexed in [`../sprint_5_doc_inventory.md`](../sprint_5_doc_inventory.md).
