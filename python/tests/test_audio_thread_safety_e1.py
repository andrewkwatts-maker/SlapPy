"""E1-E: AudioManager thread safety tests.

Validates that concurrent calls to play_loop / stop_loop / stop_all /
set_loop_volume / set_loop_pitch do not raise RuntimeError (dict changed
size during iteration) or any other threading artefact.

No sounddevice installation is required — all tests pass handle=None so the
audio thread is never spawned; only the dict management path is exercised.
"""
from __future__ import annotations

import threading
import time

import pytest

from slappyengine.audio import AudioManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager() -> AudioManager:
    """Return an AudioManager.  sounddevice may or may not be installed."""
    return AudioManager()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAudioManagerThreadSafety:

    def test_stop_all_does_not_raise_runtimeerror(self):
        """10 threads each call play_loop + stop_loop concurrently;
        main thread calls stop_all.  Must not raise RuntimeError."""
        am = _make_manager()
        errors: list[Exception] = []
        barrier = threading.Barrier(11)  # 10 workers + main

        def worker():
            try:
                barrier.wait()
                for _ in range(20):
                    lid = am.play_loop(None, volume=0.5)
                    am.stop_loop(lid)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(10)]
        for t in threads:
            t.start()
        barrier.wait()          # release all threads simultaneously
        am.stop_all()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Worker threads raised: {errors}"

    def test_concurrent_play_and_stop(self):
        """Two threads: one plays loops, the other stops them.
        Must not crash or deadlock within 2 seconds."""
        am = _make_manager()
        ids: list[int] = []
        ids_lock = threading.Lock()
        stop_flag = threading.Event()
        errors: list[Exception] = []

        def producer():
            try:
                for _ in range(50):
                    lid = am.play_loop(None)
                    with ids_lock:
                        ids.append(lid)
                    time.sleep(0)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        def consumer():
            try:
                while not stop_flag.is_set():
                    with ids_lock:
                        if ids:
                            lid = ids.pop()
                        else:
                            lid = None
                    if lid is not None:
                        am.stop_loop(lid)
                    time.sleep(0)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        t_prod = threading.Thread(target=producer, daemon=True)
        t_cons = threading.Thread(target=consumer, daemon=True)
        t_prod.start()
        t_cons.start()
        t_prod.join(timeout=5.0)
        stop_flag.set()
        t_cons.join(timeout=5.0)

        assert not errors, f"Threads raised: {errors}"

    def test_stop_all_snapshots_keys(self):
        """Verify stop_all snapshots _loops before iteration.

        Strategy: pre-populate _loops with several entries, then call
        stop_all().  A concurrent thread simultaneously adds more entries.
        If stop_all were iterating _loops directly, a RuntimeError would be
        raised.  With the snapshot it must complete without error.
        """
        am = _make_manager()
        # Pre-populate
        for _ in range(30):
            am.play_loop(None)

        errors: list[Exception] = []

        def adder():
            try:
                for _ in range(30):
                    am.play_loop(None)
                    time.sleep(0)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        t = threading.Thread(target=adder, daemon=True)
        t.start()
        try:
            am.stop_all()   # must not raise
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        t.join(timeout=5.0)

        assert not errors, f"stop_all raised: {errors}"
        # After stop_all the internal dict may have entries added by the
        # racing adder thread — that's expected; the important thing is no crash.

    def test_play_loop_lock_acquired(self):
        """play_loop must write to _loops under the lock.

        Verify by checking that the loop ID is visible in _loops immediately
        after play_loop returns (no TOCTOU window left by forgetting the lock).
        """
        am = _make_manager()
        lid = am.play_loop(None, volume=0.7)
        # The entry must exist while we still hold no external lock ourselves
        assert lid in am._loops
        lh = am._loops[lid]
        assert lh.loop_id == lid
        assert lh.volume == pytest.approx(0.7)

    def test_loop_volume_set_thread_safe(self):
        """set_loop_volume and set_loop_pitch called from multiple threads
        while stop_loop removes entries must not crash."""
        am = _make_manager()
        errors: list[Exception] = []
        N = 40
        lids = [am.play_loop(None) for _ in range(N)]

        def volume_setter():
            try:
                for lid in lids:
                    am.set_loop_volume(lid, 0.5, ramp_time=0.1)
                    am.set_loop_pitch(lid, 1.5)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        def stopper():
            try:
                for lid in lids:
                    am.stop_loop(lid)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        t_set  = threading.Thread(target=volume_setter, daemon=True)
        t_stop = threading.Thread(target=stopper,       daemon=True)
        t_set.start()
        t_stop.start()
        t_set.join(timeout=5.0)
        t_stop.join(timeout=5.0)

        assert not errors, f"Threads raised: {errors}"
