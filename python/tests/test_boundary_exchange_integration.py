"""Integration tests for :class:`BoundaryExchange` driven through
:meth:`PhysicsWorld.step`.

The unit suite in ``test_boundary_exchange.py`` drives the exchange routine
directly with hand-crafted contact pairs.  These tests instead exercise the
*wired-up* path: a real ``PhysicsWorld.step()`` loop, real broadphase
contacts emitted by the narrowphase, and the boundary-exchange config flag.

Test methodology
----------------

A drop scenario also fires the *impact-injection* heat path
(:meth:`PhysicsWorld._inject_local_velocity_field`), which on a typical
ball-onto-ground impact deposits orders of magnitude more heat than the
seam-conduction pass moves in one frame.  To isolate the wiring under
test we use a **no-gravity world** and **pin the upper body in slight
overlap with the ground each frame**:

  * Closing velocity is zero ⇒ no impulse, no impact heat.
  * Narrowphase still emits the contact pair every frame ⇒ the seam
    exchange runs ~120 times instead of once.

The ground we use is a fixed slab the **same size** as the upper body
so the strip masses on each side of the seam are comparable; this
prevents heat dilution into a huge sink that would mask the transfer.

The two materially-distinct tests assert the seam pass actually
conducted heat (lava cooled by >10%, steel cooled).  Two further tests
verify the config flag toggles the pass and that wall contacts are
skipped cleanly.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.world import WorldConfig


# --- channel indices (mirror cell.CELL_PIXEL_STRUCT) ------------------------
_IDX_DENSITY = 9
_IDX_HEAT = 12


# --- helpers ----------------------------------------------------------------

def _no_gravity_world() -> PhysicsWorld:
    """A no-gravity world: bodies in static contact stay in contact with
    zero closing velocity.  The impact-heat path is therefore silent and
    only :class:`BoundaryExchange` can move heat across the seam.
    """
    w = PhysicsWorld(world_bounds=(-500.0, -500.0, 500.0, 500.0))
    w.config.world = WorldConfig(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    return w


def _set_uniform_heat(body, heat_value: float) -> None:
    """Set heat to ``heat_value`` on every cell that has mass."""
    cells = body.cells
    assert cells is not None
    density = cells[..., _IDX_DENSITY]
    mask = density > 0.0
    cells[..., _IDX_HEAT] = 0.0
    cells[..., _IDX_HEAT][mask] = heat_value


def _max_heat(body) -> float:
    """Maximum heat across cells with positive density."""
    cells = body.cells
    assert cells is not None
    mask = cells[..., _IDX_DENSITY] > 0.0
    if not mask.any():
        return 0.0
    return float(cells[..., _IDX_HEAT][mask].max())


def _total_heat_energy(body) -> float:
    """Σ(m_cell × h_cell) — the conservation quantity exchange preserves."""
    cells = body.cells
    assert cells is not None
    h = body.world.hulls
    hid = body.root_hull_id
    area = float(h.cell_size_x[hid]) * float(h.cell_size_y[hid])
    return float(
        (body.material.density_rho
         * cells[..., _IDX_DENSITY].astype(np.float64)
         * area
         * cells[..., _IDX_HEAT].astype(np.float64)).sum()
    )


def _pin(world: PhysicsWorld, body, position=(0.0, 0.0)) -> None:
    """Pin a body's hull at ``position`` with zero velocity.

    Called each frame to defeat the narrowphase's position-correction
    pushback, so the bodies stay in slight overlap and the broadphase
    re-emits the contact every step.
    """
    hid = body.root_hull_id
    world.hulls.position[hid, 0] = float(position[0])
    world.hulls.position[hid, 1] = float(position[1])
    world.hulls.velocity[hid, 0] = 0.0
    world.hulls.velocity[hid, 1] = 0.0
    world.hulls.omega[hid] = 0.0


def _build_lava_on_ice(enable_exchange: bool):
    """Equal-size rectangle ice slab + lava block in static contact."""
    w = _no_gravity_world()
    w.config.boundary_exchange.enabled = enable_exchange
    ice = w.create_body(
        make_rect_silhouette(32, 32),
        material="ice",
        position=(0.0, 24.0),  # top at y=8, bottom at y=40
        fixed=True,
    )
    lava = w.create_body(
        make_rect_silhouette(32, 32),
        material="lava",
        position=(0.0, 0.0),   # top at y=-16, bottom at y=16 ⇒ overlap y∈[8,16]
    )
    _set_uniform_heat(lava, 12.0)
    _set_uniform_heat(ice, 0.0)
    return w, lava, ice


def _build_steel_on_stone(enable_exchange: bool):
    w = _no_gravity_world()
    w.config.boundary_exchange.enabled = enable_exchange
    stone = w.create_body(
        make_rect_silhouette(32, 32),
        material="stone",
        position=(0.0, 24.0),
        fixed=True,
    )
    steel = w.create_body(
        make_rect_silhouette(32, 32),
        material="steel",
        position=(0.0, 0.0),
    )
    _set_uniform_heat(steel, 8.0)
    _set_uniform_heat(stone, 0.0)
    return w, steel, stone


def _run_pinned(w: PhysicsWorld, mover, frames: int) -> int:
    """Step ``frames`` times, pinning ``mover`` in overlap every frame."""
    contacts_seen = 0
    for _ in range(frames):
        _pin(w, mover, position=(0.0, 0.0))
        contacts = w.step()
        contacts_seen += sum(1 for p in contacts if p.b >= 0)
    return contacts_seen


# --- tests ------------------------------------------------------------------

def test_lava_in_contact_with_ice_loses_heat_over_time():
    """Pin a pre-heated lava block in static contact with an equal-size
    cold ice slab.  After 120 frames:

      * Lava's max heat must have dropped by >10% (exchange + internal
        diffusion + radiation drain it through the seam).
      * Ice must have gained measurable heat across the seam — total
        thermal energy on the ice side rises by more than the
        exchange-OFF baseline by at least 0.5 (heat-energy units).
    """
    w_on, lava_on, ice_on = _build_lava_on_ice(enable_exchange=True)
    w_off, lava_off, ice_off = _build_lava_on_ice(enable_exchange=False)

    lava_max_initial = _max_heat(lava_on)
    assert lava_max_initial == pytest.approx(12.0)

    contacts_on = _run_pinned(w_on, lava_on, 120)
    contacts_off = _run_pinned(w_off, lava_off, 120)

    assert contacts_on >= 100, (
        f"only {contacts_on}/120 frames produced body-body contacts — "
        f"the integration is not exercising the seam pass each step"
    )
    assert contacts_off >= 100

    lava_max_final = _max_heat(lava_on)
    drop_pct = (lava_max_initial - lava_max_final) / lava_max_initial
    assert drop_pct > 0.10, (
        f"lava max heat dropped only {drop_pct * 100:.1f}% "
        f"({lava_max_initial:.4f} → {lava_max_final:.4f}); expected >10%"
    )

    ice_energy_on = _total_heat_energy(ice_on)
    ice_energy_off = _total_heat_energy(ice_off)
    # With exchange disabled and no closing velocity, NO heat path can
    # reach the ice — its thermal energy stays at zero.
    assert ice_energy_off == pytest.approx(0.0, abs=1e-4), (
        f"ice gained heat ({ice_energy_off:.6e}) with exchange disabled"
    )
    assert ice_energy_on - ice_energy_off > 0.5, (
        f"ice gained only {ice_energy_on - ice_energy_off:.4f} additional "
        f"heat energy from the boundary exchange — expected >0.5"
    )


def test_steel_ball_on_cold_stone_thermalizes():
    """Pin a pre-heated steel block on cold stone.  After 120 frames the
    ball's max heat must drop (some flowed across the seam) AND the
    stone must end up hotter than with exchange disabled.
    """
    w_on, steel_on, stone_on = _build_steel_on_stone(enable_exchange=True)
    w_off, steel_off, stone_off = _build_steel_on_stone(enable_exchange=False)

    steel_max_initial = _max_heat(steel_on)

    _run_pinned(w_on, steel_on, 120)
    _run_pinned(w_off, steel_off, 120)

    steel_max_final = _max_heat(steel_on)
    assert steel_max_final < steel_max_initial, (
        f"steel max heat did not drop "
        f"({steel_max_final:.4f} vs {steel_max_initial:.4f})"
    )

    stone_energy_on = _total_heat_energy(stone_on)
    stone_energy_off = _total_heat_energy(stone_off)
    assert stone_energy_off == pytest.approx(0.0, abs=1e-4)
    assert stone_energy_on > stone_energy_off, (
        f"stone did not absorb heat across the seam "
        f"(on={stone_energy_on:.4f}, off={stone_energy_off:.4f})"
    )


def test_disable_via_config_stops_exchange():
    """With ``boundary_exchange.enabled = False`` and static contact (no
    impact heating), ice must NOT pick up any heat from a lava block —
    the seam pass is the only path between them.
    """
    w, lava, ice = _build_lava_on_ice(enable_exchange=False)
    _run_pinned(w, lava, 120)

    ice_total = _total_heat_energy(ice)
    # No closing velocity ⇒ no impact heat; exchange disabled ⇒ no seam
    # path either.  Total thermal energy on the ice side must be zero
    # (up to float rounding from the per-pixel kernel running on cold cells).
    assert ice_total == pytest.approx(0.0, abs=1e-4), (
        f"ice gained heat energy ({ice_total:.6e}) with exchange disabled — "
        f"something other than BoundaryExchange is moving heat across the seam"
    )


def test_exchange_runs_for_walls_too():
    """A hot ball bouncing inside ``world_bounds`` generates wall contacts
    (``b == -1``).  :class:`BoundaryExchange` must skip those rather than
    crashing — walls have no cells to exchange with.
    """
    # Re-enable gravity so the ball actually hits walls.
    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    ball = w.create_body(
        make_circle_silhouette(24),
        material="steel",
        position=(0.0, 0.0),
        velocity=(120.0, 60.0),
    )
    _set_uniform_heat(ball, 5.0)

    saw_wall_contact = False
    for _ in range(120):
        contacts = w.step()  # must not raise
        if any(p.b < 0 for p in contacts):
            saw_wall_contact = True

    assert saw_wall_contact, (
        "expected at least one wall contact in this scenario — "
        "the BoundaryExchange wall-skip path was not exercised"
    )
    # Heat values stay finite (no NaN / Inf) — walls were skipped
    # cleanly without dereferencing the b=-1 slot.
    assert np.all(np.isfinite(ball.cells[..., _IDX_HEAT]))
