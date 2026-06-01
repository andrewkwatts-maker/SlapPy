# Sprint 5 — Documentation Inventory

One-page index of every Markdown file under `docs/` with a one-line
description. Locked by `tests/test_docs_inventory.py` — every file under
`docs/**/*.md` must appear here, and every entry below must point at a file
that exists on disk.

Regenerate after adding or removing any doc.

## Top-level guides (`docs/`)

| Path | Description |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | SlapPyEngine architecture guide — repo layout, conventions, and key subsystems. |
| [`ONBOARDING.md`](ONBOARDING.md) | Contributor onboarding — install variants, architecture tour, and first-change walk-through. |
| [`architecture_overview.md`](architecture_overview.md) | 5-minute orientation for the rebuilt 2D physics layer (softbody / fluid / dynamics / studio) and dependency direction. |
| [`dynamics_design.md`](dynamics_design.md) | Design reference for `slappyengine.dynamics`: XPBD substrate, the seven `JointSpec` kinds, authoring helpers, and failure modes. |
| [`dynamics_quickstart.md`](dynamics_quickstart.md) | 10-minute hands-on quick-start for the dynamics primitives, with six runnable snippets (4/4 tripwire tests green). |
| [`engine_surface_v030.md`](engine_surface_v030.md) | Auto-generated v0.3 engine-surface reference — 75 top-level symbols across 19 declared subpackages (regenerate via `scripts/gen_engine_surface_doc.py`). |
| [`examples_smoke_2026_05_31.md`](examples_smoke_2026_05_31.md) | Read-only smoke audit of every `examples/*.py` (Sprint 1E, 2026-05-31). |
| [`examples_smoke_2026_06_01.md`](examples_smoke_2026_06_01.md) | Examples smoke audit v2 — refresh of the 2026-05-31 audit (2026-06-01). |
| [`fluid_design.md`](fluid_design.md) | Design reference for the Position-Based Fluids (PBF) 2D particle simulator (`slappyengine.fluid`). |
| [`getting_started.md`](getting_started.md) | Game-dev tutorial; build a runnable mini-game in 15 minutes with 8 verified-runnable snippets (5/5 tripwire tests green, 298 lines). |
| [`hardening_audit_2026_05_29.md`](hardening_audit_2026_05_29.md) | Phase-B/C subpackage input-validation hardening audit (2026-05-29). |
| [`lighting_presets.md`](lighting_presets.md) | Sprint-3 ready-to-use post-process chain presets composing the lighting-polish helpers into flagship game looks. |
| [`material_catalog.md`](material_catalog.md) | Reference catalogue for every material shipped in `config/softbody.yml` and `config/fluid.yml`. |
| [`particle_field_design.md`](particle_field_design.md) | ParticleField design notes — what worked, what didn't, Phase 1+2 foundation cleanup rationale. |
| [`particle_field_gpu_buffers.md`](particle_field_gpu_buffers.md) | ParticleField GPU buffer-layout design document (std430 storage buffers, textures, growth strategy). |
| [`particle_field_gpu_port.md`](particle_field_gpu_port.md) | ParticleField GPU port — 7-sprint architecture for migrating `particle_field` onto WGSL compute shaders. |
| [`particle_field_v2_summary.md`](particle_field_v2_summary.md) | ParticleField v2 sprint summary — what landed in the multi-hour refactor sprint, in commit order. |
| [`per_pixel_sim_audit_2026_05_31.md`](per_pixel_sim_audit_2026_05_31.md) | Branch-reachability audit of `per_pixel_sim.wgsl` ahead of the Phase D strip (Sprint 3E, 2026-05-31). |
| [`perf_dashboard.md`](perf_dashboard.md) | One-page perf tripwire across the six v0.3 hot paths (dynamics, numerics, thermal, topology, telemetry, zones) with bound classifications. |
| [`perf_dashboard_prev.md`](perf_dashboard_prev.md) | Prior perf dashboard snapshot (2026-05-29) preserved for trend comparison. |
| [`phase_d_strip_plan_2026_05_31.md`](phase_d_strip_plan_2026_05_31.md) | Phase D strip-pass execution plan (Sprint F, 2026-05-31) — gated on Ochema CI greenness. |
| [`physics_module.md`](physics_module.md) | Entry point for the hierarchical-hull per-pixel physics module (`slappyengine.physics`). |
| [`rust_migration_plan.md`](rust_migration_plan.md) | Rust migration plan — staged path to 1000 fps via Rust-backed hot-path migration. |
| [`rust_port_plan_dynamics.md`](rust_port_plan_dynamics.md) | Phase 1 MVP Rust-port plan for `slappyengine.dynamics`: `_project_distance` first, 3-4x estimated speedup (4/4 green). |
| [`softbody_design.md`](softbody_design.md) | Design reference for the BeamNG-style soft-body lattice XPBD simulator (`slappyengine.softbody`). |
| [`sprint_1_game_compat_2026_05_30.md`](sprint_1_game_compat_2026_05_30.md) | Sprint 1 game-integration verification — engine surface contract honoured for Ochema Circuit / Bullet Strata / Stone Keep. |
| [`sprint_1_retrospective.md`](sprint_1_retrospective.md) | Sprint 1 retrospective — ParticleField GPU port (compute scaffolding and SoA upload). |
| [`sprint_2_retrospective.md`](sprint_2_retrospective.md) | Sprint 2 retrospective — per-particle GPU kernels (5 kernels landed under opt-in flags). |
| [`sprint_4_serialization_gaps.md`](sprint_4_serialization_gaps.md) | Sprint 4 serialization gap analysis — which subsystems have JSON round-trips and which don't. |
| [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) | This file — Sprint 5 doc inventory. Every `docs/**/*.md` must appear here. |
| [`sprint_6_dynamics_profile_recheck.md`](sprint_6_dynamics_profile_recheck.md) | Sprint 6 read-only re-check of the `dynamics` 100-node lattice profile against the Rust port plan baseline. |
| [`sprint_6_test_audit.md`](sprint_6_test_audit.md) | Sprint 6 test audit — every `skip` / `xfail` / `skipif` reviewed with a resolve/keep/delete recommendation. |
| [`sprint_7_ship_checklist.md`](sprint_7_ship_checklist.md) | Sprint 7 production-hardening and ship-readiness checklist gating the v0.3.x → tagged-release transition. |
| [`sprite_audit_recipe.md`](sprite_audit_recipe.md) | Sprite-anchor and atlas audit workflow recipe for the `slappyengine.tools.sprite_audit` CPU-only utility. |
| [`strip_pass_v2_audit.md`](strip_pass_v2_audit.md) | Phase D strip-pass v2 dry-run audit — enumerates deletion candidates and their consumer counts (no files deleted; gated on downstream-game CI). |
| [`studio_quickstart.md`](studio_quickstart.md) | 5-minute tour of `slappyengine.studio` — high-level scene-scaffolding helpers wrapping the rebuild physics stack into ~15-line demos. |
| [`telemetry_design.md`](telemetry_design.md) | Design notes for `slappyengine.telemetry`: low-overhead event emission (86 ns no-subscriber) plus the round-2 first-segment bucket-index 6.42x dispatch speedup. |
| [`tier_11_future_instructions.md`](tier_11_future_instructions.md) | Tier 11 GPU compute migration — deferred 2026-05-26; self-contained "how to do it if we come back" reference. |
| [`tier_11_gpu_compute_discussion.md`](tier_11_gpu_compute_discussion.md) | Tier 11 GPU compute (wgpu) discussion document — state-of-the-engine and trade-offs after Tiers 1-10 landed. |
| [`tutorial_build_a_game.md`](tutorial_build_a_game.md) | End-to-end "build a top-down arcade game" walk-through; 10 sections with 10 verified-runnable snippets (13/13 tripwire tests green, 215 lines). |
| [`video_output.md`](video_output.md) | Video output guide — MP4 default vs GIF fallback for SlapPyEngine's showcase and capture tools. |
| [`zones_design.md`](zones_design.md) | Design reference for `slappyengine.zones`: named axis-aligned rectangular regions with enter/exit callbacks, material tags, and scalar threshold events. |

