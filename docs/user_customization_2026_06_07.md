# SlapPyEngine — User Customization Guide

*Written 2026-06-07*

SlapPyEngine ships with a **folder-based user-override layer**. You can
drop Python files, YAML config, and WGSL shaders under
`~/.pharos_engine/ui/` to extend or replace parts of the editor
**without touching the installed package**.

This guide covers:

1. What the override folder looks like
2. How the loader works (contract summary)
3. Five worked examples — a custom panel, custom hotkeys with commands,
   a spawn card, a page-lining shader, and a config-file toggle.
4. Troubleshooting

---

## 1. Directory layout

The layer lives at `~/.pharos_engine/ui/`. Its structure is fixed:

```
~/.pharos_engine/
└── ui/
    ├── panels/                     ← user-defined editor panels (.py)
    │   └── my_timeline.py
    ├── hotkeys/                    ← extra key bindings + commands
    │   ├── my_hotkeys.yaml
    │   └── commands.py
    ├── spawn_actions/              ← extra spawn cards (.py)
    │   └── my_spawn.py
    ├── shaders/
    │   ├── page_linings/           ← .wgsl page-lining shaders
    │   ├── washi_tape/             ← .wgsl washi-tape shaders
    │   └── edge_strokes/           ← .wgsl edge-stroke shaders
    ├── examples/                   ← starter samples (disabled by default)
    │   ├── _example_panel.py
    │   ├── _example_hotkeys.yaml
    │   └── _example_shader.wgsl
    ├── config.yaml                 ← master toggles
    ├── README.md
    └── panels/README.md
```

On the **first launch** the editor calls
`UserOverrideLoader.ensure_scaffolded()` which creates every directory
above plus a `README.md` in each folder. The example files ship
disabled — their filenames start with `_` so the loader skips them.

> **Files starting with `_` are skipped.** Use this to disable an
> override without deleting it.

---

## 2. Contract summary

The user-override layer is implemented in
`python/pharos_engine/ui/user_overrides.py`. The public surface is:

* **`UserOverrideLoader(root=None)`** — construct with a path or let it
  default to `~/.pharos_engine/ui`.
* **`ensure_scaffolded()`** — populate the tree with folders + README
  files + a default `config.yaml` on first run.
* **`load_all() -> UserOverrideBundle`** — discover + load every user
  file. Never raises.

`UserOverrideBundle` carries five things:

| Field | Type | Notes |
|-------|------|-------|
| `panels` | `list[Any]` | Instantiated panel objects |
| `hotkey_bindings` | `dict[str, str]` | Key → command id |
| `hotkey_commands` | `dict[str, Callable]` | Command id → callable |
| `spawn_actions` | `list[dict]` | Extra spawn card specs |
| `shaders` | `dict[str, str]` | Shader id → WGSL source |
| `shader_kinds` | `dict[str, str]` | Shader id → kind |
| `config` | `dict[str, Any]` | Merged config (defaults + on-disk) |
| `errors` | `list[tuple[str, str]]` | Per-file failures |

**Every user file is loaded inside a try/except.** Failures are logged
via `logging` and appended to `bundle.errors`, but they never crash
the editor.

---

## 3. Worked examples

### 3.1 A custom editor panel — `panels/my_timeline.py`

```python
"""My custom horizontal-scrub timeline."""


class MyTimeline:
    TITLE = "Timeline (User)"

    def build(self, parent_tag):
        import dearpygui.dearpygui as dpg
        with dpg.child_window(parent=parent_tag, height=120):
            dpg.add_text("t = 0.00")
            dpg.add_slider_float(
                label="scrub", min_value=0.0, max_value=10.0,
                default_value=0.0,
            )


def get_panel():
    return MyTimeline()
```

The factory **must** be named `get_panel`. The returned object must
implement `build(parent_tag)` — same contract as every built-in
panel. `EditorShell` calls `register_panel(...)` for you and adds the
panel to the `View > User` submenu.

### 3.2 Extra hotkeys with commands — `hotkeys/my_hotkeys.yaml` + `commands.py`

