"""Temporal-averaging tests for :class:`PhysicsRenderer` (Option 3).

The renderer keeps a short history of per-body ``u_xy`` / density
snapshots and, when ``RenderConfig.temporal_average_frames > 1``, paints
the forward-splat path using the *mean* of the recent N snapshots.  This
smooths visible jitter from fast-moving cell deformation without
touching the solver.

These tests cover:

  * default (frames=1) is bit-identical to the prior renderer
  * averaging actually reduces per-frame "max |u|" variation across a
    multi-frame sequence
  * a body that disappears between frames doesn't crash the renderer
  * a body that didn't exist on the previous frame is rendered using
    its current state only (no smoothing artefacts at spawn time)
"""
from __future__ import annotations

import numpy as np

from slappyengine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
)
from slappyengine.physics.render import (
    PhysicsRenderer,
    RenderConfig,
)


# Cell-channel indices mirror render.py.  Kept local so the test file
# stays self-contained.
_IDX_U_X, _IDX_U_Y = 0, 1
_IDX_V_X, _IDX_V_Y = 2, 3
_IDX_DENSITY = 9


def _world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _ball_world(diameter: int = 48, material: str = "mud") -> PhysicsWorld:
    w = _world()
    w.create_body(make_circle_silhouette(diameter), material, position=(0.0, 0.0))
    return w


def _inject_displacement(world: PhysicsWorld, amp: float = 4.0) -> None:
    """Stamp a large oscillating u/v field on every body so successive
    frames produce a visibly different splat — mimics fast-moving cell
    deformation that this feature is designed to smooth."""
    for body in world.iter_bodies():
        cells = body.cells
        if cells is None:
            continue
        # A radial sin pattern: large enough that frame-to-frame stepping
        # produces big swings in max(|u|).
        cy, cx = np.mgrid[0:cells.shape[0], 0:cells.shape[1]].astype(np.float32)
        cx -= cells.shape[1] * 0.5
        cy -= cells.shape[0] * 0.5
        cells[..., _IDX_U_X] += amp * np.sin(0.4 * cx + 0.2 * cy)
        cells[..., _IDX_U_Y] += amp * np.cos(0.3 * cx - 0.25 * cy)
        # And matching velocity so the next step evolves the field instead
        # of just damping it back.
        cells[..., _IDX_V_X] += amp * np.cos(0.1 * cx)
        cells[..., _IDX_V_Y] += amp * np.sin(0.1 * cy)


# -------------------------------------------------------------------------
# 1. Default config = no averaging = bit-identical to prior renderer
# -------------------------------------------------------------------------

def test_default_is_single_frame():
    """``RenderConfig().temporal_average_frames`` must default to 1 and the
    rendered output must match a renderer that *never* touches the new
    code path."""
    assert RenderConfig().temporal_average_frames == 1

    w_a = _ball_world()
    w_b = _ball_world()
    r_default = PhysicsRenderer()
    r_explicit_one = PhysicsRenderer(config=RenderConfig(temporal_average_frames=1))
    f_default = r_default.render(w_a)
    f_explicit = r_explicit_one.render(w_b)
    # The two worlds are independently constructed with identical seeds —
    # the rendered frames must agree bit-for-bit.
    assert np.array_equal(f_default, f_explicit), (
        "temporal_average_frames=1 must be bit-identical to the default "
        "renderer (zero-overhead backwards-compat)."
    )

    # Multi-frame run: even when the world steps, the frames=1 path must
    # still match a frames=1 explicit renderer (history is never consulted).
    w_step_a = _ball_world()
    w_step_b = _ball_world()
    r_a = PhysicsRenderer()
    r_b = PhysicsRenderer(config=RenderConfig(temporal_average_frames=1))
    for _ in range(5):
        w_step_a.step()
        w_step_b.step()
        fa = r_a.render(w_step_a)
        fb = r_b.render(w_step_b)
        assert np.array_equal(fa, fb), (
            "frames=1 must remain bit-identical across stepped frames."
        )


# -------------------------------------------------------------------------
# 2. Averaging smooths the visible "max u" across a multi-frame run
# -------------------------------------------------------------------------

