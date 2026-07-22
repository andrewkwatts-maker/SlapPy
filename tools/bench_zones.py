"""
Bench :class:`pharos_engine.zones.ZoneManager.update` under load.

Compares the legacy O(zones × entities) linear-scan against the
spatial-hash accelerated path across four scenarios:

    * 100 entities / 10 zones
    * 500 entities / 25 zones
    * 1000 entities / 50 zones
    * 5000 entities / 100 zones

For each scenario, builds a manager + zones, scatters entities
randomly across a 100×100 world, calls ``update(positions)`` 100
times, and measures the median wall-clock per call.

Usage
-----
    cd <worktree-root>
    PYTHONPATH=python python tools/bench_zones.py

Output is a markdown table on stdout, ready to paste into the design
doc.
"""
from __future__ import annotations

import gc
import random
import statistics
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PY_SRC = _REPO_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

from pharos_engine.zones import RectZone, ZoneManager  # noqa: E402


WORLD = 100.0
FRAMES = 100
SCENARIOS = [
    (100, 10),
    (500, 25),
    (1000, 50),
    (5000, 100),
]


def _build_manager(n_zones: int, rng: random.Random) -> ZoneManager:
    mgr = ZoneManager()
    # Zones are 4-12 units on a side, scattered across the world.
    # Keeps cell-size around the upper clamp (12 * 1.5 = 18 → 16) so the
    # bench reflects the typical "many small zones in a big world" case.
    for i in range(n_zones):
        w = rng.uniform(4.0, 12.0)
        h = rng.uniform(4.0, 12.0)
        x = rng.uniform(0.0, WORLD - w)
        y = rng.uniform(0.0, WORLD - h)
        mgr.add(RectZone(name=f"z{i}", x=x, y=y, w=w, h=h))
    return mgr


def _build_positions(
    n_entities: int, rng: random.Random,
) -> dict[int, tuple[float, float]]:
    return {
        i: (rng.uniform(0.0, WORLD), rng.uniform(0.0, WORLD))
        for i in range(n_entities)
    }


def _time_update(
    mgr: ZoneManager,
    positions: dict[int, tuple[float, float]],
    frames: int,
) -> float:
    """Return median per-call wall-clock in microseconds."""
    samples: list[float] = []
    for _ in range(frames):
        t0 = time.perf_counter()
        mgr.update(positions)
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1e6)
    return statistics.median(samples)


def _run_scenario(
    n_entities: int, n_zones: int, frames: int = FRAMES,
) -> tuple[float, float, float]:
    """Return ``(linear_us, hash_us, speedup)`` for one scenario."""
    # Same seed for both passes — identical entities + zones → identical
    # contains_point traffic — so the speedup figure isolates the index.
    rng_zones = random.Random(0x5A11A47ED)
    rng_pos = random.Random(0xC0DEDBAD)

    mgr_linear = _build_manager(n_zones, rng_zones)
    mgr_linear.enable_spatial_hash(False)
    positions = _build_positions(n_entities, rng_pos)
    # Warm cache (occupancy seeded, first-frame enter events fired).
    mgr_linear.update(positions)
    gc.collect()
    linear_us = _time_update(mgr_linear, positions, frames)

    rng_zones = random.Random(0x5A11A47ED)
    rng_pos = random.Random(0xC0DEDBAD)
    mgr_hash = _build_manager(n_zones, rng_zones)
    positions = _build_positions(n_entities, rng_pos)
    mgr_hash.update(positions)
    gc.collect()
    hash_us = _time_update(mgr_hash, positions, frames)

    speedup = linear_us / hash_us if hash_us > 0 else float("inf")
    return linear_us, hash_us, speedup


def main() -> int:
    rows: list[tuple[int, int, float, float, float]] = []
    for n_entities, n_zones in SCENARIOS:
        linear_us, hash_us, speedup = _run_scenario(n_entities, n_zones)
        rows.append((n_entities, n_zones, linear_us, hash_us, speedup))

    print("# ZoneManager.update - spatial-hash vs linear-scan")
    print()
    print("| entities | zones | linear (us) | spatial-hash (us) | speedup |")
    print("|---------:|------:|------------:|------------------:|--------:|")
    for n_entities, n_zones, linear_us, hash_us, speedup in rows:
        print(
            f"| {n_entities} | {n_zones} | "
            f"{linear_us:.1f} | {hash_us:.1f} | "
            f"{speedup:.2f}x |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
