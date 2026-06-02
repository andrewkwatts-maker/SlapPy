"""
InputProvider — abstract input source for controllable entities.

An entity that accepts movement commands only cares about axis values and
button states, not where those values come from.  Swap PlayerInputProvider
for ScriptInputProvider (driven by AI, replay, or network) at any time
without changing physics code.

Standard axis names
-------------------
"throttle"   0..1    forward acceleration
"brake"      0..1    deceleration / reverse
"steer"     -1..1    left (−1) → right (+1)

Standard action names
---------------------
"fire"       bool
"nitro"      bool
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class InputProvider(Protocol):
    """Structural protocol — any object with these two methods qualifies."""

    def get_axes(self) -> dict[str, float]: ...
    def get_actions(self) -> dict[str, bool]: ...


class PlayerInputProvider:
    """Reads live keyboard state (and optionally a gamepad) for one player slot.

    Parameters
    ----------
    player_id:
        0 → WASD / F / N
        1 → Arrow keys / RShift / RCtrl
    engine_input:
        The engine's InputManager.  Can be set after construction via the
        ``input_manager`` attribute (useful when the engine starts after the
        provider is created).
    """

    _BINDINGS: list[dict[str, str]] = [
        {"accel": "w",   "brake": "s",    "left": "a",     "right": "d",
         "fire":  "f",   "nitro": "n"},
        {"accel": "up",  "brake": "down", "left": "left",  "right": "right",
         "fire":  "rshift", "nitro": "rctrl"},
    ]

    # Gamepad axis / button indices (SDL / pygame convention)
    _GP_AXIS_STEER       = 0   # left stick X
    _GP_AXIS_THROTTLE    = 5   # right trigger (0..1 range after normalise)
    _GP_AXIS_BRAKE       = 2   # left trigger  (0..1 range after normalise)
    _GP_BTN_FIRE         = 0   # A / Cross
    _GP_BTN_NITRO        = 2   # X / Square
    _GP_DEADZONE         = 0.1

    def __init__(self, player_id: int = 0, engine_input=None):
        self.player_id    = player_id
        self.input_manager = engine_input
        self._gamepad_idx: int | None = None   # None = keyboard only
        self._gamepad = None                   # pygame joystick object (lazy)

    # ------------------------------------------------------------------
    # Gamepad configuration
    # ------------------------------------------------------------------

    def use_gamepad(self, gamepad_index: int = 0) -> bool:
        """Attempt to attach a gamepad.

        Returns True if a gamepad was found and connected, False otherwise.
        The provider falls back to keyboard when no gamepad is attached.
        """
        try:
            import pygame
            if not pygame.get_init():
                pygame.init()
            pygame.joystick.init()
            count = pygame.joystick.get_count()
            if count <= gamepad_index:
                return False
            self._gamepad = pygame.joystick.Joystick(gamepad_index)
            self._gamepad.init()
            self._gamepad_idx = gamepad_index
            return True
        except Exception:
            return False

    def has_gamepad(self) -> bool:
        """Return True if a gamepad is currently attached."""
        return self._gamepad is not None

    def rumble(self, duration: float = 0.15, strength: float = 0.8) -> None:
        """Trigger gamepad rumble (no-op when no gamepad or rumble unsupported)."""
        if self._gamepad is None:
            return
        try:
            # pygame 2.0+: Joystick.rumble(low, high, duration_ms)
            low  = strength * 0.6
            high = strength
            self._gamepad.rumble(low, high, int(duration * 1000))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rumble event wiring
    # ------------------------------------------------------------------

    def subscribe_rumble_events(self, tracked_vehicle=None) -> None:
        """Wire game-bus events to gamepad rumble feedback.

        Call once after the player vehicle is known.  All subscriptions are
        stored in ``_rumble_handles`` and cleaned up by
        ``unsubscribe_rumble_events()``.

        Parameters
        ----------
        tracked_vehicle:
            Filter per-vehicle events to this object.  Pass ``None`` to react
            to any vehicle (useful in single-player with one bus).
        """
        try:
            from slappyengine.event_bus import subscribe as _subscribe
        except ImportError:
            return

        self._rumble_tracked = tracked_vehicle
        self._rumble_handles: list[int] = getattr(self, "_rumble_handles", [])

        def _on_collision(evt) -> None:
            if tracked_vehicle is not None and evt.publisher is not tracked_vehicle:
                return
            force = float(getattr(evt, "force", 50.0))
            strength = min(1.0, force / 200.0)
            self.rumble(duration=0.15, strength=strength)

        def _on_boundary(evt) -> None:
            if tracked_vehicle is not None and evt.publisher is not tracked_vehicle:
                return
            self.rumble(duration=0.08, strength=0.4)

        def _on_boost(evt) -> None:
            if tracked_vehicle is not None and evt.publisher is not tracked_vehicle:
                return
            self.rumble(duration=0.12, strength=0.6)

        def _on_finished(evt) -> None:
            # Victory triple-pulse (staggered — first pulse immediate)
            self.rumble(duration=0.1, strength=0.9)

        self._rumble_handles = [
            _subscribe("Vehicle.Collision",    _on_collision),
            _subscribe("Vehicle.BoundaryHit",  _on_boundary),
            _subscribe("Vehicle.Boost",        _on_boost),
            _subscribe("Race.Finished",        _on_finished),
        ]

    def unsubscribe_rumble_events(self) -> None:
        """Remove all rumble event subscriptions."""
        try:
            from slappyengine.event_bus import unsubscribe as _unsub
        except ImportError:
            return
        for h in getattr(self, "_rumble_handles", []):
            try:
                _unsub(h)
            except Exception:
                pass
        self._rumble_handles = []

    # ------------------------------------------------------------------
    # Axis reading
    # ------------------------------------------------------------------

    def get_axes(self) -> dict[str, float]:
        if self._gamepad is not None:
            return self._get_gamepad_axes()
        return self._get_keyboard_axes()

    def _get_keyboard_axes(self) -> dict[str, float]:
        inp = self.input_manager
        if inp is None:
            return {"throttle": 0.0, "brake": 0.0, "steer": 0.0}
        b = self._BINDINGS[self.player_id % len(self._BINDINGS)]
        throttle = 1.0 if inp.key_held(b["accel"]) else 0.0
        brake    = 1.0 if inp.key_held(b["brake"])  else 0.0
        steer    = (1.0 if inp.key_held(b["right"]) else 0.0) \
                 - (1.0 if inp.key_held(b["left"])  else 0.0)
        return {"throttle": throttle, "brake": brake, "steer": steer}

    def _get_gamepad_axes(self) -> dict[str, float]:
        try:
            import pygame
            pygame.event.pump()
            gp = self._gamepad

            raw_steer = gp.get_axis(self._GP_AXIS_STEER)
            # Apply deadzone and square for finer control near centre
            if abs(raw_steer) < self._GP_DEADZONE:
                raw_steer = 0.0
            steer = raw_steer * abs(raw_steer)   # squaring preserves sign

            # Triggers: SDL range is -1..+1 at rest (−1 = not pressed, +1 = full)
            raw_throttle = gp.get_axis(self._GP_AXIS_THROTTLE)
            raw_brake    = gp.get_axis(self._GP_AXIS_BRAKE)
            throttle = max(0.0, (raw_throttle + 1.0) * 0.5)
            brake    = max(0.0, (raw_brake    + 1.0) * 0.5)

            return {"throttle": throttle, "brake": brake, "steer": steer}
        except Exception:
            return self._get_keyboard_axes()

    # ------------------------------------------------------------------
    # Action reading
    # ------------------------------------------------------------------

    def get_actions(self) -> dict[str, bool]:
        if self._gamepad is not None:
            return self._get_gamepad_actions()
        return self._get_keyboard_actions()

    def _get_keyboard_actions(self) -> dict[str, bool]:
        inp = self.input_manager
        if inp is None:
            return {"fire": False, "nitro": False}
        b = self._BINDINGS[self.player_id % len(self._BINDINGS)]
        return {
            "fire":  inp.key_held(b["fire"]),
            "nitro": inp.key_held(b["nitro"]),
        }

    def _get_gamepad_actions(self) -> dict[str, bool]:
        try:
            import pygame
            gp = self._gamepad
            return {
                "fire":  bool(gp.get_button(self._GP_BTN_FIRE)),
                "nitro": bool(gp.get_button(self._GP_BTN_NITRO)),
            }
        except Exception:
            return self._get_keyboard_actions()


class ScriptInputProvider:
    """Input provider whose values are written by an AI script or replay.

    An AI script calls ``set_axis`` / ``set_action`` each frame *before* the
    vehicle physics script reads from this provider.

    Example::

        provider = ScriptInputProvider()
        vehicle.input_provider = provider

        class MyAI:
            def on_tick(self, entity, dt):
                provider.set_axis("throttle", 1.0)
                provider.set_axis("steer", -0.4)
    """

    def __init__(self):
        self._axes:    dict[str, float] = {"throttle": 0.0, "brake": 0.0, "steer": 0.0}
        self._actions: dict[str, bool]  = {"fire": False, "nitro": False}

    def set_axis(self, name: str, value: float) -> None:
        self._axes[name] = float(value)

    def set_action(self, name: str, pressed: bool) -> None:
        self._actions[name] = bool(pressed)

    def reset(self) -> None:
        """Zero all axes and release all actions."""
        self._axes    = {"throttle": 0.0, "brake": 0.0, "steer": 0.0}
        self._actions = {"fire": False, "nitro": False}

    def get_axes(self) -> dict[str, float]:
        return dict(self._axes)

    def get_actions(self) -> dict[str, bool]:
        return dict(self._actions)
