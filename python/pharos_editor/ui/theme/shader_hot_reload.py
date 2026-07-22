"""Hot-reload watcher for WGSL theme shaders.

This module extends the AA6 shader-lint suite
(:mod:`pharos_editor.ui.theme.shader_lint`) with a filesystem watcher
that re-runs :func:`~pharos_editor.ui.theme.shader_lint.lint_wgsl`
whenever a WGSL file changes on disk.

The intended use cases are:

* **Live iteration on user-override shaders** — creators drop
  ``.wgsl`` files under ``~/.pharos_engine/ui/shaders/<library>/`` and
  see lint results update without restarting the editor.
* **Live iteration on baked-out builtin shaders** — internal tools
  can dump the embedded ``WASHI_TAPES`` / ``PAGE_LININGS`` /
  ``EDGE_STROKES`` sources to disk, edit them freely, and see the
  linter re-fire on every write.

The watcher is intentionally aligned with the X6 ``WatcherHandle``
pattern used by :mod:`pharos_editor.ui.user_overrides`:

* :mod:`watchdog` is soft-imported; when it is missing a
  :class:`NullWatcherHandle` equivalent is returned and no crash
  occurs.
* Raw filesystem events are coalesced by a 100 ms debounce pump.
* :meth:`ShaderHotReloadWatcher.stop` joins the pump + observer
  threads inside a timeout window.
* Files whose basename starts with ``_`` or ``.`` are filtered out
  (matches the loader convention — such files are treated as
  "disabled" examples).

Deliverables
------------

* :class:`ShaderChangeEvent` — dataclass describing a single change.
* :class:`ShaderHotReloadWatcher` — the watcher itself.
* :class:`WGSLShaderRegistry` — an in-memory ``{path: (source,
  lint_result)}`` cache with invalidation callbacks, populated by the
  watcher.
* :func:`start_default_hot_reload` — convenience helper that starts a
  watcher on the three built-in library dirs plus (optionally) a
  user-override shaders dir.
* :func:`hot_reload_context_manager` — a ``with``-statement wrapper
  for the watcher, mainly used by tests.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from pharos_editor.ui.theme.shader_lint import (
    SHADER_CONTRACTS,
    WGSLLintResult,
    lint_wgsl,
)


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Debounce window applied to raw filesystem events, matching the X6
#: user-override watcher default.
_DEBOUNCE_SECONDS: float = 0.100


#: Set once we've logged the "watchdog missing" warning so we don't
#: spam the log every time a watcher is started.
_WATCHDOG_WARNED: bool = False


#: Directory-name → library-name map used when auto-detecting which
#: contract applies to a given ``.wgsl`` file.  The parent directory
#: of the file is consulted first; if it matches one of these names
#: the corresponding library contract is used.
_KNOWN_LIBRARIES: tuple[str, ...] = (
    "washi_tape",
    "page_linings",
    "edge_strokes",
)


# ---------------------------------------------------------------------------
# ShaderChangeEvent
# ---------------------------------------------------------------------------


@dataclass
class ShaderChangeEvent:
    """A single debounced filesystem event for a WGSL shader.

    Attributes
    ----------
    path:
        Absolute :class:`~pathlib.Path` of the shader file that changed.
    kind:
        One of ``"created"``, ``"modified"``, ``"deleted"``.
    library:
        Library name inferred from the parent directory — one of
        ``"washi_tape"``, ``"page_linings"``, ``"edge_strokes"``, or
        ``"unknown"`` when the parent directory doesn't match any
        known library.
    lint_result:
        The :class:`WGSLLintResult` produced by re-running
        :func:`lint_wgsl` against the freshly-read source.  ``None``
        for delete events (nothing to lint) and when the file could
        not be read.
    """

    path: Path
    kind: str
    library: str
    lint_result: WGSLLintResult | None = None


# ---------------------------------------------------------------------------
# Watcher handles
# ---------------------------------------------------------------------------


class ShaderWatcherHandle:
    """Handle returned by :meth:`ShaderHotReloadWatcher.start`.

    Owns the background pump thread + the underlying watchdog
    ``Observer``.  Calling :meth:`stop` cleanly joins both. The handle
    doubles as a context manager so ``with watcher.start() as h:``
    works.
    """

    def __init__(
        self,
        observer: Any,
        stop_event: threading.Event,
        thread: threading.Thread | None,
    ) -> None:
        self._observer = observer
        self._stop_event = stop_event
        self._thread = thread
        self._stopped = False

    # -- Public API -----------------------------------------------------

    def stop(self, timeout: float = 5.0) -> None:
        """Cancel the watcher; block until threads have joined."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        obs = self._observer
        if obs is not None:
            try:
                obs.stop()
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "ShaderWatcherHandle: observer.stop() raised: %s", exc,
                )
            try:
                obs.join(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "ShaderWatcherHandle: observer.join() raised: %s", exc,
                )
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)

    def is_running(self) -> bool:
        """Return ``True`` while the pump thread is still alive."""
        if self._stopped:
            return False
        t = self._thread
        if t is None:
            return False
        return t.is_alive()

    # -- Context-manager sugar -----------------------------------------

    def __enter__(self) -> "ShaderWatcherHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401,ANN001
        self.stop()


