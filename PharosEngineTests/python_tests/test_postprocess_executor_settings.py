"""Headless tests for PostProcessExecutor._make_params_buffer,
DofPass.make_pass(), MotionBlurPass.make_pass(), and SettingsScene._resolved_values."""
from __future__ import annotations
import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock, call
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_ctx():
    """Return a mock GPUContext whose device captures write_buffer calls."""
    ctx = MagicMock()
    buf = MagicMock()
    ctx.device.create_buffer.return_value = buf
    return ctx


def _executor_with_ctx(ctx=None):
    from pharos_engine.post_process.executor import PostProcessExecutor
    if ctx is None:
        ctx = _make_ctx()
    ex = PostProcessExecutor(ctx)
    return ex, ctx


def _fake_pass(shader_path, params=None, raw_params_bytes=None, label="test"):
    from pharos_engine.post_process.chain import PostProcessPass
    return PostProcessPass(
        shader_path=shader_path,
        params=params or {},
        label=label,
        raw_params_bytes=raw_params_bytes,
    )


# =============================================================================
# PostProcessExecutor._make_params_buffer — nv_grain.wgsl
# =============================================================================

class TestMakeParamsBufferNvGrain:
    def _pack_data(self, gain, grain, vignette, time, w, h):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("nv_grain.wgsl", params={
            "gain": gain,
            "grain_strength": grain,
            "vignette_strength": vignette,
            "time": time,
        })
        ex._make_params_buffer(p, w, h)
        return ctx.device.queue.write_buffer.call_args[0][2]

    def test_nv_grain_buffer_created(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("nv_grain.wgsl")
        ex._make_params_buffer(p, 1280, 720)
        ctx.device.create_buffer.assert_called_once()

    def test_nv_grain_defaults_written(self):
        data = self._pack_data(3.0, 0.08, 1.2, 0.0, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[0] == pytest.approx(3.0)     # gain
        assert vals[1] == pytest.approx(0.08)    # grain_strength
        assert vals[2] == pytest.approx(1.2)     # vignette_strength
        assert vals[3] == pytest.approx(0.0)     # time

    def test_nv_grain_width_height_packed(self):
        data = self._pack_data(3.0, 0.08, 1.2, 0.0, 800, 600)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[4] == 800
        assert vals[5] == 600

    def test_nv_grain_custom_gain(self):
        data = self._pack_data(5.0, 0.08, 1.2, 0.0, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[0] == pytest.approx(5.0)

    def test_nv_grain_custom_time(self):
        data = self._pack_data(3.0, 0.08, 1.2, 0.5, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[3] == pytest.approx(0.5)

    def test_nv_grain_32_bytes(self):
        data = self._pack_data(3.0, 0.08, 1.2, 0.0, 1280, 720)
        assert len(data) == 32

    def test_nv_grain_pad_zero(self):
        data = self._pack_data(3.0, 0.08, 1.2, 0.0, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[6] == 0   # _pad0
        assert vals[7] == 0   # _pad1

    def test_nv_grain_missing_param_defaults(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("nv_grain.wgsl", params={})  # no params at all
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<ffffIIII", data)
        assert vals[0] == pytest.approx(3.0)   # gain default
        assert vals[1] == pytest.approx(0.08)  # grain_strength default


# =============================================================================
# PostProcessExecutor._make_params_buffer — chromatic_aberration.wgsl
# =============================================================================

class TestMakeParamsBufferChromatic:
    def _pack_data(self, strength, cx, cy, w, h):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("chromatic_aberration.wgsl", params={
            "strength": strength,
            "center_x": cx,
            "center_y": cy,
        })
        ex._make_params_buffer(p, w, h)
        return ctx.device.queue.write_buffer.call_args[0][2]

    def test_chromatic_buffer_created(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("chromatic_aberration.wgsl",
                       params={"strength": 0.005, "center_x": 0.5, "center_y": 0.5})
        ex._make_params_buffer(p, 1280, 720)
        ctx.device.create_buffer.assert_called_once()

    def test_chromatic_strength_packed(self):
        data = self._pack_data(0.008, 0.5, 0.5, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[0] == pytest.approx(0.008)

    def test_chromatic_center_packed(self):
        data = self._pack_data(0.005, 0.3, 0.7, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[1] == pytest.approx(0.3)
        assert vals[2] == pytest.approx(0.7)

    def test_chromatic_pad_zero(self):
        data = self._pack_data(0.005, 0.5, 0.5, 1280, 720)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[3] == pytest.approx(0.0)   # _pad

    def test_chromatic_32_bytes(self):
        data = self._pack_data(0.005, 0.5, 0.5, 1280, 720)
        assert len(data) == 32

    def test_chromatic_width_height(self):
        data = self._pack_data(0.005, 0.5, 0.5, 640, 480)
        vals = struct.unpack("<ffffIIII", data)
        assert vals[4] == 640
        assert vals[5] == 480

    def test_chromatic_missing_param_defaults(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("chromatic_aberration.wgsl", params={})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<ffffIIII", data)
        assert vals[0] == pytest.approx(0.005)  # strength default


# =============================================================================
# PostProcessExecutor._make_params_buffer — tonemap.wgsl
# =============================================================================

class TestMakeParamsBufferTonemap:
    def _pack_default(self, w=1280, h=720):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("tonemap.wgsl")
        ex._make_params_buffer(p, w, h)
        return ctx.device.queue.write_buffer.call_args[0][2]

    def test_tonemap_buffer_created(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("tonemap.wgsl")
        ex._make_params_buffer(p, 1280, 720)
        ctx.device.create_buffer.assert_called_once()

    def test_tonemap_56_bytes(self):
        data = self._pack_default()
        assert len(data) == 56

    def test_tonemap_defaults(self):
        data = self._pack_default()
        # <fIffffffffffII>
        vals = struct.unpack("<fIffffffffffII", data)
        assert vals[0] == pytest.approx(0.0)   # exposure_ev
        assert vals[1] == 0                     # mode
        assert vals[2] == pytest.approx(1.0)   # saturation
        assert vals[3] == pytest.approx(1.0)   # contrast

    def test_tonemap_gain_channels(self):
        data = self._pack_default()
        vals = struct.unpack("<fIffffffffffII", data)
        # gain_r, gain_g, gain_b are at indices 7, 8, 9
        assert vals[7] == pytest.approx(1.0)
        assert vals[8] == pytest.approx(1.0)
        assert vals[9] == pytest.approx(1.0)

    def test_tonemap_gamma_default(self):
        data = self._pack_default()
        vals = struct.unpack("<fIffffffffffII", data)
        assert vals[10] == pytest.approx(1.0)  # gamma

    def test_tonemap_width_height(self):
        data = self._pack_default(640, 360)
        vals = struct.unpack("<fIffffffffffII", data)
        assert vals[12] == 640
        assert vals[13] == 360

    def test_tonemap_custom_exposure(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("tonemap.wgsl", params={"exposure_ev": 1.5})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<fIffffffffffII", data)
        assert vals[0] == pytest.approx(1.5)

    def test_tonemap_custom_mode(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("tonemap.wgsl", params={"mode": 2})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<fIffffffffffII", data)
        assert vals[1] == 2


# =============================================================================
# PostProcessExecutor._make_params_buffer — legacy (blur, pixelate)
# =============================================================================

class TestMakeParamsBufferLegacy:
    def test_blur_uses_radius(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("blur.wgsl", params={"radius": 4})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<IIII", data)
        assert vals[0] == 4   # radius

    def test_pixelate_uses_block_size(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("pixelate.wgsl", params={"block_size": 8})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<IIII", data)
        assert vals[0] == 8   # block_size

    def test_legacy_width_height_in_buffer(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("blur.wgsl", params={"radius": 2})
        ex._make_params_buffer(p, 400, 300)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<IIII", data)
        assert vals[1] == 400
        assert vals[2] == 300

    def test_legacy_16_bytes(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("blur.wgsl", params={"radius": 2})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        assert len(data) == 16

    def test_legacy_pad_zero(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("blur.wgsl", params={"radius": 3})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<IIII", data)
        assert vals[3] == 0  # _pad

    def test_legacy_no_params_zero(self):
        ex, ctx = _executor_with_ctx()
        p = _fake_pass("unknown_shader.wgsl", params={})
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        vals = struct.unpack("<IIII", data)
        assert vals[0] == 0  # neither radius nor block_size


# =============================================================================
# PostProcessExecutor._make_params_buffer — raw_params_bytes bypass
# =============================================================================

class TestMakeParamsBufferRawBytes:
    def test_raw_bytes_used_as_is(self):
        ex, ctx = _executor_with_ctx()
        raw = b"\x01\x02\x03\x04" * 8
        p = _fake_pass("anything.wgsl", raw_params_bytes=raw)
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        assert data == raw

    def test_raw_bytes_ignores_params(self):
        ex, ctx = _executor_with_ctx()
        raw = b"\xFF" * 16
        p = _fake_pass("blur.wgsl",
                       params={"radius": 99},
                       raw_params_bytes=raw)
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        assert data == raw   # should be raw, not the blur packing

    def test_raw_bytes_empty(self):
        ex, ctx = _executor_with_ctx()
        raw = b""
        p = _fake_pass("anything.wgsl", raw_params_bytes=raw)
        ex._make_params_buffer(p, 1280, 720)
        data = ctx.device.queue.write_buffer.call_args[0][2]
        assert data == b""


# =============================================================================
# DofPass.make_pass() struct packing
# =============================================================================

class TestDofPassMakePass:
    def test_make_pass_returns_post_process_pass(self):
        from pharos_engine.post_process.dof import DofPass
        from pharos_engine.post_process.chain import PostProcessPass
        dp = DofPass()
        result = dp.make_pass("scene_tex", "depth_tex")
        assert isinstance(result, PostProcessPass)

    def test_make_pass_label(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass()
        p = dp.make_pass("scene_tex", "depth_tex")
        assert p.label == "dof"

    def test_make_pass_raw_bytes_not_none(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass()
        p = dp.make_pass("scene_tex", "depth_tex")
        assert p.raw_params_bytes is not None

    def test_make_pass_raw_bytes_32_bytes(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass()
        p = dp.make_pass("scene_tex", "depth_tex")
        assert len(p.raw_params_bytes) == 32

    def test_make_pass_default_focal_distance(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass(focal_distance=0.5)
        p = dp.make_pass("scene_tex", "depth_tex")
        # Layout: <IIfffIII>: width(0), height(0), focal_distance, focal_range, max_coc, samples, pad0, pad1
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[2] == pytest.approx(0.5)

    def test_make_pass_default_focal_range(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass(focal_range=0.3)
        p = dp.make_pass("scene_tex", "depth_tex")
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[3] == pytest.approx(0.3)

    def test_make_pass_max_coc(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass(max_coc_radius=16.0)
        p = dp.make_pass("scene_tex", "depth_tex")
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[4] == pytest.approx(16.0)

    def test_make_pass_bokeh_samples(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass(bokeh_samples=12)
        p = dp.make_pass("scene_tex", "depth_tex")
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[5] == 12

    def test_make_pass_width_height_zero_initially(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass()
        p = dp.make_pass("scene_tex", "depth_tex")
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[0] == 0   # width — executor fills
        assert vals[1] == 0   # height — executor fills

    def test_make_pass_custom_values(self):
        from pharos_engine.post_process.dof import DofPass
        dp = DofPass(focal_distance=0.3, focal_range=0.15,
                     max_coc_radius=8.0, bokeh_samples=8)
        p = dp.make_pass("s", "d")
        vals = struct.unpack("<IIfffIII", p.raw_params_bytes)
        assert vals[2] == pytest.approx(0.3)
        assert vals[3] == pytest.approx(0.15)
        assert vals[4] == pytest.approx(8.0)
        assert vals[5] == 8


# =============================================================================
# MotionBlurPass.make_pass() struct packing
# =============================================================================

class TestMotionBlurPassMakePass:
    def test_make_pass_returns_post_process_pass(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        from pharos_engine.post_process.chain import PostProcessPass
        mb = MotionBlurPass()
        result = mb.make_pass("scene_tex", "velocity_tex")
        assert isinstance(result, PostProcessPass)

    def test_make_pass_label(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass()
        p = mb.make_pass("scene_tex", "velocity_tex")
        assert p.label == "motion_blur"

    def test_make_pass_raw_bytes_not_none(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass()
        p = mb.make_pass("scene_tex", "velocity_tex")
        assert p.raw_params_bytes is not None

    def test_make_pass_32_bytes(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass()
        p = mb.make_pass("scene_tex", "velocity_tex")
        assert len(p.raw_params_bytes) == 32

    def test_make_pass_default_sample_count(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass(sample_count=8)
        p = mb.make_pass("scene_tex", "velocity_tex")
        # Layout: <IIIfIIII>: width(0), height(0), sample_count, strength, _pad x4
        vals = struct.unpack("<IIIfIIII", p.raw_params_bytes)
        assert vals[2] == 8

    def test_make_pass_default_strength(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass(strength=1.0)
        p = mb.make_pass("scene_tex", "velocity_tex")
        vals = struct.unpack("<IIIfIIII", p.raw_params_bytes)
        assert vals[3] == pytest.approx(1.0)

    def test_make_pass_width_height_zero(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass()
        p = mb.make_pass("scene_tex", "velocity_tex")
        vals = struct.unpack("<IIIfIIII", p.raw_params_bytes)
        assert vals[0] == 0
        assert vals[1] == 0

    def test_make_pass_custom_values(self):
        from pharos_engine.post_process.motion_blur import MotionBlurPass
        mb = MotionBlurPass(sample_count=4, strength=2.0)
        p = mb.make_pass("scene_tex", "velocity_tex")
        vals = struct.unpack("<IIIfIIII", p.raw_params_bytes)
        assert vals[2] == 4
        assert vals[3] == pytest.approx(2.0)


# =============================================================================
# SettingsScene._resolved_values() (pure logic, no GPU)
# =============================================================================

def _make_engine_for_settings():
    engine = MagicMock()
    engine._settings = {}
    cfg = MagicMock()
    cfg.window.width = 1280
    cfg.window.height = 720
    engine._cfg = cfg
    engine.camera = MagicMock()
    return engine


class TestSettingsSceneResolvedValues:
    def _make_scene(self, saved=None):
        from scenes.settings import SettingsScene
        eng = _make_engine_for_settings()
        if saved:
            eng._settings = saved
        return SettingsScene(eng)

    def test_resolved_returns_dict(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert isinstance(vals, dict)

    def test_resolved_has_all_keys(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        expected_keys = {"music_vol", "sfx_vol", "ai_count",
                         "difficulty", "particles", "shake", "cam_zoom",
                         "post_process"}
        assert expected_keys == set(vals.keys())

    def test_default_music_vol(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["music_vol"] == 50  # default index 2 → 50

    def test_default_sfx_vol(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["sfx_vol"] == 75  # default index 3 → 75

    def test_default_ai_count(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["ai_count"] == 3  # default index 2 → 3

    def test_default_difficulty(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["difficulty"] == "Normal"  # default index 1

    def test_default_particles(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["particles"] == "High"  # default index 2

    def test_default_screen_shake(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["shake"] == "On"  # default index 1

    def test_default_cam_zoom(self):
        scene = self._make_scene()
        vals = scene._resolved_values()
        assert vals["cam_zoom"] == "Normal"  # default index 1

    def test_saved_settings_override_default(self):
        scene = self._make_scene(saved={"difficulty": "Hard"})
        vals = scene._resolved_values()
        assert vals["difficulty"] == "Hard"

    def test_saved_numeric_override(self):
        scene = self._make_scene(saved={"music_vol": 100})
        vals = scene._resolved_values()
        assert vals["music_vol"] == 100

    def test_invalid_saved_setting_falls_back_to_default(self):
        # value not in opts → falls back to default
        scene = self._make_scene(saved={"difficulty": "Impossible"})
        vals = scene._resolved_values()
        # Should still be "Normal" (the default index 1)
        assert vals["difficulty"] == "Normal"

    def test_save_to_engine_populates_engine_settings(self):
        scene = self._make_scene()
        scene._save_to_engine()
        stored = scene._engine._settings
        assert "music_vol" in stored
        assert "difficulty" in stored

    def test_navigate_changes_selected(self):
        scene = self._make_scene()
        assert scene._selected == 0
        # Directly mutate to simulate navigation
        scene._selected = 3
        assert scene._selected == 3
