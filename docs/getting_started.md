# SlapPyEngine — Getting Started

A friendly tour that takes you from `pip install slappy-engine` (v0.3.0b0
at time of writing) to a running mini-game in 15 minutes. For deeper docs
see [studio_quickstart.md](studio_quickstart.md) (5-min `studio` tour),
[dynamics_quickstart.md](dynamics_quickstart.md) (10-min physics tour),
[demo_gallery.md](demo_gallery.md) (curated showcase),
[dynamics_design.md](dynamics_design.md), and
[engine_surface_v030.md](engine_surface_v030.md).

This guide walks the v0.3 public surface: a Rust-accelerated physics core, a
Python wrapper for ergonomics, and a few opt-in GPU subsystems. Most snippets
on this page are headless — they run without opening a window so you can paste
them into a REPL or pytest. The "Hello, sprite" block lights up a wgpu canvas
when you have the `[render]` extra installed.

## 1. Install

```bash
pip install slappy-engine
```

That gives you the headless engine: dynamics, zones, telemetry, materials,
serialisation, the CLI scaffolder, and the audio stub. To turn on the GPU
renderer, audio output, and editor UI, install the extras you want:

```bash
pip install "slappy-engine[render]"   # wgpu canvas + post-process chain
pip install "slappy-engine[audio]"    # sounddevice + soundfile playback
pip install "slappy-engine[editor]"   # Dear PyGui in-tree editor
```

Smoke-test the install:

```python
import slappyengine as se

print("slappyengine", se.__version__)
print("native Rust core available:", se.HAS_NATIVE)
```

If `HAS_NATIVE` prints `False`, the Python fallback paths still run — the
engine is just slower. See [rust_port_plan_dynamics.md](rust_port_plan_dynamics.md)
for what gets accelerated.

## 2. Hello, sprite

The engine's core trio is `Engine`, `Scene`, and `Entity`. An `Entity` holds a
position and a list of `Layer`s; a `Scene` owns the entities; an `Engine` owns
the GPU and ticks the scene each frame. Layers are the actual texels you see:
`Layer2D(width, height)` gives you a numpy-backed RGBA buffer you can paint
into before the first frame draws.

```python
import numpy as np
import slappyengine as se

# 1. Build a scene with one camera-centred sprite.
scene = se.Scene(name="hello")
sprite = se.Asset(name="player", position=(0.0, 0.0), size=(64, 64))

# 2. Paint a solid 64x64 magenta square into the visual layer.
layer = se.Layer2D(name="body", width=64, height=64)
layer._image_data[:] = np.array([255, 0, 200, 255], dtype=np.uint8)
sprite.add_layer(layer)

scene.add(sprite)
print(f"scene has {len(scene)} entity, layer pixel sum = {int(layer._image_data.sum())}")

# 3. Wire it to an Engine. engine.run() blocks on a wgpu canvas;
#    skip the run() call when you only want to verify scene wiring.
engine = se.Engine(width=640, height=360, title="hello sprite")
engine.load_scene(scene)
# engine.run()   # <-- uncomment when you have the [render] extra installed
```

The `Engine(**overrides)` kwargs forward to `engine.yml`'s `window` block — see
the [engine_surface_v030.md](engine_surface_v030.md) Core table for the full
constructor signature. The `Asset` you just added subclasses
`RenderTarget`, which subclasses `Entity`; everything in
[engine_surface_v030.md](engine_surface_v030.md) (Layers, Entities, Components)
plugs into the same `Scene`.

## 3. Add physics

`slappyengine.dynamics` is the unified physics layer: a single `World` holds
nodes, joints, and bodies, and every primitive (rope, ragdoll, spring, motor,
ik chain) writes into the same arrays. It runs without a GPU. The snippet
below drops a 24-bead rope between two anchors and lets gravity pull it into
a catenary.

```python
from slappyengine.dynamics import RopeSpec, World, build_rope

world = World(gravity=(0.0, -9.81))
world.solver_iterations = 16

spec = RopeSpec(
    node_count=24,
    total_length=6.0,         # 50 percent slack across the 4.0-unit span
    mass_per_node=0.05,
    stiffness=2.0e6,
    damping=0.08,
    anchor_a_pinned=True,
    anchor_b_pinned=True,
)
body = build_rope(spec, world, anchor_a=(-2.0, 2.0), anchor_b=(2.0, 2.0))

for _ in range(120):
    world.step(1.0 / 60.0)

mid = body.node_offset + body.node_count // 2
print(f"rope midpoint y after 2s: {float(world.positions[mid, 1]):.3f}")
```

