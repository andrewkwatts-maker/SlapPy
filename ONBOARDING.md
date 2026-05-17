# SlapPyEngine — Contributor Onboarding

Welcome to SlapPyEngine. This document covers the architecture, the data model, and everything you need to ship your first change in about ten minutes. Read it top-to-bottom once; afterwards the [ARCHITECTURE.md](ARCHITECTURE.md) file is a faster reference for day-to-day conventions.

---

## 1. What is SlapPyEngine?

SlapPyEngine is a GPU-accelerated pixel-art game engine whose primary render target is a 2D compute-shader pipeline. A second, opt-in 3D render path lives behind a Rust feature flag and a PyPI extra so the base wheel stays small.

| Install variant | Command | Approximate size |
|---|---|---|
| Core 2D | `pip install slappyengine` | ~15 MB |
| With 3D | `pip install slappyengine[3d]` | ~35 MB |
| Full dev rig | `pip install -e ".[dev,editor,audio,network]"` | varies |

Three first-party games ship alongside the engine as living integration tests:

- **Bullet Strata** (`H:\DaedalusSVN\Bullet Strata`) — arena shooter
- **Ochema Circuit** (`H:\DaedalusSVN\Ochema Circuit`) — vehicle builder with destructible pixel terrain
- **Stone Keep** — castle-defense game (planned)

The engine is in **alpha** (`Development Status :: 3 - Alpha`). APIs may change between milestones.

---

## 2. Repository Layout

