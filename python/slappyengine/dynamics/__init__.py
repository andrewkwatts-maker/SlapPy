"""Unified dynamics primitives layered on top of the XPBD substrate.

This package generalises the softbody-specific ``BodyMeta`` / ``VehicleSpec``
/ ``WheelSpec`` types into a small composable type system:

* :class:`Body`           — handle for any contiguous slice of nodes
* :class:`Material`       — bulk physical parameters
* :class:`JointSpec`      — generic two-node constraint (7 kinds)
* :class:`SpringSpec`,    :func:`make_spring`  — convenience constructors
* :class:`MotorSpec`,     :func:`make_motor`
* :class:`RopeSpec`,      :func:`build_rope`   — chain of nodes between two anchors
* :class:`RagdollSpec`,   :func:`build_ragdoll` — tree of bones with angle limits
* :class:`IKChainSpec`,   :func:`solve_ik`     — CCD inverse kinematics
* :class:`Humanoid`,      :func:`build_humanoid`, :func:`build_flesh_wrap`
  — 13-node anatomical skeleton + muscle/skin shells
* :class:`World`, :class:`SoftBodyWorld` — substrate that hosts the above

Every constraint resolves to the same XPBD distance / angular projections in
:mod:`slappyengine.dynamics.joint`, so vehicles, ropes, ragdolls, and IK
chains coexist in a single :meth:`World.step` with no special-case branches.

Builder naming convention
-------------------------

* ``make_*`` returns a pure :class:`JointSpec` (or kind-specific spec
  dataclass) without touching any world — use for batched spec
  construction or serialisation.
* ``build_*`` mutates a world (adds nodes, joints, beams, bodies) and
  returns a handle: a node index, a :class:`Body`, or a :class:`Humanoid`.
* ``solve_*`` mutates positions in place to satisfy a constraint but
  does not add new nodes or joints (currently :func:`solve_ik`).

Two legacy spellings predate the convention and remain as deprecated
aliases: :func:`make_humanoid` → :func:`build_humanoid` and
:func:`wrap_in_flesh` → :func:`build_flesh_wrap`. Both emit
:class:`DeprecationWarning` and forward to their new names.
"""
from __future__ import annotations

from .body import Body
from .humanoid import (
    Humanoid,
    LAYER_BONE,
    LAYER_MUSCLE,
    LAYER_SKIN,
    build_flesh_wrap,
    build_humanoid,
    make_humanoid,
    place_feet_on_terrain,
    wrap_in_flesh,
)
from .ik import IKChainSpec, solve_ik
from .joint import (
    JointSpec,
    KIND_PARAM_KEYS,
    make_distance,
    resolve as resolve_joint,
    resolve_joint_specs,
)
from .material import Material
from .motor import MotorSpec, make_motor
from .ragdoll import BoneSpec, RagdollSpec, build_ragdoll
from .rope import RopeSpec, build_rope
from .serialize import (
    SCHEMA_VERSION,
    body_from_dict,
    body_to_dict,
    bone_spec_from_dict,
    bone_spec_to_dict,
    humanoid_from_dict,
    humanoid_to_dict,
    ik_chain_from_dict,
    ik_chain_to_dict,
    joint_from_dict,
    joint_to_dict,
    load_world,
    material_from_dict,
    material_to_dict,
    motor_from_dict,
    motor_to_dict,
    ragdoll_spec_from_dict,
    ragdoll_spec_to_dict,
    rope_spec_from_dict,
    rope_spec_to_dict,
    save_world,
    spring_from_dict,
    spring_to_dict,
    world_from_dict,
    world_to_dict,
)
from .spring import SpringSpec, make_spring
from .world import (
    OVERDAMPING_THRESHOLD,
    SoftBodyWorld,
    World,
    estimate_effective_damping,
)

__all__ = [
    "Body",
    "BoneSpec",
    "Humanoid",
    "IKChainSpec",
    "JointSpec",
    "KIND_PARAM_KEYS",
    "LAYER_BONE",
    "LAYER_MUSCLE",
    "LAYER_SKIN",
    "Material",
    "MotorSpec",
    "OVERDAMPING_THRESHOLD",
    "RagdollSpec",
    "RopeSpec",
    "SCHEMA_VERSION",
    "SoftBodyWorld",
    "SpringSpec",
    "World",
    "body_from_dict",
    "body_to_dict",
    "bone_spec_from_dict",
    "bone_spec_to_dict",
    "build_flesh_wrap",
    "build_humanoid",
    "build_ragdoll",
    "build_rope",
    "estimate_effective_damping",
    "humanoid_from_dict",
    "humanoid_to_dict",
    "ik_chain_from_dict",
    "ik_chain_to_dict",
    "joint_from_dict",
    "joint_to_dict",
    "load_world",
    "make_distance",
    "make_humanoid",
    "make_motor",
    "make_spring",
    "material_from_dict",
    "material_to_dict",
    "motor_from_dict",
    "motor_to_dict",
    "place_feet_on_terrain",
    "ragdoll_spec_from_dict",
    "ragdoll_spec_to_dict",
    "resolve_joint",
    "resolve_joint_specs",
    "rope_spec_from_dict",
    "rope_spec_to_dict",
    "save_world",
    "solve_ik",
    "spring_from_dict",
    "spring_to_dict",
    "world_from_dict",
    "world_to_dict",
    "wrap_in_flesh",
]
