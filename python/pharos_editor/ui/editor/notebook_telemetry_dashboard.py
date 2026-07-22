"""Diary-themed live telemetry dashboard panel.

The :class:`NotebookTelemetryDashboard` is a *dashboard*-style companion to
:class:`NotebookTelemetryPanel` (the raw event-stream viewer).  Instead of
scrolling every :class:`~pharos_engine.telemetry.TelemetryEvent`, this panel
buckets events into four synthetic views computed from event payloads:

Counters
    Any event carrying a numeric ``count`` / ``delta`` / ``value`` payload
    is aggregated into a monotonically increasing counter keyed by event
    name.  The dashboard shows the current value plus the delta accrued
    since the previous poll tick.

Gauges
    Events carrying a ``gauge`` / ``value`` payload update a gauge whose
    most-recent value is displayed alongside a tiny 60-sample sparkline
    rendered as a polyline with a small pencil-jitter offset to keep the
    diary theme.

Histograms
    Events carrying a ``bucket`` payload (or a ``histogram`` dict of
    ``{bucket_label: count}``) are aggregated into a per-name bucket map
    which is rendered as a small hand-drawn bar chart of the last window.

Perf timers
    Events carrying a ``duration_ms`` payload feed a rolling-window perf
    aggregator.  The dashboard sorts rows by mean duration descending and
    shows count / p50 / p95 / p99 / max.

Layout
------

* Diary title with a washi-tape / ``~~~~~`` underline.
* Header row: Pause/Resume, Clear, Auto-scroll toggle, Export CSV, and a
  poll-interval slider (100 ms ‥ 5000 ms).
* :class:`DoodleSeparator` between rows for the hand-drawn look.
* A tab bar switching between **Counters**, **Gauges**, **Histograms**,
  **Perf**.

Headless-safe — every DPG call is funnelled through ``_safe_dpg`` so the
panel imports + builds under a stub DPG in tests.  The
:class:`MovablePanelWindow` wrapper is optional and only reached via
:meth:`wrap_in_window`; the panel itself only requires ``build(parent_tag)``.
"""
from __future__ import annotations

import csv
import math
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Iterable

from pharos_engine import telemetry
from pharos_engine._validation import (
    validate_non_negative_int,
    validate_str,
)
from pharos_engine.telemetry import TelemetryEvent
from pharos_editor.ui.widgets.doodle_separator import DoodleSeparator
from pharos_editor.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from pharos_editor.ui.widgets.sticker_button import StickerButton


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


SPARKLINE_SAMPLE_COUNT: int = 60
"""Number of samples kept per gauge for the sparkline preview."""


TAB_NAMES: tuple[str, str, str, str] = (
    "Counters",
    "Gauges",
    "Histograms",
    "Perf",
)


POLL_INTERVAL_MIN_MS: int = 100
POLL_INTERVAL_MAX_MS: int = 5000
POLL_INTERVAL_DEFAULT_MS: int = 500


def _pencil_jitter(seed: int, amplitude: float = 0.6) -> float:
    """Return a tiny deterministic pixel offset for the pencil-jitter look.

    The seed is hashed with a small integer generator so each sparkline
    point picks a different but reproducible sub-pixel offset — that is
    what gives the polylines the hand-drawn feel without breaking the
    ordering of samples.
    """
    # Constant multiplication + xor gives a cheap PRNG-like offset that is
    # stable across runs (no ``random.random()`` — the diary theme insists
    # on determinism so screenshots stay pixel-identical).
    h = (seed * 2654435761) & 0xFFFFFFFF
    frac = (h & 0xFFFF) / 0xFFFF - 0.5
    return frac * 2.0 * amplitude


# ---------------------------------------------------------------------------
# Value extraction
# ---------------------------------------------------------------------------


