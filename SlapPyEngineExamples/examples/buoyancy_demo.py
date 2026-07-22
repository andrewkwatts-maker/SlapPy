"""Buoyancy — wood floats, steel sinks (density-based Archimedes).

A wood block (density 600 kg/m^3) and a steel block (7800) of the same
size are dropped into a pool of water. The engine's
:func:`pharos_engine.fluid.apply_fluid_buoyancy` applies per-node
Archimedes upthrust to every submerged node; nodes lighter than the
water they displace rise, denser ones fall.

Output is a side-by-side GIF: particle disc-splat on the left, watery
shaded surface (Lambert + rim + turbulence-foam + refraction + godrays +
specular, with sparse splash droplets crossfading into tails) on the
right. Both renders draw the wood/steel softbody overlays so the
buoyancy behaviour reads the same way in either view.

Run:
    python examples/buoyancy_demo.py

Output:
    examples/output/buoyancy/buoyancy.gif
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from pharos_engine.fluid import (
    FluidRenderConfig,
    FluidRenderer,
    apply_fluid_buoyancy,
    apply_fluid_buoyancy_iterative,
)
from pharos_engine.media import save_frames
from pharos_engine.softbody import make_lattice_body
from pharos_engine.softbody import step as softbody_step
from pharos_engine.fluid import pbf_step
from pharos_engine.studio import fluid_with_softbody_stage, output_path


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
        "surface_light_dir": [-0.4, -0.9],
    })
    return FluidRenderer(config=splat_cfg), FluidRenderer(config=surf_cfg)


def main(frames: int = 200) -> Path:
    stage = fluid_with_softbody_stage(
        view_box=(-2.0, 2.0, 2.0, 6.2), width=480, height=320,
        floor_y=6.0, walls=(-1.8, 1.8),
        pool=dict(material="water", nx=28, ny=22, spacing=0.06,
                   origin=(-0.84, 2.7), jitter=0.04),
        settle_steps=140,
    )

    drop_y = stage.surface_y - 0.6
    wood = make_lattice_body(stage.softbody, "wood",
                              width_cells=4, height_cells=2, cell_size=0.10,
                              position=(-1.10, drop_y))
    steel = make_lattice_body(stage.softbody, "steel",
                               width_cells=4, height_cells=2, cell_size=0.10,
                               position=( 0.30, drop_y))

    # Build dual renderers; the stage's own renderer is unused so the
    # surface-mode demo gets the watery shader stack on the right.
    splat_r, surf_r = _make_pair(360, 240)
    out = output_path("buoyancy", __file__, subdir="buoyancy")
    pil_frames: list[Image.Image] = []
    splash_total = 0
    for _ in range(frames):
        # Iterative pass: 3 sub-iterations + per-column local surface
        # sampling + splash spawning. The legacy one-shot impulse
        # ``apply_fluid_buoyancy`` lets the wood block overshoot
        # equilibrium and sit above the waterline; the iterative
        # version converges within the frame. The splash side-effect
        # gives the watery-shader render real droplet events on the
        # steel impact.
        m1 = apply_fluid_buoyancy_iterative(
            stage.fluid, stage.softbody, stage.dt,
            body_meta=wood, iterations=3,
            splash_strength=0.4, splash_threshold=1.2,
        )
        m2 = apply_fluid_buoyancy_iterative(
            stage.fluid, stage.softbody, stage.dt,
            body_meta=steel, iterations=3,
            splash_strength=0.6, splash_threshold=1.2,
        )
        splash_total += int(m1["splashes_spawned"] + m2["splashes_spawned"])
        softbody_step(stage.softbody)
        pbf_step(stage.fluid)
        a = splat_r.render(stage.fluid, view_box=stage.view_box,
                           softbody=stage.softbody)
        b = surf_r.render(stage.fluid, view_box=stage.view_box,
                           softbody=stage.softbody)
        H, _, _ = a.shape
        divider = np.full((H, _DIVIDER_PX, 4), 30, dtype=np.uint8)
        divider[..., 3] = 255
        stitched = np.concatenate([a, divider, b], axis=1)
        pil_frames.append(Image.fromarray(stitched, mode="RGBA").convert("RGB"))

    save_frames(pil_frames, out, fps=30)

    wood_y = wood.centroid(stage.softbody)[1]
    steel_y = steel.centroid(stage.softbody)[1]
    print(f"wrote {out}")
    print(f"water surface y={stage.surface_y:.3f}, floor y=6.0")
    print(f"wood block centroid y={wood_y:.3f}  (lower y = higher in screen)")
    print(f"steel block centroid y={steel_y:.3f}")
    print(f"wood is {'above' if wood_y < steel_y else 'below'} steel")
    print(f"total splash impulses spawned: {splash_total}")
    return out


if __name__ == "__main__":
    main()
