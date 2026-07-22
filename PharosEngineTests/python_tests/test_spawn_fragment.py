"""Tests for HullTree.spawn_fragment and the connected-components labeller.

Sprint 4 (fracture follow-up): brittle fracture severs bonds in the cell
grid but leaves *all* mass attached to the original rigid body.  When the
severed cells form a disjoint cluster, ``spawn_fragment`` is responsible
for spinning that cluster off into a new root hull, so the cluster can
actually fly apart.

These tests build a body, hand-sever bonds along a known line to force a
known split, and check that ``spawn_fragment``:

* returns the right number of new hulls,
* the new body inherits the cluster's velocity and angular velocity,
* the parent's cells in the cluster region are emptied, and
* total mass is conserved across the operation.
"""
from __future__ import annotations

import numpy as np

from pharos_engine.physics import PhysicsWorld, make_rect_silhouette
from pharos_engine.physics.cell import CELL_GRID_SIZE
from pharos_engine.physics.cc_label import connected_components

# Cell-struct channel indices used directly here.  Must match
# pharos_engine.physics.cell.CELL_PIXEL_STRUCT.
_IDX_V_X = 2
_IDX_V_Y = 3
_IDX_DENSITY = 9
_IDX_BOND_N = 13
_IDX_BOND_E = 14
_IDX_BOND_S = 15


def _world() -> PhysicsWorld:
    """Zero-gravity world so we don't accumulate momentum from gravity."""
    w = PhysicsWorld(world_bounds=(-200.0, -200.0, 200.0, 200.0))
    w.config.world = type(w.config.world)(
        default_dt=w.config.world.default_dt,
        substeps=w.config.world.substeps,
        gravity=(0.0, 0.0),
    )
    return w


def _make_full_block_body(w: PhysicsWorld, material: str = "iron"):
    """Spawn a fully-solid rectangular body with uniform density everywhere.

    The default ``make_rect_silhouette`` is solid, and once downsampled to
    32x32 every cell ends up with density ≈ 1.0 — exactly what we want
    when we then hand-sever a known line of bonds.
    """
    sil = make_rect_silhouette(64, 64)
    body = w.create_body(sil, material=material, position=(0.0, 0.0))
    # Ensure the density field really is uniform > threshold everywhere
    # so the cc-labeller sees one solid block.
    body.cells[..., _IDX_DENSITY] = 1.0
    return body


# ---------------------------------------------------------------------------
# Labeller smoke tests
# ---------------------------------------------------------------------------

def test_cc_label_single_cluster_when_all_bonds_alive():
    """A fully-bonded grid is one component."""
    density = np.ones((CELL_GRID_SIZE, CELL_GRID_SIZE), dtype=np.float32)
    bond_e = np.ones_like(density)
    bond_s = np.ones_like(density)
    labels, n = connected_components(density, bond_e, bond_s)
    assert n == 1
    assert (labels == 0).all()


def test_cc_label_two_clusters_when_column_bonds_severed():
    """Cutting every east-bond along one column splits the grid in two."""
    density = np.ones((CELL_GRID_SIZE, CELL_GRID_SIZE), dtype=np.float32)
    bond_e = np.ones_like(density)
    bond_s = np.ones_like(density)
    cut_col = CELL_GRID_SIZE // 2 - 1  # bond between col=15 and col=16
    bond_e[:, cut_col] = 0.0
    labels, n = connected_components(density, bond_e, bond_s)
    assert n == 2, f"expected 2 clusters, got {n}"
    left_label = labels[0, 0]
    right_label = labels[0, CELL_GRID_SIZE - 1]
    assert left_label != right_label
    assert (labels[:, : cut_col + 1] == left_label).all()
    assert (labels[:, cut_col + 1 :] == right_label).all()


# ---------------------------------------------------------------------------
# spawn_fragment behaviour
# ---------------------------------------------------------------------------

def test_no_fragmentation_when_single_cluster():
    """An untouched body must return [] — nothing was severed."""
    w = _world()
    body = _make_full_block_body(w)
    spawned = w.hulls.spawn_fragment(
        body.root_hull_id, w.cell_pool, w._materials
    )
    assert spawned == [], f"expected no fragments, got {spawned}"


