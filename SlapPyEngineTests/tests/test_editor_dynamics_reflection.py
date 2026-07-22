"""Phase A: PropertyInspector reflection over pharos_engine.dynamics types.

The unified dynamics layer (``Body``, ``Material``, ``JointSpec``,
``MotorSpec``, ``SpringSpec``, ``RopeSpec``, ``IKChainSpec``,
``RagdollSpec``) intentionally piggybacks on the *existing* property
inspector reflection so authoring tools get a generic editor for free.

These tests stay independent of dearpygui by stubbing a no-op DPG module
that records every ``add_*`` call so we can assert which widgets the
inspector built. For each dataclass we verify:

1. The inspector iterates every dataclass field via ``_iter_fields``.
2. The refresh path produces at least one widget per primitive field
   (recorded in ``self._widget_map``).
3. Writing a new value through the generated callback updates the
   dataclass attribute.
"""
from __future__ import annotations

import dataclasses
import math
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# DPG stub fixture — records every ``add_*`` invocation so we can assert.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    created: list[tuple[str, tuple, dict]] = []

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _NoOp:
        def __getattr__(self, name):
            def _fn(*a, **kw):
                if name.startswith("add_"):
                    created.append((name, a, kw))
                return _Ctx()
            return _fn

        def does_item_exist(self, *a, **kw):
            return True

        def delete_item(self, *a, **kw):
            return None

    inst = _NoOp()
    inst.created = created

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = inst
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", inst)
    yield inst


# ---------------------------------------------------------------------------
# Import guards — skip the whole module if dynamics or the inspector isn't
# importable in this checkout.
# ---------------------------------------------------------------------------

try:
    from pharos_engine.ui.editor.property_inspector import (
        PropertyInspector,
        _is_engine_object,
        _is_list_of_int,
        _is_primitive,
        _is_simple_value_dict,
    )
    from pharos_engine.dynamics import (
        Body,
        BoneSpec,
        IKChainSpec,
        JointSpec,
        Material,
        MotorSpec,
        RagdollSpec,
        RopeSpec,
        SpringSpec,
        make_motor,
        make_spring,
    )
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"dynamics or property_inspector not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Sample factories — every dynamics dataclass with at least one non-default
# primitive field so writeback assertions have something to flip.
# ---------------------------------------------------------------------------

def _sample_body() -> Body:
    return Body(
        kind="rope",
        node_offset=4,
        node_count=8,
        label="cable",
        parameters={"preset": "steel"},
    )


def _sample_material() -> Material:
    return Material(
        name="rubber",
        density=850.0,
        stiffness=5.0e5,
        damping=0.1,
        restitution=0.3,
        friction=0.6,
        breaking_strain=2.0,
        properties={"color": "red"},
    )


def _sample_jointspec() -> JointSpec:
    return JointSpec(
        kind="distance",
        node_a=0,
        node_b=1,
        rest_length=2.5,
        stiffness=1.0e8,
        damping=0.05,
        params={},
    )


def _sample_motorspec() -> MotorSpec:
    # MotorSpec is the pure-data record; make_motor produces a JointSpec.
    return MotorSpec(
        hub=0,
        rim_a=1,
        rim_b=2,
        target_omega=1.5,
        max_torque=10.0,
        radius=0.4,
        axis=(1.0, 0.0),
    )


def _sample_springspec() -> SpringSpec:
    return SpringSpec(node_a=0, node_b=1, rest_length=1.25)


def _sample_ropespec() -> RopeSpec:
    return RopeSpec(node_count=8, total_length=4.0)


def _sample_ikchainspec() -> IKChainSpec:
    return IKChainSpec(
        node_indices=[0, 1, 2, 3],
        target=(2.5, 1.0),
        fixed_root=True,
    )


def _sample_ragdollspec() -> RagdollSpec:
    bones = [
        BoneSpec(parent_idx=-1, length=1.0, mass=1.0),
        BoneSpec(parent_idx=0, length=0.5, mass=0.5),
    ]
    return RagdollSpec(bones=bones)


_SAMPLE_FACTORIES = {
    "Body":         _sample_body,
    "Material":     _sample_material,
    "JointSpec":    _sample_jointspec,
    "MotorSpec":    _sample_motorspec,
    "SpringSpec":   _sample_springspec,
    "RopeSpec":     _sample_ropespec,
    "IKChainSpec":  _sample_ikchainspec,
    "RagdollSpec":  _sample_ragdollspec,
}


