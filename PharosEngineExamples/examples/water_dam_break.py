"""Classic dam-break: a tall column of water collapses inside a wide basin.

A column 8 wide x 30 tall is dropped in the left corner of a wide walled
basin. As it falls, the front collapses outward and the column splashes
against the right wall before settling.

The output is a side-by-side GIF: particle disc-splat on the left, the
shaded surface ("watery" shader stack: Lambert + rim + turbulence-foam
+ refraction + godrays + specular, with sparse splash droplets fading in
as tails) on the right. Splash + breakup look obviously wetter on the
right hand side, especially when the dam-front first hits the
opposite wall.

Run:
    PYTHONPATH=python python examples/water_dam_break.py

Output:
    examples/output/fluid/dam_break.gif
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image

from pharos_engine.fluid import FluidRenderConfig, FluidRenderer, pbf_step
from pharos_engine.media import save_frames
from pharos_engine.studio import fluid_stage, output_path


_DIVIDER_PX = 4


def _make_pair(width: int, height: int) -> tuple[FluidRenderer, FluidRenderer]:
    splat_cfg = FluidRenderConfig.from_yaml({
        "width": width, "height": height,
        "surface_mode": False,
    })
    surf_cfg = FluidRenderConfig.from_yaml({
        "width": width, "height": height,
        "surface_mode": True,
        "dual_view": True,
        "surface_turbulence_enabled": True,
        "surface_refraction_enabled": True,
        "surface_godrays_enabled": True,
        "surface_specular_enabled": True,
        # Light from upper-left so the right-wall splash gets a bright
        # rim/spec when the dam front impacts.
        "surface_light_dir": [-0.6, -0.8],
    })
    return FluidRenderer(config=splat_cfg), FluidRenderer(config=surf_cfg)


def main(frames: int = 360) -> Path:
    stage = fluid_stage(
        view_box=(-2.0, 1.0, 2.0, 5.3), width=480, height=360,
        floor_y=5.0, walls=(-1.8, 1.8),
        pool=dict(material="water", nx=8, ny=30, spacing=0.06,
                  origin=(-1.7, 3.1), jitter=0.02),
    )

    splat_r, surf_r = _make_pair(360, 270)
    out = output_path("dam_break", __file__, subdir="fluid")
    pil_frames: list[Image.Image] = []
    surf_times: list[float] = []
    for _ in range(frames):
        pbf_step(stage.fluid)
        a = splat_r.render(stage.fluid, view_box=stage.view_box)
        t0 = time.perf_counter()
        b = surf_r.render(stage.fluid, view_box=stage.view_box)
        surf_times.append((time.perf_counter() - t0) * 1000.0)
        H, _, _ = a.shape
        divider = np.full((H, _DIVIDER_PX, 4), 30, dtype=np.uint8)
        divider[..., 3] = 255
        stitched = np.concatenate([a, divider, b], axis=1)
        pil_frames.append(Image.fromarray(stitched, mode="RGBA").convert("RGB"))

    save_frames(pil_frames, out, fps=30)

    fluid = stage.fluid
    speeds = np.linalg.norm(fluid.particles.vel, axis=1)
    peak_v = float(speeds.max())
    count = int(fluid.particles.count)
    surface_y = float(fluid.particles.pos[:, 1].min())
    pool_depth = float(fluid.floor_y) - surface_y
    surf_mean = float(np.mean(surf_times))
    surf_p95 = float(np.percentile(surf_times, 95))
    print(f"wrote {out}")
    print(f"particles: {count}")
    print(f"peak |v|: {peak_v:.3f}")
    print(f"final pool depth: {pool_depth:.3f} (surface y={surface_y:.3f}, "
          f"floor_y={fluid.floor_y})")
    print(f"surface render ms: mean={surf_mean:.2f} p95={surf_p95:.2f}")
    return out


if __name__ == "__main__":
    main()
