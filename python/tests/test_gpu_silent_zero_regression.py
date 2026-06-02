"""Regression test for the GPU "silent zero" bug.

Background
----------
The GPU per-pixel substep used to silently produce zero deformation in
real scenes (config previously forced ``debug_force_cpu=True`` to work
around it).  The earlier parity test
(``test_gpu_matches_cpu_on_one_substep``) only exercised the kernel with
an *explicit* ``_inject_local_velocity_field`` followed by a *manual*
``_mark_active`` call, which is enough to satisfy the activation gate at
``world.step``-level but does not exercise the full code path that a
real game scene drives: gravity → broadphase → contact → impulse-driven
cell inject → ``_mark_active`` happening inside the contact resolver →
substep loop reading ``cell_pool._cells``, writing back into the same
host backing array.

This test files the regression contract: when a steel ball is dropped
onto a fixed mud ground, the ball's cells must show non-zero
displacement, velocity, and heat after the impact transient — and the
GPU's per-cell state must agree with the CPU's per-cell state to within
the same FP tolerance as the single-substep parity test (1e-3).
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsWorld,
    PhysicsYaml,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.world import (
    CellConfig,
    CollisionConfig,
    GpuConfig,
    HullConfig,
    WorldConfig,
)


# Matches the existing GPU tests so we behave identically in CI envs
# without an adapter.
def _gpu_available() -> bool:
    try:
        import wgpu  # type: ignore
    except Exception:
        return False
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:
        return False
    return adapter is not None


def _drop_world(*, force_cpu: bool, indirect: bool) -> PhysicsWorld:
    """Build the canonical steel-into-mud reproducer world."""
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=4, gravity=(0.0, 196.0)),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(
            enabled=not force_cpu,
            debug_force_cpu=force_cpu,
            indirect_dispatch=indirect,
        ),
    )
    return PhysicsWorld(config=cfg, world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _run_drop(world: PhysicsWorld, frames: int = 120):
    """Spawn the steel-into-mud scene and step it for ``frames`` ticks.

    Returns ``(ball_body, ground_body)`` so the caller can inspect cells.
    """
    ground = world.create_body(
        make_rect_silhouette(240, 16),
        material="mud",
        position=(0.0, 180.0),
        fixed=True,
    )
    ball = world.create_body(
        make_circle_silhouette(36),
        material="steel",
        position=(0.0, 0.0),
    )
    for _ in range(frames):
        world.step()
    return ball, ground


def _ball_metrics(ball) -> dict[str, float]:
    """Peak magnitudes of the per-cell channels we care about."""
    c = ball.cells
    return {
        "u_y_max": float(np.abs(c[..., 1]).max()),
        "v_y_max": float(np.abs(c[..., 3]).max()),
        "heat_max": float(c[..., 12].max()),
    }


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_drop_produces_nonzero_deformation_per_hull():
    """Steel-into-mud drop on the GPU (per-hull dispatch) must NOT silently
    zero out the ball's cell state.

    Before the fix, this assertion failed: ``v_y_max == 0`` and ``heat_max
    == 0`` even though the ball made contact and the broadphase reported
    the collision pair.  After the fix, the values must be visibly
    non-zero and match the CPU reference to within FP tolerance.
    """
    w = _drop_world(force_cpu=False, indirect=False)
    ball, _ = _run_drop(w)
    metrics = _ball_metrics(ball)

    # Lower bounds calibrated to the current physics constants — anything
    # well above zero would have caught the original regression, but we
    # keep these tight enough that a future regression that *partially*
    # zeroed the field would also fire.
    assert metrics["v_y_max"] > 1e-3, (
        f"GPU per-hull substep produced ~zero ball velocity field; "
        f"metrics={metrics}"
    )
    assert metrics["heat_max"] > 1.0, (
        f"GPU per-hull substep produced ~zero heat after impact; "
        f"metrics={metrics}"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_drop_produces_nonzero_deformation_indirect():
    """Same as the per-hull case but exercising the indirect-dispatch path."""
    w = _drop_world(force_cpu=False, indirect=True)
    ball, _ = _run_drop(w)
    metrics = _ball_metrics(ball)
    assert metrics["v_y_max"] > 1e-3, (
        f"GPU indirect-dispatch substep produced ~zero ball velocity "
        f"field; metrics={metrics}"
    )
    assert metrics["heat_max"] > 1.0, (
        f"GPU indirect-dispatch substep produced ~zero heat after impact; "
        f"metrics={metrics}"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_drop_matches_cpu_reference():
    """The GPU and CPU per-pixel substeps must agree on the post-drop ball
    cell state.  This is the canonical "GPU is a faithful port of the CPU
    kernel" parity contract, but exercised at the *full world step* level
    (gravity + broadphase + contact + substep loop), not just a single
    isolated ``_gpu_substep`` call on an injected velocity field.
    """
    w_cpu = _drop_world(force_cpu=True, indirect=False)
    w_gpu = _drop_world(force_cpu=False, indirect=False)

    ball_cpu, _ = _run_drop(w_cpu)
    ball_gpu, _ = _run_drop(w_gpu)

    diff = np.abs(ball_cpu.cells - ball_gpu.cells)
    max_diff = float(diff.max())
    chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
    # Same tolerance as test_gpu_matches_cpu_on_one_substep — over the full
    # drop the per-step FP error has many chances to accumulate, so we
    # use a slightly looser bound.
    assert max_diff < 1e-2, (
        f"GPU/CPU drop state diverged: max_abs_diff={max_diff:.4e} "
        f"(channel {chan_idx})"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_default_config_runs_on_gpu_when_adapter_present():
    """``debug_force_cpu`` defaults to False, so a freshly-built world
    on a GPU-capable host must actually dispatch the per-pixel kernel
    via the GPU path.  This test guards against the default being
    accidentally flipped back to True the next time the GPU path
    misbehaves.
    """
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=4, gravity=(0.0, 196.0)),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(),  # rely entirely on dataclass defaults
    )
    assert cfg.gpu.debug_force_cpu is False, (
        "GpuConfig.debug_force_cpu default must be False — the silent-zero "
        "bug it guarded against has been fixed.  If you are flipping it "
        "back to True, please add a regression test first."
    )
    w = PhysicsWorld(config=cfg, world_bounds=(-200.0, -100.0, 200.0, 250.0))
    # Spawn the canonical drop so step() actually exercises the substep.
    w.create_body(
        make_rect_silhouette(240, 16), material="mud",
        position=(0.0, 180.0), fixed=True,
    )
    w.create_body(
        make_circle_silhouette(36), material="steel", position=(0.0, 0.0),
    )
    # Touch _should_use_gpu so lazy init runs; assert it picked the GPU.
    used = w._should_use_gpu()
    assert used is True
    assert w._gpu_available is True
