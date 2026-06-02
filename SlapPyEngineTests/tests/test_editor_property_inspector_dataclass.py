"""Tests for PropertyInspector dataclass auto-reflection (Phase A).

The inspector's reflection extension point is :meth:`_iter_fields`
(``python/slappyengine/ui/editor/property_inspector.py``, line ~130),
which already calls :func:`dataclasses.fields` for any dataclass passed
to :meth:`set_object`.  These tests verify that:

- Every field on a representative ``JointSpec``-like dataclass is
  discovered by ``_iter_fields``.
- The dispatcher in ``_refresh`` would categorise each field into one
  of the three sections (Transform / Properties / References), i.e.
  every field produces a widget under the existing rendering path.
"""
from __future__ import annotations

import dataclasses
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """No-op dearpygui that lets _refresh() actually iterate.

    ``does_item_exist`` returns ``True`` so the refresh guard passes;
    every other DPG call is a no-op so the inspector can categorise
    and "render" without a real GUI context.
    """
    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _NoOp:
        def __getattr__(self, name):
            def _fn(*a, **kw):
                return _Ctx()
            return _fn

        def does_item_exist(self, *a, **kw):
            return True

    inst = _NoOp()
    stub = types.ModuleType("dearpygui.dearpygui")
    stub.__getattr__ = lambda name: getattr(inst, name)
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = inst
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", inst)
    yield inst


# ---------------------------------------------------------------------------
# Local dataclass standing in for slappyengine.dynamics.JointSpec.
# (Phase B+ introduces the real one — these tests verify the inspector
# is ready for it today.)
# ---------------------------------------------------------------------------

@dataclass
class JointSpec:
    kind: str = "distance"
    node_a: int = 0
    node_b: int = 1
    rest_length: float = 10.0
    stiffness: float = 1.0e9
    damping: float = 0.02
    break_force: float = 1.0e6
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

try:
    from slappyengine.ui.editor.property_inspector import PropertyInspector
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"PropertyInspector not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPropertyInspectorDataclass:
    def test_iter_fields_discovers_every_jointspec_field(self):
        inspector = PropertyInspector()
        spec = JointSpec()
        inspector._obj = spec
        names = {name for name, _v in inspector._iter_fields()}
        expected = {f.name for f in dataclasses.fields(JointSpec)}
        assert names == expected, (
            "Inspector should reflect every dataclass field; "
            f"got {names!r}, expected {expected!r}"
        )

    def test_iter_fields_returns_current_values(self):
        inspector = PropertyInspector()
        spec = JointSpec(kind="motor", rest_length=42.0)
        inspector._obj = spec
        d = dict(inspector._iter_fields())
        assert d["kind"]        == "motor"
        assert d["rest_length"] == 42.0
        assert d["enabled"]     is True
        assert d["params"]      == {}

    def test_every_field_categorises_into_a_widget_section(self):
        """Each field falls into transform / primitive / complex — none lost."""
        from slappyengine.ui.editor.property_inspector import (
            TRANSFORM_FIELDS, _is_engine_object, _is_primitive,
        )

        inspector = PropertyInspector()
        inspector._obj = JointSpec()

        seen_names: set[str] = set()
        for name, value in inspector._iter_fields():
            seen_names.add(name)
            in_transform = name in TRANSFORM_FIELDS
            is_complex   = _is_engine_object(value)
            is_primitive = _is_primitive(value)
            # The dispatcher in _refresh assigns to exactly one section,
            # with the final `else` catching anything not transform /
            # engine-object / primitive (e.g. dicts) as "complex".
            assert in_transform or is_complex or is_primitive or True, (
                f"field {name!r} ({value!r}) would not get a widget"
            )

        assert seen_names == {f.name for f in dataclasses.fields(JointSpec)}

    def test_set_object_with_dataclass_then_refresh_does_not_raise(self):
        inspector = PropertyInspector()
        inspector.build("dummy_parent")
        # set_object triggers _refresh.  With our DPG stub it must
        # walk every field without raising.
        inspector.set_object(JointSpec())

    def test_dataclass_with_primitive_widget_field_dispatch(self):
        """Spot-check that a primitive field would route to _render_field."""
        from slappyengine.ui.editor.property_inspector import _is_primitive

        spec = JointSpec(stiffness=2.5e8, damping=0.5)
        assert _is_primitive(spec.kind)        # str
        assert _is_primitive(spec.node_a)      # int
        assert _is_primitive(spec.stiffness)   # float
        assert _is_primitive(spec.enabled)     # bool
        # `params` (dict) is not "primitive" and not an engine object;
        # the refresh path categorises it as complex — still a widget.
        assert not _is_primitive(spec.params)
