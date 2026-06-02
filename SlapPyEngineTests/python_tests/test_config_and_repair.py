"""Engine tests for config.py dataclasses and deform_repair.py.
All headless — no GPU/file-system access required for dataclass tests.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Config dataclass defaults — all these are pure Python, no I/O
# ---------------------------------------------------------------------------

class TestResidencyConfig:
    def test_defaults(self):
        from slappyengine.config import ResidencyConfig
        r = ResidencyConfig()
        assert r.streaming_radius_gpu == 500
        assert r.streaming_radius_ram == 2000
        assert r.vram_budget_mb == 512
        assert r.ram_budget_mb == 2048
        assert r.tile_cache_size == 64
        assert r.save_dir == "."

    def test_custom_values(self):
        from slappyengine.config import ResidencyConfig
        r = ResidencyConfig(vram_budget_mb=1024, ram_budget_mb=4096)
        assert r.vram_budget_mb == 1024
        assert r.ram_budget_mb == 4096


class TestComputeConfig:
    def test_defaults(self):
        from slappyengine.config import ComputeConfig
        c = ComputeConfig()
        assert c.workgroup_size_x == 16
        assert c.workgroup_size_y == 16
        assert c.max_readback_buffers == 8


class TestPhysicsConfig:
    def test_defaults(self):
        from slappyengine.config import PhysicsConfig
        p = PhysicsConfig()
        assert p.default_dt == pytest.approx(0.016667)
        assert p.substeps == 1


class TestTagsConfig:
    def test_defaults(self):
        from slappyengine.config import TagsConfig
        t = TagsConfig()
        assert t.max_bits == 64


class TestZHeightConfig:
    def test_defaults(self):
        from slappyengine.config import ZHeightConfig
        z = ZHeightConfig()
        assert z.default_z == pytest.approx(0.0)
        assert z.cloud_z == pytest.approx(500.0)
        assert z.parallax_enabled is True


class TestPixelPhysicsConfig:
    def test_defaults(self):
        from slappyengine.config import PixelPhysicsConfig
        p = PixelPhysicsConfig()
        assert p.gravity == pytest.approx(98.0)
        assert p.melt_temp == pytest.approx(100.0)
        assert p.boil_temp == pytest.approx(300.0)
        assert p.max_vel == pytest.approx(500.0)


class TestFluidSimConfig:
    def test_defaults(self):
        from slappyengine.config import FluidSimConfig
        f = FluidSimConfig()
        assert f.enabled is False
        assert f.lod_mode == "exp"
        assert f.noise_type == "fbm"
        assert f.god_rays is True
        assert f.caustics is False

    def test_render_tint_tuple(self):
        from slappyengine.config import FluidSimConfig
        f = FluidSimConfig()
        assert len(f.render_tint) == 3


class TestAudioConfig:
    def test_defaults(self):
        from slappyengine.config import AudioConfig
        a = AudioConfig()
        assert a.speed_of_sound == pytest.approx(343.0)
        assert a.sonic_boom_threshold == pytest.approx(0.95)


class TestNetConfig:
    def test_defaults(self):
        from slappyengine.config import NetConfig
        n = NetConfig()
        assert n.enabled is False
        assert n.tick_rate == 30
        assert n.timeout_ms == 100
        assert n.max_players == 8
        assert n.use_lan_discovery is True
        assert n.use_dht_discovery is True
        assert n.udp_port == 0


class TestLightingConfig:
    def test_defaults(self):
        from slappyengine.config import LightingConfig
        l = LightingConfig()
        assert l.enabled is True
        assert l.max_point_lights == 16
        assert l.max_cone_lights == 8
        assert l.radiance_cascades is False
        assert l.clustered_lighting is True
        assert l.cluster_tile_size == 8

    def test_ambient_color_tuple(self):
        from slappyengine.config import LightingConfig
        l = LightingConfig()
        assert len(l.ambient_color) == 3


class TestDeformConfig:
    def test_defaults(self):
        from slappyengine.config import DeformConfig
        d = DeformConfig()
        assert d.sim_mode == "collision_triggered"
        assert d.decay_mode == "curve"
        assert d.spring_decay == pytest.approx(0.94)
        assert d.crack_mode == "none"
        assert d.crack_count == 6
        assert d.destroy_mode == "persist"
        assert d.repair_mode == "event_only"
        assert d.repair_rate == pytest.approx(1.0)
        assert d.critical_damage_threshold == pytest.approx(0.3)

    def test_decay_curve_non_empty(self):
        from slappyengine.config import DeformConfig
        d = DeformConfig()
        assert len(d.decay_curve) > 0

    def test_emit_events_list(self):
        from slappyengine.config import DeformConfig
        d = DeformConfig()
        assert isinstance(d.emit_events, list)
        assert "Deform.Impact" in d.emit_events

    def test_custom_crack_mode(self):
        from slappyengine.config import DeformConfig
        d = DeformConfig(crack_mode="radial", crack_count=8)
        assert d.crack_mode == "radial"
        assert d.crack_count == 8


class TestInputConfig:
    def test_defaults(self):
        from slappyengine.config import InputConfig
        i = InputConfig()
        assert i.default_player0 == "wasd"
        assert i.default_player1 == "arrows"


class TestSplitScreenConfig:
    def test_defaults(self):
        from slappyengine.config import SplitScreenConfig
        s = SplitScreenConfig()
        assert s.enabled is False
        assert s.border_px == 2
        assert len(s.border_color) == 3


class TestMaterialsConfig:
    def test_defaults(self):
        from slappyengine.config import MaterialsConfig
        m = MaterialsConfig()
        assert m.auto_dispatch is True
        assert m.max_materials == 64
        assert m.dispatch_frequency == 1


# ---------------------------------------------------------------------------
# DeformRepairer
# ---------------------------------------------------------------------------

class TestDeformRepairer:
    def _layer(self, h=32, w=32, alpha=255):
        class FakeLayer:
            def __init__(self, h, w, a):
                self._image_data = np.full((h, w, 4), 0, dtype=np.uint8)
                self._image_data[:, :, 3] = a
        return FakeLayer(h, w, alpha)

    def test_instantiates(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        assert r is not None

    def test_queue_radial_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.queue_radial(16, 16, radius=8.0, rate=2.0)
        assert len(r._pending) == 1

    def test_queue_pixel_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.queue_pixel(5, 10)
        assert len(r._pending) == 1

    def test_queue_full_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.queue_full(rate=1.5)
        assert len(r._pending) == 1

    def test_dispatch_no_queue_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.dispatch()

    def test_dispatch_clears_queue(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.queue_radial(16, 16, radius=8.0)
        r.dispatch()
        assert len(r._pending) == 0

    def test_dispatch_radial_repairs_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = self._layer(alpha=0)
        r = DeformRepairer(layer)
        r.queue_radial(16, 16, radius=10.0, rate=50.0, falloff=False)
        r.dispatch()
        # Center pixel should have been repaired
        assert layer._image_data[16, 16, 3] > 0

    def test_dispatch_full_repairs_all(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = self._layer(alpha=0)
        r = DeformRepairer(layer)
        r.queue_full(rate=100.0)
        r.dispatch()
        assert np.all(layer._image_data[:, :, 3] > 0)

    def test_repair_capped_by_original_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = self._layer(alpha=0)
        orig = np.full((32, 32), 128.0, dtype=np.float32)
        r = DeformRepairer(layer, original_alpha=orig)
        r.queue_full(rate=500.0)  # huge rate
        r.dispatch()
        # Max restored alpha should not exceed 128
        assert int(layer._image_data[:, :, 3].max()) <= 128

    def test_dispatch_pixel_repairs_single(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = self._layer(alpha=0)
        r = DeformRepairer(layer)
        r.queue_pixel(5, 7, rate=255.0)
        r.dispatch()
        assert layer._image_data[7, 5, 3] > 0

    def test_dispatch_with_falloff(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = self._layer(alpha=0)
        r = DeformRepairer(layer)
        r.queue_radial(16, 16, radius=8.0, rate=200.0, falloff=True)
        r.dispatch()
        center_alpha = layer._image_data[16, 16, 3]
        edge_alpha = layer._image_data[16, 24, 3]  # 8px from center
        # Center should get more repair than edge (falloff applied)
        assert center_alpha >= edge_alpha

    def test_none_layer_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer

        class EmptyLayer:
            _image_data = None

        r = DeformRepairer(EmptyLayer())
        r.queue_full(rate=1.0)
        r.dispatch()  # should not raise

    def test_multiple_events_queue(self):
        from slappyengine.deform_repair import DeformRepairer
        r = DeformRepairer(self._layer())
        r.queue_radial(5, 5, 4.0)
        r.queue_pixel(10, 10)
        r.queue_full(1.0)
        assert len(r._pending) == 3
        r.dispatch()
        assert len(r._pending) == 0
