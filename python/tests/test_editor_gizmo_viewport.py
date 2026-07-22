"""Headless tests for GizmoOverlay and ViewportPanel pure Python logic.

Covers:
- slappyengine.ui.editor.gizmo_overlay  (GizmoOverlay class constants + pure-Python API)
- slappyengine.ui.editor.viewport_panel (_look_at, _make_blank_pixels, ViewportPanel)

DPG guard: force a safe MagicMock so panel methods can be called headlessly.
"""
from __future__ import annotations
import sys
import math
import unittest.mock

# ---------------------------------------------------------------------------
# DPG mock — prevents segfault from dearpygui without a viewport context.
# ---------------------------------------------------------------------------
_DPG_MOCK = unittest.mock.MagicMock()
_DPG_MOCK.does_item_exist.return_value = False
if 'dearpygui.dearpygui' not in sys.modules:
    sys.modules['dearpygui'] = unittest.mock.MagicMock()
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK
else:
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK


# ---------------------------------------------------------------------------
# Module-level helpers in viewport_panel
# ---------------------------------------------------------------------------

class TestLookAt:
    def test_returns_16_elements(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        assert len(result) == 16

    def test_all_floats(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        assert all(isinstance(v, float) for v in result)

    def test_last_element_is_one(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        assert result[15] == 1.0

    def test_col3_w_is_zero(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        # column-major: col 3 starts at index 12; last row of col 3 = index 15
        assert result[3] == 0.0    # row 3 of col 0
        assert result[7] == 0.0    # row 3 of col 1
        assert result[11] == 0.0   # row 3 of col 2

    def test_identity_look_along_neg_z(self):
        """Looking from +Z toward origin — right-hand convention gives identity-like rotation."""
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        # Right (rx, ry, rz) should be approximately (1, 0, 0)
        assert abs(result[0] - 1.0) < 1e-9   # rx
        assert abs(result[1]) < 1e-9          # ry
        assert abs(result[2]) < 1e-9          # rz

    def test_up_vector_col1(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        # True-up col1: (ux, uy, uz, 0)  ≈  (0, 1, 0, 0)
        assert abs(result[4]) < 1e-9          # ux
        assert abs(result[5] - 1.0) < 1e-9   # uy
        assert abs(result[6]) < 1e-9          # uz

    def test_forward_col2_neg_z(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        # -forward (col 2): (0, 0, 1, 0)  i.e. -(-Z) = +Z
        assert abs(result[8]) < 1e-9          # -fx
        assert abs(result[9]) < 1e-9          # -fy
        assert abs(result[10] - 1.0) < 1e-9   # -fz (pointing away from origin)

    def test_non_trivial_eye(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([3, 4, 5], [1, 1, 1], [0, 1, 0])
        assert len(result) == 16
        # Orthogonality: dot(col0, col1) ≈ 0
        dot = result[0]*result[4] + result[1]*result[5] + result[2]*result[6]
        assert abs(dot) < 1e-9

    def test_rotation_submatrix_columns_unit(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        result = _look_at([2, 3, 4], [0, 0, 0], [0, 1, 0])
        col0_len = math.sqrt(result[0]**2 + result[1]**2 + result[2]**2)
        col1_len = math.sqrt(result[4]**2 + result[5]**2 + result[6]**2)
        col2_len = math.sqrt(result[8]**2 + result[9]**2 + result[10]**2)
        assert abs(col0_len - 1.0) < 1e-9
        assert abs(col1_len - 1.0) < 1e-9
        assert abs(col2_len - 1.0) < 1e-9

    def test_translation_components_present(self):
        from slappyengine.ui.editor.viewport_panel import _look_at
        # Camera at (0,0,5) looking at origin — tx=0, ty=0, tz=-5
        result = _look_at([0, 0, 5], [0, 0, 0], [0, 1, 0])
        assert abs(result[12]) < 1e-9          # tx = 0
        assert abs(result[13]) < 1e-9          # ty = 0
        assert abs(result[14] - (-5.0)) < 1e-9  # tz = dot(forward=(0,0,-1), eye=(0,0,5)) = -5


class TestMakeBlankPixels:
    def test_length_1x1(self):
        from slappyengine.ui.editor.viewport_panel import _make_blank_pixels
        result = _make_blank_pixels(1, 1)
        assert len(result) == 4

    def test_length_2x3(self):
        from slappyengine.ui.editor.viewport_panel import _make_blank_pixels
        result = _make_blank_pixels(2, 3)
        assert len(result) == 24

    def test_length_formula(self):
        from slappyengine.ui.editor.viewport_panel import _make_blank_pixels
        w, h = 320, 240
        result = _make_blank_pixels(w, h)
        assert len(result) == w * h * 4

    def test_all_zeros(self):
        from slappyengine.ui.editor.viewport_panel import _make_blank_pixels
        result = _make_blank_pixels(4, 4)
        assert all(v == 0.0 for v in result)

    def test_returns_list(self):
        from slappyengine.ui.editor.viewport_panel import _make_blank_pixels
        result = _make_blank_pixels(10, 10)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ViewportPanel — __init__ and pure-Python methods
# ---------------------------------------------------------------------------

class TestViewportPanelInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p is not None

    def test_stores_width(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=800, height=600)
        assert p._width == 800

    def test_stores_height(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=800, height=600)
        assert p._height == 600

    def test_pixel_data_length(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=4, height=4)
        assert len(p._pixel_data) == 4 * 4 * 4

    def test_pixel_data_all_zero(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=4, height=4)
        assert all(v == 0.0 for v in p._pixel_data)

    def test_default_mode_2d(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._mode == "2D"

    def test_default_cam_yaw(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._cam_yaw == 0.0

    def test_default_cam_pitch(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._cam_pitch == 30.0

    def test_default_cam_distance(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._cam_distance == 5.0

    def test_default_cam_target(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._cam_target == [0.0, 0.0, 0.0]

    def test_default_cam_fov(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._cam_fov == 60.0

    def test_texture_tag(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._texture_tag == "viewport_texture"

    def test_image_tag(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._image_tag == "viewport_image"

    def test_dragging_left_false(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._dragging_left is False

    def test_dragging_right_false(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        assert p._dragging_right is False


class TestViewportPanelGetSize:
    def test_returns_tuple(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_size()
        assert isinstance(result, tuple)

    def test_returns_width_height(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=640, height=480)
        assert p.get_size() == (640, 480)

    def test_custom_dimensions(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1920, height=1080)
        assert p.get_size() == (1920, 1080)


class TestViewportPanelSetMode:
    def test_set_mode_3d(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        p.set_mode("3D")
        assert p._mode == "3D"

    def test_set_mode_2d(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        p.set_mode("3D")
        p.set_mode("2D")
        assert p._mode == "2D"

    def test_invalid_mode_raises_valueerror(self):
        import pytest
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        with pytest.raises(ValueError):
            p.set_mode("isometric")

    def test_invalid_mode_empty_string(self):
        import pytest
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        with pytest.raises(ValueError):
            p.set_mode("")

    def test_set_mode_resets_drag_left(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        p._dragging_left = True
        p.set_mode("3D")
        assert p._dragging_left is False

    def test_set_mode_resets_drag_right(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        p._dragging_right = True
        p.set_mode("2D")
        assert p._dragging_right is False


class TestViewportPanelGetViewMatrix:
    def test_returns_16_elements(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_view_matrix()
        assert len(result) == 16

    def test_all_floats(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_view_matrix()
        assert all(isinstance(v, float) for v in result)

    def test_last_element_one(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_view_matrix()
        assert result[15] == 1.0

    def test_changes_with_yaw(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p1 = ViewportPanel(engine=None, width=1280, height=720)
        p1._cam_yaw = 0.0
        m1 = p1.get_view_matrix()

        p2 = ViewportPanel(engine=None, width=1280, height=720)
        p2._cam_yaw = 90.0
        m2 = p2.get_view_matrix()

        assert m1 != m2

    def test_changes_with_distance(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p1 = ViewportPanel(engine=None, width=1280, height=720)
        p1._cam_distance = 5.0
        m1 = p1.get_view_matrix()

        p2 = ViewportPanel(engine=None, width=1280, height=720)
        p2._cam_distance = 10.0
        m2 = p2.get_view_matrix()

        assert m1 != m2


class TestViewportPanelGetProjMatrix:
    def test_returns_16_elements(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_proj_matrix(aspect=16/9)
        assert len(result) == 16

    def test_all_floats(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_proj_matrix(aspect=16/9)
        assert all(isinstance(v, float) for v in result)

    def test_col2_w_is_neg_one(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_proj_matrix(aspect=1.0)
        # col 2 row 3 (index 11) = -1
        assert result[11] == -1.0

    def test_col3_z_is_zero(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        result = p.get_proj_matrix(aspect=1.0)
        # col 3 row 3 (index 15) = 0 (not 1 — perspective divide)
        assert result[15] == 0.0

    def test_aspect_ratio_affects_col0(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        m_wide = p.get_proj_matrix(aspect=2.0)
        m_square = p.get_proj_matrix(aspect=1.0)
        # f/aspect for col 0 should differ
        assert m_wide[0] != m_square[0]

    def test_col1_same_for_any_aspect(self):
        from slappyengine.ui.editor.viewport_panel import ViewportPanel
        p = ViewportPanel(engine=None, width=1280, height=720)
        m_wide = p.get_proj_matrix(aspect=2.0)
        m_square = p.get_proj_matrix(aspect=1.0)
        # f (col1[0,0]) does not depend on aspect
        assert m_wide[5] == m_square[5]


# ---------------------------------------------------------------------------
# GizmoOverlay — class constants
# ---------------------------------------------------------------------------

class TestGizmoOverlayConstants:
    def test_handle_radius(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.HANDLE_RADIUS == 8

    def test_arrow_len(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.ARROW_LEN == 50

    def test_rotate_radius(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.ROTATE_RADIUS == 45

    def test_scale_handle_size(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.SCALE_HANDLE_SIZE == 10

    def test_color_x_is_red(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        r, g, b, a = GizmoOverlay.COLOR_X
        assert r > 200
        assert g < 150
        assert b < 150

    def test_color_y_is_green(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        r, g, b, a = GizmoOverlay.COLOR_Y
        assert r < 150
        assert g > 200
        assert b < 150

    def test_color_z_is_blue(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        r, g, b, a = GizmoOverlay.COLOR_Z
        assert r < 150
        assert b > 200

    def test_color_center_tuple_length(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert len(GizmoOverlay.COLOR_CENTER) == 4

    def test_color_hover_is_white(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        r, g, b, a = GizmoOverlay.COLOR_HOVER
        assert r == 255 and g == 255 and b == 255

    def test_color_bbox_tuple_length(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert len(GizmoOverlay.COLOR_BBOX) == 4

    def test_arrow_3d_len(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.ARROW_3D_LEN == 40

    def test_ring_3d_rx(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.RING_3D_RX == 36

    def test_ring_3d_cr(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        assert GizmoOverlay.RING_3D_CR == 36


# ---------------------------------------------------------------------------
# GizmoOverlay — __init__ defaults
# ---------------------------------------------------------------------------

class TestGizmoOverlayInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g is not None

    def test_entity_none(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._entity is None

    def test_camera_none(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._camera is None

    def test_default_tool_select(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._tool == "select"

    def test_default_vp_w(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._vp_w == 1280

    def test_default_vp_h(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._vp_h == 720

    def test_dragging_none(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._dragging is None

    def test_drag_start_mouse(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._drag_start_mouse == (0.0, 0.0)

    def test_drag_start_entity_pos(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._drag_start_entity_pos == (0.0, 0.0)

    def test_drag_start_entity_rot(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._drag_start_entity_rot == 0.0

    def test_drag_start_entity_scale(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._drag_start_entity_scale == (1.0, 1.0)

    def test_dl_tag(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._dl_tag == "gizmo_drawlist"

    def test_mouse_zero(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._mouse == (0.0, 0.0)

    def test_mode_3d_false(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        assert g._mode_3d is False


# ---------------------------------------------------------------------------
# GizmoOverlay — pure-Python public API
# ---------------------------------------------------------------------------

class TestGizmoOverlayPublicAPI:
    def test_set_entity(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay

        class FakeEntity:
            x, y = 10.0, 20.0

        g = GizmoOverlay()
        e = FakeEntity()
        g.set_entity(e)
        assert g._entity is e

    def test_set_entity_none(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay

        class FakeEntity:
            pass

        g = GizmoOverlay()
        g.set_entity(FakeEntity())
        g.set_entity(None)
        assert g._entity is None

    def test_set_camera(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay

        class FakeCamera:
            pass

        g = GizmoOverlay()
        c = FakeCamera()
        g.set_camera(c)
        assert g._camera is c

    def test_set_tool_translate(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_tool("translate")
        assert g._tool == "translate"

    def test_set_tool_rotate(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_tool("rotate")
        assert g._tool == "rotate"

    def test_set_tool_scale(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_tool("scale")
        assert g._tool == "scale"

    def test_set_tool_clears_dragging(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g._dragging = "x"
        g.set_tool("rotate")
        assert g._dragging is None

    def test_set_tool_same_tool_does_not_clear_dragging(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g._dragging = "x"
        g.set_tool("select")  # already "select"
        # dragging should still be "x" since tool didn't change
        assert g._dragging == "x"

    def test_set_mode_3d(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_mode("3D")
        assert g._mode_3d is True

    def test_set_mode_2d(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_mode("3D")
        g.set_mode("2D")
        assert g._mode_3d is False

    def test_set_mode_other_value(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_mode("iso")
        assert g._mode_3d is False

    def test_set_viewport_size(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_viewport_size(1920, 1080)
        assert g._vp_w == 1920
        assert g._vp_h == 1080

    def test_set_viewport_size_small(self):
        from slappyengine.ui.editor.gizmo_overlay import GizmoOverlay
        g = GizmoOverlay()
        g.set_viewport_size(320, 240)
        assert g._vp_w == 320
        assert g._vp_h == 240
