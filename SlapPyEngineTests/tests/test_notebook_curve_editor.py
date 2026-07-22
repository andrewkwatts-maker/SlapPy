"""Tests for :class:`NotebookCurveEditor` (GG5 sprint).

Covers:

* Construction defaults.
* Panel builds under a stub DPG.
* ``set_track`` swaps the edited track and refreshes.
* Add / delete keyframe.
* Drag keyframe updates ``(t, v)``.
* Snap-to-grid rounds correctly under Ctrl-drag.
* Interpolation samples match the analytic expectation for
  linear / step / hermite endpoints.
* Auto-fit adjusts the Y range from the track's value span.
* Zoom is clamped to :data:`MIN_ZOOM` / :data:`MAX_ZOOM`.
* Curve palette registration + kind validation.
* Right-click context menu open / close / delete / set-ease.
* Registration in editor ``__init__.__all__`` + ``_LAZY_MAP`` alphabetical.
"""
from __future__ import annotations

import math
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors the Z2 pattern used across the notebook tests)
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

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)

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
        "add_input_float", "add_input_text", "add_combo",
        "add_slider_float", "add_separator",
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


def _make_track(name: str = "camera.zoom"):
    from pharos_engine.ui.editor.notebook_timeline_editor import TimelineTrack
    return TimelineTrack(name)


def _make_editor(track=None, **kw):
    from pharos_engine.ui.editor.notebook_curve_editor import NotebookCurveEditor
    return NotebookCurveEditor(track=track, **kw)


