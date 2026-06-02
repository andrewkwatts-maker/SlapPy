"""Tests for the per-frame heat-exchange pass across body boundaries.

These tests exercise :class:`BoundaryExchange` in isolation — we drive it
directly with handcrafted :class:`ContactPair` objects rather than going
through :meth:`PhysicsWorld.step`, because the integration into
``world.py`` is owned by another agent and not yet wired up.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.deform_modes import CellMaterial
from slappyengine.physics import (
    BoundaryExchange,
    ContactPair,
    PhysicsWorld,
    make_rect_silhouette,
)


# --- helpers ----------------------------------------------------------------

def _world() -> PhysicsWorld:
    """No-gravity world large enough to hold two side-by-side rect bodies."""
    w = PhysicsWorld(world_bounds=(-1000.0, -1000.0, 1000.0, 1000.0))
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    return w


def _exchange(w: PhysicsWorld) -> BoundaryExchange:
    return BoundaryExchange(
        cell_pool=w.cell_pool,
        hulls=w.hulls,
        body_lookup=w._body_for_hull,
        material_lookup=w._materials,
    )


def _make_pair(a_hull: int, b_hull: int, normal=(1.0, 0.0)) -> ContactPair:
    """A synthetic contact: a → b along ``normal``, at origin."""
    return ContactPair(
        a=a_hull,
        b=b_hull,
        normal=normal,
        depth=0.0,
        point=(0.0, 0.0),
    )


def _set_uniform_heat(body, heat_value: float) -> None:
    """Set heat to ``heat_value`` on every cell that has mass."""
    cells = body.cells
    assert cells is not None
    density = cells[..., 9]
    mask = density > 0.0
    cells[..., 12] = 0.0
    cells[..., 12][mask] = heat_value


def _total_heat_energy(body) -> float:
    """Σ(m_cell * h_cell) — the quantity BoundaryExchange must preserve."""
    cells = body.cells
    assert cells is not None
    density = cells[..., 9].astype(np.float64)
    heat = cells[..., 12].astype(np.float64)
    # cell_size is uniform per body; pull from the hull tree.
    h = body.world.hulls
    hid = body.root_hull_id
    cell_area = float(h.cell_size_x[hid]) * float(h.cell_size_y[hid])
    rho = body.material.density_rho
    return float((rho * density * cell_area * heat).sum())


def _total_mass(body) -> float:
    cells = body.cells
    assert cells is not None
    density = cells[..., 9].astype(np.float64)
    h = body.world.hulls
    hid = body.root_hull_id
    cell_area = float(h.cell_size_x[hid]) * float(h.cell_size_y[hid])
    return float((body.material.density_rho * density * cell_area).sum())


def _mean_temperature(body) -> float:
    """Mass-weighted mean heat across all cells with mass."""
    m = _total_mass(body)
    if m <= 0.0:
        return 0.0
    return _total_heat_energy(body) / m


# --- tests ------------------------------------------------------------------

def test_lava_cools_against_ice_in_contact():
    """A pre-heated lava body next to ice should cool while ice warms up."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    lava = w.create_body(sil, "lava", position=(-16.0, 0.0))
    ice = w.create_body(sil, "ice", position=(16.0, 0.0))

    _set_uniform_heat(lava, 12.0)
    _set_uniform_heat(ice, 0.0)

    t_lava_0 = _mean_temperature(lava)
    t_ice_0 = _mean_temperature(ice)
    assert t_lava_0 > t_ice_0

    bx = _exchange(w)
    pair = _make_pair(lava.root_hull_id, ice.root_hull_id, normal=(1.0, 0.0))
    for _ in range(50):
        bx.exchange([pair], dt=1.0 / 60.0)

    t_lava_1 = _mean_temperature(lava)
    t_ice_1 = _mean_temperature(ice)

    assert t_lava_1 < t_lava_0, "lava should have cooled"
    assert t_ice_1 > t_ice_0, "ice should have warmed"
    # Should not have crossed over — equilibrium lies between the two.
    assert t_lava_1 > t_ice_1


def test_heat_exchange_conserves_total_thermal_energy():
    """Σ(mass × heat) across both bodies must be exact before vs. after."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    a = w.create_body(sil, "lava", position=(-16.0, 0.0))
    b = w.create_body(sil, "ice", position=(16.0, 0.0))

    _set_uniform_heat(a, 8.0)
    _set_uniform_heat(b, 1.0)

    total_before = _total_heat_energy(a) + _total_heat_energy(b)

    bx = _exchange(w)
    pair = _make_pair(a.root_hull_id, b.root_hull_id, normal=(1.0, 0.0))
    for _ in range(25):
        bx.exchange([pair], dt=1.0 / 60.0)

    total_after = _total_heat_energy(a) + _total_heat_energy(b)
    # Float32 backing + float64 accumulation: rounding tolerance.
    assert total_after == pytest.approx(total_before, rel=1e-5, abs=1e-4)


def test_no_exchange_when_temperatures_equal():
    """Equal temperatures → flux is zero → heat fields unchanged."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    a = w.create_body(sil, "stone", position=(-16.0, 0.0))
    b = w.create_body(sil, "stone", position=(16.0, 0.0))

    _set_uniform_heat(a, 3.5)
    _set_uniform_heat(b, 3.5)

    before_a = a.cells[..., 12].copy()
    before_b = b.cells[..., 12].copy()

    bx = _exchange(w)
    pair = _make_pair(a.root_hull_id, b.root_hull_id, normal=(1.0, 0.0))
    for _ in range(10):
        bx.exchange([pair], dt=1.0 / 60.0)

    np.testing.assert_array_equal(a.cells[..., 12], before_a)
    np.testing.assert_array_equal(b.cells[..., 12], before_b)


