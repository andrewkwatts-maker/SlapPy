"""Headless tests for RenderTarget, CubeArray, AABB, and _python_convex_hull."""
from __future__ import annotations
import sys
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())


# =============================================================================
# RenderTarget
# =============================================================================

class TestRenderTargetInit:
    def test_init_no_crash(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt is not None

    def test_name_stored(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(name="test_rt")
        assert rt.name == "test_rt"

    def test_position_stored(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(position=(10.0, 20.0))
        assert rt.position == (10.0, 20.0)

    def test_size_stored(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(size=(128, 64))
        assert rt.size == (128, 64)

    def test_no_layers_initially(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.layers == []

    def test_visible_initially(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.visible is True

    def test_z_order_zero(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.z_order == pytest.approx(0.0)

    def test_no_post_process_initially(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.post_process is None


class TestRenderTargetLayers:
    def test_add_layer_returns_layer(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer
        rt = RenderTarget()
        layer = Layer.blank(8, 8)
        result = rt.add_layer(layer)
        assert result is layer

    def test_add_layer_appends_to_list(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer
        rt = RenderTarget()
        layer = Layer.blank(8, 8)
        rt.add_layer(layer)
        assert len(rt.layers) == 1
        assert rt.layers[0] is layer

    def test_add_layer_sets_entity_ref(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer
        rt = RenderTarget()
        layer = Layer.blank(8, 8)
        rt.add_layer(layer)
        assert layer.entity is rt

    def test_remove_layer(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer
        rt = RenderTarget()
        layer = Layer.blank(8, 8)
        rt.add_layer(layer)
        rt.remove_layer(layer)
        assert len(rt.layers) == 0

    def test_add_multiple_layers(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer
        rt = RenderTarget()
        for _ in range(3):
            rt.add_layer(Layer.blank(4, 4))
        assert len(rt.layers) == 3


class TestRenderTargetTick:
    def test_tick_no_crash_no_layers(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        rt.tick(0.016)

    def test_tick_calls_layer_tick(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        layer = MagicMock()
        layer.entity = None
        rt.layers.append(layer)
        rt.tick(0.016)
        layer.tick.assert_called_once_with(0.016)


# =============================================================================
# CubeArray
# =============================================================================

class TestCubeArrayInit:
    def test_init_no_crash(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca is not None

    def test_frame_count_1_initially(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.frame_count == 1

    def test_current_frame_zero(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.current_frame == 0

    def test_fps_24(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.fps == pytest.approx(24.0)

    def test_not_playing_initially(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.playing is False

    def test_loop_true_initially(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.loop is True

    def test_no_animation_graph_initially(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        assert ca.animation_graph is None


class TestCubeArrayPlayback:
    def test_play_sets_playing(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        assert ca.playing is True

    def test_pause_clears_playing(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.play()
        ca.pause()
        assert ca.playing is False

    def test_seek_to_valid_frame(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(5)
        assert ca.current_frame == 5

    def test_seek_clamped_below_zero(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.seek(-5)
        assert ca.current_frame == 0

    def test_seek_clamped_above_max(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 5
        ca.seek(100)
        assert ca.current_frame == 4

    def test_tick_not_playing_no_advance(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.tick(1.0)  # not playing
        assert ca.current_frame == 0

    def test_tick_playing_single_frame_no_advance(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 1
        ca.play()
        ca.tick(1.0)  # only 1 frame — no looping possible
        assert ca.current_frame == 0

    def test_tick_advances_frame_with_loop(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 8
        ca.fps = 8.0  # 1 frame per second
        ca.loop = True
        ca.play()
        ca.tick(1.0)  # should advance 8 frames, wrap to 0
        assert ca.current_frame == 0  # 0 + 8 % 8 = 0

    def test_tick_advances_partial_frame(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 10
        ca.fps = 8.0
        ca.play()
        # 0.5s * 8fps = 4 frames elapsed
        ca.tick(0.5)
        assert ca.current_frame == 4

    def test_tick_no_loop_stops_at_last(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0
        ca.loop = False
        ca.play()
        ca.tick(2.0)  # 8 frames would elapse but capped at 3
        assert ca.current_frame == 3
        assert ca.playing is False

    def test_tick_no_loop_still_at_last_after_more_ticks(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0
        ca.loop = False
        ca.play()
        ca.tick(1.0)
        # After stopping, tick again
        ca.tick(1.0)
        assert ca.current_frame == 3

    def test_tick_loop_wraps_frames(self):
        from slappyengine.cube_array import CubeArray
        ca = CubeArray()
        ca.frame_count = 4
        ca.fps = 4.0
        ca.loop = True
        ca.current_frame = 2
        ca.play()
        ca.tick(1.0)  # 4 frames → (2 + 4) % 4 = 2
        assert ca.current_frame == 2


# =============================================================================
# AABB (from compute.spatial)
# =============================================================================

class TestAABB:
    def test_init(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(min_x=1.0, min_y=2.0, max_x=5.0, max_y=8.0)
        assert aabb.min_x == pytest.approx(1.0)
        assert aabb.max_y == pytest.approx(8.0)

    def test_width(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 5.0)
        assert aabb.width() == pytest.approx(10.0)

    def test_height(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 5.0)
        assert aabb.height() == pytest.approx(5.0)

    def test_center(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 6.0)
        cx, cy = aabb.center()
        assert cx == pytest.approx(5.0)
        assert cy == pytest.approx(3.0)

    def test_contains_inside(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 10.0)
        assert aabb.contains(5.0, 5.0) is True

    def test_contains_outside_x(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 10.0)
        assert aabb.contains(15.0, 5.0) is False

    def test_contains_outside_y(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 10.0)
        assert aabb.contains(5.0, 15.0) is False

    def test_contains_on_boundary(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(0.0, 0.0, 10.0, 10.0)
        assert aabb.contains(0.0, 0.0) is True
        assert aabb.contains(10.0, 10.0) is True

    def test_zero_size_aabb(self):
        from slappyengine.compute.spatial import AABB
        aabb = AABB(5.0, 5.0, 5.0, 5.0)
        assert aabb.width() == pytest.approx(0.0)
        assert aabb.height() == pytest.approx(0.0)


# =============================================================================
# _python_convex_hull (pure Python fallback — no GPU needed)
# =============================================================================

class TestPythonConvexHull:
    def test_empty_returns_empty(self):
        from slappyengine.compute.spatial import _python_convex_hull
        result = _python_convex_hull([])
        assert result == []

    def test_one_point_returns_it(self):
        from slappyengine.compute.spatial import _python_convex_hull
        result = _python_convex_hull([(5.0, 5.0)])
        assert result == [(5.0, 5.0)]

    def test_two_points_returns_them(self):
        from slappyengine.compute.spatial import _python_convex_hull
        pts = [(0.0, 0.0), (1.0, 0.0)]
        result = _python_convex_hull(pts)
        assert len(result) == 2

    def test_triangle_hull_has_3_points(self):
        from slappyengine.compute.spatial import _python_convex_hull
        pts = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
        result = _python_convex_hull(pts)
        assert len(result) == 3

    def test_square_hull_has_4_points(self):
        from slappyengine.compute.spatial import _python_convex_hull
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        result = _python_convex_hull(pts)
        assert len(result) == 4

    def test_interior_point_excluded(self):
        from slappyengine.compute.spatial import _python_convex_hull
        # Square with interior point
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)]
        result = _python_convex_hull(pts)
        assert (0.5, 0.5) not in result

    def test_result_is_list_of_tuples(self):
        from slappyengine.compute.spatial import _python_convex_hull
        pts = [(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)]
        result = _python_convex_hull(pts)
        assert all(isinstance(p, tuple) and len(p) == 2 for p in result)

    def test_collinear_points(self):
        from slappyengine.compute.spatial import _python_convex_hull
        # All collinear — degenerate hull
        pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
        result = _python_convex_hull(pts)
        # Should return at least the endpoints
        xs = [p[0] for p in result]
        assert 0.0 in xs and 3.0 in xs

    def test_hull_vertices_are_subset_of_input(self):
        from slappyengine.compute.spatial import _python_convex_hull
        pts = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0), (2.0, 1.5)]
        result = _python_convex_hull(pts)
        for p in result:
            assert p in pts