```
SlapPyEngine/
├── python/
│   └── SlapPyEngine/              # Python package root
│       ├── __init__.py            # Public API, lazy-import map, HAS_NATIVE flag
│       ├── engine.py              # Engine class — GPU init, draw loop, subsystems
│       ├── scene.py               # Scene, SceneComputeAPI, DecalSystem
│       ├── entity.py              # Entity base class (scripts, tags, Z-height)
│       ├── asset.py               # Asset(RenderTarget) — layers + material map
│       ├── layer.py               # Layer — per-pixel image + struct data
│       ├── camera.py              # Camera (position, zoom, viewport)
│       ├── lighting.py            # LightingSystem, DirectionalLight, PointLight …
│       ├── config.py              # YAML loader, typed dataclasses (Config)
│       ├── tags.py                # TagRegistry — up to 32-bit pixel tags
│       ├── collision.py           # CollisionWorld, AABBShape, CircleShape
│       ├── animation/
│       │   ├── graph.py           # AnimationGraph, AnimState, AnimTransition
│       │   └── procedural.py      # ProceduralRig, ControlPoint (IK)
│       ├── compute/
│       │   ├── pipeline.py        # ComputePass — single WGSL dispatch
│       │   ├── asset_compute.py   # AssetComputeAPI, PixelAPI (wired by engine)
│       │   ├── effect.py          # EffectPipeline (node material dispatches)
│       │   ├── mutator.py         # Pixel mutator helpers
│       │   ├── readback.py        # GPU → CPU readback utilities
│       │   ├── spatial.py         # Spatial queries over pixel buffers
│       │   ├── stats.py           # GPU reduction stats
│       │   └── ast_compiler.py    # Expression → WGSL AST compiler
│       ├── gpu/
│       │   ├── context.py         # GPUContext — wgpu device + queue wrapper
│       │   ├── render_pipeline.py # RenderPipeline — quad vert/frag shaders
│       │   ├── entity_renderer.py # EntityRenderer — draws Entity quads each frame
│       │   ├── texture_manager.py # TextureManager — upload / cache layer textures
│       │   ├── buffer_manager.py  # BufferManager — pixel struct buffers
│       │   ├── mesh_pipeline.py   # MeshPipeline (3D, lazy-created)
│       │   ├── mesh_renderer.py   # MeshRenderer (3D, one per 3D Layer)
│       │   ├── mesh.py            # MeshGeometry data class
│       │   ├── pbr_material.py    # PbrMaterial (3D PBR parameters)
│       │   ├── sdf_extruder.py    # SdfExtruder — extrude 2D SDF into 3D mesh
│       │   └── material_buffer.py # MaterialBuffer — GPU uniform for material map
│       ├── material/
│       │   ├── map.py             # MaterialMap, ColorRange, MaterialDef
│       │   └── node_material.py   # NodeMaterial + all node types (Add, Lerp …)
│       ├── post_process/
│       │   ├── chain.py           # PostProcessChain, PostProcessPass
│       │   └── executor.py        # PostProcessExecutor (dispatches chain each frame)
│       ├── residency/
│       │   ├── manager.py         # ResidencyManager — disk/RAM/VRAM promotion
│       │   ├── slap_format.py     # .slap binary format (LZ4-compressed layers)
│       │   └── compression.py     # compress_array / decompress_raw wrappers
│       ├── net/
│       │   ├── session.py         # GameSession, SessionConfig (P2P host/join)
│       │   ├── peer.py            # Peer, PeerState
│       │   ├── sync.py            # LockstepSync, InputFrame
│       │   ├── discovery.py       # LAN (zeroconf) + DHT (kademlia) discovery
│       │   └── room.py            # RoomCode — 6-char human-readable codes
│       ├── ui/
│       │   ├── editor/
│       │   │   ├── shell.py       # EditorShell — DPG window layout driver
│       │   │   ├── toolbar.py     # EditorToolbar (2D/3D toggle, play/stop)
│       │   │   ├── scene_outliner.py  # SceneOutliner — entity tree panel
│       │   │   ├── property_inspector.py  # PropertyInspector — right panel
│       │   │   ├── layer_panel.py # LayerPanel — layer list + mode radio buttons
│       │   │   ├── layer_lighting_panel.py  # Per-layer LightingContext controls
│       │   │   ├── viewport_panel.py  # ViewportPanel — live wgpu canvas tab
│       │   │   ├── content_browser.py # ContentBrowser — bottom file tree
│       │   │   ├── material_editor.py # MaterialEditor (node graph UI)
│       │   │   ├── node_graph_panel.py # NodeGraphPanel
│       │   │   ├── anim_graph_panel.py # AnimGraphPanel
│       │   │   ├── gizmo_overlay.py   # GizmoOverlay (transform handles)
│       │   │   ├── code_mode_panel.py # CodeModePanel — script editor
│       │   │   ├── tag_painter.py    # TagPainter — pixel tag painting
│       │   │   ├── mesh_inspector.py # MeshInspector (3D layer geometry)
│       │   │   ├── behavior_panel.py # BehaviorPanel (AI-assisted scripting)
│       │   │   ├── ollama_setup_modal.py  # Ollama local-LLM configuration
│       │   │   └── theme.py       # Nova3D dark DPG theme
│       │   ├── scene_ui.py        # SceneUIEntity — in-world UI widgets
│       │   ├── hud_widgets.py     # draw_stat_bar and other HUD helpers
│       │   └── project_manager.py # ProjectManager (HTML webview window)
│       ├── input/
│       │   ├── action_map.py      # ActionMap — rebindable player input
│       │   └── _manager.py        # InputManager — keyboard/mouse/gamepad state
│       ├── iso/                   # Isometric projection helpers
│       ├── ext/                   # Thin shims for optional subsystems
│       ├── modules/               # StructModules: health, physics, fluid_params …
│       ├── tools/                 # CLI utilities (gen_placeholders, etc.)
│       └── ai/                    # LLM client + script generation (httpx)
├── src/                           # Rust _core crate (PyO3 / maturin)
│   ├── lib.rs                     # Module registration (all submodules)
│   ├── math.rs                    # Vec2, AABB, ray-cast helpers
│   ├── math_3d.rs                 # Vec3, Mat4 (feature = "3d" only)
│   ├── ik_solver.rs               # FABRIK IK solver
│   ├── hull.rs                    # Convex hull utilities
│   ├── node_compiler.rs           # Material node → WGSL compiler
│   ├── slap_format.rs             # .slap binary I/O helpers
│   ├── struct_layout.rs           # Pixel struct layout calculator
│   └── tile_cache.rs              # Tile streaming cache
├── shaders/                       # WGSL shader templates (used by Python at runtime)
│   ├── quad_vert.wgsl             # Vertex shader — axis-aligned quad
│   ├── quad_frag.wgsl             # Fragment shader — single texture2d
│   ├── quad_frag_array.wgsl       # Fragment shader — texture2d_array (CubeArray)
│   ├── pixel_physics.wgsl         # Per-pixel gravity, melt, boil simulation
│   ├── material_dispatch.wgsl     # Color → material tag assignment
│   ├── lighting_point.wgsl        # Point light contribution
│   ├── lighting_cone.wgsl         # Cone/spot light contribution
│   ├── lighting_directional.wgsl  # Directional light + shadow
│   ├── lighting_cluster.wgsl      # Tile-based clustered lighting cull pass
│   ├── lighting_emission.wgsl     # Blackbody emission from hot pixels
│   ├── lighting_radiance_cascade.wgsl  # Radiance cascade (optional)
│   ├── lighting_combine.wgsl      # Accumulation → final lit texture
│   ├── fluid_sim_advect.wgsl      # Fluid advection (Navier-Stokes)
│   ├── fluid_project.wgsl         # Fluid pressure projection
│   ├── fluid_render.wgsl          # Fluid density → RGBA
│   ├── mesh_vert_3d.wgsl          # 3D mesh vertex shader
│   ├── mesh_frag_pbr.wgsl         # PBR fragment shader
│   ├── sdf_3d_extrude.wgsl        # SDF → 3D extrusion compute
│   ├── outline.wgsl               # Post-process outline
│   ├── blur.wgsl                  # Gaussian blur pass
│   ├── pixelate.wgsl              # Pixelation pass
│   ├── decal_paint.wgsl           # Decal blending compute
│   └── … (40+ shaders total)
├── config/
│   ├── engine.yml                 # All numeric engine defaults
│   └── materials.yml              # Color-range → behavior mappings
├── tests/                         # pytest suite (~22 test files)
└── examples/
    ├── hello_world.py
    ├── layered_character.py
    ├── fluid_sandbox.py
    ├── landscape_demo.py
    ├── editor_demo.py
    ├── hud_demo.py
    └── multiplayer_demo.py
```

