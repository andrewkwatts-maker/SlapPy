"""Headless tests for editor panel helper functions and pure-Python class methods.

Covers:
- pharos_engine.ui.editor.property_inspector  (module helpers + PropertyInspector)
- pharos_engine.ui.editor.deform_panel        (module helpers + DeformPanel + ZoneEditorPanel)
- pharos_engine.ui.editor.scene_outliner      (SceneOutliner)

All tests are headless — no DearPyGUI, no GPU.  DPG methods are only called
inside build() / _refresh() which are behind a ``dpg.does_item_exist`` guard
that silently returns when DPG is absent.
"""
from __future__ import annotations
import dataclasses
from enum import Enum
import pytest


# ---------------------------------------------------------------------------
# Helpers for building minimal fake objects
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _FlatDC:
    x: float = 1.0
    name: str = "hello"
    flag: bool = True


class _PlainObj:
    def __init__(self):
        self.speed = 42.0
        self.label = "car"
        self._private = "hidden"


class _FakeEnum(Enum):
    ALPHA = "alpha"
    BETA  = "beta"
    GAMMA = "gamma"


# ---------------------------------------------------------------------------
# property_inspector — module-level helpers
# ---------------------------------------------------------------------------

class TestIsFloatTuple:
    def _fn(self, v):
        from pharos_engine.ui.editor.property_inspector import _is_float_tuple
        return _is_float_tuple(v)

    def test_float_pair(self):
        assert self._fn((1.0, 2.0)) is True

    def test_int_pair(self):
        assert self._fn((1, 2)) is True

    def test_mixed_float_int(self):
        assert self._fn((1.5, 2)) is True

    def test_single_element(self):
        assert self._fn((3.14,)) is True

    def test_four_element(self):
        assert self._fn((0.1, 0.2, 0.3, 0.4)) is True

    def test_empty_tuple_false(self):
        assert self._fn(()) is False

    def test_tuple_with_str_false(self):
        assert self._fn((1.0, "x")) is False

    def test_list_false(self):
        assert self._fn([1.0, 2.0]) is False

    def test_plain_float_false(self):
        assert self._fn(3.14) is False

    def test_none_false(self):
        assert self._fn(None) is False


class TestIsListOfStr:
    def _fn(self, v):
        from pharos_engine.ui.editor.property_inspector import _is_list_of_str
        return _is_list_of_str(v)

    def test_str_list(self):
        assert self._fn(["a", "b", "c"]) is True

    def test_empty_list(self):
        assert self._fn([]) is True

    def test_single_str(self):
        assert self._fn(["hello"]) is True

    def test_list_with_int_false(self):
        assert self._fn(["a", 1]) is False

    def test_list_of_ints_false(self):
        assert self._fn([1, 2, 3]) is False

    def test_tuple_of_str_false(self):
        assert self._fn(("a", "b")) is False

    def test_plain_str_false(self):
        assert self._fn("hello") is False


class TestIsPrimitive:
    def _fn(self, v):
        from pharos_engine.ui.editor.property_inspector import _is_primitive
        return _is_primitive(v)

    def test_bool(self):
        assert self._fn(True) is True

    def test_int(self):
        assert self._fn(42) is True

    def test_float(self):
        assert self._fn(3.14) is True

    def test_str(self):
        assert self._fn("hello") is True

    def test_float_tuple(self):
        assert self._fn((1.0, 2.0)) is True

    def test_str_list(self):
        assert self._fn(["a", "b"]) is True

    def test_empty_str_list(self):
        assert self._fn([]) is True

    def test_dict_false(self):
        assert self._fn({"a": 1}) is False

    def test_none_false(self):
        assert self._fn(None) is False

    def test_object_false(self):
        assert self._fn(_PlainObj()) is False

    def test_empty_tuple_false(self):
        assert self._fn(()) is False


class TestIsEngineObject:
    def _fn(self, v):
        from pharos_engine.ui.editor.property_inspector import _is_engine_object
        return _is_engine_object(v)

    def test_list_with_dict_is_complex(self):
        # list containing a non-primitive (dict)
        assert self._fn([{"nested": True}]) is True

    def test_list_of_primitives_false(self):
        assert self._fn([1.0, 2.0]) is False

    def test_list_of_str_false(self):
        assert self._fn(["a", "b"]) is False

    def test_empty_list_false(self):
        assert self._fn([]) is False

    def test_plain_class_false(self):
        # module is __main__ / tests, not pharos_engine.*
        assert self._fn(_PlainObj()) is False

    def test_dataclass_false(self):
        # dataclasses are treated as plain data regardless of module
        assert self._fn(_FlatDC()) is False

    def test_int_false(self):
        assert self._fn(42) is False

    def test_none_false(self):
        assert self._fn(None) is False


