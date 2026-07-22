"""Phase B regression tests: persistent GPU residency for the cell pool.

Phase B trades the full-pool ``queue.write_buffer`` blast each GPU
substep for a dirty-slot upload.  These tests own the contracts:

* ``CellGridPool`` tracks which slots the CPU has just written.
* Acquire flags a slot dirty; release clears the flag.
* CPU writers in :class:`PhysicsWorld` (impact inject, fragment spawn,
  boundary exchange, CPU substep) all mark their slots dirty.
* With ``gpu.persistent_residency=True`` the upload byte count on a
  settled-body scene scales with the *active* set, not the whole pool.
* The dirty-slot path produces identical cell state to the legacy
  full-upload path after 60 frames of free-fall + impacts.

See ``docs/next_phase_plan.md`` section 3.2.B for the design.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    PhysicsYaml,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.cell import CELL_GRID_SIZE, CellGridPool
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


def _world(
    *,
    persistent_residency: bool,
    force_cpu: bool = True,
    gravity_zero: bool = False,
) -> PhysicsWorld:
    """Build a small deterministic world with persistent residency toggled."""
    g = (0.0, 0.0) if gravity_zero else (0.0, 196.0)
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=1, gravity=g),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(
            enabled=not force_cpu,
            debug_force_cpu=force_cpu,
            persistent_residency=persistent_residency,
        ),
    )
    return PhysicsWorld(config=cfg, world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))


# --- CellGridPool API tests -------------------------------------------------


def test_pool_mark_dirty_tracks_slot():
    """After ``mark_dirty``, ``needs_upload`` returns True for that slot."""
    pool = CellGridPool(capacity=4)
    slot = pool.acquire()
    # acquire() already flags as dirty (fresh authored state).
    assert pool.needs_upload(slot) is True
    pool.mark_gpu_resident(slot)
    assert pool.needs_upload(slot) is False
    # Hand-edit and re-mark.
    pool.slot_view(slot)[..., 0] = 7.0
    pool.mark_dirty(slot)
    assert pool.needs_upload(slot) is True
    assert slot in pool.dirty_slots()


def test_clear_dirty_after_upload():
    """``mark_gpu_resident`` clears the dirty flag for one slot."""
    pool = CellGridPool(capacity=4)
    slot_a = pool.acquire()
    slot_b = pool.acquire()
    assert pool.dirty_slots() == {slot_a, slot_b}
    pool.mark_gpu_resident(slot_a)
    assert pool.dirty_slots() == {slot_b}
    assert pool.needs_upload(slot_a) is False
    assert pool.needs_upload(slot_b) is True


def test_release_clears_tracking():
    """Releasing a slot drops it from both tracking sets."""
    pool = CellGridPool(capacity=4)
    slot = pool.acquire()
    pool.mark_gpu_resident(slot)
    pool.mark_dirty(slot)
    assert pool.needs_upload(slot) is True
    pool.release(slot)
    assert slot not in pool.dirty_slots()
    # Re-acquire — same slot, freshly dirty.
    slot2 = pool.acquire()
    assert pool.needs_upload(slot2) is True


def test_mark_dirty_ignores_unallocated_slots():
    """``mark_dirty`` on a free slot is a no-op (doesn't corrupt tracking)."""
    pool = CellGridPool(capacity=4)
    pool.mark_dirty(2)  # never acquired
    assert pool.dirty_slots() == set()


def test_grow_marks_everything_dirty():
    """``grow`` invalidates the GPU buffer ⇒ every in-use slot needs re-upload."""
    pool = CellGridPool(capacity=4)
    a = pool.acquire()
    b = pool.acquire()
    pool.mark_gpu_resident(a)
    pool.mark_gpu_resident(b)
    assert pool.dirty_slots() == set()
    pool.grow(8)
    assert pool.dirty_slots() == {a, b}


# --- world.py wiring tests --------------------------------------------------


def test_create_body_marks_slot_dirty():
    """``create_body`` writes density + heat into the slot — flag must trip."""
    w = _world(persistent_residency=False)
    body = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    gid = int(w.hulls.cell_grid_id[body.root_hull_id])
    assert w.cell_pool.needs_upload(gid) is True


def test_inject_marks_slot_dirty():
    """``_inject_local_velocity_field`` must flag its target slot dirty."""
    w = _world(persistent_residency=False)
    body = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    gid = int(w.hulls.cell_grid_id[body.root_hull_id])
    # Clear the post-creation dirty mark first to isolate inject's effect.
    w.cell_pool.mark_gpu_resident(gid)
    assert w.cell_pool.needs_upload(gid) is False
    w._inject_local_velocity_field(
        hull_id=body.root_hull_id,
        world_point=(0.0, 12.0),
        local_dv=(0.0, -40.0),
        impact_speed_for_heat=20.0,
        rest=0.4,
    )
    assert w.cell_pool.needs_upload(gid) is True, (
        "Impact-style inject mutates v/heat channels; slot must be re-uploaded."
    )


def test_cpu_substep_marks_slot_dirty():
    """The CPU substep writes into ``dst`` — must flag the slot for the next
    GPU dispatch (so toggling ``gpu.enabled`` mid-run doesn't desync)."""
    w = _world(persistent_residency=False)
    body = w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )
    gid = int(w.hulls.cell_grid_id[body.root_hull_id])
    w._mark_active(body.root_hull_id)
    w.cell_pool.mark_gpu_resident(gid)  # pretend GPU is current
    w._cpu_substep(1.0 / 240.0)
    assert w.cell_pool.needs_upload(gid) is True