class NullShaderWatcherHandle(ShaderWatcherHandle):
    """Placeholder returned when :mod:`watchdog` is not installed.

    Same API as :class:`ShaderWatcherHandle`, but every method is a
    no-op and :meth:`is_running` always returns ``False``.  Callers
    can treat the two interchangeably.
    """

    def __init__(self) -> None:
        super().__init__(
            observer=None,
            stop_event=threading.Event(),
            thread=None,
        )
        self._stopped = True

    def stop(self, timeout: float = 5.0) -> None:  # noqa: D401,ARG002
        """No-op."""
        return

    def is_running(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# WGSLShaderRegistry
# ---------------------------------------------------------------------------


class WGSLShaderRegistry:
    """In-memory ``{path: (source, lint_result)}`` cache.

    The registry is populated by :class:`ShaderHotReloadWatcher` on
    every change event so callers can look up "what does the linter
    currently think of this file?" without re-reading the disk.

    Thread-safe: all reads + writes go through an internal lock.
    Invalidation callbacks fire on the calling thread — keep them
    short.
    """

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[str, WGSLLintResult | None]] = {}
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[ShaderChangeEvent], None]] = []

    # -- Mutations ------------------------------------------------------

    def apply_event(self, event: ShaderChangeEvent) -> None:
        """Fold *event* into the cache + fire invalidation callbacks.

        * ``"created"`` / ``"modified"`` events store the fresh source
          + lint result under the canonical path.
        * ``"deleted"`` events drop the entry (silent no-op when the
          path was never in the cache).
        * Any other kind is ignored (defensive — future-proof against
          new watchdog event kinds).
        """
        with self._lock:
            if event.kind in ("created", "modified"):
                source = ""
                try:
                    source = event.path.read_text(encoding="utf-8")
                except OSError:
                    source = ""
                self._entries[event.path] = (source, event.lint_result)
            elif event.kind == "deleted":
                self._entries.pop(event.path, None)
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "WGSLShaderRegistry: invalidation cb raised: %s", exc,
                )

    def clear(self) -> None:
        """Drop every entry (invalidation cbs are NOT fired)."""
        with self._lock:
            self._entries.clear()

    def on_invalidate(
        self, callback: Callable[[ShaderChangeEvent], None],
    ) -> None:
        """Register a callback fired on every :meth:`apply_event`."""
        if not callable(callback):
            raise TypeError(
                f"on_invalidate: callback must be callable; got {callback!r}"
            )
        with self._lock:
            self._callbacks.append(callback)

    # -- Reads ----------------------------------------------------------

    def get(
        self, path: Path,
    ) -> tuple[str, WGSLLintResult | None] | None:
        """Return the cached ``(source, lint_result)`` for *path*, or None."""
        with self._lock:
            return self._entries.get(Path(path))

    def get_source(self, path: Path) -> str | None:
        entry = self.get(path)
        return None if entry is None else entry[0]

    def get_lint(self, path: Path) -> WGSLLintResult | None:
        entry = self.get(path)
        return None if entry is None else entry[1]

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, (str, Path)):
            return False
        with self._lock:
            return Path(path) in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def paths(self) -> list[Path]:
        with self._lock:
            return list(self._entries.keys())

    def snapshot(self) -> dict[Path, tuple[str, WGSLLintResult | None]]:
        """Return a shallow copy of the cache."""
        with self._lock:
            return dict(self._entries)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _library_for_path(path: Path) -> str:
    """Infer the library name from *path*'s parent directory.

    Returns ``"unknown"`` when no ancestor matches a known library
    name.  Walks up the tree so shaders nested under
    ``.../shaders/washi_tape/subgroup/foo.wgsl`` still resolve to
    ``"washi_tape"``.
    """
    for parent in (path.parent, *path.parents):
        name = parent.name
        if name in _KNOWN_LIBRARIES:
            return name
    return "unknown"


