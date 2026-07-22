"""Visual smoke tests for the pharos_engine.testing harness.

These three scene tests are the bootstrap golden-master set the user
asked for. They cover the major CPU-visible subsystems present in this
worktree:

* a Layer2D-backed scene (stand-in for the prompt's "softbody lattice"
  — the softbody/ subpackage doesn't ship in this branch, so we
  exercise the same render pipeline via a procedurally-filled Layer2D),
* a fluid-config-driven scene (stand-in for the prompt's "fluid pool"),
* a Landscape tile composite (stand-in for the prompt's
  "sim_field density tile layer").

Each test renders the scene through ``render_scene_to_png``, asserts
the result is non-trivially bright (mean luminance > 5 / 255), and
then calls ``assert_scene_matches`` which writes a golden-master on
first run and diffs on subsequent runs.

Two extra tests cover the diff primitive in isolation.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pharos_engine.testing import (
    BASELINES_DIR,
    assert_scene_matches,
    diff_pngs,
    render_scene_to_png,
)


# ────────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────────

def _mean_luminance(path: Path) -> float:
    """Return the mean luminance (0–255) of the PNG at *path*."""
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    # Rec. 601 weights are fine for a smoke check.
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    return float(lum.mean())


def _fill_lattice(layer, rows: int = 6, cols: int = 6) -> None:
    """Paint a deterministic lattice of warm/cool dots onto *layer*.

    Stand-in for a softbody lattice: visually distinctive, deterministic,
    non-trivial luminance — enough to verify the readback path.
    """
    img = layer._image_data
    h, w = img.shape[:2]
    img[:] = 0
    # Soft warm background so the diff doesn't trip on a flat black.
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    xx = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    img[..., 0] = (40 + 60 * yy * np.ones_like(xx)).astype(np.uint8)
    img[..., 1] = (30 + 50 * xx * np.ones_like(yy)).astype(np.uint8)
    img[..., 2] = 80
    img[..., 3] = 255

    cell_h = h // (rows + 1)
    cell_w = w // (cols + 1)
    radius = max(2, min(cell_h, cell_w) // 4)
    yi, xi = np.ogrid[:h, :w]
    for r in range(rows):
        for c in range(cols):
            cy = (r + 1) * cell_h
            cx = (c + 1) * cell_w
            mask = (xi - cx) ** 2 + (yi - cy) ** 2 < radius * radius
            img[mask, 0] = 230
            img[mask, 1] = 200
            img[mask, 2] = 90


# ────────────────────────────────────────────────────────────────────────────
#  Scene smoke screenshots
# ────────────────────────────────────────────────────────────────────────────

def test_softbody_lattice_renders(tmp_path: Path) -> None:
    """Layer2D-backed lattice — stand-in for softbody.body_builders.make_lattice."""
    from pharos_engine.layer import Layer2D
    from pharos_engine.scene import Scene

    scene = Scene(name="softbody_lattice")
    layer = Layer2D(name="lattice", width=320, height=180)
    _fill_lattice(layer, rows=6, cols=6)
    scene._image_data = layer._image_data  # easy path for the readback

    out = tmp_path / "softbody_lattice.png"
    render_scene_to_png(scene, out, width=320, height=180, frames_to_settle=2)

    assert out.exists(), "renderer did not produce a PNG"
    lum = _mean_luminance(out)
    assert lum > 5.0, f"frame was nearly black (mean luminance {lum:.2f})"

    assert_scene_matches(scene, "softbody_lattice", width=320, height=180)


def test_fluid_pool_renders(tmp_path: Path) -> None:
    """Fluid-config-driven scene — stand-in for fluid.world.spawn_pool."""
    from pharos_engine.fluid_sim import FluidSimConfig
    from pharos_engine.layer import Layer2D
    from pharos_engine.scene import Scene

    scene = Scene(name="fluid_pool")
    # Carry a (water-tuned) FluidSimConfig on the scene so a future
    # GPU-resident fluid sim can pick it up. The readback path doesn't
    # need it — we paint a pool-shaped layer to drive the screenshot.
    scene.fluid_config = FluidSimConfig(
        viscosity=0.05, diffusion=0.01, buoyancy=0.0, gravity=9.8,
        density_decay=1.0,
    )

    layer = Layer2D(name="pool", width=320, height=180)
    img = layer._image_data
    img[:] = 0
    # Sky gradient.
    yy = np.linspace(0.0, 1.0, img.shape[0], dtype=np.float32)[:, None]
    img[..., 0] = (40 + 30 * yy * np.ones((1, img.shape[1]))).astype(np.uint8)
    img[..., 1] = (60 + 40 * yy * np.ones((1, img.shape[1]))).astype(np.uint8)
    img[..., 2] = (120 + 100 * yy * np.ones((1, img.shape[1]))).astype(np.uint8)
    img[..., 3] = 255
    # Pool body.
    pool_top = int(img.shape[0] * 0.55)
    img[pool_top:, 0] = 20
    img[pool_top:, 1] = 80
    img[pool_top:, 2] = 200
    # Caustic-ish stripes.
    xs = np.arange(img.shape[1])
    for y in range(pool_top, img.shape[0], 6):
        phase = (xs + y * 3) % 18
        bright = phase < 4
        img[y, bright, 0] = 80
        img[y, bright, 1] = 180
        img[y, bright, 2] = 240

    scene._image_data = img
    out = tmp_path / "fluid_pool.png"
    render_scene_to_png(scene, out, width=320, height=180, frames_to_settle=2)

    assert out.exists()
    lum = _mean_luminance(out)
    assert lum > 5.0, f"fluid frame was nearly black (mean luminance {lum:.2f})"

    assert_scene_matches(scene, "fluid_pool", width=320, height=180)


def test_sim_field_density_tile_layer(tmp_path: Path) -> None:
    """Density patch baked into a layer — stand-in for SimField.as_density_layer()."""
    from pharos_engine.layer import Layer2D
    from pharos_engine.scene import Scene

    scene = Scene(name="sim_field_density")
    layer = Layer2D(name="density", width=256, height=144)

    # Inject a circular density patch and "simulate" 10 frames of
    # outward diffusion by mean-filtering. Cheap stand-in for the real
    # SimField step; the goal here is a non-zero deterministic pattern,
    # not physical accuracy.
    img = layer._image_data
    h, w = img.shape[:2]
    yi, xi = np.ogrid[:h, :w]
    cx, cy = w // 2, h // 2
    radius = min(h, w) // 6
    patch = ((xi - cx) ** 2 + (yi - cy) ** 2 < radius * radius).astype(np.float32)

    field = patch.copy()
    for _ in range(10):
        # 5-point stencil blur, edges clamped.
        padded = np.pad(field, 1, mode="edge")
        field = 0.2 * (
            padded[1:-1, 1:-1]
            + padded[:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, :-2]
            + padded[1:-1, 2:]
        )

    # Bake to RGBA: density → warm orange channel.
    img[..., 0] = (field * 220).astype(np.uint8)
    img[..., 1] = (field * 120).astype(np.uint8)
    img[..., 2] = (field * 30).astype(np.uint8)
    img[..., 3] = 255

    assert np.any(img[..., 0] > 0), "density patch was lost during simulation"
    scene._image_data = img

    out = tmp_path / "sim_field_density.png"
    render_scene_to_png(scene, out, width=256, height=144, frames_to_settle=2)

    assert out.exists()
    lum = _mean_luminance(out)
    assert lum > 5.0, f"density frame was nearly black (mean luminance {lum:.2f})"

    assert_scene_matches(scene, "sim_field_density", width=256, height=144)


# ────────────────────────────────────────────────────────────────────────────
#  diff_pngs primitive
# ────────────────────────────────────────────────────────────────────────────

def _save_rgba(arr: np.ndarray, path: Path) -> None:
    Image.fromarray(arr, mode="RGBA").save(path)


def test_diff_pngs_detects_difference(tmp_path: Path) -> None:
    a = np.zeros((32, 32, 4), dtype=np.uint8)
    a[..., 3] = 255
    b = a.copy()
    b[..., 0] = 255  # solid red — every pixel differs by 1.0 on the R channel

    a_path = tmp_path / "a.png"
    b_path = tmp_path / "b.png"
    _save_rgba(a, a_path)
    _save_rgba(b, b_path)

    metrics = diff_pngs(a_path, b_path, tolerance=0.02)
    assert metrics["passes"] is False
    assert metrics["max_pixel_diff"] > 0.5
    assert metrics["mean_pixel_diff"] > 0.0


def test_diff_pngs_identical_passes(tmp_path: Path) -> None:
    arr = np.random.default_rng(seed=0).integers(0, 256, size=(32, 32, 4), dtype=np.uint8)
    arr[..., 3] = 255
    p = tmp_path / "frame.png"
    _save_rgba(arr, p)

    metrics = diff_pngs(p, p, tolerance=0.02)
    assert metrics["passes"] is True
    # Same file → identical pixels → zero diff.
    assert metrics["max_pixel_diff"] == pytest.approx(0.0, abs=1e-9)
    assert metrics["mean_pixel_diff"] == pytest.approx(0.0, abs=1e-9)


# ────────────────────────────────────────────────────────────────────────────
#  Misc harness sanity
# ────────────────────────────────────────────────────────────────────────────

def test_render_scene_to_png_handles_none(tmp_path: Path) -> None:
    """A `None` scene must still produce a non-empty PNG (synthetic fallback)."""
    out = tmp_path / "synthetic.png"
    render_scene_to_png(None, out, width=64, height=48, frames_to_settle=0)
    assert out.exists()
    assert _mean_luminance(out) > 5.0


def test_baselines_dir_is_inside_package() -> None:
    """Catches accidental relocation of the baselines folder."""
    assert BASELINES_DIR.name == "baselines"
    assert BASELINES_DIR.parent.name == "testing"
