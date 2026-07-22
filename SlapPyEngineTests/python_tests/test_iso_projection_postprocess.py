"""Engine tests for iso/projection.py and post_process/{dof,ssr,gtao,motion_blur}.py.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# iso/projection.py
# ---------------------------------------------------------------------------

class TestIsoViewpoint:
    def test_values(self):
        from pharos_engine.iso.projection import IsoViewpoint
        assert IsoViewpoint.NE == 0
        assert IsoViewpoint.NW == 1
        assert IsoViewpoint.SW == 2
        assert IsoViewpoint.SE == 3

    def test_distinct(self):
        from pharos_engine.iso.projection import IsoViewpoint
        vals = [IsoViewpoint.NE, IsoViewpoint.NW, IsoViewpoint.SW, IsoViewpoint.SE]
        assert len(set(vals)) == 4


class TestViewpointTransform:
    def test_transforms_present_for_all_viewpoints(self):
        from pharos_engine.iso.projection import TRANSFORMS, IsoViewpoint
        for vp in IsoViewpoint:
            assert vp in TRANSFORMS

    def test_ne_transform(self):
        from pharos_engine.iso.projection import TRANSFORMS, IsoViewpoint
        t = TRANSFORMS[IsoViewpoint.NE]
        assert t.xx == 1
        assert t.xy == -1
        assert t.yx == 1
        assert t.yy == 1
        assert t.depth_sign == 1


class TestWorldToScreen:
    def test_origin_maps_to_origin(self):
        from pharos_engine.iso.projection import world_to_screen, IsoViewpoint
        sx, sy = world_to_screen(0, 0, 0, IsoViewpoint.NE)
        assert sx == pytest.approx(0.0)
        assert sy == pytest.approx(0.0)

    def test_returns_tuple_of_two(self):
        from pharos_engine.iso.projection import world_to_screen, IsoViewpoint
        result = world_to_screen(1, 2, 0, IsoViewpoint.NE)
        assert len(result) == 2

    def test_z_offset_moves_screen_up(self):
        from pharos_engine.iso.projection import world_to_screen, IsoViewpoint
        sx0, sy0 = world_to_screen(0, 0, 0, IsoViewpoint.NE)
        sx1, sy1 = world_to_screen(0, 0, 1, IsoViewpoint.NE)
        # Higher z → lower screen_y (up on screen)
        assert sy1 < sy0

    def test_camera_offset_applied(self):
        from pharos_engine.iso.projection import world_to_screen, IsoViewpoint
        sx, sy = world_to_screen(0, 0, 0, IsoViewpoint.NE, cam_x=100.0, cam_y=50.0)
        assert sx == pytest.approx(-100.0)
        assert sy == pytest.approx(-50.0)

    def test_all_viewpoints_produce_values(self):
        from pharos_engine.iso.projection import world_to_screen, IsoViewpoint
        for vp in IsoViewpoint:
            sx, sy = world_to_screen(3, 4, 1, vp)
            assert isinstance(sx, float) and isinstance(sy, float)


class TestScreenToWorld:
    def test_origin_maps_to_origin(self):
        from pharos_engine.iso.projection import screen_to_world, IsoViewpoint
        gx, gy = screen_to_world(0, 0, IsoViewpoint.NE)
        assert gx == 0 and gy == 0

    def test_returns_integers(self):
        from pharos_engine.iso.projection import screen_to_world, IsoViewpoint
        gx, gy = screen_to_world(32.0, 16.0, IsoViewpoint.NE)
        assert isinstance(gx, int) and isinstance(gy, int)

    def test_roundtrip_ne(self):
        from pharos_engine.iso.projection import world_to_screen, screen_to_world, IsoViewpoint
        gx_in, gy_in = 3, 5
        sx, sy = world_to_screen(gx_in, gy_in, 0, IsoViewpoint.NE)
        gx_out, gy_out = screen_to_world(sx, sy, IsoViewpoint.NE)
        assert gx_out == gx_in
        assert gy_out == gy_in

    def test_roundtrip_sw(self):
        from pharos_engine.iso.projection import world_to_screen, screen_to_world, IsoViewpoint
        gx_in, gy_in = -2, 4
        sx, sy = world_to_screen(gx_in, gy_in, 0, IsoViewpoint.SW)
        gx_out, gy_out = screen_to_world(sx, sy, IsoViewpoint.SW)
        assert gx_out == gx_in
        assert gy_out == gy_in


class TestDepthKey:
    def test_returns_float(self):
        from pharos_engine.iso.projection import depth_key, IsoViewpoint
        k = depth_key(0, 0, 0, IsoViewpoint.NE)
        assert isinstance(k, float)

    def test_further_tile_has_smaller_key(self):
        from pharos_engine.iso.projection import depth_key, IsoViewpoint
        k_close = depth_key(0, 0, 0, IsoViewpoint.NE)
        k_far = depth_key(-5, -5, 0, IsoViewpoint.NE)
        # Smaller value = further back
        assert k_far < k_close

    def test_higher_z_increases_key(self):
        from pharos_engine.iso.projection import depth_key, IsoViewpoint
        k0 = depth_key(2, 2, 0, IsoViewpoint.NE)
        k1 = depth_key(2, 2, 1, IsoViewpoint.NE)
        assert k1 > k0

    def test_all_viewpoints_no_crash(self):
        from pharos_engine.iso.projection import depth_key, IsoViewpoint
        for vp in IsoViewpoint:
            k = depth_key(1, 2, 3, vp)
            assert isinstance(k, float)


# ---------------------------------------------------------------------------
# post_process/dof.py — DofPass
# ---------------------------------------------------------------------------

class TestDofPass:
    def test_instantiates(self):
        from pharos_engine.post_process.dof import DofPass
        d = DofPass()
        assert d is not None

    def test_defaults(self):
        from pharos_engine.post_process.dof import DofPass
        d = DofPass()
        assert d.focal_distance == pytest.approx(0.5)
        assert d.focal_range == pytest.approx(0.3)
        assert d.max_coc_radius == pytest.approx(12.0)
        assert d.bokeh_samples == 16

    def test_custom_values(self):
        from pharos_engine.post_process.dof import DofPass
        d = DofPass(focal_distance=0.2, focal_range=0.1,
                    max_coc_radius=8.0, bokeh_samples=8)
        assert d.focal_distance == pytest.approx(0.2)
        assert d.bokeh_samples == 8

    def test_label(self):
        from pharos_engine.post_process.dof import DofPass
        assert DofPass.label == "dof"


# ---------------------------------------------------------------------------
# post_process/ssr.py — SSRPass
# ---------------------------------------------------------------------------

class TestSSRPass:
    def test_instantiates(self):
        from pharos_engine.post_process.ssr import SSRPass
        s = SSRPass()
        assert s is not None

    def test_defaults(self):
        from pharos_engine.post_process.ssr import SSRPass
        s = SSRPass()
        assert s.max_steps == 16
        assert s.stride == pytest.approx(1.5)
        assert s.thickness == pytest.approx(0.5)
        assert s.strength == pytest.approx(0.8)
        assert s.roughness_cutoff == pytest.approx(0.6)

    def test_custom_values(self):
        from pharos_engine.post_process.ssr import SSRPass
        s = SSRPass(max_steps=32, strength=0.5)
        assert s.max_steps == 32
        assert s.strength == pytest.approx(0.5)

    def test_label(self):
        from pharos_engine.post_process.ssr import SSRPass
        assert SSRPass.label == "ssr"

    def test_apply_initially_none(self):
        from pharos_engine.post_process.ssr import SSRPass
        s = SSRPass()
        assert s._apply is None


# ---------------------------------------------------------------------------
# post_process/gtao.py — GTAOPass
# ---------------------------------------------------------------------------

class TestGTAOPass:
    def test_instantiates(self):
        from pharos_engine.post_process.gtao import GTAOPass
        g = GTAOPass()
        assert g is not None

    def test_defaults(self):
        from pharos_engine.post_process.gtao import GTAOPass
        g = GTAOPass()
        assert g.num_directions == 8
        assert g.num_steps == 4
        assert g.radius == pytest.approx(2.0)
        assert g.bias == pytest.approx(0.05)
        assert g.max_pixel_radius == pytest.approx(64.0)

    def test_power_from_intensity(self):
        from pharos_engine.post_process.gtao import GTAOPass
        g = GTAOPass(intensity=2.0)
        assert g.power == pytest.approx(0.5)

    def test_intensity_one_gives_power_one(self):
        from pharos_engine.post_process.gtao import GTAOPass
        g = GTAOPass(intensity=1.0)
        assert g.power == pytest.approx(1.0)

    def test_label(self):
        from pharos_engine.post_process.gtao import GTAOPass
        assert GTAOPass.label == "gtao"

    def test_inv_proj_default_identity(self):
        from pharos_engine.post_process.gtao import GTAOPass, _IDENTITY_MAT4
        g = GTAOPass()
        assert g.inv_proj == _IDENTITY_MAT4


# ---------------------------------------------------------------------------
# post_process/motion_blur.py — MotionBlurPass
# ---------------------------------------------------------------------------

class TestMotionBlurPass:
    def test_instantiates(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        m = MotionBlurPass()
        assert m is not None

    def test_defaults(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        m = MotionBlurPass()
        assert m.sample_count == 8
        assert m.strength == pytest.approx(1.0)

    def test_custom_values(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        m = MotionBlurPass(sample_count=16, strength=2.0)
        assert m.sample_count == 16
        assert m.strength == pytest.approx(2.0)

    def test_label(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        assert MotionBlurPass.label == "motion_blur"
