"""Humanoid skeleton + flesh wrap + foot-IK factories.

This module sits on top of the :class:`slappyengine.softbody.SoftBodyWorld`
SoA arrays (``world.nodes``, ``world.beams``) rather than the slim
:class:`slappyengine.dynamics.World` substrate, because the humanoid demos
and the layered-destruction visual test all rely on the softbody layer
fields (``world.nodes.layer``, ``world.beams.broken``, ``break_strain``,
etc.). The :class:`Humanoid` handle exposes named node indices for the
canonical anatomy joints (pelvis, head, ankles, knees, shoulders, ...) so
demo code can reach into the SoA arrays without re-deriving offsets.

Coordinate convention: y increases *downward* (the engine convention used
by every other softbody demo). ``root_position`` is the pelvis; the head
sits above (smaller y) and the ankles sit below (larger y).

Three public entry points:

* :func:`make_humanoid` — builds a 13-node skeleton: pelvis + neck + head +
  shoulder_L + elbow_L + wrist_L + shoulder_R + elbow_R + wrist_R + knee_L
  + ankle_L + knee_R + ankle_R. Bone segments are XPBD distance beams; all
  bone nodes are written to layer 0 so downstream destruction code can
  count cuts per layer.
* :func:`wrap_in_flesh` — wraps the skeleton in two flesh layers (muscle,
  skin) of distance beams. Each bone node is given a paired muscle node
  (layer 1) and a paired skin node (layer 2), tied back to the skeleton
  with breakable radial beams.
* :func:`place_feet_on_terrain` — analytic 2-bone IK for each leg so the
  ankles sit on the supplied terrain. Pelvis vertical anchor is set
  relative to the *lower* foot's terrain height; legs then bend at the
  knee to plant both ankles on the surface. Falls back to the package-
  level :func:`solve_ik` CCD solver if the analytic solution overshoots.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


# Canonical layer indices (also written into ``world.nodes.layer``).
LAYER_BONE = 0
LAYER_MUSCLE = 1
LAYER_SKIN = 2


@dataclass
class Humanoid:
    """Named handle returned by :func:`make_humanoid`.

    All attributes named after a body part hold the absolute node index of
    that joint inside ``world.nodes``. ``node_slice`` is the half-open
    ``(start, end)`` range covering every bone node owned by this skeleton
    (used by demos to translate the whole figure with a single slice).

    ``flesh_node_slices`` is populated by :func:`wrap_in_flesh` with one
    entry per flesh layer ("muscle", "skin") so callers can later iterate
    or render flesh layers independently.
    """
    pelvis: int = -1
    neck: int = -1
    head: int = -1
    shoulder_l: int = -1
    elbow_l: int = -1
    wrist_l: int = -1
    shoulder_r: int = -1
    elbow_r: int = -1
    wrist_r: int = -1
    hip_l: int = -1
    knee_l: int = -1
    ankle_l: int = -1
    hip_r: int = -1
    knee_r: int = -1
    ankle_r: int = -1
    node_slice: tuple[int, int] = (0, 0)
    beam_slice: tuple[int, int] = (0, 0)
    body_id: int = 0
    bone_lengths: dict[str, float] = field(default_factory=dict)
    flesh_node_slices: dict[str, tuple[int, int]] = field(default_factory=dict)
    flesh_beam_slices: dict[str, tuple[int, int]] = field(default_factory=dict)

    # Convenience aliases — examples reference ``ankle_l`` / ``ankle_r``
    # but also ``foot_l`` / ``foot_r``. Keep them in sync via properties.
    @property
    def foot_l(self) -> int:
        return self.ankle_l

    @property
    def foot_r(self) -> int:
        return self.ankle_r


# Default anatomical proportions (in metres). Tuned for a ~1.7 m figure
# with the pelvis at the canonical (0, 1) anchor used by every demo.
_DEFAULT_PROPORTIONS: dict[str, float] = {
    "torso_length": 0.45,        # pelvis -> neck
    "neck_length": 0.08,         # neck -> head base
    "head_length": 0.18,         # head height
    "shoulder_offset": 0.18,     # neck -> shoulder horizontal half-width
    "upper_arm_length": 0.30,
    "forearm_length": 0.28,
    "hip_offset": 0.12,          # pelvis -> hip horizontal half-width
    "upper_leg_length": 0.50,
    "lower_leg_length": 0.50,
}


def _append_skeleton_node(
    world,
    pos: tuple[float, float],
    mass: float,
    body_id: int,
    damping: float,
) -> int:
    """Append a single bone node and return its absolute index."""
    arr_pos = np.asarray([pos], dtype=np.float32)
    arr_mass = np.asarray([mass], dtype=np.float32)
    arr_damp = np.asarray([damping], dtype=np.float32)
    start = world.nodes.append(
        arr_pos, arr_mass, body_id=body_id, layer=LAYER_BONE,
        damping=arr_damp,
    )
    return int(start)


def _append_beams(
    world,
    pairs: list[tuple[int, int]],
    body_id: int,
    *,
    stiffness: float,
    damping: float,
    break_strain: float,
) -> tuple[int, int]:
    """Append distance beams; returns ``(beam_start, beam_end)``."""
    if not pairs:
        return (world.beams.count, world.beams.count)
    a = np.asarray([p[0] for p in pairs], dtype=np.uint32)
    b = np.asarray([p[1] for p in pairs], dtype=np.uint32)
    rest = np.linalg.norm(
        world.nodes.pos[a.astype(np.int64)]
        - world.nodes.pos[b.astype(np.int64)],
        axis=1,
    ).astype(np.float32)
    n = a.shape[0]
    start = world.beams.append(
        a, b, rest,
        np.full(n, stiffness, dtype=np.float32),
        np.full(n, damping, dtype=np.float32),
        np.full(n, break_strain, dtype=np.float32),
        body_id=body_id,
        yield_strain=np.full(n, 0.0, dtype=np.float32),
        plasticity_rate=np.full(n, 0.0, dtype=np.float32),
    )
    return int(start), world.beams.count


def make_humanoid(
    world,
    root_position: tuple[float, float] = (0.0, 1.0),
    *,
    proportions: dict[str, float] | None = None,
    bone_mass: float = 1.0,
    head_mass: float = 1.5,
    bone_stiffness: float = 5.0e6,
    bone_damping: float = 0.05,
    bone_break_strain: float = 0.25,
) -> Humanoid:
    """Spawn a 13-node humanoid skeleton in ``world``.

    The skeleton uses 13 bone nodes (pelvis + neck + head + 2*(shoulder,
    elbow, wrist) + 2*(hip, knee, ankle)) connected by rigid distance
    beams. All nodes are written to layer 0 so layered-destruction tests
    can distinguish "bone cuts" from flesh cuts after
    :func:`wrap_in_flesh`.

    ``proportions`` overrides the default anatomical bone lengths; pass a
    partial dict to tweak (e.g. ``{"head_length": 0.22}``) — keys not
    present fall back to defaults.

    The returned :class:`Humanoid` exposes one attribute per joint
    (``pelvis``, ``head``, ``ankle_l``, …) holding the absolute node
    index inside ``world.nodes``.
    """
    if not hasattr(world, "nodes") or not hasattr(world, "beams"):
        raise TypeError(
            f"make_humanoid: world must expose .nodes / .beams SoA arrays; "
            f"got {type(world).__name__}"
        )

    px, py = float(root_position[0]), float(root_position[1])
    props = dict(_DEFAULT_PROPORTIONS)
    if proportions:
        props.update({k: float(v) for k, v in proportions.items()})

    body_id = world.next_body_id()
    node_start = world.nodes.count

    # Anchor positions (y grows downward; head is above pelvis -> smaller y).
    torso_top_y = py - props["torso_length"]
    head_base_y = torso_top_y - props["neck_length"]
    head_top_y = head_base_y - props["head_length"]

    pelvis = _append_skeleton_node(world, (px, py), bone_mass, body_id, bone_damping)
    neck = _append_skeleton_node(world, (px, torso_top_y), bone_mass, body_id, bone_damping)
    head = _append_skeleton_node(world, (px, head_top_y), head_mass, body_id, bone_damping)

    # Arms.
    shoulder_l = _append_skeleton_node(
        world, (px - props["shoulder_offset"], torso_top_y),
        bone_mass, body_id, bone_damping,
    )
    elbow_l = _append_skeleton_node(
        world,
        (px - props["shoulder_offset"], torso_top_y + props["upper_arm_length"]),
        bone_mass, body_id, bone_damping,
    )
    wrist_l = _append_skeleton_node(
        world,
        (px - props["shoulder_offset"],
         torso_top_y + props["upper_arm_length"] + props["forearm_length"]),
        bone_mass, body_id, bone_damping,
    )
    shoulder_r = _append_skeleton_node(
        world, (px + props["shoulder_offset"], torso_top_y),
        bone_mass, body_id, bone_damping,
    )
    elbow_r = _append_skeleton_node(
        world,
        (px + props["shoulder_offset"], torso_top_y + props["upper_arm_length"]),
        bone_mass, body_id, bone_damping,
    )
    wrist_r = _append_skeleton_node(
        world,
        (px + props["shoulder_offset"],
         torso_top_y + props["upper_arm_length"] + props["forearm_length"]),
        bone_mass, body_id, bone_damping,
    )

    # Legs.
    hip_l_y = py
    knee_y = py + props["upper_leg_length"]
    ankle_y = knee_y + props["lower_leg_length"]

    # The pelvis itself is the structural hip anchor; for IK we want a
    # *distinct* hip node so the upper-leg bone can rotate independently
    # of the pelvis-torso chain. Spawn hip nodes coincident with the
    # pelvis x-offset.
    hip_l = _append_skeleton_node(
        world, (px - props["hip_offset"], hip_l_y),
        bone_mass, body_id, bone_damping,
    )
    knee_l = _append_skeleton_node(
        world, (px - props["hip_offset"], knee_y),
        bone_mass, body_id, bone_damping,
    )
    ankle_l = _append_skeleton_node(
        world, (px - props["hip_offset"], ankle_y),
        bone_mass, body_id, bone_damping,
    )
    hip_r = _append_skeleton_node(
        world, (px + props["hip_offset"], hip_l_y),
        bone_mass, body_id, bone_damping,
    )
    knee_r = _append_skeleton_node(
        world, (px + props["hip_offset"], knee_y),
        bone_mass, body_id, bone_damping,
    )
    ankle_r = _append_skeleton_node(
        world, (px + props["hip_offset"], ankle_y),
        bone_mass, body_id, bone_damping,
    )

    node_end = world.nodes.count

    # Wire bone beams. Each pair is a rigid distance constraint; the rest
    # length is computed from the spawned node positions.
    bone_pairs: list[tuple[int, int]] = [
        # Spine.
        (pelvis, neck), (neck, head),
        # Pelvis girdle (rigid triangle so the hips don't drift apart).
        (pelvis, hip_l), (pelvis, hip_r), (hip_l, hip_r),
        # Shoulder girdle.
        (neck, shoulder_l), (neck, shoulder_r), (shoulder_l, shoulder_r),
        # Arms.
        (shoulder_l, elbow_l), (elbow_l, wrist_l),
        (shoulder_r, elbow_r), (elbow_r, wrist_r),
        # Legs.
        (hip_l, knee_l), (knee_l, ankle_l),
        (hip_r, knee_r), (knee_r, ankle_r),
    ]
    beam_start, beam_end = _append_beams(
        world, bone_pairs, body_id,
        stiffness=bone_stiffness, damping=bone_damping,
        break_strain=bone_break_strain,
    )

    # Cache rest lengths so place_feet_on_terrain can do analytic 2-bone
    # IK without re-walking the beam array.
    pos = world.nodes.pos
    bone_lengths = {
        "upper_leg_l": float(np.linalg.norm(pos[knee_l] - pos[hip_l])),
        "lower_leg_l": float(np.linalg.norm(pos[ankle_l] - pos[knee_l])),
        "upper_leg_r": float(np.linalg.norm(pos[knee_r] - pos[hip_r])),
        "lower_leg_r": float(np.linalg.norm(pos[ankle_r] - pos[knee_r])),
        "torso": float(np.linalg.norm(pos[neck] - pos[pelvis])),
        "neck": float(np.linalg.norm(pos[head] - pos[neck])),
        "upper_arm_l": float(np.linalg.norm(pos[elbow_l] - pos[shoulder_l])),
        "forearm_l": float(np.linalg.norm(pos[wrist_l] - pos[elbow_l])),
        "upper_arm_r": float(np.linalg.norm(pos[elbow_r] - pos[shoulder_r])),
        "forearm_r": float(np.linalg.norm(pos[wrist_r] - pos[elbow_r])),
    }

    return Humanoid(
        pelvis=pelvis, neck=neck, head=head,
        shoulder_l=shoulder_l, elbow_l=elbow_l, wrist_l=wrist_l,
        shoulder_r=shoulder_r, elbow_r=elbow_r, wrist_r=wrist_r,
        hip_l=hip_l, knee_l=knee_l, ankle_l=ankle_l,
        hip_r=hip_r, knee_r=knee_r, ankle_r=ankle_r,
        node_slice=(node_start, node_end),
        beam_slice=(beam_start, beam_end),
        body_id=body_id,
        bone_lengths=bone_lengths,
    )


def _wrap_one_layer(
    world,
    humanoid: Humanoid,
    *,
    offset: float,
    layer_id: int,
    stiffness: float,
    damping: float,
    break_strain: float,
    label: str,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Spawn one flesh layer around the bone skeleton.

    For every bone node, we add a paired flesh node displaced laterally
    by ``offset`` (alternating sign so successive flesh nodes don't pile
    up on the same side — gives the silhouette some width). Each flesh
    node is tied back to its bone node by a radial breakable beam, and
    adjacent flesh nodes get a tangential ring beam so the layer behaves
    like a continuous shell.
    """
    ns, ne = humanoid.node_slice
    bone_indices = list(range(ns, ne))
    if not bone_indices:
        return ((world.nodes.count, world.nodes.count),
                (world.beams.count, world.beams.count))

    # Offset every flesh node perpendicular to the local "vertical" — for
    # the standing pose this is purely horizontal. Alternate sign so the
    # layer wraps both sides of each bone.
    bone_pos = world.nodes.pos[bone_indices].astype(np.float32)
    n = len(bone_indices)
    signs = np.where(np.arange(n) % 2 == 0, 1.0, -1.0).astype(np.float32)
    flesh_pos = bone_pos.copy()
    flesh_pos[:, 0] += signs * float(offset)

    mass = np.full(n, 0.25, dtype=np.float32)
    damp = np.full(n, damping, dtype=np.float32)
    flesh_start = world.nodes.append(
        flesh_pos, mass, body_id=humanoid.body_id, layer=layer_id,
        damping=damp,
    )
    flesh_indices = list(range(flesh_start, flesh_start + n))
    flesh_end = world.nodes.count

    # Radial beams: bone <-> flesh, breakable.
    radial_pairs = list(zip(bone_indices, flesh_indices))
    # Tangential beams: flesh[i] <-> flesh[i+1] (ring within layer).
    tangent_pairs = list(zip(flesh_indices[:-1], flesh_indices[1:]))

    beam_start = world.beams.count
    _append_beams(
        world, radial_pairs, humanoid.body_id,
        stiffness=stiffness, damping=damping, break_strain=break_strain,
    )
    _append_beams(
        world, tangent_pairs, humanoid.body_id,
        stiffness=stiffness * 0.5, damping=damping,
        break_strain=break_strain,
    )
    beam_end = world.beams.count

    humanoid.flesh_node_slices[label] = (flesh_start, flesh_end)
    humanoid.flesh_beam_slices[label] = (beam_start, beam_end)
    return (flesh_start, flesh_end), (beam_start, beam_end)


