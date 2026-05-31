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