**`hotkeys/my_hotkeys.yaml`:**

```yaml
ctrl+shift+m: user.mark_bookmark
ctrl+alt+p:   editor.profiler_toggle    # rebind an existing command
```

**`hotkeys/commands.py`:**

```python
"""Callables invoked by `user.*` command ids in hotkey YAMLs."""

def mark_bookmark() -> None:
    from pharos_editor.ui.editor.editor_undo import global_stack
    global_stack().push_bookmark("user_bookmark")
```

Notes:

* User bindings **win** on collision with built-ins.
* Only command ids that start with `user.` are looked up in
  `commands.py`; every other id is passed straight to the shell's
  command dispatcher (so you can trigger built-ins from your own
  keybinds).
* Keys are normalised — `Ctrl+Shift+M`, `ctrl+shift+m`, and
  `SHIFT+ctrl+m` all resolve to the same binding.

### 3.3 A user spawn card — `spawn_actions/my_spawn.py`

```python
"""Extra spawn card that drops a beach ball into the world."""


def get_spawn_card() -> dict:
    return {
        "card_id":      "user.beach_ball",
        "label":        "Beach Ball",
        "portrait_svg": "<svg viewBox='0 0 24 24'>"
                        "<circle cx='12' cy='12' r='10' fill='pink'/></svg>",
        "on_summon":    lambda world: world.spawn_particle(pos=(0, 0), kind="ball"),
    }
```

The dict is appended to `SPAWN_ACTIONS`, so it appears at the end of
the "+ Add" popup.

### 3.4 A page-lining shader — `shaders/page_linings/my_lining.wgsl`

```wgsl
struct Uniforms { u_size: vec2<f32>, u_time: f32 };
@group(0) @binding(0) var<uniform> u: Uniforms;

@fragment
fn fs_main(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let stripe = step(0.95, fract(frag.y / 12.0));
    return vec4<f32>(0.8, 0.8, 0.8, stripe * 0.4);
}
```

* Filename → shader id (`my_lining`).
* Parent folder → kind (`page_linings`).
* The loader hands the WGSL source verbatim to the `PAGE_LININGS`
  registry via a `LiningStyle` entry. Themes can then reference the
  id like any built-in style.

Do the same in `shaders/washi_tape/` and `shaders/edge_strokes/` for
the other registries.

### 3.5 The master `config.yaml`

```yaml
# ~/.pharos_engine/ui/config.yaml
enable_user_panels:        true
enable_user_hotkeys:       true
enable_user_spawn_actions: true
enable_user_shaders:       true
# Watchdog polls the folder + reloads panels on change.
watch_reload:              false
```

Any key that is absent inherits the default (all true). Set a category
to `false` to bypass loading entirely — useful for quickly disabling
a single feature during debugging.

---

## 4. Troubleshooting

* **My panel doesn't show up.** Check `~/.pharos_engine/ui/panels/` —
  the factory must be named `get_panel` exactly and return a non-None
  object with a `build(parent_tag)` method.
* **A hotkey doesn't fire.** Ensure the key string is lower-case
  (`ctrl+shift+m`, not `Ctrl+Shift+M`) inside the YAML — the loader
  normalises but a typo like `contorl+m` is silently ignored.
* **A shader is not applied.** Confirm the file lives under one of the
  three kind subdirectories. Shaders directly in `shaders/` are
  skipped by design.
* **Nothing is loading.** Inspect the editor log — every failure
  emits a `WARNING` from `pharos_editor.ui.user_overrides`. Bundles
  also carry the errors on `bundle.errors` for programmatic access.

---

## 5. Programmatic use

The loader is a plain Python class you can consume outside the editor:

```python
from pharos_editor.ui.user_overrides import UserOverrideLoader

loader = UserOverrideLoader()
loader.ensure_scaffolded()
bundle = loader.load_all()

print(bundle.summary())
# → {'panels': 1, 'hotkeys': 2, 'spawn_actions': 0, 'shaders': 1, 'errors': 0}
```

Pass `root=Path(...)` to point at a non-standard directory (this is
what the test suite does with `tmp_path`).
