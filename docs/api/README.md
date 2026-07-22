# API Reference Index

Index / gap tracker for every `docs/api/*.md` reference. See
[`_template.md`](_template.md) for the canonical hand-authored
structure — every hand-authored ref file must carry the do-not-
regenerate marker on line 1, use the `# pharos_engine.<X> — API
Reference` H1, and provide one of the canonical landing H2s
(`## Overview` / `## Public surface` / `## Usage`). Enforced by
`SlapPyEngineTests/tests/test_docs_api_template_conformance.py`.

This file is **index-only** — no per-symbol content lives here. It
tracks which shipped subpackages have references and which do not.

## Shipped subpackages WITH references

| Subpackage | Doc |
|---|---|
| `pharos_engine.actions` | [`actions.md`](actions.md) |
| `pharos_engine.ai` | [`ai.md`](ai.md) |
| `pharos_engine.animation` | [`animation.md`](animation.md) |
| `pharos_engine.animation.skeleton_runtime` | [`animation_skeleton.md`](animation_skeleton.md) |
| `pharos_engine.asset_import` | [`asset_import.md`](asset_import.md) |
| `pharos_engine.assets` | [`assets.md`](assets.md) |
| `pharos_engine.audio_3d` | [`audio_3d.md`](audio_3d.md) |
| `pharos_engine.audio_runtime` | [`audio_runtime.md`](audio_runtime.md) |
| `pharos_engine.capture` | [`capture.md`](capture.md) |
| `pharos_engine.compute` | [`compute.md`](compute.md) |
| `pharos_engine.diagnostics` | [`diagnostics.md`](diagnostics.md) |
| `pharos_engine.dynamics` | [`dynamics.md`](dynamics.md) |
| `pharos_engine.exporter` | [`exporter.md`](exporter.md) |
| `pharos_engine.ext` | [`ext.md`](ext.md) |
| `pharos_engine.gi` | [`gi.md`](gi.md) |
| `pharos_engine.gpu` | [`gpu.md`](gpu.md) |
| `pharos_engine.input` | [`input.md`](input.md) |
| `pharos_engine.iso` | [`iso.md`](iso.md) |
| `pharos_engine.material` | [`material.md`](material.md) |
| `pharos_engine.math` | [`math.md`](math.md) |
| `pharos_engine.modules` | [`modules.md`](modules.md) |
| `pharos_engine.net` | [`net.md`](net.md) |
| `pharos_engine.numerics` | [`numerics.md`](numerics.md) |
| `pharos_engine.perf` | [`perf.md`](perf.md) |
| `pharos_engine.physics3_bridge` | [`physics3_bridge.md`](physics3_bridge.md) |
| `pharos_engine.post_process` | [`post_process.md`](post_process.md) |
| `pharos_engine.prefabs` | [`prefabs.md`](prefabs.md) |
| `pharos_engine.projects` | [`projects.md`](projects.md) |
| `pharos_engine.render.bvh_3d` | [`render_bvh_3d.md`](render_bvh_3d.md) |
| `pharos_engine.render.instanced` | [`render_instanced.md`](render_instanced.md) |
| `pharos_engine.render.scene_walker` | [`render_scene_walker.md`](render_scene_walker.md) |
| `pharos_engine.render.shadows` | [`render_shadows.md`](render_shadows.md) |
| `pharos_engine.render.skybox` | [`render_skybox.md`](render_skybox.md) |
| `pharos_engine.residency` | [`residency.md`](residency.md) |
| `pharos_engine.studio` | [`studio.md`](studio.md) |
| `pharos_engine.telemetry` | [`telemetry.md`](telemetry.md) |
| `pharos_engine.testing` | [`testing.md`](testing.md) |
| `pharos_engine.thermal` | [`thermal.md`](thermal.md) |
| `pharos_engine.tools` | [`tools.md`](tools.md) |
| `pharos_engine.topology` | [`topology.md`](topology.md) |
| `pharos_engine.ui.editor` | [`ui_editor.md`](ui_editor.md) |
| `pharos_engine.ui.runtime.hud_overlay` | [`hud_overlay.md`](hud_overlay.md) |
| `pharos_engine.ui.theme` | [`ui_theme.md`](ui_theme.md) |
| `pharos_engine.ui.widgets` | [`ui_widgets.md`](ui_widgets.md) |
| `pharos_engine.visual_scripting` | [`visual_scripting.md`](visual_scripting.md) |
| `pharos_engine.zones` | [`zones.md`](zones.md) |

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
| `pharos_engine.build` | Build-manifest helpers — small internal utility surface. Deferred: low external caller count. |
| `pharos_engine.render` | Composite root package; individual first-class refs already exist for the load-bearing modules (`render.scene_walker`, `render.shadows`, `render.bvh_3d`, `render.skybox`, `render.instanced`). A top-level `render.md` would only summarise the split refs above. Deferred: covered by the sub-refs. |
| `pharos_engine.scenes` | Scene registration + persistence helpers. Deferred: rewrite pending after WW-batch WIP unfreeze. |
| `pharos_engine.text` | SDF text renderer. Deferred: covered inline by [`../feature_map_2026_06_03.md`](../feature_map_2026_06_03.md) until dedicated ref lands. |
| `pharos_engine.ui` (top level) | Composite root package; first-class refs exist for `ui.editor`, `ui.theme`, `ui.widgets`, `ui.runtime.hud_overlay`. Deferred: covered by the sub-refs. |

## WIP subpackages — refs deliberately withheld

| Subpackage | Reason |
|---|---|
| `pharos_engine.softbody` | WIP — active sprint. Do not document until subpackage lands. |
| `pharos_engine.fluid` | WIP — active sprint. Do not document until subpackage lands. |
| `pharos_engine.physics` | WIP — active sprint. Do not document until subpackage lands. |
| `pharos_engine.physics2` | WIP — active sprint. Do not document until subpackage lands. |
