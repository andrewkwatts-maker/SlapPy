# pip Extras Reference — 2026-07-05 (II6)

This document catalogs every optional-dependency extra shipped by the
`slappy-engine` PyPI wheel, explains what capability each extra
unlocks, cross-references which SlapPyEngine subpackage soft-imports
each dep, and shows the install command for common developer +
end-user profiles.

Landed by the II6 background scrum agent per HH3's recommendation in
`docs/nova3d_gap_audit_2026_07_05.md` §6-§8. Extras count grew from
**8** (editor, video, audio, dev, ai, math, network, 3d) to **10**
(added `assets` + `hud` + `all` meta) and existing extras were
extended where HH5 / HH4 / HH7 identified additional soft-imported
deps.

---

## 1. Extras table

| Extra     | Deps                                                               | Unlocks                                          | Wheel adds |
|-----------|--------------------------------------------------------------------|--------------------------------------------------|------------|
| `editor`  | `dearpygui>=1.11`, `pywebview>=4.0`, `arithma>=2.0.2`              | Notebook / diary editor UI + project manager     | ~30 MB     |
| `assets`  | `pygltflib>=1.16`, `trimesh>=4.0`, `imageio>=2.34`, `Pillow>=10.0` | glTF / OBJ / STL / PLY mesh + HDR/EXR/DDS import | ~40 MB     |
| `hud`     | `imgui[glfw]>=2.0`                                                  | Immediate-mode game HUD                          | ~5 MB      |
| `math`    | `arithma>=2.0.2`                                                    | Rust-backed symbolic Formula surface             | ~2 MB      |
| `video`   | `av>=12.0`, `opencv-python>=4.9`, `imageio-ffmpeg>=0.4`             | Video recording + import (multiple backends)     | ~80 MB     |
| `audio`   | `sounddevice>=0.4`, `soundfile>=0.12`, `pyaudio>=0.2`               | Audio playback + spatial mixing + capture        | ~4 MB      |
| `network` | `kademlia>=2.2.2`, `aioice>=0.9.0`, `zeroconf>=0.131`, `websockets>=12.0` | Multiplayer P2P + DHT + WebRTC + LAN discovery   | ~3 MB      |
| `ai`      | `httpx>=0.27`, `torch>=2.0`, `transformers>=4.30`                   | Local LLM authoring assist + HuggingFace models  | ~800 MB    |
| `dev`     | `pytest>=7.0`, `pytest-asyncio>=0.21`, `watchdog>=3.0`, `maturin>=1.5` | Test suite + hot reload + Rust wheel build      | ~30 MB     |
| `3d`      | (none — build-time only)                                            | `_core` Rust crate `3d` feature flag             | 0 MB       |
| `all`     | `slappy-engine[editor,assets,hud,math,video,audio,network]`         | Meta: everything except the heavy `ai` bundle    | ~150 MB    |

---

## 2. Install command examples

Everyday use cases and the exact command that unlocks them.

```bash
# Headless server / CI / import-time smoke tests — no GPU, no HUD.
# Only base deps: wgpu / numpy / Pillow / glfw / pyyaml / lz4.
pip install slappy-engine

# Ship a game with a HUD (no editor).
pip install slappy-engine[hud]

# Import glTF / OBJ meshes at editor / bake time.
pip install slappy-engine[assets]

# Full engine dev — editor + asset pipeline + HUD + math backend.
pip install slappy-engine[editor,assets,hud,math]

# Everything except the ~800 MB torch bundle.
pip install slappy-engine[all]

# Add AI features (Ollama client + Hugging Face pipelines).
pip install slappy-engine[all,ai]

# Contributing to the engine (tests + Rust wheel build).
pip install slappy-engine[dev]

# Multiplayer game.
pip install slappy-engine[hud,network,audio]
```

---

## 3. Cross-reference: subpackage → extra

Which `slappyengine.<subpackage>` requires which extra? All entries
soft-import — importing the subpackage never fails, only the
extra-gated code path does.

| Subpackage / module                              | Required extra | Soft-import target                       |
|--------------------------------------------------|----------------|------------------------------------------|
| `slappyengine.asset_import.gltf_importer`        | `assets`       | `pygltflib`                              |
| `slappyengine.asset_import.stub_importer`        | `assets`       | `trimesh` (STL/PLY paths)                |
| `slappyengine.asset_import.texture_importer`     | (base)         | `PIL.Image` (Pillow — core dep)          |
| `slappyengine.ui.editor.*`                       | `editor`       | `dearpygui`                              |
| `slappyengine.ui.editor.notebook_project_picker` | `editor`       | `pywebview`                              |
| `slappyengine.math.Formula` (Rust-backed path)   | `math`         | `arithma`                                |
| `slappyengine.audio` + `audio_runtime`           | `audio`        | `sounddevice`, `soundfile`               |
| `slappyengine.animation.video_import`            | `video`        | `av`                                     |
| `slappyengine.tools.video`                       | `video`        | `imageio-ffmpeg`, `opencv-python`        |
| `slappyengine.net.*`                             | `network`      | `kademlia`, `aioice`, `zeroconf`         |
| `slappyengine.ai.llm_client`                     | `ai`           | `httpx`                                  |
| `slappyengine.ai` (transformer path)             | `ai`           | `torch`, `transformers`                  |
| `slappyengine.ui.runtime.hud_kit` (imgui bridge) | `hud`          | `imgui`                                  |
| `slappyengine._core` 3D features                 | `3d`           | Rust feature flag (build-time)           |
| `slappyengine.testing`                           | `dev`          | `pytest`, `pytest-asyncio`               |
| `slappyengine.watcher`                           | `dev`          | `watchdog`                               |

