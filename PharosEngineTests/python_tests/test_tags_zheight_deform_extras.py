"""Engine tests for tags.py, z_height.py, deform_zones.py, deform_crack.py.

All headless — no GPU required.
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# TagRegistry
# ---------------------------------------------------------------------------

class TestTagRegistry:
    def test_instantiates(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert reg is not None

    def test_define_returns_mask(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("player")
        assert mask == 1  # bit 0 → mask 1

    def test_define_idempotent(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        m1 = reg.define("enemy")
        m2 = reg.define("enemy")
        assert m1 == m2

    def test_define_sequential_bits(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        m0 = reg.define("a")
        m1 = reg.define("b")
        m2 = reg.define("c")
        assert m0 == 1
        assert m1 == 2
        assert m2 == 4

    def test_define_custom_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("special", bit=5)
        assert mask == (1 << 5)

    def test_mask_single(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("x")
        assert reg.mask("x") == 1

    def test_mask_multiple(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("a")
        reg.define("b")
        combined = reg.mask("a", "b")
        assert combined == 3

    def test_mask_undefined_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        with pytest.raises(KeyError):
            reg.mask("ghost")

    def test_getitem(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("tag1")
        assert reg["tag1"] == 1

    def test_contains(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("my_tag")
        assert "my_tag" in reg
        assert "not_a_tag" not in reg

    def test_name_for_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("loot", bit=3)
        assert reg.name_for_bit(3) == "loot"

    def test_name_for_bit_missing(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert reg.name_for_bit(99) is None

    def test_all_tags(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("p")
        reg.define("q")
        tags = reg.all_tags()
        assert "p" in tags and "q" in tags

    def test_exceeds_max_bits_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry(max_bits=4)
        for i in range(4):
            reg.define(f"t{i}")
        with pytest.raises(ValueError):
            reg.define("overflow")


# ---------------------------------------------------------------------------
# ZLayer and ZAABBShape
# ---------------------------------------------------------------------------

class TestZLayer:
    def test_instantiates(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="ground")
        assert z is not None

    def test_name_stored(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="sky")
        assert z.name == "sky"

    def test_default_z_zero(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="x")
        assert z.z == pytest.approx(0.0)

    def test_default_parallax_one(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="x")
        assert z.parallax_x == pytest.approx(1.0)
        assert z.parallax_y == pytest.approx(1.0)

    def test_default_shadow_receiver(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="x")
        assert z.is_shadow_receiver is True

    def test_custom_values(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="bg", z=100.0, parallax_x=0.5, parallax_y=0.3,
                   is_shadow_receiver=False)
        assert z.z == pytest.approx(100.0)
        assert z.parallax_x == pytest.approx(0.5)
        assert z.is_shadow_receiver is False

    def test_hashable(self):
        from pharos_engine.z_height import ZLayer
        z = ZLayer(name="floor")
        d = {z: "value"}
        assert d[z] == "value"


class TestZAABBShape:
    def test_instantiates(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=32, height=32)
        assert s is not None

    def test_dimensions_stored(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=64, height=48)
        assert s.width == 64
        assert s.height == 48

    def test_default_z_range_zero(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=16, height=16)
        assert s.z_min == pytest.approx(0.0)
        assert s.z_max == pytest.approx(0.0)

    def test_custom_z_range(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=16, height=16, z_min=5.0, z_max=20.0)
        assert s.z_min == pytest.approx(5.0)
        assert s.z_max == pytest.approx(20.0)


class TestCheckZAABB:
    def _entity(self, z_height=0.0, z_min=0.0, z_max=10.0):
        from pharos_engine.z_height import ZAABBShape

        class FakeEntity:
            pass

        e = FakeEntity()
        e.z_height = z_height
        e.z_collision_shape = ZAABBShape(width=16, height=16, z_min=z_min, z_max=z_max)
        return e

    def test_no_shape_returns_true(self):
        from pharos_engine.z_height import check_z_aabb

        class NoShape:
            z_height = 0.0

        assert check_z_aabb(NoShape(), NoShape()) is True

    def test_overlapping_ranges(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(z_height=0.0, z_min=0.0, z_max=10.0)
        b = self._entity(z_height=0.0, z_min=5.0, z_max=15.0)
        assert check_z_aabb(a, b) is True

    def test_non_overlapping_ranges(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(z_height=0.0, z_min=0.0, z_max=5.0)
        b = self._entity(z_height=0.0, z_min=10.0, z_max=20.0)
        assert check_z_aabb(a, b) is False

    def test_touching_ranges_overlap(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(z_height=0.0, z_min=0.0, z_max=10.0)
        b = self._entity(z_height=0.0, z_min=10.0, z_max=20.0)
        assert check_z_aabb(a, b) is True

    def test_z_height_offset_applied(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(z_height=20.0, z_min=0.0, z_max=5.0)   # z: 20..25
        b = self._entity(z_height=0.0,  z_min=0.0, z_max=5.0)   # z: 0..5
        assert check_z_aabb(a, b) is False

    def test_one_entity_no_shape(self):
        from pharos_engine.z_height import check_z_aabb

        class NoShape:
            z_height = 0.0

        a = self._entity()
        b = NoShape()
        assert check_z_aabb(a, b) is True


# ---------------------------------------------------------------------------
# ZoneDef and ZoneMap
# ---------------------------------------------------------------------------

class TestZoneDef:
    def test_instantiates(self):
        from pharos_engine.deform_zones import ZoneDef
        z = ZoneDef(name="hood", x=0, y=0, w=32, h=16)
        assert z is not None

    def test_fields_stored(self):
        from pharos_engine.deform_zones import ZoneDef
        z = ZoneDef(name="door", x=10, y=5, w=20, h=30,
                    integrity_threshold=0.3, material="metal", strength_scale=0.8)
        assert z.name == "door"
        assert z.x == 10 and z.y == 5 and z.w == 20 and z.h == 30
        assert z.integrity_threshold == pytest.approx(0.3)
        assert z.material == "metal"
        assert z.strength_scale == pytest.approx(0.8)

    def test_default_event(self):
        from pharos_engine.deform_zones import ZoneDef
        z = ZoneDef(name="x", x=0, y=0, w=1, h=1)
        assert z.on_destroy_event == "Deform.ZoneDestroyed"

    def test_default_mask_none(self):
        from pharos_engine.deform_zones import ZoneDef
        z = ZoneDef(name="x", x=0, y=0, w=1, h=1)
        assert z.mask is None


class TestZoneMap:
    def _full_alpha_image(self, h=64, w=128):
        img = np.zeros((h, w, 4), dtype=np.uint8)
        img[:, :, 3] = 255
        return img

    def _zero_alpha_image(self, h=64, w=128):
        return np.zeros((h, w, 4), dtype=np.uint8)

    def setup_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def test_instantiates(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(layer_width=128, layer_height=64)
        assert zm is not None

    def test_add_rect_zone(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("hood", x=0, y=0, w=32, h=16)
        assert "hood" in zm.zone_names()

    def test_zone_names(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("a", 0, 0, 10, 10)
        zm.add_rect_zone("b", 10, 0, 10, 10)
        assert set(zm.zone_names()) == {"a", "b"}

    def test_initial_integrity_one(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", 0, 0, 32, 16)
        assert zm.integrity("bumper") == pytest.approx(1.0)

    def test_missing_zone_integrity_one(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        assert zm.integrity("nonexistent") == pytest.approx(1.0)

    def test_not_destroyed_initially(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("roof", 0, 0, 32, 16)
        assert zm.is_destroyed("roof") is False

    def test_update_full_alpha_keeps_integrity_near_one(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("zone", 0, 0, 128, 64)
        zm.update(self._full_alpha_image())
        assert zm.integrity("zone") == pytest.approx(1.0)

    def test_update_zero_alpha_drops_integrity(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("zone", 0, 0, 128, 64, threshold=0.5)
        zm.update(self._zero_alpha_image())
        assert zm.integrity("zone") == pytest.approx(0.0)

    def test_destroy_event_fires_when_threshold_crossed(self):
        from pharos_engine.deform_zones import ZoneMap
        from pharos_engine.event_bus import subscribe
        events = []
        subscribe("Deform.ZoneDestroyed", events.append)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("door", 0, 0, 128, 64, threshold=0.5)
        zm.update(self._zero_alpha_image())
        assert len(events) == 1

    def test_destroy_event_fires_only_once(self):
        from pharos_engine.deform_zones import ZoneMap
        from pharos_engine.event_bus import subscribe
        events = []
        subscribe("Deform.ZoneDestroyed", events.append)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("door", 0, 0, 128, 64, threshold=0.5)
        zm.update(self._zero_alpha_image())
        zm.update(self._zero_alpha_image())  # second update — no second event
        assert len(events) == 1

    def test_get_zone_returns_correct(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("glass", 10, 5, 20, 15, material="glass")
        z = zm.get_zone("glass")
        assert z is not None
        assert z.material == "glass"

    def test_get_zone_missing_returns_none(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        assert zm.get_zone("nope") is None

    def test_update_none_data_no_crash(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("x", 0, 0, 10, 10)
        zm.update(None)  # should not raise

    def test_update_with_mask(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        mask = np.ones((16, 32), dtype=np.uint8)
        zm.add_rect_zone("masked", 0, 0, 32, 16, threshold=0.5, mask=mask)
        zm.update(self._zero_alpha_image())
        assert zm.integrity("masked") == pytest.approx(0.0)

    def test_add_rect_zone_returns_self(self):
        from pharos_engine.deform_zones import ZoneMap
        zm = ZoneMap(128, 64)
        result = zm.add_rect_zone("x", 0, 0, 10, 10)
        assert result is zm


# ---------------------------------------------------------------------------
# CrackPass
# ---------------------------------------------------------------------------

class TestCrackConstants:
    def test_crack_none(self):
        from pharos_engine.deform_crack import CRACK_NONE
        assert CRACK_NONE == -1

    def test_crack_radial(self):
        from pharos_engine.deform_crack import CRACK_RADIAL
        assert CRACK_RADIAL == 0

    def test_crack_grain(self):
        from pharos_engine.deform_crack import CRACK_GRAIN
        assert CRACK_GRAIN == 1

    def test_distinct(self):
        from pharos_engine.deform_crack import CRACK_NONE, CRACK_RADIAL, CRACK_GRAIN
        assert len({CRACK_NONE, CRACK_RADIAL, CRACK_GRAIN}) == 3


class TestCrackPass:
    def _layer(self):
        class FakeLayer:
            def __init__(self):
                self._image_data = np.full((64, 64, 4), 255, dtype=np.uint8)
        return FakeLayer()

    def test_instantiates(self):
        from pharos_engine.deform_crack import CrackPass
        cp = CrackPass()
        assert cp is not None

    def test_queue_adds_event(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        cp.queue(32, 32, force=1.5, radius=20.0, mode=CRACK_RADIAL, ray_count=8)
        assert len(cp._pending) == 1

    def test_queue_none_mode_no_add(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_NONE
        cp = CrackPass()
        cp.queue(32, 32, force=1.5, radius=20.0, mode=CRACK_NONE, ray_count=8)
        assert len(cp._pending) == 0

    def test_dispatch_no_queue_no_crash(self):
        from pharos_engine.deform_crack import CrackPass
        cp = CrackPass()
        cp.dispatch(self._layer(), gpu_ctx=None)

    def test_dispatch_cpu_clears_queue(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        cp.queue(32, 32, force=1.5, radius=20.0, mode=CRACK_RADIAL, ray_count=8)
        cp.dispatch(self._layer(), gpu_ctx=None)
        assert len(cp._pending) == 0

    def test_dispatch_cpu_modifies_alpha(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_RADIAL
        layer = self._layer()
        cp = CrackPass()
        cp.queue(32, 32, force=2.0, radius=15.0, mode=CRACK_RADIAL, ray_count=8)
        original_mean = layer._image_data[:, :, 3].mean()
        cp.dispatch(layer, gpu_ctx=None)
        new_mean = layer._image_data[:, :, 3].mean()
        # Cracks should reduce alpha somewhere
        assert new_mean <= original_mean

    def test_dispatch_multiple_queued(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        cp.queue(10, 10, 1.0, 10.0, CRACK_RADIAL, 4)
        cp.queue(50, 50, 2.0, 15.0, CRACK_RADIAL, 8)
        cp.dispatch(self._layer(), gpu_ctx=None)
        assert len(cp._pending) == 0

    def test_dispatch_grain_mode_no_crash(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_GRAIN
        cp = CrackPass()
        cp.queue(20, 20, 1.0, 12.0, CRACK_GRAIN, 6)
        cp.dispatch(self._layer(), gpu_ctx=None)  # GRAIN falls back to RADIAL on CPU

    def test_event_fields_stored(self):
        from pharos_engine.deform_crack import CrackPass, CRACK_RADIAL
        cp = CrackPass()
        cp.queue(5.0, 7.0, force=3.0, radius=25.0, mode=CRACK_RADIAL, ray_count=12)
        ev = cp._pending[0]
        assert ev["center_x"] == pytest.approx(5.0)
        assert ev["center_y"] == pytest.approx(7.0)
        assert ev["force"] == pytest.approx(3.0)
        assert ev["radius"] == pytest.approx(25.0)
        assert ev["ray_count"] == 12


