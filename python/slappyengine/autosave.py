"""``AutosaveManager`` — periodic crash-safe snapshotting for the editor.

Every editor session accumulates unsaved user work (scene edits, prefab
tweaks, notebook page dirt) between explicit File > Save clicks. If the
process dies — GPU driver crash, out-of-memory, dear-pygui viewport hang,
or a plain ``KeyboardInterrupt`` at the wrong moment — that work is
gone. This module bolts a background timer to the editor that snapshots
the current state every N seconds and offers to restore it on the next
boot.

Architecture
------------
Three orthogonal pieces live in this module:

* :class:`AutosaveState` — the plain-data config bag (interval, dir,
  cap, ``enabled`` toggle). Kept dataclass-only so the editor's Options
  panel can serialise it straight into user_overrides.yaml.
* :class:`AutosaveManager` — the runtime brains. Owns the
  :class:`threading.Timer`, the on-disk snapshot ring buffer, and a
  :class:`threading.Lock` guarding both.
* :class:`RecoveryPrompt` — a boot-time helper that inspects the
  snapshot dir and returns a :class:`RecoveryOffer` iff the newest
  snapshot is newer than the project's last-saved timestamp.

The manager is deliberately I/O-driven (writes YAML, prunes files) so
crash recovery works even after a hard-kill — the timer never has to
"flush" anything; each tick's write is atomic-rename.

Thread safety
-------------
Both :meth:`AutosaveManager._tick` and :meth:`AutosaveManager.force_save`
grab ``self._lock`` before invoking ``save_callback`` or touching the
snapshot list. Restart-with-new-interval is likewise lock-protected so a
timer tick can't fire mid-reconfigure. The lock is a plain
:class:`threading.Lock` — recursion isn't needed because the callback
runs *inside* the critical section but never re-enters the manager's
public API.

Snapshot format
---------------
Files are named ``YYYYMMDD_HHMMSS_<seq>.snap.yaml`` where ``<seq>`` is
a 4-digit monotonic counter (so ticks < 1 s apart don't collide). The
YAML payload has two top-level keys:

.. code-block:: yaml

    meta:
      saved_at: 2026-07-04T18:45:12Z
      project: my_scene
      engine_version: 0.7.0
    payload: <whatever save_callback returned>

The ``payload`` slot accepts a ``dict`` (dumped straight to YAML), a
``bytes`` blob (base64-encoded), or a ``str`` (dumped verbatim). Any
other type is coerced via ``repr``.

Design provenance: sprint Y6 (autosave + crash-recovery).
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from slappyengine._validation import (
    validate_bool,
    validate_callable,
    validate_non_empty_str,
    validate_path_like,
    validate_positive_float,
    validate_positive_int,
)


_LOG = logging.getLogger(__name__)


__all__ = [
    "AutosaveManager",
    "AutosaveReadError",
    "AutosaveState",
    "RecoveryChoice",
    "RecoveryOffer",
    "RecoveryPrompt",
    "default_snapshot_dir",
    "snapshot_timestamp",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AutosaveReadError(Exception):
    """Raised when a ``.snap.yaml`` file cannot be decoded.

    Carries the offending line number on the exception when a YAML
    parse error pinpoints one — the editor's "restore" toast surfaces
    that line so the user knows exactly where the file broke.

    Attributes
    ----------
    path:
        The snapshot file that failed to parse.
    line:
        1-indexed line number of the parse failure, or ``None`` when
        the underlying loader could not pinpoint one.
    """

    def __init__(
        self,
        message: str,
        *,
        path: Optional[Path] = None,
        line: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.line = line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SNAPSHOT_SUFFIX = ".snap.yaml"


def default_snapshot_dir(project_name: str) -> Path:
    """Return ``~/.slappyengine/autosave/<project_name>/`` for *project_name*.

    The directory is *not* created here — :meth:`AutosaveManager._tick`
    creates it lazily via ``mkdir(parents=True, exist_ok=True)`` so a
    read-only home dir doesn't crash the constructor.

    Raises
    ------
    TypeError
        If *project_name* is not a ``str``.
    """
    if not isinstance(project_name, str):
        raise TypeError(
            f"default_snapshot_dir: project_name must be a str; "
            f"got {type(project_name).__name__}"
        )
    safe = project_name.strip() or "unnamed"
    # Replace path separators so a slash in project_name can't escape.
    safe = safe.replace("/", "_").replace("\\", "_")
    return Path.home() / ".slappyengine" / "autosave" / safe


def snapshot_timestamp(when: Optional[float] = None) -> str:
    """Format *when* (or ``time.time()``) as ``YYYYMMDD_HHMMSS`` UTC."""
    ts = when if when is not None else time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y%m%d_%H%M%S",
    )


def _iso_utc(when: Optional[float] = None) -> str:
    """Format *when* as ISO 8601 UTC with a ``Z`` suffix."""
    ts = when if when is not None else time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


def _yaml_dumps(payload: dict) -> str:
    """Serialise *payload* to YAML text (falls back to JSON when pyyaml absent)."""
    try:
        import yaml  # type: ignore[import-not-found]
        return yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except Exception:
        # JSON is a strict subset of YAML 1.2 so a real YAML reader can
        # still ingest the fallback file on the recovery path.
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)


def _yaml_loads(text: str) -> Any:
    """Deserialise *text* — YAML if pyyaml is available, else JSON."""
    try:
        import yaml  # type: ignore[import-not-found]
        return yaml.safe_load(text)
    except ImportError:
        try:
            return json.loads(text)
        except Exception:
            return None
    except Exception:
        return None


def _yaml_loads_verbose(text: str) -> tuple[Any, Optional[int]]:
    """Like :func:`_yaml_loads` but returns ``(doc, line)``.

    ``line`` is the 1-indexed parse-error line when the underlying
    loader raises with a locatable mark, or ``None`` when the loader
    succeeds or can't pinpoint one. The document itself is ``None``
    only when parsing genuinely failed (empty YAML documents decode to
    ``None`` too — those callers must inspect the return value).
    """
    try:
        import yaml  # type: ignore[import-not-found]
        try:
            return yaml.safe_load(text), None
        except yaml.YAMLError as exc:
            line: Optional[int] = None
            mark = getattr(exc, "problem_mark", None)
            if mark is not None:
                line = int(getattr(mark, "line", 0)) + 1
            return None, line
    except ImportError:
        try:
            return json.loads(text), None
        except json.JSONDecodeError as exc:
            return None, int(getattr(exc, "lineno", 0)) or None
        except Exception:
            return None, None


def _peek_line(text: str, line: Optional[int]) -> str:
    """Return the (stripped) contents of *text*'s 1-indexed *line*, or ''."""
    if not line or line <= 0:
        return ""
    lines = text.splitlines()
    if line > len(lines):
        return ""
    return lines[line - 1].strip()


