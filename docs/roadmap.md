# SlapPyEngine — Roadmap

> Living "what's next" document for the v0.3.x → v0.4 → v1.0 line. Source
> for each entry is cited inline so the rationale survives the next
> compaction.

The roadmap is organised by milestone band, not by sprint. Sprint-level
detail lives in `docs/sprint_*_retrospective.md` and the per-sprint plan
documents (`docs/sprint_*.md`).

---

## Near-term — v0.3.x (next 1-3 patch cycles)

Carry-overs from the active sprint chain plus the items the dead-code /
core-engine / hardening audits flagged as "fix before tag".

### Physics core — softbody / fluid WIP commit

- **What:** the in-progress edits parked under
  `python/slappyengine/softbody/` and `python/slappyengine/fluid/` are
  off-limits for the polish sprints (deliberate freeze — see the
  `2026-06-01 v3 refresh` reminder block in
  `benchmarks/baseline_report.md`). The next physics sprint reconciles
  those edits onto master so the rest of the engine can land follow-up
  changes that touch the Rust-backed substrate.
- **Source:** memory note
  `project_sprint_2026_05_29.md` ("C4 thermal-fluid held pending user
  fluid WIP reconcile"); `benchmarks/baseline_report.md` § 2026-06-01.

### Phase D strip-pass — step 6 follow-through

- **What:** `docs/phase_d_strip_plan_2026_05_31.md` enumerates an
  ordered cut list for the legacy `physics/` / `deform_*` /
  `boundary_exchange` modules. Steps 1-5 are behind the existing Phase B
  repackage (`topology`, `numerics`, `thermal`, `zones`). Step 6+ are
  gated on Ochema Circuit CI greenness — once green, walk the remaining
  cuts one commit per module, keeping the rebuild suite green at each
  step.
- **Source:** `docs/phase_d_strip_plan_2026_05_31.md` § (a) Ordered cut
  list; `docs/strip_pass_v2_audit.md`.

### Hardening — additional rounds

- **What:** rounds 1-13 covered the public-API entry points of every
  v0.3 subsystem (asset, audio, camera, dynamics, event bus, gpu, iso,
  layer, numerics, node-material, post-process, residency, telemetry,
  sprite_audit, action map, input manager, animation, assetdb). Open
  candidates: `slappyengine.compute` (ComputePass dispatch ranges +
  buffer sizes), `slappyengine.gi` (cascade params + denoiser feedback
  history), `slappyengine.material.MaterialMap`, the studio Stage
  builders (range checks on `view_box`, `floor_y`, etc.).
- **Source:** `docs/hardening_audit_2026_05_29.md`; companion
  `SlapPyEngineTests/tests/test_hardening_*.py` (20 files at v0.3.0b0); memory note
  `project_completion.md`.

### Rust migrations — remaining hot paths

- **What:** Rust kernels landed for renderer rasterisation, softbody
  XPBD, PBF inner step, `_kinetic_relax`, `_collide`, `_thermal_step`,
  `_drill_through`, `_slide`. Open candidates from the perf rollup:
  `_slump_loose` (still 31% share on Scenario A small),
  `_pbf_bridge_step` (32% share on Scenario B medium even after the YAML
  cache fix), and the per-particle `_slide` superlinear scaling on
  Scenario C large.
- **Source:** `benchmarks/baseline_report.md` § Sprint 2 + § 2026-06-01;
  `docs/rust_migration_plan.md`; `docs/rust_port_plan_dynamics.md`;
  memory note `project_rust_migration_final_2026_05.md`.

### Doc / inventory hygiene

- **What:** keep `docs/sprint_5_doc_inventory.md` in lockstep with new
  files under `docs/**`. Three test files lock the invariant
  (`SlapPyEngineTests/tests/test_docs_inventory.py`, `SlapPyEngineTests/tests/test_docs_links_resolve_all.py`,
  `SlapPyEngineTests/tests/test_docs_api_template_conformance.py`). Roll new hand-authored
  API docs through the `<!-- handauthored: do not regenerate -->` marker
  at the top of each file (see `docs/api/_template.md`).
- **Source:** `docs/sprint_5_doc_inventory.md`;
  `SlapPyEngineTests/tests/test_docs_inventory.py`; `docs/api/_template.md`.

### Ship-checklist closures

- **What:** the v0.3.0 ship gate (`docs/sprint_7_ship_checklist.md`)
  pinned six tripwires that must close before the first non-beta tag:
  game-compat tripwire 54/54, all-demos smoke 14/14 exit-zero,
  hardening green, perf dashboard ±10% band, docs link resolution,
  version consistency across `pyproject.toml` / `Cargo.toml` /
  `__init__.__version__`.
- **Source:** `docs/sprint_7_ship_checklist.md` § Gate criteria.

---

## Mid-term — v0.4 (next minor)

Driven by the subpackage-gap audit (`docs/core_engine_audit_2026_06_02.md`
+ `docs/dead_code_audit_2026_06_02.md`) and the serialization-gap
analysis (`docs/sprint_4_serialization_gaps.md`).

### `ai` / `animation` exposure

- **What:** `slappyengine.ai` ships LLM-client + Ollama-manager + code
  sync helpers but has no entry in the public surface map and no
  `docs/api/ai.md`. `slappyengine.animation` has a hand-authored API
  reference but the AnimationGraph state-machine surface is still
  marked "Phase A" in places. Both subpackages need a v0.3-style audit
  and a `docs/api/<x>.md` mirror.
- **Source:** memory note `project_editor_sprint.md` (Ollama manager
  shipped under `slappyengine.ai`);
  `docs/core_engine_audit_2026_06_02.md` § subpackage discoverability;
  `docs/api/animation.md`.

### ECS layer formalisation

- **What:** the engine currently leans on `Entity`, `Scene`, `Layer`,
  `DataComponent`, `Observable`, plus the `components.py` mixins. The
  topology / zones / dynamics subpackages already use light-weight
  manager objects (`ZoneManager`, `World`) rather than ECS systems.
  v0.4 candidate: formalise an ECS narrative (where systems live, how
  scheduling chains, how the existing `engine.tick` loop binds to
  per-subsystem `step(dt)` calls).
- **Source:** memory note `project_completion.md`;
  `python/slappyengine/__init__.py` top-level docstring (the engine-
  as-library tour already groups by Simulation / Rendering /
  Authoring / Game-compat).

### Audio backend hardening

- **What:** `slappyengine.audio_runtime` switches between `sounddevice +
  soundfile` and a silent stub at import time; the
  `AudioManager.play` boundary picked up `validate_handle` /
  `validate_volume` in round 8 but the *backend* path (sample-rate
  conversion, mono/stereo handling, ring-buffer underrun policy) is
  un-audited. v0.4 candidate: end-to-end audio integration test +
  validation pass.
- **Source:** `benchmarks/baseline_report.md` § Hardening overhead audit;
  `docs/api/audio_runtime.md`.

### Multiplayer rough patches

- **What:** the `slappy-engine[network]` extra installs Kademlia DHT +
  ICE hole-punching dependencies but the integration is under-
  documented. No `docs/api/network.md`. v0.4 candidate: spec the
  authoritative-host vs. relay-fallback path, document the discovery
  protocol, add a hardening round, and ship a `hello_multiplayer.py`
  smoke demo.
- **Source:** `README.md` install section (the `[network]` extra is
  advertised); memory note `project_completion.md` (P2P milestone).

### Serialization gap closure

- **What:** `dynamics.save_world` / `load_world` is the only first-class
  JSON round-trip. `HeatField`, `ZoneManager`, `SimField`, and the
  particle field all have parity-test probes asserting their *absence*.
  v0.4 candidate: ship `to_dict` / `from_dict` on the remaining sim
  subsystems, framed in the same JSON envelope as `World`.
- **Source:** `docs/sprint_4_serialization_gaps.md` § 1-N (each missing
  subsystem); `SlapPyEngineTests/tests/test_composite_serialize_roundtrip.py`.

### Telemetry subscriber backpressure

- **What:** the 6.42× bucket-index speedup landed in round 2
  (`docs/telemetry_design.md`) but subscriber backpressure (slow handler
  blocking the publisher) is not addressed. v0.4 candidate: an async
  dispatch tier or a ring-buffer drop policy.
- **Source:** `docs/telemetry_design.md`;
  `python/slappyengine/telemetry.py`; memory note
  `project_phase_b_repackage.md`.

---

## Long-term — v1.0 (API freeze candidates)

Items that depend on the three flagship downstream games (Ochema Circuit,
Bullet Strata, Stone Keep) migrating off the legacy compat surface.

### Deprecated alias removal

- **What:** `make_humanoid` / `wrap_in_flesh` were shipped as deprecated
  aliases of `build_humanoid` / `build_flesh_wrap` in Sprint R-D and
  still have 9 internal callers (4 examples, 4 tests, 1 comment-only).
  v1.0 candidate: migrate every caller in a single sweep, drop the
  aliases.
- **Source:** `docs/dead_code_audit_2026_06_02.md` § Task 1
  (deprecated alias internal callers).

### `_compat`-routed symbol cleanup

- **What:** `MaterialPreset`, `CrackMode`, `SimState`,
  `SimFrequencyBudget`, `DeformController`, `ZoneMap`, `CellMaterial`,
  `cell_material_for` resolve through `_LAZY_MAP` → `_compat.py` purely
  to satisfy the game-compat tripwire test. Zero direct
  `from slappyengine import` callers exist on master today.
- **Source:** `docs/core_engine_audit_2026_06_02.md` § 1b (compat-routed
  symbol usage). The audit lists exact migration targets per symbol
  (e.g. `MaterialPreset.X` → `"x"` string against
  `softbody.material.MATERIALS`).

### API freeze candidates

- **What:** the v0.3 public surface (75 symbols across 21 subpackages —
  see `docs/engine_surface_v030.md`) becomes the v1.0 freeze candidate
  *modulo* the compat removals above. Specific freeze blockers:
  - `studio.Stage` field shape (currently tracking the in-flux rebuild
    physics layer);
  - `post_process` UBO layouts (the `PARAMS_LAYOUT` + `UboField`
    migration in `672e893` finalised this for the eight complex passes,
    but the legacy `params` dict path still exists for parity);
  - `dynamics.JointSpec` kind enum (seven kinds today — any addition
    breaks `save_world` schema compatibility, hence the
    `SCHEMA_VERSION` field already in place).
- **Source:** `docs/engine_surface_v030.md`;
  `docs/sprint_4_serialization_gaps.md` § What IS serialisable today;
  commit `672e893` (post-process base-class migration).

### GPU compute (Tier 11)

- **What:** Tier 11 (wgpu compute migration) was deferred at the end of
  the Rust migration sprint pending user discussion. Re-evaluate for
  v1.0 against the per-kernel break-even thresholds the Sprint 2
  benchmark established (`_collide` ≥ 30k, `_thermal_step` never,
  `_kinetic_relax` ≥ 2k, etc.). A clean win likely requires a
  `GpuPolicy` helper that auto-flips opt-in flags per workload.
- **Source:** `docs/tier_11_gpu_compute_discussion.md`;
  `docs/tier_11_future_instructions.md`;
  `benchmarks/baseline_report.md` § Recommended default-ON threshold
  (per kernel).

### Per-pixel materials hierarchical hulls

- **What:** the per-pixel materials sim is converging toward nested
  hulls with √2 layers + state-disagreement subdivision + transforms at
  hull level (memory directive). The convergence is partial today —
  v1.0 candidate is the full architectural landing of that pattern.
- **Source:** memory note `project_materials_hierarchical_hulls.md`.

---

## How to add a roadmap entry

Roadmap entries follow a simple shape:

1. **What:** one paragraph describing the deliverable and acceptance
   shape.
2. **Source:** explicit citation — memory note path, design doc path,
   sprint retrospective path, or perf-bench section. Never leave an
   entry without a source.

Entries graduate (near-term → mid-term → long-term) only when their
source citation also bumps; otherwise leave them in place. When an
entry lands, remove it from the roadmap and add a line to the relevant
`CHANGELOG.md` section instead.
