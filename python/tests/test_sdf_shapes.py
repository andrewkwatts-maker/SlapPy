"""Engine tests for SdfCanvas — CPU rasterizer path (no GPU)."""
from __future__ import annotations
import numpy as np
import pytest


def _make_layer(w=64, h=64):
    """Fake layer with a black RGBA image_data array."""
    class _FakeLayer:
        pass
    layer = _FakeLayer()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    return layer


class TestSdfCanvasInit:
    def test_init_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        assert canvas is not None

    def test_shapes_empty_initially(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        assert len(canvas._shapes) == 0


class TestSdfCanvasShapeBuilders:
    def test_circle_adds_shape(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.circle(center=(32.0, 32.0), radius=10.0)
        assert len(canvas._shapes) == 1

    def test_circle_returns_self_for_chaining(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        result = canvas.circle((32.0, 32.0), 10.0)
        assert result is canvas

    def test_box_adds_shape(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.box(center=(32.0, 32.0), size=(20.0, 10.0))
        assert len(canvas._shapes) == 1

    def test_box_returns_self(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        assert canvas.box((0.0, 0.0), (10.0, 10.0)) is canvas

    def test_segment_adds_shape(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.segment(a=(0.0, 0.0), b=(32.0, 32.0), thickness=2.0)
        assert len(canvas._shapes) == 1

    def test_segment_returns_self(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        assert canvas.segment((0.0, 0.0), (10.0, 10.0)) is canvas

    def test_ring_adds_shape(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.ring(center=(32.0, 32.0), radius=15.0, thickness=3.0)
        assert len(canvas._shapes) == 1

    def test_ring_returns_self(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        assert canvas.ring((0.0, 0.0), 10.0, 2.0) is canvas

    def test_method_chaining(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.circle((32.0, 32.0), 5.0).box((10.0, 10.0), (8.0, 8.0)).ring((50.0, 50.0), 4.0, 1.0)
        assert len(canvas._shapes) == 3


class TestSdfCanvasClear:
    def test_clear_removes_all_shapes(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.circle((32.0, 32.0), 10.0)
        canvas.box((10.0, 10.0), (5.0, 5.0))
        canvas.clear()
        assert len(canvas._shapes) == 0

    def test_clear_on_empty_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.clear()


class TestSdfCanvasFlush:
    def test_flush_empty_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.flush()

    def test_flush_clears_shapes(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.circle((32.0, 32.0), 10.0)
        canvas.flush()
        assert len(canvas._shapes) == 0

    def test_flush_circle_paints_center_pixel(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32.0, 32.0), radius=8.0,
                      color=(1.0, 0.0, 0.0, 1.0))
        canvas.flush()
        # Center pixel should be painted red (R channel > 0)
        assert int(layer._image_data[32, 32, 0]) > 0

    def test_flush_circle_leaves_corners_black(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32.0, 32.0), radius=5.0,
                      color=(1.0, 1.0, 1.0, 1.0))
        canvas.flush()
        # Corner pixels should be untouched (alpha=0)
        assert int(layer._image_data[0, 0, 3]) == 0

    def test_flush_box_paints_center(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.box(center=(32.0, 32.0), size=(20.0, 20.0),
                   color=(0.0, 1.0, 0.0, 1.0))
        canvas.flush()
        assert int(layer._image_data[32, 32, 1]) > 0  # green channel

    def test_flush_ring_hollow_center(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.ring(center=(32.0, 32.0), radius=12.0, thickness=2.0,
                    color=(0.0, 0.0, 1.0, 1.0))
        canvas.flush()
        # Center of ring should remain black (inside the hollow)
        assert int(layer._image_data[32, 32, 2]) < 50  # blue channel mostly absent at center

    def test_flush_multiple_shapes_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(128, 128)
        canvas = SdfCanvas(layer)
        canvas.circle((64.0, 64.0), 20.0, color=(1.0, 0.0, 0.0, 1.0))
        canvas.box((20.0, 20.0), (10.0, 10.0), color=(0.0, 1.0, 0.0, 1.0))
        canvas.segment((0.0, 0.0), (128.0, 128.0), thickness=2.0)
        canvas.ring((100.0, 100.0), 15.0, thickness=3.0)
        canvas.flush()

    def test_flush_glow_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32.0, 32.0), radius=8.0,
                      color=(1.0, 1.0, 0.0, 1.0),
                      glow_color=(1.0, 0.5, 0.0, 0.8),
                      glow_radius=6.0)
        canvas.flush()

    def test_flush_shadow_no_crash(self):
        from slappyengine.sdf_shapes import SdfCanvas
        layer = _make_layer(64, 64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32.0, 32.0), radius=8.0,
                      shadow_alpha=0.5, shadow_offset=(3.0, 3.0))
        canvas.flush()


class TestSdfShapeKinds:
    def test_circle_kind_is_zero(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.circle((0.0, 0.0), 5.0)
        assert canvas._shapes[0].kind == 0

    def test_box_kind_is_one(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.box((0.0, 0.0), (10.0, 10.0))
        assert canvas._shapes[0].kind == 1

    def test_segment_kind_is_two(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.segment((0.0, 0.0), (10.0, 10.0))
        assert canvas._shapes[0].kind == 2

    def test_ring_kind_is_three(self):
        from slappyengine.sdf_shapes import SdfCanvas
        canvas = SdfCanvas(_make_layer())
        canvas.ring((0.0, 0.0), 10.0, 2.0)
        assert canvas._shapes[0].kind == 3
