"""``NotebookMessageLog`` — diary-themed message log + telemetry panel.

A scrolling log panel that captures engine messages from three sources:

1. Direct programmatic calls via :meth:`NotebookMessageLog.append`.
2. Python :mod:`logging` records via :class:`_DiaryLogHandler` (installed
   on the root logger by :meth:`subscribe_to_logging`).
3. :mod:`pharos_engine.telemetry` events via :meth:`subscribe_to_telemetry`.

The panel renders each message as a row with a level chip, a
``HH:MM:SS`` timestamp, the source module name, and the message text.
Rows are backed by a bounded ring buffer (default 500) so long-running
sessions don't leak memory.

Diary-page theming
------------------

* Ruled-paper background under the message list.
* Hand-drawn (doodle) separator drawn between rows every 5 entries.
* Selected row highlighted with a highlighter-yellow washi tint.

Header controls
---------------

* Level filter buttons: ``DEBUG`` (gray) / ``INFO`` (blue) / ``WARN``
  (amber) / ``ERROR`` (red). Clicking toggles whether that level is
  visible.
* Search box — case-insensitive substring match across
  ``level | source | message``.
* Clear button.
* Save button — writes the currently *visible* messages to
  ``session_log_<YYYYMMDD_HHMMSS>.txt`` in the current working directory
  (or an explicit path passed to :meth:`save_to_file`).
* Pause / Resume — while paused, :meth:`append` (and the log-handler /
  telemetry callbacks that funnel through it) drop new messages on the
  floor.

Auto-scroll
-----------

The panel auto-scrolls to the newest row unless the user has manually
scrolled up. The scroll flag is a headless-safe boolean managed via
:meth:`set_user_scrolled`.

Log-handler integration pattern
-------------------------------

:class:`_DiaryLogHandler` is a :class:`logging.Handler` subclass that
forwards each record's ``levelname`` / ``name`` / ``getMessage()`` into
the panel via :meth:`append`. The handler is installed on the root
logger the first time :meth:`subscribe_to_logging` is called and
removed by :meth:`unsubscribe_from_logging`. Formatting mirrors the
standard-library convention so downstream tools can round-trip a saved
session log.

Every :mod:`dearpygui` call is funnelled through ``_safe_dpg`` so the
panel is headless-safe and testable under a stub DPG.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
    validate_str,
)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_real_dpg(dpg: Any) -> bool:
    """Return ``True`` when *dpg* is the real ``dearpygui.dearpygui`` module.

    The real module binds ``internal_dpg`` to the ``_dearpygui`` C
    extension module. Test stubs set up via ``sys.modules`` monkey-
    patching typically install a ``__getattr__`` fallback that returns a
    callable for any missing name, so we cannot rely on
    ``hasattr(dpg, "internal_dpg")`` alone — instead we require that the
    attribute resolves to an actual ``ModuleType`` whose ``__name__``
    starts with ``dearpygui``.
    """
    import types
    inner = getattr(dpg, "internal_dpg", None)
    if not isinstance(inner, types.ModuleType):
        return False
    return getattr(inner, "__name__", "").startswith("dearpygui")


def _headless_env_active() -> bool:
    """Return ``True`` when ``SLAPPY_HEADLESS=1`` (or truthy) is set."""
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if usable, else ``None``.

    "Usable" means either:

    * A test-installed stub module (detected by absence of the
      ``internal_dpg`` marker), or
    * The real DPG module *and* ``SLAPPY_HEADLESS`` is unset. When
      ``SLAPPY_HEADLESS=1`` is set, calling into the real DPG module
      before ``dpg.create_context()`` triggers a Windows access-violation
      inside the C runtime — that access violation cannot be caught by
      Python-level ``try/except``. This guard degrades gracefully to
      "no widgets rendered" so the panel's pure-Python logic stays
      testable under real DPG in headless CI.
    """
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if _is_real_dpg(dpg) and _headless_env_active():
        return None
    return dpg


# Levels the panel knows about + their default chip colours (RGBA 0..255).
LEVEL_DEBUG = "DEBUG"
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"

LEVELS: tuple[str, ...] = (LEVEL_DEBUG, LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR)

