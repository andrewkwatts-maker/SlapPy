"""Tests for the notebook-themed welcome / splash screen.

The welcome panel is a Nova3D ``build(parent_tag)`` editor surface that
introduces Pharos Engine on first launch. Coverage:

* Construction
    - Constructs without DPG errors.
    - Rejects non-callable callbacks at the boundary.
* First-run detection
    - True on fresh settings; flips False after :meth:`mark_seen`.
    - ``welcome_shown=True`` from the start suppresses first-run.
* Layout
    - All 3 demo cards present in render order.
    - All 6 theme swatches present in render order.
* Callbacks
    - Click demo card fires ``on_open_demo`` with the correct id
      *and* dismisses *and* marks seen.
    - Click theme swatch applies the theme + dismisses.
    - ``Start drawing!`` fires ``on_start_blank`` + dismisses.
* HeartCheckbox
    - Toggle updates ``settings.welcome_shown``.
* Sparkle creature integration
    - Sparkle appears in the built-in roster.
    - ``tick_sparkle()`` is a no-op when no scheduler is bound.
    - ``tick_sparkle()`` routes through the scheduler when bound.
* Settings extension
    - ``UISettings.welcome_shown`` defaults to False.
    - ``UISettings.last_opened_demo`` defaults to "".
    - Opening a demo writes ``last_opened_demo``.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "collapsing_header",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_state(stub_dpg):
    """Reset theme + sticker registry between tests."""
    from pharos_editor.ui.widgets import notebook_theme
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme
    from pharos_editor.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()


# ---------------------------------------------------------------------------
# Lightweight fakes
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Build a fresh :class:`UISettings` with optional field overrides."""
    from pharos_editor.ui.editor.settings import UISettings

    return UISettings(**overrides)


class _CallbackRecorder:
    def __init__(self) -> None:
        self.start_blank_calls: int = 0
        self.open_demo_calls: list[str] = []
        self.dismiss_calls: int = 0

    def start_blank(self) -> None:
        self.start_blank_calls += 1

    def open_demo(self, demo_id: str) -> None:
        self.open_demo_calls.append(demo_id)

    def dismiss(self) -> None:
        self.dismiss_calls += 1


def _make_welcome(settings=None, callbacks=None):
    """Construct a :class:`NotebookWelcome` with sensible defaults."""
    from pharos_editor.ui.editor.notebook_welcome import NotebookWelcome

    settings = settings or _make_settings()
    callbacks = callbacks or _CallbackRecorder()
    welcome = NotebookWelcome(
        settings=settings,
        on_start_blank=callbacks.start_blank,
        on_open_demo=callbacks.open_demo,
        on_dismiss=callbacks.dismiss,
    )
    return welcome, settings, callbacks


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg_errors(self):
        welcome, _, _ = _make_welcome()
        assert welcome.TITLE == "Welcome"
        assert welcome.WIDTH == 600
        assert welcome.HEIGHT == 500

    def test_rejects_non_callable_on_start_blank(self):
        from pharos_editor.ui.editor.notebook_welcome import NotebookWelcome

        with pytest.raises(TypeError):
            NotebookWelcome(
                settings=_make_settings(),
                on_start_blank="nope",  # type: ignore[arg-type]
                on_open_demo=lambda d: None,
                on_dismiss=lambda: None,
            )

    def test_rejects_non_callable_on_open_demo(self):
        from pharos_editor.ui.editor.notebook_welcome import NotebookWelcome

        with pytest.raises(TypeError):
            NotebookWelcome(
                settings=_make_settings(),
                on_start_blank=lambda: None,
                on_open_demo="nope",  # type: ignore[arg-type]
                on_dismiss=lambda: None,
            )

    def test_rejects_non_callable_on_dismiss(self):
        from pharos_editor.ui.editor.notebook_welcome import NotebookWelcome

        with pytest.raises(TypeError):
            NotebookWelcome(
                settings=_make_settings(),
                on_start_blank=lambda: None,
                on_open_demo=lambda d: None,
                on_dismiss="nope",  # type: ignore[arg-type]
            )

    def test_build_completes_without_dpg_errors(self, stub_dpg):
        welcome, _, _ = _make_welcome()
        welcome.build("editor_root")
        # build should have produced at least one widget call.
        any_calls = (
            "add_text" in stub_dpg.calls
            or "add_button" in stub_dpg.calls
            or "child_window" in stub_dpg.calls
        )
        assert any_calls


