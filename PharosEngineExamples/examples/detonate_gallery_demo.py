"""Crater config gallery — 6 detonation variants side-by-side.

Renders six different blasts using the SAME preset but different
:class:`DetonateCurves` settings, so you can A/B the new shaping knobs
without re-rendering each one manually.

The gallery lays out 2 rows × 3 cols:

  +-----------------+-----------------+-----------------+
  | smooth bowl     | noisy bowl      | cone-shape bowl |
  |  curve_pow=2.0  |  noise=0.4      |  curve_pow=1.0  |
  +-----------------+-----------------+-----------------+
  | fountain        | side-blast 45°  | flat splash     |
  |  up_scale=2.0   |  direction=45°  |  lateral=2.0    |
  +-----------------+-----------------+-----------------+

Run:
    python examples/detonate_gallery_demo.py
    python examples/detonate_gallery_demo.py --preset rock
    python examples/detonate_gallery_demo.py --preset sloppy --frames 100

Output:
    examples/output/particles/detonate_gallery_<preset>.gif
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pharos_engine.physics.blast import DetonateCurves, detonate
from pharos_engine.physics.particle_field import ParticleField
from pharos_engine.physics.splatter_presets import PRESETS, get as get_preset


CELL_W, CELL_H = 320, 200
GROUND_Y = 160
BLAST_X = CELL_W // 2
BLAST_FRAME = 8
CRATER_RADIUS = 40
CRATER_DEPTH = 22


def _make_cell(preset_name, curves, label):
    """Build a single-cell ParticleField and run the blast."""
    p = get_preset(preset_name)
    f = ParticleField(width=CELL_W, height=CELL_H, gravity=p.gravity)
    # Earthy ground; same for every cell so colour samples agree.
    f.fill_ground(top_y=GROUND_Y, color=(180, 145, 80), sub_color=(60, 44, 28))
    return f, curves, label


def _step_cell(f, p, curves, frame, rng):
    if frame == BLAST_FRAME:
        detonate(
            f, p,
            x=float(BLAST_X), y=float(GROUND_Y),
            crater_radius=float(CRATER_RADIUS),
            crater_depth=float(CRATER_DEPTH),
            rng=rng,
            curves=curves,
        )
    f.step(1.0 / 30.0)


def _composite_cell(f, label):
    sky = np.zeros((CELL_H, CELL_W, 3), dtype=np.uint8)
    for y in range(CELL_H):
        t = y / CELL_H
        sky[y, :] = (int(15 + t * 25), int(20 + t * 35), int(40 + t * 50))
    fg = f.render(mode="discs")
    solid = f.mask[..., 3] > 0
    live = fg.sum(axis=-1) > 0
    m = solid | live
    sky[m] = fg[m]
    im = Image.fromarray(sky, mode="RGB")
    d = ImageDraw.Draw(im)
    d.rectangle([(0, 0), (CELL_W - 1, 16)], fill=(0, 0, 0))
    d.text((4, 2), label, fill=(255, 255, 255))
    return im


def main(preset_name: str = "sloppy", frames: int = 110) -> Path:
    rng = np.random.default_rng(2026)
    # Six configurations.
    cells = [
        ("smooth | curve=2.0", DetonateCurves(crater_curve_pow=2.0,
                                              crater_noise=0.0)),
        ("noisy  | noise=0.4", DetonateCurves(crater_curve_pow=2.0,
                                              crater_noise=0.4)),
        ("cone   | curve=1.0", DetonateCurves(crater_curve_pow=1.0,
                                              crater_noise=0.1)),
        ("fountain | up=2.0", DetonateCurves(up_velocity_scale=2.0,
                                             lateral_velocity_scale=0.7,
                                             crater_noise=0.15)),
        ("angled | dir=+45°", DetonateCurves(blast_direction_deg=45.0,
                                             crater_noise=0.15)),
        ("splash | lat=2.0",  DetonateCurves(up_velocity_scale=0.6,
                                             lateral_velocity_scale=2.0,
                                             crater_noise=0.15)),
    ]
    fields = []
    for label, curves in cells:
        f, c, lab = _make_cell(preset_name, curves, label)
        fields.append((f, c, lab))

    p = get_preset(preset_name)
    out_frames: list[Image.Image] = []
    for fnum in range(frames):
        # Step all cells.
        for f, c, _ in fields:
            _step_cell(f, p, c, fnum, rng)
        # Composite into a 2×3 grid.
        cell_imgs = [_composite_cell(f, lab) for f, _, lab in fields]
        grid = Image.new("RGB", (CELL_W * 3, CELL_H * 2 + 24), (10, 10, 12))
        # Title.
        d = ImageDraw.Draw(grid)
        d.text((8, 4), f"detonate gallery — preset: {preset_name}  frame {fnum}",
               fill=(240, 240, 240))
        for k, im in enumerate(cell_imgs):
            cx = (k % 3) * CELL_W
            cy = 24 + (k // 3) * CELL_H
            grid.paste(im, (cx, cy))
        out_frames.append(grid)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"detonate_gallery_{preset_name}.gif"
    out_frames[0].save(
        out_path,
        save_all=True,
        append_images=out_frames[1:],
        duration=50,
        loop=0,
        optimize=False,
    )
    print(f"wrote {out_path}")
    for _, _, lab in fields:
        print(f"  cell: {lab}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default="sloppy", choices=list(PRESETS))
    ap.add_argument("--frames", type=int, default=110)
    args = ap.parse_args()
    main(args.preset, args.frames)
