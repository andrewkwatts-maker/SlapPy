"""CCD IK converges for reachable targets, fails gracefully for unreachable ones."""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.dynamics import IKChainSpec, World, solve_ik


def _make_chain(world: World, lengths: list[float]) -> list[int]:
    """Spawn a chain along +x and return its node indices."""
    nodes: list[int] = []
    x = 0.0
    for i, L in enumerate(lengths):
        nodes.append(world.add_node((x, 0.0), mass=1.0 if i > 0 else 0.0))
        x += L
    # tip
    nodes.append(world.add_node((x, 0.0), mass=1.0))
    return nodes


def test_ik_converges_for_reachable_target():
    w = World(gravity=(0.0, 0.0))
    nodes = _make_chain(w, [1.0, 1.0, 1.0])  # reach = 3, 4 nodes including tip
    spec = IKChainSpec(node_indices=nodes, target=(1.5, 1.5))
    ok = solve_ik(spec, w, iterations=40, tolerance=0.02)
    assert ok
    tip = w.positions[nodes[-1]]
    assert float(np.linalg.norm(tip - np.array([1.5, 1.5]))) < 0.05


def test_ik_returns_false_for_unreachable_target():
    w = World(gravity=(0.0, 0.0))
    nodes = _make_chain(w, [1.0, 1.0, 1.0])  # reach = 3
    spec = IKChainSpec(node_indices=nodes, target=(100.0, 0.0))
    ok = solve_ik(spec, w, iterations=10, tolerance=0.01)
    assert not ok
    # No NaN, no crash, chain extended toward the target.
    tip = w.positions[nodes[-1]]
    assert not np.isnan(tip).any()
    # Chain should straighten toward +x.
    assert tip[0] > 2.5


def test_ik_root_pin_preserved():
    w = World(gravity=(0.0, 0.0))
    nodes = _make_chain(w, [1.0, 1.0, 1.0])
    root_pos = w.positions[nodes[0]].copy()
    spec = IKChainSpec(
        node_indices=nodes,
        target=(0.5, 2.0),
        fixed_root=True,
    )
    solve_ik(spec, w, iterations=20, tolerance=0.05)
    # Root should not have moved.
    assert np.allclose(w.positions[nodes[0]], root_pos, atol=1e-9)
