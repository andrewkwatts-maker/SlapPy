"""Tests for the woodland-creature event-bus adapter + idle emitter.

Covers:

* :data:`EVENT_TO_CREATURE_ANIMS` matches the canonical doc.
* :class:`CreatureBusAdapter` install / uninstall + bus subscription set.
* End-to-end publish-to-trigger: ``engine.save`` -> butterfly flutter,
  ``engine.error`` -> owl + porcupine.
* Debounce: same binding doesn't refire within 500 ms.
* Tolerant scheduler: missing creature is a warning, not a crash.
* :class:`IdleEventEmitter` fires after the threshold, only once per
  idle window, and :meth:`reset_activity` reopens it.
* Validation: bad inputs raise ``TypeError`` / ``ValueError`` early.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from pharos_engine.event_bus import EventBus
from pharos_editor.ui.theme.creatures import (
    CreatureBusAdapter,
    EVENT_TO_CREATURE_ANIMS,
    IdleEventEmitter,
)
from pharos_editor.ui.theme.creatures.bus_adapter import DEFAULT_DEBOUNCE_MS


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubScheduler:
    """Records every ``trigger`` call; optionally raises for unknown ids."""

    def __init__(
        self,
        *,
        known_ids: set[str] | None = None,
        always_known: bool = True,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._known = known_ids if known_ids is not None else set()
        self._always_known = always_known

    def trigger(self, creature_id: str, anim_name: str) -> None:
        if not self._always_known and creature_id not in self._known:
            raise KeyError(creature_id)
        self.calls.append((creature_id, anim_name))


# ---------------------------------------------------------------------------
# Bindings table coverage
# ---------------------------------------------------------------------------


# Canonical set sourced from docs/idle_animation_system_2026_06_03.md §2
# plus the task brief's expanded sample. We assert membership, not
# strict equality, so adding rarely-fired bindings later doesn't break.
_REQUIRED_EVENT_KEYS = frozenset(
    {
        "engine.save",
        "engine.build_success",
        "engine.build_failure",
        "engine.error",
        "engine.scene_loaded",
        "engine.scene_closed",
        "engine.test_pass",
        "engine.idle_60s",
        "engine.idle_120s",
        "engine.first_run",
        "engine.progress_start",
        "engine.progress_end",
        "engine.loading_start",
        "engine.loading_cancel",
        "ui.scene_outliner.select_root",
        "ui.code_mode.bookmark_add",
        "ui.click_on_mushroom_decoration",
    }
)


def test_bindings_table_covers_every_documented_event():
    missing = _REQUIRED_EVENT_KEYS - set(EVENT_TO_CREATURE_ANIMS)
    assert not missing, f"missing event bindings: {sorted(missing)}"


def test_bindings_table_has_no_empty_value_lists():
    for event, bindings in EVENT_TO_CREATURE_ANIMS.items():
        assert bindings, f"{event!r} has no bindings"


def test_bindings_pairs_are_two_string_tuples():
    for event, bindings in EVENT_TO_CREATURE_ANIMS.items():
        for pair in bindings:
            assert isinstance(pair, tuple) and len(pair) == 2, event
            cid, anim = pair
            assert isinstance(cid, str) and cid, event
            assert isinstance(anim, str) and anim, event


def test_bindings_save_uses_butterfly_flutter():
    assert ("butterfly_01", "flutter") in EVENT_TO_CREATURE_ANIMS[
        "engine.save"
    ]


def test_bindings_error_fires_owl_and_porcupine():
    pairs = EVENT_TO_CREATURE_ANIMS["engine.error"]
    assert ("owl_01", "hoot") in pairs
    assert ("porcupine_01", "ball_up") in pairs


def test_bindings_build_success_includes_bee_and_acorn():
    pairs = EVENT_TO_CREATURE_ANIMS["engine.build_success"]
    creatures = {cid for cid, _ in pairs}
    assert "bee_01" in creatures
    assert "acorn_01" in creatures


# ---------------------------------------------------------------------------
# CreatureBusAdapter — install / uninstall / subscription set
# ---------------------------------------------------------------------------


def test_adapter_install_subscribes_to_every_event_key():
    bus = EventBus()
    sched = _StubScheduler()
    adapter = CreatureBusAdapter(sched, bus)
    adapter.install()

    for event in EVENT_TO_CREATURE_ANIMS:
        assert bus.listener_count(event) >= 1, event

    assert adapter.installed is True
    assert set(adapter.subscribed_events) == set(EVENT_TO_CREATURE_ANIMS)


def test_adapter_install_is_idempotent():
    bus = EventBus()
    sched = _StubScheduler()
    adapter = CreatureBusAdapter(sched, bus)
    adapter.install()
    adapter.install()  # second call must be a no-op
    for event in EVENT_TO_CREATURE_ANIMS:
        assert bus.listener_count(event) == 1, event


def test_adapter_uninstall_clears_every_subscription():
    bus = EventBus()
    sched = _StubScheduler()
    adapter = CreatureBusAdapter(sched, bus)
    adapter.install()
    adapter.uninstall()
    for event in EVENT_TO_CREATURE_ANIMS:
        assert bus.listener_count(event) == 0, event
    assert adapter.installed is False
    assert adapter.subscribed_events == ()


# ---------------------------------------------------------------------------
# CreatureBusAdapter — publish-to-trigger
# ---------------------------------------------------------------------------


def test_publish_save_triggers_butterfly_flutter():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()

    bus.publish("engine.save")

    assert ("butterfly_01", "flutter") in sched.calls
    assert len(sched.calls) == 1


def test_publish_error_triggers_owl_and_porcupine():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()

    bus.publish("engine.error")

    assert ("owl_01", "hoot") in sched.calls
    assert ("porcupine_01", "ball_up") in sched.calls
    assert len(sched.calls) == 2


def test_publish_unbound_event_is_noop():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()

    bus.publish("engine.totally_unknown_event")

    assert sched.calls == []


def test_trigger_for_event_returns_fire_count():
    bus = EventBus()
    sched = _StubScheduler()
    adapter = CreatureBusAdapter(sched, bus)
    adapter.install()

    fired = adapter.trigger_for_event("engine.error")
    assert fired == 2

    # An unbound event reports zero fires without raising.
    assert adapter.trigger_for_event("engine.unknown") == 0


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------


def test_debounce_collapses_same_event_within_window():
    bus = EventBus()
    sched = _StubScheduler()
    # 500 ms default — three rapid publishes should fire once.
    CreatureBusAdapter(sched, bus).install()

    bus.publish("engine.save")
    bus.publish("engine.save")
    bus.publish("engine.save")

    save_calls = [c for c in sched.calls if c == ("butterfly_01", "flutter")]
    assert len(save_calls) == 1


def test_debounce_releases_after_window_elapses():
    bus = EventBus()
    sched = _StubScheduler()
    # 5 ms debounce so the test is fast but still meaningful.
    CreatureBusAdapter(sched, bus, debounce_ms=5.0).install()

    bus.publish("engine.save")
    time.sleep(0.020)  # comfortably past the 5 ms window
    bus.publish("engine.save")

    save_calls = [c for c in sched.calls if c == ("butterfly_01", "flutter")]
    assert len(save_calls) == 2


def test_debounce_is_per_binding_not_global():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()

    # Two different events fire two different creatures; neither should
    # be debounced by the other.
    bus.publish("engine.save")
    bus.publish("engine.error")

    assert ("butterfly_01", "flutter") in sched.calls
    assert ("owl_01", "hoot") in sched.calls


# ---------------------------------------------------------------------------
# Tolerance: missing creatures
# ---------------------------------------------------------------------------


def test_missing_creature_logs_warning_and_does_not_crash(caplog):
    bus = EventBus()
    # Scheduler raises KeyError for every unknown id; we register none,
    # so every trigger is a miss.
    sched = _StubScheduler(known_ids=set(), always_known=False)
    CreatureBusAdapter(sched, bus).install()

    with caplog.at_level(logging.WARNING, logger="pharos_editor.ui.theme.creatures.bus_adapter"):
        bus.publish("engine.save")

    assert sched.calls == []  # no successful trigger recorded
    assert any("no creature" in rec.message for rec in caplog.records)


def test_partial_roster_still_fires_known_creatures():
    bus = EventBus()
    # Only the owl is registered; porcupine is missing.
    sched = _StubScheduler(known_ids={"owl_01"}, always_known=False)
    CreatureBusAdapter(sched, bus).install()

    bus.publish("engine.error")

    assert sched.calls == [("owl_01", "hoot")]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_adapter_rejects_non_bus():
    sched = _StubScheduler()
    with pytest.raises(TypeError):
        CreatureBusAdapter(sched, bus="not a bus")  # type: ignore[arg-type]


def test_adapter_rejects_none_bus():
    sched = _StubScheduler()
    with pytest.raises(TypeError):
        CreatureBusAdapter(sched, bus=None)  # type: ignore[arg-type]


def test_adapter_rejects_scheduler_without_trigger():
    bus = EventBus()

    class _Bad:
        pass

    with pytest.raises(TypeError):
        CreatureBusAdapter(_Bad(), bus)


def test_adapter_rejects_non_positive_debounce():
    bus = EventBus()
    sched = _StubScheduler()
    with pytest.raises(ValueError):
        CreatureBusAdapter(sched, bus, debounce_ms=0.0)
    with pytest.raises(ValueError):
        CreatureBusAdapter(sched, bus, debounce_ms=-1.0)


def test_default_debounce_is_500ms():
    assert DEFAULT_DEBOUNCE_MS == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# IdleEventEmitter
# ---------------------------------------------------------------------------


def _make_idle_recorder(bus: EventBus, event: str) -> list[dict]:
    """Subscribe a recorder for *event* and return the payload list."""
    received: list[dict] = []

    def _cb(payload: dict) -> None:
        received.append(payload)

    bus.subscribe(event, _cb)
    return received


def test_idle_emitter_fires_after_threshold():
    bus = EventBus()
    received = _make_idle_recorder(bus, "engine.idle_60s")

    emitter = IdleEventEmitter(bus)
    emitter.tick(30.0)
    assert received == []
    emitter.tick(31.0)  # total 61 s, past 60 s threshold
    assert len(received) == 1


def test_idle_emitter_fires_each_threshold_exactly_once():
    bus = EventBus()
    received_60 = _make_idle_recorder(bus, "engine.idle_60s")
    received_120 = _make_idle_recorder(bus, "engine.idle_120s")

    emitter = IdleEventEmitter(bus)
    # One huge tick should fire BOTH thresholds, each exactly once.
    emitter.tick(200.0)
    assert len(received_60) == 1
    assert len(received_120) == 1

    # Further ticks without reset must not refire.
    emitter.tick(50.0)
    assert len(received_60) == 1
    assert len(received_120) == 1


def test_idle_emitter_reset_activity_reopens_window():
    bus = EventBus()
    received = _make_idle_recorder(bus, "engine.idle_60s")

    emitter = IdleEventEmitter(bus)
    emitter.tick(61.0)
    assert len(received) == 1
    assert emitter.has_fired("engine.idle_60s")

    emitter.reset_activity()
    assert emitter.idle_seconds == 0.0
    assert not emitter.has_fired("engine.idle_60s")

    emitter.tick(30.0)
    assert len(received) == 1  # still not refired yet
    emitter.tick(31.0)
    assert len(received) == 2


def test_idle_emitter_reset_before_threshold_cancels_pending_event():
    bus = EventBus()
    received = _make_idle_recorder(bus, "engine.idle_60s")

    emitter = IdleEventEmitter(bus)
    emitter.tick(59.0)
    emitter.reset_activity()
    emitter.tick(30.0)
    assert received == []  # never crossed 60 s in any single window


def test_idle_emitter_zero_dt_is_noop():
    bus = EventBus()
    received = _make_idle_recorder(bus, "engine.idle_60s")

    emitter = IdleEventEmitter(bus)
    emitter.tick(0.0)
    assert received == []
    assert emitter.idle_seconds == 0.0


def test_idle_emitter_custom_intervals():
    bus = EventBus()
    received = _make_idle_recorder(bus, "engine.idle_300s")

    emitter = IdleEventEmitter(
        bus, intervals=[("engine.idle_300s", 300.0)]
    )
    emitter.tick(299.0)
    assert received == []
    emitter.tick(2.0)
    assert len(received) == 1


def test_idle_emitter_validation():
    bus = EventBus()
    with pytest.raises(TypeError):
        IdleEventEmitter(bus=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IdleEventEmitter(bus, intervals=[("engine.idle_60s", 0.0)])
    with pytest.raises(TypeError):
        IdleEventEmitter(bus, intervals=[("only_one_field",)])  # type: ignore[list-item]


def test_idle_emitter_tick_rejects_negative_dt():
    bus = EventBus()
    emitter = IdleEventEmitter(bus)
    with pytest.raises(ValueError):
        emitter.tick(-0.001)


# ---------------------------------------------------------------------------
# End-to-end: idle emitter -> adapter -> scheduler
# ---------------------------------------------------------------------------


def test_idle_emitter_drives_adapter_and_fires_fox_stretch():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()
    emitter = IdleEventEmitter(bus)

    emitter.tick(61.0)
    assert ("fox_01", "stretch") in sched.calls


def test_idle_emitter_drives_adapter_for_idle_120s():
    bus = EventBus()
    sched = _StubScheduler()
    CreatureBusAdapter(sched, bus).install()
    emitter = IdleEventEmitter(bus)

    emitter.tick(121.0)
    assert ("fox_01", "stretch") in sched.calls
    assert ("frog_01", "hop") in sched.calls
