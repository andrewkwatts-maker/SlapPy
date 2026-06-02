"""Engine tests for deform sub-modules — headless CPU path.

Covers CrackPass (deform_crack), DeformRepairer (deform_repair),
and ZoneMap (deform_zones).
"""
from __future__ import annotations
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_layer(w=64, h=64, alpha=255):
    """Return a minimal layer stub with RGBA image data."""
    layer = type("L", (), {})()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    layer._image_data[:, :, :3] = 180
    layer._image_data[:, :, 3] = alpha
    return layer


# ---------------------------------------------------------------------------
# CrackPass (deform_crack.py)
# ---------------------------------------------------------------------------

class TestCrackPass:
    def test_init_no_pending(self):
        from slappyengine.deform_crack import CrackPass
        cp = CrackPass()
        assert cp._pending == []

    def test_queue_adds_event(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        cp.queue(32.0, 32.0, force=1.5, radius=20.0, mode=CRACK_RADIAL, ray_count=8)
        assert len(cp._pending) == 1

    def test_queue_none_mode_is_ignored(self):
        from slappyengine.deform_crack import CrackPass, CRACK_NONE
        cp = CrackPass()
        cp.queue(0, 0, force=1.0, radius=10.0, mode=CRACK_NONE, ray_count=4)
        assert len(cp._pending) == 0

    def test_dispatch_clears_pending(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        layer = _make_layer()
        cp.queue(32.0, 32.0, force=1.0, radius=10.0, mode=CRACK_RADIAL, ray_count=4)
        cp.dispatch(layer, gpu_ctx=None)
        assert len(cp._pending) == 0

    def test_dispatch_no_pending_no_crash(self):
        from slappyengine.deform_crack import CrackPass
        cp = CrackPass()
        layer = _make_layer()
        cp.dispatch(layer, gpu_ctx=None)

    def test_dispatch_cpu_reduces_alpha_near_impact(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        layer = _make_layer(alpha=255)
        # Strong force, many rays, large radius → centre should lose alpha
        cp.queue(32.0, 32.0, force=10.0, radius=20.0, mode=CRACK_RADIAL, ray_count=16)
        cp.dispatch(layer, gpu_ctx=None)
        # At least some pixels around centre should have reduced alpha
        region = layer._image_data[28:36, 28:36, 3]
        assert int(region.min()) < 255

    def test_dispatch_cpu_no_image_data_no_crash(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        layer = type("L", (), {"_image_data": None})()
        cp.queue(10.0, 10.0, force=1.0, radius=5.0, mode=CRACK_RADIAL, ray_count=4)
        cp.dispatch(layer, gpu_ctx=None)

    def test_dispatch_cpu_no_alpha_channel_no_crash(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        layer = type("L", (), {})()
        layer._image_data = np.zeros((32, 32, 3), dtype=np.uint8)  # no alpha
        cp.queue(16.0, 16.0, force=1.0, radius=5.0, mode=CRACK_RADIAL, ray_count=4)
        cp.dispatch(layer, gpu_ctx=None)

    def test_dispatch_cpu_grain_mode_falls_back_to_radial(self):
        from slappyengine.deform_crack import CrackPass, CRACK_GRAIN
        cp = CrackPass()
        layer = _make_layer(alpha=255)
        cp.queue(32.0, 32.0, force=5.0, radius=15.0, mode=CRACK_GRAIN, ray_count=8)
        cp.dispatch(layer, gpu_ctx=None)  # CPU only does radial; should not raise

    def test_multiple_queued_events_all_dispatched(self):
        from slappyengine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        layer = _make_layer(alpha=255)
        for i in range(5):
            cp.queue(float(i * 10), 32.0, force=2.0, radius=10.0,
                     mode=CRACK_RADIAL, ray_count=4)
        assert len(cp._pending) == 5
        cp.dispatch(layer, gpu_ctx=None)
        assert len(cp._pending) == 0


# ---------------------------------------------------------------------------
# DeformRepairer (deform_repair.py)
# ---------------------------------------------------------------------------

class TestDeformRepairer:
    def test_init_no_pending(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        assert dr._pending == []

    def test_queue_radial_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        dr.queue_radial(32.0, 32.0, radius=10.0, rate=2.0)
        assert len(dr._pending) == 1

    def test_queue_pixel_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        dr.queue_pixel(16, 16)
        assert len(dr._pending) == 1

    def test_queue_full_adds_event(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        dr.queue_full(rate=1.0)
        assert len(dr._pending) == 1

    def test_dispatch_clears_pending(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=100)
        original = layer._image_data[:, :, 3].copy().astype(np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=2.0)
        dr.dispatch(gpu_ctx=None)
        assert len(dr._pending) == 0

    def test_dispatch_no_pending_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        dr.dispatch(gpu_ctx=None)

    def test_radial_repair_increases_alpha_near_centre(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=100)
        original = np.full((64, 64), 255, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_radial(32.0, 32.0, radius=10.0, rate=50.0)
        dr.dispatch(gpu_ctx=None)
        centre_alpha = int(layer._image_data[32, 32, 3])
        assert centre_alpha > 100

    def test_pixel_repair_increases_alpha_at_pixel(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=0)
        original = np.full((64, 64), 255, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_pixel(20, 20, rate=50.0)
        dr.dispatch(gpu_ctx=None)
        assert int(layer._image_data[20, 20, 3]) > 0

    def test_full_repair_increases_all_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=50)
        original = np.full((64, 64), 200, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=10.0)
        dr.dispatch(gpu_ctx=None)
        assert float(layer._image_data[:, :, 3].mean()) > 50.0

    def test_repair_does_not_exceed_original_alpha(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=180)
        original = np.full((64, 64), 180, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=999.0)
        dr.dispatch(gpu_ctx=None)
        assert int(layer._image_data[:, :, 3].max()) <= 180

    def test_dispatch_no_image_data_no_crash(self):
        from slappyengine.deform_repair import DeformRepairer
        layer = type("L", (), {"_image_data": None})()
        dr = DeformRepairer(layer)
        dr.queue_pixel(0, 0)
        dr.dispatch(gpu_ctx=None)


# ---------------------------------------------------------------------------
# ZoneMap (deform_zones.py)
# ---------------------------------------------------------------------------

class TestZoneMap:
    def test_init_empty(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        assert len(zm._zones) == 0

    def test_add_rect_zone_stores_zone(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("head", x=10, y=0, w=20, h=15)
        assert len(zm._zones) == 1
        assert zm._zones[0].name == "head"

    def test_zone_integrity_starts_at_one(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(64, 64)
        zm.add_rect_zone("torso", x=0, y=0, w=64, h=64)
        img = np.full((64, 64, 4), 255, dtype=np.uint8)
        zm.update(img)
        assert zm._zone_integrity.get("torso", 1.0) == pytest.approx(1.0, abs=0.05)

    def test_damaged_zone_integrity_below_one(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(64, 64)
        zm.add_rect_zone("front", x=0, y=0, w=32, h=32)
        img = np.zeros((64, 64, 4), dtype=np.uint8)
        img[:32, :32, 3] = 50  # low alpha = heavy damage
        zm.update(img)
        assert zm._zone_integrity.get("front", 1.0) < 1.0

    def test_destroy_event_fires_when_below_threshold(self):
        from slappyengine.deform_zones import ZoneMap
        from slappyengine.event_bus import subscribe, unsubscribe
        zm = ZoneMap(32, 32)
        zm.add_rect_zone("weakspot", x=0, y=0, w=32, h=32,
                          threshold=0.5,
                          on_destroy="Test.ZoneDestroyed")
        img = np.zeros((32, 32, 4), dtype=np.uint8)
        img[:, :, 3] = 0  # fully transparent = 0 integrity
        events = []
        h = subscribe("Test.ZoneDestroyed", lambda e: events.append(e))
        try:
            zm.update(img)
            assert len(events) >= 1
        finally:
            unsubscribe(h)

    def test_destroy_fires_only_once(self):
        from slappyengine.deform_zones import ZoneMap
        from slappyengine.event_bus import subscribe, unsubscribe
        zm = ZoneMap(32, 32)
        zm.add_rect_zone("zone", x=0, y=0, w=32, h=32,
                          threshold=0.9,
                          on_destroy="Test.OnceZone")
        img = np.zeros((32, 32, 4), dtype=np.uint8)
        events = []
        h = subscribe("Test.OnceZone", lambda e: events.append(e))
        try:
            zm.update(img)
            zm.update(img)
            zm.update(img)
            assert len(events) == 1
        finally:
            unsubscribe(h)

    def test_get_zone_integrity_returns_value(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(64, 64)
        zm.add_rect_zone("part", x=0, y=0, w=64, h=64)
        img = np.full((64, 64, 4), 128, dtype=np.uint8)
        zm.update(img)
        val = zm.integrity("part")
        assert 0.0 <= val <= 1.0

    def test_get_zone_integrity_missing_returns_one(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(32, 32)
        assert zm.integrity("nonexistent") == pytest.approx(1.0)

    def test_multiple_zones_tracked_independently(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(64, 32)
        zm.add_rect_zone("left", x=0, y=0, w=32, h=32)
        zm.add_rect_zone("right", x=32, y=0, w=32, h=32)
        img = np.full((32, 64, 4), 255, dtype=np.uint8)
        img[:, :32, 3] = 10  # left side heavily damaged
        zm.update(img)
        assert zm.integrity("left") < zm.integrity("right")

    def test_strength_scale_stored_on_zone(self):
        from slappyengine.deform_zones import ZoneMap
        zm = ZoneMap(64, 64)
        zm.add_rect_zone("weak", x=0, y=0, w=32, h=32, strength_scale=0.3)
        assert zm._zones[0].strength_scale == pytest.approx(0.3)
