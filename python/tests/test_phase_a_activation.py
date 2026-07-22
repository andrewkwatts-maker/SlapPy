"""Phase A regression tests: SoA activation column + auto-tick frontier.

Phase A promoted the dict-based ``world.active_until_frame`` to a numpy
SoA column on :class:`HullTree`, vectorised ``_gather_active_slots``, and
wired :class:`FrontierSolver` so ``world.step`` ticks it automatically.
These tests exercise each of those wires end-to-end:

* the substep loop is skipped entirely on quiescent scenes,
* contacts re-mark both bodies hot via the new column,
* the vectorised mask returns exactly the hot subset,
* the frontier solver ticks once per ``world.step``,
* settled scenes are measurably cheaper than active ones, and
* ``subdivide`` / ``coalesce`` propagate activation between tiers.

See ``docs/next_phase_plan.md`` section 3.2 for the wider design context.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from slappyengine.physics import (
    FrontierConfig,
    FrontierSolver,
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)


# --- helpers ----------------------------------------------------------------


def _world_no_frontier() -> PhysicsWorld:
    """Build a world with auto-tick disabled.

    Several tests want to exercise the activation column in isolation
    (without subdivide/coalesce churn from the frontier policy) so the
    behaviour we observe is purely the gating wire.
    """
    w = PhysicsWorld(world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))
    w.config.frontier.enabled = False
    return w


def _world_frontier_on() -> PhysicsWorld:
    """Build a world with the Phase A auto-tick enabled (default)."""
    w = PhysicsWorld(world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))
    w.config.frontier.enabled = True
    return w


# --- tests ------------------------------------------------------------------


def test_quiescent_hull_skips_substep(monkeypatch):
    """Once a hull's settle window has elapsed the substep loop must not run.

    Spawn a single isolated steel body with zero velocity, never mark it
    active, then advance the world long enough for any inherited
    deadline to expire.  The CPU substep counter must read zero across
    the post-settle frames.
    """
    w = _world_no_frontier()
    # Zero gravity so there are no contacts and no auto-reactivation.
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    body = w.create_body(make_rect_silhouette(32, 32), "iron", position=(0.0, 0.0))
    # No _mark_active call -> quiescent from frame 0.
    assert not w._is_active(body.root_hull_id)

    # Spy on _cpu_substep so we can count invocations across the run.
    calls = {"n": 0}
    original = w._cpu_substep

    def _counting_substep(dt):  # noqa: ANN001
        calls["n"] += 1
        original(dt)

    monkeypatch.setattr(w, "_cpu_substep", _counting_substep)

    settle = w.config.hull.settle_frames
    # Run well past the settle window so even an accidental activation
    # would have decayed back to quiescent.
    for _ in range(settle + 5):
        w.step()
    assert calls["n"] == 0, (
        f"Quiescent steel body must skip the substep loop entirely "
        f"(got {calls['n']} _cpu_substep calls over {settle + 5} frames)"
    )


def test_contact_reactivates_both_bodies():
    """A frame-resolved contact must mark both participants hot.

    Drop a steel ball on a fixed stone ground; when the ball reaches the
    ground both hulls' ``active_until_frame`` deadlines should be in the
    future (the standard ``_mark_active`` writes ``frame + settle_frames``).
    """
    w = _world_no_frontier()
    ground = w.create_body(
        make_rect_silhouette(240, 16),
        material="stone",
        position=(0.0, 180.0),
        fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(24),
        material="steel",
        position=(0.0, 0.0),
    )

    contact_seen = False
    for _ in range(200):
        contacts = w.step()
        if any(c.b >= 0 for c in contacts):
            contact_seen = True
            # Inspect the column directly: contact handling writes through
            # _mark_active which now updates the SoA column.
            au = w.hulls.active_until_frame
            assert int(au[ball.root_hull_id]) >= int(w.frame), (
                "ball must be re-activated by the contact"
            )
            assert int(au[ground.root_hull_id]) >= int(w.frame), (
                "ground must be re-activated by the contact"
            )
            break
    assert contact_seen, "expected at least one ball-ground contact in 200 frames"


def test_gather_active_slots_returns_only_hot_hulls():
    """The vectorised mask in ``_gather_active_slots`` must filter to hot."""
    w = _world_no_frontier()
    bodies = [
        w.create_body(make_rect_silhouette(32, 32), "iron", position=(100.0 * i, 0.0))
        for i in range(5)
    ]
    hids = [b.root_hull_id for b in bodies]
    # All hulls have a cell grid (T2) so they're all candidates -- only
    # the two we mark active should end up in the gathered slots.
    w._mark_active(hids[1])
    w._mark_active(hids[3])
    active = w._gather_active_slots()
    active_hids = sorted(h for (h, _g, _m) in active)
    assert active_hids == sorted([hids[1], hids[3]]), (
        f"_gather_active_slots returned {active_hids} but expected "
        f"only the marked hulls {sorted([hids[1], hids[3]])}"
    )


def test_frontier_auto_tick_runs():
    """The world step must invoke ``FrontierSolver.tick`` on every frame that
    has work for it.

    Phase A short-circuits the tick when the scene has no hot hulls AND no
    subdivided parents pending coalesce -- otherwise quiescent scenes would
    pay the per-frame disagreement-scoring cost for no benefit.  We keep
    one body hot for the duration of the run so the tick fires every step.
    """
    w = _world_frontier_on()
    # Force the solver into existence so we can instrument it.
    solver = w._ensure_frontier_solver()
    calls = {"n": 0}
    original_tick = solver.tick

    def _counting_tick(world):  # noqa: ANN001
        calls["n"] += 1
        original_tick(world)

    solver.tick = _counting_tick  # type: ignore[method-assign]

    # Spawn one body and keep it hot so the auto-tick fast-path doesn't
    # short-circuit on a fully-quiescent scene.
    body = w.create_body(make_rect_silhouette(32, 32), "iron", position=(0.0, 0.0))

    n_steps = 10
    for _ in range(n_steps):
        w._mark_active(body.root_hull_id)
        w.step()
    assert calls["n"] == n_steps, (
        f"FrontierSolver.tick should fire exactly once per world.step "
        f"while a hot hull exists; got {calls['n']} ticks over {n_steps} frames"
    )


def test_settled_world_zero_substep_cost():
    """Settled scenes must be measurably cheaper than active ones.

    Build a small pile of stones, settle them, then measure the
    post-settle per-frame cost.  It must be < 50% of the per-frame cost
    of an equivalent active scene.  We use stones because their wave
    speed lets the velocity field decay below the frontier's LOW
    threshold within ``settle_frames``.
    """
    n_bodies = 20

    def _build_world(active: bool) -> PhysicsWorld:
        # Frontier off here so the cost difference is purely about the
        # substep gate, not about subdivide churn.
        w = _world_no_frontier()
        # Zero gravity + ample spacing so the broadphase never finds a
        # contact (which would re-activate everyone via _mark_active and
        # invalidate the settled half of the test).
        w.config.world = type(w.config.world)(
            default_dt=w.config.world.default_dt,
            substeps=w.config.world.substeps,
            gravity=(0.0, 0.0),
        )
        for i in range(n_bodies):
            body = w.create_body(
                make_rect_silhouette(32, 32),
                "stone",
                position=(80.0 * i, 0.0),
            )
            if active:
                # Keep them hot by re-marking every frame outside the loop.
                w._mark_active(body.root_hull_id)
        return w

    def _measure(world: PhysicsWorld, frames: int, refresh_active: bool) -> float:
        # Warm-up to JIT numpy paths.
        for _ in range(3):
            world.step()
        start = time.perf_counter()
        for _ in range(frames):
            if refresh_active:
                for hid in range(world.hulls.capacity):
                    if world.hulls._alive[hid]:
                        world._mark_active(hid)
            world.step()
        return (time.perf_counter() - start) / frames

    # Active scene: keep every body hot each frame.
    w_active = _build_world(active=True)
    active_per_frame = _measure(w_active, frames=30, refresh_active=True)

    # Settled scene: spawn, settle past the deadline, then measure.
    w_settled = _build_world(active=False)
    # Push the world's frame counter past any inherited deadline.
    for _ in range(w_settled.config.hull.settle_frames + 5):
        w_settled.step()
    # Verify nothing is hot before timing.
    assert (
        w_settled.hulls.active_until_frame[w_settled.hulls._alive] < int(w_settled.frame)
    ).all(), "expected every body to be quiescent after settle window"
    settled_per_frame = _measure(w_settled, frames=30, refresh_active=False)

    assert settled_per_frame < 0.5 * active_per_frame, (
        f"settled per-frame cost ({settled_per_frame * 1000:.3f} ms) is not "
        f"under 50% of the active cost ({active_per_frame * 1000:.3f} ms); "
        f"Phase A substep skip is not paying off"
    )


def test_subdivide_inherits_activation():
    """Children of a hot parent must inherit ``activation_level`` and the deadline."""
    w = _world_no_frontier()
    body = w.create_body(make_rect_silhouette(32, 32), "iron", position=(0.0, 0.0))
    hid = body.root_hull_id
    w._mark_active(hid)
    parent_until = int(w.hulls.active_until_frame[hid])
    parent_level = int(w.hulls.activation_level[hid])
    assert parent_level == 2, "expected _mark_active to set level=2"

    child_ids = w.hulls.subdivide(hid, cell_pool=w.cell_pool)
    assert len(child_ids) == 7
    for cid in child_ids:
        assert int(w.hulls.activation_level[cid]) == parent_level, (
            f"child {cid} did not inherit activation_level "
            f"(got {int(w.hulls.activation_level[cid])}, want {parent_level})"
        )
        assert int(w.hulls.active_until_frame[cid]) == parent_until, (
            f"child {cid} did not inherit active_until_frame deadline"
        )


def test_coalesce_takes_max_child_activation():
    """``coalesce`` must set the parent to ``max(child_activation_level)``."""
    w = _world_no_frontier()
    body = w.create_body(make_rect_silhouette(32, 32), "iron", position=(0.0, 0.0))
    hid = body.root_hull_id
    child_ids = w.hulls.subdivide(hid, cell_pool=w.cell_pool)
    assert len(child_ids) == 7

    # Reset everyone to a known baseline, then set one hot, one cold.
    for cid in child_ids:
        w.hulls.activation_level[cid] = 0
        w.hulls.active_until_frame[cid] = -1
    w.hulls.activation_level[hid] = 0
    w.hulls.active_until_frame[hid] = -1

    a, b = child_ids[0], child_ids[1]
    w.hulls.activation_level[a] = 2
    w.hulls.active_until_frame[a] = 42
    w.hulls.activation_level[b] = 0
    w.hulls.active_until_frame[b] = -1

    w.hulls.coalesce(hid, cell_pool=w.cell_pool)
    assert int(w.hulls.activation_level[hid]) == 2, (
        "parent must take max(child_activation_level) after coalesce"
    )
    assert int(w.hulls.active_until_frame[hid]) == 42, (
        "parent must take max(child_active_until_frame) after coalesce"
    )
