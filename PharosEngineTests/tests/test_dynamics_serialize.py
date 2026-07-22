"""Round-trip serialisation tests for :mod:`pharos_engine.dynamics.serialize`.

Covers in-memory round trip, on-disk round trip, malformed-input rejection,
and post-roundtrip step determinism — the contract a game save needs to
honour to resume mid-frame without visible discontinuity.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.dynamics import (
    JointSpec,
    RopeSpec,
    World,
    build_rope,
    load_world,
    save_world,
    world_from_dict,
    world_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rope_world(node_count: int = 24) -> World:
    """Build a deterministic rope world for round-trip tests."""
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 8
    spec = RopeSpec(
        node_count=node_count,
        total_length=4.0,
        mass_per_node=0.05,
        stiffness=2.0e6,
        damping=0.05,
        anchor_a_pinned=True,
        anchor_b_pinned=True,
    )
    build_rope(spec, w, anchor_a=(-2.0, 5.0), anchor_b=(2.0, 5.0))
    # Run a few steps so positions / velocities diverge from rest.
    dt = 1.0 / 240.0
    for _ in range(10):
        w.step(dt)
    return w


def _states_match(a: World, b: World, tol: float = 1e-9) -> None:
    np.testing.assert_allclose(a.positions, b.positions, atol=tol)
    np.testing.assert_allclose(a.prev_positions, b.prev_positions, atol=tol)
    np.testing.assert_allclose(a.velocities, b.velocities, atol=tol)
    np.testing.assert_allclose(a.inv_masses, b.inv_masses, atol=tol)
    np.testing.assert_allclose(a.gravity, b.gravity, atol=tol)
    assert a.solver_iterations == b.solver_iterations
    assert a.warn_overdamping == b.warn_overdamping
    assert a.frame == b.frame
    assert len(a.joints) == len(b.joints)
    assert len(a.bodies) == len(b.bodies)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_world_to_dict_then_from_dict_round_trip():
    """24-node rope: serialise → deserialise; state matches within 1e-9."""
    w = _make_rope_world(24)
    payload = world_to_dict(w)
    # Sanity: payload is JSON-serialisable.
    s = json.dumps(payload)
    assert isinstance(s, str)
    w2 = world_from_dict(json.loads(s))
    _states_match(w, w2)


def test_save_and_load_round_trip_to_disk(tmp_path: Path):
    w = _make_rope_world(24)
    p = tmp_path / "world.json"
    save_world(w, p)
    assert p.is_file()
    w2 = load_world(p)
    _states_match(w, w2)


def test_save_world_rejects_non_json_extension(tmp_path: Path):
    w = _make_rope_world(8)
    with pytest.raises(ValueError, match="must end with .json"):
        save_world(w, tmp_path / "world.txt")


def test_load_world_rejects_non_json_extension(tmp_path: Path):
    p = tmp_path / "world.txt"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="must end with .json"):
        load_world(p)


def test_load_world_rejects_malformed_json(tmp_path: Path):
    p = tmp_path / "garbage.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_world(p)


def test_world_from_dict_rejects_non_dict():
    with pytest.raises(ValueError, match="expected a dict"):
        world_from_dict([1, 2, 3])  # type: ignore[arg-type]


def test_world_from_dict_rejects_empty_dict():
    with pytest.raises(ValueError, match="missing required keys"):
        world_from_dict({})


def test_world_from_dict_rejects_corrupt_marker():
    with pytest.raises(ValueError, match="missing required keys"):
        world_from_dict({"corrupt": True})


def test_world_from_dict_rejects_missing_required_keys():
    w = _make_rope_world(8)
    payload = world_to_dict(w)
    del payload["velocities"]
    with pytest.raises(ValueError, match="missing required keys"):
        world_from_dict(payload)


def test_world_from_dict_rejects_wrong_array_shape():
    w = _make_rope_world(8)
    payload = world_to_dict(w)
    # Corrupt the positions array shape so it claims to be (N, 3).
    bad = np.zeros((8, 3), dtype=np.float64)
    from pharos_engine.dynamics.serialize import _encode_array
    payload["positions"] = _encode_array(bad)
    with pytest.raises(ValueError, match=r"positions must be \(N, 2\)"):
        world_from_dict(payload)


def test_world_from_dict_rejects_mismatched_array_length():
    w = _make_rope_world(8)
    payload = world_to_dict(w)
    from pharos_engine.dynamics.serialize import _encode_array
    payload["inv_masses"] = _encode_array(np.ones((99,), dtype=np.float64))
    with pytest.raises(
        ValueError, match="inv_masses shape"
    ):
        world_from_dict(payload)


def test_world_from_dict_rejects_unknown_joint_kind():
    w = _make_rope_world(8)
    payload = world_to_dict(w)
    payload["joints"][0]["kind"] = "bogus"
    with pytest.raises(ValueError, match="unknown kind"):
        world_from_dict(payload)


def test_world_from_dict_rejects_bad_schema_version():
    w = _make_rope_world(4)
    payload = world_to_dict(w)
    payload["schema_version"] = 9999
    with pytest.raises(ValueError, match="schema_version"):
        world_from_dict(payload)


def test_one_step_post_roundtrip_matches_original():
    """Step both worlds once after round-trip; positions agree to 1e-9."""
    w = _make_rope_world(24)
    w2 = world_from_dict(world_to_dict(w))
    dt = 1.0 / 240.0
    w.step(dt)
    w2.step(dt)
    err = float(np.max(np.abs(w.positions - w2.positions)))
    assert err <= 1e-9, f"post-roundtrip step error {err} exceeds 1e-9"
    np.testing.assert_allclose(w.velocities, w2.velocities, atol=1e-9)


def test_joint_break_force_preserved():
    """A finite break_force survives a JSON round trip exactly."""
    w = World()
    w.add_node((0.0, 0.0), mass=0.0)
    w.add_node((1.0, 0.0), mass=1.0)
    j = JointSpec(
        kind="spring",
        node_a=0,
        node_b=1,
        rest_length=1.0,
        stiffness=1.0e5,
        damping=0.1,
        break_force=10.0,
    )
    w.add_joint(j)
    w2 = world_from_dict(world_to_dict(w))
    assert len(w2.joints) == 1
    j2 = w2.joints[0]
    assert j2.break_force == 10.0
    assert isinstance(j2.break_force, float)


def test_joint_break_force_infinity_preserved():
    """Default +inf break_force survives JSON round trip."""
    w = World()
    w.add_node((0.0, 0.0), mass=1.0)
    w.add_node((1.0, 0.0), mass=1.0)
    j = JointSpec(
        kind="distance",
        node_a=0,
        node_b=1,
        rest_length=1.0,
    )
    assert math.isinf(j.break_force)
    w.add_joint(j)
    w2 = world_from_dict(world_to_dict(w))
    assert math.isinf(w2.joints[0].break_force)


def test_world_with_motor_round_trip():
    """A motor joint's params dict (hub, axis, target_omega, max_torque)
    round-trips with no precision loss."""
    w = World(gravity=(0.0, 0.0))
    hub = w.add_node((0.0, 0.0), mass=0.0)
    rim_a = w.add_node((1.0, 0.0), mass=1.0)
    rim_b = w.add_node((-1.0, 0.0), mass=1.0)
    joint = JointSpec(
        kind="motor",
        node_a=rim_a,
        node_b=rim_b,
        rest_length=1.0,
        stiffness=1.0e5,
        damping=0.05,
        params={
            "hub": hub,
            "axis": (0.0, 1.0),
            "target_omega": 6.2831853,
            "max_torque": 25.0,
        },
    )
    w.add_joint(joint)
    payload = json.dumps(world_to_dict(w))
    w2 = world_from_dict(json.loads(payload))
    j2 = w2.joints[0]
    assert j2.kind == "motor"
    assert j2.params["hub"] == hub
    assert j2.params["target_omega"] == pytest.approx(6.2831853, abs=1e-12)
    assert j2.params["max_torque"] == 25.0
    # axis came through as a 2-list.
    axis = j2.params["axis"]
    assert list(axis) == [0.0, 1.0]


def test_body_metadata_preserved():
    """Body kind / label / node_offset / node_count round-trip."""
    w = _make_rope_world(8)
    payload = world_to_dict(w)
    w2 = world_from_dict(payload)
    assert len(w.bodies) == len(w2.bodies)
    for ba, bb in zip(w.bodies, w2.bodies):
        assert ba.kind == bb.kind
        assert ba.label == bb.label
        assert ba.node_offset == bb.node_offset
        assert ba.node_count == bb.node_count


def test_save_world_rejects_non_world():
    with pytest.raises(TypeError, match="expected a World"):
        save_world({"not": "a world"}, "out.json")  # type: ignore[arg-type]


def test_world_to_dict_rejects_non_world():
    with pytest.raises(TypeError, match="expected a World"):
        world_to_dict({"not": "a world"})  # type: ignore[arg-type]
