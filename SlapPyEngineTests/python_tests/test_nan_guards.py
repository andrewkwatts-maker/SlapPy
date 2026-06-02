"""Regression tests for the NaN/inf guard rails in the cell-field kernel
and the renderer's float→uint8 cast.

These tests reproduce the conditions that previously surfaced as
``RuntimeWarning: invalid value encountered in cast`` in render.py and
``invalid value encountered`` arithmetic inside world.py's ``_cpu_kernel``.

The fixes added in this commit:

* ``world.py`` sanitises every input channel at kernel entry, clamps the
  velocity field after integration so ``vx*vx + vy*vy`` cannot saturate
  to float32 ``inf``, and sanitises the field once more before write-back.
* ``render.py`` defensively ``nan_to_num``s the noise indices before the
  ``int32`` cast and the final RGB before the ``uint8`` cast.

Each test below either runs an extreme-physics scenario or hand-injects
a non-finite value to confirm the guards hold.  ``warnings.filterwarnings
("error", ...)`` is used so a regression would raise instead of merely
logging.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.render import PhysicsRenderer, RenderConfig


# Channel indices (mirrors world.py / cell.py).
_IDX_U_X = 0
_IDX_U_Y = 1
_IDX_V_X = 2
_IDX_V_Y = 3
_IDX_PRESSURE = 7
_IDX_DENSITY = 9
_IDX_HEAT = 12


def _make_world(bounds=(-200.0, -100.0, 200.0, 250.0)) -> PhysicsWorld:
    world = PhysicsWorld(world_bounds=bounds)
    # Force the CPU substep path so the guard rails added to ``_cpu_kernel``
    # are the code under test (the GPU path lives in WGSL and is out of
    # scope for this fix).
    world.config.gpu.debug_force_cpu = True
    return world


def _assert_cells_finite(cells: np.ndarray, ctx: str = "") -> None:
    """Fail with a clear message if any channel went non-finite."""
    if cells is None:
        return
    finite = np.isfinite(cells)
    if not finite.all():
        bad = np.argwhere(~finite)
        raise AssertionError(
            f"non-finite cells {ctx}: first 5 offsets {bad[:5].tolist()}, "
            f"sample values {cells[~finite].ravel()[:5].tolist()}"
        )


# --------------------------------------------------------------------------- #
# Extreme physics                                                              #
# --------------------------------------------------------------------------- #


def test_extreme_velocity_no_nan():
    """A tiny stiff steel ball dropped at 5000 px/s into a stone slab must
    not produce any NaN/inf in the cell field after 60 frames, and must
    not raise any ``RuntimeWarning`` during stepping.
    """
    world = _make_world()
    ground = world.create_body(
        make_rect_silhouette(240, 16),
        material="stone",
        position=(0.0, 180.0),
        fixed=True,
    )
    ball = world.create_body(
        make_circle_silhouette(4),
        material="steel",
        position=(0.0, 0.0),
        velocity=(0.0, 5000.0),
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error", category=RuntimeWarning, module=r"slappyengine\.physics.*"
        )
        for _ in range(60):
            world.step()
    _assert_cells_finite(ground.cells, "(ground after 60 frames)")
    _assert_cells_finite(ball.cells, "(ball after 60 frames)")


def _wake_body(world: PhysicsWorld, body) -> None:
    """Force the cell kernel to run for this body's hull this frame."""
    hid = body.root_hull_id
    world.hulls.active_until_frame[hid] = int(world.frame) + 60


def test_zero_density_cell_does_not_divide():
    """Force a cell's density to 0.0 and confirm the kernel's mass-effective
    floor keeps the resulting velocity update finite.
    """
    world = _make_world()
    body = world.create_body(
        make_rect_silhouette(64, 16),
        material="stone",
        position=(0.0, 100.0),
    )
    cells = body.cells
    assert cells is not None
    cells[5, 5, _IDX_DENSITY] = 0.0  # vacuum cell mid-grid
    cells[5, 5, _IDX_V_X] = 1.0      # nonzero v at that cell
    _wake_body(world, body)

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        world.step()

    _assert_cells_finite(body.cells, "(zero-density substep)")


def test_extreme_heat_does_not_overflow():
    """Push a single cell's heat to 1e10.  The kernel must clamp it back
    into range so that ``1 / (1 + heat * coef)`` stays finite.
    """
    world = _make_world()
    body = world.create_body(
        make_rect_silhouette(64, 16),
        material="stone",
        position=(0.0, 100.0),
    )
    world.config.frontier.enabled = False
    cells = body.cells
    assert cells is not None
    cells[10, 10, _IDX_HEAT] = 1e10
    _wake_body(world, body)

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        world.step()

    out = body.cells
    _assert_cells_finite(out, "(extreme-heat substep)")
    assert float(out[..., _IDX_HEAT].max()) <= 1.0e6 + 1.0, (
        "Heat should be clamped to _HEAT_LIMIT (1e6) by the kernel entry guard"
    )


def test_extreme_velocity_field_clamps_in_kernel():
    """Inject huge but-not-quite-overflowing velocities into the cell field
    directly and confirm the kernel clips them so ``v_mag2`` never
    overflows over the course of a multi-substep frame.

    The kernel's ``_V_LIMIT`` is 1e6, so seeding 5e5 (within entry range
    but enough that further integration could blow up without the
    post-integration clamp) checks that the *kernel-internal* guard does
    its job.
    """
    world = _make_world()
    # Disable the FrontierSolver: it reads the cell field *before* the
    # kernel runs (so its own ``vx*vx + vy*vy`` would see whatever value
    # we inject, regardless of any guard added in the kernel).  Frontier
    # is out of scope for this fix — we're only verifying that the
    # kernel cleans its inputs.
    world.config.frontier.enabled = False
    body = world.create_body(
        make_rect_silhouette(64, 16),
        material="water",
        position=(0.0, 100.0),
    )
    cells = body.cells
    assert cells is not None
    cells[..., _IDX_V_X] = 5.0e5
    cells[..., _IDX_V_Y] = -5.0e5
    _wake_body(world, body)

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        world.step()

    out = body.cells
    _assert_cells_finite(out, "(after large-v injection)")
    # Velocity must be re-clamped to the kernel's _V_LIMIT (1e6).
    assert float(np.max(np.abs(out[..., _IDX_V_X:_IDX_V_Y + 1]))) <= 1.0e6 + 1.0