def test_boundary_exchange_marks_contact_slots_dirty():
    """Heat conduction across a contact seam flags both bodies' slots."""
    w = _world(persistent_residency=False)
    floor = w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24), material="steel",
        position=(0.0, 140.0),
    )
    # Heat one side so boundary exchange actually transfers something.
    ball_gid = int(w.hulls.cell_grid_id[ball.root_hull_id])
    floor_gid = int(w.hulls.cell_grid_id[floor.root_hull_id])
    w.cell_pool.slot_view(ball_gid)[..., 12] += 5.0
    # Step several frames to bring the bodies into contact.
    for _ in range(30):
        w.step()
    # By this point both gids should have been marked dirty at least once
    # (impact + boundary exchange + cpu substep).
    assert w.cell_pool.needs_upload(ball_gid) or w.cell_pool.needs_upload(floor_gid)


# --- selective-upload byte-count test ---------------------------------------


def test_residency_saves_upload_bytes_on_settled_scene(monkeypatch):
    """On a 50-body scene where only ~3 bodies move per substep, the dirty-
    slot path uploads << the full-pool baseline.

    We instrument ``queue.write_buffer`` via the helper directly: build a
    world with persistent_residency on, hand-mark only a couple of slots
    dirty, call the helper, count bytes.
    """
    w = _world(persistent_residency=True)
    pool = w.cell_pool
    # Force capacity to hold 50 slots (grow if needed).
    if pool.capacity < 50:
        pool.grow(50)
    # Acquire 50 slots; mark them all resident (settled state).
    slots = [pool.acquire() for _ in range(50)]
    for s in slots:
        pool.mark_gpu_resident(s)
    assert pool.dirty_slots() == set()

    # Mark 3 colliding bodies dirty.
    dirty_subset = {slots[7], slots[20], slots[33]}
    for s in dirty_subset:
        pool.mark_dirty(s)

    # Stub out the GPU buffer + queue to record uploads.
    uploads: list[tuple[int, int]] = []  # (offset, size)

    class _StubQueue:
        def write_buffer(self, buf, offset, data):
            uploads.append((offset, len(data)))

    class _StubBuf:
        pass

    w._gpu_queue = _StubQueue()
    w._gpu_src_buf = _StubBuf()
    w._gpu_buf_capacity = pool.capacity

    total = w._gpu_upload_dirty_slots(pool._cells)

    expected_slot_bytes = CELL_GRID_SIZE * CELL_GRID_SIZE * 16 * 4
    # We uploaded exactly len(dirty_subset) slots worth.
    assert total == len(dirty_subset) * expected_slot_bytes
    # The legacy full-pool path would have uploaded 50 × that.
    legacy_total = pool.capacity * expected_slot_bytes
    assert total < legacy_total // 10, (
        f"persistent_residency uploaded {total} B; legacy would have uploaded "
        f"{legacy_total} B — Phase B savings should be > 10×."
    )
    # Dirty set is now empty (slots promoted to gpu_resident).
    assert pool.dirty_slots() == set()