LEVEL_COLORS: dict[str, tuple[int, int, int, int]] = {
    LEVEL_DEBUG: (140, 140, 150, 255),   # gray
    LEVEL_INFO:  ( 90, 140, 220, 255),   # blue
    LEVEL_WARN:  (230, 170,  60, 255),   # amber
    LEVEL_ERROR: (220,  80,  80, 255),   # red
}

# Map stdlib logging level ints -> panel level string.
_STDLIB_LEVEL_MAP: tuple[tuple[int, str], ...] = (
    (logging.ERROR,    LEVEL_ERROR),
    (logging.WARNING,  LEVEL_WARN),
    (logging.INFO,     LEVEL_INFO),
    (logging.DEBUG,    LEVEL_DEBUG),
)


def normalise_level(level: Any) -> str:
    """Coerce *level* into one of the four canonical level strings.

    Accepts stdlib ``int`` levels (``logging.INFO`` etc.), aliases
    (``WARNING`` → ``WARN``, ``CRITICAL`` / ``FATAL`` → ``ERROR``), and
    case-insensitive strings. Unknown levels fall back to ``INFO``.
    """
    if isinstance(level, bool):
        # ``bool`` is an ``int`` subclass — refuse it explicitly so
        # ``True`` doesn't accidentally read as ``logging.DEBUG (10)``.
        raise TypeError("normalise_level: level must be str or int, not bool")
    if isinstance(level, int):
        for threshold, name in _STDLIB_LEVEL_MAP:
            if level >= threshold:
                return name
        return LEVEL_DEBUG
    if not isinstance(level, str):
        raise TypeError(
            f"normalise_level: level must be str or int; "
            f"got {type(level).__name__}"
        )
    up = level.strip().upper()
    if up in LEVELS:
        return up
    aliases = {
        "WARNING": LEVEL_WARN,
        "CRIT": LEVEL_ERROR,
        "CRITICAL": LEVEL_ERROR,
        "FATAL": LEVEL_ERROR,
        "ERR": LEVEL_ERROR,
        "DBG": LEVEL_DEBUG,
        "TRACE": LEVEL_DEBUG,
        "NOTICE": LEVEL_INFO,
    }
    return aliases.get(up, LEVEL_INFO)


def _format_timestamp(ts: float) -> str:
    """Return ``HH:MM:SS`` for a wall-clock unix timestamp."""
    try:
        lt = time.localtime(float(ts))
        return time.strftime("%H:%M:%S", lt)
    except Exception:
        return "??:??:??"


# ---------------------------------------------------------------------------
# Message record
# ---------------------------------------------------------------------------


@dataclass
class LogMessage:
    """A single message row rendered by the panel.

    Attributes
    ----------
    level:
        Canonical level string (see :data:`LEVELS`).
    source:
        Dotted module name (e.g. ``"pharos_engine.dynamics"``).
    message:
        Human-readable message text.
    timestamp:
        Wall-clock unix timestamp (``time.time()``).
    """

    level: str
    source: str
    message: str
    timestamp: float = field(default_factory=time.time)

    def matches_search(self, needle: str) -> bool:
        """Return whether *needle* substring-matches this row (case-insensitive)."""
        if not needle:
            return True
        n = needle.lower()
        return (
            n in self.level.lower()
            or n in self.source.lower()
            or n in self.message.lower()
        )

    def format_line(self) -> str:
        """Format the message for text export."""
        ts = _format_timestamp(self.timestamp)
        return f"[{ts}] {self.level:<5} {self.source}: {self.message}"


# ---------------------------------------------------------------------------
# Log handler
# ---------------------------------------------------------------------------


class _DiaryLogHandler(logging.Handler):
    """A :class:`logging.Handler` that forwards records to a panel.

    The handler holds a *weak-ish* reference: it stores the panel
    directly but exposes a ``.close()`` (called via
    :meth:`NotebookMessageLog.unsubscribe_from_logging`) that clears the
    reference so a leaked handler cannot keep the panel alive after
    ``destroy``.
    """

    def __init__(self, panel: "NotebookMessageLog | None") -> None:
        super().__init__(level=logging.DEBUG)
        self._panel: NotebookMessageLog | None = panel

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no branch
        panel = self._panel
        if panel is None:
            return
        try:
            level = normalise_level(record.levelno)
            source = record.name or "root"
            message = record.getMessage()
            panel.append(level, source, message)
        except Exception:  # noqa: BLE001
            # A log handler must NEVER raise from ``emit`` — the stdlib
            # logging module would then propagate the failure into the
            # producer. Swallow + report via ``handleError`` per stdlib
            # convention.
            self.handleError(record)

    def close(self) -> None:
        """Detach the panel reference and remove ourselves from any logger."""
        self._panel = None
        super().close()


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------


