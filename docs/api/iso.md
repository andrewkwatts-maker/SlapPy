<!-- handauthored: do not regenerate -->
# pharos_engine.iso — API Reference

> Hand-curated reference. Format mirrors the auto-generated subpackage
> dumps but extends them with the `combat` surface added by Sprint 1C
> (Phase C3 of *"editor polish + repackage proven subsystems"*). Stone
> Keep, the engine's iso flagship game, consumes these helpers for
> tower-defence wave + attack resolution.


## Overview

Pharos Engine.iso — Isometric 2D-grid-with-Z rendering subsystem.

## Rendering surface (summary)

The grid / camera / entity / scene types are stable and documented by
the auto-generated dump; the short version:

- `IsoViewpoint` — `IntEnum` of the four cardinal angles (`NE`, `NW`,
  `SW`, `SE`).
- `IsoTileDef(name, sprite_path, sprite_paths=…, z_height=0.0, passable=True, color=(128,128,128))`
  — visual definition for a tile type, with per-viewpoint sprite
  overrides and a `sprite_for(vp)` lookup.
- `IsoCell(gx, gy, gz, tile_def=None, entity=None, z_offset=0.0)` —
  one cell in the sparse grid.
- `IsoGrid(width, height, depth=8, tile_w=64, tile_h=32, z_scale=16.0)`
  — `set_tile`, `get_cell`, `remove_tile`, `top_z`, `all_cells`,
  `world_to_screen`, and `sorted_cells(vp, …)` for painter's-order
  rendering with viewport culling.
- `IsoEntity(grid_x=0, grid_y=0, grid_z=0, local_z=0, facing_angle=0, receives_fluid_forces=False)`
  — `move_to`, `move_by`, `face_toward`, `distance_to`, plus
  `total_z = grid_z + local_z` for the engine's Z-height lighting.
- `IsoCamera(viewpoint=NE, tile_w=64, tile_h=32)` — `pan`, `reset_pan`,
  `rotate_cw`, `rotate_ccw`, `set_viewpoint`, `screen_to_grid`, and
  `update_entity_viewpoints` so the engine's `AngleSpriteMap` picks the
  right per-viewpoint sprite when the camera rotates.
- `IsoScene(grid_w=20, grid_h=20, grid_d=4, …)` — drop-in `Scene`
  replacement; `add_iso_entity`, `remove_iso_entity`, `add_z_layer`,
  `remove_z_layer`, `sorted_render_list`, `update(dt)`.

Projection helpers in `pharos_engine.iso.projection`:

- `world_to_screen(gx, gy, gz, vp, tile_w=64, tile_h=32, z_scale=16.0, cam_x=0, cam_y=0) -> (sx, sy)`
- `screen_to_world(sx, sy, vp, tile_w=64, tile_h=32, cam_x=0, cam_y=0) -> (gx, gy)`
  — Cramer's rule on the 2×2 viewpoint matrix, picks the ground plane.
- `depth_key(gx, gy, gz, vp) -> float` — painter's sort key; `gz` as
  fractional tie-breaker.

## Combat surface (`pharos_engine.iso.combat`)

Pure-logic combat primitives for iso games. No rendering imports, no
RNG, no game-side dependencies. Determinism is a contract — same
`(WaveSpec list, dt sequence)` inputs always produce identical
`Defender` outputs (same positions, same hp, same order).

### Classes

#### `Attacker`

_dataclass — `pharos_engine.iso.combat`_

An entity that can deal damage in iso world space.

```python
Attacker(pos: tuple[float, float], damage: float, reach: float, team: str = 'player') -> None
```

- `pos` — iso world coordinates.
- `damage` — applied to a defender within `reach`; may be `0`.
- `reach` — max Euclidean hit distance in iso world units.
- `team` — free-form id; **not** consulted by `resolve_attack`.

#### `Defender`

_dataclass — `pharos_engine.iso.combat`_

An entity that can receive damage in iso world space.

```python
Defender(pos: tuple[float, float], hp: float, team: str = 'enemy') -> None
```

- `pos` — iso world coordinates.
- `hp` — current hit points; mutated in place by `resolve_attack`.
- `team` — free-form id.

#### `WaveSpec`

_dataclass — `pharos_engine.iso.combat`_

Describes a single wave of defenders to be spawned over time.

```python
WaveSpec(count: int, spawn_points: list[tuple[float, float]], hp_each: float, interval: float, delay: float = 0.0) -> None
```

