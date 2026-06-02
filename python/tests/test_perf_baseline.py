"""Performance regression baselines for the rebuild physics stack.

These tests aren't tight — they only catch ORDER-OF-MAGNITUDE regressions
(e.g. someone rebuilding shader pipelines per-frame, or removing a numpy
vectorisation in favour of a Python loop). The thresholds are
intentionally ~3x the local measured baseline (2026-05-25) so they don't
flake on slower CI machines.

Last-measured baselines on the developer workstation (2026-05-26):
  * softbody step  ~ 6.2 ms / frame   (3 wood lattices, 4x4 cells each)
                     was 7.8 ms before broadphase batching;
                     bigger scenes scale ~35% better.
  * pbf_step       ~ 3.6 ms / frame   (140 water particles)
                     was 4.9 ms before the bincount substitution.
  See project_perf_2026_05.md for the breakdown — bincount for PBF
  transient accumulators, batched 9-cell searchsorted for softbody
  broadphase.

If a test here fires red, the right first step is to compare against the
last green git commit on the touched module — not to bump the threshold.
"""
from __future__ import annotations

import time

import pytest

from slappyengine.softbody import SoftBodyWorld, make_lattice_body, step
from slappyengine.fluid import FluidWorld, pbf_step


# Generous thresholds — 3x baseline. Adjust upward only if hardware
# changed permanently; downward if you intentionally optimised.
SOFTBODY_STEP_BUDGET_MS = 30.0
PBF_STEP_BUDGET_MS = 20.0


def _avg_step_ms(world, step_fn, frames: int = 30, warmup: int = 5) -> float:
    """Average per-step wall-clock in milliseconds.

    Warmup discards the first ``warmup`` steps to avoid JIT-style first-call
    overhead skewing the average.
    """
    for _ in range(int(warmup)):
        step_fn(world)
    t0 = time.perf_counter()
    for _ in range(int(frames)):
        step_fn(world)
    return (time.perf_counter() - t0) / max(frames, 1) * 1000.0


def test_softbody_step_baseline_under_30ms_avg():
    """Three wood lattice bodies dropped under gravity. Step time must stay
    well under one 60Hz frame."""
    sb = SoftBodyWorld()
    sb.config["floor_y"] = 5.0
    for i in range(3):
        make_lattice_body(sb, "wood",
                           width_cells=4, height_cells=4, cell_size=0.10,
                           position=(-0.5 + i * 0.5, 1.0 + i * 0.3))
    avg_ms = _avg_step_ms(sb, step, frames=30)
    assert avg_ms < SOFTBODY_STEP_BUDGET_MS, (
        f"softbody step regression: {avg_ms:.2f} ms / step "
        f"(budget {SOFTBODY_STEP_BUDGET_MS} ms). Did someone bypass numpy "
        f"vectorisation or rebuild buffers per-frame?"
    )


def test_pbf_step_baseline_under_20ms_avg():
    """Small water pool. PBF step must stay well under one 60Hz frame."""
    fluid = FluidWorld()
    fluid.config["floor_y"] = 5.0
    fluid.add_block_of_particles("water", nx=14, ny=10, spacing=0.06,
                                  origin=(-0.42, 2.4))
    avg_ms = _avg_step_ms(fluid, pbf_step, frames=30)
    assert avg_ms < PBF_STEP_BUDGET_MS, (
        f"pbf_step regression: {avg_ms:.2f} ms / step "
        f"(budget {PBF_STEP_BUDGET_MS} ms). Likely culprit: density-iter "
        f"loop went non-vectorised, or neighbour grid rebuilt every iter."
    )


def test_softbody_zero_body_step_is_cheap():
    """An empty world should step in well under a millisecond — sanity that
    we're not paying per-frame allocator cost just to do nothing."""
    sb = SoftBodyWorld()
    avg_ms = _avg_step_ms(sb, step, frames=50, warmup=10)
    assert avg_ms < 2.0, (
        f"empty-world step is too expensive: {avg_ms:.3f} ms"
    )


def test_pbf_zero_particle_step_is_cheap():
    fluid = FluidWorld()
    avg_ms = _avg_step_ms(fluid, pbf_step, frames=50, warmup=10)
    assert avg_ms < 2.0, (
        f"empty-fluid step is too expensive: {avg_ms:.3f} ms"
    )
