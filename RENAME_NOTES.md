# Rename + Rust/Vulkan Rewrite — v0.3.0b1

**Landed 2026-07-22 through 2026-07-23 as a 10-sprint push. This file
is the shipping summary; each Sprint N has its own commit on `master`
with a full changelog.**

## Package split

| Wheel | Contents | Deps | Size target |
|-------|----------|------|-------------|
| `pharos-engine` | Rust cdylib (`_core`) + Python engine, physics, fluid, softbody, animation, materials, HUD, asset_import | numpy, Pillow, wgpu, glfw, pyyaml, lz4 | ~5 MB |
| `pharos-editor` | DearPyGui notebook editor, themes, gizmos, spawn menu, layout persistence | `pharos-engine==0.3.0b1`, dearpygui, pywebview, arithma | ~15 MB |

`pip install pharos-editor` transitively installs `pharos-engine`.
Headless / server / build-tool users pay no editor cost.

Rule: **`pharos_engine` must never top-level-import `pharos_editor`.**
Enforced by `scripts/import_lint.py`. Runs green on `master`.

## Cargo workspace

Five crates under `crates/`:

| Crate | Type | Role |
|-------|------|------|
| `pharos_core`  | rlib | Physics / fluid / softbody / geometry / IK / material_eval kernels. Hosts `#[pyfunction]` / `#[pyclass]` types re-exported through pharos_py. |
| `pharos_render`| rlib | wgpu + Vulkan backend, VCR pipeline, CSM, skinning, scene walker, GPU compute (pbf / softbody). |
| `pharos_py`    | cdylib | PyO3 `_core` extension — thin wrapper over pharos_core + pyo3-heavy helpers. |
| `pharos_bin`   | bin  | `pharos-headless` standalone Rust+wgpu runtime; no Python required. |
| `pharos_c_abi` | cdylib + staticlib | Stable C ABI for Godot / Unity / JS / any FFI-capable runtime. Header via cbindgen. |

`cargo check --workspace` clean; requires `PYO3_PYTHON=<real python>`
to bypass the Windows-Store Python-launcher shim.

## VCR pipeline (Nova3D port)

Six stages under `crates/pharos_render/src/vcr/` + six WGSL shaders
under `crates/pharos_render/shaders/vcr_*.wgsl`:

1. `seed`         — init reservoir from G-buffer (specular + refraction slots)
2. `accumulate`   — extended-frustum raster; per-fragment cone test → additive contribution
3. `merge`        — WRS drop of least-important slot per pixel
4. `composite`    — sum K slots, env-cube LOD sampling, Beer-Lambert, Fresnel-lite output
5. `temporal`     — motion-vector reproject prev-frame reservoir (Standard+ presets only)
6. `config`       — SSoT constants + `wgsl_define_block()` injected at pipeline creation

Presets Off / Compat / Standard / Cinematic ported verbatim from Nova3D
`VCRConfig.hpp`.

## GPU compute migration

`crates/pharos_render/src/compute/{pbf,softbody}.rs` + WGSL:

- `pbf_step.wgsl`      — 4 compute entries: predict / hash / solve / integrate
- `softbody_step.wgsl` — 3 compute entries: predict / solve_beams / integrate

Python-side dispatch chooser at
`python/pharos_engine/compute/dispatch.py:choose_backend(kind, size)`:
CPU under threshold (Nova3D-measured 50–100 μs GPU launch cost);
GPU above. Overrideable via `engine_config.yaml` or `PHAROS_FORCE_GPU=1`.

## Nova3D flaw remediation (Sprint 8)

Ten documented Nova3D flaws → six landed as real infra:

| # | Flaw | Pharos |
|---|------|--------|
| 1 | ImGui docking leaks | `pharos_editor/layout_schema.py` — YAML-backed, quarantines corrupt files |
| 2 | Glassmorphism hard-coded | `pharos_editor/themes/*.yaml` — palette is data |
| 3 | No runtime HUD | `pharos_engine/hud/` — imgui[glfw] path, text-mode fallback |
| 4 | Panel redraw unprofiled | `pharos_editor/panel_protocol.py` — `PanelHost` measures tick, emits telemetry on 2-frame >5ms streak |
| 5 | No asset import | Already shipped: `pharos_engine/asset_import/gltf_importer.py` + `obj_importer.py` |
| 6 | Scene→drawcall path | `pharos_render/src/scene/walker.rs` — frustum cull + material sort |
| 7 | No CSM shadows | `pharos_render/src/shadow/csm.rs` + `shaders/shadow_csm.wgsl` |
| 8 | Skinning missing | `pharos_render/src/skinning.rs` + `shaders/skinning.wgsl` |
| 9 | Single theme | `pharos_editor/themes/colorblind_safe.yaml` (Wong 2011 palette), teengirl_notebook default |
| 10 | 50+ silent `except: pass` | `pharos_editor/errors.py:route()` + `scripts/errors_lint.py` CI guard |

## UI polish (Sprint 9)

Seven Sprint T7 usability wins land as reusable primitives every
remaining shell integration hooks into:

| # | Item | Module |
|---|------|--------|
| 1 | Tooltip registry (500ms hover) | `pharos_editor/tooltips.py` |
| 2 | Right-click context menu (7 actions) | `pharos_editor/context_menu.py` |
| 3 | Ctrl+C / Ctrl+V clipboard | `pharos_editor/clipboard.py` |
| 4 | Ctrl+click / Shift+click multi-select | `pharos_editor/multiselect.py` |
| 5 | Content-browser breadcrumbs | `pharos_editor/breadcrumbs.py` |
| 6 | Recently-used spawn cards | `pharos_editor/recently_used.py` |
| 7 | Undo/redo command stack (128-depth) | `pharos_editor/command_stack.py` |

## CLI + Cargo entry points

| Command | Path | Purpose |
|---------|------|---------|
| `pharos`         | pharos_engine.cli:main   | Headless engine CLI |
| `pharos-edit`    | pharos_editor.__main__:main | Boots the notebook editor |
| `pharos-headless`| pharos_bin/src/main.rs   | Standalone Rust+wgpu; renders a scene YAML → PNG with no Python involved |

## Publishing (Sprint 10 deferrable)

`pyproject.toml` (root) + `pharos-editor/pyproject.toml` are ready for
`maturin publish` / `python -m build` respectively. The actual PyPI
release + crates.io push for `pharos_core` remain a manual gate
(credentials + explicit user go-ahead).
