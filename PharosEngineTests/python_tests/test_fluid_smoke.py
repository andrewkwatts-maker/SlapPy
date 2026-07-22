"""Smoke tests for the Position-Based Fluids (PBF) foundation.

Each test instantiates a small :class:`FluidWorld`, drives it for a
number of frames, emits a GIF, and asserts a structural physics-
meaningful invariant — pooling, accumulating fill, merging, splashing.
Tests also assert mass conservation and KE dissipation.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.fluid import (
    FluidRenderConfig,
    FluidRenderer,
    FluidWorld,
    pbf_step,
    project_fluid_softbody_contacts,
)
from pharos_engine.media import save_frames
from pharos_engine.softbody import SoftBodyWorld, make_lattice_body, step as softbody_step

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "output" / "fluid"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


def _make_renderer(size: tuple[int, int] = (320, 240)) -> FluidRenderer:
    cfg = FluidRenderConfig.from_yaml({"width": size[0], "height": size[1]})
    return FluidRenderer(config=cfg)


def _render_frame(world: FluidWorld, view_box, renderer: FluidRenderer | None = None,
                  softbody=None):
    from PIL import Image
    r = renderer or _make_renderer()
    arr = r.render(world, view_box=view_box, softbody=softbody)
    return Image.fromarray(arr, mode="RGBA").convert("RGB")


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _initial_potential_energy(world: FluidWorld) -> float:
    g = float(world.config["gravity"][1])
    floor_y = world.floor_y
    pos_y = world.particles.pos[:, 1]
    masses = world.particles.mass
    # PE = m·g·h where h is drop distance from spawn to floor
    drop = np.maximum(floor_y - pos_y, 0.0)
    return float((masses * g * drop).sum())


def _kinetic_energy(world: FluidWorld) -> float:
    v2 = np.einsum("ij,ij->i", world.particles.vel, world.particles.vel)
    return float(0.5 * (world.particles.mass * v2).sum())


def test_water_drops_into_basin_and_pools():
    w = FluidWorld()
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -1.0
    w.config["wall_x_max"] = 1.0
    spacing = 0.06
    w.add_block_of_particles("water", nx=8, ny=8, spacing=spacing,
                             origin=(-0.21, 2.5), jitter=0.05)
    n_before = w.particles.count
    pe0 = _initial_potential_energy(w)

    renderer = _make_renderer()
    frames = []
    for _ in range(180):
        pbf_step(w)
        frames.append(_render_frame(w, view_box=(-1.2, 2.0, 1.2, 5.3),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "water_basin.gif", fps=30)

    assert w.particles.count == n_before, "mass not conserved"
    assert not np.any(np.isnan(w.particles.pos))
    assert not np.any(np.isinf(w.particles.pos))

    ys = w.particles.pos[:, 1]
    # All particles within walls
    assert (ys <= w.floor_y + 1e-3).all()
    # Surface is roughly flat: top of the column ys.min() and width of the top
    # band should be within a tolerance.
    top_band_mask = ys < ys.min() + spacing * 1.5
    top_band_y = ys[top_band_mask]
    assert top_band_y.std() < spacing * 1.2, (
        f"top surface not flat: std={top_band_y.std():.3f} spacing={spacing}"
    )
    # KE has dissipated below 10% of initial PE.
    ke = _kinetic_energy(w)
    assert ke < pe0 * 0.10, f"KE not dissipated: ke={ke:.2f} pe0={pe0:.2f}"


def test_water_pours_continuously_and_fills_higher():
    w = FluidWorld()
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -0.6
    w.config["wall_x_max"] = 0.6
    spacing = 0.06

    renderer = _make_renderer()
    frames = []

    # First pour
    w.add_block_of_particles("water", nx=6, ny=6, spacing=spacing,
                             origin=(-0.18, 3.5), jitter=0.05)
    n_after_first_emit = w.particles.count
    for _ in range(120):
        pbf_step(w)
        frames.append(_render_frame(w, view_box=(-0.8, 3.0, 0.8, 5.3),
                                    renderer=renderer))
    first_top_y = float(w.particles.pos[:, 1].min())

    # Second pour
    w.add_block_of_particles("water", nx=6, ny=6, spacing=spacing,
                             origin=(-0.18, 3.5), jitter=0.05)
    n_after_second_emit = w.particles.count
    assert n_after_second_emit == 2 * n_after_first_emit
    for _ in range(180):
        pbf_step(w)
        frames.append(_render_frame(w, view_box=(-0.8, 3.0, 0.8, 5.3),
                                    renderer=renderer))
    final_top_y = float(w.particles.pos[:, 1].min())

    save_frames(frames, _OUT_DIR / "water_fills_higher.gif", fps=30)

    assert w.particles.count == n_after_second_emit, "mass not conserved"
    assert not np.any(np.isnan(w.particles.pos))
    # In our convention smaller y = higher. Second pour means a smaller (higher) top.
    assert final_top_y < first_top_y - spacing * 0.5, (
        f"pool did not rise after second pour: first={first_top_y:.3f} final={final_top_y:.3f}"
    )


def test_two_water_streams_merge():
    w = FluidWorld()
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -1.5
    w.config["wall_x_max"] = 1.5
    spacing = 0.06

    # Left stream moving right, right stream moving left, both at the same height.
    w.add_block_of_particles("water", nx=4, ny=6, spacing=spacing,
                             origin=(-1.2, 3.5),
                             velocity=(2.5, 0.0), jitter=0.05)
    n_left = w.particles.count
    w.add_block_of_particles("water", nx=4, ny=6, spacing=spacing,
                             origin=(1.0 - 0.18, 3.5),
                             velocity=(-2.5, 0.0), jitter=0.05)
    n_total = w.particles.count
    n_right = n_total - n_left
    pe0 = _initial_potential_energy(w)

    renderer = _make_renderer()
    frames = []
    for _ in range(180):
        pbf_step(w)
        frames.append(_render_frame(w, view_box=(-1.6, 3.0, 1.6, 5.3),
                                    renderer=renderer))
    save_frames(frames, _OUT_DIR / "water_streams_merge.gif", fps=30)

    assert w.particles.count == n_total, "mass not conserved"
    assert not np.any(np.isnan(w.particles.pos))

    xs = w.particles.pos[:, 0]
    # After merge, there must be at least some particles straddling the centre band.
    centre_band = np.abs(xs) < spacing * 2.5
    assert int(centre_band.sum()) > max(3, int(n_total * 0.05)), (
        f"streams did not merge across centre: only {int(centre_band.sum())} in band"
    )
    # The merged column straddles the centre with both halves of the population.
    left_mass = float((xs < 0.0).sum())
    right_mass = float((xs > 0.0).sum())
    ratio = min(left_mass, right_mass) / max(max(left_mass, right_mass), 1.0)
    assert ratio > 0.20, f"streams escaped instead of merging: ratio={ratio:.3f}"

    ke = _kinetic_energy(w)
    assert ke < pe0 * 0.5 + 50.0, f"streams did not dissipate: ke={ke:.2f}"


def test_water_splashes_when_object_drops_in():
    fluid = FluidWorld()
    fluid.config["floor_y"] = 5.0
    fluid.config["wall_x_min"] = -1.0
    fluid.config["wall_x_max"] = 1.0
    spacing = 0.06
    fluid.add_block_of_particles("water", nx=10, ny=6, spacing=spacing,
                                 origin=(-0.30, 3.8), jitter=0.05)
    n_before = fluid.particles.count

    # Pre-settle the pool
    for _ in range(120):
        pbf_step(fluid)
    settled_y = fluid.particles.pos[:, 1].copy()
    settled_top = float(settled_y.min())
    settled_top_std = float(settled_y[settled_y < settled_top + spacing * 1.5].std())

    # Drop a steel softbody block from above.
    sb = SoftBodyWorld()
    sb.config["floor_y"] = 5.0
    sb.config["contact"]["enabled"] = False  # no body-body
    meta = make_lattice_body(sb, "steel", width_cells=4, height_cells=4,
                             cell_size=0.06, position=(-0.12, 2.8))
    ns, ne = meta.node_slice
    sb.nodes.vel[ns:ne, 1] = 6.0  # initial downward velocity

    renderer = _make_renderer()
    frames = []

    # Custom coupled step
    def coupled_step():
        # advance softbody one frame (with its own substeps), then PBF, then resolve contacts
        softbody_step(sb)
        cfg = fluid.config
        sub_dt = float(cfg["default_dt"]) / max(int(cfg["substeps"]), 1)
        pbf_step(fluid)
        # one extra fluid-softbody contact projection at the frame level
        project_fluid_softbody_contacts(fluid, sb, sub_dt)

    splash_max_dy = 0.0
    for _ in range(180):
        coupled_step()
        ys = fluid.particles.pos[:, 1]
        dy = float(settled_top - ys.min())
        if dy > splash_max_dy:
            splash_max_dy = dy
        frames.append(_render_frame(fluid, view_box=(-1.2, 2.0, 1.2, 5.3),
                                    renderer=renderer, softbody=sb))
    save_frames(frames, _OUT_DIR / "water_splash.gif", fps=30)

    assert fluid.particles.count == n_before, "mass not conserved"
    assert not np.any(np.isnan(fluid.particles.pos))
    assert not np.any(np.isnan(sb.nodes.pos))

    # Splash: particles displaced upward by more than spacing.
    assert splash_max_dy > spacing * 1.0, (
        f"no splash above settled top: max_dy={splash_max_dy:.3f}"
    )
    # Some particles return below where the steel block ended up
    final_yps = fluid.particles.pos[:, 1]
    sb_floor_y = float(sb.nodes.pos[ns:ne, 1].max())
    below = (final_yps >= sb_floor_y - spacing).sum()
    assert below > n_before * 0.3, (
        f"too few particles below block: {below}/{n_before}"
    )