def test_single_split_spawns_one_new_body():
    """Sever every east-bond on column 15 of a uniformly solid body — the
    left half and right half become two clusters.  ``spawn_fragment`` must
    spin one of them off.
    """
    w = _world()
    body = _make_full_block_body(w)
    parent_id = body.root_hull_id
    parent_mass_before = float(w.hulls.mass[parent_id])

    cells = body.cells
    # Cut the column-15→column-16 bond line.
    cut_col = CELL_GRID_SIZE // 2 - 1
    cells[:, cut_col, _IDX_BOND_E] = 0.0

    spawned = w.hulls.spawn_fragment(parent_id, w.cell_pool, w._materials)
    assert len(spawned) == 1, f"expected one fragment, got {spawned}"

    new_id = spawned[0]
    new_mass = float(w.hulls.mass[new_id])
    parent_mass_after = float(w.hulls.mass[parent_id])
    # Combined mass within 1% of the original (rounded sub-cell loss only).
    err = abs((parent_mass_after + new_mass) - parent_mass_before) / parent_mass_before
    assert err < 0.01, (
        f"combined mass {parent_mass_after + new_mass:.3f} drifted from "
        f"original {parent_mass_before:.3f} by {err:.2%}"
    )


def test_fragment_inherits_cluster_velocity():
    """If a cluster's cells are pre-loaded with v=(50, 0) and the parent
    is at rest, the new fragment's rigid velocity should be ~(50, 0).
    """
    w = _world()
    body = _make_full_block_body(w)
    parent_id = body.root_hull_id

    cells = body.cells
    cut_col = CELL_GRID_SIZE // 2 - 1
    # Sever the bond column.
    cells[:, cut_col, _IDX_BOND_E] = 0.0
    # Load the right-half cells with v=(50, 0).
    right_slice = slice(cut_col + 1, CELL_GRID_SIZE)
    cells[:, right_slice, _IDX_V_X] = 50.0
    cells[:, right_slice, _IDX_V_Y] = 0.0

    spawned = w.hulls.spawn_fragment(parent_id, w.cell_pool, w._materials)
    assert len(spawned) == 1
    new_id = spawned[0]
    vx = float(w.hulls.velocity[new_id, 0])
    vy = float(w.hulls.velocity[new_id, 1])
    # Loose tolerance: the labelled cluster is whichever (left or right)
    # had fewer cells; in this exactly-symmetric cut numpy's argmax keeps
    # whichever label index 0 is.  Either way, the spawned cluster's
    # cells all carry v=(50, 0) OR v=(0, 0) depending on which side spawned.
    # The right-half cluster carries v=(50, 0); the left-half v=(0, 0).
    # The largest cluster is whichever has the larger label-count tie-
    # break — both have 512 cells, np.argmax returns the FIRST max, which
    # is label 0 (the left half, since cc-label walks row-major).  So
    # the spawned hull is the right half with v=(50, 0).
    assert abs(vx - 50.0) < 2.0, f"vx={vx}, expected ~50"
    assert abs(vy) < 2.0, f"vy={vy}, expected ~0"


def test_fragment_inherits_cluster_omega():
    """If a cluster's cells carry a rotational velocity field about a
    point inside the cluster, the spawned fragment's ω must be nonzero
    with the right sign.
    """
    w = _world()
    body = _make_full_block_body(w)
    parent_id = body.root_hull_id
    cs_x = float(w.hulls.cell_size_x[parent_id])
    cs_y = float(w.hulls.cell_size_y[parent_id])

    cells = body.cells
    cut_col = CELL_GRID_SIZE // 2 - 1
    cells[:, cut_col, _IDX_BOND_E] = 0.0
    right_slice = slice(cut_col + 1, CELL_GRID_SIZE)

    # Spin the right half around its own centroid: pure CCW rotation
    # (positive ω in our convention) → v = (-ω*ry, +ω*rx).
    yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
    c_idx = (CELL_GRID_SIZE - 1) * 0.5
    # Right-half centroid is at column index ≈ 23.5 (cells 16..31, mean 23.5).
    right_cx_idx = (cut_col + 1 + CELL_GRID_SIZE - 1) * 0.5
    rx = (xx - right_cx_idx) * cs_x
    ry = (yy - c_idx) * cs_y
    omega_seed = 3.0
    # Body-local velocity field encoding pure rotation about the cluster
    # centroid.  Subtract the cluster mean later by relying on the
    # cluster being closed (this *is* zero-mean over the right half).
    cells[:, right_slice, _IDX_V_X] = (-omega_seed * ry[:, right_slice]).astype(np.float32)
    cells[:, right_slice, _IDX_V_Y] = (+omega_seed * rx[:, right_slice]).astype(np.float32)

    spawned = w.hulls.spawn_fragment(parent_id, w.cell_pool, w._materials)
    assert len(spawned) == 1
    new_id = spawned[0]
    om = float(w.hulls.omega[new_id])
    # Right sign + non-negligible magnitude.  ω is recovered from
    # L_residual/I; for our pure rotation this comes back close to the
    # seeded omega_seed but isn't exact because of discretisation +
    # rounding of the centroid translation.
    assert om > 0.5, f"omega={om}, expected positive and substantial"


