from __future__ import annotations

from pharos_engine.input._manager_validation import (
    validate_key_name,
    validate_nonneg_int,
)


class InputManager:
    """
    Keyboard, mouse, and gamepad input manager.

    Registered on the canvas in Engine._setup_gpu() via add_event_handler.
    State is reset each frame via frame_reset() called at end of draw loop.

    Key names use lowercase strings matching rendercanvas/GLFW conventions:
      letters: "a"-"z"
      digits:  "0"-"9"
      special: "space", "enter", "escape", "backspace", "tab"
      arrows:  "arrowleft", "arrowright", "arrowup", "arrowdown"
      mods:    "shift", "ctrl", "alt"
      aliases: "left"="arrowleft", "right"="arrowright", "up"="arrowup", "down"="arrowdown",
               "rctrl"="ctrl", "rshift"="shift", "lmb"="mouse_left", "rmb"="mouse_right"

    Gamepad: wraps GLFW joystick API.
    """

    # Key alias map
    _ALIASES = {
        "left": "arrowleft", "right": "arrowright",
        "up": "arrowup", "down": "arrowdown",
        "rctrl": "ctrl", "rshift": "shift",
        "lmb": "mouse_left", "rmb": "mouse_right",
        "mouse_left": "mouse_left", "mouse_right": "mouse_right",
    }

    def __init__(self):
        self._held: set[str] = set()
        self._just_pressed: set[str] = set()
        self._just_released: set[str] = set()
        self._mouse_pos: tuple[float, float] = (0.0, 0.0)
        self._mouse_buttons: set[str] = set()
        self._mouse_just_pressed: set[str] = set()
        self._mouse_just_released: set[str] = set()

    def _normalize(self, key: str) -> str:
        k = key.lower()
        return self._ALIASES.get(k, k)

    def _on_key_event(self, event: dict):
        key = self._normalize(event.get("key", ""))
        if not key:
            return
        etype = event.get("type", "")
        if etype == "key_down":
            if key not in self._held:
                self._just_pressed.add(key)
            self._held.add(key)
        elif etype == "key_up":
            self._held.discard(key)
            self._just_released.add(key)

    def _on_pointer_event(self, event: dict):
        self._mouse_pos = (float(event.get("x", 0)), float(event.get("y", 0)))
        etype = event.get("type", "")
        btn_map = {1: "mouse_left", 2: "mouse_right", 3: "mouse_middle"}
        btn_id = event.get("button", 0)
        btn = btn_map.get(btn_id, f"mouse_{btn_id}")
        if etype == "pointer_down":
            if btn not in self._mouse_buttons:
                self._mouse_just_pressed.add(btn)
            self._mouse_buttons.add(btn)
        elif etype == "pointer_up":
            self._mouse_buttons.discard(btn)
            self._mouse_just_released.add(btn)

    def frame_reset(self):
        """Call at end of each frame to clear just_pressed/just_released."""
        self._just_pressed.clear()
        self._just_released.clear()
        self._mouse_just_pressed.clear()
        self._mouse_just_released.clear()

    def key_held(self, key: str) -> bool:
        """Return True while the key is held down.

        Raises
        ------
        TypeError
            If ``key`` is not a ``str``.
        ValueError
            If ``key`` is the empty string.
        """
        validate_key_name("key", "InputManager.key_held", key)
        k = self._normalize(key)
        return k in self._held or k in self._mouse_buttons

    def key_just_pressed(self, key: str) -> bool:
        """Return True only on the frame the key was first pressed.

        Raises
        ------
        TypeError
            If ``key`` is not a ``str``.
        ValueError
            If ``key`` is the empty string.
        """
        validate_key_name("key", "InputManager.key_just_pressed", key)
        k = self._normalize(key)
        return k in self._just_pressed or k in self._mouse_just_pressed

    def key_just_released(self, key: str) -> bool:
        """Return True only on the frame the key was released.

        Raises
        ------
        TypeError
            If ``key`` is not a ``str``.
        ValueError
            If ``key`` is the empty string.
        """
        validate_key_name("key", "InputManager.key_just_released", key)
        k = self._normalize(key)
        return k in self._just_released or k in self._mouse_just_released

    @property
    def mouse_pos(self) -> tuple[float, float]:
        """Current pointer position in canvas pixels as ``(x, y)``."""
        return self._mouse_pos

    def axis(self, gamepad_id: int, axis_index: int) -> float:
        """Gamepad axis value in the range -1.0 to 1.0. Returns 0.0 if unavailable.

        Raises
        ------
        TypeError
            If ``gamepad_id`` or ``axis_index`` is not a plain ``int``
            (``bool`` refused).
        ValueError
            If either argument is negative.
        """
        validate_nonneg_int("gamepad_id", "InputManager.axis", gamepad_id)
        validate_nonneg_int("axis_index", "InputManager.axis", axis_index)
        try:
            import glfw
            axes = glfw.get_joystick_axes(gamepad_id)
            if axes and axis_index < len(axes):
                return float(axes[axis_index])
        except Exception:
            pass
        return 0.0

    def button(self, gamepad_id: int, btn_index: int) -> bool:
        """Gamepad button state. Returns False if unavailable.

        Raises
        ------
        TypeError
            If ``gamepad_id`` or ``btn_index`` is not a plain ``int``
            (``bool`` refused).
        ValueError
            If either argument is negative.
        """
        validate_nonneg_int("gamepad_id", "InputManager.button", gamepad_id)
        validate_nonneg_int("btn_index", "InputManager.button", btn_index)
        try:
            import glfw
            buttons = glfw.get_joystick_buttons(gamepad_id)
            if buttons and btn_index < len(buttons):
                return bool(buttons[btn_index])
        except Exception:
            pass
        return False
