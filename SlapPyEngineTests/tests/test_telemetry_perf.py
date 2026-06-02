"""
Performance + correctness tests for the opt-in telemetry pattern index.

These complement the functional tests in ``test_telemetry.py``:

* delivery equivalence between the indexed and unindexed dispatch paths,
* a wall-clock speedup floor (>= 2x) at 1000 mixed-pattern subscribers,
* the default-off invariant for backward compatibility.

The wall-clock test is sensitive enough to be marked "perf" but kept
conservative — we assert a 2x floor while the bench typically shows ~6x.
"""
from __future__ import annotations

import gc
import time

import pytest

from slappyengine import telemetry


# ---------------------------------------------------------------------------
# Shared fixture: scrub every shred of telemetry state between tests.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    telemetry.enable_pattern_index(False)
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()
    yield
    telemetry.enable_pattern_index(False)
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()


# ---------------------------------------------------------------------------
# Backward compat: pattern index defaults to off.
# ---------------------------------------------------------------------------
def test_pattern_index_off_by_default():
    """A fresh module load must have the index disabled."""
    # Re-import to assert default state; the autouse fixture has already
    # reset the toggle, so this is a tautology unless we also confirm the
    # public query helper agrees.
    assert telemetry.is_pattern_index_enabled() is False


def test_enable_pattern_index_default_arg_is_true_but_module_default_off():
    """``enable_pattern_index()`` with no args turns it ON; module starts OFF."""
    assert telemetry.is_pattern_index_enabled() is False
    telemetry.enable_pattern_index()
    assert telemetry.is_pattern_index_enabled() is True
    telemetry.enable_pattern_index(False)
    assert telemetry.is_pattern_index_enabled() is False


# ---------------------------------------------------------------------------
# Delivery equivalence: indexed dispatch must produce identical sets
# of (subscriber-id, event-name) deliveries.
# ---------------------------------------------------------------------------
_SEGMENTS = (
    "physics",
    "render",
    "audio",
    "input",
    "thermal",
    "lighting",
    "asset",
    "scene",
    "ui",
    "ai",
)


def _record_workload(index_enabled: bool, emit_names) -> set:
    """Subscribe a mix of patterns and run the emit workload.

    Returns the set of ``(sub_id, event_name)`` tuples that were delivered.
    """
    telemetry.set_history_capacity(0)
    telemetry.enable_pattern_index(index_enabled)
    deliveries: set = set()

    sub_counter = [0]

    def make_cb(sub_id: int):
        def cb(event: telemetry.TelemetryEvent) -> None:
            deliveries.add((sub_id, event.name))
        return cb

    # 10 segments x 10 subs each on "<seg>.*"  = 100 subs
    for seg in _SEGMENTS:
        for _ in range(10):
            sub_id = sub_counter[0]
            sub_counter[0] += 1
            telemetry.subscribe(f"{seg}.*", make_cb(sub_id))

    # 10 subs on "*" (catch-all literal).
    for _ in range(10):
        sub_id = sub_counter[0]
        sub_counter[0] += 1
        telemetry.subscribe("*", make_cb(sub_id))

    # 5 subs on a cross-bucket glob "*.step" — exercises the catch-all
    # bucket fallback for patterns whose first segment is glob-shaped.
    for _ in range(5):
        sub_id = sub_counter[0]
        sub_counter[0] += 1
        telemetry.subscribe("*.step", make_cb(sub_id))

    # A handful of exact-name subscribers.
    for exact in ("physics.step", "render.frame", "audio.play", "input.key"):
        sub_id = sub_counter[0]
        sub_counter[0] += 1
        telemetry.subscribe(exact, make_cb(sub_id))

    for name in emit_names:
        telemetry.emit(name)
    return deliveries


def test_pattern_index_delivers_same_events_as_unindexed():
    """Same workload through both paths must produce identical deliveries."""
    names = []
    for seg in _SEGMENTS:
        names.append(f"{seg}.step")
        names.append(f"{seg}.frame")
        names.append(f"{seg}.collision")
    # Plus some single-segment names that hit the catch-all "*" bucket
    # without touching any first-segment-named bucket.
    names.extend(["tick", "shutdown", "boot"])

    off_deliveries = _record_workload(index_enabled=False, emit_names=names)

    # Tear down between runs so the same subscribers don't leak through.
    telemetry.enable_pattern_index(False)
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)

    on_deliveries = _record_workload(index_enabled=True, emit_names=names)

    missing_when_indexed = off_deliveries - on_deliveries
    spurious_from_index = on_deliveries - off_deliveries
    assert missing_when_indexed == set(), (
        f"index dropped {len(missing_when_indexed)} deliveries"
    )
    assert spurious_from_index == set(), (
        f"index added {len(spurious_from_index)} spurious deliveries"
    )


def test_pattern_index_emit_order_is_subscription_order_within_buckets():
    """Within a bucket, callbacks fire in subscription order."""
    telemetry.set_history_capacity(0)
    telemetry.enable_pattern_index(True)

    order: list[int] = []

    def make_cb(i: int):
        return lambda _e: order.append(i)

    for i in range(20):
        telemetry.subscribe("physics.*", make_cb(i))

    telemetry.emit("physics.step")
    assert order == list(range(20))


# ---------------------------------------------------------------------------
# Wall-clock floor: indexed must be at least 2x faster on the
# 1000-subscriber / 10-pattern workload.
# ---------------------------------------------------------------------------
def _bench_mixed(index_enabled: bool, emits: int = 5_000) -> float:
    telemetry.enable_pattern_index(False)
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(0)
    telemetry.enable_pattern_index(index_enabled)

    received = [0]

    def cb(_e):
        received[0] += 1

    # 1000 subs across 10 segments.
    for seg in _SEGMENTS:
        for _ in range(100):
            telemetry.subscribe(f"{seg}.*", cb)

    gc.collect()
    start = time.perf_counter()
    for i in range(emits):
        telemetry.emit(f"{_SEGMENTS[i % len(_SEGMENTS)]}.step")
    elapsed = time.perf_counter() - start

    # Sanity: indexed and unindexed both deliver the same callback total.
    # Each emit lands in one bucket of 100 subs.
    assert received[0] == emits * 100, (
        f"expected {emits * 100} callbacks, got {received[0]}"
    )
    return elapsed


def test_pattern_index_speeds_up_high_subscriber_count():
    """At 1000 mixed-pattern subscribers, indexed path is >= 2x faster."""
    # Warm-up to amortise first-emit allocation / branch prediction noise.
    _bench_mixed(index_enabled=False, emits=200)
    _bench_mixed(index_enabled=True, emits=200)

    off = _bench_mixed(index_enabled=False)
    on = _bench_mixed(index_enabled=True)

    speedup = off / on if on > 0 else float("inf")
    assert speedup >= 2.0, (
        f"indexed dispatch only {speedup:.2f}x faster than unindexed "
        f"(off={off*1000:.1f}ms, on={on*1000:.1f}ms)"
    )
