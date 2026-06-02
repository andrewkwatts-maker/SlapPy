"""Tests for slappyengine.topology — connected components on arbitrary graphs."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.topology import (
    BACKGROUND_LABEL,
    connected_components,
    connected_components_grid,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def test_single_node_no_edges_is_one_cluster():
    labels, n = connected_components(1, np.zeros((0, 2), dtype=np.int64))
    assert n == 1
    assert labels.tolist() == [0]


def test_two_disconnected_nodes():
    labels, n = connected_components(2, np.zeros((0, 2), dtype=np.int64))
    assert n == 2
    assert set(labels.tolist()) == {0, 1}


def test_two_nodes_one_edge_one_cluster():
    edges = np.array([[0, 1]], dtype=np.int64)
    labels, n = connected_components(2, edges)
    assert n == 1
    assert labels[0] == labels[1]


def test_chain_of_five_is_one_cluster():
    edges = np.array([[0, 1], [1, 2], [2, 3], [3, 4]], dtype=np.int64)
    labels, n = connected_components(5, edges)
    assert n == 1
    assert len(set(labels.tolist())) == 1


def test_two_chains_two_clusters():
    edges = np.array(
        [[0, 1], [1, 2], [3, 4], [4, 5]], dtype=np.int64
    )
    labels, n = connected_components(6, edges)
    assert n == 2
    # Nodes 0,1,2 share a label; 3,4,5 share another.
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] == labels[5]
    assert labels[0] != labels[3]


def test_active_mask_breaks_connection():
    """Two nodes joined by a single broken edge should be 2 clusters."""
    edges = np.array([[0, 1]], dtype=np.int64)
    active = np.array([False], dtype=bool)
    labels, n = connected_components(2, edges, active=active)
    assert n == 2
    assert labels[0] != labels[1]


def test_node_mask_excludes_background():
    edges = np.array([[0, 1], [2, 3]], dtype=np.int64)
    node_mask = np.array([True, True, False, True], dtype=bool)
    labels, n = connected_components(4, edges, node_mask=node_mask)
    # Node 2 is masked; node 3 is alive but disconnected (edge 2-3 has a dead endpoint).
    assert n == 2  # {0,1} and {3}
    assert labels[2] == BACKGROUND_LABEL
    assert labels[0] == labels[1]
    assert labels[3] != labels[0]


def test_self_loop_tolerated():
    edges = np.array([[0, 0], [0, 1]], dtype=np.int64)
    labels, n = connected_components(2, edges)
    assert n == 1


def test_duplicate_edges_tolerated():
    edges = np.array([[0, 1], [1, 0], [0, 1]], dtype=np.int64)
    labels, n = connected_components(2, edges)
    assert n == 1


def test_large_random_graph_consistent():
    """Random graph: each component should have a unique label."""
    rng = np.random.default_rng(42)
    n = 200
    # Generate a random graph with ~3*n edges; some components will form.
    edges = rng.integers(0, n, size=(3 * n, 2), dtype=np.int64)
    labels, n_components = connected_components(n, edges)
    # Sanity: every node has a label in [0, n_components)
    assert (labels >= 0).all()
    assert (labels < n_components).all()
    # Endpoints of every active edge share a label.
    for a, b in edges:
        assert labels[a] == labels[b]


# ── Backward-compat grid form ──────────────────────────────────────────────


def test_grid_all_solid_one_cluster():
    density = np.full((4, 4), 0.5, dtype=np.float32)
    bond_e = np.full((4, 4), 0.5, dtype=np.float32)
    bond_s = np.full((4, 4), 0.5, dtype=np.float32)
    labels, n = connected_components_grid(density, bond_e, bond_s)
    assert n == 1
    assert (labels[density > 0.1] >= 0).all()
    # All cells share the same label
    assert len(np.unique(labels)) == 1


def test_grid_severed_bond_splits():
    density = np.full((1, 4), 0.5, dtype=np.float32)
    bond_e = np.full((1, 4), 0.5, dtype=np.float32)
    bond_s = np.zeros((1, 4), dtype=np.float32)
    # Sever the middle east bond.
    bond_e[0, 1] = 0.0
    labels, n = connected_components_grid(density, bond_e, bond_s)
    assert n == 2
    # Cells (0,0) and (0,1) share; (0,2) and (0,3) share.
    assert labels[0, 0] == labels[0, 1]
    assert labels[0, 2] == labels[0, 3]
    assert labels[0, 0] != labels[0, 2]


def test_grid_background_cells_are_labeled_minus_one():
    density = np.array([[0.5, 0.0, 0.5]], dtype=np.float32)
    bond_e = np.zeros((1, 3), dtype=np.float32)
    bond_s = np.zeros((1, 3), dtype=np.float32)
    labels, n = connected_components_grid(density, bond_e, bond_s)
    assert n == 2  # Two solid cells, no shared bond → two clusters
    assert labels[0, 1] == BACKGROUND_LABEL
    assert labels[0, 0] != labels[0, 2]


def test_grid_shape_mismatch_raises():
    density = np.zeros((3, 3), dtype=np.float32)
    bond_e = np.zeros((3, 4), dtype=np.float32)
    bond_s = np.zeros((3, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        connected_components_grid(density, bond_e, bond_s)
