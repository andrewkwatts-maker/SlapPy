"""
Tests for :mod:`pharos_engine.telemetry`.

Covers the no-subscriber fast path, glob pattern matching, unsubscribe,
the ring-buffer history API, and thread-safety under concurrent emits.
"""
from __future__ import annotations

import threading
import time

import pytest

from pharos_engine import telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    """Reset module state between tests so order does not matter."""
    # Drop every subscription installed by a previous test.
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()
    yield
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()


# ---------------------------------------------------------------------------
# Fast path
# ---------------------------------------------------------------------------
def test_emit_with_no_subscribers_is_no_op():
    """10k emits with zero subscribers and history disabled stay under 50ms."""
    telemetry.set_history_capacity(0)  # also disable ring buffer
    # Pre-warm any import / attribute lookup costs.
    telemetry.emit("warmup")

    start = time.perf_counter()
    for _ in range(10_000):
        telemetry.emit("physics.step", dt=0.016)
    elapsed = time.perf_counter() - start

    # Generous budget — actual cost should be a couple ms.
    assert elapsed < 0.050, f"10k no-op emits took {elapsed*1000:.2f}ms (budget 50ms)"


# ---------------------------------------------------------------------------
# Subscription semantics
# ---------------------------------------------------------------------------
def test_subscribe_receives_matching_events():
    received: list[telemetry.TelemetryEvent] = []
    telemetry.subscribe("physics.*", received.append)

    telemetry.emit("physics.step", dt=0.016)
    telemetry.emit("render.frame", frame=1)

    assert len(received) == 1
    assert received[0].name == "physics.step"
    assert received[0].payload == {"dt": 0.016}


def test_subscribe_glob_pattern():
    received: list[telemetry.TelemetryEvent] = []
    telemetry.subscribe("thermal.*", received.append)

    telemetry.emit("thermal.phase_change", from_="ice", to="water")
    telemetry.emit("thermal.equilibrium", temp=300.0)
    telemetry.emit("lighting.update", lux=400)

    assert len(received) == 2
    names = [e.name for e in received]
    assert names == ["thermal.phase_change", "thermal.equilibrium"]


def test_unsubscribe_stops_delivery():
    received: list[telemetry.TelemetryEvent] = []
    handle = telemetry.subscribe("*", received.append)

    telemetry.emit("foo")
    assert len(received) == 1

    telemetry.unsubscribe(handle)
    telemetry.emit("bar")
    assert len(received) == 1  # bar should NOT have been delivered

    # Double unsubscribe is safe.
    telemetry.unsubscribe(handle)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def test_history_records_events():
    for i in range(5):
        telemetry.emit("tick", i=i)

    history = telemetry.get_event_history()
    assert len(history) == 5
    assert [e.payload["i"] for e in history] == [0, 1, 2, 3, 4]
    assert all(e.name == "tick" for e in history)


def test_history_pattern_filter():
    telemetry.emit("physics.step")
    telemetry.emit("render.frame")
    telemetry.emit("physics.collision")
    telemetry.emit("audio.play")

    physics = telemetry.get_event_history("physics.*")
    assert [e.name for e in physics] == ["physics.step", "physics.collision"]

    audio = telemetry.get_event_history("audio.*")
    assert [e.name for e in audio] == ["audio.play"]


def test_history_capacity_caps_size():
    telemetry.set_history_capacity(3)
    for i in range(5):
        telemetry.emit("e", i=i)

    history = telemetry.get_event_history()
    assert len(history) == 3
    # Should retain the most recent three.
    assert [e.payload["i"] for e in history] == [2, 3, 4]


def test_clear_history():
    telemetry.emit("a")
    telemetry.emit("b")
    assert len(telemetry.get_event_history()) == 2

    telemetry.clear_history()
    assert telemetry.get_event_history() == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------
def test_thread_safety_concurrent_emits():
    counter_lock = threading.Lock()
    count = {"n": 0}

    def on_event(_event: telemetry.TelemetryEvent) -> None:
        with counter_lock:
            count["n"] += 1

    telemetry.subscribe("worker.*", on_event)

    n_threads = 4
    per_thread = 1000
    barrier = threading.Barrier(n_threads)

    def worker(tid: int) -> None:
        barrier.wait()
        for i in range(per_thread):
            telemetry.emit("worker.tick", tid=tid, i=i)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert count["n"] == n_threads * per_thread, (
        f"expected {n_threads * per_thread} callbacks, got {count['n']}"
    )
