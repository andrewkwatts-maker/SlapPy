"""SlapPyEngine — Hello Topology

Minimal demo of :func:`slappyengine.topology.connected_components`.

A 64-node graph is laid out as an 8x8 grid in unit-square world
coordinates. We start with **no edges** at all (64 disjoint singletons)
and add bonds in a deterministic order — all horizontal bonds left-to-
right by row first, then all vertical bonds top-to-bottom by column.
After each batch of 4 added edges we recompute the connected components
and record the (edges_added, component_count) pair.

The transcript on stdout shows the union-find collapsing islands from
64 → 1 as connectivity grows. For the full 8x8 grid the graph fully
connects somewhere around the first 63 edges (a spanning tree on 64
nodes) and remains a single component out to the full 112-edge
4-neighbour grid.

Run::

    PYTHONPATH=python python examples/hello_topology.py
    PYTHONPATH=python python examples/hello_topology.py --render
    PYTHONPATH=python python examples/hello_topology.py --render --out out/

No GPU is required — when ``--render`` is supplied snapshots at
``edges = 0, 16, 32, 48, 64+`` (plus the fully connected end state) are
rasterised side-by-side as a single PNG with pure PIL. Each node is
coloured by its connected-component label so an eye can watch islands
merge.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from slappyengine.topology import connected_components


# ── Demo parameters ────────────────────────────────────────────────────────
GRID_W: int = 8
GRID_H: int = 8
N_NODES: int = GRID_W * GRID_H  # 64
BATCH_SIZE: int = 4

# Snapshot edge-counts that the renderer draws panels for. The final
# snapshot is always the fully connected end state regardless of where
# it falls, so the side-by-side grid bookends the sequence.
SNAPSHOT_EDGES: tuple[int, ...] = (0, 16, 32, 48, 64)

# ── Render parameters ──────────────────────────────────────────────────────
PANEL_W: int = 240
PANEL_H: int = 240
PANEL_PADDING: int = 16  # margin inside each panel between border and grid
PANEL_GAP: int = 8       # gap between panels in the strip
PANEL_LABEL_H: int = 28  # space reserved at the top for the text label
BACKGROUND_RGBA: tuple[int, int, int, int] = (16, 16, 24, 255)
PANEL_BG_RGBA: tuple[int, int, int, int] = (28, 28, 40, 255)
EDGE_RGBA: tuple[int, int, int, int] = (140, 140, 160, 255)
NODE_RADIUS: int = 6


# ────────────────────────────────────────────────────────────────────────────
# Graph construction
# ────────────────────────────────────────────────────────────────────────────

def build_node_positions() -> np.ndarray:
    """Lay out :data:`N_NODES` on a regular grid inside the unit square.

    Node index is ``row * GRID_W + col`` with row 0 at the top in world
    coordinates that map directly to image space (y grows downward when
    rendered). Positions are in ``[0, 1]`` on both axes.
    """
    positions = np.zeros((N_NODES, 2), dtype=np.float64)
    if GRID_W <= 1:
        xs = np.array([0.5])
    else:
        xs = np.linspace(0.0, 1.0, GRID_W)
    if GRID_H <= 1:
        ys = np.array([0.5])
    else:
        ys = np.linspace(0.0, 1.0, GRID_H)
    for row in range(GRID_H):
        for col in range(GRID_W):
            idx = row * GRID_W + col
            positions[idx, 0] = xs[col]
            positions[idx, 1] = ys[row]
    return positions


def build_edge_list() -> np.ndarray:
    """Deterministic edge ordering for the 8x8 grid.

    Order:

    * **Horizontal bonds**, by row top-to-bottom and left-to-right within
      each row. That's ``GRID_H * (GRID_W - 1) = 8 * 7 = 56`` edges.
    * **Vertical bonds**, by column left-to-right and top-to-bottom
      within each column. ``(GRID_H - 1) * GRID_W = 7 * 8 = 56`` edges.

    Total: ``56 + 56 = 112`` edges for the full 4-neighbour grid.
    """
    horiz: list[tuple[int, int]] = []
    for row in range(GRID_H):
        for col in range(GRID_W - 1):
            a = row * GRID_W + col
            b = row * GRID_W + (col + 1)
            horiz.append((a, b))

    vert: list[tuple[int, int]] = []
    for col in range(GRID_W):
        for row in range(GRID_H - 1):
            a = row * GRID_W + col
            b = (row + 1) * GRID_W + col
            vert.append((a, b))

    edges = horiz + vert
    return np.asarray(edges, dtype=np.int64)


# ────────────────────────────────────────────────────────────────────────────
# Stepping
# ────────────────────────────────────────────────────────────────────────────

def run_components_sequence(
    edges: np.ndarray,
    batch_size: int = BATCH_SIZE,
) -> list[tuple[int, int]]:
    """Walk through *edges* in batches and record component counts.

    Returns a list of ``(n_edges_added, n_components)`` pairs starting at
    ``(0, N_NODES)`` and ending at ``(len(edges), final_components)``.
    The list always finishes on the full edge list so the caller can see
    the final component count regardless of where ``batch_size`` falls.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    sequence: list[tuple[int, int]] = []

    # Initial state: no edges -> N_NODES singleton components.
    labels0, n0 = connected_components(N_NODES, edges[:0])
    sequence.append((0, n0))

    total = int(edges.shape[0])
    k = batch_size
    while k <= total:
        _, n = connected_components(N_NODES, edges[:k])
        sequence.append((k, n))
        k += batch_size

    # Snap the final point on if the last batch didn't land exactly on
    # ``total`` (it does for batch_size=4 / total=112, but stay robust).
    if sequence[-1][0] != total:
        _, n = connected_components(N_NODES, edges[:total])
        sequence.append((total, n))

    return sequence


