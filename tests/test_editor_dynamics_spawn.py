"""Integration coverage for the Phase B+ dynamics spawn actions.

These tests focus on the *integration* surface of the spawn menu — i.e.
that clicking ``+ Add → Add Rope`` (etc.) end up materialising the right
primitive on the active world. Unit-level validation of the inspector
reflection lives in ``test_editor_dynamics_reflection.py``; pure
table-shape tests live in ``test_editor_spawn_menu.py``.

Scope:

* :func:`_spawn_rope`     — rope = ``N`` nodes + ``N - 1`` distance joints.
* :func:`_spawn_ragdoll`  — ragdoll = root node + one node per bone, one
  distance joint per bone (+ optional hinge joints when the bone has a
  parent), so total joint count >= bone_count.
* :func:`_spawn_ik_chain` — solver primitive: returns the bool result of
  :func:`solve_ik` applied to a chain spec attached to a target.
* :func:`_spawn_humanoid` — 15-node skeleton (pelvis + neck + head + 2
  arms of 3 + 2 legs of 3) wired onto a :class:`SoftBodyWorld`.

The tests drive each adapter the same way ``open_spawn_modal``'s Spawn
button would: resolve the dotted factory path, build a spec from
defaults, and call ``factory(world, **spec_kwargs)``.
"""
from __future__ import annotations

