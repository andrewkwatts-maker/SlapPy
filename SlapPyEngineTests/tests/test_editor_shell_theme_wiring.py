"""Smoke tests for the editor shell's theme + creature wiring.

These tests exercise :meth:`EditorShell.setup_theme_subsystem` —
the headless slice of :meth:`EditorShell.setup` that registers the
starter themes, builds the creature scheduler, installs the bus
adapter, spawns the idle emitter, and registers the
:class:`ThemeSwitcherPanel`. The full ``setup`` method requires a real
Dear PyGui context, so we drive the subsystem entry point directly —
the production ``setup`` calls the same method as its first action.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_theme_registry():
    """Drop the registry + active theme + module-level scheduler."""
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.widgets.notebook_theme import set_active_theme
    from slappyengine.ui.theme.creatures import _reset_default_scheduler_for_tests

    _reset_registry_for_tests()
    set_active_theme(None)
    _reset_default_scheduler_for_tests()
    yield
    _reset_registry_for_tests()
    set_active_theme(None)
    _reset_default_scheduler_for_tests()


@pytest.fixture
def isolated_bus(monkeypatch):
    """Replace the module-level default bus with a fresh one per test.

    The :class:`CreatureBusAdapter` subscribes on
    :func:`slappyengine.event_bus.get_default_bus`; we swap the
    underlying singleton so handlers landing in one test do not leak
    into the next.
    """
    from slappyengine import event_bus as eb

    fresh = eb.EventBus()
    monkeypatch.setattr(eb, "_DEFAULT_BUS", fresh)
    return fresh


def _make_shell(ui_settings=None):
    """Build an :class:`EditorShell` with a minimal engine stub.

    The shell only stores the engine reference until ``run`` — we can
    hand in any object that satisfies ``hasattr`` lookups.
    """
    from slappyengine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    shell = EditorShell(_StubEngine(), ui_settings=ui_settings)
    return shell


# ---------------------------------------------------------------------------
# UISettings dataclass — module under test #1
# ---------------------------------------------------------------------------


class TestUISettings:
    def test_default_values(self):
        from slappyengine.ui.editor.settings import UISettings

        settings = UISettings()
        assert settings.default_theme == "teengirl_notebook"
        assert settings.creature_animations is True
        assert settings.reduced_motion is False
        assert settings.easter_eggs is True

    def test_override_default_theme(self):
        from slappyengine.ui.editor.settings import UISettings

        settings = UISettings(default_theme="cozy_diary")
        assert settings.default_theme == "cozy_diary"

    def test_empty_default_theme_rejected(self):
        from slappyengine.ui.editor.settings import UISettings

        with pytest.raises(ValueError):
            UISettings(default_theme="")

    def test_non_bool_creature_animations_rejected(self):
        from slappyengine.ui.editor.settings import UISettings

        with pytest.raises(TypeError):
            UISettings(creature_animations=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Theme registration + apply
# ---------------------------------------------------------------------------


class TestThemeRegistration:
    def test_starter_themes_registered(self, isolated_bus):
        from slappyengine.ui.theme import list_registered_themes

        shell = _make_shell()
        shell.setup_theme_subsystem()

        names = list_registered_themes()
        assert "teengirl_notebook" in names
        assert "cozy_diary" in names
        assert "bullet_journal" in names

    def test_default_theme_applied(self, isolated_bus):
        from slappyengine.ui.theme import get_active_theme

        shell = _make_shell()
        shell.setup_theme_subsystem()

        assert get_active_theme().name == "teengirl_notebook"

    def test_default_theme_override_honored(self, isolated_bus):
        from slappyengine.ui.editor.settings import UISettings
        from slappyengine.ui.theme import get_active_theme

        shell = _make_shell(UISettings(default_theme="cozy_diary"))
        shell.setup_theme_subsystem()

        assert get_active_theme().name == "cozy_diary"

    def test_unknown_default_theme_falls_back(self, isolated_bus):
        """A bad ``default_theme`` falls back to a registered name."""
        from slappyengine.ui.editor.settings import UISettings
        from slappyengine.ui.theme import get_active_theme, list_registered_themes

        shell = _make_shell(UISettings(default_theme="not_a_real_theme"))
        shell.setup_theme_subsystem()

        active = get_active_theme().name
        assert active in list_registered_themes()


# ---------------------------------------------------------------------------
# Panel registration
# ---------------------------------------------------------------------------


class TestPanelRegistration:
    def test_theme_switcher_registered(self, isolated_bus):
        from slappyengine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel

        shell = _make_shell()
        shell.setup_theme_subsystem()

        # Exactly one ThemeSwitcherPanel must be registered.
        switchers = [p for p in shell._panels if isinstance(p, ThemeSwitcherPanel)]
        assert len(switchers) == 1
        assert shell._theme_switcher_panel is switchers[0]

    def test_theme_switcher_bound_to_scheduler(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        panel = shell._theme_switcher_panel
        assert panel is not None
        assert panel._scheduler is shell._creature_scheduler


# ---------------------------------------------------------------------------
# Notebook panel family — Nova3D variants must not be wired
# ---------------------------------------------------------------------------


class TestNotebookPanelsAreExclusive:
    """The shell must wire Notebook* panels and never the Nova3D siblings."""

    def test_notebook_toolbar_registered(self, isolated_bus):
        from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar
        from slappyengine.ui.editor.toolbar import EditorToolbar

        shell = _make_shell()
        shell.setup_theme_subsystem()
        shell.setup_notebook_panels()

        assert isinstance(shell._toolbar, NotebookToolbar)
        assert not isinstance(shell._toolbar, EditorToolbar)

    def test_notebook_outliner_registered(self, isolated_bus):
        from slappyengine.ui.editor.notebook_outliner import NotebookOutliner
        from slappyengine.ui.editor.scene_outliner import SceneOutliner

        shell = _make_shell()
        shell.setup_theme_subsystem()
        shell.setup_notebook_panels()

        assert isinstance(shell._scene_outliner, NotebookOutliner)
        assert not isinstance(shell._scene_outliner, SceneOutliner)

    def test_notebook_inspector_registered(self, isolated_bus):
        from slappyengine.ui.editor.notebook_inspector import NotebookInspector
        from slappyengine.ui.editor.property_inspector import PropertyInspector

        shell = _make_shell()
        shell.setup_theme_subsystem()
        shell.setup_notebook_panels()

        assert isinstance(shell._inspector, NotebookInspector)
        assert not isinstance(shell._inspector, PropertyInspector)
        # The inspector must also be registered on the Details sidebar.
        inspectors = [
            p for p in shell._panels if isinstance(p, NotebookInspector)
        ]
        assert len(inspectors) == 1
        assert inspectors[0] is shell._inspector

    def test_notebook_gizmo_overlay_wired(self, isolated_bus):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        from slappyengine.ui.editor.notebook_gizmos import NotebookGizmoOverlay

        shell = _make_shell()
        shell.setup_theme_subsystem()
        shell.setup_notebook_panels()

        assert isinstance(shell._gizmo_overlay, NotebookGizmoOverlay)
        assert not isinstance(shell._gizmo_overlay, GizmoOverlay)

    def test_nova3d_apply_dark_theme_not_called_during_boot(
        self, isolated_bus, monkeypatch
    ):
        """``slappyengine.ui.editor.theme.apply_editor_theme`` must not run."""
        from slappyengine.ui.editor import theme as nova_theme

        calls: list[str] = []

        def _tripwire():
            calls.append("apply_editor_theme")

        monkeypatch.setattr(nova_theme, "apply_editor_theme", _tripwire)

        shell = _make_shell()
        shell.setup_theme_subsystem()
        shell.setup_notebook_panels()

        # Neither the theme nor the notebook-panel wiring may invoke the
        # legacy Nova3D dark-theme entrypoint.
        assert calls == []

    def test_active_theme_is_a_diary_variant(self, isolated_bus):
        from slappyengine.ui.theme import get_active_theme

        shell = _make_shell()
        shell.setup_theme_subsystem()

        # Default UISettings.default_theme is "teengirl_notebook" — one
        # of the diary family. The fallback branch must still land on a
        # diary-family theme name.
        diary_family = {
            "teengirl_notebook",
            "cozy_diary",
            "bullet_journal",
            "scrapbook_summer",
            "cottagecore_garden",
            "kawaii_planner",
        }
        active = get_active_theme()
        assert active is not None
        assert active.name in diary_family


# ---------------------------------------------------------------------------
# Creature scheduler + builtins
# ---------------------------------------------------------------------------


class TestCreatureScheduler:
    def test_builtins_registered(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        sched = shell._creature_scheduler
        assert sched is not None
        ids = set(sched.registered_ids)
        assert {"fox_01", "butterfly_01", "sparkle"} <= ids

    def test_scheduler_respects_animations_setting(self, isolated_bus):
        from slappyengine.ui.editor.settings import UISettings

        shell = _make_shell(UISettings(creature_animations=False))
        shell.setup_theme_subsystem()

        assert shell._creature_scheduler.is_enabled is False

    def test_scheduler_respects_reduced_motion_setting(self, isolated_bus):
        from slappyengine.ui.editor.settings import UISettings

        shell = _make_shell(UISettings(reduced_motion=True))
        shell.setup_theme_subsystem()

        assert shell._creature_scheduler.is_reduced_motion is True


# ---------------------------------------------------------------------------
# Bus adapter
# ---------------------------------------------------------------------------


class TestBusAdapter:
    def test_adapter_installed(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        adapter = shell._creature_bus_adapter
        assert adapter is not None
        assert adapter.installed is True
        # Must subscribe to ``engine.save`` (the butterfly_01/flutter binding).
        assert "engine.save" in adapter.subscribed_events

    def test_publishing_engine_save_triggers_animation(self, isolated_bus):
        """Publishing the bound event must fire a creature animation."""
        shell = _make_shell()
        shell.setup_theme_subsystem()

        sched = shell._creature_scheduler
        # No animations active before the event.
        assert sched.active_count == 0

        isolated_bus.publish("engine.save")

        # butterfly_01 should now be mid-animation.
        assert sched.active_count >= 1


# ---------------------------------------------------------------------------
# Idle emitter
# ---------------------------------------------------------------------------


class TestIdleEmitter:
    def test_emitter_created(self, isolated_bus):
        from slappyengine.ui.theme.creatures import IdleEventEmitter

        shell = _make_shell()
        shell.setup_theme_subsystem()

        assert isinstance(shell._idle_emitter, IdleEventEmitter)
        assert shell._idle_emitter.idle_seconds == 0.0

    def test_emitter_ticks_with_tick_subsystems(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        shell.tick_subsystems(0.25)
        # Idle emitter must have absorbed the tick.
        assert shell._idle_emitter.idle_seconds == pytest.approx(0.25, abs=1e-9)

    def test_notify_user_activity_resets_idle(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        shell.tick_subsystems(10.0)
        assert shell._idle_emitter.idle_seconds == pytest.approx(10.0, abs=1e-9)

        shell.notify_user_activity()
        assert shell._idle_emitter.idle_seconds == 0.0

    def test_idle_60s_event_publishes(self, isolated_bus):
        """Accumulating 60+ seconds of idle time fires ``engine.idle_60s``."""
        events: list[dict] = []
        isolated_bus.subscribe("engine.idle_60s", lambda payload: events.append(payload))

        shell = _make_shell()
        shell.setup_theme_subsystem()

        shell.tick_subsystems(65.0)
        assert len(events) == 1
        assert events[0]["idle_seconds"] >= 60.0

    def test_notify_user_activity_safe_before_setup(self):
        """Calling notify_user_activity before setup must not raise."""
        shell = _make_shell()
        # No setup_theme_subsystem yet — idle_emitter is None.
        shell.notify_user_activity()


# ---------------------------------------------------------------------------
# tick_subsystems integration
# ---------------------------------------------------------------------------


class TestTickSubsystems:
    def test_tick_subsystems_advances_scheduler(self, isolated_bus):
        shell = _make_shell()
        shell.setup_theme_subsystem()

        # Drive a non-zero tick — must not raise.
        shell.tick_subsystems(1.0 / 60.0)

    def test_tick_subsystems_renders_when_draw_list_supplied(self, isolated_bus):
        """Passing a draw_list routes through scheduler.render."""
        calls: list[tuple] = []

        def _render_fn(draw_list, x, y, phase):
            calls.append((draw_list, x, y, phase))

        shell = _make_shell()
        shell.setup_theme_subsystem()
        # Replace each creature's render_fn with a recorder so we can
        # assert render() was called.
        for rec in shell._creature_scheduler._slots.values():
            rec.creature.render_fn = _render_fn

        sentinel = object()
        shell.tick_subsystems(1.0 / 60.0, draw_list=sentinel)

        # One render per registered creature.
        assert len(calls) >= 3
        assert all(call[0] is sentinel for call in calls)