def _seed_two_key(track, *, interp: str = "linear"):
    """Seed *track* with (0, 0) and (1, 10) using *interp*."""
    track.add_keyframe(0.0, 0.0, interp)
    track.add_keyframe(1.0, 10.0, interp)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults_no_track(self):
        ed = _make_editor()
        assert ed.track is None
        assert ed.selected_keyframe is None
        assert ed.curve_kind == "linear"

    def test_defaults_with_track(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        assert ed.track is tr

    def test_title_constant(self):
        from pharos_engine.ui.editor.notebook_curve_editor import (
            NotebookCurveEditor,
        )
        assert NotebookCurveEditor.TITLE == "Curve Editor"
        assert NotebookCurveEditor.MIN_WIDTH == 400
        assert NotebookCurveEditor.MIN_HEIGHT == 300

    def test_grid_defaults(self):
        ed = _make_editor()
        assert ed.grid_time > 0.0
        assert ed.grid_value > 0.0

    def test_view_defaults(self):
        ed = _make_editor()
        assert ed.view.zoom == pytest.approx(1.0)
        assert ed.view.pan_time == pytest.approx(0.0)
        assert ed.view.auto_fit is True

    def test_curve_kinds_constant(self):
        from pharos_engine.ui.editor.notebook_curve_editor import CURVE_KINDS
        assert set(CURVE_KINDS) == {"linear", "step", "hermite", "bezier"}

    def test_rejects_non_track(self):
        with pytest.raises(TypeError):
            _make_editor(track="not a track")

    def test_rejects_non_callable_provider(self):
        with pytest.raises(TypeError):
            _make_editor(tracks_provider="nope")

    def test_rejects_non_callable_on_change(self):
        with pytest.raises(TypeError):
            _make_editor(on_curve_changed=42)


# ===========================================================================
# Track selector
# ===========================================================================


class TestSetTrack:
    def test_set_track_swaps(self):
        ed = _make_editor()
        tr = _make_track("a.b")
        ed.set_track(tr)
        assert ed.track is tr

    def test_set_track_none_clears(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.set_track(None)
        assert ed.track is None
        assert ed.selected_keyframe is None

    def test_set_track_rejects_wrong_type(self):
        ed = _make_editor()
        with pytest.raises(TypeError):
            ed.set_track("bad")

    def test_available_tracks_from_provider(self):
        a = _make_track("a")
        b = _make_track("b")
        ed = _make_editor(tracks_provider=lambda: [a, b])
        names = [t.property_name for t in ed.available_tracks()]
        assert names == ["a", "b"]

    def test_available_tracks_falls_back_to_current(self):
        tr = _make_track("only")
        ed = _make_editor(track=tr)
        names = [t.property_name for t in ed.available_tracks()]
        assert names == ["only"]

    def test_available_tracks_provider_error_returns_empty(self):
        def boom():
            raise RuntimeError("boom")
        ed = _make_editor(tracks_provider=boom)
        assert ed.available_tracks() == []


# ===========================================================================
# Keyframe operations
# ===========================================================================


class TestKeyframes:
    def test_add_keyframe(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.5, 2.0)
        assert kf.time == pytest.approx(0.5)
        assert kf.value == pytest.approx(2.0)
        assert ed.selected_keyframe == kf.id

    def test_add_keyframe_no_track_raises(self):
        ed = _make_editor()
        with pytest.raises(RuntimeError):
            ed.add_keyframe(0.0, 0.0)

    def test_delete_keyframe(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.5, 2.0)
        ed.delete_keyframe(kf.id)
        assert tr.keyframes == []
        assert ed.selected_keyframe is None

    def test_delete_missing_keyframe_raises(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        with pytest.raises(KeyError):
            ed.delete_keyframe(9999)

    def test_delete_no_track_raises(self):
        ed = _make_editor()
        with pytest.raises(RuntimeError):
            ed.delete_keyframe(0)

    def test_drag_keyframe_updates_time_and_value(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.drag_keyframe(kf.id, 1.25, 4.75)
        moved = tr.keyframes[0]
        assert moved.time == pytest.approx(1.25)
        assert moved.value == pytest.approx(4.75)
        assert moved.id == kf.id

    def test_drag_no_track_raises(self):
        ed = _make_editor()
        with pytest.raises(RuntimeError):
            ed.drag_keyframe(0, 0.0, 0.0)

    def test_snap_to_grid_time(self):
        tr = _make_track()
        ed = _make_editor(track=tr, grid_time=0.25, grid_value=0.5)
        kf = ed.add_keyframe(0.0, 0.0)
        # 0.37s snaps to 0.25 (nearest quarter), 1.1v snaps to 1.0.
        ed.drag_keyframe(kf.id, 0.37, 1.1, snap=True)
        moved = tr.keyframes[0]
        assert moved.time == pytest.approx(0.25)
        assert moved.value == pytest.approx(1.0)

    def test_snap_to_grid_rounds_up(self):
        tr = _make_track()
        ed = _make_editor(track=tr, grid_time=0.5, grid_value=1.0)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.drag_keyframe(kf.id, 0.76, 1.6, snap=True)
        moved = tr.keyframes[0]
        assert moved.time == pytest.approx(1.0)
        assert moved.value == pytest.approx(2.0)

    def test_no_snap_when_flag_off(self):
        tr = _make_track()
        ed = _make_editor(track=tr, grid_time=0.5, grid_value=0.5)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.drag_keyframe(kf.id, 0.37, 1.13, snap=False)
        moved = tr.keyframes[0]
        assert moved.time == pytest.approx(0.37)
        assert moved.value == pytest.approx(1.13)


# ===========================================================================
# Interpolation samples
# ===========================================================================


class TestInterpolation:
    def test_linear_endpoints(self):
        tr = _make_track()
        _seed_two_key(tr, interp="linear")
        ed = _make_editor(track=tr)
        pts = ed.get_curve_points(sample_rate=30)
        # First / last samples land on the keyframes.
        assert pts[0][1] == pytest.approx(0.0)
        assert pts[-1][1] == pytest.approx(10.0)

    def test_linear_midpoint(self):
        tr = _make_track()
        _seed_two_key(tr, interp="linear")
        ed = _make_editor(track=tr)
        # 60 samples over 1s → sample near middle should be ~5.0.
        pts = ed.get_curve_points(sample_rate=60)
        mid = pts[len(pts) // 2][1]
        assert mid == pytest.approx(5.0, abs=0.2)

    def test_step_holds_earlier(self):
        tr = _make_track()
        _seed_two_key(tr, interp="step")
        ed = _make_editor(track=tr)
        pts = ed.get_curve_points(sample_rate=30)
        # Everything strictly inside the segment holds the earlier value.
        interior = [v for _t, v in pts[1:-1]]
        assert all(v == pytest.approx(0.0) for v in interior)
        assert pts[-1][1] == pytest.approx(10.0)

    def test_hermite_endpoints(self):
        tr = _make_track()
        _seed_two_key(tr, interp="cubic_hermite")
        ed = _make_editor(track=tr)
        pts = ed.get_curve_points(sample_rate=30)
        assert pts[0][1] == pytest.approx(0.0)
        assert pts[-1][1] == pytest.approx(10.0)

    def test_empty_track_returns_empty(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        assert ed.get_curve_points(sample_rate=30) == []

    def test_no_track_returns_empty(self):
        ed = _make_editor()
        assert ed.get_curve_points(sample_rate=30) == []

    def test_sample_rate_positive(self):
        tr = _make_track()
        _seed_two_key(tr)
        ed = _make_editor(track=tr)
        with pytest.raises(ValueError):
            ed.get_curve_points(sample_rate=0)


# ===========================================================================
# Auto-fit / Y range
# ===========================================================================


class TestAutoFit:
    def test_autofit_after_add_keyframe(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.add_keyframe(0.0, -3.0)
        ed.add_keyframe(1.0, 7.0)
        # Autofit inflates by 5% so range strictly contains keyframes.
        assert ed.view.y_min < -3.0
        assert ed.view.y_max > 7.0

    def test_explicit_y_range_disables_autofit(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.set_y_range(-1.0, 2.0)
        assert ed.view.auto_fit is False
        assert ed.view.y_min == pytest.approx(-1.0)
        assert ed.view.y_max == pytest.approx(2.0)

    def test_set_y_range_rejects_inverted(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.set_y_range(1.0, 0.0)

    def test_set_auto_fit_true_refits(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.set_y_range(-100.0, 100.0)
        assert ed.view.auto_fit is False
        tr.add_keyframe(0.0, 0.0)
        tr.add_keyframe(1.0, 1.0)
        ed.set_auto_fit(True)
        assert ed.view.auto_fit is True
        assert ed.view.y_min < 0.0
        assert ed.view.y_max > 1.0

    def test_autofit_constant_curve_inflates(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.add_keyframe(0.0, 3.0)
        ed.add_keyframe(1.0, 3.0)
        # Even a flat curve gets a non-degenerate Y span.
        assert ed.view.y_max > ed.view.y_min


# ===========================================================================
# Zoom / pan
# ===========================================================================


class TestZoom:
    def test_zoom_in(self):
        ed = _make_editor()
        ed.zoom(2.0)
        assert ed.view.zoom == pytest.approx(2.0)

    def test_zoom_out(self):
        ed = _make_editor()
        ed.zoom(0.5)
        assert ed.view.zoom == pytest.approx(0.5)

    def test_zoom_clamped_max(self):
        from pharos_engine.ui.editor.notebook_curve_editor import MAX_ZOOM
        ed = _make_editor()
        # Try to shoot past max in one call.
        ed.zoom(1e6)
        assert ed.view.zoom == pytest.approx(MAX_ZOOM)

    def test_zoom_clamped_min(self):
        from pharos_engine.ui.editor.notebook_curve_editor import MIN_ZOOM
        ed = _make_editor()
        ed.zoom(1e-6)
        assert ed.view.zoom == pytest.approx(MIN_ZOOM)

    def test_zoom_rejects_zero(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.zoom(0.0)

    def test_pan(self):
        ed = _make_editor()
        ed.pan(1.5)
        assert ed.view.pan_time == pytest.approx(1.5)
        ed.pan(-0.5)
        assert ed.view.pan_time == pytest.approx(1.0)

    def test_scroll_zooms(self):
        ed = _make_editor()
        z0 = ed.view.zoom
        ed.on_scroll(1.0)
        assert ed.view.zoom > z0
        ed.on_scroll(-2.0)
        assert ed.view.zoom < z0

    def test_reset_view(self):
        ed = _make_editor()
        ed.zoom(4.0)
        ed.pan(2.0)
        ed.reset_view()
        assert ed.view.zoom == pytest.approx(1.0)
        assert ed.view.pan_time == pytest.approx(0.0)


# ===========================================================================
# Curve palette
# ===========================================================================


class TestCurvePalette:
    def test_set_curve_kind(self):
        ed = _make_editor()
        for kind in ("linear", "step", "hermite", "bezier"):
            ed.set_curve_kind(kind)
            assert ed.curve_kind == kind

    def test_set_curve_kind_rejects_unknown(self):
        ed = _make_editor()
        with pytest.raises(ValueError):
            ed.set_curve_kind("bogus")


# ===========================================================================
# Selection + context menu
# ===========================================================================


class TestSelection:
    def test_select(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.select(None)
        assert ed.selected_keyframe is None
        ed.select(kf.id)
        assert ed.selected_keyframe == kf.id

    def test_select_unknown_raises(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        with pytest.raises(KeyError):
            ed.select(9999)

    def test_select_no_track_raises(self):
        ed = _make_editor()
        with pytest.raises(RuntimeError):
            ed.select(0)


class TestContextMenu:
    def test_open_and_close(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.open_context_menu(kf.id)
        assert ed.context_open is True
        assert ed.context_target == kf.id
        ed.close_context_menu()
        assert ed.context_open is False
        assert ed.context_target is None

    def test_open_unknown_raises(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        with pytest.raises(KeyError):
            ed.open_context_menu(9999)

    def test_open_no_track_raises(self):
        ed = _make_editor()
        with pytest.raises(RuntimeError):
            ed.open_context_menu(0)

    def test_context_delete(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.open_context_menu(kf.id)
        ed.context_delete()
        assert tr.keyframes == []
        assert ed.context_open is False

    def test_context_set_ease(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.open_context_menu(kf.id)
        ed.context_set_ease("step")
        assert tr.keyframes[0].interp == "step"
        assert ed.context_open is False

    def test_context_set_tangent(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.open_context_menu(kf.id)
        ed.context_set_tangent("cubic_hermite")
        assert tr.keyframes[0].interp == "cubic_hermite"
        assert ed.context_open is False

    def test_context_actions_noop_when_closed(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.add_keyframe(0.0, 0.0)
        # Nothing to do — should not raise.
        ed.context_delete()
        ed.context_set_ease("step")
        ed.context_set_tangent("linear")
        assert len(tr.keyframes) == 1


# ===========================================================================
# Mouse input adapters
# ===========================================================================


class TestMouseAdapters:
    def test_double_click_adds_keyframe(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.on_double_click_empty(0.25, 3.14)
        assert kf.time == pytest.approx(0.25)
        assert kf.value == pytest.approx(3.14)

    def test_left_drag_moves(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.on_left_drag(kf.id, 0.9, 4.2)
        assert tr.keyframes[0].time == pytest.approx(0.9)
        assert tr.keyframes[0].value == pytest.approx(4.2)

    def test_left_drag_with_ctrl_snaps(self):
        tr = _make_track()
        ed = _make_editor(track=tr, grid_time=0.5, grid_value=1.0)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.on_left_drag(kf.id, 0.6, 0.4, ctrl=True)
        assert tr.keyframes[0].time == pytest.approx(0.5)
        assert tr.keyframes[0].value == pytest.approx(0.0)

    def test_right_click_opens_context(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        kf = ed.add_keyframe(0.0, 0.0)
        ed.on_right_click(kf.id)
        assert ed.context_open is True

    def test_middle_drag_pans(self):
        ed = _make_editor()
        ed.on_middle_drag(2.5)
        assert ed.view.pan_time == pytest.approx(2.5)


# ===========================================================================
# on_curve_changed callback
# ===========================================================================


class TestCallback:
    def test_notify_on_add(self):
        tr = _make_track("v")
        recorded: list[str] = []
        ed = _make_editor(
            track=tr, on_curve_changed=lambda p: recorded.append(p),
        )
        ed.add_keyframe(0.0, 0.0)
        assert recorded and recorded[-1] == "v"

    def test_notify_on_drag(self):
        tr = _make_track("v")
        recorded: list[str] = []
        ed = _make_editor(
            track=tr, on_curve_changed=lambda p: recorded.append(p),
        )
        kf = ed.add_keyframe(0.0, 0.0)
        recorded.clear()
        ed.drag_keyframe(kf.id, 0.5, 1.0)
        assert recorded == ["v"]

    def test_notify_on_delete(self):
        tr = _make_track("v")
        recorded: list[str] = []
        ed = _make_editor(
            track=tr, on_curve_changed=lambda p: recorded.append(p),
        )
        kf = ed.add_keyframe(0.0, 0.0)
        recorded.clear()
        ed.delete_keyframe(kf.id)
        assert recorded == ["v"]

    def test_notify_isolation(self):
        # A bad callback must not break the mutator.
        def boom(_p):
            raise RuntimeError("boom")
        tr = _make_track("v")
        ed = _make_editor(track=tr, on_curve_changed=boom)
        # Must not raise.
        ed.add_keyframe(0.0, 0.0)


# ===========================================================================
# Hand-drawn preview (diary theme)
# ===========================================================================


class TestHandDrawn:
    def test_hand_drawn_deterministic(self):
        tr1 = _make_track()
        _seed_two_key(tr1)
        ed1 = _make_editor(track=tr1)
        tr2 = _make_track()
        _seed_two_key(tr2)
        ed2 = _make_editor(track=tr2)
        assert ed1.hand_drawn_points(30) == ed2.hand_drawn_points(30)

    def test_hand_drawn_empty_track(self):
        tr = _make_track()
        ed = _make_editor(track=tr)
        assert ed.hand_drawn_points(30) == []

    def test_keyframe_diamonds(self):
        tr = _make_track()
        _seed_two_key(tr)
        ed = _make_editor(track=tr)
        diamonds = ed.keyframe_diamonds()
        assert len(diamonds) == 2
        assert all(len(d) == 3 for d in diamonds)

    def test_keyframe_diamonds_empty(self):
        ed = _make_editor()
        assert ed.keyframe_diamonds() == []


# ===========================================================================
# Headless DPG build smoke
# ===========================================================================


class TestHeadlessDPG:
    def test_build_smokes(self, stub_dpg):
        ed = _make_editor()
        ed.build("parent-tag")
        assert "group" in stub_dpg.calls

    def test_build_with_track(self, stub_dpg):
        tr = _make_track()
        _seed_two_key(tr)
        ed = _make_editor(track=tr)
        ed.build("parent-tag")
        assert "add_text" in stub_dpg.calls or "group" in stub_dpg.calls

    def test_build_rejects_bad_parent(self):
        ed = _make_editor()
        with pytest.raises(TypeError):
            ed.build(3.14)  # type: ignore[arg-type]

    def test_refresh_after_add(self, stub_dpg):
        tr = _make_track()
        ed = _make_editor(track=tr)
        ed.build("parent-tag")
        ed.add_keyframe(0.0, 0.0)
        # Refresh under DPG is a no-crash smoke.
        ed.refresh()
        assert ed.track is tr

    def test_destroy_flips_built(self, stub_dpg):
        ed = _make_editor()
        ed.build("parent-tag")
        ed.destroy()
        # Destroy resets internal built flag; subsequent refresh no-ops.
        ed.refresh()


# ===========================================================================
# Registration
# ===========================================================================


class TestRegistration:
    def test_all_exports_contains_editor(self):
        import pharos_engine.ui.editor as editor_pkg
        assert "NotebookCurveEditor" in editor_pkg.__all__

    def test_lazy_map_has_editor(self):
        import pharos_engine.ui.editor as editor_pkg
        assert "NotebookCurveEditor" in editor_pkg._LAZY_MAP

    def test_lazy_import_yields_class(self):
        from pharos_engine.ui.editor import NotebookCurveEditor
        assert NotebookCurveEditor.__name__ == "NotebookCurveEditor"

    def test_all_list_alphabetical_neighbourhood(self):
        import pharos_engine.ui.editor as editor_pkg
        names = editor_pkg.__all__
        idx = names.index("NotebookCurveEditor")
        assert names[idx - 1] < "NotebookCurveEditor"
        assert names[idx + 1] > "NotebookCurveEditor"

    def test_lazy_map_alphabetical_neighbourhood(self):
        import pharos_engine.ui.editor as editor_pkg
        keys = list(editor_pkg._LAZY_MAP.keys())
        idx = keys.index("NotebookCurveEditor")
        assert keys[idx - 1] < "NotebookCurveEditor"
        assert keys[idx + 1] > "NotebookCurveEditor"


# ===========================================================================
# CurveView
# ===========================================================================


class TestCurveView:
    def test_view_defaults(self):
        from pharos_engine.ui.editor.notebook_curve_editor import CurveView
        v = CurveView()
        assert v.y_min == pytest.approx(0.0)
        assert v.y_max == pytest.approx(1.0)
        assert v.zoom == pytest.approx(1.0)
        assert v.auto_fit is True

    def test_view_degenerate_range_inflated(self):
        from pharos_engine.ui.editor.notebook_curve_editor import CurveView
        v = CurveView(y_min=1.0, y_max=1.0)
        assert v.y_max > v.y_min

    def test_view_rejects_non_finite(self):
        from pharos_engine.ui.editor.notebook_curve_editor import CurveView
        with pytest.raises(ValueError):
            CurveView(y_min=math.nan)

    def test_view_clone(self):
        from pharos_engine.ui.editor.notebook_curve_editor import CurveView
        v = CurveView(y_min=-1.0, y_max=2.0, pan_time=0.5, zoom=2.0)
        c = v.clone()
        assert c is not v
        assert c.y_min == v.y_min
        assert c.y_max == v.y_max
        assert c.pan_time == v.pan_time
        assert c.zoom == v.zoom
        assert c.auto_fit == v.auto_fit
