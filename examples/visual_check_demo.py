"""Fast visual regression check for the particle physics system.

Renders a SHORT scenario (60 frames @ 200×140 px) for each of the 5 builtin
splatter presets — sand, mud, sloppy, rock, snow — and composites them into
a single 1×5 grid GIF. Designed to be run at every refactor checkpoint so
the user can flip through the file and visually confirm nothing regressed:
airborne ejecta, landing, sliding, settling all in one ~2 second clip.

Deterministic (seed=2026) so re-runs produce byte-identical output unless
behaviour actually changed.

Usage:
    cd h:/Github/SlapPyEngine && PYTHONPATH=python python examples/visual_check_demo.py

Output:
    examples/output/particles/visual_check.gif
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from slappyengine.physics.blast import detonate
from slappyengine.physics.particle_field import ParticleField
from slappyengine.physics.splatter_presets import (
    SplatterPreset,
    get as get_preset,
)


PRESET_NAMES = ("sand", "mud", "sloppy", "rock", "snow")
CELL_W, CELL_H = 200, 140
GROUND_Y = 100
BLAST_X = CELL_W // 2
BLAST_FRAME = 5
CRATER_RADIUS = 22
CRATER_DEPTH = 14
FRAMES = 60
DT = 1.0 / 30.0
SEED = 2026


# ── Per-preset palette helpers — mirrors sand_crater_demo._ground_for_preset
# and ._bg_for_preset so the visual diff reads the same as the canonical
# single-preset demo.

def _bg_for_preset(p: SplatterPreset) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if p.name == "snow":
        return ((30, 38, 58), (170, 184, 210))
    if p.name in ("mud", "sloppy"):
        return ((18, 14, 8), (40, 30, 18))
    if p.name == "rock":
        return ((8, 10, 18), (30, 36, 50))
    return ((10, 14, 28), (40, 56, 92))


def _ground_for_preset(p: SplatterPreset) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if p.name == "snow":
        return ((232, 240, 250), (130, 150, 175))
    if p.name in ("mud", "sloppy"):
        return ((90, 64, 32), (40, 28, 14))
    if p.name == "rock":
        return ((130, 124, 116), (60, 56, 50))
    return ((200, 162, 90), (60, 44, 28))


def _sky(arr: np.ndarray, top: tuple[int, int, int], bot: tuple[int, int, int]) -> None:
    h = arr.shape[0]
    for y in range(h):
        t = y / h
        arr[y, :, 0] = int(top[0] + (bot[0] - top[0]) * t)
        arr[y, :, 1] = int(top[1] + (bot[1] - top[1]) * t)
        arr[y, :, 2] = int(top[2] + (bot[2] - top[2]) * t)


def _stats(field: ParticleField) -> dict:
    """Per-preset numeric snapshot used for the regression summary."""
    solid_now = field.mask[..., 3] > 0
    col_has = solid_now.any(axis=0)
    top_y = np.where(col_has, solid_now.argmax(axis=0), GROUND_Y).astype(np.int32)
    crater_max = int((top_y - GROUND_Y).max(initial=0))
    pile_max = int((GROUND_Y - top_y).max(initial=0))
    return {
        "settled": int(field.settled.sum()),
        "baked": int(field.bake_flag.sum()),
        "total": int(field.settled.size),
        "pile_max": pile_max,
        "crater_max": crater_max,
    }


def run_preset(preset: SplatterPreset) -> tuple[list[Image.Image], dict]:
    """Run one preset, return (per-frame cell images, final stats)."""
    rng = np.random.default_rng(SEED)
    field = ParticleField(width=CELL_W, height=CELL_H, gravity=preset.gravity)
    ground_top, ground_sub = _ground_for_preset(preset)
    field.fill_ground(top_y=GROUND_Y, color=ground_top, sub_color=ground_sub)

    sky_top, sky_bot = _bg_for_preset(preset)
    sky_buf = np.zeros((CELL_H, CELL_W, 3), dtype=np.uint8)
    _sky(sky_buf, sky_top, sky_bot)

    frames_out: list[Image.Image] = []
    spawned = False
    for f in range(FRAMES):
        if f == BLAST_FRAME and not spawned:
            spawned = True
            detonate(
                field, preset,
                x=float(BLAST_X), y=float(GROUND_Y),
                crater_radius=float(CRATER_RADIUS),
                crater_depth=float(CRATER_DEPTH),
                rng=rng,
            )

        field.step(DT)

        fg = field.render(mode="discs")
        composed = sky_buf.copy()
        solid = field.mask[..., 3] > 0
        live = fg.sum(axis=-1) > 0
        mask = solid | live
        composed[mask] = fg[mask]

        im = Image.fromarray(composed, mode="RGB")
        d = ImageDraw.Draw(im)
        n_baked = int(field.bake_flag.sum())
        n_total = int(field.settled.size)
        # Cell label (top), tight rows so it fits in 140 px.
        d.text((4, 2), preset.name, fill=(255, 255, 255))
        d.text((4, 14), f"f{f:02d}  {n_baked}/{n_total}", fill=(220, 220, 220))
        frames_out.append(im)

    return frames_out, _stats(field)


def main() -> None:
    t0 = time.perf_counter()
    print(f"visual_check: rendering {len(PRESET_NAMES)} presets × {FRAMES} frames "
          f"@ {CELL_W}×{CELL_H} (seed={SEED})...")

    cell_runs: list[list[Image.Image]] = []
    all_stats: dict[str, dict] = {}
    for name in PRESET_NAMES:
        t_cell = time.perf_counter()
        cells, stats = run_preset(get_preset(name))
        cell_runs.append(cells)
        all_stats[name] = stats
        print(f"  {name:<7} {time.perf_counter() - t_cell:5.2f}s  "
              f"settled={stats['settled']:>4} baked={stats['baked']:>4} "
              f"pile_max={stats['pile_max']:>3} crater_max={stats['crater_max']:>3}")

    # ── Composite 1×5 grid frames ─────────────────────────────────────
    grid_w = CELL_W * len(PRESET_NAMES)
    grid_h = CELL_H
    grid_frames: list[Image.Image] = []
    for f in range(FRAMES):
        grid = Image.new("RGB", (grid_w, grid_h), (0, 0, 0))
        for col, cells in enumerate(cell_runs):
            grid.paste(cells[f], (col * CELL_W, 0))
        grid_frames.append(grid)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "visual_check.gif"
    grid_frames[0].save(
        out_path,
        save_all=True,
        append_images=grid_frames[1:],
        duration=33,
        loop=0,
        optimize=False,
    )

    elapsed = time.perf_counter() - t0
    size_kb = out_path.stat().st_size / 1024.0
    print()
    print(f"wrote: {out_path}  ({size_kb:.1f} KB)")
    print(f"total runtime: {elapsed:.2f}s")
    print("stats summary (settled/baked  pile_max  crater_max):")
    for name in PRESET_NAMES:
        s = all_stats[name]
        print(f"  {name:<7} settled={s['settled']:>4}/{s['total']}  "
              f"baked={s['baked']:>4}  pile_max={s['pile_max']:>3}  "
              f"crater_max={s['crater_max']:>3}")


if __name__ == "__main__":
    main()
