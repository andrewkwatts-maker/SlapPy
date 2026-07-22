"""Tests for MaterialEditor's three-kind discriminator (Phase A).

The editor auto-detects which "kind" of material target it has and
renders accordingly:

- ``"material_map"`` — :class:`pharos_engine.material.map.MaterialMap`
- ``"softbody"``     — a ``softbody.Material`` dataclass (stubbed here)
- ``"fluid"``        — a ``fluid.FluidMaterial`` dataclass (stubbed here)

These tests stand in stubs for the softbody/fluid dataclasses (they
live in modules that may not exist yet in this checkout) and verify
that the editor builds a non-empty widget tree for each.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field

import pytest


# ---------------------------------------------------------------------------
# DPG stub
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """No-op dearpygui with widget-creation tracking so we can assert
    that something *was* built per kind."""

    created_widgets: list[tuple[str, tuple, dict]] = []

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _NoOp:
        def __getattr__(self, name):
            def _fn(*a, **kw):
                if name.startswith("add_"):
                    created_widgets.append((name, a, kw))
                return _Ctx()
            return _fn

        def does_item_exist(self, *a, **kw):
            return True

        def delete_item(self, *a, **kw):
            return None

    inst = _NoOp()
    stub = types.ModuleType("dearpygui.dearpygui")
    stub.__getattr__ = lambda name: getattr(inst, name)
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = inst
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", inst)

    # Expose for tests via the stub object itself.
    inst.created_widgets = created_widgets
    yield inst


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

try:
    from pharos_engine.ui.editor.material_editor import (
        MaterialEditor,
        KIND_MATERIAL_MAP,
        KIND_SOFTBODY,
        KIND_FLUID,
        _detect_kind,
    )
    from pharos_engine.material.map import MaterialMap, ColorRange
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"material editor deps not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Stub softbody.Material and fluid.FluidMaterial in sys.modules so type
# detection works.  Both are simple dataclasses with primitive fields.
# ---------------------------------------------------------------------------

def _install_softbody_stub():
    # Always override the Material class in sys.modules — if the real
    # pharos_engine.softbody is already imported it carries a strict
    # 7-positional-arg dataclass that breaks our default ctor. We force
    # the stub onto the existing or new module entry.
    mod = sys.modules.get("pharos_engine.softbody")
    if mod is None:
        mod = types.ModuleType("pharos_engine.softbody")
        sys.modules["pharos_engine.softbody"] = mod

    @dataclass
    class Material:
        name: str = "rubber"
        color: tuple[float, float, float, float] = (0.3, 0.3, 0.3, 1.0)
        density: float = 1.0
        stiffness: float = 1.0e9
        damping: float = 0.02
        plasticity: float = 0.0

    # _detect_kind reads type(target).__module__ — set it so the
    # synthetic dataclass behaves like a real softbody.* member.
    Material.__module__ = "pharos_engine.softbody"
    mod.Material = Material
    return mod


def _install_fluid_stub():
    mod = sys.modules.get("pharos_engine.fluid")
    if mod is None:
        mod = types.ModuleType("pharos_engine.fluid")
        sys.modules["pharos_engine.fluid"] = mod

    @dataclass
    class FluidMaterial:
        name: str = "water"
        color: tuple[float, float, float, float] = (0.1, 0.4, 0.8, 0.6)
        viscosity: float = 0.01
        surface_tension: float = 0.07
        rest_density: float = 1000.0

    FluidMaterial.__module__ = "pharos_engine.fluid"
    mod.FluidMaterial = FluidMaterial
    return mod


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestKindDetection:
    def test_materialmap_detected(self):
        mm = MaterialMap()
        assert _detect_kind(mm) == KIND_MATERIAL_MAP

    def test_softbody_material_detected(self):
        mod = _install_softbody_stub()
        mat = mod.Material()
        assert _detect_kind(mat) == KIND_SOFTBODY

    def test_fluid_material_detected(self):
        mod = _install_fluid_stub()
        mat = mod.FluidMaterial()
        assert _detect_kind(mat) == KIND_FLUID


# ---------------------------------------------------------------------------
# Rendering tests — assert non-empty widget tree for each kind.
# ---------------------------------------------------------------------------

class TestMaterialEditorKinds:
    def _new_editor(self) -> MaterialEditor:
        return MaterialEditor()

    def test_materialmap_produces_widgets(self, stub_dearpygui):
        ed = self._new_editor()
        mm = MaterialMap()
        mm.add("water", ColorRange(), behaviors=["fluid"])
        ed.build("parent_tag")
        ed.set_material_map(mm)
        assert ed._kind == KIND_MATERIAL_MAP
        # At least the title + the material header should have been added.
        names = [w[0] for w in stub_dearpygui.created_widgets]
        assert any("add_text" in n for n in names)

    def test_softbody_material_produces_widgets(self, stub_dearpygui):
        mod = _install_softbody_stub()
        ed = self._new_editor()
        ed.build("parent_tag")
        ed.set_target(mod.Material())
        assert ed._kind == KIND_SOFTBODY
        names = [w[0] for w in stub_dearpygui.created_widgets]
        # Dataclass-reflection path adds an inspector child_window and
        # at least one field widget.
        assert names, "expected at least one widget to be created"

    def test_fluid_material_produces_widgets(self, stub_dearpygui):
        mod = _install_fluid_stub()
        ed = self._new_editor()
        ed.build("parent_tag")
        ed.set_target(mod.FluidMaterial())
        assert ed._kind == KIND_FLUID
        names = [w[0] for w in stub_dearpygui.created_widgets]
        assert names, "expected at least one widget to be created"

    def test_set_target_with_explicit_kind_overrides_detection(self):
        mm = MaterialMap()
        ed = self._new_editor()
        ed.set_target(mm, kind=KIND_SOFTBODY)
        assert ed._kind == KIND_SOFTBODY

    def test_add_material_noop_for_dataclass_kinds(self):
        mod = _install_softbody_stub()
        ed = self._new_editor()
        ed.set_target(mod.Material())
        # Should not raise and should not mutate anything.
        ed._add_material()
