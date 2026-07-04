"""Tests for :mod:`slappyengine.ui.theme.shader_hot_reload` (BB4).

The module extends the AA6 shader-lint suite with:

* :class:`ShaderChangeEvent` — dataclass describing a debounced change.
* :class:`ShaderHotReloadWatcher` — watchdog-backed watcher that
  re-lints WGSL files on every change.
* :class:`WGSLShaderRegistry` — in-memory cache keyed by path.
* :func:`start_default_hot_reload` + :func:`hot_reload_context_manager`
  — convenience helpers.

Watchdog-dependent tests are guarded with :func:`pytest.importorskip`
so the suite still runs on machines without ``watchdog`` installed.
The soft-import + null-handle path is exercised unconditionally by
monkey-patching ``builtins.__import__``.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from slappyengine.ui.theme.shader_hot_reload import (
    NullShaderWatcherHandle,
    ShaderChangeEvent,
    ShaderHotReloadWatcher,
    ShaderWatcherHandle,
    WGSLShaderRegistry,
    hot_reload_context_manager,
    start_default_hot_reload,
)
from slappyengine.ui.theme.shader_lint import (
    SHADER_CONTRACTS,
    WGSLLintResult,
    lint_wgsl,
)


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------


# A minimal WGSL fragment shader that passes the washi_tape contract.
_VALID_WASHI = (
    "struct U { u_time: f32, u_size: vec2<f32>, "
    "u_theme_color_1: vec4<f32>, u_theme_color_2: vec4<f32> };\n"
    "@group(0) @binding(0) var<uniform> u: U;\n"
    "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
    "  return u.u_theme_color_1;\n"
    "}\n"
)


class _Sink:
    """Thread-safe collector for :class:`ShaderChangeEvent` callbacks."""

    def __init__(self) -> None:
        self.events: list[ShaderChangeEvent] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def __call__(self, event: ShaderChangeEvent) -> None:
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def wait_for(self, count: int, timeout: float = 3.0) -> bool:
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
            return [e.kind for e in self.events]

    def paths(self) -> list[Path]:
        with self._lock:
            return [e.path for e in self.events]


@pytest.fixture()
def shader_root(tmp_path: Path) -> Path:
    """Create three empty theme subdirs under *tmp_path* and return the root."""
    for lib in ("washi_tape", "page_linings", "edge_strokes"):
        (tmp_path / lib).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def sink() -> _Sink:
    return _Sink()


# ---------------------------------------------------------------------------
# ShaderChangeEvent — dataclass shape
# ---------------------------------------------------------------------------


def test_shader_change_event_fields() -> None:
    """``ShaderChangeEvent`` carries path / kind / library / lint_result."""
    event = ShaderChangeEvent(
        path=Path("x.wgsl"),
        kind="created",
        library="washi_tape",
        lint_result=None,
    )
    assert event.path == Path("x.wgsl")
    assert event.kind == "created"
    assert event.library == "washi_tape"
    assert event.lint_result is None


def test_shader_change_event_defaults_lint_none() -> None:
    """``lint_result`` defaults to ``None``."""
    event = ShaderChangeEvent(
        path=Path("y.wgsl"), kind="modified", library="page_linings",
    )
    assert event.lint_result is None


def test_shader_change_event_carries_lint_result() -> None:
    """A caller-provided :class:`WGSLLintResult` is preserved verbatim."""
    result = lint_wgsl(
        "test", _VALID_WASHI, contract=SHADER_CONTRACTS["washi_tape"],
    )
    event = ShaderChangeEvent(
        path=Path("a.wgsl"),
        kind="modified",
        library="washi_tape",
        lint_result=result,
    )
    assert event.lint_result is result
    assert isinstance(event.lint_result, WGSLLintResult)


# ---------------------------------------------------------------------------
# NullShaderWatcherHandle — always safe, always inert
# ---------------------------------------------------------------------------


def test_null_handle_is_watcher_subclass() -> None:
    assert isinstance(NullShaderWatcherHandle(), ShaderWatcherHandle)


def test_null_handle_not_running() -> None:
    handle = NullShaderWatcherHandle()
    assert handle.is_running() is False


def test_null_handle_stop_is_noop() -> None:
    handle = NullShaderWatcherHandle()
    handle.stop()
    handle.stop()  # repeated calls are safe
    assert handle.is_running() is False


def test_null_handle_supports_context_manager() -> None:
    with NullShaderWatcherHandle() as handle:
        assert handle.is_running() is False


# ---------------------------------------------------------------------------
# WGSLShaderRegistry — cache semantics
# ---------------------------------------------------------------------------


def test_registry_starts_empty() -> None:
    reg = WGSLShaderRegistry()
    assert len(reg) == 0
    assert reg.paths() == []


def test_registry_caches_by_path(shader_root: Path) -> None:
    """A created/modified event stores ``(source, lint_result)``."""
    reg = WGSLShaderRegistry()
    shader = shader_root / "washi_tape" / "a.wgsl"
    shader.write_text(_VALID_WASHI, encoding="utf-8")
    lint = lint_wgsl(
        "a", _VALID_WASHI, contract=SHADER_CONTRACTS["washi_tape"],
    )
    event = ShaderChangeEvent(
        path=shader, kind="created", library="washi_tape", lint_result=lint,
    )
    reg.apply_event(event)
    assert shader in reg
    entry = reg.get(shader)
    assert entry is not None
    source, cached_lint = entry
    assert _VALID_WASHI == source
    assert cached_lint is lint


def test_registry_delete_removes_entry(shader_root: Path) -> None:
    reg = WGSLShaderRegistry()
    shader = shader_root / "washi_tape" / "b.wgsl"
    shader.write_text(_VALID_WASHI, encoding="utf-8")
    reg.apply_event(
        ShaderChangeEvent(
            path=shader, kind="created", library="washi_tape",
        )
    )
    assert shader in reg
    reg.apply_event(
        ShaderChangeEvent(
            path=shader, kind="deleted", library="washi_tape",
        )
    )
    assert shader not in reg


def test_registry_clear() -> None:
    reg = WGSLShaderRegistry()
    reg.apply_event(
        ShaderChangeEvent(
            path=Path("z.wgsl"), kind="created", library="unknown",
        )
    )
    reg.clear()
    assert len(reg) == 0


def test_registry_fires_invalidation_callback() -> None:
    reg = WGSLShaderRegistry()
    seen: list[ShaderChangeEvent] = []
    reg.on_invalidate(seen.append)
    event = ShaderChangeEvent(
        path=Path("q.wgsl"), kind="created", library="unknown",
    )
    reg.apply_event(event)
    assert seen == [event]


def test_registry_on_invalidate_rejects_non_callable() -> None:
    reg = WGSLShaderRegistry()
    with pytest.raises(TypeError):
        reg.on_invalidate("not callable")  # type: ignore[arg-type]


def test_registry_get_source_and_lint(shader_root: Path) -> None:
    reg = WGSLShaderRegistry()
    shader = shader_root / "washi_tape" / "c.wgsl"
    shader.write_text(_VALID_WASHI, encoding="utf-8")
    lint = lint_wgsl(
        "c", _VALID_WASHI, contract=SHADER_CONTRACTS["washi_tape"],
    )
    reg.apply_event(
        ShaderChangeEvent(
            path=shader,
            kind="modified",
            library="washi_tape",
            lint_result=lint,
        )
    )
    assert reg.get_source(shader) == _VALID_WASHI
    assert reg.get_lint(shader) is lint


def test_registry_get_missing_returns_none() -> None:
    reg = WGSLShaderRegistry()
    assert reg.get(Path("nope.wgsl")) is None
    assert reg.get_source(Path("nope.wgsl")) is None
    assert reg.get_lint(Path("nope.wgsl")) is None


def test_registry_snapshot_is_shallow_copy() -> None:
    reg = WGSLShaderRegistry()
    reg.apply_event(
        ShaderChangeEvent(
            path=Path("snap.wgsl"), kind="created", library="unknown",
        )
    )
    snap = reg.snapshot()
    assert Path("snap.wgsl") in snap
    # Mutating the snapshot does NOT affect the registry.
    snap.clear()
    assert Path("snap.wgsl") in reg


def test_registry_contains_rejects_non_path() -> None:
    reg = WGSLShaderRegistry()
    assert (123 in reg) is False  # type: ignore[operator]
    assert (None in reg) is False


# ---------------------------------------------------------------------------
# ShaderHotReloadWatcher — construction + validation
# ---------------------------------------------------------------------------


def test_watcher_rejects_non_callable_on_change(shader_root: Path) -> None:
    with pytest.raises(TypeError):
        ShaderHotReloadWatcher(
            shader_dirs=[shader_root], on_change="not callable",  # type: ignore[arg-type]
        )


def test_watcher_rejects_zero_debounce(shader_root: Path) -> None:
    with pytest.raises(ValueError):
        ShaderHotReloadWatcher(
            shader_dirs=[shader_root], on_change=lambda _e: None, debounce=0.0,
        )


def test_watcher_exposes_shader_dirs(shader_root: Path) -> None:
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=lambda _e: None,
    )
    assert watcher.shader_dirs == [shader_root / "washi_tape"]


def test_watcher_attaches_default_registry(shader_root: Path) -> None:
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root], on_change=lambda _e: None,
    )
    assert isinstance(watcher.registry, WGSLShaderRegistry)


def test_watcher_accepts_external_registry(shader_root: Path) -> None:
    reg = WGSLShaderRegistry()
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root], on_change=lambda _e: None, registry=reg,
    )
    assert watcher.registry is reg


def test_watcher_is_not_running_until_started(shader_root: Path) -> None:
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root], on_change=lambda _e: None,
    )
    assert watcher.is_running() is False


def test_watcher_stop_when_not_started_is_noop(shader_root: Path) -> None:
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root], on_change=lambda _e: None,
    )
    watcher.stop()  # must not raise
    assert watcher.is_running() is False


# ---------------------------------------------------------------------------
# Missing watchdog — null handle path (unconditional)
# ---------------------------------------------------------------------------


def test_missing_watchdog_returns_null_handle(
    shader_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When :mod:`watchdog` cannot be imported, ``.start()`` returns a null handle."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kw: Any) -> Any:
        if name.startswith("watchdog"):
            raise ImportError("simulated missing watchdog")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import slappyengine.ui.theme.shader_hot_reload as mod
    monkeypatch.setattr(mod, "_WATCHDOG_WARNED", False)

    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root], on_change=lambda _e: None,
    )
    handle = watcher.start()
    try:
        assert isinstance(handle, NullShaderWatcherHandle)
        assert handle.is_running() is False
    finally:
        watcher.stop()


def test_missing_watchdog_warns_only_once(
    shader_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kw: Any) -> Any:
        if name.startswith("watchdog"):
            raise ImportError("simulated missing watchdog")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import slappyengine.ui.theme.shader_hot_reload as mod
    monkeypatch.setattr(mod, "_WATCHDOG_WARNED", False)

    with caplog.at_level("WARNING", logger="slappyengine.ui.theme.shader_hot_reload"):
        for _ in range(3):
            watcher = ShaderHotReloadWatcher(
                shader_dirs=[shader_root], on_change=lambda _e: None,
            )
            watcher.start()
            watcher.stop()
        warns = [
            r for r in caplog.records
            if "watchdog not installed" in r.getMessage()
        ]
    assert len(warns) == 1


# ---------------------------------------------------------------------------
# start_default_hot_reload — safe without a user_dir
# ---------------------------------------------------------------------------


def test_start_default_hot_reload_without_user_dir(tmp_path: Path) -> None:
    """Passing ``user_dir=None`` uses the default and does not crash."""
    watcher = start_default_hot_reload(
        user_dir=None,
        include_builtins=False,
        on_change=lambda _e: None,
        debounce=0.05,
    )
    try:
        assert isinstance(watcher, ShaderHotReloadWatcher)
        # Should have wired up the three known-library subdirs under the
        # default user dir.
        assert any("washi_tape" in str(p) for p in watcher.shader_dirs)
        assert any("page_linings" in str(p) for p in watcher.shader_dirs)
        assert any("edge_strokes" in str(p) for p in watcher.shader_dirs)
    finally:
        watcher.stop()


def test_start_default_hot_reload_with_user_dir(tmp_path: Path) -> None:
    """Passing a concrete ``user_dir`` routes the watcher there."""
    user_dir = tmp_path / "user_ui_shaders"
    watcher = start_default_hot_reload(
        user_dir=user_dir,
        include_builtins=False,
        on_change=lambda _e: None,
        debounce=0.05,
    )
    try:
        assert user_dir / "washi_tape" in watcher.shader_dirs
        assert user_dir / "page_linings" in watcher.shader_dirs
        assert user_dir / "edge_strokes" in watcher.shader_dirs
    finally:
        watcher.stop()


def test_start_default_hot_reload_includes_builtins(tmp_path: Path) -> None:
    """``include_builtins=True`` adds the three shipped theme dirs."""
    watcher = start_default_hot_reload(
        user_dir=tmp_path,
        include_builtins=True,
        on_change=lambda _e: None,
        debounce=0.05,
    )
    try:
        # We should have >=6 dirs (3 built-in + 3 user).
        assert len(watcher.shader_dirs) >= 6
    finally:
        watcher.stop()


# ---------------------------------------------------------------------------
# hot_reload_context_manager — start + stop bookend
# ---------------------------------------------------------------------------


def test_context_manager_starts_and_stops(
    shader_root: Path, sink: _Sink,
) -> None:
    """The context manager arms the watcher on ``__enter__`` and joins on exit."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ) as watcher:
        assert isinstance(watcher, ShaderHotReloadWatcher)
        # If watchdog is present the watcher should actually be running;
        # if not, ``is_running()`` returns False. Either way it must be a bool.
        assert isinstance(watcher.is_running(), bool)
    # After the block the pump is stopped.
    assert watcher.is_running() is False


