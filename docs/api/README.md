# API Reference Index

Index / gap tracker for every `docs/api/*.md` reference. See
[`_template.md`](_template.md) for the canonical hand-authored
structure — every hand-authored ref file must carry the do-not-
regenerate marker on line 1, use the `# slappyengine.<X> — API
Reference` H1, and provide one of the canonical landing H2s
(`## Overview` / `## Public surface` / `## Usage`). Enforced by
`SlapPyEngineTests/tests/test_docs_api_template_conformance.py`.

This file is **index-only** — no per-symbol content lives here. It
tracks which shipped subpackages have references and which do not.

## Shipped subpackages WITH references

| Subpackage | Doc |
|---|---|
| `slappyengine.actions` | [`actions.md`](actions.md) |
| `slappyengine.ai` | [`ai.md`](ai.md) |
| `slappyengine.animation` | [`animation.md`](animation.md) |
| `slappyengine.animation.skeleton_runtime` | [`animation_skeleton.md`](animation_skeleton.md) |
| `slappyengine.asset_import` | [`asset_import.md`](asset_import.md) |
| `slappyengine.assets` | [`assets.md`](assets.md) |
| `slappyengine.audio_3d` | [`audio_3d.md`](audio_3d.md) |
| `slappyengine.audio_runtime` | [`audio_runtime.md`](audio_runtime.md) |
| `slappyengine.capture` | [`capture.md`](capture.md) |
| `slappyengine.compute` | [`compute.md`](compute.md) |
| `slappyengine.diagnostics` | [`diagnostics.md`](diagnostics.md) |
| `slappyengine.dynamics` | [`dynamics.md`](dynamics.md) |
| `slappyengine.exporter` | [`exporter.md`](exporter.md) |
| `slappyengine.ext` | [`ext.md`](ext.md) |
| `slappyengine.gi` | [`gi.md`](gi.md) |
| `slappyengine.gpu` | [`gpu.md`](gpu.md) |
| `slappyengine.input` | [`input.md`](input.md) |
| `slappyengine.iso` | [`iso.md`](iso.md) |
| `slappyengine.material` | [`material.md`](material.md) |
| `slappyengine.math` | [`math.md`](math.md) |
| `slappyengine.modules` | [`modules.md`](modules.md) |
| `slappyengine.net` | [`net.md`](net.md) |
| `slappyengine.numerics` | [`numerics.md`](numerics.md) |
| `slappyengine.perf` | [`perf.md`](perf.md) |
| `slappyengine.physics3_bridge` | [`physics3_bridge.md`](physics3_bridge.md) |
| `slappyengine.post_process` | [`post_process.md`](post_process.md) |
| `slappyengine.prefabs` | [`prefabs.md`](prefabs.md) |
| `slappyengine.projects` | [`projects.md`](projects.md) |
| `slappyengine.render.bvh_3d` | [`render_bvh_3d.md`](render_bvh_3d.md) |
| `slappyengine.render.instanced` | [`render_instanced.md`](render_instanced.md) |
| `slappyengine.render.scene_walker` | [`render_scene_walker.md`](render_scene_walker.md) |
| `slappyengine.render.shadows` | [`render_shadows.md`](render_shadows.md) |
| `slappyengine.render.skybox` | [`render_skybox.md`](render_skybox.md) |
| `slappyengine.residency` | [`residency.md`](residency.md) |
| `slappyengine.studio` | [`studio.md`](studio.md) |
| `slappyengine.telemetry` | [`telemetry.md`](telemetry.md) |
| `slappyengine.testing` | [`testing.md`](testing.md) |
| `slappyengine.thermal` | [`thermal.md`](thermal.md) |
| `slappyengine.tools` | [`tools.md`](tools.md) |
| `slappyengine.topology` | [`topology.md`](topology.md) |
| `slappyengine.ui.editor` | [`ui_editor.md`](ui_editor.md) |
| `slappyengine.ui.runtime.hud_overlay` | [`hud_overlay.md`](hud_overlay.md) |
| `slappyengine.ui.theme` | [`ui_theme.md`](ui_theme.md) |
| `slappyengine.ui.widgets` | [`ui_widgets.md`](ui_widgets.md) |
| `slappyengine.visual_scripting` | [`visual_scripting.md`](visual_scripting.md) |
| `slappyengine.zones` | [`zones.md`](zones.md) |

## Shader / theme references

| Reference | Doc |
|---|---|
| Edge-stroke WGSL shaders (pen / pencil / marker / chalk) | [`edge_stroke_shaders.md`](edge_stroke_shaders.md) |
| Page-lining WGSL shaders (paper stocks) | [`page_lining_shaders.md`](page_lining_shaders.md) |
| Washi-tape WGSL corner decorations | [`washi_tape_shaders.md`](washi_tape_shaders.md) |
| `DeclarativeTheme` source grammar | [`theme_declarative.md`](theme_declarative.md) |

## Shipped subpackages WITHOUT direct API refs — TODO tracker

Tracking gaps only. Filling these in is out of scope for the doc-polish
sprint (WW6 landed 2026-07-07) — see the notes column for the reason
each row is deferred. Filed for follow-on agents.

| Subpackage | Notes |
|---|---|
| `slappyengine.build` | Build-manifest helpers — small internal utility surface. Deferred: low external caller count. |
| `slappyengine.render` | Composite root package; individual first-class refs already exist for the load-bearing modules (`render.scene_walker`, `render.shadows`, `render.bvh_3d`, `render.skybox`, `render.instanced`). A top-level `render.md` would only summarise the split refs above. Deferred: covered by the sub-refs. |
| `slappyengine.scenes` | Scene registration + persistence helpers. Deferred: rewrite pending after WW-batch WIP unfreeze. |
| `slappyengine.text` | SDF text renderer. Deferred: covered inline by [`../feature_map_2026_06_03.md`](../feature_map_2026_06_03.md) until dedicated ref lands. |
| `slappyengine.ui` (top level) | Composite root package; first-class refs exist for `ui.editor`, `ui.theme`, `ui.widgets`, `ui.runtime.hud_overlay`. Deferred: covered by the sub-refs. |

## WIP subpackages — refs deliberately withheld

| Subpackage | Reason |
|---|---|
| `slappyengine.softbody` | WIP — active sprint. Do not document until subpackage lands. |
| `slappyengine.fluid` | WIP — active sprint. Do not document until subpackage lands. |
| `slappyengine.physics` | WIP — active sprint. Do not document until subpackage lands. |
| `slappyengine.physics2` | WIP — active sprint. Do not document until subpackage lands. |
