"""Phase B default-flip guard: persistent residency parity + default.

This file is the regression net that locks in the
``GpuConfig.persistent_residency=True`` default flip.  It owns three
contracts:

1. **Default is on.**  ``GpuConfig().persistent_residency`` evaluates
   to ``True`` after the flip; ``config/physics.yml`` matches.
2. **Cell-state parity** across all six baseline benchmark scenarios:
   running the same scenario for 120 frames with persistent_residency
   on vs off produces per-cell state that agrees within 1e-3 at frames
   30 / 60 / 90 / 120.  Tested on the CPU canonical path (always
   available) and — when a wgpu adapter is present — on the GPU path
   too.  The CPU path runs ``_gpu_upload_dirty_slots`` only when the
   GPU is initialised, so the CPU-only legs validate the dirty-set
   bookkeeping (it must never desync the pool's in_use / dirty / gpu_
   resident sets even with no real GPU writes).
3. **Special-case parity** for two scenarios that the broad sweep
   doesn't naturally exercise:
   - ``test_persistent_residency_after_fracture`` — after a glass
     impact fragments the body, the newly spawned shard cells must
     match between the two paths.
   - ``test_persistent_residency_after_inject`` — calling
     ``_inject_local_velocity_field`` directly must keep both worlds
     coherent (covers the impulse-driven path that ``world.step``
     drives during collision resolution).

See ``docs/persistent_residency_decision.md`` for the A/B numbers that
justified the flip and ``docs/next_phase_plan.md`` §3.2.B for the
design.
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
from slappyengine.physics.profile import _SCENARIO_BUILDERS, baseline_scenarios
from slappyengine.physics.world import (
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


def _build_scenario_world(
    name: str,
    *,
    persistent_residency: bool,
    force_cpu: bool,
) -> PhysicsWorld:
    """Build a scenario world with explicit residency / CPU toggles.

    Mirrors :meth:`BenchmarkScenario.build_world` but lets the caller
    drive the residency + CPU/GPU knobs (the benchmark builder hard-
    codes both off).
    """
    scens = {s.name: s for s in baseline_scenarios()}
    scen = scens[name]
    world = PhysicsWorld(world_bounds=scen.world_bounds)
    world.config.world = type(world.config.world)(
        default_dt=world.config.world.default_dt,
        substeps=world.config.world.substeps,
        gravity=scen.gravity,
    )
    world.config.gpu.enabled = not force_cpu
    world.config.gpu.debug_force_cpu = bool(force_cpu)
    world.config.gpu.persistent_residency = bool(persistent_residency)
    # Hold indirect_dispatch at its post-flip default; this test only
    # varies persistent_residency.
    world.config.gpu.indirect_dispatch = True
    builder = _SCENARIO_BUILDERS[name]
    builder(scen, world)
    return world


def _snapshot_cell_pool(world: PhysicsWorld) -> np.ndarray:
    """Snapshot only the slots in_use so capacity-growth differences
    between worlds don't trip the diff."""
    pool = world.cell_pool
    in_use = sorted(pool._in_use)
    if not in_use:
        return np.empty((0,), dtype=np.float32)
    return np.stack([pool._cells[gid].copy() for gid in in_use])


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("inf")
    if a.size == 0:
        return 0.0
    return float(np.abs(a - b).max())


# --- (1) Default is on ------------------------------------------------------


def test_default_is_persistent():
    """After the flip, ``GpuConfig`` defaults to persistent residency."""
    assert GpuConfig().persistent_residency is True
    # The default of the top-level config dataclass also flows through.
    assert PhysicsYaml().gpu.persistent_residency is True


def test_yaml_default_matches_dataclass():
    """``config/physics.yml`` must agree with the dataclass default so
    callers don't see a different effective value depending on whether
    they go through ``load_physics_config`` or ``PhysicsYaml()``.
    """
    from pathlib import Path

    import yaml

    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "config" / "physics.yml"
        if cand.exists():
            yml_path = cand
            break
    else:
        pytest.skip("config/physics.yml not found relative to test file.")
    raw = yaml.safe_load(yml_path.read_text(encoding="utf-8")) or {}
    assert bool(raw.get("gpu", {}).get("persistent_residency", False)) is True, (
        "config/physics.yml gpu.persistent_residency must equal the new "
        "dataclass default (True)."
    )


# --- (2) Broad parity sweep -------------------------------------------------