# ---------------------------------------------------------------------------
# Predicate-level tests
# ---------------------------------------------------------------------------

class TestPredicates:
    def test_dynamics_dataclasses_are_not_treated_as_engine_objects(self):
        """Every dataclass should be reflected, not opaque-popup'd."""
        for name, factory in _SAMPLE_FACTORIES.items():
            obj = factory()
            assert dataclasses.is_dataclass(obj), name
            assert not _is_engine_object(obj), (
                f"{name} should reflect through dataclass path, "
                f"not the engine-ref popup"
            )

    def test_list_of_int_is_primitive_for_node_indices(self):
        assert _is_list_of_int([0, 1, 2]) is True
        assert _is_primitive([0, 1, 2]) is True
        # bool subclasses int — make sure we don't treat a list of bools as ints.
        assert _is_list_of_int([True, False]) is False

    def test_params_bag_dict_is_simple(self):
        assert _is_simple_value_dict({}) is True
        assert _is_simple_value_dict({"hub": 0, "target_omega": 2.0}) is True
        # Mixed-with-non-primitive value disqualifies inline rendering.
        class _Opaque: ...
        assert _is_simple_value_dict({"x": _Opaque()}) is False


# ---------------------------------------------------------------------------
# Reflection / refresh tests
# ---------------------------------------------------------------------------

class TestReflectionPerType:
    @pytest.mark.parametrize("type_name", list(_SAMPLE_FACTORIES.keys()))
    def test_iter_fields_covers_every_dataclass_field(self, type_name):
        obj = _SAMPLE_FACTORIES[type_name]()
        inspector = PropertyInspector()
        inspector._obj = obj
        seen = {n for n, _v in inspector._iter_fields()}
        expected = {f.name for f in dataclasses.fields(obj)}
        assert seen == expected, (
            f"{type_name}: inspector missed fields "
            f"{expected - seen} (extra: {seen - expected})"
        )

    @pytest.mark.parametrize("type_name", list(_SAMPLE_FACTORIES.keys()))
    def test_refresh_builds_at_least_one_widget(
        self, type_name, stub_dearpygui,
    ):
        """End-to-end: build + set_object must add widgets and not raise."""
        obj = _SAMPLE_FACTORIES[type_name]()
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        # Reset recorded widgets so we only count what set_object built.
        stub_dearpygui.created.clear()
        inspector.set_object(obj)
        names = [w[0] for w in stub_dearpygui.created]
        assert names, (
            f"{type_name}: refresh produced zero widgets"
        )
        # Type header must always appear.
        assert any(n == "add_text" for n in names), (
            f"{type_name}: expected the 'Type:' header text widget"
        )

    @pytest.mark.parametrize("type_name", list(_SAMPLE_FACTORIES.keys()))
    def test_every_primitive_field_records_a_widget(self, type_name):
        """``_widget_map`` should contain a tag for every primitive field."""
        obj = _SAMPLE_FACTORIES[type_name]()
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        inspector.set_object(obj)
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            if _is_primitive(value):
                assert f.name in inspector._widget_map, (
                    f"{type_name}.{f.name} (primitive) missing widget tag"
                )


# ---------------------------------------------------------------------------
# Writeback tests — each primitive field's callback must mutate the object.
# ---------------------------------------------------------------------------

