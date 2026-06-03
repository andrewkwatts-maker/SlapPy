<!-- handauthored: do not regenerate -->
# slappyengine.ui.widgets — API Reference

> Hand-written reference for the notebook-themed Dear PyGui widget primitives.
> These widgets are a theme-agnostic structural layer above DPG; concrete
> themes (e.g. the TeenGirl Notebook theme that lands in the next sprint)
> plug in via [`set_active_theme`](#set_active_theme).  For the underlying
> editor shell that hosts these widgets see
> [`ui_editor.md`](ui_editor.md).

## Overview

The `slappyengine.ui.widgets` subpackage layers a *notebook flavour* on
top of Dear PyGui without binding to any one visual theme.  Every widget
queries the active [`NotebookTheme`](#notebooktheme) at construction time
for its palette, nine-slice path, sticker glyph, and ASCII fallback.
When no theme is registered the widgets fall back to a built-in pastel
palette so the editor remains usable in vanilla mode.

The widgets coexist with the legacy PIL-backed primitives (`Widget`,
`Button`, `Panel`, `LayoutBox`, …) re-exported from the same package.
The notebook widgets are distinguished by their `_NotebookWidget` base
class and by being themed via the dataclass registry rather than the
legacy `Theme` palette.

The package is **import-safe in headless contexts**: the heavy
`dearpygui` import is deferred to each widget's `build()` method, so
constructing widgets, reading their colour snapshots, and registering
sticker corners all work even when the `[editor]` extra is not
installed.

## Public surface

```python
from slappyengine.ui.widgets import (
    # Theme registry
    NotebookTheme,
    get_active_theme,
    register_theme_listener,
    resolve_theme,
    set_active_theme,
    unregister_theme_listener,
    # Widgets
    DoodleSeparator,
    HeartCheckbox,
    HighlighterSlider,
    NotebookTab,
    StickerButton,
    WashiPanel,
    # Decorations
    add_sticker_corner,
    list_sticker_corners,
    remove_sticker_corner,
)
```

The legacy PIL-backed `Widget` / `Button` / `Panel` / `Theme` symbols
remain exported from the same package — see the corresponding entries
in `__all__`.

## Theme registry

### `NotebookTheme`

_dataclass — defined in `slappyengine.ui.widgets.notebook_theme`_

The asset bundle every notebook widget queries at construction time.

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | `str` | `"default"` | Human-readable identifier. |
| `palette` | `dict[str, RGBA]` | `{}` | Colour bag indexed by semantic slot. |
| `nine_slice` | `dict[str, str]` | `{}` | Slot → texture path. |
| `stickers` | `dict[str, str]` | `{}` | `sticker_id` → PNG path. |
| `icon_fallback` | `dict[str, str]` | `{}` | `sticker_id` → emoji / text. |
| `sticker_rotation` | `float` | `4.0` | Default sticker tilt (clamped to ±15°). |

Recognised palette slots: `paper`, `ink`, `accent`, `highlight`,
`washi`, `heart`.  Recognised nine-slice slots: `sticker_button`,
`washi_panel`, `notebook_tab`, `highlighter_slider`, `heart_checkbox`.

Helper methods (each routed through the shared `_validation` helpers):

- `color(slot, default=...)` — palette lookup with default.
- `nine_slice_path(slot)` — texture path lookup, `""` when absent.
- `sticker_path(sticker_id)` — sticker PNG path, `""` when absent.
- `icon_for(sticker_id, default="*")` — emoji fallback lookup.

### `set_active_theme(theme: NotebookTheme | None) -> None`

Registers *theme* as the active notebook theme.  Pass `None` to clear.
Notifies every subscribed widget via the listener hook so already-built
widgets restyle without an explicit refresh call.  Raises `TypeError`
if *theme* is not a `NotebookTheme` instance or `None`.

### `get_active_theme() -> NotebookTheme | None`

Returns the currently registered theme, or `None` when no theme is set.

### `resolve_theme() -> NotebookTheme`

Returns the active theme, or a built-in fallback when none is set.
Widgets call this internally; user code rarely needs it.

### `register_theme_listener(callback) -> None` / `unregister_theme_listener(callback) -> None`

Subscribe / unsubscribe a callback invoked on every `set_active_theme`
call.  The callback receives the new theme (or `None`).  Listeners that
raise have their exception swallowed so a misbehaving subscriber cannot
poison the registry.

## Widget primitives

### `StickerButton`

_class — defined in `slappyengine.ui.widgets.sticker_button`_

Sticker-style button.  Renders consistently as a peeled sticker via
`palette["accent"]` + `nine_slice["sticker_button"]` + a tilted DPG
group.

```python
StickerButton(
    label: str,
    sticker_icon: str,
    callback: Callable,
    *,
    rotation: float | None = None,
    width: int = 120,
    height: int = 36,
) -> None
```

Read-only properties: `accent_color`, `sticker_path`, `fallback_icon`,
`rotation`, `root_tag`.

### `WashiPanel`

_class — defined in `slappyengine.ui.widgets.washi_panel`_

Bordered panel with a washi-tape strip above the title.

```python
WashiPanel(
    title: str,
    children: Sequence[Callable[[], None]] | None = None,
    *,
    width: int = -1,
    height: int = -1,
) -> None
```

Children are zero-arg builders invoked inside the panel's content
container during `build()`.  Each child failure is swallowed so a
single broken builder doesn't break its siblings.

### `NotebookTab`

_class — defined in `slappyengine.ui.widgets.notebook_tab`_

Tab with a torn-paper edge.  Prefers the real DPG `tab` primitive when
the parent is a `tab_bar`; degrades to a labelled `child_window` for
non-tab parents.

```python
NotebookTab(
    label: str,
    children: Sequence[Callable[[], None]] | None = None,
) -> None
```

### `HighlighterSlider`

_class — defined in `slappyengine.ui.widgets.highlighter_slider`_

Float slider rendered as a highlighter strip.  Clamps its initial value
to `[min, max]` on construction.

```python
HighlighterSlider(
    label: str,
    value: float,
    min: float,
    max: float,
    callback: Callable,
) -> None
```

Programmatic update: `set_value(v)` re-clamps and fires the callback.

### `HeartCheckbox`

_class — defined in `slappyengine.ui.widgets.heart_checkbox`_

Boolean checkbox styled as a heart — fills when checked.

```python
HeartCheckbox(
    label: str,
    value: bool,
    callback: Callable,
) -> None
```

Helpers: `toggle()` returns the new value; `set_value(v)` matches the
slider's pattern.

### `DoodleSeparator`

_class — defined in `slappyengine.ui.widgets.doodle_separator`_

Decorative horizontal divider.

```python
DoodleSeparator(style: str = "wavy") -> None
```

`style` must be one of `"wavy"`, `"dotted"`, `"star_chain"`.  The
widget exposes `glyph` for the ASCII fallback the theme renders when
no glyph font is available.

## Sticker decorations

### `add_sticker_corner(parent, sticker_id, corner="TR") -> str`

Spawn a decorative sticker in a panel corner.  Returns a string handle
that can be passed to `remove_sticker_corner` to take the sticker back
off.  *corner* must be one of `"TL"`, `"TR"`, `"BL"`, `"BR"`
(case-insensitive — normalised internally).

### `remove_sticker_corner(handle) -> bool`

Remove a sticker previously created by `add_sticker_corner`.  Returns
`True` if a matching handle was removed, `False` if the handle was
unknown (idempotent — safe to call twice).

### `list_sticker_corners(parent=None) -> list[str]`

List active sticker handles, optionally filtered by parent tag.

## Inner modules

- `slappyengine.ui.widgets.notebook_theme` — `NotebookTheme`, the
  registry, the fallback palette.
- `slappyengine.ui.widgets._dpg_base` — `_NotebookWidget` base class
  (theme snapshot + build / destroy lifecycle).
- `slappyengine.ui.widgets.sticker_button` — `StickerButton`.
- `slappyengine.ui.widgets.washi_panel` — `WashiPanel`.
- `slappyengine.ui.widgets.notebook_tab` — `NotebookTab`.
- `slappyengine.ui.widgets.highlighter_slider` — `HighlighterSlider`.
- `slappyengine.ui.widgets.heart_checkbox` — `HeartCheckbox`.
- `slappyengine.ui.widgets.doodle_separator` — `DoodleSeparator`.
- `slappyengine.ui.widgets.sticker_corner` —
  `add_sticker_corner` / `remove_sticker_corner` /
  `list_sticker_corners`.

## Conventions

- **Lazy DPG.** No widget module imports `dearpygui` at import time —
  every DPG call is deferred to `build()` or guarded by a try / except
  in headless code paths.  This keeps the package importable on CI
  runners without the `[editor]` extra.
- **Validation.** Every constructor routes its arguments through the
  shared `slappyengine._validation` helpers (`validate_non_empty_str`,
  `validate_callable`, `validate_bool`, `validate_finite_float`, …).
  Bad inputs raise `TypeError` / `ValueError` with a clear `{fn}: {name}
  ...` prefix.
- **Theme snapshot at construction.** Widgets read the active theme
  exactly once at construction time and cache the resolved colours /
  paths in private fields.  When `set_active_theme` is called later,
  the listener hook re-runs `refresh_theme` so the cached snapshot
  stays in sync.
- **Fallback rendering.** When no theme is registered, widgets fall
  back to a built-in pastel palette plus ASCII / emoji glyphs.  The
  visual contract degrades gracefully — no widget raises because a
  theme slot is missing.
- **Headless tests.** Every widget is exercised by
  `SlapPyEngineTests/tests/test_ui_widgets_notebook.py` against a
  stubbed `dearpygui.dearpygui` module.  Constructors, theme
  re-binding, and callback firing all work without a live DPG context.

## See also

- [`ui_editor.md`](ui_editor.md) — the editor shell that hosts these
  widget primitives.
- [`material.md`](material.md) — material editing surface inside the
  editor.
