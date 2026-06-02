"""Tests for ComputeLibrary CPU fallback paths."""
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# reduce
# ---------------------------------------------------------------------------

def test_reduce_max():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([1.0, 5.0, 3.0, 2.0])
    assert ComputeLibrary.reduce(arr, "max") == pytest.approx(5.0)


def test_reduce_min():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([1.0, 5.0, 3.0, 2.0])
    assert ComputeLibrary.reduce(arr, "min") == pytest.approx(1.0)


def test_reduce_sum():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([1.0, 2.0, 3.0])
    assert ComputeLibrary.reduce(arr, "sum") == pytest.approx(6.0)


def test_reduce_mean():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([2.0, 4.0, 6.0])
    assert ComputeLibrary.reduce(arr, "mean") == pytest.approx(4.0)


def test_reduce_std():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    expected = float(np.std(arr))
    assert ComputeLibrary.reduce(arr, "std") == pytest.approx(expected, rel=1e-5)


def test_reduce_unknown_op():
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(ValueError, match="Unknown op"):
        ComputeLibrary.reduce(np.array([1.0]), "median")


def test_reduce_2d_array():
    from slappyengine.compute.library import ComputeLibrary
    arr = np.array([[1.0, 2.0], [3.0, 4.0]])
    assert ComputeLibrary.reduce(arr, "max") == pytest.approx(4.0)


def test_reduce_empty():
    from slappyengine.compute.library import ComputeLibrary
    assert ComputeLibrary.reduce(np.array([]), "max") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# convex_hull
# ---------------------------------------------------------------------------

def test_convex_hull_square():
    from slappyengine.compute.library import ComputeLibrary
    pts = np.array([
        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
        [0.5, 0.5],  # interior point
    ], dtype=np.float32)
    hull = ComputeLibrary.convex_hull(pts)
    assert len(hull) == 4, f"Expected 4 hull points, got {len(hull)}"


def test_convex_hull_collinear():
    from slappyengine.compute.library import ComputeLibrary
    # Only 2 points (degenerate)
    pts = np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float32)
    hull = ComputeLibrary.convex_hull(pts)
    assert len(hull) >= 2


def test_convex_hull_wrong_shape():
    from slappyengine.compute.library import ComputeLibrary
    with pytest.raises(ValueError):
        ComputeLibrary.convex_hull(np.array([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# concave_hull
# ---------------------------------------------------------------------------

def test_concave_hull_returns_array():
    from slappyengine.compute.library import ComputeLibrary
    rng = np.random.default_rng(42)
    pts = rng.uniform(0, 100, (50, 2)).astype(np.float32)
    hull = ComputeLibrary.concave_hull(pts, alpha=0.3)
    assert hull.ndim == 2 and hull.shape[1] == 2
    assert len(hull) >= 3


def test_concave_hull_small():
    from slappyengine.compute.library import ComputeLibrary
    pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]], dtype=np.float32)
    hull = ComputeLibrary.concave_hull(pts, alpha=0.5)
    assert len(hull) >= 3


# ---------------------------------------------------------------------------
# reduce_field
# ---------------------------------------------------------------------------

class FakeLayer:
    def __init__(self):
        # 4×4 RGBA image, alpha = 128 for all pixels
        self._image_data = np.full((4, 4, 4), 128, dtype=np.uint8)
        self._data_array = None


def test_reduce_field_alpha():
    from slappyengine.compute.library import ComputeLibrary
    layer = FakeLayer()
    val = ComputeLibrary.reduce_field(layer, field="alpha", op="mean")
    assert val == pytest.approx(128.0, abs=0.01)


def test_reduce_field_r():
    from slappyengine.compute.library import ComputeLibrary
    layer = FakeLayer()
    layer._image_data[:, :, 0] = 200  # red channel
    val = ComputeLibrary.reduce_field(layer, field="r", op="max")
    assert val == pytest.approx(200.0)


def test_reduce_field_no_data():
    from slappyengine.compute.library import ComputeLibrary

    class Empty:
        _image_data = None
        _data_array = None

    with pytest.raises(AttributeError):
        ComputeLibrary.reduce_field(Empty(), field="alpha")


def test_reduce_field_structured_array():
    from slappyengine.compute.library import ComputeLibrary

    class StructLayer:
        _image_data = None
        _data_array = np.array(
            [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
            dtype=[("health", "f4"), ("shield", "f4")],
        )

    val = ComputeLibrary.reduce_field(StructLayer(), field="health", op="sum")
    assert val == pytest.approx(9.0, abs=0.01)
