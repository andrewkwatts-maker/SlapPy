"""SlapPyEngine — Hello Numerics

Minimal demo of :func:`pharos_engine.numerics.vcycle_poisson` showing a
multigrid Poisson solve on a 64x64 cell-centred grid.

A 2-D Gaussian bump is placed at the grid centre:

* Centre  : ``(32, 32)``
* Sigma   : ``4.0`` cells
* Peak    : ``1.0``

The bump is fed to :func:`vcycle_poisson` as the right-hand side of the
Poisson equation ``Δp = rhs``. A circular fluid mask of radius 28 is
also supplied so the solver treats cells outside the disc as vacuum
(clamped to zero, no flux). Five V-cycles are run with the default
SOR / level / smoother knobs.

After the solve we recompute the residual ``r = rhs - Δp`` with a
5-point Laplacian and print:

* ``max(rhs)``         — peak source amplitude (sanity).
* ``max(solution)``    — peak pressure / potential at the bump centre.
* ``max(|residual|)``  — worst pointwise residual after 5 cycles.
* ``||residual||_2``   — L2 norm of the residual over the live mask.

Run::

    PYTHONPATH=python python examples/hello_numerics.py
    PYTHONPATH=python python examples/hello_numerics.py --render
    PYTHONPATH=python python examples/hello_numerics.py --render --out out/

When ``--render`` is supplied a single 3-panel PNG is written: source
(red colormap), solution (blue colormap), residual (green colormap),
each labelled with its field name and ``[min, max]`` range. Pure PIL —
no GPU required.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from pharos_engine.numerics import vcycle_poisson


# ── Demo parameters ────────────────────────────────────────────────────────
GRID_SIZE: int = 64
SOURCE_CENTRE: tuple[int, int] = (32, 32)
SOURCE_SIGMA: float = 4.0
SOURCE_PEAK: float = 1.0

MASK_CENTRE: tuple[int, int] = (32, 32)
MASK_RADIUS: float = 28.0

N_CYCLES: int = 5

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
PANEL_GUTTER: int = 8  # pixels of black gutter between panels


# ────────────────────────────────────────────────────────────────────────────
# Field construction
# ────────────────────────────────────────────────────────────────────────────

def build_source(
    grid_size: int = GRID_SIZE,
    centre: tuple[int, int] = SOURCE_CENTRE,
    sigma: float = SOURCE_SIGMA,
    peak: float = SOURCE_PEAK,
) -> np.ndarray:
    """Return a (grid_size, grid_size) float32 Gaussian bump.

    ``rhs[y, x] = peak * exp(-((x - cx)^2 + (y - cy)^2) / (2 * sigma^2))``.
    """
    ys, xs = np.indices((grid_size, grid_size), dtype=np.float64)
    cy, cx = centre
    r2 = (xs - cx) ** 2 + (ys - cy) ** 2
    rhs = peak * np.exp(-r2 / (2.0 * sigma * sigma))
    return rhs.astype(np.float32)


def build_mask(
    grid_size: int = GRID_SIZE,
    centre: tuple[int, int] = MASK_CENTRE,
    radius: float = MASK_RADIUS,
) -> np.ndarray:
    """Return a (grid_size, grid_size) bool circular mask.

    True ↔ fluid (solved for), False ↔ vacuum (clamped to zero).
    """
    ys, xs = np.indices((grid_size, grid_size), dtype=np.float64)
    cy, cx = centre
    r2 = (xs - cx) ** 2 + (ys - cy) ** 2
    return r2 <= radius * radius


# ────────────────────────────────────────────────────────────────────────────
# Residual computation (independent re-implementation as a sanity check)
# ────────────────────────────────────────────────────────────────────────────

def laplacian_5pt(p: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Return the 5-point Laplacian ``Δp`` of *p* with optional mask.

    Standard ``p_l + p_r + p_t + p_b - 4·p`` stencil. Out-of-bounds
    neighbours are zero (Dirichlet). When a mask is supplied, vacuum
    neighbours contribute zero too.
    """
    p_f = np.asarray(p, dtype=np.float64)
    if mask is None:
        m = np.ones_like(p_f)
    else:
        m = (np.asarray(mask) >= 0.5).astype(np.float64)

    p_m = p_f * m  # vacuum cells are zero anyway, but be explicit

    left = np.zeros_like(p_m)
    left[:, 1:] = p_m[:, :-1] * m[:, :-1]
    right = np.zeros_like(p_m)
    right[:, :-1] = p_m[:, 1:] * m[:, 1:]
    top = np.zeros_like(p_m)
    top[1:, :] = p_m[:-1, :] * m[:-1, :]
    bot = np.zeros_like(p_m)
    bot[:-1, :] = p_m[1:, :] * m[1:, :]

    lap = (left + right + top + bot - 4.0 * p_m) * m
    return lap


