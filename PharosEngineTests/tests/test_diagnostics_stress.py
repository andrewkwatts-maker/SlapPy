"""Stress tests for :mod:`pharos_engine.diagnostics` (PP7 sprint).

Complements the OO6 landing test suite (``test_diagnostics.py``) which
covers the *functional* contract of :class:`DiagnosticsCollector`. This
file exercises the aggregator under load — thousands of events, ring
overflow, thread contention, install/uninstall churn — so we catch
regressions in the lock discipline, ring-buffer eviction ordering, and
handler-attach idempotence.

The four tests below correspond one-to-one with the PP7 sprint spec:

* :func:`test_diagnostics_1000_events` — 10 subsystems × 100 warnings
  each; asserts stats() per-level, per-subsystem, and total.
* :func:`test_diagnostics_ring_buffer_overflow` — 2000 emits into a
  ``max_events=500`` collector; asserts exactly 500 retained and that
  the oldest 1500 were dropped.
* :func:`test_diagnostics_thread_safety` — 8 threads × 100 emits into
  the same collector; asserts total ``events()`` length is 800 with no
  exceptions leaking out of the workers.
* :func:`test_diagnostics_install_uninstall_cycle` — install / emit /
  uninstall / emit-during-gap / re-install / emit; asserts the
  uninstalled window drops silently.
"""
from __future__ import annotations

import logging
import threading

import pytest

from pharos_engine.diagnostics import DiagnosticsCollector


# ---------------------------------------------------------------------------
# The 10 subsystems we fan warnings across — a representative slice of
# the 13 subsystems MM1 wired up loggers for.  Kept module-level so the
# tests read as a straight loop over a stable list.
# ---------------------------------------------------------------------------

_SUBSYSTEMS: tuple[str, ...] = (
    "audio_3d",
    "capture",
    "exporter",
    "physics3_bridge",
    "render.ssao",
    "render.skybox",
    "render.instanced",
    "text",
    "asset_import.gltf",
    "asset_import.usd",
)


def _logger_for(sub: str) -> logging.Logger:
    """Return the ``pharos_engine.<sub>`` logger."""
    return logging.getLogger(f"pharos_engine.{sub}")


def _expected_subsystem_tag(sub: str) -> str:
    """Mirror the aggregator's ``_subsystem_from_logger_name`` grouping.

    ``render.ssao`` -> ``render`` (first component past ``pharos_engine.``).
    ``audio_3d``    -> ``audio_3d``.
    """
    return sub.split(".", 1)[0]


# ---------------------------------------------------------------------------
# Test 1 — 1000 events across 10 subsystems, stats() correctness
# ---------------------------------------------------------------------------


def test_diagnostics_1000_events():
    """Emit 1000 warnings across 10 subsystems; verify stats() correctness.

    The stats dict flattens level + subsystem counts into a single
    namespace, so the test walks it back into two dicts and compares
    against the deterministic ground truth (100 events per subsystem,
    1000 WARNING total).
    """
    collector = DiagnosticsCollector(max_events=2000, min_level="WARNING")
    collector.install()
    try:
        for i in range(100):
            for sub in _SUBSYSTEMS:
                _logger_for(sub).warning("stress-event %d", i)

        events = collector.events()
        assert len(events) == 1000, (
            f"expected 1000 captured events, got {len(events)}"
        )

        stats = collector.stats()
        assert stats["total"] == 1000
        # Only WARNING was emitted, so exactly one level bucket.
        assert stats["level:WARNING"] == 1000
        assert "level:ERROR" not in stats
        assert "level:CRITICAL" not in stats

        # Per-subsystem counts — logical tags collapse ``render.ssao`` →
        # ``render``, so ``render`` receives 3×100 = 300 events and every
        # other tag receives 100.
        expected_sub_counts: dict[str, int] = {}
        for sub in _SUBSYSTEMS:
            tag = _expected_subsystem_tag(sub)
            expected_sub_counts[tag] = expected_sub_counts.get(tag, 0) + 100
        for tag, expected in expected_sub_counts.items():
            key = f"subsystem:{tag}"
            assert stats[key] == expected, (
                f"{key} = {stats[key]}, expected {expected}"
            )
        # Sanity: sum of per-subsystem counts equals total.
        sub_total = sum(
            v for k, v in stats.items() if k.startswith("subsystem:")
        )
        assert sub_total == 1000
    finally:
        collector.uninstall()


# ---------------------------------------------------------------------------
# Test 2 — ring buffer overflow drops oldest
# ---------------------------------------------------------------------------