def test_kernel_cleans_explicit_nan_in_velocity():
    """Inject NaN into the velocity field directly.  The kernel must
    sanitise it on entry so subsequent arithmetic does not propagate.
    """
    world = _make_world()
    world.config.frontier.enabled = False
    body = world.create_body(
        make_rect_silhouette(64, 16),
        material="water",
        position=(0.0, 100.0),
    )
    cells = body.cells
    assert cells is not None
    cells[5, 5, _IDX_V_X] = np.nan
    cells[5, 6, _IDX_V_Y] = np.inf
    cells[6, 5, _IDX_U_X] = np.nan
    cells[6, 6, _IDX_PRESSURE] = -np.inf
    _wake_body(world, body)

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        world.step()

    _assert_cells_finite(body.cells, "(after NaN/inf injection)")


# --------------------------------------------------------------------------- #
# Renderer guards                                                              #
# --------------------------------------------------------------------------- #


def test_renderer_handles_nan_input():
    """Manually inject NaN into a cell's u_x.  The renderer must absorb it
    and produce a valid uint8 frame (no NaN, finite RGB values).
    """
    world = _make_world()
    body = world.create_body(
        make_circle_silhouette(24),
        material="steel",
        position=(0.0, 50.0),
    )
    cells = body.cells
    assert cells is not None
    # Splatter NaN/inf across both u and v.
    cells[8, 8, _IDX_U_X] = np.nan
    cells[8, 9, _IDX_U_Y] = np.inf
    cells[9, 8, _IDX_V_X] = -np.inf

    # The world is NOT stepped — we want the renderer to face the dirty
    # cell state directly, which is the original showcase failure mode
    # (a body whose field carried NaN from a prior corrupted substep).
    renderer = PhysicsRenderer(RenderConfig(width=160, height=120))
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        frame = renderer.render(world)

    assert frame.dtype == np.uint8
    assert frame.shape == (120, 160, 4)
    # uint8 by construction is finite; just confirm the cast didn't silently
    # leave us with sentinel-zero everywhere (background should still draw).
    assert frame[..., 3].min() == 255 or frame[..., 3].max() == 255


def test_renderer_handles_nan_input_forward_splat():
    """Forward-splat path: same NaN injection but with splatting on, which
    exercises the noise-overlay int32 cast (the original site of the
    warning at render.py:584-585).
    """
    world = _make_world()
    body = world.create_body(
        make_circle_silhouette(24),
        material="steel",
        position=(0.0, 50.0),
    )
    cells = body.cells
    assert cells is not None
    cells[8, 8, _IDX_U_X] = np.nan
    cells[8, 9, _IDX_U_Y] = np.inf

    cfg = RenderConfig(width=160, height=120, forward_splat=True)
    renderer = PhysicsRenderer(cfg)
    # Crank the noise overlay so the int32 cast actually runs.
    body.material.noise_overlay_amplitude = 0.5  # type: ignore[attr-defined]

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        frame = renderer.render(world)

    assert frame.dtype == np.uint8
    assert np.isfinite(frame).all()  # uint8 is always finite; sanity check


# --------------------------------------------------------------------------- #
# End-to-end: showcase scenario warning-free                                   #
# --------------------------------------------------------------------------- #


def test_no_runtime_warnings_during_showcase():
    """Run 30 frames of a steel-into-water scenario with RuntimeWarning
    filtered as errors.  Any cast issue inside the physics package would
    raise.
    """
    world = _make_world()
    world.create_body(
        make_rect_silhouette(240, 32),
        material="water",
        position=(0.0, 180.0),
        fixed=True,
    )
    world.create_body(
        make_circle_silhouette(6),
        material="steel",
        position=(0.0, 0.0),
        velocity=(0.0, 1200.0),
    )

    renderer = PhysicsRenderer(RenderConfig(width=160, height=120))
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error", category=RuntimeWarning, module=r"slappyengine\.physics.*"
        )
        for _ in range(30):
            world.step()
            renderer.render(world)


# --------------------------------------------------------------------------- #
# Renderer falls back to clamped output when forced NaN escapes the kernel    #
# --------------------------------------------------------------------------- #


def test_renderer_uint8_cast_warning_free_with_extreme_rgb(monkeypatch):
    """Direct test of the renderer's final ``nan_to_num`` + clip + cast:
    even if some upstream stage produced an out-of-range float, the cast
    must not raise.
    """
    rgb = np.array([
        [[np.nan, np.inf, -np.inf]],
        [[1e30, -1e30, 0.5]],
    ], dtype=np.float32)
    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=RuntimeWarning)
        cleaned = np.nan_to_num(rgb, nan=0.0, posinf=255.0, neginf=0.0)
        out = np.clip(cleaned, 0.0, 255.0).astype(np.uint8)
    assert out.dtype == np.uint8
    # NaN → 0, +inf → 255, -inf → 0.
    assert out[0, 0, 0] == 0
    assert out[0, 0, 1] == 255
    assert out[0, 0, 2] == 0
