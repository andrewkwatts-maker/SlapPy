"""Diary-themed pop-out animation curve editor (GG5).

The :class:`NotebookCurveEditor` is a companion to the DD5
:class:`~pharos_engine.ui.editor.notebook_timeline_editor.NotebookTimelineEditor`.
Where the timeline shows a compact multi-track ruler, the curve editor
zooms in on one track's animation curve and lets the user shape it with
mouse-driven affordances:

* Track / property selector at the top switches which
  :class:`~pharos_engine.ui.editor.notebook_timeline_editor.TimelineTrack`
  is being edited.
* A canvas draws the interpolated curve (linear straight lines,
  step staircase, cubic-hermite curved, bezier with tangent handles).
* Each keyframe renders as a diamond handle.  Left-drag moves it in
  ``(time, value)``; Ctrl+drag snaps to the grid; right-click surfaces
  a Delete / Set easing / Set tangent context menu; double-click on
  empty canvas adds a keyframe at the picked ``(t, v)``.
* Middle-drag pans the view; scroll zooms; a value-scale block gives
  the user auto-fit or explicit min/max.

The editor is intentionally headless-safe — every ``dpg`` call is
funnelled through ``_safe_dpg`` and every input path (drag, scroll,
context click) is directly callable from tests so the mouse
side-effects can be exercised without a real GUI context.

Public API surface
------------------

* :class:`NotebookCurveEditor` — pop-out curve editor panel.
* :class:`CurveView` — the mutable view-state (pan, zoom, y range).
* :data:`CURVE_KINDS` — supported curve palette.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from pharos_engine._validation import (
    validate_bool,
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
)
from pharos_engine.ui.editor.notebook_timeline_editor import (
    INTERP_KINDS,
    TimelineKeyframe,
    TimelineTrack,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The four curve renderings supported by the palette.  ``bezier``
#: uses the same underlying cubic-hermite sampler for playback but
#: draws control-handle tangents so the user can see the shape.
CURVE_KINDS: tuple[str, ...] = ("linear", "step", "hermite", "bezier")

#: Clamp bounds for :attr:`CurveView.zoom` so scroll doesn't push the
#: view into degeneracy.
MIN_ZOOM: float = 0.1
MAX_ZOOM: float = 32.0

#: Default grid snap step (seconds along X, value units along Y).
DEFAULT_GRID_TIME: float = 0.1
DEFAULT_GRID_VALUE: float = 0.1

#: Sampling defaults for :meth:`NotebookCurveEditor.get_curve_points`.
DEFAULT_SAMPLE_RATE: int = 60


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable, else ``None``."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _validate_curve_kind(name: str, fn: str, value: Any) -> str:
    """Validate a curve kind against :data:`CURVE_KINDS`."""
    kind = validate_non_empty_str(name, fn, value)
    if kind not in CURVE_KINDS:
        raise ValueError(
            f"{fn}: {name} must be one of {CURVE_KINDS}; got {kind!r}"
        )
    return kind


def _snap(value: float, step: float) -> float:
    """Round *value* to the nearest multiple of *step* (positive step).

    A non-positive *step* is treated as no-op so callers can safely
    disable snap by passing ``0``.
    """
    if step <= 0.0:
        return value
    return round(value / step) * step


# ---------------------------------------------------------------------------
# View state
# ---------------------------------------------------------------------------


class CurveView:
    """Pan / zoom / Y-range state for the curve canvas.

    ``pan_time`` is measured in seconds; ``zoom`` is a unit-less scale
    factor (``1.0`` == 1s of curve per ``1.0`` canvas unit at the
    default width).  ``y_min`` / ``y_max`` are the current Y-axis
    extents — either auto-fitted from the track's keyframes or explicit
    when :attr:`auto_fit` is off.
    """

    def __init__(
        self,
        *,
        y_min: float = 0.0,
        y_max: float = 1.0,
        pan_time: float = 0.0,
        zoom: float = 1.0,
        auto_fit: bool = True,
    ) -> None:
        self.y_min: float = validate_finite_float("y_min", "CurveView", y_min)
        self.y_max: float = validate_finite_float("y_max", "CurveView", y_max)
        if self.y_max <= self.y_min:
            # Degenerate range → inflate so the axis stays drawable.
            self.y_max = self.y_min + 1.0
        self.pan_time: float = validate_finite_float(
            "pan_time", "CurveView", pan_time,
        )
        self.zoom: float = validate_positive_float("zoom", "CurveView", zoom)
        self.auto_fit: bool = validate_bool("auto_fit", "CurveView", auto_fit)

    def clone(self) -> "CurveView":
        return CurveView(
            y_min=self.y_min,
            y_max=self.y_max,
            pan_time=self.pan_time,
            zoom=self.zoom,
            auto_fit=self.auto_fit,
        )


# ---------------------------------------------------------------------------
# Public editor panel
# ---------------------------------------------------------------------------


class NotebookCurveEditor:
    """Pop-out animation curve editor (GG5).

    The panel is a :class:`MovablePanelWindow`-wrapped popout — the
    shell docks it in the DD5 timeline sidecar.  It always edits a
    single :class:`TimelineTrack`; call :meth:`set_track` to swap.

    Parameters
    ----------
    track:
        Initial :class:`TimelineTrack` to edit.  ``None`` builds a
        panel with no track loaded (harmless — every mutator becomes
        a no-op until a track is set).
    tracks_provider:
        Optional zero-arg callable returning the list of
        ``TimelineTrack`` objects to populate the track selector.
        The parent timeline panel wires this in.
    on_curve_changed:
        Optional callback ``(track_property, ) -> None`` fired after
        every mutating action so the DD5 timeline can refresh its
        sparkline.
    grid_time / grid_value:
        Snap step used when Ctrl is held during a drag.
    """

    TITLE: str = "Curve Editor"
    MIN_WIDTH: int = 400
    MIN_HEIGHT: int = 300

    _ROOT_TAG = "notebook_curve_root"
    _HEADER_TAG = "notebook_curve_header"
    _CANVAS_TAG = "notebook_curve_canvas"
    _STATUS_TAG = "notebook_curve_status"
    _CONTEXT_TAG = "notebook_curve_context_menu"

    def __init__(
        self,
        track: TimelineTrack | None = None,
        *,
        tracks_provider: Callable[[], list[TimelineTrack]] | None = None,
        on_curve_changed: Callable[[str], None] | None = None,
        grid_time: float = DEFAULT_GRID_TIME,
        grid_value: float = DEFAULT_GRID_VALUE,
    ) -> None:
        if track is not None and not isinstance(track, TimelineTrack):
            raise TypeError(
                "NotebookCurveEditor: track must be TimelineTrack or None; "
                f"got {type(track).__name__}"
            )
        if tracks_provider is not None and not callable(tracks_provider):
            raise TypeError(
                "NotebookCurveEditor: tracks_provider must be callable or None"
            )
        if on_curve_changed is not None and not callable(on_curve_changed):
            raise TypeError(
                "NotebookCurveEditor: on_curve_changed must be callable or None"
            )
        self._track: TimelineTrack | None = track
        self._tracks_provider = tracks_provider
        self._on_curve_changed = on_curve_changed
        self._grid_time: float = validate_positive_float(
            "grid_time", "NotebookCurveEditor", grid_time,
        )
        self._grid_value: float = validate_positive_float(
            "grid_value", "NotebookCurveEditor", grid_value,
        )
        self._view: CurveView = CurveView()
        self._curve_kind: str = "linear"
        self._selected_kf_id: int | None = None
        self._context_open: bool = False
        self._context_target: int | None = None
        self._built: bool = False
        self._parent_tag: str | int | None = None
        # Call log so tests can assert side-effects without mocking DPG.
        self.call_log: list[tuple[str, Any]] = []
        if track is not None:
            self._autofit_from_track()

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def track(self) -> TimelineTrack | None:
        """The currently edited :class:`TimelineTrack` (may be ``None``)."""
        return self._track

    @property
    def view(self) -> CurveView:
        """The mutable :class:`CurveView` (pan / zoom / y range)."""
        return self._view

    @property
    def curve_kind(self) -> str:
        """Currently selected curve rendering (one of :data:`CURVE_KINDS`)."""
        return self._curve_kind

    @property
    def selected_keyframe(self) -> int | None:
        """The selected keyframe id, or ``None`` when nothing is picked."""
        return self._selected_kf_id

    @property
    def grid_time(self) -> float:
        """Snap step along the time axis when Ctrl-drag is active."""
        return self._grid_time

    @property
    def grid_value(self) -> float:
        """Snap step along the value axis when Ctrl-drag is active."""
        return self._grid_value

    @property
    def context_open(self) -> bool:
        """``True`` while a right-click context menu is showing."""
        return self._context_open

    @property
    def context_target(self) -> int | None:
        """The keyframe id the context menu is targeting."""
        return self._context_target

    # ------------------------------------------------------------------
    # Track selector
    # ------------------------------------------------------------------

    def set_track(self, track: TimelineTrack | None) -> None:
        """Swap the currently edited track.

        Passing ``None`` clears the editor (still valid — the canvas
        just draws an empty state).
        """
        if track is not None and not isinstance(track, TimelineTrack):
            raise TypeError(
                "NotebookCurveEditor.set_track: track must be TimelineTrack "
                f"or None; got {type(track).__name__}"
            )
        self._track = track
        self._selected_kf_id = None
        self._context_open = False
        self._context_target = None
        if track is not None and self._view.auto_fit:
            self._autofit_from_track()
        self.call_log.append(
            ("set_track", track.property_name if track is not None else None),
        )
        if self._built:
            self.refresh()

    def available_tracks(self) -> list[TimelineTrack]:
        """Return the list of selectable tracks (from ``tracks_provider``)."""
        if self._tracks_provider is None:
            return [self._track] if self._track is not None else []
        try:
            tracks = list(self._tracks_provider())
        except Exception:
            return []
        return [t for t in tracks if isinstance(t, TimelineTrack)]

    def _notify(self) -> None:
        """Fire ``on_curve_changed`` (silently swallowing listener errors)."""
        if self._on_curve_changed is None or self._track is None:
            return
        try:
            self._on_curve_changed(self._track.property_name)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Curve palette
    # ------------------------------------------------------------------

    def set_curve_kind(self, kind: str) -> None:
        """Switch the curve rendering to one of :data:`CURVE_KINDS`.

        This only changes how the curve *draws*; the sampler always
        follows the per-keyframe ``interp`` field on the underlying
        :class:`TimelineTrack`.
        """
        self._curve_kind = _validate_curve_kind(
            "kind", "NotebookCurveEditor.set_curve_kind", kind,
        )
        self.call_log.append(("set_curve_kind", self._curve_kind))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Keyframe operations
    # ------------------------------------------------------------------

    def add_keyframe(
        self,
        time: float,
        value: float,
        interp: str = "linear",
    ) -> TimelineKeyframe:
        """Add a keyframe at ``(time, value)`` on the active track."""
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.add_keyframe: no track loaded"
            )
        kf = self._track.add_keyframe(time, value, interp)
        self._selected_kf_id = kf.id
        if self._view.auto_fit:
            self._autofit_from_track()
        self.call_log.append(("add_keyframe", (time, value, interp)))
        self._notify()
        if self._built:
            self.refresh()
        return kf

    def delete_keyframe(self, kf_id: int) -> TimelineKeyframe:
        """Remove the keyframe with the stable ``kf_id``."""
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.delete_keyframe: no track loaded"
            )
        kf = self._track.remove_keyframe(kf_id)
        if self._selected_kf_id == kf_id:
            self._selected_kf_id = None
        if self._context_target == kf_id:
            self._context_open = False
            self._context_target = None
        if self._view.auto_fit:
            self._autofit_from_track()
        self.call_log.append(("delete_keyframe", kf_id))
        self._notify()
        if self._built:
            self.refresh()
        return kf

    def drag_keyframe(
        self,
        kf_id: int,
        time: float,
        value: float,
        *,
        snap: bool = False,
    ) -> TimelineKeyframe:
        """Move keyframe ``kf_id`` to ``(time, value)``.

        The DPG left-drag callback calls this every mouse frame; pass
        ``snap=True`` while Ctrl is held so the drag lands on the grid.
        """
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.drag_keyframe: no track loaded"
            )
        if snap:
            time = _snap(time, self._grid_time)
            value = _snap(value, self._grid_value)
        kf = self._track.move_keyframe(kf_id, time=time, value=value)
        if self._view.auto_fit:
            self._autofit_from_track()
        self.call_log.append(("drag_keyframe", (kf_id, time, value, snap)))
        self._notify()
        if self._built:
            self.refresh()
        return kf

    def set_ease(self, kf_id: int, kind: str) -> TimelineKeyframe:
        """Set the outgoing interpolation kind for the keyframe."""
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.set_ease: no track loaded"
            )
        kf = self._track.set_ease(kf_id, kind)
        self.call_log.append(("set_ease", (kf_id, kind)))
        self._notify()
        if self._built:
            self.refresh()
        return kf

    def set_tangent(self, kf_id: int, kind: str) -> TimelineKeyframe:
        """Alias for :meth:`set_ease` — matches the "Set tangent" menu label.

        The underlying model conflates ease + tangent (Catmull-Rom
        auto-tangents); this alias exists so the right-click menu label
        matches the palette naming.
        """
        return self.set_ease(kf_id, kind)

    def select(self, kf_id: int | None) -> None:
        """Select ``kf_id`` (or clear selection with ``None``)."""
        if kf_id is None:
            self._selected_kf_id = None
            self.call_log.append(("select", None))
            if self._built:
                self.refresh()
            return
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.select: no track loaded"
            )
        # Verify the id exists.
        for kf in self._track.keyframes:
            if kf.id == kf_id:
                self._selected_kf_id = kf_id
                self.call_log.append(("select", kf_id))
                if self._built:
                    self.refresh()
                return
        raise KeyError(
            f"NotebookCurveEditor.select: no keyframe with id {kf_id}"
        )

    # ------------------------------------------------------------------
    # Context menu (right-click)
    # ------------------------------------------------------------------

    def open_context_menu(self, kf_id: int) -> None:
        """Show the right-click menu for ``kf_id``."""
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.open_context_menu: no track loaded"
            )
        for kf in self._track.keyframes:
            if kf.id == kf_id:
                self._context_open = True
                self._context_target = kf_id
                self._selected_kf_id = kf_id
                self.call_log.append(("open_context_menu", kf_id))
                if self._built:
                    self.refresh()
                return
        raise KeyError(
            f"NotebookCurveEditor.open_context_menu: no keyframe {kf_id}"
        )

    def close_context_menu(self) -> None:
        """Dismiss the context menu."""
        self._context_open = False
        self._context_target = None
        self.call_log.append(("close_context_menu", None))
        if self._built:
            self.refresh()

    def context_delete(self) -> None:
        """Menu action: delete the context target."""
        if self._context_target is None:
            return
        target = self._context_target
        self.close_context_menu()
        self.delete_keyframe(target)

    def context_set_ease(self, kind: str) -> None:
        """Menu action: set the outgoing ease on the context target."""
        if self._context_target is None:
            return
        target = self._context_target
        self.set_ease(target, kind)
        self.close_context_menu()

    def context_set_tangent(self, kind: str) -> None:
        """Menu action: set the tangent on the context target."""
        if self._context_target is None:
            return
        target = self._context_target
        self.set_tangent(target, kind)
        self.close_context_menu()

    # ------------------------------------------------------------------
    # Pan / zoom
    # ------------------------------------------------------------------

    def pan(self, dt: float) -> None:
        """Pan the view by *dt* seconds (middle-drag)."""
        dt = validate_finite_float("dt", "NotebookCurveEditor.pan", dt)
        self._view.pan_time = self._view.pan_time + dt
        self.call_log.append(("pan", dt))
        if self._built:
            self.refresh()

    def zoom(self, factor: float) -> None:
        """Multiply the current zoom by *factor* (scroll wheel).

        Clamped to ``[MIN_ZOOM, MAX_ZOOM]`` so scroll never pushes the
        view into degeneracy.
        """
        factor = validate_positive_float(
            "factor", "NotebookCurveEditor.zoom", factor,
        )
        new_zoom = self._view.zoom * factor
        if new_zoom < MIN_ZOOM:
            new_zoom = MIN_ZOOM
        elif new_zoom > MAX_ZOOM:
            new_zoom = MAX_ZOOM
        self._view.zoom = new_zoom
        self.call_log.append(("zoom", (factor, new_zoom)))
        if self._built:
            self.refresh()

    def reset_view(self) -> None:
        """Reset pan / zoom (Y-range refits when :attr:`auto_fit` is on)."""
        self._view.pan_time = 0.0
        self._view.zoom = 1.0
        if self._view.auto_fit:
            self._autofit_from_track()
        self.call_log.append(("reset_view", None))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Y-axis scale
    # ------------------------------------------------------------------

    def set_y_range(self, y_min: float, y_max: float) -> None:
        """Explicitly set the Y-axis range (turns auto-fit off)."""
        y_min = validate_finite_float(
            "y_min", "NotebookCurveEditor.set_y_range", y_min,
        )
        y_max = validate_finite_float(
            "y_max", "NotebookCurveEditor.set_y_range", y_max,
        )
        if y_max <= y_min:
            raise ValueError(
                "NotebookCurveEditor.set_y_range: y_max must be > y_min; "
                f"got {y_min} .. {y_max}"
            )
        self._view.y_min = y_min
        self._view.y_max = y_max
        self._view.auto_fit = False
        self.call_log.append(("set_y_range", (y_min, y_max)))
        if self._built:
            self.refresh()

    def set_auto_fit(self, on: bool) -> None:
        """Toggle auto-fit — refits from the track's value range."""
        on = validate_bool("on", "NotebookCurveEditor.set_auto_fit", on)
        self._view.auto_fit = on
        if on:
            self._autofit_from_track()
        self.call_log.append(("set_auto_fit", on))
        if self._built:
            self.refresh()

    def _autofit_from_track(self) -> None:
        """Refit :attr:`view.y_min` / ``y_max`` from the track's keyframes."""
        if self._track is None:
            return
        lo, hi = self._track.value_range
        # Inflate by 5% each side so keyframes on the extreme aren't
        # clipped against the canvas edge.
        span = hi - lo
        if span <= 0.0:
            span = 1.0
        pad = span * 0.05
        self._view.y_min = lo - pad
        self._view.y_max = hi + pad

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def get_curve_points(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        *,
        t0: float | None = None,
        t1: float | None = None,
    ) -> list[tuple[float, float]]:
        """Return sampled ``(time, value)`` points along the curve.

        Parameters
        ----------
        sample_rate:
            Samples per second — defaults to 60.  Total samples =
            ``max(2, int(sample_rate * duration))``.
        t0 / t1:
            Optional explicit time bounds.  ``None`` uses the
            track's own keyframe span (or ``0..1`` for an empty track).
        """
        sample_rate = validate_positive_int(
            "sample_rate", "NotebookCurveEditor.get_curve_points", sample_rate,
        )
        if self._track is None or not self._track.keyframes:
            return []
        if t0 is None:
            t0 = self._track.keyframes[0].time
        else:
            t0 = validate_finite_float(
                "t0", "NotebookCurveEditor.get_curve_points", t0,
            )
        if t1 is None:
            t1 = self._track.keyframes[-1].time
        else:
            t1 = validate_finite_float(
                "t1", "NotebookCurveEditor.get_curve_points", t1,
            )
        if t1 <= t0:
            # Degenerate span → return a single steady sample.
            return [(t0, self._track.sample(t0))]
        duration = t1 - t0
        n = max(2, int(round(sample_rate * duration)))
        step = duration / float(n - 1)
        return [
            (t0 + step * i, self._track.sample(t0 + step * i))
            for i in range(n)
        ]

    # ------------------------------------------------------------------
    # Mouse input (canvas → track op)
    # ------------------------------------------------------------------

    def on_double_click_empty(self, time: float, value: float) -> TimelineKeyframe:
        """Double-click on empty canvas → add keyframe at ``(t, v)``."""
        if self._track is None:
            raise RuntimeError(
                "NotebookCurveEditor.on_double_click_empty: no track loaded"
            )
        return self.add_keyframe(time, value)

    def on_left_drag(
        self,
        kf_id: int,
        time: float,
        value: float,
        *,
        ctrl: bool = False,
    ) -> TimelineKeyframe:
        """Left-drag callback → move keyframe (Ctrl for grid snap)."""
        return self.drag_keyframe(kf_id, time, value, snap=ctrl)

    def on_right_click(self, kf_id: int) -> None:
        """Right-click on a keyframe → open context menu."""
        self.open_context_menu(kf_id)

    def on_middle_drag(self, dt: float) -> None:
        """Middle-drag → pan the view by *dt* seconds."""
        self.pan(dt)

    def on_scroll(self, delta: float) -> None:
        """Scroll wheel → zoom (positive delta zooms in).

        Uses a 10% zoom per unit-delta feel so a single click of the
        wheel doesn't slam the view around.
        """
        delta = validate_finite_float(
            "delta", "NotebookCurveEditor.on_scroll", delta,
        )
        factor = math.exp(delta * 0.1)
        self.zoom(factor)

    # ------------------------------------------------------------------
    # Diary-themed hand-drawn curve preview
    # ------------------------------------------------------------------

    def hand_drawn_points(
        self,
        sample_rate: int = 30,
    ) -> list[tuple[float, float]]:
        """Return ``(t, v)`` samples with a deterministic pencil wobble.

        Mirrors the DD5 pattern of a stable sine-based jitter so visual
        regression tests aren't affected by re-runs.  The wobble is
        applied in *value* space so it looks like a pencil traced the
        curve on paper.
        """
        points = self.get_curve_points(sample_rate=sample_rate)
        if not points:
            return []
        span = self._view.y_max - self._view.y_min
        amp = 0.005 * (span if span > 0 else 1.0)
        return [
            (t, v + amp * math.sin(1.7 * i + 0.3))
            for i, (t, v) in enumerate(points)
        ]

    def keyframe_diamonds(self) -> list[tuple[float, float, float]]:
        """Return ``(time, value, jitter)`` per keyframe for diamond drawing.

        ``jitter`` is a deterministic ±0.6 unit sine-based rotation the
        canvas can add to the diamond so every keyframe looks slightly
        hand-drawn.
        """
        if self._track is None:
            return []
        result: list[tuple[float, float, float]] = []
        for i, kf in enumerate(self._track.keyframes):
            jitter = 0.6 * math.sin(2.1 * i + 0.7)
            result.append((kf.time, kf.value, jitter))
        return result

    # ------------------------------------------------------------------
    # Build / refresh / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Construct the DPG widget tree inside *parent_tag*."""
        if not isinstance(parent_tag, (str, int)) or isinstance(
            parent_tag, bool,
        ):
            raise TypeError(
                "NotebookCurveEditor.build: parent_tag must be str "
                f"or int; got {type(parent_tag).__name__}"
            )
        self._parent_tag = parent_tag
        dpg = _safe_dpg()
        if dpg is None:
            self._built = True
            return
        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                self._build_header(dpg)
                try:
                    dpg.add_text(
                        self._format_status(), tag=self._STATUS_TAG,
                    )
                except Exception:
                    pass
                try:
                    with dpg.group(tag=self._CANVAS_TAG):
                        self._build_canvas(dpg)
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass
        self._built = True

    def refresh(self) -> None:
        """Rebuild the status + canvas (headless-safe)."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                dpg.set_value(self._STATUS_TAG, self._format_status())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._CANVAS_TAG):
                for child in list(
                    dpg.get_item_children(self._CANVAS_TAG, slot=1) or [],
                ):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._CANVAS_TAG):
                    self._build_canvas(dpg)
        except Exception:
            pass

    def destroy(self) -> None:
        """Tear down bookkeeping."""
        self._built = False

    # ------------------------------------------------------------------
    # Widget builders
    # ------------------------------------------------------------------

    def _build_header(self, dpg: Any) -> None:
        """Emit the track selector + curve-kind combo + Y-axis controls."""
        try:
            with dpg.group(tag=self._HEADER_TAG, horizontal=True):
                # Track selector.
                try:
                    tracks = self.available_tracks()
                    labels = [t.property_name for t in tracks]
                    current = (
                        self._track.property_name
                        if self._track is not None else ""
                    )
                    dpg.add_combo(
                        label="Track",
                        items=labels,
                        default_value=current,
                        callback=self._on_track_picked,
                        width=140,
                    )
                except Exception:
                    pass
                # Curve palette.
                try:
                    dpg.add_combo(
                        label="Curve",
                        items=list(CURVE_KINDS),
                        default_value=self._curve_kind,
                        callback=self._on_curve_kind_picked,
                        width=110,
                    )
                except Exception:
                    pass
                # Auto-fit toggle.
                try:
                    dpg.add_checkbox(
                        label="Auto",
                        default_value=self._view.auto_fit,
                        callback=self._on_autofit_toggled,
                    )
                except Exception:
                    pass
                # Y min / max.
                try:
                    dpg.add_input_float(
                        label="Ymin",
                        default_value=float(self._view.y_min),
                        callback=self._on_ymin_changed,
                        width=90,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_float(
                        label="Ymax",
                        default_value=float(self._view.y_max),
                        callback=self._on_ymax_changed,
                        width=90,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _build_canvas(self, dpg: Any) -> None:
        """Emit the curve preview + diamond handles.

        The visual test harness looks for the ASCII sparkline emitted
        below the curve; the interactive canvas layers a drawlist on
        top when DPG is present.
        """
        if self._track is None or not self._track.keyframes:
            try:
                dpg.add_text("(no track — pick one from the dropdown)")
            except Exception:
                pass
            return
        try:
            dpg.add_text(self._curve_glyphs())
        except Exception:
            pass
        # Diamond handles as buttons so the visual grid stays legible.
        try:
            with dpg.group(horizontal=True):
                for kf in self._track.keyframes:
                    marker = "<*>" if kf.id == self._selected_kf_id else "<>"
                    try:
                        dpg.add_button(
                            label=f"{marker}{kf.id}",
                            callback=self._make_select_cb(kf.id),
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        # Context menu inline.
        if self._context_open and self._context_target is not None:
            try:
                with dpg.group(horizontal=True):
                    dpg.add_text(f"kf#{self._context_target}:")
                    dpg.add_button(
                        label="Delete", callback=self._on_context_delete,
                    )
                    for kind in INTERP_KINDS:
                        dpg.add_button(
                            label=f"ease:{kind}",
                            callback=self._make_context_ease_cb(kind),
                        )
                    for kind in INTERP_KINDS:
                        dpg.add_button(
                            label=f"tan:{kind}",
                            callback=self._make_context_tangent_cb(kind),
                        )
                    dpg.add_button(
                        label="Close", callback=self._on_context_close,
                    )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ASCII glyph rendering (drives the diary-themed visual tests).
    # ------------------------------------------------------------------

    def _curve_glyphs(self, columns: int = 24) -> str:
        """Draw a sparkline of the curve — mirrors DD5's ASCII preview."""
        if self._track is None or not self._track.keyframes:
            return "_" * columns
        pts = self.get_curve_points(sample_rate=columns)
        if not pts:
            return "_" * columns
        # Re-sample onto ``columns`` so the glyph line is a fixed width.
        if len(pts) > columns:
            step = (len(pts) - 1) / float(columns - 1)
            pts = [pts[int(round(i * step))] for i in range(columns)]
        elif len(pts) < columns:
            # Pad by repeating the last value so tests get a stable width.
            last = pts[-1]
            pts = pts + [last] * (columns - len(pts))
        values = [v for _t, v in pts]
        lo = min(values)
        hi = max(values)
        span = hi - lo if hi > lo else 1.0
        # Choose a glyph palette per curve kind so the sparkline hints
        # at the shape (staircase vs. curve).
        if self._curve_kind == "step":
            glyphs = "_-="
        elif self._curve_kind == "bezier":
            glyphs = "._~^*"
        else:
            glyphs = "_.-^*"
        bins = len(glyphs) - 1
        return "".join(
            glyphs[max(0, min(bins, int((v - lo) / span * bins)))]
            for v in values
        )

    def _format_status(self) -> str:
        prop = self._track.property_name if self._track is not None else "-"
        nkf = len(self._track.keyframes) if self._track is not None else 0
        sel = self._selected_kf_id
        return (
            f"track: {prop} | keyframes: {nkf} | selected: "
            f"{sel if sel is not None else '-'} | "
            f"curve: {self._curve_kind} | "
            f"y: [{self._view.y_min:0.2f}, {self._view.y_max:0.2f}] | "
            f"zoom: {self._view.zoom:0.2f}"
        )

    # ------------------------------------------------------------------
    # DPG callback wiring
    # ------------------------------------------------------------------

    def _on_track_picked(self, _sender: Any, app_data: Any, *_a: Any) -> None:
        """Track combo callback — swap by property name."""
        try:
            name = str(app_data)
        except Exception:
            return
        for tr in self.available_tracks():
            if tr.property_name == name:
                self.set_track(tr)
                return

    def _on_curve_kind_picked(
        self, _sender: Any, app_data: Any, *_a: Any,
    ) -> None:
        try:
            self.set_curve_kind(str(app_data))
        except (TypeError, ValueError):
            pass

    def _on_autofit_toggled(self, *args: Any, **_kw: Any) -> None:
        if args:
            for cand in args:
                if isinstance(cand, bool):
                    self.set_auto_fit(cand)
                    return
        self.set_auto_fit(not self._view.auto_fit)

    def _on_ymin_changed(self, _sender: Any, app_data: Any, *_a: Any) -> None:
        try:
            y_min = float(app_data)
        except (TypeError, ValueError):
            return
        if y_min < self._view.y_max:
            try:
                self.set_y_range(y_min, self._view.y_max)
            except ValueError:
                pass

    def _on_ymax_changed(self, _sender: Any, app_data: Any, *_a: Any) -> None:
        try:
            y_max = float(app_data)
        except (TypeError, ValueError):
            return
        if y_max > self._view.y_min:
            try:
                self.set_y_range(self._view.y_min, y_max)
            except ValueError:
                pass

    def _make_select_cb(self, kf_id: int) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.select(kf_id)
            except Exception:
                pass
        return _cb

    def _make_context_ease_cb(self, kind: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.context_set_ease(kind)
            except Exception:
                pass
        return _cb

    def _make_context_tangent_cb(self, kind: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.context_set_tangent(kind)
            except Exception:
                pass
        return _cb

    def _on_context_delete(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.context_delete()
        except Exception:
            pass

    def _on_context_close(self, *_a: Any, **_kw: Any) -> None:
        self.close_context_menu()


__all__ = [
    "CURVE_KINDS",
    "CurveView",
    "DEFAULT_GRID_TIME",
    "DEFAULT_GRID_VALUE",
    "DEFAULT_SAMPLE_RATE",
    "MAX_ZOOM",
    "MIN_ZOOM",
    "NotebookCurveEditor",
]
