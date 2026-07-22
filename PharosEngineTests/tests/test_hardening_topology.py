"""Input-validation tests for the public ``pharos_engine.topology`` API.

Mirrors the ``test_hardening_dynamics.py`` policy: validate at system
boundaries, refuse bad input loudly rather than silently coercing it.
Each test pins one rejection path with a substring match so messages
stay useful for callers debugging their authoring code.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.topology import (
    BACKGROUND_LABEL,
    connected_components,
)


# ---------------------------------------------------------------------------
# n_nodes
# ---------------------------------------------------------------------------


def test_connected_components_rejects_float_n_nodes():
    edges = np.zeros((0, 2), dtype=np.int64)
    with pytest.raises(TypeError, match="connected_components: n_nodes"):
        connected_components(3.7, edges)  # type: ignore[arg-type]


def test_connected_components_rejects_string_n_nodes():
    edges = np.zeros((0, 2), dtype=np.int64)
    with pytest.raises(TypeError, match="connected_components: n_nodes"):
        connected_components("five", edges)  # type: ignore[arg-type]


def test_connected_components_rejects_negative_n_nodes():
    edges = np.zeros((0, 2), dtype=np.int64)
    with pytest.raises(ValueError, match="n_nodes"):
        connected_components(-1, edges)


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------


def test_connected_components_rejects_list_edges():
    with pytest.raises(TypeError, match="edges"):
        connected_components(3, [[0, 1], [1, 2]])  # type: ignore[arg-type]


def test_connected_components_rejects_float_dtype_edges():
    edges = np.array([[0.0, 1.0]], dtype=np.float64)
    with pytest.raises(TypeError, match="edges"):
        connected_components(3, edges)


def test_connected_components_rejects_one_d_edges():
    edges = np.array([0, 1, 2], dtype=np.int64)
    with pytest.raises(ValueError, match=r"\(E, 2\)"):
        connected_components(3, edges)


def test_connected_components_rejects_wrong_second_dim_edges():
    edges = np.array([[0, 1, 2]], dtype=np.int64)
    with pytest.raises(ValueError, match=r"\(E, 2\)"):
        connected_components(3, edges)


def test_connected_components_rejects_negative_edge_endpoint():
    edges = np.array([[-1, 0]], dtype=np.int64)
    with pytest.raises(ValueError, match="minimum"):
        connected_components(3, edges)


def test_connected_components_rejects_too_large_edge_endpoint():
    edges = np.array([[0, 99]], dtype=np.int64)
    with pytest.raises(ValueError, match="maximum"):
        connected_components(3, edges)


def test_connected_components_rejects_edge_equal_to_n_nodes():
    # Boundary: n_nodes=4 means valid ids are [0, 3]. id=4 is out of range.
    edges = np.array([[0, 4]], dtype=np.int64)
    with pytest.raises(ValueError, match="maximum"):
        connected_components(4, edges)


# ---------------------------------------------------------------------------
# active
# ---------------------------------------------------------------------------


def test_connected_components_rejects_active_wrong_length():
    edges = np.array([[0, 1], [1, 2]], dtype=np.int64)
    active = np.array([True], dtype=bool)
    with pytest.raises(ValueError, match="active"):
        connected_components(3, edges, active=active)


def test_connected_components_rejects_active_non_bool_dtype():
    edges = np.array([[0, 1]], dtype=np.int64)
    active = np.array([1], dtype=np.int64)
    with pytest.raises(TypeError, match="active"):
        connected_components(3, edges, active=active)


def test_connected_components_rejects_active_not_ndarray():
    edges = np.array([[0, 1]], dtype=np.int64)
    with pytest.raises(TypeError, match="active"):
        connected_components(3, edges, active=[True])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# node_mask
# ---------------------------------------------------------------------------


def test_connected_components_rejects_node_mask_wrong_length():
    edges = np.array([[0, 1]], dtype=np.int64)
    mask = np.array([True, False], dtype=bool)  # wrong length (2 != n_nodes=3)
    with pytest.raises(ValueError, match="node_mask"):
        connected_components(3, edges, node_mask=mask)


def test_connected_components_rejects_node_mask_non_bool():
    edges = np.array([[0, 1]], dtype=np.int64)
    mask = np.array([1, 0, 1], dtype=np.int64)
    with pytest.raises(TypeError, match="node_mask"):
        connected_components(3, edges, node_mask=mask)


# ---------------------------------------------------------------------------
# Positive sanity — validators must not break the canonical paths.
# ---------------------------------------------------------------------------


def test_positive_empty_edges_returns_singletons():
    edges = np.zeros((0, 2), dtype=np.int64)
    labels, n = connected_components(5, edges)
    assert n == 5
    assert sorted(labels.tolist()) == [0, 1, 2, 3, 4]


def test_positive_two_pairs_yields_two_components():
    edges = np.array([[0, 1], [2, 3]], dtype=np.int64)
    labels, n = connected_components(4, edges)
    assert n == 2
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]


def test_positive_zero_n_nodes_with_zero_edges():
    edges = np.zeros((0, 2), dtype=np.int64)
    labels, n = connected_components(0, edges)
    assert n == 0
    assert labels.shape == (0,)


def test_positive_int32_edges_accepted():
    edges = np.array([[0, 1]], dtype=np.int32)
    labels, n = connected_components(3, edges)
    assert n == 2  # nodes 0-1 merged, node 2 alone
    assert labels[0] == labels[1]
    assert labels[2] != labels[0]


def test_positive_active_and_node_mask_both_applied():
    edges = np.array([[0, 1], [1, 2]], dtype=np.int64)
    active = np.array([True, False], dtype=bool)
    mask = np.array([True, True, True], dtype=bool)
    labels, n = connected_components(3, edges, active=active, node_mask=mask)
    # Only edge (0,1) is active; 2 stays alone.
    assert n == 2
    assert labels[0] == labels[1]
    assert labels[2] != labels[0]
