"""Engine tests for gi/cascade.py, gi/restir.py, gi/svgf.py — headless (no GPU)."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# RadianceCascadeSystem
# ---------------------------------------------------------------------------

class TestRadianceCascadeSystemInit:
    def test_instantiates(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        assert rc is not None

    def test_default_dimensions(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=800, height=600)
        assert rc.width == 800
        assert rc.height == 600

    def test_default_num_cascades(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        assert rc.num_cascades == 4

    def test_custom_num_cascades(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480, num_cascades=2)
        assert rc.num_cascades == 2

    def test_not_initialized_without_gpu(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        assert rc._initialized is False

    def test_gpu_ref_initially_none(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        assert rc._gpu is None

    def test_base_probe_spacing(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480, base_probe_spacing=16)
        assert rc.base_probe_spacing == 16

    def test_temporal_blend_stored(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480, temporal_blend=0.1)
        assert rc.temporal_blend == pytest.approx(0.1)

    def test_rays_per_probe(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480, rays_per_probe_l0=256)
        assert rc.rays_per_probe_l0 == 256


class TestRadianceCascadeSystemDispatch:
    def test_dispatch_no_op_when_not_initialized(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        # Should not raise — early return when not initialized
        rc.dispatch(encoder=None, scene_texture=None, lighting_accumulator=None)

    def test_init_gpu_handles_no_wgpu(self):
        from slappyengine.gi.cascade import RadianceCascadeSystem
        rc = RadianceCascadeSystem(width=640, height=480)
        # Pass a fake gpu object — should not raise (errors are caught internally)
        rc.init_gpu(gpu=None)
        # When no real GPU: _initialized stays False
        assert rc._initialized is False


# ---------------------------------------------------------------------------
# SVGFDenoiser
# ---------------------------------------------------------------------------

class TestSVGFConstants:
    def test_phi_color_positive(self):
        from slappyengine.gi.svgf import PHI_COLOR
        assert PHI_COLOR > 0

    def test_phi_normal_positive(self):
        from slappyengine.gi.svgf import PHI_NORMAL
        assert PHI_NORMAL > 0

    def test_phi_depth_positive(self):
        from slappyengine.gi.svgf import PHI_DEPTH
        assert PHI_DEPTH > 0

    def test_temporal_alpha_range(self):
        from slappyengine.gi.svgf import TEMPORAL_ALPHA
        assert 0.0 < TEMPORAL_ALPHA <= 1.0

    def test_max_history_positive(self):
        from slappyengine.gi.svgf import MAX_HISTORY
        assert MAX_HISTORY > 0


class TestSVGFDenoiserInit:
    def test_instantiates(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser(width=640, height=480)
        assert d is not None

    def test_dimensions_stored(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser(width=1280, height=720)
        assert d.width == 1280
        assert d.height == 720

    def test_not_initialized_without_gpu(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser(width=640, height=480)
        assert d._initialized is False

    def test_gpu_initially_none(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser()
        assert d._gpu is None

    def test_default_zero_dimensions(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser()
        assert d.width == 0
        assert d.height == 0

    def test_init_gpu_handles_no_device(self):
        from slappyengine.gi.svgf import SVGFDenoiser
        d = SVGFDenoiser(width=640, height=480)
        # None gpu → exception caught internally
        d.init_gpu(gpu=None, width=640, height=480)
        assert d._initialized is False


# ---------------------------------------------------------------------------
# ReSTIRSystem
# ---------------------------------------------------------------------------

class TestReSTIRConstants:
    def test_reservoir_stride_is_32(self):
        from slappyengine.gi.restir import _RESERVOIR_STRIDE
        assert _RESERVOIR_STRIDE == 32


class TestReSTIRSystemInit:
    def test_instantiates(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(width=640, height=480)
        assert r is not None

    def test_dimensions_stored(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(width=1920, height=1080)
        assert r.width == 1920
        assert r.height == 1080

    def test_max_candidates_stored(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(max_candidates=64)
        assert r.max_candidates == 64

    def test_not_initialized_without_gpu(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(width=640, height=480)
        assert r._initialized is False

    def test_frame_counter_initially_zero(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem()
        assert r._frame == 0

    def test_gpu_initially_none(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem()
        assert r._gpu is None

    def test_default_dimensions_are_zero(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem()
        assert r.width == 0
        assert r.height == 0


class TestReSTIRSystemDispatch:
    def test_dispatch_no_op_when_not_initialized(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(width=640, height=480)
        # Not initialized → dispatch is a no-op, should not raise
        r.dispatch(encoder=None,
                   gbuffer_pos=None, gbuffer_normal=None, gbuffer_albedo=None,
                   light_buf=None, output_tex=None, frame_count=0)

    def test_init_gpu_handles_none(self):
        from slappyengine.gi.restir import ReSTIRSystem
        r = ReSTIRSystem(width=640, height=480)
        r.init_gpu(gpu=None, width=640, height=480)
        assert r._initialized is False
