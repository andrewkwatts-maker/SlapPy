"""CPU/GPU parity scaffolding for the upcoming ParticleField GPU port.

Each GPU kernel we land in Sprints 2-3 must produce results within
float-tolerance of the existing CPU implementation. This file holds
the shared assertion / setup helpers plus one demo test per kernel.

Until a kernel ships, both halves of the pair run the CPU path — the
test still exercises the harness (CPU vs CPU == identical), and we
flip the GPU instance to ``use_gpu=True`` once the kernel exists.
The skipped placeholders mark each kernel slot so removing the skip
decorator is the only step needed to enable a parity check.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.particle_field import (
    ParticleField,
    SAND_MAT,
)


# ── Helpers ────────────────────────────────────────────────────────────


def assert_soa_close(cpu_field, gpu_field, rtol=1e-4, atol=1e-5):
    """Compare two ParticleField SoAs element-wise."""
    for fname in (
        'pos', 'vel', 'material_id', 'radius', 'bake_radius',
        'color', 'phase', 'phase_age', 'kinetic_age',
        'rigidify_at', 'impact_vel', 'temperature',
    ):
        cpu_val = getattr(cpu_field, fname)
        gpu_val = getattr(gpu_field, fname)
        np.testing.assert_allclose(
            cpu_val, gpu_val, rtol=rtol, atol=atol,
            err_msg=f"SoA field {fname!r} divergence",
        )


def make_paired_fields(n_particles=200, seed=42):
    """Construct two identical ParticleField instances seeded with the
    same particles. Returns ``(cpu, gpu)``.

    For now BOTH instances run the CPU path — the GPU one will be
    flipped to ``use_gpu=True`` once GPU kernels exist. The test still
    passes (CPU vs CPU) which confirms the harness works.
    """
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    # Pin the internal RNG so spawn() picks identical fragment shapes,
    # rotations and rigidify_at draws for both fields.
    cpu._rng = np.random.default_rng(seed)
    gpu._rng = np.random.default_rng(seed)

    # Drive the particle layout from a third RNG so the spawn loop is
    # not coupled to the per-field RNG that spawn() advances internally.
    layout_rng = np.random.default_rng(seed + 1)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[16.0, 16.0],
        high=[240.0, 96.0],   # spawn in upper portion so they fall
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = layout_rng.uniform(
        low=[-40.0, -20.0],
        high=[40.0, 20.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    return cpu, gpu


def step_both(cpu, gpu, dt=1 / 60, n=10):
    """Step both fields the same number of times."""
    for _ in range(n):
        cpu.step(dt)
        gpu.step(dt)


# ── Active tests ───────────────────────────────────────────────────────


def test_integrate_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    # Spawn happened in mid-air with varying velocities so gravity +
    # drag have a noticeable effect after a few frames. Step a small
    # number of times to keep particles airborne (and therefore inside
    # the _integrate path) without all of them landing.
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


# ── Sprint 2 placeholders ─────────────────────────────────────────────


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 2")
def test_collide_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 2")
def test_drill_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


# ── Sprint 3 placeholders ─────────────────────────────────────────────


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_slump_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_kinetic_relax_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_fluid_relax_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_thermal_step_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_bake_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)