def _lint_file(path: Path, library: str) -> WGSLLintResult | None:
    """Read *path* and lint it against the *library* contract.

    Returns ``None`` on read failure or empty source.  Falls back to
    the ``washi_tape`` contract when *library* is unknown so the
    linter still produces *some* result — callers can inspect the
    resulting ``library`` field on the event to decide how strict to
    be.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning(
            "ShaderHotReloadWatcher: cannot read %s: %s", path, exc,
        )
        return None
    if not source:
        return None
    contract = SHADER_CONTRACTS.get(library)
    if contract is None:
        # Best-effort — use washi contract as a permissive fallback.
        contract = SHADER_CONTRACTS["washi_tape"]
    try:
        return lint_wgsl(path.stem, source, contract=contract)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "ShaderHotReloadWatcher: lint of %s raised: %s", path, exc,
        )
        return None


# ---------------------------------------------------------------------------
# ShaderHotReloadWatcher
# ---------------------------------------------------------------------------


class ShaderHotReloadWatcher:
    """Filesystem watcher that re-lints WGSL shaders on every change.

    Parameters
    ----------
    shader_dirs:
        Sequence of directories to watch.  Missing directories are
        created on :meth:`start` so watchdog doesn't raise; the
        directories may be empty at start time.
    on_change:
        Callable fired with a :class:`ShaderChangeEvent` for every
        debounced change.  Runs on the pump thread — keep it short
        and thread-safe.
    registry:
        Optional :class:`WGSLShaderRegistry` to fold each event into
        before firing ``on_change``.  When ``None`` a fresh registry
        is created and attached — :attr:`registry` exposes it.
    debounce:
        Coalesce raw filesystem events within this many seconds into
        a single callback per ``(kind, path)`` pair.  Defaults to 100
        ms.

    Attributes
    ----------
    registry:
        The attached :class:`WGSLShaderRegistry` (never ``None``).
    shader_dirs:
        The list of directories being watched.
    """

    def __init__(
        self,
        shader_dirs: Iterable[Path],
        on_change: Callable[[ShaderChangeEvent], None],
        *,
        registry: WGSLShaderRegistry | None = None,
        debounce: float = _DEBOUNCE_SECONDS,
    ) -> None:
        if not callable(on_change):
            raise TypeError(
                f"ShaderHotReloadWatcher: on_change must be callable; "
                f"got {on_change!r}"
            )
        try:
            dirs = [Path(d) for d in shader_dirs]
        except TypeError as exc:
            raise TypeError(
                "ShaderHotReloadWatcher: shader_dirs must be an iterable "
                f"of paths; got {shader_dirs!r} ({exc})"
            ) from exc
        if debounce <= 0:
            raise ValueError(
                f"ShaderHotReloadWatcher: debounce must be > 0; got {debounce!r}"
            )
        self._shader_dirs: list[Path] = dirs
        self._on_change = on_change
        self._debounce = float(debounce)
        self._handle: ShaderWatcherHandle | None = None
        self.registry: WGSLShaderRegistry = (
            registry if registry is not None else WGSLShaderRegistry()
        )

    # -- Introspection --------------------------------------------------

    @property
    def shader_dirs(self) -> list[Path]:
        return list(self._shader_dirs)

    def is_running(self) -> bool:
        return self._handle is not None and self._handle.is_running()

    # -- Lifecycle ------------------------------------------------------

    def start(self) -> ShaderWatcherHandle:
        """Arm the watcher + return a :class:`ShaderWatcherHandle`.

        Calling :meth:`start` while already running returns the
        existing handle — repeated starts are a no-op.
        """
        if self._handle is not None and self._handle.is_running():
            return self._handle

        global _WATCHDOG_WARNED
        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
            from watchdog.observers import Observer  # type: ignore[import-not-found]
        except ImportError:
            if not _WATCHDOG_WARNED:
                _log.warning(
                    "ShaderHotReloadWatcher: watchdog not installed — "
                    "hot reload disabled",
                )
                _WATCHDOG_WARNED = True
            handle = NullShaderWatcherHandle()
            self._handle = handle
            return handle

        # Ensure directories exist — watchdog raises otherwise.
        for d in self._shader_dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _log.warning(
                    "ShaderHotReloadWatcher: cannot create %s: %s", d, exc,
                )

        stop_event = threading.Event()
        pending: dict[tuple[str, str], float] = {}
        pending_lock = threading.Lock()

        def _record(kind: str, path_str: str) -> None:
            p = Path(path_str)
            # Only care about .wgsl files, and filter dot / underscore.
            if p.suffix.lower() != ".wgsl":
                return
            if p.name.startswith(".") or p.name.startswith("_"):
                return
            with pending_lock:
                pending[(kind, path_str)] = time.monotonic()

        class _Handler(FileSystemEventHandler):  # type: ignore[misc,valid-type]
            def on_created(self, event: Any) -> None:  # noqa: D401
                if getattr(event, "is_directory", False):
                    return
                _record("created", str(event.src_path))

            def on_modified(self, event: Any) -> None:  # noqa: D401
                if getattr(event, "is_directory", False):
                    return
                _record("modified", str(event.src_path))

            def on_deleted(self, event: Any) -> None:  # noqa: D401
                if getattr(event, "is_directory", False):
                    return
                _record("deleted", str(event.src_path))

            def on_moved(self, event: Any) -> None:  # noqa: D401
                if getattr(event, "is_directory", False):
                    return
                src = getattr(event, "src_path", None)
                dst = getattr(event, "dest_path", None)
                if src:
                    _record("deleted", str(src))
                if dst:
                    _record("created", str(dst))

        observer = Observer()
        try:
            for d in self._shader_dirs:
                if not d.is_dir():
                    continue
                observer.schedule(_Handler(), str(d), recursive=True)
            observer.start()
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "ShaderHotReloadWatcher: observer.start() raised: %s", exc,
            )
            handle = NullShaderWatcherHandle()
            self._handle = handle
            return handle

        poll_interval = max(0.01, self._debounce / 4.0)
        debounce = self._debounce
        on_change = self._on_change
        registry = self.registry

        def _pump() -> None:
            while not stop_event.is_set():
                now = time.monotonic()
                due: list[tuple[str, str]] = []
                with pending_lock:
                    for key, ts in list(pending.items()):
                        if now - ts >= debounce:
                            due.append(key)
                            del pending[key]
                for kind, path_str in due:
                    path = Path(path_str)
                    library = _library_for_path(path)
                    lint_result: WGSLLintResult | None = None
                    if kind != "deleted":
                        lint_result = _lint_file(path, library)
                    event = ShaderChangeEvent(
                        path=path,
                        kind=kind,
                        library=library,
                        lint_result=lint_result,
                    )
                    # Fold into the registry first so the callback can
                    # inspect the up-to-date cache if it wants to.
                    try:
                        registry.apply_event(event)
                    except Exception as exc:  # noqa: BLE001
                        _log.warning(
                            "ShaderHotReloadWatcher: registry.apply_event "
                            "raised: %s", exc,
                        )
                    try:
                        on_change(event)
                    except Exception as exc:  # noqa: BLE001
                        _log.warning(
                            "ShaderHotReloadWatcher: on_change raised on "
                            "(%s, %s): %s", kind, path_str, exc,
                        )
                stop_event.wait(poll_interval)

        thread = threading.Thread(
            target=_pump,
            name="ShaderHotReloadWatcher.pump",
            daemon=True,
        )
        thread.start()
        handle = ShaderWatcherHandle(
            observer=observer, stop_event=stop_event, thread=thread,
        )
        self._handle = handle
        return handle

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the watcher (no-op when not running)."""
        if self._handle is None:
            return
        self._handle.stop(timeout=timeout)
        self._handle = None


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def _default_theme_dirs() -> list[Path]:
    """Return the three builtin theme-library dirs (may be empty on disk)."""
    theme_root = Path(__file__).parent
    return [
        theme_root / "washi_tape",
        theme_root / "page_linings",
        theme_root / "edge_strokes",
    ]


