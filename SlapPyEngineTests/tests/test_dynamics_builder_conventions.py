"""Builder naming + return-shape conventions for ``slappyengine.dynamics``.

The package has two builder prefixes with distinct contracts:

* ``make_*`` returns a pure :class:`JointSpec` / kind-specific spec
  dataclass; no world is touched.
* ``build_*`` mutates the supplied world (adds nodes / joints / beams /
  bodies) and returns a handle (an :class:`int`, a :class:`Body`, or a
  :class:`Humanoid`).

Two legacy spellings (``make_humanoid``, ``wrap_in_flesh``) predate the
convention and mutate a softbody world; they remain as deprecated aliases
of ``build_humanoid`` / ``build_flesh_wrap`` and emit
:class:`DeprecationWarning` on call. These tests pin the contract so a
future rename can't silently violate it.
"""
from __future__ import annotations

import inspect
import warnings
from dataclasses import is_dataclass

import pytest

import slappyengine.dynamics as dyn
from slappyengine.dynamics import (
    Body,
    BoneSpec,
    Humanoid,
    JointSpec,
    RagdollSpec,
    RopeSpec,
    World,
    build_flesh_wrap,
    build_humanoid,
    build_ragdoll,
    build_rope,
    make_distance,
    make_humanoid,
    make_motor,
    make_spring,
    wrap_in_flesh,
)


# ---------------------------------------------------------------------------
# make_* builders return a pure spec, no world touched.
# ---------------------------------------------------------------------------


def test_make_spring_returns_joint_spec_without_world():
    spec = make_spring(0, 1, rest_length=1.0)
    assert isinstance(spec, JointSpec)
    assert spec.kind == "spring"
    # No world argument anywhere in the signature.
    sig = inspect.signature(make_spring)
    assert "world" not in sig.parameters


def test_make_distance_returns_joint_spec_without_world():
    spec = make_distance(0, 1, rest_length=1.0)
    assert isinstance(spec, JointSpec)
    assert spec.kind == "distance"
    sig = inspect.signature(make_distance)
    assert "world" not in sig.parameters


def test_make_motor_returns_joint_spec_without_world():
    spec = make_motor(0, 1, 2, target_omega=1.0, max_torque=10.0, radius=1.0)
    assert isinstance(spec, JointSpec)
    assert spec.kind == "motor"
    sig = inspect.signature(make_motor)
    assert "world" not in sig.parameters


def test_every_public_make_builder_returns_spec_and_takes_no_world():
    """Every ``make_*`` symbol exported by the package must follow the rule.

    Skips serialiser helpers (``make_humanoid`` is a deprecated alias and
    is checked explicitly below).
    """
    deprecated = {"make_humanoid"}
    make_names = [
        name for name in dyn.__all__
        if name.startswith("make_") and name not in deprecated
    ]
    assert make_names, "expected at least one make_* builder in the public surface"
    for name in make_names:
        fn = getattr(dyn, name)
        assert callable(fn), f"{name} is exported but not callable"
        sig = inspect.signature(fn)
        assert "world" not in sig.parameters, (
            f"{name} accepts a `world` parameter — make_* builders must be "
            f"pure spec constructors. Move world mutation into a build_* "
            f"counterpart."
        )


# ---------------------------------------------------------------------------
# build_* builders accept a world (positional) and mutate it.
# ---------------------------------------------------------------------------


def test_build_rope_accepts_world_and_mutates_it():
    world = World(gravity=(0.0, 0.0))
    spec = RopeSpec(node_count=4, total_length=2.0, mass_per_node=0.1)
    before = len(world.positions)
    body = build_rope(spec, world, anchor_a=(0.0, 0.0), anchor_b=(2.0, 0.0))
    after = len(world.positions)
    assert isinstance(body, Body)
    assert after > before, "build_rope must add nodes to the world"


def test_build_ragdoll_accepts_world_and_mutates_it():
    world = World(gravity=(0.0, 0.0))
    spec = RagdollSpec(bones=[
        BoneSpec(parent_idx=-1, length=0.5, mass=1.0, direction=(0.0, -1.0)),
        BoneSpec(parent_idx=0, length=0.5, mass=1.0, direction=(0.0, -1.0)),
    ])
    before = len(world.positions)
    body = build_ragdoll(spec, world, anchor_pos=(0.0, 2.0))
    assert isinstance(body, Body)
    assert len(world.positions) > before


def test_build_humanoid_accepts_world_and_mutates_it():
    pytest.importorskip("slappyengine.softbody")
    from slappyengine.softbody import SoftBodyWorld

    world = SoftBodyWorld()
    before_nodes = world.nodes.count
    before_beams = world.beams.count
    hum = build_humanoid(world, root_position=(0.0, 1.0))
    assert isinstance(hum, Humanoid)
    assert world.nodes.count > before_nodes
    assert world.beams.count > before_beams