def _encode_payload(payload: Any) -> Any:
    """Coerce arbitrary *payload* into a YAML-safe representation.

    * ``None`` / ``bool`` / ``int`` / ``float`` / ``str`` → pass-through.
    * ``dict`` / ``list`` / ``tuple`` → recursively encoded (tuples → lists).
    * ``bytes`` / ``bytearray`` → base64 text wrapped in a marker dict.
    * anything else → ``repr(payload)`` as a str fallback.
    """
    if payload is None or isinstance(payload, (bool, int, float, str)):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        return {
            "__slappyengine_autosave_bytes__": True,
            "b64": base64.b64encode(bytes(payload)).decode("ascii"),
        }
    if isinstance(payload, dict):
        return {str(k): _encode_payload(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_encode_payload(v) for v in payload]
    return repr(payload)


def _decode_payload(payload: Any) -> Any:
    """Inverse of :func:`_encode_payload` — collapses the bytes marker back."""
    if isinstance(payload, dict):
        if payload.get("__slappyengine_autosave_bytes__") is True and "b64" in payload:
            try:
                return base64.b64decode(payload["b64"])
            except Exception:
                return b""
        return {k: _decode_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_decode_payload(v) for v in payload]
    return payload


def _parse_iso_utc(stamp: Any) -> Optional[float]:
    """Parse a ``YYYY-MM-DDTHH:MM:SSZ`` string into a POSIX timestamp."""
    if not isinstance(stamp, str) or not stamp:
        return None
    text = stamp
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _snapshot_mtime(path: Path) -> float:
    """Return *path*'s mtime, falling back to 0.0 on any OSError."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# AutosaveState — plain-data config bag
# ---------------------------------------------------------------------------


@dataclass
class AutosaveState:
    """Persistent config for the autosave subsystem.

    Attributes
    ----------
    enabled:
        Master toggle. When ``False`` the manager still constructs
        cleanly but :meth:`AutosaveManager.start` becomes a no-op.
    interval_seconds:
        Delay between ticks. Kept as ``float`` under the hood so tests
        can hand in ``0.02`` — the dataclass default is a plain int for
        easy YAML round-tripping.
    snapshot_dir:
        Root directory for the ring buffer. Defaults to
        ``~/.slappyengine/autosave/<project_name>/`` via
        :func:`default_snapshot_dir` (populated at manager construction
        when the caller doesn't override it).
    max_snapshots:
        Cap on the ring buffer — the oldest ``.snap.yaml`` files are
        pruned once this many exist.
    last_saved_at:
        POSIX timestamp of the most recent successful tick. ``None``
        before the first tick fires. The manager updates this in-place
        so the editor's status bar can surface "last autosave 12 s ago".
    """

    enabled: bool = True
    interval_seconds: float = 60.0
    snapshot_dir: Path = field(default_factory=lambda: Path.home() / ".slappyengine" / "autosave")
    max_snapshots: int = 20
    last_saved_at: Optional[float] = None

    def __post_init__(self) -> None:
        # Coerce path first so validation error messages reference a
        # proper Path.
        if not isinstance(self.snapshot_dir, Path):
            self.snapshot_dir = Path(self.snapshot_dir)
        validate_bool("enabled", "AutosaveState", self.enabled)
        # Accept ints and floats; validate_positive_float rejects bools.
        self.interval_seconds = float(
            validate_positive_float(
                "interval_seconds", "AutosaveState", self.interval_seconds,
            )
        )
        self.max_snapshots = validate_positive_int(
            "max_snapshots", "AutosaveState", self.max_snapshots,
        )
        if self.last_saved_at is not None and not isinstance(
            self.last_saved_at, (int, float),
        ):
            raise TypeError(
                "AutosaveState: last_saved_at must be a real number or None; "
                f"got {type(self.last_saved_at).__name__}"
            )

    def to_dict(self) -> dict:
        """Return a YAML-safe dict representation."""
        return {
            "enabled": bool(self.enabled),
            "interval_seconds": float(self.interval_seconds),
            "snapshot_dir": str(self.snapshot_dir),
            "max_snapshots": int(self.max_snapshots),
            "last_saved_at": (
                None if self.last_saved_at is None else float(self.last_saved_at)
            ),
        }


# ---------------------------------------------------------------------------
# RecoveryOffer / RecoveryChoice / RecoveryPrompt
# ---------------------------------------------------------------------------


class RecoveryChoice(str, Enum):
    """User's answer to the "restore autosave?" boot prompt."""

    RESTORE = "restore"
    DISCARD = "discard"
    KEEP_BOTH = "keep_both"


@dataclass(frozen=True)
class RecoveryOffer:
    """One in-flight offer the recovery UI can present to the user.

    Attributes
    ----------
    snapshot_path:
        The ``.snap.yaml`` file that's newer than the project's own
        last-saved timestamp — the payload the user might want back.
    project_last_saved:
        POSIX timestamp of the project's last explicit File > Save. May
        be ``None`` if the project has never been saved.
    snapshot_saved:
        POSIX timestamp of the snapshot file (mtime).
    """

    snapshot_path: Path
    project_last_saved: Optional[float]
    snapshot_saved: float


class RecoveryPrompt:
    """Boot-time helper — offers to restore an autosave iff it's newer.

    Parameters
    ----------
    snapshot_dir:
        Where autosaves are stored. Matches
        :attr:`AutosaveState.snapshot_dir`.
    project_last_saved:
        ISO 8601 timestamp string OR POSIX float OR ``None`` describing
        the project's last explicit save. The prompt compares this
        against the newest snapshot's mtime and only surfaces an offer
        when the snapshot is *strictly* newer.
    """

    def __init__(
        self,
        snapshot_dir: Path | str,
        project_last_saved: Optional[float | str] = None,
    ) -> None:
        self._snapshot_dir = validate_path_like(
            "snapshot_dir", "RecoveryPrompt", snapshot_dir,
        )
        self._project_last_saved: Optional[float]
        if project_last_saved is None:
            self._project_last_saved = None
        elif isinstance(project_last_saved, (int, float)) and not isinstance(
            project_last_saved, bool,
        ):
            self._project_last_saved = float(project_last_saved)
        elif isinstance(project_last_saved, str):
            self._project_last_saved = _parse_iso_utc(project_last_saved)
        else:
            raise TypeError(
                "RecoveryPrompt: project_last_saved must be None, str, or "
                f"real number; got {type(project_last_saved).__name__}"
            )

    @property
    def snapshot_dir(self) -> Path:
        return self._snapshot_dir

    @property
    def project_last_saved(self) -> Optional[float]:
        return self._project_last_saved

    def check(self) -> Optional[RecoveryOffer]:
        """Return an offer iff the newest snapshot is newer than the project.

        Returns ``None`` when:

        * the snapshot dir doesn't exist,
        * no ``.snap.yaml`` files live there,
        * the newest snapshot is older-or-equal to
          ``project_last_saved``.
        """
        try:
            if not self._snapshot_dir.is_dir():
                return None
        except OSError:
            return None
        snapshots = sorted(
            (p for p in self._snapshot_dir.iterdir() if p.name.endswith(_SNAPSHOT_SUFFIX)),
            key=_snapshot_mtime,
            reverse=True,
        )
        if not snapshots:
            return None
        newest = snapshots[0]
        snap_mtime = _snapshot_mtime(newest)
        if snap_mtime == 0.0:
            return None
        if (
            self._project_last_saved is not None
            and snap_mtime <= self._project_last_saved
        ):
            return None
        return RecoveryOffer(
            snapshot_path=newest,
            project_last_saved=self._project_last_saved,
            snapshot_saved=snap_mtime,
        )


# ---------------------------------------------------------------------------
# AutosaveManager
# ---------------------------------------------------------------------------


class AutosaveManager:
    """Owns the background timer + snapshot ring buffer.

    Parameters
    ----------
    state:
        Persistent config. Mutated in-place on each successful tick to
        stamp ``last_saved_at``.
    project:
        Any object exposing ``.name`` (typically a
        :class:`slappyengine.project_registry.RegisteredProject`). Used
        to fill in the default snapshot dir when
        ``state.snapshot_dir`` still points at the module-level default.
    save_callback:
        Zero-arg callable that returns the payload to snapshot. May
        return a dict, str, bytes, or any other type — the payload is
        run through :func:`_encode_payload` before hitting YAML.

    Notes
    -----
    The timer is created lazily in :meth:`start` — the constructor does
    not touch threading state. This keeps unit tests and headless CI
    predictable: the manager only spawns a thread when the editor
    explicitly asks for one.
    """

    def __init__(
        self,
        state: AutosaveState,
        project: Any,
        save_callback: Callable[[], Any],
    ) -> None:
        if not isinstance(state, AutosaveState):
            raise TypeError(
                "AutosaveManager: state must be an AutosaveState; "
                f"got {type(state).__name__}"
            )
        if not hasattr(project, "name"):
            raise TypeError(
                "AutosaveManager: project must expose a .name attribute; "
                f"got {type(project).__name__}"
            )
        validate_callable("save_callback", "AutosaveManager", save_callback)
        project_name = getattr(project, "name")
        validate_non_empty_str("project.name", "AutosaveManager", project_name)

        self._state = state
        self._project = project
        self._save_callback = save_callback
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running: bool = False
        self._seq: int = 0

        # If the caller left snapshot_dir at the module default, refine
        # it under the project's name so multiple projects don't share a
        # ring buffer.
        if state.snapshot_dir == Path.home() / ".slappyengine" / "autosave":
            state.snapshot_dir = default_snapshot_dir(project_name)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def state(self) -> AutosaveState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def snapshot_dir(self) -> Path:
        return self._state.snapshot_dir

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Kick off the background timer.

        A no-op when :attr:`AutosaveState.enabled` is ``False`` or the
        manager is already running.
        """
        if not self._state.enabled:
            return
        with self._lock:
            if self._running:
                return
            self._running = True
            self._schedule_locked()

    def stop(self) -> None:
        """Cancel the timer cleanly. Safe to call from any thread."""
        with self._lock:
            self._running = False
            timer = self._timer
            self._timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass
            # Best-effort join so the caller can trust the thread is
            # gone before it tears down the editor. A tick fires quickly
            # so this is effectively instant in tests.
            try:
                timer.join(timeout=1.0)
            except Exception:
                pass

    def _schedule_locked(self) -> None:
        """Arm the next timer — caller MUST already hold ``self._lock``."""
        if not self._running:
            return
        timer = threading.Timer(self._state.interval_seconds, self._tick)
        timer.daemon = True
        self._timer = timer
        timer.start()

    # ------------------------------------------------------------------
    # Snapshot writes
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Timer callback — write a snapshot then re-arm."""
        try:
            self._write_snapshot()
        except Exception as exc:
            # Autosave failures MUST NOT bring the editor down. Swallow
            # every exception; a failed tick just means the ring buffer
            # doesn't grow this round. Log at warning level so a
            # persistently-failing autosave surfaces in the log tail.
            _LOG.warning(
                "AutosaveManager._tick: snapshot failed (%s: %s)",
                type(exc).__name__, exc,
            )
        with self._lock:
            self._schedule_locked()

    def force_save(self) -> Path:
        """Trigger an immediate snapshot outside the timer path.

        Returns the newly-written ``.snap.yaml`` file. Raises whatever
        the callback / filesystem raise so the caller can surface a
        toast — unlike :meth:`_tick`, ``force_save`` propagates errors.
        """
        return self._write_snapshot()

    def _write_snapshot(self) -> Path:
        """Serialise the callback's payload to a fresh ``.snap.yaml``.

        Runs under :attr:`_lock` so concurrent ticks + force_saves can't
        collide on ``_seq`` or the on-disk prune step.
        """
        with self._lock:
            self._seq = (self._seq + 1) % 10000
            seq = self._seq
            now = time.time()
            snap_dir = self._state.snapshot_dir
            try:
                snap_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _LOG.warning(
                    "AutosaveManager._write_snapshot: cannot mkdir %s "
                    "(%s: %s)",
                    snap_dir, type(exc).__name__, exc,
                )
                raise
            try:
                raw_payload = self._save_callback()
            except Exception as exc:
                # Wrap the callback failure so ``force_save`` callers
                # get a consistent RuntimeError instead of whatever the
                # callback raised (dear-pygui hosts can raise anything).
                raise RuntimeError(
                    f"AutosaveManager: save_callback raised {type(exc).__name__}: {exc}"
                ) from exc
            if raw_payload is None:
                # Silent-acceptance guard: a callback returning None
                # would produce an empty snapshot the recovery UI can't
                # do anything useful with. Refuse — the tick swallows
                # this and logs, force_save propagates.
                raise ValueError(
                    "AutosaveManager: save_callback returned None; "
                    "refusing to snapshot an empty payload"
                )
            filename = f"{snapshot_timestamp(now)}_{seq:04d}{_SNAPSHOT_SUFFIX}"
            path = snap_dir / filename
            document = {
                "meta": {
                    "saved_at": _iso_utc(now),
                    "project": getattr(self._project, "name", "unknown"),
                    "engine_version": self._engine_version(),
                },
                "payload": _encode_payload(raw_payload),
            }
            text = _yaml_dumps(document)
            # Atomic write via .tmp swap — a crash mid-write can't leave
            # a half-truncated snap file for the recovery prompt to
            # choke on.
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            self._state.last_saved_at = now
            self._prune_locked()
            return path

    # ------------------------------------------------------------------
    # Ring buffer maintenance
    # ------------------------------------------------------------------

    def _prune_locked(self) -> None:
        """Drop the oldest snapshots beyond ``max_snapshots``.

        Caller MUST hold ``self._lock``. Prune failures are swallowed —
        losing a stale file on a read-only volume is not worth crashing
        the timer for.
        """
        snapshots = self._collect_snapshots()
        if len(snapshots) <= self._state.max_snapshots:
            return
        # ``snapshots`` is newest-first; the tail past max_snapshots is
        # everyone we want to prune.
        for stale in snapshots[self._state.max_snapshots:]:
            try:
                stale.unlink()
            except OSError:
                pass

    def _collect_snapshots(self) -> list[Path]:
        """Return every ``.snap.yaml`` in ``snapshot_dir``, newest-first."""
        snap_dir = self._state.snapshot_dir
        try:
            if not snap_dir.is_dir():
                return []
        except OSError:
            return []
        try:
            candidates = [
                p for p in snap_dir.iterdir()
                if p.name.endswith(_SNAPSHOT_SUFFIX) and p.is_file()
            ]
        except OSError:
            return []
        candidates.sort(key=_snapshot_mtime, reverse=True)
        return candidates

    # ------------------------------------------------------------------
    # Queries + restore
    # ------------------------------------------------------------------

    def list_snapshots(self) -> list[Path]:
        """Return every snapshot for this project, newest first."""
        with self._lock:
            return self._collect_snapshots()

    def latest_snapshot(self) -> Optional[Path]:
        """Return the newest snapshot, or ``None`` if the ring is empty."""
        with self._lock:
            snapshots = self._collect_snapshots()
        return snapshots[0] if snapshots else None

    @classmethod
    def read_snapshot(cls, path: Path | str) -> dict:
        """Load *path* and return the decoded snapshot document.

        Public counterpart to the private ``_decode_payload`` helper —
        surfaces both ``meta`` and ``payload`` from a ``.snap.yaml``
        file so external tools (recovery UIs, migration scripts, unit
        tests) can inspect a snapshot without reaching into module
        internals.

        The returned dict always exposes:

        * ``"meta"``      — copied from the file (``{}`` if missing).
        * ``"payload"``   — decoded via the module's internal
          ``_decode_payload`` (base64 → bytes, etc.).

        Parameters
        ----------
        path:
            Filesystem path to a ``.snap.yaml`` snapshot.

        Returns
        -------
        dict
            ``{"meta": {...}, "payload": <decoded>}``.

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        AutosaveReadError
            If the file cannot be decoded as YAML/JSON, or if the top-
            level document is not a dict. The exception's :attr:`line`
            attribute pinpoints the parse failure when available.
        """
        snap_path = validate_path_like("path", "AutosaveManager.read_snapshot", path)
        if not snap_path.is_file():
            raise FileNotFoundError(
                f"AutosaveManager.read_snapshot: snapshot not found: {snap_path}"
            )
        try:
            text = snap_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AutosaveReadError(
                f"AutosaveManager.read_snapshot: cannot read {snap_path}: {exc}",
                path=snap_path,
            ) from exc
        document, parse_line = _yaml_loads_verbose(text)
        if document is None:
            raise AutosaveReadError(
                f"AutosaveManager.read_snapshot: {snap_path} failed to parse"
                + (f" at line {parse_line}" if parse_line is not None else "")
                + (f": '{_peek_line(text, parse_line)}'" if parse_line is not None else ""),
                path=snap_path,
                line=parse_line,
            )
        if not isinstance(document, dict):
            raise AutosaveReadError(
                f"AutosaveManager.read_snapshot: {snap_path} decoded to "
                f"{type(document).__name__}, expected dict",
                path=snap_path,
            )
        meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
        payload = _decode_payload(document.get("payload"))
        return {"meta": dict(meta), "payload": payload}

    def restore_snapshot(
        self,
        path: Path | str,
        restore_callback: Callable[[Any], None],
    ) -> Any:
        """Load *path* and hand its payload to *restore_callback*.

        Parameters
        ----------
        path:
            The snapshot file (typically :attr:`RecoveryOffer.snapshot_path`).
        restore_callback:
            One-arg callable that receives the decoded payload. Any
            exception from the callback propagates so the editor can
            show a toast.

        Returns
        -------
        The decoded payload (the same value passed to
        ``restore_callback``) so callers that want to inspect the
        snapshot can do so without re-reading the file.
        """
        snap_path = validate_path_like("path", "restore_snapshot", path)
        validate_callable(
            "restore_callback", "restore_snapshot", restore_callback,
        )
        if not snap_path.is_file():
            raise FileNotFoundError(
                f"restore_snapshot: snapshot not found: {snap_path}"
            )
        text = snap_path.read_text(encoding="utf-8")
        document = _yaml_loads(text)
        if not isinstance(document, dict):
            raise ValueError(
                f"restore_snapshot: snapshot payload is not a dict: {snap_path}"
            )
        payload = _decode_payload(document.get("payload"))
        restore_callback(payload)
        return payload

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _engine_version() -> str:
        """Return ``slappyengine.__version__`` with a graceful fallback."""
        try:
            import slappyengine as _sp
            v = getattr(_sp, "__version__", None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
        return "unknown"