`world.positions` is a `(N, 2)` numpy array — the renderer just reads it
each frame, so any drawer (PIL, pygame, wgpu) can visualise it. For more
primitives (ragdoll, IK, spring, motor, full vehicle), see
[dynamics_quickstart.md](dynamics_quickstart.md) and the per-subpackage API
ref at [api/dynamics.md](api/dynamics.md).

## 4. Listen for events

The engine ships two pub/sub pipelines:

- `slappyengine.zones` — spatial triggers. Register `RectZone` or
  `ThresholdZone` with a `ZoneManager`; call `update()` each frame with the
  latest entity positions, and `on_enter` / `on_exit` / `on_threshold`
  callbacks fire. The manager uses a uniform-grid spatial hash by default —
  see [api/zones.md](api/zones.md).
- `slappyengine.telemetry` — name-based events. `emit("physics.step", ...)`
  publishes, `subscribe("physics.*", cb)` listens via fnmatch glob patterns,
  and a ring buffer remembers the last N events for post-mortem queries.
  See [api/telemetry.md](api/telemetry.md).

```python
from slappyengine import telemetry
from slappyengine.zones import RectZone, ZoneManager

# --- Spatial: fire when the player walks into a 4x4 pad at (0, 0). ---
entered = []
pad = RectZone(name="pickup", x=0.0, y=0.0, w=4.0, h=4.0,
               on_enter=lambda eid: entered.append(eid))
mgr = ZoneManager()
mgr.add(pad)

# Frame 1: player outside the pad.
mgr.update({"player": (10.0, 10.0)})
# Frame 2: player inside the pad -> on_enter fires.
mgr.update({"player": (2.0, 2.0)})

print(f"zone entrances: {entered}")          # ['player']
print(f"current occupancy: {mgr.occupancy('pickup')}")

# --- Named: subscribe to any physics.* event. ---
heard = []
handle = telemetry.subscribe("physics.*", lambda ev: heard.append(ev.name))
telemetry.emit("physics.step", dt=1/60)
telemetry.emit("physics.collision", entity_a="player", entity_b="wall")
telemetry.emit("render.frame", index=42)     # different namespace, ignored

telemetry.unsubscribe(handle)
print(f"physics events heard: {heard}")
```

The Scene also exposes a synchronous `EventBus` at `scene.bus` (alias
`scene.events`) for `entity:created` / `entity:destroyed` / `collision`
notifications — handy when one entity needs to react to another's lifecycle.

## 5. Render with post-processing

`PostProcessChain` is an ordered list of compute passes the engine runs every
frame after the main scene draw. Each `add_*` helper appends a tagged
`PostProcessPass` you can later toggle, remove, or look up by label. Bloom is
its own `BloomPass` class (Lottes 2017 smooth-knee) that emits a `PostProcessPass`
via `make_pass()`.

```python
from slappyengine import PostProcessChain
from slappyengine.post_process.bloom import BloomPass

chain = PostProcessChain()
chain.add(BloomPass(threshold=1.0, knee=0.2, intensity=1.0).make_pass())
chain.add_vignette(strength=1.2, inner_radius=0.4, feather=0.25)
chain.add_tonemap(exposure_ev=0.0, saturation=1.05, contrast=1.05)

print(f"{len(chain.passes)} enabled passes: "
      f"{[p.label for p in chain.passes]}")

# Hand the chain to the engine by stashing it on the scene; the engine
# picks it up automatically in run() when scene.post_process is non-empty.
import slappyengine as se
scene = se.Scene(name="lit")
scene.post_process = list(chain.passes)
print(f"scene wired with {len(scene.post_process)} post-process passes")
```

For the deep-dive (auto-exposure, GTAO, motion blur, depth-of-field, TAA,
SSR, volumetric fog, CSM shadows) see the rest of `slappyengine.post_process`
in [engine_surface_v030.md](engine_surface_v030.md). The dynamic chain helpers
(`add_outline`, `add_chromatic_aberration`, `add_night_vision`, etc.) all
live on `PostProcessChain` itself.

## 6. Polish: audio, save state, performance

### Audio

Audio is exposed as `engine.audio` (an `AudioManager`) after `engine.run()`
sets up the device. Without the `[audio]` extra installed it falls back to a
silent stub backend — your game still launches, it just ships muted. The
backend abstraction lives in `slappyengine.audio_runtime`.

```python
from slappyengine.audio import AudioManager
from slappyengine import audio_runtime

audio = AudioManager()
print(f"audio backend available: {audio.available}")
print(f"backend.is_real(): {audio_runtime.get_backend().is_real()}")

# When you have a .wav on disk and the [audio] extra installed:
#   handle = audio.load("assets/audio/jump.wav")
#   audio.play(handle, volume=0.8)
```

