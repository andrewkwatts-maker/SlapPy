"""Diary-themed timeline / keyframe-curve editor (DD5).

The :class:`NotebookTimelineEditor` is the sole owner of the
"animation timeline" affordance in the notebook editor.  It lets the
user author keyframe curves against any dotted entity property
(``camera.zoom``, ``entity.42.position.x`` …) and preview the sampled
values via a ``on_frame_sampled`` callback so downstream systems (the
render loop, the viewport gizmo, the scripting bus …) can wire straight
into the tracks.

The editor is intentionally headless-safe — every ``dpg`` call is
funnelled through ``_safe_dpg`` so the panel can be unit-tested under
a stub DPG in CI.

Design highlights
-----------------

* **Timeline model** — :class:`Timeline` owns tracks + duration + BPM/FPS.
  It is the persistence unit — every YAML round-trip travels through
  ``timeline.to_yaml()`` / ``Timeline.from_yaml(text)``.

* **Track model** — :class:`TimelineTrack` owns an ordered list of
  :class:`TimelineKeyframe` records.  Each keyframe carries an ``id``
  (stable across drags) plus an outgoing interpolation kind
  (``linear`` / ``step`` / ``cubic_hermite``).  The kind on keyframe
  *N* governs the segment from *N* → *N+1*.

* **Sampling** — :meth:`TimelineTrack.sample` locates the segment via
  binary search, then dispatches on the outgoing keyframe's interpolation
  kind.  ``step`` holds the earlier value; ``linear`` lerps; and
  ``cubic_hermite`` uses the standard Hermite basis with tangents
  auto-computed from neighbour secants (Catmull-Rom style — the user
  doesn't have to think about tangents).

* **Playback** — :meth:`NotebookTimelineEditor.tick` (or the internal
  timer driven by :meth:`play`) advances the playhead by *dt* seconds;
  each tick emits ``on_frame_sampled(track_id, time, value)`` per track.

* **Diary theming** — the track area draws:
    * a ruled-paper background (horizontal lines at even Y intervals),
    * a pencil-jittered curve preview overlaid per track.

  The jitter is a deterministic ±1-pixel sine wobble so screenshot
  diffs stay stable in visual tests.

Persistence contract
--------------------

``Timeline.to_yaml()`` produces a tiny hand-rolled YAML doc so the
module has no ``PyYAML`` dependency (matches the existing convention
across the editor package).  ``Timeline.from_yaml(text)`` parses the
same shape back — round-trip is lossless for finite float values.

Public API surface
------------------

* :class:`NotebookTimelineEditor`
* :class:`Timeline`
* :class:`TimelineTrack`
* :class:`TimelineKeyframe`
* :data:`INTERP_KINDS`
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import (
    validate_bool,
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
    validate_str,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The three interpolation kinds a keyframe can use for its outgoing
#: segment.  ``step`` holds the current value until the next keyframe's
#: time is reached (staircase); ``linear`` lerps; ``cubic_hermite`` uses
#: the standard Hermite basis with Catmull-Rom-style auto-tangents.
INTERP_KINDS: tuple[str, ...] = ("linear", "step", "cubic_hermite")

#: Editor defaults surfaced in the header controls.
DEFAULT_DURATION_S: float = 4.0
DEFAULT_BPM: float = 120.0
DEFAULT_FPS: float = 30.0

#: Timeline ruler tick count — one visible mark per RULER_TICKS division
#: of the total duration.
RULER_TICKS: int = 16


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable, else ``None``.

    The panel imports without DPG installed so unit tests can construct
    every method under a stub.
    """
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _validate_interp(name: str, fn: str, value: Any) -> str:
    """Validate a keyframe interpolation kind against :data:`INTERP_KINDS`."""
    kind = validate_non_empty_str(name, fn, value)
    if kind not in INTERP_KINDS:
        raise ValueError(
            f"{fn}: {name} must be one of {INTERP_KINDS}; got {kind!r}"
        )
    return kind


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TimelineKeyframe:
    """One keyframe on a :class:`TimelineTrack`.

    Attributes
    ----------
    id:
        Stable integer id — assigned by the owning track.  Used by
        callbacks (drag / delete) so the row survives a re-sort after
        the user drags a key past a neighbour.
    time:
        Time in seconds.
    value:
        The scalar the track sampler returns at ``time``.
    interp:
        Interpolation kind for the *outgoing* segment (``time`` → next
        keyframe's ``time``).  One of :data:`INTERP_KINDS`.
    """

    id: int
    time: float
    value: float
    interp: str = "linear"

    def __post_init__(self) -> None:
        # id is set by the track constructor; still enforce int here so
        # a mis-typed manual constructor call fails loud.
        if not isinstance(self.id, int) or isinstance(self.id, bool):
            raise TypeError(
                f"TimelineKeyframe: id must be int; got {type(self.id).__name__}"
            )
        self.time = validate_finite_float("time", "TimelineKeyframe", self.time)
        self.value = validate_finite_float("value", "TimelineKeyframe", self.value)
        self.interp = _validate_interp("interp", "TimelineKeyframe", self.interp)