---

## 3. Quick Start (10 minutes)

### Prerequisites

- Python 3.11, 3.12, or 3.13
- Rust toolchain (stable) for the Rust extension
- A GPU with Vulkan, Metal, or DX12 support (or WebGPU via a browser)

### Step 1 — Install

```bash
# Clone the repo (or open the existing checkout)
cd H:\Github\SlapPyEngine

# Editable install with dev and editor extras
pip install -e ".[dev,editor]"

# Build the Rust extension (_core) in debug mode
maturin develop
```

**Windows gotcha:** If `maturin develop` fails with a Python discovery error, the Windows Store Python stub is interfering. Point maturin at the real interpreter:

```powershell
$env:PYO3_PYTHON = "C:\Users\Andrew\AppData\Local\Programs\Python\Python313\python.exe"
maturin develop --extras dev
```

### Step 2 — Run the minimal example

```python
# examples/hello_world.py  (already in the repo)
import slappyengine as se

engine = se.Engine()   # reads config/engine.yml — no magic numbers here
engine.run()           # opens an 800×600 window, clears to dark slate
```

```bash
python examples/hello_world.py
```

### Step 3 — A scene with an asset

```python
import slappyengine as se

engine = se.Engine()
scene  = se.Scene(name="MyScene")

# Asset: a positioned render target that owns layers
asset = se.Asset(name="Hero", position=(100.0, 100.0), size=(64, 64))

# Layer: the actual pixel data + per-pixel struct buffer
layer = se.Layer.blank(64, 64, name="Sprite")
asset.add_layer(layer)

scene.add(asset)          # triggers asset.on_create()
engine.load_scene(scene)
engine.run()
```

### Step 4 — Load a sprite from an image

```python
asset = se.Asset.from_image("art/hero.png", name="Hero")
# Layer is created automatically; asset.size matches the image dimensions
scene.add(asset)
```

### Step 5 — Run tests

```bash
# _core must be built first
maturin develop
pytest tests/
```

---

## 4. Key Concepts

### Entity → Asset → Layer → Pixels

Everything visible on screen is an `Entity`. The most common concrete subclass is `Asset`, which extends `RenderTarget` and owns an ordered list of `Layer` objects.

```
Entity          (python/slappyengine/entity.py)
 └── RenderTarget  (render_target.py)
      └── Asset     (asset.py)
           └── Layer  (layer.py)   ←  visual_texture (wgpu) + data_buffer (wgpu)
```

A `Layer` carries two parallel data stores:

