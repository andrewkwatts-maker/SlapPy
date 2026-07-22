"""Tests for pharos_engine.physics.blast — explosion onto a ParticleField."""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics.blast import (
    detonate,
    ensure_preset_material,
    material_from_preset,
)
from pharos_engine.physics.particle_field import ParticleField
from pharos_engine.physics.splatter_presets import get as get_preset


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
    # Spawn count is now driven by curves.mass_conservation × removed
    # pixels (see test_blast_conservation.py for the contract). At
    # ratio=1.0 with this bowl, count ~= removed-pixel count.
    before = int((f.mask[..., 3] > 0).sum())
    n = detonate(f, p, x=64, y=60, crater_radius=20, crater_depth=10, rng=rng)
    after = int((f.mask[..., 3] > 0).sum())
    pixels_removed = before - after
    assert abs(n - pixels_removed) <= 1
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
    from pharos_engine.physics.blast import DetonateCurves
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
    from pharos_engine.physics.blast import DetonateCurves
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90))
    # 90° blast direction → velocity field rotates: "up" becomes "right".
    detonate(f, get_preset("sand"), x=64, y=60,
              crater_radius=20, crater_depth=10,
              rng=np.random.default_rng(0),
              curves=DetonateCurves(blast_direction_deg=90.0))
    # Mean vx should be positive (pointing right) instead of mean vy < 0.
    assert float(f.vel[:, 0].mean()) > 30.0


def test_detonate_uses_material_grid_for_ejecta() -> None:
    # Ground filled with material="sand"; the spawned particles should
    # inherit the sand material id (NOT just the preset's material id,
    # though in this case they happen to be the same — the point is
    # they come from the GRID, not the preset). Use a preset with a
    # different name so we can distinguish.
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(200, 160, 90), material="sand")
    sand_mid = f.material_id_of("sand")
    p = get_preset("mud")  # preset name != grid material
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=64, y=60, crater_radius=20, crater_depth=10, rng=rng)
    assert n > 0
    # Every spawned particle should have the sand material id from the
    # grid, not the mud preset's id.
    assert int((f.material_id == sand_mid).sum()) == n
    mud_mid = f.material_id_of("mud")
    assert int((f.material_id == mud_mid).sum()) == 0


def test_detonate_layered_terrain_yields_correct_materials() -> None:
    # Sub-layer = rock; top 5 rows = mud (painted manually as a layer).
    # A blast from above the surface should sample BOTH materials and
    # spawn ejecta of both kinds.
    f = ParticleField(width=128, height=96)
    f.fill_ground(top_y=60, color=(110, 100, 90), material="rock")
    mud_mid = f.material_id_of("mud")
    rock_mid = f.material_id_of("rock")
    # Paint the top 5 rows of the ground as mud (mask + material_grid).
    f.mask[60:65, :, :3] = (96, 66, 34)
    f.mask[60:65, :, 3] = 255
    f.material_grid[60:65, :] = mud_mid
    p = get_preset("sand")  # preset is neither rock nor mud
    rng = np.random.default_rng(0)
    # Crater depth 15 reaches well past the 5-row mud cap into the rock.
    n = detonate(f, p, x=64, y=60, crater_radius=20, crater_depth=15, rng=rng)
    assert n > 0
    has_mud = bool((f.material_id == mud_mid).any())
    has_rock = bool((f.material_id == rock_mid).any())
    assert has_mud, "expected at least one mud-material particle from the top layer"
    assert has_rock, "expected at least one rock-material particle from the sub-layer"
    # And NONE should be the sand preset id (every solid pixel had a
    # valid material_grid entry).
    sand_mid = f.material_id_of("sand")
    # Sand exists as a builtin, but we expect zero particles assigned
    # to it from the bowl (no sand pixels under the bowl).
    assert int((f.material_id == sand_mid).sum()) == 0


def test_detonate_falls_back_to_preset_when_material_grid_unset() -> None:
    # No fill_ground — material_grid stays at -1 everywhere. The blast
    # is mid-air, so sampled_rgb is empty AND fallback to preset id
    # should kick in via the `np.full(n, mid, ...)` pre-fill.
    f = ParticleField(width=64, height=64)
    p = get_preset("rock")
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=32, y=20, crater_radius=5, crater_depth=3, rng=rng)
    assert n > 0
    # The preset material is registered, and every spawned particle
    # should use that id.
    preset_mid = f.material_id_of(p.name)
    assert int((f.material_id == preset_mid).sum()) == n


def test_detonate_falls_back_to_preset_for_unset_pixels_in_bowl() -> None:
    # Paint terrain pixels directly into mask WITHOUT setting
    # material_grid (leaving it at -1). The bowl will sample colour
    # from the mask but no valid material — preset fallback engages
    # per-particle.
    f = ParticleField(width=64, height=64)
    # Direct mask write, no material_grid update.
    f.mask[40:64, :, :3] = (180, 130, 70)
    f.mask[40:64, :, 3] = 255
    # material_grid[40:64, :] stays at -1.
    p = get_preset("sand")
    preset_mid = ensure_preset_material(f, p)
    rng = np.random.default_rng(0)
    n = detonate(f, p, x=32, y=40, crater_radius=10, crater_depth=5, rng=rng)
    assert n > 0
    # Every particle should fall back to the preset's material id
    # because the sampled material entries were -1.
    assert int((f.material_id == preset_mid).sum()) == n


def test_detonate_up_velocity_scale_amplifies_vertical() -> None:
    from pharos_engine.physics.blast import DetonateCurves
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
