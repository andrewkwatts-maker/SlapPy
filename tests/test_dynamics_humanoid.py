"""Humanoid factory smoke + invariants.

Covers ``build_humanoid``, ``build_flesh_wrap``, ``place_feet_on_terrain``
against ``slappyengine.softbody.SoftBodyWorld`` — the same world type
the four humanoid examples and ``test_vis_humanoid_destruction.py`` use.
"""
from __future__ import annotations

import math

import numpy as np

from slappyengine.dynamics import (
    Humanoid,
    LAYER_BONE,
    LAYER_MUSCLE,
    LAYER_SKIN,
    build_humanoid,
    place_feet_on_terrain,
    build_flesh_wrap,
)
from slappyengine.softbody import SoftBodyWorld, step


def _bare_world() -> SoftBodyWorld:
    world = SoftBodyWorld()
    # Disable gravity / contact for kinematic IK tests; demos do the
    # same.
    world.config["floor_y"] = 100.0
    world.config["contact"]["enabled"] = False
    world.config["gravity"] = [0.0, 0.0]
    return world


def test_build_humanoid_returns_handle_with_13_bone_nodes():
    world = _bare_world()
    skel = build_humanoid(world, root_position=(0.0, 1.0))

    assert isinstance(skel, Humanoid)
    ns, ne = skel.node_slice
    # 15 = pelvis + neck + head + 3 arm × 2 + (hip + knee + ankle) × 2.
    assert ne - ns == 15, f"expected 15 bone nodes, got {ne - ns}"
    # Every named joint resolves to a valid index inside the slice.
    for name in ("pelvis", "neck", "head",
                 "shoulder_l", "elbow_l", "wrist_l",
                 "shoulder_r", "elbow_r", "wrist_r",
                 "hip_l", "knee_l", "ankle_l",
                 "hip_r", "knee_r", "ankle_r"):
        idx = getattr(skel, name)
        assert ns <= idx < ne, f"{name} idx {idx} outside skeleton slice"
    # All bone nodes carry layer 0.
    assert np.all(world.nodes.layer[ns:ne] == LAYER_BONE)
    # Head sits above pelvis (smaller y in engine convention).
    assert world.nodes.pos[skel.head, 1] < world.nodes.pos[skel.pelvis, 1]
    # Ankles sit below pelvis.
    assert world.nodes.pos[skel.ankle_l, 1] > world.nodes.pos[skel.pelvis, 1]
    assert world.nodes.pos[skel.ankle_r, 1] > world.nodes.pos[skel.pelvis, 1]


def test_humanoid_one_step_does_not_nan():
    world = _bare_world()
    build_humanoid(world, root_position=(0.0, 1.0))
    step(world)
    assert not np.isnan(world.nodes.pos).any()
    assert not np.isnan(world.nodes.vel).any()


def test_build_flesh_wrap_adds_muscle_and_skin_layers():
    world = _bare_world()
    skel = build_humanoid(world, root_position=(0.0, 1.0))
    bone_node_count = skel.node_slice[1] - skel.node_slice[0]
    beam_count_before = world.beams.count

    returned = build_flesh_wrap(
        world, skel,
        muscle_offset=0.10, skin_offset=0.18,
        muscle_stiffness=1.0e6, skin_stiffness=2.5e5,
        flesh_break_strain=0.18,
    )

    # build_flesh_wrap returns the same handle for chaining.
    assert returned is skel
    # Two flesh slices were recorded.
    assert set(skel.flesh_node_slices.keys()) == {"muscle", "skin"}
    # Each flesh layer has one node per bone node.
    for label in ("muscle", "skin"):
        fs, fe = skel.flesh_node_slices[label]
        assert fe - fs == bone_node_count, (
            f"layer {label!r} should have {bone_node_count} flesh nodes; got {fe - fs}"
        )
    # Muscle layer is layer 1, skin layer is layer 2.
    ms, me = skel.flesh_node_slices["muscle"]
    ss, se = skel.flesh_node_slices["skin"]
    assert np.all(world.nodes.layer[ms:me] == LAYER_MUSCLE)
    assert np.all(world.nodes.layer[ss:se] == LAYER_SKIN)
    # Beams grew by radial+tangential pairs per layer (2 layers × bones).
    assert world.beams.count > beam_count_before


def test_build_flesh_wrap_then_step_stays_finite():
    world = _bare_world()
    skel = build_humanoid(world, root_position=(0.0, 1.0))
    build_flesh_wrap(world, skel)
    for _ in range(5):
        step(world)
    assert not np.isnan(world.nodes.pos).any()


def test_place_feet_on_terrain_flat_floor_converges():
    world = _bare_world()
    skel = build_humanoid(world, root_position=(0.0, 1.5))

    floor_y = 3.5
    converged = place_feet_on_terrain(
        world, skel, lambda x: floor_y,
        pelvis_height_above_terrain=0.95,
    )

    assert converged, "flat-floor IK should converge"
    # Both ankles are on the floor (within tolerance).
    assert abs(float(world.nodes.pos[skel.ankle_l, 1]) - floor_y) < 0.01
    assert abs(float(world.nodes.pos[skel.ankle_r, 1]) - floor_y) < 0.01
    # Pelvis sits ~0.95 above the floor.
    pelvis_above = floor_y - float(world.nodes.pos[skel.pelvis, 1])
    assert abs(pelvis_above - 0.95) < 0.05


def test_place_feet_on_terrain_sinusoid_lands_both_feet():
    world = _bare_world()
    skel = build_humanoid(world, root_position=(-1.0, 1.5))

    def terrain(x: float) -> float:
        return 3.5 + 0.25 * math.sin(x * 1.2)

    place_feet_on_terrain(
        world, skel, terrain,
        pelvis_height_above_terrain=0.9,
        max_iterations=6,
    )
    # Each ankle should now be near the terrain height at its own x.
    for ankle in (skel.ankle_l, skel.ankle_r):
        x = float(world.nodes.pos[ankle, 0])
        y = float(world.nodes.pos[ankle, 1])
        assert abs(y - terrain(x)) < 0.02
