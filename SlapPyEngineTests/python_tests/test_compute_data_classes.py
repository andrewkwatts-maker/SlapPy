"""Engine tests for pure-Python data classes in compute subpackage.
AABB (compute/spatial.py), StatsResult (compute/stats.py),
EffectShader (compute/effect.py), _FILTER_OP_* constants (compute/mutator.py).
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# AABB
# ---------------------------------------------------------------------------

class TestAABB:
    def test_instantiates(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(min_x=0.0, min_y=0.0, max_x=10.0, max_y=5.0)
        assert a is not None

    def test_width(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 5.0)
        assert a.width() == pytest.approx(10.0)

    def test_height(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 5.0)
        assert a.height() == pytest.approx(5.0)

    def test_center(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 6.0)
        cx, cy = a.center()
        assert cx == pytest.approx(5.0)
        assert cy == pytest.approx(3.0)

    def test_contains_interior_point(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 10.0)
        assert a.contains(5.0, 5.0) is True

    def test_contains_boundary_point(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 10.0)
        assert a.contains(0.0, 0.0) is True
        assert a.contains(10.0, 10.0) is True

    def test_does_not_contain_exterior_point(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(0.0, 0.0, 10.0, 10.0)
        assert a.contains(11.0, 5.0) is False

    def test_zero_width_aabb(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(5.0, 0.0, 5.0, 10.0)
        assert a.width() == pytest.approx(0.0)

    def test_negative_coords(self):
        from slappyengine.compute.spatial import AABB
        a = AABB(-10.0, -5.0, 0.0, 0.0)
        assert a.width() == pytest.approx(10.0)
        assert a.height() == pytest.approx(5.0)
        assert a.contains(-5.0, -2.5) is True


# ---------------------------------------------------------------------------
# StatsResult
# ---------------------------------------------------------------------------

class TestStatsResult:
    def test_instantiates(self):
        from slappyengine.compute.stats import StatsResult
        r = StatsResult()
        assert r is not None

    def test_default_mean_zero(self):
        from slappyengine.compute.stats import StatsResult
        r = StatsResult()
        assert r.mean == pytest.approx(0.0)

    def test_default_sum_zero(self):
        from slappyengine.compute.stats import StatsResult
        assert StatsResult().sum == pytest.approx(0.0)

    def test_default_min_zero(self):
        from slappyengine.compute.stats import StatsResult
        assert StatsResult().min == pytest.approx(0.0)

    def test_default_max_zero(self):
        from slappyengine.compute.stats import StatsResult
        assert StatsResult().max == pytest.approx(0.0)

    def test_default_count_zero(self):
        from slappyengine.compute.stats import StatsResult
        assert StatsResult().count == 0

    def test_default_std_zero(self):
        from slappyengine.compute.stats import StatsResult
        assert StatsResult().std == pytest.approx(0.0)

    def test_requested_ops_empty_list(self):
        from slappyengine.compute.stats import StatsResult
        r = StatsResult()
        assert r.requested_ops == []

    def test_custom_values(self):
        from slappyengine.compute.stats import StatsResult
        r = StatsResult(mean=3.5, sum=35.0, min=1.0, max=10.0, count=10, std=2.5)
        assert r.mean == pytest.approx(3.5)
        assert r.count == 10

    def test_requested_ops_mutable(self):
        from slappyengine.compute.stats import StatsResult
        r = StatsResult(requested_ops=["mean", "min"])
        assert "mean" in r.requested_ops


# ---------------------------------------------------------------------------
# EffectShader
# ---------------------------------------------------------------------------

class TestEffectShader:
    def test_instantiates(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// dummy shader")
        assert es is not None

    def test_wgsl_stored(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="@compute fn main() {}")
        assert es.wgsl == "@compute fn main() {}"

    def test_default_blend_normal(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// shader")
        assert es.blend == "normal"

    def test_default_label(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// shader")
        assert es.label == "effect"

    def test_custom_blend(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// shader", blend="additive")
        assert es.blend == "additive"

    def test_custom_label(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// shader", label="FireEffect")
        assert es.label == "FireEffect"

    def test_pipeline_initially_none(self):
        from slappyengine.compute.effect import EffectShader
        es = EffectShader(wgsl="// shader")
        assert es._pipeline is None


# ---------------------------------------------------------------------------
# PixelMutator filter op constants
# ---------------------------------------------------------------------------

class TestMutatorConstants:
    def test_filter_op_tag(self):
        from slappyengine.compute.mutator import _FILTER_OP_TAG
        assert _FILTER_OP_TAG == 0

    def test_filter_op_gt(self):
        from slappyengine.compute.mutator import _FILTER_OP_GT
        assert _FILTER_OP_GT == 1

    def test_filter_op_lt(self):
        from slappyengine.compute.mutator import _FILTER_OP_LT
        assert _FILTER_OP_LT == 2

    def test_filter_op_eq(self):
        from slappyengine.compute.mutator import _FILTER_OP_EQ
        assert _FILTER_OP_EQ == 3

    def test_constants_unique(self):
        from slappyengine.compute.mutator import (
            _FILTER_OP_TAG, _FILTER_OP_GT, _FILTER_OP_LT, _FILTER_OP_EQ
        )
        vals = [_FILTER_OP_TAG, _FILTER_OP_GT, _FILTER_OP_LT, _FILTER_OP_EQ]
        assert len(set(vals)) == 4


# ---------------------------------------------------------------------------
# compute/readback.py — module-level import check only
# ---------------------------------------------------------------------------

class TestReadbackModuleImport:
    def test_importable(self):
        from slappyengine.compute.readback import ReadbackBuffer
        assert ReadbackBuffer is not None


# ---------------------------------------------------------------------------
# compute/spatial.py — SpatialCompute importable
# ---------------------------------------------------------------------------

class TestSpatialComputeImport:
    def test_importable(self):
        from slappyengine.compute.spatial import SpatialCompute
        assert SpatialCompute is not None


# ---------------------------------------------------------------------------
# compute/asset_compute.py — import + StatsResult + AABB re-exported
# ---------------------------------------------------------------------------

class TestAssetComputeImport:
    def test_importable(self):
        from slappyengine.compute.asset_compute import AssetComputeAPI
        assert AssetComputeAPI is not None

    def test_stats_result_re_exported(self):
        from slappyengine.compute.asset_compute import StatsResult
        assert StatsResult is not None

    def test_aabb_re_exported(self):
        from slappyengine.compute.asset_compute import AABB
        assert AABB is not None
