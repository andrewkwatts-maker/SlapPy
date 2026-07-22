"""Runtime diagnostics aggregator — subscribes to subsystem loggers.

MM1 (`1e584e4`) sprinkled ``_LOG = logging.getLogger(__name__)`` warnings
across 13 subsystem files (audio_3d, capture, exporter, physics3_bridge,
render/ssao|skybox|instanced, text, asset_import/*, etc.). Prior to this
module those warnings just spammed stderr and disappeared. The
:class:`DiagnosticsCollector` in this module attaches a
:class:`logging.Handler` to the ``pharos_engine`` root logger, captures
records at ``min_level+``, keeps a rolling buffer, and exposes structured
:class:`DiagnosticEvent` objects for the HUD overlay and downstream
tooling.

The aggregator is *passive*: it does not modify any existing logging
call site. Subsystems keep using ``_LOG.warning(...)`` as before; the
collector subscribes on top.

Typical wiring::

    from pharos_engine.diagnostics import get_global_collector
    collector = get_global_collector()
    collector.install()
    ...
    for evt in collector.events()[-5:]:
        print(evt.level, evt.subsystem, evt.message)

The HUD widget in :mod:`pharos_engine.hud_bridge` uses the same singleton
so the running frame surfaces the last few warnings/errors in-viewport.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union


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
        logger named ``pharos_engine.render.ssao`` the subsystem is
        ``"render"`` (the first component past ``pharos_engine.``). For
        loggers without a ``pharos_engine`` prefix the top-level module
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


_PKG_PREFIX = "pharos_engine"


def _subsystem_from_logger_name(name: str) -> str:
    """Return the subsystem tag for a logger name.

    * ``pharos_engine.render.ssao``      -> ``"render"``
    * ``pharos_engine.audio_3d``         -> ``"audio_3d"``
    * ``pharos_engine``                  -> ``"pharos_engine"``
    * ``other.pkg.thing``               -> ``"other"``

    The rule: if the name starts with ``pharos_engine.`` we take the
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
    """Rolling-buffer aggregator for ``pharos_engine.*`` log records.

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
        """Attach the capture handler to the ``pharos_engine`` logger.

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
    # RR4 extensions — filter / aggregate / serialise
    # ------------------------------------------------------------------

    def filter_by_level(self, level: str) -> list[DiagnosticEvent]:
        """Return events at exactly *level* (case-insensitive).

        Parameters
        ----------
        level:
            Level name (``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``,
            ``"INFO"``, ``"DEBUG"``). Match is case-insensitive.

        Raises
        ------
        ValueError
            If *level* is not a recognised logging level name.
        """
        if not isinstance(level, str):
            raise ValueError(
                f"DiagnosticsCollector.filter_by_level: level must be str; got {level!r}"
            )
        upper = level.upper()
        # Validate via _coerce_level — raises ValueError on unknown.
        num = logging.getLevelName(upper)
        if not isinstance(num, int):
            raise ValueError(
                f"DiagnosticsCollector.filter_by_level: unknown level {level!r}"
            )
        with self._lock:
            return [e for e in self._events if e.level == upper]

    def top_subsystems(self, n: int = 5) -> list[tuple[str, int]]:
        """Return the top-*n* subsystems by event count, descending.

        ``n <= 0`` returns an empty list.
        """
        if n <= 0:
            return []
        with self._lock:
            counts: Counter[str] = Counter(e.subsystem for e in self._events)
        return counts.most_common(n)

    def since(self, timestamp: float) -> list[DiagnosticEvent]:
        """Return events with ``event.timestamp >= timestamp``."""
        with self._lock:
            return [e for e in self._events if e.timestamp >= timestamp]

    def clear_by_subsystem(self, name: str) -> int:
        """Remove events whose ``subsystem`` starts with *name*.

        Returns the number of events removed. Prefix match mirrors
        :meth:`filter_by_subsystem`.
        """
        with self._lock:
            before = len(self._events)
            kept = [e for e in self._events if not e.subsystem.startswith(name)]
            removed = before - len(kept)
            if removed:
                self._events.clear()
                self._events.extend(kept)
            return removed

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialise current events + stats to a JSON string.

        Format::

            {
              "events": [ {level, subsystem, message, timestamp, exc_info}, ... ],
              "stats":  { "total": N, "level:WARNING": ..., ... },
              "meta":   { "max_events": int, "min_level": str, "captured_at": iso8601 }
            }

        *indent* is forwarded to :func:`json.dumps`.
        """
        with self._lock:
            events_payload = [asdict(e) for e in self._events]
            stats_payload = self._stats_locked()
            min_level_name = logging.getLevelName(self._min_level_num)
            meta_payload = {
                "max_events": int(self._max_events),
                "min_level": str(min_level_name),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        payload = {
            "events": events_payload,
            "stats": stats_payload,
            "meta": meta_payload,
        }
        return json.dumps(payload, indent=indent)

    @classmethod
    def from_json(cls, data: str) -> "DiagnosticsCollector":
        """Load a JSON dump; return a fresh (uninstalled) collector.

        The returned collector is populated with the serialised events
        and its ``max_events`` / ``min_level`` come from the ``meta``
        block. It is *not* installed on any logger — the caller must
        call :meth:`install` explicitly if live capture is wanted.

        Raises
        ------
        ValueError
            If the JSON is malformed, or required top-level keys
            (``events``, ``meta``) are missing / mis-shaped.
        """
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"DiagnosticsCollector.from_json: malformed JSON ({exc})"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                "DiagnosticsCollector.from_json: top-level must be an object"
            )
        for key in ("events", "meta"):
            if key not in payload:
                raise ValueError(
                    f"DiagnosticsCollector.from_json: missing key {key!r}"
                )
        meta = payload["meta"]
        if not isinstance(meta, dict):
            raise ValueError(
                "DiagnosticsCollector.from_json: 'meta' must be an object"
            )
        events_raw = payload["events"]
        if not isinstance(events_raw, list):
            raise ValueError(
                "DiagnosticsCollector.from_json: 'events' must be a list"
            )
        max_events = meta.get("max_events", 500)
        min_level = meta.get("min_level", "WARNING")
        try:
            max_events_int = int(max_events)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"DiagnosticsCollector.from_json: bad max_events {max_events!r}"
            ) from exc
        try:
            collector = cls(max_events=max_events_int, min_level=min_level)
        except ValueError as exc:
            raise ValueError(
                f"DiagnosticsCollector.from_json: bad meta ({exc})"
            ) from exc
        rebuilt: list[DiagnosticEvent] = []
        required_fields = {"level", "subsystem", "message", "timestamp", "exc_info"}
        for i, raw in enumerate(events_raw):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"DiagnosticsCollector.from_json: event #{i} is not an object"
                )
            missing = required_fields - raw.keys()
            if missing:
                raise ValueError(
                    f"DiagnosticsCollector.from_json: event #{i} missing {sorted(missing)}"
                )
            try:
                rebuilt.append(
                    DiagnosticEvent(
                        level=str(raw["level"]),
                        subsystem=str(raw["subsystem"]),
                        message=str(raw["message"]),
                        timestamp=float(raw["timestamp"]),
                        exc_info=(
                            None if raw["exc_info"] is None else str(raw["exc_info"])
                        ),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"DiagnosticsCollector.from_json: event #{i} bad field ({exc})"
                ) from exc
        with collector._lock:
            collector._events.extend(rebuilt)
        return collector

    # ------------------------------------------------------------------
    # SS6 extension — Markdown report generator
    # ------------------------------------------------------------------

    def render_markdown_report(
        self, max_events: int = 50, group_by: str = "subsystem"
    ) -> str:
        """Render a one-shot Markdown problem panel for dev / QA workflow.

        Parameters
        ----------
        max_events:
            Maximum number of rows in the "Recent events" table. Older
            events beyond this cap are dropped from the rendered table
            (but summary + top-subsystem totals still reflect the full
            buffer).
        group_by:
            Row ordering for the recent-events table.

            * ``"subsystem"`` — group by subsystem, then oldest-first
              within each subsystem.
            * ``"time"`` — pure descending timestamp (newest first).
            * ``"level"`` — descending severity (CRITICAL > ERROR >
              WARNING > INFO > DEBUG), then newest-first within a level.

        Returns
        -------
        str
            Markdown document with sections:
            ``# Diagnostics Report`` (with ISO-8601 timestamp),
            ``## Summary`` (totals + warning/error counts), ``## Top
            subsystems`` (aggregated table), ``## Recent events``.

        Raises
        ------
        ValueError
            If *group_by* is not one of the recognised keys.
        """
        if group_by not in ("subsystem", "time", "level"):
            raise ValueError(
                "DiagnosticsCollector.render_markdown_report: "
                f"group_by must be 'subsystem', 'time', or 'level'; got {group_by!r}"
            )
        if max_events < 0:
            raise ValueError(
                "DiagnosticsCollector.render_markdown_report: "
                f"max_events must be >= 0; got {max_events!r}"
            )

        with self._lock:
            events_snapshot = list(self._events)
            stats_snapshot = self._stats_locked()

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        total = int(stats_snapshot.get("total", 0))
        warn_count = int(stats_snapshot.get("level:WARNING", 0))
        error_count = int(stats_snapshot.get("level:ERROR", 0)) + int(
            stats_snapshot.get("level:CRITICAL", 0)
        )
        subsystems_affected = sum(
            1 for k in stats_snapshot if k.startswith("subsystem:")
        )

        lines: list[str] = []
        lines.append(f"# Diagnostics Report — {now_iso}")
        lines.append("")
        lines.append("## Summary")
        lines.append(f"- **Total events:** {total}")
        lines.append(f"- **Warnings:** {warn_count}, **Errors:** {error_count}")
        lines.append(f"- **Subsystems affected:** {subsystems_affected}")
        lines.append("")

        # Top subsystems table (top 10 by count).
        top_subs = Counter(e.subsystem for e in events_snapshot).most_common(10)
        lines.append("## Top subsystems")
        if not top_subs:
            lines.append("_No subsystems recorded._")
        else:
            lines.append("| Subsystem | Events |")
            lines.append("|---|---|")
            for sub, count in top_subs:
                lines.append(f"| {_md_escape(sub)} | {count} |")
        lines.append("")

        # Order the recent events.
        if group_by == "time":
            ordered = sorted(events_snapshot, key=lambda e: e.timestamp, reverse=True)
        elif group_by == "level":
            ordered = sorted(
                events_snapshot,
                key=lambda e: (_level_rank(e.level), e.timestamp),
                reverse=True,
            )
        else:  # subsystem
            ordered = sorted(
                events_snapshot, key=lambda e: (e.subsystem, e.timestamp)
            )

        truncated = ordered[:max_events]
        lines.append(f"## Recent events (last {max_events})")
        if not truncated:
            lines.append("_0 events recorded._")
        else:
            lines.append("| Time | Level | Subsystem | Message |")
            lines.append("|---|---|---|---|")
            for evt in truncated:
                # HH:MM:SS in local time — matches the sample in the spec.
                t_str = datetime.fromtimestamp(evt.timestamp).strftime("%H:%M:%S")
                lines.append(
                    "| {t} | {lvl} | {sub} | {msg} |".format(
                        t=t_str,
                        lvl=_md_escape(evt.level),
                        sub=_md_escape(evt.subsystem),
                        msg=_md_escape(evt.message),
                    )
                )
        lines.append("")

        return "\n".join(lines)

    def save_report(
        self, path: Union[str, Path], **kwargs
    ) -> Path:
        """Render the markdown report and write it to *path*.

        Parameters
        ----------
        path:
            Destination file path. Parent directory must exist.
        **kwargs:
            Forwarded to :meth:`render_markdown_report` (``max_events``,
            ``group_by``).

        Returns
        -------
        Path
            The resolved output path (as :class:`pathlib.Path`).
        """
        out = Path(path)
        content = self.render_markdown_report(**kwargs)
        out.write_text(content, encoding="utf-8")
        return out

    # ------------------------------------------------------------------
    # TT6 extension — message-substring / regex filter + time-window count
    # ------------------------------------------------------------------

    def filter_by_message(
        self, pattern: str, *, regex: bool = False
    ) -> list[DiagnosticEvent]:
        """Return events whose ``.message`` matches *pattern*.

        Parameters
        ----------
        pattern:
            Substring to look for in ``event.message`` (default), or a
            regex pattern when ``regex=True``.
        regex:
            When ``True`` treat *pattern* as a regex compiled via
            :func:`re.compile` and match with :meth:`re.Pattern.search`.

        Raises
        ------
        ValueError
            When ``regex=True`` and *pattern* is not a valid regex.
        """
        if regex:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    "DiagnosticsCollector.filter_by_message: "
                    f"invalid regex {pattern!r} ({exc})"
                ) from exc
            with self._lock:
                return [e for e in self._events if compiled.search(e.message)]
        with self._lock:
            return [e for e in self._events if pattern in e.message]

    def count_by_time_window(self, seconds: float) -> int:
        """Return the number of events captured in the last *seconds*.

        Uses :func:`time.time` as the reference clock and counts events
        with ``event.timestamp >= time.time() - seconds``.

        Raises
        ------
        ValueError
            If *seconds* is negative.
        """
        if seconds < 0:
            raise ValueError(
                "DiagnosticsCollector.count_by_time_window: "
                f"seconds must be >= 0; got {seconds!r}"
            )
        cutoff = time.time() - float(seconds)
        with self._lock:
            return sum(1 for e in self._events if e.timestamp >= cutoff)

    def _stats_locked(self) -> dict[str, int]:
        """Internal :meth:`stats` body assuming the lock is already held."""
        level_counts: Counter[str] = Counter(e.level for e in self._events)
        subsys_counts: Counter[str] = Counter(e.subsystem for e in self._events)
        out: dict[str, int] = {"total": len(self._events)}
        for lvl, n in level_counts.items():
            out[f"level:{lvl}"] = int(n)
        for sub, n in subsys_counts.items():
            out[f"subsystem:{sub}"] = int(n)
        return out

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


# ---------------------------------------------------------------------------
# Markdown-report helpers (SS6)
# ---------------------------------------------------------------------------


_LEVEL_RANK = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _level_rank(level: str) -> int:
    """Return a numeric severity for sorting; unknown levels map to 0."""
    return _LEVEL_RANK.get(level.upper(), 0)


def _md_escape(text: str) -> str:
    """Escape characters that would break a Markdown table row.

    Replaces ``|`` with ``\\|`` and collapses newlines to a space so a
    multi-line message stays on one row.
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\\", "\\\\").replace("|", "\\|")
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s


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