| Field | Type | Purpose |
|---|---|---|
| `_image_data` | `np.ndarray` (H×W×4 uint8) | Visual RGBA pixels |
| `_data_array` | `np.ndarray` (H×W×N float32) | Per-pixel struct fields |
| `visual_texture` | `wgpu.GPUTexture` | GPU-side colour texture |
| `data_buffer` | `wgpu.GPUBuffer` | GPU-side struct buffer |

The struct layout is defined at runtime via `StructRegistry` (see `python/slappyengine/struct_registry.py`). Fields like `health`, `temperature`, and `velocity` are read and written by WGSL compute shaders.

### Layer.mode — 2D vs 3D

Every `Layer` has a `mode` attribute that selects the render path:

- `mode = "2D"` (default) — rendered as a textured quad through `RenderPipeline` + `EntityRenderer`.
- `mode = "3D"` — rendered through `MeshPipeline` + `MeshRenderer` (lazy-created on first use, requires the `[3d]` extra at build time). The resulting offscreen texture is blitted onto the frame after the 2D pass completes.

The mode can be changed at runtime; the engine checks it every frame in the draw loop (`engine.py`, `_draw` callback).

### LightingContext per-layer

`LightingSystem` (wired into `engine._lighting`) maintains separate accumulation buffers per layer. Lights registered via `engine.lighting.add(light)` contribute to the accumulation pass. The combine shader (`shaders/lighting_combine.wgsl`) multiplies the scene texture by `(ambient + accumulated)` then blits the result.

Key light types in `python/slappyengine/lighting.py`:

| Class | Description |
|---|---|
| `DirectionalLight` | Parallel sun/moon with Z-height shadow offset |
| `PointLight` | Radial with Z attenuation |
| `ConeLight` | Spotlight / vehicle headlight |
| `FlashLight` | Short-lived burst (muzzle flash, explosion); auto-expired |
| `ShapeLight` | Mask-texture-shaped light |

Clustered lighting (`config/engine.yml → lighting.clustered_lighting: true`) tiles the screen into 8×8 pixel clusters and culls lights per tile before the accumulation passes.

Radiance cascades (`lighting.radiance_cascades: false` by default) can be enabled for global illumination approximation; the shader lives at `shaders/lighting_radiance_cascade.wgsl`.

### Config — no magic numbers in Python

All numeric defaults live in `config/engine.yml`. Reading them uses the singleton loader:

```python
from slappyengine.config import engine_config

cfg = engine_config()           # returns the cached Config object
print(cfg.window.width)         # 800
print(cfg.physics.default_dt)   # 0.016667
print(cfg.lighting.max_point_lights)  # 16
```

The typed dataclass hierarchy is defined in `python/slappyengine/config.py`:
`WindowConfig`, `RenderingConfig`, `ResidencyConfig`, `ComputeConfig`, `PhysicsConfig`, `LightingConfig`, `FluidSimConfig`, `NetConfig`, and more.

You can override individual window settings when constructing the engine:

```python
engine = se.Engine(width=1280, height=720, title="My Game")
```

Or point at an alternate config file:

```python
engine = se.Engine(config_path="config/my_project.yml")
```

### Materials — color → behavior

`config/materials.yml` maps color ranges to `MaterialDef` entries (name, density, tags, pixel-physics behavior). The compute shader `shaders/material_dispatch.wgsl` runs each frame (configurable via `materials.dispatch_frequency`) and stamps per-pixel material tags into the data buffer based on pixel color.

```python
from slappyengine.config import load_materials_config

materials = load_materials_config()
```

### EventBus

Every `Scene` has a `bus: EventBus`. Entity lifecycle events (`entity:created`, `entity:destroyed`) are published automatically. Games can subscribe to custom events:

```python
scene.bus.subscribe("player:death", lambda **kw: print("Player died", kw))
scene.bus.publish("player:death", player_id=0)
```

---

## 5. Architecture Overview

### 2D Render Pipeline

