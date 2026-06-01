# Changelog

All notable changes to SlapPyEngine (`slappy-engine` on PyPI).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-05-31

v0.3 widens the public engine surface from physics + render kernels to a full
set of game-side primitives: dynamics, zones, topology, numerics, thermal,
iso, telemetry, and a visual-regression testing harness. Every new subpackage
ships as a top-level lazy export so games can `import slappyengine as sle`
and reach the contract without knowing the on-disk layout. Beta-tested vs
Ochema Circuit (1124/1126) and Bullet Strata (54/54).

The full v0.3 surface is auto-generated at
[`docs/engine_surface_v030.md`](docs/engine_surface_v030.md) — 75 top-level
symbols across 19 declared subpackages.

### Added

**New subpackages (top-level lazy exports):**

- `slappyengine.dynamics` — unified XPBD primitives: `Body`, `Material`,
  `JointSpec` (7 kinds), `RopeSpec`, `RagdollSpec`, `IKChainSpec`, `World`,
  `SoftBodyWorld`, plus authoring helpers `build_rope`, `build_ragdoll`,
  `make_spring`, `make_motor`, `solve_ik`, `resolve_joint`. JSON round-trip
  via `save_world` / `load_world` (byte-identical 0.0 step error, 20/20
  green). Reference: [`docs/dynamics_design.md`](docs/dynamics_design.md).
- `slappyengine.dynamics.humanoid` — humanoid skeleton (`make_humanoid`,
  `Humanoid` dataclass), flesh-wrap (`wrap_in_flesh`, layer constants
  `LAYER_BONE` / `LAYER_MUSCLE` / `LAYER_SKIN`), and foot-IK terrain
  placement (`place_feet_on_terrain`). Sprint 2A.
- `slappyengine.dynamics` joint authoring — `make_distance` factory for
  distance constraints and `resolve_joint_specs` batch resolver round
  out the Sprint 7A joint surface alongside `resolve_joint`.
- `slappyengine.zones` — generic zone primitives (`RectZone`,
  `ThresholdZone`, `ZoneManager`, enter/exit + threshold callbacks).
  Optional spatial-hash backend for 10.9x speedup at 1000 entities.
- `slappyengine.topology` — connected-components / union-find primitives
  lifted from the bond solver.
- `slappyengine.numerics` — generic numerical kernels: `vcycle_poisson`,
  `sor_smooth`, `compute_residual`.
- `slappyengine.thermal` — `HeatField` plus `exchange_two_regions`
  pairwise boundary exchange.
- `slappyengine.iso` — isometric 2D-grid-with-Z rendering: `IsoCamera`,
  `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`,
  `IsoViewpoint`, plus an `iso.combat` module (Phase C3 / Stone Keep).
- `slappyengine.telemetry` — low-overhead event emission (86 ns when no
  subscriber is attached; 6.42x dispatch speedup with subscribers via
  first-segment bucket index). Design:
  [`docs/telemetry_design.md`](docs/telemetry_design.md).
- `slappyengine.testing` — visual regression harness:
  `assert_scene_matches`, `render_scene_to_png`, `diff_pngs`,
  baseline/diff directory constants.
- `slappyengine.tools.sprite_audit` — sprite-anchor / atlas audit utility
  (CPU-only). Recipe: [`docs/sprite_audit_recipe.md`](docs/sprite_audit_recipe.md).
- `slappyengine.audio_runtime` — soft-import with silent-stub fallback so
  headless test environments load cleanly.

**Ochema engine-surface registration (Phase C):**

- Race-scene names added to the top-level `_LAZY_MAP`:
  `CatmullRomSpline`, `SplineTrack`, `PlayerInputProvider`, `CacheMode`,
  `PixelCollisionPass`.
- Phase C close-out: `TriggerSystem`, `ZoneMap`, `GpuParticleSystem`,
  `Observable`, module-level `event_bus.publish` / `subscribe`,
  `StrataWorld` / `StrataLayer`, `RigidBody`, `DeformableLayer`,
  `InputDriven` components.