### Save state

Round-trip a `dynamics.World` to JSON. `save_world` enforces a `.json`
suffix; `load_world` reproduces the world to machine precision per the
[determinism contract](dynamics_design.md).

```python
import tempfile
from pathlib import Path
from slappyengine.dynamics import World
from slappyengine.dynamics.serialize import save_world, load_world

world = World(gravity=(0.0, -9.81))
a = world.add_node((0.0, 0.0), mass=1.0)
b = world.add_node((1.0, 0.0), mass=1.0)
world.step(1.0 / 60.0)

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "save.json"
    save_world(world, path)
    restored = load_world(path)
    print(f"restored {len(restored.positions)} nodes from {path.name}")
    print(f"position[a] match: "
          f"{tuple(world.positions[a]) == tuple(restored.positions[a])}")
```

### Performance

Two free wins for any non-trivial scene:

```python
from slappyengine import telemetry
from slappyengine.zones import RectZone, ZoneManager

# 1. ZoneManager spatial hash — on by default since v0.3, but you can
#    confirm and toggle it for parity tests.
mgr = ZoneManager()
mgr.add(RectZone(name="z", x=0, y=0, w=10, h=10))
print(f"spatial hash enabled: {mgr.spatial_hash_enabled}")
mgr.enable_spatial_hash(True)   # idempotent

# 2. Telemetry pattern index — O(matching) dispatch instead of O(all).
#    Opt-in because it changes cross-bucket subscriber ordering.
telemetry.enable_pattern_index(True)
print(f"pattern index on: {telemetry.is_pattern_index_enabled()}")
telemetry.enable_pattern_index(False)   # tidy up after the smoke test
```

For benchmark numbers (current best: dynamics 100-node lattice 12 ms/frame
Python-bound) see [perf_dashboard.md](perf_dashboard.md). The Rust port plan
that shrinks them further is in [rust_port_plan_dynamics.md](rust_port_plan_dynamics.md).

## 7. Next steps

- [dynamics_quickstart.md](dynamics_quickstart.md) — 10-minute hands-on tour
  of every dynamics primitive (rope, ragdoll, spring, motor, IK chain) with
  copy-paste snippets that produce GIFs.
- [studio_quickstart.md](studio_quickstart.md) — 5-minute tour of
  `slappyengine.studio` (`softbody_stage` / `fluid_stage` / `humanoid_stage`
  / `dynamics_stage` / `record(...)`). The shortest path from `import` to
  rendered GIF.
- [demo_gallery.md](demo_gallery.md) — curated tour of flagship demos with
  the exact `PYTHONPATH=python python examples/...` command for each. Every
  artefact is checked in so the gallery renders on GitHub without a local
  install.
- [examples/](../examples/) — every `hello_*.py` demo wired through
  `slappyengine.examples_common` (`--frames`, `--no-gif`, `--out`, `--seed`):
  rope, ragdoll, IK, joint, spring, motor, thermal, zone, telemetry,
  lighting, physics, pixel-physics, iso, topology, audio, composite, studio,
  GI, and the humanoid walking / IK-terrain demos.
- [api/dynamics.md](api/dynamics.md), [api/studio.md](api/studio.md),
  [api/zones.md](api/zones.md), [api/telemetry.md](api/telemetry.md),
  [api/thermal.md](api/thermal.md), [api/iso.md](api/iso.md),
  [api/numerics.md](api/numerics.md), [api/testing.md](api/testing.md),
  [api/tools.md](api/tools.md), [api/topology.md](api/topology.md) —
  per-subpackage signatures + Raises.
- [dynamics_design.md](dynamics_design.md) — when to pick which primitive,
  numerical stability notes, determinism contract.
- [rust_port_plan_dynamics.md](rust_port_plan_dynamics.md) — what is already
  Rust-accelerated and what is on deck.
- [perf_dashboard.md](perf_dashboard.md) — current benchmark numbers for
  the six instrumented subsystems.
- [engine_surface_v030.md](engine_surface_v030.md) — the full v0.3 contract:
  every name in `__all__`, every declared subpackage, every signature.

## Where to ask for help

If something here drifts from `master` HEAD — wrong kwarg, missing symbol,
broken link — please open an issue on the GitHub repo so we can patch the
tripwire test that should have caught it. Patches welcome; the doc lives
at `docs/getting_started.md` and is gated by `tests/test_docs_getting_started.py`.
