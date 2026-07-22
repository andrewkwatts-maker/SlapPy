"""Tests for the live-reload watcher on :class:`UserOverrideLoader`.

Task X6 landed the following surface:

* ``UserOverrideLoader.watch_dir(cb)`` — background watcher; fires
  ``cb(event_kind, file_path)`` with debounced events.
* ``UserOverrideLoader.reload_all()`` → :class:`ReloadedBundle` —
  atomic reload of every category.
* ``UserOverrideLoader.autoreload(on_reload)`` — end-to-end wire of
  ``watch_dir`` + ``reload_all``.
* :class:`WatcherHandle` / :class:`NullWatcherHandle` — clean-shutdown
  handles; ``NullWatcherHandle`` is returned when :mod:`watchdog` is
  not importable.

Event-driven tests below are marked with :func:`pytest.importorskip`
so the suite still runs on machines without ``watchdog`` installed.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from pharos_editor.ui.user_overrides import (
    NullWatcherHandle,
    ReloadedBundle,
    UserOverrideBundle,
    UserOverrideLoader,
    WatcherHandle,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def loader(tmp_path: Path) -> UserOverrideLoader:
    """A loader rooted at a tmp path (never touches ``~/.pharos_engine``)."""
    root = tmp_path / "ui"
    loader = UserOverrideLoader(root=root)
    loader.ensure_scaffolded()
    return loader


class _Sink:
    """Thread-safe collector for callback invocations.

    Provides a ``wait_for(count, timeout)`` helper so tests can block
    on a definite number of events rather than sleeping a fixed
    duration.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, Path]] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def __call__(self, kind: str, path: Path) -> None:
        with self._cond:
            self.events.append((kind, path))
            self._cond.notify_all()

    def wait_for(self, count: int, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while len(self.events) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def kinds(self) -> list[str]:
        with self._lock:
            return [k for k, _ in self.events]

    def paths(self) -> list[Path]:
        with self._lock:
            return [p for _, p in self.events]

    def clear(self) -> None:
        with self._lock:
            self.events.clear()


def _touch(path: Path, body: str = "x") -> None:
    """Write ``body`` to ``path``, creating parent dirs first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# NullWatcherHandle — always safe, always inert
# ---------------------------------------------------------------------------


def test_null_watcher_handle_is_not_running() -> None:
    """``NullWatcherHandle`` reports ``is_running() -> False``."""
    handle = NullWatcherHandle()
    assert handle.is_running() is False


def test_null_watcher_handle_stop_is_noop() -> None:
    """``NullWatcherHandle.stop()`` never raises + stays inert."""
    handle = NullWatcherHandle()
    handle.stop()
    handle.stop()
    assert handle.is_running() is False


def test_null_watcher_handle_is_watcher_handle_subclass() -> None:
    """``NullWatcherHandle`` obeys the :class:`WatcherHandle` contract."""
    assert isinstance(NullWatcherHandle(), WatcherHandle)


def test_null_watcher_handle_supports_context_manager() -> None:
    """``NullWatcherHandle`` can be used as a ``with`` block."""
    with NullWatcherHandle() as handle:
        assert handle.is_running() is False


def test_watch_dir_returns_handle(loader: UserOverrideLoader) -> None:
    """``watch_dir`` always returns *some* :class:`WatcherHandle`."""
    handle = loader.watch_dir(lambda _k, _p: None)
    try:
        assert isinstance(handle, WatcherHandle)
    finally:
        handle.stop()


def test_watch_dir_missing_watchdog_returns_null(
    loader: UserOverrideLoader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When :mod:`watchdog` cannot be imported, we get a :class:`NullWatcherHandle`."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kw: Any) -> Any:
        if name.startswith("watchdog"):
            raise ImportError("simulated missing watchdog")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Reset warned flag so we don't skip the branch under test.
    import pharos_editor.ui.user_overrides as mod
    monkeypatch.setattr(mod, "_WATCHDOG_WARNED", False)

    handle = loader.watch_dir(lambda _k, _p: None)
    assert isinstance(handle, NullWatcherHandle)
    handle.stop()


def test_watch_dir_missing_watchdog_only_warns_once(
    loader: UserOverrideLoader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Second call with missing watchdog should not re-log the warning."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kw: Any) -> Any:
        if name.startswith("watchdog"):
            raise ImportError("simulated missing watchdog")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import pharos_editor.ui.user_overrides as mod
    monkeypatch.setattr(mod, "_WATCHDOG_WARNED", False)

    with caplog.at_level("WARNING", logger="pharos_editor.ui.user_overrides"):
        loader.watch_dir(lambda _k, _p: None).stop()
        first_count = sum(
            1 for r in caplog.records if "watchdog not installed" in r.getMessage()
        )
        loader.watch_dir(lambda _k, _p: None).stop()
        second_count = sum(
            1 for r in caplog.records if "watchdog not installed" in r.getMessage()
        )
    assert first_count == 1
    assert second_count == 1  # unchanged after 2nd call


# ---------------------------------------------------------------------------
# reload_all — atomic, dataclass-shaped
# ---------------------------------------------------------------------------


def test_reload_all_returns_reloaded_bundle(loader: UserOverrideLoader) -> None:
    """``reload_all()`` returns a :class:`ReloadedBundle` with all fields."""
    reloaded = loader.reload_all()
    assert isinstance(reloaded, ReloadedBundle)
    assert isinstance(reloaded.bundle, UserOverrideBundle)
    # All categories exposed via passthroughs.
    assert isinstance(reloaded.panels, list)
    assert isinstance(reloaded.hotkey_bindings, dict)
    assert isinstance(reloaded.hotkey_commands, dict)
    assert isinstance(reloaded.spawn_actions, list)
    assert isinstance(reloaded.shaders, dict)
    assert isinstance(reloaded.shader_kinds, dict)
    assert isinstance(reloaded.config, dict)
    assert isinstance(reloaded.errors, list)


def test_reload_all_first_call_has_no_previous(loader: UserOverrideLoader) -> None:
    """First :meth:`reload_all` returns ``previous_bundle=None``."""
    reloaded = loader.reload_all()
    assert reloaded.previous_bundle is None


def test_reload_all_threads_previous(loader: UserOverrideLoader) -> None:
    """Passing ``previous=`` links reloads into a chain."""
    r1 = loader.reload_all()
    r2 = loader.reload_all(previous=r1)
    assert r2.previous_bundle is r1


def test_reload_all_summary_matches_load_all(loader: UserOverrideLoader) -> None:
    """The summary should match a raw :meth:`load_all` result."""
    reloaded = loader.reload_all()
    direct = loader.load_all()
    assert reloaded.summary() == direct.summary()


def test_reload_all_atomically_swaps_bundle(loader: UserOverrideLoader) -> None:
    """A new reload returns a distinct bundle instance (never mutated in place)."""
    r1 = loader.reload_all()
    r2 = loader.reload_all(previous=r1)
    assert r1.bundle is not r2.bundle


def test_reload_all_picks_up_new_shader(loader: UserOverrideLoader) -> None:
    """A newly written shader shows up on the next :meth:`reload_all`."""
    shader = loader.root / "shaders" / "page_linings" / "brand_new.wgsl"
    _touch(shader, "@fragment fn fs_main() {}")
    reloaded = loader.reload_all()
    assert "brand_new" in reloaded.shaders
    assert reloaded.shader_kinds["brand_new"] == "page_linings"


def test_reload_all_config_defaults_present(loader: UserOverrideLoader) -> None:
    """Config toggles default to ``True`` after reload."""
    reloaded = loader.reload_all()
    assert reloaded.config.get("enable_user_panels") is True
    assert reloaded.config.get("enable_user_shaders") is True


def test_reloaded_bundle_reloaded_at_is_recent(loader: UserOverrideLoader) -> None:
    """``reloaded_at`` timestamp is close to *now* (± 5s slack)."""
    before = time.time()
    reloaded = loader.reload_all()
    after = time.time()
    assert before - 1.0 <= reloaded.reloaded_at <= after + 1.0


# ---------------------------------------------------------------------------
# Watcher — event delivery. Requires watchdog.
# ---------------------------------------------------------------------------


watchdog = pytest.importorskip(
    "watchdog", reason="watchdog is a soft dep — install to exercise the pump",
)


@pytest.fixture()
def sink() -> _Sink:
    return _Sink()


def test_watcher_fires_on_create(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """A newly written file triggers a ``created`` callback."""
    with loader.watch_dir(sink, debounce=0.05) as handle:
        assert handle.is_running() is True
        target = loader.root / "panels" / "my_panel.py"
        _touch(target, "def get_panel(): return object()\n")
        assert sink.wait_for(1, timeout=3.0), sink.events
    kinds = sink.kinds()
    assert "created" in kinds or "modified" in kinds


def test_watcher_fires_on_modify(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Rewriting an existing file fires a ``modified`` callback."""
    target = loader.root / "panels" / "existing.py"
    _touch(target, "def get_panel(): return object()\n")
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)  # let the observer settle before we mutate
        target.write_text(
            "def get_panel(): return object()  # v2\n", encoding="utf-8",
        )
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert any(k in ("modified", "created") for k in sink.kinds())


