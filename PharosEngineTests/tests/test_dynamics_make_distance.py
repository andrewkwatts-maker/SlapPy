"""Regression coverage for ``make_distance`` + ``resolve_joint_specs``.

Both helpers were briefly dropped from ``pharos_engine.dynamics``'s public
API and ``examples/ik_skeleton_demo.py`` regressed to an import error in
the 2026-06-01 examples-smoke audit (``docs/examples_smoke_2026_06_01.md``,
commit ``106faea``). These tests pin both:

1. ``make_distance`` is the rigid-link sibling of ``make_spring`` /
   ``make_motor`` and yields a ``JointSpec(kind='distance')`` with the
   author-tuned defaults the IK demo relies on.
2. ``resolve_joint_specs`` is the batch-install helper that routes a list
   of specs into either a dynamics ``World`` (adds them as joints) or a
   softbody ``SoftBodyWorld`` duck (appends distance-flavoured specs to
   the beam SoA).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from pharos_engine.dynamics import (
    JointSpec,
    World,
    make_distance,
    resolve_joint_specs,
)


# ---------------------------------------------------------------------------
# make_distance
# ---------------------------------------------------------------------------

def test_make_distance_returns_distance_jointspec():
    j = make_distance(0, 1, rest_length=2.0)
    assert isinstance(j, JointSpec)
    assert j.kind == "distance"
    assert j.node_a == 0
    assert j.node_b == 1
    assert j.rest_length == pytest.approx(2.0)
    # Defaults match make_spring's siblings: stiff rigid-link defaults.
    assert j.stiffness == pytest.approx(1.0e9)
    assert j.damping == pytest.approx(0.02)
    assert j.params == {}


def test_make_distance_accepts_overrides():
    j = make_distance(3, 7, rest_length=0.5, stiffness=1.0e10, damping=0.05)
    assert j.node_a == 3
    assert j.node_b == 7
    assert j.stiffness == pytest.approx(1.0e10)
    assert j.damping == pytest.approx(0.05)


@pytest.mark.parametrize(
    "kwargs, exc, match",
    [
        ({"node_a": "bad", "node_b": 1, "rest_length": 1.0}, TypeError, "node_a"),
        ({"node_a": -1, "node_b": 1, "rest_length": 1.0}, ValueError, "non-negative"),
        ({"node_a": 0, "node_b": 0, "rest_length": 1.0}, ValueError, "differ"),
        ({"node_a": 0, "node_b": 1, "rest_length": -0.1}, ValueError, "rest_length"),
        ({"node_a": 0, "node_b": 1, "rest_length": 1.0, "stiffness": 0.0},
         ValueError, "stiffness"),
        ({"node_a": 0, "node_b": 1, "rest_length": 1.0, "damping": 1.5},
         ValueError, "damping"),
        ({"node_a": 0, "node_b": 1, "rest_length": math.inf},
         ValueError, "rest_length"),
    ],
)
def test_make_distance_validates_inputs(kwargs, exc, match):
    with pytest.raises(exc, match=match):
        make_distance(**kwargs)


def test_make_distance_holds_segment_under_step():
    # Two nodes pulled apart heal back to the rest length under XPBD.
    w = World(gravity=(0.0, 0.0))
    w.add_node((0.0, 0.0), mass=1.0)
    w.add_node((2.0, 0.0), mass=1.0)
    w.add_joint(make_distance(0, 1, rest_length=1.0))
    for _ in range(40):
        w.step(1.0 / 60.0)
    d = float(np.linalg.norm(w.positions[1] - w.positions[0]))
    assert d == pytest.approx(1.0, abs=2e-3)


# ---------------------------------------------------------------------------
# resolve_joint_specs — dynamics.World path
# ---------------------------------------------------------------------------

def test_resolve_joint_specs_appends_to_world():
    w = World(gravity=(0.0, 0.0))
    for x in range(4):
        w.add_node((float(x), 0.0), mass=1.0)
    specs = [make_distance(i, i + 1, rest_length=1.0) for i in range(3)]
    handles = resolve_joint_specs(w, specs)
    assert handles == [0, 1, 2]
    assert len(w.joints) == 3
    # The installed joints are the exact spec objects, in order.
    assert w.joints[0] is specs[0]
    assert w.joints[2] is specs[2]


def test_resolve_joint_specs_world_can_step_after_install():
    w = World(gravity=(0.0, 0.0))
    w.add_node((0.0, 0.0), mass=0.0)  # pinned
    w.add_node((1.5, 0.0), mass=1.0)
    handles = resolve_joint_specs(
        w, [make_distance(0, 1, rest_length=1.0, stiffness=1.0e10, damping=0.0)]
    )
    assert handles == [0]
    for _ in range(60):
        w.step(1.0 / 60.0)
    d = float(np.linalg.norm(w.positions[1] - w.positions[0]))
    assert d == pytest.approx(1.0, abs=5e-3)


# ---------------------------------------------------------------------------
# resolve_joint_specs — softbody.SoftBodyWorld duck path
# ---------------------------------------------------------------------------

def test_resolve_joint_specs_routes_distance_specs_into_softbody_beams():
    # The IK skeleton demo wires its rigid bones via this code path.
    sb = pytest.importorskip("pharos_engine.softbody")
    world = sb.SoftBodyWorld()
    pos = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]], dtype=np.float32)
    mass = np.full(3, 1.0, dtype=np.float32)
    damping = np.full(3, 0.1, dtype=np.float32)
    fixed = np.array([True, False, False])
    world.nodes.append(pos=pos, mass=mass, body_id=0, layer=2,
                       damping=damping, fixed=fixed)
    specs = [make_distance(0, 1, rest_length=1.0),
             make_distance(1, 2, rest_length=1.0)]
    handles = resolve_joint_specs(world, specs)
    # Two beams appended, in input order.
    assert handles == [0, 1]
    assert world.beams.count == 2
    assert int(world.beams.node_a[0]) == 0 and int(world.beams.node_b[0]) == 1
    assert int(world.beams.node_a[1]) == 1 and int(world.beams.node_b[1]) == 2
    assert float(world.beams.rest_length[0]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# resolve_joint_specs — input validation
# ---------------------------------------------------------------------------

def test_resolve_joint_specs_rejects_non_list():
    w = World()
    with pytest.raises(TypeError, match="list"):
        resolve_joint_specs(w, "not-a-list")  # type: ignore[arg-type]


def test_resolve_joint_specs_rejects_non_spec_entries():
    w = World()
    with pytest.raises(TypeError, match="JointSpec"):
        resolve_joint_specs(w, [object()])  # type: ignore[list-item]


def test_resolve_joint_specs_rejects_unknown_world():
    class Bare:
        pass

    with pytest.raises(TypeError, match="world"):
        resolve_joint_specs(Bare(), [make_distance(0, 1, rest_length=1.0)])