def _numeric(payload: dict[str, Any], *keys: str) -> float | None:
    """Return the first numeric value in ``payload`` under any key in *keys*."""
    for k in keys:
        v = payload.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _classify_event(event: TelemetryEvent) -> str:
    """Classify *event* into one of ``counter|gauge|histogram|perf|other``.

    The classification is based on payload keys — telemetry events are
    intentionally schema-free so we sniff for the well-known payload keys
    the dashboard understands.  Events that miss every key fall through
    to ``"other"`` and are ignored by every tab.
    """
    p = event.payload
    if "duration_ms" in p or "perf" in p:
        return "perf"
    if "bucket" in p or "histogram" in p:
        return "histogram"
    if "gauge" in p:
        return "gauge"
    if "count" in p or "delta" in p or "counter" in p:
        return "counter"
    if "value" in p and isinstance(p["value"], (int, float)) and not isinstance(p["value"], bool):
        # Bare ``value`` payloads default to gauge — most useful default.
        return "gauge"
    return "other"


# ---------------------------------------------------------------------------
# Rolling perf window
# ---------------------------------------------------------------------------


class _PerfSeries:
    """Rolling window of ``duration_ms`` samples for one timer name.

    Kept small (``maxlen=256``) so p95 / p99 is representative of the recent
    tail without leaking memory.  Percentiles are computed via a sorted
    snapshot on demand — cheap for a 256-sample window and doesn't need a
    heavy statistics dependency.
    """

    __slots__ = ("samples", "count")

    def __init__(self) -> None:
        self.samples: Deque[float] = deque(maxlen=256)
        # Distinct from ``len(samples)`` — this is the lifetime count,
        # useful when the user sorts the perf tab by call count.
        self.count: int = 0

    def push(self, ms: float) -> None:
        self.samples.append(float(ms))
        self.count += 1

    def stats(self) -> dict[str, float]:
        if not self.samples:
            return {
                "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0,
            }
        arr = sorted(self.samples)
        n = len(arr)
        return {
            "mean": sum(arr) / n,
            "p50": arr[int(n * 0.50) - 0 if n * 0.50 >= 1 else 0],
            "p95": arr[min(n - 1, int(math.ceil(n * 0.95)) - 1)],
            "p99": arr[min(n - 1, int(math.ceil(n * 0.99)) - 1)],
            "max": arr[-1],
        }


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class NotebookTelemetryDashboard:
    """Live telemetry dashboard — counters / gauges / histograms / perf.

    Parameters
    ----------
    poll_interval_ms:
        How often :meth:`tick` may refresh the visible tab (in ms).  Direct
        subscriber updates are always processed; the interval only rate
        limits the DPG refresh so a burst of events doesn't hammer the
        renderer.  Clamped to ``[100, 5000]``.
    auto_scroll:
        Whether tables should scroll to the newest row when refreshed.
    """

    TITLE = "Telemetry Dashboard"
    MIN_WIDTH: int = 420
    MIN_HEIGHT: int = 320

    _ROOT_TAG = "notebook_telemetry_dashboard_root"
    _STATUS_TAG = "notebook_telemetry_dashboard_status"
    _TAB_BODY_TAG = "notebook_telemetry_dashboard_body"

    def __init__(
        self,
        *,
        poll_interval_ms: int = POLL_INTERVAL_DEFAULT_MS,
        auto_scroll: bool = True,
    ) -> None:
        # ── Validation --------------------------------------------------
        validate_non_negative_int(
            "poll_interval_ms", "NotebookTelemetryDashboard", poll_interval_ms,
        )
        if not isinstance(auto_scroll, bool):
            raise TypeError(
                "NotebookTelemetryDashboard: auto_scroll must be a bool; "
                f"got {type(auto_scroll).__name__}"
            )

        # ── State -------------------------------------------------------
        self._poll_interval_ms: int = self._clamp_poll(poll_interval_ms)
        self._auto_scroll: bool = bool(auto_scroll)
        self._paused: bool = False
        self._active_tab: str = TAB_NAMES[0]

        # Counters — {name: (current, last_poll_value)}
        self._counters: dict[str, list[float]] = {}
        # Gauges — {name: (current, deque of last 60 samples)}
        self._gauges: dict[str, tuple[float, Deque[float]]] = {}
        # Histograms — {name: {bucket_label: count}}
        self._histograms: dict[str, dict[str, int]] = {}
        # Perf — {name: _PerfSeries}
        self._perf: dict[str, _PerfSeries] = {}

        # Book-keeping for :meth:`tick` — accumulated time since last flush.
        self._elapsed_ms: float = 0.0
        # Timestamp of the last refresh (perf_counter seconds).
        self._last_refresh_at: float = 0.0

        # Subscription handle.
        self._subscription_handle: int | None = None

        # Theme.
        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        # DPG bookkeeping.
        self._built: bool = False
        self._parent_tag: str | int | None = None
        # Call log — mirrors NotebookTelemetryPanel for test assertions.
        self.call_log: list[tuple[str, Any]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def auto_scroll(self) -> bool:
        return self._auto_scroll

    @property
    def poll_interval_ms(self) -> int:
        return self._poll_interval_ms

    @property
    def active_tab(self) -> str:
        return self._active_tab

    @property
    def counters(self) -> dict[str, float]:
        """Snapshot of the current counter values (not the delta)."""
        return {k: v[0] for k, v in self._counters.items()}

    @property
    def gauges(self) -> dict[str, float]:
        """Snapshot of the current gauge values."""
        return {k: v[0] for k, v in self._gauges.items()}

    @property
    def histograms(self) -> dict[str, dict[str, int]]:
        """Snapshot of the current histogram bucket counts."""
        return {k: dict(v) for k, v in self._histograms.items()}

    @property
    def perf(self) -> dict[str, dict[str, float]]:
        """Snapshot of ``{name: stats}`` for every perf timer."""
        return {k: v.stats() for k, v in self._perf.items()}

    def gauge_samples(self, name: str) -> list[float]:
        """Return the sparkline sample buffer for the named gauge."""
        entry = self._gauges.get(name)
        if entry is None:
            return []
        return list(entry[1])

    def perf_series(self, name: str) -> _PerfSeries | None:
        return self._perf.get(name)

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
    # Subscription lifecycle
    # ------------------------------------------------------------------

    def subscribe_to_telemetry(self) -> None:
        """Attach the dashboard to the telemetry bus.  Idempotent."""
        if self._subscription_handle is not None:
            return
        self._subscription_handle = telemetry.subscribe("*", self._on_event)

    # Alias so callers can spell the shorter :func:`subscribe` too.
    subscribe = subscribe_to_telemetry

    def unsubscribe(self) -> None:
        """Detach from the telemetry bus.  Idempotent."""
        if self._subscription_handle is None:
            return
        try:
            telemetry.unsubscribe(self._subscription_handle)
        except Exception:
            pass
        self._subscription_handle = None

    def _on_event(self, event: TelemetryEvent) -> None:
        """Aggregate *event* into the matching bucket."""
        if self._paused:
            return
        kind = _classify_event(event)
        if kind == "counter":
            delta = _numeric(event.payload, "delta", "count", "counter", "value")
            if delta is None:
                delta = 1.0
            cur, _last = self._counters.get(event.name, [0.0, 0.0])
            self._counters[event.name] = [cur + delta, _last]
        elif kind == "gauge":
            value = _numeric(event.payload, "gauge", "value")
            if value is None:
                return
            cur_entry = self._gauges.get(event.name)
            if cur_entry is None:
                dq: Deque[float] = deque(maxlen=SPARKLINE_SAMPLE_COUNT)
            else:
                dq = cur_entry[1]
            dq.append(value)
            self._gauges[event.name] = (value, dq)
        elif kind == "histogram":
            bucket_map = self._histograms.setdefault(event.name, {})
            if "histogram" in event.payload and isinstance(
                event.payload["histogram"], dict,
            ):
                for label, cnt in event.payload["histogram"].items():
                    if isinstance(cnt, (int, float)) and not isinstance(cnt, bool):
                        bucket_map[str(label)] = int(
                            bucket_map.get(str(label), 0) + int(cnt),
                        )
            elif "bucket" in event.payload:
                label = str(event.payload["bucket"])
                bucket_map[label] = int(bucket_map.get(label, 0) + 1)
        elif kind == "perf":
            duration = _numeric(event.payload, "duration_ms", "perf")
            if duration is None:
                return
            series = self._perf.get(event.name)
            if series is None:
                series = _PerfSeries()
                self._perf[event.name] = series
            series.push(duration)
        # ``other`` — silently dropped.

    # ------------------------------------------------------------------
    # Poll interval / auto-scroll / pause / clear
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_poll(ms: int) -> int:
        return max(POLL_INTERVAL_MIN_MS, min(POLL_INTERVAL_MAX_MS, int(ms)))

    def set_poll_interval_ms(self, ms: int) -> int:
        """Update the polling interval; returns the clamped value."""
        validate_non_negative_int(
            "ms", "NotebookTelemetryDashboard.set_poll_interval_ms", ms,
        )
        self._poll_interval_ms = self._clamp_poll(ms)
        self.call_log.append(("poll_interval", self._poll_interval_ms))
        return self._poll_interval_ms

    def set_auto_scroll(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError(
                "NotebookTelemetryDashboard.set_auto_scroll: enabled must be "
                f"bool; got {type(enabled).__name__}"
            )
        self._auto_scroll = enabled
        self.call_log.append(("auto_scroll", enabled))

    def toggle_pause(self) -> bool:
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

    def clear(self) -> None:
        """Drop every counter / gauge / histogram / perf entry."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._perf.clear()
        self.call_log.append(("clear", None))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    def set_active_tab(self, name: str) -> None:
        validate_str(
            "name", "NotebookTelemetryDashboard.set_active_tab", name,
            allow_empty=False,
        )
        if name not in TAB_NAMES:
            raise ValueError(
                "NotebookTelemetryDashboard.set_active_tab: name must be one "
                f"of {TAB_NAMES}; got {name!r}"
            )
        self._active_tab = name
        self.call_log.append(("active_tab", name))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Poll tick
    # ------------------------------------------------------------------

    def tick(self, dt_seconds: float) -> bool:
        """Advance the internal poll clock and refresh when needed.

        Returns ``True`` iff the dashboard actually refreshed on this
        tick.  When :attr:`paused` is set, this is always ``False`` — the
        panel keeps state but doesn't touch DPG.
        """
        if not isinstance(dt_seconds, (int, float)) or isinstance(dt_seconds, bool):
            raise TypeError(
                "NotebookTelemetryDashboard.tick: dt_seconds must be a number; "
                f"got {type(dt_seconds).__name__}"
            )
        if dt_seconds < 0:
            raise ValueError(
                "NotebookTelemetryDashboard.tick: dt_seconds must be >= 0; "
                f"got {dt_seconds!r}"
            )
        if self._paused:
            return False
        self._elapsed_ms += float(dt_seconds) * 1000.0
        if self._elapsed_ms < self._poll_interval_ms:
            return False
        self._elapsed_ms = 0.0
        self._last_refresh_at = time.perf_counter()
        # Freeze counter deltas.
        for name, (cur, _last) in list(self._counters.items()):
            self._counters[name] = [cur, cur]
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_csv(self, path: str | Path) -> Path:
        """Write the current counter + gauge snapshot to *path* as CSV.

        The CSV has two columns — ``kind`` (``counter`` / ``gauge``) and
        ``name`` — plus a ``value`` column.  Returns the resolved
        :class:`Path` so callers can log where the file landed.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["kind", "name", "value"])
            for name, (cur, _last) in sorted(self._counters.items()):
                writer.writerow(["counter", name, cur])
            for name, (cur, _samples) in sorted(self._gauges.items()):
                writer.writerow(["gauge", name, cur])
        self.call_log.append(("export_csv", str(p)))
        return p

    # ------------------------------------------------------------------
    # Build / refresh / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Render the dashboard under *parent_tag*.

        Auto-subscribes to the telemetry bus.
        """
        dpg = _safe_dpg()
        self._parent_tag = parent_tag
        self.subscribe_to_telemetry()

        if dpg is None:
            self._built = True
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                try:
                    dpg.add_text(self.TITLE, color=ink)
                except Exception:
                    pass
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass

                # Header row.
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
                            dpg.add_checkbox(
                                label="Auto-scroll",
                                default_value=self._auto_scroll,
                                callback=self._on_auto_scroll_changed,
                            )
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Export CSV",
                                sticker_icon="bunny",
                                callback=self._on_export_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            dpg.add_slider_int(
                                label="poll ms",
                                default_value=self._poll_interval_ms,
                                min_value=POLL_INTERVAL_MIN_MS,
                                max_value=POLL_INTERVAL_MAX_MS,
                                callback=self._on_poll_slider_changed,
                                width=140,
                            )
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
                    dpg.add_text(
                        self._format_status(),
                        tag=self._STATUS_TAG,
                        color=accent,
                    )
                except Exception:
                    pass

                # Tab bar.
                try:
                    with dpg.tab_bar(callback=self._on_tab_changed):
                        for tab_name in TAB_NAMES:
                            try:
                                with dpg.tab(label=tab_name):
                                    pass
                            except Exception:
                                pass
                except Exception:
                    pass

                # Body — refreshed on every tick.
                try:
                    with dpg.group(tag=self._TAB_BODY_TAG):
                        self._build_active_tab_body()
                except Exception:
                    self._build_active_tab_body()

        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        """Rebuild the currently-visible tab + status line."""
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
            if dpg.does_item_exist(self._TAB_BODY_TAG):
                for child in list(dpg.get_item_children(self._TAB_BODY_TAG, slot=1) or []):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._TAB_BODY_TAG):
                    self._build_active_tab_body()
        except Exception:
            try:
                self._build_active_tab_body()
            except Exception:
                pass

    def destroy(self) -> None:
        """Detach from telemetry + the theme registry."""
        self.unsubscribe()
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ------------------------------------------------------------------
    # MovablePanelWindow helper
    # ------------------------------------------------------------------

    def wrap_in_window(self, **kwargs: Any) -> Any:
        """Return a :class:`MovablePanelWindow` around this dashboard."""
        from pharos_editor.ui.editor.movable_panel import MovablePanelWindow
        return MovablePanelWindow(self, title=self.TITLE, **kwargs)

    # ------------------------------------------------------------------
    # Tab body rendering
    # ------------------------------------------------------------------

    def _build_active_tab_body(self) -> None:
        dispatch: dict[str, Callable[[], None]] = {
            "Counters":   self._build_counters_tab,
            "Gauges":     self._build_gauges_tab,
            "Histograms": self._build_histograms_tab,
            "Perf":       self._build_perf_tab,
        }
        try:
            dispatch[self._active_tab]()
        except KeyError:
            self._build_counters_tab()

    # ---- Counters ----------------------------------------------------

    def _build_counters_tab(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._counters:
            try:
                dpg.add_text("(no counters yet)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        for name in sorted(self._counters):
            cur, last = self._counters[name]
            delta = cur - last
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(name, color=ink)
                    except Exception:
                        pass
                    try:
                        dpg.add_text(f" = {cur:.3g}", color=ink)
                    except Exception:
                        pass
                    try:
                        dpg.add_text(
                            f"  (+{delta:.3g})" if delta >= 0
                            else f"  ({delta:.3g})",
                            color=accent,
                        )
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(f"{name} = {cur:.3g}")
                except Exception:
                    pass
            # Hand-drawn separator between rows for the diary look.
            try:
                DoodleSeparator("dotted").build(self._TAB_BODY_TAG)
            except Exception:
                pass

    # ---- Gauges ------------------------------------------------------

    def _build_gauges_tab(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._gauges:
            try:
                dpg.add_text("(no gauges yet)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        for name in sorted(self._gauges):
            cur, samples = self._gauges[name]
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(name, color=ink)
                    except Exception:
                        pass
                    try:
                        dpg.add_text(f" = {cur:.3g}", color=ink)
                    except Exception:
                        pass
                    try:
                        drawlist = dpg.add_drawlist(width=180, height=32)
                        self._draw_sparkline(dpg, drawlist, list(samples))
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(f"{name} = {cur:.3g}")
                except Exception:
                    pass
            try:
                DoodleSeparator("dotted").build(self._TAB_BODY_TAG)
            except Exception:
                pass

    def _draw_sparkline(
        self, dpg: Any, canvas_tag: Any, samples: list[float],
    ) -> None:
        """Draw *samples* as a jittered polyline on *canvas_tag*."""
        if len(samples) < 2:
            return
        w = 180.0
        h = 32.0
        lo = min(samples)
        hi = max(samples)
        span = hi - lo
        if span < 1e-9:
            span = 1.0
        n = len(samples)
        # Scale x to [0, w] and y to [h, 0] (top = high value).
        pts: list[tuple[float, float]] = []
        for i, v in enumerate(samples):
            x = i * (w / max(1, n - 1))
            y = h - ((v - lo) / span) * h
            # Pencil jitter — tiny sub-pixel offset per point.
            jx = _pencil_jitter(i * 7 + 1, amplitude=0.4)
            jy = _pencil_jitter(i * 11 + 3, amplitude=0.4)
            pts.append((x + jx, y + jy))
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        try:
            dpg.draw_polyline(
                points=pts, color=ink, thickness=1.0, parent=canvas_tag,
            )
        except Exception:
            # Fall back to draw_line between consecutive points.
            for a, b in zip(pts, pts[1:]):
                try:
                    dpg.draw_line(
                        p1=a, p2=b, color=ink, thickness=1.0,
                        parent=canvas_tag,
                    )
                except Exception:
                    pass

    # ---- Histograms --------------------------------------------------

    def _build_histograms_tab(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._histograms:
            try:
                dpg.add_text("(no histograms yet)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        for name in sorted(self._histograms):
            buckets = self._histograms[name]
            try:
                dpg.add_text(name, color=ink)
            except Exception:
                pass
            if not buckets:
                try:
                    dpg.add_text("  (empty)")
                except Exception:
                    pass
                continue
            total = max(1, sum(buckets.values()))
            for label in sorted(buckets):
                cnt = buckets[label]
                # Hand-drawn ASCII bar for the diary look — 24 chars max.
                bar_len = int(round(24.0 * cnt / total))
                bar = "#" * max(1, bar_len)
                try:
                    with dpg.group(horizontal=True):
                        try:
                            dpg.add_text(f"  {label:>10}", color=ink)
                        except Exception:
                            pass
                        try:
                            dpg.add_text(f" {bar} {cnt}", color=accent)
                        except Exception:
                            pass
                except Exception:
                    try:
                        dpg.add_text(f"  {label} {bar} {cnt}")
                    except Exception:
                        pass
            try:
                DoodleSeparator("dotted").build(self._TAB_BODY_TAG)
            except Exception:
                pass

    # ---- Perf --------------------------------------------------------

    def _build_perf_tab(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._perf:
            try:
                dpg.add_text("(no perf timers yet)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        # Sort by mean duration descending.
        entries = sorted(
            self._perf.items(),
            key=lambda kv: kv[1].stats()["mean"],
            reverse=True,
        )
        try:
            dpg.add_text(
                "name              count   p50    p95    p99    max",
                color=accent,
            )
        except Exception:
            pass
        for name, series in entries:
            s = series.stats()
            row = (
                f"{name[:16]:<16}  {series.count:>5}   "
                f"{s['p50']:>5.2f}  {s['p95']:>5.2f}  "
                f"{s['p99']:>5.2f}  {s['max']:>5.2f}"
            )
            try:
                dpg.add_text(row, color=ink)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_pause_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.toggle_pause()

    def _on_clear_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.clear()

    def _on_auto_scroll_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        self.set_auto_scroll(bool(app_data))

    def _on_export_clicked(self, *_a: Any, **_kw: Any) -> None:
        # Default target — the CWD.  Callers who need a specific path
        # should invoke :meth:`export_csv` directly.
        try:
            self.export_csv(Path.cwd() / "telemetry_snapshot.csv")
        except Exception:
            pass

    def _on_poll_slider_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        try:
            self.set_poll_interval_ms(int(app_data))
        except (TypeError, ValueError):
            pass

    def _on_tab_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        # DPG passes the tab item id; the label is stored on the item.
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            label = dpg.get_item_label(app_data)
        except Exception:
            return
        if isinstance(label, str) and label in TAB_NAMES:
            self.set_active_tab(label)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _format_status(self) -> str:
        state = "paused" if self._paused else "live"
        return (
            f"{state} | counters: {len(self._counters)} | "
            f"gauges: {len(self._gauges)} | "
            f"histograms: {len(self._histograms)} | "
            f"perf: {len(self._perf)} | "
            f"poll: {self._poll_interval_ms} ms"
        )


__all__ = [
    "NotebookTelemetryDashboard",
    "POLL_INTERVAL_DEFAULT_MS",
    "POLL_INTERVAL_MAX_MS",
    "POLL_INTERVAL_MIN_MS",
    "SPARKLINE_SAMPLE_COUNT",
    "TAB_NAMES",
]
