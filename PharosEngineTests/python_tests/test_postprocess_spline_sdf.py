"""Engine tests for post_process/chain.py (extras), post_process/volumetric_fog.py,
post_process/taa.py, post_process/shadow_csm.py, spline.py, and sdf_shapes.py.
All headless — no GPU required.
"""
from __future__ import annotations
import math
import struct
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# post_process/chain.py — PostProcessPass, PostProcessChain, named subclasses
# ---------------------------------------------------------------------------

class TestPostProcessPass:
    def test_instantiates(self):
        from pharos_engine.post_process.chain import PostProcessPass
        p = PostProcessPass(shader_path="blur.wgsl")
        assert p is not None

    def test_defaults(self):
        from pharos_engine.post_process.chain import PostProcessPass
        p = PostProcessPass(shader_path="blur.wgsl")
        assert p.params == {}
        assert p.label == ""
        assert p.enabled is True
        assert p.entry_point == "main"
        assert p.raw_params_bytes is None

    def test_custom_values(self):
        from pharos_engine.post_process.chain import PostProcessPass
        p = PostProcessPass(shader_path="blur.wgsl", params={"r": 3}, label="blur",
                            enabled=False, entry_point="my_main")
        assert p.params["r"] == 3
        assert p.label == "blur"
        assert p.enabled is False
        assert p.entry_point == "my_main"


