"""Tests for the notebook global-hotkey table.

Verifies the brief's contract:

* Table membership: Ctrl+S / Ctrl+Z / Ctrl+Y / Ctrl+N / Ctrl+O /
  F1 / F3 / F5 / F11 / S / T / R / C / H plus two easter eggs.
* Modifier normalisation: ``handle_key_event("s", ["Ctrl"])`` and
  ``handle_key_event("CTRL+S")`` both resolve to ``editor.save``.
* Easter-egg gating: Ctrl+Shift+F / Ctrl+Shift+B only fire the
  scheduler trigger when ``settings.ui.easter_eggs`` is True.
* Dispatcher is invoked exactly once per matching event.
* Unknown bindings return False without raising.
"""
from __future__ import annotations

import pytest

from slappyengine.ui.editor.notebook_hotkeys import (
    NotebookHotkeys,
    _normalize_key,
    _EASTER_EGG_COMMANDS,
    _EASTER_EGG_TRIGGERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingDispatcher:
    """Captures every command id passed to the dispatcher."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def __call__(self, command: str) -> None:
        self.commands.append(command)


class _RecordingScheduler:
    """Minimal CreatureScheduler stand-in."""

    def __init__(self, *, accept: bool = True) -> None:
        self.triggers: list[tuple[str, str]] = []
        self._accept = accept

    def trigger(self, creature_id: str, anim_name: str) -> bool:
        self.triggers.append((creature_id, anim_name))
        if not self._accept:
            raise LookupError("anim missing")
        return True


# ---------------------------------------------------------------------------
# 1. Table contents
# ---------------------------------------------------------------------------


def test_bindings_cover_ctrl_save():
    assert NotebookHotkeys.BINDINGS["ctrl+s"] == "editor.save"


def test_bindings_cover_ctrl_undo_redo():
    assert NotebookHotkeys.BINDINGS["ctrl+z"] == "editor.undo"
    assert NotebookHotkeys.BINDINGS["ctrl+y"] == "editor.redo"


def test_bindings_cover_function_keys():
    assert NotebookHotkeys.BINDINGS["f1"]  == "editor.help"
    assert NotebookHotkeys.BINDINGS["f3"]  == "editor.profiler_toggle"
    assert NotebookHotkeys.BINDINGS["f5"]  == "editor.run"
    assert NotebookHotkeys.BINDINGS["f11"] == "editor.toggle_fullscreen"


def test_bindings_cover_tool_letters():
    assert NotebookHotkeys.BINDINGS["s"] == "editor.tool_select"
    assert NotebookHotkeys.BINDINGS["t"] == "editor.tool_move"
    assert NotebookHotkeys.BINDINGS["r"] == "editor.tool_rotate"
    assert NotebookHotkeys.BINDINGS["c"] == "editor.tool_scale"


def test_bindings_cover_easter_eggs():
    assert NotebookHotkeys.BINDINGS["ctrl+shift+f"] == "editor.easter_feed_fox"
    assert NotebookHotkeys.BINDINGS["ctrl+shift+b"] == \
        "editor.easter_baby_porcupine_roll"


def test_easter_egg_command_set_is_exact():
    assert NotebookHotkeys.EASTER_EGG_COMMANDS == frozenset({
        "editor.easter_feed_fox",
        "editor.easter_baby_porcupine_roll",
    })


def test_bindings_table_is_a_copy_not_class_attr_reference():
    # bindings() returns a shallow copy so a caller can't smuggle a
    # mutation back onto the class attribute.
    hk = NotebookHotkeys(_RecordingDispatcher())
    bindings = hk.bindings()
    bindings["ctrl+x"] = "editor.compromised"
    assert "ctrl+x" not in NotebookHotkeys.BINDINGS


# ---------------------------------------------------------------------------
# 2. Modifier normalisation
# ---------------------------------------------------------------------------


def test_normalize_key_reorders_modifiers():
    assert _normalize_key("s", ["Shift", "Ctrl"]) == "ctrl+shift+s"


def test_normalize_key_lowercases_everything():
    assert _normalize_key("S", ["CTRL"]) == "ctrl+s"


def test_normalize_key_accepts_composite_string():
    assert _normalize_key("CTRL+SHIFT+F") == "ctrl+shift+f"


def test_normalize_key_dedupes_modifiers():
    assert _normalize_key("s", ["Ctrl", "ctrl"]) == "ctrl+s"


# ---------------------------------------------------------------------------
# 3. Dispatch
# ---------------------------------------------------------------------------


def test_handle_key_event_dispatches_ctrl_s():
    rec = _RecordingDispatcher()
    hk = NotebookHotkeys(rec)
    assert hk.handle_key_event("s", ["ctrl"]) is True
    assert rec.commands == ["editor.save"]


def test_handle_key_event_dispatches_tool_letter():
    rec = _RecordingDispatcher()
    hk = NotebookHotkeys(rec)
    assert hk.handle_key_event("r", []) is True
    assert rec.commands == ["editor.tool_rotate"]


def test_handle_key_event_returns_false_for_unbound():
    rec = _RecordingDispatcher()
    hk = NotebookHotkeys(rec)
    assert hk.handle_key_event("q", ["alt"]) is False
    assert rec.commands == []


def test_handle_key_event_with_string_modifier_list_normalisation():
    rec = _RecordingDispatcher()
    hk = NotebookHotkeys(rec)
    # "Ctrl" / lowercase mix should still hit ctrl+s.
    assert hk.handle_key_event("S", ["Ctrl"]) is True
    assert rec.commands == ["editor.save"]


def test_command_for_lookup_helper():
    hk = NotebookHotkeys(_RecordingDispatcher())
    assert hk.command_for("f3") == "editor.profiler_toggle"
    assert hk.command_for("s", ["ctrl"]) == "editor.save"
    assert hk.command_for("q") is None


def test_dispatcher_error_does_not_break_dispatch_chain():
    def boom(_cmd: str) -> None:
        raise RuntimeError("kaboom")
    hk = NotebookHotkeys(boom)
    # Returns True because the event matched; the dispatcher exception
    # is swallowed so subsequent presses still work.
    assert hk.handle_key_event("s", ["ctrl"]) is True


# ---------------------------------------------------------------------------
# 4. Easter-egg gating
# ---------------------------------------------------------------------------


def test_easter_egg_suppressed_when_gate_closed():
    rec = _RecordingDispatcher()
    sched = _RecordingScheduler()
    hk = NotebookHotkeys(rec, easter_eggs=False)
    hk.set_creature_scheduler(sched)
    assert hk.handle_key_event("f", ["ctrl", "shift"]) is True
    # Dispatcher NOT called when the gate is closed — that's the brief.
    assert rec.commands == []
    # Scheduler NOT touched.
    assert sched.triggers == []
    # And the suppression counter incremented so diagnostics can find it.
    assert hk.suppressed_easter_egg_count == 1


def test_easter_egg_fires_when_gate_open():
    rec = _RecordingDispatcher()
    sched = _RecordingScheduler()
    hk = NotebookHotkeys(rec, easter_eggs=True)
    hk.set_creature_scheduler(sched)
    assert hk.handle_key_event("f", ["ctrl", "shift"]) is True
    assert rec.commands == ["editor.easter_feed_fox"]
    assert sched.triggers == [("fox_01", "feed")]


def test_easter_egg_porcupine_routes_to_ball_up():
    rec = _RecordingDispatcher()
    sched = _RecordingScheduler()
    hk = NotebookHotkeys(rec)
    hk.set_creature_scheduler(sched)
    hk.handle_key_event("b", ["ctrl", "shift"])
    assert sched.triggers == [("porcupine_01", "ball_up")]


def test_easter_egg_swallows_scheduler_lookup_error():
    rec = _RecordingDispatcher()
    sched = _RecordingScheduler(accept=False)
    hk = NotebookHotkeys(rec)
    hk.set_creature_scheduler(sched)
    # Scheduler raises LookupError on trigger; hotkey table should
    # swallow it and still fire the dispatcher.
    assert hk.handle_key_event("f", ["ctrl", "shift"]) is True
    assert rec.commands == ["editor.easter_feed_fox"]


def test_easter_egg_without_scheduler_is_safe():
    rec = _RecordingDispatcher()
    hk = NotebookHotkeys(rec, easter_eggs=True)
    # No scheduler set — should not raise.
    assert hk.handle_key_event("f", ["ctrl", "shift"]) is True
    assert rec.commands == ["editor.easter_feed_fox"]


def test_set_easter_eggs_toggle_at_runtime():
    rec = _RecordingDispatcher()
    sched = _RecordingScheduler()
    hk = NotebookHotkeys(rec, easter_eggs=True)
    hk.set_creature_scheduler(sched)
    hk.set_easter_eggs(False)
    hk.handle_key_event("f", ["ctrl", "shift"])
    assert sched.triggers == []
    hk.set_easter_eggs(True)
    hk.handle_key_event("f", ["ctrl", "shift"])
    assert sched.triggers == [("fox_01", "feed")]


def test_easter_egg_trigger_table_covers_both_commands():
    # Cross-check: every command in EASTER_EGG_COMMANDS has a matching
    # entry in the internal trigger table.
    for cmd in _EASTER_EGG_COMMANDS:
        assert cmd in _EASTER_EGG_TRIGGERS
        creature_id, anim = _EASTER_EGG_TRIGGERS[cmd]
        assert creature_id and anim


# ---------------------------------------------------------------------------
# 5. Install
# ---------------------------------------------------------------------------


def test_install_without_dpg_is_safe(monkeypatch):
    """``install`` should never raise on a host without DPG."""
    import sys
    monkeypatch.setitem(sys.modules, "dearpygui", None)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", None)
    hk = NotebookHotkeys(_RecordingDispatcher())
    hk.install()
    assert hk.handler_registry_tag is None


# ---------------------------------------------------------------------------
# 6. Constructor validation
# ---------------------------------------------------------------------------


def test_constructor_rejects_non_callable_dispatcher():
    with pytest.raises(TypeError):
        NotebookHotkeys("not a callable")  # type: ignore[arg-type]


def test_constructor_rejects_non_bool_easter_eggs():
    with pytest.raises(TypeError):
        NotebookHotkeys(_RecordingDispatcher(), easter_eggs="yes")  # type: ignore[arg-type]


def test_set_creature_scheduler_rejects_none():
    hk = NotebookHotkeys(_RecordingDispatcher())
    with pytest.raises(TypeError):
        hk.set_creature_scheduler(None)
