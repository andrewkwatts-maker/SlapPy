"""Engine tests for CatmullRomSpline — headless, no GPU."""
from __future__ import annotations
import math
import pytest


def _square_spline():
    from pharos_engine.spline import CatmullRomSpline
    pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    return CatmullRomSpline(pts, closed=True)


class TestCatmullRomSplineSample:
    def test_sample_t0_at_first_point(self):
        spline = _square_spline()
        x, y = spline.sample(0.0)
        assert x == pytest.approx(0.0, abs=1.0)
        assert y == pytest.approx(0.0, abs=1.0)

    def test_sample_t025_near_second_point(self):
        spline = _square_spline()
        x, y = spline.sample(0.25)
        # At t=0.25 we should be near (100, 0)
        assert x == pytest.approx(100.0, abs=5.0)
        assert y == pytest.approx(0.0, abs=5.0)

    def test_sample_returns_float_tuple(self):
        spline = _square_spline()
        result = spline.sample(0.5)
        assert len(result) == 2
        assert isinstance(result[0], float)

    def test_sample_t1_same_as_t0_closed(self):
        spline = _square_spline()
        # Closed spline: t=1 should be very close to t=0
        x0, y0 = spline.sample(0.0)
        x1, y1 = spline.sample(1.0)
        assert abs(x0 - x1) < 2.0
        assert abs(y0 - y1) < 2.0

    def test_sample_all_t_no_crash(self):
        spline = _square_spline()
        for i in range(101):
            spline.sample(i / 100.0)


class TestCatmullRomSplineTangent:
    def test_tangent_is_normalized(self):
        spline = _square_spline()
        for t in [0.0, 0.25, 0.5, 0.75]:
            tx, ty = spline.tangent(t)
            mag = math.hypot(tx, ty)
            assert mag == pytest.approx(1.0, abs=0.01)

    def test_tangent_along_straight_segment(self):
        spline = _square_spline()
        # At t=0.125, we're approximately mid-way on the first horizontal segment
        tx, ty = spline.tangent(0.125)
        # Tangent should be mostly horizontal (rightward)
        assert abs(tx) > abs(ty)


class TestCatmullRomSplineNormal:
    def test_normal_perpendicular_to_tangent(self):
        spline = _square_spline()
        for t in [0.0, 0.25, 0.5, 0.75]:
            tx, ty = spline.tangent(t)
            nx, ny = spline.normal(t)
            dot = tx * nx + ty * ny
            assert dot == pytest.approx(0.0, abs=0.01)


class TestCatmullRomSplineLength:
    def test_length_positive(self):
        spline = _square_spline()
        assert spline.length() > 0.0

    def test_length_roughly_perimeter(self):
        spline = _square_spline()
        # Catmull-Rom overshoots control points — length > geometric perimeter (400)
        assert spline.length() > 300.0

    def test_longer_spline_has_larger_length(self):
        from pharos_engine.spline import CatmullRomSpline
        small = CatmullRomSpline([(0, 0), (50, 0), (50, 50), (0, 50)], closed=True)
        big = CatmullRomSpline([(0, 0), (200, 0), (200, 200), (0, 200)], closed=True)
        assert big.length() > small.length()


class TestCatmullRomSplineUniformSamples:
    def test_uniform_samples_count(self):
        spline = _square_spline()
        pts = spline.uniform_samples(10)
        assert len(pts) == 10

    def test_uniform_samples_are_tuples(self):
        spline = _square_spline()
        pts = spline.uniform_samples(4)
        for pt in pts:
            assert len(pt) == 2

    def test_uniform_ts_count(self):
        spline = _square_spline()
        ts = spline.uniform_ts(12)
        assert len(ts) == 12

    def test_uniform_ts_in_range(self):
        spline = _square_spline()
        ts = spline.uniform_ts(20)
        for t in ts:
            assert 0.0 <= t <= 1.0

    def test_uniform_ts_monotone(self):
        spline = _square_spline()
        ts = spline.uniform_ts(16)
        assert ts == sorted(ts)

    def test_uniform_samples_count_zero_no_crash(self):
        spline = _square_spline()
        pts = spline.uniform_samples(0)
        assert pts == []


class TestCatmullRomSplineOpenCurve:
    def test_open_spline_no_crash(self):
        from pharos_engine.spline import CatmullRomSpline
        pts = [(0.0, 0.0), (50.0, 25.0), (100.0, 0.0)]
        spline = CatmullRomSpline(pts, closed=False)
        spline.sample(0.0)
        spline.sample(0.5)

    def test_open_spline_has_length(self):
        from pharos_engine.spline import CatmullRomSpline
        pts = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
        spline = CatmullRomSpline(pts, closed=False)
        assert spline.length() > 0.0


class TestCatmullRomSplineTension:
    def test_different_tension_different_curve(self):
        from pharos_engine.spline import CatmullRomSpline
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        s1 = CatmullRomSpline(pts, tension=0.0)
        s2 = CatmullRomSpline(pts, tension=1.0)
        x1, y1 = s1.sample(0.125)
        x2, y2 = s2.sample(0.125)
        # Different tensions should produce different midpoints
        assert abs(x1 - x2) > 0.5 or abs(y1 - y2) > 0.5