def wrap_in_flesh(
    world,
    humanoid: Humanoid,
    *,
    muscle_offset: float = 0.10,
    skin_offset: float = 0.18,
    muscle_stiffness: float = 1.0e6,
    skin_stiffness: float = 2.5e5,
    muscle_damping: float = 0.05,
    skin_damping: float = 0.05,
    flesh_break_strain: float = 0.18,
) -> Humanoid:
    """Wrap a humanoid skeleton in muscle (layer 1) + skin (layer 2) shells.

    Each shell adds one flesh node per bone node, tied back to the
    skeleton with breakable radial beams plus tangential ring beams
    within the shell. The humanoid handle is updated in place with the
    new flesh slices (``humanoid.flesh_node_slices``); the function also
    returns the humanoid for chaining.
    """
    if not hasattr(world, "nodes") or not hasattr(world, "beams"):
        raise TypeError(
            f"wrap_in_flesh: world must expose .nodes / .beams SoA arrays; "
            f"got {type(world).__name__}"
        )
    if not isinstance(humanoid, Humanoid):
        raise TypeError(
            f"wrap_in_flesh: humanoid must be a Humanoid; "
            f"got {type(humanoid).__name__}"
        )

    _wrap_one_layer(
        world, humanoid,
        offset=muscle_offset, layer_id=LAYER_MUSCLE,
        stiffness=muscle_stiffness, damping=muscle_damping,
        break_strain=flesh_break_strain,
        label="muscle",
    )
    _wrap_one_layer(
        world, humanoid,
        offset=skin_offset, layer_id=LAYER_SKIN,
        stiffness=skin_stiffness, damping=skin_damping,
        break_strain=flesh_break_strain * 0.6,  # skin tears easier
        label="skin",
    )
    return humanoid


