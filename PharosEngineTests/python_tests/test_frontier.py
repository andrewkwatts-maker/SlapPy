"""Tests for the A*-frontier-driven automatic hull-refinement pass.

The :class:`FrontierSolver` is a SEPARATE pass that the game calls between
``world.step`` invocations.  These tests drive it directly with handcrafted
cell state -- we don't run the physics step in most tests because the goal
is to verify the policy decisions, not the per-pixel solver itself.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics import (
    FrontierConfig,
    FrontierSolver,
    PhysicsWorld,
    make_rect_silhouette,
)
from pharos_engine.physics.frontier import (
    _CH_DAMAGE,
    _CH_VX,
    _CH_VY,
)
from pharos_engine.physics.hull import NO_CELL_GRID


# --- helpers ----------------------------------------------------------------

def _world() -> PhysicsWorld:
    """No-gravity, no-bounds world for deterministic frontier tests."""
    w = PhysicsWorld(world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    return w


def _solver(**cfg_overrides) -> FrontierSolver:
    """Solver with predictable thresholds.  Defaults match FrontierConfig
    but a few are tightened so unit-test cell magnitudes register clearly."""
    cfg = FrontierConfig(**cfg_overrides)
    return FrontierSolver(cfg)


def _make_body(w: PhysicsWorld, material: str = "iron", **kw):
    """Author a 32x32-pixel rect body and return (body, hull_id)."""
    sil = make_rect_silhouette(32, 32)
    body = w.create_body(sil, material, **kw)
    return body, body.root_hull_id


def _inject_high_velocity_half(body, vmag: float = 50.0) -> None:
    """Set the body's cell velocity field so HALF the cells have a strong
    velocity -- guarantees a large std(|v|) and triggers subdivision."""
    cells = body.cells
    assert cells is not None
    cells[..., _CH_VX] = 0.0
    cells[..., _CH_VY] = 0.0
    # Half the cells = high velocity, half = zero.
    cells[:16, :, _CH_VX] = vmag
    # damage stays zero -- we want this to fire on velocity alone.


def _zero_all_cells(body) -> None:
    cells = body.cells
    assert cells is not None
    cells[..., _CH_VX] = 0.0
    cells[..., _CH_VY] = 0.0
    cells[..., _CH_DAMAGE] = 0.0


# --- tests ------------------------------------------------------------------

def test_solver_does_nothing_on_uniform_body():
    """Zero-velocity, zero-damage body has 0 disagreement -> no subdivide."""
    w = _world()
    body, hid = _make_body(w)
    _zero_all_cells(body)
    solver = _solver()

    pre_count = w.hulls.count
    solver.tick(w)

    assert solver.last_subdivided == []
    assert solver.last_coalesced == []
    assert w.hulls.count == pre_count
    assert int(w.hulls.child_count[hid]) == 0


def test_solver_subdivides_on_high_disagreement():
    """A body with a high-velocity region must be subdivided after one tick."""
    w = _world()
    body, hid = _make_body(w)
    _inject_high_velocity_half(body, vmag=50.0)
    solver = _solver()

    assert int(w.hulls.child_count[hid]) == 0
    solver.tick(w)
    assert hid in solver.last_subdivided
    assert int(w.hulls.child_count[hid]) == 7


def test_solver_respects_max_depth():
    """With max_depth=3, the 4th subdivision in a chain must NOT fire.

    To keep the test deterministic and within the cell-pool budget we
    walk a SINGLE chain of subdivisions: each round only the first child
    of the previous round gets a loud cell field, so only one hull
    subdivides per tick.  After three rounds the chain ends at a hull
    of depth=3, which must be the deepest subdivision-eligible hull.
    """
    w = _world()
    # Grow the pool so we have headroom for a 3-deep chain (1+7+7+7 = 22 slots).
    w.cell_pool.grow(64)
    body, hid = _make_body(w)
    solver = _solver(max_depth=3, coalesce_hysteresis_frames=1)

    chain = [hid]
    for round_ in range(3):
        # Make ONLY the current chain head loud; zero all other cell grids
        # so no sibling subdivides.
        head = chain[-1]
        alive_ids = np.nonzero(w.hulls._alive)[0]
        for aid in alive_ids:
            gid = int(w.hulls.cell_grid_id[aid])
            if gid == NO_CELL_GRID:
                continue
            cells = w.cell_pool.slot_view(gid)
            cells[..., _CH_VX] = 0.0
            cells[..., _CH_VY] = 0.0
        gid_head = int(w.hulls.cell_grid_id[head])
        if gid_head != NO_CELL_GRID:
            head_cells = w.cell_pool.slot_view(gid_head)
            head_cells[:16, :, _CH_VX] = 50.0
        # Clear cooldowns so the head can subdivide immediately.
        for st in solver._states.values():
            st.cooldown_frames = 0
        solver.tick(w)
        assert head in solver.last_subdivided, (
            f"round {round_}: expected hull {head} (depth "
            f"{int(w.hulls.depth[head])}) to subdivide"
        )
        # Pick first child as next chain head.
        off = int(w.hulls.child_offset[head])
        chain.append(int(w.hulls.children_buffer[off]))

    deepest = chain[-1]
    assert int(w.hulls.depth[deepest]) == 3

    # Now make the depth=3 leaf loud.  It must NOT subdivide.
    alive_ids = np.nonzero(w.hulls._alive)[0]
    for aid in alive_ids:
        gid = int(w.hulls.cell_grid_id[aid])
        if gid == NO_CELL_GRID:
            continue
        w.cell_pool.slot_view(gid)[...] = 0.0
    gid_deep = int(w.hulls.cell_grid_id[deepest])
    if gid_deep != NO_CELL_GRID:
        w.cell_pool.slot_view(gid_deep)[:16, :, _CH_VX] = 50.0
    for st in solver._states.values():
        st.cooldown_frames = 0
    pre_count = w.hulls.count
    solver.tick(w)
    assert solver.last_subdivided == [], (
        f"max_depth=3 must block further subdivision; got "
        f"{solver.last_subdivided}"
    )
    assert w.hulls.count == pre_count


def test_coalesce_after_settle():
    """Subdivide, then zero all children's cells; K+1 quiet ticks must
    coalesce."""
    w = _world()
    body, hid = _make_body(w)
    _inject_high_velocity_half(body, vmag=50.0)
    solver = _solver(coalesce_hysteresis_frames=4)

    solver.tick(w)
    assert int(w.hulls.child_count[hid]) == 7
    # Skip parent's post-subdivide cooldown by zeroing it -- we want to
    # test the COALESCE policy, not the cooldown.
    solver._states[hid].cooldown_frames = 0
    for st in solver._states.values():
        st.cooldown_frames = 0

    # Zero out every child's cells so disagreement = 0.
    off = int(w.hulls.child_offset[hid])
    children = [int(w.hulls.children_buffer[off + i]) for i in range(7)]
    for cid in children:
        gid = int(w.hulls.cell_grid_id[cid])
        if gid != NO_CELL_GRID:
            w.cell_pool.slot_view(gid)[...] = 0.0

    # Tick K times; coalesce should fire on the Kth tick.
    coalesced_at = -1
    for t in range(8):
        solver.tick(w)
        if hid in solver.last_coalesced:
            coalesced_at = t
            break

    assert coalesced_at >= 0, "parent never coalesced after settling"
    # And after coalesce the parent has no children.
    assert int(w.hulls.child_count[hid]) == 0


def test_hysteresis_prevents_thrash():
    """Alternate high/low cell state every frame.  The frontier solver
    must NOT subdivide-then-coalesce-then-subdivide the SAME hull within
    one ``coalesce_hysteresis_frames`` window.

    Concretely: we record the frame numbers on which ``hid`` either
    subdivides OR coalesces, then assert any two consecutive events are
    at least ``K`` ticks apart.
    """
    w = _world()
    body, hid = _make_body(w)
    K = 4
    # max_depth=1 means children (depth=1) cannot subdivide further, so
    # only `hid` is ever a subdivide candidate.  Keeps the cell pool tame
    # while still exercising the hysteresis policy on `hid`.
    solver = _solver(coalesce_hysteresis_frames=K, max_depth=1)

    events: list[tuple[int, str]] = []
    for f in range(20):
        # Always write into the ROOT's cell grid (subdivide leaves it intact).
        gid = int(w.hulls.cell_grid_id[hid])
        if gid != NO_CELL_GRID:
            cells = w.cell_pool.slot_view(gid)
            cells[..., _CH_VX] = 0.0
            if f % 2 == 0:
                cells[:16, :, _CH_VX] = 50.0  # loud
        # Also zero / load every child's cells so coalesce can fire on
        # quiet frames (they need ALL children below LOW for K frames).
        if int(w.hulls.child_count[hid]) > 0:
            off = int(w.hulls.child_offset[hid])
            for i in range(int(w.hulls.child_count[hid])):
                cid = int(w.hulls.children_buffer[off + i])
                cgid = int(w.hulls.cell_grid_id[cid])
                if cgid == NO_CELL_GRID:
                    continue
                ccells = w.cell_pool.slot_view(cgid)
                if f % 2 == 0:
                    ccells[:16, :, _CH_VX] = 50.0
                else:
                    ccells[..., _CH_VX] = 0.0
        solver.tick(w)
        if hid in solver.last_subdivided:
            events.append((f, "sub"))
        if hid in solver.last_coalesced:
            events.append((f, "coa"))

    # No two events on the same hull within K frames of each other.
    for (fa, _), (fb, _) in zip(events, events[1:]):
        assert fb - fa >= K, (
            f"events on hull {hid} within hysteresis window K={K}: {events}"
        )


def test_solver_skips_t0_hulls():
    """A hull with NO_CELL_GRID gets disagreement 0 and is never subdivided."""
    w = _world()
    # T0 body has no cell grid by construction.
    from pharos_engine.physics import TIER_T0
    sil = make_rect_silhouette(32, 32)
    body = w.create_body(sil, "iron", tier=TIER_T0)
    hid = body.root_hull_id
    assert int(w.hulls.cell_grid_id[hid]) == NO_CELL_GRID

    solver = _solver()
    solver.tick(w)
    assert solver.last_subdivided == []
    assert int(w.hulls.child_count[hid]) == 0
    assert solver.disagreement_score(w, hid) == 0.0


def test_solver_skips_fixed_grounds():
    """``fixed=True`` hulls must never be auto-subdivided even when their
    cell field is loud."""
    w = _world()
    body, hid = _make_body(w, fixed=True)
    _inject_high_velocity_half(body, vmag=100.0)
    solver = _solver()

    solver.tick(w)
    assert hid not in solver.last_subdivided
    assert int(w.hulls.child_count[hid]) == 0


def test_disable_in_config_subdivides_nothing():
    """``enable_subdivide=False`` -> no subdivide() calls even on a
    loud body."""
    w = _world()
    body, hid = _make_body(w)
    _inject_high_velocity_half(body, vmag=100.0)
    solver = _solver(enable_subdivide=False)

    solver.tick(w)
    assert solver.last_subdivided == []
    assert int(w.hulls.child_count[hid]) == 0


# --- bonus regression: disagreement_score sanity ----------------------------

def test_disagreement_score_zero_for_uniform_field():
    w = _world()
    body, hid = _make_body(w)
    _zero_all_cells(body)
    solver = _solver()
    assert solver.disagreement_score(w, hid) == pytest.approx(0.0)


def test_disagreement_score_responds_to_damage():
    """Damage variance alone produces a non-zero score even when velocity
    is uniform."""
    w = _world()
    body, hid = _make_body(w)
    _zero_all_cells(body)
    cells = body.cells
    assert cells is not None
    cells[:16, :, _CH_DAMAGE] = 1.0  # half the cells fully damaged
    solver = _solver()
    score = solver.disagreement_score(w, hid)
    assert score > 0.0
