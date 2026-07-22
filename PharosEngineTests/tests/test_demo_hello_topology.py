"""Tests for the ``examples/hello_topology.py`` demo.

Pinned behaviours:

1. ``main(render=False)`` is callable in-process and never raises.
2. With zero edges the union-find returns ``N_NODES`` singleton
   components (no edge-list = no merges).
3. After every edge in the full 8x8 4-neighbour grid (8x7 + 7x8 = 112
   edges) the union-find collapses everything to a single component.
4. The component count is monotonically non-increasing as edges are
   added — there is no operation in the demo that ever splits a
   component, so any regression here is a real bug.
5. The rendered snapshot strip reproduces a stable golden master via
   :mod:`pharos_engine.testing`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pharos_engine.testing import assert_scene_matches

# Load the demo as a module so we don't depend on examples/ being on path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_topology.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_topology_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_topology_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_topology_runs_without_error(demo, tmp_path):
    """``main(render=False)`` returns a summary dict and never raises."""
    summary = demo.main(render=False, out=tmp_path / "ignored.png")
    assert summary["n_nodes"] == demo.N_NODES
    assert summary["total_edges"] == 112  # 8 * 7 + 7 * 8
    # Sequence must include the initial (0 edges) and final (all edges) points.
    seq = summary["sequence"]
    assert seq[0][0] == 0
    assert seq[-1][0] == summary["total_edges"]


# ────────────────────────────────────────────────────────────────────────────
# Test 2: initial component count == n_nodes
# ────────────────────────────────────────────────────────────────────────────

def test_initial_components_equal_n_nodes(demo):
    """At zero edges every node is its own singleton -> 64 components."""
    edges = demo.build_edge_list()
    labels, n_comp = demo.connected_components(demo.N_NODES, edges[:0])
    assert n_comp == demo.N_NODES == 64
    # Every label is unique.
    assert set(labels.tolist()) == set(range(demo.N_NODES))


# ────────────────────────────────────────────────────────────────────────────
# Test 3: full edge list -> one component
# ────────────────────────────────────────────────────────────────────────────

def test_eventually_one_component(demo):
    """All 112 grid edges fully connect the graph."""
    edges = demo.build_edge_list()
    assert edges.shape == (112, 2)
    labels, n_comp = demo.connected_components(demo.N_NODES, edges)
    assert n_comp == 1
    # Every live node sits on the single component label 0.
    assert set(labels.tolist()) == {0}


# ────────────────────────────────────────────────────────────────────────────
# Test 4: monotonic decrease in component count
# ────────────────────────────────────────────────────────────────────────────

def test_monotonic_decrease(demo):
    """Adding an edge can only merge components, never split them."""
    edges = demo.build_edge_list()
    sequence = demo.run_components_sequence(edges, batch_size=demo.BATCH_SIZE)

    # Each batch is non-increasing in component count.
    for i in range(1, len(sequence)):
        prev_edges, prev_comp = sequence[i - 1]
        cur_edges, cur_comp = sequence[i]
        assert cur_edges > prev_edges, (
            f"edge counts must strictly increase: "
            f"prev={prev_edges} cur={cur_edges}"
        )
        assert cur_comp <= prev_comp, (
            f"component count rose from {prev_comp} -> {cur_comp} "
            f"between edges={prev_edges} and edges={cur_edges}"
        )

    # And end-to-end the count went from 64 down to 1.
    assert sequence[0][1] == demo.N_NODES
    assert sequence[-1][1] == 1


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_topology_visual_baseline(demo):
    """Render the snapshot strip and diff against the committed baseline."""
    positions = demo.build_node_positions()
    edges = demo.build_edge_list()
    sequence = demo.run_components_sequence(edges, batch_size=demo.BATCH_SIZE)
    snapshots = demo.compute_snapshot_edges(sequence)

    rendered = demo._render_snapshots(positions, edges, snapshots)
    assert rendered.dtype == np.uint8
    assert rendered.ndim == 3 and rendered.shape[2] == 4

    width = demo.render_width(len(snapshots))
    height = demo.render_height()
    assert rendered.shape == (height, width, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_topology",
        tolerance=0.05,
        width=width,
        height=height,
    )
