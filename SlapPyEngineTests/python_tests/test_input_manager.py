"""Engine tests for input/_manager.py (InputManager) — headless."""
from __future__ import annotations
import pytest


class TestInputManagerInit:
    def test_instantiates(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m is not None

    def test_no_keys_held_initially(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert not m.key_held("a")

    def test_no_keys_just_pressed_initially(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert not m.key_just_pressed("a")

    def test_no_keys_just_released_initially(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert not m.key_just_released("a")

    def test_mouse_pos_zero_initially(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m.mouse_pos == (0.0, 0.0)


class TestInputManagerNormalize:
    def test_lowercase_passthrough(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("a") == "a"

    def test_uppercase_lowercased(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("A") == "a"

    def test_left_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("left") == "arrowleft"

    def test_right_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("right") == "arrowright"

    def test_up_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("up") == "arrowup"

    def test_down_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("down") == "arrowdown"

    def test_space_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("space") == " "

    def test_lmb_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("lmb") == "mouse_left"

    def test_rmb_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("rmb") == "mouse_right"

    def test_rctrl_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("rctrl") == "ctrl"

    def test_rshift_alias(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        assert m._normalize("rshift") == "shift"


class TestInputManagerKeyboard:
    def test_key_down_sets_held(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "w", "event_type": "key_down"})
        assert m.key_held("w")

    def test_key_down_sets_just_pressed(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "w", "event_type": "key_down"})
        assert m.key_just_pressed("w")

    def test_key_up_clears_held(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "a", "event_type": "key_down"})
        m._on_key_event({"key": "a", "event_type": "key_up"})
        assert not m.key_held("a")

    def test_key_up_sets_just_released(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "a", "event_type": "key_down"})
        m._on_key_event({"key": "a", "event_type": "key_up"})
        assert m.key_just_released("a")

    def test_key_held_second_down_does_not_double_add_just_pressed(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "s", "event_type": "key_down"})
        # Second key_down while still held (repeat event)
        m._on_key_event({"key": "s", "event_type": "key_down"})
        assert m.key_held("s")
        assert m.key_just_pressed("s")  # still in just_pressed from first event

    def test_frame_reset_clears_just_pressed(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "d", "event_type": "key_down"})
        m.frame_reset()
        assert not m.key_just_pressed("d")

    def test_frame_reset_clears_just_released(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "d", "event_type": "key_down"})
        m._on_key_event({"key": "d", "event_type": "key_up"})
        m.frame_reset()
        assert not m.key_just_released("d")

    def test_frame_reset_does_not_clear_held(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "q", "event_type": "key_down"})
        m.frame_reset()
        assert m.key_held("q")

    def test_key_held_uppercase_query(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "x", "event_type": "key_down"})
        assert m.key_held("X")  # alias normalization makes this work

    def test_alias_in_event_resolves(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"key": "ArrowLeft", "event_type": "key_down"})
        assert m.key_held("left")

    def test_empty_key_event_no_crash(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_key_event({"event_type": "key_down"})  # no "key" field

    def test_type_field_fallback(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        # Some backends use "type" instead of "event_type"
        m._on_key_event({"key": "e", "type": "key_down"})
        assert m.key_held("e")


class TestInputManagerMouse:
    def test_pointer_down_sets_mouse_held(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 1, "x": 10, "y": 20})
        assert m.key_held("mouse_left")

    def test_pointer_down_sets_just_pressed(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 1, "x": 0, "y": 0})
        assert m.key_just_pressed("lmb")

    def test_pointer_up_clears_held(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 1, "x": 0, "y": 0})
        m._on_pointer_event({"event_type": "pointer_up", "button": 1, "x": 0, "y": 0})
        assert not m.key_held("mouse_left")

    def test_pointer_up_sets_just_released(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 1, "x": 0, "y": 0})
        m._on_pointer_event({"event_type": "pointer_up", "button": 1, "x": 0, "y": 0})
        assert m.key_just_released("mouse_left")

    def test_pointer_move_updates_mouse_pos(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_move", "button": 0, "x": 320.0, "y": 240.0})
        assert m.mouse_pos == (320.0, 240.0)

    def test_right_mouse_button(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 2, "x": 0, "y": 0})
        assert m.key_held("mouse_right")

    def test_frame_reset_clears_mouse_just_pressed(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        m._on_pointer_event({"event_type": "pointer_down", "button": 1, "x": 0, "y": 0})
        m.frame_reset()
        assert not m.key_just_pressed("mouse_left")


class TestInputManagerGamepad:
    def test_axis_returns_zero_without_glfw(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        # No GLFW available in headless test — should return 0.0
        val = m.axis(0, 0)
        assert val == pytest.approx(0.0)

    def test_button_returns_false_without_glfw(self):
        from slappyengine.input._manager import InputManager
        m = InputManager()
        val = m.button(0, 0)
        assert val is False
