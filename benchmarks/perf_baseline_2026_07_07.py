"""Perf re-baseline harness (SS4, 2026-07-07) — closes v0.4 ship gate #13.

Measures six hot paths cited by OO7's ship-checklist gate #13 and the RR6
reconciliation:

* ``raster.line_batch``    — 10k lines rasterised (PIL fallback if the
  ``_core.raster`` symbols aren't present; the Rust ``raster`` module is
  currently WIP and gated behind gate #11, so this benchmark documents
  the reference throughput rather than the target).
* ``raster.circle_batch``  — 5k circles.
* ``_core.hull.convex_hull`` — 1k random points (Graham scan).
* ``_core.ik_solver.solve`` — 20-joint chain, 100 iters (FABRIK).
* ``World3D.raycast_bvh``   — 500 bodies, 1000 rays; also captures the
  linear-path baseline for the OO2 21.86x speedup comparison.
* ``DiagnosticsCollector.install()`` throughput — 10k events emitted;
  measures capture ms per 10k warnings so gate #13 can flag any
  regression in the passive listener installed by OO6.

Each benchmark runs 3 warmup + 10 measured passes with
``time.perf_counter()`` and reports min / mean / stddev in ms.

Usage::

    python benchmarks/perf_baseline_2026_07_07.py

The script exits 0 on success; individual benches that require the
compiled ``_core`` extension skip cleanly if the extension isn't built.

Do NOT modify any subsystem code from this harness — it is *read-only*
with respect to the engine (only spawns transient World3D / IK / hull
inputs). Constraint per the SS4 sprint scope.
"""
from __future__ import annotations