def compute_residual_field(
    rhs: np.ndarray, solution: np.ndarray, mask: np.ndarray | None
) -> np.ndarray:
    """Return ``r = rhs - Δp`` on the masked 5-point Laplacian."""
    lap = laplacian_5pt(solution, mask)
    r = (np.asarray(rhs, dtype=np.float64) - lap)
    if mask is not None:
        r = r * (np.asarray(mask) >= 0.5).astype(np.float64)
    return r.astype(np.float64)


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _colormap_channel(
    field: np.ndarray, channel: str
) -> np.ndarray:
    """Map a 2D float field to an RGB image using a single-channel colormap.

    The field is normalised to [0, 1] by its own absolute max so panels
    are always readable regardless of magnitude. ``channel`` ∈ {"red",
    "blue", "green"} picks which channel carries the signal. Negative
    values render as the complementary channel for residual readability.
    """
    f = np.asarray(field, dtype=np.float64)
    peak = float(np.max(np.abs(f))) if f.size else 0.0
    if peak <= 0.0:
        norm = np.zeros_like(f, dtype=np.float32)
    else:
        norm = (f / peak).astype(np.float32)
    # ``mag`` shows magnitude regardless of sign — useful for the
    # Δp = +rhs convention where the Poisson solution is everywhere
    # negative for a positive source. ``pos`` / ``neg`` still expose
    # sign for the residual panel.
    mag = np.clip(np.abs(norm), 0.0, 1.0)
    pos = np.clip(norm, 0.0, 1.0)
    neg = np.clip(-norm, 0.0, 1.0)

    h, w = f.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    if channel == "red":
        rgb[..., 0] = mag
        # Slight pink tint for very high values so the eye reads gradient.
        rgb[..., 1] = mag * 0.15
        rgb[..., 2] = mag * 0.15
    elif channel == "blue":
        rgb[..., 2] = mag
        rgb[..., 0] = mag * 0.15
        rgb[..., 1] = mag * 0.25
    elif channel == "green":
        # Green for positive residual, magenta for negative — keeps sign visible.
        rgb[..., 1] = pos
        rgb[..., 0] = neg
        rgb[..., 2] = neg
    else:  # pragma: no cover - defensive
        raise ValueError(f"unknown channel {channel!r}")

    rgb = np.clip(rgb, 0.0, 1.0)
    return (rgb * 255.0).astype(np.uint8)


def _render_panel(
    field: np.ndarray,
    channel: str,
    panel_w: int,
    panel_h: int,
) -> np.ndarray:
    """Rasterise a single (H, W) field as a (panel_h, panel_w, 4) RGBA tile."""
    from PIL import Image

    rgb = _colormap_channel(field, channel)  # (H, W, 3) uint8
    img = Image.fromarray(rgb, mode="RGB").resize(
        (panel_w, panel_h), Image.Resampling.NEAREST
    )
    arr = np.asarray(img, dtype=np.uint8)
    alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.concatenate([arr, alpha], axis=-1)


