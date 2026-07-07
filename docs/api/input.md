<!-- handauthored: do not regenerate -->
# slappyengine.input — API Reference

> Hand-written reference for `slappyengine.input` — keyboard, mouse,
> and gamepad input for the runtime. Two classes: a low-level
> per-frame `InputManager` and a higher-level per-player `ActionMap`.
> Sibling references: [`ui_editor.md`](ui_editor.md) is the notebook
> editor shell whose hotkey layer sits on top of the primitives below;
> [`actions.md`](actions.md) is the headless `ctx: dict -> dict` action
> callback surface routed from bound keys via the `ToolRouter`.

## Overview

`slappyengine.input` covers the two input questions the engine core
needs to answer on every frame:

1. **"Is a specific physical key / button held right now?"** —
   :class:`InputManager` owns the per-frame state and is the object the
   engine wires onto the canvas via the rendercanvas / GLFW event
   handlers. It stores three sets — held, just-pressed, just-released —
   that must be reset at the end of each frame via
   :meth:`InputManager.frame_reset`.
2. **"Which gameplay action, per player, does that key map to?"** —
   :class:`ActionMap` layers a per-player abstraction on top:
   `am.bind("fire", "space")` binds an action name to a canonical key,
   and the engine's internal `_press` / `_release` fan the raw key
   event out to every action bound to it. Axis pairs
   (`bind_axis("horizontal", "move_left", "move_right")`) collapse two
   boolean actions into a signed float for movement.

Both classes route their public arguments through
`slappyengine.input._validation` and `_manager_validation`, so bad
input (empty key name, negative gamepad id, non-string action) fails
loudly with a canonical `TypeError` / `ValueError` at the call site
rather than silently no-op-ing inside the state machine.

Key names use the rendercanvas / GLFW lowercase convention (`"a"` …
`"z"`, `"0"` … `"9"`, `"space"`, `"return"`, `"escape"`, `"arrowleft"`,
`"left_shift"`, `"left_control"`, …). Both classes normalise short-form
aliases (`"up"` → `"arrowup"`, `"shift"` → `"left_shift"`, `"enter"`
→ `"return"`, `"lmb"` → `"mouse_left"`) so authoring code can use the
short forms without knowing about the underlying event layer.

Gamepad support is provided by soft-importing `glfw`; when the module
is unavailable :meth:`InputManager.axis` returns `0.0` and
:meth:`InputManager.button` returns `False` — headless CI stays valid
with no guard.

## Public surface

```python
from slappyengine.input import ActionMap, InputManager
```

* :class:`InputManager` — per-frame held / just-pressed / just-released
  key + mouse-button state; mouse position; gamepad axis + button
  passthrough.
* :class:`ActionMap` — per-player `action name → key` binding table,
  axis pairs, `wasd()` / `arrows()` / `ijkl()` preset constructors,
  and `from_dict()` bulk-bind factory.

## Classes

### `InputManager`

_class — defined in `slappyengine.input._manager`_

