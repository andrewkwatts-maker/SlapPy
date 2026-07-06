"""Runtime diagnostics aggregator — subscribes to subsystem loggers.

MM1 (`1e584e4`) sprinkled ``_LOG = logging.getLogger(__name__)`` warnings
across 13 subsystem files (audio_3d, capture, exporter, physics3_bridge,
render/ssao|skybox|instanced, text, asset_import/*, etc.). Prior to this
module those warnings just spammed stderr and disappeared. The
:class:`DiagnosticsCollector` in this module attaches a
:class:`logging.Handler` to the ``slappyengine`` root logger, captures
records at ``min_level+``, keeps a rolling buffer, and exposes structured
:class:`DiagnosticEvent` objects for the HUD overlay and downstream
tooling.

The aggregator is *passive*: it does not modify any existing logging
call site. Subsystems keep using ``_LOG.warning(...)`` as before; the
collector subscribes on top.

Typical wiring::

    from slappyengine.diagnostics import get_global_collector
    collector = get_global_collector()
    collector.install()
    ...
    for evt in collector.events()[-5:]:
        print(evt.level, evt.subsystem, evt.message)

The HUD widget in :mod:`slappyengine.hud_bridge` uses the same singleton
so the running frame surfaces the last few warnings/errors in-viewport.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticEvent:
    """One captured logging record, distilled for HUD / tooling display.

    Parameters
    ----------
    level:
        Logger level name, upper-case (``"WARNING"``, ``"ERROR"``, ...).
    subsystem:
        Best-effort subsystem tag derived from ``record.name``. For a
        logger named ``slappyengine.render.ssao`` the subsystem is
        ``"render"`` (the first component past ``slappyengine.``). For
        loggers without a ``slappyengine`` prefix the top-level module
        name is used.
    message:
        Fully formatted log message (``record.getMessage()``).
    timestamp:
        Wall-clock time in seconds since epoch (``time.time()`` at
        capture).
    exc_info:
        Formatted traceback when the log call carried ``exc_info=True``;
        ``None`` otherwise.
    """

    level: str
    subsystem: str
    message: str
    timestamp: float
    exc_info: Optional[str]


# ---------------------------------------------------------------------------
# Subsystem extraction helper
# ---------------------------------------------------------------------------


_PKG_PREFIX = "slappyengine"


def _subsystem_from_logger_name(name: str) -> str:
    """Return the subsystem tag for a logger name.

    * ``slappyengine.render.ssao``      -> ``"render"``
    * ``slappyengine.audio_3d``         -> ``"audio_3d"``
    * ``slappyengine``                  -> ``"slappyengine"``
    * ``other.pkg.thing``               -> ``"other"``

    The rule: if the name starts with ``slappyengine.`` we take the
    *first* component past the prefix; otherwise we take the first
    component of the dotted name. Empty / malformed names collapse to
    ``"unknown"``.
    """
    if not name:
        return "unknown"
    parts = name.split(".")
    if parts[0] == _PKG_PREFIX and len(parts) >= 2:
        return parts[1]
    return parts[0]


# ---------------------------------------------------------------------------
# Handler + collector
# ---------------------------------------------------------------------------


class _CollectorHandler(logging.Handler):
    """Thin logging.Handler that forwards records to a collector.

    Kept as a nested private class so :meth:`DiagnosticsCollector.install`
    can attach exactly one handler per collector instance and identify it
    on uninstall via the ``collector`` back-pointer.
    """

    def __init__(self, collector: "DiagnosticsCollector") -> None:
        super().__init__(level=collector._min_level_num)
        self.collector = collector

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        try:
            self.collector._capture(record)
        except Exception:
            # Never let the handler take down the caller. The
            # logging.Handler.handleError fallback keeps error visibility
            # without escaping into user code.
            self.handleError(record)


class DiagnosticsCollector:
    """Rolling-buffer aggregator for ``slappyengine.*`` log records.

    Parameters
    ----------
    max_events:
        Ring-buffer capacity. When the buffer fills, the oldest events
        are dropped first.
    min_level:
        Minimum log level captured. Records below this level are
        ignored. Accepts standard level names (``"DEBUG"``, ``"INFO"``,
        ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``) or their integer
        equivalents. Defaults to ``"WARNING"`` because the point of this
        aggregator is to surface warnings + errors.

    The collector is thread-safe: :meth:`_capture` acquires an internal
    lock so concurrent log calls from worker threads (e.g. audio, GPU
    upload) do not clobber the ring buffer.
    """

    def __init__(self, max_events: int = 500, min_level: str = "WARNING") -> None:
        if max_events <= 0:
            raise ValueError(
                f"DiagnosticsCollector: max_events must be > 0; got {max_events!r}"
            )
        self._max_events = int(max_events)
        self._min_level_num = _coerce_level(min_level)
        self._events: deque[DiagnosticEvent] = deque(maxlen=self._max_events)
        self._lock = threading.RLock()
        self._handler: Optional[_CollectorHandler] = None
        self._root_logger_name = _PKG_PREFIX

    # ------------------------------------------------------------------
    # install / uninstall
    # ------------------------------------------------------------------

    def install(self) -> None:
        """Attach the capture handler to the ``slappyengine`` logger.

        Idempotent — a second call is a no-op. The handler forwards
        records at ``min_level`` or above; lower-level records are
        filtered out cheaply by the logging framework's own level check.
        """
        with self._lock:
            if self._handler is not None:
                return
            logger = logging.getLogger(self._root_logger_name)
            handler = _CollectorHandler(self)
            handler.setLevel(self._min_level_num)
            logger.addHandler(handler)
            # Ensure the root logger's effective level lets warnings
            # through, without demoting a stricter user config.
            if logger.level == logging.NOTSET or logger.level > self._min_level_num:
                # Do NOT lower a user-set stricter level; only widen if
                # unset. This preserves user intent while making sure
                # warnings actually reach our handler.
                if logger.level == logging.NOTSET:
                    logger.setLevel(self._min_level_num)
            self._handler = handler

    def uninstall(self) -> None:
        """Detach the capture handler. Idempotent."""
        with self._lock:
            if self._handler is None:
                return
            logger = logging.getLogger(self._root_logger_name)
            try:
                logger.removeHandler(self._handler)
            finally:
                self._handler = None

    def is_installed(self) -> bool:
        """Return ``True`` iff the capture handler is currently attached."""
        return self._handler is not None

    # ------------------------------------------------------------------
    # Buffer ops
    # ------------------------------------------------------------------

    def events(self) -> list[DiagnosticEvent]:
        """Return a snapshot copy of the buffered events (oldest first)."""
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        """Drop every buffered event."""
        with self._lock:
            self._events.clear()

    def stats(self) -> dict[str, int]:
        """Return per-level + per-subsystem counts.

        The result dict has two flat namespaces so HUD widgets can
        consume it directly:

        * ``level:WARNING`` / ``level:ERROR`` / ``level:CRITICAL`` / ...
        * ``subsystem:render`` / ``subsystem:audio_3d`` / ...

        Plus a ``total`` key with the count of events in the buffer.
        """
        with self._lock:
            level_counts: Counter[str] = Counter(e.level for e in self._events)
            subsys_counts: Counter[str] = Counter(e.subsystem for e in self._events)
            out: dict[str, int] = {"total": len(self._events)}
            for lvl, n in level_counts.items():
                out[f"level:{lvl}"] = int(n)
            for sub, n in subsys_counts.items():
                out[f"subsystem:{sub}"] = int(n)
            return out

    def filter_by_subsystem(self, name: str) -> list[DiagnosticEvent]:
        """Return events whose ``subsystem`` starts with *name*.

        Prefix match so ``"render"`` catches both ``render`` and any
        future ``render.ssao`` sub-tag.
        """
        with self._lock:
            return [e for e in self._events if e.subsystem.startswith(name)]

    # ------------------------------------------------------------------
    # Internal capture path
    # ------------------------------------------------------------------

    def _capture(self, record: logging.LogRecord) -> None:
        # Belt-and-braces level filter — the handler's setLevel already
        # rejects lower records but a caller may push records through
        # this path directly (e.g. tests).
        if record.levelno < self._min_level_num:
            return
        exc_text: Optional[str] = None
        if record.exc_info:
            try:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
            except Exception:
                exc_text = None
        evt = DiagnosticEvent(
            level=record.levelname,
            subsystem=_subsystem_from_logger_name(record.name),
            message=record.getMessage(),
            timestamp=time.time(),
            exc_info=exc_text,
        )
        with self._lock:
            self._events.append(evt)


def _coerce_level(level: str | int) -> int:
    """Convert *level* (name or number) to the integer level constant."""
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        num = logging.getLevelName(level.upper())
        if isinstance(num, int):
            return num
    raise ValueError(f"DiagnosticsCollector: unknown log level {level!r}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_GLOBAL_COLLECTOR: Optional[DiagnosticsCollector] = None
_GLOBAL_LOCK = threading.Lock()


def get_global_collector() -> DiagnosticsCollector:
    """Return the process-wide :class:`DiagnosticsCollector` (lazy init).

    The first call constructs the collector with default parameters
    (``max_events=500``, ``min_level="WARNING"``) but does *not*
    :meth:`~DiagnosticsCollector.install` it — the caller (HUD widget,
    app bootstrap, test harness) decides when to attach the handler.
    """
    global _GLOBAL_COLLECTOR
    with _GLOBAL_LOCK:
        if _GLOBAL_COLLECTOR is None:
            _GLOBAL_COLLECTOR = DiagnosticsCollector()
        return _GLOBAL_COLLECTOR


__all__ = [
    "DiagnosticEvent",
    "DiagnosticsCollector",
    "get_global_collector",
]
