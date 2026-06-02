"""Headless tests for track_tools — export_track_boundary, generate_track_decal_mask, _sample_spline."""
from __future__ import annotations
import numpy as np
import pytest
from pathlib import Path


class _MockSpline:
    def __init__(self, pts=None):
        self._pts = pts if pts is not None else [
            (0.0, 0.0), (100.0, 0.0), (200.0, 50.0), (100.0, 100.0), (0.0, 50.0)
        ]

    def sample_points(self, n=256):
        if not self._pts:
            return []
        step = max(1, len(self._pts) // n)
        return self._pts[::step][:n]


class _EvaluateSpline:
    def evaluate(self, t):
        return (t * 300.0, t * 200.0)


class _ControlPointSpline:
    control_points = [(0, 0), (100, 50), (200, 0)]


class _IterableSpline:
    def __iter__(self):
        return iter([(10.0, 20.0), (30.0, 40.0), (50.0, 60.0)])


# =============================================================================
# export_track_boundary
# =============================================================================

class TestExportTrackBoundary:
    def test_creates_file(self, tmp_path):
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(256, 256))
        assert Path(out).exists()

    def test_returns_string_path(self, tmp_path):
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        result = export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(256, 256))
        assert isinstance(result, str)

    def test_returns_absolute_path(self, tmp_path):
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        result = export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(256, 256))
        assert Path(result).is_absolute()

    def test_output_is_rgba_png(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(128, 128))
        img = Image.open(out)
        assert img.mode == "RGBA"

    def test_canvas_size_respected(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(320, 240))
        img = Image.open(out)
        assert img.size == (320, 240)

    def test_alpha_channel_has_road_pixels(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=40.0, out_png=out, canvas_size=(256, 256))
        img = Image.open(out)
        arr = np.array(img)
        alpha = arr[:, :, 3]
        # Road pixels have alpha=0, off-road have alpha=255
        assert 0 in alpha  # some road pixels exist

    def test_alpha_channel_has_off_road_pixels(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=10.0, out_png=out, canvas_size=(256, 256))
        img = Image.open(out)
        arr = np.array(img)
        alpha = arr[:, :, 3]
        assert 255 in alpha  # off-road pixels exist

    def test_empty_spline_all_off_road(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline(pts=[])
        out = str(tmp_path / "boundary_empty.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(64, 64))
        img = Image.open(out)
        arr = np.array(img)
        alpha = arr[:, :, 3]
        # All pixels should be off-road (alpha=255)
        assert alpha.min() == 255

    def test_rgb_channels_are_zero(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(128, 128))
        img = Image.open(out)
        arr = np.array(img)
        assert arr[:, :, 0].max() == 0  # R = 0
        assert arr[:, :, 1].max() == 0  # G = 0
        assert arr[:, :, 2].max() == 0  # B = 0

    def test_creates_parent_dirs(self, tmp_path):
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        nested = str(tmp_path / "a" / "b" / "c" / "boundary.png")
        export_track_boundary(spline, width=30.0, out_png=nested, canvas_size=(64, 64))
        assert Path(nested).exists()

    def test_wide_track_produces_road_pixels(self, tmp_path):
        from PIL import Image
        from slappyengine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "wide.png")
        export_track_boundary(spline, width=30.0, out_png=out, canvas_size=(256, 256))
        arr = np.array(Image.open(out))
        road_pixels = (arr[:, :, 3] == 0).sum()
        assert road_pixels > 0


# =============================================================================
# generate_track_decal_mask
# =============================================================================

class TestGenerateTrackDecalMask:
    def test_returns_ndarray(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=30.0)
        assert isinstance(mask, np.ndarray)

    def test_returns_boolean_dtype(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=30.0)
        assert mask.dtype == bool

    def test_returns_2d_array(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=30.0)
        assert mask.ndim == 2

    def test_has_true_pixels_for_track(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=30.0)
        assert mask.any()  # some road pixels

    def test_has_false_pixels_for_narrow_track(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=5.0)
        assert not mask.all()  # not all pixels are road

    def test_empty_spline_returns_100x100_false(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline(pts=[])
        mask = generate_track_decal_mask(spline, width=30.0)
        assert mask.shape == (100, 100)
        assert not mask.any()

    def test_wider_track_more_true_pixels(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        narrow = generate_track_decal_mask(spline, width=5.0)
        wide = generate_track_decal_mask(spline, width=80.0)
        assert wide.sum() > narrow.sum()

    def test_margin_increases_road_coverage(self):
        from slappyengine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        no_margin = generate_track_decal_mask(spline, width=20.0, margin=0.0)
        big_margin = generate_track_decal_mask(spline, width=20.0, margin=50.0)
        assert big_margin.sum() > no_margin.sum()


# =============================================================================
# _sample_spline — interface dispatch
# =============================================================================

class TestSampleSpline:
    def test_sample_points_interface(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _MockSpline()
        pts = _sample_spline(spline, n=5)
        assert len(pts) > 0

    def test_returns_list_of_tuples(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _MockSpline()
        pts = _sample_spline(spline)
        assert isinstance(pts, list)
        for p in pts:
            assert isinstance(p, tuple)
            assert len(p) == 2

    def test_evaluate_interface(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _EvaluateSpline()
        pts = _sample_spline(spline, n=10)
        assert len(pts) == 10

    def test_evaluate_interface_values(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _EvaluateSpline()
        pts = _sample_spline(spline, n=2)
        # t=0 → (0.0, 0.0); t=1 → (300.0, 200.0)
        assert pts[0] == (pytest.approx(0.0), pytest.approx(0.0))
        assert pts[-1] == (pytest.approx(300.0), pytest.approx(200.0))

    def test_control_points_interface(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _ControlPointSpline()
        pts = _sample_spline(spline)
        assert len(pts) == 3
        assert (0.0, 0.0) in pts

    def test_iterable_interface(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _IterableSpline()
        pts = _sample_spline(spline)
        assert len(pts) == 3
        assert (10.0, 20.0) in pts

    def test_no_interface_returns_empty(self):
        from slappyengine.tools.track_tools import _sample_spline
        result = _sample_spline(object())
        assert result == []

    def test_all_values_are_floats(self):
        from slappyengine.tools.track_tools import _sample_spline
        spline = _ControlPointSpline()
        pts = _sample_spline(spline)
        for x, y in pts:
            assert isinstance(x, float)
            assert isinstance(y, float)
