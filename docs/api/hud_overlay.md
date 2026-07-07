<!-- handauthored: do not regenerate -->
# slappyengine.ui.runtime.hud_overlay — API Reference

> Hand-written reference for the LL1 HUD overlay + registry surface plus
> the MM2 :mod:`slappyengine.hud_bridge` glue that mounts it onto the
> :class:`~slappyengine.App` lifecycle. Sibling references:
> [`ui_widgets.md`](ui_widgets.md) documents the notebook-themed DPG
> primitives that back editor UIs (a separate axis from the game HUD);
> [`render_instanced.md`](render_instanced.md) covers the
> :class:`Renderer` surface the overlay ultimately submits sprites to;
> [`diagnostics.md`](diagnostics.md) is the source of the
> :class:`DiagnosticEvent` records surfaced by
> :func:`add_diagnostics_widget`.

## Overview

`slappyengine.ui.runtime.hud_overlay` is the LL1 landing. It gives games
a screen-space overlay that sits on top of the rendered 3D scene,
managed as a per-frame `begin → build widgets → end → submit` pipeline:

* :class:`HUDOverlay` — the frame-scoped manager. Owns a private
  :class:`ImmediateUI` context so the game's own UI (if any) is not
  disturbed. Renderer-agnostic: any object with
  ``submit_sprite(texture, transform_2d, tint)`` and
  ``submit_lines(vertices, colors)`` works.
* :class:`HUDRegistry` (in `hud_registry.py`) — factory registry with
  nine first-party widgets pre-registered: `health_bar`, `stamina_bar`,
  `ammo_counter`, `compass`, `minimap`, `toast`, `crosshair`,
  `score_counter`, `objective_marker`.
* :func:`hud_command_to_sprite` / :func:`hud_command_to_text` —
  stateless helpers that convert a :class:`DrawCommand` into a
  renderer submission payload.

The MM2 :mod:`slappyengine.hud_bridge` glue module wires an overlay
into :class:`~slappyengine.App`'s ``after_tick`` +
``before_frame_render`` hook chains so a caller opts in with a single
:func:`mount_hud(app)` call and never writes lifecycle plumbing.

## Public surface

```python
# LL1 — core overlay surface
from slappyengine.ui.runtime.hud_overlay import (
    HUDOverlay, SpriteSubmission,
    hud_command_to_sprite, hud_command_to_text,
)
from slappyengine.ui.runtime.hud_registry import HUDRegistry, WidgetFactory

# MM2 — App-lifecycle glue + diagnostics widget
from slappyengine.hud_bridge import (
    mount_hud, unmount_hud,
    default_game_hud_widgets,
    add_diagnostics_widget,
)
```

## Classes

### `HUDOverlay`

_class — defined in `slappyengine.ui.runtime.hud_overlay`_

Screen-space HUD manager that renders on top of the 3D viewport.

```python
HUDOverlay(
    renderer: Any,
    camera_2d: Any,
    *,
    text_atlas: Any = None,
    theme: RuntimeTheme | None = None,
    default_font_size: int = 14,
)
```

Raises `ValueError` when *renderer* or *camera_2d* is `None`.

Widget management:

- `attach(widget) -> None` — register a widget (must have `.build(ui)`).
- `detach(widget) -> None`
- `clear() -> None` — detach all widgets.
- `widgets() -> tuple[_HUDWidget, ...]` — defensive copy.
- `set_visible(visible: bool) -> None` — toggle the whole HUD.

Frame lifecycle:

- `begin_frame(dt, input_state=None) -> None` — open the frame. Raises
  `RuntimeError` when called twice without an intervening
  :meth:`end_frame`. Widget `.build()` exceptions are swallowed so a
  misbehaving widget cannot tank the whole HUD.
- `end_frame() -> list[DrawCommand]` — close the frame. Drops the
  `ImmediateUI` full-frame clear (z=0, size=(0,0)) so the overlay
  never blanks the 3D viewport.
- `submit_to_renderer() -> int` — walk the last-frame draw list; return
  the number of commands forwarded. Handles `rect`, `textured_quad`,
  `line` (batched), `text` (via SDF atlas), and `circle` (fallback to
  filled rect).

Attributes: `visible: bool`, `command_count -> int` (last frame),
`widget_count -> int`.

### `SpriteSubmission`

_dataclass — defined in `slappyengine.ui.runtime.hud_overlay`_

Payload for a `Renderer.submit_sprite` call.

| Field | Type | Notes |
|-------|------|-------|
| `texture_id` | `int \| None` | `None` for solid-colour rects. |
| `transform_2d` | `np.ndarray` | Row-major 3x3 affine (position + scale). |
| `tint` | `tuple[float, float, float, float]` | RGBA in `[0, 1]`. |

### `HUDRegistry`

_class — defined in `slappyengine.ui.runtime.hud_registry`_

Named-factory registry for HUD widgets. Ships with the nine first-party
widgets pre-registered.

- `register(name, factory) -> None` — raises `ValueError` on empty
  name, `TypeError` on non-callable factory.
- `unregister(name) -> bool`
- `create(name, config=None) -> Any` — raises `KeyError` for unknown
  names. Missing / typo'd config keys are silently ignored so shared
  config schemas can address multiple widget types.
- `list_available() -> list[str]` — sorted.
- Supports `name in registry` and `len(registry)`.

