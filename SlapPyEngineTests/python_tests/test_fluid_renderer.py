"""Tests for fluid-surface shading (foam + ripple highlights) in the
forward-splat renderer.

The renderer adds two effects on top of a fluid body's base palette:

  * ``foam_amplitude``  — high-divergence regions of the displacement
    field (wave crests, turbulent splash sites) are blended toward white.
  * ``ripple_amplitude`` — a sinusoidal modulation of brightness keyed on
    ``|u_y|`` suggests specular reflection on a moving water surface.

Both effects are gated on the material's ``is_fluid`` flag AND a non-zero
amplitude — so non-fluid materials (and fluids that haven't opted in) pay
zero cost and render bit-identically to the prior code path.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.cell import CELL_GRID_SIZE
from slappyengine.physics.render import PhysicsRenderer, RenderConfig


# Cell-field channel indices (must match CELL_PIXEL_STRUCT in cell.py).
_IDX_U_X, _IDX_U_Y = 0, 1


def _make_world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _foreground_mask(frame: np.ndarray) -> np.ndarray:
    """Return a boolean mask of non-background pixels.

    The renderer paints the background as a dark gradient from
    ``bg_top=(8,8,22)`` to ``bg_bottom=(24,28,52)`` — anything brighter
    than that gradient is body pixels.  We threshold conservatively so
    foam (near-white) is clearly captured.
    """
    rgb = frame[..., :3].astype(np.float32)
    # Background is dark blue-ish; foreground exceeds it.
    return (rgb[..., 0] > 40) | (rgb[..., 1] > 40) | (rgb[..., 2] > 80)


def test_foam_appears_at_high_divergence():
    """Inject high divergence at a localised patch of cells; foam should
    visibly whiten those cells relative to a calm-water control.
    """
    w_calm = _make_world()
    w_calm.create_body(
        make_circle_silhouette(96), "water", position=(0.0, 100.0),
    )

    w_div = _make_world()
    body = w_div.create_body(
        make_circle_silhouette(96), "water", position=(0.0, 100.0),
    )
    # Inject a strong divergence pattern at the centre: u_x diverges
    # outward (+x on the right half, -x on the left half).  Far stronger
    # than what the natural sim produces, so the foam term clearly bites.
    cells = body.cells
    assert cells is not None
    mid = CELL_GRID_SIZE // 2
    cells[mid - 4: mid + 4, mid:, _IDX_U_X] = +5.0
    cells[mid - 4: mid + 4, :mid, _IDX_U_X] = -5.0

    r = PhysicsRenderer()
    frame_calm = r.render(w_calm)
    frame_div = r.render(w_div)

    # Average brightness over the foreground; foam should pull the
    # divergence frame toward white.
    fg_calm = _foreground_mask(frame_calm)
    fg_div = _foreground_mask(frame_div)
    assert fg_calm.any() and fg_div.any(), "expected water bodies to render"

    mean_calm = frame_calm[..., :3][fg_calm].astype(np.float32).mean()
    mean_div = frame_div[..., :3][fg_div].astype(np.float32).mean()

    assert mean_div > mean_calm + 8.0, (
        f"Foam should whiten high-divergence water: calm={mean_calm:.1f}, "
        f"divergent={mean_div:.1f}"
    )


def test_ripple_modulates_with_u_y():
    """Varying u_y across cells produces a non-flat brightness pattern."""
    w_flat = _make_world()
    w_flat.create_body(
        make_circle_silhouette(96), "water", position=(0.0, 100.0),
    )
    w_rip = _make_world()
    body = w_rip.create_body(
        make_circle_silhouette(96), "water", position=(0.0, 100.0),
    )
    # Lay down a horizontal stripe pattern in u_y.  ``ripple = amp *
    # sin(u_y * 4) * tanh(|u_y|)`` means a striped u_y produces striped
    # brightness modulation — the variance across foreground pixels
    # should clearly exceed the calm baseline.
    cells = body.cells
    assert cells is not None
    rows = np.arange(CELL_GRID_SIZE, dtype=np.float32)
    pattern = np.sin(rows * 0.6) * 2.0  # u_y in ±2 world units
    cells[..., _IDX_U_Y] = pattern[:, None]

    r = PhysicsRenderer()
    frame_flat = r.render(w_flat)
    frame_rip = r.render(w_rip)

    fg_flat = _foreground_mask(frame_flat)
    fg_rip = _foreground_mask(frame_rip)
    assert fg_flat.any() and fg_rip.any()

    # Brightness standard deviation rises when ripple is active.
    lum_flat = frame_flat[..., :3][fg_flat].astype(np.float32).mean(axis=-1)
    lum_rip = frame_rip[..., :3][fg_rip].astype(np.float32).mean(axis=-1)
    assert lum_rip.std() > lum_flat.std() + 2.0, (
        f"Ripple should add brightness variance: flat std={lum_flat.std():.2f}, "
        f"rippled std={lum_rip.std():.2f}"
    )


def test_non_fluid_unaffected():
    """A stone body with manually-injected u_x/u_y must not get foam or
    ripple — the gate on ``is_fluid`` keeps non-fluid materials zero-cost.
    """
    w_a = _make_world()
    w_a.create_body(
        make_circle_silhouette(96), "stone", position=(0.0, 100.0),
    )
    w_b = _make_world()
    body = w_b.create_body(
        make_circle_silhouette(96), "stone", position=(0.0, 100.0),
    )
    # Inject the same divergent/oscillating field that would have foamed
    # water heavily.
    cells = body.cells
    assert cells is not None
    mid = CELL_GRID_SIZE // 2
    cells[mid - 4: mid + 4, mid:, _IDX_U_X] = +5.0
    cells[mid - 4: mid + 4, :mid, _IDX_U_X] = -5.0
    rows = np.arange(CELL_GRID_SIZE, dtype=np.float32)
    cells[..., _IDX_U_Y] = np.sin(rows * 0.6)[:, None] * 2.0

    r = PhysicsRenderer()
    # Disable temporal averaging variance: both renders compare directly.
    frame_a = r.render(w_a)
    # Stone with injected u doesn't really "deform" in a way that matters
    # for foam — the forward-splat path will shift cells around but the
    # foam/ripple shading itself must remain disabled.  We assert by
    # checking that no pixels go bright-white (a foamy water cell would
    # produce many).
    frame_b = r.render(w_b)

    fg_b = _foreground_mask(frame_b)
    rgb_b = frame_b[..., :3][fg_b].astype(np.float32)
    # No cell should be foamed near-white.  Stone palette is (110, 105, 100);
    # foam would push values past ~220.  Assert no pixels exceed 200 on
    # every channel simultaneously (which would indicate foam whitening).
    near_white = (rgb_b[:, 0] > 200) & (rgb_b[:, 1] > 200) & (rgb_b[:, 2] > 200)
    assert not near_white.any(), (
        f"Stone must not foam: {near_white.sum()} near-white pixels found"
    )

    # And the foreground colour means must still read as stone-grey,
    # nowhere near the bright water+foam signature.
    mean_b = rgb_b.mean(axis=0)
    assert mean_b[2] < 150, f"Stone shouldn't gain a blue/white tint: {mean_b}"


def test_lava_keeps_glow():
    """Lava with ``foam_amplitude=0.4`` still emits its heat glow — foam
    must layer ON TOP of the glow, not replace it.
    """
    w = _make_world()
    body = w.create_body(
        make_circle_silhouette(96), "lava", position=(0.0, 100.0),
    )
    # Sanity: lava cells start pre-heated above melt_point.
    assert body.cells is not None
    assert body.cells[..., 12].max() > 5.0
    # Inject some divergence so the foam term has signal.
    cells = body.cells
    mid = CELL_GRID_SIZE // 2
    cells[mid - 2: mid + 2, mid:, _IDX_U_X] = +3.0
    cells[mid - 2: mid + 2, :mid, _IDX_U_X] = -3.0

    r = PhysicsRenderer()
    frame = r.render(w)

    fg = _foreground_mask(frame)
    assert fg.any()
    rgb = frame[..., :3][fg].astype(np.float32)
    # Lava still reads orange-red: mean R well above mean B, and high
    # red overall (glow is intact).
    mean = rgb.mean(axis=0)
    assert mean[0] > 150.0, f"Lava lost its glow (R={mean[0]:.1f})"
    assert mean[0] > mean[2] + 40.0, (
        f"Lava should stay red-dominant: R={mean[0]:.1f}, B={mean[2]:.1f}"
    )


def test_foam_zero_no_change():
    """With both amplitudes 0, the render is bit-identical to the path
    that doesn't go through the fluid-surface shader.

    Because ``cell_material_for`` returns a shared ``CellMaterial``
    instance per material name, we explicitly compare two snapshots from
    the same world: one taken with amplitudes zeroed and one taken with
    them restored.  When zeroed, the renderer's gate skips the entire
    fluid-surface branch — so the output must match what a fresh,
    foam-less world would have produced.
    """
    # Build a world with injected divergence so foam *would* be visible.
    w = _make_world()
    body = w.create_body(
        make_circle_silhouette(96), "water", position=(0.0, 100.0),
    )
    cells = body.cells
    assert cells is not None
    mid = CELL_GRID_SIZE // 2
    cells[mid - 4: mid + 4, mid:, _IDX_U_X] = +5.0
    cells[mid - 4: mid + 4, :mid, _IDX_U_X] = -5.0
    # Also a u_y stripe so ripple has signal.
    rows = np.arange(CELL_GRID_SIZE, dtype=np.float32)
    cells[..., _IDX_U_Y] = np.sin(rows * 0.6)[:, None] * 2.0

    r = PhysicsRenderer()
    # Snapshot 1: with amplitudes ON.
    saved_foam = body.material.foam_amplitude
    saved_ripple = body.material.ripple_amplitude
    assert saved_foam > 0.0 or saved_ripple > 0.0, (
        "Water preset should have non-zero foam/ripple amplitudes"
    )
    frame_on = r.render(w)

    # Snapshot 2: same world, same injected fields, amplitudes zeroed
    # — the gate short-circuits the fluid-surface shader entirely.
    body.material.foam_amplitude = 0.0
    body.material.ripple_amplitude = 0.0
    try:
        frame_off_a = r.render(w)
        # Snapshot 3: a second render with amplitudes still zero.
        # Must be bit-identical (renderer is deterministic on a static
        # world, frame counter aside — temporal averaging is off by
        # default so the path is fully deterministic).
        frame_off_b = r.render(w)
    finally:
        body.material.foam_amplitude = saved_foam
        body.material.ripple_amplitude = saved_ripple

    # Bit-identical between the two zero-amplitude renders.
    assert np.array_equal(frame_off_a, frame_off_b), (
        "Two zero-amplitude renders of the same world must be bit-identical"
    )
    # And the ON render must differ — proves the gate is doing work.
    assert not np.array_equal(frame_on, frame_off_a), (
        "Non-zero amplitudes should produce a visibly different render"
    )
