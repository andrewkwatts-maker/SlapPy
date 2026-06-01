"""Negative-path tests for :class:`InputManager` public-boundary validation
(hardening round 9).

The InputManager owns per-frame keyboard / mouse / gamepad state queried
every game loop tick. Silent acceptance of mistyped keys or out-of-range
gamepad indices would make "input not responding" or "axis returning the
wrong stick" bugs surface only at the player's machine. We refuse loudly
at the call site instead.

Silent-acceptance bugs found while writing this file (now fixed):

* ``key_held(b"a")`` previously called ``b"a".lower()`` which returns
  ``bytes``, then the membership test against the ``str`` keys held in
  ``_held`` silently returned ``False`` forever.
* ``axis(0, -1)`` previously evaluated ``-1 < len(axes)`` as true, then
  ``axes[-1]`` returned the LAST axis via Python negative indexing — a
  silent wrong-result bug instead of the documented ``0.0`` "unavailable"
  return.
* ``button(0, -1)`` had the same negative-index wrong-result bug.
* ``axis(True, 0)`` silently meant ``gamepad_id=1``; ``button(0, True)``
  silently meant ``btn_index=1``.

This file documents the rejection cases for those silent paths plus the
str-only key-name contract on ``key_held`` / ``key_just_pressed`` /
``key_just_released``.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from slappyengine.input._manager import InputManager  # noqa: E402


# ---------------------------------------------------------------------------
# key_held — string key contract
# ---------------------------------------------------------------------------

def test_key_held_rejects_empty_string():
    im = InputManager()
    with pytest.raises(ValueError, match="key must be non-empty"):
        im.key_held("")


def test_key_held_rejects_bytes():
    # bytes.lower() returns bytes which would silently never match
    # the str keys in _held — refuse so the typo surfaces.
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_held(b"a")


def test_key_held_rejects_none():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_held(None)


def test_key_held_rejects_int():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_held(97)  # ord('a')


def test_key_held_rejects_bool():
    # bool is a subclass of int — refuse via the str-only check too.
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_held(True)


def test_key_held_rejects_list():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_held(["a"])


# ---------------------------------------------------------------------------
# key_just_pressed / key_just_released — string key contract
# ---------------------------------------------------------------------------

def test_key_just_pressed_rejects_empty_string():
    im = InputManager()
    with pytest.raises(ValueError, match="key must be non-empty"):
        im.key_just_pressed("")


def test_key_just_pressed_rejects_bytes():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_just_pressed(b"a")


def test_key_just_pressed_rejects_none():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_just_pressed(None)


def test_key_just_released_rejects_empty_string():
    im = InputManager()
    with pytest.raises(ValueError, match="key must be non-empty"):
        im.key_just_released("")


def test_key_just_released_rejects_int():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_just_released(0)


def test_key_just_released_rejects_float():
    im = InputManager()
    with pytest.raises(TypeError, match="key must be a str"):
        im.key_just_released(1.5)


# ---------------------------------------------------------------------------
# axis — gamepad_id / axis_index
# ---------------------------------------------------------------------------

def test_axis_rejects_bool_gamepad_id():
    # True silently meant joystick id 1 before — refuse.
    im = InputManager()
    with pytest.raises(TypeError, match="gamepad_id must be an int"):
        im.axis(True, 0)


def test_axis_rejects_float_gamepad_id():
    im = InputManager()
    with pytest.raises(TypeError, match="gamepad_id must be an int"):
        im.axis(0.0, 0)


def test_axis_rejects_nan_gamepad_id():
    im = InputManager()
    with pytest.raises(TypeError, match="gamepad_id must be an int"):
        im.axis(math.nan, 0)


def test_axis_rejects_negative_gamepad_id():
    im = InputManager()
    with pytest.raises(ValueError, match="gamepad_id must be >= 0"):
        im.axis(-1, 0)


def test_axis_rejects_str_gamepad_id():
    im = InputManager()
    with pytest.raises(TypeError, match="gamepad_id must be an int"):
        im.axis("0", 0)


def test_axis_rejects_negative_axis_index():
    # Negative indexing into the GLFW axes tuple silently returned the
    # LAST axis — refuse so this surfaces.
    im = InputManager()
    with pytest.raises(ValueError, match="axis_index must be >= 0"):
        im.axis(0, -1)


def test_axis_rejects_bool_axis_index():
    im = InputManager()
    with pytest.raises(TypeError, match="axis_index must be an int"):
        im.axis(0, False)


def test_axis_rejects_oversize_axis_index_still_returns_zero():
    # Huge but valid (non-negative, non-bool) int silently returns 0.0
    # since no joystick is connected during pytest — must NOT raise.
    im = InputManager()
    assert im.axis(0, 10_000) == 0.0


# ---------------------------------------------------------------------------
# button — gamepad_id / btn_index
# ---------------------------------------------------------------------------

def test_button_rejects_bool_btn_index():
    im = InputManager()
    with pytest.raises(TypeError, match="btn_index must be an int"):
        im.button(0, True)


def test_button_rejects_float_btn_index():
    im = InputManager()
    with pytest.raises(TypeError, match="btn_index must be an int"):
        im.button(0, 0.0)


def test_button_rejects_negative_btn_index():
    im = InputManager()
    with pytest.raises(ValueError, match="btn_index must be >= 0"):
        im.button(0, -1)


def test_button_rejects_negative_gamepad_id():
    im = InputManager()
    with pytest.raises(ValueError, match="gamepad_id must be >= 0"):
        im.button(-1, 0)


def test_button_rejects_inf_gamepad_id():
    im = InputManager()
    with pytest.raises(TypeError, match="gamepad_id must be an int"):
        im.button(math.inf, 0)


def test_button_rejects_none_btn_index():
    im = InputManager()
    with pytest.raises(TypeError, match="btn_index must be an int"):
        im.button(0, None)


# ---------------------------------------------------------------------------
# Positive sanity — query round trip still works
# ---------------------------------------------------------------------------

def test_key_held_returns_false_for_unpressed_key():
    im = InputManager()
    assert im.key_held("space") is False
    assert im.key_just_pressed("a") is False
    assert im.key_just_released("escape") is False


def test_key_alias_normalisation_still_works():
    # Press "arrowleft" via the internal callback, query via "left".
    im = InputManager()
    im._on_key_event({"type": "key_down", "key": "arrowleft"})
    assert im.key_held("left") is True
    assert im.key_just_pressed("arrowleft") is True


def test_mouse_pos_property_still_returns_2tuple():
    im = InputManager()
    assert im.mouse_pos == (0.0, 0.0)


def test_axis_and_button_return_safe_zeros_when_no_gamepad():
    # With no joystick connected, both must early-return after validation.
    im = InputManager()
    assert im.axis(0, 0) == 0.0
    assert im.button(0, 0) is False
