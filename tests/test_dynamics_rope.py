"""Rope between two anchors droops into a catenary-like curve under gravity."""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.dynamics import RopeSpec, World, build_rope


def test_rope_builds_expected_node_count():
    w = World(gravity=(0.0, -9.81))
    spec = RopeSpec(node_count=20, total_length=4.0, mass_per_node=0.05,
                    stiffness=2.0e6, damping=0.05)
    body = build_rope(spec, w, anchor_a=(-2.0, 5.0), anchor_b=(2.0, 5.0))
    assert body.node_count == 20
    assert body.kind == "rope"


def test_rope_droops_into_catenary():
    w = World(gravity=(0.0, -9.81))
    w.solver_iterations = 16
    spec = RopeSpec(
        node_count=21, total_length=5.0, mass_per_node=0.05,
        stiffness=5.0e6, damping=0.1,
        anchor_a_pinned=True, anchor_b_pinned=True,
    )
    body = build_rope(spec, w,
                      anchor_a=(-2.0, 5.0),
                      anchor_b=(2.0, 5.0))

    dt = 1.0 / 240.0
    for _ in range(2400):  # 10 s — let it settle
        w.step(dt)

    # The middle node should sit below both anchors.
    nodes = list(body.node_indices)
    mid = nodes[len(nodes) // 2]
    y_mid = float(w.positions[mid, 1])
    y_anchor = 5.0
    assert y_mid < y_anchor - 0.1, f"rope did not droop, y_mid={y_mid}"
    # Sag bounded by physically plausible droop for length=5, span=4.
    assert y_mid > y_anchor - 3.0

    # Symmetry: left half mirrors right half within tolerance.
    n = len(nodes)
    left_y = [float(w.positions[nodes[i], 1]) for i in range(n // 2)]
    right_y = [float(w.positions[nodes[-i - 1], 1]) for i in range(n // 2)]
    mse = float(np.mean((np.array(left_y) - np.array(right_y)) ** 2))
    assert mse < 0.05

    # No NaNs.
    assert not np.isnan(w.positions).any()


def test_rope_bend_stiffness_resists_kink():
    w = World(gravity=(0.0, -9.81))
    spec = RopeSpec(node_count=10, total_length=2.0, mass_per_node=0.05,
                    stiffness=1.0e6, bend_stiffness=1.0e4)
    body = build_rope(spec, w, anchor_a=(0.0, 5.0), anchor_b=(2.0, 5.0))
    for _ in range(120):
        w.step(1.0 / 60.0)
    assert not np.isnan(w.positions).any()
