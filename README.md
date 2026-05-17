# SlapPyEngine

**2D pixel-art game engine with optional 3D layers, Rust backends, and wgpu rendering.**

Build fast, expressive games in Python — from classic pixel-art shooters to hybrid 2D/3D worlds — backed by a high-performance Rust core and cross-platform GPU rendering via wgpu.

---

## Features

- **2D pixel-art pipeline** — per-tile compute shaders, sprite batching, palette swapping, and atlas packing
- **Optional 3D layers** — PBR mesh rendering composited over the 2D scene (`pip install slappyengine[3d]`)
- **Per-layer lighting** — independent ambient, point, and directional lights on each scene layer
- **Cross-platform GPU** — wgpu backend targets Vulkan, Metal, and DirectX 12 from a single code path
- **Rust `_core` backend** — performance-critical subsystems (asset I/O, LZ4 compression, physics) compiled via PyO3/maturin
- **DearPyGui editor** — Nova3D dark-themed in-engine editor with toolbar, gizmos, and Code Mode (`pip install slappyengine[editor]`)
- **P2P networking** — Kademlia DHT + ICE hole-punching for low-latency peer-to-peer multiplayer (`pip install slappyengine[network]`)
- **Spatial audio** — positional audio with rolloff curves (`pip install slappyengine[audio]`)

---

## Install

```bash
# Core engine (2D only)
pip install slappyengine

# With 3D layer support
pip install slappyengine[3d]

# Full stack: editor, networking, audio, video
pip install slappyengine[editor,network,audio,video]
```

Requires Python 3.11+ and a GPU driver that supports Vulkan, Metal, or DirectX 12.

---

## Quick Start

```python
import slappyengine as sle

engine = sle.Engine(title="My Game", width=640, height=360)

# Create a blank 2D pixel layer
layer = engine.add_layer("world", sle.Layer2D(tile_size=16))

# Load a sprite sheet and place a sprite
sheet = engine.assets.load_sprite_sheet("player.png", tile_w=16, tile_h=16)
player = layer.spawn_sprite(sheet, tile=0, x=160, y=90)

engine.run()
```

---

## Architecture

### 2D Pipeline

Each `Layer2D` is a WGSL compute pass. Tiles are packed into a GPU buffer; per-frame dispatch updates transforms, palette swaps, and lighting before a single textured quad draw call flattens the layer to a render texture.

### 3D Pipeline (optional)

`Layer3D` instances sit above or below 2D layers in the compositor stack. PBR meshes are rendered to their own MSAA texture, then alpha-composited with the 2D render texture during the final blit pass. Enable at build time with `maturin build --features 3d`.

### Cross-Layer Baking

The compositor (`slappyengine.compose`) resolves layer order, blending modes, and shared lighting probes into a single swap-chain frame. Baked lightmaps are stored in `.slap` asset bundles (LZ4-compressed, built by the Rust core).

### Rust `_core`

The `slappyengine._core` extension module (compiled via PyO3 + maturin) provides:

| Module | Responsibility |
|---|---|
| `_core.assets` | LZ4 asset bundle read/write |
| `_core.physics` | Broad-phase collision (rayon parallel) |
| `_core.audio` | Spatial audio mixer |
| `_core.net` | ICE/STUN hole-punching helpers |

---

## Making Your Game

### 1 — Scaffold a new project

```bash
slap new MyGame
cd MyGame
slap run
```

This creates a ready-to-run project with `Content/`, `Source/`, `Config/`, and `Builds/` folders plus platform build scripts (`Build_EXE.bat`, `Build_Web.bat`, `Build_APK.bat`).

### 2 — Add a scene

```python
# Source/scenes/level1.py
import slappyengine as se

class Level1(se.Scene):
    def on_create(self):
        hero = se.Asset.from_image("Content/Assets/sprites/hero.png", name="Hero")
        hero.position = (400.0, 300.0)
        self.add(hero)

        self.lighting.add(se.DirectionalLight(direction=(0.707, 0.707), intensity=1.2))
```

### 3 — Wire player input

```python
from slappyengine.input import ActionMap

engine.add_player(ActionMap.wasd(player_id=0))
# Scripts receive on_action(action, player_id, pressed) calls automatically
```

### 4 — Add physics

```python
from slappyengine import PhysicsComponent, CollisionComponent, AABBShape

hero.add_component(PhysicsComponent(gravity_scale=1.0))
hero.add_component(CollisionComponent(shape=AABBShape(32, 48)))
```

### 5 — Script behaviour

```python
from slappyengine.script import Script

class EnemyAI(Script):
    def on_update(self, entity, dt):
        entity.position = (entity.position[0] - 60 * dt, entity.position[1])

enemy.attach_script(EnemyAI())
```

### 6 — Build and ship

```bash
slap build --target=exe      # Windows EXE via PyInstaller
slap build --target=web      # Browser (Pyodide + WebGPU)
slap build --target=apk      # Android APK via Buildozer
```

---

## Build from Source

> Requires: Rust toolchain (stable), Python 3.11+, maturin

```bash
# Clone
git clone https://github.com/andrewkwatts-maker/SlapPyEngine
cd SlapPyEngine

# Install maturin
pip install maturin

# Editable dev install (debug Rust build)
maturin develop --extras dev

# Run tests
pytest tests/

# Release wheel
maturin build --release

# Release wheel with 3D support
maturin build --release --features 3d
```

**Windows note:** If maturin fails to locate Python, set `PYO3_PYTHON` explicitly:

```powershell
$env:PYO3_PYTHON = "C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe"
maturin develop --extras dev
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
