"""Tests for slappyengine.physics.blast — explosion onto a ParticleField."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.blast import (
    detonate,
    ensure_preset_material,
    material_from_preset,
)
from slappyengine.physics.particle_field import ParticleField
from slappyengine.physics.splatter_presets import get as get_preset


def test_material_from_preset_inherits_cohesion_and_drag() -> None:
    p = get_preset("sand")
    m = material_from_preset(p)
    assert m.name == "sand"
    assert m.cohesion == p.cohesion
    assert m.air_drag_per_sec == p.air_drag_per_sec
    assert m.binding_force == p.impact_binding_ke


def test_ensure_preset_material_is_idempotent() -> None:
    f = ParticleField(width=64, height=64)
    p = get_preset("mud")
    mid_a = ensure_preset_material(f, p)
    mid_b = ensure_preset_material(f, p)
    assert mid_a == mid_b
    # Material now resolvable by name.
    assert f.material("mud").name == "mud"


def test_detonate_carves_bowl_and_spawns_particles() -> None:
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90), sub_color=(60, 44, 28))
    p = get_preset("sand")
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=64, y=60, crater_radius=20, crater_depth=10, rng=rng)
    assert n == p.n_grains + p.n_chunks
    # Bowl carved (alpha cleared in centre).
    assert f.mask[63, 64, 3] == 0
    # Outside the bowl still solid.
    assert f.mask[63, 0, 3] == 255
    # Particles exist with non-zero velocity.
    assert f.pos.shape[0] == n
    assert np.any(f.vel[:, 1] < 0)  # at least some go upward


def test_detonate_samples_colours_from_original_pixels() -> None:
    # Bowl pixels are painted bright red BEFORE detonation; chunks
    # should inherit that red.
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=40, color=(255, 0, 0))  # all red
    p = get_preset("sand")
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=32, y=40, crater_radius=10, crater_depth=5, rng=rng)
    # At least one spawned particle should have red dominant.
    # Allow for small darkening from post_blast_darken.
    red_dominant = (f.color[:, 0] > f.color[:, 1]) & (f.color[:, 0] > f.color[:, 2])
    assert red_dominant.sum() > n // 2


def test_detonate_falls_back_to_palette_for_mid_air_blast() -> None:
    # No solid pixels in the bowl → fall back to preset palette.
    f = ParticleField(width=64, height=64)  # no fill_ground
    p = get_preset("rock")
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=32, y=20, crater_radius=5, crater_depth=3, rng=rng)
    # Should still spawn particles using palette colour.
    assert f.pos.shape[0] == n
    # Colours non-zero (palette had non-black entries).
    assert f.color.sum() > 0


def test_detonate_velocities_reflect_up_and_radial_boosts() -> None:
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90))
    p = get_preset("rock")  # has the largest up_boost (180)
    rng = np.random.default_rng(0)
    detonate(f, p, x=64, y=60, crater_radius=20, crater_depth=8, rng=rng)
    # Mean vy should be strongly negative (upward).
    assert float(f.vel[:, 1].mean()) < -50.0
    # Mean |vx| should be substantial — rocks fly outward.
    assert float(np.abs(f.vel[:, 0]).mean()) > 30.0


def test_detonate_crater_noise_breaks_smooth_bowl() -> None:
    from slappyengine.physics.blast import DetonateCurves
    # Without noise: bowl depth is monotonically deepest at centre.
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90))
    detonate(f, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=15,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(crater_noise=0.0))
    smooth = f.mask[..., 3].copy()
    # With noise: depth perturbed per column.
    f2 = ParticleField(width=128, height=96)
    f2.fill_ground(top_y=60, color=(200, 160, 90))
    detonate(f2, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=15,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(crater_noise=0.5))
    noisy = f2.mask[..., 3].copy()
    # The two carves should differ.
    assert not np.array_equal(smooth, noisy)


def test_detonate_blast_direction_rotates_velocity_field() -> None:
    from slappyengine.physics.blast import DetonateCurves
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90))
    # 90° blast direction → velocity field rotates: "up" becomes "right".
    detonate(f, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=10,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(blast_direction_deg=90.0))
    # Mean vx should be positive (pointing right) instead of mean vy < 0.
    assert float(f.vel[:, 0].mean()) > 30.0


def test_detonate_up_velocity_scale_amplifies_vertical() -> None:
    from slappyengine.physics.blast import DetonateCurves
    f1 = ParticleField(width=128, height=96)
    f1.fill_ground(top_y=60, color=(200, 160, 90))
    detonate(f1, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=10,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(up_velocity_scale=1.0))
    base_vy = float(f1.vel[:, 1].mean())
    f2 = ParticleField(width=128, height=96)
    f2.fill_ground(top_y=60, color=(200, 160, 90))
    detonate(f2, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=10,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(up_velocity_scale=2.0))
    boosted_vy = float(f2.vel[:, 1].mean())
    # Doubled up_scale should make vy ~2x more negative.
    assert boosted_vy < base_vy * 1.5
