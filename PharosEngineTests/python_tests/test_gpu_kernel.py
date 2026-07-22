"""GPU per-pixel kernel tests.

Sprint 2: verify the WGSL kernel runs and matches the CPU numpy port.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    PhysicsYaml,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.world import (
    CellConfig,
    CollisionConfig,
    GpuConfig,
    HullConfig,
    WorldConfig,
)


def _build_world(*, force_cpu: bool, gravity_zero: bool = False) -> PhysicsWorld:
    """Build a PhysicsWorld with a controlled GPU/CPU choice."""
    g = (0.0, 0.0) if gravity_zero else (0.0, 196.0)
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=1, gravity=g),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(enabled=not force_cpu, debug_force_cpu=force_cpu),
    )
    return PhysicsWorld(config=cfg)


def _gpu_available() -> bool:
    """Probe whether a wgpu adapter is available, without mutating state."""
    try:
        import wgpu  # type: ignore
    except Exception:
        return False
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:
        return False
    return adapter is not None


def test_gpu_falls_back_when_unavailable(monkeypatch):
    """If no wgpu adapter exists, _gpu_available must remain False and the
    world must keep running through the CPU path.
    """
    import wgpu  # type: ignore

    monkeypatch.setattr(
        wgpu.gpu, "request_adapter_sync", lambda *a, **kw: None,
        raising=True,
    )

    w = _build_world(force_cpu=False)
    # Spawn a body so step() actually invokes the substep loop.
    w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    # Touch _should_use_gpu so init runs.
    used = w._should_use_gpu()
    assert used is False, "Adapter is None — GPU path must be disabled."
    assert w._gpu_available is False
    # And the world must still step successfully via the CPU path.
    w.step()
    w.step()


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_substep_runs_without_error():
    """Smoke test: spawn a body, run a few GPU-driven frames, no exceptions."""
    w = _build_world(force_cpu=False)
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    for _ in range(5):
        w.step()
    # Confirm we actually used the GPU.
    assert w._gpu_available is True


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_matches_cpu_on_one_substep():
    """The GPU kernel must produce the same per-cell state as the CPU
    numpy port to within FP tolerance after a single substep applied to
    an identically-injected ball.
    """
    # Two worlds with the same initial state, zero gravity so the only
    # state change comes from the substep itself.
    w_cpu = _build_world(force_cpu=True, gravity_zero=True)
    w_gpu = _build_world(force_cpu=False, gravity_zero=True)

    # Identical body in each world.
    body_cpu = w_cpu.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )
    body_gpu = w_gpu.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )

    # Apply the same impact-style velocity injection to both.
    impact_args = dict(
        world_point=(0.0, 12.0),
        local_dv=(0.0, -40.0),
        impact_speed_for_heat=20.0,
        rest=0.4,
    )
    w_cpu._inject_local_velocity_field(
        hull_id=body_cpu.root_hull_id, **impact_args,
    )
    w_gpu._inject_local_velocity_field(
        hull_id=body_gpu.root_hull_id, **impact_args,
    )

    # Mark both as active so the substep actually runs.
    w_cpu._mark_active(body_cpu.root_hull_id)
    w_gpu._mark_active(body_gpu.root_hull_id)

    # Snapshot pre-state for verification.
    pre_cpu = body_cpu.cells.copy()
    pre_gpu = body_gpu.cells.copy()
    assert np.allclose(pre_cpu, pre_gpu, atol=1e-6), (
        "Initial cell state should match before substep."
    )

    dt = 1.0 / 240.0  # short dt to keep CFL margin
    # Run one substep on each.
    w_cpu._cpu_substep(dt)
    assert w_gpu._should_use_gpu(), "GPU path must be active for this test"
    w_gpu._gpu_substep(dt)

    cpu_state = body_cpu.cells
    gpu_state = body_gpu.cells

    # Compare channel by channel with a sane tolerance.
    diff = np.abs(cpu_state - gpu_state)
    max_diff = float(diff.max())
    # Find which channel maxes out for diagnostics.
    chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
    assert max_diff < 1e-3, (
        f"GPU/CPU cell state diverged: max_abs_diff={max_diff:.4e} "
        f"(channel {chan_idx})"
    )
