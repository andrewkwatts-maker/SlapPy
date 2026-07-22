"""Notebook-themed live telemetry stream viewer.

The :class:`NotebookTelemetryPanel` subscribes to
:func:`pharos_engine.telemetry.subscribe` with the ``"*"`` catch-all
pattern and renders the running stream of :class:`TelemetryEvent`
records as a notebook-styled log table.

Panel layout
------------

* Title row with a washi-tape underline + a paw / ear sticker.
* Filter input — ``fnmatch`` pattern AND/OR substring (substring
  wins when the pattern contains no glob metachar so casual users
  can just type ``"physics"``).
* Three :class:`StickerButton` controls:

  - **Pause** / **Resume** — flips a local ``_paused`` flag that the
    subscriber respects so the live stream still ticks behind the
    scenes; resuming does not back-fill missed events.
  - **Clear** — drops every event currently rendered (the underlying
    ring buffer is unchanged so other consumers keep their view).
  - **Pin** — pins the currently-selected event for quick navigation
    via the *Pinned* drawer below the table.

* A :class:`WashiPanel` with a table-like list of rows:
  ``ts | name | payload preview``.  Newest event scrolls to the top so
  the user always sees the latest signal.
* A second :class:`WashiPanel` ("Pinned") that lists each pinned event
  with a "go to" button that scrolls the main log to the matching row.

Headless-safe — every DPG call is funnelled through ``_safe_dpg``.
"""
from __future__ import annotations

import fnmatch
import time
from typing import Any, Callable

from pharos_engine import telemetry
from pharos_engine._validation import (
    validate_non_negative_int,
    validate_str,
)
from pharos_engine.telemetry import TelemetryEvent
from pharos_engine.ui.widgets.doodle_separator import DoodleSeparator
from pharos_engine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from pharos_engine.ui.widgets.sticker_button import StickerButton
from pharos_engine.ui.widgets.washi_panel import WashiPanel


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

_GLOB_METACHARS: frozenset[str] = frozenset("*?[")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _payload_preview(event: TelemetryEvent, max_len: int = 60) -> str:
    """Return a short ``key=value`` preview of the event payload."""
    if not event.payload:
        return ""
    bits: list[str] = []
    for k, v in event.payload.items():
        if k == "source":
            continue
        sv = repr(v) if not isinstance(v, str) else v
        if len(sv) > 18:
            sv = sv[:15] + "..."
        bits.append(f"{k}={sv}")
        if sum(len(b) for b in bits) + 2 * len(bits) >= max_len:
            break
    out = ", ".join(bits)
    if len(out) > max_len:
        out = out[: max_len - 1] + "..."
    return out


