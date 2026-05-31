"""Tests for slappyengine.physics.particle_field — unified material sim."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.particle_field import (
    BUILTIN_MATERIALS,
    MUD_MAT,
    Material,
    ParticleField,
    ROCK_MAT,
    SAND_MAT,
    SNOW_MAT,
    WATER,
)


def test_builtins_cover_expected_substances() -> None:
    names = {m.name for m in BUILTIN_MATERIALS}
    assert names == {"water", "sand", "mud", "rock", "snow", "ice"}


def test_engine_user_can_register_custom_material() -> None:
    # The whole point of Material being a public dataclass is that
    # users can define their own substances. Verify the flow.
    f = ParticleField(width=64, height=64)
    glass = Material(
        name="glass",
        binding_force=4.0e5,
        cohesion=0.9,
        slump_angle_deg=80.0,
        color=(180, 220, 220),
        radius_min=1,
        radius_max=1,
    )
    mid = f.register_material(glass)
    assert mid >= 0
    # Idempotent — re-registering returns the same id.
    assert f.register_material(glass) == mid
    # Resolvable by name.
    assert f.material("glass").binding_force == 4.0e5
    # Spawnable.
    f.spawn(x=10.0, y=10.0, material="glass")
    assert f.material_id[0] == mid


def test_water_is_fluid_others_are_not() -> None:
    assert WATER.is_fluid
    for m in (SAND_MAT, MUD_MAT, ROCK_MAT, SNOW_MAT):
        assert not m.is_fluid


def test_density_ordering_matches_real_substances() -> None:
    # snow < water < sand < mud < rock by density.
    by_name = {m.name: m for m in BUILTIN_MATERIALS}
    assert by_name["snow"].density < by_name["water"].density
    assert by_name["water"].density < by_name["sand"].density
    assert by_name["sand"].density < by_name["mud"].density
    assert by_name["mud"].density < by_name["rock"].density


def test_field_constructs_with_empty_particle_arrays() -> None:
    f = ParticleField(width=128, height=96)
    assert f.pos.shape == (0, 2)
    assert f.vel.shape == (0, 2)
    assert f.mask.shape == (96, 128, 4)
    assert f.region_grid.shape_cells == (2, 2)  # 96/64=2, 128/64=2


def test_field_rejects_bad_dims() -> None:
    with pytest.raises(ValueError):
        ParticleField(width=0, height=10)
    with pytest.raises(ValueError):
        ParticleField(width=10, height=-1)


def test_spawn_appends_one_particle() -> None:
    f = ParticleField(width=64, height=64)
    idx = f.spawn(x=10.0, y=20.0, vx=5.0, vy=-15.0, material="sand", radius=2)
    assert idx == 0
    assert f.pos[0, 0] == 10.0
    assert f.pos[0, 1] == 20.0
    assert f.vel[0, 1] == -15.0
    assert f.radius[0] == 2.0
    assert f.material_id[0] == f.material_id_of("sand")
    # Color inherited from material.
    assert tuple(int(c) for c in f.color[0]) == SAND_MAT.color


def test_spawn_batch_is_equivalent_to_per_particle() -> None:
    f = ParticleField(width=64, height=64)
    pos = np.array([[10, 20], [30, 40]], dtype=np.float32)
    vel = np.array([[1, 2], [3, 4]], dtype=np.float32)
    mids = np.array([f.material_id_of("water"), f.material_id_of("rock")],
                    dtype=np.int32)
    radii = np.array([1.5, 2.0], dtype=np.float32)
    f.spawn_batch(pos=pos, vel=vel, material_ids=mids, radii=radii)
    assert f.pos.shape == (2, 2)
    assert f.material_id[0] == f.material_id_of("water")
    assert f.material_id[1] == f.material_id_of("rock")


def test_fill_ground_writes_solid_band_to_mask() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=40, color=(200, 160, 90), sub_color=(60, 44, 28))
    # Top row coloured + alpha.
    assert f.mask[40, 10, 3] == 255
    assert tuple(int(c) for c in f.mask[40, 10, :3]) == (200, 160, 90)
    # Sub-ground band.
    assert tuple(int(c) for c in f.mask[55, 10, :3]) == (60, 44, 28)
    # Above ground is empty.
    assert f.mask[20, 10, 3] == 0


def test_carve_clears_alpha_in_region() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=40, color=(200, 160, 90))
    bowl = np.zeros((64, 64), dtype=bool)
    bowl[40:50, 20:40] = True
    f.carve(bowl)
    assert f.mask[45, 30, 3] == 0  # carved
    assert f.mask[45, 5, 3] == 255  # outside bowl, still solid


def test_carve_rejects_wrong_shape() -> None:
    f = ParticleField(width=64, height=64)
    with pytest.raises(ValueError):
        f.carve(np.zeros((32, 32), dtype=bool))


def test_step_drops_sand_until_it_hits_ground_and_settles() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=50, color=(200, 160, 90))
    f.spawn(x=32.0, y=10.0, vx=0.0, vy=20.0, material="sand")
    dt = 1.0 / 60.0
    # Step until landed (cap at 400 frames).
    for _ in range(400):
        f.step(dt)
        if f.landed[0] and f.settled[0]:
            break
    assert f.landed[0]
    assert f.settled[0]
    # Particle ends up at or above the ground row.
    assert f.pos[0, 1] <= 50


def test_step_water_does_not_settle_keeps_bouncing() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=50, color=(40, 80, 160))
    f.spawn(x=32.0, y=10.0, vx=0.0, vy=20.0, material="water")
    dt = 1.0 / 60.0
    # Water hits ground then bounces; never marks "landed" as final.
    for _ in range(20):
        f.step(dt)
    # Water is fluid → keeps integrating; never sets the final landed
    # flag (we reset it in _collide when material.is_fluid).
    assert not f.settled[0]


def test_step_skips_when_no_particles() -> None:
    f = ParticleField(width=64, height=64)
    f.step(1.0 / 60.0)  # must not raise


def test_render_discs_paints_live_particle() -> None:
    f = ParticleField(width=64, height=64)
    f.spawn(x=32.0, y=20.0, material="sand", radius=2)
    img = f.render(mode="discs")
    assert img.shape == (64, 64, 3)
    # The particle disc should be coloured around (32, 20).
    assert tuple(int(c) for c in img[20, 32]) == SAND_MAT.color


def test_render_marching_squares_renders_density_band() -> None:
    f = ParticleField(width=64, height=64)
    # Cluster five particles in one grid cell so density > iso.
    for _ in range(5):
        f.spawn(x=32.0, y=32.0, material="water")
    img = f.render(mode="marching_squares")
    assert img.shape == (64, 64, 3)
    # The 4x4 cell that contains (32, 32) should be filled with water
    # blue (last-write-wins is water's colour since all are water).
    assert tuple(int(c) for c in img[32, 32]) == WATER.color


def test_render_unknown_mode_raises() -> None:
    f = ParticleField(width=16, height=16)
    with pytest.raises(ValueError, match="unknown render mode"):
        f.render(mode="nope")


def test_material_defaults_to_discs_render_mode() -> None:
    # A bare Material with no overrides should default to disc rendering.
    m = Material(name="dirt")
    assert m.render_mode == "discs"


def test_water_defaults_to_marching_squares_render_mode() -> None:
    # WATER ships with render_mode='marching_squares' so it pools smoothly.
    assert WATER.render_mode == "marching_squares"
    # And the other built-ins stick with discs.
    for m in (SAND_MAT, MUD_MAT, ROCK_MAT, SNOW_MAT):
        assert m.render_mode == "discs"


def test_material_rejects_invalid_render_mode() -> None:
    with pytest.raises(ValueError, match="render_mode"):
        Material(name="bad", render_mode="potato")


def test_render_water_particle_uses_marching_squares_by_default() -> None:
    # No explicit override → per-material mode. Water cluster should
    # paint the iso-surface in the cell that contains the particles.
    f = ParticleField(width=64, height=64)
    for _ in range(5):
        f.spawn(x=32.0, y=32.0, material="water")
    img = f.render()  # no mode/override → per-material
    assert img.shape == (64, 64, 3)
    assert tuple(int(c) for c in img[32, 32]) == WATER.color


def test_render_mixed_materials_gets_both_pixel_and_iso() -> None:
    # One sand pixel (disc) and a cluster of water (iso) in the same
    # frame should each paint with their own renderer.
    f = ParticleField(width=64, height=64)
    f.spawn(x=10.0, y=10.0, material="sand", radius=1)
    for _ in range(5):
        f.spawn(x=40.0, y=40.0, material="water")
    img = f.render()
    # Sand pixel painted as a disc rectangle.
    assert tuple(int(c) for c in img[10, 10]) == SAND_MAT.color
    # Water cluster painted as iso-surface in its grid cell.
    assert tuple(int(c) for c in img[40, 40]) == WATER.color


def test_render_override_forces_all_particles_to_discs() -> None:
    # With override='discs', water should render as a disc even though
    # its material asks for marching_squares.
    f = ParticleField(width=64, height=64)
    f.spawn(x=32.0, y=32.0, material="water", radius=1)
    img = f.render(override_render_mode="discs")
    assert tuple(int(c) for c in img[32, 32]) == WATER.color
    # Single water particle far from any other → marching squares
    # density (1.0 in one cell, smoothed) wouldn't reach iso=0.5
    # alone after the blur. The disc override forces a hit.
    # (Verifies the override path executes the disc branch.)


def test_custom_material_can_be_added() -> None:
    custom = Material(name="oil", binding_force=0.0, density=0.9,
                      color=(40, 30, 10))
    f = ParticleField(width=32, height=32, materials=[WATER, custom])
    f.spawn(x=10.0, y=10.0, material="oil")
    assert f.material("oil").name == "oil"
    assert tuple(int(c) for c in f.color[0]) == (40, 30, 10)


def test_region_grid_tracks_live_particle_locations() -> None:
    f = ParticleField(width=128, height=128, cell_size=32)
    f.spawn(x=10.0, y=10.0, material="sand")
    f.spawn(x=100.0, y=100.0, material="sand")
    # The step call updates region_grid via record_live.
    f.step(1.0 / 60.0)
    # Both particles are in distinct cells → both active.
    assert f.region_grid.active_cell_count() >= 1


def test_fill_ground_marks_pixels_fixed_not_loose() -> None:
    f = ParticleField(width=32, height=32)
    f.fill_ground(top_y=20, color=(100, 100, 100))
    assert f._fixed_mask[25, 10] == True
    assert f.loose[25, 10] == False


def test_carve_clears_fixed_and_loose_for_carved_region() -> None:
    f = ParticleField(width=32, height=32)
    f.fill_ground(top_y=20, color=(100, 100, 100))
    bowl = np.zeros((32, 32), dtype=bool)
    bowl[20:25, 10:20] = True
    f.carve(bowl)
    assert f._fixed_mask[22, 15] == False
    assert f.mask[22, 15, 3] == 0


def test_slump_does_not_touch_fixed_terrain() -> None:
    # Fixed ground row should stay put even when the field steps.
    f = ParticleField(width=32, height=32)
    f.fill_ground(top_y=20, color=(100, 100, 100))
    before = f.mask[20:32, :, 3].copy()
    for _ in range(20):
        f.step(1.0 / 60.0)
    after = f.mask[20:32, :, 3]
    assert np.array_equal(before, after)


def test_settled_particles_become_loose_and_can_slump() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=50, color=(120, 100, 80))
    # Drop a single rock particle (cohesion 0.05 — falls easily).
    f.spawn(x=32.0, y=10.0, vx=0.0, vy=10.0, material="rock", radius=1)
    for _ in range(400):
        f.step(1.0 / 60.0)
        if f.settled[0] and f.bake_flag[0]:
            break
    # The settled particle's pixels should be marked LOOSE.
    assert f.loose[:, :].sum() >= 1


def test_fluid_relax_pushes_overlapping_water_particles_apart() -> None:
    # Naive _fluid_relax only — PBF requires >= ~7 particles for the
    # density constraint to fire (well-documented canonical behaviour).
    f = ParticleField(width=64, height=64, use_pbf_bridge=False)
    # Two water particles separated by < rest_length so they push apart.
    f.spawn(x=32.0, y=32.0, material="water")
    f.spawn(x=32.5, y=32.0, material="water")
    pre_dx = abs(f.pos[0, 0] - f.pos[1, 0])
    f.step(1.0 / 60.0)
    post_dx = abs(f.pos[0, 0] - f.pos[1, 0])
    assert post_dx > pre_dx


def test_fluid_relax_skipped_for_solid_materials() -> None:
    # Two sand particles overlapping → should NOT relax (they're not fluid).
    f = ParticleField(width=64, height=64)
    f.spawn(x=10.0, y=10.0, material="sand")
    f.spawn(x=10.0, y=10.0, material="sand")
    p0_before = f.pos[0].copy()
    p1_before = f.pos[1].copy()
    # One step with no terrain — they fall but don't push apart from relax.
    # Position deltas should match (both fall same amount).
    f.step(1.0 / 60.0)
    # Both fell the same y, no lateral push.
    assert abs(f.pos[0, 0] - p0_before[0]) < 0.01
    assert abs(f.pos[1, 0] - p1_before[0]) < 0.01


def test_bullet_drills_through_thin_wall() -> None:
    f = ParticleField(width=64, height=64)
    bullet_mat = Material(
        name="bullet",
        binding_force=1.0e3,
        drill_max_px=10,
        drill_velocity_loss=0.95,
        drill_eject_gain=0.0,
        gravity_scale=0.0,
        air_drag_per_sec=1.0,
    )
    f.materials.append(bullet_mat)
    f._name_to_id["bullet"] = len(f.materials) - 1
    # Solid 3-px wall at x=32.
    f.mask[:, 30:33, 3] = 255
    f.mask[:, 30:33, :3] = (200, 200, 200)
    # Bullet flying right at high speed, started close enough to hit
    # the wall in a few small steps.
    f.spawn(x=25.0, y=30.0, vx=1500.0, vy=0.0, material="bullet", radius=1)
    for _ in range(10):
        f.step(1.0 / 120.0)
    # The wall should now have holes (alpha=0 in at least one pixel).
    assert (f.mask[30, 30:33, 3] == 0).any()


def test_bullet_drill_with_eject_spawns_particles() -> None:
    f = ParticleField(width=64, height=64)
    bullet_mat = Material(
        name="bullet",
        binding_force=1.0e3,
        drill_max_px=5,
        drill_velocity_loss=0.9,
        drill_eject_gain=2.0,        # 5 drilled → ~10 ejecta
        mass_conservation=1.0,
        gravity_scale=0.0,
        air_drag_per_sec=1.0,
    )
    f.materials.append(bullet_mat)
    f._name_to_id["bullet"] = len(f.materials) - 1
    # Solid wall column.
    f.mask[20:40, 30:35, 3] = 255
    f.mask[20:40, 30:35, :3] = (180, 50, 30)
    n_before = f.pos.shape[0]
    f.spawn(x=25.0, y=30.0, vx=2000.0, vy=0.0, material="bullet", radius=1)
    for _ in range(10):
        f.step(1.0 / 120.0)
    # Drilled at least one pixel → ejecta spawned.
    n_after = f.pos.shape[0]
    # before + 1 bullet + N ejecta
    assert n_after > n_before + 1


def test_low_velocity_particle_does_not_drill() -> None:
    f = ParticleField(width=64, height=64)
    f.fill_ground(top_y=50, color=(100, 100, 100))
    # Sand has drill_max_px=0 by default → never drills.
    f.spawn(x=32.0, y=10.0, vx=0.0, vy=400.0, material="sand")
    for _ in range(60):
        f.step(1.0 / 60.0)
    # The ground row should still be fully solid (no holes).
    assert (f.mask[50, :, 3] == 255).all()


def test_drill_clears_loose_flag_on_drilled_pixels() -> None:
    f = ParticleField(width=64, height=64)
    bullet_mat = Material(
        name="bullet", binding_force=1.0e3,
        drill_max_px=5, drill_velocity_loss=0.95,
        gravity_scale=0.0, air_drag_per_sec=1.0,
    )
    f.materials.append(bullet_mat)
    f._name_to_id["bullet"] = len(f.materials) - 1
    # Loose wall — settled-particle territory.
    f.mask[30, 20:25, 3] = 255
    f.mask[30, 20:25, :3] = (50, 50, 50)
    f.loose[30, 20:25] = True
    f.spawn(x=18.0, y=30.0, vx=1500.0, vy=0.0, material="bullet", radius=1)
    for _ in range(10):
        f.step(1.0 / 120.0)
    # After drilling, the cleared pixels' loose flag is False.
    cleared = f.mask[30, 20:25, 3] == 0
    if cleared.any():
        for k, c in enumerate(cleared):
            if c:
                assert f.loose[30, 20 + k] == False
