"""Tests for SimField — headless CPU-only paths (no wgpu context required)."""
import numpy as np
import pytest


def test_atmosphere_cpu_no_gpu():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(64, 64))
    assert f._cpu_density is not None
    assert f._cpu_density.shape == (64, 64)


def test_seed_noise_cpu():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(64, 64))
    before = f._cpu_density.copy()
    f.seed_noise(mode="fbm", octaves=2, seed=42)
    assert not np.allclose(f._cpu_density, before)  # changed


def test_add_remove_force():
    from slappyengine.sim_field import SimField
    f = SimField(gpu=None)
    h1 = f.add_force_uniform(1.0, 0.0)
    h2 = f.add_force_radial((100, 100), strength=2.0)
    assert len(f._forces) == 2
    f.remove_force(h1)
    assert len(f._forces) == 1
    assert f._forces[0]["id"] == h2


def test_add_remove_displacer():
    from slappyengine.sim_field import SimField

    class FakeEntity:
        position = (50, 50)

    f = SimField(gpu=None)
    eid = f.add_displacer(FakeEntity(), radius=30)
    assert len(f._displacers) == 1
    f.remove_displacer(eid)
    assert len(f._displacers) == 0


def test_inject_density():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(64, 64))
    f.inject((32, 32), radius=5, channel="density", value=1.0)
    assert f._cpu_density[32, 32] > 0.5


def test_sample_cpu():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(64, 64))
    result = f.sample((10, 10))
    assert "density" in result
    assert "velocity_x" in result


def test_update_wind_moves_density():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(64, 64))
    f.seed_noise(seed=0)
    f.add_force_uniform(100.0, 0.0)  # strong rightward wind
    before = f._cpu_density.copy()
    f.update(dt=1.0)  # large dt to see movement
    # Density should have shifted
    assert not np.allclose(f._cpu_density, before)


def test_particle_factory_cpu():
    from slappyengine.sim_field import SimField, ParticleTemplate
    f = SimField.particles(gpu=None, max_particles=100)
    # No crash when spawning without GPU
    f.spawn((50, 50), count=10, template=ParticleTemplate(z=5.0))


def test_set_phase_transition():
    from slappyengine.sim_field import SimField
    f = SimField.particles(gpu=None)
    f.set_phase_transition(z_threshold=0.0, ground_damping=0.05)
    assert f._phase_z == 0.0
    assert f._ground_damping == 0.05


def test_as_density_layer_cpu():
    from slappyengine.sim_field import SimField
    f = SimField.atmosphere(gpu=None, size=(32, 32))
    f.inject((16, 16), radius=4, channel="density", value=0.8)
    layer = f.as_density_layer()
    assert layer is not None
    # Alpha channel should reflect density
    assert layer._image_data[16, 16, 3] > 100