## Functions

### `hud_command_to_sprite(cmd) -> SpriteSubmission`

_defined in `slappyengine.ui.runtime.hud_overlay`_

Convert a `rect` or `textured_quad` :class:`DrawCommand` into a
:class:`SpriteSubmission`. `size == (0, 0)` is treated as fullscreen
(expands to a 1x1 quad at origin). Raises `ValueError` on any other
`cmd.kind`.

### `hud_command_to_text(cmd, atlas) -> TextMesh | None`

_defined in `slappyengine.ui.runtime.hud_overlay`_

Convert a `text` :class:`DrawCommand` into an SDF `TextMesh` via the
KK6 `slappyengine.text` renderer. Returns `None` when *atlas* is
`None` (headless-safe). Raises `ValueError` for the wrong kind.

### `mount_hud(app, *, widgets=None) -> HUDOverlay`

_defined in `slappyengine.hud_bridge`_

Instantiate an :class:`HUDOverlay` bound to *app*, attach *widgets*
(defaults to :func:`default_game_hud_widgets`), and hook the overlay
into two lifecycle chains:

- ``after_tick(app, dt)`` → `overlay.begin_frame(dt) +
  overlay.end_frame()` — folds both phases into one hook so the widget
  draw list is fully baked before the render pass runs.
- ``before_frame_render(app)`` → `overlay.submit_to_renderer()` —
  pushes the baked draw list through the renderer's submission
  surface.

When *app*'s renderer is the pre-HH4 log-only stub (no
`submit_sprite`), the bridge wraps it in a private `_HUDStubRenderer`
that records every submission into a Python list — the 2-line "pip
install and render" promise still works in headless CI.

Idempotent: a second call returns the already-mounted overlay.
Traces emit `("hud_mount", widget_count)`, `("hud_begin_frame", dt,
cmd_count)`, `("hud_submit", n)` per frame.

### `unmount_hud(app) -> bool`

_defined in `slappyengine.hud_bridge`_

Detach the HUD. Returns `True` when a HUD was actually detached,
`False` when nothing was mounted. Emits a `("hud_unmount",)` trace.

### `default_game_hud_widgets() -> list[Any]`

_defined in `slappyengine.hud_bridge`_

Return a fresh list of five default widgets (HealthBar, StaminaBar,
AmmoCounter, Compass, Crosshair) laid out for a 1280x720 viewport.
Fresh instances each call — safe to mutate.

### `add_diagnostics_widget(app, collector=None) -> _DiagnosticsHUDWidget`

_defined in `slappyengine.hud_bridge`_

Attach a compact diagnostics readout widget (OO6). Mounts an
:class:`HUDOverlay` via :func:`mount_hud` if none is present, then
attaches the widget bound to *collector* (or the module-level
:func:`slappyengine.diagnostics.get_global_collector` singleton if
`None`). The widget renders one summary line
(``ERROR: n | WARN: m``) plus up to three most-recent event messages.

Raises `ValueError` when *app* is `None`.

## Usage

```python
from slappyengine.app import App
from slappyengine.hud_bridge import mount_hud, default_game_hud_widgets

app = App()   # HH1 lifecycle host
overlay = mount_hud(app, widgets=default_game_hud_widgets())

# The App.run() tick loop now drives begin_frame + end_frame +
# submit_to_renderer once per frame. Tests can inspect via:
assert overlay.widget_count == 5
assert ("hud_mount", 5) in app.trace
```

Direct overlay use (bypassing the bridge):

```python
from slappyengine.ui.runtime.hud_overlay import HUDOverlay
from slappyengine.ui.runtime.hud_registry import HUDRegistry

registry = HUDRegistry()
overlay = HUDOverlay(renderer=my_renderer, camera_2d=my_camera_2d)
overlay.attach(registry.create("crosshair", {"center": (640.0, 360.0)}))

overlay.begin_frame(dt=1.0 / 60.0, input_state={"mouse": (100.0, 200.0)})
overlay.end_frame()
n = overlay.submit_to_renderer()
```

## Skip the wrapper

`slappyengine.ui.runtime.hud_overlay` and `slappyengine.hud_bridge` are
Python-only. Grep of `slappyengine._core_facade.RUST_MODULE_MAP` shows
**no** `hud_overlay` / `hud_bridge` entry — the per-frame work is
`ImmediateUI.begin_frame` bookkeeping + a handful of DrawCommand
translations, dwarfed by the actual renderer submission cost.

Games with an existing HUD stack can bypass :class:`HUDOverlay`
entirely and use :func:`hud_command_to_sprite` /
:func:`hud_command_to_text` as stateless DrawCommand-to-payload
converters. Games that only want the registry can instantiate
:class:`HUDRegistry` directly without touching the overlay.

## See also

- [`ui_widgets.md`](ui_widgets.md) — notebook-themed DPG editor
  widgets (structural layer above DPG); separate axis from the game
  HUD.
- [`render_instanced.md`](render_instanced.md) — Renderer surface the
  overlay submits sprites through.
- [`diagnostics.md`](diagnostics.md) — source of the
  :class:`DiagnosticEvent` records surfaced by
  :func:`add_diagnostics_widget`.
- [`telemetry.md`](telemetry.md) — recommended emitter for HUD
  lifecycle events.
