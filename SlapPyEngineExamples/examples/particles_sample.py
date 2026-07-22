"""Visual demo of the contact-driven particle system.

Renders a single composite frame showing every emission style at
once -- shatter, spark, splatter, splash, ember, and dust -- after a
short simulated burst.  Writes ``examples/particles_sample.png``.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from pharos_engine.physics.particles import ParticleSystem

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - dev environment
    raise SystemExit("PIL/Pillow is required to write the sample image") from exc


def main() -> None:
    rng = random.Random(2025)
    ps = ParticleSystem(
        gravity=(0.0, 240.0),
        air_drag=0.6,
        max_particles=8192,
        rng=rng,
    )

    # World view: 0..640 x 0..360 (16:9-ish).
    W, H = 640, 360
    view = (0.0, 0.0, float(W), float(H))

    # One burst per style, laid out horizontally.
    bursts = [
        ("stone",  ( 80, 220), (0.0, -1.0)),   # shatter
        ("iron",   (200, 220), (0.2, -1.0)),   # spark
        ("mud",    (320, 220), (0.0, -1.0)),   # splatter
        ("water",  (440, 220), (-0.1, -1.0)),  # splash
        ("lava",   (560, 220), (0.1, -1.0)),   # ember
        ("sand",   (620, 220), (0.0, -1.0)),   # dust
    ]
    for mat, pt, imp in bursts:
        ps.emit(pt, imp, mat, count=80)

    # Simulate for a short time so they spread.
    dt = 1.0 / 60.0
    for _ in range(18):  # 0.3s
        ps.step(dt)

    # Compose frame: dark wasteland-ish background.
    frame = np.zeros((H, W, 4), dtype=np.uint8)
    frame[..., 0] = 18
    frame[..., 1] = 20
    frame[..., 2] = 28
    frame[..., 3] = 255

    # Floor line for context.
    frame[250:252, :, :3] = (60, 50, 40)

    ps.render(frame, world_view=view)

    out_path = Path(__file__).resolve().parent / "particles_sample.png"
    Image.fromarray(frame, mode="RGBA").save(out_path)
    print(f"wrote {out_path}  (live particles: {ps.count})")


if __name__ == "__main__":
    main()