_SCENARIO_NAMES = (
    "solo_drop",
    "multi_body_5",
    "multi_body_50",
    "fluid_pool",
    "fracture",
    "idle_settled",
)
_CHECK_FRAMES = (30, 60, 90, 120)
_PARITY_TOL = 1e-3


@pytest.mark.parametrize("scenario", _SCENARIO_NAMES)
def test_persistent_residency_parity_cpu(scenario):
    """CPU canonical path: persistent vs legacy worlds must stay locked.

    With ``debug_force_cpu=True`` the GPU substep helpers are not
    invoked, so this leg specifically validates that toggling
    persistent_residency on the CPU path does not perturb the cell
    state — the dirty-set bookkeeping must be a pure invariant, never a
    semantic change.  Runs all six baseline scenarios.
    """
    np.random.seed(0)
    w_legacy = _build_scenario_world(
        scenario, persistent_residency=False, force_cpu=True,
    )
    w_resi = _build_scenario_world(
        scenario, persistent_residency=True, force_cpu=True,
    )

    max_frame = max(_CHECK_FRAMES)
    diffs: dict[int, float] = {}
    for frame in range(1, max_frame + 1):
        w_legacy.step()
        w_resi.step()
        if frame in _CHECK_FRAMES:
            snap_l = _snapshot_cell_pool(w_legacy)
            snap_r = _snapshot_cell_pool(w_resi)
            diffs[frame] = _diff(snap_l, snap_r)
            assert diffs[frame] < _PARITY_TOL, (
                f"[{scenario}] CPU parity broke at frame {frame}: "
                f"max_abs_diff={diffs[frame]:.4e}"
            )

    # Bookkeeping invariants on the residency pool must hold.
    pool = w_resi.cell_pool
    assert pool._dirty.issubset(pool._in_use)
    assert pool._gpu_resident.issubset(pool._in_use)


@pytest.mark.skipif(not _gpu_available(), reason="No wgpu adapter present.")
@pytest.mark.parametrize("scenario", _SCENARIO_NAMES)
def test_persistent_residency_parity_gpu(scenario):
    """GPU path: dirty-slot upload must match legacy full-upload state.

    This is the hard parity contract — the dirty-set must cover *every*
    cell write the CPU performs between dispatches, or the GPU sees
    stale data and diverges.
    """
    np.random.seed(0)
    w_legacy = _build_scenario_world(
        scenario, persistent_residency=False, force_cpu=False,
    )
    w_resi = _build_scenario_world(
        scenario, persistent_residency=True, force_cpu=False,
    )
    if not (w_legacy._should_use_gpu() and w_resi._should_use_gpu()):
        pytest.skip("GPU path not live in this build.")

    max_frame = max(_CHECK_FRAMES)
    for frame in range(1, max_frame + 1):
        w_legacy.step()
        w_resi.step()
        if frame in _CHECK_FRAMES:
            snap_l = _snapshot_cell_pool(w_legacy)
            snap_r = _snapshot_cell_pool(w_resi)
            d = _diff(snap_l, snap_r)
            assert d < _PARITY_TOL, (
                f"[{scenario}] GPU parity broke at frame {frame}: "
                f"max_abs_diff={d:.4e}"
            )


# --- (3) Special-case parity ------------------------------------------------