**Cross-subsystem serialization:**

- Unified JSON + YAML round-trip for `thermal`, `zones`, `iso.combat`,
  `telemetry`, and `SaveGame` (15/15 green).
- `WaveSchedule` round-trip fix (uses `_waves` attribute, not `specs`).
- `SetVersion.bat` helper for version-string consistency.

**Studio / demo authoring (Sprint 7G):**

- `slappyengine.studio.dynamics_stage` — turn-key Stage wrapper around a
  `dynamics.World` with a default PIL renderer, joining the existing
  `softbody_stage` / `fluid_stage` / `humanoid_stage` set so demos can
  record dynamics scenes with the same 3-line recipe.

**Game-compat shims (Sprint 5B + R2S1-B):**

- `slappyengine._compat` surfaces back-compat names lifted from retired
  Ochema / Bullet Strata subsystems so downstream games keep importing
  cleanly: `MaterialPreset` and `CrackMode` enums, `SimState` and
  `SimFrequencyBudget` minimal stubs, `DeformController` no-op shim,
  `ZoneMap` alias of `zones.ZoneManager`, `CellMaterial` dataclass +
  `cell_material_for` lookup ported verbatim from the legacy
  `deform_modes` module.

**Engine + tooling:**

- `Engine.run(max_frames=N)` — CI-driveable bounded run for demo smoke
  (Sprint 2C).
- Perf dashboard (`tools/perf_dashboard`) — 6 subsystems, regression
  tripwire on Sprint 6 baselines.
- All-demos integration smoke harness (29 demos discovered, 13 hello_*
  demos in the gallery grid).
- Auto-generated subpackage API reference (9 docs, 30/30 green).
- Editor `spawn_menu` gains rope / ragdoll / IK chain / humanoid
  (Sprint 2F) actions; property inspector reflects dynamics dataclasses
  via runtime introspection (Sprint 3G); material editor extended via
  reflection.

**Demos & docs:**

- `examples/hello_rope.py` — XPBD rope droop reference (2.02 m baseline).
- `examples/hello_ragdoll.py` — humanoid ragdoll demo.
- `examples/hello_ik_chain.py` — CCD IK over a 5-link chain.
- `examples/hello_motor.py` — `MotorSpec` driving a wheel hub + 2 rims
  (ω error 0.05%).
- `examples/hello_spring.py` — 1D Hookean oscillator (2.06% period error).
- `examples/hello_joint.py` — distance / weld / ball / hinge in one scene.
- `examples/hello_thermal.py` — two `HeatField` grids with edge contact.
- `examples/hello_zone.py` — three `RectZone`s + `ThresholdZone` tracking.
- `examples/hello_iso.py` — 10×10 iso arena with wave schedule + combat.
- `examples/hello_telemetry.py` — 60-frame timeline + 100k-emit bench.
- `examples/hello_topology.py` — union-find on 8×8 grid, 64→1 components.
- `examples/hello_numerics.py` — 64×64 Poisson V-cycle solve.
- `examples/hello_audio.py` — `audio_runtime` + sounddevice fallback.
- `examples/hello_composite.py` — iso combat + rope + zones + thermal in
  one scene, telemetry-wired.
- `examples/hello_dynamics_serialize.py` — byte-identical round-trip
  (0.0 delta, 4.4 KB on disk for 16-node rope).
- [`docs/dynamics_quickstart.md`](docs/dynamics_quickstart.md) — 10-minute
  hands-on guide with 6 runnable snippets.
- [`docs/tutorial_build_a_game.md`](docs/tutorial_build_a_game.md) — full
  game tutorial (10 sections, 10 verified-runnable snippets).
- [`docs/getting_started.md`](docs/getting_started.md) — game-dev
  tutorial (8 verified-runnable snippets).
- [`docs/examples_smoke_2026_05_31.md`](docs/examples_smoke_2026_05_31.md)
  — read-only audit of every example on master.