def _render_frame(
    rhs: np.ndarray,
    solution: np.ndarray,
    residual: np.ndarray,
) -> np.ndarray:
    """Compose the three-panel render.

    Layout: |  source (red)  |  solution (blue)  |  residual (green)  |
    Each panel is labelled in the top-left corner with field name and
    ``[min, max]`` range.
    """
    from PIL import Image, ImageDraw

    total_gutters = PANEL_GUTTER * 2
    panel_w = (RENDER_W - total_gutters) // 3
    panel_h = RENDER_H

    p_src = _render_panel(rhs, "red", panel_w, panel_h)
    p_sol = _render_panel(solution, "blue", panel_w, panel_h)
    p_res = _render_panel(residual, "green", panel_w, panel_h)

    frame = np.zeros((RENDER_H, RENDER_W, 4), dtype=np.uint8)
    x0 = 0
    frame[:, x0 : x0 + panel_w] = p_src
    x0 += panel_w + PANEL_GUTTER
    frame[:, x0 : x0 + panel_w] = p_sol
    x0 += panel_w + PANEL_GUTTER
    frame[:, x0 : x0 + panel_w] = p_res

    # Labels: black box, white text.
    img = Image.fromarray(frame, mode="RGBA")
    draw = ImageDraw.Draw(img)

    def _label(x: int, text: str) -> None:
        # 2-line label in a black box at top-left of each panel.
        box_w = 320
        box_h = 56
        draw.rectangle(
            [(x + 4, 4), (x + 4 + box_w, 4 + box_h)],
            fill=(0, 0, 0, 200),
        )
        draw.text((x + 12, 8), text, fill=(255, 255, 255, 255))

    _label(
        0,
        f"source rhs\n[{float(rhs.min()):.3e}, {float(rhs.max()):.3e}]",
    )
    _label(
        panel_w + PANEL_GUTTER,
        f"solution p\n[{float(solution.min()):.3e}, {float(solution.max()):.3e}]",
    )
    _label(
        2 * (panel_w + PANEL_GUTTER),
        f"residual r=rhs-dp\n[{float(residual.min()):.3e}, {float(residual.max()):.3e}]",
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(
    rhs: np.ndarray,
    solution: np.ndarray,
    residual: np.ndarray,
    out_path: Path,
) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(rhs, solution, residual)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(
    rhs: np.ndarray,
    solution: np.ndarray,
    residual: np.ndarray,
    mask: np.ndarray,
) -> dict:
    """Return a JSON-friendly summary used by both the CLI and tests."""
    mask_f = (np.asarray(mask) >= 0.5)
    inside = mask_f
    outside = ~mask_f

    # Solution gradient inside the mask: central differences where both
    # neighbours are live. Gives us a smoothness sanity check.
    p = np.asarray(solution, dtype=np.float64)
    dx = np.zeros_like(p)
    dy = np.zeros_like(p)
    dx[:, 1:-1] = 0.5 * (p[:, 2:] - p[:, :-2])
    dy[1:-1, :] = 0.5 * (p[2:, :] - p[:-2, :])
    grad_mag = np.sqrt(dx * dx + dy * dy)
    grad_inside = float(grad_mag[inside].max()) if inside.any() else 0.0

    centre_val = float(solution[MASK_CENTRE[0], MASK_CENTRE[1]])

    return {
        "grid_size": int(GRID_SIZE),
        "n_cycles": int(N_CYCLES),
        "max_rhs": float(rhs.max()),
        "min_rhs": float(rhs.min()),
        "max_solution": float(solution.max()),
        "min_solution": float(solution.min()),
        "max_abs_residual": float(np.max(np.abs(residual))),
        "residual_l2_norm": float(np.sqrt(np.sum(residual * residual))),
        "centre_solution": centre_val,
        "max_grad_inside": grad_inside,
        "live_cells": int(inside.sum()),
        "vacuum_cells": int(outside.sum()),
        "vacuum_sum_abs_solution": float(np.sum(np.abs(solution[outside]))),
        "nan_seen": bool(not np.all(np.isfinite(solution))),
    }


def print_summary(summary: dict) -> None:
    print("hello_numerics summary")
    print(f"  grid size            : {summary['grid_size']}x{summary['grid_size']}")
    print(f"  v-cycles             : {summary['n_cycles']}")
    print(f"  max(rhs)             : {summary['max_rhs']:.6f}")
    print(f"  max(solution)        : {summary['max_solution']:.6f}")
    print(f"  min(solution)        : {summary['min_solution']:.6f}")
    print(f"  max(|residual|)      : {summary['max_abs_residual']:.6e}")
    print(f"  ||residual||_2       : {summary['residual_l2_norm']:.6e}")
    print(f"  solution at centre   : {summary['centre_solution']:.6f}")
    print(f"  max |grad| inside    : {summary['max_grad_inside']:.6f}")
    print(f"  live cells           : {summary['live_cells']}")
    print(f"  vacuum cells         : {summary['vacuum_cells']}")
    print(f"  sum|sol| in vacuum   : {summary['vacuum_sum_abs_solution']:.6e}")
    print(f"  any NaN in solution  : {summary['nan_seen']}")


# ────────────────────────────────────────────────────────────────────────────
# Top-level demo entry
# ────────────────────────────────────────────────────────────────────────────

def solve(
    rhs: np.ndarray,
    mask: np.ndarray,
    n_cycles: int = N_CYCLES,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the V-cycle solve and return ``(solution, residual)``."""
    solution = vcycle_poisson(rhs, mask, n_cycles=n_cycles)
    residual = compute_residual_field(rhs, solution, mask)
    return solution, residual


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Numerics — SlapPyEngine demo")
    parser.add_argument(
        "--n-cycles", type=int, default=N_CYCLES,
        help=f"number of V-cycles to run (default: {N_CYCLES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the 3-panel result to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_numerics.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    n_cycles: int = N_CYCLES,
    render: bool = False,
    out: Path | str = Path("out/hello_numerics.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    rhs = build_source()
    mask = build_mask()
    solution, residual = solve(rhs, mask, n_cycles=n_cycles)
    summary = summarise(rhs, solution, residual, mask)
    print_summary(summary)

    if render:
        out_path = save_render(rhs, solution, residual, Path(out))
        print(f"  rendered to          : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(n_cycles=args.n_cycles, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_numerics: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