class TestPostProcessChain:
    def test_instantiates_empty(self):
        from pharos_engine.post_process.chain import PostProcessChain
        c = PostProcessChain()
        assert c is not None
        assert c.passes == []

    def test_instantiates_with_passes(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        p = PostProcessPass(shader_path="blur.wgsl", label="blur", enabled=True)
        c = PostProcessChain([p])
        assert len(c.passes) == 1

    def test_add_pass(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        c = PostProcessChain()
        p = PostProcessPass(shader_path="test.wgsl", label="test")
        c.add(p)
        assert len(c.passes) == 1

    def test_remove_by_label(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        c = PostProcessChain()
        c.add(PostProcessPass(shader_path="a.wgsl", label="a"))
        c.add(PostProcessPass(shader_path="b.wgsl", label="b"))
        c.remove("a")
        labels = [p.label for p in c.passes]
        assert "a" not in labels
        assert "b" in labels

    def test_passes_excludes_disabled(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        c = PostProcessChain()
        c.add(PostProcessPass(shader_path="a.wgsl", label="a", enabled=True))
        c.add(PostProcessPass(shader_path="b.wgsl", label="b", enabled=False))
        assert len(c.passes) == 1

    def test_add_blur(self):
        from pharos_engine.post_process.chain import PostProcessChain
        c = PostProcessChain()
        p = c.add_blur(radius=4)
        assert p.label == "blur"
        assert p.params["radius"] == 4
        assert len(c.passes) == 1

    def test_add_pixelate(self):
        from pharos_engine.post_process.chain import PostProcessChain
        c = PostProcessChain()
        p = c.add_pixelate(block_size=8)
        assert p.label == "pixelate"
        assert p.params["block_size"] == 8

    def test_add_outline(self):
        from pharos_engine.post_process.chain import PostProcessChain
        c = PostProcessChain()
        p = c.add_outline(color=(0.0, 1.0, 0.0, 1.0), threshold=0.2)
        assert p.label == "outline"
        assert p.params["outline_g"] == pytest.approx(1.0)
        assert p.params["threshold"] == pytest.approx(0.2)

    def test_add_gravity_warp(self):
        from pharos_engine.post_process.chain import PostProcessChain
        c = PostProcessChain()
        p = c.add_gravity_warp(center=(0.3, 0.7), strength=2.0, radius=0.4)
        assert p.label == "gravity_warp"
        assert p.params["center_x"] == pytest.approx(0.3)
        assert p.params["center_y"] == pytest.approx(0.7)


class TestNamedPasses:
    def test_chromatic_aberration_defaults(self):
        from pharos_engine.post_process.chain import ChromaticAberrationPass
        ca = ChromaticAberrationPass()
        assert ca.strength == pytest.approx(0.005)
        assert ca.label == "chromatic_aberration"

    def test_chromatic_aberration_custom_strength(self):
        from pharos_engine.post_process.chain import ChromaticAberrationPass
        ca = ChromaticAberrationPass(strength=0.01)
        assert ca.strength == pytest.approx(0.01)

    def test_chromatic_aberration_strength_setter(self):
        from pharos_engine.post_process.chain import ChromaticAberrationPass
        ca = ChromaticAberrationPass()
        ca.strength = 0.02
        assert ca.strength == pytest.approx(0.02)
        assert ca.params["strength"] == pytest.approx(0.02)

    def test_vignette_defaults(self):
        from pharos_engine.post_process.chain import VignettePass
        v = VignettePass()
        assert v.strength == pytest.approx(0.4)
        assert v.label == "vignette"

    def test_vignette_strength_setter(self):
        from pharos_engine.post_process.chain import VignettePass
        v = VignettePass()
        v.strength = 0.8
        assert v.strength == pytest.approx(0.8)

    def test_film_grain_defaults(self):
        from pharos_engine.post_process.chain import FilmGrainPass
        fg = FilmGrainPass()
        assert fg.strength == pytest.approx(0.025)
        assert fg.label == "film_grain"

    def test_bloom_defaults(self):
        from pharos_engine.post_process.chain import BloomPass
        b = BloomPass()
        assert b.intensity == pytest.approx(1.0)
        assert b.label == "bloom"
        assert b.params["threshold"] == pytest.approx(0.7)

    def test_bloom_intensity_setter(self):
        from pharos_engine.post_process.chain import BloomPass
        b = BloomPass()
        b.intensity = 2.5
        assert b.intensity == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# post_process/volumetric_fog.py — VolumetricFog
# ---------------------------------------------------------------------------

class TestVolumetricFog:
    def test_instantiates(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        vf = VolumetricFog()
        assert vf is not None

    def test_defaults(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        vf = VolumetricFog()
        assert vf.density == pytest.approx(0.02)
        assert vf.scatter == pytest.approx(0.5)
        assert vf.absorption == pytest.approx(0.01)
        assert vf.phase_g == pytest.approx(0.3)
        assert vf.num_steps == 64
        assert vf.max_dist == pytest.approx(500.0)
        assert vf.fog_start == pytest.approx(1.0)
        assert vf.ambient == pytest.approx(0.1)
        assert vf.sun_intensity == pytest.approx(1.0)

    def test_label(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        assert VolumetricFog.label == "volumetric_fog"

    def test_custom_values(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        vf = VolumetricFog(density=0.1, num_steps=32)
        assert vf.density == pytest.approx(0.1)
        assert vf.num_steps == 32

    def test_make_pass_returns_post_process_pass(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        from pharos_engine.post_process.chain import PostProcessPass
        vf = VolumetricFog()
        p = vf.make_pass()
        assert isinstance(p, PostProcessPass)

    def test_make_pass_has_raw_params(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        vf = VolumetricFog()
        p = vf.make_pass()
        assert isinstance(p.raw_params_bytes, bytes)
        assert len(p.raw_params_bytes) > 0

    def test_make_pass_label_matches(self):
        from pharos_engine.post_process.volumetric_fog import VolumetricFog
        vf = VolumetricFog()
        p = vf.make_pass()
        assert p.label == "volumetric_fog"

    def test_identity_mat4(self):
        from pharos_engine.post_process.volumetric_fog import _IDENTITY_MAT4
        assert len(_IDENTITY_MAT4) == 16
        assert _IDENTITY_MAT4[0] == pytest.approx(1.0)
        assert _IDENTITY_MAT4[5] == pytest.approx(1.0)
        assert _IDENTITY_MAT4[10] == pytest.approx(1.0)
        assert _IDENTITY_MAT4[15] == pytest.approx(1.0)
        assert _IDENTITY_MAT4[1] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# post_process/taa.py — TAAPass
# ---------------------------------------------------------------------------

class TestTAAPass:
    def test_instantiates(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass()
        assert t is not None

    def test_defaults(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass()
        assert t.alpha == pytest.approx(0.1)
        assert t.motion_weight == pytest.approx(1.0)
        # sharpening = max(0, variance_clip_gamma - 1) = max(0, 1-1) = 0
        assert t.sharpening == pytest.approx(0.0)

    def test_label(self):
        from pharos_engine.post_process.taa import TAAPass
        assert TAAPass.label == "taa"

    def test_variance_clip_gamma_above_one(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass(variance_clip_gamma=1.5)
        assert t.sharpening == pytest.approx(0.5)

    def test_variance_clip_gamma_below_one(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass(variance_clip_gamma=0.5)
        # sharpening = max(0, 0.5-1) = 0
        assert t.sharpening == pytest.approx(0.0)

    def test_make_pass_returns_post_process_pass(self):
        from pharos_engine.post_process.taa import TAAPass
        from pharos_engine.post_process.chain import PostProcessPass
        t = TAAPass()
        p = t.make_pass("frame", "history", "motion")
        assert isinstance(p, PostProcessPass)

    def test_make_pass_has_raw_bytes(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass()
        p = t.make_pass("frame", "history", "motion")
        assert isinstance(p.raw_params_bytes, bytes)
        assert len(p.raw_params_bytes) == 16  # 4 fields × 4 bytes

    def test_make_pass_label(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass()
        p = t.make_pass(None, None, None)
        assert p.label == "taa"

    def test_make_pass_textures_in_params(self):
        from pharos_engine.post_process.taa import TAAPass
        t = TAAPass()
        p = t.make_pass("ft", "ht", "mt")
        assert p.params["frame_tex"] == "ft"
        assert p.params["history_tex"] == "ht"
        assert p.params["motion_tex"] == "mt"


# ---------------------------------------------------------------------------
# post_process/shadow_csm.py — ShadowCSM
# ---------------------------------------------------------------------------

class TestShadowCSM:
    def test_instantiates(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        s = ShadowCSM()
        assert s is not None

    def test_defaults(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        s = ShadowCSM()
        assert s.num_cascades == 4
        assert s.pcss_enabled is True
        assert s.light_size == pytest.approx(0.05)
        assert s.near == pytest.approx(0.1)
        assert s.depth_bias == pytest.approx(0.005)
        assert s.pcf_radius == pytest.approx(1.5)

    def test_label(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        assert ShadowCSM.label == "shadow_csm"

    def test_custom_values(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        s = ShadowCSM(num_cascades=3, pcss_enabled=False, depth_bias=0.01)
        assert s.num_cascades == 3
        assert s.pcss_enabled is False
        assert s.depth_bias == pytest.approx(0.01)

    def test_make_pass_returns_post_process_pass(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        from pharos_engine.post_process.chain import PostProcessPass
        s = ShadowCSM()
        p = s.make_pass()
        assert isinstance(p, PostProcessPass)

    def test_make_pass_has_raw_bytes(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        s = ShadowCSM()
        p = s.make_pass()
        assert isinstance(p.raw_params_bytes, bytes)
        assert len(p.raw_params_bytes) > 0

    def test_make_pass_label(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        s = ShadowCSM()
        p = s.make_pass()
        assert p.label == "shadow_csm"

    def test_default_split_dists(self):
        from pharos_engine.post_process.shadow_csm import ShadowCSM, _DEFAULT_SPLIT_DISTS
        assert len(_DEFAULT_SPLIT_DISTS) == 4
        assert _DEFAULT_SPLIT_DISTS[0] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# spline.py — CatmullRomSpline
# ---------------------------------------------------------------------------

_SQUARE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


class TestCatmullRomSplineDefaults:
    def test_instantiates(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        assert s is not None

    def test_closed_default(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        assert s.closed is True

    def test_tension_default(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        assert s.tension == pytest.approx(0.5)

    def test_points_stored(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        assert s.points == _SQUARE

    def test_total_length_positive(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        assert s.length() > 0

    def test_open_spline(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE, closed=False)
        assert s.closed is False


class TestCatmullRomSplineSample:
    def test_sample_returns_tuple(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        pt = s.sample(0.0)
        assert len(pt) == 2

    def test_sample_at_zero_is_first_point(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        pt = s.sample(0.0)
        # At t=0, should be near the first control point
        assert abs(pt[0] - _SQUARE[0][0]) < 1.0
        assert abs(pt[1] - _SQUARE[0][1]) < 1.0

    def test_sample_multiple_t_values(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        for t in [0.0, 0.25, 0.5, 0.75]:
            pt = s.sample(t)
            assert isinstance(pt[0], float)
            assert isinstance(pt[1], float)

    def test_uniform_samples_count(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        pts = s.uniform_samples(8)
        assert len(pts) == 8

    def test_uniform_ts_count(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        ts = s.uniform_ts(10)
        assert len(ts) == 10

    def test_uniform_ts_monotone(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        ts = s.uniform_ts(8)
        for i in range(len(ts) - 1):
            assert ts[i] <= ts[i + 1]


class TestCatmullRomSplineTangentNormal:
    def test_tangent_returns_tuple(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        tx, ty = s.tangent(0.0)
        assert isinstance(tx, float) and isinstance(ty, float)

    def test_tangent_is_unit_length(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        for t in [0.1, 0.3, 0.6, 0.9]:
            tx, ty = s.tangent(t)
            mag = math.hypot(tx, ty)
            assert mag == pytest.approx(1.0, abs=1e-4)

    def test_normal_perpendicular_to_tangent(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        for t in [0.1, 0.4, 0.7]:
            tx, ty = s.tangent(t)
            nx, ny = s.normal(t)
            dot = tx * nx + ty * ny
            assert abs(dot) < 1e-4

    def test_normal_returns_tuple(self):
        from pharos_engine.spline import CatmullRomSpline
        s = CatmullRomSpline(_SQUARE)
        nx, ny = s.normal(0.5)
        assert isinstance(nx, float) and isinstance(ny, float)


# ---------------------------------------------------------------------------
# sdf_shapes.py — SdfCanvas CPU rasterizer
# ---------------------------------------------------------------------------

def _make_layer(w=64, h=64):
    """Create a minimal mock layer for SdfCanvas tests."""
    import numpy as np

    class FakeLayer:
        def __init__(self):
            self._image_data = np.zeros((h, w, 4), dtype=np.uint8)
            self._device = None
            self._texture = None

    return FakeLayer()


class TestSdfCanvasInstantiation:
    def test_instantiates(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        assert canvas is not None

    def test_empty_shapes(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        assert canvas._shapes == []

    def test_flush_empty_no_crash(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.flush()  # should not raise


class TestSdfCanvasCircle:
    def test_circle_adds_shape(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32, 32), radius=10)
        assert len(canvas._shapes) == 1

    def test_circle_kind_zero(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32, 32), radius=10)
        assert canvas._shapes[0].kind == 0

    def test_circle_flush_writes_pixels(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer(w=64, h=64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32, 32), radius=10, color=(1.0, 0.0, 0.0, 1.0))
        canvas.flush()
        # Center pixel should be non-zero red
        assert layer._image_data[32, 32, 0] > 0

    def test_circle_clears_after_flush(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32, 32), radius=10)
        canvas.flush()
        assert len(canvas._shapes) == 0

    def test_chaining(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        result = canvas.circle(center=(32, 32), radius=5)
        assert result is canvas


class TestSdfCanvasBox:
    def test_box_adds_shape(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.box(center=(32, 32), size=(20, 10))
        assert len(canvas._shapes) == 1

    def test_box_kind_one(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.box(center=(32, 32), size=(20, 10))
        assert canvas._shapes[0].kind == 1

    def test_box_flush_writes_pixels(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer(w=64, h=64)
        canvas = SdfCanvas(layer)
        canvas.box(center=(32, 32), size=(20, 10), color=(0.0, 1.0, 0.0, 1.0))
        canvas.flush()
        assert layer._image_data[32, 32, 1] > 0  # green channel


class TestSdfCanvasSegment:
    def test_segment_adds_shape(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.segment(a=(10, 10), b=(50, 50), thickness=2.0)
        assert len(canvas._shapes) == 1

    def test_segment_kind_two(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.segment(a=(10, 10), b=(50, 50))
        assert canvas._shapes[0].kind == 2

    def test_segment_flush_no_crash(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.segment(a=(5, 5), b=(60, 60), thickness=3.0)
        canvas.flush()


class TestSdfCanvasRing:
    def test_ring_adds_shape(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.ring(center=(32, 32), radius=15, thickness=3)
        assert len(canvas._shapes) == 1

    def test_ring_kind_three(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.ring(center=(32, 32), radius=15, thickness=3)
        assert canvas._shapes[0].kind == 3

    def test_ring_flush_writes_pixels(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer(w=64, h=64)
        canvas = SdfCanvas(layer)
        canvas.ring(center=(32, 32), radius=12, thickness=4, color=(0.0, 0.0, 1.0, 1.0))
        canvas.flush()
        # Some pixel near the ring circumference should be non-zero
        assert layer._image_data[:, :, 2].max() > 0  # blue channel has something


class TestSdfCanvasMultipleShapes:
    def test_multiple_shapes_queued(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.circle(center=(20, 20), radius=5)
        canvas.box(center=(40, 40), size=(10, 10))
        canvas.ring(center=(50, 50), radius=8, thickness=2)
        assert len(canvas._shapes) == 3

    def test_clear_empties_shapes(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer()
        canvas = SdfCanvas(layer)
        canvas.circle(center=(32, 32), radius=5)
        canvas.clear()
        assert len(canvas._shapes) == 0

    def test_multiple_flush_accumulates(self):
        from pharos_engine.sdf_shapes import SdfCanvas
        layer = _make_layer(w=64, h=64)
        canvas = SdfCanvas(layer)
        canvas.circle(center=(16, 16), radius=5, color=(1.0, 0.0, 0.0, 1.0))
        canvas.flush()
        canvas.circle(center=(48, 48), radius=5, color=(0.0, 1.0, 0.0, 1.0))
        canvas.flush()
        # Both regions should have color
        assert layer._image_data[16, 16, 0] > 0
        assert layer._image_data[48, 48, 1] > 0