def _solve_2bone_ik(
    world,
    hip_idx: int,
    knee_idx: int,
    ankle_idx: int,
    target: tuple[float, float],
    upper_len: float,
    lower_len: float,
    knee_bends_forward: bool = True,
) -> None:
    """Place hip→knee→ankle so the ankle hits ``target`` (analytic IK).

    Standard law-of-cosines 2-bone IK. If the target is out of reach,
    the chain is straightened toward it. ``knee_bends_forward`` flips
    the elbow/knee solution between the two valid bends.
    """
    hip = world.nodes.pos[hip_idx].astype(np.float64)
    tgt = np.asarray(target, dtype=np.float64)
    delta = tgt - hip
    dist = float(np.linalg.norm(delta))
    L1 = float(upper_len)
    L2 = float(lower_len)
    chain_max = L1 + L2 - 1e-4
    if dist > chain_max:
        # Out of reach: straighten the leg toward the target.
        if dist < 1e-6:
            return
        d_hat = delta / dist
        world.nodes.pos[knee_idx] = (hip + d_hat * L1).astype(np.float32)
        world.nodes.pos[ankle_idx] = (hip + d_hat * (L1 + L2)).astype(np.float32)
        world.nodes.prev_pos[knee_idx] = world.nodes.pos[knee_idx]
        world.nodes.prev_pos[ankle_idx] = world.nodes.pos[ankle_idx]
        return

    # Direction from hip to target.
    d_hat = delta / max(dist, 1e-9)
    # Cosine of the hip angle (between upper leg and hip→ankle axis).
    cos_hip = (L1 * L1 + dist * dist - L2 * L2) / (2.0 * L1 * dist)
    cos_hip = float(np.clip(cos_hip, -1.0, 1.0))
    sin_hip = math.sqrt(max(0.0, 1.0 - cos_hip * cos_hip))
    if not knee_bends_forward:
        sin_hip = -sin_hip
    # Perpendicular direction (rotate d_hat by 90 deg CCW).
    perp = np.array([-d_hat[1], d_hat[0]])
    knee_pos = hip + L1 * (cos_hip * d_hat + sin_hip * perp)
    world.nodes.pos[knee_idx] = knee_pos.astype(np.float32)
    world.nodes.pos[ankle_idx] = np.asarray(target, dtype=np.float32)
    world.nodes.prev_pos[knee_idx] = world.nodes.pos[knee_idx]
    world.nodes.prev_pos[ankle_idx] = world.nodes.pos[ankle_idx]


