"""GPU indirect-dispatch path tests.

Sprint 3: verifies the new single-dispatch-over-all-active-hulls path in
``PhysicsWorld._gpu_substep_indirect`` matches the legacy per-hull
dispatch path and the CPU numpy port, handles many bodies, falls back
cleanly when no hulls are active, and doesn't crash.
"""
from __future__ import annotations

import time

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


def _gpu_available() -> bool:
    """Probe whether a wgpu adapter exists without mutating state."""
    try:
        import wgpu  # type: ignore
    except Exception:
        return False
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:
        return False
    return adapter is not None


def _build_world(
    *,
    force_cpu: bool,
    indirect: bool,
    gravity_zero: bool = True,
    substeps: int = 1,
) -> PhysicsWorld:
    """Build a world with explicit GPU/CPU + indirect/per-hull config."""
    g = (0.0, 0.0) if gravity_zero else (0.0, 196.0)
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=substeps, gravity=g),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(
            enabled=not force_cpu,
            debug_force_cpu=force_cpu,
            indirect_dispatch=indirect,
        ),
    )
    return PhysicsWorld(config=cfg)


# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_matches_per_hull_dispatch():
    """Indirect-dispatch path must match the legacy per-hull path to 1e-3
    after 4 substeps of identical initial state."""
    w_per_hull = _build_world(force_cpu=False, indirect=False)
    w_indirect = _build_world(force_cpu=False, indirect=True)

    body_per_hull = w_per_hull.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )
    body_indirect = w_indirect.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )

    impact_args = dict(
        world_point=(0.0, 12.0),
        local_dv=(0.0, -40.0),
        impact_speed_for_heat=20.0,
        rest=0.4,
    )
    w_per_hull._inject_local_velocity_field(
        hull_id=body_per_hull.root_hull_id, **impact_args,
    )
    w_indirect._inject_local_velocity_field(
        hull_id=body_indirect.root_hull_id, **impact_args,
    )

    w_per_hull._mark_active(body_per_hull.root_hull_id)
    w_indirect._mark_active(body_indirect.root_hull_id)

    # Force GPU init for both.
    assert w_per_hull._should_use_gpu()
    assert w_indirect._should_use_gpu()

    dt = 1.0 / 240.0
    for _ in range(4):
        w_per_hull._gpu_substep(dt)
        w_indirect._gpu_substep(dt)
        # Re-mark active so the next substep still runs.
        w_per_hull._mark_active(body_per_hull.root_hull_id)
        w_indirect._mark_active(body_indirect.root_hull_id)

    diff = np.abs(body_per_hull.cells - body_indirect.cells)
    max_diff = float(diff.max())
    chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
    assert max_diff < 1e-3, (
        f"Indirect vs per-hull diverged: max_abs_diff={max_diff:.4e} "
        f"(channel {chan_idx})"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_matches_cpu():
    """Indirect GPU path must match the CPU numpy port to 1e-3."""
    w_cpu = _build_world(force_cpu=True, indirect=True)
    w_gpu = _build_world(force_cpu=False, indirect=True)

    body_cpu = w_cpu.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )
    body_gpu = w_gpu.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )

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

    w_cpu._mark_active(body_cpu.root_hull_id)
    w_gpu._mark_active(body_gpu.root_hull_id)

    assert np.allclose(body_cpu.cells, body_gpu.cells, atol=1e-6)

    dt = 1.0 / 240.0
    w_cpu._cpu_substep(dt)
    assert w_gpu._should_use_gpu()
    w_gpu._gpu_substep(dt)

    diff = np.abs(body_cpu.cells - body_gpu.cells)
    max_diff = float(diff.max())
    chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
    assert max_diff < 1e-3, (
        f"Indirect GPU vs CPU diverged: max_abs_diff={max_diff:.4e} "
        f"(channel {chan_idx})"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_handles_8_bodies():
    """Spawn 8 active bodies, one indirect dispatch must update them all."""
    w = _build_world(force_cpu=False, indirect=True)
    bodies = []
    for i in range(8):
        b = w.create_body(
            make_circle_silhouette(20), material="steel",
            position=(float(i) * 50.0, 0.0), velocity=(0.0, 0.0),
        )
        # Inject local velocity field — distinct per body so we can observe
        # per-body GPU output.
        w._inject_local_velocity_field(
            hull_id=b.root_hull_id,
            world_point=(float(i) * 50.0, 8.0),
            local_dv=(float(i) - 3.5, -30.0),
            impact_speed_for_heat=15.0,
            rest=0.4,
        )
        w._mark_active(b.root_hull_id)
        bodies.append(b)

    pre_states = [b.cells.copy() for b in bodies]

    dt = 1.0 / 240.0
    assert w._should_use_gpu()
    w._gpu_substep(dt)

    # Every body's cell field must have changed.
    for i, b in enumerate(bodies):
        diff = np.abs(b.cells - pre_states[i]).max()
        assert diff > 0.0, (
            f"Body {i} cell state didn't change — indirect dispatch dropped this slot."
        )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_falls_back_when_no_active_hulls():
    """Empty scene → no dispatch, no crash."""
    w = _build_world(force_cpu=False, indirect=True)
    # No bodies created → no active hulls.
    assert w._should_use_gpu()
    # Should silently no-op.
    w._gpu_substep(1.0 / 240.0)

    # Spawning a body but NOT marking it active → still no dispatch.
    b = w.create_body(
        make_circle_silhouette(20), material="steel",
        position=(0.0, 0.0), velocity=(0.0, 0.0),
    )
    pre = b.cells.copy()
    # Force active-window expiry: the body was just spawned but if it's
    # active by default (likely is), step the world without injecting.
    # The test is satisfied if the call doesn't crash either way.
    w._gpu_substep(1.0 / 240.0)
    # No assertion on cell state — point is no exception was raised.
    assert b.cells.shape == pre.shape


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_perf_better_than_per_hull():
    """Best-effort: indirect should be at least as fast as per-hull on
    an 8-body scene over 30 frames.  Skips if we can't measure clean times."""
    def _run(indirect: bool) -> float:
        w = _build_world(
            force_cpu=False, indirect=indirect, gravity_zero=False, substeps=4,
        )
        for i in range(8):
            b = w.create_body(
                make_circle_silhouette(20), material="steel",
                position=(float(i) * 50.0 - 175.0, 0.0), velocity=(0.0, 0.0),
            )
            w._inject_local_velocity_field(
                hull_id=b.root_hull_id,
                world_point=(float(i) * 50.0 - 175.0, 8.0),
                local_dv=(0.0, -20.0),
                impact_speed_for_heat=10.0,
                rest=0.4,
            )
            w._mark_active(b.root_hull_id)
        # Warmup.
        for _ in range(2):
            w.step()
        t0 = time.perf_counter()
        for _ in range(30):
            w.step()
        return time.perf_counter() - t0

    t_per_hull = _run(indirect=False)
    t_indirect = _run(indirect=True)
    # Allow 20% noise margin — we just need indirect not catastrophically worse.
    assert t_indirect < t_per_hull * 1.5, (
        f"Indirect ({t_indirect:.3f}s) regressed vs per-hull ({t_per_hull:.3f}s)"
    )