Low-level per-frame input state. The engine registers `InputManager`
against the canvas in `Engine._setup_gpu()` via `add_event_handler`,
and the caller (or the engine's draw loop) must invoke
:meth:`frame_reset` at the end of each frame.

#### Constructor

```python
InputManager()
```

No arguments — every field is initialised to the empty state.

#### Public methods

| Method | Returns | Notes |
|--------|---------|-------|
| `key_held(key: str) -> bool` | `bool` | `True` while `key` is down; validates `key` is a non-empty `str`. |
| `key_just_pressed(key: str) -> bool` | `bool` | `True` only on the frame the key transitioned to `held`. |
| `key_just_released(key: str) -> bool` | `bool` | `True` only on the frame the key transitioned to released. |
| `axis(gamepad_id: int, axis_index: int) -> float` | `float` in `[-1.0, 1.0]` | Gamepad axis passthrough; `0.0` when `glfw` is unavailable. |
| `button(gamepad_id: int, btn_index: int) -> bool` | `bool` | Gamepad button passthrough; `False` when `glfw` is unavailable. |
| `frame_reset() -> None` | `None` | End-of-frame reset for the `just_pressed` / `just_released` sets. Must be called every frame. |
| `mouse_pos -> tuple[float, float]` | `(x, y)` | Property. Current pointer position in canvas pixels. |

**Validation contract.** `key` must be a non-empty `str` (validated via
`validate_key_name` — `bytes` is refused because `bytes.lower()`
returns `bytes` and would silently never match the state sets).
`gamepad_id` / `axis_index` / `btn_index` must be plain non-negative
`int` values (bare `bool` is refused). Violations raise `TypeError` or
`ValueError`.

### `ActionMap`

_dataclass — defined in `slappyengine.input.action_map`_

Per-player mapping from action names (`"fire"`, `"move_up"`, …) to
canonical key names. The engine calls the internal `_press(key)` /
`_release(key)` when a key event arrives; game code queries
`is_held(action)` or `axis(axis_name)` on the next frame.

#### Constructor

```python
ActionMap(player_id: int)
```

`player_id` distinguishes local-multiplayer maps (player 0 typically
`wasd`, player 1 typically `arrows`).

#### Public methods

| Method | Purpose |
|--------|---------|
| `bind(action, key)` | Bind `action` to `key` (single key; replaces any prior binding). |
| `unbind(action)` | Remove the binding for `action`. |
| `bind_axis(axis_name, neg_action, pos_action)` | Define a float axis from two boolean actions. |
| `axis(axis_name) -> float` | Return -1.0 / 0.0 / +1.0 for a named axis. |
| `is_held(action) -> bool` | Return `True` while `action`'s key is held. |
| `actions_for_key(key) -> list[str]` | Return every action bound to `key` (multiple actions per key are supported). |

**Validation contract.** `action` must be a non-empty `str` (validated
via `validate_action_name`). `key` must be a non-empty `str` or a
non-empty iterable of non-empty `str` (via `validate_keys_arg`);
when a list is passed, the historical single-key contract keeps the
first entry as the canonical bind.

#### Constructors

- `ActionMap.from_dict(player_id, bindings)` — bulk-bind from a
  `{action: key}` dict.
- `ActionMap.wasd(player_id=0)` — standard WASD layout
  (`move_up=w / move_down=s / move_left=a / move_right=d /
  fire=space / interact=e / dodge=left_shift`).
- `ActionMap.arrows(player_id=1)` — arrow-key layout for player 1.
- `ActionMap.ijkl(player_id=2)` — IJKL layout for player 2.

#### Module-level helper

- `normalize_key(key: str) -> str` — lowercase the key and apply the
  canonical alias table (`"up"` → `"arrowup"`, `"shift"` →
  `"left_shift"`, `"enter"` → `"return"`, `"esc"` → `"escape"`,
  `"del"` → `"delete"`, `"ctrl"` → `"left_control"`, `"alt"` →
  `"left_alt"`, plus the identity round-trips for the full forms).

## Usage

```python
from slappyengine.input import ActionMap, InputManager

# --- Low-level: per-frame key state ---------------------------------
im = InputManager()

# Simulate the engine's canvas-event dispatch for a headless test.
im._on_key_event({"type": "key_down", "key": "space"})
assert im.key_held("space") is True
assert im.key_just_pressed("space") is True
assert im.key_just_pressed("SPACE") is True  # case-insensitive
im.frame_reset()
assert im.key_just_pressed("space") is False  # cleared for next frame
assert im.key_held("space") is True            # still held

# --- Higher-level: per-player action map ----------------------------
p1 = ActionMap.wasd(player_id=0)
p1.bind_axis("horizontal", "move_left", "move_right")
p1.bind_axis("vertical",   "move_down", "move_up")

# Engine-internal fan-out: raw key press → all bound actions.
triggered = p1._press("d")
assert triggered == ["move_right"]
assert p1.is_held("move_right") is True
assert p1.axis("horizontal") == 1.0

# Custom binding table with the from_dict factory.
p2 = ActionMap.from_dict(1, {
    "jump": "space",
    "crouch": "left_control",
    "throw": "q",
})
assert p2.actions_for_key("space") == ["jump"]
```

## Skip the wrapper

`slappyengine.input` is Python-only. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `input` entry —
the per-frame hot path is a couple of `set` operations plus a dict
lookup per key event, already O(1). Rewriting in Rust would move no
measurable frame-time needle even on gamepad-heavy scenes.

Callers who need to skip the wrapper (custom SDL / pygame event pump,
or a headless test harness driving the engine deterministically) can
call the internal `_on_key_event({"type": ..., "key": ...})` and
`_on_pointer_event({...})` methods on :class:`InputManager` directly —
these are the same entry points the canvas event handler uses. The
:meth:`ActionMap._press` / :meth:`ActionMap._release` methods are
similarly public-in-behaviour, private-in-name: engine-internal
fan-out from raw key to bound actions, safe to call from a custom
input loop.

`glfw` is optional — the gamepad passthrough soft-imports it and
returns neutral values when it is missing. There is no compile-time
dependency on any input backend.

## Conventions

- **Lowercase canonical keys.** All state sets store lowercase key
  names post-alias. Callers may pass any case; `normalize_key` and
  `InputManager._normalize` collapse to the canonical form.
- **Frame reset is the caller's responsibility.** :class:`InputManager`
  never clears `just_pressed` / `just_released` on its own — the engine
  draw loop (or the caller's test harness) must invoke
  :meth:`frame_reset` at the end of each frame or those sets will
  accumulate forever.
- **Single-key bind, multi-key alias.** :meth:`ActionMap.bind` accepts
  a list of key names but binds only the first — kept for a legacy
  authoring format that stored key alternatives as a list. Use
  :meth:`ActionMap.bind` multiple times or maintain a per-player
  overlay if you need true multi-key actions.
- **Gamepad axis IDs pass through untouched.** Both `gamepad_id` and
  `axis_index` / `btn_index` are forwarded straight into `glfw` after
  validation; the caller owns the GLFW joystick-slot semantics.

## See also

- [`actions.md`](actions.md) — the headless `ctx: dict -> dict` action
  callback surface. Hotkey → action-id resolution goes through the
  `ToolRouter`; the primitives here are what the router queries when
  the hotkey layer is enabled.
- [`ui_editor.md`](ui_editor.md) — the notebook editor shell whose
  hotkey remap layer stacks on top of :class:`ActionMap`.
- [`../notebook_editor_manual_2026_06_03.md`](../notebook_editor_manual_2026_06_03.md)
  — user-facing manual with the full editor hotkey table.
