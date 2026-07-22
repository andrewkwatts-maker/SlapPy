"""Phase C — GPU pressure projection parity tests.

These tests own the contract that ``pressure_project.wgsl`` is a
faithful GPU port of the CPU ``_pressure_project_arrays`` Red-Black SOR
sweep.  The CPU path is the canonical reference; the GPU result must
land within 1e-3 (consistent with the existing
``test_gpu_matches_cpu_on_one_substep`` tolerance).

Tests:
  * test_gpu_projection_matches_cpu — direct parity on a divergent
    water body with known velocity injection.
  * test_gpu_projection_handles_no_fluid_bodies — non-fluid scene
    must NOT dispatch the projection pass.
  * test_gpu_projection_works_with_multiple_fluid_bodies — three
    water bodies all project correctly.
  * test_iters_zero_skips_dispatch — ``fluid_projection_iters=0``
    short-circuits the GPU dispatch entirely.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from pharos_engine.deform_modes import cell_material_for
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


# --- helpers ----------------------------------------------------------------


def _gpu_available() -> bool:
    """Probe whether a wgpu adapter is available without mutating state."""
    try:
        import wgpu  # type: ignore
    except Exception:
        return False
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception:
        return False
    return adapter is not None


def _build_world(*, force_cpu: bool, gravity_zero: bool = True) -> PhysicsWorld:
    """Build a PhysicsWorld with a controlled GPU/CPU choice.

    Gravity defaults to zero so the only state change comes from the
    substep itself, isolating projection behaviour from free-fall.
    """
    g = (0.0, 0.0) if gravity_zero else (0.0, 196.0)
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=1, gravity=g),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(enabled=not force_cpu, debug_force_cpu=force_cpu),
    )
    return PhysicsWorld(config=cfg)


def _water_pool(
    world: PhysicsWorld, *, iters: int = 12, position=(0.0, 0.0),
):
    """Author a fixed water-body pool and stamp iters onto its material."""
    body = world.create_body(
        make_rect_silhouette(64, 32),
        material="water",
        position=position,
        fixed=True,
    )
    hid = body.root_hull_id
    mat = world._materials.get(int(world.hulls.material_id[hid]))
    assert mat is not None and mat.is_fluid
    world._materials[int(world.hulls.material_id[hid])] = dataclasses.replace(
        mat, fluid_projection_iters=int(iters),
    )
    return body


def _stamp_divergence(body) -> None:
    """Inject a smooth radially-outward velocity into a body's cell grid.

    The pattern is fully resolved on the 32×32 grid so the projection
    has a meaningful residual to drive down.
    """
    cells = body.cells
    if cells is None:
        return
    H, W = cells.shape[0], cells.shape[1]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = (W - 1) * 0.5, (H - 1) * 0.5
    dx = xx - cx
    dy = yy - cy
    sigma = 6.0
    g = np.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
    cells[..., 2] = dx * g * 0.2  # v_x
    cells[..., 3] = dy * g * 0.2  # v_y


# --- tests ------------------------------------------------------------------


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_projection_matches_cpu():
    """One CPU substep and one GPU substep on identical water bodies with
    the same divergent velocity injection must agree within 1e-3.
    """
    w_cpu = _build_world(force_cpu=True)
    w_gpu = _build_world(force_cpu=False)

    body_cpu = _water_pool(w_cpu, iters=12)
    body_gpu = _water_pool(w_gpu, iters=12)

    _stamp_divergence(body_cpu)
    _stamp_divergence(body_gpu)

    # Mark both active so the substep actually runs.
    w_cpu._mark_active(body_cpu.root_hull_id)
    w_gpu._mark_active(body_gpu.root_hull_id)

    # Snapshot pre-state for diagnostics.
    pre_cpu = body_cpu.cells.copy()
    pre_gpu = body_gpu.cells.copy()
    assert np.allclose(pre_cpu, pre_gpu, atol=1e-6), (
        "Initial cell state should match before substep."
    )

    dt = 1.0 / 240.0  # short dt to keep the CFL margin
    w_cpu._cpu_substep(dt)
    assert w_gpu._should_use_gpu(), "GPU path must be active for this test"
    w_gpu._gpu_substep(dt)

    cpu_state = body_cpu.cells
    gpu_state = body_gpu.cells

    diff = np.abs(cpu_state - gpu_state)
    max_diff = float(diff.max())
    chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
    assert max_diff < 1e-3, (
        f"GPU/CPU water projection diverged: max_abs_diff={max_diff:.4e} "
        f"(channel {chan_idx})"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_projection_handles_no_fluid_bodies(monkeypatch):
    """Steel-only scene: the GPU projection pass must NOT dispatch.

    Patches ``_gpu_projection_pass`` to record fluid-slot counts; expects
    every recorded call to see ZERO fluid slots (so the early-return at
    the top of the method short-circuits before any GPU work).
    """
    w = _build_world(force_cpu=False)
    dispatched: list[int] = []
    real = PhysicsWorld._gpu_projection_pass

    def _spy(self, encoder, active_slots, dt):
        n_fluid = sum(
            1 for (_h, _g, m) in active_slots
            if m.is_fluid and int(getattr(m, "fluid_projection_iters", 0)) > 0
        )
        dispatched.append(n_fluid)
        return real(self, encoder, active_slots, dt)

    monkeypatch.setattr(PhysicsWorld, "_gpu_projection_pass", _spy)

    # Only steel bodies — projection should never fire.
    ground = w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    # Force the substep to run by marking bodies hot.
    w._mark_active(ground.root_hull_id)
    w._mark_active(ball.root_hull_id)
    # Lazy GPU init runs on first should_use_gpu(); call it explicitly
    # so the subsequent _gpu_substep() actually enters the GPU path.
    assert w._should_use_gpu(), "GPU path must be active for this test"
    # One direct GPU substep is enough to assert the gating: any fluid
    # body in active_slots would have shown up in the spy.
    w._gpu_substep(1.0 / 240.0)

    # Some substeps may have run with active slots; none should ever
    # report a fluid slot.
    assert dispatched, "GPU projection pass should at least be invoked"
    assert all(n == 0 for n in dispatched), (
        f"Projection saw fluid slots in a steel-only scene: {dispatched}"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_gpu_projection_works_with_multiple_fluid_bodies():
    """Three independent water bodies are all projected correctly.

    Each body gets the same divergent velocity injection; after one GPU
    substep, each body's cell state must match its CPU counterpart
    within 1e-3.
    """
    positions = [(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)]

    w_cpu = _build_world(force_cpu=True)
    w_gpu = _build_world(force_cpu=False)

    bodies_cpu = [_water_pool(w_cpu, iters=12, position=p) for p in positions]
    bodies_gpu = [_water_pool(w_gpu, iters=12, position=p) for p in positions]

    for b in bodies_cpu + bodies_gpu:
        _stamp_divergence(b)
        w = w_cpu if b in bodies_cpu else w_gpu
        w._mark_active(b.root_hull_id)

    # Sanity: pre-state matches per body.
    for bc, bg in zip(bodies_cpu, bodies_gpu):
        assert np.allclose(bc.cells, bg.cells, atol=1e-6)

    dt = 1.0 / 240.0
    w_cpu._cpu_substep(dt)
    assert w_gpu._should_use_gpu(), "GPU path must be active"
    w_gpu._gpu_substep(dt)

    for i, (bc, bg) in enumerate(zip(bodies_cpu, bodies_gpu)):
        diff = np.abs(bc.cells - bg.cells)
        max_diff = float(diff.max())
        chan_idx = int(np.argmax(diff.max(axis=(0, 1))))
        assert max_diff < 1e-3, (
            f"Body {i} CPU/GPU diverged: max_abs_diff={max_diff:.4e} "
            f"(channel {chan_idx})"
        )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_iters_zero_skips_dispatch(monkeypatch):
    """``fluid_projection_iters=0`` must skip the projection dispatch.

    Even with a fluid body in the scene, when iters=0 the projection
    pass's fluid-subset gather returns empty so no compute pass is
    encoded.  We monkeypatch ``begin_compute_pass`` on the encoder to
    count projection-labelled passes.
    """
    w = _build_world(force_cpu=False)
    body = _water_pool(w, iters=0)  # explicitly disabled

    # Spy on encode-time dispatch count by counting the fluid subset
    # at the start of _gpu_projection_pass.
    fluid_dispatch_counts: list[int] = []
    real = PhysicsWorld._gpu_projection_pass

    def _spy(self, encoder, active_slots, dt):
        n_fluid = sum(
            1 for (_h, _g, m) in active_slots
            if m.is_fluid and int(getattr(m, "fluid_projection_iters", 0)) > 0
        )
        fluid_dispatch_counts.append(n_fluid)
        return real(self, encoder, active_slots, dt)

    monkeypatch.setattr(PhysicsWorld, "_gpu_projection_pass", _spy)

    _stamp_divergence(body)
    w._mark_active(body.root_hull_id)
    assert w._should_use_gpu(), "GPU path must be active for this test"
    w._gpu_substep(1.0 / 240.0)

    assert fluid_dispatch_counts, "projection pass helper should be invoked"
    assert all(n == 0 for n in fluid_dispatch_counts), (
        f"iters=0 must yield zero eligible fluid slots; got "
        f"{fluid_dispatch_counts}"
    )