def _record_max_u_series(
    frames_window: int, n_frames: int = 6,
) -> list[float]:
    """Run a fixed-seed sim, render ``n_frames`` frames with the given
    averaging window, and return the per-frame "max |u|" actually painted
    by the renderer (peeked from history so we measure the averaged
    value, not the raw solver state)."""
    np.random.seed(0)
    w = _ball_world(diameter=48, material="mud")
    _inject_displacement(w, amp=6.0)
    cfg = RenderConfig(temporal_average_frames=frames_window)
    r = PhysicsRenderer(config=cfg)

    maxes: list[float] = []
    for _ in range(n_frames):
        r.render(w)
        # Compute the painted max-u for the body using the same averaging
        # logic the renderer applies internally.  Mirrors _averaged_state.
        body = next(iter(w.iter_bodies()))
        cells = body.cells
        ux_now = cells[..., _IDX_U_X].astype(np.float32)
        uy_now = cells[..., _IDX_U_Y].astype(np.float32)
        d_now = cells[..., _IDX_DENSITY].astype(np.float32)
        ux_avg, uy_avg, _ = r._averaged_state(body, ux_now, uy_now, d_now)
        maxes.append(float(np.sqrt(ux_avg ** 2 + uy_avg ** 2).max()))
        # Step + re-inject so each frame has new high-frequency content.
        w.step()
        _inject_displacement(w, amp=4.0)
    return maxes


def test_averaging_smooths_fast_motion():
    """With ``temporal_average_frames=3`` the per-frame "max |u|" should
    have lower frame-to-frame variation than with ``frames=1``.

    The world gets a large oscillating displacement injected each frame
    so the raw max-u swings hard; the averaged renderer should report a
    smoother curve.
    """
    series_one = _record_max_u_series(frames_window=1, n_frames=6)
    series_three = _record_max_u_series(frames_window=3, n_frames=6)

    var_one = float(np.std(series_one))
    var_three = float(np.std(series_three))

    assert var_three < var_one, (
        f"Averaging window=3 should reduce per-frame max-|u| variation "
        f"(std_1={var_one:.3f}, std_3={var_three:.3f})"
    )


# -------------------------------------------------------------------------
# 3. A body that disappears between frames doesn't break the next render
# -------------------------------------------------------------------------

def test_history_drops_dead_bodies():
    """Spawn a body, render a few frames so it lands in history, then free
    its hull (simulating fragment cleanup).  A subsequent render must not
    raise — the history snapshot for the now-dead hull is simply ignored
    because the body is no longer in ``world.iter_bodies()``.
    """
    w = _ball_world(diameter=36, material="mud")
    r = PhysicsRenderer(config=RenderConfig(temporal_average_frames=3))

    # Render a couple of frames to populate history.
    r.render(w)
    w.step()
    r.render(w)
    w.step()
    r.render(w)

    # Kill the body: remove from bodies list AND free the hull slot.
    body = next(iter(w.iter_bodies()))
    hid = body.root_hull_id
    w.bodies.remove(body)
    w.hulls.free(hid)

    # The renderer must cope: no body left to render, history still holds
    # the dead snapshot, but the next-frame loop won't touch it.
    frame = r.render(w)
    assert frame.shape[2] == 4, "renderer should still emit an RGBA frame"
    # And one more frame for good measure — history should now have
    # rotated the dead entry out completely.
    frame2 = r.render(w)
    assert frame2.shape[2] == 4


# -------------------------------------------------------------------------
# 4. A newly-spawned body is painted using its current state only
# -------------------------------------------------------------------------

def test_newly_spawned_body_uses_current_only():
    """A body that didn't exist on the previous frame has no history, so
    the renderer must paint it using the current frame only — identical
    to what ``temporal_average_frames=1`` would produce."""
    # Renderer A: averaging on, populate history with an unrelated body,
    # then add the body-of-interest and render once.
    r_avg = PhysicsRenderer(config=RenderConfig(temporal_average_frames=4))
    w_a = _world()
    # Pre-populate history with a different, soon-to-be-removed body so
    # the history list isn't empty when the new body arrives.
    decoy = w_a.create_body(make_circle_silhouette(24), "stone", position=(80.0, 80.0))
    r_avg.render(w_a)
    r_avg.render(w_a)
    # Remove the decoy and add the body-of-interest.
    w_a.bodies.remove(decoy)
    w_a.hulls.free(decoy.root_hull_id)
    w_a.create_body(make_circle_silhouette(48), "mud", position=(0.0, 0.0))
    frame_avg = r_avg.render(w_a)

    # Renderer B: averaging off, freshly built world, same spawn.
    r_one = PhysicsRenderer(config=RenderConfig(temporal_average_frames=1))
    w_b = _world()
    w_b.create_body(make_circle_silhouette(48), "mud", position=(0.0, 0.0))
    frame_one = r_one.render(w_b)

    # The newly-spawned body should look identical in both renderers
    # because the averaging window has no entries for its hull id yet.
    assert np.array_equal(frame_avg, frame_one), (
        "A body without prior history must be rendered using its current "
        "state only — no smoothing from unrelated past snapshots."
    )
