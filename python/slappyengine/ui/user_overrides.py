"""User-override layer for the SlapPyEngine editor UI.

Users can drop Python files, YAML config, and WGSL shaders into
``~/.slappyengine/ui/`` to extend or replace parts of the editor
**without touching the installed package**. The loader here discovers
those files, imports them defensively, and returns a
:class:`UserOverrideBundle` that :class:`EditorShell` folds into its
built-in wiring.

Layout
------
::

    ~/.slappyengine/ui/
    ├── panels/            *.py    -> def get_panel() -> Panel
    ├── hotkeys/           *.yaml  -> {key: command_id}
    │   └── commands.py            -> def <name>() -> None
    ├── spawn_actions/     *.py    -> def get_spawn_card() -> dict
    ├── shaders/
    │   ├── page_linings/  *.wgsl
    │   ├── washi_tape/    *.wgsl
    │   └── edge_strokes/  *.wgsl
    └── config.yaml

Contract highlights
-------------------

* Every user file is loaded inside a ``try / except`` guard — failures
  are logged (via :mod:`logging`) but never propagate, so the base
  editor keeps working even if half the user files are broken.
* A missing ``~/.slappyengine/ui/`` tree silently produces an empty
  bundle; :meth:`UserOverrideLoader.ensure_scaffolded` is called from
  the editor shell before the first load to populate the tree with
  ``README.md`` files and a few disabled examples.
* Config toggles let users disable any category without deleting
  files. Toggles that are absent default to ``True``.

Design provenance
-----------------

* Sprint plan ``docs/sprint_plan_2026_06_03.md`` §12 — "user override
  folder layer" (this file).
* Full guide: ``docs/user_customization_2026_06_07.md``.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Watcher constants
# ---------------------------------------------------------------------------


#: Debounce window (in seconds) applied to raw filesystem events before the
#: user's callback fires. Events landing within this window are coalesced
#: into a single callback per unique ``(kind, path)`` tuple.
_WATCH_DEBOUNCE_SECONDS: float = 0.100


#: Set once we've logged the "watchdog missing" warning so we don't spam
#: the log every time ``watch_dir`` is called.
_WATCHDOG_WARNED: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Directory names inside ``~/.slappyengine/ui/`` — the constant is the
#: single source of truth for both scaffolding and discovery.
_UI_SUBDIRS: tuple[str, ...] = (
    "panels",
    "hotkeys",
    "spawn_actions",
    "shaders",
    "shaders/page_linings",
    "shaders/washi_tape",
    "shaders/edge_strokes",
    "examples",
)


#: Map of parent-directory name (relative to ``shaders/``) → registry
#: kind used by the theme registries.
_SHADER_KINDS: dict[str, str] = {
    "page_linings":  "page_linings",
    "washi_tape":    "washi_tape",
    "edge_strokes":  "edge_strokes",
}


#: Default values for the master ``config.yaml``. Any key that is absent
#: from the on-disk file falls back to the entry here so partial config
#: files remain usable.
_CONFIG_DEFAULTS: dict[str, bool] = {
    "enable_user_panels":        True,
    "enable_user_hotkeys":       True,
    "enable_user_spawn_actions": True,
    "enable_user_shaders":       True,
    "watch_reload":              False,
}


# ---------------------------------------------------------------------------
# UserOverrideBundle
# ---------------------------------------------------------------------------


@dataclass
class UserOverrideBundle:
    """Result of :meth:`UserOverrideLoader.load_all`.

    Attributes
    ----------
    panels:
        Instantiated panel objects returned by user ``get_panel()``
        factories.  Order matches disk order (``sorted``).
    hotkey_bindings:
        Mapping of canonical key string (e.g. ``"ctrl+shift+m"``) → editor
        command id (e.g. ``"user.my_command"``). Merged into
        :attr:`NotebookHotkeys.BINDINGS` by the editor shell.
    hotkey_commands:
        Mapping of command id → zero-arg callable. Populated from
        ``commands.py`` files sitting alongside the hotkey YAMLs.
    spawn_actions:
        Extra spawn-card specs (dicts with ``card_id`` / ``label`` /
        ``portrait_svg`` / ``on_summon``). Appended to the built-in card
        list.
    shaders:
        ``{shader_id: wgsl_source}`` — the shader id is the filename
        with ``.wgsl`` stripped.
    shader_kinds:
        ``{shader_id: kind}`` — mirrors :attr:`shaders` and lets the
        editor route each shader to the correct theme registry.
    config:
        The resolved config dict (defaults merged with on-disk values).
    errors:
        Log of per-file failures — ``(path, message)`` — kept so tests
        can assert graceful degradation and the editor can surface a
        toast on first launch.
    """

    panels:          list[Any]             = field(default_factory=list)
    hotkey_bindings: dict[str, str]        = field(default_factory=dict)
    hotkey_commands: dict[str, Callable[[], None]] = field(default_factory=dict)
    spawn_actions:   list[dict[str, Any]]  = field(default_factory=list)
    shaders:         dict[str, str]        = field(default_factory=dict)
    shader_kinds:    dict[str, str]        = field(default_factory=dict)
    config:          dict[str, Any]        = field(default_factory=dict)
    errors:          list[tuple[str, str]] = field(default_factory=list)

    # -- Convenience accessors ---------------------------------------

    def has_errors(self) -> bool:
        return bool(self.errors)

    def summary(self) -> dict[str, int]:
        """Return a short ``{"panels": N, ...}`` dict for status bars."""
        return {
            "panels":        len(self.panels),
            "hotkeys":       len(self.hotkey_bindings),
            "spawn_actions": len(self.spawn_actions),
            "shaders":       len(self.shaders),
            "errors":        len(self.errors),
        }


# ---------------------------------------------------------------------------
# ReloadedBundle
# ---------------------------------------------------------------------------


@dataclass
class ReloadedBundle:
    """A :class:`UserOverrideBundle` returned by :meth:`UserOverrideLoader.reload_all`.

    Mirrors the shape of :class:`UserOverrideBundle` (categories on
    ``bundle`` so existing consumers keep working) and also carries a
    ``previous_bundle`` handle so watchers can diff panels / hotkeys /
    shaders between reloads.

    Attributes
    ----------
    bundle:
        The freshly loaded :class:`UserOverrideBundle`.
    previous_bundle:
        The bundle returned by the *previous* :meth:`reload_all` call
        (``None`` on the very first reload).
    reloaded_at:
        Wall-clock timestamp (from :func:`time.time`) at which the reload
        finished — handy for logging + tests.
    """

    bundle:          UserOverrideBundle
    previous_bundle: Optional["ReloadedBundle"] = None
    reloaded_at:     float = field(default_factory=time.time)

    # -- Convenience passthroughs — mirror :class:`UserOverrideBundle` --

    @property
    def panels(self) -> list[Any]:
        return self.bundle.panels

    @property
    def hotkey_bindings(self) -> dict[str, str]:
        return self.bundle.hotkey_bindings

    @property
    def hotkey_commands(self) -> dict[str, Callable[[], None]]:
        return self.bundle.hotkey_commands

    @property
    def spawn_actions(self) -> list[dict[str, Any]]:
        return self.bundle.spawn_actions

    @property
    def shaders(self) -> dict[str, str]:
        return self.bundle.shaders

    @property
    def shader_kinds(self) -> dict[str, str]:
        return self.bundle.shader_kinds

    @property
    def config(self) -> dict[str, Any]:
        return self.bundle.config

    @property
    def errors(self) -> list[tuple[str, str]]:
        return self.bundle.errors

    def summary(self) -> dict[str, int]:
        return self.bundle.summary()


# ---------------------------------------------------------------------------
# Watcher handles
# ---------------------------------------------------------------------------


class WatcherHandle:
    """Handle returned by :meth:`UserOverrideLoader.watch_dir`.

    Owns the background thread + underlying :mod:`watchdog` observer.
    Call :meth:`stop` to join the thread cleanly. The handle also
    doubles as a context manager so ``with loader.watch_dir(cb):`` works.
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
        """Cancel the watcher; block until the thread has joined."""
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
                    "WatcherHandle: observer.stop() raised: %s", exc,
                )
            try:
                obs.join(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "WatcherHandle: observer.join() raised: %s", exc,
                )
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)

    def is_running(self) -> bool:
        """Return ``True`` when the watcher is still active."""
        if self._stopped:
            return False
        t = self._thread
        if t is None:
            return False
        return t.is_alive()

    # -- Context-manager sugar -----------------------------------------

    def __enter__(self) -> "WatcherHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401,ANN001
        self.stop()


