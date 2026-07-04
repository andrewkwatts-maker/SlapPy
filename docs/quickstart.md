# SlapPyEngine — 5-Minute Quickstart

*Last updated 2026-07-04*

Boot the engine, run a demo, open the notebook-diary editor, and land your
first three customisations (theme, hotkey, prefab) in under five minutes.

New contributors should read this front-to-back once; the more
architectural [`docs/ONBOARDING.md`](ONBOARDING.md) is the follow-up when
you are ready to touch engine internals.

---

## 1. Prerequisites

- **Python 3.11, 3.12, or 3.13** (`python --version`).
- **A GPU** with a Vulkan / Metal / DirectX 12 driver — the wgpu backend
  auto-selects. Headless dynamics / zones / telemetry / studio work on
  any CPU.
- **Rust toolchain** (stable) only if you plan to build from source. The
  wheel on PyPI already ships the compiled `_core` extension.
- *(Optional)* [`arithma>=2.0.2`](https://pypi.org/project/arithma/) — the
  symbolic-math sibling library. `slappyengine.math.Formula` transparently
  upgrades to Arithma's Rust-backed `Expression` when installed;
  otherwise it stays in a locked-down `math` sandbox.

---

## 2. Install

Pick one of the install variants; the `editor` extra pulls the Dear PyGui
notebook shell + pywebview + Arithma.

```bash
# Core engine only (headless-safe subpackages + Rust core)
pip install slappy-engine==0.3.0b0

# Recommended for new contributors — brings the notebook editor + Arithma
pip install "slappy-engine[editor]"

# Full contributor rig
pip install "slappy-engine[editor,audio,dev,math]"
```

**Windows note:** if `pip` warns about missing wheels, upgrade pip first
(`python -m pip install -U pip`). If you build from source and `maturin
develop` cannot find a Python interpreter, point it at the real one:

```powershell
$env:PYO3_PYTHON = "C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe"
maturin develop --extras dev
```

---

## 3. First demo — verify the install

Every `hello_*` script under
[`SlapPyEngineExamples/examples/`](../SlapPyEngineExamples/examples/) is
runnable headlessly. The ragdoll demo touches the biggest slice of the
Rust core (softbody XPBD + IK + rasterisation) so it makes a good smoke
test:

```bash
# From a checkout:
python SlapPyEngineExamples/examples/hello_ragdoll.py --no-gif

# Or emit a 120-frame GIF:
python SlapPyEngineExamples/examples/hello_ragdoll.py --frames 120 --out ragdoll.gif
```

Every demo uses the shared `slappyengine.examples_common` argparse helper,
so `--frames` / `--out` / `--no-gif` / `--render` behave the same across
the 47-demo gallery. If you installed via `pip`, download the demo
scripts from the [SlapPyEngineExamples folder on GitHub](https://github.com/andrewkwatts-maker/SlapPyEngine/tree/master/SlapPyEngineExamples/examples)
or clone the repo (`git clone …`).

---

## 4. First editor boot

Two entry points, pick whichever suits you:

**A. From Python (recommended for first-timers):**

```python
import slappyengine as se

engine = se.Engine()          # loads config/engine.yml defaults
engine.run_editor()            # opens the DearPyGui notebook shell
```

Save that as `boot.py` and run `python boot.py`.

**B. From the example script:**

```bash
python SlapPyEngineExamples/examples/editor_demo.py
```

This variant prepopulates a demo scene (terrain, material map, animation
graph) so every panel has content to show.

On the first launch the editor calls `UserOverrideLoader.ensure_scaffolded()`
and creates `~/.slappyengine/` on disk — you will use those folders in
the next three sections.

---

## 5. First custom theme

Six diary themes ship in the box (`teengirl_notebook`, `cozy_diary`,
`bullet_journal`, `scrapbook_summer`, `cottagecore_garden`,
`kawaii_planner`); cycle them with `Ctrl+Shift+T`. To ship your own
theme:

```bash
# Baked themes are copied here on first editor launch.
ls ~/.slappyengine/themes/
# → cozy_diary.theme.yaml  teengirl_notebook.theme.yaml  …

cp ~/.slappyengine/themes/cozy_diary.theme.yaml \
   ~/.slappyengine/themes/my_diary.theme.yaml
```

Edit `my_diary.theme.yaml` — palette colours, font, page-lining shader
id, edge-stroke id, washi-tape id are all top-level YAML keys.
References:

- 15 page-lining shaders (`PAGE_LININGS` in
  `python/slappyengine/ui/theme/page_linings/library.py`) —
  ruled_paper, dot_grid, graph_grid, isometric_grid, hex_grid, music_staff,
  blank_cream, parchment_aged, kraft_paper, watercolor_paper,
  graph_engineering, polka_dot_soft, star_scatter, linen_woven,
  notebook_college.
- 15 edge-stroke shaders (`EDGE_STROKES` in
  `python/slappyengine/ui/theme/edge_strokes/library.py`) — ballpoint,
  gel, pencil_2b, pencil_hb, marker, highlighter, brush_watercolor,
  chalk, charcoal, crayon, ink_wash, sharpie, colored_pencil,
  fountain_pen, quill.
- 23 washi-tape shaders (`WASHI_TAPES` in
  `python/slappyengine/ui/theme/washi_tape/library.py`) — 15 static
  patterns plus 8 animated (heart_pulse, sparkle_shimmer,
  rainbow_flow, marching_dots, wave_shift, dashed_scroll, stars_twinkle,
  music_notes_flow).

Restart the editor (or use `Ctrl+T` → **Reload themes**) and the new
theme appears in the theme-switcher dropdown.

Programmatic access:

```python
from slappyengine.ui.theme.user_themes import UserThemeStore

store = UserThemeStore()
store.bake_defaults()          # idempotent copy of baked themes
print(store.list_names())      # includes "my_diary" once saved
```

---

## 6. First custom hotkey

The `~/.slappyengine/ui/hotkeys/` folder holds both YAML bindings and a
sibling `commands.py` for `user.*` command handlers.

**`~/.slappyengine/ui/hotkeys/my_hotkeys.yaml`:**

```yaml
ctrl+shift+m: user.mark_bookmark
ctrl+alt+p:   editor.profiler_toggle   # rebind an existing built-in
```

**`~/.slappyengine/ui/hotkeys/commands.py`:**

```python
"""Callables invoked by user.* command ids."""


def mark_bookmark() -> None:
    from slappyengine.ui.editor.editor_undo import global_stack
    global_stack().push_bookmark("user_bookmark")
```

Rules:

- User bindings **win** on collision with built-ins.
- Only `user.*` ids resolve inside `commands.py`; every other id is
  passed straight to the tool-router dispatcher (so you can rebind
  built-in actions from your own YAML).
- Keys are case-normalised — `Ctrl+Shift+M`, `ctrl+shift+m`, and
  `SHIFT+ctrl+m` all resolve to the same binding.
- The 27 built-in bindings live frozen in
  `python/slappyengine/ui/editor/notebook_hotkeys.py::_BINDINGS_FROZEN`.

For the full customisation contract, see
[`docs/user_customization_2026_06_07.md`](user_customization_2026_06_07.md).

---

## 7. First prefab drop

The prefab library ships six baked entries out of the box — `ball`,
`bridge`, `chain`, `crate`, `ragdoll`, `windmill` — under
`python/slappyengine/prefabs/baked/`. On first use, `PrefabLibrary`
copies them into `~/.slappyengine/prefabs/` so you can edit them
without touching the installed wheel.

Programmatic drop into a scene:

```python
from slappyengine.prefabs import PrefabLibrary
from slappyengine import studio

library = PrefabLibrary()
library.bake_defaults()                    # copy baked → user dir
library.load_from_dir(library.USER_DIR)    # merge YAML into registry

stage = studio.dynamics_stage(gravity=(0.0, -9.81))
library.get("ragdoll").instantiate(stage.dynamics, position=(0.0, 3.0))
stage.record("ragdoll.gif", frames=180)
```

Editor drop:

1. Boot the editor (Section 4).
2. Click the **+ Add** stationery button on the notebook toolbar.
3. Pick **Prefab → ragdoll** (or any other entry) — the spawn card
   drops the entity at the cursor position.

Author a new prefab by copying one of the YAML files:

```bash
cp ~/.slappyengine/prefabs/chain.prefab.yaml \
   ~/.slappyengine/prefabs/my_chain.prefab.yaml
```

Edit the top-level `name`, `category`, and `spec` keys; the library
picks it up on next `load_from_dir` call.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| **`ImportError: slappyengine._core`** — the Rust extension is missing. | You are on a source checkout; run `maturin develop` (set `$env:PYO3_PYTHON` on Windows if the wrong interpreter is picked). Pure-Python fallbacks exist for every critical path, but performance drops sharply. |
| **`dearpygui not found` when calling `engine.run_editor()`** | Install the editor extra: `pip install "slappy-engine[editor]"`. `dearpygui`, `pywebview`, and `arithma` land together. |
| **Editor boots but the window is dark grey with no panels.** | The Nova3D fallback layout is active. Press `Ctrl+0` (Reset Layout) or pick `View → Layout Presets → Default`. |
| **A hotkey doesn't fire.** | Confirm the key string is lower-case in the YAML and the command id exists in `tool_router.REGISTRY` (or in your `commands.py` if `user.*`). Failures are logged via `logging.WARNING` — inspect the console. |
| **A custom theme does not appear.** | Check the filename ends in `.theme.yaml` and the top-level `id:` field is unique. `UserThemeStore.list_names()` returns everything the store can see. |
| **`hello_*` demo runs but no GIF is written.** | Pillow needs to be installed (`pip install Pillow>=10`). Pass `--no-gif` to run headless only. |
| **`wgpu` fails to initialise on Windows.** | Update your GPU driver, or force a backend via `config/engine.yml → rendering.backend: "vulkan"` (or `"dx12"`). |
| **Autosave keeps prompting me on boot.** | Delete stale snapshots in `~/.slappyengine/autosave/` or disable the timer via `AutosaveManager(enabled=False)` in your own boot script. |

---

## 9. Where to Go Next

- [`docs/ONBOARDING.md`](ONBOARDING.md) — architecture, the Entity /
  Asset / Layer / Pixel model, the Rust `_core` module map, and the
  `actions/` / prefab / autosave subsystems.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — the short reference for
  day-to-day conventions.
- [`docs/user_customization_2026_06_07.md`](user_customization_2026_06_07.md)
  — the full user-override contract (panels, spawn cards, shaders,
  config).
- [`docs/engine_feature_map_2026_07_04.md`](engine_feature_map_2026_07_04.md)
  — the 256-row status table (238 WIRED / 15 STUB / 3 BROKEN after
  Y7). If a menu item seems to no-op, look here first.
- [`docs/demo_gallery.md`](demo_gallery.md) — 6 curated flagship demos
  with reproducible commands.
- [`docs/studio_quickstart.md`](studio_quickstart.md) — the 5-minute
  tour of the `slappyengine.studio` scaffolding helpers.
- [`docs/notebook_editor_manual_2026_06_03.md`](notebook_editor_manual_2026_06_03.md)
  — panel-by-panel tour of the diary shell.
- [`docs/CONTRIBUTING.md`](CONTRIBUTING.md) — the hardening pattern,
  doc markers, naming conventions, and post-process pass authoring.

Welcome aboard. If something breaks, open an issue with the console
output and the platform triple (OS + Python + GPU driver).