---

## 4. Lightweight py-only install

For the *lightest* install (no GPU, no editor, no assets), just:

```bash
pip install slappy-engine
```

This gives you the base `wgpu`, `numpy`, `Pillow`, `glfw`, `pyyaml`,
`lz4` deps + the whole `slappyengine._core` Rust extension (~13 MB
total wheel weight). Roughly 90% of the engine surface still imports
cleanly:

* `slappyengine.compute` — GPU compute pipelines (still needs a
  display for wgpu adapter, but `--headless` CI runners work with the
  llvmpipe / SwiftShader fallbacks).
* `slappyengine.dynamics` — Rust-backed 2D physics.
* `slappyengine.render` — null renderer path (`renderer.py` falls back
  to a no-op canvas when `wgpu.request_adapter()` returns `None`).
* `slappyengine.scene`, `entity`, `components`, `event_bus`,
  `serialize` — all core ECS + YAML persistence.
* `slappyengine.asset_import.stub_importer` — no-op stubs for FBX /
  STL / PLY that return `ImportResult(ok=False, error=...)` when
  `trimesh` is absent. Used by unit tests to exercise the
  dispatcher without pulling `trimesh` into every CI run.
* `slappyengine.testing` (golden-master API) — Pillow-only.

The following will raise `ImportDependencyError` until you install the
gating extra:

* Any mesh import via `pygltflib` → `pip install slappy-engine[assets]`.
* Any DearPyGui editor panel → `pip install slappy-engine[editor]`.
* Any Formula symbolic route → `pip install slappy-engine[math]`.
* Any audio playback → `pip install slappy-engine[audio]`.

Recommended CI matrix for headless testing:

```yaml
# Bare-minimum: import-time smoke.
pip install slappy-engine

# Full non-heavy suite (matches `dev` extra).
pip install slappy-engine[dev,assets,audio,math]
```

The `ai` extra is deliberately excluded from CI matrices because
torch + transformers push the container image size past 3 GB.

---

## 5. Rationale for the `all` meta-extra

The `all` extra pulls in `editor`, `assets`, `hud`, `math`, `video`,
`audio`, `network` — everything a game developer or engine
contributor is likely to want in one shot. It excludes:

* `ai` — torch + transformers add ~800 MB. Users who want AI
  authoring assist opt-in with `pip install slappy-engine[all,ai]`.
* `dev` — pytest + maturin are only needed by contributors, not
  end-users shipping games. Add explicitly with
  `pip install slappy-engine[all,dev]`.
* `3d` — build-time flag, no Python deps.

This keeps the "install everything" path under ~150 MB while the full
super-set (`[all,ai,dev]`) lands around ~1 GB — the standard
"kitchen sink" flavor for AI-heavy authoring workflows.

---

## 6. Version-pin philosophy

All extras use `>=` minimums, never `==` pins. Rationale:

* SlapPyEngine soft-imports every optional dep and gracefully
  degrades when they are missing — a mismatched version is very
  rarely fatal.
* Users often have `torch` / `numpy` / `Pillow` already installed via
  other packages; hard-pinning would break their environment.
* The minimums are chosen at the earliest version where the API the
  engine uses has been stable. Bumping the minimum requires a
  changelog entry.

Base package dependencies stay minimal on purpose:

* `wgpu>=0.18` — required for the whole render surface.
* `numpy>=1.24` — required for the compute + dynamics kernels.
* `Pillow>=10.0` — required for texture load + save.
* `glfw>=2.5` — required for the game-tick event loop.
* `pyyaml>=6.0` — required for scene / prefab / manifest load.
* `lz4>=4.0` — required for save-file + content-blob compression.

No hidden heavy deps (torch, opencv, transformers) leak into the base
install. This keeps `pip install slappy-engine` under 15 MB total.

---

## 7. Change log

* **2026-07-05 (II6)** — Added `assets`, `hud`, `all` meta-extra.
  Extended `video` with `opencv-python` + `imageio-ffmpeg`. Extended
  `audio` with `pyaudio`. Extended `ai` with `torch` + `transformers`.
  Extended `network` with `websockets`. Extended `dev` with `maturin`.
* **2026-06 (Phase B)** — Original 7 extras: `editor`, `video`,
  `audio`, `dev`, `ai`, `math`, `network` + build-time `3d`.

---

## 8. Cross-references

* `pyproject.toml` — the source of truth for all extras.
* `docs/nova3d_gap_audit_2026_07_05.md` §6.5, §7.2, §8 — HH3's
  original recommendation for the `assets` + `hud` + `all` structure.
* `python/slappyengine/asset_import/gltf_importer.py` — glTF loader
  that soft-imports `pygltflib`.
* `python/slappyengine/asset_import/stub_importer.py` — trimesh soft
  import for STL / PLY.
* `python/slappyengine/audio.py`,
  `python/slappyengine/audio_runtime.py` — sounddevice + soundfile
  soft imports.
* `python/slappyengine/animation/video_import.py` — `av` soft import.
* `python/slappyengine/ai/llm_client.py` — httpx soft import.
* `SlapPyEngineTests/tests/test_pyproject_extras.py` — regression
  suite locking in the extras structure.