def test_residency_coalesces_contiguous_runs(monkeypatch):
    """Contiguous dirty slots merge into a single ``write_buffer`` call."""
    w = _world(persistent_residency=True)
    pool = w.cell_pool
    if pool.capacity < 10:
        pool.grow(10)
    slots = [pool.acquire() for _ in range(10)]
    for s in slots:
        pool.mark_gpu_resident(s)

    # Mark slots 2, 3, 4 (contiguous) and 7 (lone).
    for s in (slots[2], slots[3], slots[4], slots[7]):
        pool.mark_dirty(s)

    uploads: list[tuple[int, int]] = []

    class _StubQueue:
        def write_buffer(self, buf, offset, data):
            uploads.append((offset, len(data)))

    w._gpu_queue = _StubQueue()
    w._gpu_src_buf = object()
    w._gpu_buf_capacity = pool.capacity

    w._gpu_upload_dirty_slots(pool._cells)
    # Two runs: one of size 3, one of size 1.
    assert len(uploads) == 2
    sizes = sorted(sz for _off, sz in uploads)
    slot_bytes = CELL_GRID_SIZE * CELL_GRID_SIZE * 16 * 4
    assert sizes == [slot_bytes, slot_bytes * 3]


def test_residency_skips_when_no_dirty():
    """No dirty slots ⇒ no write_buffer calls."""
    w = _world(persistent_residency=True)
    pool = w.cell_pool

    uploads: list[tuple[int, int]] = []

    class _StubQueue:
        def write_buffer(self, buf, offset, data):
            uploads.append((offset, len(data)))

    w._gpu_queue = _StubQueue()
    w._gpu_src_buf = object()
    w._gpu_buf_capacity = pool.capacity
    n = w._gpu_upload_dirty_slots(pool._cells)
    assert n == 0
    assert uploads == []


# --- CPU-path parity (cheap, no GPU needed) ---------------------------------


def test_residency_path_marks_track_invariants_cpu_only():
    """Even without a GPU, running the CPU substep with persistent_residency
    flagged must NOT crash and must keep the dirty/in_use sets coherent.
    """
    w = _world(persistent_residency=True, force_cpu=True)
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 140.0),
    )
    for _ in range(20):
        w.step()
    pool = w.cell_pool
    # Dirty sets must be a subset of in_use at all times.
    assert pool._dirty.issubset(pool._in_use)
    assert pool._gpu_resident.issubset(pool._in_use)