```
Engine.run()
  └── canvas.request_draw(_draw)
        ├── EntityRenderer.render(scene, render_pass)
        │     └── for each Asset with visible layers:
        │           ├── TextureManager.upload(layer)   → wgpu.GPUTexture
        │           └── RenderPipeline.draw(quad)      → shaders/quad_vert.wgsl
        │                                                 shaders/quad_frag.wgsl
        │
        ├── EffectPipeline.dispatch_effects(asset)     → NodeMaterial WGSL
        ├── pixel_physics dispatch                     → shaders/pixel_physics.wgsl
        ├── CollisionWorld.dispatch_pixel_scan()
        ├── PostProcessExecutor.execute(chain)         → outline / blur / pixelate
        └── LightingSystem.dispatch(frame_tex)
              ├── cull_lights                          → lighting_cluster.wgsl
              ├── per-light accumulation passes        → lighting_point/cone/dir…
              ├── emission                             → lighting_emission.wgsl
              ├── combine                              → lighting_combine.wgsl
              └── fullscreen blit                     → fullscreen_blit.wgsl
```

Key GPU objects (all in `python/slappyengine/gpu/`):

- `GPUContext` (`context.py`) — wraps the wgpu device, queue, and surface. Call `ctx.create_encoder()`, `ctx.write_texture()`, `ctx.submit()`.
- `RenderPipeline` (`render_pipeline.py`) — creates and holds the `wgpu.GPURenderPipeline` for textured quads and texture-array quads. Built once via `pipeline.build()`.
- `EntityRenderer` (`entity_renderer.py`) — iterates visible entities each frame, uploads layers via `TextureManager`, and issues draw calls.
- `TextureManager` (`texture_manager.py`) — caches `wgpu.GPUTexture` objects keyed by `id(layer)`.
- `BufferManager` (`buffer_manager.py`) — creates and caches per-layer pixel struct buffers.

### Compute Pipeline

Compute shaders run through `ComputePass` (`python/slappyengine/compute/pipeline.py`):

```python
from slappyengine.compute.pipeline import ComputePass

pass_ = ComputePass.from_wgsl(Path("shaders/my_shader.wgsl"))
await asset.compute.dispatch(pass_)
```

`AssetComputeAPI` is wired to each `Asset` by the engine after GPU init. It provides:
- `dispatch(pass_or_name, **params)` — dispatch a named or inline compute pass
- `readback()` — copy data buffer back to CPU as numpy array

The `EffectPipeline` (`compute/effect.py`) manages node-material compute passes. Each `NodeMaterial` compiles to WGSL via `node_compiler.rs` in the Rust extension.

### 3D Render Pipeline

The 3D path is zero-overhead when unused — the engine only enters it when at least one `Layer(mode="3D")` exists in the scene.

```
Engine._draw()  [after 2D pass]
  └── for each Layer(mode="3D"):
        Engine._draw_3d_layer_to_texture(layer, w, h)
          ├── MeshPipeline (lazy-created once per engine)    → mesh_pipeline.py
          │     └── shaders/mesh_vert_3d.wgsl + mesh_frag_pbr.wgsl
          ├── MeshRenderer (lazy-created once per layer)     → mesh_renderer.py
          │     ├── renderer.set_mesh(layer.mesh_geometry)
          │     └── renderer.render_to_texture(w, h)
          └── blit offscreen texture → swapchain via copy_texture_to_texture
```

To place 3D geometry on a layer:

```python
from slappyengine.gpu.mesh import MeshGeometry
from slappyengine.gpu.pbr_material import PbrMaterial

layer = se.Layer(name="3D Layer", mode="3D")
layer.mesh_geometry = MeshGeometry(vertices=..., indices=...)
layer.mesh_material  = PbrMaterial(base_color=(0.8, 0.2, 0.1, 1.0))
asset.add_layer(layer)
```

Build the 3D Rust extension:

```bash
maturin develop --features 3d
```

`src/math_3d.rs` (guarded with `#[cfg(feature = "3d")]`) exposes Vec3 and Mat4 to Python.

### Rust _core Extension

`src/lib.rs` registers these modules into `slappyengine._core`:

| Module | File | What it provides |
|---|---|---|
| `math` | `math.rs` | `Vec2`, `AABB`, ray-cast, `clamp_to_aabb` |
| `math_3d` | `math_3d.rs` | `Vec3`, `Mat4` (3d feature only) |
| `ik_solver` | `ik_solver.rs` | FABRIK IK chain solver (used by `ProceduralRig`) |
| `hull` | `hull.rs` | Convex hull, point-in-polygon |
| `node_compiler` | `node_compiler.rs` | `NodeMaterial` → WGSL source |
| `slap_format` | `slap_format.rs` | .slap binary helpers |
| `struct_layout` | `struct_layout.rs` | Pixel struct byte-offset calculator |
| `tile_cache` | `tile_cache.rs` | Streaming tile cache for `ResidencyManager` |

