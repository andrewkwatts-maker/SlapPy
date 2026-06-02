"""Engine tests for config.py sub-dataclasses and load_config — headless."""
from __future__ import annotations
import os
import pytest
from pathlib import Path


# Minimal valid engine.yml content for testing load_config()
_MINIMAL_ENGINE_YML = """\
window:
  title: TestWindow
  width: 640
  height: 480
  clear_color: [0.1, 0.1, 0.1, 1.0]
  vsync: false

rendering:
  max_layers_per_asset: 4
  max_frames_per_animation: 32
  texture_format: rgba8unorm
"""


class TestWindowConfig:
    def test_init(self):
        from slappyengine.config import WindowConfig
        wc = WindowConfig(
            title="Test", width=800, height=600,
            clear_color=(0.0, 0.0, 0.0, 1.0), vsync=False
        )
        assert wc.title == "Test"
        assert wc.width == 800
        assert wc.height == 600
        assert wc.vsync is False

    def test_clear_color_is_tuple(self):
        from slappyengine.config import WindowConfig
        wc = WindowConfig(
            title="X", width=1, height=1,
            clear_color=(0.1, 0.2, 0.3, 1.0), vsync=True
        )
        assert len(wc.clear_color) == 4


class TestRenderingConfig:
    def test_defaults(self):
        from slappyengine.config import RenderingConfig
        rc = RenderingConfig(
            max_layers_per_asset=8,
            max_frames_per_animation=64,
            texture_format="rgba8unorm"
        )
        assert rc.max_layers_per_asset == 8
        assert rc.max_frames_per_animation == 64
        assert rc.backend == "auto"

    def test_backend_override(self):
        from slappyengine.config import RenderingConfig
        rc = RenderingConfig(
            max_layers_per_asset=4,
            max_frames_per_animation=16,
            texture_format="rgba8unorm",
            backend="vulkan"
        )
        assert rc.backend == "vulkan"


class TestResidencyConfig:
    def test_defaults(self):
        from slappyengine.config import ResidencyConfig
        rc = ResidencyConfig()
        assert rc.streaming_radius_gpu == 500
        assert rc.streaming_radius_ram == 2000
        assert rc.vram_budget_mb == 512


class TestComputeConfig:
    def test_defaults(self):
        from slappyengine.config import ComputeConfig
        cc = ComputeConfig()
        assert cc.workgroup_size_x == 16
        assert cc.workgroup_size_y == 16
        assert cc.max_readback_buffers == 8


class TestPhysicsConfig:
    def test_defaults(self):
        from slappyengine.config import PhysicsConfig
        pc = PhysicsConfig()
        assert pc.default_dt == pytest.approx(0.016667)
        assert pc.substeps == 1


class TestAudioConfig:
    def test_defaults(self):
        from slappyengine.config import AudioConfig
        ac = AudioConfig()
        assert ac.speed_of_sound == pytest.approx(343.0)
        assert ac.sonic_boom_threshold > 0.0
        assert ac.sonic_boom_threshold < 1.0

    def test_custom_speed_of_sound(self):
        from slappyengine.config import AudioConfig
        ac = AudioConfig(speed_of_sound=500.0)
        assert ac.speed_of_sound == pytest.approx(500.0)


class TestLightingConfig:
    def test_defaults(self):
        from slappyengine.config import LightingConfig
        lc = LightingConfig()
        assert lc.enabled is True
        assert lc.max_point_lights > 0
        assert lc.max_cone_lights > 0
        assert len(lc.ambient_color) == 3

    def test_clustered_lighting_default(self):
        from slappyengine.config import LightingConfig
        lc = LightingConfig()
        assert isinstance(lc.clustered_lighting, bool)


class TestNetConfig:
    def test_defaults(self):
        from slappyengine.config import NetConfig
        nc = NetConfig()
        assert nc.enabled is False
        assert nc.tick_rate > 0
        assert nc.max_players > 0


class TestDeformConfig:
    def test_defaults(self):
        from slappyengine.config import DeformConfig
        dc = DeformConfig()
        assert dc.sim_mode == "collision_triggered"
        assert dc.spring_decay == pytest.approx(0.94)
        assert isinstance(dc.decay_curve, list)
        assert len(dc.decay_curve) > 0


class TestZHeightConfig:
    def test_defaults(self):
        from slappyengine.config import ZHeightConfig
        zc = ZHeightConfig()
        assert zc.default_z == pytest.approx(0.0)
        assert zc.cloud_z > 0.0
        assert zc.parallax_enabled is True


class TestLoadConfig:
    def test_load_from_scaffolded_dir(self, tmp_path):
        """scaffold → load_config → Config object returned."""
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert cfg is not None

    def test_config_has_window(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert hasattr(cfg, "window")
        assert isinstance(cfg.window.width, int)

    def test_config_has_rendering(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert hasattr(cfg, "rendering")
        assert isinstance(cfg.rendering.max_layers_per_asset, int)

    def test_config_has_lighting(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert hasattr(cfg, "lighting")
        assert cfg.lighting.enabled is True

    def test_config_has_audio(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert hasattr(cfg, "audio")
        assert cfg.audio.speed_of_sound > 0.0

    def test_env_var_config_dir(self, tmp_path, monkeypatch):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        monkeypatch.setenv("SLAPPY_CONFIG_DIR", str(config_dir))
        cfg = load_config()
        assert cfg is not None

    def test_two_loads_return_independent_objects(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        path = str(config_dir / "engine.yml")
        cfg1 = load_config(path)
        cfg2 = load_config(path)
        assert cfg1 is not cfg2


class TestFluidSimConfigInConfig:
    def test_config_fluid_sim_sub(self, tmp_path):
        from slappyengine.config import _scaffold_first_run, load_config
        config_dir = _scaffold_first_run(tmp_path)
        cfg = load_config(str(config_dir / "engine.yml"))
        assert hasattr(cfg, "fluid_sim")
        assert isinstance(cfg.fluid_sim.viscosity, float)