class NullWatcherHandle(WatcherHandle):
    """Placeholder returned when :mod:`watchdog` is not installed.

    Provides the same API as :class:`WatcherHandle` but performs no work
    and reports ``is_running() -> False``. :meth:`stop` is a no-op.
    """

    def __init__(self) -> None:
        super().__init__(observer=None, stop_event=threading.Event(), thread=None)
        # Nothing to run — behave as already-stopped.
        self._stopped = True

    def stop(self, timeout: float = 5.0) -> None:  # noqa: D401,ARG002
        """No-op."""
        return

    def is_running(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# UserOverrideLoader
# ---------------------------------------------------------------------------


class UserOverrideLoader:
    """Discovers + loads user overrides from ``~/.slappyengine/ui/``.

    The loader is intentionally defensive: every file is imported inside
    a ``try / except`` guard, and unexpected exceptions are logged to
    :mod:`logging` at ``WARNING`` and appended to
    :attr:`UserOverrideBundle.errors`. The base editor stays functional
    even when user files are broken.

    Parameters
    ----------
    root:
        Override the discovery root — the default is
        ``Path.home() / ".slappyengine" / "ui"``.  Tests pass a tmp path.
    """

    ROOT: Path = Path.home() / ".slappyengine" / "ui"

    def __init__(self, root: Path | None = None) -> None:
        self._root: Path = Path(root) if root is not None else Path(self.ROOT)

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Scaffolding
    # ------------------------------------------------------------------

    def ensure_scaffolded(self) -> None:
        """Create the override directory tree and drop starter README files.

        Safe to call on every editor launch — existing files are left
        untouched. On the first launch (empty ``~/.slappyengine/ui``)
        this populates each folder with a short ``README.md`` that
        explains its contract and creates an ``examples/`` folder with
        one disabled sample per category.
        """
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log.warning("UserOverrideLoader: cannot create %s: %s", self._root, exc)
            return

        for sub in _UI_SUBDIRS:
            try:
                (self._root / sub).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _log.warning(
                    "UserOverrideLoader: cannot create %s: %s",
                    self._root / sub, exc,
                )

        # README files — one per top-level folder.
        for name, body in _README_BODIES.items():
            path = self._root / name
            if path.exists():
                continue
            try:
                path.write_text(body, encoding="utf-8")
            except OSError as exc:
                _log.warning(
                    "UserOverrideLoader: cannot write %s: %s", path, exc,
                )

        # Master config file — default toggles.
        cfg_path = self._root / "config.yaml"
        if not cfg_path.exists():
            try:
                cfg_path.write_text(_DEFAULT_CONFIG_YAML, encoding="utf-8")
            except OSError as exc:
                _log.warning("UserOverrideLoader: cannot write %s: %s", cfg_path, exc)

        # Example files (all disabled — filenames start with ``_``).
        examples_dir = self._root / "examples"
        for filename, body in _EXAMPLE_FILES.items():
            path = examples_dir / filename
            if path.exists():
                continue
            try:
                path.write_text(body, encoding="utf-8")
            except OSError as exc:
                _log.warning(
                    "UserOverrideLoader: cannot write %s: %s", path, exc,
                )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_user_panels(self) -> list[Path]:
        """Return sorted ``*.py`` files in ``panels/``."""
        return self._list_python(self._root / "panels")

    def list_user_hotkeys(self) -> list[Path]:
        """Return sorted ``*.yaml`` / ``*.yml`` files in ``hotkeys/``."""
        d = self._root / "hotkeys"
        if not d.is_dir():
            return []
        out: list[Path] = []
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}:
                out.append(p)
        return out

    def list_user_spawn_actions(self) -> list[Path]:
        """Return sorted ``*.py`` files in ``spawn_actions/``."""
        return self._list_python(self._root / "spawn_actions")

    def list_user_shaders(self) -> list[tuple[str, Path]]:
        """Return ``(kind, path)`` for every ``*.wgsl`` found.

        The *kind* is derived from the parent directory name — one of
        ``"page_linings"`` / ``"washi_tape"`` / ``"edge_strokes"``.
        Shaders sitting directly in ``shaders/`` (no kind subdir) are
        skipped.
        """
        base = self._root / "shaders"
        if not base.is_dir():
            return []
        out: list[tuple[str, Path]] = []
        for kind_dir, kind in _SHADER_KINDS.items():
            sub = base / kind_dir
            if not sub.is_dir():
                continue
            for p in sorted(sub.iterdir()):
                if p.is_file() and p.suffix.lower() == ".wgsl":
                    out.append((kind, p))
        return out

    # ------------------------------------------------------------------
    # Load-everything entry point
    # ------------------------------------------------------------------

    def load_all(self) -> UserOverrideBundle:
        """Discover + load every override under :attr:`root`.

        Returns an empty bundle when the root does not exist. Individual
        file failures are logged + recorded but never re-raised.
        """
        bundle = UserOverrideBundle()

        if not self._root.exists():
            return bundle

        # Config first — some categories can be disabled globally.
        bundle.config = self._load_config()

        if bundle.config.get("enable_user_panels", True):
            self._load_panels(bundle)

        if bundle.config.get("enable_user_hotkeys", True):
            self._load_hotkeys(bundle)

        if bundle.config.get("enable_user_spawn_actions", True):
            self._load_spawn_actions(bundle)

        if bundle.config.get("enable_user_shaders", True):
            self._load_shaders(bundle)

        return bundle

    # ------------------------------------------------------------------
    # Reload + watch
    # ------------------------------------------------------------------

    def reload_all(
        self,
        previous: "ReloadedBundle | None" = None,
    ) -> "ReloadedBundle":
        """Atomically reload every category — returns a fresh bundle.

        The reload is built up on a *new* :class:`UserOverrideBundle`
        instance which only replaces the caller's reference once the
        load has finished. Downstream consumers therefore never observe
        a half-populated bundle.

        Parameters
        ----------
        previous:
            Optional handle to the previously returned
            :class:`ReloadedBundle`; retained on the new object so
            callers can diff panels / shaders between reloads.
        """
        fresh = self.load_all()
        return ReloadedBundle(bundle=fresh, previous_bundle=previous)

    def watch_dir(
        self,
        callback: Callable[[str, Path], None],
        *,
        debounce: float = _WATCH_DEBOUNCE_SECONDS,
    ) -> "WatcherHandle":
        """Start a background watcher on the override directory.

        Parameters
        ----------
        callback:
            Fired with ``(event_kind, file_path)`` per debounced change.
            ``event_kind`` is one of ``"created"``, ``"modified"``,
            ``"deleted"``. Callbacks run on a background thread — keep
            them short + thread-safe.
        debounce:
            Coalesce raw filesystem events within this many seconds into
            a single callback. Defaults to
            :data:`_WATCH_DEBOUNCE_SECONDS` (100 ms).

        Returns
        -------
        WatcherHandle
            Call :meth:`WatcherHandle.stop` to cancel the watcher. If
            :mod:`watchdog` is not installed a :class:`NullWatcherHandle`
            is returned and a one-time warning is logged.
        """
        global _WATCHDOG_WARNED

        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
            from watchdog.observers import Observer  # type: ignore[import-not-found]
        except ImportError:
            if not _WATCHDOG_WARNED:
                _log.warning(
                    "UserOverrideLoader.watch_dir: watchdog not installed — "
                    "live reload disabled",
                )
                _WATCHDOG_WARNED = True
            return NullWatcherHandle()

        # Ensure the target directory exists — watchdog raises otherwise.
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _log.warning(
                "UserOverrideLoader.watch_dir: cannot create %s: %s",
                self._root, exc,
            )
            return NullWatcherHandle()

        stop_event = threading.Event()
        # Pending events keyed by ``(kind, path)`` → last-seen wall time.
        pending: dict[tuple[str, str], float] = {}
        pending_lock = threading.Lock()

        def _record(kind: str, path_str: str) -> None:
            # Filter: skip files whose basename starts with '.' or '_'.
            name = Path(path_str).name
            if name.startswith(".") or name.startswith("_"):
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
                # Model a move as delete(src) + create(dest).
                src = getattr(event, "src_path", None)
                dst = getattr(event, "dest_path", None)
                if src:
                    _record("deleted", str(src))
                if dst:
                    _record("created", str(dst))

        observer = Observer()
        try:
            observer.schedule(_Handler(), str(self._root), recursive=True)
            observer.start()
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "UserOverrideLoader.watch_dir: observer.start() raised: %s",
                exc,
            )
            return NullWatcherHandle()

        # Debounce pump — polls the pending dict, fires callbacks once
        # `debounce` seconds have elapsed since the last event for a
        # given key.
        poll_interval = max(0.01, debounce / 4.0)

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
                    try:
                        callback(kind, Path(path_str))
                    except Exception as exc:  # noqa: BLE001
                        _log.warning(
                            "UserOverrideLoader.watch_dir: callback "
                            "raised on (%s, %s): %s",
                            kind, path_str, exc,
                        )
                stop_event.wait(poll_interval)

        thread = threading.Thread(
            target=_pump,
            name="UserOverrideLoader.watch_dir",
            daemon=True,
        )
        thread.start()
        return WatcherHandle(observer=observer, stop_event=stop_event, thread=thread)

    def autoreload(
        self,
        on_reload: Callable[["ReloadedBundle"], None],
        *,
        debounce: float = _WATCH_DEBOUNCE_SECONDS,
    ) -> "WatcherHandle":
        """Wire watch + debounce + :meth:`reload_all` into one pipeline.

        Every debounced filesystem change triggers a fresh
        :meth:`reload_all` and the resulting :class:`ReloadedBundle` is
        handed to ``on_reload``. The previous bundle is threaded through
        so ``on_reload`` can diff panels / hotkeys / shaders.

        Returns
        -------
        WatcherHandle
            Call :meth:`WatcherHandle.stop` to tear the pipeline down.
        """
        state: dict[str, ReloadedBundle | None] = {"previous": None}
        state_lock = threading.Lock()

        def _wrapped_callback(_kind: str, _path: Path) -> None:
            # Serialise reloads so on_reload always observes a monotonic
            # chain of previous_bundle links.
            with state_lock:
                previous = state["previous"]
                try:
                    reloaded = self.reload_all(previous=previous)
                except Exception as exc:  # noqa: BLE001
                    _log.warning(
                        "UserOverrideLoader.autoreload: reload_all() "
                        "raised: %s", exc,
                    )
                    return
                state["previous"] = reloaded
            try:
                on_reload(reloaded)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "UserOverrideLoader.autoreload: on_reload() raised: %s",
                    exc,
                )

        return self.watch_dir(_wrapped_callback, debounce=debounce)

    # ------------------------------------------------------------------
    # Internal — config
    # ------------------------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        cfg = dict(_CONFIG_DEFAULTS)
        path = self._root / "config.yaml"
        if not path.is_file():
            return cfg
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            _log.warning(
                "UserOverrideLoader: PyYAML not installed — using config defaults"
            )
            return cfg
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, Exception) as exc:  # noqa: BLE001
            _log.warning("UserOverrideLoader: cannot parse %s: %s", path, exc)
            return cfg
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str):
                    cfg[k] = v
        return cfg

    # ------------------------------------------------------------------
    # Internal — panels
    # ------------------------------------------------------------------

    def _load_panels(self, bundle: UserOverrideBundle) -> None:
        for path in self.list_user_panels():
            module = self._import_file(path, module_prefix="slappy_user_panel")
            if module is None:
                bundle.errors.append((str(path), "import failed"))
                continue
            factory = getattr(module, "get_panel", None)
            if not callable(factory):
                msg = "missing get_panel() factory"
                _log.warning("UserOverrideLoader: %s — %s", path, msg)
                bundle.errors.append((str(path), msg))
                continue
            try:
                panel = factory()
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "UserOverrideLoader: get_panel() raised in %s: %s",
                    path, exc,
                )
                bundle.errors.append((str(path), f"get_panel() raised: {exc}"))
                continue
            if panel is None:
                bundle.errors.append((str(path), "get_panel() returned None"))
                continue
            bundle.panels.append(panel)

    # ------------------------------------------------------------------
    # Internal — hotkeys
    # ------------------------------------------------------------------

    def _load_hotkeys(self, bundle: UserOverrideBundle) -> None:
        # First pass — load YAML files. Later duplicate keys override.
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            for path in self.list_user_hotkeys():
                bundle.errors.append((str(path), "PyYAML not installed"))
            return

        for path in self.list_user_hotkeys():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except (OSError, Exception) as exc:  # noqa: BLE001
                _log.warning("UserOverrideLoader: cannot parse %s: %s", path, exc)
                bundle.errors.append((str(path), f"parse error: {exc}"))
                continue
            if not isinstance(data, dict):
                bundle.errors.append((str(path), "root is not a mapping"))
                continue
            for key, cmd in data.items():
                if not isinstance(key, str) or not isinstance(cmd, str):
                    continue
                bundle.hotkey_bindings[key.strip().lower()] = cmd

        # Second pass — pull ``commands.py`` from the hotkeys/ folder so
        # ``user.foo`` command ids can dispatch to callables.
        cmd_file = self._root / "hotkeys" / "commands.py"
        if cmd_file.is_file():
            module = self._import_file(
                cmd_file, module_prefix="slappy_user_hotkey_commands",
            )
            if module is None:
                bundle.errors.append((str(cmd_file), "import failed"))
                return
            for cmd_id in bundle.hotkey_bindings.values():
                if not cmd_id.startswith("user."):
                    continue
                name = cmd_id[len("user."):]
                fn = getattr(module, name, None)
                if callable(fn):
                    bundle.hotkey_commands[cmd_id] = fn

    # ------------------------------------------------------------------
    # Internal — spawn actions
    # ------------------------------------------------------------------

    def _load_spawn_actions(self, bundle: UserOverrideBundle) -> None:
        for path in self.list_user_spawn_actions():
            module = self._import_file(
                path, module_prefix="slappy_user_spawn",
            )
            if module is None:
                bundle.errors.append((str(path), "import failed"))
                continue
            factory = getattr(module, "get_spawn_card", None)
            if not callable(factory):
                msg = "missing get_spawn_card() factory"
                _log.warning("UserOverrideLoader: %s — %s", path, msg)
                bundle.errors.append((str(path), msg))
                continue
            try:
                card = factory()
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "UserOverrideLoader: get_spawn_card() raised in %s: %s",
                    path, exc,
                )
                bundle.errors.append(
                    (str(path), f"get_spawn_card() raised: {exc}")
                )
                continue
            if not isinstance(card, dict):
                bundle.errors.append(
                    (str(path), "get_spawn_card() must return a dict")
                )
                continue
            if not card.get("card_id"):
                bundle.errors.append(
                    (str(path), "spawn card missing card_id")
                )
                continue
            bundle.spawn_actions.append(card)

    # ------------------------------------------------------------------
    # Internal — shaders
    # ------------------------------------------------------------------

    def _load_shaders(self, bundle: UserOverrideBundle) -> None:
        for kind, path in self.list_user_shaders():
            try:
                src = path.read_text(encoding="utf-8")
            except OSError as exc:
                _log.warning(
                    "UserOverrideLoader: cannot read %s: %s", path, exc,
                )
                bundle.errors.append((str(path), f"read failed: {exc}"))
                continue
            shader_id = path.stem
            bundle.shaders[shader_id] = src
            bundle.shader_kinds[shader_id] = kind

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_python(directory: Path) -> list[Path]:
        """List ``*.py`` files in *directory* (skipping ``__pycache__``)."""
        if not directory.is_dir():
            return []
        out: list[Path] = []
        for p in sorted(directory.iterdir()):
            if (
                p.is_file()
                and p.suffix.lower() == ".py"
                and not p.name.startswith("_")
                and p.name != "commands.py"
            ):
                out.append(p)
        return out

    @staticmethod
    def _import_file(path: Path, *, module_prefix: str) -> Any | None:
        """Import a standalone Python file — returns ``None`` on any error.

        The module name is derived from ``module_prefix`` + the file's
        absolute path hash so multiple user files with the same basename
        never collide in :data:`sys.modules`.
        """
        try:
            mod_name = f"{module_prefix}_{abs(hash(str(path))):x}"
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                _log.warning(
                    "UserOverrideLoader: no import spec for %s", path,
                )
                return None
            module = importlib.util.module_from_spec(spec)
            # Register before exec so recursive imports work.
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "UserOverrideLoader: import of %s raised: %s", path, exc,
            )
            return None