def _default_user_shader_dirs(user_dir: Path | None) -> list[Path]:
    """Return the user-override shader dirs — one per known library."""
    if user_dir is None:
        user_dir = Path.home() / ".pharos_engine" / "ui" / "shaders"
    else:
        user_dir = Path(user_dir)
    return [user_dir / lib for lib in _KNOWN_LIBRARIES]


def start_default_hot_reload(
    user_dir: Path | None = None,
    *,
    on_change: Callable[[ShaderChangeEvent], None] | None = None,
    include_builtins: bool = True,
    registry: WGSLShaderRegistry | None = None,
    debounce: float = _DEBOUNCE_SECONDS,
) -> ShaderHotReloadWatcher:
    """Start a watcher on the built-in + user-override shader dirs.

    Parameters
    ----------
    user_dir:
        Root of the user-override shader tree — typically
        ``USER_DIR / "ui" / "shaders"``.  Pass ``None`` to use the
        default (``~/.pharos_engine/ui/shaders/``); pass a concrete
        path (e.g. a ``tmp_path`` fixture) to point the watcher
        somewhere else.
    on_change:
        Callback fired on every debounced change.  Defaults to a
        no-op so callers can rely on the attached ``registry`` alone.
    include_builtins:
        When ``True`` (default) the three built-in theme dirs are
        watched too.  Pass ``False`` to only watch the user tree.
    registry:
        Optional pre-existing :class:`WGSLShaderRegistry` to fold
        events into.
    debounce:
        Debounce window in seconds.

    Returns
    -------
    ShaderHotReloadWatcher
        Already-started watcher.  Call :meth:`ShaderHotReloadWatcher.stop`
        to tear it down.
    """
    dirs: list[Path] = []
    if include_builtins:
        dirs.extend(_default_theme_dirs())
    dirs.extend(_default_user_shader_dirs(user_dir))
    cb = on_change if on_change is not None else (lambda _e: None)
    watcher = ShaderHotReloadWatcher(
        shader_dirs=dirs,
        on_change=cb,
        registry=registry,
        debounce=debounce,
    )
    watcher.start()
    return watcher


@contextlib.contextmanager
def hot_reload_context_manager(
    shader_dirs: Iterable[Path],
    on_change: Callable[[ShaderChangeEvent], None],
    *,
    registry: WGSLShaderRegistry | None = None,
    debounce: float = _DEBOUNCE_SECONDS,
) -> Iterator[ShaderHotReloadWatcher]:
    """Context manager wrapping :meth:`ShaderHotReloadWatcher.start`/``stop``.

    Example
    -------
    ::

        with hot_reload_context_manager([Path("shaders/")], on_change) as w:
            ...  # edit files; ``on_change`` fires
        # watcher is stopped + threads joined on exit
    """
    watcher = ShaderHotReloadWatcher(
        shader_dirs=shader_dirs,
        on_change=on_change,
        registry=registry,
        debounce=debounce,
    )
    watcher.start()
    try:
        yield watcher
    finally:
        watcher.stop()


__all__ = [
    "NullShaderWatcherHandle",
    "ShaderChangeEvent",
    "ShaderHotReloadWatcher",
    "ShaderWatcherHandle",
    "WGSLShaderRegistry",
    "hot_reload_context_manager",
    "start_default_hot_reload",
]
