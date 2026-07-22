"""Ragdoll authoring spec + builder.

A ragdoll is a tree of bones rooted at an anchor. Each bone is a single rigid
segment expressed as two nodes (a parent endpoint and a child endpoint) joined
by a stiff distance constraint. Adjacent bones share an endpoint by reusing
the parent's child node, so the tree topology emerges automatically.

Rotational limits between a bone and its parent are enforced with the angular
constraint added to :mod:`pharos_engine.dynamics.joint`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ._validation import validate_anchor, validate_world
from .body import Body
from .joint import JointSpec


@dataclass
class BoneSpec:
    """One bone in a ragdoll skeleton.

    ``parent_idx`` is the index of the parent :class:`BoneSpec` in the
    ``bones`` list of the owning :class:`RagdollSpec`; ``-1`` denotes the
    root bone (which anchors at the world position passed to
    :func:`build_ragdoll`). ``angle_limit`` is a ``(min, max)`` rotation
    band in radians, measured relative to the parent bone direction.
    ``direction`` is the bone's offset vector (unit) — combined with
    ``length`` it places the child endpoint.

    Raises
    ------
    ValueError
        If ``length <= 0``, ``mass <= 0``, ``angle_limit`` is mis-shaped or
        has ``min > max``, or ``direction`` is mis-shaped.
    """
    parent_idx: int = -1
    length: float = 1.0
    mass: float = 1.0
    angle_limit: tuple[float, float] = (-math.pi, math.pi)
    direction: tuple[float, float] = (0.0, -1.0)
    label: str = ""

    def __post_init__(self) -> None:
        try:
            pidx = int(self.parent_idx)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"BoneSpec.parent_idx must be int-coercible; "
                f"got {self.parent_idx!r}"
            ) from exc
        if pidx < -1:
            raise ValueError(
                f"BoneSpec.parent_idx must be -1 (root) or a non-negative "
                f"index; got {self.parent_idx!r}"
            )
        length = float(self.length)
        if not math.isfinite(length) or length <= 0.0:
            raise ValueError(
                f"BoneSpec.length must be finite and > 0; "
                f"got {self.length!r}"
            )
        mass = float(self.mass)
        if not math.isfinite(mass) or mass <= 0.0:
            raise ValueError(
                f"BoneSpec.mass must be finite and > 0; got {self.mass!r}"
            )
        # angle_limit: (min, max), both finite, min <= max.
        if not hasattr(self.angle_limit, "__len__") or len(self.angle_limit) != 2:
            raise ValueError(
                f"BoneSpec.angle_limit must be a (min, max) 2-sequence; "
                f"got {self.angle_limit!r}"
            )
        amin = float(self.angle_limit[0])
        amax = float(self.angle_limit[1])
        if not (math.isfinite(amin) and math.isfinite(amax)):
            raise ValueError(
                f"BoneSpec.angle_limit entries must be finite; "
                f"got {self.angle_limit!r}"
            )
        if amin > amax:
            raise ValueError(
                f"BoneSpec.angle_limit must satisfy min <= max; "
                f"got ({amin!r}, {amax!r})"
            )
        if not hasattr(self.direction, "__len__") or len(self.direction) != 2:
            raise ValueError(
                f"BoneSpec.direction must be a 2-sequence; "
                f"got {self.direction!r}"
            )
        dx = float(self.direction[0])
        dy = float(self.direction[1])
        if not (math.isfinite(dx) and math.isfinite(dy)):
            raise ValueError(
                f"BoneSpec.direction entries must be finite; "
                f"got {self.direction!r}"
            )


@dataclass
class RagdollSpec:
    """Skeleton description for :func:`build_ragdoll`.

    Raises
    ------
    TypeError
        If ``bones`` or ``joints`` is not a list, or any entry is wrong type.
    ValueError
        If ``bones`` is empty, any bone references a non-existent parent
        index, ``stiffness <= 0``, or ``damping`` is outside ``[0, 1]``.
    """
    bones: list[BoneSpec] = field(default_factory=list)
    joints: list[JointSpec] = field(default_factory=list)
    stiffness: float = 5.0e6
    damping: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.bones, list):
            raise TypeError(
                f"RagdollSpec.bones must be a list; "
                f"got {type(self.bones).__name__}"
            )
        if not isinstance(self.joints, list):
            raise TypeError(
                f"RagdollSpec.joints must be a list; "
                f"got {type(self.joints).__name__}"
            )
        if not self.bones:
            raise ValueError(
                "RagdollSpec.bones must not be empty; at least one "
                "BoneSpec is required (the root)"
            )
        for i, bone in enumerate(self.bones):
            if not isinstance(bone, BoneSpec):
                raise TypeError(
                    f"RagdollSpec.bones[{i}] must be a BoneSpec; "
                    f"got {type(bone).__name__}"
                )
            if bone.parent_idx >= 0 and bone.parent_idx >= len(self.bones):
                raise ValueError(
                    f"RagdollSpec.bones[{i}].parent_idx={bone.parent_idx} "
                    f"is out of range for bones list of length "
                    f"{len(self.bones)}"
                )
            # Parent must precede child (the builder walks the list once).
            if bone.parent_idx >= 0 and bone.parent_idx >= i:
                raise ValueError(
                    f"RagdollSpec.bones[{i}].parent_idx={bone.parent_idx} "
                    f"must reference an earlier bone (parent < child); "
                    f"either reorder bones or set parent_idx < {i}"
                )
        for j, joint in enumerate(self.joints):
            if not isinstance(joint, JointSpec):
                raise TypeError(
                    f"RagdollSpec.joints[{j}] must be a JointSpec; "
                    f"got {type(joint).__name__}"
                )
        stiffness = float(self.stiffness)
        if not math.isfinite(stiffness) or stiffness <= 0.0:
            raise ValueError(
                f"RagdollSpec.stiffness must be finite and > 0; "
                f"got {self.stiffness!r}"
            )
        damping = float(self.damping)
        if math.isnan(damping) or not (0.0 <= damping <= 1.0):
            raise ValueError(
                f"RagdollSpec.damping must be in [0, 1]; "
                f"got {self.damping!r}"
            )


def build_ragdoll(
    spec: RagdollSpec,
    world,
    anchor_pos: tuple[float, float],
    pin_root: bool = False,
) -> Body:
    """Spawn nodes + joints for the ragdoll skeleton.

    The first bone is rooted at ``anchor_pos``; subsequent bones extend from
    their parent's child endpoint along ``direction * length``.

    Returns a :class:`Body` covering all spawned nodes (root + one child node
    per bone).

    Raises
    ------
    TypeError
        If ``spec`` is not a :class:`RagdollSpec`, ``world`` is not
        compatible, or ``anchor_pos`` is not a 2-sequence.
    ValueError
        If ``anchor_pos`` contains non-finite values, or any bone references
        a parent that has not been built yet (legacy guard kept for safety).
    """
    if not isinstance(spec, RagdollSpec):
        raise TypeError(
            f"build_ragdoll: spec must be a RagdollSpec; "
            f"got {type(spec).__name__}"
        )
    validate_world("build_ragdoll", world)
    ax, ay = validate_anchor("anchor_pos", "build_ragdoll", anchor_pos)
    anchor_pos = (ax, ay)

    # Pre-compute node positions following the parent chain.
    bone_count = len(spec.bones)
    # child_node_idx[i] is the absolute node index of bone i's child endpoint.
    child_node_idx: list[int] = [-1] * bone_count
    parent_node_for_bone: list[int] = [-1] * bone_count  # node holding bone's parent endpoint

    positions: list[tuple[float, float]] = []
    masses: list[float] = []
    # Root node first.
    positions.append((float(anchor_pos[0]), float(anchor_pos[1])))
    masses.append(0.0 if pin_root else float(spec.bones[0].mass))
    offset, _ = world.add_nodes(np.array([positions[0]]), np.array([masses[0]]))
    root_node = offset

    # We'll bulk-add the rest of the child endpoints in order so we can
    # reference parent child-nodes as we go.
    for bi, bone in enumerate(spec.bones):
        if bone.parent_idx < 0:
            parent_node = root_node
        else:
            parent_node = child_node_idx[bone.parent_idx]
            if parent_node < 0:
                raise ValueError(
                    f"Bone {bi} references parent {bone.parent_idx} not yet built"
                )
        parent_node_for_bone[bi] = parent_node
        # Compute child endpoint position.
        d = np.asarray(bone.direction, dtype=np.float64)
        n = float(np.linalg.norm(d))
        if n < 1e-9:
            d = np.array([0.0, -1.0])
        else:
            d = d / n
        parent_pos = world.positions[parent_node]
        child_pos = parent_pos + d * float(bone.length)
        idx = world.add_node((float(child_pos[0]), float(child_pos[1])), bone.mass)
        child_node_idx[bi] = idx

    # Now wire joints: each bone is a distance constraint parent_node -> child.
    for bi, bone in enumerate(spec.bones):
        parent_node = parent_node_for_bone[bi]
        child = child_node_idx[bi]
        world.add_joint(
            JointSpec(
                kind="distance",
                node_a=parent_node,
                node_b=child,
                rest_length=float(bone.length),
                stiffness=spec.stiffness,
                damping=spec.damping,
            )
        )
        # Angular limit relative to the parent bone, when there is one.
        if bone.parent_idx >= 0:
            grandparent = parent_node_for_bone[bone.parent_idx]
            min_a, max_a = bone.angle_limit
            world.add_joint(
                JointSpec(
                    kind="hinge",
                    node_a=grandparent,
                    node_b=child,
                    rest_length=float(np.linalg.norm(
                        world.positions[child] - world.positions[grandparent]
                    )),
                    stiffness=spec.stiffness * 0.2,
                    damping=spec.damping,
                    params={
                        "anchor": parent_node,
                        "min_angle": float(min_a),
                        "max_angle": float(max_a),
                    },
                )
            )

    # Append any user-supplied extra joints.
    for j in spec.joints:
        world.add_joint(j)

    node_count = 1 + bone_count
    body = Body(
        kind="ragdoll",
        parameters={
            "spec": spec,
            "root_node": root_node,
            "child_nodes": list(child_node_idx),
        },
        node_offset=root_node,
        node_count=node_count,
        label="ragdoll",
    )
    world.register_body(body)
    return body


__all__ = ["BoneSpec", "RagdollSpec", "build_ragdoll"]