def test_diagnostics_ring_buffer_overflow():
    """Emit 2000 events into a ``max_events=500`` collector; oldest dropped.

    We tag each message with its emit index so we can verify that
    indices 0..1499 got evicted and indices 1500..1999 survived.
    """
    collector = DiagnosticsCollector(max_events=500, min_level="WARNING")
    collector.install()
    try:
        log = logging.getLogger("pharos_engine.render")
        for i in range(2000):
            log.warning("overflow-event %d", i)

        events = collector.events()
        assert len(events) == 500, (
            f"ring buffer should cap at 500, got {len(events)}"
        )
        # Oldest surviving event is index 1500 (2000 - 500).
        assert "overflow-event 1500" in events[0].message, (
            f"oldest retained event should be #1500, got: {events[0].message!r}"
        )
        # Newest event is #1999.
        assert "overflow-event 1999" in events[-1].message

        # And stats() reflects the capped total, not the emit count.
        stats = collector.stats()
        assert stats["total"] == 500
        assert stats["level:WARNING"] == 500
    finally:
        collector.uninstall()


# ---------------------------------------------------------------------------
# Test 3 — thread safety under contention
# ---------------------------------------------------------------------------


def test_diagnostics_thread_safety():
    """8 worker threads × 100 emits into a shared collector; no data loss.

    The collector's internal ``RLock`` must serialise ``_capture`` calls
    so all 800 events land and no worker raises. We also assert no
    thread bubbled an exception up through the ``errors`` list.
    """
    collector = DiagnosticsCollector(max_events=2000, min_level="WARNING")
    collector.install()

    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _worker(worker_id: int) -> None:
        try:
            log = logging.getLogger(f"pharos_engine.worker_{worker_id}")
            for i in range(100):
                log.warning("thread %d event %d", worker_id, i)
        except BaseException as exc:  # pragma: no cover - defensive
            with errors_lock:
                errors.append(exc)

    try:
        threads = [
            threading.Thread(target=_worker, args=(wid,), name=f"pp7-w{wid}")
            for wid in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
            assert not t.is_alive(), f"worker {t.name} did not finish in 30s"

        assert errors == [], f"workers raised: {errors!r}"
        events = collector.events()
        assert len(events) == 800, (
            f"expected 800 captured events, got {len(events)}"
        )
        # Every worker's tag should be represented in the stats.
        stats = collector.stats()
        for wid in range(8):
            key = f"subsystem:worker_{wid}"
            assert stats[key] == 100, (
                f"{key} = {stats.get(key)}, expected 100"
            )
    finally:
        collector.uninstall()


# ---------------------------------------------------------------------------
# Test 4 — install / uninstall / re-install cycle
# ---------------------------------------------------------------------------


def test_diagnostics_install_uninstall_cycle():
    """During the uninstalled gap, emitted warnings must NOT be captured.

    Emit 10 → uninstall → emit 10 (skipped) → re-install → emit 10.
    Final buffer count is 20; the 10 middle events are gone.
    """
    collector = DiagnosticsCollector(max_events=100, min_level="WARNING")
    log = logging.getLogger("pharos_engine.cycle_test")

    try:
        # Phase 1 — installed, 10 events captured.
        collector.install()
        assert collector.is_installed()
        for i in range(10):
            log.warning("phase-1-%d", i)
        assert len(collector.events()) == 10

        # Phase 2 — uninstalled, 10 events must be dropped on the floor.
        collector.uninstall()
        assert not collector.is_installed()
        for i in range(10):
            log.warning("phase-2-%d", i)
        # Buffer unchanged during the uninstalled window.
        assert len(collector.events()) == 10, (
            "events must not be captured while uninstalled"
        )

        # Phase 3 — re-installed, 10 more events captured, total 20.
        collector.install()
        assert collector.is_installed()
        for i in range(10):
            log.warning("phase-3-%d", i)
        events = collector.events()
        assert len(events) == 20, (
            f"expected 20 total after re-install, got {len(events)}"
        )

        # None of the phase-2 messages leaked into the buffer.
        messages = [e.message for e in events]
        assert not any("phase-2-" in m for m in messages), (
            "phase-2 events were captured despite the uninstalled window"
        )
        # First 10 are phase-1, next 10 are phase-3, in emit order.
        assert all("phase-1-" in m for m in messages[:10])
        assert all("phase-3-" in m for m in messages[10:])
    finally:
        collector.uninstall()