def test_watcher_fires_on_delete(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Deleting a file fires a ``deleted`` callback."""
    target = loader.root / "panels" / "doomed.py"
    _touch(target, "def get_panel(): return object()\n")
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)
        target.unlink()
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert "deleted" in sink.kinds()


def test_watcher_debounces_burst(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Five rapid writes to the same file collapse to a single callback."""
    target = loader.root / "panels" / "burst.py"
    _touch(target, "v0\n")
    with loader.watch_dir(sink, debounce=0.15):
        time.sleep(0.05)
        for i in range(5):
            target.write_text(f"v{i}\n", encoding="utf-8")
            time.sleep(0.005)  # tighter than debounce window
        assert sink.wait_for(1, timeout=3.0), sink.events
        time.sleep(0.4)  # give any tail events time to appear
    # Debouncer should collapse the burst to a single event for
    # ``burst.py``. We do not assert exactly 1 because watchdog on some
    # OSes emits a stray create+modify pair, but it MUST be << 5.
    burst_events = [e for e in sink.events if Path(e[1]).name == "burst.py"]
    assert 1 <= len(burst_events) <= 2, sink.events


def test_watcher_filters_dot_prefix(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Files starting with '.' are ignored."""
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)
        _touch(loader.root / "panels" / ".hidden.py", "x")
        time.sleep(0.4)
    for _kind, path in sink.events:
        assert not path.name.startswith(".")


def test_watcher_filters_underscore_prefix(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Files starting with '_' are ignored (matches loader convention)."""
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)
        _touch(loader.root / "panels" / "_example.py", "x")
        time.sleep(0.4)
    for _kind, path in sink.events:
        assert not path.name.startswith("_")


def test_watcher_passes_through_normal_files(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """A normally named file is *not* filtered."""
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)
        _touch(loader.root / "panels" / "keep.py", "x")
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert any(p.name == "keep.py" for p in sink.paths())


def test_watcher_stop_joins_thread(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """``handle.stop()`` shuts the pump thread down within the timeout."""
    handle = loader.watch_dir(sink, debounce=0.05)
    assert handle.is_running() is True
    handle.stop(timeout=3.0)
    assert handle.is_running() is False


def test_watcher_stop_is_idempotent(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Calling :meth:`stop` twice is safe."""
    handle = loader.watch_dir(sink, debounce=0.05)
    handle.stop()
    handle.stop()  # must not raise
    assert handle.is_running() is False


def test_watcher_callback_exceptions_do_not_kill_pump(
    loader: UserOverrideLoader,
) -> None:
    """A callback that raises must NOT stop the watcher thread."""
    call_count = {"n": 0}
    stopped_event = threading.Event()

    def cb(_kind: str, _path: Path) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        stopped_event.set()

    with loader.watch_dir(cb, debounce=0.05) as handle:
        time.sleep(0.1)
        _touch(loader.root / "panels" / "a.py", "1")
        time.sleep(0.3)
        _touch(loader.root / "panels" / "b.py", "2")
        assert stopped_event.wait(timeout=3.0)
        # Pump is still alive after the raise.
        assert handle.is_running() is True


def test_watcher_ignores_directories(
    loader: UserOverrideLoader, sink: _Sink,
) -> None:
    """Directory events do not fire the callback."""
    with loader.watch_dir(sink, debounce=0.05):
        time.sleep(0.1)
        (loader.root / "panels" / "subdir").mkdir()
        time.sleep(0.4)
    for _kind, path in sink.events:
        # We only care that the callback wasn't invoked for the
        # bare directory — any files under it would be OK.
        assert path.name != "subdir"


# ---------------------------------------------------------------------------
# autoreload — end-to-end pipeline
# ---------------------------------------------------------------------------


def test_autoreload_fires_reload_on_change(
    loader: UserOverrideLoader,
) -> None:
    """A file drop triggers :meth:`reload_all` + delivers the bundle."""
    reloads: list[ReloadedBundle] = []
    got = threading.Event()

    def on_reload(bundle: ReloadedBundle) -> None:
        reloads.append(bundle)
        got.set()

    with loader.autoreload(on_reload, debounce=0.1):
        time.sleep(0.1)
        _touch(
            loader.root / "shaders" / "page_linings" / "auto_lining.wgsl",
            "@fragment fn fs_main() {}\n",
        )
        assert got.wait(timeout=3.0), reloads

    assert reloads, "autoreload should have fired at least one bundle"
    latest = reloads[-1]
    assert isinstance(latest, ReloadedBundle)
    assert "auto_lining" in latest.shaders


def test_autoreload_chains_previous_bundles(
    loader: UserOverrideLoader,
) -> None:
    """Sequential reloads thread ``previous_bundle`` through."""
    reloads: list[ReloadedBundle] = []
    lock = threading.Lock()
    got_two = threading.Event()

    def on_reload(bundle: ReloadedBundle) -> None:
        with lock:
            reloads.append(bundle)
            if len(reloads) >= 2:
                got_two.set()

    with loader.autoreload(on_reload, debounce=0.1):
        time.sleep(0.1)
        _touch(loader.root / "shaders" / "washi_tape" / "one.wgsl", "a\n")
        time.sleep(0.4)  # let debounce fire
        _touch(loader.root / "shaders" / "washi_tape" / "two.wgsl", "b\n")
        assert got_two.wait(timeout=4.0), reloads

    with lock:
        assert len(reloads) >= 2
        # The 2nd bundle links back to the 1st.
        assert reloads[1].previous_bundle is reloads[0]


def test_autoreload_survives_on_reload_exception(
    loader: UserOverrideLoader,
) -> None:
    """An ``on_reload`` that raises does NOT kill the pipeline."""
    call_count = {"n": 0}
    second_reached = threading.Event()

    def on_reload(_bundle: ReloadedBundle) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("on_reload boom")
        second_reached.set()

    with loader.autoreload(on_reload, debounce=0.1) as handle:
        time.sleep(0.1)
        _touch(loader.root / "panels" / "one.py", "x=1\n")
        time.sleep(0.4)
        _touch(loader.root / "panels" / "two.py", "x=2\n")
        assert second_reached.wait(timeout=4.0)
        assert handle.is_running() is True


def test_autoreload_returns_watcher_handle(loader: UserOverrideLoader) -> None:
    """``autoreload`` returns a real :class:`WatcherHandle`."""
    handle = loader.autoreload(lambda _b: None, debounce=0.05)
    try:
        assert isinstance(handle, WatcherHandle)
        assert handle.is_running() is True
    finally:
        handle.stop()
        assert handle.is_running() is False
