"""Tripwire suite for ``slappyengine.autosave`` — sprint Y6.

Covers:

* :class:`AutosaveState` field defaults + validation.
* :class:`AutosaveManager` lifecycle (start / stop / re-start).
* Timer actually fires the ``save_callback`` at the configured interval.
* ``force_save`` writes a snapshot outside the timer path.
* Ring buffer prunes beyond ``max_snapshots``.
* ``list_snapshots`` returns newest-first, ``latest_snapshot`` picks the
  head.
* :class:`RecoveryPrompt` returns an offer iff the snapshot is newer
  than the project's last-saved timestamp; ``None`` otherwise.
* ``restore_snapshot`` round-trips arbitrary payloads (dict, str, bytes).
* Concurrent ``force_save`` + timer ticks don't corrupt state (lock
  stress test).

All tests use ``tmp_path`` for the snapshot dir so the suite never
touches the user's ``~/.slappyengine/`` directory. Short timer intervals
(``0.02 s``) plus tight sleeps keep the full run under ~2 s.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from slappyengine.autosave import (
    AutosaveManager,
    AutosaveState,
    RecoveryChoice,
    RecoveryOffer,
    RecoveryPrompt,
    default_snapshot_dir,
    snapshot_timestamp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path, **overrides) -> AutosaveState:
    """Build an :class:`AutosaveState` under ``tmp_path`` with fast defaults."""
    defaults = dict(
        enabled=True,
        interval_seconds=0.02,
        snapshot_dir=tmp_path / "autosave",
        max_snapshots=5,
    )
    defaults.update(overrides)
    return AutosaveState(**defaults)


def _make_manager(
    tmp_path: Path,
    payload=None,
    counter: list | None = None,
    **overrides,
) -> AutosaveManager:
    """Build a manager whose callback returns *payload* and bumps *counter*."""
    state = _make_state(tmp_path, **overrides)
    project = SimpleNamespace(name="unit_test_project")

    def _callback():
        if counter is not None:
            counter.append(time.time())
        return payload if payload is not None else {"scene": "hello"}

    return AutosaveManager(state, project, _callback)


def _wait_for(pred, timeout=1.5):
    """Poll *pred* until it returns truthy or *timeout* elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------------------
# AutosaveState
# ---------------------------------------------------------------------------


def test_autosave_state_defaults(tmp_path):
    state = AutosaveState()
    assert state.enabled is True
    assert state.interval_seconds == 60.0
    assert state.max_snapshots == 20
    assert state.last_saved_at is None


def test_autosave_state_rejects_zero_interval(tmp_path):
    with pytest.raises(ValueError):
        AutosaveState(interval_seconds=0)


def test_autosave_state_rejects_negative_max(tmp_path):
    with pytest.raises(ValueError):
        AutosaveState(max_snapshots=0)


def test_autosave_state_rejects_bool_enabled(tmp_path):
    with pytest.raises(TypeError):
        AutosaveState(enabled="yes")  # type: ignore[arg-type]


def test_autosave_state_to_dict_round_trips(tmp_path):
    state = _make_state(tmp_path)
    payload = state.to_dict()
    assert payload["enabled"] is True
    assert payload["interval_seconds"] == pytest.approx(0.02)
    assert payload["max_snapshots"] == 5
    assert payload["snapshot_dir"].endswith("autosave")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_default_snapshot_dir_uses_project_name():
    path = default_snapshot_dir("MyProject")
    assert path.parts[-2:] == ("autosave", "MyProject")


def test_default_snapshot_dir_sanitises_separators():
    path = default_snapshot_dir("evil/../name")
    assert "/" not in path.name and "\\" not in path.name


def test_snapshot_timestamp_shape():
    stamp = snapshot_timestamp(1_700_000_000)
    # YYYYMMDD_HHMMSS → 15 chars including the underscore.
    assert len(stamp) == 15
    assert stamp[8] == "_"


# ---------------------------------------------------------------------------
# AutosaveManager — construction
# ---------------------------------------------------------------------------


def test_manager_rejects_wrong_state_type(tmp_path):
    with pytest.raises(TypeError):
        AutosaveManager("nope", SimpleNamespace(name="x"), lambda: {})  # type: ignore[arg-type]


def test_manager_rejects_project_without_name(tmp_path):
    state = _make_state(tmp_path)
    with pytest.raises(TypeError):
        AutosaveManager(state, object(), lambda: {})


def test_manager_rejects_non_callable(tmp_path):
    state = _make_state(tmp_path)
    with pytest.raises(TypeError):
        AutosaveManager(state, SimpleNamespace(name="x"), "not-callable")  # type: ignore[arg-type]