def test_persistent_residency_after_inject():
    """Explicit ``_inject_local_velocity_field`` calls must keep cells
    coherent between the two paths.

    The collision resolver drives this helper many times per frame at
    contact zones; if the inject forgets to ``mark_dirty`` its slot we
    would see deterministic drift after the first frame.  We test the
    CPU path here (always available) — the GPU path is covered by the
    broad sweep above.
    """
    def _make() -> PhysicsWorld:
        cfg = PhysicsYaml(
            world=WorldConfig(default_dt=1.0 / 60.0, substeps=1, gravity=(0.0, 0.0)),
            hull=HullConfig(),
            cell=CellConfig(),
            collision=CollisionConfig(),
        )
        return PhysicsWorld(
            config=cfg, world_bounds=(-200.0, -200.0, 200.0, 200.0),
        )

    w_legacy = _make()
    w_resi = _make()
    w_legacy.config.gpu.persistent_residency = False
    w_resi.config.gpu.persistent_residency = True
    w_legacy.config.gpu.debug_force_cpu = True
    w_resi.config.gpu.debug_force_cpu = True

    # Same body in each world.
    for w in (w_legacy, w_resi):
        w.create_body(
            make_circle_silhouette(24), material="steel",
            position=(0.0, 0.0),
        )

    body_legacy = w_legacy.bodies[0]
    body_resi = w_resi.bodies[0]
    inject_points = [
        ((6.0, 0.0), (0.0, -40.0), 20.0),
        ((-4.0, 3.0), (10.0, 0.0), 15.0),
        ((0.0, -8.0), (0.0, 30.0), 25.0),
    ]
    for (pt, dv, sp) in inject_points:
        w_legacy._inject_local_velocity_field(
            hull_id=body_legacy.root_hull_id,
            world_point=pt, local_dv=dv,
            impact_speed_for_heat=sp, rest=0.4,
        )
        w_resi._inject_local_velocity_field(
            hull_id=body_resi.root_hull_id,
            world_point=pt, local_dv=dv,
            impact_speed_for_heat=sp, rest=0.4,
        )

    # Inject alone (no step) must produce identical slot bytes.
    gid_l = int(w_legacy.hulls.cell_grid_id[body_legacy.root_hull_id])
    gid_r = int(w_resi.hulls.cell_grid_id[body_resi.root_hull_id])
    cells_l = w_legacy.cell_pool.slot_view(gid_l)
    cells_r = w_resi.cell_pool.slot_view(gid_r)
    assert _diff(cells_l, cells_r) < _PARITY_TOL, (
        "Inject-only divergence: persistent_residency is not supposed to "
        "alter cell values, only the upload schedule."
    )
    # And the residency pool must know it needs to upload that slot.
    assert w_resi.cell_pool.needs_upload(gid_r) is True

    # Now step a few frames and check ongoing parity.
    for frame in range(1, 31):
        w_legacy.step()
        w_resi.step()
    cells_l = w_legacy.cell_pool.slot_view(gid_l)
    cells_r = w_resi.cell_pool.slot_view(gid_r)
    assert _diff(cells_l, cells_r) < _PARITY_TOL


def test_persistent_residency_after_fracture():
    """After a brittle-fracture event, any newly spawned shard hulls
    must match between persistent and legacy paths.

    Uses the same scene as the ``assess_sim.glass_shatter`` scenario:
    a steel projectile slams into a glass plate at high velocity.
    Whether or not the world actually spawns fragment bodies in 90
    frames, the cells of every in_use slot must agree to tolerance.
    """
    def _make() -> PhysicsWorld:
        cfg = PhysicsYaml(
            world=WorldConfig(default_dt=1.0 / 60.0, substeps=4, gravity=(0.0, 0.0)),
            hull=HullConfig(),
            cell=CellConfig(),
            collision=CollisionConfig(),
        )
        return PhysicsWorld(
            config=cfg, world_bounds=(-200.0, -100.0, 200.0, 250.0),
        )

    w_legacy = _make()
    w_resi = _make()
    for w, persistent in ((w_legacy, False), (w_resi, True)):
        w.config.gpu.persistent_residency = persistent
        w.config.gpu.debug_force_cpu = True  # CPU canonical for deterministic compare
        w.create_body(
            make_rect_silhouette(80, 24), material="glass", position=(60.0, 0.0),
        )
        w.create_body(
            make_circle_silhouette(14), material="steel",
            position=(-160.0, 0.0), velocity=(360.0, 0.0),
        )

    # Sanity: identical initial state.
    assert _diff(_snapshot_cell_pool(w_legacy), _snapshot_cell_pool(w_resi)) < _PARITY_TOL

    for frame in range(1, 91):
        w_legacy.step()
        w_resi.step()
        # Per-frame parity check at every 30th frame is cheap enough.
        if frame % 30 == 0:
            snap_l = _snapshot_cell_pool(w_legacy)
            snap_r = _snapshot_cell_pool(w_resi)
            assert snap_l.shape == snap_r.shape, (
                f"Shard spawn diverged at frame {frame}: "
                f"legacy in_use={snap_l.shape[0]} vs persistent {snap_r.shape[0]}"
            )
            d = _diff(snap_l, snap_r)
            assert d < _PARITY_TOL, (
                f"Fracture parity broke at frame {frame}: "
                f"max_abs_diff={d:.4e}"
            )

    # Residency pool's bookkeeping must remain coherent across fragment
    # spawns (which add new in_use slots that have to be tracked).
    pool = w_resi.cell_pool
    assert pool._dirty.issubset(pool._in_use)
    assert pool._gpu_resident.issubset(pool._in_use)
