"""Surface-render mode smoke + side-by-side comparison.

Renders a water pool with both the disc-splat and the marching-squares
surface mode, asserts both produce valid output, and writes a side-by-
side reference PNG to `tests/output/fluid/surface_compare.png`.
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
)

_OUT_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "output" / "fluid"
_OUT_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def _make_water_pool() -> FluidWorld:
    w = FluidWorld()
    w.config["floor_y"] = 5.0
    w.config["wall_x_min"] = -1.0
    w.config["wall_x_max"] = 1.0
    spacing = 0.06
    w.add_block_of_particles(
        "water", nx=10, ny=8, spacing=spacing,
        origin=(-0.30, 3.5), jitter=0.04,
    )
    return w


def _render_with_mode(world: FluidWorld, surface: bool,
                     view_box=(-1.2, 2.5, 1.2, 5.3)) -> np.ndarray:
    cfg = FluidRenderConfig.from_yaml({
        "width": 320, "height": 240,
        "surface_mode": surface,
    })
    return FluidRenderer(config=cfg).render(world, view_box=view_box)


def _longest_water_run(row: np.ndarray) -> int:
    """Length of the longest contiguous run of water-coloured pixels in a row."""
    is_water = (row[:, 2] > 80) & (row[:, 0] < 100)
    if not np.any(is_water):
        return 0
    # Run-length: diff of cumulative-sum gives runs
    diffs = np.diff(np.r_[0, is_water.astype(np.int32), 0])
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    return int((ends - starts).max())


def test_surface_mode_renders_water_pool():
    w = _make_water_pool()
    for _ in range(140):
        pbf_step(w)

    img_dot = _render_with_mode(w, surface=False)
    img_surf = _render_with_mode(w, surface=True)

    assert img_dot.shape == (240, 320, 4)
    assert img_surf.shape == (240, 320, 4)
    assert np.all(np.isfinite(img_dot))
    assert np.all(np.isfinite(img_surf))

    # Both have non-trivial water-coloured pixels.
    blue_dot = int(((img_dot[..., 2] > 80) & (img_dot[..., 0] < 100)).sum())
    blue_surf = int(((img_surf[..., 2] > 80) & (img_surf[..., 0] < 100)).sum())
    assert blue_dot > 200, f"disc-splat produced too few water pixels: {blue_dot}"
    assert blue_surf > 300, f"surface mode produced too few water pixels: {blue_surf}"

    # The discriminating invariant: surface mode produces longer *contiguous*
    # runs of water-colored pixels per row, because disc splats leave gaps
    # between particles whereas the marching-squares fill is connected.
    # Probe ~10 rows in the bottom half (where the settled pool sits).
    H = img_surf.shape[0]
    rows = np.linspace(int(H * 0.55), H - 5, 10, dtype=int)
    runs_dot = max(_longest_water_run(img_dot[r]) for r in rows)
    runs_surf = max(_longest_water_run(img_surf[r]) for r in rows)
    assert runs_surf >= runs_dot, (
        f"surface mode should produce at least as long a contiguous "
        f"water run as disc-splat: surf={runs_surf} dot={runs_dot}"
    )
    # And surface mode should have *no* obvious sub-particle gaps:
    # its longest run should be a meaningful fraction of the body width.
    assert runs_surf > 50, (
        f"surface mode pool too gappy: longest run {runs_surf} px"
    )


def test_surface_mode_handles_empty_world():
    w = FluidWorld()
    img = _render_with_mode(w, surface=True)
    # No crash; output is just background.
    assert img.shape == (240, 320, 4)
    assert np.all(np.isfinite(img))


def test_surface_comparison_image_written():
    """Renders both modes side-by-side and writes to a reference PNG."""
    from PIL import Image
    w = _make_water_pool()
    for _ in range(140):
        pbf_step(w)
    img_dot = _render_with_mode(w, surface=False)
    img_surf = _render_with_mode(w, surface=True)
    # Stitch left|right with a 4-pixel divider
    H, W, _ = img_dot.shape
    divider = np.full((H, 4, 4), 30, dtype=np.uint8)
    divider[..., 3] = 255
    stitched = np.concatenate([img_dot, divider, img_surf], axis=1)
    out_path = _OUT_DIR / "surface_compare.png"
    Image.fromarray(stitched, mode="RGBA").convert("RGB").save(out_path)
    assert out_path.is_file()
    assert out_path.stat().st_size > 0
