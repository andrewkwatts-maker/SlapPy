"""Perf + parity tests for the vectorised ``_kinetic_relax`` rewrite.

The vectorised path is the reference implementation that the GPU port
will mirror. These tests pin:

1. **Parity** — for the same input, the vectorised path produces the
   same particle positions as the legacy nested-loop path, within
   float tolerance.
2. **Perf** — on 5000 particles the vectorised path is at least 3×
   faster than the legacy path.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from slappyengine.physics.particle_field import ParticleField, SAND_MAT


def _spawn_random(
    field: ParticleField, n: int, *, seed: int = 0, region: tuple[float, float] | None = None,
) -> None:
    """Spawn ``n`` sand particles at random positions in the field.

    If ``region`` is given as ``(width, height)``, particles are packed
    into that sub-region centred on the field — this matches the
    realistic worst case where particles are densely packed (e.g. a
    collapsed sand pile) and per-cell pair work dominates.
    """
    rng = np.random.default_rng(seed)
    W = field.mask.shape[1]
    H = field.mask.shape[0]
    if region is None:
        x_lo, x_hi = 2.0, W - 2.0
        y_lo, y_hi = 2.0, H - 2.0
    else:
        rw, rh = region
        cx, cy = W * 0.5, H * 0.5
        x_lo, x_hi = cx - rw * 0.5, cx + rw * 0.5
        y_lo, y_hi = cy - rh * 0.5, cy + rh * 0.5
    xs = rng.uniform(x_lo, x_hi, size=n).astype(np.float32)
    ys = rng.uniform(y_lo, y_hi, size=n).astype(np.float32)
    for x, y in zip(xs, ys):
        field.spawn(x=float(x), y=float(y), material="sand")
    # Reset kinetic_age so all particles are in the active phase
    # (otherwise everything goes baseline-only and the test gets boring).
    field.kinetic_age[:] = 0.0
    field.settled[:] = False
    field.bake_flag[:] = False


def _snapshot_positions(field: ParticleField) -> np.ndarray:
    return field.pos.copy()


def _restore_positions(field: ParticleField, pos: np.ndarray) -> None:
    field.pos[:] = pos


def test_kinetic_relax_vectorised_matches_loop() -> None:
    """Vectorised _kinetic_relax must produce the same positions as
    the legacy loop, within 1e-5 absolute tolerance, on 200 particles."""
    field = ParticleField(width=128, height=128)
    _spawn_random(field, 200, seed=42)

    # Snapshot initial positions so both calls operate on the same input.
    initial = _snapshot_positions(field)

    # Vectorised path.
    field._kinetic_relax(dt=1.0 / 60.0)
    vec_pos = _snapshot_positions(field)

    # Reset, then run legacy path.
    _restore_positions(field, initial)
    field._kinetic_relax_legacy(dt=1.0 / 60.0)
    legacy_pos = _snapshot_positions(field)

    # Sanity check: at least *some* particles were actually pushed
    # (otherwise we're asserting nothing meaningful).
    assert not np.allclose(vec_pos, initial), (
        "vectorised path did not push any particles — bad test setup"
    )

    # Parity within 1e-5. Atol is appropriate because typical pushes
    # are well below 1.0 unit; we want bit-stable relative to the
    # reference, modulo floating-point reduction order.
    np.testing.assert_allclose(
        vec_pos, legacy_pos,
        atol=1e-5, rtol=1e-5,
        err_msg=(
            "vectorised _kinetic_relax diverged from legacy reference; "
            "max diff = {:.3e}".format(float(np.max(np.abs(vec_pos - legacy_pos))))
        ),
    )


def test_kinetic_relax_perf_better() -> None:
    """Vectorised _kinetic_relax must be at least 3x faster than the
    legacy loop on 5000 particles. Single-shot timing — both paths
    run on identical input. The factor is intentionally loose (3x) to
    avoid CI flakes on cold caches; in practice the speedup is much
    larger."""
    field = ParticleField(width=512, height=512)
    # Pack 5000 particles into a 100x100 region so per-cell pair work
    # dominates (matches the realistic worst case: a collapsing sand
    # pile). A sparse spread degenerates to single-occupancy cells
    # where the vectorised path's sort overhead doesn't pay off and
    # both paths are effectively no-ops anyway.
    _spawn_random(field, 5000, seed=7, region=(100.0, 100.0))

    initial = _snapshot_positions(field)

    # Warm-up to avoid first-call JIT / cache effects (numpy itself
    # doesn't JIT, but argsort allocations and page faults skew the
    # very first call).
    _restore_positions(field, initial)
    field._kinetic_relax(dt=1.0 / 60.0)
    _restore_positions(field, initial)
    field._kinetic_relax_legacy(dt=1.0 / 60.0)

    # Time vectorised.
    _restore_positions(field, initial)
    t0 = time.perf_counter()
    field._kinetic_relax(dt=1.0 / 60.0)
    t_vec = time.perf_counter() - t0

    # Time legacy.
    _restore_positions(field, initial)
    t0 = time.perf_counter()
    field._kinetic_relax_legacy(dt=1.0 / 60.0)
    t_legacy = time.perf_counter() - t0

    speedup = t_legacy / max(t_vec, 1e-9)
    # Surface the numbers even on success so the perf trend is visible
    # in -v output.
    print(
        f"\n[kinetic_relax 5000 particles] "
        f"legacy={t_legacy*1000:.2f}ms  "
        f"vectorised={t_vec*1000:.2f}ms  "
        f"speedup={speedup:.2f}x"
    )
    assert speedup >= 3.0, (
        f"vectorised path only {speedup:.2f}x faster than legacy "
        f"(legacy {t_legacy*1000:.2f}ms vs vectorised {t_vec*1000:.2f}ms); "
        f"expected >= 3x"
    )