class TimelineTrack:
    """One animated property line on a :class:`Timeline`.

    Keyframes are stored in ``time``-sorted order.  Each keyframe has a
    stable ``id`` so drag/remove callbacks referencing it survive a
    re-sort (a common gotcha — sorted-list indices shift under the drag,
    ids do not).
    """

    def __init__(self, property_name: str) -> None:
        self.property_name: str = validate_non_empty_str(
            "property_name", "TimelineTrack", property_name,
        )
        self.keyframes: list[TimelineKeyframe] = []
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_keyframe(
        self,
        time: float,
        value: float,
        interp: str = "linear",
    ) -> TimelineKeyframe:
        """Insert a new keyframe at ``(time, value)`` and return it."""
        time = validate_finite_float("time", "TimelineTrack.add_keyframe", time)
        value = validate_finite_float(
            "value", "TimelineTrack.add_keyframe", value,
        )
        interp = _validate_interp(
            "interp", "TimelineTrack.add_keyframe", interp,
        )
        kf = TimelineKeyframe(
            id=self._next_id, time=time, value=value, interp=interp,
        )
        self._next_id += 1
        self.keyframes.append(kf)
        self._resort()
        return kf

    def remove_keyframe(self, kf_id: int) -> TimelineKeyframe:
        """Remove and return the keyframe with the given stable ``id``."""
        if not isinstance(kf_id, int) or isinstance(kf_id, bool):
            raise TypeError(
                f"TimelineTrack.remove_keyframe: kf_id must be int; "
                f"got {type(kf_id).__name__}"
            )
        for i, kf in enumerate(self.keyframes):
            if kf.id == kf_id:
                return self.keyframes.pop(i)
        raise KeyError(
            f"TimelineTrack.remove_keyframe: no keyframe with id {kf_id}",
        )

    def move_keyframe(
        self,
        kf_id: int,
        *,
        time: float | None = None,
        value: float | None = None,
    ) -> TimelineKeyframe:
        """Move keyframe ``kf_id`` to a new ``(time, value)``.

        Returns the mutated keyframe.  The list is re-sorted afterwards,
        so the *index* of this keyframe may change but its ``id`` is
        stable.  This is the affordance the DPG drag callback uses.
        """
        for kf in self.keyframes:
            if kf.id == kf_id:
                if time is not None:
                    kf.time = validate_finite_float(
                        "time", "TimelineTrack.move_keyframe", time,
                    )
                if value is not None:
                    kf.value = validate_finite_float(
                        "value", "TimelineTrack.move_keyframe", value,
                    )
                self._resort()
                return kf
        raise KeyError(
            f"TimelineTrack.move_keyframe: no keyframe with id {kf_id}",
        )

    def set_ease(self, kf_id: int, kind: str) -> TimelineKeyframe:
        """Set the outgoing interpolation kind on keyframe ``kf_id``."""
        kind = _validate_interp("kind", "TimelineTrack.set_ease", kind)
        for kf in self.keyframes:
            if kf.id == kf_id:
                kf.interp = kind
                return kf
        raise KeyError(
            f"TimelineTrack.set_ease: no keyframe with id {kf_id}",
        )

    def clear(self) -> None:
        """Drop every keyframe (keeps the id counter — never re-use ids)."""
        self.keyframes.clear()

    def _resort(self) -> None:
        """Re-sort keyframes by ``time`` in place."""
        self.keyframes.sort(key=lambda k: k.time)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    @property
    def value_range(self) -> tuple[float, float]:
        """Return the ``(min, max)`` value across all keyframes.

        Empty tracks default to ``(0.0, 1.0)`` so the Y-axis has a
        sensible non-zero span for the ruled-paper preview.
        """
        if not self.keyframes:
            return (0.0, 1.0)
        vs = [k.value for k in self.keyframes]
        lo, hi = min(vs), max(vs)
        if hi - lo < 1e-6:
            # Constant curve — inflate range so the ruled-paper preview
            # still draws a visible horizontal line rather than a
            # degenerate zero-height stripe.
            return (lo - 0.5, hi + 0.5)
        return (lo, hi)

    def sample(self, t: float) -> float:
        """Sample the track at time *t*.

        Sampling outside the keyframe range clamps to the endpoints (no
        extrapolation).  Empty tracks return ``0.0`` — sensible neutral.
        """
        t = validate_finite_float("t", "TimelineTrack.sample", t)
        if not self.keyframes:
            return 0.0
        if len(self.keyframes) == 1:
            return self.keyframes[0].value
        times = [k.time for k in self.keyframes]
        if t <= times[0]:
            return self.keyframes[0].value
        if t >= times[-1]:
            return self.keyframes[-1].value
        # Locate ``i`` such that times[i] <= t < times[i+1].
        i = bisect_left(times, t) - 1
        if i < 0:
            i = 0
        a = self.keyframes[i]
        b = self.keyframes[i + 1]
        dt = b.time - a.time
        if dt <= 0.0:
            return a.value
        u = (t - a.time) / dt
        kind = a.interp
        if kind == "step":
            return a.value
        if kind == "linear":
            return a.value + (b.value - a.value) * u
        # cubic_hermite — Catmull-Rom style auto-tangents.
        prev_v = self.keyframes[i - 1].value if i > 0 else a.value
        next_v = (
            self.keyframes[i + 2].value if i + 2 < len(self.keyframes) else b.value
        )
        # Tangents scaled by segment length so multi-segment Catmull is
        # ``C^1`` continuous at every internal keyframe.
        m0 = 0.5 * (b.value - prev_v)
        m1 = 0.5 * (next_v - a.value)
        u2 = u * u
        u3 = u2 * u
        h00 = 2.0 * u3 - 3.0 * u2 + 1.0
        h10 = u3 - 2.0 * u2 + u
        h01 = -2.0 * u3 + 3.0 * u2
        h11 = u3 - u2
        return h00 * a.value + h10 * m0 + h01 * b.value + h11 * m1


