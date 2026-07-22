"""Input-validation tests for the public :class:`pharos_engine.dynamics.World`
API (hardening round 8).

Mirrors the structure of ``test_hardening_audio.py``: positive paths are
covered by ``test_dynamics_unified_step.py`` / ``test_dynamics_*.py``;
this file only exercises the rejection contract added on top of
``_validation.py``'s new helpers.

Engineering policy under test: validate at the public boundary, refuse
silent coercion / NaN-poisoning / out-of-range params loudly so the
failure surfaces at the authoring site instead of as a NaN cascade
several frames later inside the XPBD solver.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from pharos_engine.dynamics import (  # noqa: E402
    Body,
    JointSpec,
    World,
)


# ---------------------------------------------------------------------------
# World.__init__ — gravity
# ---------------------------------------------------------------------------


def test_init_accepts_default_gravity():
    w = World()
    assert tuple(w.gravity) == (0.0, -9.81)


def test_init_rejects_nan_gravity_x():
    with pytest.raises(ValueError, match="gravity"):
        World(gravity=(float("nan"), -9.81))


def test_init_rejects_nan_gravity_y():
    with pytest.raises(ValueError, match="gravity"):
        World(gravity=(0.0, float("nan")))


def test_init_rejects_inf_gravity():
    with pytest.raises(ValueError, match="gravity"):
        World(gravity=(0.0, float("inf")))


def test_init_rejects_neg_inf_gravity():
    with pytest.raises(ValueError, match="gravity"):
        World(gravity=(-float("inf"), 0.0))


def test_init_rejects_short_gravity():
    with pytest.raises(ValueError, match="length 2"):
        World(gravity=(0.0,))  # type: ignore[arg-type]


def test_init_rejects_long_gravity():
    with pytest.raises(ValueError, match="length 2"):
        World(gravity=(0.0, -9.81, 0.0))  # type: ignore[arg-type]


def test_init_rejects_string_gravity():
    with pytest.raises(TypeError, match="gravity"):
        World(gravity="down")  # type: ignore[arg-type]


def test_init_rejects_none_gravity():
    with pytest.raises(TypeError, match="gravity"):
        World(gravity=None)  # type: ignore[arg-type]


def test_init_rejects_non_numeric_gravity_entries():
    with pytest.raises(TypeError, match="gravity"):
        World(gravity=("x", "y"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# World.solver_iterations setter
# ---------------------------------------------------------------------------


def test_solver_iterations_default_is_eight():
    assert World().solver_iterations == 8


def test_solver_iterations_accepts_one():
    w = World()
    w.solver_iterations = 1
    assert w.solver_iterations == 1


def test_solver_iterations_accepts_hundred():
    w = World()
    w.solver_iterations = 100
    assert w.solver_iterations == 100


def test_solver_iterations_rejects_zero():
    w = World()
    with pytest.raises(ValueError, match="solver_iterations"):
        w.solver_iterations = 0


def test_solver_iterations_rejects_negative():
    w = World()
    with pytest.raises(ValueError, match="solver_iterations"):
        w.solver_iterations = -1


def test_solver_iterations_rejects_over_max():
    w = World()
    with pytest.raises(ValueError, match="solver_iterations"):
        w.solver_iterations = 101


def test_solver_iterations_rejects_huge_value():
    # Silent-acceptance bug class: ``solver_iterations = 1_000_000`` would
    # silently grind step() to a halt for ~minutes per frame. Refuse loudly.
    w = World()
    with pytest.raises(ValueError, match="solver_iterations"):
        w.solver_iterations = 1_000_000


def test_solver_iterations_rejects_float():
    w = World()
    with pytest.raises(TypeError, match="solver_iterations"):
        w.solver_iterations = 8.5  # type: ignore[assignment]


def test_solver_iterations_rejects_bool():
    # ``world.solver_iterations = True`` silently means 1 iteration. Refuse.
    w = World()
    with pytest.raises(TypeError, match="solver_iterations"):
        w.solver_iterations = True  # type: ignore[assignment]


def test_solver_iterations_rejects_string():
    w = World()
    with pytest.raises(TypeError, match="solver_iterations"):
        w.solver_iterations = "8"  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# World.step — dt
# ---------------------------------------------------------------------------


def test_step_accepts_typical_dt():
    w = World()
    w.add_node((0.0, 0.0))
    w.step(1.0 / 60.0)
    assert w.frame == 1


def test_step_rejects_zero_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(0.0)


def test_step_rejects_negative_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(-1.0 / 60.0)


def test_step_rejects_dt_above_one_second():
    # dt > 1.0 silently tunnels nodes through every constraint.
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(1.5)


def test_step_rejects_huge_dt_unit_typo():
    # Silent-acceptance bug class: passing microseconds (1e6) instead of
    # seconds (1.0) produced NaN positions on the first frame.
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(1e6)


def test_step_rejects_nan_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(float("nan"))


def test_step_rejects_inf_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(ValueError, match="dt"):
        w.step(float("inf"))


def test_step_rejects_string_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(TypeError, match="dt"):
        w.step("0.016")  # type: ignore[arg-type]


def test_step_rejects_none_dt():
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(TypeError, match="dt"):
        w.step(None)  # type: ignore[arg-type]


def test_step_rejects_bool_dt():
    # Silent-acceptance bug class: ``step(True)`` would integrate one full
    # second of physics in a single XPBD step.
    w = World()
    w.add_node((0.0, 0.0))
    with pytest.raises(TypeError, match="dt"):
        w.step(True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# World.add_node
# ---------------------------------------------------------------------------


def test_add_node_returns_increasing_indices():
    w = World()
    assert w.add_node((0.0, 0.0)) == 0
    assert w.add_node((1.0, 0.0)) == 1


def test_add_node_rejects_nan_position():
    # Silent-acceptance bug class: a NaN initial position is gravity-
    # integrated to NaN velocities and the entire scene goes opaque.
    w = World()
    with pytest.raises(ValueError, match="pos"):
        w.add_node((float("nan"), 0.0))


def test_add_node_rejects_inf_position():
    w = World()
    with pytest.raises(ValueError, match="pos"):
        w.add_node((0.0, float("inf")))


def test_add_node_rejects_short_position():
    w = World()
    with pytest.raises(ValueError, match="length 2"):
        w.add_node((0.0,))  # type: ignore[arg-type]


def test_add_node_rejects_long_position():
    w = World()
    with pytest.raises(ValueError, match="length 2"):
        w.add_node((0.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_add_node_rejects_string_position():
    w = World()
    with pytest.raises(TypeError, match="pos"):
        w.add_node("origin")  # type: ignore[arg-type]


def test_add_node_rejects_none_position():
    w = World()
    with pytest.raises(TypeError, match="pos"):
        w.add_node(None)  # type: ignore[arg-type]


def test_add_node_rejects_negative_mass():
    # Silent-acceptance bug class: negative mass was silently turned into
    # a pinned node via the ``mass <= 0.0`` branch in the legacy impl.
    w = World()
    with pytest.raises(ValueError, match="mass"):
        w.add_node((0.0, 0.0), mass=-1.0)


def test_add_node_rejects_nan_mass():
    w = World()
    with pytest.raises(ValueError, match="mass"):
        w.add_node((0.0, 0.0), mass=float("nan"))


def test_add_node_rejects_inf_mass():
    w = World()
    with pytest.raises(ValueError, match="mass"):
        w.add_node((0.0, 0.0), mass=float("inf"))


def test_add_node_rejects_string_mass():
    w = World()
    with pytest.raises(TypeError, match="mass"):
        w.add_node((0.0, 0.0), mass="heavy")  # type: ignore[arg-type]


def test_add_node_accepts_zero_mass_as_pin():
    w = World()
    idx = w.add_node((0.0, 0.0), mass=0.0)
    assert w.inv_masses[idx] == 0.0


# ---------------------------------------------------------------------------
# World.add_nodes
# ---------------------------------------------------------------------------


def test_add_nodes_accepts_array_positions():
    w = World()
    offset, count = w.add_nodes(np.array([[0.0, 0.0], [1.0, 0.0]]))
    assert (offset, count) == (0, 2)


def test_add_nodes_rejects_nan_positions():
    w = World()
    with pytest.raises(ValueError, match="positions"):
        w.add_nodes(np.array([[0.0, float("nan")]]))


def test_add_nodes_rejects_inf_positions():
    w = World()
    with pytest.raises(ValueError, match="positions"):
        w.add_nodes(np.array([[float("inf"), 0.0]]))


def test_add_nodes_rejects_none():
    w = World()
    with pytest.raises(TypeError, match="positions"):
        w.add_nodes(None)  # type: ignore[arg-type]


def test_add_nodes_rejects_mass_length_mismatch():
    w = World()
    with pytest.raises(ValueError, match="masses length"):
        w.add_nodes(np.zeros((3, 2)), masses=np.array([1.0, 1.0]))


def test_add_nodes_rejects_negative_mass_array():
    w = World()
    with pytest.raises(ValueError, match="masses"):
        w.add_nodes(np.zeros((2, 2)), masses=np.array([1.0, -1.0]))


def test_add_nodes_rejects_nan_mass_array():
    w = World()
    with pytest.raises(ValueError, match="masses"):
        w.add_nodes(np.zeros((2, 2)), masses=np.array([1.0, float("nan")]))


def test_add_nodes_rejects_bool_scalar_mass():
    w = World()
    with pytest.raises(TypeError, match="masses"):
        w.add_nodes(np.zeros((2, 2)), masses=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# World.register_body
# ---------------------------------------------------------------------------


def test_register_body_accepts_body():
    w = World()
    w.add_node((0.0, 0.0))
    body = Body(kind="lattice", node_offset=0, node_count=1)
    assert w.register_body(body) is body
    assert w.bodies == [body]


def test_register_body_rejects_non_body():
    w = World()
    with pytest.raises(TypeError, match="body"):
        w.register_body({"node_offset": 0, "node_count": 1})  # type: ignore[arg-type]


def test_register_body_rejects_none():
    w = World()
    with pytest.raises(TypeError, match="body"):
        w.register_body(None)  # type: ignore[arg-type]


def test_register_body_rejects_string():
    w = World()
    with pytest.raises(TypeError, match="body"):
        w.register_body("rope")  # type: ignore[arg-type]


def test_register_body_rejects_duplicate_body():
    # Silent-acceptance bug class: the same Body registered twice would
    # appear twice in the editor outliner and trip serialiser invariants.
    w = World()
    w.add_node((0.0, 0.0))
    body = Body(kind="lattice", node_offset=0, node_count=1)
    w.register_body(body)
    with pytest.raises(ValueError, match="already registered"):
        w.register_body(body)


def test_register_body_rejects_node_slice_past_world():
    # Silent-acceptance bug class: a Body claiming nodes [0, 10) on a
    # 0-node world silently passed and crashed the renderer later.
    w = World()
    body = Body(kind="lattice", node_offset=0, node_count=10)
    with pytest.raises(ValueError, match="node slice"):
        w.register_body(body)


def test_register_body_rejects_negative_node_offset():
    w = World()
    body = Body(kind="lattice", node_offset=-1, node_count=0)
    with pytest.raises(ValueError, match="node_offset"):
        w.register_body(body)


def test_register_body_rejects_negative_node_count():
    w = World()
    body = Body(kind="lattice", node_offset=0, node_count=-1)
    with pytest.raises(ValueError, match="node_count"):
        w.register_body(body)


# ---------------------------------------------------------------------------
# World.add_joint
# ---------------------------------------------------------------------------


def test_add_joint_accepts_jointspec():
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    j = JointSpec(kind="distance", node_a=0, node_b=1, rest_length=1.0)
    assert w.add_joint(j) is j
    assert w.joints == [j]


def test_add_joint_rejects_dict():
    # Silent-acceptance bug class: dict slipping through crashes the solver
    # mid-step with a confusing AttributeError on .kind.
    w = World()
    with pytest.raises(TypeError, match="joint"):
        w.add_joint({"kind": "distance", "node_a": 0, "node_b": 1})  # type: ignore[arg-type]


def test_add_joint_rejects_none():
    w = World()
    with pytest.raises(TypeError, match="joint"):
        w.add_joint(None)  # type: ignore[arg-type]


def test_add_joint_rejects_string():
    w = World()
    with pytest.raises(TypeError, match="joint"):
        w.add_joint("distance")  # type: ignore[arg-type]


def test_add_joint_rejects_dangling_node_a():
    # Silent-acceptance bug class: a joint indexing past the node array
    # used to crash inside the XPBD kernel with a numpy IndexError instead
    # of failing at the add_joint authoring site.
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    j = JointSpec(kind="distance", node_a=5, node_b=1, rest_length=1.0)
    with pytest.raises(ValueError, match="node_a"):
        w.add_joint(j)


def test_add_joint_rejects_dangling_node_b():
    w = World()
    w.add_node((0.0, 0.0))
    w.add_node((1.0, 0.0))
    j = JointSpec(kind="distance", node_a=0, node_b=7, rest_length=1.0)
    with pytest.raises(ValueError, match="node_b"):
        w.add_joint(j)


# ---------------------------------------------------------------------------
# Smoke: validated World still composes a working scene end-to-end.
# ---------------------------------------------------------------------------


def test_validated_world_runs_a_full_scene():
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 4
    a = w.add_node((0.0, 1.0), mass=1.0)
    b = w.add_node((0.5, 1.0), mass=1.0)
    w.add_joint(JointSpec(
        kind="distance",
        node_a=a,
        node_b=b,
        rest_length=0.5,
        stiffness=1.0e5,
        damping=0.01,
    ))
    w.register_body(Body(
        kind="lattice",
        node_offset=a,
        node_count=2,
        label="pair",
    ))
    for _ in range(20):
        w.step(1.0 / 60.0)
    assert not np.isnan(w.positions).any()
    assert w.frame == 20
    # Distance constraint should hold rest length within solver tolerance.
    d = float(np.linalg.norm(w.positions[a] - w.positions[b]))
    assert math.isclose(d, 0.5, rel_tol=0.05)