# ---------------------------------------------------------------------------
# First-run detection
# ---------------------------------------------------------------------------


class TestFirstRun:
    def test_first_run_true_on_fresh_settings(self):
        welcome, _, _ = _make_welcome()
        assert welcome.is_first_run() is True

    def test_first_run_false_after_mark_seen(self):
        welcome, settings, _ = _make_welcome()
        welcome.mark_seen()
        assert welcome.is_first_run() is False
        assert settings.welcome_shown is True

    def test_first_run_false_when_settings_already_shown(self):
        welcome, _, _ = _make_welcome(
            settings=_make_settings(welcome_shown=True),
        )
        assert welcome.is_first_run() is False


# ---------------------------------------------------------------------------
# Demo cards
# ---------------------------------------------------------------------------


class TestDemoCards:
    def test_all_three_demo_cards_present(self):
        welcome, _, _ = _make_welcome()
        ids = welcome.demo_card_ids
        assert ids == ["ragdoll", "rope", "studio"]

    def test_demo_cards_render_into_dpg_stub(self, stub_dpg):
        welcome, _, _ = _make_welcome()
        welcome.build("editor_root")
        buttons = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label") for _, kw in buttons]
        assert "ragdoll" in labels
        assert "rope" in labels
        assert "studio" in labels

    def test_click_demo_card_fires_on_open_demo(self):
        welcome, _, callbacks = _make_welcome()
        welcome._on_demo_card_clicked("rope")
        assert callbacks.open_demo_calls == ["rope"]

    def test_click_demo_card_writes_last_opened_demo(self):
        welcome, settings, _ = _make_welcome()
        welcome._on_demo_card_clicked("studio")
        assert settings.last_opened_demo == "studio"

    def test_click_demo_card_marks_seen_and_dismisses(self):
        welcome, settings, callbacks = _make_welcome()
        welcome._on_demo_card_clicked("ragdoll")
        assert settings.welcome_shown is True
        assert callbacks.dismiss_calls == 1


# ---------------------------------------------------------------------------
# Theme swatches
# ---------------------------------------------------------------------------


class TestThemeSwatches:
    def test_six_swatches_present(self):
        welcome, _, _ = _make_welcome()
        assert len(welcome.theme_swatch_ids) == 6

    def test_swatch_ids_match_diary_family(self):
        welcome, _, _ = _make_welcome()
        assert welcome.theme_swatch_ids == [
            "teengirl_notebook",
            "cozy_diary",
            "bullet_journal",
            "scrapbook_summer",
            "cottagecore_garden",
            "kawaii_planner",
        ]

    def test_swatches_render_buttons(self, stub_dpg):
        welcome, _, _ = _make_welcome()
        welcome.build("editor_root")
        buttons = stub_dpg.calls.get("add_button", [])
        tags = [kw.get("tag") for _, kw in buttons]
        for theme_id in welcome.theme_swatch_ids:
            assert any(theme_id in (t or "") for t in tags), (
                f"missing swatch for {theme_id}; tags={tags!r}"
            )

    def test_click_swatch_applies_theme_and_dismisses(self):
        # Register starter themes so apply_theme can resolve the id.
        from pharos_editor.ui.theme import (
            _reset_registry_for_tests,
            get_active_theme,
        )
        from pharos_editor.ui.theme.themes import register_starter_themes

        _reset_registry_for_tests()
        register_starter_themes()

        welcome, settings, callbacks = _make_welcome()
        welcome._on_theme_swatch_clicked("cozy_diary")
        assert get_active_theme().name == "cozy_diary"
        assert settings.welcome_shown is True
        assert callbacks.dismiss_calls == 1

        _reset_registry_for_tests()


# ---------------------------------------------------------------------------
# Start drawing button
# ---------------------------------------------------------------------------


class TestStartDrawing:
    def test_start_button_fires_callback_and_dismisses(self):
        welcome, settings, callbacks = _make_welcome()
        welcome._on_start_blank_clicked()
        assert callbacks.start_blank_calls == 1
        assert callbacks.dismiss_calls == 1
        assert settings.welcome_shown is True