def place_feet_on_terrain(
    world,
    humanoid: Humanoid,
    terrain_height_fn: Callable[[float], float],
    *,
    pelvis_height_above_terrain: float = 0.9,
    max_iterations: int = 4,
    tolerance: float = 0.005,
) -> bool:
    """Adjust pelvis + legs so both ankles plant on the terrain surface.

    The pelvis is first translated vertically so it sits
    ``pelvis_height_above_terrain`` above the *higher* foot's terrain
    sample (so neither leg has to overextend). Then both legs are solved
    with analytic 2-bone IK toward the terrain height directly beneath
    each ankle's current x position.

    The translation also shifts the upper body (head, arms) by the same
    delta so the skeleton stays articulated. Returns ``True`` when both
    ankles end up within ``tolerance`` of the terrain.

    For the 2D engine convention (y increases downward) "above the
    terrain" means a smaller y. ``terrain_height_fn(x)`` returns the
    terrain's y at horizontal position ``x``.
    """
    if not hasattr(world, "nodes"):
        raise TypeError(
            f"place_feet_on_terrain: world must expose .nodes SoA arrays; "
            f"got {type(world).__name__}"
        )
    if not isinstance(humanoid, Humanoid):
        raise TypeError(
            f"place_feet_on_terrain: humanoid must be a Humanoid; "
            f"got {type(humanoid).__name__}"
        )

    converged = False
    for _ in range(int(max_iterations)):
        ankle_l_x = float(world.nodes.pos[humanoid.ankle_l, 0])
        ankle_r_x = float(world.nodes.pos[humanoid.ankle_r, 0])
        terrain_l = float(terrain_height_fn(ankle_l_x))
        terrain_r = float(terrain_height_fn(ankle_r_x))
        # The "higher" foot is the one with smaller y (further up). Anchor
        # the pelvis to its terrain height so the other leg can reach down.
        higher_terrain_y = min(terrain_l, terrain_r)
        desired_pelvis_y = higher_terrain_y - float(pelvis_height_above_terrain)
        current_pelvis_y = float(world.nodes.pos[humanoid.pelvis, 1])
        dy = desired_pelvis_y - current_pelvis_y
        if abs(dy) > 1e-6:
            ns, ne = humanoid.node_slice
            world.nodes.pos[ns:ne, 1] += dy
            world.nodes.prev_pos[ns:ne, 1] += dy
            # Also shift any flesh layers attached to the skeleton.
            for fs, fe in humanoid.flesh_node_slices.values():
                world.nodes.pos[fs:fe, 1] += dy
                world.nodes.prev_pos[fs:fe, 1] += dy

        # Solve each leg toward its ankle target on the terrain.
        _solve_2bone_ik(
            world, humanoid.hip_l, humanoid.knee_l, humanoid.ankle_l,
            target=(ankle_l_x, terrain_l),
            upper_len=humanoid.bone_lengths.get("upper_leg_l", 0.42),
            lower_len=humanoid.bone_lengths.get("lower_leg_l", 0.42),
        )
        _solve_2bone_ik(
            world, humanoid.hip_r, humanoid.knee_r, humanoid.ankle_r,
            target=(ankle_r_x, terrain_r),
            upper_len=humanoid.bone_lengths.get("upper_leg_r", 0.42),
            lower_len=humanoid.bone_lengths.get("lower_leg_r", 0.42),
        )

        err_l = abs(float(world.nodes.pos[humanoid.ankle_l, 1]) - terrain_l)
        err_r = abs(float(world.nodes.pos[humanoid.ankle_r, 1]) - terrain_r)
        if err_l < tolerance and err_r < tolerance:
            converged = True
            break

    return converged


__all__ = [
    "Humanoid",
    "make_humanoid",
    "wrap_in_flesh",
    "place_feet_on_terrain",
    "LAYER_BONE",
    "LAYER_MUSCLE",
    "LAYER_SKIN",
]
