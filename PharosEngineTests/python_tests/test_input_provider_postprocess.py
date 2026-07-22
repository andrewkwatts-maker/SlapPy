"""Headless tests for ScriptInputProvider, PlayerInputProvider (headless subset),
and PostProcessChain / PostProcessPass.

No GPU or keyboard state required.
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())


# ===========================================================================
# ScriptInputProvider
# ===========================================================================

class TestScriptInputProviderDefaults:
    def _sp(self):
        from pharos_engine.input_provider import ScriptInputProvider
        return ScriptInputProvider()

    def test_throttle_zero_initially(self):
        assert self._sp().get_axes()["throttle"] == 0.0

    def test_brake_zero_initially(self):
        assert self._sp().get_axes()["brake"] == 0.0

    def test_steer_zero_initially(self):
        assert self._sp().get_axes()["steer"] == 0.0

    def test_fire_false_initially(self):
        assert self._sp().get_actions()["fire"] is False

    def test_nitro_false_initially(self):
        assert self._sp().get_actions()["nitro"] is False

    def test_get_axes_returns_dict(self):
        assert isinstance(self._sp().get_axes(), dict)

    def test_get_actions_returns_dict(self):
        assert isinstance(self._sp().get_actions(), dict)

    def test_get_axes_is_copy(self):
        sp = self._sp()
        axes = sp.get_axes()
        axes["throttle"] = 99.0
        assert sp.get_axes()["throttle"] == 0.0  # original not modified

    def test_get_actions_is_copy(self):
        sp = self._sp()
        actions = sp.get_actions()
        actions["fire"] = True
        assert sp.get_actions()["fire"] is False


class TestScriptInputProviderSetAxis:
    def _sp(self):
        from pharos_engine.input_provider import ScriptInputProvider
        return ScriptInputProvider()

    def test_set_throttle(self):
        sp = self._sp()
        sp.set_axis("throttle", 1.0)
        assert sp.get_axes()["throttle"] == 1.0

    def test_set_steer_negative(self):
        sp = self._sp()
        sp.set_axis("steer", -0.5)
        assert abs(sp.get_axes()["steer"] - (-0.5)) < 1e-9

    def test_set_custom_axis(self):
        sp = self._sp()
        sp.set_axis("jump", 0.7)
        assert abs(sp.get_axes()["jump"] - 0.7) < 1e-9

    def test_set_axis_coerces_to_float(self):
        sp = self._sp()
        sp.set_axis("throttle", 1)  # int
        assert isinstance(sp.get_axes()["throttle"], float)

    def test_set_multiple_axes(self):
        sp = self._sp()
        sp.set_axis("throttle", 0.8)
        sp.set_axis("steer", -0.3)
        axes = sp.get_axes()
        assert abs(axes["throttle"] - 0.8) < 1e-9
        assert abs(axes["steer"] - (-0.3)) < 1e-9


class TestScriptInputProviderSetAction:
    def _sp(self):
        from pharos_engine.input_provider import ScriptInputProvider
        return ScriptInputProvider()

    def test_set_fire_true(self):
        sp = self._sp()
        sp.set_action("fire", True)
        assert sp.get_actions()["fire"] is True

    def test_set_nitro_true(self):
        sp = self._sp()
        sp.set_action("nitro", True)
        assert sp.get_actions()["nitro"] is True

    def test_set_action_coerces_to_bool(self):
        sp = self._sp()
        sp.set_action("fire", 1)  # truthy int
        assert sp.get_actions()["fire"] is True

    def test_set_action_zero_is_false(self):
        sp = self._sp()
        sp.set_action("fire", 0)
        assert sp.get_actions()["fire"] is False

    def test_set_custom_action(self):
        sp = self._sp()
        sp.set_action("boost", True)
        assert sp.get_actions()["boost"] is True


class TestScriptInputProviderReset:
    def _sp(self):
        from pharos_engine.input_provider import ScriptInputProvider
        return ScriptInputProvider()

    def test_reset_zeroes_axes(self):
        sp = self._sp()
        sp.set_axis("throttle", 1.0)
        sp.set_axis("steer", 0.5)
        sp.reset()
        axes = sp.get_axes()
        assert axes["throttle"] == 0.0
        assert axes["steer"] == 0.0

    def test_reset_releases_actions(self):
        sp = self._sp()
        sp.set_action("fire", True)
        sp.set_action("nitro", True)
        sp.reset()
        actions = sp.get_actions()
        assert actions["fire"] is False
        assert actions["nitro"] is False

    def test_reset_preserves_standard_keys(self):
        sp = self._sp()
        sp.reset()
        axes = sp.get_axes()
        assert "throttle" in axes
        assert "brake" in axes
        assert "steer" in axes


class TestScriptInputProviderProtocol:
    def test_satisfies_input_provider_protocol(self):
        from pharos_engine.input_provider import ScriptInputProvider, InputProvider
        sp = ScriptInputProvider()
        assert isinstance(sp, InputProvider)

    def test_has_get_axes(self):
        from pharos_engine.input_provider import ScriptInputProvider
        assert hasattr(ScriptInputProvider(), "get_axes")

    def test_has_get_actions(self):
        from pharos_engine.input_provider import ScriptInputProvider
        assert hasattr(ScriptInputProvider(), "get_actions")


# ===========================================================================
# PlayerInputProvider (headless / no keyboard state)
# ===========================================================================

class TestPlayerInputProviderConstants:
    def test_two_player_bindings(self):
        from pharos_engine.input_provider import PlayerInputProvider
        assert len(PlayerInputProvider._BINDINGS) == 2

    def test_player0_uses_wasd(self):
        from pharos_engine.input_provider import PlayerInputProvider
        b = PlayerInputProvider._BINDINGS[0]
        assert b["accel"] == "w"
        assert b["brake"] == "s"
        assert b["left"] == "a"
        assert b["right"] == "d"

    def test_player1_uses_arrows(self):
        from pharos_engine.input_provider import PlayerInputProvider
        b = PlayerInputProvider._BINDINGS[1]
        assert b["accel"] == "up"

    def test_deadzone_positive(self):
        from pharos_engine.input_provider import PlayerInputProvider
        assert PlayerInputProvider._GP_DEADZONE > 0


class TestPlayerInputProviderInit:
    def test_default_player_id(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p.player_id == 0

    def test_custom_player_id(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider(player_id=1)
        assert p.player_id == 1

    def test_no_gamepad_by_default(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p.has_gamepad() is False

    def test_get_axes_returns_dict(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        axes = p.get_axes()
        assert isinstance(axes, dict)

    def test_get_axes_has_throttle_brake_steer(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        axes = p.get_axes()
        assert "throttle" in axes
        assert "brake" in axes
        assert "steer" in axes

    def test_get_axes_zero_without_input(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        axes = p.get_axes()
        assert all(v == 0.0 for v in axes.values())

    def test_get_actions_returns_dict(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        actions = p.get_actions()
        assert isinstance(actions, dict)

    def test_get_actions_has_fire_nitro(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        actions = p.get_actions()
        assert "fire" in actions
        assert "nitro" in actions

    def test_get_actions_false_without_input(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        actions = p.get_actions()
        assert all(not v for v in actions.values())

    def test_satisfies_protocol(self):
        from pharos_engine.input_provider import PlayerInputProvider, InputProvider
        p = PlayerInputProvider()
        assert isinstance(p, InputProvider)


# ===========================================================================
# PostProcessPass
# ===========================================================================

class TestPostProcessPass:
    def _pass(self, **kwargs):
        from pharos_engine.post_process.chain import PostProcessPass
        return PostProcessPass("test.wgsl", **kwargs)

    def test_shader_path_stored(self):
        p = self._pass()
        assert p.shader_path == "test.wgsl"

    def test_label_stored(self):
        p = self._pass(label="my_pass")
        assert p.label == "my_pass"

    def test_enabled_default_true(self):
        p = self._pass()
        assert p.enabled is True

    def test_enabled_custom(self):
        p = self._pass(enabled=False)
        assert p.enabled is False

    def test_params_stored(self):
        p = self._pass(params={"strength": 0.5})
        assert p.params["strength"] == 0.5

    def test_params_none_by_default(self):
        p = self._pass()
        # None or empty dict both acceptable as "no params"
        assert not p.params

    def test_entry_point_default_main(self):
        p = self._pass()
        assert p.entry_point == "main"

    def test_entry_point_custom(self):
        p = self._pass(entry_point="fs_main")
        assert p.entry_point == "fs_main"

    def test_raw_params_none_by_default(self):
        p = self._pass()
        assert p.raw_params_bytes is None

    def test_raw_params_stored(self):
        raw = b"\x00\x01\x02"
        p = self._pass(raw_params_bytes=raw)
        assert p.raw_params_bytes == raw


# ===========================================================================
# PostProcessChain
# ===========================================================================

class TestPostProcessChainInit:
    def test_empty_passes_initially(self):
        from pharos_engine.post_process.chain import PostProcessChain
        assert PostProcessChain().passes == []

    def test_list_constructor(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        p1 = PostProcessPass("a.wgsl", label="a")
        p2 = PostProcessPass("b.wgsl", label="b")
        chain = PostProcessChain([p1, p2])
        assert len(chain.passes) == 2

    def test_passes_returns_list(self):
        from pharos_engine.post_process.chain import PostProcessChain
        assert isinstance(PostProcessChain().passes, list)


class TestPostProcessChainAdd:
    def test_add_increases_count(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        chain.add(PostProcessPass("x.wgsl", label="x"))
        assert len(chain.passes) == 1

    def test_add_multiple(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        chain.add(PostProcessPass("a.wgsl", label="a"))
        chain.add(PostProcessPass("b.wgsl", label="b"))
        assert len(chain.passes) == 2


class TestPostProcessChainRemove:
    def test_remove_by_label(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        p = chain.add_blur()
        chain.remove(p.label)
        labels = [x.label for x in chain.passes]
        assert p.label not in labels

    def test_remove_nonexistent_no_crash(self):
        from pharos_engine.post_process.chain import PostProcessChain
        PostProcessChain().remove("nonexistent")  # should not raise


class TestPostProcessChainFactories:
    def test_add_blur_returns_pass(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        p = chain.add_blur()
        assert isinstance(p, PostProcessPass)

    def test_add_blur_radius_in_params(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        p = chain.add_blur(radius=4)
        assert p.params["radius"] == 4

    def test_add_chromatic_aberration_strength(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        p = chain.add_chromatic_aberration(strength=0.007)
        assert abs(p.params["strength"] - 0.007) < 1e-9

    def test_add_night_vision(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        p = chain.add_night_vision()
        assert isinstance(p, PostProcessPass)

    def test_add_outline(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        p = chain.add_outline()
        assert isinstance(p, PostProcessPass)

    def test_add_pixelate_block_size(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        p = chain.add_pixelate(block_size=8)
        assert p.params["block_size"] == 8

    def test_add_gravity_warp(self):
        from pharos_engine.post_process.chain import PostProcessChain, PostProcessPass
        chain = PostProcessChain()
        p = chain.add_gravity_warp(center=(0.3, 0.7), strength=2.0, radius=0.2)
        assert isinstance(p, PostProcessPass)
        assert abs(p.params["strength"] - 2.0) < 1e-9

    def test_all_six_factories_add_to_chain(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        chain.add_blur()
        chain.add_chromatic_aberration()
        chain.add_night_vision()
        chain.add_outline()
        chain.add_pixelate()
        chain.add_gravity_warp()
        assert len(chain.passes) == 6

    def test_blur_label_is_blur(self):
        from pharos_engine.post_process.chain import PostProcessChain
        chain = PostProcessChain()
        p = chain.add_blur()
        assert p.label == "blur"