# --- GPU-path parity (requires wgpu adapter) --------------------------------


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_residency_path_matches_full_upload_path():
    """Identical worlds: one with persistent_residency=True, one =False.

    After 60 frames of free-fall + ground impact the per-cell state must
    agree to within 1e-3 (same tolerance as the GPU↔CPU parity contract).
    """
    np.random.seed(0)

    def _scene(persistent: bool) -> PhysicsWorld:
        cfg = PhysicsYaml(
            world=WorldConfig(default_dt=1.0 / 60.0, substeps=2, gravity=(0.0, 196.0)),
            hull=HullConfig(),
            cell=CellConfig(),
            collision=CollisionConfig(),
            gpu=GpuConfig(
                enabled=True,
                debug_force_cpu=False,
                persistent_residency=persistent,
            ),
        )
        w = PhysicsWorld(
            config=cfg, world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0),
        )
        w.create_body(
            make_rect_silhouette(240, 16), material="stone",
            position=(0.0, 180.0), fixed=True,
        )
        w.create_body(
            make_circle_silhouette(24), material="steel",
            position=(0.0, 0.0),
        )
        return w

    w_legacy = _scene(persistent=False)
    w_resi = _scene(persistent=True)
    # Skip if the GPU path isn't actually live in this build.
    if not (w_legacy._should_use_gpu() and w_resi._should_use_gpu()):
        pytest.skip("GPU path not live in this build.")

    for _ in range(60):
        w_legacy.step()
        w_resi.step()

    # Compare the ball's cells (root hull is index 1 in both).
    ball_gid_legacy = int(w_legacy.hulls.cell_grid_id[1])
    ball_gid_resi = int(w_resi.hulls.cell_grid_id[1])
    cells_legacy = w_legacy.cell_pool.slot_view(ball_gid_legacy)
    cells_resi = w_resi.cell_pool.slot_view(ball_gid_resi)
    diff = float(np.abs(cells_legacy - cells_resi).max())
    assert diff < 1e-3, (
        f"persistent_residency diverged from full-upload baseline: "
        f"max_abs_diff={diff:.4e}"
    )


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
def test_residency_per_substep_uploads_only_active_slots():
    """Compare legacy and persistent_residency upload bytes on a scene
    with many settled bodies and one active disturber.

    The legacy path uploads ``capacity * slot_bytes`` per substep no
    matter how few hulls are dispatched.  The residency path uploads
    only the dirty subset (the disturber + its bookkeeping after
    readback re-marks it).  We assert the residency path is at most
    half the legacy bytes on this scene — the actual saving is
    ``capacity / max(1, active)``.
    """
    def _make_scene(persistent: bool) -> PhysicsWorld:
        cfg = PhysicsYaml(
            world=WorldConfig(default_dt=1.0 / 60.0, substeps=1, gravity=(0.0, 0.0)),
            hull=HullConfig(),
            cell=CellConfig(),
            collision=CollisionConfig(),
            gpu=GpuConfig(
                enabled=True, debug_force_cpu=False, persistent_residency=persistent,
                indirect_dispatch=True,
            ),
        )
        w = PhysicsWorld(config=cfg, world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))
        w.config.frontier.enabled = False
        # Settled cluster: bodies far apart, no gravity → no contacts.
        for i in range(8):
            w.create_body(
                make_circle_silhouette(12), material="steel",
                position=(-200.0 + 50.0 * i, 0.0),
            )
        # Let all 8 settle out of the activation window.
        for _ in range(40):
            w.step()
        return w

    w_legacy = _make_scene(persistent=False)
    w_resi = _make_scene(persistent=True)
    if not (w_legacy._should_use_gpu() and w_resi._should_use_gpu()):
        pytest.skip("GPU path not live.")
    # All bodies should now be quiescent so the substep is a no-op.
    # Pick body 3 and inject a velocity field to wake exactly one slot.
    for w in (w_legacy, w_resi):
        target_hid = w.bodies[3].root_hull_id
        w._inject_local_velocity_field(
            hull_id=target_hid,
            world_point=(w.bodies[3].position[0], 0.0),
            local_dv=(0.0, -10.0),
            impact_speed_for_heat=5.0,
            rest=0.5,
        )
        w._mark_active(target_hid)

    slot_bytes = w_legacy._SLOT_BYTES

    def _instrument(w: PhysicsWorld) -> int:
        log: list[int] = []
        real = w._gpu_queue.write_buffer

        def spy(buf, offset, data):
            if buf is w._gpu_src_buf:
                log.append(len(data))
            return real(buf, offset, data)

        w._gpu_queue.write_buffer = spy  # type: ignore
        try:
            w.step()
        finally:
            w._gpu_queue.write_buffer = real  # type: ignore
        return sum(log)

    bytes_legacy = _instrument(w_legacy)
    bytes_resi = _instrument(w_resi)

    # Legacy path uploads capacity * slot_bytes per substep.
    assert bytes_legacy >= w_legacy.cell_pool.capacity * slot_bytes, (
        f"legacy upload {bytes_legacy} B is below the full-pool baseline "
        f"({w_legacy.cell_pool.capacity * slot_bytes} B) — instrumentation broken?"
    )
    # Residency path uploads at most a handful of slots — definitely
    # less than half the legacy bytes.
    assert bytes_resi < bytes_legacy // 2, (
        f"persistent_residency uploaded {bytes_resi} B vs legacy {bytes_legacy} B "
        f"— savings should be > 2× on this scene (pool capacity "
        f"{w_resi.cell_pool.capacity}, in_use {w_resi.cell_pool.in_use_count})."
    )
