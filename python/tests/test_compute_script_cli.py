"""Headless tests for ComputeLibrary, Script/ScriptComponent, OllamaManager utils, and CLI helpers.

No GPU required — ComputeLibrary uses numpy CPU fallbacks; wgpu is mocked at
module level for track imports.
"""
from __future__ import annotations
import sys
import json
import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

# ---------------------------------------------------------------------------
# Mock wgpu so track.py and asset chain can be imported headlessly
# ---------------------------------------------------------------------------
sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())


# ===========================================================================
# ComputeLibrary
# ===========================================================================

class TestComputeLibraryReduce:
    def test_max(self):
        from slappyengine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce(np.array([1, 5, 3, 2]), "max") == 5.0

    def test_min(self):
        from slappyengine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce(np.array([1, 5, 3, 2]), "min") == 1.0

    def test_sum(self):
        from slappyengine.compute.library import ComputeLibrary
        assert abs(ComputeLibrary.reduce(np.array([1.0, 2.0, 3.0]), "sum") - 6.0) < 1e-9

    def test_mean(self):
        from slappyengine.compute.library import ComputeLibrary
        assert abs(ComputeLibrary.reduce(np.array([2.0, 4.0]), "mean") - 3.0) < 1e-9

    def test_std(self):
        from slappyengine.compute.library import ComputeLibrary
        result = ComputeLibrary.reduce(np.array([0.0, 2.0]), "std")
        assert abs(result - 1.0) < 1e-9

    def test_empty_returns_zero(self):
        from slappyengine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce(np.array([]), "max") == 0.0

    def test_invalid_op_raises(self):
        import pytest
        from slappyengine.compute.library import ComputeLibrary
        with pytest.raises(ValueError):
            ComputeLibrary.reduce(np.array([1, 2]), "badop")

    def test_multidim_array(self):
        from slappyengine.compute.library import ComputeLibrary
        arr = np.array([[1, 2], [3, 4]], dtype=np.float32)
        assert ComputeLibrary.reduce(arr, "max") == 4.0

    def test_returns_float(self):
        from slappyengine.compute.library import ComputeLibrary
        result = ComputeLibrary.reduce(np.array([1, 2, 3]), "mean")
        assert isinstance(result, float)

    def test_single_element(self):
        from slappyengine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce(np.array([7.0]), "max") == 7.0


