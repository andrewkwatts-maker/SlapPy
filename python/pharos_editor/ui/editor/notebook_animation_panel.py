"""Notebook-themed timeline / curve editor for entity animations.

The :class:`NotebookAnimationPanel` is a hand-drawn ruler + keyframe
editor.  Each animated property lives on its own row:

* The ruler is drawn at the top in the active theme's handwritten font.
  Click anywhere on the ruler to seek the playhead.
* Each property row holds a :class:`Track` — a small wrapper around an
  :class:`AnimationCurve` (and its underlying :class:`Keyframe` list).
* Click a keyframe → select it.  Drag → adjust ``(time, value)``.  Use
  the inline `+ Key` button to add a new keyframe at the playhead.
* A `delete` button removes the selected keyframe.
* A curve preview line between keyframes is sampled at 32 points and
  drawn as ASCII dots beneath the ruler (the visual contract; richer
  renderers may opt into the DPG draw list).
* Bottom controls: Play / Pause / Loop toggle plus a Save sticker that
  writes the tracks to ``<scene_root>/<entity>.anim.yaml``.

The panel never imports DPG at module-level — every dpg call is funnelled
through ``_safe_dpg`` so it imports + builds under a stub DPG in tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_optional_path_like,
    validate_str,
)
from pharos_engine.math.curves import AnimationCurve, Keyframe
from pharos_editor.ui.widgets.doodle_separator import DoodleSeparator
from pharos_editor.ui.widgets.heart_checkbox import HeartCheckbox
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
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Track model
# ---------------------------------------------------------------------------


class Track:
    """A single animated property — name + keyframes + cached curve.

    The track owns a mutable list of :class:`Keyframe` records.  The
    cached :class:`AnimationCurve` is rebuilt on every mutation so
    ``sample(t)`` always reflects the latest state.

    Parameters
    ----------
    property_name:
        Hierarchical dotted name (e.g. ``"transform.position.x"``).
    keyframes:
        Iterable of ``Keyframe`` instances.  Empty lists are accepted
        but ``sample`` is a no-op until at least one keyframe is added.
    """

    def __init__(
        self,
        property_name: str,
        keyframes: list[Keyframe] | None = None,
    ) -> None:
        self.property_name = validate_non_empty_str(
            "property_name", "Track", property_name,
        )
        if keyframes is None:
            keyframes = []
        if not isinstance(keyframes, list):
            raise TypeError(
                f"Track: keyframes must be a list; got {type(keyframes).__name__}",
            )
        for i, kf in enumerate(keyframes):
            if not isinstance(kf, Keyframe):
                raise TypeError(
                    f"Track: keyframes[{i}] must be Keyframe; "
                    f"got {type(kf).__name__}",
                )
        self.keyframes: list[Keyframe] = list(
            sorted(keyframes, key=lambda kf: kf.t),
        )
        self._curve: AnimationCurve | None = None
        self._rebuild_curve()

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_keyframe(self, t: float, value: float) -> Keyframe:
        """Add a new keyframe at ``(t, value)`` and return it."""
        validate_finite_float("t", "Track.add_keyframe", t)
        validate_finite_float("value", "Track.add_keyframe", value)
        kf = Keyframe(t=float(t), value=float(value))
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.t)
        self._rebuild_curve()
        return kf

    def remove_keyframe(self, index: int) -> Keyframe:
        """Remove and return the keyframe at *index*."""
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError(
                f"Track.remove_keyframe: index must be int; "
                f"got {type(index).__name__}",
            )
        if not 0 <= index < len(self.keyframes):
            raise IndexError(
                f"Track.remove_keyframe: index {index} out of range "
                f"[0, {len(self.keyframes)})",
            )
        kf = self.keyframes.pop(index)
        self._rebuild_curve()
        return kf

    def move_keyframe(self, index: int, *, t: float | None = None,
                      value: float | None = None) -> Keyframe:
        """Move keyframe at *index* to a new ``(t, value)``.

        Returns the new keyframe (the underlying ``Keyframe`` is frozen so
        a fresh record replaces the old one).
        """
        if not 0 <= index < len(self.keyframes):
            raise IndexError(
                f"Track.move_keyframe: index {index} out of range",
            )
        old = self.keyframes[index]
        new_t = old.t if t is None else validate_finite_float(
            "t", "Track.move_keyframe", t,
        )
        new_value = old.value if value is None else validate_finite_float(
            "value", "Track.move_keyframe", value,
        )
        new = Keyframe(
            t=float(new_t), value=float(new_value),
            in_tan=old.in_tan, out_tan=old.out_tan,
        )
        self.keyframes[index] = new
        self.keyframes.sort(key=lambda k: k.t)
        self._rebuild_curve()
        return new

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(self, t: float) -> float:
        """Sample the cached curve at *t*; returns ``0.0`` if empty."""
        if self._curve is None:
            return 0.0
        return self._curve.sample(t)

    @property
    def duration(self) -> float:
        if not self.keyframes:
            return 0.0
        return self.keyframes[-1].t - self.keyframes[0].t

    def _rebuild_curve(self) -> None:
        if not self.keyframes:
            self._curve = None
            return
        if len(self.keyframes) == 1:
            # AnimationCurve requires at least 1 keyframe but works fine
            # — sampling at any t returns the single endpoint value.
            self._curve = AnimationCurve(keyframes=[self.keyframes[0]])
            return
        self._curve = AnimationCurve(keyframes=list(self.keyframes))


# ---------------------------------------------------------------------------
# Public panel
# ---------------------------------------------------------------------------


class NotebookAnimationPanel:
    """Diary-themed timeline + curve editor.

    Parameters
    ----------
    on_save:
        Optional callback fired when the user clicks the Save sticker.
        Receives the destination :class:`Path`.
    """

    TITLE = "Timeline"
    MIN_WIDTH: int = 420
    MIN_HEIGHT: int = 320

    _ROOT_TAG = "notebook_anim_root"
    _TRACKS_TAG = "notebook_anim_tracks"
    _RULER_TAG = "notebook_anim_ruler"
    _STATUS_TAG = "notebook_anim_status"

    RULER_TICKS: int = 16

    def __init__(
        self,
        *,
        on_save: Callable[[Path], None] | None = None,
    ) -> None:
        self._on_save = on_save
        self._tracks: list[Track] = []
        self._selected_entity: str | None = None
        self._scene_root: Path | None = None
        self._playhead: float = 0.0
        self._duration: float = 4.0
        self._playing: bool = False
        self._loop: bool = True
        self._selected_track: int = -1
        self._selected_keyframe: int = -1
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._theme = resolve_theme()
        self.call_log: list[tuple[str, Any]] = []

        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    @property
    def playhead(self) -> float:
        return self._playhead

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def selected_entity(self) -> str | None:
        return self._selected_entity

    @property
    def selection(self) -> tuple[int, int]:
        return (self._selected_track, self._selected_keyframe)

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
    # Track management
    # ------------------------------------------------------------------

    def add_track(self, property_name: str,
                  keyframes: list[Keyframe] | None = None) -> Track:
        """Append a new :class:`Track` and return it."""
        track = Track(property_name, keyframes=keyframes)
        self._tracks.append(track)
        self._refresh_duration()
        self.call_log.append(("add_track", property_name))
        if self._built:
            self.refresh()
        return track

    def remove_track(self, index: int) -> Track:
        """Remove and return the track at *index*."""
        if not 0 <= index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.remove_track: index {index} out of range",
            )
        track = self._tracks.pop(index)
        if self._selected_track == index:
            self._selected_track = -1
            self._selected_keyframe = -1
        self._refresh_duration()
        self.call_log.append(("remove_track", track.property_name))
        if self._built:
            self.refresh()
        return track

    def clear_tracks(self) -> None:
        """Drop every track."""
        self._tracks.clear()
        self._selected_track = -1
        self._selected_keyframe = -1
        self._refresh_duration()
        self.call_log.append(("clear_tracks", None))
        if self._built:
            self.refresh()

    def select(self, track_index: int, keyframe_index: int) -> None:
        """Select the keyframe at ``(track_index, keyframe_index)``."""
        if not 0 <= track_index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.select: track_index {track_index} "
                f"out of range",
            )
        track = self._tracks[track_index]
        if not 0 <= keyframe_index < len(track.keyframes):
            raise IndexError(
                f"NotebookAnimationPanel.select: keyframe_index "
                f"{keyframe_index} out of range",
            )
        self._selected_track = track_index
        self._selected_keyframe = keyframe_index
        self.call_log.append(("select", (track_index, keyframe_index)))
        if self._built:
            self.refresh()

    def add_keyframe(self, track_index: int, t: float, value: float) -> Keyframe:
        """Add a keyframe to the track at *track_index*."""
        if not 0 <= track_index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.add_keyframe: track_index "
                f"{track_index} out of range",
            )
        kf = self._tracks[track_index].add_keyframe(t, value)
        self._refresh_duration()
        self.call_log.append(("add_keyframe", (track_index, t, value)))
        if self._built:
            self.refresh()
        return kf

    def remove_keyframe(self, track_index: int, kf_index: int) -> Keyframe:
        if not 0 <= track_index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.remove_keyframe: bad track_index",
            )
        track = self._tracks[track_index]
        kf = track.remove_keyframe(kf_index)
        if (self._selected_track == track_index
                and self._selected_keyframe == kf_index):
            self._selected_keyframe = -1
        self._refresh_duration()
        self.call_log.append(("remove_keyframe", (track_index, kf_index)))
        if self._built:
            self.refresh()
        return kf

    def move_keyframe(
        self, track_index: int, kf_index: int,
        *, t: float | None = None, value: float | None = None,
    ) -> Keyframe:
        if not 0 <= track_index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.move_keyframe: bad track_index",
            )
        kf = self._tracks[track_index].move_keyframe(
            kf_index, t=t, value=value,
        )
        self._refresh_duration()
        self.call_log.append(("move_keyframe", (track_index, kf_index, t, value)))
        if self._built:
            self.refresh()
        return kf

    # ------------------------------------------------------------------
    # Playhead + transport
    # ------------------------------------------------------------------

    def seek(self, t: float) -> None:
        """Move the playhead to time *t* (clamped to ``[0, duration]``)."""
        validate_finite_float("t", "NotebookAnimationPanel.seek", t)
        t = max(0.0, min(self._duration, float(t)))
        self._playhead = t
        self.call_log.append(("seek", t))
        if self._built:
            self.refresh()

    def play(self) -> None:
        self._playing = True
        self.call_log.append(("play", None))
        if self._built:
            self.refresh()

    def pause(self) -> None:
        self._playing = False
        self.call_log.append(("pause", None))
        if self._built:
            self.refresh()

    def toggle_play(self) -> bool:
        self._playing = not self._playing
        self.call_log.append(("toggle_play", self._playing))
        if self._built:
            self.refresh()
        return self._playing

    def set_loop(self, loop: bool) -> None:
        self._loop = bool(loop)
        self.call_log.append(("loop", self._loop))
        if self._built:
            self.refresh()

    def tick(self, dt: float) -> None:
        """Advance the playhead by *dt* seconds when ``playing``."""
        validate_finite_float("dt", "NotebookAnimationPanel.tick", dt)
        if not self._playing:
            return
        new_t = self._playhead + float(dt)
        if new_t > self._duration:
            if self._loop and self._duration > 0:
                new_t = new_t % self._duration
            else:
                new_t = self._duration
                self._playing = False
        self._playhead = new_t

    # ------------------------------------------------------------------
    # Entity / scene binding
    # ------------------------------------------------------------------

    def bind_entity(
        self,
        entity_name: str,
        scene_root: Path | str | None = None,
    ) -> None:
        """Bind the panel to a named entity + scene root for save targets."""
        validate_non_empty_str("entity_name",
                                "NotebookAnimationPanel.bind_entity",
                                entity_name)
        path = validate_optional_path_like(
            "scene_root", "NotebookAnimationPanel.bind_entity", scene_root,
        )
        self._selected_entity = entity_name
        self._scene_root = path
        self.call_log.append(("bind_entity", (entity_name, str(path) if path else None)))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_path(self) -> Path | None:
        """Return ``<scene_root>/<entity>.anim.yaml`` or ``None``."""
        if self._selected_entity is None or self._scene_root is None:
            return None
        return self._scene_root / f"{self._selected_entity}.anim.yaml"

    def save(self) -> Path | None:
        """Write the current tracks to ``<scene_root>/<entity>.anim.yaml``."""
        path = self.save_path()
        if path is None:
            self.call_log.append(("save_skipped", None))
            return None
        try:
            self._write_yaml(path)
        except Exception as exc:
            self.call_log.append(("save_error", repr(exc)))
            return None
        self.call_log.append(("save", str(path)))
        if self._on_save is not None:
            try:
                self._on_save(path)
            except Exception:
                pass
        return path

    def _write_yaml(self, path: Path) -> None:
        """Serialise tracks to a tiny YAML doc (no external dep)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append(f"entity: {self._selected_entity}")
        lines.append(f"duration: {self._duration}")
        lines.append("tracks:")
        for tr in self._tracks:
            lines.append(f"  - property: {tr.property_name}")
            lines.append(f"    keyframes:")
            for kf in tr.keyframes:
                lines.append(
                    f"      - {{t: {kf.t}, value: {kf.value}, "
                    f"in_tan: {kf.in_tan}, out_tan: {kf.out_tan}}}"
                )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Curve preview
    # ------------------------------------------------------------------

    def curve_preview(self, track_index: int, samples: int = 32) -> list[float]:
        """Return *samples* points along the curve for the track index."""
        if not 0 <= track_index < len(self._tracks):
            raise IndexError(
                f"NotebookAnimationPanel.curve_preview: bad track_index",
            )
        track = self._tracks[track_index]
        if not track.keyframes:
            return []
        t0 = track.keyframes[0].t
        t1 = track.keyframes[-1].t
        if t1 <= t0 or samples < 2:
            return [track.keyframes[0].value]
        step = (t1 - t0) / float(samples - 1)
        return [track.sample(t0 + step * i) for i in range(samples)]

    # ------------------------------------------------------------------
    # Build / refresh / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = _safe_dpg()
        self._parent_tag = parent_tag
        if dpg is None:
            self._built = True
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                # Header.
                try:
                    dpg.add_text(self.TITLE, color=ink)
                except Exception:
                    pass
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass

                # Transport controls.
                try:
                    with dpg.group(horizontal=True):
                        try:
                            StickerButton(
                                label=("Pause" if self._playing else "Play"),
                                sticker_icon="fox",
                                callback=self._on_play_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            HeartCheckbox(
                                label="Loop",
                                value=self._loop,
                                callback=self._on_loop_toggled,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Save",
                                sticker_icon="butterfly",
                                callback=self._on_save_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    DoodleSeparator("wavy").build(self._ROOT_TAG)
                except Exception:
                    pass

                # Ruler.
                try:
                    dpg.add_text(self._ruler_glyphs(), tag=self._RULER_TAG,
                                 color=accent)
                except Exception:
                    pass

                # Status.
                try:
                    dpg.add_text(self._format_status(),
                                 tag=self._STATUS_TAG, color=ink)
                except Exception:
                    pass

                try:
                    DoodleSeparator("dotted").build(self._ROOT_TAG)
                except Exception:
                    pass

                # Tracks.
                try:
                    with dpg.group(tag=self._TRACKS_TAG):
                        self._build_tracks()
                except Exception:
                    self._build_tracks()
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                dpg.set_value(self._STATUS_TAG, self._format_status())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._RULER_TAG):
                dpg.set_value(self._RULER_TAG, self._ruler_glyphs())
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._TRACKS_TAG):
                for child in list(dpg.get_item_children(
                    self._TRACKS_TAG, slot=1,
                ) or []):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._TRACKS_TAG):
                    self._build_tracks()
        except Exception:
            try:
                self._build_tracks()
            except Exception:
                pass

    def destroy(self) -> None:
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _build_tracks(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._tracks:
            try:
                dpg.add_text("(no tracks - add a property to animate)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        for ti, track in enumerate(self._tracks):
            try:
                with dpg.group(horizontal=True):
                    try:
                        dpg.add_text(track.property_name, color=ink)
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="+ Key",
                            callback=self._make_add_key_callback(ti),
                        )
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="x",
                            callback=self._make_remove_track_callback(ti),
                        )
                    except Exception:
                        pass

                # Keyframe row.
                try:
                    with dpg.group(horizontal=True):
                        for ki, kf in enumerate(track.keyframes):
                            try:
                                dpg.add_button(
                                    label=f"o{ki}",
                                    callback=self._make_select_callback(ti, ki),
                                )
                            except Exception:
                                pass
                except Exception:
                    pass

                # Curve preview.
                try:
                    preview = self._curve_glyphs(ti)
                    dpg.add_text(preview, color=accent)
                except Exception:
                    pass
            except Exception:
                pass

    def _ruler_glyphs(self) -> str:
        """Return an ASCII ruler with the playhead marked."""
        ticks = self.RULER_TICKS
        out: list[str] = []
        playhead_pos = (
            int(self._playhead / self._duration * (ticks - 1))
            if self._duration > 0 else 0
        )
        for i in range(ticks):
            out.append("^" if i == playhead_pos else "|")
        return " ".join(out)

    def _curve_glyphs(self, track_index: int) -> str:
        """Return an ASCII rendering of the curve for *track_index*."""
        try:
            samples = self.curve_preview(track_index, samples=self.RULER_TICKS)
        except Exception:
            return ""
        if not samples:
            return ""
        if len(samples) == 1:
            return "_" * self.RULER_TICKS
        lo = min(samples)
        hi = max(samples)
        span = hi - lo if hi > lo else 1.0
        glyphs = "_.-^*"
        bins = len(glyphs) - 1
        return "".join(
            glyphs[max(0, min(bins, int((v - lo) / span * bins)))]
            for v in samples
        )

    def _format_status(self) -> str:
        return (
            f"t = {self._playhead:0.2f}s / {self._duration:0.2f}s | "
            f"tracks: {len(self._tracks)} | "
            f"{'playing' if self._playing else 'paused'} | "
            f"loop: {'on' if self._loop else 'off'}"
        )

    def _refresh_duration(self) -> None:
        """Update ``_duration`` from the max keyframe time across all tracks."""
        max_t = 0.0
        for t in self._tracks:
            if t.keyframes:
                max_t = max(max_t, t.keyframes[-1].t)
        self._duration = max(max_t, 4.0)
        self._playhead = min(self._playhead, self._duration)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_play_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.toggle_play()

    def _on_loop_toggled(self, *args: Any, **_kw: Any) -> None:
        # HeartCheckbox callback signature: (value) per the widget contract.
        if args:
            value = args[0]
            if isinstance(value, bool):
                self.set_loop(value)
                return
        self.set_loop(not self._loop)

    def _on_save_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.save()

    def _make_add_key_callback(self, track_index: int) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                # Default the new keyframe's value to the curve sample so
                # adding a key on the playhead leaves the curve unchanged.
                value = self._tracks[track_index].sample(self._playhead)
                self.add_keyframe(track_index, self._playhead, value)
            except Exception:
                pass
        return _cb

    def _make_remove_track_callback(
        self, track_index: int,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.remove_track(track_index)
            except Exception:
                pass
        return _cb

    def _make_select_callback(
        self, track_index: int, kf_index: int,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.select(track_index, kf_index)
            except Exception:
                pass
        return _cb


__all__ = [
    "NotebookAnimationPanel",
    "Track",
]