def test_exchange_uses_harmonic_mean_of_thermal_k():
    """A low-thermal_k insulator dominates the rate (series-resistor analog).

    Compare two scenarios with identical starting heat and density but
    different conductivities:
        scenario A: thermal_k = 10, 10  →  k_harm = 10
        scenario B: thermal_k = 10, 0.1 →  k_harm ≈ 0.198

    After the same number of identical-dt exchanges, scenario B should
    have transferred far less energy.
    """
    sil = make_rect_silhouette(32, 32)

    def run(ka: float, kb: float) -> float:
        """Return the heat that flowed from a to b after N steps."""
        w = _world()
        # Build custom materials by tweaking a registered material's
        # CellMaterial in-place via the world's lookup.
        a = w.create_body(sil, "stone", position=(-16.0, 0.0))
        b = w.create_body(sil, "stone", position=(16.0, 0.0))
        # Each body has its own material_id entry in w._materials; we
        # need separate CellMaterial instances so we don't clobber the
        # shared one.
        mid_a = int(w.hulls.material_id[a.root_hull_id])
        # They share an id because both used "stone".  Force a fresh id
        # for b so we can give it a different thermal_k.
        new_mat_a = CellMaterial(**{**a.material.__dict__})
        new_mat_a.thermal_k = ka
        new_mat_b = CellMaterial(**{**b.material.__dict__})
        new_mat_b.thermal_k = kb
        # Register fresh material slots so we don't mutate the shared one.
        w._materials[mid_a] = new_mat_a
        # Mint a new id for b so it points at the distinct material.
        new_id_b = max(w._materials.keys()) + 1
        w._materials[new_id_b] = new_mat_b
        w.hulls.material_id[b.root_hull_id] = new_id_b
        # Update PhysicsBody.material so heat-energy bookkeeping uses the
        # right density_rho (unchanged here, but for safety).
        a.material = new_mat_a
        b.material = new_mat_b

        _set_uniform_heat(a, 10.0)
        _set_uniform_heat(b, 0.0)
        e_a0 = _total_heat_energy(a)
        bx = _exchange(w)
        pair = _make_pair(a.root_hull_id, b.root_hull_id, normal=(1.0, 0.0))
        for _ in range(5):
            bx.exchange([pair], dt=1.0 / 60.0)
        return e_a0 - _total_heat_energy(a)

    flow_balanced = run(10.0, 10.0)
    flow_insulated = run(10.0, 0.1)
    assert flow_balanced > 0.0
    assert flow_insulated > 0.0
    # An insulator on one side should slow the rate by at least an order
    # of magnitude: harmonic mean of (10, 0.1) ≈ 0.198 vs. 10.
    assert flow_insulated < flow_balanced * 0.1


def test_exchange_skips_non_overlapping_bodies():
    """No contact pair → nothing changes."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    a = w.create_body(sil, "lava", position=(-100.0, 0.0))
    b = w.create_body(sil, "ice", position=(100.0, 0.0))

    _set_uniform_heat(a, 12.0)
    _set_uniform_heat(b, 0.0)

    before_a = a.cells[..., 12].copy()
    before_b = b.cells[..., 12].copy()

    bx = _exchange(w)
    # Empty contact list — broadphase emitted nothing because AABBs
    # don't overlap.
    bx.exchange([], dt=1.0 / 60.0)

    np.testing.assert_array_equal(a.cells[..., 12], before_a)
    np.testing.assert_array_equal(b.cells[..., 12], before_b)


def test_exchange_skips_wall_contacts():
    """ContactPair with b < 0 (wall) should be silently skipped."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    a = w.create_body(sil, "lava", position=(0.0, 0.0))
    _set_uniform_heat(a, 12.0)
    before_a = a.cells[..., 12].copy()

    bx = _exchange(w)
    wall_pair = ContactPair(
        a=a.root_hull_id, b=-1, normal=(1.0, 0.0), depth=0.0, point=(0.0, 0.0),
    )
    bx.exchange([wall_pair], dt=1.0 / 60.0)
    np.testing.assert_array_equal(a.cells[..., 12], before_a)


def test_exchange_zero_dt_is_noop():
    """dt <= 0 should not mutate any cell."""
    w = _world()
    sil = make_rect_silhouette(32, 32)
    a = w.create_body(sil, "lava", position=(-16.0, 0.0))
    b = w.create_body(sil, "ice", position=(16.0, 0.0))
    _set_uniform_heat(a, 12.0)
    _set_uniform_heat(b, 0.0)
    before_a = a.cells[..., 12].copy()
    before_b = b.cells[..., 12].copy()

    bx = _exchange(w)
    pair = _make_pair(a.root_hull_id, b.root_hull_id, normal=(1.0, 0.0))
    bx.exchange([pair], dt=0.0)
    np.testing.assert_array_equal(a.cells[..., 12], before_a)
    np.testing.assert_array_equal(b.cells[..., 12], before_b)
