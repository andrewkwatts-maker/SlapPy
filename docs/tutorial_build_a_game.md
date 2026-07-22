# Tutorial — Build a Top-Down Arcade Game

By the end of this tutorial you will have built a complete 2-minute arcade
game: a rocket dodging asteroids, with physics-driven movement, collision
detection, a score system, audio, and save/load. Time investment: 45-60
minutes.

Prerequisites: read [getting_started.md](getting_started.md) first.

## 1. Project layout

Create a tiny project alongside the engine source tree:

```text
my_rocket_game/
├── pyproject.toml
├── engine.yml          # optional config overrides
├── assets/
└── src/
    └── rocket/
        ├── __init__.py
        ├── main.py
        └── scenes.py
```

In `pyproject.toml` declare `pharos-engine` as a dependency. Bare minimum:

```toml
[project]
name = "rocket"
version = "0.1.0"
dependencies = ["pharos-engine"]
```

## 2. Spawning the rocket

The rocket is one dynamics body: a single node with mass, plus a Component
that translates input into velocity. Headless-safe snippet:

```python
import numpy as np
from pharos_engine.dynamics import World

world = World(gravity=(0.0, 0.0))
world.solver_iterations = 4
# One body = one node at origin, mass 1.0.
world.positions = np.array([[0.0, 0.0]], dtype=np.float32)
world.velocities = np.zeros_like(world.positions)
world.inv_masses = np.array([1.0], dtype=np.float32)
print("rocket spawned at", world.positions[0])
```

## 3. Adding asteroids

Spawn N asteroids as additional dynamics nodes that drift on a fixed
velocity:

```python
import numpy as np
from pharos_engine.dynamics import World

world = World(gravity=(0.0, 0.0))
world.solver_iterations = 4
# Rocket at index 0, then 10 asteroids in a ring.
n_asteroids = 10
positions = [[0.0, 0.0]]
velocities = [[0.0, 0.0]]
for i in range(n_asteroids):
    angle = 2 * np.pi * i / n_asteroids
    positions.append([8.0 * np.cos(angle), 8.0 * np.sin(angle)])
    velocities.append([-np.cos(angle) * 0.5, -np.sin(angle) * 0.5])
world.positions = np.array(positions, dtype=np.float32)
world.velocities = np.array(velocities, dtype=np.float32)
world.inv_masses = np.ones(len(positions), dtype=np.float32)
for _ in range(60):
    world.step(1.0 / 60.0)
print("after 1s, asteroid 1 is at", world.positions[1])
```

## 4. Collision

Use `pharos_engine.zones` to express the rocket's body as a trigger zone
that fires when an asteroid enters it:

```python
from pharos_engine.zones import RectZone, ZoneManager

hit_count = [0]
def on_hit(eid: object) -> None:
    hit_count[0] += 1

mgr = ZoneManager()
mgr.add(RectZone(
    name="rocket_body",
    x=-0.4, y=-0.4, w=0.8, h=0.8,
    on_enter=on_hit,
))
# Update with current asteroid positions every frame.
mgr.update({f"a{i}": (1.5 * (i % 3), 0.2 * i) for i in range(5)})
print("asteroid enters detected:", hit_count[0])
```

## 5. Score system

The engine's telemetry bus is the natural fit for game-event broadcasting.
Subscribe to a `score.changed` event and have collision callbacks publish:

```python
from pharos_engine import telemetry

events = []
telemetry.subscribe("score.*", lambda ev: events.append(ev.name))
telemetry.emit("score.changed", delta=10, total=10)
telemetry.emit("score.bonus", multiplier=2.0)
print("captured:", events)
```

## 6. HUD overlay

A SceneUIEntity is an entity whose layer carries text/widget pixels. Build
one and paint the score into its canvas with PIL:

```python
from pharos_engine.ui.scene_ui import SceneUIEntity

hud = SceneUIEntity(name="hud", position=(0, 0), size=(320, 60))
hud.set_text("SCORE: 0", "TIME: 00:00")
hud.set_text_color(255, 220, 30, 255)
print("hud size:", hud.size, "lines:", hud._text_lines)
```

## 7. Audio

`AudioManager` is the high-level API; it wraps the `audio_runtime` backend
which falls back to a silent stub when `sounddevice` isn't installed.

```python
from pharos_engine.audio import AudioManager

amgr = AudioManager()
print("audio backend available:", amgr.available)
# In a real game you'd load + play SFX here. Headless-safe path:
print("stubbed playback returns immediately")
```

## 8. Save / load

State serialization is JSON + base64. Round-trips byte-identically.

```python
from pathlib import Path
import tempfile
import numpy as np
from pharos_engine.dynamics import World
from pharos_engine.dynamics.serialize import save_world, load_world

world = World()
world.positions = np.array([[0.0, 1.0], [1.0, 2.0]], dtype=np.float32)
world.velocities = np.zeros_like(world.positions)
world.inv_masses = np.array([1.0, 1.0], dtype=np.float32)
with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
    path = Path(f.name)
save_world(world, path)
loaded = load_world(path)
print("round-trip max delta:",
      float(np.max(np.abs(world.positions - loaded.positions))))
```

## 9. Polish: lighting and post-process

The post-process chain composes named passes. v0.3 ships GTAO + Bloom +
TAA + Vignette + Outline + CA + AutoEV + DoF helpers — see
[engine_surface_v030.md](engine_surface_v030.md) for the full list.

```python
from pharos_engine.post_process.chain import PostProcessChain

chain = PostProcessChain()
chain.add_vignette(strength=0.6, inner_radius=0.4, feather=0.3)
chain.add_outline(threshold=0.2, softness=0.5, use_sobel=True)
chain.add_tonemap(exposure_ev=0.5, saturation=1.1, contrast=1.05)
print("post-process pass count:", len(chain.passes))
```

## 10. Performance: telemetry indexing + zones spatial hash

Both opt-in:

```python
from pharos_engine import telemetry
from pharos_engine.zones import ZoneManager

telemetry.enable_pattern_index(True)
mgr = ZoneManager()
assert mgr.spatial_hash_enabled is True
print("perf knobs on")
```

`ZoneManager.spatial_hash_enabled` defaults `True`. `telemetry.enable_pattern_index`
defaults `False` — turn it on once you have hundreds of subscribers.

## Where to take it next

- Add a wave-spawn system from `pharos_engine.iso.combat.WaveSchedule` —
  see [api/iso.md](api/iso.md).
- Add a ragdoll explosion via `pharos_engine.dynamics.RagdollSpec` — see
  [dynamics_quickstart.md](dynamics_quickstart.md).
- Profile with `tools/bench_dashboard.py` — see [perf_dashboard.md](perf_dashboard.md).
- Read [api/dynamics.md](api/dynamics.md), [api/zones.md](api/zones.md),
  [api/telemetry.md](api/telemetry.md) for full reference.
