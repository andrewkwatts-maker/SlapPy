"""Minimal PBF demo: drop a column of water into a walled basin.

Renders TWO views side-by-side every frame so you can directly compare:
* Left: particle disc-splat (every PBF particle as a tinted dot).
* Right: marching-squares surface with the watery shader stack
  (Lambert + rim + turbulence-foam + refraction + godrays + specular)
  blended with droplet tails for isolated splash particles
  (``surface_mode=True`` + ``dual_view=True``).

Run:
    python examples/fluid_demo.py

Output:
    examples/output/fluid/water_basin.gif
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine.fluid import FluidRenderConfig, FluidRenderer, pbf_step
from slappyengine.media import save_frames
from slappyengine.studio import fluid_stage, output_path


_DIVIDER_PX = 4


def _make_pair(width: int, height: int) -> tuple[FluidRenderer, FluidRenderer]:
    """Splat renderer + watery-surface renderer (dual-view crossfade ON)."""
    splat_cfg = FluidRenderConfig.from_yaml({
        "width": width, "height": height,
        "surface_mode": False,
    })
    surf_cfg = FluidRenderConfig.from_yaml({
        "width": width, "height": height,
        "surface_mode": True,
        "dual_view": True,
        # Polish defaults are ON in the dataclass; pin them here so the
        # demo's "watery look" is stable across yaml edits.
        "surface_turbulence_enabled": True,
        "surface_refraction_enabled": True,
        "surface_godrays_enabled": True,
        "surface_specular_enabled": True,
        "surface_light_dir": [-0.55, -0.85],
    })
    return FluidRenderer(config=splat_cfg), FluidRenderer(config=surf_cfg)


def _compose(left: np.ndarray, right: np.ndarray) -> Image.Image:
    H, W, _ = left.shape
    divider = np.full((H, _DIVIDER_PX, 4), 30, dtype=np.uint8)
    divider[..., 3] = 255
    stitched = np.concatenate([left, divider, right], axis=1)
    return Image.fromarray(stitched, mode="RGBA").convert("RGB")


def main(frames: int = 360) -> Path:
    stage = fluid_stage(
        view_box=(-1.6, 2.0, 1.6, 5.3), width=384, height=288,
        floor_y=5.0, walls=(-1.2, 1.2),
        pool=dict(material="water", nx=14, ny=10, spacing=0.06,
                   origin=(-0.42, 2.4), jitter=0.05),
    )
    fluid = stage.fluid

    splat_r, surf_r = _make_pair(384, 288)
    out = output_path("water_basin", __file__, subdir="fluid")
    pil_frames: list[Image.Image] = []
    surf_times: list[float] = []
    for _ in range(frames):
        pbf_step(fluid)
        a = splat_r.render(fluid, view_box=stage.view_box)
        t0 = time.perf_counter()
        b = surf_r.render(fluid, view_box=stage.view_box)
        surf_times.append((time.perf_counter() - t0) * 1000.0)
        pil_frames.append(_compose(a, b))

    save_frames(pil_frames, out, fps=30)

    speeds = np.linalg.norm(fluid.particles.vel, axis=1)
    surf_mean = float(np.mean(surf_times))
    surf_p95 = float(np.percentile(surf_times, 95))
    print(f"wrote {out}")
    print(f"particles: {fluid.particles.count}")
    print(f"final |v| max={speeds.max():.3f} mean={speeds.mean():.3f}")
    print(f"top of pool y={float(fluid.particles.pos[:,1].min()):.3f} "
          f"floor_y={fluid.floor_y}")
    print(f"surface render ms: mean={surf_mean:.2f} p95={surf_p95:.2f}")
    return out


if __name__ == "__main__":
    main()
