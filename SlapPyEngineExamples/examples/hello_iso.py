"""SlapPyEngine — Hello Iso

Minimal demo of :mod:`slappyengine.iso` + :mod:`slappyengine.iso.combat`.

Builds a small 10x10 isometric arena occupied by two stationary defender
towers placed at iso grid coordinates ``(5, 3)`` and ``(5, 7)``. A single
:class:`~slappyengine.iso.combat.WaveSchedule` carrying one
:class:`~slappyengine.iso.combat.WaveSpec` of four attackers is then
ticked over 360 frames at ``dt = 1/30`` (12 sim seconds). Attackers spawn
from the arena edges at ``(0, 5)`` and ``(9, 5)`` (round-robin), home in
on the nearest defender at 2.5 grid-units/second, and once inside their
reach call :func:`~slappyengine.iso.combat.resolve_attack` to chip away
at the defender's hp. The defenders themselves return fire each frame an
attacker is within their reach.

Run::

    PYTHONPATH=python python examples/hello_iso.py
    PYTHONPATH=python python examples/hello_iso.py --frames 360 --render
    PYTHONPATH=python python examples/hello_iso.py --render --out out/

Reporting (printed to stdout):

- total spawns emitted by the wave schedule,
- defender hp sampled every 60 frames,
- total damage dealt to each defender,
- attackers killed by defender return-fire.

When ``--render`` is supplied the demo rasterises a 256x256 PNG with pure
PIL — no GPU dependency. The render shows the arena (black background),
defenders as green squares with hp bars, attackers as red dots with a
thin reach-radius outline, and faded trails for the last 30 frames of
attacker motion.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

import numpy as np

from slappyengine.iso import IsoGrid, IsoTileDef
from slappyengine.iso.combat import (
    Attacker,
    Defender,
    WaveSchedule,
    WaveSpec,
    resolve_attack,
)


# ── Demo parameters ────────────────────────────────────────────────────────
GRID_W: int = 10
GRID_H: int = 10

DEFENDER_POSITIONS: Tuple[Tuple[float, float], ...] = ((5.0, 3.0), (5.0, 7.0))
DEFENDER_HP: float = 80.0
DEFENDER_DAMAGE: float = 2.0
DEFENDER_REACH: float = 2.5

WAVE_COUNT: int = 4
WAVE_SPAWN_POINTS: List[Tuple[float, float]] = [(0.0, 5.0), (9.0, 5.0)]
WAVE_HP_EACH: float = 40.0
WAVE_INTERVAL: float = 1.0

ATTACKER_SPEED: float = 2.5        # iso grid units per second
ATTACKER_DAMAGE: float = 3.0
ATTACKER_REACH: float = 1.8

DEFAULT_DT: float = 1.0 / 30.0
DEFAULT_FRAMES: int = 360
SAMPLE_EVERY: int = 60
TRAIL_FRAMES: int = 30

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 256
RENDER_H: int = 256
# View box covers the full 10x10 arena with a small margin.
VIEW_MIN: Tuple[float, float] = (-0.5, -0.5)
VIEW_MAX: Tuple[float, float] = (9.5, 9.5)


# ────────────────────────────────────────────────────────────────────────────
# Game-state containers
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class LiveAttacker:
    """A wave-spawned attacker in flight.

    The :class:`Defender` returned by :class:`WaveSchedule` is reused as
    the carrier of position and hp — the demo just wraps it with a few
    bookkeeping fields and an :class:`Attacker` view for damage calls.
    """

    body: Defender                       # carries pos + hp (hp = "attacker hp")
    attacker_view: Attacker              # for resolve_attack vs defenders
    trail: List[Tuple[float, float]] = field(default_factory=list)
    dead: bool = False


def _build_arena_grid() -> IsoGrid:
    """Build the 10x10 iso floor grid used by the demo."""
    grid = IsoGrid(width=GRID_W, height=GRID_H, depth=1)
    floor = IsoTileDef(
        name="arena_floor",
        sprite_path="<placeholder>",   # the demo never blits
        z_height=0.0,
        passable=True,
        color=(40, 40, 40),
    )
    for gx in range(GRID_W):
        for gy in range(GRID_H):
            grid.set_tile(gx, gy, 0, floor)
    return grid


def build_world() -> dict:
    """Construct the iso grid, defenders, attacker-views, and wave schedule."""
    grid = _build_arena_grid()

    defenders: List[Defender] = [
        Defender(pos=pos, hp=DEFENDER_HP, team="player")
        for pos in DEFENDER_POSITIONS
    ]
    # Each defender also doubles as a turret; its Attacker view is updated
    # in-place every frame so resolve_attack sees the current position.
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

    return {
        "grid": grid,
        "defenders": defenders,
        "defender_views": defender_views,
        "schedule": schedule,
        "attackers": [],          # populated as the schedule fires
        "damage_dealt_to": [0.0 for _ in defenders],
        "attackers_killed": 0,
        "total_spawns": 0,
    }


# ────────────────────────────────────────────────────────────────────────────
# Stepping
# ────────────────────────────────────────────────────────────────────────────

def _closest_defender_index(
    pos: Tuple[float, float],
    defenders: List[Defender],
) -> int:
    """Index of the closest *living* defender, or -1 if all are dead."""
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
    """Return a position moved toward ``target`` by at most ``max_step``."""
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    dist = float(np.hypot(dx, dy))
    if dist <= 1e-9 or dist <= max_step:
        return target
    inv = max_step / dist
    return (pos[0] + dx * inv, pos[1] + dy * inv)


def step_world(world: dict, frames: int, dt: float = DEFAULT_DT) -> dict:
    """Drive the wave/attack loop for ``frames`` ticks.

    Each tick:

    1. ``WaveSchedule.tick(dt)`` may emit new attackers.
    2. Every live attacker homes toward its closest living defender at
       ``ATTACKER_SPEED * dt``, leaving a short trail behind it.
    3. If the attacker is now within its reach of that defender,
       :func:`resolve_attack` debits hp and the damage counter ticks up.
    4. Each defender shoots back at every attacker inside its reach.

    The function also samples defender hp every :data:`SAMPLE_EVERY`
    frames so callers can plot decay curves.
    """
    schedule: WaveSchedule = world["schedule"]
    defenders: List[Defender] = world["defenders"]
    defender_views: List[Attacker] = world["defender_views"]
    attackers: List[LiveAttacker] = world["attackers"]
    damage_dealt_to: List[float] = world["damage_dealt_to"]

    nan_seen = False
    hp_samples: List[dict] = [{
        "frame": 0,
        "defender_hp": [float(d.hp) for d in defenders],
        "live_attackers": 0,
    }]

    for frame in range(1, frames + 1):
        # 1. Spawn from waves.
        new_defs = schedule.tick(dt)
        for spawn in new_defs:
            atk_view = Attacker(
                pos=spawn.pos,
                damage=ATTACKER_DAMAGE,
                reach=ATTACKER_REACH,
                team="enemy",
            )
            attackers.append(
                LiveAttacker(
                    body=spawn,
                    attacker_view=atk_view,
                    trail=[spawn.pos],
                )
            )
            world["total_spawns"] += 1

        # 2. Move each attacker toward closest defender.
        max_step = ATTACKER_SPEED * dt
        for live in attackers:
            if live.dead:
                continue
            target_idx = _closest_defender_index(live.body.pos, defenders)
            if target_idx < 0:
                # No defenders left; attackers idle in place.
                live.trail.append(live.body.pos)
                if len(live.trail) > TRAIL_FRAMES:
                    live.trail.pop(0)
                continue
            target = defenders[target_idx].pos
            new_pos = _move_toward(live.body.pos, target, max_step)
            live.body.pos = new_pos
            live.attacker_view.pos = new_pos
            live.trail.append(new_pos)
            if len(live.trail) > TRAIL_FRAMES:
                live.trail.pop(0)

            # 3. Attacker -> defender attack roll.
            dmg, def_alive = resolve_attack(live.attacker_view, defenders[target_idx])
            if dmg > 0.0:
                damage_dealt_to[target_idx] += float(dmg)
            # Clamp defender hp at zero for clean reporting.
            if not def_alive and defenders[target_idx].hp < 0.0:
                defenders[target_idx].hp = 0.0

        # 4. Defenders shoot back at every attacker in reach.
        for d_idx, defender in enumerate(defenders):
            if defender.hp <= 0.0:
                continue
            view = defender_views[d_idx]
            view.pos = defender.pos     # in case of future motion
            for live in attackers:
                if live.dead:
                    continue
                dmg, atk_alive = resolve_attack(view, live.body)
                if not atk_alive:
                    live.dead = True
                    world["attackers_killed"] += 1
                    if live.body.hp < 0.0:
                        live.body.hp = 0.0

        # Finite check.
        if not nan_seen:
            for d in defenders:
                if not (np.isfinite(d.pos[0]) and np.isfinite(d.pos[1])
                        and np.isfinite(d.hp)):
                    nan_seen = True
                    break
            if not nan_seen:
                for live in attackers:
                    if not (np.isfinite(live.body.pos[0])
                            and np.isfinite(live.body.pos[1])
                            and np.isfinite(live.body.hp)):
                        nan_seen = True
                        break

        if frame % SAMPLE_EVERY == 0:
            hp_samples.append({
                "frame": frame,
                "defender_hp": [float(d.hp) for d in defenders],
                "live_attackers": sum(1 for a in attackers if not a.dead),
            })

    world["hp_samples"] = hp_samples
    world["nan_seen"] = nan_seen
    return world


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(pos: Tuple[float, float]) -> Tuple[int, int]:
    """Map an iso world (x, y) coordinate to integer pixel coordinates."""
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(pos[0]) - vx0) / (vx1 - vx0)
    v = (float(pos[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round(v * (RENDER_H - 1)))   # y grows downward in image space
    return px, py


def _world_radius_to_pixels(r: float) -> int:
    vx0, _ = VIEW_MIN
    vx1, _ = VIEW_MAX
    span = vx1 - vx0
    return max(1, int(round(r / span * (RENDER_W - 1))))


def _render_frame(world: dict) -> np.ndarray:
    """Rasterise the arena, defenders, and attackers to an RGBA buffer."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    defenders: List[Defender] = world["defenders"]
    attackers: List[LiveAttacker] = world["attackers"]

    # --- attacker trails (faded behind everything) ---
    for live in attackers:
        if len(live.trail) < 2:
            continue
        n = len(live.trail)
        for i in range(n - 1):
            a = _world_to_pixel(live.trail[i])
            b = _world_to_pixel(live.trail[i + 1])
            # Older trail samples fade out.
            alpha = int(round(40 * (i + 1) / n)) + 10
            draw.line([a, b], fill=(180, 60, 60, alpha), width=1)

    # --- defenders ---
    half = max(3, _world_radius_to_pixels(0.5))
    for d in defenders:
        cx, cy = _world_to_pixel(d.pos)
        # Body: green square.
        body_color = (60, 200, 60, 255) if d.hp > 0.0 else (60, 90, 60, 255)
        draw.rectangle(
            [(cx - half, cy - half), (cx + half, cy + half)],
            fill=body_color,
            outline=(20, 120, 20, 255),
            width=1,
        )
        # Hp bar above the body.
        bar_w = 2 * half
        bar_h = 3
        bar_x0 = cx - half
        bar_y0 = cy - half - bar_h - 2
        # Background.
        draw.rectangle(
            [(bar_x0, bar_y0), (bar_x0 + bar_w, bar_y0 + bar_h)],
            fill=(60, 0, 0, 255),
            outline=(120, 120, 120, 255),
            width=1,
        )
        # Fill.
        frac = max(0.0, min(1.0, float(d.hp) / float(DEFENDER_HP)))
        fill_w = int(round(frac * bar_w))
        if fill_w > 0:
            draw.rectangle(
                [(bar_x0, bar_y0), (bar_x0 + fill_w, bar_y0 + bar_h)],
                fill=(220, 40, 40, 255),
            )

    # --- attackers (red dots + thin reach radius outlines) ---
    reach_px = _world_radius_to_pixels(ATTACKER_REACH)
    dot_r = max(2, _world_radius_to_pixels(0.12))
    for live in attackers:
        if live.dead:
            continue
        cx, cy = _world_to_pixel(live.body.pos)
        draw.ellipse(
            [(cx - reach_px, cy - reach_px), (cx + reach_px, cy + reach_px)],
            outline=(255, 120, 120, 200),
            width=1,
        )
        draw.ellipse(
            [(cx - dot_r, cy - dot_r), (cx + dot_r, cy + dot_r)],
            fill=(255, 60, 60, 255),
            outline=(255, 200, 200, 255),
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(world: dict, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(world: dict, frames: int) -> dict:
    defenders: List[Defender] = world["defenders"]
    attackers: List[LiveAttacker] = world["attackers"]
    positions_finite = all(
        np.isfinite(d.pos[0]) and np.isfinite(d.pos[1]) for d in defenders
    ) and all(
        np.isfinite(a.body.pos[0]) and np.isfinite(a.body.pos[1])
        for a in attackers
    )
    return {
        "frames": int(frames),
        "total_spawns": int(world["total_spawns"]),
        "live_attackers": int(sum(1 for a in attackers if not a.dead)),
        "attackers_killed": int(world["attackers_killed"]),
        "defender_hp": [float(d.hp) for d in defenders],
        "damage_dealt_to": [float(x) for x in world["damage_dealt_to"]],
        "hp_samples": list(world["hp_samples"]),
        "nan_seen": bool(world["nan_seen"]),
        "positions_finite": bool(positions_finite),
        "wave_finished": bool(world["schedule"].finished),
    }


def print_summary(summary: dict) -> None:
    print("hello_iso summary")
    print(f"  stepped frames       : {summary['frames']}")
    print(f"  total spawns         : {summary['total_spawns']}")
    print(f"  wave schedule done   : {summary['wave_finished']}")
    print(f"  attackers killed     : {summary['attackers_killed']}")
    print(f"  live attackers       : {summary['live_attackers']}")
    for i, hp in enumerate(summary["defender_hp"]):
        dmg = summary["damage_dealt_to"][i]
        print(
            f"  defender[{i}]         : hp={hp:.2f}  "
            f"damage_taken={dmg:.2f}"
        )
    print("  defender hp samples (frame, [hp_0, hp_1], live_attackers):")
    for s in summary["hp_samples"]:
        hp_str = ", ".join(f"{v:.2f}" for v in s["defender_hp"])
        print(
            f"    frame {s['frame']:>4d}  hp=[{hp_str}]  "
            f"live={s['live_attackers']}"
        )
    print(f"  positions finite     : {summary['positions_finite']}")
    print(f"  any non-finite state : {summary['nan_seen']}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Iso — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/30 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_iso.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_iso.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    world = build_world()
    step_world(world, frames, DEFAULT_DT)
    summary = summarise(world, frames)
    print_summary(summary)

    if render:
        out_path = save_render(world, Path(out))
        print(f"  rendered to          : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_iso: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
