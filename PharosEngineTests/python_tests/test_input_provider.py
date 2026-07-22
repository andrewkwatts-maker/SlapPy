"""Engine tests for input_provider.py — headless (no pygame/gamepad required)."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# InputProvider protocol
# ---------------------------------------------------------------------------

class TestInputProviderProtocol:
    def test_protocol_is_runtime_checkable(self):
        from pharos_engine.input_provider import InputProvider
        # A class with get_axes and get_actions should satisfy the protocol
        class MockInput:
            def get_axes(self): return {}
            def get_actions(self): return {}
        assert isinstance(MockInput(), InputProvider)

    def test_missing_method_fails_check(self):
        from pharos_engine.input_provider import InputProvider
        class BadInput:
            def get_axes(self): return {}
            # missing get_actions
        assert not isinstance(BadInput(), InputProvider)


# ---------------------------------------------------------------------------
# PlayerInputProvider (no input_manager → returns zeros)
# ---------------------------------------------------------------------------

class TestPlayerInputProviderInit:
    def test_instantiates(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p is not None

    def test_default_player_id(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p.player_id == 0

    def test_custom_player_id(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider(player_id=1)
        assert p.player_id == 1

    def test_no_gamepad_initially(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p.has_gamepad() is False

    def test_gamepad_idx_initially_none(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        assert p._gamepad_idx is None

    def test_satisfies_input_provider_protocol(self):
        from pharos_engine.input_provider import PlayerInputProvider, InputProvider
        p = PlayerInputProvider()
        assert isinstance(p, InputProvider)


class TestPlayerInputProviderNoManager:
    def test_get_axes_returns_zeros_without_manager(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        axes = p.get_axes()
        assert axes["throttle"] == pytest.approx(0.0)
        assert axes["brake"] == pytest.approx(0.0)
        assert axes["steer"] == pytest.approx(0.0)

    def test_get_actions_returns_false_without_manager(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        actions = p.get_actions()
        assert actions["fire"] is False
        assert actions["nitro"] is False

    def test_get_axes_has_required_keys(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        axes = p.get_axes()
        assert "throttle" in axes
        assert "brake" in axes
        assert "steer" in axes

    def test_get_actions_has_required_keys(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        actions = p.get_actions()
        assert "fire" in actions
        assert "nitro" in actions


class TestPlayerInputProviderGamepad:
    def test_use_gamepad_returns_false_without_pygame(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        result = p.use_gamepad(0)
        assert result is False

    def test_rumble_no_crash_without_gamepad(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        p.rumble(duration=0.1, strength=0.5)  # no-op, should not raise

    def test_bindings_defined_for_player_0(self):
        from pharos_engine.input_provider import PlayerInputProvider
        b = PlayerInputProvider._BINDINGS[0]
        assert "accel" in b
        assert "brake" in b
        assert "left" in b
        assert "right" in b

    def test_bindings_defined_for_player_1(self):
        from pharos_engine.input_provider import PlayerInputProvider
        b = PlayerInputProvider._BINDINGS[1]
        assert "accel" in b
        assert "fire" in b


class TestPlayerInputProviderRumbleEvents:
    def test_subscribe_rumble_no_crash(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        p.subscribe_rumble_events()
        assert len(p._rumble_handles) == 4

    def test_unsubscribe_rumble_clears_handles(self):
        from pharos_engine.input_provider import PlayerInputProvider
        p = PlayerInputProvider()
        p.subscribe_rumble_events()
        p.unsubscribe_rumble_events()
        assert p._rumble_handles == []


# ---------------------------------------------------------------------------
# ScriptInputProvider
# ---------------------------------------------------------------------------

class TestScriptInputProviderInit:
    def test_instantiates(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        assert s is not None

    def test_initial_axes_zero(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        axes = s.get_axes()
        assert axes["throttle"] == pytest.approx(0.0)
        assert axes["brake"] == pytest.approx(0.0)
        assert axes["steer"] == pytest.approx(0.0)

    def test_initial_actions_false(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        actions = s.get_actions()
        assert actions["fire"] is False
        assert actions["nitro"] is False

    def test_satisfies_protocol(self):
        from pharos_engine.input_provider import ScriptInputProvider, InputProvider
        s = ScriptInputProvider()
        assert isinstance(s, InputProvider)


class TestScriptInputProviderSetAxis:
    def test_set_axis_throttle(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_axis("throttle", 0.8)
        assert s.get_axes()["throttle"] == pytest.approx(0.8)

    def test_set_axis_steer(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_axis("steer", -0.5)
        assert s.get_axes()["steer"] == pytest.approx(-0.5)

    def test_set_axis_coerces_to_float(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_axis("brake", 1)  # int input
        assert isinstance(s.get_axes()["brake"], float)

    def test_set_action_fire(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_action("fire", True)
        assert s.get_actions()["fire"] is True

    def test_set_action_nitro(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_action("nitro", True)
        assert s.get_actions()["nitro"] is True

    def test_set_action_coerces_to_bool(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_action("fire", 1)  # truthy int
        assert s.get_actions()["fire"] is True

    def test_get_axes_returns_copy(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        a1 = s.get_axes()
        a1["throttle"] = 99.0
        assert s.get_axes()["throttle"] == pytest.approx(0.0)


class TestScriptInputProviderReset:
    def test_reset_zeros_axes(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_axis("throttle", 1.0)
        s.set_axis("steer", 0.7)
        s.reset()
        axes = s.get_axes()
        assert axes["throttle"] == pytest.approx(0.0)
        assert axes["steer"] == pytest.approx(0.0)

    def test_reset_clears_actions(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.set_action("fire", True)
        s.reset()
        assert s.get_actions()["fire"] is False

    def test_after_reset_axes_have_standard_keys(self):
        from pharos_engine.input_provider import ScriptInputProvider
        s = ScriptInputProvider()
        s.reset()
        assert "throttle" in s.get_axes()
        assert "brake" in s.get_axes()
        assert "steer" in s.get_axes()
