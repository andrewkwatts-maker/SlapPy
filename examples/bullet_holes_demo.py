"""Bullet holes — high-velocity drilling through terrain.

Demonstrates per-particle drilling on :class:`ParticleField`. A burst of
"bullets" (custom :class:`Material` with high ``drill_max_px`` and low
``binding_force``) fires from the left, drills through a stone wall in
the middle, ejects per-pixel debris carrying the wall's colour, and
exits out the right. Configurable knobs on the bullet material:

* ``drill_max_px``      — max pixels a bullet can punch through
* ``drill_velocity_loss`` — per-pixel velocity multiplier (0.95 = barely
                           slows; 0.5 = heavy braking)
* ``drill_eject_gain``  — fraction of drilled volume re-emitted as
                           debris (1.0 = full mass conservation; 0.0 =
                           clean tunnel, no ejecta)
* ``mass_conservation`` — system-wide multiplier on the above

Output:
    examples/output/particles/bullet_holes.gif
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from slappyengine.physics.particle_field import Material, ParticleField


W, H = 640, 240
WALL_X0, WALL_X1 = 280, 320
WALL_Y0, WALL_Y1 = 40, 200
N_BULLETS = 14
SHOTS_PER_FRAME = 1
FRAMES = 130


def main() -> Path:
    rng = np.random.default_rng(2026)
    field = ParticleField(width=W, height=H, gravity=0.0)

    # Bullet material — high drill, low binding (gets through easy),
    # lots of ejecta (mass conservation).
    bullet = Material(
        name="bullet",
        binding_force=2.0e3,
        drill_max_px=20,
        drill_velocity_loss=0.93,   # bullet keeps most velocity per px
        drill_eject_gain=2.0,        # 20 drilled → ~40 ejecta particles
        mass_conservation=1.0,
        gravity_scale=0.0,
        air_drag_per_sec=1.0,
        radius_min=1,
        radius_max=1,
        color=(255, 220, 100),
    )
    field.materials.append(bullet)
    field._name_to_id["bullet"] = len(field.materials) - 1

    # Build a stone wall in the middle.
    for x in range(WALL_X0, WALL_X1):
        for y in range(WALL_Y0, WALL_Y1):
            # Subtle colour variation so the eject debris reads as stone.
            field.mask[y, x, 0] = 110 + int(rng.integers(-15, 15))
            field.mask[y, x, 1] = 102 + int(rng.integers(-15, 15))
            field.mask[y, x, 2] = 96 + int(rng.integers(-15, 15))
            field.mask[y, x, 3] = 255
    field._fixed_mask[WALL_Y0:WALL_Y1, WALL_X0:WALL_X1] = True

    frames_out: list[Image.Image] = []
    bullets_fired = 0
    for f in range(FRAMES):
        if bullets_fired < N_BULLETS and f % 4 == 0:
            # Fire one bullet per 4 frames from the left.
            y0 = WALL_Y0 + int(rng.uniform(0, WALL_Y1 - WALL_Y0))
            field.spawn(
                x=20.0, y=float(y0),
                vx=1800.0, vy=float(rng.uniform(-20, 20)),
                material="bullet", radius=1,
            )
            bullets_fired += 1

        field.step(1.0 / 60.0)

        # Background gradient + composite the field.
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        for y in range(H):
            t = y / H
            arr[y, :, 0] = int(15 + 25 * t)
            arr[y, :, 1] = int(20 + 30 * t)
            arr[y, :, 2] = int(40 + 40 * t)
        fg = field.render(mode="discs")
        solid = field.mask[..., 3] > 0
        live = fg.sum(axis=-1) > 0
        m = solid | live
        arr[m] = fg[m]
        im = Image.fromarray(arr, mode="RGB")
        d = ImageDraw.Draw(im)
        d.text((8, 8), "Bullet holes — high-velocity drilling",
               fill=(240, 240, 240))
        d.text((8, 22),
               f"f={f}  bullets={bullets_fired}  particles={field.pos.shape[0]}",
               fill=(200, 200, 200))
        frames_out.append(im)

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bullet_holes.gif"
    frames_out[0].save(
        out_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=33,
        loop=0,
        optimize=False,
    )
    # Count holes in the wall = pixels that USED to be solid and are now empty.
    cleared_in_wall = (field.mask[WALL_Y0:WALL_Y1, WALL_X0:WALL_X1, 3] == 0).sum()
    print(f"wrote {out_path}")
    print(f"  bullets fired: {bullets_fired}")
    print(f"  wall pixels drilled away: {int(cleared_in_wall)}")
    print(f"  total particles (bullets + ejecta): {field.pos.shape[0]}")
    return out_path


if __name__ == "__main__":
    main()
