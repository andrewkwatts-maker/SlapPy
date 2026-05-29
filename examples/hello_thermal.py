"""SlapPyEngine — Hello Thermal

Minimal demo of :class:`slappyengine.thermal.HeatField` showing two grids
that diffuse internally *and* exchange heat across an edge contact strip.

Two 32x32 grids are built at an ambient temperature of 20.0:

* **grid_a** carries two hot spots at T=400 dropped at cells (8, 16) and
  (24, 16). With ``boundary='clamp'`` no heat leaves the rectangle, so
  the only sink is the cross-grid contact strip set up below.
* **grid_b** carries a cold spot at T=-100 at the centre cell (16, 16).
  Same clamped boundary.

The two grids are linked with ``contact_pairs = [((16, 0), (16, 31)),
((16, 31), (16, 0))]`` — the left edge of *grid_a* touches the right edge
of *grid_b* and vice-versa. Each frame we call ``grid_a.step``,
``grid_b.step``, then ``grid_a.exchange_with(grid_b, contact_pairs, dt)``.

After 240 frames at dt=1/60 (4 simulated seconds) the demo prints:

* total energy per grid (Σ T over all cells),
* min/max temperature per grid,
* hot-spot temperature samples every 30 frames,
* conservation residual = ``initial_total_energy - final_total_energy``.

Because ``exchange_with`` is conservative and the per-grid step uses the
``clamp`` boundary (no flux leaves the rectangle), the residual should
stay within float rounding noise.

Run::

    PYTHONPATH=python python examples/hello_thermal.py
    PYTHONPATH=python python examples/hello_thermal.py --render
    PYTHONPATH=python python examples/hello_thermal.py --frames 240 --render --out out/

No GPU is required — when ``--render`` is supplied the two fields are
rasterised side-by-side as red/white/blue heatmaps (red = hot, blue =
cold, white at the ambient 20.0) using pure PIL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from slappyengine.thermal import HeatField


# ── Demo parameters ────────────────────────────────────────────────────────
GRID_SIZE: int = 32
AMBIENT_T: float = 20.0
HOT_T: float = 400.0
COLD_T: float = -100.0
HOT_CELLS_A: tuple[tuple[int, int], ...] = ((8, 16), (24, 16))
COLD_CELL_B: tuple[int, int] = (16, 16)

CONDUCTIVITY: float = 1.0
DIFFUSIVITY: float = 0.1

# Two paired contacts: each grid's edge column 0 talks to the other's
# column 31 (and vice versa) so the strip exchanges symmetrically.
CONTACT_PAIRS: list[tuple[tuple[int, int], tuple[int, int]]] = [
    ((16, 0), (16, 31)),
    ((16, 31), (16, 0)),
]

DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 240
SAMPLE_EVERY: int = 30
BOUNDARY: str = "clamp"

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
# Display range mapped to the red/white/blue gradient.
DISPLAY_MIN: float = -120.0  # blue
DISPLAY_MID: float = AMBIENT_T  # white
DISPLAY_MAX: float = 420.0  # red


# ────────────────────────────────────────────────────────────────────────────
# Grid construction
# ────────────────────────────────────────────────────────────────────────────

def build_grids() -> tuple[HeatField, HeatField]:
    """Construct grid_a (hot spots) and grid_b (cold spot)."""
    t_a = np.full((GRID_SIZE, GRID_SIZE), AMBIENT_T, dtype=np.float64)
    for (cy, cx) in HOT_CELLS_A:
        t_a[cy, cx] = HOT_T
    grid_a = HeatField(t_a, conductivity=CONDUCTIVITY, diffusivity=DIFFUSIVITY)

    t_b = np.full((GRID_SIZE, GRID_SIZE), AMBIENT_T, dtype=np.float64)
    t_b[COLD_CELL_B[0], COLD_CELL_B[1]] = COLD_T
    grid_b = HeatField(t_b, conductivity=CONDUCTIVITY, diffusivity=DIFFUSIVITY)

    return grid_a, grid_b


# ────────────────────────────────────────────────────────────────────────────
# Stepping with per-frame sampling
# ────────────────────────────────────────────────────────────────────────────

def step_grids(
    grid_a: HeatField,
    grid_b: HeatField,
    frames: int,
    dt: float = DEFAULT_DT,
) -> dict:
    """Advance both grids for *frames* steps, sampling diagnostics as we go.

    Each frame: grid_a.step → grid_b.step → grid_a.exchange_with(grid_b, ...).
    """
    initial_total = grid_a.total_heat() + grid_b.total_heat()

    # Frame-0 snapshot
    max_a_history: list[float] = [float(grid_a.temperature.max())]
    min_a_history: list[float] = [float(grid_a.temperature.min())]
    max_b_history: list[float] = [float(grid_b.temperature.max())]
    min_b_history: list[float] = [float(grid_b.temperature.min())]

    # Sample hot-spot cells every SAMPLE_EVERY frames.
    hot_samples: list[dict] = [{
        "frame": 0,
        "hot_a0": float(grid_a.temperature[HOT_CELLS_A[0]]),
        "hot_a1": float(grid_a.temperature[HOT_CELLS_A[1]]),
        "cold_b": float(grid_b.temperature[COLD_CELL_B]),
    }]

    nan_seen = False
    total_q_moved = 0.0

    for frame in range(1, frames + 1):
        grid_a.step(dt, boundary=BOUNDARY)
        grid_b.step(dt, boundary=BOUNDARY)
        q = grid_a.exchange_with(grid_b, CONTACT_PAIRS, dt)
        total_q_moved += float(q)

        max_a_history.append(float(grid_a.temperature.max()))
        min_a_history.append(float(grid_a.temperature.min()))
        max_b_history.append(float(grid_b.temperature.max()))
        min_b_history.append(float(grid_b.temperature.min()))

        if not nan_seen and not (
            np.all(np.isfinite(grid_a.temperature))
            and np.all(np.isfinite(grid_b.temperature))
        ):
            nan_seen = True

        if frame % SAMPLE_EVERY == 0:
            hot_samples.append({
                "frame": frame,
                "hot_a0": float(grid_a.temperature[HOT_CELLS_A[0]]),
                "hot_a1": float(grid_a.temperature[HOT_CELLS_A[1]]),
                "cold_b": float(grid_b.temperature[COLD_CELL_B]),
            })

    final_total = grid_a.total_heat() + grid_b.total_heat()

    return {
        "frames": frames,
        "initial_total_energy": float(initial_total),
        "final_total_energy": float(final_total),
        "conservation_residual": float(initial_total - final_total),
        "total_q_moved": total_q_moved,
        "max_a_history": max_a_history,
        "min_a_history": min_a_history,
        "max_b_history": max_b_history,
        "min_b_history": min_b_history,
        "hot_samples": hot_samples,
        "nan_seen": nan_seen,
    }


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _temperature_to_rgb(T: np.ndarray) -> np.ndarray:
    """Map a 2D temperature field to RGB via red/white/blue gradient.

    * T == DISPLAY_MID → white (255, 255, 255)
    * T == DISPLAY_MAX → pure red (255, 0, 0)
    * T == DISPLAY_MIN → pure blue (0, 0, 255)
    * In-between → linear interpolation per side, channels clipped to [0,1].
    """
    Tf = np.asarray(T, dtype=np.float64)
    # Upper half (hot): mid → max.
    upper = np.clip(
        (Tf - DISPLAY_MID) / max(1e-9, DISPLAY_MAX - DISPLAY_MID),
        0.0,
        1.0,
    )
    # Lower half (cold): mid → min.
    lower = np.clip(
        (DISPLAY_MID - Tf) / max(1e-9, DISPLAY_MID - DISPLAY_MIN),
        0.0,
        1.0,
    )

    r = 1.0 - lower               # red drops as we go cold
    g = 1.0 - upper - lower       # green sinks at both extremes
    b = 1.0 - upper               # blue drops as we go hot
    g = np.clip(g, 0.0, 1.0)

    rgb = np.stack([r, g, b], axis=-1)
    rgb = np.clip(rgb, 0.0, 1.0)
    return (rgb * 255.0).astype(np.uint8)


def _render_grid_panel(T: np.ndarray, width: int, height: int) -> np.ndarray:
    """Rasterise a single 2D temperature field to a (height, width, 4) buffer.

    Uses nearest-neighbour upscaling so individual cells stay visible.
    """
    from PIL import Image

    rgb = _temperature_to_rgb(T)  # (H, W, 3) uint8
    img = Image.fromarray(rgb, mode="RGB").resize(
        (width, height), Image.Resampling.NEAREST
    )
    arr = np.asarray(img, dtype=np.uint8)
    alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
    return np.concatenate([arr, alpha], axis=-1)


def _render_frame(grid_a: HeatField, grid_b: HeatField) -> np.ndarray:
    """Compose a side-by-side render of both grids with a 1-px divider."""
    from PIL import Image, ImageDraw

    panel_w = RENDER_W // 2
    panel_h = RENDER_H
    panel_a = _render_grid_panel(grid_a.temperature, panel_w, panel_h)
    panel_b = _render_grid_panel(grid_b.temperature, panel_w, panel_h)

    frame = np.zeros((RENDER_H, RENDER_W, 4), dtype=np.uint8)
    frame[:, :panel_w] = panel_a
    frame[:, panel_w : panel_w * 2] = panel_b
    # If RENDER_W is odd we leave a 1-pixel black gutter on the right.

    # Black divider stripe between the two panels.
    img = Image.fromarray(frame, mode="RGBA")
    draw = ImageDraw.Draw(img)
    draw.line(
        [(panel_w - 1, 0), (panel_w - 1, RENDER_H - 1)],
        fill=(0, 0, 0, 255),
        width=2,
    )
    return np.asarray(img, dtype=np.uint8)


def save_render(grid_a: HeatField, grid_b: HeatField, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(grid_a, grid_b)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(grid_a: HeatField, grid_b: HeatField, trace: dict) -> dict:
    return {
        "frames": int(trace["frames"]),
        "grid_a_total_energy": float(grid_a.total_heat()),
        "grid_b_total_energy": float(grid_b.total_heat()),
        "grid_a_max_T": float(grid_a.temperature.max()),
        "grid_a_min_T": float(grid_a.temperature.min()),
        "grid_b_max_T": float(grid_b.temperature.max()),
        "grid_b_min_T": float(grid_b.temperature.min()),
        "initial_total_energy": float(trace["initial_total_energy"]),
        "final_total_energy": float(trace["final_total_energy"]),
        "conservation_residual": float(trace["conservation_residual"]),
        "total_q_moved": float(trace["total_q_moved"]),
        "hot_samples": list(trace["hot_samples"]),
        "max_a_initial": float(trace["max_a_history"][0]),
        "max_a_final": float(trace["max_a_history"][-1]),
        "min_b_initial": float(trace["min_b_history"][0]),
        "min_b_final": float(trace["min_b_history"][-1]),
        "nan_seen": bool(trace["nan_seen"]),
    }


def print_summary(summary: dict) -> None:
    print("hello_thermal summary")
    print(f"  stepped frames           : {summary['frames']}")
    print(f"  grid_a total energy      : {summary['grid_a_total_energy']:.6f}")
    print(f"  grid_b total energy      : {summary['grid_b_total_energy']:.6f}")
    print(
        f"  grid_a max / min T       : "
        f"{summary['grid_a_max_T']:.4f} / {summary['grid_a_min_T']:.4f}"
    )
    print(
        f"  grid_b max / min T       : "
        f"{summary['grid_b_max_T']:.4f} / {summary['grid_b_min_T']:.4f}"
    )
    print(f"  initial total energy     : {summary['initial_total_energy']:.6f}")
    print(f"  final total energy       : {summary['final_total_energy']:.6f}")
    print(
        f"  conservation residual    : "
        f"{summary['conservation_residual']:.6e}"
    )
    print(f"  total q moved (a->b)     : {summary['total_q_moved']:.6f}")
    print(f"  any NaN in temperatures  : {summary['nan_seen']}")
    print("  hot-spot samples (frame, hot_a0, hot_a1, cold_b):")
    for s in summary["hot_samples"]:
        print(
            f"    frame {s['frame']:>4d}  hot_a0={s['hot_a0']:.4f}  "
            f"hot_a1={s['hot_a1']:.4f}  cold_b={s['cold_b']:.4f}"
        )


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Thermal — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_thermal.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_thermal.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    grid_a, grid_b = build_grids()
    trace = step_grids(grid_a, grid_b, frames, DEFAULT_DT)
    summary = summarise(grid_a, grid_b, trace)
    print_summary(summary)

    if render:
        out_path = save_render(grid_a, grid_b, Path(out))
        print(f"  rendered to              : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_thermal: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
