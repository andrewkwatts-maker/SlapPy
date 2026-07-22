"""Tests for :class:`NotebookMaterialEditor` — the "colour story page" reskin.

The editor wraps the Nova3D ``MaterialEditor`` kind-discriminator contract
in a journal-themed page with a swatch row, mood line, sticker preview,
96×96 px preview pane, and a delegated :class:`NotebookInspector` for
field reflection.

Every ``dpg.*`` call is stubbed with a no-op recorder so the editor
builds cleanly in CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — every method records itself for later assertions.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal dearpygui surface with call-tracking + tag bookkeeping."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives
    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM(self.calls, "group")

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM(self.calls, "child_window")

    def collapsing_header(self, *args, **kwargs):
        self._track("collapsing_header", args, kwargs)
        return _StubCM(self.calls, "collapsing_header")

    def popup(self, *args, **kwargs):
        self._track("popup", args, kwargs)
        return _StubCM(self.calls, "popup")

    # primitives
    def add_text(self, *args, **kwargs):
        self._track("add_text", args, kwargs)

    def add_button(self, *args, **kwargs):
        self._track("add_button", args, kwargs)

    def add_checkbox(self, *args, **kwargs):
        self._track("add_checkbox", args, kwargs)

    def add_separator(self, *args, **kwargs):
        self._track("add_separator", args, kwargs)

    def add_input_int(self, *args, **kwargs):
        self._track("add_input_int", args, kwargs)

    def add_input_float(self, *args, **kwargs):
        self._track("add_input_float", args, kwargs)

    def add_input_floatx(self, *args, **kwargs):
        self._track("add_input_floatx", args, kwargs)

    def add_input_text(self, *args, **kwargs):
        self._track("add_input_text", args, kwargs)

    def add_color_edit(self, *args, **kwargs):
        self._track("add_color_edit", args, kwargs)

    def add_listbox(self, *args, **kwargs):
        self._track("add_listbox", args, kwargs)

    def add_slider_float(self, *args, **kwargs):
        self._track("add_slider_float", args, kwargs)

    def add_child_window(self, *args, **kwargs):
        self._track("add_child_window", args, kwargs)

    def configure_item(self, tag, *args, **kwargs):
        self._track("configure_item", (tag, args), kwargs)

    def delete_item(self, tag, *args, **kwargs):
        self._track("delete_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *args, **kwargs):
        return tag in self.items

    def set_value(self, tag, value, *args, **kwargs):
        self._track("set_value", (tag, value), kwargs)
        self.values[tag] = value

    def get_item_children(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module for every test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "group", "child_window", "collapsing_header", "popup",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_int", "add_input_float", "add_input_floatx",
        "add_input_text", "add_color_edit", "add_listbox",
        "add_slider_float", "add_child_window", "configure_item",
        "delete_item", "does_item_exist", "set_value", "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def reset_notebook_theme():
    """Reset the notebook theme registry between tests."""
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    yield
    set_active_theme(None)


# ---------------------------------------------------------------------------
# Fixture dataclasses standing in for softbody / fluid materials.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SoftbodyMaterialLike:
    """Stands in for ``pharos_engine.softbody.material.Material``.

    The kind discriminator keys on the module path so we hand-set it
    via the test fixture below.
    """
    name: str = "rubber"
    density: float = 100.0
    stiffness: float = 1.0e7
    damping: float = 0.1
    break_strain: float = 0.5
    yield_strain: float = 0.1
    plasticity_rate: float = 0.0
    contact_thickness: float = 0.5
    contact_stiffness: float = 1.0e9
    render_color: tuple[int, int, int] = (180, 80, 80)
    damage_color: tuple[int, int, int] = (60, 20, 20)


@dataclass(frozen=True)
class _FluidMaterialLike:
    """Stands in for ``pharos_engine.fluid.material.FluidMaterial``."""
    name: str = "water"
    rest_density: float = 1000.0
    kernel_radius: float = 1.5
    relaxation_eps: float = 100.0
    viscosity: float = 0.5
    surface_tension: float = 1.0
    surface_tension_n: float = 1.0
    particle_mass: float = 1.0
    friction_coef: float = 0.0
    is_granular: bool = False
    render_color: tuple[int, int, int] = (60, 140, 220)
    halo_color: tuple[int, int, int] = (180, 220, 255)
    thermal_conductivity: float = 0.0
    ambient_temperature: float = 20.0
    melt_temperature: float = 1.0e9
    freeze_temperature: float = -1.0e9
    melt_to: str = ""
    freeze_to: str = ""


def _make_softbody(name: str = "rubber", **kwargs: Any) -> Any:
    """Return a softbody-Material-like object with the proper module path."""
    obj = _SoftbodyMaterialLike(name=name, **kwargs)
    # The kind detector keys on type.__module__ — but we can't change
    # a frozen dataclass's module without subclassing.  Wrap in a
    # fresh subclass whose ``__module__`` lies in the softbody domain.
    sb_mod = types.ModuleType("pharos_engine.softbody._test_material")
    SBSub = type("Material", (_SoftbodyMaterialLike,), {})
    SBSub.__module__ = "pharos_engine.softbody._test_material"
    sb_mod.Material = SBSub  # type: ignore[attr-defined]
    sys.modules["pharos_engine.softbody._test_material"] = sb_mod
    return SBSub(name=name, **kwargs)


def _make_fluid(name: str = "water", **kwargs: Any) -> Any:
    """Return a fluid-FluidMaterial-like object with the proper module path."""
    fl_mod = types.ModuleType("pharos_engine.fluid._test_material")
    FlSub = type("FluidMaterial", (_FluidMaterialLike,), {})
    FlSub.__module__ = "pharos_engine.fluid._test_material"
    fl_mod.FluidMaterial = FlSub  # type: ignore[attr-defined]
    sys.modules["pharos_engine.fluid._test_material"] = fl_mod
    return FlSub(name=name, **kwargs)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


try:
    from pharos_engine.ui.editor.notebook_material_editor import (
        NotebookMaterialEditor,
    )
    from pharos_engine.material.map import ColorRange, MaterialDef, MaterialMap
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"NotebookMaterialEditor not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Construction + lifecycle
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_target(self):
        """The editor must construct cleanly with no material bound."""
        editor = NotebookMaterialEditor()
        assert editor.target is None
        assert editor.TITLE == "Material"

    def test_constructs_with_softbody_target(self):
        mat = _make_softbody(name="rubber")
        editor = NotebookMaterialEditor(target=mat)
        assert editor.target is mat
        assert editor.kind == "softbody"

    def test_builds_without_dpg_errors(self, stub_dpg):
        """The editor builds with the headless stub and registers tags."""
        editor = NotebookMaterialEditor()
        editor.build("parent_x")
        events = [entry[0] for entry in editor.call_log]
        assert "build" in events


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class TestEmptyState:
    def test_empty_material_renders_empty_state(self, stub_dpg):
        """A ``None`` target triggers the empty-state pencil hint."""
        editor = NotebookMaterialEditor()
        editor.build("parent_x")
        events = [entry[0] for entry in editor.call_log]
        assert "empty_state" in events
        # No swatch row was registered.
        assert "story_header" not in events
        assert "swatch_row" not in events

    def test_empty_state_mood_mentions_colour(self, stub_dpg):
        editor = NotebookMaterialEditor()
        editor.build("parent_x")
        assert "colour" in editor.mood.lower() or "color" in editor.mood.lower()


# ---------------------------------------------------------------------------
# MaterialMap — two swatches + gradient
# ---------------------------------------------------------------------------


class TestMaterialMapKind:
    def _make_map(self) -> MaterialMap:
        mm = MaterialMap()
        mm.add(
            name="stone",
            color_range=ColorRange(r=(60, 120), g=(60, 120), b=(60, 120)),
            alpha_meaning="opacity",
            behaviors=["solid"],
        )
        return mm

    def test_material_map_shows_two_swatches(self, stub_dpg):
        editor = NotebookMaterialEditor(target=self._make_map())
        editor.build("parent_x")
        # Exactly two stops — low + high.
        assert len(editor.swatch_stops) == 2
        # The low stop is darker than the high stop component-wise.
        low, high = editor.swatch_stops
        assert sum(low[:3]) <= sum(high[:3])

    def test_material_map_swatch_color_edits_are_added(self, stub_dpg):
        editor = NotebookMaterialEditor(target=self._make_map())
        editor.build("parent_x")
        color_edits = stub_dpg.calls.get("add_color_edit", [])
        # At least one color_edit per stop.
        assert len(color_edits) >= 2

    def test_material_map_sticker_matches_stone_keyword(self, stub_dpg):
        editor = NotebookMaterialEditor(target=self._make_map())
        editor.build("parent_x")
        assert "mountain" in editor.sticker


# ---------------------------------------------------------------------------
# softbody.Material — render_color + damage_color
# ---------------------------------------------------------------------------


class TestSoftbodyKind:
    def test_softbody_shows_render_and_damage_colors(self, stub_dpg):
        mat = _make_softbody(
            name="rubber",
            render_color=(180, 80, 80),
            damage_color=(60, 20, 20),
        )
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        stops = editor.swatch_stops
        assert len(stops) == 2
        # Render colour is the first stop, damage the second.
        assert stops[0][:3] == (180, 80, 80)
        assert stops[1][:3] == (60, 20, 20)

    def test_softbody_sticker_matches_rubber(self, stub_dpg):
        mat = _make_softbody(name="rubber")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        assert "heart" in editor.sticker

    def test_softbody_mood_is_handwritten_phrase(self, stub_dpg):
        mat = _make_softbody(name="rubber")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        assert "squishy" in editor.mood.lower() or "bounces" in editor.mood.lower()


# ---------------------------------------------------------------------------
# fluid.FluidMaterial — 3-stop heuristic gradient
# ---------------------------------------------------------------------------


class TestFluidKind:
    def test_fluid_shows_three_stop_gradient(self, stub_dpg):
        mat = _make_fluid(
            name="water",
            rest_density=1000.0,
            viscosity=0.5,
            surface_tension=1.0,
        )
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        stops = editor.swatch_stops
        assert len(stops) == 3
        # All three stops are valid RGBA tuples.
        for c in stops:
            assert len(c) == 4
            assert all(0 <= ch <= 255 for ch in c)

    def test_fluid_high_viscosity_darkens_low_stop(self, stub_dpg):
        low_visc = _make_fluid(name="water", viscosity=0.0)
        high_visc = _make_fluid(name="water", viscosity=10.0)
        editor_lo = NotebookMaterialEditor(target=low_visc)
        editor_hi = NotebookMaterialEditor(target=high_visc)
        editor_lo.build("parent_a")
        editor_hi.build("parent_b")
        assert sum(editor_hi.swatch_stops[0][:3]) < sum(editor_lo.swatch_stops[0][:3])

    def test_fluid_sticker_matches_water(self, stub_dpg):
        mat = _make_fluid(name="water")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        assert "droplet" in editor.sticker


# ---------------------------------------------------------------------------
# Sticker + mood lookup tables
# ---------------------------------------------------------------------------


class TestStickerAndMoodTables:
    def test_lava_sticker_is_flame(self, stub_dpg):
        mat = _make_fluid(name="lava", viscosity=5.0)
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        assert "flame" in editor.sticker

    def test_unknown_name_falls_back_to_kind_default(self, stub_dpg):
        mat = _make_softbody(name="entirely_made_up_widget_material")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        # The softbody default is the heart sticker.
        assert "heart" in editor.sticker


# ---------------------------------------------------------------------------
# Fields delegated to NotebookInspector
# ---------------------------------------------------------------------------


class TestInspectorDelegation:
    def test_editable_fields_delegated_to_inspector(self, stub_dpg):
        mat = _make_softbody(name="wood")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        # The editor stashes the inspector reference.
        from pharos_engine.ui.editor.notebook_inspector import NotebookInspector

        assert isinstance(editor._inspector, NotebookInspector)
        # The inspector's target is the softbody material itself.
        assert editor._inspector.target is mat

    def test_material_map_inspector_reflects_first_def(self, stub_dpg):
        mm = MaterialMap()
        mm.add(
            name="stone",
            color_range=ColorRange(r=(60, 120), g=(60, 120), b=(60, 120)),
        )
        editor = NotebookMaterialEditor(target=mm)
        editor.build("parent_x")
        # The inspector reflects the first MaterialDef, not the
        # MaterialMap itself (so name / alpha_meaning / behaviours
        # get widgets).
        assert isinstance(editor._inspector._target, MaterialDef)


# ---------------------------------------------------------------------------
# Kind switching
# ---------------------------------------------------------------------------


class TestKindSwitch:
    def test_switching_to_fluid_updates_swatch_and_fields(self, stub_dpg):
        softbody = _make_softbody(name="rubber")
        fluid = _make_fluid(name="water")

        editor = NotebookMaterialEditor(target=softbody)
        editor.build("parent_x")
        assert editor.kind == "softbody"
        assert len(editor.swatch_stops) == 2

        editor.set_material(fluid)
        assert editor.kind == "fluid"
        assert len(editor.swatch_stops) == 3
        # The inspector now reflects the fluid material.
        assert editor._inspector is not None
        assert editor._inspector.target is fluid

    def test_set_target_logs_event(self, stub_dpg):
        editor = NotebookMaterialEditor()
        editor.build("parent_x")
        editor.set_material(_make_softbody(name="wood"))
        events = [e[0] for e in editor.call_log]
        assert "set_target" in events
        assert "refresh" in events


# ---------------------------------------------------------------------------
# Mood line + sticker rendering
# ---------------------------------------------------------------------------


class TestMoodLine:
    def test_mood_line_generated_from_material_name(self, stub_dpg):
        glass_mat = _make_softbody(name="glass")
        editor = NotebookMaterialEditor(target=glass_mat)
        editor.build("parent_x")
        # The mood for glass should mention "brittle" or "clear".
        m = editor.mood.lower()
        assert "brittle" in m or "clear" in m or "handle" in m

    def test_mood_falls_back_for_unknown_material(self, stub_dpg):
        mat = _make_softbody(name="zircon")
        editor = NotebookMaterialEditor(target=mat)
        editor.build("parent_x")
        # The fallback mentions the material name.
        assert "zircon" in editor.mood.lower()


# ---------------------------------------------------------------------------
# Refresh + preview
# ---------------------------------------------------------------------------


class TestRefreshAndPreview:
    def test_refresh_before_build_is_noop(self):
        editor = NotebookMaterialEditor(target=_make_softbody(name="wood"))
        editor.refresh()  # must not crash
        events = [e[0] for e in editor.call_log]
        assert "refresh" in events
        assert "build" not in events

    def test_preview_tag_registered_after_build(self, stub_dpg):
        editor = NotebookMaterialEditor(target=_make_softbody(name="wood"))
        editor.build("parent_x")
        assert editor._preview_tag in stub_dpg.items

    def test_swatch_row_tag_registered_after_build(self, stub_dpg):
        editor = NotebookMaterialEditor(target=_make_softbody(name="wood"))
        editor.build("parent_x")
        # Either the group container or per-swatch tags are present.
        any_swatch = any(
            tag.startswith(editor._swatch_tag) for tag in stub_dpg.items
        )
        assert any_swatch


# ---------------------------------------------------------------------------
# Theme switch
# ---------------------------------------------------------------------------


class TestThemeSwitch:
    def test_theme_change_triggers_repaint(self, stub_dpg):
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        editor = NotebookMaterialEditor(target=_make_softbody(name="rubber"))
        editor.build("parent_x")

        before_refreshes = sum(
            1 for e in editor.call_log if e[0] == "refresh"
        )
        editor.on_theme_change()
        after_refreshes = sum(
            1 for e in editor.call_log if e[0] == "refresh"
        )
        assert after_refreshes > before_refreshes

        # Installing a brand-new theme also doesn't crash a subsequent
        # refresh — sanity-check the integration.
        custom = NotebookTheme(
            name="custom_journal",
            palette={
                "washi":     (10, 20, 30, 255),
                "paper":     (1, 2, 3, 255),
                "ink":       (4, 5, 6, 255),
                "accent":    (7, 8, 9, 255),
                "highlight": (10, 11, 12, 200),
                "heart":     (13, 14, 15, 255),
            },
        )
        set_active_theme(custom)
        editor.refresh()
        # The editor still has its tags after the theme swap.
        assert editor._panel_tag in stub_dpg.items