# ---------------------------------------------------------------------------
# Scaffolding content — READMEs + config + examples
# ---------------------------------------------------------------------------


_README_BODIES: dict[str, str] = {
    "README.md": (
        "# SlapPyEngine — User UI Overrides\n\n"
        "Drop files under the subfolders here to extend the editor:\n\n"
        "* `panels/`        - custom editor panels (`.py`)\n"
        "* `hotkeys/`       - extra keybindings (`.yaml` + optional `commands.py`)\n"
        "* `spawn_actions/` - extra spawn cards (`.py`)\n"
        "* `shaders/`       - user WGSL for page linings / washi tape / edge strokes\n"
        "* `config.yaml`    - master toggles\n\n"
        "See `docs/user_customization_2026_06_07.md` in the SlapPyEngine repo\n"
        "for the full guide (5 worked examples).\n"
    ),
    "panels/README.md": (
        "# User panels\n\n"
        "Each `.py` file must define::\n\n"
        "    def get_panel():\n"
        "        return MyPanel()   # object with `build(parent_tag)` method\n\n"
        "The editor calls `EditorShell.register_panel(panel)` for each\n"
        "returned object. A View > User submenu entry is auto-generated so\n"
        "the panel can be toggled at runtime.\n\n"
        "Files whose names start with `_` are ignored — use that to disable\n"
        "a panel without deleting it.\n"
    ),
    "hotkeys/README.md": (
        "# User hotkeys\n\n"
        "Drop YAML files here mapping keys to command ids::\n\n"
        "    # my_hotkeys.yaml\n"
        "    ctrl+shift+m: user.my_command\n"
        "    ctrl+alt+p:   editor.profiler_toggle\n\n"
        "Commands prefixed `user.` are resolved from a sibling\n"
        "`commands.py` file — define `def my_command() -> None:` there.\n\n"
        "User entries win when a key collides with a built-in binding.\n"
    ),
    "spawn_actions/README.md": (
        "# User spawn cards\n\n"
        "Each `.py` file must define::\n\n"
        "    def get_spawn_card() -> dict:\n"
        "        return {\n"
        '            "card_id":      \"user.my_body\",\n'
        '            "label":        \"My Body\",\n'
        '            "portrait_svg": \"<svg .../>\",\n'
        '            "on_summon":    lambda world: ...,\n'
        "        }\n\n"
        "The card is appended to the spawn menu deck.\n"
    ),
    "shaders/README.md": (
        "# User shaders\n\n"
        "Drop `.wgsl` files under one of the subfolders:\n\n"
        "* `page_linings/` - page-lining fragment shaders\n"
        "* `washi_tape/`   - washi-tape swatch shaders\n"
        "* `edge_strokes/` - hand-drawn border-stroke shaders\n\n"
        "The filename (minus `.wgsl`) becomes the shader id — the id must\n"
        "be unique per kind. Existing built-in ids are not overridden\n"
        "unless the user shader shares their id.\n"
    ),
    "examples/README.md": (
        "# Examples\n\n"
        "Copy any file here into the corresponding sibling folder to enable\n"
        "it. Every example ships **disabled** (filenames start with `_`)\n"
        "so a fresh install boots with zero user overrides.\n"
    ),
}


