"""SlapPyEngine -- Hello Composite

Composes four engine subsystems into a single "defended foundry" demo:

* :mod:`slappyengine.iso.combat` -- two stationary defenders are attacked
  by a :class:`~slappyengine.iso.combat.WaveSchedule` that emits four
  attackers from the east/west arena edges. Attackers home toward the
  nearest living defender at :data:`ATTACKER_SPEED` and call
  :func:`~slappyengine.iso.combat.resolve_attack` on contact; defenders
  shoot back inside their reach.
* :mod:`slappyengine.dynamics` -- a 16-node rope hangs between
  ``(1, 1)`` and ``(9, 1)``. It is purely decorative -- it doesn't
  collide with attackers -- and proves the dynamics ``World`` integrates
  alongside the rest of the loop without churn.
* :mod:`slappyengine.zones` -- a single :class:`RectZone` at
  ``(4, 4, 2, 2)`` tracks every attacker's iso position via
  :meth:`ZoneManager.update`. Its ``on_enter`` callback ticks an
  internal counter, exposing how many distinct attackers ever crossed
  into the foundry's defended quad.
* :mod:`slappyengine.thermal` -- a 32x32 :class:`HeatField` blankets the
  arena at ambient ``T = 20``. The two defenders are pinned hot spots at
  ``T = 300`` (re-emitted every frame so diffusion can't cool them).
  Live attackers exchange heat with the field via
  :meth:`HeatField.exchange_with` against a one-cell scratch field so
  they slowly absorb the foundry's warmth as they close in.
* :mod:`slappyengine.topology` -- after every dynamics step
  :func:`~slappyengine.topology.connected_components` is run on the
  rope's joint edges to assert the cable is still one connected piece.

Frame loop at ``dt = 1/30`` for 180 frames:

1. ``WaveSchedule.tick`` may emit new attackers.
2. Live attackers home toward the nearest living defender at
   ``ATTACKER_SPEED`` grid-units/sec.
3. :func:`resolve_attack` debits hp on both sides where the reach
   overlaps.
4. ``ZoneManager.update`` is fed the latest attacker positions.
5. ``HeatField.step`` diffuses the arena field with ``boundary='clamp'``;
   defenders are re-clamped to :data:`DEFENDER_TEMP`; attackers exchange
   with the cell directly under their foot via
   :meth:`HeatField.exchange_with`.
6. ``World.step`` advances the rope.
7. ``topology.connected_components`` over the rope's joint edges --
   asserted equal to ``1`` every frame.

Reporting (printed to stdout):

* defender hp values at frame 180,
* live attacker count,
* total damage dealt to defenders,
* foundry zone enter count,
* rope-still-connected boolean,
* max heat at frame 180.

Run::

    PYTHONPATH=python python examples/hello_composite.py
    PYTHONPATH=python python examples/hello_composite.py --frames 60
    PYTHONPATH=python python examples/hello_composite.py --render
    PYTHONPATH=python python examples/hello_composite.py --frames 180 --render --out out/

When ``--render`` is supplied the demo rasterises a 320x320 PNG with
pure PIL: dark arena background, the heat field as a red-tinted overlay,
the foundry zone outlined in yellow, the rope as white line segments
with anchor markers, defenders as green squares with hp bars, and live
attackers as red dots.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

import numpy as np

from slappyengine.dynamics import RopeSpec, World, build_rope
from slappyengine.iso.combat import (
    Attacker,
    Defender,
    WaveSchedule,
    WaveSpec,
    resolve_attack,
)
from slappyengine.thermal import HeatField
from slappyengine.topology import connected_components
from slappyengine.zones import RectZone, ZoneManager


# -- Arena layout ------------------------------------------------------------
ARENA_W: float = 10.0
ARENA_H: float = 10.0

DEFENDER_POSITIONS: Tuple[Tuple[float, float], ...] = ((3.0, 5.0), (7.0, 5.0))
DEFENDER_HP: float = 100.0
DEFENDER_DAMAGE: float = 1.0
DEFENDER_REACH: float = 1.0
DEFENDER_TEMP: float = 300.0
DEFENDER_THERMAL_RADIUS: float = 1.5  # informational; defenders pinned

WAVE_COUNT: int = 4
WAVE_SPAWN_POINTS: List[Tuple[float, float]] = [(0.0, 5.0), (10.0, 5.0)]
WAVE_HP_EACH: float = 200.0
WAVE_INTERVAL: float = 1.0

ATTACKER_SPEED: float = 2.5         # iso grid units / second
ATTACKER_DAMAGE: float = 1.0
ATTACKER_REACH: float = 1.0
ATTACKER_THERMAL_MASS: float = 0.5  # mass of the attacker's scratch cell
ATTACKER_THERMAL_K: float = 1.0     # attacker-side conductivity

# Rope (purely decorative, slack catenary from (1, 1) to (9, 1)).
ROPE_ANCHOR_A: Tuple[float, float] = (1.0, 1.0)
ROPE_ANCHOR_B: Tuple[float, float] = (9.0, 1.0)
ROPE_NODE_COUNT: int = 16
ROPE_TOTAL_LENGTH: float = 9.0    # tiny slack so the catenary droops <0.5
ROPE_MASS_PER_NODE: float = 0.05
ROPE_STIFFNESS: float = 2.0e6
ROPE_DAMPING: float = 0.015     # stays below estimate_effective_damping warn line
ROPE_GRAVITY: Tuple[float, float] = (0.0, -9.81)
ROPE_SOLVER_ITERS: int = 16

# Foundry trigger zone: (x, y, w, h).
ZONE_RECT: Tuple[float, float, float, float] = (4.0, 4.0, 2.0, 2.0)
ZONE_NAME: str = "foundry"

# Heat field configuration.
HEAT_GRID: int = 32
HEAT_AMBIENT: float = 20.0
HEAT_CONDUCTIVITY: float = 1.0
HEAT_DIFFUSIVITY: float = 0.1

DEFAULT_DT: float = 1.0 / 30.0
DEFAULT_FRAMES: int = 180

# -- Render parameters -------------------------------------------------------
RENDER_W: int = 320
RENDER_H: int = 320
# Render the arena with a small margin on each side.
VIEW_MIN: Tuple[float, float] = (-0.5, -0.5)
VIEW_MAX: Tuple[float, float] = (10.5, 10.5)


# ---------------------------------------------------------------------------
# Game-state containers
# ---------------------------------------------------------------------------


@dataclass
class LiveAttacker:
    """An in-flight attacker wrapping a :class:`Defender` body + view.

    ``preferred_target`` is the index of the defender the attacker
    initially homes toward; once that defender is dead the attacker
    falls back to the closest living defender. Attackers from the west
    edge target the east defender (and vice versa), which routes both
    lanes through the central foundry zone.
    """

    body: Defender                       # carries pos + hp (attacker hp)
    attacker_view: Attacker              # damage view for resolve_attack
    preferred_target: int = -1
    dead: bool = False


@dataclass
class Scene:
    """All the live state the composite demo owns."""

    # iso/combat
    defenders: List[Defender]
    defender_views: List[Attacker]
    schedule: WaveSchedule
    attackers: List[LiveAttacker] = field(default_factory=list)
    damage_dealt_to: List[float] = field(default_factory=list)
    attackers_killed: int = 0
    total_spawns: int = 0
    # zones
    zone_manager: ZoneManager = field(default_factory=ZoneManager)
    zone_enter_count: int = 0
    # heat
    heat_field: "HeatField | None" = None
    # rope dynamics
    world: "World | None" = None
    rope_body: "object | None" = None
    rope_edges: "np.ndarray | None" = None
    # topology
    rope_components_history: List[int] = field(default_factory=list)
    # diagnostics
    nan_seen: bool = False


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _build_zone_manager() -> Tuple[ZoneManager, dict]:
    """Build the foundry zone manager + an enter-record sink for diagnostics."""
    records: dict = {"enter": [], "exit": []}

    def _on_enter(eid):
        records["enter"].append(eid)

    def _on_exit(eid):
        records["exit"].append(eid)

    manager = ZoneManager()
    manager.add(
        RectZone(
            name=ZONE_NAME,
            x=ZONE_RECT[0],
            y=ZONE_RECT[1],
            w=ZONE_RECT[2],
            h=ZONE_RECT[3],
            material="foundry",
            on_enter=_on_enter,
            on_exit=_on_exit,
        )
    )
    return manager, records


def _build_heat_field() -> HeatField:
    """32x32 ambient grid that will host the defender hot-spots."""
    T = np.full((HEAT_GRID, HEAT_GRID), HEAT_AMBIENT, dtype=np.float64)
    return HeatField(
        T,
        conductivity=HEAT_CONDUCTIVITY,
        diffusivity=HEAT_DIFFUSIVITY,
    )


def _world_to_grid(pos: Tuple[float, float]) -> Tuple[int, int]:
    """Map an iso arena coordinate to a heat-field ``(iy, ix)`` cell index."""
    x = max(0.0, min(ARENA_W, float(pos[0])))
    y = max(0.0, min(ARENA_H, float(pos[1])))
    # Clamp so the rightmost / topmost cell still resolves to (size - 1).
    ix = min(HEAT_GRID - 1, int(x / ARENA_W * HEAT_GRID))
    iy = min(HEAT_GRID - 1, int(y / ARENA_H * HEAT_GRID))
    return iy, ix


def _build_rope_world() -> Tuple[World, object, np.ndarray]:
    """Spawn the rope inside a fresh ``World`` and return (world, body, edges)."""
    world = World(gravity=ROPE_GRAVITY)
    world.solver_iterations = ROPE_SOLVER_ITERS
    spec = RopeSpec(
        node_count=ROPE_NODE_COUNT,
        total_length=ROPE_TOTAL_LENGTH,
        mass_per_node=ROPE_MASS_PER_NODE,
        stiffness=ROPE_STIFFNESS,
        damping=ROPE_DAMPING,
        anchor_a_pinned=True,
        anchor_b_pinned=True,
    )
    body = build_rope(spec, world, anchor_a=ROPE_ANCHOR_A, anchor_b=ROPE_ANCHOR_B)

    # The rope is a chain; its joints are sequential distance constraints
    # spanning consecutive node pairs. Building the edge list once and
    # caching it lets us hand the array straight to topology each frame.
    nodes = list(body.node_indices)
    edges = np.array(
        [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)],
        dtype=np.int64,
    )
    return world, body, edges


def build_scene() -> Scene:
    """Construct the full composite scene."""
    defenders: List[Defender] = [
        Defender(pos=pos, hp=DEFENDER_HP, team="player")
        for pos in DEFENDER_POSITIONS
    ]
    defender_views: List[Attacker] = [
        Attacker(
            pos=d.pos,
            damage=DEFENDER_DAMAGE,
            reach=DEFENDER_REACH,
            team="player",
        )
        for d in defenders
    ]
    schedule = WaveSchedule([
        WaveSpec(
            count=WAVE_COUNT,
            spawn_points=list(WAVE_SPAWN_POINTS),
            hp_each=WAVE_HP_EACH,
            interval=WAVE_INTERVAL,
        ),
    ])
    zone_manager, zone_records = _build_zone_manager()
    heat_field = _build_heat_field()
    world, rope_body, rope_edges = _build_rope_world()

    scene = Scene(
        defenders=defenders,
        defender_views=defender_views,
        schedule=schedule,
        damage_dealt_to=[0.0 for _ in defenders],
        zone_manager=zone_manager,
        heat_field=heat_field,
        world=world,
        rope_body=rope_body,
        rope_edges=rope_edges,
    )
    # Stash the zone records on the scene so the stepper can read them.
    scene._zone_records = zone_records  # type: ignore[attr-defined]
    return scene


# ---------------------------------------------------------------------------
# Stepping
# ---------------------------------------------------------------------------


def _closest_defender_index(
    pos: Tuple[float, float],
    defenders: List[Defender],
) -> int:
    """Index of the closest living defender (-1 if all dead)."""
    best_idx = -1
    best_d2 = float("inf")
    for i, d in enumerate(defenders):
        if d.hp <= 0.0:
            continue
        dx = d.pos[0] - pos[0]
        dy = d.pos[1] - pos[1]
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best_idx = i
    return best_idx


def _move_toward(
    pos: Tuple[float, float],
    target: Tuple[float, float],
    max_step: float,
) -> Tuple[float, float]:
    """Move ``pos`` toward ``target`` by up to ``max_step``."""
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    dist = float(np.hypot(dx, dy))
    if dist <= 1e-9 or dist <= max_step:
        return target
    inv = max_step / dist
    return (pos[0] + dx * inv, pos[1] + dy * inv)


def _pin_defender_hotspots(field: HeatField) -> None:
    """Clamp the defender cells to :data:`DEFENDER_TEMP` every frame.

    Diffusion would otherwise rapidly equalise the spots with the
    ambient bulk; re-emitting keeps the foundry visibly hot at the
    defender locations.
    """
    T = field.temperature
    for pos in DEFENDER_POSITIONS:
        iy, ix = _world_to_grid(pos)
        T[iy, ix] = DEFENDER_TEMP


def _exchange_attacker_with_field(
    live: LiveAttacker,
    field: HeatField,
    dt: float,
) -> None:
    """Couple a live attacker's heat to the arena field.

    The attacker carries a tiny scratch field whose single cell sits at
    the attacker's body temperature. The field's
    :meth:`exchange_with` then runs the Newton's-law flux against the
    cell under the attacker's foot. Both halves of the quantum are
    written back via the shared in-place semantics, so total
    arena+attacker energy is conserved up to float rounding.

    We do not currently fold the attacker temperature into combat
    damage; the demo is about composition, not gameplay polish.
    """
    iy, ix = _world_to_grid(live.body.pos)
    # Attacker scratch field: a 2x2 grid (HeatField requires >=2 cells per
    # axis). Cell (0, 0) is the active sample we exchange against; the
    # other three cells stay at the attacker's ambient body temperature so
    # internal diffusion is a no-op.
    body_T = getattr(live, "_body_T", float(HEAT_AMBIENT))
    scratch_arr = np.full((2, 2), body_T, dtype=np.float64)
    scratch = HeatField(
        scratch_arr,
        conductivity=ATTACKER_THERMAL_K,
        diffusivity=HEAT_DIFFUSIVITY,
    )
    field.exchange_with(scratch, [((iy, ix), (0, 0))], dt=dt)
    # Persist the warmed (or cooled) sample back onto the attacker so the
    # next exchange reflects its new equilibrium.
    live._body_T = float(scratch_arr[0, 0])  # type: ignore[attr-defined]


def step_scene(
    scene: Scene,
    frames: int,
    dt: float = DEFAULT_DT,
) -> Scene:
    """Drive every subsystem for ``frames`` ticks at ``dt``."""
    schedule = scene.schedule
    defenders = scene.defenders
    defender_views = scene.defender_views
    attackers = scene.attackers
    manager = scene.zone_manager
    field = scene.heat_field
    world = scene.world
    rope_edges = scene.rope_edges
    records = getattr(scene, "_zone_records", {"enter": [], "exit": []})

    assert field is not None
    assert world is not None
    assert rope_edges is not None

    max_step = ATTACKER_SPEED * dt
    n_rope_nodes = int(world.positions.shape[0])

    for frame in range(1, frames + 1):
        # ── 1. Wave spawns ───────────────────────────────────────────────
        for spawn in schedule.tick(dt):
            atk_view = Attacker(
                pos=spawn.pos,
                damage=ATTACKER_DAMAGE,
                reach=ATTACKER_REACH,
                team="enemy",
            )
            # Cross-target: west-edge spawns head for the east defender
            # and vice versa, routing both lanes through the foundry zone
            # in the middle of the arena.
            sx = float(spawn.pos[0])
            preferred = 1 if sx < ARENA_W * 0.5 else 0
            live = LiveAttacker(
                body=spawn,
                attacker_view=atk_view,
                preferred_target=preferred,
            )
            live._body_T = float(HEAT_AMBIENT)  # type: ignore[attr-defined]
            attackers.append(live)
            scene.total_spawns += 1

        # ── 2. Attacker motion + 3. Attacker -> Defender damage ──────────
        for live in attackers:
            if live.dead:
                continue
            # Prefer the cross-arena target while it's alive; fall back
            # to the nearest living defender once it dies.
            target_idx = live.preferred_target
            if target_idx < 0 or defenders[target_idx].hp <= 0.0:
                target_idx = _closest_defender_index(live.body.pos, defenders)
            if target_idx >= 0:
                new_pos = _move_toward(
                    live.body.pos,
                    defenders[target_idx].pos,
                    max_step,
                )
                live.body.pos = new_pos
                live.attacker_view.pos = new_pos

                dmg, def_alive = resolve_attack(
                    live.attacker_view, defenders[target_idx]
                )
                if dmg > 0.0:
                    scene.damage_dealt_to[target_idx] += float(dmg)
                if not def_alive and defenders[target_idx].hp < 0.0:
                    defenders[target_idx].hp = 0.0

        # ── 4. Defender return fire ──────────────────────────────────────
        for d_idx, defender in enumerate(defenders):
            if defender.hp <= 0.0:
                continue
            view = defender_views[d_idx]
            view.pos = defender.pos
            for live in attackers:
                if live.dead:
                    continue
                _dmg, alive = resolve_attack(view, live.body)
                if not alive:
                    live.dead = True
                    scene.attackers_killed += 1
                    if live.body.hp < 0.0:
                        live.body.hp = 0.0

        # ── 5. Zone occupancy update (live attackers only) ───────────────
        prev_enter = len(records["enter"])
        positions = {
            f"atk_{i}": live.body.pos
            for i, live in enumerate(attackers)
            if not live.dead
        }
        manager.update(positions)
        scene.zone_enter_count += len(records["enter"]) - prev_enter

        # ── 6. Thermal: diffuse, re-emit hot spots, exchange attackers ───
        field.step(dt, boundary="clamp")
        _pin_defender_hotspots(field)
        for live in attackers:
            if live.dead:
                continue
            _exchange_attacker_with_field(live, field, dt)

        # ── 7. Rope dynamics step ────────────────────────────────────────
        world.step(dt)

        # ── 8. Topology: rope must stay one connected piece ──────────────
        _labels, n_components = connected_components(n_rope_nodes, rope_edges)
        scene.rope_components_history.append(int(n_components))

        # ── Diagnostics: catch NaN leaks anywhere ────────────────────────
        if not scene.nan_seen:
            if not np.all(np.isfinite(field.temperature)):
                scene.nan_seen = True
            elif not np.all(np.isfinite(world.positions)):
                scene.nan_seen = True
            else:
                for d in defenders:
                    if not (np.isfinite(d.pos[0]) and np.isfinite(d.pos[1])
                            and np.isfinite(d.hp)):
                        scene.nan_seen = True
                        break
                if not scene.nan_seen:
                    for live in attackers:
                        if not (np.isfinite(live.body.pos[0])
                                and np.isfinite(live.body.pos[1])
                                and np.isfinite(live.body.hp)):
                            scene.nan_seen = True
                            break

    return scene


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarise(scene: Scene, frames: int) -> dict:
    """Roll the scene up into the printable summary dict."""
    assert scene.heat_field is not None
    field = scene.heat_field
    max_heat = float(field.temperature.max())
    rope_connected = all(c == 1 for c in scene.rope_components_history)
    live = sum(1 for a in scene.attackers if not a.dead)
    return {
        "frames": int(frames),
        "defender_hp": [float(d.hp) for d in scene.defenders],
        "damage_dealt_to": [float(x) for x in scene.damage_dealt_to],
        "total_damage": float(sum(scene.damage_dealt_to)),
        "live_attackers": int(live),
        "attackers_killed": int(scene.attackers_killed),
        "total_spawns": int(scene.total_spawns),
        "zone_enter_count": int(scene.zone_enter_count),
        "rope_connected": bool(rope_connected),
        "max_heat": max_heat,
        "nan_seen": bool(scene.nan_seen),
    }


def print_summary(summary: dict) -> None:
    print("hello_composite summary")
    print(f"  frames                : {summary['frames']}")
    for i, hp in enumerate(summary["defender_hp"]):
        dmg = summary["damage_dealt_to"][i]
        print(f"  defender[{i}] hp        : {hp:.2f}  (dmg_taken={dmg:.2f})")
    print(f"  total damage dealt    : {summary['total_damage']:.2f}")
    print(f"  attackers alive       : {summary['live_attackers']}")
    print(f"  attackers killed      : {summary['attackers_killed']}")
    print(f"  total spawns          : {summary['total_spawns']}")
    print(f"  zone enter count      : {summary['zone_enter_count']}")
    print(f"  rope still connected  : {'yes' if summary['rope_connected'] else 'no'}")
    print(f"  max heat @ frame {summary['frames']:>3d}  : {summary['max_heat']:.4f}")
    print(f"  any NaN in state      : {summary['nan_seen']}")


# ---------------------------------------------------------------------------
# Pure-PIL renderer
# ---------------------------------------------------------------------------


def _world_to_pixel(pos: Tuple[float, float]) -> Tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(pos[0]) - vx0) / (vx1 - vx0)
    v = (float(pos[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    # World y grows up; image y grows down -- invert v.
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _world_radius_to_pixels(r: float) -> int:
    vx0, _ = VIEW_MIN
    vx1, _ = VIEW_MAX
    span = vx1 - vx0
    return max(1, int(round(r / span * (RENDER_W - 1))))


def _rect_to_pixels(
    rect: Tuple[float, float, float, float],
) -> Tuple[int, int, int, int]:
    x, y, w, h = rect
    left_px, bottom_px = _world_to_pixel((x, y))
    right_px, top_px = _world_to_pixel((x + w, y + h))
    return (
        min(left_px, right_px),
        min(top_px, bottom_px),
        max(left_px, right_px),
        max(top_px, bottom_px),
    )


def _heat_to_overlay(T: np.ndarray) -> np.ndarray:
    """Map the temperature field to a red-tinted ``(H, W, 4)`` RGBA overlay.

    Ambient cells produce a near-transparent dark wash; hotter cells
    become opaque red. Output is uint8 with shape matching the grid.
    """
    Tf = np.asarray(T, dtype=np.float64)
    # Normalise [ambient, defender_temp] → [0, 1].
    span = max(1e-9, DEFENDER_TEMP - HEAT_AMBIENT)
    frac = np.clip((Tf - HEAT_AMBIENT) / span, 0.0, 1.0)

    # Build an RGBA: red rises with heat, green/blue stay dim, alpha
    # ramps with heat so cold cells are mostly transparent.
    r = (40 + frac * 215).astype(np.uint8)
    g = (np.zeros_like(frac) + 20).astype(np.uint8)
    b = (np.zeros_like(frac) + 20).astype(np.uint8)
    a = (60 + frac * 195).astype(np.uint8)
    rgba = np.stack([r, g, b, a], axis=-1)
    return rgba


def _render_frame(scene: Scene) -> np.ndarray:
    """Rasterise the full composite scene to an ``(H, W, 4)`` uint8 RGBA buffer."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (12, 12, 18, 255))

    # ── Heat overlay (drawn first so everything else sits on top) ────────
    assert scene.heat_field is not None
    heat_rgba = _heat_to_overlay(scene.heat_field.temperature)
    heat_img = Image.fromarray(heat_rgba, mode="RGBA").resize(
        (RENDER_W, RENDER_H), Image.Resampling.BILINEAR
    )
    img.alpha_composite(heat_img)

    draw = ImageDraw.Draw(img, "RGBA")

    # ── Foundry zone outline (yellow) ────────────────────────────────────
    zone = scene.zone_manager.get(ZONE_NAME)
    if zone is not None:
        rect = _rect_to_pixels(zone.rect)
        draw.rectangle(rect, outline=(235, 220, 96, 255), width=2)

    # ── Rope (white lines + anchor nubs) ─────────────────────────────────
    assert scene.world is not None
    rope_pos = scene.world.positions
    inv_masses = scene.world.inv_masses
    n = rope_pos.shape[0]
    if n >= 2:
        # Lift the rope into the arena view: rope world y is negative
        # (catenary droops below y=1 toward y=-2), but our arena view
        # covers (-0.5..10.5). Place the rope visually at its real
        # location -- the renderer's _world_to_pixel handles the rest.
        for i in range(n - 1):
            a = _world_to_pixel((float(rope_pos[i, 0]), float(rope_pos[i, 1])))
            b = _world_to_pixel(
                (float(rope_pos[i + 1, 0]), float(rope_pos[i + 1, 1]))
            )
            draw.line([a, b], fill=(255, 255, 255, 255), width=2)
        for i in range(n):
            x, y = _world_to_pixel((float(rope_pos[i, 0]), float(rope_pos[i, 1])))
            r = 4 if inv_masses[i] == 0.0 else 2
            draw.ellipse(
                [(x - r, y - r), (x + r, y + r)],
                fill=(255, 255, 255, 255),
                outline=(255, 255, 255, 255),
            )

    # ── Defenders (green squares with hp bars) ───────────────────────────
    half = max(4, _world_radius_to_pixels(0.4))
    for d in scene.defenders:
        cx, cy = _world_to_pixel(d.pos)
        body_color = (60, 200, 60, 255) if d.hp > 0.0 else (60, 90, 60, 255)
        draw.rectangle(
            [(cx - half, cy - half), (cx + half, cy + half)],
            fill=body_color,
            outline=(20, 120, 20, 255),
            width=1,
        )
        bar_w = 2 * half
        bar_h = 3
        bar_x0 = cx - half
        bar_y0 = cy - half - bar_h - 2
        draw.rectangle(
            [(bar_x0, bar_y0), (bar_x0 + bar_w, bar_y0 + bar_h)],
            fill=(60, 0, 0, 255),
            outline=(120, 120, 120, 255),
            width=1,
        )
        frac = max(0.0, min(1.0, float(d.hp) / float(DEFENDER_HP)))
        fill_w = int(round(frac * bar_w))
        if fill_w > 0:
            draw.rectangle(
                [(bar_x0, bar_y0), (bar_x0 + fill_w, bar_y0 + bar_h)],
                fill=(220, 40, 40, 255),
            )

    # ── Live attackers (red dots) ────────────────────────────────────────
    dot_r = max(2, _world_radius_to_pixels(0.18))
    for live in scene.attackers:
        if live.dead:
            continue
        cx, cy = _world_to_pixel(live.body.pos)
        draw.ellipse(
            [(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)],
            fill=(255, 60, 60, 255),
            outline=(255, 200, 200, 255),
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(scene: Scene, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(scene)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello Composite -- SlapPyEngine demo"
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/30 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_composite.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_composite.png"),
) -> dict:
    """Run the composite demo end-to-end. Returns the summary dict for tests."""
    scene = build_scene()
    step_scene(scene, frames, DEFAULT_DT)
    summary = summarise(scene, frames)
    print_summary(summary)

    if render:
        out_path = save_render(scene, Path(out))
        print(f"  rendered to           : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_composite: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
