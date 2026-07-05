"""Tests for :class:`NotebookTimelineEditor` (DD5 sprint).

Covers:

* Construction defaults + property surface.
* Track lifecycle — add / remove / duplicate rejection.
* Keyframe lifecycle — add / remove / drag (move_keyframe).
* Interpolation — linear / step / cubic_hermite endpoint identity,
  monotonic ordering, and the midpoint sample matches the analytic
  Hermite basis for a symmetric two-key curve.
* Playback — play/pause/stop, tick advances, loop wraps at duration,
  non-loop stops at end.
* Frame-sampled callback fires once per track per tick with the
  interpolated value.
* Seek clamps to ``[0, duration_s]`` and emits a sample.
* Timeline swap resets playhead + selection.
* to_yaml / from_yaml round-trip is lossless for tracks + keyframes
  + interp kinds + tempo settings.
* Set_ease flips interpolation kind on a specific keyframe.
* Curve preview length + endpoint identity.
* Headless-DPG build smoke.
* Registration in editor ``__init__.__all__`` + ``_LAZY_MAP``
  alphabetical.
"""
from __future__ import annotations

import math
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_input_float(self, *a, **kw):
        self._track("add_input_float", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_slider_float(self, *a, **kw):
        self._track("add_slider_float", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, tag, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_checkbox",
        "add_input_float", "add_input_text", "add_slider_float",
        "add_separator",
        "does_item_exist", "delete_item",
        "get_item_children", "set_value",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    mod.__slappy_stub__ = True

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_editor(**kw):
    from slappyengine.ui.editor.notebook_timeline_editor import (
        NotebookTimelineEditor,
    )
    return NotebookTimelineEditor(**kw)


def _make_timeline(**kw):
    from slappyengine.ui.editor.notebook_timeline_editor import Timeline
    return Timeline(**kw)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_default_timeline_is_created(self):
        ed = _make_editor()
        assert ed.timeline is not None

    def test_default_duration(self):
        from slappyengine.ui.editor.notebook_timeline_editor import (
            DEFAULT_DURATION_S,
        )
        ed = _make_editor()
        assert ed.duration_s == DEFAULT_DURATION_S

    def test_defaults_paused_and_loop_on(self):
        ed = _make_editor()
        assert ed.playing is False
        assert ed.loop is True
        assert ed.playhead == 0.0

    def test_selection_starts_empty(self):
        ed = _make_editor()
        assert ed.selection == (None, None)

    def test_custom_timeline_binds(self):
        tl = _make_timeline(duration_s=8.0, bpm=140.0, fps=60.0)
        ed = _make_editor(timeline=tl)
        assert ed.timeline is tl
        assert ed.duration_s == 8.0

    def test_interp_kinds_constant(self):
        from slappyengine.ui.editor.notebook_timeline_editor import (
            INTERP_KINDS,
        )
        assert set(INTERP_KINDS) == {"linear", "step", "cubic_hermite"}

    def test_title_constant(self):
        from slappyengine.ui.editor.notebook_timeline_editor import (
            NotebookTimelineEditor,
        )
        assert NotebookTimelineEditor.TITLE == "Timeline"


# ===========================================================================
# Track lifecycle
# ===========================================================================


class TestTracks:
    def test_add_track(self):
        ed = _make_editor()
        tr = ed.add_track("camera.zoom")
        assert tr.property_name == "camera.zoom"
        assert len(ed.timeline.tracks) == 1

    def test_add_track_duplicate_rejected(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        with pytest.raises(ValueError):
            ed.add_track("camera.zoom")

    def test_remove_track(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        ed.remove_track("camera.zoom")
        assert ed.timeline.tracks == []

    def test_remove_missing_track_raises(self):
        ed = _make_editor()
        with pytest.raises(KeyError):
            ed.remove_track("nope")

    def test_track_lookup(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        assert ed.timeline.track("camera.zoom").property_name == "camera.zoom"

    def test_add_track_rejects_empty_name(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.add_track("")


# ===========================================================================
# Keyframe lifecycle
# ===========================================================================


class TestKeyframes:
    def test_add_keyframe_returns_stable_id(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf = ed.add_keyframe("camera.zoom", 0.0, 1.0)
        assert isinstance(kf.id, int)
        assert kf.time == 0.0
        assert kf.value == 1.0
        assert kf.interp == "linear"

    def test_add_multiple_keyframes_sorted(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        ed.add_keyframe("camera.zoom", 2.0, 3.0)
        ed.add_keyframe("camera.zoom", 0.5, 1.0)
        times = [k.time for k in ed.timeline.track("camera.zoom").keyframes]
        assert times == sorted(times)

    def test_remove_keyframe_by_id(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf = ed.add_keyframe("camera.zoom", 0.0, 1.0)
        ed.remove_keyframe("camera.zoom", kf.id)
        assert ed.timeline.track("camera.zoom").keyframes == []

    def test_remove_missing_keyframe_raises(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        with pytest.raises(KeyError):
            ed.remove_keyframe("camera.zoom", 9999)

    def test_move_keyframe_updates_value(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf = ed.add_keyframe("camera.zoom", 0.0, 1.0)
        ed.move_keyframe("camera.zoom", kf.id, time=1.0, value=5.0)
        moved = ed.timeline.track("camera.zoom").keyframes[0]
        assert moved.time == 1.0
        assert moved.value == 5.0
        # id must survive the move.
        assert moved.id == kf.id

    def test_move_keyframe_preserves_id_after_resort(self):
        # Drag key past a neighbour — its ordinal index changes, id doesn't.
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf_a = ed.add_keyframe("camera.zoom", 0.0, 0.0)
        _ = ed.add_keyframe("camera.zoom", 1.0, 1.0)
        # Move kf_a past kf_b.
        ed.move_keyframe("camera.zoom", kf_a.id, time=2.0)
        # kf_a should now be the *last* keyframe by time but still id 0.
        last = ed.timeline.track("camera.zoom").keyframes[-1]
        assert last.id == kf_a.id
        assert last.time == 2.0

    def test_set_ease_switches_kind(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf = ed.add_keyframe("camera.zoom", 0.0, 1.0)
        ed.set_ease("camera.zoom", kf.id, "step")
        assert ed.timeline.track("camera.zoom").keyframes[0].interp == "step"

    def test_set_ease_rejects_unknown_kind(self):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        kf = ed.add_keyframe("camera.zoom", 0.0, 1.0)
        with pytest.raises(ValueError):
            ed.set_ease("camera.zoom", kf.id, "bogus")


# ===========================================================================
# Interpolation math
# ===========================================================================


class TestInterpolation:
    def test_linear_endpoints_identity(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="linear")
        ed.add_keyframe("v", 1.0, 10.0, interp="linear")
        tr = ed.timeline.track("v")
        assert tr.sample(0.0) == pytest.approx(0.0)
        assert tr.sample(1.0) == pytest.approx(10.0)

    def test_linear_midpoint(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="linear")
        ed.add_keyframe("v", 2.0, 10.0, interp="linear")
        tr = ed.timeline.track("v")
        assert tr.sample(1.0) == pytest.approx(5.0)

    def test_step_holds_earlier_value(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="step")
        ed.add_keyframe("v", 1.0, 10.0, interp="step")
        tr = ed.timeline.track("v")
        # Anywhere strictly inside the segment holds the earlier value.
        assert tr.sample(0.001) == pytest.approx(0.0)
        assert tr.sample(0.5) == pytest.approx(0.0)
        assert tr.sample(0.999) == pytest.approx(0.0)
        # Endpoints identity is the same as linear.
        assert tr.sample(1.0) == pytest.approx(10.0)

    def test_cubic_hermite_endpoint_identity(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="cubic_hermite")
        ed.add_keyframe("v", 1.0, 10.0, interp="cubic_hermite")
        tr = ed.timeline.track("v")
        assert tr.sample(0.0) == pytest.approx(0.0)
        assert tr.sample(1.0) == pytest.approx(10.0)

    def test_cubic_hermite_two_key_midpoint_is_lerp(self):
        # With only two keyframes and Catmull-Rom auto-tangents, the
        # prev/next mirrors collapse to a linear midpoint.
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="cubic_hermite")
        ed.add_keyframe("v", 1.0, 10.0, interp="cubic_hermite")
        tr = ed.timeline.track("v")
        assert tr.sample(0.5) == pytest.approx(5.0)

    def test_clamp_before_first_keyframe(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 1.0, 5.0)
        ed.add_keyframe("v", 2.0, 10.0)
        tr = ed.timeline.track("v")
        assert tr.sample(0.0) == pytest.approx(5.0)

    def test_clamp_after_last_keyframe(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 5.0)
        ed.add_keyframe("v", 1.0, 10.0)
        tr = ed.timeline.track("v")
        assert tr.sample(99.0) == pytest.approx(10.0)

    def test_empty_track_samples_zero(self):
        ed = _make_editor()
        ed.add_track("v")
        assert ed.timeline.track("v").sample(0.5) == 0.0


# ===========================================================================
# Playback
# ===========================================================================


class TestPlayback:
    def test_play_flag(self):
        ed = _make_editor()
        ed.play()
        assert ed.playing is True

    def test_pause_flag(self):
        ed = _make_editor()
        ed.play()
        ed.pause()
        assert ed.playing is False

    def test_stop_rewinds(self):
        ed = _make_editor()
        ed.seek(1.5)
        ed.stop()
        assert ed.playhead == 0.0
        assert ed.playing is False

    def test_tick_advances_playhead(self):
        ed = _make_editor()
        ed.play()
        ed.tick(0.5)
        assert ed.playhead == pytest.approx(0.5)

    def test_tick_ignored_when_paused(self):
        ed = _make_editor()
        # Paused by default.
        ed.tick(0.5)
        assert ed.playhead == 0.0

    def test_loop_wraps_at_duration(self):
        ed = _make_editor()
        ed.set_duration_s(1.0)
        ed.set_loop(True)
        ed.play()
        ed.seek(0.8)
        ed.play()  # seek() may pause; re-play.
        ed.tick(0.5)  # 0.8 + 0.5 = 1.3 → wraps to 0.3
        assert ed.playhead == pytest.approx(0.3, abs=1e-6)
        assert ed.playing is True

    def test_non_loop_stops_at_duration(self):
        ed = _make_editor()
        ed.set_duration_s(1.0)
        ed.set_loop(False)
        ed.seek(0.5)
        ed.play()
        ed.tick(2.0)
        assert ed.playhead == pytest.approx(1.0)
        assert ed.playing is False

    def test_toggle_play(self):
        ed = _make_editor()
        assert ed.toggle_play() is True
        assert ed.toggle_play() is False


# ===========================================================================
# Sample callback
# ===========================================================================


class TestSampleCallback:
    def test_tick_emits_sample(self):
        recorded: list[tuple[str, float, float]] = []
        ed = _make_editor(on_frame_sampled=lambda p, t, v: recorded.append((p, t, v)))
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0, interp="linear")
        ed.add_keyframe("v", 1.0, 10.0, interp="linear")
        ed.play()
        ed.tick(0.5)
        assert recorded, "expected on_frame_sampled to fire"
        assert recorded[-1][0] == "v"
        assert recorded[-1][1] == pytest.approx(0.5)
        assert recorded[-1][2] == pytest.approx(5.0)

    def test_seek_emits_sample(self):
        recorded: list[tuple[str, float, float]] = []
        ed = _make_editor(on_frame_sampled=lambda p, t, v: recorded.append((p, t, v)))
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0)
        ed.add_keyframe("v", 1.0, 10.0)
        ed.seek(0.75)
        # seek() emits a sample so scrubbing previews the pose.
        assert any(r[0] == "v" for r in recorded)
        last = [r for r in recorded if r[0] == "v"][-1]
        assert last[2] == pytest.approx(7.5)

    def test_no_callback_when_none_registered(self):
        ed = _make_editor()  # no on_frame_sampled
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0)
        ed.play()
        ed.tick(0.1)  # must not raise

    def test_callback_isolation(self):
        # Bad callbacks must not break the tick loop.
        def boom(_p, _t, _v):
            raise RuntimeError("boom")
        ed = _make_editor(on_frame_sampled=boom)
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0)
        ed.play()
        ed.tick(0.1)  # must not raise
        assert ed.playhead == pytest.approx(0.1)

    def test_callback_per_track(self):
        recorded: list[str] = []
        ed = _make_editor(on_frame_sampled=lambda p, t, v: recorded.append(p))
        for name in ("a", "b", "c"):
            ed.add_track(name)
            ed.add_keyframe(name, 0.0, 0.0)
            ed.add_keyframe(name, 1.0, 1.0)
        ed.play()
        ed.tick(0.5)
        assert set(recorded) == {"a", "b", "c"}


# ===========================================================================
# Seek
# ===========================================================================


class TestSeek:
    def test_seek_clamps_high(self):
        ed = _make_editor()
        ed.set_duration_s(2.0)
        ed.seek(99.0)
        assert ed.playhead == pytest.approx(2.0)

    def test_seek_rejects_negative(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.seek(-1.0)

    def test_seek_updates_playhead(self):
        ed = _make_editor()
        ed.seek(1.5)
        assert ed.playhead == pytest.approx(1.5)


# ===========================================================================
# Timeline swap
# ===========================================================================


class TestTimelineSwap:
    def test_set_project_timeline_replaces(self):
        ed = _make_editor()
        ed.add_track("first")
        new_tl = _make_timeline(duration_s=10.0)
        ed.set_project_timeline(new_tl)
        assert ed.timeline is new_tl
        assert ed.duration_s == 10.0
        assert ed.playhead == 0.0

    def test_set_project_timeline_rejects_non_timeline(self):
        ed = _make_editor()
        with pytest.raises(TypeError):
            ed.set_project_timeline("not a timeline")

    def test_set_project_timeline_clears_selection(self):
        ed = _make_editor()
        ed.add_track("v")
        kf = ed.add_keyframe("v", 0.0, 0.0)
        ed.select("v", kf.id)
        ed.set_project_timeline(_make_timeline())
        assert ed.selection == (None, None)


# ===========================================================================
# YAML round-trip
# ===========================================================================


class TestYamlRoundTrip:
    def test_roundtrip_empty_timeline(self):
        from slappyengine.ui.editor.notebook_timeline_editor import Timeline
        tl = _make_timeline(duration_s=3.0, bpm=90.0, fps=24.0)
        text = tl.to_yaml()
        tl2 = Timeline.from_yaml(text)
        assert tl2.duration_s == pytest.approx(3.0)
        assert tl2.bpm == pytest.approx(90.0)
        assert tl2.fps == pytest.approx(24.0)
        assert tl2.tracks == []

    def test_roundtrip_preserves_keyframes(self):
        from slappyengine.ui.editor.notebook_timeline_editor import Timeline
        tl = _make_timeline(duration_s=4.0)
        tr = tl.add_track("camera.zoom")
        tr.add_keyframe(0.0, 1.0, "linear")
        tr.add_keyframe(1.5, 3.5, "cubic_hermite")
        tr.add_keyframe(3.0, 0.5, "step")
        text = tl.to_yaml()
        tl2 = Timeline.from_yaml(text)
        assert len(tl2.tracks) == 1
        tr2 = tl2.tracks[0]
        assert tr2.property_name == "camera.zoom"
        assert len(tr2.keyframes) == 3
        assert [k.time for k in tr2.keyframes] == pytest.approx([0.0, 1.5, 3.0])
        assert [k.value for k in tr2.keyframes] == pytest.approx([1.0, 3.5, 0.5])
        assert [k.interp for k in tr2.keyframes] == ["linear", "cubic_hermite", "step"]

    def test_roundtrip_via_editor_from_yaml(self):
        ed = _make_editor()
        ed.add_track("a")
        ed.add_keyframe("a", 0.0, 0.0)
        ed.add_keyframe("a", 1.0, 1.0)
        text = ed.to_yaml()
        ed.from_yaml(text)
        assert len(ed.timeline.tracks) == 1
        assert len(ed.timeline.tracks[0].keyframes) == 2

    def test_from_yaml_preserves_ids(self):
        from slappyengine.ui.editor.notebook_timeline_editor import Timeline
        tl = _make_timeline()
        tr = tl.add_track("v")
        kf1 = tr.add_keyframe(0.0, 0.0)
        kf2 = tr.add_keyframe(1.0, 1.0)
        text = tl.to_yaml()
        tl2 = Timeline.from_yaml(text)
        ids2 = [k.id for k in tl2.tracks[0].keyframes]
        assert ids2 == [kf1.id, kf2.id]


# ===========================================================================
# Curve preview
# ===========================================================================


class TestCurvePreview:
    def test_preview_length(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0)
        ed.add_keyframe("v", 4.0, 1.0)
        samples = ed.curve_preview("v", samples=17)
        assert len(samples) == 17

    def test_preview_endpoints(self):
        ed = _make_editor()
        ed.set_duration_s(1.0)
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 3.0)
        ed.add_keyframe("v", 1.0, 7.0)
        samples = ed.curve_preview("v", samples=5)
        assert samples[0] == pytest.approx(3.0)
        assert samples[-1] == pytest.approx(7.0)

    def test_preview_empty_track(self):
        ed = _make_editor()
        ed.add_track("v")
        assert ed.curve_preview("v") == []

    def test_jittered_preview_shape(self):
        ed = _make_editor()
        ed.add_track("v")
        ed.add_keyframe("v", 0.0, 0.0)
        ed.add_keyframe("v", 1.0, 1.0)
        jit = ed.curve_preview_jittered("v", samples=8)
        assert len(jit) == 8
        assert all(len(p) == 2 for p in jit)

    def test_jitter_is_deterministic(self):
        # Same inputs → same jitter (visual tests must be stable).
        ed1 = _make_editor()
        ed1.add_track("v")
        ed1.add_keyframe("v", 0.0, 0.0)
        ed1.add_keyframe("v", 1.0, 1.0)
        ed2 = _make_editor()
        ed2.add_track("v")
        ed2.add_keyframe("v", 0.0, 0.0)
        ed2.add_keyframe("v", 1.0, 1.0)
        assert ed1.curve_preview_jittered("v", 6) == \
               ed2.curve_preview_jittered("v", 6)


# ===========================================================================
# Tempo settings
# ===========================================================================


class TestTempo:
    def test_set_bpm(self):
        ed = _make_editor()
        ed.set_bpm(150.0)
        assert ed.timeline.bpm == pytest.approx(150.0)

    def test_set_bpm_rejects_zero(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.set_bpm(0.0)

    def test_set_fps(self):
        ed = _make_editor()
        ed.set_fps(60.0)
        assert ed.timeline.fps == pytest.approx(60.0)

    def test_set_duration(self):
        ed = _make_editor()
        ed.set_duration_s(12.0)
        assert ed.duration_s == pytest.approx(12.0)

    def test_set_duration_clamps_playhead(self):
        ed = _make_editor()
        ed.seek(3.0)
        ed.set_duration_s(1.0)
        assert ed.playhead == pytest.approx(1.0)


# ===========================================================================
# Headless DPG smoke
# ===========================================================================


class TestHeadlessDPG:
    def test_build_smokes(self, stub_dpg):
        ed = _make_editor()
        ed.build("parent-tag")
        # No exceptions is the pass condition; also assert the root
        # group got emitted.
        assert "group" in stub_dpg.calls

    def test_build_with_tracks(self, stub_dpg):
        ed = _make_editor()
        ed.add_track("camera.zoom")
        ed.add_keyframe("camera.zoom", 0.0, 0.0)
        ed.add_keyframe("camera.zoom", 1.0, 1.0)
        ed.build("parent-tag")
        # Track diamonds must have emitted at least one button per kf +
        # the +Key / x / +Track header buttons.
        assert "add_button" in stub_dpg.calls
        assert len(stub_dpg.calls["add_button"]) >= 4

    def test_build_rejects_bad_parent(self):
        ed = _make_editor()
        with pytest.raises(TypeError):
            ed.build(3.14)  # type: ignore[arg-type]

    def test_refresh_after_add(self, stub_dpg):
        ed = _make_editor()
        ed.build("parent-tag")
        # Adding a track after build triggers refresh — no crash.
        ed.add_track("v")
        assert ed.timeline.tracks


# ===========================================================================
# Selection
# ===========================================================================


class TestSelection:
    def test_select_valid_keyframe(self):
        ed = _make_editor()
        ed.add_track("v")
        kf = ed.add_keyframe("v", 0.0, 0.0)
        ed.select("v", kf.id)
        assert ed.selection == ("v", kf.id)

    def test_select_unknown_keyframe_raises(self):
        ed = _make_editor()
        ed.add_track("v")
        with pytest.raises(KeyError):
            ed.select("v", 999)

    def test_remove_selected_keyframe_clears_selection(self):
        ed = _make_editor()
        ed.add_track("v")
        kf = ed.add_keyframe("v", 0.0, 0.0)
        ed.select("v", kf.id)
        ed.remove_keyframe("v", kf.id)
        assert ed.selection[1] is None


# ===========================================================================
# Registration
# ===========================================================================


class TestRegistration:
    def test_all_exports_contains_editor(self):
        import slappyengine.ui.editor as editor_pkg
        assert "NotebookTimelineEditor" in editor_pkg.__all__

    def test_lazy_map_has_editor(self):
        import slappyengine.ui.editor as editor_pkg
        assert "NotebookTimelineEditor" in editor_pkg._LAZY_MAP

    def test_lazy_import_yields_class(self):
        from slappyengine.ui.editor import NotebookTimelineEditor
        assert NotebookTimelineEditor.__name__ == "NotebookTimelineEditor"

    def test_all_list_alphabetical_neighbourhood(self):
        import slappyengine.ui.editor as editor_pkg
        names = editor_pkg.__all__
        idx = names.index("NotebookTimelineEditor")
        assert names[idx - 1] < "NotebookTimelineEditor"
        assert names[idx + 1] > "NotebookTimelineEditor"


# ===========================================================================
# Data model validation
# ===========================================================================


class TestValidation:
    def test_timeline_rejects_zero_duration(self):
        with pytest.raises(ValueError):
            _make_timeline(duration_s=0.0)

    def test_timeline_rejects_negative_bpm(self):
        with pytest.raises(ValueError):
            _make_timeline(bpm=-5.0)

    def test_keyframe_rejects_nonfinite_time(self):
        ed = _make_editor()
        ed.add_track("v")
        with pytest.raises(ValueError):
            ed.add_keyframe("v", math.inf, 0.0)

    def test_keyframe_rejects_bad_interp(self):
        ed = _make_editor()
        ed.add_track("v")
        with pytest.raises(ValueError):
            ed.add_keyframe("v", 0.0, 0.0, interp="bogus")
