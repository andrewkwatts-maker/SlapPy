"""Pin down the indirect-dispatch default + key correctness guarantees.

This module is the regression net for the indirect-vs-per-hull decision
captured in ``docs/indirect_dispatch_decision.md``.  After
``benchmarks/indirect_vs_per_hull.py`` showed indirect dispatch is
30-32% faster on dispatch-heavy scenes and within μs-noise everywhere
else, the default was flipped to ``True``.  These tests guard:

* Indirect path matches the per-hull path cell-state-wise (1e-3 tol).
* Zero active hulls is a no-op (no exception, no GPU work).
* When the GPU is available and reachable, the world picks the indirect
  path by default.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsWorld,
    PhysicsYaml,
    make_circle_silhouette,
)
from slappyengine.physics.world import (
    CellConfig,
    CollisionConfig,
    GpuConfig,
    HullConfig,
    WorldConfig,
    load_physics_config,
)


def _gpu_available() -> bool:
    try:
        import wgpu  # type: ignore
    except Exception:
        return False
    try:
        return wgpu.gpu.request_adapter_sync(
            power_preference="high-performance",
        ) is not None
    except Exception:
        return False


def _build_world(*, indirect: bool, substeps: int = 1) -> PhysicsWorld:
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=substeps,
                          gravity=(0.0, 0.0)),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(enabled=True, debug_force_cpu=False,
                      indirect_dispatch=indirect),
    )
    return PhysicsWorld(config=cfg)


# ---------------------------------------------------------------------------
# Correctness: indirect-dispatch cell-state matches per-hull within 1e-3.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_dispatch_correctness():
    """30 frames into a torn-cells scenario, the indirect path must
    produce cell state matching the per-hull path within 1e-3 elementwise.
    """
    w_indirect = _build_world(indirect=True, substeps=4)
    w_per_hull = _build_world(indirect=False, substeps=4)

    sil = make_circle_silhouette(24)
    b_i = w_indirect.create_body(sil, material="steel", position=(0.0, 0.0))
    b_p = w_per_hull.create_body(sil, material="steel", position=(0.0, 0.0))

    inject = dict(world_point=(0.0, 12.0), local_dv=(0.0, -40.0),
                  impact_speed_for_heat=20.0, rest=0.4)
    w_indirect._inject_local_velocity_field(hull_id=b_i.root_hull_id, **inject)
    w_per_hull._inject_local_velocity_field(hull_id=b_p.root_hull_id, **inject)
    w_indirect._mark_active(b_i.root_hull_id)
    w_per_hull._mark_active(b_p.root_hull_id)

    dt = 1.0 / 60.0
    for _ in range(30):
        w_indirect.step(dt)
        w_per_hull.step(dt)
        # Keep both hot for the full 30-frame compare.
        w_indirect._mark_active(b_i.root_hull_id)
        w_per_hull._mark_active(b_p.root_hull_id)

    gid_i = int(w_indirect.hulls.cell_grid_id[b_i.root_hull_id])
    gid_p = int(w_per_hull.hulls.cell_grid_id[b_p.root_hull_id])
    cells_i = w_indirect.cell_pool._cells[gid_i]
    cells_p = w_per_hull.cell_pool._cells[gid_p]

    diff = np.max(np.abs(cells_i - cells_p))
    assert diff < 1e-3, f"cell-state divergence too large: {diff!r}"


# ---------------------------------------------------------------------------
# Zero active hulls → no exception (the early-return guards both paths).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_indirect_dispatch_no_crash_at_zero_active():
    """A GPU substep with zero active T2 hulls must early-return cleanly,
    not raise on empty params / indirect-arg buffers.
    """
    w = _build_world(indirect=True, substeps=1)
    # Build a body but DO NOT mark it active.  ``_gather_active_slots``
    # returns [] → ``_gpu_substep`` early-returns before any dispatch.
    w.create_body(make_circle_silhouette(24), material="steel",
                  position=(0.0, 0.0))

    # Step a handful of frames; any exception fails the test.
    for _ in range(3):
        w.step(1.0 / 60.0)


# ---------------------------------------------------------------------------
# Default: with GPU enabled + reachable, the indirect path is selected.
# ---------------------------------------------------------------------------


def test_default_is_indirect_in_dataclass():
    """``GpuConfig`` dataclass default is now True (irrespective of yaml)."""
    cfg = GpuConfig()
    assert cfg.indirect_dispatch is True, (
        "Default flipped to True after profiling — see "
        "docs/indirect_dispatch_decision.md."
    )


def test_default_is_indirect_in_yaml():
    """``config/physics.yml`` matches the dataclass default."""
    yml = load_physics_config()  # walks up from world.py to repo root
    assert yml.gpu.indirect_dispatch is True, (
        "config/physics.yml gpu.indirect_dispatch must match the dataclass "
        "default of True (see docs/indirect_dispatch_decision.md)."
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_default_is_indirect_when_gpu_enabled():
    """When ``gpu.enabled=True`` and ``_should_use_gpu()`` returns True,
    a fresh ``PhysicsWorld()`` picks the indirect path by default.
    """
    w = PhysicsWorld()
    # Don't override anything — rely on the dataclass + yaml defaults.
    assert w.config.gpu.enabled is True
    assert w._should_use_gpu() is True
    assert w._gpu_available is True
    assert w.config.gpu.indirect_dispatch is True, (
        "PhysicsWorld() default must pick the indirect path when GPU is on."
    )
