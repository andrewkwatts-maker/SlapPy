"""Lava-flow demo: molten blob drops onto ice, melts it, then cools to stone.

A 48-diameter LAVA ball (``initial_heat = 12.0`` > ``melt_point = 9.0``) is
dropped from the top of the arena onto a wide ICE slab.  Each
``world.step()`` invokes :class:`BoundaryExchange` which conducts heat across
contact seams between the two bodies' cell grids.  We expect:

  * lava heat to monotonically fall (cooling into the cold ice + ambient),
  * ice heat at the contact zone to rise (then slowly fall as it radiates),
  * ice density at the contact zone to fall (cells "melt" — phase change
    reduces effective material at the seam),
  * total mass (Σ density × ρ_mat × cell_area over every body) to stay
    conserved to within a small tolerance — heat exchange is not allowed
    to bleed mass.

Run::

    python examples/physics_lava_flow_demo.py

The script writes ``examples/output/physics_lava_flow_demo.gif`` and prints a
short summary of the thermal trajectory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.post_process import (
    BloomPass,
    PostProcessChain,
    TonemapPass,
)
from slappyengine.physics.render import (
    PhysicsRenderer,
    PointLight,
    RenderConfig,
)
from slappyengine.physics.world import WorldConfig


# --- cell channel indices (mirror CELL_PIXEL_STRUCT) ------------------------
_IDX_DENSITY = 9
_IDX_HEAT = 12

# --- scene constants --------------------------------------------------------
WORLD_BOUNDS = (-200.0, -100.0, 200.0, 250.0)
FRAME_COUNT = 300
FPS = 30
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "physics_lava_flow_demo.gif"


def build_world() -> tuple[PhysicsWorld, dict[str, object]]:
    """Construct the lava-flow scene and return refs to key bodies.

    A gentle gravity is used (≪ the YAML default of 196) so the impact-
    velocity heat injection doesn't dwarf the seam-conduction signal the
    demo is meant to showcase.  The lava still falls, lands, and rests on
    the slab — but kinetic energy at contact stays low enough that the
    cross-body BoundaryExchange dominates the post-contact thermal
    trajectory and the blob visibly cools below its starting heat.
    """
    world = PhysicsWorld(world_bounds=WORLD_BOUNDS)
    # Gentle gravity keeps the lava blob settled on the slab without
    # generating large impact velocities; the demo focuses on the
    # cross-body BoundaryExchange heat conduction, which is otherwise
    # swamped by impact-injected heat on a fast drop.
    base = world.config.world
    world.config.world = WorldConfig(
        default_dt=base.default_dt,
        substeps=base.substeps,
        gravity=(0.0, 4.0),
    )

    # Ice ground slab: 200 wide × 16 thick at y=180.  fixed=True so gravity
    # and rigid integration are skipped, but the cell grid still simulates
    # (heat conducts in and "melt" reduces local density).
    ice = world.create_body(
        silhouette=make_rect_silhouette(200, 16),
        material="ice",
        position=(0.0, 180.0),
        fixed=True,
    )

    # Lava blob: 48-diameter circle starting near the top.  No velocity —
    # gravity pulls it down.  initial_heat = 12 > melt_point = 9 so the
    # blob self-emits and starts molten.
    # The lava starts in light contact with the top of the ice slab
    # (ice top at y=172; lava radius 24 → centre at y=148 rests against
    # it).  Starting at rest means closing-velocity at the seam is
    # essentially zero, so the impulse-driven heat injection is silent
    # and BoundaryExchange is the only thermal driver — exactly the
    # mechanism this demo means to showcase.
    lava = world.create_body(
        silhouette=make_circle_silhouette(48),
        material="lava",
        position=(0.0, 148.0),
    )

    # Two steel witnesses on either side of the impact zone.
    steel_l = world.create_body(
        silhouette=make_circle_silhouette(20),
        material="steel",
        position=(-60.0, 150.0),
    )
    steel_r = world.create_body(
        silhouette=make_circle_silhouette(20),
        material="steel",
        position=(60.0, 150.0),
    )

    return world, {
        "ice": ice,
        "lava": lava,
        "steel_l": steel_l,
        "steel_r": steel_r,
    }


def _ice_contact_columns(ice_cells: np.ndarray) -> slice:
    """Return the column slice of the ice grid directly under the lava
    drop.  The slab is 200 wide → 32 cells → ~6.25 world units/cell.  A
    48-diameter ball centred at x=0 covers ±24 → ~4 cells about column 16.
    Pick a generous 8-cell window for the "contact zone" stats.
    """
    centre = 16
    half = 4
    return slice(centre - half, centre + half)


def _total_mass(world: PhysicsWorld) -> float:
    """Σ density × ρ_mat × cell_area across every body's cell grid.

    Matches the mass integral used in ``PhysicsWorld.create_body`` so any
    drift here reflects density mutation (e.g. heat-exchange leaking mass).
    """
    total = 0.0
    for body in world.iter_bodies():
        cells = body.cells
        if cells is None:
            continue
        hid = body.root_hull_id
        cs_x = float(world.hulls.cell_size_x[hid])
        cs_y = float(world.hulls.cell_size_y[hid])
        cell_area = cs_x * cs_y
        density = cells[..., _IDX_DENSITY]
        total += float((body.material.density_rho * density * cell_area).sum())
    return total


def run_demo(
    save_gif: bool = True,
    frame_count: int = FRAME_COUNT,
) -> dict[str, object]:
    """Run the demo, write the GIF, and return tracked metrics.

    Returned dict keys:
        ``frames``       — list of post-processed RGBA frames
        ``lava_heat``    — list[float] of lava max heat per frame
        ``ice_heat``     — list[float] of ice max heat per frame
                            (whole grid; matches the spec's
                            ``ice.cells[..., 12].max()``)
        ``ice_contact_heat`` — list[float] of ice contact-zone max heat
        ``ice_min_density`` — list[float] of ice contact-zone min density
        ``lava_mass``    — list[float] of lava total mass per frame
        ``total_mass``   — list[float] of world total mass per frame
        ``initial_lava_heat`` — float (== 12.0)
        ``output_path``  — Path or None
    """
    world, bodies = build_world()
    ice = bodies["ice"]
    lava = bodies["lava"]

    initial_lava_heat = float(lava.cells[..., _IDX_HEAT].max())

    # Renderer: red/orange ambient with a single cool blue accent light to
    # contrast the lava glow.  Bloom + tonemap give the molten cells a
    # convincing halo.
    cfg = RenderConfig(
        width=640,
        height=360,
        bg_top=(12, 6, 18),
        bg_bottom=(36, 18, 28),
        world_view=WORLD_BOUNDS,
        ambient_intensity=0.55,
        lights=[
            PointLight(
                position=(120.0, -40.0),
                color=(120, 180, 255),
                intensity=0.8,
                radius=260.0,
            ),
        ],
        enable_normal_map=True,
        normal_curvature_bias=0.35,
    )
    renderer = PhysicsRenderer(config=cfg)
    post = PostProcessChain([
        BloomPass(threshold=150, intensity=1.2, radius_px=10.0),
        TonemapPass(exposure=1.4),
    ])

    ice_cols = _ice_contact_columns(ice.cells)

    frames: list[np.ndarray] = []
    lava_heat: list[float] = []
    ice_heat: list[float] = []
    ice_contact_heat: list[float] = []
    ice_min_density: list[float] = []
    lava_mass: list[float] = []
    total_mass: list[float] = []

    lava_rho = lava.material.density_rho
    lava_hid = lava.root_hull_id
    lava_cell_area = (
        float(world.hulls.cell_size_x[lava_hid])
        * float(world.hulls.cell_size_y[lava_hid])
    )

    for _ in range(frame_count):
        world.step()

        # Track per-frame metrics.
        lava_cells = lava.cells
        ice_cells = ice.cells
        assert lava_cells is not None and ice_cells is not None

        lava_heat.append(float(lava_cells[..., _IDX_HEAT].max()))
        # Spec metric: ``ice.cells[..., 12].max()`` — whole-grid peak heat.
        ice_heat.append(float(ice_cells[..., _IDX_HEAT].max()))
        contact = ice_cells[:, ice_cols, :]
        ice_contact_heat.append(float(contact[..., _IDX_HEAT].max()))
        # Only consider cells that originally had material (density > 0).
        contact_density = contact[..., _IDX_DENSITY]
        seeded = contact_density > 0.01
        if seeded.any():
            ice_min_density.append(float(contact_density[seeded].min()))
        else:
            ice_min_density.append(0.0)
        lava_mass.append(
            float((lava_rho * lava_cells[..., _IDX_DENSITY] * lava_cell_area).sum())
        )
        total_mass.append(_total_mass(world))

        # Render + post-process.
        rgba = renderer.render(world)
        rgba = post.apply(rgba)
        frames.append(rgba)

    output_path: Path | None = None
    if save_gif:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = renderer.save_gif(frames, OUTPUT_PATH, fps=FPS)

    return {
        "frames": frames,
        "lava_heat": lava_heat,
        "ice_heat": ice_heat,
        "ice_contact_heat": ice_contact_heat,
        "ice_min_density": ice_min_density,
        "lava_mass": lava_mass,
        "total_mass": total_mass,
        "initial_lava_heat": initial_lava_heat,
        "output_path": output_path,
    }


def _summarise(metrics: dict[str, object]) -> str:
    lava_heat = metrics["lava_heat"]  # type: ignore[index]
    ice_heat = metrics["ice_heat"]    # type: ignore[index]
    lava_mass = metrics["lava_mass"]  # type: ignore[index]
    initial = metrics["initial_lava_heat"]
    final_lava = lava_heat[-1]
    peak_ice = max(ice_heat)
    lava_start_mass = lava_mass[0]
    lava_end_mass = lava_mass[-1]
    return (
        f"Lava cooled from {initial:.2f} -> {final_lava:.4f} over "
        f"{len(lava_heat)} frames. "
        f"Ice peak heat reached {peak_ice:.4f}. "
        f"Density preserved: lava {lava_start_mass:.4f} -> {lava_end_mass:.4f}."
    )


def main() -> None:
    metrics = run_demo(save_gif=True)
    print(_summarise(metrics))
    out = metrics["output_path"]
    if out is not None:
        print(f"GIF written to {out}")


if __name__ == "__main__":
    main()