class TestWriteback:
    def test_jointspec_primitive_writebacks(self):
        spec = _sample_jointspec()
        inspector = PropertyInspector()
        inspector._obj = spec

        # Build the per-field callbacks directly — same path _render_field uses.
        cb_stiffness = inspector._make_callback("stiffness")
        cb_stiffness(None, 2.5e7, None)
        assert spec.stiffness == 2.5e7

        cb_damping = inspector._make_callback("damping")
        cb_damping(None, 0.42, None)
        assert math.isclose(spec.damping, 0.42)

        cb_kind = inspector._make_callback("kind")
        cb_kind(None, "spring", None)
        assert spec.kind == "spring"

    def test_motorspec_primitive_writebacks(self):
        spec = _sample_motorspec()
        inspector = PropertyInspector()
        inspector._obj = spec

        inspector._make_callback("target_omega")(None, 9.5, None)
        assert spec.target_omega == 9.5

        inspector._make_callback("max_torque")(None, 22.0, None)
        assert spec.max_torque == 22.0

    def test_body_label_writeback(self):
        body = _sample_body()
        inspector = PropertyInspector()
        inspector._obj = body
        inspector._make_callback("label")(None, "renamed", None)
        assert body.label == "renamed"

    def test_material_primitive_writeback(self):
        mat = _sample_material()
        inspector = PropertyInspector()
        inspector._obj = mat
        inspector._make_callback("friction")(None, 0.91, None)
        assert math.isclose(mat.friction, 0.91)

    def test_ropespec_primitive_writeback(self):
        spec = _sample_ropespec()
        inspector = PropertyInspector()
        inspector._obj = spec
        inspector._make_callback("anchor_a_pinned")(None, False, None)
        assert spec.anchor_a_pinned is False

    def test_springspec_primitive_writeback(self):
        spec = _sample_springspec()
        inspector = PropertyInspector()
        inspector._obj = spec
        inspector._make_callback("rest_length")(None, 3.75, None)
        assert spec.rest_length == 3.75

    def test_ikchainspec_node_indices_text_callback_roundtrip(
        self, stub_dearpygui,
    ):
        """The list-of-int widget parses comma-separated text back into a list."""
        spec = _sample_ikchainspec()
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        inspector.set_object(spec)

        # The list-of-int branch registers an inline input_text widget;
        # locate it by inspecting recorded add_input_text calls keyed on
        # the unique tag for node_indices.
        target_tag = inspector._widget_map.get("node_indices")
        assert target_tag is not None, "node_indices widget not registered"

        cb = None
        for fn_name, args, kw in stub_dearpygui.created:
            if fn_name != "add_input_text":
                continue
            if kw.get("tag") == target_tag:
                cb = kw.get("callback")
                break
        assert cb is not None, "no callback registered for node_indices"

        cb(None, "7, 8, 9", None)
        assert spec.node_indices == [7, 8, 9]
        # Tolerate trailing junk + alternate separators.
        cb(None, "1; 2; 3,", None)
        assert spec.node_indices == [1, 2, 3]
        # Bad input must not crash (silently rejected).
        cb(None, "not, ints, here", None)
        assert spec.node_indices == [1, 2, 3]

    def test_jointspec_params_dict_inline_writeback(self, stub_dearpygui):
        """Params bag renders as inline rows and writes through to the dict."""
        # Use a hinge spec because its params has a couple of primitive keys.
        spec = JointSpec(
            kind="hinge",
            node_a=0,
            node_b=1,
            rest_length=1.0,
            stiffness=1.0e8,
            damping=0.05,
            params={"anchor": 2, "min_angle": -1.0, "max_angle": 1.0},
        )
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        inspector.set_object(spec)

        # Write back to params["anchor"].
        cb_anchor = inspector._make_dict_callback("params", "anchor")
        cb_anchor(None, 5, None)
        assert spec.params["anchor"] == 5

        cb_max = inspector._make_dict_callback("params", "max_angle")
        cb_max(None, 2.5, None)
        assert math.isclose(spec.params["max_angle"], 2.5)

    def test_ragdollspec_primitive_writeback(self):
        spec = _sample_ragdollspec()
        inspector = PropertyInspector()
        inspector._obj = spec
        inspector._make_callback("stiffness")(None, 1.0e7, None)
        assert spec.stiffness == 1.0e7
        inspector._make_callback("damping")(None, 0.08, None)
        assert math.isclose(spec.damping, 0.08)


# ---------------------------------------------------------------------------
# Builder-output reflection: make_spring / make_motor return JointSpec, so
# those compositions must reflect too.
# ---------------------------------------------------------------------------

class TestBuilderOutputs:
    def test_make_spring_jointspec_reflects(self, stub_dearpygui):
        spec = make_spring(0, 1, rest_length=2.0)
        assert isinstance(spec, JointSpec)
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        stub_dearpygui.created.clear()
        inspector.set_object(spec)
        assert stub_dearpygui.created, "make_spring JointSpec produced no widgets"

    def test_make_motor_jointspec_reflects(self, stub_dearpygui):
        spec = make_motor(
            hub=0, rim_a=1, rim_b=2,
            target_omega=2.0, max_torque=5.0, radius=0.3,
        )
        assert isinstance(spec, JointSpec)
        inspector = PropertyInspector()
        inspector.build("parent_tag")
        stub_dearpygui.created.clear()
        inspector.set_object(spec)
        assert stub_dearpygui.created, "make_motor JointSpec produced no widgets"
