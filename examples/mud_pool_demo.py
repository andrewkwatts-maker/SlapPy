"""Mud pool with a water layer on top — both run from one ParticleField.

Demonstrates the unified physics base in
:mod:`slappyengine.physics.particle_field`. Mud (binding_force > 0) sits
at the bottom as a per-pixel mask; water (binding_force = 0) keeps
integrating each frame and bounces off the mud surface. Both materials
share the same gravity, the same per-pixel collision mask, and the same
render pipeline.

Run:
    python examples/mud_pool_demo.py
    python examples/mud_pool_demo.py --frames 200 --render discs
    python examples/mud_pool_demo.py --render marching_squares

Output:
    examples/output/particles/mud_pool[_<mode>].gif
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from slappyengine.physics.particle_field import (
    MUD_MAT,
    ParticleField,
    WATER,
)


W, H = 480, 320
MUD_TOP_Y = 230
WATER_BAND = (60, 200)  # x range water particles spawn over
BLAST_X = W // 2
BLAST_FRAME = 12
CRATER_RADIUS = 40
CRATER_DEPTH = 18


def _sky_gradient(arr: np.ndarray) -> None:
    top, bot = (12, 22, 50), (60, 110, 175)
    for y in range(H):
        t = y / H
        arr[y, :, 0] = int(top[0] + (bot[0] - top[0]) * t)
        arr[y, :, 1] = int(top[1] + (bot[1] - top[1]) * t)
        arr[y, :, 2] = int(top[2] + (bot[2] - top[2]) * t)


def main(frames: int = 220, render_mode: str = "discs") -> Path:
    rng = np.random.default_rng(2026)
    field = ParticleField(width=W, height=H, gravity=720.0)
    field.fill_ground(top_y=MUD_TOP_Y,
                      color=MUD_MAT.color,
                      sub_color=(50, 32, 16))

    # Pre-fill a basin of water sitting on top of the mud (just particles,
    # not part of the mask). The water layer settles into the dip first,
    # then the explosion will throw mud up through it.
    water_mid = field.material_id_of("water")
    n_water = 700
    water_pos = np.column_stack([
        rng.uniform(WATER_BAND[0], WATER_BAND[1], n_water),
        rng.uniform(MUD_TOP_Y - 50, MUD_TOP_Y - 1, n_water),
    ]).astype(np.float32)
    water_vel = np.zeros((n_water, 2), dtype=np.float32)
    field.spawn_batch(
        pos=water_pos,
        vel=water_vel,
        material_ids=np.full(n_water, water_mid, dtype=np.int32),
        radii=np.full(n_water, 1.0, dtype=np.float32),
    )

    frames_out: list[Image.Image] = []
    spawned_blast = False
    for f in range(frames):
        if f == BLAST_FRAME and not spawned_blast:
            spawned_blast = True
            # Carve the crater bowl out of the mud mask.
            bowl = np.zeros((H, W), dtype=bool)
            for col in range(W):
                dx = col - BLAST_X
                if abs(dx) > CRATER_RADIUS:
                    continue
                depth = int(CRATER_DEPTH * (1.0 - (dx / CRATER_RADIUS) ** 2))
                bowl[MUD_TOP_Y:MUD_TOP_Y + depth + 1, col] = True
            field.carve(bowl)
            # Spawn 500 mud chunks flying upward + outward.
            mud_mid = field.material_id_of("mud")
            n_mud = 500
            angles = rng.uniform(-math.radians(55), math.radians(55), n_mud)
            speeds = rng.uniform(160.0, 360.0, n_mud)
            offs = rng.uniform(-CRATER_RADIUS, CRATER_RADIUS, n_mud)
            mud_pos = np.column_stack([
                BLAST_X + offs,
                np.full(n_mud, MUD_TOP_Y - 2.0),
            ]).astype(np.float32)
            mud_vel = np.column_stack([
                np.sin(angles) * speeds + offs * 2.0,  # edge boost
                -np.cos(angles) * speeds,
            ]).astype(np.float32)
            field.spawn_batch(
                pos=mud_pos,
                vel=mud_vel,
                material_ids=np.full(n_mud, mud_mid, dtype=np.int32),
                radii=rng.integers(2, 4, n_mud).astype(np.float32),
            )

        field.step(1.0 / 30.0)

        # Compose frame: sky + field render.
        sky = np.zeros((H, W, 3), dtype=np.uint8)
        _sky_gradient(sky)
        fg = field.render(mode=render_mode)
        # Where the field has solid pixels (alpha>0 in mask OR live
        # particle pixels), use the field render; else use sky.
        solid_mask = (field.mask[..., 3] > 0) | (fg.sum(axis=-1) > 0)
        sky[solid_mask] = fg[solid_mask]
        im = Image.fromarray(sky, mode="RGB")
        d = ImageDraw.Draw(im)
        d.text((8, 8), f"mud + water  render={render_mode}",
               fill=(240, 240, 240))
        d.text((8, 22), f"f={f}  active cells={field.region_grid.active_cell_count()}",
               fill=(200, 200, 200))
        frames_out.append(im)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if render_mode == "discs" else f"_{render_mode}"
    out_path = out_dir / f"mud_pool{suffix}.gif"
    frames_out[0].save(
        out_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=33,
        loop=0,
        optimize=False,
    )
    print(f"wrote {out_path}")
    print(f"  particles: {field.pos.shape[0]}")
    print(f"  active cells: {field.region_grid.active_cell_count()}")
    print(f"  static cells: {field.region_grid.static_cell_count()}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=int, default=220)
    ap.add_argument("--render", default="discs",
                    choices=["discs", "marching_squares"])
    args = ap.parse_args()
    main(frames=args.frames, render_mode=args.render)