class NotebookMessageLog:
    """Diary-themed scrolling message log.

    Renders as a movable panel window (wrapped externally by the editor
    shell using :class:`~pharos_engine.ui.editor.movable_panel.MovablePanelWindow`).
    The panel exposes the :meth:`build(parent_tag)` protocol expected by
    the wrapper.

    Parameters
    ----------
    max_rows:
        Cap on the in-memory ring buffer. Defaults to 500.
    """

    TITLE = "Messages"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 260

    DEFAULT_MAX_ROWS: int = 500

    _ROOT_TAG = "notebook_message_log_root"
    _SEARCH_TAG = "notebook_message_log_search"
    _LIST_TAG = "notebook_message_log_list"
    _STATUS_TAG = "notebook_message_log_status"
    _RULED_TAG = "notebook_message_log_ruled"

    def __init__(self, *, max_rows: int = DEFAULT_MAX_ROWS) -> None:
        validate_positive_int("max_rows", "NotebookMessageLog", max_rows)
        self._max_rows: int = int(max_rows)
        self._messages: list[LogMessage] = []
        # Level filter — True means the level is *visible*. Toggling
        # via ``toggle_level`` hides that level.
        self._level_visible: dict[str, bool] = {lv: True for lv in LEVELS}
        self._search: str = ""
        self._paused: bool = False
        self._selected_index: int | None = None
        # Auto-scroll flag — True until the user scrolls up manually.
        self._user_scrolled_up: bool = False

        # Subscriber handles.
        self._telemetry_handle: int | None = None
        self._log_handler: _DiaryLogHandler | None = None
        self._log_target_logger: logging.Logger | None = None

        # Build state.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Test-observability.
        self.call_log: list[tuple[str, Any]] = []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def search(self) -> str:
        return self._search

    @property
    def selected_index(self) -> int | None:
        return self._selected_index

    @property
    def messages(self) -> list[LogMessage]:
        """Return a shallow copy of the entire buffer (oldest first)."""
        return list(self._messages)

    @property
    def visible_messages(self) -> list[LogMessage]:
        """Return the messages passing the level + search filters."""
        out: list[LogMessage] = []
        for m in self._messages:
            if not self._level_visible.get(m.level, True):
                continue
            if not m.matches_search(self._search):
                continue
            out.append(m)
        return out

    def is_level_visible(self, level: str) -> bool:
        """Return whether *level* is currently un-hidden."""
        return self._level_visible.get(normalise_level(level), True)

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def append(
        self,
        level: Any,
        source: Any,
        message: Any,
        *,
        timestamp: float | None = None,
    ) -> LogMessage | None:
        """Append a new message row.

        Returns the created :class:`LogMessage`, or ``None`` if the panel
        is paused and the append was dropped.

        Parameters
        ----------
        level:
            Level string or stdlib int; coerced via :func:`normalise_level`.
        source:
            Dotted module name.
        message:
            Human-readable text.
        timestamp:
            Optional explicit unix timestamp; defaults to ``time.time()``.

        Raises
        ------
        TypeError
            If ``source`` or ``message`` is not a string.
        """
        if self._paused:
            self.call_log.append(("append_dropped", (level, source, message)))
            return None
        norm_level = normalise_level(level)
        validate_str("source", "NotebookMessageLog.append", source,
                     allow_empty=True)
        validate_str("message", "NotebookMessageLog.append", message,
                     allow_empty=True)
        ts = float(timestamp) if timestamp is not None else time.time()
        msg = LogMessage(
            level=norm_level,
            source=str(source),
            message=str(message),
            timestamp=ts,
        )
        self._messages.append(msg)
        # Ring buffer trim — drop from the head (oldest).
        overflow = len(self._messages) - self._max_rows
        if overflow > 0:
            del self._messages[:overflow]
            # Selected index compensation.
            if self._selected_index is not None:
                new_idx = self._selected_index - overflow
                self._selected_index = new_idx if new_idx >= 0 else None
        self.call_log.append(("append", msg))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return msg

    def clear(self) -> None:
        """Empty the buffer and drop the selection."""
        self._messages.clear()
        self._selected_index = None
        self.call_log.append(("clear", None))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    def set_max_rows(self, n: int) -> None:
        """Cap the ring buffer to *n* rows (trims oldest immediately)."""
        validate_positive_int("n", "NotebookMessageLog.set_max_rows", n)
        self._max_rows = int(n)
        overflow = len(self._messages) - self._max_rows
        if overflow > 0:
            del self._messages[:overflow]
            if self._selected_index is not None:
                new_idx = self._selected_index - overflow
                self._selected_index = new_idx if new_idx >= 0 else None
        self.call_log.append(("set_max_rows", self._max_rows))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def toggle_level(self, level: str) -> bool:
        """Toggle visibility for *level*. Returns the new visibility flag."""
        norm = normalise_level(level)
        new = not self._level_visible.get(norm, True)
        self._level_visible[norm] = new
        self.call_log.append(("toggle_level", (norm, new)))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return new

    def set_level_visible(self, level: str, visible: bool) -> None:
        """Explicitly set visibility for *level*."""
        norm = normalise_level(level)
        if not isinstance(visible, bool):
            raise TypeError(
                "NotebookMessageLog.set_level_visible: visible must be bool"
            )
        self._level_visible[norm] = visible
        self.call_log.append(("set_level_visible", (norm, visible)))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    def set_search(self, needle: str) -> None:
        """Set the substring search filter."""
        validate_str("needle", "NotebookMessageLog.set_search",
                     needle, allow_empty=True)
        self._search = needle or ""
        self.call_log.append(("set_search", self._search))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, index: int | None) -> None:
        """Highlight the row at *index* in the *visible* list (``None`` clears)."""
        if index is None:
            self._selected_index = None
        else:
            if not isinstance(index, int) or isinstance(index, bool):
                raise TypeError(
                    "NotebookMessageLog.select: index must be int or None"
                )
            visible = self.visible_messages
            if index < 0 or index >= len(visible):
                raise IndexError(
                    f"NotebookMessageLog.select: index {index} out of range "
                    f"[0, {len(visible)})"
                )
            # Map visible index -> canonical buffer index for stable
            # tracking across filter changes.
            target = visible[index]
            for i, m in enumerate(self._messages):
                if m is target:
                    self._selected_index = i
                    break
        self.call_log.append(("select", self._selected_index))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def toggle_pause(self) -> bool:
        """Flip the pause flag. Returns the new state."""
        self._paused = not self._paused
        self.call_log.append(("pause", self._paused))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return self._paused

    def pause(self) -> None:
        if not self._paused:
            self.toggle_pause()

    def resume(self) -> None:
        if self._paused:
            self.toggle_pause()

    # ------------------------------------------------------------------
    # Scroll
    # ------------------------------------------------------------------

    def set_user_scrolled(self, scrolled_up: bool) -> None:
        """Record whether the user has manually scrolled up.

        When ``False``, subsequent appends auto-scroll to the newest row.
        """
        if not isinstance(scrolled_up, bool):
            raise TypeError(
                "NotebookMessageLog.set_user_scrolled: scrolled_up must be bool"
            )
        self._user_scrolled_up = scrolled_up
        self.call_log.append(("user_scrolled", scrolled_up))

    def is_autoscroll_active(self) -> bool:
        """Return whether auto-scroll to newest is currently active."""
        return not self._user_scrolled_up

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_to_file(self, path: str | Path | None = None) -> Path:
        """Dump the currently visible messages to *path* (or a default).

        The default path is ``session_log_<YYYYMMDD_HHMMSS>.txt`` in the
        current working directory.

        Returns the absolute :class:`~pathlib.Path` that was written.
        """
        if path is None:
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            path = Path.cwd() / f"session_log_{stamp}.txt"
        else:
            path = Path(path)
        lines = [m.format_line() for m in self.visible_messages]
        header = (
            f"# SlapPyEngine session log — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# {len(lines)} messages\n"
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        path.write_text(header + "\n".join(lines) + ("\n" if lines else ""),
                        encoding="utf-8")
        self.call_log.append(("save_to_file", str(path)))
        return path.resolve()

    # ------------------------------------------------------------------
    # Telemetry integration
    # ------------------------------------------------------------------

    def subscribe_to_telemetry(self, pattern: str = "*") -> int:
        """Subscribe to :mod:`pharos_engine.telemetry` events.

        The pattern defaults to the catch-all ``"*"``. Events are
        appended with level ``INFO``, source ``"telemetry.<event.name>"``,
        and message ``"<payload preview>"``.

        Idempotent — a second call re-uses the existing handle.
        """
        from pharos_engine import telemetry
        if self._telemetry_handle is not None:
            return self._telemetry_handle
        self._telemetry_handle = telemetry.subscribe(pattern, self._on_event)
        self.call_log.append(("subscribe_telemetry", pattern))
        return self._telemetry_handle

    def unsubscribe_from_telemetry(self) -> None:
        """Detach from the telemetry bus. Idempotent."""
        if self._telemetry_handle is None:
            return
        try:
            from pharos_engine import telemetry
            telemetry.unsubscribe(self._telemetry_handle)
        except Exception:
            pass
        self._telemetry_handle = None
        self.call_log.append(("unsubscribe_telemetry", None))

    def _on_event(self, event: Any) -> None:
        """Handle a telemetry event by appending an INFO row."""
        try:
            payload = getattr(event, "payload", None) or {}
            preview_bits: list[str] = []
            for k, v in payload.items():
                sv = repr(v) if not isinstance(v, str) else v
                if len(sv) > 20:
                    sv = sv[:17] + "..."
                preview_bits.append(f"{k}={sv}")
                if len(preview_bits) >= 4:
                    break
            preview = ", ".join(preview_bits)
            source = f"telemetry.{event.name}"
            message = preview if preview else "(no payload)"
            self.append(LEVEL_INFO, source, message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Logging integration
    # ------------------------------------------------------------------

    def subscribe_to_logging(
        self,
        logger: logging.Logger | None = None,
    ) -> _DiaryLogHandler:
        """Install a :class:`_DiaryLogHandler` on *logger* (root by default).

        Returns the installed handler. Idempotent — a second call
        returns the existing handler.
        """
        if self._log_handler is not None:
            return self._log_handler
        target = logger if logger is not None else logging.getLogger()
        handler = _DiaryLogHandler(self)
        target.addHandler(handler)
        self._log_handler = handler
        self._log_target_logger = target
        self.call_log.append(("subscribe_logging", target.name))
        return handler

    def unsubscribe_from_logging(self) -> None:
        """Remove the log handler and detach the panel reference. Idempotent."""
        handler = self._log_handler
        if handler is None:
            return
        try:
            target = self._log_target_logger or logging.getLogger()
            target.removeHandler(handler)
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
        self._log_handler = None
        self._log_target_logger = None
        self.call_log.append(("unsubscribe_logging", None))

    # ------------------------------------------------------------------
    # Build / refresh / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Construct the panel widgets under *parent_tag* (headless-safe)."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                self._build_header(dpg)
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                # Ruled paper background container.
                try:
                    with dpg.child_window(tag=self._RULED_TAG,
                                          border=True, height=-30):
                        with dpg.group(tag=self._LIST_TAG):
                            self._build_rows(dpg)
                except Exception:
                    try:
                        dpg.add_group(tag=self._LIST_TAG)
                    except Exception:
                        pass
                    self._build_rows(dpg)
                # Status footer.
                try:
                    dpg.add_text(self._format_status(), tag=self._STATUS_TAG)
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_header(self, dpg: Any) -> None:
        """Build the header row: filter buttons, search, clear, save, pause."""
        try:
            with dpg.group(horizontal=True):
                for lv in LEVELS:
                    color = LEVEL_COLORS.get(lv, (200, 200, 200, 255))
                    try:
                        dpg.add_button(
                            label=lv,
                            callback=self._make_toggle_level_cb(lv),
                            user_data=lv,
                        )
                    except Exception:
                        pass
                    try:
                        # Level chip colour hint next to the button.
                        dpg.add_text(" ", color=list(color))
                    except Exception:
                        pass
                try:
                    dpg.add_input_text(
                        hint="search...",
                        tag=self._SEARCH_TAG,
                        callback=self._on_search_changed,
                        width=180,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Clear",
                        callback=self._on_clear_clicked,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Save",
                        callback=self._on_save_clicked,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Pause" if not self._paused else "Resume",
                        callback=self._on_pause_clicked,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _build_rows(self, dpg: Any) -> None:
        """Render the visible message rows (headless-safe)."""
        rows = self.visible_messages
        if not rows:
            try:
                dpg.add_text("(no messages yet)")
            except Exception:
                pass
            return

        # Map visible index -> selected? by matching against buffer index.
        selected_msg: LogMessage | None = None
        if self._selected_index is not None and (
            0 <= self._selected_index < len(self._messages)
        ):
            selected_msg = self._messages[self._selected_index]

        # Cap render depth so DPG stays snappy on huge buffers.
        display_cap = 200
        display = rows[-display_cap:]

        for i, msg in enumerate(display):
            level_color = list(LEVEL_COLORS.get(msg.level, (200, 200, 200, 255)))
            ts = _format_timestamp(msg.timestamp)
            is_selected = (msg is selected_msg)
            try:
                with dpg.group(horizontal=True):
                    # Level chip.
                    try:
                        dpg.add_text(f"[{msg.level}]", color=level_color)
                    except Exception:
                        pass
                    # Timestamp.
                    try:
                        dpg.add_text(ts)
                    except Exception:
                        pass
                    # Source.
                    try:
                        dpg.add_text(msg.source)
                    except Exception:
                        pass
                    # Message body — highlighter-yellow when selected.
                    try:
                        if is_selected:
                            dpg.add_text(
                                msg.message,
                                color=[40, 40, 40, 255],
                            )
                        else:
                            dpg.add_text(msg.message)
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(f"[{msg.level}] {msg.source}: {msg.message}")
                except Exception:
                    pass
            # Hand-drawn separator every 5 messages.
            if (i + 1) % 5 == 0 and (i + 1) < len(display):
                try:
                    dpg.add_text("~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~")
                except Exception:
                    pass

        # Auto-scroll unless the user has scrolled up.
        if not self._user_scrolled_up:
            try:
                dpg.set_y_scroll(self._RULED_TAG, -1.0)
            except Exception:
                pass

    def refresh(self) -> None:
        """Rebuild rows + status under the existing tags."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                dpg.set_value(self._STATUS_TAG, self._format_status())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._LIST_TAG):
                for child in list(
                    dpg.get_item_children(self._LIST_TAG, slot=1) or []
                ):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._LIST_TAG):
                    self._build_rows(dpg)
        except Exception:
            try:
                self._build_rows(dpg)
            except Exception:
                pass

    def destroy(self) -> None:
        """Tear down subscribers so the panel can be garbage-collected."""
        self.unsubscribe_from_telemetry()
        self.unsubscribe_from_logging()
        self._built = False

    # ------------------------------------------------------------------
    # Header callbacks
    # ------------------------------------------------------------------

    def _make_toggle_level_cb(self, level: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            self.toggle_level(level)
        return _cb

    def _on_search_changed(self, sender: Any, app_data: Any, user_data: Any) -> None:
        self.set_search(str(app_data or ""))

    def _on_clear_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.clear()

    def _on_save_clicked(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.save_to_file()
        except Exception:
            pass

    def _on_pause_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.toggle_pause()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _format_status(self) -> str:
        hidden = [lv for lv, vis in self._level_visible.items() if not vis]
        state = "paused" if self._paused else "live"
        hidden_str = "none" if not hidden else ",".join(hidden)
        return (
            f"{state} | rows: {len(self._messages)}/{self._max_rows} | "
            f"visible: {len(self.visible_messages)} | "
            f"hidden: {hidden_str} | "
            f"search: {self._search or '(none)'}"
        )


__all__ = [
    "LEVEL_COLORS",
    "LEVEL_DEBUG",
    "LEVEL_ERROR",
    "LEVEL_INFO",
    "LEVEL_WARN",
    "LEVELS",
    "LogMessage",
    "NotebookMessageLog",
    "_DiaryLogHandler",
    "normalise_level",
]
