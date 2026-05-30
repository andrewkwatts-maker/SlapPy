"""Crater explosion demo — preset-driven, runs on ParticleField.

All physics now lives in :class:`slappyengine.physics.particle_field.ParticleField`;
this demo just configures a field, fills the ground, and calls
:func:`slappyengine.physics.blast.detonate` once on the blast frame. The
preset's knobs (cone, speeds, KE binding, drill, slump cohesion, bake
radius, settle jitter, up/radial blast boosts) drive everything.

Usage:
    python examples/sand_crater_demo.py                     # sand preset
    python examples/sand_crater_demo.py --preset mud
    python examples/sand_crater_demo.py --all               # one gif per preset
    python examples/sand_crater_demo.py --render marching_squares

Output:
    examples/output/particles/sand_crater[_<preset>][_<mode>].gif
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from slappyengine.physics.blast import detonate
from slappyengine.physics.particle_field import ParticleField
from slappyengine.physics.splatter_presets import (
    PRESETS,
    SplatterPreset,
    get as get_preset,
)


W, H = 640, 360
GROUND_Y = 280
BLAST_X = W // 2
BLAST_FRAME = 10
CRATER_RADIUS = 60
CRATER_DEPTH = 28


# ── Per-preset palette helpers (sky + ground only — particle colours
# now come from the *original pixels* via blast.detonate sampling). ──

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


def run_preset(
    preset: SplatterPreset,
    *,
    frames: int = 130,
    render_mode: str = "discs",
) -> Path:
    rng = np.random.default_rng(2026)
    field = ParticleField(width=W, height=H, gravity=preset.gravity)
    ground_top, ground_sub = _ground_for_preset(preset)
    field.fill_ground(top_y=GROUND_Y, color=ground_top, sub_color=ground_sub)

    sky_top, sky_bot = _bg_for_preset(preset)
    sky_buf = np.zeros((H, W, 3), dtype=np.uint8)
    _sky(sky_buf, sky_top, sky_bot)

    frames_out: list[Image.Image] = []
    spawned = False
    for f in range(frames):
        if f == BLAST_FRAME and not spawned:
            spawned = True
            n_spawned = detonate(
                field, preset,
                x=float(BLAST_X), y=float(GROUND_Y),
                crater_radius=float(CRATER_RADIUS),
                crater_depth=float(CRATER_DEPTH),
                rng=rng,
            )
            assert n_spawned > 0

        field.step(1.0 / 30.0)

        fg = field.render(mode=render_mode)
        composed = sky_buf.copy()
        # Where the field has any solid mask OR any live-particle pixel,
        # composite the field on top of the sky.
        solid = field.mask[..., 3] > 0
        live = fg.sum(axis=-1) > 0
        mask = solid | live
        composed[mask] = fg[mask]

        im = Image.fromarray(composed, mode="RGB")
        d = ImageDraw.Draw(im)
        d.text((8, 8), f"preset: {preset.name}", fill=(255, 255, 255))
        d.text(
            (8, 22),
            f"cone +/-{preset.max_blast_angle_deg:.0f}deg  "
            f"g/c={preset.n_grains}/{preset.n_chunks}  "
            f"coh={preset.cohesion:.2f}",
            fill=(220, 220, 220),
        )
        frames_out.append(im)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if preset.name == "sand" else f"_{preset.name}"
    if render_mode != "discs":
        suffix += f"_{render_mode}"
    out_path = out_dir / f"sand_crater{suffix}.gif"
    frames_out[0].save(
        out_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=33,
        loop=0,
        optimize=False,
    )

    # Stats: read the field's mask + region grid (consolidated).
    solid_now = field.mask[..., 3] > 0
    col_has = solid_now.any(axis=0)
    top_y = np.where(col_has, solid_now.argmax(axis=0), GROUND_Y).astype(np.int32)
    crater = int((top_y - GROUND_Y).max(initial=0))
    pile = int((GROUND_Y - top_y).max(initial=0))
    n_settled = int(field.settled.sum())
    n_baked = int(field.bake_flag.sum())

    print(f"[{preset.name}]")
    print(f"  wrote: {out_path}")
    print(f"  grains/chunks: {preset.n_grains}/{preset.n_chunks}  "
          f"total: {preset.n_grains + preset.n_chunks}")
    print(f"  settled: {n_settled}  baked: {n_baked}")
    print(f"  crater max depth: {crater}px   pile max: {pile}px")
    print(f"  cohesion: {preset.cohesion:.2f}  slump: {preset.slump_angle_deg:.0f}deg")
    print(f"  up_boost: {preset.blast_up_boost:.0f}  "
          f"radial_boost: {preset.blast_radial_boost:.0f}  "
          f"edge_boost: {preset.edge_outward_boost:.0f}")
    print(f"  regions: {field.region_grid.static_cell_count()} static, "
          f"{field.region_grid.active_cell_count()} active")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default="sand", choices=list(PRESETS))
    ap.add_argument("--all", action="store_true",
                    help="render one gif per preset")
    ap.add_argument("--frames", type=int, default=130)
    ap.add_argument("--render", default="discs",
                    choices=["discs", "marching_squares"])
    args = ap.parse_args()

    if args.all:
        for name in PRESETS:
            run_preset(get_preset(name), frames=args.frames,
                       render_mode=args.render)
    else:
        run_preset(get_preset(args.preset), frames=args.frames,
                   render_mode=args.render)


if __name__ == "__main__":
    main()