class TestComputeLibraryConvexHull:
    def test_square_produces_4_vertices(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[0] == 4

    def test_interior_point_excluded(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]], dtype=np.float32)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[0] == 4

    def test_output_is_float32(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float64)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.dtype == np.float32

    def test_two_points_returns_as_is(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 1]], dtype=np.float32)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[0] == 2

    def test_wrong_shape_raises(self):
        import pytest
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([1, 2, 3], dtype=np.float32)
        with pytest.raises(ValueError):
            ComputeLibrary.convex_hull(pts)

    def test_triangle_produces_3_vertices(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [2, 0], [1, 2]], dtype=np.float32)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[0] == 3

    def test_output_shape_2_columns(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
        hull = ComputeLibrary.convex_hull(pts)
        assert hull.shape[1] == 2


class TestComputeLibraryConcaveHull:
    def _circle_pts(self, n=12, r=1.0):
        return np.array(
            [[r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)]
             for i in range(n)],
            dtype=np.float32,
        )

    def test_returns_ndarray(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = self._circle_pts()
        result = ComputeLibrary.concave_hull(pts, alpha=0.5)
        assert isinstance(result, np.ndarray)

    def test_output_is_float32(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = self._circle_pts()
        result = ComputeLibrary.concave_hull(pts, alpha=0.5)
        assert result.dtype == np.float32

    def test_two_columns(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = self._circle_pts()
        result = ComputeLibrary.concave_hull(pts, alpha=0.5)
        assert result.shape[1] == 2

    def test_wrong_shape_raises(self):
        import pytest
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([1, 2, 3], dtype=np.float32)
        with pytest.raises(ValueError):
            ComputeLibrary.concave_hull(pts, alpha=0.5)

    def test_fewer_than_4_falls_back_to_convex(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32)
        result = ComputeLibrary.concave_hull(pts, alpha=0.5)
        assert result.shape[0] == 3

    def test_alpha_zero_approx_convex(self):
        from slappyengine.compute.library import ComputeLibrary
        pts = self._circle_pts(n=8)
        result = ComputeLibrary.concave_hull(pts, alpha=0.0)
        assert result.shape[0] >= 4


class TestComputeLibraryReduceAsync:
    def test_returns_scalar(self):
        from slappyengine.compute.library import ComputeLibrary
        result = ComputeLibrary.reduce_async(np.array([1.0, 2.0, 3.0]), "max")
        assert isinstance(result, float)

    def test_correct_value(self):
        from slappyengine.compute.library import ComputeLibrary
        assert ComputeLibrary.reduce_async(np.array([1.0, 2.0, 3.0]), "max") == 3.0

    def test_no_event_name_no_publish(self):
        from slappyengine.compute.library import ComputeLibrary
        from slappyengine.event_bus import global_bus
        calls = []
        global_bus.subscribe("__test_no_evt__", lambda e: calls.append(e))
        ComputeLibrary.reduce_async(np.array([1.0]), "max", "")
        assert calls == []

    def test_publishes_when_subscriber_present(self):
        from slappyengine.compute.library import ComputeLibrary
        from slappyengine.event_bus import global_bus
        evt_name = "__test_reduce_async_pub__"
        received = []
        # Event dict: {"_event": EventDetails(..., payload={"result": ..., ...})}
        handle = global_bus.subscribe(evt_name,
            lambda e: received.append(e["_event"].payload["result"]))
        try:
            ComputeLibrary.reduce_async(np.array([5.0, 3.0]), "max", evt_name)
            assert len(received) == 1
            assert received[0] == 5.0
        finally:
            global_bus.unsubscribe(evt_name, handle)

    def test_no_publish_when_no_subscribers(self):
        from slappyengine.compute.library import ComputeLibrary
        from slappyengine.event_bus import global_bus
        evt_name = "__test_reduce_async_no_sub__"
        # Ensure no subscribers for this event
        received = []
        result = ComputeLibrary.reduce_async(np.array([9.0]), "max", evt_name)
        assert result == 9.0
        assert received == []


class TestComputeLibraryReduceField:
    def _layer_with_alpha(self, w=4, h=4, alpha=128):
        img = np.zeros((h, w, 4), dtype=np.uint8)
        img[:, :, 3] = alpha

        class L:
            _image_data = img

        return L()

    def test_alpha_mean(self):
        from slappyengine.compute.library import ComputeLibrary
        layer = self._layer_with_alpha(alpha=200)
        assert abs(ComputeLibrary.reduce_field(layer, "alpha", "mean") - 200.0) < 1e-9

    def test_r_channel(self):
        from slappyengine.compute.library import ComputeLibrary
        img = np.zeros((4, 4, 4), dtype=np.uint8)
        img[:, :, 0] = 100  # r=100

        class L:
            _image_data = img

        assert abs(ComputeLibrary.reduce_field(L(), "r", "mean") - 100.0) < 1e-9

    def test_no_image_data_raises(self):
        import pytest
        from slappyengine.compute.library import ComputeLibrary

        class L:
            pass

        with pytest.raises(AttributeError):
            ComputeLibrary.reduce_field(L(), "alpha", "mean")

    def test_data_array_named_field(self):
        from slappyengine.compute.library import ComputeLibrary
        dt = np.dtype([("hp", np.float32)])
        arr = np.array([(1.0,), (3.0,), (5.0,)], dtype=dt)

        class L:
            _data_array = arr

        assert abs(ComputeLibrary.reduce_field(L(), "hp", "mean") - 3.0) < 1e-9


class TestComputeLibrarySetContext:
    def test_set_and_clear_context(self):
        from slappyengine.compute.library import ComputeLibrary
        ComputeLibrary.set_context(None, None, None)
        assert ComputeLibrary._gpu_context is None

    def test_set_context_stores_values(self):
        from slappyengine.compute.library import ComputeLibrary
        fake_ctx = object()
        fake_stats = object()
        ComputeLibrary.set_context(fake_ctx, stats=fake_stats)
        assert ComputeLibrary._gpu_context is fake_ctx
        assert ComputeLibrary._stats_compute is fake_stats
        ComputeLibrary.set_context(None)


class TestMonotoneChain:
    def test_square(self):
        from slappyengine.compute.library import _monotone_chain
        pts = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
        hull = _monotone_chain(pts)
        assert len(hull) == 4

    def test_collinear_three(self):
        from slappyengine.compute.library import _monotone_chain
        pts = np.array([[0, 0], [1, 0], [2, 0]], dtype=np.float64)
        hull = _monotone_chain(pts)
        # Collinear — expect degenerate hull (2 unique points)
        assert len(hull) >= 2


class TestCircumradius:
    def test_right_triangle(self):
        from slappyengine.compute.library import _circumradius
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([0.0, 1.0])
        r = _circumradius(a, b, c)
        assert abs(r - math.sqrt(2) / 2.0) < 1e-6

    def test_degenerate_collinear_returns_inf(self):
        from slappyengine.compute.library import _circumradius
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([2.0, 0.0])
        r = _circumradius(a, b, c)
        assert r == math.inf


# ===========================================================================
# Script / ScriptComponent
# ===========================================================================

class TestScript:
    def test_instantiates(self):
        from slappyengine.script import Script
        s = Script()
        assert s is not None

    def test_on_start_no_op(self):
        from slappyengine.script import Script
        Script().on_start(None)  # should not raise

    def test_on_update_no_op(self):
        from slappyengine.script import Script
        Script().on_update(None, 0.016)

    def test_on_event_no_op(self):
        from slappyengine.script import Script
        Script().on_event(None, "test_event")

    def test_on_destroy_no_op(self):
        from slappyengine.script import Script
        Script().on_destroy(None)

    def test_on_collision_no_op(self):
        from slappyengine.script import Script
        Script().on_collision(None, None)

    def test_subclass_override(self):
        from slappyengine.script import Script
        results = []

        class MyScript(Script):
            def on_update(self, entity, dt):
                results.append(dt)

        s = MyScript()
        s.on_update(None, 0.05)
        assert results == [0.05]


class TestScriptComponent:
    def _entity(self):
        class E:
            pass

        return E()

    def test_instantiates(self):
        from slappyengine.script import ScriptComponent
        sc = ScriptComponent()
        assert sc is not None

    def test_entity_none_initially(self):
        from slappyengine.script import ScriptComponent
        sc = ScriptComponent()
        assert sc.entity is None

    def test_on_attach_sets_entity(self):
        from slappyengine.script import ScriptComponent
        sc = ScriptComponent()
        e = self._entity()
        sc.on_attach(e)
        assert sc.entity is e

    def test_on_detach_clears_entity(self):
        from slappyengine.script import ScriptComponent
        sc = ScriptComponent()
        e = self._entity()
        sc.on_attach(e)
        sc.on_detach(e)
        assert sc.entity is None

    def test_update_calls_on_update(self):
        from slappyengine.script import ScriptComponent
        ticks = []

        class Ticking(ScriptComponent):
            def on_update(self, entity, dt):
                ticks.append(dt)

        sc = Ticking()
        e = self._entity()
        sc.on_attach(e)
        sc.update(0.016)
        assert ticks == [0.016]

    def test_update_no_op_when_no_entity(self):
        from slappyengine.script import ScriptComponent
        sc = ScriptComponent()
        sc.update(0.1)  # should not raise; entity is None

    def test_on_attach_calls_on_start(self):
        from slappyengine.script import ScriptComponent
        started = []

        class S(ScriptComponent):
            def on_start(self, entity):
                started.append(entity)

        e = self._entity()
        S().on_attach(e)
        assert len(started) == 1
        assert started[0] is e

    def test_on_detach_calls_on_destroy(self):
        from slappyengine.script import ScriptComponent
        destroyed = []

        class S(ScriptComponent):
            def on_destroy(self, entity):
                destroyed.append(entity)

        sc = S()
        e = self._entity()
        sc.on_attach(e)
        sc.on_detach(e)
        assert len(destroyed) == 1


# ===========================================================================
# OllamaManager utility functions
# ===========================================================================

class TestLoadSaveAiSettings:
    def test_load_missing_returns_empty(self):
        from slappyengine.ai.ollama_manager import load_ai_settings
        import slappyengine.ai.ollama_manager as m
        orig = m._SETTINGS_FILE
        m._SETTINGS_FILE = Path(tempfile.mkdtemp()) / "nonexistent.json"
        try:
            result = load_ai_settings()
            assert result == {}
        finally:
            m._SETTINGS_FILE = orig

    def test_save_and_reload(self):
        from slappyengine.ai.ollama_manager import load_ai_settings, save_ai_settings
        import slappyengine.ai.ollama_manager as m
        td = tempfile.mkdtemp()
        orig_file = m._SETTINGS_FILE
        orig_dir = m._SETTINGS_DIR
        m._SETTINGS_DIR = Path(td)
        m._SETTINGS_FILE = Path(td) / "ai_settings.json"
        try:
            save_ai_settings({"model": "test", "enabled": True})
            data = load_ai_settings()
            assert data["model"] == "test"
            assert data["enabled"] is True
        finally:
            m._SETTINGS_FILE = orig_file
            m._SETTINGS_DIR = orig_dir

    def test_save_creates_file(self):
        from slappyengine.ai.ollama_manager import save_ai_settings
        import slappyengine.ai.ollama_manager as m
        td = tempfile.mkdtemp()
        target = Path(td) / "sub" / "ai_settings.json"
        orig_file = m._SETTINGS_FILE
        orig_dir = m._SETTINGS_DIR
        m._SETTINGS_DIR = target.parent
        m._SETTINGS_FILE = target
        try:
            save_ai_settings({"x": 1})
            assert target.exists()
        finally:
            m._SETTINGS_FILE = orig_file
            m._SETTINGS_DIR = orig_dir

    def test_load_invalid_json_returns_empty(self):
        from slappyengine.ai.ollama_manager import load_ai_settings
        import slappyengine.ai.ollama_manager as m
        td = tempfile.mkdtemp()
        bad = Path(td) / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        orig = m._SETTINGS_FILE
        m._SETTINGS_FILE = bad
        try:
            result = load_ai_settings()
            assert result == {}
        finally:
            m._SETTINGS_FILE = orig


class TestOllamaManagerConstants:
    def test_default_model(self):
        from slappyengine.ai.ollama_manager import OllamaManager
        assert OllamaManager.DEFAULT_MODEL == "qwen2.5-coder:7b"

    def test_percent_re_matches(self):
        from slappyengine.ai.ollama_manager import _PERCENT_RE
        m = _PERCENT_RE.search("downloading 42%")
        assert m is not None
        assert m.group(1) == "42"

    def test_percent_re_no_match(self):
        from slappyengine.ai.ollama_manager import _PERCENT_RE
        assert _PERCENT_RE.search("no percentage") is None

    def test_percent_re_100(self):
        from slappyengine.ai.ollama_manager import _PERCENT_RE
        m = _PERCENT_RE.search("100%")
        assert m.group(1) == "100"

    def test_is_ollama_installed_returns_bool(self):
        from slappyengine.ai.ollama_manager import OllamaManager
        result = OllamaManager().is_ollama_installed()
        assert isinstance(result, bool)


# ===========================================================================
# CLI helpers
# ===========================================================================

class TestBuildParser:
    def _p(self):
        from slappyengine.cli import _build_parser
        return _build_parser()

    def test_instantiates(self):
        p = self._p()
        assert p is not None

    def test_info_subcommand(self):
        args = self._p().parse_args(["info"])
        assert args.command == "info"

    def test_new_name(self):
        args = self._p().parse_args(["new", "myproject"])
        assert args.name == "myproject"

    def test_new_default_template(self):
        args = self._p().parse_args(["new", "foo"])
        assert args.template == "blank"

    def test_new_custom_template(self):
        args = self._p().parse_args(["new", "foo", "--template", "2d"])
        assert args.template == "2d"

    def test_build_target_exe(self):
        args = self._p().parse_args(["build", "--target", "exe"])
        assert args.target == "exe"

    def test_build_release_default_false(self):
        args = self._p().parse_args(["build", "--target", "web"])
        assert args.release is False

    def test_build_release_flag(self):
        args = self._p().parse_args(["build", "--target", "exe", "--release"])
        assert args.release is True

    def test_run_default_project_none(self):
        args = self._p().parse_args(["run"])
        assert args.project is None


class TestFindProjectFile:
    def test_finds_in_directory(self):
        from slappyengine.cli import _find_project_file
        td = tempfile.mkdtemp()
        (Path(td) / "project.slap_proj").write_text("{}")
        found = _find_project_file(td)
        assert found.name == "project.slap_proj"

    def test_accepts_direct_file_path(self):
        from slappyengine.cli import _find_project_file
        td = tempfile.mkdtemp()
        proj = Path(td) / "project.slap_proj"
        proj.write_text("{}")
        found = _find_project_file(str(proj))
        assert found == proj.resolve()

    def test_missing_calls_die(self):
        import pytest
        from slappyengine.cli import _find_project_file
        td = tempfile.mkdtemp()
        with pytest.raises(SystemExit):
            _find_project_file(td)

    def test_none_uses_cwd_or_die(self):
        import pytest
        from slappyengine.cli import _find_project_file
        # Unless we're in a directory with project.slap_proj, this should fail
        td = tempfile.mkdtemp()
        import os
        orig = os.getcwd()
        os.chdir(td)
        try:
            with pytest.raises(SystemExit):
                _find_project_file(None)
        finally:
            os.chdir(orig)


# ===========================================================================
# SplineTrack (headless — PIL rasterisation only)
# ===========================================================================

class TestSplineTrack:
    def _spline(self):
        from slappyengine.spline import CatmullRomSpline
        return CatmullRomSpline(
            [(0, 0), (200, 0), (200, 200), (0, 200)], closed=True
        )

    def test_instantiates(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), width=60, canvas_size=(128, 128), segments=8)
        assert t is not None

    def test_road_width_stored(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), width=80, canvas_size=(64, 64), segments=4)
        assert t.road_width == 80

    def test_canvas_size_stored(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), canvas_size=(256, 128), segments=4)
        assert t.canvas_size == (256, 128)

    def test_segments_stored(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), segments=12, canvas_size=(64, 64))
        assert t.segments == 12

    def test_road_color_stored(self):
        from slappyengine.track import SplineTrack
        color = (100, 100, 80, 255)
        t = SplineTrack(self._spline(), road_color=color, canvas_size=(64, 64), segments=4)
        assert t.road_color == color

    def test_rebuild_no_crash(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), canvas_size=(64, 64), segments=4)
        t.rebuild()  # should not raise

    def test_has_layer(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), canvas_size=(64, 64), segments=4)
        assert t._layer is not None

    def test_edge_points_length_matches_segments(self):
        from slappyengine.track import SplineTrack
        n = 6
        t = SplineTrack(self._spline(), canvas_size=(64, 64), segments=n)
        lp, rp, lk, rk, ctr = t._edge_points()
        assert len(lp) == n
        assert len(rp) == n

    def test_z_height_zero(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), canvas_size=(64, 64), segments=4)
        assert t.z_height == 0.0

    def test_no_road_texture_by_default(self):
        from slappyengine.track import SplineTrack
        t = SplineTrack(self._spline(), canvas_size=(64, 64), segments=4)
        assert t._road_tex is None