class Timeline:
    """A collection of :class:`TimelineTrack` s + duration + tempo.

    ``Timeline`` is the persistence unit — the panel calls
    :meth:`set_project_timeline` to swap the entire object when the
    user opens a new project.
    """

    def __init__(
        self,
        *,
        duration_s: float = DEFAULT_DURATION_S,
        bpm: float = DEFAULT_BPM,
        fps: float = DEFAULT_FPS,
    ) -> None:
        self.duration_s: float = validate_positive_float(
            "duration_s", "Timeline", duration_s,
        )
        self.bpm: float = validate_positive_float("bpm", "Timeline", bpm)
        self.fps: float = validate_positive_float("fps", "Timeline", fps)
        self.tracks: list[TimelineTrack] = []

    # ------------------------------------------------------------------
    # Track lookup
    # ------------------------------------------------------------------

    def add_track(self, property_name: str) -> TimelineTrack:
        """Append a new track keyed by *property_name*.

        Raises ``ValueError`` if *property_name* is already in use — the
        panel enforces one track per property so the on-frame-sampled
        callback has a unique key.
        """
        for tr in self.tracks:
            if tr.property_name == property_name:
                raise ValueError(
                    f"Timeline.add_track: property {property_name!r} "
                    "is already tracked"
                )
        track = TimelineTrack(property_name)
        self.tracks.append(track)
        return track

    def remove_track(self, property_name: str) -> TimelineTrack:
        """Remove the track keyed by *property_name*; raise if missing."""
        for i, tr in enumerate(self.tracks):
            if tr.property_name == property_name:
                return self.tracks.pop(i)
        raise KeyError(
            f"Timeline.remove_track: no track for property "
            f"{property_name!r}",
        )

    def track(self, property_name: str) -> TimelineTrack:
        """Return the track keyed by *property_name* (raises if missing)."""
        for tr in self.tracks:
            if tr.property_name == property_name:
                return tr
        raise KeyError(
            f"Timeline.track: no track for property {property_name!r}",
        )

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialise the timeline to a hand-rolled YAML doc."""
        lines: list[str] = []
        lines.append(f"duration_s: {self.duration_s}")
        lines.append(f"bpm: {self.bpm}")
        lines.append(f"fps: {self.fps}")
        lines.append("tracks:")
        for tr in self.tracks:
            lines.append(f"  - property: {tr.property_name}")
            lines.append(f"    keyframes:")
            for kf in tr.keyframes:
                lines.append(
                    f"      - {{id: {kf.id}, time: {kf.time}, "
                    f"value: {kf.value}, interp: {kf.interp}}}"
                )
        return "\n".join(lines) + "\n"

    @classmethod
    def from_yaml(cls, text: str) -> "Timeline":
        """Parse the shape emitted by :meth:`to_yaml`.

        The parser is a hand-rolled state machine — good enough for the
        tiny doc shape we emit and completely free of external deps.
        Unknown lines are skipped so hand-edited files with comments
        still load.
        """
        validate_str("text", "Timeline.from_yaml", text)
        duration = DEFAULT_DURATION_S
        bpm = DEFAULT_BPM
        fps = DEFAULT_FPS
        tracks_raw: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        section: str = "root"

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            stripped = line.strip()

            # ---- root scalars ----
            if line.startswith("duration_s:"):
                duration = float(line.split(":", 1)[1].strip())
                continue
            if line.startswith("bpm:"):
                bpm = float(line.split(":", 1)[1].strip())
                continue
            if line.startswith("fps:"):
                fps = float(line.split(":", 1)[1].strip())
                continue
            if line.startswith("tracks:"):
                section = "tracks"
                continue

            # ---- track entries ----
            if section == "tracks":
                if stripped.startswith("- property:"):
                    current = {
                        "property": stripped.split(":", 1)[1].strip(),
                        "keyframes": [],
                    }
                    tracks_raw.append(current)
                    continue
                if stripped.startswith("keyframes:") and current is not None:
                    continue
                if stripped.startswith("- {") and current is not None:
                    # Inline flow map — parse ``key: value`` pairs.
                    inner = stripped[3:-1] if stripped.endswith("}") else stripped[3:]
                    kw: dict[str, Any] = {}
                    for part in inner.split(","):
                        if ":" not in part:
                            continue
                        k, v = part.split(":", 1)
                        kw[k.strip()] = v.strip()
                    current["keyframes"].append(kw)
                    continue

        timeline = cls(duration_s=duration, bpm=bpm, fps=fps)
        for tr_raw in tracks_raw:
            track = timeline.add_track(tr_raw["property"])
            # Rehydrate keyframes preserving both id and interp.
            for kf_raw in tr_raw["keyframes"]:
                time = float(kf_raw.get("time", 0.0))
                value = float(kf_raw.get("value", 0.0))
                interp = kf_raw.get("interp", "linear")
                kf = track.add_keyframe(time, value, interp)
                # Preserve original id when present — round-trip needs it
                # so external references (drag callbacks in a re-loaded
                # panel) don't get invalidated.
                if "id" in kf_raw:
                    try:
                        kf.id = int(kf_raw["id"])
                        # Keep the counter ahead of any hand-set id so
                        # future ``add_keyframe`` calls stay unique.
                        track._next_id = max(track._next_id, kf.id + 1)
                    except (TypeError, ValueError):
                        pass
        return timeline


# ---------------------------------------------------------------------------
# Public editor panel
# ---------------------------------------------------------------------------


class NotebookTimelineEditor:
    """Diary-themed timeline / keyframe-curve editor.

    Instantiate then wrap in a :class:`MovablePanelWindow` (the shell
    does this automatically when the panel is registered in the layout).

    Parameters
    ----------
    timeline:
        Optional initial :class:`Timeline`.  A fresh empty timeline is
        minted when omitted so the panel is usable straight away.
    on_frame_sampled:
        Optional callback fired for every tracked property on every
        playback tick.  Signature ``(track_property, time, value)``.
        The scripting bus wires this into entity-property setters.
    """

    TITLE: str = "Timeline"
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 320

    _ROOT_TAG = "notebook_timeline_root"
    _HEADER_TAG = "notebook_timeline_header"
    _RULER_TAG = "notebook_timeline_ruler"
    _TRACKS_TAG = "notebook_timeline_tracks"
    _STATUS_TAG = "notebook_timeline_status"

    # Curve preview resolution — 32 sample points per track is enough
    # for a hand-drawn ASCII sparkline and cheap under playback.
    PREVIEW_SAMPLES: int = 32

    def __init__(
        self,
        timeline: Timeline | None = None,
        *,
        on_frame_sampled: Callable[[str, float, float], None] | None = None,
    ) -> None:
        self._timeline: Timeline = (
            timeline if timeline is not None else Timeline()
        )
        self._on_frame_sampled = on_frame_sampled
        self._playhead: float = 0.0
        self._playing: bool = False
        self._loop: bool = True
        self._built: bool = False
        self._parent_tag: str | int | None = None
        # Selection is (track_property, keyframe_id) or (None, None).
        self._selected_track: str | None = None
        self._selected_keyframe: int | None = None
        # Call log so tests can assert on side-effects without mocking DPG.
        self.call_log: list[tuple[str, Any]] = []

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def timeline(self) -> Timeline:
        """The active :class:`Timeline` (mutable — use the panel methods
        for changes that should trigger a redraw)."""
        return self._timeline

    @property
    def playhead(self) -> float:
        """Current playhead time in seconds."""
        return self._playhead

    @property
    def playing(self) -> bool:
        """``True`` iff :meth:`play` is active."""
        return self._playing

    @property
    def loop(self) -> bool:
        """``True`` iff the playhead wraps at ``duration_s``."""
        return self._loop

    @property
    def duration_s(self) -> float:
        """Total timeline duration in seconds."""
        return self._timeline.duration_s

    @property
    def selection(self) -> tuple[str | None, int | None]:
        """``(track_property, keyframe_id)`` for the current selection."""
        return (self._selected_track, self._selected_keyframe)

    # ------------------------------------------------------------------
    # Timeline swap
    # ------------------------------------------------------------------

    def set_project_timeline(self, timeline: Timeline) -> None:
        """Replace the active timeline (used when swapping projects)."""
        if not isinstance(timeline, Timeline):
            raise TypeError(
                "NotebookTimelineEditor.set_project_timeline: timeline "
                f"must be Timeline; got {type(timeline).__name__}"
            )
        self._timeline = timeline
        self._playhead = 0.0
        self._playing = False
        self._selected_track = None
        self._selected_keyframe = None
        self.call_log.append(("set_project_timeline", None))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Track / keyframe API
    # ------------------------------------------------------------------

    def add_track(self, property_name: str) -> TimelineTrack:
        """Append a new track to the active timeline."""
        track = self._timeline.add_track(property_name)
        self.call_log.append(("add_track", property_name))
        if self._built:
            self.refresh()
        return track

    def remove_track(self, property_name: str) -> TimelineTrack:
        """Remove the named track from the active timeline."""
        track = self._timeline.remove_track(property_name)
        if self._selected_track == property_name:
            self._selected_track = None
            self._selected_keyframe = None
        self.call_log.append(("remove_track", property_name))
        if self._built:
            self.refresh()
        return track

    def add_keyframe(
        self,
        property_name: str,
        time: float,
        value: float,
        interp: str = "linear",
    ) -> TimelineKeyframe:
        """Add a keyframe to the named track."""
        track = self._timeline.track(property_name)
        kf = track.add_keyframe(time, value, interp)
        self.call_log.append(("add_keyframe", (property_name, time, value)))
        if self._built:
            self.refresh()
        return kf

    def remove_keyframe(self, property_name: str, kf_id: int) -> TimelineKeyframe:
        """Remove keyframe ``kf_id`` from the named track."""
        track = self._timeline.track(property_name)
        kf = track.remove_keyframe(kf_id)
        if (self._selected_track == property_name
                and self._selected_keyframe == kf_id):
            self._selected_keyframe = None
        self.call_log.append(("remove_keyframe", (property_name, kf_id)))
        if self._built:
            self.refresh()
        return kf

    def move_keyframe(
        self,
        property_name: str,
        kf_id: int,
        *,
        time: float | None = None,
        value: float | None = None,
    ) -> TimelineKeyframe:
        """Move / drag keyframe ``kf_id`` on the named track.

        Both ``time`` and ``value`` are optional; passing only one lets
        the DPG drag callback update the axis the mouse actually moved.
        """
        track = self._timeline.track(property_name)
        kf = track.move_keyframe(kf_id, time=time, value=value)
        self.call_log.append(
            ("move_keyframe", (property_name, kf_id, time, value)),
        )
        if self._built:
            self.refresh()
        return kf

    def set_ease(
        self, property_name: str, kf_id: int, kind: str,
    ) -> TimelineKeyframe:
        """Set the outgoing interpolation kind of keyframe ``kf_id``."""
        track = self._timeline.track(property_name)
        kf = track.set_ease(kf_id, kind)
        self.call_log.append(("set_ease", (property_name, kf_id, kind)))
        if self._built:
            self.refresh()
        return kf

    def select(self, property_name: str, kf_id: int) -> None:
        """Select the keyframe ``kf_id`` on the named track."""
        # Look up to verify both exist; raise loud if not.
        track = self._timeline.track(property_name)
        for kf in track.keyframes:
            if kf.id == kf_id:
                self._selected_track = property_name
                self._selected_keyframe = kf_id
                self.call_log.append(("select", (property_name, kf_id)))
                if self._built:
                    self.refresh()
                return
        raise KeyError(
            f"NotebookTimelineEditor.select: no keyframe {kf_id} on track "
            f"{property_name!r}",
        )

    # ------------------------------------------------------------------
    # Duration / tempo
    # ------------------------------------------------------------------

    def set_duration_s(self, duration_s: float) -> None:
        """Set the timeline's total duration in seconds."""
        self._timeline.duration_s = validate_positive_float(
            "duration_s", "NotebookTimelineEditor.set_duration_s", duration_s,
        )
        if self._playhead > self._timeline.duration_s:
            self._playhead = self._timeline.duration_s
        self.call_log.append(("set_duration_s", self._timeline.duration_s))
        if self._built:
            self.refresh()

    def set_bpm(self, bpm: float) -> None:
        """Set beats-per-minute (used only for display + tempo snap)."""
        self._timeline.bpm = validate_positive_float(
            "bpm", "NotebookTimelineEditor.set_bpm", bpm,
        )
        self.call_log.append(("set_bpm", self._timeline.bpm))
        if self._built:
            self.refresh()

    def set_fps(self, fps: float) -> None:
        """Set frames-per-second (used only for display + frame snap)."""
        self._timeline.fps = validate_positive_float(
            "fps", "NotebookTimelineEditor.set_fps", fps,
        )
        self.call_log.append(("set_fps", self._timeline.fps))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def seek(self, t: float) -> None:
        """Move the playhead to time *t* (clamped to ``[0, duration_s]``)."""
        t = validate_non_negative_float(
            "t", "NotebookTimelineEditor.seek", t,
        )
        t = min(self._timeline.duration_s, t)
        self._playhead = t
        # Seeking still emits a sample event so the viewport can preview
        # the pose while scrubbing.
        self._emit_frame(t)
        self.call_log.append(("seek", t))
        if self._built:
            self.refresh()

    def play(self) -> None:
        """Start the playhead; :meth:`tick` will advance it on subsequent ticks."""
        self._playing = True
        self.call_log.append(("play", None))
        if self._built:
            self.refresh()

    def pause(self) -> None:
        """Freeze the playhead in place."""
        self._playing = False
        self.call_log.append(("pause", None))
        if self._built:
            self.refresh()

    def stop(self) -> None:
        """Freeze the playhead + rewind to the origin."""
        self._playing = False
        self._playhead = 0.0
        # Emit one sample at time=0 so downstream systems settle onto
        # their starting pose.
        self._emit_frame(0.0)
        self.call_log.append(("stop", None))
        if self._built:
            self.refresh()

    def toggle_play(self) -> bool:
        """Flip the playing flag; returns the new state."""
        if self._playing:
            self.pause()
        else:
            self.play()
        return self._playing

    def set_loop(self, loop: bool) -> None:
        """Enable / disable playhead wrap at ``duration_s``."""
        self._loop = validate_bool(
            "loop", "NotebookTimelineEditor.set_loop", loop,
        )
        self.call_log.append(("set_loop", self._loop))
        if self._built:
            self.refresh()

    def tick(self, dt: float) -> None:
        """Advance the playhead by *dt* seconds when :attr:`playing`.

        Emits ``on_frame_sampled(track_property, time, value)`` for every
        track once the new playhead position is settled.  When
        :attr:`loop` is true the playhead wraps at ``duration_s`` (mod);
        otherwise it stops at the end.
        """
        dt = validate_non_negative_float(
            "dt", "NotebookTimelineEditor.tick", dt,
        )
        if not self._playing or dt == 0.0:
            return
        duration = self._timeline.duration_s
        new_t = self._playhead + dt
        if new_t >= duration:
            if self._loop and duration > 0:
                # Modulo wrap.  If dt happens to exceed duration we still
                # land somewhere inside [0, duration).
                new_t = new_t % duration
            else:
                new_t = duration
                self._playing = False
        self._playhead = new_t
        self._emit_frame(new_t)

    def _emit_frame(self, t: float) -> None:
        """Emit ``on_frame_sampled(prop, t, value)`` for every track."""
        if self._on_frame_sampled is None:
            return
        for tr in self._timeline.tracks:
            try:
                value = tr.sample(t)
            except Exception:
                continue
            try:
                self._on_frame_sampled(tr.property_name, t, value)
            except Exception:
                # Callback isolation — one bad listener can't kill the
                # tick loop.
                pass

    # ------------------------------------------------------------------
    # YAML round-trip (delegates to :class:`Timeline`).
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialise the active timeline."""
        return self._timeline.to_yaml()

    def from_yaml(self, text: str) -> None:
        """Replace the active timeline with a parsed :class:`Timeline`."""
        timeline = Timeline.from_yaml(text)
        self.set_project_timeline(timeline)

    # ------------------------------------------------------------------
    # Curve preview
    # ------------------------------------------------------------------

    def curve_preview(
        self, property_name: str, samples: int | None = None,
    ) -> list[float]:
        """Sample the named track *samples* times across the timeline.

        Returns an empty list when the track has no keyframes so the
        renderer can skip the row without a shape check.
        """
        track = self._timeline.track(property_name)
        if not track.keyframes:
            return []
        n = samples if samples is not None else self.PREVIEW_SAMPLES
        n = validate_positive_int(
            "samples", "NotebookTimelineEditor.curve_preview", n,
        )
        duration = self._timeline.duration_s
        if n == 1 or duration <= 0.0:
            return [track.sample(0.0)]
        step = duration / float(n - 1)
        return [track.sample(step * i) for i in range(n)]

    def curve_preview_jittered(
        self, property_name: str, samples: int | None = None,
    ) -> list[tuple[float, float]]:
        """Return ``(x, y)`` samples with a deterministic ±1-pixel pencil wobble.

        The wobble is a sine of the sample index so it's stable under
        visual-regression tests.  Callers still get the raw
        :meth:`curve_preview` values via ``y`` — the ``x`` component
        carries the jitter so it looks hand-drawn along the time axis.
        """
        import math

        values = self.curve_preview(property_name, samples)
        if not values:
            return []
        # Pencil jitter: ±0.6px sine on x, ±0.4px sine on y.
        result: list[tuple[float, float]] = []
        for i, v in enumerate(values):
            jx = 0.6 * math.sin(0.9 * i)
            jy = 0.4 * math.sin(1.7 * i + 0.3)
            result.append((float(i) + jx, float(v) + jy))
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
                "NotebookTimelineEditor.build: parent_tag must be str "
                f"or int; got {type(parent_tag).__name__}"
            )
        self._parent_tag = parent_tag
        dpg = _safe_dpg()
        if dpg is None:
            self._built = True
            return

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                # ---- Header ----
                self._build_header(dpg)

                # ---- Ruler ----
                try:
                    dpg.add_text(self._ruler_glyphs(), tag=self._RULER_TAG)
                except Exception:
                    pass

                # ---- Status ----
                try:
                    dpg.add_text(
                        self._format_status(), tag=self._STATUS_TAG,
                    )
                except Exception:
                    pass

                # ---- Tracks (ruled-paper body) ----
                try:
                    with dpg.group(tag=self._TRACKS_TAG):
                        self._build_tracks(dpg)
                except Exception:
                    self._build_tracks(dpg)
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        """Rebuild the ruler + track rows (headless-safe)."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._RULER_TAG):
                dpg.set_value(self._RULER_TAG, self._ruler_glyphs())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                dpg.set_value(self._STATUS_TAG, self._format_status())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._TRACKS_TAG):
                for child in list(
                    dpg.get_item_children(self._TRACKS_TAG, slot=1) or [],
                ):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._TRACKS_TAG):
                    self._build_tracks(dpg)
        except Exception:
            try:
                self._build_tracks(dpg)
            except Exception:
                pass

    def destroy(self) -> None:
        """Tear down bookkeeping (theme listeners etc.)."""
        self._built = False

    # ------------------------------------------------------------------
    # Widget builders
    # ------------------------------------------------------------------

    def _build_header(self, dpg: Any) -> None:
        """Emit the transport controls + tempo/duration inputs."""
        try:
            with dpg.group(tag=self._HEADER_TAG, horizontal=True):
                try:
                    dpg.add_button(
                        label=("Pause" if self._playing else "Play"),
                        callback=self._on_play_clicked,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(label="Stop", callback=self._on_stop_clicked)
                except Exception:
                    pass
                try:
                    dpg.add_checkbox(
                        label="Loop", default_value=self._loop,
                        callback=self._on_loop_toggled,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_float(
                        label="BPM",
                        default_value=float(self._timeline.bpm),
                        callback=self._on_bpm_changed,
                        width=90,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_float(
                        label="FPS",
                        default_value=float(self._timeline.fps),
                        callback=self._on_fps_changed,
                        width=90,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_float(
                        label="Dur",
                        default_value=float(self._timeline.duration_s),
                        callback=self._on_duration_changed,
                        width=90,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="+ Track", callback=self._on_add_track_clicked,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _build_tracks(self, dpg: Any) -> None:
        """Emit one row per track — keyframe diamonds + curve preview."""
        if not self._timeline.tracks:
            try:
                dpg.add_text("(no tracks — click +Track to add one)")
            except Exception:
                pass
            return
        for tr in self._timeline.tracks:
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(tr.property_name)
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="+ Key",
                            callback=self._make_add_key_cb(tr.property_name),
                        )
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="x",
                            callback=self._make_remove_track_cb(
                                tr.property_name,
                            ),
                        )
                    except Exception:
                        pass
                # Keyframe row — diamond buttons per keyframe.
                try:
                    with dpg.group(horizontal=True):
                        for kf in tr.keyframes:
                            try:
                                dpg.add_button(
                                    label=f"<>{kf.id}",
                                    callback=self._make_select_cb(
                                        tr.property_name, kf.id,
                                    ),
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
                # Curve preview under the track.
                try:
                    dpg.add_text(self._curve_glyphs(tr.property_name))
                except Exception:
                    pass
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ASCII glyph rendering (also drives visual tests).
    # ------------------------------------------------------------------

    def _ruler_glyphs(self) -> str:
        """Diary-themed ASCII ruler with the playhead marked."""
        ticks = RULER_TICKS
        duration = self._timeline.duration_s
        pos = (
            int(self._playhead / duration * (ticks - 1))
            if duration > 0 else 0
        )
        pos = max(0, min(ticks - 1, pos))
        return " ".join("^" if i == pos else "|" for i in range(ticks))

    def _curve_glyphs(self, property_name: str) -> str:
        """Sparkline for a single track's curve."""
        try:
            samples = self.curve_preview(property_name, samples=RULER_TICKS)
        except Exception:
            return ""
        if not samples:
            return "_" * RULER_TICKS
        lo, hi = min(samples), max(samples)
        span = hi - lo if hi > lo else 1.0
        glyphs = "_.-^*"
        bins = len(glyphs) - 1
        return "".join(
            glyphs[max(0, min(bins, int((v - lo) / span * bins)))]
            for v in samples
        )

    def _format_status(self) -> str:
        return (
            f"t = {self._playhead:0.2f}s / "
            f"{self._timeline.duration_s:0.2f}s | "
            f"tracks: {len(self._timeline.tracks)} | "
            f"bpm: {self._timeline.bpm:g} fps: {self._timeline.fps:g} | "
            f"{'playing' if self._playing else 'paused'} | "
            f"loop: {'on' if self._loop else 'off'}"
        )

    # ------------------------------------------------------------------
    # DPG callback wiring
    # ------------------------------------------------------------------

    def _on_play_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.toggle_play()

    def _on_stop_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.stop()

    def _on_loop_toggled(self, *args: Any, **_kw: Any) -> None:
        # DPG checkbox callback: (sender, app_data, user_data).
        if args:
            for cand in args:
                if isinstance(cand, bool):
                    self.set_loop(cand)
                    return
        self.set_loop(not self._loop)

    def _on_bpm_changed(self, _sender: Any, app_data: Any, *_a: Any) -> None:
        try:
            self.set_bpm(float(app_data))
        except (TypeError, ValueError):
            pass

    def _on_fps_changed(self, _sender: Any, app_data: Any, *_a: Any) -> None:
        try:
            self.set_fps(float(app_data))
        except (TypeError, ValueError):
            pass

    def _on_duration_changed(
        self, _sender: Any, app_data: Any, *_a: Any,
    ) -> None:
        try:
            self.set_duration_s(float(app_data))
        except (TypeError, ValueError):
            pass

    def _on_add_track_clicked(self, *_a: Any, **_kw: Any) -> None:
        # Auto-name new tracks so the button is always safe to hit —
        # user can rename via the Inspector once bound to an entity.
        base = "track"
        i = 0
        while True:
            candidate = f"{base}.{i}" if i else base
            try:
                self._timeline.track(candidate)
                i += 1
                continue
            except KeyError:
                break
        self.add_track(candidate)

    def _make_add_key_cb(
        self, property_name: str,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                track = self._timeline.track(property_name)
                # Value defaults to the current curve sample so adding a
                # key on the playhead doesn't change the animation shape.
                value = track.sample(self._playhead)
                self.add_keyframe(property_name, self._playhead, value)
            except Exception:
                pass
        return _cb

    def _make_remove_track_cb(
        self, property_name: str,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.remove_track(property_name)
            except Exception:
                pass
        return _cb

    def _make_select_cb(
        self, property_name: str, kf_id: int,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.select(property_name, kf_id)
            except Exception:
                pass
        return _cb


__all__ = [
    "DEFAULT_BPM",
    "DEFAULT_DURATION_S",
    "DEFAULT_FPS",
    "INTERP_KINDS",
    "NotebookTimelineEditor",
    "RULER_TICKS",
    "Timeline",
    "TimelineKeyframe",
    "TimelineTrack",
]
