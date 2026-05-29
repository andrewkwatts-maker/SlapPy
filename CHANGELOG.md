# Changelog

All notable changes to SlapPyEngine (`slappy-engine` on PyPI).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-05-29

v0.3 widens the public engine surface from physics/render kernels to a full
set of game-side primitives: dynamics, zones, topology, numerics, thermal,
iso, telemetry, and a visual-regression testing harness. Every new
subpackage ships as a top-level lazy export so games can `import slappyengine
as sle` and reach the contract without knowing the on-disk layout.

The full v0.3 surface is auto-generated at
[`docs/engine_surface_v030.md`](docs/engine_surface_v030.md) — 75 top-level
symbols across 19 declared subpackages.

### Added

**New subpackages (top-level lazy exports):**

- `slappyengine.dynamics` — unified XPBD primitives: `Body`, `Material`,
  `JointSpec` (7 kinds), `RopeSpec`, `RagdollSpec`, `IKChainSpec`,
  `World`, `SoftBodyWorld`, plus authoring helpers `build_rope`,
  `build_ragdoll`, `make_spring`, `make_motor`, `solve_ik`,
  `resolve_joint`. Reference: [`docs/dynamics_design.md`](docs/dynamics_design.md).
- `slappyengine.zones` — generic zone primitives (`RectZone`,
  `ThresholdZone`, `ZoneManager`, enter/exit and threshold callbacks).
- `slappyengine.topology` — connected-components / union-find primitives
  lifted from the bond solver.
- `slappyengine.numerics` — generic numerical kernels: `vcycle_poisson`,
  `sor_smooth`, `compute_residual`.
- `slappyengine.thermal` — `HeatField` plus `exchange_two_regions`
  pairwise boundary exchange.
- `slappyengine.iso` — isometric 2D-grid-with-Z rendering: `IsoCamera`,
  `IsoCell`, `IsoEntity`, `IsoGrid`, `IsoScene`, `IsoTileDef`,
  `IsoViewpoint`, plus an `iso.combat` module (Phase C3 / Stone Keep).
- `slappyengine.telemetry` — low-overhead event emission (86ns when no
  subscriber is attached). Design: [`docs/telemetry_design.md`](docs/telemetry_design.md).
- `slappyengine.testing` — visual regression harness:
  `assert_scene_matches`, `render_scene_to_png`, `diff_pngs`,
  baseline/diff directory constants.
- `slappyengine.tools.sprite_audit` — sprite-anchor / atlas audit utility
  (CPU-only). Recipe: [`docs/sprite_audit_recipe.md`](docs/sprite_audit_recipe.md).

**Ochema engine-surface registration:**

- `CatmullRomSpline`, `SplineTrack`, `PlayerInputProvider`, `CacheMode`,
  `PixelCollisionPass` added to the top-level `_LAZY_MAP` so race-scene
  imports resolve directly off `slappyengine`.

**Demos & editor:**

- `examples/hello_rope.py` — XPBD rope droop reference (2.02m droop
  baseline).
- `examples/hello_ragdoll.py` — humanoid ragdoll demo with visual
  baseline.
- `examples/hello_ik_chain.py` — CCD IK over a 5-link chain tracking
  an orbiting target.
- Editor `spawn_menu` gains rope / ragdoll / IK chain actions; property
  inspector and material editor extended via reflection.

### Improved

- **Lighting round 2** — GTAO depth-adaptive radius (Jimenez 2016).
- **Lighting round 3 (bloom)** — Lottes 2017 smooth threshold replaces
  the binary cutoff (14/14 regression tests green).
- **Lighting round 3 (TAA)** — Karis luminance-inverse weighted blend
  cuts ghosting by ~41% on motion-heavy scenes.
- **Hardening** — dynamics primitives now validate input at the public
  API boundary; 89-test hardening suite catches 8 silent-bug classes.
- **Audio runtime** — `slappyengine.ext.audio_runtime` soft-imports
  with a silent-stub fallback so headless test environments load
  cleanly.

### Internal

- **Phase B repackages** — `topology`, `numerics`, `thermal`, and
  `zones` lifted out of legacy locations into first-class subpackages
  with stable surfaces.
- **Phase C1** — Ochema race-scene engine-surface tripwire +
  completed `_LAZY_MAP`.
- **Phase D dry-run audit** — strip-pass v2 enumerates deletion
  candidates and their consumer counts at
  [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md). No
  files deleted; gated on downstream-game CI.
- **Cross-package integration scene** — `iso/zones/thermal/dynamics`
  exercised together as one 6/6 regression test.
- **Visual harness** — `slappyengine.testing` underpins demo baselines
  (hello_rope, hello_ragdoll, hello_ik_chain).

### Documentation

- [`docs/engine_surface_v030.md`](docs/engine_surface_v030.md) — auto-generated reference for the v0.3 public surface (regenerate via `scripts/gen_engine_surface_doc.py`).
- [`docs/dynamics_design.md`](docs/dynamics_design.md) — XPBD substrate, `JointSpec` kinds, authoring helpers, failure modes.
- [`docs/strip_pass_v2_audit.md`](docs/strip_pass_v2_audit.md) — Phase D deletion-candidate audit (dry-run).
- [`docs/sprite_audit_recipe.md`](docs/sprite_audit_recipe.md) — sprite-anchor audit workflow.
- [`docs/telemetry_design.md`](docs/telemetry_design.md) — telemetry module design.

## [0.2.0a0] — 2026-05-25

Pre-Rust-migration alpha. Pure-Python physics + numpy renderers. See
git history for incremental changes.

## [0.1.0a0]

Initial alpha pre-release.