The import is guarded in `__init__.py`:

```python
try:
    from slappyengine import _core
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False
```

Pure-Python fallbacks exist for all critical paths so tests can run without the Rust build step (though performance will differ).

### Asset Residency

`ResidencyManager` (`python/slappyengine/residency/manager.py`) promotes and demotes assets through three tiers each frame based on camera distance:

```
disk  →  RAM (decompress .slap)  →  VRAM (upload to GPU)
                                         ↑
                              streaming_radius_gpu (config)
```

Budget thresholds in `config/engine.yml`:
- `residency.vram_budget_mb` — default 512 MB
- `residency.ram_budget_mb` — default 2048 MB
- `residency.streaming_radius_gpu` — default 500 world units

The `.slap` format (`residency/slap_format.py`) packs visual PNG + LZ4-compressed struct data into a single binary file. Magic bytes: `SLAP`, version 1.

### Fluid Simulation

The Navier-Stokes fluid sim runs entirely on the GPU across four compute shaders:

| Shader | Purpose |
|---|---|
| `fluid_noise_init.wgsl` | Initialize density field with FBM/Worley/uniform noise |
| `fluid_sim_advect.wgsl` | Semi-Lagrangian advection |
| `fluid_project.wgsl` | Pressure projection (divergence-free constraint) |
| `fluid_render.wgsl` | Density → RGBA with god-rays and tint |

Enable it via:

```python
from slappyengine import FluidSimConfig

engine.enable_fluid_sim(FluidSimConfig(
    viscosity=0.05,
    god_rays=True,
    render_tint=(0.8, 0.9, 1.0),
))
```

All numeric knobs live in `config/engine.yml → fluid_sim`.

### P2P Networking

`GameSession` (`python/slappyengine/net/session.py`) implements lock-step multiplayer. Peer discovery uses LAN broadcast (zeroconf) and a DHT (kademlia) for internet play. Room codes are 6-character alphanumeric strings generated by `RoomCode` (`net/room.py`).

```python
# Host
session = await engine.host_game(player_id=0)
print(session.room_code)   # e.g. "X7K2MQ"

# Join
session = await engine.join_game("X7K2MQ", player_id=1)

# Per tick
from slappyengine.net.sync import InputFrame
frame = InputFrame(tick=session.sync.tick, player_id=0,
                   actions={"fire": True}, axes={"move_x": 0.5})
all_inputs = await session.sync.tick_async(frame, session.broadcast)
```

Requires the `[network]` extra: `pip install slappyengine[network]`.

### Post-Processing

`PostProcessChain` (`python/slappyengine/post_process/chain.py`) holds an ordered list of `PostProcessPass` objects. Factory helpers are defined at the top level of the package:

```python
scene.post_process = [
    se.OutlinePass(color=(1.0, 0.0, 0.0, 1.0), threshold=0.1),
    se.BlurPass(radius=2),
    se.PixelatePass(block_size=4),
]
```

Each pass references a WGSL shader by name in `shaders/`. `PostProcessExecutor` dispatches the chain after the main render pass each frame.

### Spatial Audio

`AudioManager` is wired into `engine._audio` after `run()`. It wraps `sounddevice` + `soundfile`. Entities with `z_height` participate in 3D spatial panning. Requires the `[audio]` extra.

### IK Animation

`ProceduralRig` (`animation/procedural.py`) wraps the FABRIK solver from `src/ik_solver.rs`. Define a chain of `ControlPoint` objects; call `rig.solve(target_position)` each tick.

`AnimationGraph` (`animation/graph.py`) drives frame-based sprite animation. Define `AnimState` objects (frame indices, FPS, loop), connect them with `AnimTransition` (condition lambdas), then call `graph.update(dt)` each tick to get an `AnimUpdate`.

---

## 6. Build Reference

### Development build (2D only)

```bash
maturin develop
```

Compiles `src/` into `python/slappyengine/_core.pyd` (Windows) or `_core.so` (Linux/macOS) and installs the package in editable mode.

### Development build with 3D

```bash
maturin develop --features 3d
```

Activates `#[cfg(feature = "3d")]` blocks in `src/lib.rs` and `src/math_3d.rs`. The Python `[3d]` extra itself has no additional Python packages — the wgpu dependency is already in core.

