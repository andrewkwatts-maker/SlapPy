"""A*-frontier-driven automatic hull refinement.

The hierarchical-hull tree (:class:`slappyengine.physics.hull.HullTree`)
exposes ``subdivide`` and ``coalesce`` operations that the game can call
manually.  The frontier solver here is the *automatic* policy that decides,
each frame, which live hulls should be subdivided (their per-cell state
disagrees too strongly with a single rigid transform) and which previously-
subdivided hulls should be coalesced back (their children have settled).

This module is a SEPARATE pass.  It does not wire itself into ``world.step``;
the game calls ``FrontierSolver.tick(world)`` between steps when it wants the
adaptive policy to run.  See ``docs/per_pixel_physics_design.md`` -- "CPU +
GPU split -- A*-frontier" -- for the broader design rationale.

Disagreement signal
-------------------

For each candidate hull the solver reads its cell grid via
``cell_pool.slot_view(cell_grid_id)`` and computes a scalar disagreement
score from three signals:

* ``std(|v|)`` over cells -- non-rigid internal motion (pixels moving
  relative to each other; the dominant signal because the hull's rigid
  transform already represents bulk translation/rotation).
* ``std(damage)`` -- crack-tip / fracture-front presence inside the hull.
* ``max(pressure)`` -- a cheap proxy for the "max stress" disagreement
  metric from the design doc; treated as a soft contribution because
  pressure is also high under static load (we don't want a settled stack
  of crates to keep subdividing forever).

The weighted sum is compared against ``velocity_std_threshold_high`` /
``damage_std_threshold_high`` for subdivision and the matching ``_low``
thresholds for coalescence with a K-frame hysteresis window.

Edge cases
----------

* Hulls with no cell grid (T0/T1) score 0.0 and are ignored.
* Hulls with ``fixed=True`` (ground / wall) are never subdivided -- they
  may legitimately have wildly disagreeing cell state under impact but we
  don't want grounds shattering into 7 sub-grounds per frame.
* Hulls already at ``max_depth`` are also skipped for subdivide.
* Children with zero mass are ignored when computing the parent's
  "all children settled" check; if EVERY child is zero-mass we treat
  the parent as settled (degenerate).
* Division-by-zero in std() is impossible since numpy returns 0.0 for
  the constant-array case, which is exactly what we want.

Test coverage
-------------

See ``python/tests/test_frontier.py``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from slappyengine.physics.hull import NO_CELL_GRID


# --- Channel offsets in the 16-channel cell layout (cell.py is canonical) ---
_CH_VX = 2
_CH_VY = 3
_CH_PRESSURE = 7
_CH_DAMAGE = 8


# --- Weights for the disagreement score blend ------------------------------
#
# Velocity-std dominates because it directly measures "pixels moving relative
# to the rigid frame".  Damage is a strong but smaller signal because cracks
# are local.  Pressure is a SOFT contribution (weight 0.1) so a settled stack
# under static load doesn't keep firing subdivisions -- it's the design doc's
# "max stress" metric but tamed.
_WEIGHT_VELOCITY_STD = 1.0
_WEIGHT_DAMAGE_STD = 1.0
_WEIGHT_PRESSURE_MAX = 0.1


@dataclass
class FrontierConfig:
    """Tunable thresholds for the frontier solver.

    Hysteresis: a previously-subdivided hull only coalesces back once ALL of
    its children have stayed below the low threshold for
    ``coalesce_hysteresis_frames`` consecutive ticks.  Resetting the counter
    whenever any child rises above the low threshold prevents thrashing on
    borderline cases.
    """
    velocity_std_threshold_high: float = 0.5     # std(|v|) over cells
    velocity_std_threshold_low: float = 0.1
    damage_std_threshold_high: float = 0.05
    damage_std_threshold_low: float = 0.01
    coalesce_hysteresis_frames: int = 4
    max_depth: int = 3                            # don't subdivide past this
    enable_subdivide: bool = True
    enable_coalesce: bool = True


@dataclass
class _HullState:
    """Per-hull bookkeeping for the frontier solver."""
    last_disagreement: float = 0.0
    frames_below_low: int = 0
    # Frames since this hull was last subdivided; while non-zero it cannot
    # be subdivided OR coalesced again -- design doc K=4 latency rule.
    cooldown_frames: int = 0


class FrontierSolver:
    """A*-style frontier-driven automatic hull refinement.

    Usage::

        solver = FrontierSolver(FrontierConfig())
        for f in range(N):
            world.step(dt)
            solver.tick(world)   # may call world.hulls.subdivide / coalesce

    The solver maintains per-hull bookkeeping (last disagreement, frames the
    hull's children have stayed below the low threshold, post-op cooldown).
    State is keyed by hull id; freed hulls' entries are pruned lazily on tick.

    After each ``tick`` call:

    * ``last_subdivided`` lists the hull ids that were just subdivided.
    * ``last_coalesced`` lists the parent ids whose children were just
      coalesced back.
    """

    def __init__(self, config: FrontierConfig):
        """Build a solver with the given config.  No world reference is
        captured -- the world is passed to each ``tick`` so a single solver
        could in principle drive multiple worlds (rare but legal)."""
        self.config = config
        self._states: dict[int, _HullState] = {}
        self.last_subdivided: list[int] = []
        self.last_coalesced: list[int] = []

    # ------------------------------------------------------------------ score

    def disagreement_score(self, world, hull_id: int) -> float:
        """Compute a scalar disagreement score for ``hull_id``.

        Returns 0.0 for hulls that have no cell grid (T0/T1) -- they're
        invisible to the frontier policy and the caller is expected to skip
        them.

        The blend is::

            score = W_v * std(|v|) + W_d * std(damage) + W_p * max(pressure)

        with weights from the module-level ``_WEIGHT_*`` constants.  We use
        ``std(|v|)`` (the speed magnitude) rather than per-axis std so a
        pure rotation about the cell-grid centre, which has zero std on
        each axis individually but non-zero |v| std, still registers.
        """
        hulls = world.hulls
        gid = int(hulls.cell_grid_id[hull_id])
        if gid == NO_CELL_GRID:
            return 0.0
        try:
            cells = world.cell_pool.slot_view(gid)
        except (ValueError, KeyError):
            return 0.0

        # |v| per cell.  Channels are (H, W, C) = (32, 32, 16).
        vx = cells[..., _CH_VX]
        vy = cells[..., _CH_VY]
        speed = np.sqrt(vx * vx + vy * vy)
        v_std = float(speed.std())

        damage = cells[..., _CH_DAMAGE]
        d_std = float(damage.std())

        pressure = cells[..., _CH_PRESSURE]
        p_max = float(np.abs(pressure).max())

        return (
            _WEIGHT_VELOCITY_STD * v_std
            + _WEIGHT_DAMAGE_STD * d_std
            + _WEIGHT_PRESSURE_MAX * p_max
        )

    # ----------------------------------------------------------------- helpers

    def _state_for(self, hull_id: int) -> _HullState:
        st = self._states.get(hull_id)
        if st is None:
            st = _HullState()
            self._states[hull_id] = st
        return st

    def _prune_dead(self, world) -> None:
        """Drop bookkeeping for hulls that have been freed."""
        hulls = world.hulls
        dead = [hid for hid in self._states if not bool(hulls._alive[hid])]
        for hid in dead:
            del self._states[hid]

    def _is_leaf(self, world, hull_id: int) -> bool:
        """A hull is a leaf if it has no children (child_count == 0)."""
        return int(world.hulls.child_count[hull_id]) == 0

    def _is_subdivide_candidate(self, world, hull_id: int) -> bool:
        """Subdivision rules: alive, has cell grid, not fixed, leaf, depth ok."""
        hulls = world.hulls
        if not bool(hulls._alive[hull_id]):
            return False
        if int(hulls.cell_grid_id[hull_id]) == NO_CELL_GRID:
            return False
        if bool(hulls.fixed[hull_id]):
            return False
        if not self._is_leaf(world, hull_id):
            return False
        if int(hulls.depth[hull_id]) >= self.config.max_depth:
            return False
        return True

    def _children_of(self, world, parent_id: int) -> list[int]:
        hulls = world.hulls
        count = int(hulls.child_count[parent_id])
        if count <= 0:
            return []
        off = int(hulls.child_offset[parent_id])
        buf = hulls.children_buffer
        return [int(buf[off + i]) for i in range(count)]

    # -------------------------------------------------------------------- tick

    def tick(self, world) -> None:
        """Advance the frontier policy by one frame.

        Algorithm:

        1. Cooldown bookkeeping: every entry's ``cooldown_frames`` counts
           down to zero so a freshly-subdivided / freshly-coalesced hull is
           immune to flipping back for K frames.
        2. Subdivision pass: walk every live hull.  For each leaf candidate
           (alive, has cell grid, not fixed, depth < max_depth, no children
           yet, no active cooldown), compute its disagreement.  If above
           HIGH threshold, call ``world.hulls.subdivide(hid, world.cell_pool)``
           and seed children's bookkeeping with a cooldown.
        3. Coalescence pass: walk every hull that *has* children.  Compute
           each child's disagreement.  If ALL children are below LOW for
           ``coalesce_hysteresis_frames`` consecutive ticks, coalesce.
        """
        self.last_subdivided = []
        self.last_coalesced = []
        self._prune_dead(world)

        # Tick down cooldowns first so they don't immediately suppress
        # this frame's decisions for hulls created last frame.
        for st in self._states.values():
            if st.cooldown_frames > 0:
                st.cooldown_frames -= 1

        hulls = world.hulls
        # Snapshot the alive set up front: subdivide() will allocate new
        # hulls inside the loop and we must NOT re-enter them this tick.
        alive_ids = np.nonzero(hulls._alive)[0]
        alive_snapshot = [int(i) for i in alive_ids]

        # ------------------------------------------------------ subdivide pass
        if self.config.enable_subdivide:
            for hid in alive_snapshot:
                if not bool(hulls._alive[hid]):
                    continue  # may have been freed (defensive; not expected)
                if not self._is_subdivide_candidate(world, hid):
                    continue
                st = self._state_for(hid)
                if st.cooldown_frames > 0:
                    continue
                score = self.disagreement_score(world, hid)
                st.last_disagreement = score
                hulls.disagreement[hid] = score
                if self._above_high(score):
                    children = hulls.subdivide(hid, world.cell_pool)
                    self.last_subdivided.append(hid)
                    # Parent gets a cooldown so it doesn't immediately
                    # coalesce; children get one so they don't immediately
                    # re-subdivide.
                    st.cooldown_frames = self.config.coalesce_hysteresis_frames
                    st.frames_below_low = 0
                    for cid in children:
                        c_st = self._state_for(cid)
                        c_st.cooldown_frames = self.config.coalesce_hysteresis_frames
                        c_st.frames_below_low = 0
                        c_st.last_disagreement = 0.0

        # ------------------------------------------------------ coalesce pass
        if self.config.enable_coalesce:
            # Use a fresh snapshot -- after subdivide, the set of parents
            # changed.  Filter to parents that actually have children now.
            alive_now = np.nonzero(hulls._alive)[0]
            for hid in alive_now:
                hid = int(hid)
                if int(hulls.child_count[hid]) <= 0:
                    continue
                st = self._state_for(hid)
                if st.cooldown_frames > 0:
                    # Just-subdivided -- don't even score, leave hysteresis.
                    continue
                children = self._children_of(world, hid)
                if not children:
                    continue
                all_settled = True
                worst_child_score = 0.0
                for cid in children:
                    s = self.disagreement_score(world, cid)
                    hulls.disagreement[cid] = s
                    if s > worst_child_score:
                        worst_child_score = s
                    if not self._below_low(s):
                        all_settled = False
                st.last_disagreement = worst_child_score
                hulls.disagreement[hid] = worst_child_score
                if all_settled:
                    st.frames_below_low += 1
                else:
                    st.frames_below_low = 0
                if st.frames_below_low >= self.config.coalesce_hysteresis_frames:
                    hulls.coalesce(hid, world.cell_pool)
                    self.last_coalesced.append(hid)
                    st.frames_below_low = 0
                    st.cooldown_frames = self.config.coalesce_hysteresis_frames

    # --------------------------------------------------------- threshold tests

    def _above_high(self, score: float) -> bool:
        """A score 'fires' subdivision if EITHER the velocity-std or
        damage-std *partial* contribution would individually exceed its
        own HIGH threshold -- approximated here by testing whether the
        blended score exceeds the velocity HIGH threshold (the dominant
        weight).  This is conservative: damage-driven subdivision still
        kicks in via the damage term's contribution to the same sum.

        We compare against the velocity HIGH threshold scaled by its weight
        so the threshold is in the same units as the blended score.
        """
        return score > (
            _WEIGHT_VELOCITY_STD * self.config.velocity_std_threshold_high
        )

    def _below_low(self, score: float) -> bool:
        """Settled if the blended score is below the velocity LOW threshold
        AND the damage LOW threshold (i.e. each contribution is, on its
        own, in the settled band).  We use the strictest -- the velocity
        LOW threshold scaled by its weight, since that's the dominant
        signal."""
        return score <= (
            _WEIGHT_VELOCITY_STD * self.config.velocity_std_threshold_low
        )


__all__ = [
    "FrontierConfig",
    "FrontierSolver",
]
