"""Headless tests for pure-Python engine modules.

Covers:
- slappyengine.tags            (TagRegistry)
- slappyengine.z_height        (ZLayer, ZAABBShape, ZHeightModule, check_z_aabb)
- slappyengine.render_channel  (RenderPass, NightVisionPass, ThermalPass,
                                RenderChannelCompositor pure-Python API)
- slappyengine.render_target   (RenderTarget)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# tags.py — TagRegistry
# ---------------------------------------------------------------------------

class TestTagRegistryInit:
    def test_instantiates(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert r is not None

    def test_default_max_bits_32(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert r._max_bits == 32

    def test_custom_max_bits(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry(max_bits=64)
        assert r._max_bits == 64

    def test_no_tags_initially(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert r._tags == {}

    def test_next_bit_starts_zero(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert r._next_bit == 0


class TestTagRegistryDefine:
    def test_define_returns_bitmask(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        mask = r.define("player")
        assert mask == 1  # bit 0 → 2^0 = 1

    def test_define_second_tag(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("player")
        mask = r.define("enemy")
        assert mask == 2  # bit 1 → 2^1 = 2

    def test_define_idempotent(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        m1 = r.define("player")
        m2 = r.define("player")
        assert m1 == m2

    def test_define_explicit_bit(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        mask = r.define("special", bit=5)
        assert mask == (1 << 5)

    def test_define_exceeds_max_bits_raises(self):
        import pytest
        from slappyengine.tags import TagRegistry
        r = TagRegistry(max_bits=4)
        with pytest.raises(ValueError):
            r.define("overflow", bit=4)

    def test_contains_after_define(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("hero")
        assert "hero" in r

    def test_not_contains_undefined(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert "ghost" not in r

    def test_getitem_returns_mask(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("bullet")
        assert r["bullet"] == 1

    def test_auto_sequential_bits(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        masks = [r.define(f"tag{i}") for i in range(8)]
        assert masks == [1 << i for i in range(8)]


class TestTagRegistryMask:
    def test_mask_single_tag(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("player")
        assert r.mask("player") == 1

    def test_mask_two_tags(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("player")
        r.define("enemy")
        combined = r.mask("player", "enemy")
        assert combined == 3  # bits 0 and 1

    def test_mask_three_tags(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("a")
        r.define("b")
        r.define("c")
        combined = r.mask("a", "b", "c")
        assert combined == 7

    def test_mask_undefined_tag_raises(self):
        import pytest
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        with pytest.raises(KeyError):
            r.mask("undefined")

    def test_name_for_bit(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("alpha")
        assert r.name_for_bit(0) == "alpha"

    def test_name_for_bit_none_if_missing(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        assert r.name_for_bit(5) is None

    def test_all_tags_returns_dict(self):
        from slappyengine.tags import TagRegistry
        r = TagRegistry()
        r.define("x")
        r.define("y")
        d = r.all_tags()
        assert isinstance(d, dict)
        assert "x" in d and "y" in d


# ---------------------------------------------------------------------------
# z_height.py
# ---------------------------------------------------------------------------

class TestZLayer:
    def test_instantiates(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="ground")
        assert zl is not None

    def test_name_stored(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="sky")
        assert zl.name == "sky"

    def test_default_z(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="mid")
        assert zl.z == 0.0

    def test_custom_z(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="high", z=10.0)
        assert zl.z == 10.0

    def test_default_parallax(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="bg")
        assert zl.parallax_x == 1.0
        assert zl.parallax_y == 1.0

    def test_default_shadow_receiver(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="floor")
        assert zl.is_shadow_receiver is True

    def test_hash_is_identity(self):
        from slappyengine.z_height import ZLayer
        zl = ZLayer(name="layer")
        assert hash(zl) == id(zl)


class TestZAABBShape:
    def test_instantiates(self):
        from slappyengine.z_height import ZAABBShape
        s = ZAABBShape(width=32.0, height=48.0)
        assert s is not None

    def test_width_height(self):
        from slappyengine.z_height import ZAABBShape
        s = ZAABBShape(width=16.0, height=24.0)
        assert s.width == 16.0
        assert s.height == 24.0

    def test_default_z_range(self):
        from slappyengine.z_height import ZAABBShape
        s = ZAABBShape(width=10, height=10)
        assert s.z_min == 0.0
        assert s.z_max == 0.0

    def test_custom_z_range(self):
        from slappyengine.z_height import ZAABBShape
        s = ZAABBShape(width=10, height=10, z_min=2.0, z_max=8.0)
        assert s.z_min == 2.0
        assert s.z_max == 8.0

    def test_default_offset_zero(self):
        from slappyengine.z_height import ZAABBShape
        s = ZAABBShape(width=10, height=10)
        assert s.offset_x == 0.0
        assert s.offset_y == 0.0


class TestCheckZAabb:
    def _entity(self, z_min=0.0, z_max=1.0, z_height=0.0):
        class E:
            pass
        e = E()
        from slappyengine.z_height import ZAABBShape
        e.z_collision_shape = ZAABBShape(width=10, height=10, z_min=z_min, z_max=z_max)
        e.z_height = z_height
        return e

    def test_overlap_returns_true(self):
        from slappyengine.z_height import check_z_aabb
        a = self._entity(z_min=0.0, z_max=2.0)
        b = self._entity(z_min=1.0, z_max=3.0)
        assert check_z_aabb(a, b) is True

    def test_no_overlap_returns_false(self):
        from slappyengine.z_height import check_z_aabb
        a = self._entity(z_min=0.0, z_max=1.0)
        b = self._entity(z_min=2.0, z_max=3.0)
        assert check_z_aabb(a, b) is False

    def test_touching_returns_true(self):
        from slappyengine.z_height import check_z_aabb
        a = self._entity(z_min=0.0, z_max=1.0)
        b = self._entity(z_min=1.0, z_max=2.0)
        assert check_z_aabb(a, b) is True  # touching at z=1

    def test_no_shape_returns_true(self):
        from slappyengine.z_height import check_z_aabb
        class E:
            pass
        a = E()
        b = self._entity()
        assert check_z_aabb(a, b) is True  # no z_collision_shape on a

    def test_both_no_shape_returns_true(self):
        from slappyengine.z_height import check_z_aabb
        class E:
            pass
        assert check_z_aabb(E(), E()) is True

    def test_z_height_offset_applied(self):
        from slappyengine.z_height import check_z_aabb
        # a at z [0,1] + z_height=5 → [5,6]; b at [0,1] → no overlap
        a = self._entity(z_min=0.0, z_max=1.0, z_height=5.0)
        b = self._entity(z_min=0.0, z_max=1.0, z_height=0.0)
        assert check_z_aabb(a, b) is False


# ---------------------------------------------------------------------------
# render_channel.py — RenderPass dataclass + pre-built passes
# ---------------------------------------------------------------------------

class TestRenderPass:
    def test_instantiates(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="test")
        assert rp is not None

    def test_name_stored(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="nv")
        assert rp.name == "nv"

    def test_default_tint(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="base")
        assert rp.tint == (1.0, 1.0, 1.0)

    def test_default_gain(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="base")
        assert rp.gain == 1.0

    def test_default_blend_mode(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="base")
        assert rp.blend_mode == "lerp"

    def test_default_blend_alpha_zero(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="base")
        assert rp.blend_alpha == 0.0

    def test_custom_tint(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="t", tint=(0.5, 0.5, 0.5))
        assert rp.tint == (0.5, 0.5, 0.5)

    def test_default_post_shaders_empty(self):
        from slappyengine.render_channel import RenderPass
        rp = RenderPass(name="x")
        assert rp.post_shaders == []


class TestPrebuiltPasses:
    def test_night_vision_pass_name(self):
        from slappyengine.render_channel import NightVisionPass
        assert NightVisionPass.name == "night_vision"

    def test_night_vision_green_tint(self):
        from slappyengine.render_channel import NightVisionPass
        r, g, b = NightVisionPass.tint
        assert g > r and g > b

    def test_night_vision_gain_above_one(self):
        from slappyengine.render_channel import NightVisionPass
        assert NightVisionPass.gain > 1.0

    def test_night_vision_blend_mode_replace(self):
        from slappyengine.render_channel import NightVisionPass
        assert NightVisionPass.blend_mode == "replace"

    def test_thermal_pass_name(self):
        from slappyengine.render_channel import ThermalPass
        assert ThermalPass.name == "thermal"

    def test_thermal_pass_red_tint(self):
        from slappyengine.render_channel import ThermalPass
        r, g, b = ThermalPass.tint
        assert r > g and r > b

    def test_thermal_pass_blend_mode_replace(self):
        from slappyengine.render_channel import ThermalPass
        assert ThermalPass.blend_mode == "replace"


class TestRenderChannelCompositor:
    def _make_compositor(self):
        from slappyengine.render_channel import RenderChannelCompositor
        return RenderChannelCompositor(gpu=None, width=1280, height=720)

    def test_instantiates(self):
        c = self._make_compositor()
        assert c is not None

    def test_passes_empty_initially(self):
        c = self._make_compositor()
        assert c._passes == {}

    def test_add_channel_by_pass(self):
        from slappyengine.render_channel import RenderChannelCompositor, RenderPass
        c = self._make_compositor()
        rp = RenderPass(name="test_pass")
        added = c.add_channel(rp)
        assert added is rp
        assert "test_pass" in c._passes

    def test_add_channel_by_string(self):
        from slappyengine.render_channel import RenderChannelCompositor, RenderPass
        c = self._make_compositor()
        added = c.add_channel("my_channel")
        assert isinstance(added, RenderPass)
        assert added.name == "my_channel"
        assert "my_channel" in c._passes

    def test_set_mix_clamps_to_zero(self):
        from slappyengine.render_channel import RenderChannelCompositor, RenderPass
        c = self._make_compositor()
        c.add_channel("ch")
        c.set_mix("ch", -0.5)
        assert c._passes["ch"].blend_alpha == 0.0

    def test_set_mix_clamps_to_one(self):
        from slappyengine.render_channel import RenderChannelCompositor, RenderPass
        c = self._make_compositor()
        c.add_channel("ch")
        c.set_mix("ch", 1.5)
        assert c._passes["ch"].blend_alpha == 1.0

    def test_set_mix_sets_value(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.set_mix("nv", 0.7)
        assert abs(c._passes["nv"].blend_alpha - 0.7) < 1e-9

    def test_set_mix_nonexistent_no_crash(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.set_mix("ghost", 1.0)  # should not raise

    def test_lerp_to_sets_transition(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.lerp_to("nv", 1.0, duration=1.0)
        assert "nv" in c._transitions

    def test_lerp_to_nonexistent_no_crash(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.lerp_to("ghost", 1.0)  # should not raise

    def test_tick_advances_blend_alpha(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.lerp_to("nv", 1.0, duration=1.0)
        c.tick(0.5)
        assert c._passes["nv"].blend_alpha > 0.0

    def test_tick_completes_transition(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.lerp_to("nv", 1.0, duration=0.1)
        c.tick(1.0)  # large dt — should complete
        assert abs(c._passes["nv"].blend_alpha - 1.0) < 1e-9
        assert "nv" not in c._transitions

    def test_active_passes_empty_when_all_alpha_zero(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.add_channel("thermal")
        assert c.active_passes == []

    def test_active_passes_includes_nonzero_alpha(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = self._make_compositor()
        c.add_channel("nv")
        c.set_mix("nv", 0.5)
        active = c.active_passes
        assert len(active) == 1
        assert active[0].name == "nv"

    def test_width_height_stored(self):
        from slappyengine.render_channel import RenderChannelCompositor
        c = RenderChannelCompositor(gpu=None, width=800, height=600)
        assert c._width == 800
        assert c._height == 600


# ---------------------------------------------------------------------------
# render_target.py — RenderTarget
# ---------------------------------------------------------------------------

class TestRenderTarget:
    def test_instantiates(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt is not None

    def test_default_name(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.name == ""

    def test_custom_name(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(name="hud")
        assert rt.name == "hud"

    def test_default_size(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.size == (64, 64)

    def test_custom_size(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget(size=(1280, 720))
        assert rt.size == (1280, 720)

    def test_layers_empty(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.layers == []

    def test_visible_true(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.visible is True

    def test_z_order_zero(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.z_order == 0.0

    def test_post_process_none(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.post_process is None

    def test_default_position(self):
        from slappyengine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.position == (0.0, 0.0)

    def test_add_layer_appends(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        layer = Layer2D(width=64, height=64)
        rt.add_layer(layer)
        assert len(rt.layers) == 1

    def test_add_layer_returns_layer(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        layer = Layer2D(width=32, height=32)
        result = rt.add_layer(layer)
        assert result is layer

    def test_add_layer_sets_entity(self):
        from slappyengine.render_target import RenderTarget
        from slappyengine.layer import Layer2D
        rt = RenderTarget()
        layer = Layer2D(width=16, height=16)
        rt.add_layer(layer)
        assert layer.entity is rt