### Release wheel

```bash
maturin build --release
maturin build --release --features 3d   # for the [3d] wheel
```

Wheels are emitted to `target/wheels/`.

### Run tests

```bash
# Must have _core built first
pytest tests/

# A single file
pytest tests/test_animation.py -v

# Skip GPU-heavy tests in headless CI
pytest tests/ -k "not gpu_headless"
```

Test files of interest for new contributors:
- `tests/test_basic.py` — Entity, Scene, Asset smoke tests
- `tests/test_material.py` — MaterialMap + ColorRange
- `tests/test_animation.py` — AnimationGraph state machine
- `tests/test_ik.py` — ProceduralRig + Rust IK solver
- `tests/test_residency.py` — .slap round-trip
- `tests/test_mixed_2d_3d.py` — 2D/3D layer coexistence

---

## 7. Adding a New Game

### Step 1 — Create a project directory

```
my_game/
├── main.py
├── project.slap_proj      # metadata (name, entry scene, etc.)
├── scenes/
│   └── level_1.py
├── assets/
│   └── hero.png
└── config/
    └── engine.yml         # override defaults for this game only
```

### Step 2 — Implement your scene

A scene is any class that sets up entities and hands itself to the engine. SlapPyEngine does not enforce a base class for scenes beyond `se.Scene`, but the recommended pattern is to subclass:

```python
# scenes/level_1.py
import slappyengine as se

class Level1(se.Scene):
    def __init__(self):
        super().__init__(name="Level1")

    def on_create(self):
        """Called once when the scene is first loaded."""
        hero = se.Asset.from_image("assets/hero.png", name="Hero")
        hero.position = (400.0, 300.0)
        self.add(hero)

        sun = se.DirectionalLight(
            direction=(0.707, 0.707),
            elevation=0.785,
            intensity=1.2,
        )
        self.bus.publish("light:add", light=sun)
```

### Step 3 — Wire the engine

```python
# main.py
import slappyengine as se
from scenes.level_1 import Level1

engine = se.Engine(config_path="config/engine.yml")
scene  = Level1()
scene.on_create()
engine.load_scene(scene)
engine.run()
```

### Step 4 — Script-based behavior

Attach scripts (plain Python objects with lifecycle hooks) to entities instead of subclassing:

```python
class HeroScript:
    def on_spawn(self, entity):
        entity.tags.add("player")

    def on_tick(self, entity, dt: float):
        # move right
        x, y = entity.position
        entity.position = (x + 100.0 * dt, y)

    def on_action(self, action: str, player_id: int, pressed: bool):
        if action == "jump" and pressed:
            ...  # apply impulse

hero._scripts.append(HeroScript())
```

Scripts receive `on_action` calls when keyboard events are routed through an `ActionMap`:

```python
from slappyengine.input import ActionMap
engine.add_player(ActionMap.wasd(player_id=0))
```

---

## 8. Editor Usage

### Launch

```bash
python -m slappyengine.ui.editor
```

Or from Python:

```python
engine = se.Engine()
engine.load_scene(scene)
engine.run_editor()   # DPG-driven loop instead of wgpu loop
```

Requires `pip install slappyengine[editor]`.

### Layout

The editor is built from `EditorShell` (`python/slappyengine/ui/editor/shell.py`) with a fixed four-zone DearPyGui layout:

```
┌─────────────────────────────────────────────────────┐
│  Toolbar (h=36)  [2D] [3D] | ▶ Play  ■ Stop  …     │
├──────────────────┬──────────────────┬────────────────┤
│  Scene Outliner  │                  │   Properties   │
│  (w=200)         │   Viewport       │   Inspector    │
│                  │   (wgpu canvas)  │   (w=300)      │
│  Layer Panel     │                  │   Material Ed. │
│  (below)         │                  │   Tag Painter  │
├──────────────────┴──────────────────┴────────────────┤
│  Content Browser (h=220)  [project file tree]        │
└─────────────────────────────────────────────────────┘
```

### Key panels and their source files

