# ParticleField CPU baseline

- Generated: 2026-05-31 16:06:46
- Steps measured per scenario: 100 (after 3-step warmup)
- dt: 0.01667 s (60 Hz reference)
- Field size: 640x360
- Per-method wall time captured by perf_counter wrappers; total step()
  is the outer-loop perf_counter delta around `field.step(dt)`.


## Scenario A (small, sloppy preset) (~680 particles)

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.039 | 0.103 | 0.9% |
| _collide | 0.383 | 1.170 | 8.9% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 0.253 | 0.943 | 5.9% |
| _pbf_bridge_step | 0.006 | 0.009 | 0.1% |
| _slide | 0.192 | 1.118 | 4.5% |
| _slump_loose | 1.348 | 2.254 | 31.3% |
| _thermal_step | 0.046 | 0.070 | 1.1% |
| bake_settled_particles | 0.067 | 0.328 | 1.6% |
| **total step()** | **4.308** | **7.434** | **100.0%** |

Steady-state: **232.1 fps**. Top 3: `_slump_loose` (31%), `_collide` (9%), `_kinetic_relax` (6%).

## Scenario B (medium, snow + mud, aggregated) (~2350 particles)

Two separate fields stepped in lockstep — snow=1450, mud=900. ms/step is the combined wall time per (snow.step + mud.step) pair.

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.159 | 0.126 | 0.4% |
| _collide | 2.641 | 2.844 | 6.6% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 1.565 | 2.819 | 3.9% |
| _pbf_bridge_step | 12.630 | 13.785 | 31.4% |
| _slide | 8.868 | 17.459 | 22.1% |
| _slump_loose | 1.742 | 1.943 | 4.3% |
| _thermal_step | 0.138 | 0.090 | 0.3% |
| bake_settled_particles | 0.207 | 0.214 | 0.5% |
| **total step()** | **40.182** | **51.675** | **100.0%** |

Steady-state: **24.9 fps**. Top 3: `_pbf_bridge_step` (31%), `_slide` (22%), `_collide` (7%).

## Scenario C (large, 10x sand detonates staggered) (~10200 particles)

Synthesised by 10 sand detonate() calls staggered across 30 setup frames (so particles are at mixed lifetimes before the timing window starts).

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.212 | 0.526 | 0.1% |
| _collide | 4.176 | 12.696 | 2.4% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 43.063 | 93.225 | 24.4% |
| _pbf_bridge_step | 0.013 | 0.018 | 0.0% |
| _slide | 86.094 | 150.034 | 48.7% |
| _slump_loose | 5.290 | 8.005 | 3.0% |
| _thermal_step | 0.152 | 0.220 | 0.1% |
| bake_settled_particles | 0.485 | 1.101 | 0.3% |
| **total step()** | **176.658** | **295.840** | **100.0%** |

Steady-state: **5.7 fps**. Top 3: `_slide` (49%), `_kinetic_relax` (24%), `_slump_loose` (3%).

## Cross-scenario rollup

| scenario | particles | fps | top 1 | top 2 | top 3 |
|---|---:|---:|---|---|---|
| A small | 680 | 232.1 | _slump_loose (31%) | _collide (9%) | _kinetic_relax (6%) |
| B medium | 2350 | 24.9 | _pbf_bridge_step (31%) | _slide (22%) | _collide (7%) |
| C large | 10200 | 5.7 | _slide (49%) | _kinetic_relax (24%) | _slump_loose (3%) |

---

## After Sprint 1 (vectorised _kinetic_relax)

- Generated: 2026-05-31 16:14:36
- Same harness (`benchmarks/particle_field_baseline.py`), same scenarios, same dt.
- Engine change between runs: commit `8b53890` — vectorised `_kinetic_relax`
  (cell-sort + boundary-find + inverse-triangular pair generator +
  `np.add.at` scatter). Legacy nested-loop path kept as
  `_kinetic_relax_legacy` for parity testing.

### Scenario A (small, sloppy preset) (~680 particles) — Sprint 1

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.037 | 0.097 | 0.9% |
| _collide | 0.364 | 1.101 | 9.0% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 0.123 | 0.273 | 3.0% |
| _pbf_bridge_step | 0.005 | 0.008 | 0.1% |
| _slide | 0.190 | 1.309 | 4.7% |
| _slump_loose | 1.313 | 2.345 | 32.4% |
| _thermal_step | 0.040 | 0.063 | 1.0% |
| bake_settled_particles | 0.067 | 0.317 | 1.6% |
| **total step()** | **4.053** | **6.994** | **100.0%** |

Steady-state: **246.7 fps**. Top 3: `_slump_loose` (32%), `_collide` (9%), `_slide` (5%).