## Per-subpackage API references (`docs/api/`)

Auto-generated by `scripts/gen_subpackage_api_docs.py`. Each lists every
public class / function / constant with full signatures and parsed
`Raises:` sections. Do not hand-edit.

| Path | Description |
|---|---|
| [`api/dynamics.md`](api/dynamics.md) | Auto-generated API reference for `slappyengine.dynamics` (Body, Material, JointSpec, RopeSpec, RagdollSpec, IKChainSpec, World, SoftBodyWorld, build_*, make_*, solve_ik, resolve_joint, save_world, load_world). |
| [`api/iso.md`](api/iso.md) | Auto-generated API reference for `slappyengine.iso` (IsoCamera, IsoCell, IsoEntity, IsoGrid, IsoScene, IsoTileDef, IsoViewpoint, plus the `iso.combat` Stone Keep module). |
| [`api/numerics.md`](api/numerics.md) | Auto-generated API reference for `slappyengine.numerics` (vcycle_poisson, sor_smooth, compute_residual). |
| [`api/telemetry.md`](api/telemetry.md) | Auto-generated API reference for `slappyengine.telemetry` (emit, subscribe, unsubscribe, low-overhead event bus surface). |
| [`api/testing.md`](api/testing.md) | Auto-generated API reference for `slappyengine.testing` visual regression harness (assert_scene_matches, render_scene_to_png, diff_pngs, baseline/diff directory constants). |
| [`api/thermal.md`](api/thermal.md) | Auto-generated API reference for `slappyengine.thermal` (HeatField plus the pairwise `exchange_two_regions` boundary exchange). |
| [`api/tools.md`](api/tools.md) | Auto-generated API reference for `slappyengine.tools` (`sprite_audit` CPU-only utility surface). |
| [`api/topology.md`](api/topology.md) | Auto-generated API reference for `slappyengine.topology` (connected-components / union-find primitives lifted from the bond solver). |
| [`api/zones.md`](api/zones.md) | Auto-generated API reference for `slappyengine.zones` (RectZone, ThresholdZone, ZoneManager, enter/exit + threshold callbacks). |