def test_manager_specialises_snapshot_dir_when_default(tmp_path, monkeypatch):
    # Redirect Path.home() so the default expands under tmp_path.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    state = AutosaveState()  # snapshot_dir = default
    manager = AutosaveManager(state, SimpleNamespace(name="alpha"), lambda: {})
    assert manager.snapshot_dir.parts[-2:] == ("autosave", "alpha")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_manager_start_stop_clean(tmp_path):
    manager = _make_manager(tmp_path)
    manager.start()
    assert manager.is_running is True
    manager.stop()
    assert manager.is_running is False


def test_manager_start_disabled_is_noop(tmp_path):
    manager = _make_manager(tmp_path, enabled=False)
    manager.start()
    assert manager.is_running is False


def test_manager_double_start_is_idempotent(tmp_path):
    manager = _make_manager(tmp_path)
    try:
        manager.start()
        manager.start()
        assert manager.is_running is True
    finally:
        manager.stop()


def test_manager_stop_without_start_safe(tmp_path):
    manager = _make_manager(tmp_path)
    # Should not raise even though no timer was ever armed.
    manager.stop()


# ---------------------------------------------------------------------------
# Timer ticks
# ---------------------------------------------------------------------------


def test_timer_fires_save_callback(tmp_path):
    ticks: list[float] = []
    manager = _make_manager(tmp_path, counter=ticks)
    manager.start()
    try:
        assert _wait_for(lambda: len(ticks) >= 3, timeout=1.5)
    finally:
        manager.stop()
    assert len(ticks) >= 3


def test_timer_updates_last_saved_at(tmp_path):
    manager = _make_manager(tmp_path)
    manager.start()
    try:
        assert _wait_for(
            lambda: manager.state.last_saved_at is not None,
            timeout=1.5,
        )
    finally:
        manager.stop()
    assert manager.state.last_saved_at is not None
    assert manager.state.last_saved_at <= time.time() + 0.1


def test_timer_swallows_callback_exceptions(tmp_path):
    state = _make_state(tmp_path)
    project = SimpleNamespace(name="explodes")
    calls: list[int] = []

    def _boom():
        calls.append(1)
        raise RuntimeError("nope")

    manager = AutosaveManager(state, project, _boom)
    manager.start()
    try:
        # We should still see multiple attempts — the timer must not
        # die just because one tick blew up.
        assert _wait_for(lambda: len(calls) >= 2, timeout=1.5)
    finally:
        manager.stop()


# ---------------------------------------------------------------------------
# force_save
# ---------------------------------------------------------------------------


def test_force_save_writes_snapshot(tmp_path):
    manager = _make_manager(tmp_path)
    path = manager.force_save()
    assert path.is_file()
    assert path.name.endswith(".snap.yaml")


def test_force_save_updates_last_saved_at(tmp_path):
    manager = _make_manager(tmp_path)
    assert manager.state.last_saved_at is None
    manager.force_save()
    assert manager.state.last_saved_at is not None


def test_force_save_propagates_callback_error(tmp_path):
    state = _make_state(tmp_path)
    project = SimpleNamespace(name="explodes")

    def _boom():
        raise ValueError("cannot serialise")

    manager = AutosaveManager(state, project, _boom)
    with pytest.raises(RuntimeError):
        manager.force_save()


def test_force_save_writes_multiple_distinct_files(tmp_path):
    manager = _make_manager(tmp_path)
    paths = {manager.force_save() for _ in range(5)}
    assert len(paths) == 5


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------


def test_prune_beyond_max_snapshots(tmp_path):
    manager = _make_manager(tmp_path, max_snapshots=3)
    for _ in range(6):
        manager.force_save()
    snapshots = manager.list_snapshots()
    assert len(snapshots) == 3


def test_list_snapshots_newest_first(tmp_path):
    manager = _make_manager(tmp_path, max_snapshots=10)
    paths = []
    for _ in range(4):
        paths.append(manager.force_save())
        # Bump mtimes so sort order is stable even on coarse-clock
        # filesystems (e.g. FAT32).
        time.sleep(0.01)
    snapshots = manager.list_snapshots()
    assert snapshots[0] == paths[-1]
    assert snapshots[-1] == paths[0]


def test_latest_snapshot_matches_list_head(tmp_path):
    manager = _make_manager(tmp_path)
    assert manager.latest_snapshot() is None
    manager.force_save()
    assert manager.latest_snapshot() == manager.list_snapshots()[0]


def test_list_snapshots_ignores_non_snap_files(tmp_path):
    manager = _make_manager(tmp_path)
    manager.force_save()
    stray = manager.snapshot_dir / "notes.txt"
    stray.write_text("hello", encoding="utf-8")
    snapshots = manager.list_snapshots()
    assert all(p.name.endswith(".snap.yaml") for p in snapshots)


# ---------------------------------------------------------------------------
# restore_snapshot round-trips
# ---------------------------------------------------------------------------


