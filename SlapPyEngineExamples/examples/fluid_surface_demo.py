"""Fluid surface — dense PBF pool rendered as a marching-squares blob.

Roughly 1.4x the particle count of the basic ``fluid_demo`` (smaller
spacing → finer surface detail) plus the full watery shader stack on
the surface mode side (Lambert + rim + turbulence-foam + refraction +
godrays + specular + droplet-tail crossfade for sparse splash
particles).

Emits a side-by-side gif comparing the disc-splat view (left) to the
shaded isosurface + droplet tails (right) so the visual win is obvious.
Also reports per-frame wall-clock as a perf sanity check.

Run:
    python examples/fluid_surface_demo.py

Output:
    examples/output/fluid/surface_overlay.gif
    examples/output/fluid/surface_overlay_perf.txt
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine.fluid import (
    FluidRenderConfig,
    FluidRenderer,
    FluidWorld,
    pbf_step,
)
from slappyengine.media import save_frames


def _make_pool() -> FluidWorld:
    w = FluidWorld()
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -1.2
    w.config["wall_x_max"] = 1.2
    # Denser pool: smaller spacing (0.04 vs the basic demo's 0.06) and more cells.
    # 14 × 12 = 168 particles vs the basic demo's 64 — ~2.6× denser fluid.
    w.add_block_of_particles(
        "water", nx=14, ny=12, spacing=0.04,
        origin=(-0.28, 3.2), jitter=0.04,
    )
    return w


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
        "surface_light_dir": [-0.5, -0.85],
    })
    return FluidRenderer(config=splat_cfg), FluidRenderer(config=surf_cfg)


def _render_pair(
    splat_r: FluidRenderer,
    surf_r: FluidRenderer,
    world: FluidWorld,
    view_box,
) -> Image.Image:
    a = splat_r.render(world, view_box=view_box)
    b = surf_r.render(world, view_box=view_box)
    H, _, _ = a.shape
    divider = np.full((H, 4, 4), 30, dtype=np.uint8)
    divider[..., 3] = 255
    stitched = np.concatenate([a, divider, b], axis=1)
    return Image.fromarray(stitched, mode="RGBA").convert("RGB")


def main(out_path: Path | None = None, frames: int = 180) -> Path:
    out_path = out_path or Path(__file__).parent / "output" / "fluid" / "surface_overlay.gif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    perf_path = out_path.with_name("surface_overlay_perf.txt")

    world = _make_pool()
    splat_r, surf_r = _make_pair(280, 220)
    view_box = (-1.4, 2.5, 1.4, 5.3)

    pil_frames: list[Image.Image] = []
    sim_times: list[float] = []
    render_times: list[float] = []
    surf_only_times: list[float] = []

    for f in range(frames):
        t0 = time.perf_counter()
        pbf_step(world)
        t1 = time.perf_counter()
        a = splat_r.render(world, view_box=view_box)
        t_surf0 = time.perf_counter()
        b = surf_r.render(world, view_box=view_box)
        t_surf1 = time.perf_counter()
        H, _, _ = a.shape
        divider = np.full((H, 4, 4), 30, dtype=np.uint8)
        divider[..., 3] = 255
        stitched = np.concatenate([a, divider, b], axis=1)
        pil_frames.append(Image.fromarray(stitched, mode="RGBA").convert("RGB"))
        t2 = time.perf_counter()
        sim_times.append((t1 - t0) * 1000.0)
        render_times.append((t2 - t1) * 1000.0)
        surf_only_times.append((t_surf1 - t_surf0) * 1000.0)

    save_frames(pil_frames, out_path, fps=30)

    sim_mean = float(np.mean(sim_times))
    render_mean = float(np.mean(render_times))
    sim_p95 = float(np.percentile(sim_times, 95))
    surf_mean = float(np.mean(surf_only_times))
    surf_p95 = float(np.percentile(surf_only_times, 95))
    perf_msg = (
        f"particles: {world.particles.count}\n"
        f"frames: {frames}\n"
        f"sim ms/frame   mean={sim_mean:.2f}  p95={sim_p95:.2f}\n"
        f"render ms/frame mean={render_mean:.2f}  "
        f"(splat + watery surface stitched)\n"
        f"surface-only ms/frame mean={surf_mean:.2f} p95={surf_p95:.2f}\n"
        f"total wall ms/frame   mean={sim_mean + render_mean:.2f}\n"
    )
    perf_path.write_text(perf_msg, encoding="utf-8")

    print(f"wrote {out_path}")
    print(perf_msg.rstrip())
    print(f"perf log: {perf_path}")
    return out_path


if __name__ == "__main__":
    main()