def test_build_flesh_wrap_accepts_world_and_mutates_it():
    pytest.importorskip("slappyengine.softbody")
    from slappyengine.softbody import SoftBodyWorld

    world = SoftBodyWorld()
    hum = build_humanoid(world, root_position=(0.0, 1.0))
    before_nodes = world.nodes.count
    before_beams = world.beams.count
    returned = build_flesh_wrap(world, hum)
    assert returned is hum, "build_flesh_wrap should return the humanoid for chaining"
    assert world.nodes.count > before_nodes
    assert world.beams.count > before_beams


def test_every_public_build_builder_takes_a_world_positionally():
    """Every ``build_*`` callable in the public surface must expose ``world``.

    Skips serialiser dataclass-style functions like
    ``humanoid_to_dict`` — those are handled by the serializer test
    module.
    """
    build_names = [name for name in dyn.__all__ if name.startswith("build_")]
    assert build_names, "expected at least one build_* builder in the public surface"
    for name in build_names:
        fn = getattr(dyn, name)
        assert callable(fn), f"{name} is exported but not callable"
        params = list(inspect.signature(fn).parameters.values())
        # Either the world is the first parameter (build_humanoid,
        # build_flesh_wrap) or the spec is first and the world is second
        # (build_rope, build_ragdoll). Either way it appears somewhere in
        # the positional-or-keyword arguments.
        positional_names = [
            p.name for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                          inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        assert "world" in positional_names, (
            f"{name} does not expose a `world` positional parameter; "
            f"got positional params {positional_names!r}"
        )


# ---------------------------------------------------------------------------
# Deprecated aliases emit DeprecationWarning and forward correctly.
# ---------------------------------------------------------------------------


def test_make_humanoid_alias_emits_deprecation_warning():
    pytest.importorskip("slappyengine.softbody")
    from slappyengine.softbody import SoftBodyWorld

    world = SoftBodyWorld()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        hum = make_humanoid(world, root_position=(0.0, 1.0))
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, (
        "make_humanoid should emit a DeprecationWarning pointing at build_humanoid"
    )
    assert "build_humanoid" in str(deprecations[0].message)
    assert isinstance(hum, Humanoid)


def test_wrap_in_flesh_alias_emits_deprecation_warning():
    pytest.importorskip("slappyengine.softbody")
    from slappyengine.softbody import SoftBodyWorld

    world = SoftBodyWorld()
    # Build via the new name so the wrap call is the only deprecation.
    hum = build_humanoid(world, root_position=(0.0, 1.0))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        returned = wrap_in_flesh(world, hum)
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecations, (
        "wrap_in_flesh should emit a DeprecationWarning pointing at build_flesh_wrap"
    )
    assert "build_flesh_wrap" in str(deprecations[0].message)
    assert returned is hum


def test_deprecated_aliases_forward_to_canonical_builders():
    """The legacy callables must produce the same Humanoid the build_* form does."""
    pytest.importorskip("slappyengine.softbody")
    from slappyengine.softbody import SoftBodyWorld

    w1 = SoftBodyWorld()
    w2 = SoftBodyWorld()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        legacy = make_humanoid(w1, root_position=(0.0, 1.0))
    canonical = build_humanoid(w2, root_position=(0.0, 1.0))

    assert isinstance(legacy, Humanoid) and isinstance(canonical, Humanoid)
    # Same number of bone nodes / beams spawned.
    assert legacy.node_slice[1] - legacy.node_slice[0] == (
        canonical.node_slice[1] - canonical.node_slice[0]
    )
    assert legacy.beam_slice[1] - legacy.beam_slice[0] == (
        canonical.beam_slice[1] - canonical.beam_slice[0]
    )
    assert legacy.bone_lengths == canonical.bone_lengths


# ---------------------------------------------------------------------------
# Spec dataclasses returned by make_* are dataclasses (editor-friendly).
# ---------------------------------------------------------------------------


def test_specs_returned_by_make_builders_are_dataclasses():
    """JointSpec and friends must remain plain dataclasses.

    The editor's PropertyInspector reflects fields through ``dataclasses``;
    a subclass that hides fields would break the inspector silently.
    """
    spec = make_spring(0, 1, rest_length=1.0)
    assert is_dataclass(spec)
    spec_d = make_distance(0, 1, rest_length=1.0)
    assert is_dataclass(spec_d)
    spec_m = make_motor(0, 1, 2, target_omega=1.0, max_torque=10.0, radius=1.0)
    assert is_dataclass(spec_m)