def test_parent_loses_fragment_density():
    """After spawn, the parent's cells at the fragment region must have
    density=0 — the parent no longer claims them.
    """
    w = _world()
    body = _make_full_block_body(w)
    parent_id = body.root_hull_id

    cells = body.cells
    cut_col = CELL_GRID_SIZE // 2 - 1
    cells[:, cut_col, _IDX_BOND_E] = 0.0

    spawned = w.hulls.spawn_fragment(parent_id, w.cell_pool, w._materials)
    assert len(spawned) == 1

    # Parent should now have density 0 for the right half (cluster 1, which
    # was spawned).  Left half (cluster 0, the "largest" by tie-break) stays.
    parent_cells_after = w.cell_pool.slot_view(int(w.hulls.cell_grid_id[parent_id]))
    right_density = parent_cells_after[:, cut_col + 1 :, _IDX_DENSITY]
    assert float(right_density.max()) == 0.0, (
        f"parent still claims density in fragment region, max="
        f"{float(right_density.max())}"
    )
    # And the kept half is still solid.
    left_density = parent_cells_after[:, : cut_col + 1, _IDX_DENSITY]
    assert float(left_density.min()) > 0.5, (
        f"parent's kept half lost density, min={float(left_density.min())}"
    )


def test_total_mass_conserved_across_fragment():
    """Σ (parent_after + all fragments) mass == original parent mass
    within 1%.  Sub-cell rounding when translating the cluster into the
    new grid is the only allowed loss path.
    """
    w = _world()
    body = _make_full_block_body(w)
    parent_id = body.root_hull_id
    rho = body.material.density_rho
    cs_x = float(w.hulls.cell_size_x[parent_id])
    cs_y = float(w.hulls.cell_size_y[parent_id])
    cell_area = cs_x * cs_y

    def _cells_mass(cells: np.ndarray) -> float:
        return float((rho * cells[..., _IDX_DENSITY] * cell_area).sum())

    parent_cells_before = w.cell_pool.slot_view(int(w.hulls.cell_grid_id[parent_id]))
    m_before = _cells_mass(parent_cells_before)

    # Two cuts → three clusters (rough thirds).
    cells = body.cells
    cells[:, 9, _IDX_BOND_E] = 0.0
    cells[:, 20, _IDX_BOND_E] = 0.0

    spawned = w.hulls.spawn_fragment(parent_id, w.cell_pool, w._materials)
    assert len(spawned) >= 1, (
        f"expected at least one fragment after two cuts, got {spawned}"
    )

    # Sum cell-mass across parent + all fragments.
    total_m_after = _cells_mass(
        w.cell_pool.slot_view(int(w.hulls.cell_grid_id[parent_id]))
    )
    for new_id in spawned:
        new_cells = w.cell_pool.slot_view(int(w.hulls.cell_grid_id[new_id]))
        total_m_after += _cells_mass(new_cells)

    err = abs(total_m_after - m_before) / m_before
    assert err < 0.01, (
        f"cell-mass not conserved: before={m_before:.4f}, "
        f"after={total_m_after:.4f}, err={err:.2%}"
    )