import argparse
import logging
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class BenchResult:
    name: str
    unit: str
    samples: list[float] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def min_ms(self) -> float:
        return min(self.samples) if self.samples else float("nan")

    @property
    def mean_ms(self) -> float:
        return statistics.fmean(self.samples) if self.samples else float("nan")

    @property
    def stdev_ms(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) >= 2 else 0.0

    def as_row(self) -> str:
        if self.skipped:
            return f"| {self.name} | SKIP | SKIP | SKIP | {self.skip_reason} |"
        return (
            f"| {self.name} | {self.min_ms:.3f} | {self.mean_ms:.3f} | "
            f"{self.stdev_ms:.3f} | {self.unit} |"
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


WARMUP_PASSES = 3
MEASURED_PASSES = 10


def run_bench(
    name: str,
    setup: Callable[[], object],
    body: Callable[[object], None],
    unit: str = "1 pass",
) -> BenchResult:
    """Run ``body(state)`` for ``WARMUP_PASSES + MEASURED_PASSES`` passes.

    ``setup`` is called *once* before warmup and the returned state is
    threaded into every ``body`` call. This mirrors the pattern used by
    the existing ``benchmarks/refresh_2026_05_31.py`` harness so the
    numbers are apples-to-apples comparable.
    """
    result = BenchResult(name=name, unit=unit)
    try:
        state = setup()
    except _SkipBench as exc:
        result.skipped = True
        result.skip_reason = str(exc)
        return result
    # Warmup
    for _ in range(WARMUP_PASSES):
        body(state)
    # Measure
    for _ in range(MEASURED_PASSES):
        t0 = time.perf_counter()
        body(state)
        result.samples.append((time.perf_counter() - t0) * 1000.0)
    return result


class _SkipBench(RuntimeError):
    """Raised from setup() to skip the bench cleanly."""


# ---------------------------------------------------------------------------
# Bench 1 + 2 — raster.line_batch / raster.circle_batch
# ---------------------------------------------------------------------------


def _try_import_core_raster():
    """Return the ``_core.raster`` module if the Rust extension is built.

    The Rust ``raster`` module is currently WIP (``src/raster.rs`` is
    untracked per gate #11) and is *not* part of the tracked ``_core``
    surface at commit ``40a79bd``. When absent we fall back to a pure-PIL
    reference implementation so the harness produces a meaningful number
    even before the WIP unfreeze lands.
    """
    try:
        import pharos_engine._core as core  # type: ignore
    except ImportError:
        return None
    return getattr(core, "raster", None)


def setup_line_batch():
    rng = np.random.default_rng(20260707)
    W, H = 512, 512
    N = 10_000
    x0 = rng.uniform(0, W, N).astype(np.float32)
    y0 = rng.uniform(0, H, N).astype(np.float32)
    x1 = rng.uniform(0, W, N).astype(np.float32)
    y1 = rng.uniform(0, H, N).astype(np.float32)
    colors = rng.integers(0, 256, size=(N, 3), dtype=np.uint8)
    core_raster = _try_import_core_raster()
    return {
        "W": W,
        "H": H,
        "N": N,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "colors": colors,
        "core_raster": core_raster,
    }


def _pil_line_batch(state):
    """PIL fallback: `ImageDraw.line` for every entry.

    Reference implementation for when the Rust raster module isn't
    compiled. Not the target throughput — the Rust path is expected to
    be 5-10x faster once gate #11 lands.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (state["W"], state["H"]), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    x0 = state["x0"]
    y0 = state["y0"]
    x1 = state["x1"]
    y1 = state["y1"]
    colors = state["colors"]
    for i in range(state["N"]):
        draw.line(
            (float(x0[i]), float(y0[i]), float(x1[i]), float(y1[i])),
            fill=(int(colors[i, 0]), int(colors[i, 1]), int(colors[i, 2])),
            width=1,
        )


def body_line_batch(state):
    core_raster = state["core_raster"]
    if core_raster is not None and hasattr(core_raster, "rasterize_lines"):
        # Rust path — matches the WIP src/raster.rs signature.
        buf = bytearray(state["W"] * state["H"] * 3)
        core_raster.rasterize_lines(
            buf,
            state["W"],
            state["H"],
            state["x0"].tobytes(),
            state["y0"].tobytes(),
            state["x1"].tobytes(),
            state["y1"].tobytes(),
            state["colors"].tobytes(),
            state["N"],
            1,  # thickness
        )
    else:
        _pil_line_batch(state)


def setup_circle_batch():
    rng = np.random.default_rng(20260707)
    W, H = 512, 512
    N = 5_000
    cx = rng.uniform(0, W, N).astype(np.float32)
    cy = rng.uniform(0, H, N).astype(np.float32)
    radii = rng.uniform(1, 6, N).astype(np.float32)
    colors = rng.integers(0, 256, size=(N, 3), dtype=np.uint8)
    core_raster = _try_import_core_raster()
    return {
        "W": W,
        "H": H,
        "N": N,
        "cx": cx,
        "cy": cy,
        "radii": radii,
        "colors": colors,
        "core_raster": core_raster,
    }


def _pil_circle_batch(state):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (state["W"], state["H"]), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = state["cx"]
    cy = state["cy"]
    radii = state["radii"]
    colors = state["colors"]
    for i in range(state["N"]):
        r = float(radii[i])
        x = float(cx[i])
        y = float(cy[i])
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=(int(colors[i, 0]), int(colors[i, 1]), int(colors[i, 2])),
        )


def body_circle_batch(state):
    core_raster = state["core_raster"]
    if core_raster is not None and hasattr(core_raster, "rasterize_circles"):
        buf = bytearray(state["W"] * state["H"] * 3)
        core_raster.rasterize_circles(
            buf,
            state["W"],
            state["H"],
            state["cx"].tobytes(),
            state["cy"].tobytes(),
            state["radii"].tobytes(),
            state["colors"].tobytes(),
            state["N"],
        )
    else:
        _pil_circle_batch(state)


# ---------------------------------------------------------------------------
# Bench 3 — _core.hull.convex_hull (1k points)
# ---------------------------------------------------------------------------


def setup_convex_hull():
    try:
        import pharos_engine._core as core  # type: ignore
    except ImportError:
        raise _SkipBench("pharos_engine._core extension not built (maturin develop --release)")
    if not hasattr(core, "convex_hull"):
        raise _SkipBench("_core.convex_hull missing (hull.rs not compiled)")
    rng = random.Random(20260707)
    pts = [(rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0)) for _ in range(1000)]
    return {"pts": pts, "convex_hull": core.convex_hull}


def body_convex_hull(state):
    state["convex_hull"](state["pts"])


# ---------------------------------------------------------------------------
# Bench 4 — _core.ik_solver.solve (20-joint chain, 100 iters)
# ---------------------------------------------------------------------------


def setup_ik_solve():
    try:
        import pharos_engine._core as core  # type: ignore
    except ImportError:
        raise _SkipBench("pharos_engine._core extension not built (maturin develop --release)")
    if not hasattr(core, "solve_ik"):
        raise _SkipBench("_core.solve_ik missing (ik_solver.rs not compiled)")
    N = 20
    # Straight chain along +x, one unit per bone.
    chain = [(float(i), 0.0) for i in range(N + 1)]
    lengths = [1.0] * N
    # Target within reach but off-axis so FABRIK actually iterates.
    target = (float(N) * 0.7, float(N) * 0.4)
    return {
        "chain": chain,
        "lengths": lengths,
        "target": target,
        "solve_ik": core.solve_ik,
    }


def body_ik_solve(state):
    state["solve_ik"](
        state["chain"],
        state["target"],
        state["lengths"],
        max_iter=100,
        tolerance=0.0001,
    )


# ---------------------------------------------------------------------------
# Bench 5 — World3D.raycast BVH vs linear (500 bodies, 1000 rays)
# ---------------------------------------------------------------------------


def _build_world_for_raycast(N: int):
    from pharos_engine.physics3_bridge import Body3D, World3D

    rng = random.Random(20260707)
    world = World3D(backend="fallback")
    for _ in range(N):
        pos = (
            rng.uniform(-50.0, 50.0),
            rng.uniform(-50.0, 50.0),
            rng.uniform(-50.0, 50.0),
        )
        world.add_body(Body3D(position=pos, shape_kind="sphere", shape_params={"radius": 0.5}))
    return world


def _build_ray_batch(M: int):
    rng = random.Random(20260707 + 1)
    rays = []
    for _ in range(M):
        # Origin outside the box, direction toward origin (unit).
        origin = (
            rng.uniform(-100.0, 100.0),
            rng.uniform(-100.0, 100.0),
            rng.uniform(-100.0, 100.0),
        )
        length = math.sqrt(origin[0] ** 2 + origin[1] ** 2 + origin[2] ** 2)
        if length < 1e-6:
            length = 1.0
        direction = (-origin[0] / length, -origin[1] / length, -origin[2] / length)
        rays.append((origin, direction))
    return rays


def setup_raycast_bvh():
    try:
        world = _build_world_for_raycast(500)
        world.build_bvh()
    except Exception as exc:
        raise _SkipBench(f"World3D setup failed: {exc}")
    rays = _build_ray_batch(1000)
    return {"world": world, "rays": rays}


def body_raycast_bvh(state):
    world = state["world"]
    for origin, direction in state["rays"]:
        world.raycast(origin, direction, max_distance=200.0, use_bvh=True)


def setup_raycast_linear():
    try:
        world = _build_world_for_raycast(500)
    except Exception as exc:
        raise _SkipBench(f"World3D setup failed: {exc}")
    rays = _build_ray_batch(1000)
    return {"world": world, "rays": rays}


def body_raycast_linear(state):
    world = state["world"]
    for origin, direction in state["rays"]:
        world.raycast(origin, direction, max_distance=200.0, use_bvh=False)


# ---------------------------------------------------------------------------
# Bench 6 — DiagnosticsCollector.install() 10k events
# ---------------------------------------------------------------------------


def setup_diagnostics():
    try:
        from pharos_engine.diagnostics import DiagnosticsCollector
    except ImportError as exc:
        raise _SkipBench(f"pharos_engine.diagnostics unavailable: {exc}")
    return {
        "DiagnosticsCollector": DiagnosticsCollector,
        "logger": logging.getLogger("pharos_engine.perf_baseline_ss4"),
        "N": 10_000,
    }


def body_diagnostics(state):
    collector = state["DiagnosticsCollector"](max_events=state["N"] + 100, min_level="WARNING")
    collector.install()
    log = state["logger"]
    for i in range(state["N"]):
        log.warning("perf-baseline event %d", i)
    _ = len(collector.events())
    collector.uninstall()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


BENCH_SPECS: list[tuple[str, str, Callable, Callable]] = [
    ("raster.line_batch (10k lines, 512x512)", "10k lines", setup_line_batch, body_line_batch),
    ("raster.circle_batch (5k circles, 512x512)", "5k circles", setup_circle_batch, body_circle_batch),
    ("_core.hull.convex_hull (1k pts)", "1k pts", setup_convex_hull, body_convex_hull),
    ("_core.ik_solver.solve (20 joints, 100 iters)", "1 solve", setup_ik_solve, body_ik_solve),
    ("World3D.raycast BVH (500 bodies, 1000 rays)", "1000 rays", setup_raycast_bvh, body_raycast_bvh),
    ("World3D.raycast linear (500 bodies, 1000 rays)", "1000 rays", setup_raycast_linear, body_raycast_linear),
    ("DiagnosticsCollector.install (10k events)", "10k events", setup_diagnostics, body_diagnostics),
]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary in addition to the Markdown table.",
    )
    args = parser.parse_args(argv)

    results: list[BenchResult] = []
    for name, unit, setup, body in BENCH_SPECS:
        print(f"[bench] {name} ...", flush=True)
        result = run_bench(name, setup, body, unit=unit)
        results.append(result)
        if result.skipped:
            print(f"  SKIP: {result.skip_reason}")
        else:
            print(
                f"  min={result.min_ms:.3f} ms  mean={result.mean_ms:.3f} ms  "
                f"stdev={result.stdev_ms:.3f} ms  (n={len(result.samples)})"
            )

    print()
    print("| bench | min (ms) | mean (ms) | stdev (ms) | unit |")
    print("|---|---:|---:|---:|---|")
    for result in results:
        print(result.as_row())

    if args.json:
        import json

        payload = {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "warmup_passes": WARMUP_PASSES,
            "measured_passes": MEASURED_PASSES,
            "results": [
                {
                    "name": r.name,
                    "unit": r.unit,
                    "skipped": r.skipped,
                    "skip_reason": r.skip_reason,
                    "min_ms": r.min_ms if not r.skipped else None,
                    "mean_ms": r.mean_ms if not r.skipped else None,
                    "stdev_ms": r.stdev_ms if not r.skipped else None,
                    "samples": r.samples,
                }
                for r in results
            ],
        }
        print()
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