def test_restore_snapshot_round_trips_dict(tmp_path):
    manager = _make_manager(tmp_path, payload={"scene": {"nodes": [1, 2, 3]}})
    path = manager.force_save()
    received = []
    manager.restore_snapshot(path, received.append)
    assert received == [{"scene": {"nodes": [1, 2, 3]}}]


def test_restore_snapshot_round_trips_bytes(tmp_path):
    manager = _make_manager(tmp_path, payload=b"\x00\x01\x02\xff")
    path = manager.force_save()
    received = []
    manager.restore_snapshot(path, received.append)
    assert received == [b"\x00\x01\x02\xff"]


def test_restore_snapshot_round_trips_str(tmp_path):
    manager = _make_manager(tmp_path, payload="plain text")
    path = manager.force_save()
    received = []
    manager.restore_snapshot(path, received.append)
    assert received == ["plain text"]


def test_restore_snapshot_missing_file(tmp_path):
    manager = _make_manager(tmp_path)
    with pytest.raises(FileNotFoundError):
        manager.restore_snapshot(
            tmp_path / "nonexistent.snap.yaml", lambda _: None,
        )


# ---------------------------------------------------------------------------
# RecoveryPrompt
# ---------------------------------------------------------------------------


def test_recovery_prompt_returns_none_when_dir_missing(tmp_path):
    prompt = RecoveryPrompt(tmp_path / "does-not-exist")
    assert prompt.check() is None


def test_recovery_prompt_returns_none_when_dir_empty(tmp_path):
    (tmp_path / "empty").mkdir()
    prompt = RecoveryPrompt(tmp_path / "empty")
    assert prompt.check() is None


def test_recovery_prompt_offers_snapshot_newer_than_project(tmp_path):
    manager = _make_manager(tmp_path)
    snap_path = manager.force_save()
    # Project last-saved is way in the past — snapshot wins.
    prompt = RecoveryPrompt(manager.snapshot_dir, project_last_saved=0.0)
    offer = prompt.check()
    assert offer is not None
    assert offer.snapshot_path == snap_path


def test_recovery_prompt_returns_none_when_project_is_newer(tmp_path):
    manager = _make_manager(tmp_path)
    snap_path = manager.force_save()
    # Project last-saved is in the future — no offer.
    future = time.time() + 3600
    prompt = RecoveryPrompt(manager.snapshot_dir, project_last_saved=future)
    assert prompt.check() is None


def test_recovery_prompt_offer_when_no_project_timestamp(tmp_path):
    manager = _make_manager(tmp_path)
    manager.force_save()
    prompt = RecoveryPrompt(manager.snapshot_dir, project_last_saved=None)
    offer = prompt.check()
    assert offer is not None
    assert offer.project_last_saved is None


def test_recovery_prompt_accepts_iso_timestamp(tmp_path):
    manager = _make_manager(tmp_path)
    manager.force_save()
    prompt = RecoveryPrompt(
        manager.snapshot_dir,
        project_last_saved="1970-01-01T00:00:00Z",
    )
    offer = prompt.check()
    assert offer is not None
    assert offer.project_last_saved == pytest.approx(0.0)


def test_recovery_prompt_rejects_bad_timestamp_type(tmp_path):
    with pytest.raises(TypeError):
        RecoveryPrompt(tmp_path, project_last_saved=[1, 2])  # type: ignore[arg-type]


def test_recovery_choice_enum_values():
    assert RecoveryChoice.RESTORE.value == "restore"
    assert RecoveryChoice.DISCARD.value == "discard"
    assert RecoveryChoice.KEEP_BOTH.value == "keep_both"


def test_recovery_offer_is_frozen():
    offer = RecoveryOffer(
        snapshot_path=Path("x"),
        project_last_saved=0.0,
        snapshot_saved=1.0,
    )
    with pytest.raises(Exception):
        offer.snapshot_path = Path("y")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_force_save_and_timer_no_corruption(tmp_path):
    """Timer ticks + hammered force_saves must not corrupt the ring buffer.

    We fire force_save from a pool of threads while the timer is
    running. When both settle, every remaining file on disk must parse
    as a valid snapshot (proving no half-written state leaked).
    """
    manager = _make_manager(
        tmp_path,
        payload={"count": 42, "nested": {"a": 1, "b": [1, 2, 3]}},
        max_snapshots=8,
    )
    manager.start()
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def _worker():
        try:
            barrier.wait(timeout=2.0)
            for _ in range(10):
                manager.force_save()
        except BaseException as exc:  # pragma: no cover - test bug catch
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)
    manager.stop()

    assert not errors, f"worker errors: {errors!r}"

    # Every remaining file must be a valid, parseable snapshot.
    for path in manager.list_snapshots():
        received: list = []
        manager.restore_snapshot(path, received.append)
        assert received[0] == {"count": 42, "nested": {"a": 1, "b": [1, 2, 3]}}

    # Ring buffer must respect the cap.
    assert len(manager.list_snapshots()) <= manager.state.max_snapshots