def matches_filter(event_name: str, pattern: str) -> bool:
    """Return whether *event_name* matches *pattern*.

    Empty pattern matches everything.  Patterns containing any of the
    fnmatch metachars (``*?[``) are dispatched through
    :func:`fnmatch.fnmatchcase`; bare substrings do a case-insensitive
    substring match so casual users can type ``"physics"`` and get all
    ``physics.*`` events.
    """
    p = (pattern or "").strip()
    if not p:
        return True
    if any(c in _GLOB_METACHARS for c in p):
        return fnmatch.fnmatchcase(event_name, p)
    return p.lower() in event_name.lower()


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class NotebookTelemetryPanel:
    """Live event-stream viewer for :mod:`pharos_engine.telemetry`.

    Subscribes to the catch-all ``"*"`` pattern at :meth:`build` time
    and unsubscribes on :meth:`destroy`.  When paused, the subscriber
    is still attached but the event is dropped on the floor; resuming
    starts capturing new events again without back-filling.
    """

    TITLE = "Telemetry"
    MIN_WIDTH: int = 360
    MIN_HEIGHT: int = 240

    _TABLE_TAG = "notebook_telemetry_table"
    _FILTER_TAG = "notebook_telemetry_filter"
    _STATUS_TAG = "notebook_telemetry_status"
    _PINNED_TAG = "notebook_telemetry_pinned"
    _ROOT_TAG = "notebook_telemetry_root"

    DEFAULT_CAPACITY: int = 500

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        initial_filter: str = "",
    ) -> None:
        validate_non_negative_int(
            "capacity", "NotebookTelemetryPanel", capacity,
        )
        validate_str(
            "initial_filter", "NotebookTelemetryPanel",
            initial_filter, allow_empty=True,
        )
        self._capacity: int = int(capacity)
        self._filter: str = initial_filter
        self._paused: bool = False
        self._events: list[TelemetryEvent] = []
        self._pinned: list[TelemetryEvent] = []
        self._subscription_handle: int | None = None
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._theme = resolve_theme()
        self.call_log: list[tuple[str, Any]] = []

        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[TelemetryEvent]:
        """Return the *visible* event list (newest first, filter-respected)."""
        return [e for e in self._events if matches_filter(e.name, self._filter)]

    @property
    def pinned(self) -> list[TelemetryEvent]:
        """Return the list of pinned events."""
        return list(self._pinned)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def filter(self) -> str:
        return self._filter

    # ------------------------------------------------------------------
    # Theme listener
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        self.call_log.append(("theme_changed", None))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Subscriber lifecycle
    # ------------------------------------------------------------------

    def _on_event(self, event: TelemetryEvent) -> None:
        """Receive an event from the telemetry bus."""
        if self._paused:
            return
        # Newest first so the visual log reads "latest at top".
        self._events.insert(0, event)
        if len(self._events) > self._capacity:
            del self._events[self._capacity :]
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    def subscribe(self) -> None:
        """Attach the panel to the telemetry bus.  Idempotent."""
        if self._subscription_handle is not None:
            return
        self._subscription_handle = telemetry.subscribe("*", self._on_event)

    def unsubscribe(self) -> None:
        """Detach the panel from the telemetry bus.  Idempotent."""
        if self._subscription_handle is None:
            return
        try:
            telemetry.unsubscribe(self._subscription_handle)
        except Exception:
            pass
        self._subscription_handle = None

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    def set_filter(self, pattern: str) -> None:
        """Update the active filter and re-render."""
        validate_str("pattern", "NotebookTelemetryPanel.set_filter",
                     pattern, allow_empty=True)
        self._filter = pattern or ""
        self.call_log.append(("filter", self._filter))
        if self._built:
            self.refresh()

    def toggle_pause(self) -> bool:
        """Flip the pause flag, returning the new state."""
        self._paused = not self._paused
        self.call_log.append(("pause", self._paused))
        if self._built:
            self.refresh()
        return self._paused

    def pause(self) -> None:
        """Stop ingesting new events."""
        if not self._paused:
            self.toggle_pause()

    def resume(self) -> None:
        """Resume ingesting new events."""
        if self._paused:
            self.toggle_pause()

    def clear(self) -> None:
        """Drop every event currently rendered."""
        self._events.clear()
        self.call_log.append(("clear", None))
        if self._built:
            self.refresh()

    def pin(self, event: TelemetryEvent) -> None:
        """Pin *event* in the *Pinned* drawer for quick navigation."""
        if event in self._pinned:
            return
        self._pinned.append(event)
        self.call_log.append(("pin", event.name))
        if self._built:
            self.refresh()

    def unpin(self, event: TelemetryEvent) -> None:
        """Remove *event* from the pinned drawer (silent on miss)."""
        try:
            self._pinned.remove(event)
        except ValueError:
            return
        self.call_log.append(("unpin", event.name))
        if self._built:
            self.refresh()

    def set_capacity(self, capacity: int) -> None:
        """Resize the in-panel ring buffer."""
        validate_non_negative_int(
            "capacity", "NotebookTelemetryPanel.set_capacity", capacity,
        )
        self._capacity = int(capacity)
        if len(self._events) > self._capacity:
            del self._events[self._capacity :]
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Render the panel under *parent_tag*.

        Auto-subscribes to the telemetry bus so a freshly-built panel
        starts capturing events immediately.
        """
        dpg = _safe_dpg()
        self._parent_tag = parent_tag
        self.subscribe()

        if dpg is None:
            self._built = True
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                try:
                    dpg.add_text(self.TITLE, color=ink)
                except Exception:
                    pass
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass

                # Filter row.
                try:
                    dpg.add_input_text(
                        hint="Filter (fnmatch or substring)...",
                        tag=self._FILTER_TAG,
                        callback=self._on_filter_changed,
                        width=-1,
                    )
                except Exception:
                    pass

                # Controls row — Pause / Clear / Pin.
                try:
                    with dpg.group(horizontal=True):
                        try:
                            StickerButton(
                                label="Pause" if not self._paused else "Resume",
                                sticker_icon="fox",
                                callback=self._on_pause_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Clear",
                                sticker_icon="butterfly",
                                callback=self._on_clear_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Pin top",
                                sticker_icon="bunny",
                                callback=self._on_pin_top_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    DoodleSeparator("wavy").build(self._ROOT_TAG)
                except Exception:
                    pass

                # Status line.
                try:
                    dpg.add_text(self._format_status(), tag=self._STATUS_TAG,
                                 color=accent)
                except Exception:
                    pass

                # Main event table.
                try:
                    with dpg.group(tag=self._TABLE_TAG):
                        self._build_rows()
                except Exception:
                    self._build_rows()

                try:
                    DoodleSeparator("dotted").build(self._ROOT_TAG)
                except Exception:
                    pass

                # Pinned drawer.
                try:
                    with dpg.group(tag=self._PINNED_TAG):
                        self._build_pinned()
                except Exception:
                    self._build_pinned()
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        """Rebuild rows + status from the current state."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                try:
                    dpg.set_value(self._STATUS_TAG, self._format_status())
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._TABLE_TAG):
                for child in list(dpg.get_item_children(self._TABLE_TAG, slot=1) or []):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._TABLE_TAG):
                    self._build_rows()
        except Exception:
            try:
                self._build_rows()
            except Exception:
                pass
        try:
            if dpg.does_item_exist(self._PINNED_TAG):
                for child in list(dpg.get_item_children(self._PINNED_TAG, slot=1) or []):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._PINNED_TAG):
                    self._build_pinned()
        except Exception:
            try:
                self._build_pinned()
            except Exception:
                pass

    def destroy(self) -> None:
        """Detach from the telemetry bus + the theme registry."""
        self.unsubscribe()
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _build_rows(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        rows = self.events
        if not rows:
            try:
                dpg.add_text("(no events yet)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        for event in rows[:60]:  # cap render to keep DPG snappy
            ts = _format_timestamp(event.timestamp)
            preview = _payload_preview(event)
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(f"[{ts}]", color=accent)
                    except Exception:
                        pass
                    try:
                        dpg.add_text(event.name, color=ink)
                    except Exception:
                        pass
                    if preview:
                        try:
                            dpg.add_text(f" :: {preview}", color=ink)
                        except Exception:
                            pass
                    try:
                        dpg.add_button(
                            label="pin",
                            callback=self._make_pin_callback(event),
                        )
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(event.name)
                except Exception:
                    pass

    def _build_pinned(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._pinned:
            try:
                dpg.add_text("(nothing pinned)")
            except Exception:
                pass
            return
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        for event in self._pinned:
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(f"* {event.name}", color=accent)
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="unpin",
                            callback=self._make_unpin_callback(event),
                        )
                    except Exception:
                        pass
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_filter_changed(self, sender: Any, app_data: Any, user_data: Any) -> None:
        self.set_filter(str(app_data or ""))

    def _on_pause_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.toggle_pause()

    def _on_clear_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.clear()

    def _on_pin_top_clicked(self, *_a: Any, **_kw: Any) -> None:
        if self.events:
            self.pin(self.events[0])

    def _make_pin_callback(
        self, event: TelemetryEvent,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            self.pin(event)
        return _cb

    def _make_unpin_callback(
        self, event: TelemetryEvent,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            self.unpin(event)
        return _cb

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _format_status(self) -> str:
        state = "paused" if self._paused else "live"
        return (
            f"{state} | events: {len(self._events)} | "
            f"filter: {self._filter or '(all)'} | "
            f"pinned: {len(self._pinned)}"
        )


def _format_timestamp(ts: float) -> str:
    """Return a compact ``HH:MM:SS.mmm`` representation of *ts*."""
    try:
        # ``time.perf_counter()`` returns a monotonic clock; we present it
        # modulo a minute so the table stays scannable.
        seconds = ts % 60.0
        return f"{seconds:06.3f}"
    except Exception:
        return "?"


__all__ = [
    "NotebookTelemetryPanel",
    "matches_filter",
]