# ---------------------------------------------------------------------------
# HeartCheckbox hide toggle
# ---------------------------------------------------------------------------


class TestHideCheckbox:
    def test_hide_checkbox_is_heart_checkbox(self):
        from pharos_editor.ui.widgets.heart_checkbox import HeartCheckbox

        welcome, _, _ = _make_welcome()
        assert isinstance(welcome.hide_checkbox, HeartCheckbox)

    def test_toggle_updates_welcome_shown(self):
        welcome, settings, _ = _make_welcome()
        assert settings.welcome_shown is False
        welcome.hide_checkbox.toggle()
        assert settings.welcome_shown is True

    def test_set_value_updates_welcome_shown(self):
        welcome, settings, _ = _make_welcome()
        welcome.hide_checkbox.set_value(True)
        assert settings.welcome_shown is True
        welcome.hide_checkbox.set_value(False)
        assert settings.welcome_shown is False


# ---------------------------------------------------------------------------
# Sparkle creature integration
# ---------------------------------------------------------------------------


class TestSparkleCreature:
    def test_sparkle_in_builtin_roster(self):
        from pharos_editor.ui.theme.creatures import CreatureScheduler
        from pharos_editor.ui.theme.creatures.builtin import register_builtins

        scheduler = CreatureScheduler()
        register_builtins(scheduler)
        assert "sparkle" in scheduler.registered_ids

    def test_tick_sparkle_noop_without_scheduler(self):
        welcome, _, _ = _make_welcome()
        assert welcome.tick_sparkle() is False
        assert welcome.sparkle_trigger_count == 0

    def test_tick_sparkle_routes_through_bound_scheduler(self):
        from pharos_editor.ui.theme.creatures import CreatureScheduler
        from pharos_editor.ui.theme.creatures.builtin import register_builtins

        scheduler = CreatureScheduler()
        register_builtins(scheduler)

        welcome, _, _ = _make_welcome()
        welcome.bind_creature_scheduler(scheduler)
        ok = welcome.tick_sparkle()
        assert ok is True
        assert welcome.sparkle_trigger_count == 1


# ---------------------------------------------------------------------------
# UISettings extension
# ---------------------------------------------------------------------------


class TestSettings:
    def test_welcome_shown_defaults_false(self):
        s = _make_settings()
        assert s.welcome_shown is False

    def test_last_opened_demo_defaults_empty(self):
        s = _make_settings()
        assert s.last_opened_demo == ""

    def test_rejects_non_bool_welcome_shown(self):
        with pytest.raises(TypeError):
            _make_settings(welcome_shown="yes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dismiss + destroy cleanup
# ---------------------------------------------------------------------------


class TestDismissAndDestroy:
    def test_dismiss_fires_on_dismiss_callback(self):
        welcome, _, callbacks = _make_welcome()
        welcome.dismiss()
        assert callbacks.dismiss_calls == 1

    def test_dismiss_removes_sticker_corners(self, stub_dpg):
        from pharos_editor.ui.widgets.sticker_corner import list_sticker_corners

        welcome, _, _ = _make_welcome()
        welcome.build("editor_root")
        # At least one sticker is pinned on the panel.
        active_before = list_sticker_corners()
        panel_stickers = [
            s for s in active_before if welcome.panel_tag in s
        ]
        assert len(panel_stickers) >= 1
        welcome.dismiss()
        active_after = list_sticker_corners()
        for handle in panel_stickers:
            assert handle not in active_after

    def test_destroy_is_idempotent(self):
        welcome, _, _ = _make_welcome()
        welcome.destroy()
        # second call must not raise
        welcome.destroy()


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_demo_cards_exported(self):
        from pharos_editor.ui.editor.notebook_welcome import DEMO_CARDS

        assert isinstance(DEMO_CARDS, tuple)
        assert len(DEMO_CARDS) == 3

    def test_theme_swatches_exported(self):
        from pharos_editor.ui.editor.notebook_welcome import THEME_SWATCHES

        assert isinstance(THEME_SWATCHES, tuple)
        assert len(THEME_SWATCHES) == 6