def test_context_manager_stops_on_exception(shader_root: Path) -> None:
    """Exceptions inside the ``with`` block still tear the watcher down."""
    watcher_ref: dict[str, ShaderHotReloadWatcher] = {}
    with pytest.raises(RuntimeError, match="boom"):
        with hot_reload_context_manager(
            [shader_root / "washi_tape"], lambda _e: None, debounce=0.05,
        ) as watcher:
            watcher_ref["w"] = watcher
            raise RuntimeError("boom")
    assert watcher_ref["w"].is_running() is False


# ---------------------------------------------------------------------------
# Watcher event delivery — requires watchdog
# ---------------------------------------------------------------------------


def _watchdog_available() -> bool:
    try:
        import watchdog  # noqa: F401
    except ImportError:
        return False
    return True


needs_watchdog = pytest.mark.skipif(
    not _watchdog_available(),
    reason="watchdog is a soft dep — install to exercise the pump",
)


@needs_watchdog
def test_watcher_fires_on_create(
    shader_root: Path, sink: _Sink,
) -> None:
    """A newly written ``.wgsl`` triggers a ``created`` event."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ) as watcher:
        assert watcher.is_running() is True
        (shader_root / "washi_tape" / "new.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        assert sink.wait_for(1, timeout=3.0), sink.events
    kinds = sink.kinds()
    assert "created" in kinds or "modified" in kinds


@needs_watchdog
def test_watcher_fires_on_modify(
    shader_root: Path, sink: _Sink,
) -> None:
    """Rewriting an existing shader fires a ``modified`` event."""
    target = shader_root / "washi_tape" / "existing.wgsl"
    target.write_text(_VALID_WASHI, encoding="utf-8")
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        # Overwrite with a trivial byte change.
        target.write_text(_VALID_WASHI + "// v2\n", encoding="utf-8")
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert any(k in ("modified", "created") for k in sink.kinds())


@needs_watchdog
def test_watcher_fires_on_delete(
    shader_root: Path, sink: _Sink,
) -> None:
    """Deleting a shader fires a ``deleted`` event."""
    target = shader_root / "washi_tape" / "doomed.wgsl"
    target.write_text(_VALID_WASHI, encoding="utf-8")
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        target.unlink()
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert "deleted" in sink.kinds()


@needs_watchdog
def test_watcher_debounces_five_rapid_events(
    shader_root: Path, sink: _Sink,
) -> None:
    """Five rapid writes collapse to at most a couple of callbacks."""
    target = shader_root / "washi_tape" / "burst.wgsl"
    target.write_text("// v0\n" + _VALID_WASHI, encoding="utf-8")
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.2,
    ):
        time.sleep(0.05)
        for i in range(5):
            target.write_text(
                f"// v{i}\n" + _VALID_WASHI, encoding="utf-8",
            )
            time.sleep(0.01)
        assert sink.wait_for(1, timeout=3.0), sink.events
        time.sleep(0.5)
    burst_events = [e for e in sink.events if e.path.name == "burst.wgsl"]
    # Debounce should collapse the 5 writes → very few callbacks.
    assert 1 <= len(burst_events) <= 3, sink.events


@needs_watchdog
def test_watcher_filters_underscore_prefix(
    shader_root: Path, sink: _Sink,
) -> None:
    """Files whose basename starts with '_' are filtered out."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "washi_tape" / "_disabled.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        time.sleep(0.4)
    for event in sink.events:
        assert not event.path.name.startswith("_")


