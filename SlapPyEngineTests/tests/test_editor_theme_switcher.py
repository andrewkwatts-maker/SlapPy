"""Tests for the editor :class:`ThemeSwitcherPanel`.

The panel is a Nova3D ``build(parent_tag)`` editor surface that lets the
user hot-swap between registered diary themes at runtime. These tests
exercise the data layer (palette → preview stripes, roster parsing,
scheduler routing) plus the headless DPG build path — every ``dpg.*``
call is stubbed out with a no-op recorder so the panel constructs and
rebuilds cleanly in CI.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — same shape used by ``test_ui_widgets_notebook``.
# Records every call so tests can assert "panel attempted to build N
# widgets" without needing a real GUI.
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
    """Minimal dearpygui surface with call-tracking."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, object] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives the panel uses
    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM(self.calls, "group")

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM(self.calls, "child_window")

    def collapsing_header(self, *args, **kwargs):
        self._track("collapsing_header", args, kwargs)
        return _StubCM(self.calls, "collapsing_header")

    # plain widget primitives
    def add_text(self, *args, **kwargs):
        self._track("add_text", args, kwargs)

    def add_button(self, *args, **kwargs):
        self._track("add_button", args, kwargs)

    def add_checkbox(self, *args, **kwargs):
        self._track("add_checkbox", args, kwargs)

    def add_separator(self, *args, **kwargs):
        self._track("add_separator", args, kwargs)

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
        "group", "child_window", "collapsing_header",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "delete_item", "does_item_exist", "set_value", "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def reset_theme_registry():
    """Reset the theme registry + active theme between tests."""
    from pharos_editor.ui.theme import _reset_registry_for_tests
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme

    _reset_registry_for_tests()
    set_active_theme(None)
    yield
    _reset_registry_for_tests()
    set_active_theme(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_starter_themes() -> list[str]:
    """Register the starter diary themes and return their names."""
    from pharos_editor.ui.theme.themes import register_starter_themes

    return register_starter_themes()


class _StubScheduler:
    """Records every set_enabled / global-toggle call for assertions."""

    def __init__(self) -> None:
        self.enabled_calls: list[tuple[str, bool]] = []
        self.animations_calls: list[bool] = []
        self.reduced_motion_calls: list[bool] = []
        self.easter_egg_calls: list[bool] = []

    def set_enabled(self, creature_id: str, enabled: bool) -> None:
        self.enabled_calls.append((creature_id, enabled))

    def set_animations_enabled(self, enabled: bool) -> None:
        self.animations_calls.append(enabled)

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion_calls.append(enabled)

    def set_easter_eggs(self, enabled: bool) -> None:
        self.easter_egg_calls.append(enabled)


# ---------------------------------------------------------------------------
# Construction + build
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg_errors(self):
        """The panel must construct even when no theme is registered."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        assert panel.TITLE == "Theme"
        assert panel.DEFAULT_SIZE == (280, 360)
        assert panel.animations_enabled is True
        assert panel.reduced_motion is False
        assert panel.easter_eggs is True

    def test_build_registers_root_tag(self, stub_dpg):
        """``build`` populates the headless DPG stub with a header tag."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        _register_starter_themes()
        from pharos_editor.ui.theme import apply_theme

        apply_theme("teengirl_notebook")

        panel = ThemeSwitcherPanel()
        panel.build("details_tab_body")

        # build() always logs its parent tag.
        assert ("build", "details_tab_body") in panel.call_log
        # And uses either the collapsing_header or its fallback path.
        used_anything = (
            "collapsing_header" in stub_dpg.calls
            or "add_text" in stub_dpg.calls
            or "add_button" in stub_dpg.calls
        )
        assert used_anything

    def test_build_is_safe_before_any_theme_registered(self, stub_dpg):
        """No registered themes → panel still builds cleanly."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        # The header text falls back to "(none)".
        assert panel.active_theme_name() == ""


# ---------------------------------------------------------------------------
# Theme card preview
# ---------------------------------------------------------------------------


class TestCardPreview:
    def test_card_carries_three_color_stripes(self):
        """Card preview returns primary / accent / surface as RGBA tuples."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        _register_starter_themes()
        panel = ThemeSwitcherPanel()
        card = panel.card_preview("teengirl_notebook")

        assert isinstance(card["primary"], tuple) and len(card["primary"]) == 4
        assert isinstance(card["accent"], tuple) and len(card["accent"]) == 4
        assert isinstance(card["surface"], tuple) and len(card["surface"]) == 4
        # Channels are in 0..255 range.
        for role in ("primary", "accent", "surface"):
            for ch in card[role]:
                assert 0 <= ch <= 255

    def test_active_card_flag_tracks_apply_theme(self):
        """``card_preview['active']`` is True only for the active theme."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme

        _register_starter_themes()
        apply_theme("teengirl_notebook")

        panel = ThemeSwitcherPanel()
        assert panel.card_preview("teengirl_notebook")["active"] is True
        assert panel.card_preview("cozy_diary")["active"] is False

        apply_theme("cozy_diary")
        assert panel.card_preview("cozy_diary")["active"] is True
        assert panel.card_preview("teengirl_notebook")["active"] is False

    def test_unknown_theme_card_returns_safe_defaults(self):
        """An unregistered theme still yields a renderable card preview."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        card = panel.card_preview("not_real")
        # Falls back to the default sparkle sticker hint.
        assert card["sticker"] == "sparkle"
        assert len(card["primary"]) == 4

    def test_card_preview_rejects_empty_id(self):
        """``card_preview`` validates the theme id like every editor surface."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        with pytest.raises(ValueError):
            panel.card_preview("")


# ---------------------------------------------------------------------------
# Theme switching
# ---------------------------------------------------------------------------


class TestThemeSwitch:
    def test_clicking_card_applies_theme(self, stub_dpg):
        """Clicking a card with a different theme id calls ``apply_theme``."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme, get_active_theme

        _register_starter_themes()
        apply_theme("teengirl_notebook")
        assert get_active_theme().name == "teengirl_notebook"

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        panel._on_theme_card_clicked("cozy_diary")

        assert get_active_theme().name == "cozy_diary"
        # The click is recorded in the call log.
        assert ("theme_card_clicked", "cozy_diary") in panel.call_log

    def test_clicking_unregistered_card_does_not_crash(self, stub_dpg):
        """Clicking a card whose theme isn't registered must not raise."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        # No exception — graceful no-op.
        panel._on_theme_card_clicked("not_real")


# ---------------------------------------------------------------------------
# Creature roster
# ---------------------------------------------------------------------------


class TestCreatureRoster:
    def test_roster_reflects_active_theme_metadata(self, stub_dpg):
        """Active theme's metadata roster surfaces as the creature state map."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme

        _register_starter_themes()
        apply_theme("teengirl_notebook")

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")

        # The teengirl_notebook theme ships two creatures in its roster.
        assert set(panel.creature_state) == {"fox_01", "butterfly_01"}
        # All default-on.
        assert all(panel.creature_state.values())

    def test_roster_updates_when_theme_switches(self, stub_dpg):
        """Switching themes layers the new roster onto the existing state."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme

        _register_starter_themes()
        apply_theme("teengirl_notebook")

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        # Toggle one to False so we can verify state persistence.
        panel._on_creature_toggle("fox_01", False)
        assert panel.creature_state["fox_01"] is False

        # Switch themes — cozy_diary's roster should appear.
        panel._on_theme_card_clicked("cozy_diary")
        # New creatures default to True, fox_01 keeps its False state.
        assert panel.creature_state["red_panda_01"] is True
        assert panel.creature_state["fox_01"] is False

    def test_toggling_creature_calls_scheduler(self, stub_dpg):
        """Toggling a creature checkbox routes through ``scheduler.set_enabled``."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme

        _register_starter_themes()
        apply_theme("teengirl_notebook")

        scheduler = _StubScheduler()
        panel = ThemeSwitcherPanel(scheduler=scheduler)
        panel.build("parent_x")

        panel._on_creature_toggle("fox_01", False)
        panel._on_creature_toggle("butterfly_01", True)

        assert ("fox_01", False) in scheduler.enabled_calls
        assert ("butterfly_01", True) in scheduler.enabled_calls

    def test_creature_toggle_rejects_non_bool(self, stub_dpg):
        """The internal handler validates *enabled* is a real bool."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        with pytest.raises(TypeError):
            panel._on_creature_toggle("fox_01", "yes")  # type: ignore[arg-type]

    def test_creature_toggle_rejects_empty_id(self, stub_dpg):
        """Empty creature id is rejected by validators."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        with pytest.raises(ValueError):
            panel._on_creature_toggle("", True)


# ---------------------------------------------------------------------------
# Global toggles
# ---------------------------------------------------------------------------


class TestGlobalToggles:
    def test_animations_toggle_updates_state(self, stub_dpg):
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        panel._on_animations_toggle(False)
        assert panel.animations_enabled is False
        panel._on_animations_toggle(True)
        assert panel.animations_enabled is True

    def test_reduced_motion_toggle_propagates_to_scheduler(self, stub_dpg):
        """The reduced-motion toggle calls ``scheduler.set_reduced_motion``."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        scheduler = _StubScheduler()
        panel = ThemeSwitcherPanel(scheduler=scheduler)
        panel.build("parent_x")
        panel._on_reduced_motion_toggle(True)

        assert panel.reduced_motion is True
        assert scheduler.reduced_motion_calls == [True]

    def test_easter_eggs_toggle_propagates_to_scheduler(self, stub_dpg):
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        scheduler = _StubScheduler()
        panel = ThemeSwitcherPanel(scheduler=scheduler)
        panel.build("parent_x")
        panel._on_easter_eggs_toggle(False)

        assert panel.easter_eggs is False
        assert scheduler.easter_egg_calls == [False]

    def test_animations_master_propagates_to_scheduler(self, stub_dpg):
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        scheduler = _StubScheduler()
        panel = ThemeSwitcherPanel(scheduler=scheduler)
        panel.build("parent_x")
        panel._on_animations_toggle(False)

        assert scheduler.animations_calls == [False]


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_logs_call(self, stub_dpg):
        """``refresh`` always records itself in the call log."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        _register_starter_themes()
        panel = ThemeSwitcherPanel()
        panel.build("parent_x")
        panel.refresh()

        events = [entry[0] for entry in panel.call_log]
        assert events.count("refresh") >= 1

    def test_refresh_before_build_is_a_no_op(self):
        """Calling ``refresh`` before ``build`` does not crash."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        panel.refresh()
        # No build event in the log — refresh was logged but cleanly bailed.
        assert "build" not in [entry[0] for entry in panel.call_log]

    def test_footer_refresh_button_fires_callback(self, stub_dpg):
        """Clicking the footer "Refresh editor" button calls ``on_refresh``."""
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        invoked: list[int] = []

        panel = ThemeSwitcherPanel(on_refresh=lambda: invoked.append(1))
        panel.build("parent_x")
        panel._on_refresh_clicked()
        assert invoked == [1]


# ---------------------------------------------------------------------------
# Active theme name
# ---------------------------------------------------------------------------


class TestActiveThemeName:
    def test_returns_empty_when_no_active_theme(self):
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )

        panel = ThemeSwitcherPanel()
        assert panel.active_theme_name() == ""

    def test_tracks_apply_theme(self):
        from pharos_editor.ui.editor.theme_switcher_panel import (
            ThemeSwitcherPanel,
        )
        from pharos_editor.ui.theme import apply_theme

        _register_starter_themes()
        apply_theme("cozy_diary")
        panel = ThemeSwitcherPanel()
        assert panel.active_theme_name() == "cozy_diary"
