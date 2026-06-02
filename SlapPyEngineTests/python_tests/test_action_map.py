"""Engine tests for ActionMap + normalize_key — headless."""
from __future__ import annotations
import pytest


class TestNormalizeKey:
    def test_lowercase(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("W") == "w"
        assert normalize_key("SPACE") == "space"

    def test_alias_ctrl(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("ctrl") == "left_control"

    def test_alias_shift(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("shift") == "left_shift"

    def test_alias_alt(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("alt") == "left_alt"

    def test_alias_enter(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("enter") == "return"

    def test_alias_esc(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("esc") == "escape"

    def test_alias_up_arrow(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("up") == "arrowup"

    def test_alias_down_arrow(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("down") == "arrowdown"

    def test_alias_del(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("del") == "delete"

    def test_unknown_key_passed_through(self):
        from slappyengine.input.action_map import normalize_key
        assert normalize_key("gamepad0_a") == "gamepad0_a"


class TestActionMapBind:
    def test_bind_stores_action(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        assert am.is_held("jump") is False  # bound but not pressed

    def test_bind_normalises_key(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("dodge", "shift")
        # "shift" → "left_shift"
        assert "dodge" in am.actions_for_key("left_shift")

    def test_bind_replaces_existing(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("fire", "space")
        am.bind("fire", "f")
        # Old binding removed
        assert "fire" not in am.actions_for_key("space")
        assert "fire" in am.actions_for_key("f")

    def test_unbind_removes_action(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        am.unbind("jump")
        assert "jump" not in am.actions_for_key("space")

    def test_unbind_unbound_action_no_crash(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.unbind("nonexistent")  # should not raise


class TestActionMapPressRelease:
    def test_press_sets_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("move_up", "w")
        am._press("w")
        assert am.is_held("move_up") is True

    def test_release_clears_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("move_up", "w")
        am._press("w")
        am._release("w")
        assert am.is_held("move_up") is False

    def test_press_returns_triggered_actions(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        triggered = am._press("space")
        assert "jump" in triggered

    def test_press_twice_not_duplicated(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        am._press("space")
        triggered = am._press("space")  # already held
        assert "jump" not in triggered

    def test_release_returns_released_actions(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        am._press("space")
        released = am._release("space")
        assert "jump" in released

    def test_release_when_not_held_no_return(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        released = am._release("space")  # never pressed
        assert "jump" not in released

    def test_unbound_key_press_no_crash(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am._press("x")  # no binding

    def test_is_held_unknown_action_false(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        assert am.is_held("phantom") is False


class TestActionMapAxis:
    def test_axis_zero_when_neither_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("left", "a")
        am.bind("right", "d")
        am.bind_axis("horizontal", "left", "right")
        assert am.axis("horizontal") == pytest.approx(0.0)

    def test_axis_positive_when_pos_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("left", "a")
        am.bind("right", "d")
        am.bind_axis("horizontal", "left", "right")
        am._press("d")
        assert am.axis("horizontal") == pytest.approx(1.0)

    def test_axis_negative_when_neg_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("left", "a")
        am.bind("right", "d")
        am.bind_axis("horizontal", "left", "right")
        am._press("a")
        assert am.axis("horizontal") == pytest.approx(-1.0)

    def test_axis_zero_when_both_held(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("left", "a")
        am.bind("right", "d")
        am.bind_axis("horizontal", "left", "right")
        am._press("a")
        am._press("d")
        assert am.axis("horizontal") == pytest.approx(0.0)

    def test_axis_unknown_returns_zero(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        assert am.axis("nonexistent") == pytest.approx(0.0)


class TestActionMapActionsForKey:
    def test_actions_for_key_returns_list(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("jump", "space")
        am.bind("confirm", "space")  # two actions on same key
        actions = am.actions_for_key("space")
        assert "jump" in actions
        assert "confirm" in actions

    def test_actions_for_key_empty_when_unbound(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        assert am.actions_for_key("x") == []

    def test_actions_for_key_normalises_input(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap(player_id=0)
        am.bind("dodge", "shift")
        # Query with alias should work
        assert "dodge" in am.actions_for_key("left_shift")


class TestActionMapFactories:
    def test_from_dict(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap.from_dict(0, {"fire": "space", "jump": "w"})
        assert "fire" in am.actions_for_key("space")
        assert "jump" in am.actions_for_key("w")

    def test_wasd_factory_has_move_actions(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap.wasd()
        assert am.player_id == 0
        assert "move_up" in am.actions_for_key("w")
        assert "move_down" in am.actions_for_key("s")

    def test_arrows_factory_player_id_1(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap.arrows()
        assert am.player_id == 1
        assert "move_up" in am.actions_for_key("arrowup")

    def test_ijkl_factory_player_id_2(self):
        from slappyengine.input.action_map import ActionMap
        am = ActionMap.ijkl()
        assert am.player_id == 2
        assert "move_up" in am.actions_for_key("i")
        assert "move_down" in am.actions_for_key("k")