def labels_at(edges: np.ndarray, n_edges_added: int) -> np.ndarray:
    """Return the ``(N_NODES,)`` int label array after *n_edges_added* edges."""
    labels, _ = connected_components(N_NODES, edges[:n_edges_added])
    return labels


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _component_color(label: int) -> tuple[int, int, int]:
    """Stable, deterministic colour per component label.

    A small hash mixes the label across the 0-255 byte range so adjacent
    labels read as visually distinct rather than walking a smooth ramp.
    """
    if label < 0:
        return (90, 90, 90)
    # Three independent multiplicative hashes mod 256, biased away from 0
    # so the dots never disappear into the dark panel background.
    r = (label * 67 + 53) & 0xFF
    g = (label * 131 + 17) & 0xFF
    b = (label * 197 + 89) & 0xFF
    # Keep min channel >= 96 so colours stay readable on a dark bg.
    r = 96 + (r % (256 - 96))
    g = 96 + (g % (256 - 96))
    b = 96 + (b % (256 - 96))
    return (int(r), int(g), int(b))


def _panel_pixel(
    positions: np.ndarray,
    node_idx: int,
    panel_x: int,
    panel_y: int,
) -> tuple[int, int]:
    """Map node *node_idx* to a pixel inside the panel at (panel_x, panel_y)."""
    grid_x0 = panel_x + PANEL_PADDING
    grid_y0 = panel_y + PANEL_LABEL_H + PANEL_PADDING
    grid_w = PANEL_W - 2 * PANEL_PADDING
    grid_h = PANEL_H - PANEL_LABEL_H - 2 * PANEL_PADDING
    nx = float(positions[node_idx, 0])
    ny = float(positions[node_idx, 1])
    px = grid_x0 + int(round(nx * grid_w))
    py = grid_y0 + int(round(ny * grid_h))
    return px, py


def _draw_panel(
    draw,
    positions: np.ndarray,
    edges: np.ndarray,
    n_edges_added: int,
    labels: np.ndarray,
    n_components: int,
    panel_x: int,
    panel_y: int,
) -> None:
    """Draw a single component-state panel onto *draw* at (panel_x, panel_y)."""
    # Panel background rectangle.
    draw.rectangle(
        [(panel_x, panel_y), (panel_x + PANEL_W - 1, panel_y + PANEL_H - 1)],
        fill=PANEL_BG_RGBA,
        outline=(60, 60, 80, 255),
        width=1,
    )

    # Label at the top of the panel.
    label = f"edges={n_edges_added}  comp={n_components}"
    draw.text(
        (panel_x + 8, panel_y + 6),
        label,
        fill=(220, 220, 230, 255),
    )

    # Edges first so node dots paint on top.
    if n_edges_added > 0:
        sub = edges[:n_edges_added]
        for k in range(sub.shape[0]):
            a = int(sub[k, 0])
            b = int(sub[k, 1])
            ax, ay = _panel_pixel(positions, a, panel_x, panel_y)
            bx, by = _panel_pixel(positions, b, panel_x, panel_y)
            draw.line([(ax, ay), (bx, by)], fill=EDGE_RGBA, width=1)

    # Node dots, coloured by component label.
    r = NODE_RADIUS
    for i in range(N_NODES):
        px, py = _panel_pixel(positions, i, panel_x, panel_y)
        color = _component_color(int(labels[i]))
        draw.ellipse(
            [(px - r, py - r), (px + r, py + r)],
            fill=color + (255,),
            outline=(0, 0, 0, 255),
        )


