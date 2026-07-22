"""Tests for the fluid_bridge module — verifies the bridge routes
ParticleField fluid particles through the canonical PBF solver and
respects the mask_grid collision boundary.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics.fluid_bridge import (
    FluidBridgeConfig,
    bridge_step,
)


def test_bridge_step_with_no_particles_is_noop() -> None:
    """Empty arrays in → empty arrays out (no crash, correct shape)."""
    pos = np.empty((0, 2), dtype=np.float32)
    vel = np.empty((0, 2), dtype=np.float32)
    cfg = FluidBridgeConfig()
    new_pos, new_vel = bridge_step(pos, vel, mask_grid=None, cfg=cfg, dt=1.0 / 60.0)
    assert new_pos.shape == (0, 2)
    assert new_vel.shape == (0, 2)
    assert new_pos.dtype == np.float32
    assert new_vel.dtype == np.float32


def test_bridge_step_separates_overlapping_particles() -> None:
    """A small cluster of tightly-overlapped particles must spread out
    under PBF density relaxation.

    Note: PBF's constraint is one-sided — it only pushes apart when
    the SPH-summed density *exceeds* the rest density. A pair of two
    isolated particles is actually *under*-densified relative to the
    rest packing (you need ~12 neighbours in 2D for the SPH sum to
    reach rho0), so the canonical PBF would *not* push them apart.

    To trigger real overcompression we use a small cluster — multiple
    particles packed inside one rest cell — so the local SPH density
    genuinely exceeds the target. The solver then redistributes them.
    """
    # 7 particles packed into a tiny ~1px-radius cluster, far tighter
    # than the rest_distance of 3.0 px. This guarantees the SPH-summed
    # density exceeds rho0 → positive constraint → real push.
    pos = np.array([
        [50.0, 50.0],
        [50.3, 50.0],
        [49.7, 50.0],
        [50.0, 50.3],
        [50.0, 49.7],
        [50.2, 50.2],
        [49.8, 49.8],
    ], dtype=np.float32)
    vel = np.zeros_like(pos)
    cfg = FluidBridgeConfig(
        rest_distance=3.0,
        iterations=4,
        gravity=(0.0, 0.0),  # disable gravity so we isolate the relax step
    )

    # Mean pairwise distance before and after step. PBF should spread
    # the cluster out, increasing mean separation.
    def mean_pair_dist(p: np.ndarray) -> float:
        n = p.shape[0]
        ii, jj = np.triu_indices(n, k=1)
        return float(np.linalg.norm(p[ii] - p[jj], axis=1).mean())

    before = mean_pair_dist(pos)
    new_pos, _ = bridge_step(pos, vel, mask_grid=None, cfg=cfg, dt=1.0 / 60.0)
    after = mean_pair_dist(new_pos)

    assert after > before, (
        f"cluster did not expand: mean pairwise distance {after} <= {before}"
    )
    # Require a non-trivial expansion (well above float32 noise but
    # generous enough for the 4-iter default config).
    assert (after - before) > 0.01, (
        f"cluster expansion too small: {after - before}"
    )


def test_bridge_step_applies_gravity() -> None:
    """A single mid-air particle's vy must grow under gravity."""
    pos = np.array([[100.0, 100.0]], dtype=np.float32)
    vel = np.zeros_like(pos)
    cfg = FluidBridgeConfig(gravity=(0.0, 720.0))
    dt = 1.0 / 60.0

    # Step a few frames so even with substepping the accumulated
    # velocity is clearly non-zero.
    cur_pos = pos
    cur_vel = vel
    for _ in range(5):
        cur_pos, cur_vel = bridge_step(
            cur_pos, cur_vel, mask_grid=None, cfg=cfg, dt=dt
        )

    # vy should be growing toward g·t. After 5 frames @ 60fps with
    # g=720: vy ≈ 720 · (5/60) = 60. Allow generous slack (PBF
    # substepping can slightly damp this).
    assert cur_vel[0, 1] > 20.0, (
        f"vy did not grow under gravity: {cur_vel[0, 1]}"
    )
    # Position must have moved downward (y+).
    assert cur_pos[0, 1] > pos[0, 1], (
        f"particle did not fall: y={cur_pos[0, 1]} vs start {pos[0, 1]}"
    )


def test_bridge_step_against_solid_mask() -> None:
    """A particle above a horizontal solid strip + downward gravity →
    after several steps, it must not have tunnelled through the solid
    band into the empty region beyond."""
    # 60×40 RGBA mask. Rows 30-34 are solid (alpha=255).
    h, w = 40, 60
    mask = np.zeros((h, w, 4), dtype=np.uint8)
    mask[30:35, :, 3] = 255  # solid horizontal strip at y=30..34

    # Particle starts at y=20 (above strip), heading down under gravity.
    pos = np.array([[30.0, 20.0]], dtype=np.float32)
    vel = np.array([[0.0, 50.0]], dtype=np.float32)
    cfg = FluidBridgeConfig(gravity=(0.0, 720.0))
    dt = 1.0 / 60.0

    cur_pos = pos
    cur_vel = vel
    for _ in range(20):
        cur_pos, cur_vel = bridge_step(
            cur_pos, cur_vel, mask_grid=mask, cfg=cfg, dt=dt
        )

    final_y = float(cur_pos[0, 1])
    # The particle must not have penetrated through to the open
    # region past y=35 (where the solid strip ends). Allow it to sit
    # right at or just above the solid surface.
    assert final_y < 35.0, (
        f"particle tunnelled through solid strip: final y={final_y}"
    )
    # Also confirm the eject worked — it shouldn't be sitting INSIDE
    # the solid band (rows 30-34).
    iy = int(np.clip(np.floor(cur_pos[0, 1]), 0, h - 1))
    ix = int(np.clip(np.floor(cur_pos[0, 0]), 0, w - 1))
    assert mask[iy, ix, 3] == 0, (
        f"particle ended up inside solid: pixel ({ix},{iy}) "
        f"alpha={mask[iy, ix, 3]}"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
