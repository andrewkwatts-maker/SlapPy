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
* :class:`World`, :class:`SoftBodyWorld` — substrate that hosts the above

Every constraint resolves to the same XPBD distance / angular projections in
:mod:`slappyengine.dynamics.joint`, so vehicles, ropes, ragdolls, and IK
chains coexist in a single :meth:`World.step` with no special-case branches.
"""
from __future__ import annotations

from .body import Body
from .humanoid import (
    Humanoid,
    LAYER_BONE,
    LAYER_MUSCLE,
    LAYER_SKIN,
    make_humanoid,
    place_feet_on_terrain,
    wrap_in_flesh,
)
from .ik import IKChainSpec, solve_ik
from .joint import JointSpec, KIND_PARAM_KEYS, resolve as resolve_joint
from .material import Material
from .motor import MotorSpec, make_motor
from .ragdoll import BoneSpec, RagdollSpec, build_ragdoll
from .rope import RopeSpec, build_rope
from .serialize import (
    SCHEMA_VERSION,
    load_world,
    save_world,
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
    "Material",
    "JointSpec",
    "KIND_PARAM_KEYS",
    "resolve_joint",
    "SpringSpec",
    "make_spring",
    "MotorSpec",
    "make_motor",
    "RopeSpec",
    "build_rope",
    "BoneSpec",
    "RagdollSpec",
    "build_ragdoll",
    "Humanoid",
    "LAYER_BONE",
    "LAYER_MUSCLE",
    "LAYER_SKIN",
    "make_humanoid",
    "wrap_in_flesh",
    "place_feet_on_terrain",
    "IKChainSpec",
    "solve_ik",
    "World",
    "SoftBodyWorld",
    "estimate_effective_damping",
    "OVERDAMPING_THRESHOLD",
    "SCHEMA_VERSION",
    "world_to_dict",
    "world_from_dict",
    "save_world",
    "load_world",
]