_DEFAULT_CONFIG_YAML: str = (
    "# SlapPyEngine user override toggles\n"
    "enable_user_panels:        true\n"
    "enable_user_hotkeys:       true\n"
    "enable_user_spawn_actions: true\n"
    "enable_user_shaders:       true\n"
    "# When true, the editor watches this folder + reloads panels on change.\n"
    "watch_reload:              false\n"
)


_EXAMPLE_FILES: dict[str, str] = {
    "_example_panel.py": (
        '"""Example user panel — copy to ../panels/ and remove leading `_`."""\n'
        "class ExamplePanel:\n"
        '    TITLE = "Example User Panel"\n\n'
        "    def build(self, parent_tag):\n"
        "        try:\n"
        "            import dearpygui.dearpygui as dpg\n"
        "            with dpg.child_window(parent=parent_tag):\n"
        '                dpg.add_text("Hello from a user panel!")\n'
        "        except Exception:\n"
        "            pass\n\n\n"
        "def get_panel():\n"
        "    return ExamplePanel()\n"
    ),
    "_example_hotkeys.yaml": (
        "# Copy to ../hotkeys/ to enable\n"
        "ctrl+shift+m: user.my_command\n"
    ),
    "_example_shader.wgsl": (
        "// Copy to ../shaders/page_linings/ (or washi_tape/, edge_strokes/) to enable.\n"
        "@fragment\n"
        "fn fs_main() -> @location(0) vec4<f32> {\n"
        "    return vec4<f32>(1.0, 0.5, 0.75, 1.0);\n"
        "}\n"
    ),
}


__all__ = [
    "NullWatcherHandle",
    "ReloadedBundle",
    "UserOverrideBundle",
    "UserOverrideLoader",
    "WatcherHandle",
]