def _render_snapshots(
    positions: np.ndarray,
    edges: np.ndarray,
    snapshots: list[int],
) -> np.ndarray:
    """Rasterise a horizontal strip of panels, one per snapshot edge count."""
    from PIL import Image, ImageDraw

    n_panels = len(snapshots)
    total_w = n_panels * PANEL_W + (n_panels - 1) * PANEL_GAP
    total_h = PANEL_H
    img = Image.new("RGBA", (total_w, total_h), BACKGROUND_RGBA)
    draw = ImageDraw.Draw(img)

    for idx, n_edges_added in enumerate(snapshots):
        labels, n_comp = connected_components(N_NODES, edges[:n_edges_added])
        panel_x = idx * (PANEL_W + PANEL_GAP)
        panel_y = 0
        _draw_panel(
            draw,
            positions,
            edges,
            n_edges_added,
            labels,
            n_comp,
            panel_x,
            panel_y,
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(
    positions: np.ndarray,
    edges: np.ndarray,
    snapshots: list[int],
    out_path: Path,
) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_snapshots(positions, edges, snapshots)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


def render_width(n_panels: int) -> int:
    return n_panels * PANEL_W + (n_panels - 1) * PANEL_GAP


def render_height() -> int:
    return PANEL_H


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def compute_snapshot_edges(sequence: list[tuple[int, int]]) -> list[int]:
    """Pick the edge counts used for the visualisation strip.

    Always include :data:`SNAPSHOT_EDGES` plus the final fully-connected
    state. Duplicates and out-of-range values are dropped. Result is in
    strictly ascending order.
    """
    total_edges = sequence[-1][0]
    wanted: list[int] = []
    for e in SNAPSHOT_EDGES:
        if 0 <= e <= total_edges and e not in wanted:
            wanted.append(e)
    if total_edges not in wanted:
        wanted.append(total_edges)
    wanted.sort()
    return wanted


def summarise(
    sequence: list[tuple[int, int]],
    snapshots: list[int],
) -> dict:
    initial_edges, initial_comp = sequence[0]
    final_edges, final_comp = sequence[-1]
    first_fully_connected = None
    for n_edges, n_comp in sequence:
        if n_comp == 1:
            first_fully_connected = n_edges
            break

    # Monotonic decrease check (component count never increases).
    monotonic = all(
        sequence[i][1] <= sequence[i - 1][1] for i in range(1, len(sequence))
    )

    return {
        "n_nodes": N_NODES,
        "total_edges": final_edges,
        "initial_components": initial_comp,
        "final_components": final_comp,
        "first_fully_connected_at": first_fully_connected,
        "sequence_length": len(sequence),
        "monotonic_decrease": bool(monotonic),
        "snapshot_edges": list(snapshots),
        "sequence": list(sequence),
    }


def print_summary(summary: dict) -> None:
    print("hello_topology summary")
    print(f"  n_nodes                 : {summary['n_nodes']}")
    print(f"  total edges in graph    : {summary['total_edges']}")
    print(f"  initial components      : {summary['initial_components']}")
    print(f"  final components        : {summary['final_components']}")
    print(
        "  first fully connected at: "
        f"{summary['first_fully_connected_at']} edges"
    )
    print(f"  monotonic decrease      : {summary['monotonic_decrease']}")
    print("  component-count sequence:")
    for n_edges, n_comp in summary["sequence"]:
        print(f"    edges={n_edges:>3d}  components={n_comp}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello Topology — SlapPyEngine demo"
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise a side-by-side panel strip to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_topology.png"),
        help="output PNG path when --render is supplied",
    )
    parser.add_argument(
        "--batch", type=int, default=BATCH_SIZE,
        help=f"edges added between recompute (default: {BATCH_SIZE})",
    )
    return parser.parse_args(argv)


def main(
    render: bool = False,
    out: Path | str = Path("out/hello_topology.png"),
    batch: int = BATCH_SIZE,
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    positions = build_node_positions()
    edges = build_edge_list()
    sequence = run_components_sequence(edges, batch_size=batch)
    snapshots = compute_snapshot_edges(sequence)
    summary = summarise(sequence, snapshots)
    print_summary(summary)

    if render:
        out_path = save_render(positions, edges, snapshots, Path(out))
        print(f"  rendered to             : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(render=args.render, out=args.out, batch=args.batch)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_topology: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