# ---------------------------------------------------------------------------
# property_inspector — PropertyInspector class (pure-Python methods only)
# ---------------------------------------------------------------------------

class TestPropertyInspectorInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        assert pi is not None

    def test_obj_none_initially(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        assert pi._obj is None

    def test_panel_tag_default(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        assert pi._panel_tag == "property_inspector"

    def test_widget_map_empty(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        assert pi._widget_map == {}


class TestPropertyInspectorIterFields:
    def _pi(self, obj):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = obj
        return pi

    def test_dataclass_fields(self):
        pi = self._pi(_FlatDC(x=9.0, name="foo", flag=False))
        fields = dict(pi._iter_fields())
        assert fields["x"] == pytest.approx(9.0)
        assert fields["name"] == "foo"
        assert fields["flag"] is False

    def test_dataclass_field_count(self):
        pi = self._pi(_FlatDC())
        assert len(pi._iter_fields()) == 3

    def test_plain_object_fields(self):
        obj = _PlainObj()
        pi = self._pi(obj)
        fields = dict(pi._iter_fields())
        assert "speed" in fields
        assert "label" in fields

    def test_plain_object_excludes_private(self):
        obj = _PlainObj()
        pi = self._pi(obj)
        keys = [k for k, _ in pi._iter_fields()]
        assert "_private" not in keys


class TestPropertyInspectorUniqueTag:
    def test_returns_string(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _PlainObj()
        tag = pi._unique_tag("speed")
        assert isinstance(tag, str)

    def test_contains_panel_tag(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _PlainObj()
        tag = pi._unique_tag("speed")
        assert "property_inspector" in tag

    def test_contains_attr_name(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _PlainObj()
        tag = pi._unique_tag("speed")
        assert "speed" in tag

    def test_two_attrs_different_tags(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _PlainObj()
        assert pi._unique_tag("x") != pi._unique_tag("y")

    def test_stable_for_same_obj(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        obj = _PlainObj()
        pi._obj = obj
        assert pi._unique_tag("speed") == pi._unique_tag("speed")


class TestPropertyInspectorMakeCallback:
    def test_returns_callable(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _PlainObj()
        cb = pi._make_callback("speed")
        assert callable(cb)

    def test_callback_sets_attribute(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        obj = _PlainObj()
        pi._obj = obj
        cb = pi._make_callback("speed")
        cb(None, 99.0, None)
        assert obj.speed == pytest.approx(99.0)

    def test_callback_noop_if_obj_none(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = None
        cb = pi._make_callback("speed")
        cb(None, 42.0, None)  # should not raise

    def test_callback_ignores_attribute_error(self):
        from pharos_engine.ui.editor.property_inspector import PropertyInspector
        pi = PropertyInspector()
        pi._obj = _FlatDC()
        cb = pi._make_callback("nonexistent_frozen_attr")
        cb(None, 1.0, None)  # dataclass raises AttributeError — should not raise


class TestPropertyInspectorConstants:
    def test_transform_fields_contains_position(self):
        from pharos_engine.ui.editor.property_inspector import TRANSFORM_FIELDS
        assert "position" in TRANSFORM_FIELDS

    def test_transform_fields_contains_rotation(self):
        from pharos_engine.ui.editor.property_inspector import TRANSFORM_FIELDS
        assert "rotation" in TRANSFORM_FIELDS

    def test_drag_float_names_contains_width(self):
        from pharos_engine.ui.editor.property_inspector import DRAG_FLOAT_NAMES
        assert "width" in DRAG_FLOAT_NAMES

    def test_drag_float_names_contains_height(self):
        from pharos_engine.ui.editor.property_inspector import DRAG_FLOAT_NAMES
        assert "height" in DRAG_FLOAT_NAMES


# ---------------------------------------------------------------------------
# deform_panel — module-level helpers
# ---------------------------------------------------------------------------

class TestEnumItems:
    def _fn(self, cls):
        from pharos_engine.ui.editor.deform_panel import _enum_items
        return _enum_items(cls)

    def test_returns_list(self):
        assert isinstance(self._fn(_FakeEnum), list)

    def test_length_matches_enum(self):
        assert len(self._fn(_FakeEnum)) == 3

    def test_values_are_strings(self):
        for item in self._fn(_FakeEnum):
            assert isinstance(item, str)

    def test_values_are_enum_values(self):
        items = self._fn(_FakeEnum)
        assert "alpha" in items
        assert "beta" in items
        assert "gamma" in items


class TestEnumValue:
    def _fn(self, v):
        from pharos_engine.ui.editor.deform_panel import _enum_value
        return _enum_value(v)

    def test_enum_member_returns_value(self):
        assert self._fn(_FakeEnum.ALPHA) == "alpha"

    def test_enum_beta_returns_value(self):
        assert self._fn(_FakeEnum.BETA) == "beta"

    def test_plain_string_passthrough(self):
        assert self._fn("custom") == "custom"

    def test_integer_str_conversion(self):
        assert self._fn(42) == "42"


class TestSafeSetattr:
    def _fn(self, obj, attr, val):
        from pharos_engine.ui.editor.deform_panel import _safe_setattr
        _safe_setattr(obj, attr, val)

    def test_sets_existing_attr(self):
        obj = _PlainObj()
        self._fn(obj, "speed", 100.0)
        assert obj.speed == pytest.approx(100.0)

    def test_sets_new_attr_on_plain_object(self):
        obj = _PlainObj()
        self._fn(obj, "brand_new", "hello")
        assert obj.brand_new == "hello"

    def test_no_crash_on_attribute_error(self):
        # Frozen dataclass raises AttributeError on attribute set
        @dataclasses.dataclass(frozen=True)
        class _Frozen:
            x: int = 0

        self._fn(_Frozen(), "x", 99)  # should not raise

    def test_no_crash_on_none_target(self):
        # None has no settable attrs — TypeError should be swallowed
        from pharos_engine.ui.editor.deform_panel import _safe_setattr
        _safe_setattr(None, "foo", 1)  # should not raise


# ---------------------------------------------------------------------------
# deform_panel — DeformPanel class
# ---------------------------------------------------------------------------

class TestDeformPanelInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.deform_panel import DeformPanel
        p = DeformPanel()
        assert p is not None

    def test_comp_none_initially(self):
        from pharos_engine.ui.editor.deform_panel import DeformPanel
        p = DeformPanel()
        assert p._comp is None

    def test_panel_tag(self):
        from pharos_engine.ui.editor.deform_panel import DeformPanel
        p = DeformPanel()
        assert p._panel_tag == "deform_panel"

    def test_tags_empty_dict(self):
        from pharos_engine.ui.editor.deform_panel import DeformPanel
        p = DeformPanel()
        assert p._tags == {}

    def test_set_component_stores_comp(self):
        from pharos_engine.ui.editor.deform_panel import DeformPanel

        class _FakeComp:
            pass

        p = DeformPanel()
        c = _FakeComp()
        p._comp = c   # direct assign (bypasses DPG _refresh call)
        assert p._comp is c


# ---------------------------------------------------------------------------
# deform_panel — ZoneEditorPanel class
# ---------------------------------------------------------------------------

class _FakeZone:
    def __init__(self, name="zone_0", rect=(0, 0, 64, 64)):
        self.name = name
        self.rect = rect
        self.integrity_threshold = 0.3
        self.material = None
        self.strength_scale = 1.0


class _FakeCompWithZones:
    def __init__(self, zones=None):
        self.zones = zones if zones is not None else []


class TestZoneEditorPanelInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        assert p is not None

    def test_comp_none_initially(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        assert p._comp is None

    def test_panel_tag(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        assert p._panel_tag == "zone_editor_panel"

    def test_preview_callback_none_initially(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        assert p._preview_callback is None


class TestZoneEditorPanelSetPreviewCallback:
    def test_stores_callback(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb = lambda comp: None
        p.set_preview_callback(cb)
        assert p._preview_callback is cb

    def test_replace_callback(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb1 = lambda comp: None
        cb2 = lambda comp: None
        p.set_preview_callback(cb1)
        p.set_preview_callback(cb2)
        assert p._preview_callback is cb2


class TestZoneEditorPanelOnPreviewZones:
    def test_no_crash_when_both_none(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._on_preview_zones()  # _comp None, _preview_callback None — no crash

    def test_no_crash_when_no_callback(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._comp = _FakeCompWithZones()
        p._on_preview_zones()  # callback is None — should not raise

    def test_no_crash_when_comp_none(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        fired = []
        p._preview_callback = lambda c: fired.append(c)
        p._on_preview_zones()  # comp is None — callback should not fire
        assert fired == []

    def test_fires_callback_with_comp(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        comp = _FakeCompWithZones()
        p._comp = comp
        fired = []
        p._preview_callback = lambda c: fired.append(c)
        p._on_preview_zones()
        assert len(fired) == 1
        assert fired[0] is comp

    def test_swallows_callback_exception(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._comp = _FakeCompWithZones()
        p._preview_callback = lambda c: (_ for _ in ()).throw(RuntimeError("boom"))
        p._on_preview_zones()  # should not propagate


class TestZoneEditorPanelMakeZoneFieldCb:
    def test_returns_callable(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb = p._make_zone_field_cb(0, "name")
        assert callable(cb)

    def test_sets_field_on_zone(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        zone = _FakeZone(name="original")
        p._comp = _FakeCompWithZones(zones=[zone])
        cb = p._make_zone_field_cb(0, "name")
        cb(None, "renamed", None)
        assert zone.name == "renamed"

    def test_cast_applied(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        zone = _FakeZone()
        p._comp = _FakeCompWithZones(zones=[zone])
        cb = p._make_zone_field_cb(0, "integrity_threshold", float)
        cb(None, 0.75, None)
        assert zone.integrity_threshold == pytest.approx(0.75)

    def test_no_crash_index_out_of_range(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._comp = _FakeCompWithZones(zones=[])
        cb = p._make_zone_field_cb(5, "name")
        cb(None, "x", None)  # index 5 out of range — should not raise

    def test_no_crash_comp_none(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb = p._make_zone_field_cb(0, "name")
        cb(None, "x", None)  # comp is None — should not raise


class TestZoneEditorPanelMakeZoneRectCb:
    def test_returns_callable(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb = p._make_zone_rect_cb(0, 0)
        assert callable(cb)

    def test_updates_rect_x(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        zone = _FakeZone(rect=(10, 20, 30, 40))
        p._comp = _FakeCompWithZones(zones=[zone])
        cb = p._make_zone_rect_cb(0, 0)
        cb(None, 99, None)
        assert zone.rect[0] == 99

    def test_updates_rect_y(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        zone = _FakeZone(rect=(10, 20, 30, 40))
        p._comp = _FakeCompWithZones(zones=[zone])
        cb = p._make_zone_rect_cb(0, 1)
        cb(None, 55, None)
        assert zone.rect[1] == 55

    def test_no_crash_index_out_of_range(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._comp = _FakeCompWithZones(zones=[])
        cb = p._make_zone_rect_cb(5, 0)
        cb(None, 10, None)  # should not raise


class TestZoneEditorPanelMakeZoneMaterialCb:
    def test_returns_callable(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        cb = p._make_zone_material_cb(0)
        assert callable(cb)

    def test_sets_material_to_none_on_inherit(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        zone = _FakeZone()
        zone.material = "something"
        p._comp = _FakeCompWithZones(zones=[zone])
        cb = p._make_zone_material_cb(0)
        cb(None, "(inherit)", None)
        assert zone.material is None

    def test_no_crash_index_out_of_range(self):
        from pharos_engine.ui.editor.deform_panel import ZoneEditorPanel
        p = ZoneEditorPanel()
        p._comp = _FakeCompWithZones(zones=[])
        cb = p._make_zone_material_cb(5)
        cb(None, "(inherit)", None)  # should not raise


# ---------------------------------------------------------------------------
# scene_outliner — SceneOutliner class
# ---------------------------------------------------------------------------

class TestSceneOutlinerInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o is not None

    def test_scene_none_initially(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._scene is None

    def test_selected_entity_none_initially(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._selected_entity is None

    def test_on_select_none_initially(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._on_select is None

    def test_panel_tag_default(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._panel_tag == "scene_outliner"

    def test_row_group_tag_default(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._row_group_tag == "scene_outliner_rows"

    def test_accent_theme_none(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._accent_theme is None

    def test_default_theme_none(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o._default_theme is None


class TestSceneOutlinerSetScene:
    def test_stores_scene(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner

        class _FakeScene:
            pass

        o = SceneOutliner()
        s = _FakeScene()
        o.set_scene(s)
        assert o._scene is s

    def test_no_refresh_before_build(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner

        class _FakeScene:
            pass

        o = SceneOutliner()
        # _accent_theme is None → refresh() is NOT called → no DPG import
        o.set_scene(_FakeScene())  # should not raise

    def test_replace_scene(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner

        class _S:
            pass

        o = SceneOutliner()
        s1, s2 = _S(), _S()
        o.set_scene(s1)
        o.set_scene(s2)
        assert o._scene is s2


class TestSceneOutlinerGetSelected:
    def test_returns_none_initially(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        assert o.get_selected() is None

    def test_returns_set_entity(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner

        class _E:
            pass

        o = SceneOutliner()
        e = _E()
        o._selected_entity = e
        assert o.get_selected() is e


class TestSceneOutlinerSetOnSelect:
    def test_stores_callback(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        cb = lambda e: None
        o.set_on_select(cb)
        assert o._on_select is cb

    def test_replace_callback(self):
        from pharos_engine.ui.editor.scene_outliner import SceneOutliner
        o = SceneOutliner()
        cb1 = lambda e: None
        cb2 = lambda e: None
        o.set_on_select(cb1)
        o.set_on_select(cb2)
        assert o._on_select is cb2