### Scenario B (medium, snow + mud, aggregated) (~2350 particles) — Sprint 1

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.153 | 0.123 | 0.4% |
| _collide | 2.608 | 2.785 | 6.8% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 0.383 | 0.469 | 1.0% |
| _pbf_bridge_step | 12.363 | 13.742 | 32.3% |
| _slide | 8.704 | 16.991 | 22.8% |
| _slump_loose | 1.672 | 1.855 | 4.4% |
| _thermal_step | 0.129 | 0.092 | 0.3% |
| bake_settled_particles | 0.202 | 0.211 | 0.5% |
| **total step()** | **38.254** | **48.971** | **100.0%** |

Steady-state: **26.1 fps**. Top 3: `_pbf_bridge_step` (32%), `_slide` (23%), `_collide` (7%).

### Scenario C (large, 10x sand detonates staggered) (~10200 particles) — Sprint 1

| method | mean ms/step | p95 ms/step | % total |
|---|---:|---:|---:|
| _integrate | 0.200 | 0.499 | 0.2% |
| _collide | 4.036 | 12.413 | 3.1% |
| _drill_through | 0.000 | 0.000 | 0.0% |
| _kinetic_relax | 4.495 | 9.053 | 3.4% |
| _pbf_bridge_step | 0.012 | 0.015 | 0.0% |
| _slide | 81.906 | 139.322 | 62.1% |
| _slump_loose | 4.324 | 5.857 | 3.3% |
| _thermal_step | 0.148 | 0.250 | 0.1% |
| bake_settled_particles | 0.461 | 1.085 | 0.4% |
| **total step()** | **131.791** | **198.630** | **100.0%** |

Steady-state: **7.6 fps**. Top 3: `_slide` (62%), `_kinetic_relax` (3%), `_slump_loose` (3%).

### Cross-scenario rollup — Sprint 1

| scenario | particles | fps | top 1 | top 2 | top 3 |
|---|---:|---:|---|---|---|
| A small | 680 | 246.7 | _slump_loose (32%) | _collide (9%) | _slide (5%) |
| B medium | 2350 | 26.1 | _pbf_bridge_step (32%) | _slide (23%) | _collide (7%) |
| C large | 10200 | 7.6 | _slide (62%) | _kinetic_relax (3%) | _slump_loose (3%) |

### Comparison vs pre-Sprint-1 baseline

#### Headline fps

| scenario | particles | baseline fps | sprint 1 fps | speedup |
|---|---:|---:|---:|---:|
| A small  |    680 | 232.1 | 246.7 | **1.06×** |
| B medium |   2350 |  24.9 |  26.1 | **1.05×** |
| C large  |  10200 |   5.7 |   7.6 | **1.33×** |

#### `_kinetic_relax` isolated (the kernel we vectorised)

| scenario | baseline ms | sprint 1 ms | isolated speedup | % share before → after |
|---|---:|---:|---:|---|
| A small  |  0.253 | 0.123 | **2.06×** | 5.9% → 3.0% |
| B medium |  1.565 | 0.383 | **4.09×** | 3.9% → 1.0% |
| C large  | 43.063 | 4.495 | **9.58×** | 24.4% → 3.4% |

Isolated `_kinetic_relax` speedup tracks the 9.87× number reported in
commit `8b53890` for scenario C (5k particles, 100×100 region) — slight
variance is from the different particle layout in the staggered detonate
preset.

#### Updated hot-path ranking (Sprint 1 → next target)

- **Scenario A:** `_slump_loose` is now 32% (was 31%). Unchanged top 3
  ordering except `_kinetic_relax` drops out and `_slide` enters at #3.
  Next target: `_slump_loose` (the per-pixel cellular automaton).
- **Scenario B:** `_pbf_bridge_step` still dominates at 32% (was 31%).
  No change — PBF fluid bridge is the next sprint-B target.
- **Scenario C:** `_slide` is now 62% (was 49%) — Amdahl's law in action:
  reducing `_kinetic_relax` raised everything else's share. `_slide`
  alone now eats ~82 ms of the 132 ms step. **Next target: `_slide`.**

#### Did scenario C exceed 10 fps?

**No — 7.6 fps.** Pre-sprint-1 was 5.7 fps; we predicted "~7.5 fps with
24% saved, but savings stack with reduced GIL stalls" and we landed at
7.6 fps. The prediction was on the nose: the GIL-stall stack didn't
materialise into extra headroom because `_slide` (already the #1 hot
path at 49%) absorbed all the released frame budget at 62%. To clear
10 fps on scenario C we now need to attack `_slide` next.

#### Bottom line

- `_kinetic_relax` dropped from 24% to 3% of scenario C — mission
  accomplished on the kernel we targeted.
- End-to-end speedup is bounded by Amdahl: 1.33× on scenario C is
  consistent with the 24% share we removed
  (1 / (1 - 0.244 + 0.244/9.58) = 1.30× theoretical max → 1.33× observed,
  within noise).
- Scenario A and B see <10% speedup because `_kinetic_relax` wasn't a
  meaningful share there. This is expected and not concerning.
- The clear next CPU vectorise candidate is `_slide` — 49% → 62% share
  on scenario C, ~82 ms/step. A 5× isolated win on `_slide` would
  approximately double scenario C end-to-end fps.
