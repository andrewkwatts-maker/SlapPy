"""
playslap.input
==================

Keyboard / mouse / gamepad input utilities.

Public symbols
--------------
InputManager  — low-level per-frame key state (held, just_pressed, just_released).
ActionMap     — per-player action → key binding table with axis helpers.
"""
from __future__ import annotations

from playslap.input._manager import InputManager
from playslap.input.action_map import ActionMap

__all__ = ["InputManager", "ActionMap"]