| Panel | File | Purpose |
|---|---|---|
| `EditorToolbar` | `toolbar.py` | 2D/3D mode toggle, play/stop, scene selector |
| `SceneOutliner` | `scene_outliner.py` | Entity tree; selection drives GizmoOverlay |
| `ViewportPanel` | `viewport_panel.py` | Live wgpu render inside a DPG texture widget |
| `PropertyInspector` | `property_inspector.py` | Selected entity fields |
| `LayerPanel` | `layer_panel.py` | Layer list; 2D/3D radio per layer |
| `LayerLightingPanel` | `layer_lighting_panel.py` | Per-layer ambient/light config |
| `MaterialEditor` | `material_editor.py` | Node graph for `NodeMaterial` |
| `NodeGraphPanel` | `node_graph_panel.py` | Interactive node connections |
| `AnimGraphPanel` | `anim_graph_panel.py` | `AnimationGraph` state machine view |
| `GizmoOverlay` | `gizmo_overlay.py` | Translate/rotate/scale handles in viewport |
| `CodeModePanel` | `code_mode_panel.py` | Script editor with file-watch refresh |
| `ContentBrowser` | `content_browser.py` | Project file tree; double-click opens in CodeMode |
| `TagPainter` | `tag_painter.py` | Paint pixel tags onto layers |
| `MeshInspector` | `mesh_inspector.py` | 3D layer geometry + PBR material |
| `BehaviorPanel` | `behavior_panel.py` | AI-assisted scripting (requires `[ai]` extra) |

### 2D/3D mode toggle

The toolbar exposes a global 2D/3D mode flag (`EditorShell._editor_mode`). When set to `"3D"`:
- `MeshInspector` and `LayerLightingPanel` panels appear in the right column.
- `LayerPanel` exposes per-layer 2D/3D radio buttons.
- The viewport continues to render the full scene (both 2D and 3D layers coexist).

Setting a single layer to 3D mode in the `LayerPanel` writes `layer.mode = "3D"` directly; the engine picks it up on the next frame.

### Theme

The editor uses the Nova3D dark theme defined in `python/slappyengine/ui/editor/theme.py`. Colors and font sizes are set via DearPyGui theme APIs at editor startup inside `EditorShell.setup()`.

---

## 9. Common Gotchas

**`_core` import fails after editing Rust source**
You must re-run `maturin develop` after any change to `src/*.rs`. The Python import of `slappyengine._core` will silently degrade to `HAS_NATIVE = False` if the old .pyd/.so is missing or stale.

**Magic numbers in Python PRs**
Any numeric literal that represents a tunable value belongs in `config/engine.yml`, not in Python source. PRs that hardcode physics constants, timeout values, or pixel counts will be flagged in review.

**Shader path discovery**
Shaders are resolved relative to the Python package root at runtime. The pattern used throughout the codebase is:

```python
_SHADER_DIR = Path(__file__).parent.parent.parent / "shaders"
```

Adjust the number of `.parent` steps depending on how deep the calling module is.

**wgpu backend selection**
`config/engine.yml → rendering.backend: "auto"` lets wgpu pick the best available adapter. Force a specific backend by setting it to `"vulkan"`, `"metal"`, `"dx12"`, or `"webgpu"` for debugging.

**Fluid sim before `run()`**
`engine.enable_fluid_sim()` can be called before or after `run()`. If called before, the GPU is not yet available; the engine lazy-initializes it inside `_setup_gpu()`. Do not call `fluid_sim.dispatch()` manually before the engine loop starts.

**Async networking in a sync loop**
`GameSession` methods are all `async`. From a wgpu draw callback (which is synchronous), drive them with `asyncio.get_event_loop().run_until_complete()`, or restructure your game loop to run inside `asyncio.run()`.

---

## 10. Where to Go Next

| Goal | Start here |
|---|---|
| Understand GPU resource flow | `python/slappyengine/gpu/context.py` |
| Write a custom compute effect | `python/slappyengine/compute/pipeline.py` + any shader in `shaders/` |
| Add a new light type | `python/slappyengine/lighting.py` + new `.wgsl` in `shaders/` |
| Add a new material node | `src/node_compiler.rs` + `python/slappyengine/material/node_material.py` |
| Extend the editor with a panel | `python/slappyengine/ui/editor/shell.py` — implement `build(parent_tag)` |
| Add a new config key | `config/engine.yml` + matching dataclass field in `python/slappyengine/config.py` |
| Profile the render loop | Set `rendering.backend: "vulkan"` and use RenderDoc or PIX |
| Understand the `.slap` format | `python/slappyengine/residency/slap_format.py` + `src/slap_format.rs` |