- `count` — total defenders to spawn; must be ≥ 1.
- `spawn_points` — iso world coordinates, cycled round-robin
  (`spawn_points[i % len(spawn_points)]` for defender `i`); non-empty.
- `hp_each` — initial `hp` for every spawned defender; must be > 0.
- `interval` — seconds between successive spawns within this wave; ≥ 0.
- `delay` — seconds to wait, from the moment this wave becomes active,
  before the first spawn fires.

Raises `TypeError` for wrong types; `ValueError` for `count < 1`,
empty `spawn_points`, `hp_each <= 0`, or negative / non-finite
`interval` / `delay`.

#### `WaveSchedule`

_class — `pharos_engine.iso.combat`_

Deterministic sequential scheduler for a list of `WaveSpec`. Each wave
runs to completion (all `count` defenders spawned) before the next
becomes active. Leftover `dt` is carried across wave boundaries so
total-`dt` determinism holds regardless of how the frame budget is
sliced. No RNG anywhere.

```python
WaveSchedule(waves: list[WaveSpec]) -> None
```

Methods:

- `tick(self, dt: float) -> list[Defender]` — advance the schedule by
  `dt` seconds and return newly-spawned defenders in spawn order (empty
  when no spawns are due). Multiple spawns can fire on one tick when
  `dt` is large vs `interval`; a zero-`dt` tick still fires spawns
  whose `next_spawn_at` was reached on a prior tick. Raises `TypeError`
  if `dt` is not a real number; `ValueError` if `dt` is non-finite or
  negative.
- `finished` (property) — `True` iff every wave has emitted all of its
  defenders.

### Functions

#### `resolve_attack(attacker: Attacker, defender: Defender) -> tuple[float, bool]`

Resolve a single attack. Returns `(damage_dealt, defender_alive)`:

- `damage_dealt` — hp removed; `0.0` if the defender is out of reach.
- `defender_alive` — `True` iff `defender.hp > 0` after the exchange.

Pure: no globals, no RNG. The only side effect is mutating
`defender.hp` when a hit lands. Gameplay code that needs team filtering
must do so **before** calling `resolve_attack` — the function itself
does not consult `attacker.team` / `defender.team`.

Raises:

- `TypeError` — if `attacker` lacks `pos` / `damage` / `reach`, or
  `defender` lacks `pos` / `hp`.
- `ValueError` — if `attacker.damage`, `attacker.reach`, or
  `defender.hp` are negative or non-finite.

### Wave-event surface

`WaveSchedule.tick` is the entire event surface. Each call returns a
fresh list of `Defender` instances spawned on that tick. Game code
typically threads this into its iso scene:

```python
from pharos_engine.iso import IsoEntity
from pharos_engine.iso.combat import WaveSpec, WaveSchedule

schedule = WaveSchedule([
    WaveSpec(count=5, spawn_points=[(0.0, 0.0), (10.0, 0.0)],
             hp_each=20.0, interval=0.5, delay=1.0),
    WaveSpec(count=3, spawn_points=[(5.0, 5.0)],
             hp_each=50.0, interval=1.0),
])

for defender in schedule.tick(dt):
    scene.add_iso_entity(IsoEntity(grid_x=defender.pos[0],
                                    grid_y=defender.pos[1]))
    game.register_defender(defender)
```

No `on_spawn` callback, no event-bus hook, no outside mutation of the
schedule — just the return value of `tick`. This keeps it trivially
testable: assert spawn order and timing against a hard-coded `dt`
sequence.

## Inner modules

- `pharos_engine.iso.combat`
- `pharos_engine.iso.iso_camera`
- `pharos_engine.iso.iso_entity`
- `pharos_engine.iso.iso_grid`
- `pharos_engine.iso.iso_scene`
- `pharos_engine.iso.projection`

## Design notes

No separate `iso_design.md` ships — the isometric rendering
conventions (four-cardinal `IsoViewpoint`, Cramer's-rule ground-plane
pick in `screen_to_world`, `gz`-as-fractional painter's-order tie-
breaker, the determinism-as-contract posture for `WaveSchedule.tick`)
are documented inline above. The combat surface in particular
deliberately ships without an `on_spawn` callback or event hook so the
return-value contract stays trivially testable.

If a future sprint adds free-rotation cameras, dynamic LOD, or
networked wave scheduling, promote that material to a dedicated
`iso_design.md` and link both ways.

## See also

- [`ext.md`](ext.md) — `pharos_engine.ext.iso` re-exports the same
  surface for back-compat imports.
- [`gpu.md`](gpu.md) — the renderer side the iso scene composes onto.