@needs_watchdog
def test_watcher_filters_dot_prefix(
    shader_root: Path, sink: _Sink,
) -> None:
    """Files whose basename starts with '.' are filtered out."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "washi_tape" / ".hidden.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        time.sleep(0.4)
    for event in sink.events:
        assert not event.path.name.startswith(".")


@needs_watchdog
def test_watcher_filters_non_wgsl(
    shader_root: Path, sink: _Sink,
) -> None:
    """Non-``.wgsl`` files never trigger a callback."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "washi_tape" / "README.md").write_text(
            "hello", encoding="utf-8",
        )
        time.sleep(0.4)
    for event in sink.events:
        assert event.path.suffix.lower() == ".wgsl"


@needs_watchdog
def test_watcher_event_carries_lint_result(
    shader_root: Path, sink: _Sink,
) -> None:
    """Every event for a created/modified WGSL file has a lint result."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "washi_tape" / "linted.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        assert sink.wait_for(1, timeout=3.0), sink.events
    for event in sink.events:
        if event.kind == "deleted":
            continue
        assert isinstance(event.lint_result, WGSLLintResult)
        assert event.lint_result.parseable is True
        assert event.lint_result.has_entry_point is True


@needs_watchdog
def test_watcher_infers_library_from_parent(
    shader_root: Path, sink: _Sink,
) -> None:
    """Shader library is inferred from the parent directory name."""
    with hot_reload_context_manager(
        [shader_root / "page_linings"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "page_linings" / "lined.wgsl").write_text(
            "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
            "  return vec4<f32>(1.0);\n"
            "}\n",
            encoding="utf-8",
        )
        assert sink.wait_for(1, timeout=3.0), sink.events
    libs = {e.library for e in sink.events}
    assert "page_linings" in libs


@needs_watchdog
def test_watcher_registry_is_populated(
    shader_root: Path,
) -> None:
    """The attached registry is populated on every event."""
    sink = _Sink()
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ) as watcher:
        time.sleep(0.1)
        target = shader_root / "washi_tape" / "cached.wgsl"
        target.write_text(_VALID_WASHI, encoding="utf-8")
        assert sink.wait_for(1, timeout=3.0), sink.events
    assert target in watcher.registry


@needs_watchdog
def test_watcher_stop_joins_threads(
    shader_root: Path, sink: _Sink,
) -> None:
    """``stop()`` joins both the observer and pump threads."""
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=sink,
        debounce=0.05,
    )
    handle = watcher.start()
    assert handle.is_running() is True
    watcher.stop(timeout=3.0)
    assert handle.is_running() is False


@needs_watchdog
def test_watcher_stop_is_idempotent(
    shader_root: Path, sink: _Sink,
) -> None:
    """Calling ``stop()`` twice is safe."""
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=sink,
        debounce=0.05,
    )
    watcher.start()
    watcher.stop()
    watcher.stop()  # must not raise


@needs_watchdog
def test_watcher_double_start_is_noop(
    shader_root: Path, sink: _Sink,
) -> None:
    """A second ``start()`` while already running returns the same handle."""
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=sink,
        debounce=0.05,
    )
    handle1 = watcher.start()
    handle2 = watcher.start()
    try:
        assert handle1 is handle2
    finally:
        watcher.stop()


@needs_watchdog
def test_watcher_callback_exception_does_not_kill_pump(
    shader_root: Path,
) -> None:
    """A callback that raises must NOT stop the pump thread."""
    call_count = {"n": 0}
    second_done = threading.Event()

    def cb(_event: ShaderChangeEvent) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        second_done.set()

    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=cb,
        debounce=0.05,
    )
    handle = watcher.start()
    try:
        time.sleep(0.1)
        (shader_root / "washi_tape" / "a.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        time.sleep(0.4)
        (shader_root / "washi_tape" / "b.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        assert second_done.wait(timeout=3.0)
        assert handle.is_running() is True
    finally:
        watcher.stop()


@needs_watchdog
def test_watcher_ignores_directory_events(
    shader_root: Path, sink: _Sink,
) -> None:
    """Directory create events do NOT fire the callback."""
    with hot_reload_context_manager(
        [shader_root / "washi_tape"], sink, debounce=0.05,
    ):
        time.sleep(0.1)
        (shader_root / "washi_tape" / "subgroup").mkdir()
        time.sleep(0.4)
    for event in sink.events:
        assert event.path.name != "subgroup"


@needs_watchdog
def test_watcher_registry_invalidation_callback_fires(
    shader_root: Path,
) -> None:
    """A registry ``on_invalidate`` callback fires on every event."""
    reg = WGSLShaderRegistry()
    invalidated: list[ShaderChangeEvent] = []
    reg.on_invalidate(invalidated.append)

    sink = _Sink()
    watcher = ShaderHotReloadWatcher(
        shader_dirs=[shader_root / "washi_tape"],
        on_change=sink,
        registry=reg,
        debounce=0.05,
    )
    watcher.start()
    try:
        time.sleep(0.1)
        (shader_root / "washi_tape" / "inv.wgsl").write_text(
            _VALID_WASHI, encoding="utf-8",
        )
        assert sink.wait_for(1, timeout=3.0), sink.events
        time.sleep(0.1)
    finally:
        watcher.stop()

    assert invalidated, "invalidation callback should have fired"