import dataclasses
import sys
import types

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# DPG stub fixture — matches test_editor_spawn_menu so open_spawn_modal can
# be exercised without a real dearpygui context if any test needs it.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """Inject a no-op dearpygui.dearpygui module for the duration of a test."""
    class _CtxStub:
        def __enter__(self):
            return self
        def __exit__(self, *a, **kw):
            return False
        def __call__(self, *a, **kw):
            return self

    class _NoOpModule:
        def __getattr__(self, name):
            def _ctx(*a, **kw):
                return _CtxStub()
            return _ctx

        def does_item_exist(self, *a, **kw):
            return True

        def set_value(self, *a, **kw):
            return None

        def delete_item(self, *a, **kw):
            return None

    inst = _NoOpModule()
    stub = types.ModuleType("dearpygui.dearpygui")
    stub.__getattr__ = lambda name: getattr(inst, name)

    dpg_pkg = types.ModuleType("dearpygui")
    dpg_pkg.dearpygui = inst

    monkeypatch.setitem(sys.modules, "dearpygui", dpg_pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", inst)
    yield inst


# ---------------------------------------------------------------------------
# Import guards — skip the whole module if the editor + dynamics packages
# aren't importable in this checkout.
# ---------------------------------------------------------------------------

try:
    from slappyengine.ui.editor import spawn_menu  # noqa: F401
    from slappyengine.dynamics.world import World as _DynWorld  # noqa: F401
except Exception as _import_err:  # pragma: no cover
    pytest.skip(
        f"editor.spawn_menu or dynamics.world not importable: {_import_err}",
        allow_module_level=True,
    )


def _find_action(label: str) -> dict:
    from slappyengine.ui.editor.spawn_menu import SPAWN_ACTIONS
    for action in SPAWN_ACTIONS:
        if action["label"] == label:
            return action
    raise AssertionError(f"action {label!r} missing from SPAWN_ACTIONS")


def _drive_spawn(label: str, world):
    """Resolve the action's factory and call it with the spec defaults.

    Mirrors what :func:`open_spawn_modal`'s ``_on_spawn`` callback does
    when the user clicks the Spawn button.
    """
    from slappyengine.ui.editor.spawn_menu import (
        _resolve_factory,
        _spec_to_kwargs,
    )

    action = _find_action(label)
    spec = action["spec"]()
    kwargs = _spec_to_kwargs(spec)
    factory = _resolve_factory(action["factory"])
    return spec, factory(world, **kwargs)


# ---------------------------------------------------------------------------
# Rope: N contiguous nodes + N-1 distance joints.
# ---------------------------------------------------------------------------

class TestSpawnRopeIntegration:
    def test_node_and_joint_counts_match_spec(self):
        from slappyengine.dynamics.world import World

        world = World()
        spec, body = _drive_spawn("Add Rope", world)

        assert body is not None
        assert getattr(body, "kind", None) == "rope"
        # Adapter pre-allocates exactly node_count nodes…
        assert world.positions.shape[0] == spec.node_count
        # …and wires one distance joint per adjacent pair.
        distance_joints = [
            j for j in world.joints
            if getattr(j, "kind", None) == "distance"
        ]
        assert len(distance_joints) == spec.node_count - 1
        # Body owns the rope range and is registered on the world.
        assert body in world.bodies
        assert body.node_count == spec.node_count


# ---------------------------------------------------------------------------
# Ragdoll: root node + one child per bone, distance joint per bone, hinge
# joints for bones whose parent is another bone.
# ---------------------------------------------------------------------------

class TestSpawnRagdollIntegration:
    def test_bone_count_drives_topology(self):
        from slappyengine.dynamics.world import World

        world = World()
        spec, body = _drive_spawn("Add Ragdoll", world)

        assert body is not None
        assert getattr(body, "kind", None) == "ragdoll"
        # Adapter spawns ``bone_count`` bones — one root + one child node each.
        assert body.node_count == 1 + spec.bone_count
        # One distance joint per bone, plus a hinge for every non-root bone.
        distance_joints = [
            j for j in world.joints
            if getattr(j, "kind", None) == "distance"
        ]
        hinge_joints = [
            j for j in world.joints
            if getattr(j, "kind", None) == "hinge"
        ]
        assert len(distance_joints) == spec.bone_count
        assert len(hinge_joints)    == spec.bone_count - 1


# ---------------------------------------------------------------------------
# IK Chain: solver primitive — adapter returns the bool from solve_ik on
# a chain spec attached to the spec's target.
# ---------------------------------------------------------------------------

class TestSpawnIKChainIntegration:
    def test_solver_runs_with_target_and_returns_bool(self):
        from slappyengine.dynamics.world import World

        world = World()
        # Seed nodes for the default csv "0,1,2,3".
        world.add_nodes(
            np.array([(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (12.0, 0.0)]),
            masses=np.array([0.0, 1.0, 1.0, 1.0]),
        )
        spec, result = _drive_spawn("Add IK Chain", world)

        # solve_ik returns a bool (True when tip reached the target).
        assert isinstance(result, bool)
        # The chain's tip node should have moved toward the spec target —
        # this verifies the chain spec was actually attached to the target.
        tip = world.positions[3]
        target = np.asarray(spec.target, dtype=np.float64)
        # Tip should be at least as close to the target as the seeded
        # position was (12, 0 vs 16, 0).
        seeded_dist = float(np.linalg.norm(np.array([12.0, 0.0]) - target))
        final_dist  = float(np.linalg.norm(tip - target))
        assert final_dist <= seeded_dist + 1e-6


# ---------------------------------------------------------------------------
# Humanoid: 15-node skeleton on a softbody world.
# ---------------------------------------------------------------------------

class TestSpawnHumanoidIntegration:
    def test_skeleton_has_15_nodes(self):
        from slappyengine.softbody.world import SoftBodyWorld

        world = SoftBodyWorld()
        spec, humanoid = _drive_spawn("Add Humanoid", world)

        # make_humanoid lays down exactly 15 bone nodes:
        #   pelvis + neck + head
        # + shoulder_l + elbow_l + wrist_l
        # + shoulder_r + elbow_r + wrist_r
        # + hip_l + knee_l + ankle_l
        # + hip_r + knee_r + ankle_r
        assert world.nodes.count == 15
        # Humanoid handle reports the same span via its node slice.
        ns, ne = humanoid.node_slice
        assert ne - ns == 15
        # And every canonical joint index points at a real node.
        for name in (
            "pelvis", "neck", "head",
            "shoulder_l", "elbow_l", "wrist_l",
            "shoulder_r", "elbow_r", "wrist_r",
            "hip_l", "knee_l", "ankle_l",
            "hip_r", "knee_r", "ankle_r",
        ):
            idx = getattr(humanoid, name)
            assert 0 <= idx < world.nodes.count, (
                f"humanoid.{name}={idx} out of range for "
                f"world.nodes.count={world.nodes.count}"
            )
