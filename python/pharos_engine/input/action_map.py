from __future__ import annotations
from dataclasses import dataclass, field

from pharos_engine.input._validation import (
    validate_action_name,
    validate_keys_arg,
)


# ---------------------------------------------------------------------------
# Key-name normalisation helpers
# ---------------------------------------------------------------------------

_KEY_ALIASES: dict[str, str] = {
    # Modifiers
    "ctrl":        "left_control",
    "lctrl":       "left_control",
    "rctrl":       "right_control",
    "shift":       "left_shift",
    "lshift":      "left_shift",
    "rshift":      "right_shift",
    "alt":         "left_alt",
    "lalt":        "left_alt",
    "ralt":        "right_alt",
    # Enter / escape
    "enter":       "return",
    "ret":         "return",
    "esc":         "escape",
    # Delete
    "del":         "delete",
    # Arrow keys — rendercanvas/GLFW report these as "arrowleft" etc.;
    # action maps accept the short forms too.
    "up":          "arrowup",
    "down":        "arrowdown",
    "left":        "arrowleft",
    "right":       "arrowright",
    # Symmetrical: if a caller already passes the full form it round-trips.
    "arrowup":     "arrowup",
    "arrowdown":   "arrowdown",
    "arrowleft":   "arrowleft",
    "arrowright":  "arrowright",
}


def normalize_key(key: str) -> str:
    """Lowercase a key name and apply canonical aliases."""
    k = key.lower()
    return _KEY_ALIASES.get(k, k)


# ---------------------------------------------------------------------------
# ActionMap
# ---------------------------------------------------------------------------

@dataclass
class ActionMap:
    """
    Maps string action names to key names for one player.

    Key names follow wgpu/rendercanvas/GLFW conventions after normalisation:
    letters ("a"-"z"), digits ("0"-"9"), "space", "escape", "return",
    "backspace", "tab", "arrowleft", "arrowright", "arrowup", "arrowdown",
    "left_shift", "right_shift", "left_control", "right_control",
    "left_alt", "right_alt", "delete", "gamepad0_a", etc.

    Short-form aliases (e.g. "up", "shift", "enter") are normalised
    automatically by :func:`normalize_key`.

    Usage::

        am = ActionMap(player_id=0)
        am.bind("move_up",    "w")
        am.bind("move_down",  "s")
        am.bind("move_left",  "a")
        am.bind("move_right", "d")
        am.bind("fire",       "space")

        # Or load from a dict:
        am = ActionMap.from_dict(0, {
            "move_up": "w", "move_down": "s",
            "move_left": "a", "move_right": "d",
            "fire": "space",
        })
    """

    player_id: int
    _bindings: dict[str, str] = field(default_factory=dict)       # action → canonical key
    _reverse:  dict[str, list[str]] = field(default_factory=dict) # canonical key → [actions]
    _state:    dict[str, bool] = field(default_factory=dict)       # action → held
    _axes:     dict[str, tuple[str, str]] = field(default_factory=dict)  # axis → (neg, pos)

    # ------------------------------------------------------------------
    # Binding management
    # ------------------------------------------------------------------

    def bind(self, action: str, key: str) -> None:
        """Bind *action* to *key* (replaces any previous binding for that action).

        Raises
        ------
        TypeError
            If ``action`` is not a ``str``, or ``key`` is not a ``str`` /
            non-empty iterable of ``str``.
        ValueError
            If ``action`` is the empty string, or ``key`` is empty (empty
            string / empty iterable / contains empty entries).
        """
        validate_action_name("action", "ActionMap.bind", action)
        validated_key = validate_keys_arg("key", "ActionMap.bind", key)
        # Historical single-key contract: take the first key if a list is given.
        first_key = validated_key if isinstance(validated_key, str) else validated_key[0]
        canonical = normalize_key(first_key)
        # Remove old binding if present
        if action in self._bindings:
            old_key = self._bindings[action]
            lst = self._reverse.get(old_key, [])
            if action in lst:
                lst.remove(action)
        self._bindings[action] = canonical
        self._reverse.setdefault(canonical, []).append(action)
        self._state.setdefault(action, False)

    def unbind(self, action: str) -> None:
        """Remove the binding for *action*.

        Raises
        ------
        TypeError
            If ``action`` is not a ``str``.
        ValueError
            If ``action`` is the empty string.
        """
        validate_action_name("action", "ActionMap.unbind", action)
        if action in self._bindings:
            key = self._bindings.pop(action)
            lst = self._reverse.get(key, [])
            if action in lst:
                lst.remove(action)
            self._state.pop(action, None)

    def bind_axis(self, axis_name: str, neg_action: str, pos_action: str) -> None:
        """Define a float axis from two boolean actions.

        :meth:`axis` returns -1, 0, or +1 depending on which actions are held.
        """
        self._axes[axis_name] = (neg_action, pos_action)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def axis(self, axis_name: str) -> float:
        """Return -1.0, 0.0, or +1.0 for a named axis."""
        if axis_name not in self._axes:
            return 0.0
        neg, pos = self._axes[axis_name]
        return float(self._state.get(pos, False)) - float(self._state.get(neg, False))

    def is_held(self, action: str) -> bool:
        """Return ``True`` while the action's key is held."""
        return self._state.get(action, False)

    def actions_for_key(self, key: str) -> list[str]:
        """Return all action names bound to *key*."""
        return list(self._reverse.get(normalize_key(key), []))

    # ------------------------------------------------------------------
    # Engine-internal press/release (called by Engine._on_key_down/up)
    # ------------------------------------------------------------------

    def _press(self, key: str) -> list[str]:
        """Mark actions for *key* as pressed. Returns newly-triggered actions."""
        triggered: list[str] = []
        for action in self._reverse.get(normalize_key(key), []):
            if not self._state.get(action, False):
                self._state[action] = True
                triggered.append(action)
        return triggered

    def _release(self, key: str) -> list[str]:
        """Mark actions for *key* as released. Returns actions that were held."""
        released: list[str] = []
        for action in self._reverse.get(normalize_key(key), []):
            if self._state.get(action, False):
                self._state[action] = False
                released.append(action)
        return released

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, player_id: int, bindings: dict[str, str]) -> "ActionMap":
        """Create an ActionMap from a ``{action: key}`` dict."""
        am = cls(player_id=player_id)
        for action, key in bindings.items():
            am.bind(action, key)
        return am

    @classmethod
    def wasd(cls, player_id: int = 0) -> "ActionMap":
        """Standard WASD layout for player 0."""
        return cls.from_dict(player_id, {
            "move_up":    "w",
            "move_down":  "s",
            "move_left":  "a",
            "move_right": "d",
            "fire":       "space",
            "interact":   "e",
            "dodge":      "left_shift",
        })

    @classmethod
    def arrows(cls, player_id: int = 1) -> "ActionMap":
        """Arrow-key layout for player 1."""
        return cls.from_dict(player_id, {
            "move_up":    "arrowup",
            "move_down":  "arrowdown",
            "move_left":  "arrowleft",
            "move_right": "arrowright",
            "fire":       "right_control",
            "interact":   "return",
            "dodge":      "right_shift",
        })

    @classmethod
    def ijkl(cls, player_id: int = 2) -> "ActionMap":
        """IJKL layout for player 2."""
        return cls.from_dict(player_id, {
            "move_up":    "i",
            "move_down":  "k",
            "move_left":  "j",
            "move_right": "l",
            "fire":       "u",
            "interact":   "o",
            "dodge":      "h",
        })