- [`docs/sprint_7_ship_checklist.md`](docs/sprint_7_ship_checklist.md),
  [`docs/perf_dashboard.md`](docs/perf_dashboard.md),
  [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md),
  [`docs/rust_port_plan_dynamics.md`](docs/rust_port_plan_dynamics.md).

### Changed

**Lighting / post-process rounds 2–9:**

- Round 2 (GTAO) — depth-adaptive sample radius (Jimenez 2016) plus
  Sprint 4C `multibounce` toggle on `GTAOPass` (Jimenez 2016 §2.3
  multibounce-visibility approximation, default on).
- Round 3 (Bloom) — Lottes 2017 smooth threshold replaces the binary
  cutoff (14/14 green); Sprint 3D adds 13-tap Mitchell-Netravali
  downsample + 9-tap tent upsample (`upsample_tent9`) for a smoother
  Gaussian-shaped bloom lobe with no extra ringing.
- Round 3 (TAA) — Karis luminance-inverse weighted blend cuts ghosting
  on motion-heavy scenes by 41.3%.
- Round 4 (Vignette) — smoothstep falloff with `inner_radius` + `feather`
  (-23% banding vs legacy quadratic).
- Round 4 (TAA) — variance-based AABB tightening (Salvi 2016).
- Round 4 (TAA) — `tight_variance_clip` now defaults to `True`
  (`variance_clip_gamma=1.0`, Salvi's canonical 1-sigma envelope) after
  Sprint 4D confirmed off-path baselines stay bit-identical. The new
  default delivers Sprint 3D's headline win on disocclusion bands:
  -19.5% ghost residual and +1 dB PSNR vs the legacy min/max envelope,
  with no measurable cost on converged frames. Pass
  `tight_variance_clip=False` to restore the round-3 behaviour.
- Round 5 (TAA, Sprint 5C + R2S1-F) — motion-vector-aware disocclusion
  rejection adds `reject_on_depth_disocclusion` (Andersson INSIDE 2015)
  and `reject_on_normal_disocclusion` (Karis Siggraph 2014) fields on
  `TAAPass`; defaults on, opt out per field to restore Round 4 behaviour.
- Round 5 (Outline) — Sobel + smoothstep edge detection (-84% temporal
  flicker, 13/13 green).
- Round 6 (Chromatic aberration) — Lottes 2014 polynomial falloff (+47%
  corner fringing, 6/6 green).
- Round 7 (Tonemap) — auto-EV via log-luminance + smoothing (95%
  convergence in ~58 frames).
- Round 8 (Render channels) — Kahn topological sort with `depends_on` +
  insertion-order tie-break.
- Round 9 (DoF) — `focus_transition` shape parameter with smoothstep
  softening / sharpening (backward-compat at `transition=1.0`).
- Preset chains — `cinematic` / `arcade` / `iso-strategy`; `add_dof` and
  `add_bloom` helpers; `PostProcessPass.depends_on` field.

**Perf:**

- `numerics.vcycle_poisson` — 2.45x speedup at 256×256 (dropped redundant
  mask multiplies + strided restrict; hot path now ~73% raw numpy).
- `zones` — spatial-hash backend, 10.9x speedup at 1000 entities (parity
  preserved, opt-out via `enable_spatial_hash(False)`).
- `telemetry` — first-segment bucket index, 6.42x dispatch speedup at
  1000 subscribers.
- `EventBus.publish` — inline fast-path validation (218 ns → ~140 ns).
- Sprint 6 perf tripwire — numerics -43%, dynamics 100-node lattice -59%
  steady-state, 80 demo tests green.

**Hardening — input validation at public boundaries.** Six rounds caught
**46+ silent-acceptance bugs** across the v0.3 surface:

- Round 1 (dynamics) — `Body`, `Material`, `JointSpec` family, `RopeSpec`,
  `RagdollSpec`, `IKChainSpec`, and `build_*` / `make_*` helpers raise on
  invalid input at construction. **8 silent-bug classes** (89 tests green).
- Round 2 (zones / topology / numerics / thermal / iso) — `_validation`
  modules on all five Phase-B subpackages. **24 silent-acceptance bugs**
  (111 tests green); worst offender was `WaveSpec(spawn_points=[])`
  raising `ZeroDivisionError` deep inside `tick()`.
- Round 3 (post_process / telemetry / testing / sprite_audit) — 73
  negative tests, 14 silent-acceptance bugs, plus a path-traversal fix in
  `assert_scene_matches`.
- Round 4 (camera / event_bus / action_map) — 41 tests, caught `zoom=0`
  div-by-zero + NaN position + bytes `event_type` silent mismatch.
- Round 5 (AssetDatabase / ResidencyManager) — 45 tests, caught
  `register_handler` ext-without-dot silent dead handler + NaN position
  cascade data-loss.
- Round 6 (animation graph) — 22 tests, caught empty-name + NaN fps +
  non-callable condition + negative-dt silent path.
- Dynamics over-damp warning — fires once process-wide at
  `1 - (1 - damping)^iters > 0.5`, no longer spams the test suite.

**Visual harness baselines** — `slappyengine.testing` underpins demo
baselines for `hello_rope`, `hello_ragdoll`, `hello_ik_chain`,
`hello_motor`, `hello_spring`, `hello_joint`, `hello_thermal`,
`hello_zone`, `hello_iso`, `hello_telemetry`, `hello_topology`,
`hello_numerics`, `hello_audio`, `hello_composite`, and
`hello_dynamics_serialize`, plus the lighting round-4 side-by-side
baselines.

**Internal:**

- Phase B repackages — `topology`, `numerics`, `thermal`, `zones` lifted
  from legacy locations into first-class subpackages with stable surfaces.
- Phase C1 — Ochema race-scene engine-surface tripwire + completed
  `_LAZY_MAP`.
- Phase C2/C3 — `audio_runtime` shim, `iso.combat` for Stone Keep.
- Phase D dry-run audit — strip-pass v2 deletion candidates enumerated at
  [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md); no files
  deleted, gated on downstream-game CI. Step 1 marked BLOCKED — `world.py`
  is a live frontier consumer.
- Cross-package integration scene — `iso/zones/thermal/dynamics`
  exercised together as one 6/6 regression test (v2 of the harness).
- Game-compat tripwire — 54 names across Ochema / Bullet Strata / Stone
  Keep, 39 pass + 15 xfail tracking Phase C gaps (now closed in Phase C).
- Sprint 7 ship-readiness — version-consistency tripwire
  (`tests/test_version_consistency.py`), `_KNOWN_BROKEN` ratchet
  (20-entry ceiling tracking uncommitted-WIP module gaps).

### Fixed

- `TAA` executor — splice width / height into pre-packed `TaaParams` UBO
  (previously stale).
- `SVGFDenoiser` — restored CPU `denoise_numpy` path + `reset_history()`
  API (Sprint 2B).
- `Layer3D.lighting_mode` + `gbuffer_target` setter — wires through to
  `defer_2d` (4 tests recovered).
- `IKChainSpec.node_indices` validator — rejects non-int (float was
  silently truncated to 1; docstring-validator mismatch surfaced by API
  reference auto-gen).
- `WaveSchedule` round-trip — uses `_waves` attribute, not `specs`.
- `collision.stamp_entity` / `stamp_all_entities` — implemented.
- `NodeMaterial` — restored sim-field / math / output node factories.

### Removed

- Stale `slappyengine.compose` reference in the previous README.
- Legacy `mud_pool` demo (replaced by `ParticleField` polish series).
- Phase D `Unreleased` placeholder section (work landed under this
  version).

## [0.2.0a0] — 2026-05-25

Pre-Rust-migration alpha. Pure-Python physics + numpy renderers. See git
history for incremental changes.

## [0.1.0a0]

Initial alpha pre-release.
