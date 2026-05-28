"""Tripwire tests for :mod:`slappyengine.topology` connected components.

This test guards the Phase B repackage of the union-find core out of
``slappyengine.physics.cc_label`` into the clean public
``slappyengine.topology`` home. If Phase D later deletes the old physics
shim, the public surface (and the four invariants below) must keep
working.

Covered cases:

* Basic round-trip: 4 nodes, two disjoint pairs bonded -> exactly 2 labels.
* Single component: every node bonded -> exactly 1 label.
* Degenerate: zero edges -> exactly N labels.
* Cross-check: the legacy 2-D grid form must produce the same partition
  as ``physics.cc_label.connected_components`` for identical inputs
  (label-id permutations are allowed).
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.topology import (
    BACKGROUND_LABEL,
    connected_components,
    connected_components_grid,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _partition_from_labels(labels: np.ndarray) -> frozenset[frozenset[int]]:
    """Convert a label array into a permutation-invariant partition.

    Background-labelled cells (``BACKGROUND_LABEL``) are dropped so they
    don't bleed into the comparison. The result is a frozenset of
    frozensets — two label arrays produce equal partitions iff they
    encode the same grouping, regardless of which integer id was used
    for which group.
    """
    flat = labels.reshape(-1)
    buckets: dict[int, set[int]] = {}
    for idx, lbl in enumerate(flat.tolist()):
        if lbl == BACKGROUND_LABEL:
            continue
        buckets.setdefault(int(lbl), set()).add(idx)
    return frozenset(frozenset(v) for v in buckets.values())


# ── Required tripwire cases ────────────────────────────────────────────────


def test_basic_two_pairs_gives_two_labels():
    """4 nodes, two disjoint bonded pairs (0-1, 2-3) -> exactly 2 labels."""
    edges = np.array([[0, 1], [2, 3]], dtype=np.int64)
    labels, n = connected_components(4, edges)

    assert n == 2
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    # All labels are non-background.
    assert (labels != BACKGROUND_LABEL).all()


def test_single_component_fully_connected():
    """4 nodes, edges forming one chain/cycle -> exactly 1 label."""
    edges = np.array(
        [[0, 1], [1, 2], [2, 3], [3, 0]],  # cycle
        dtype=np.int64,
    )
    labels, n = connected_components(4, edges)

    assert n == 1
    assert len(set(labels.tolist())) == 1
    assert labels[0] != BACKGROUND_LABEL


def test_degenerate_zero_bonds_gives_n_labels():
    """Zero edges on N nodes -> exactly N singleton clusters."""
    n_nodes = 7
    edges = np.zeros((0, 2), dtype=np.int64)
    labels, n = connected_components(n_nodes, edges)

    assert n == n_nodes
    # Every node is its own cluster.
    assert len(set(labels.tolist())) == n_nodes
    # All are valid labels (no background since no node_mask was given).
    assert (labels >= 0).all()
    assert (labels < n_nodes).all()


def test_cross_check_against_physics_cc_label_grid():
    """Public topology grid form must match legacy physics.cc_label exactly.

    Builds a 4x4 grid with two solid regions split by a row of background
    cells and a severed east bond. The new public API and the legacy
    ``physics.cc_label.connected_components`` must produce the same
    partition (modulo label-id permutation).
    """
    # Import inside the test so collection doesn't fail if the legacy
    # module ever goes away unexpectedly.
    from slappyengine.physics import cc_label as legacy

    rng = np.random.default_rng(20260529)
    h, w = 4, 4
    # Random but reproducible density/bond fields with a clear split.
    density = rng.uniform(0.2, 1.0, size=(h, w)).astype(np.float32)
    bond_e = rng.uniform(0.1, 1.0, size=(h, w)).astype(np.float32)
    bond_s = rng.uniform(0.1, 1.0, size=(h, w)).astype(np.float32)

    # Carve a clear topology: knock out row 1 entirely (background),
    # sever the (0,1)-(0,2) east bond, sever the (2,1)-(2,2) east bond.
    density[1, :] = 0.0
    bond_e[0, 1] = 0.0
    bond_e[2, 1] = 0.0

    new_labels, new_n = connected_components_grid(
        density, bond_e, bond_s,
        density_threshold=0.1,
        bond_threshold=0.05,
    )
    legacy_labels, legacy_n = legacy.connected_components(
        density, bond_e, bond_s,
        density_threshold=0.1,
        bond_threshold=0.05,
    )

    # Same number of clusters.
    assert new_n == legacy_n

    # Same partition of cells (modulo label-id permutation).
    assert _partition_from_labels(new_labels) == _partition_from_labels(
        legacy_labels
    )

    # Same background mask.
    new_bg = (new_labels == BACKGROUND_LABEL)
    legacy_bg = (legacy_labels == legacy.BACKGROUND_LABEL)
    np.testing.assert_array_equal(new_bg, legacy_bg)


# ── Sanity surface: lazy-import path is wired ──────────────────────────────


def test_topology_is_importable_as_submodule():
    """``from slappyengine import topology`` must resolve to this module."""
    import slappyengine

    topology_mod = slappyengine.topology  # noqa: F841 — triggers __getattr__
    assert hasattr(topology_mod, "connected_components")
    assert hasattr(topology_mod, "BACKGROUND_LABEL")
