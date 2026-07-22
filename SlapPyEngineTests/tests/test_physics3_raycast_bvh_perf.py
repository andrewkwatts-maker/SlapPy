"""Perf regression for BVH-accelerated :meth:`World3D.raycast` — OO2.

Builds a 500-body World3D of random axis-aligned boxes, fires the same
batch of rays through the linear O(n) path (``use_bvh=False``) and the
BVH-accelerated path (``use_bvh=True``), and asserts the BVH is at
least 3x faster wall-clock. This is a coarse floor — the real speedup
should be closer to log-n / n; the 3x threshold just guards against
regressions that silently disable the BVH.

Deterministic: the random seed is fixed so the perf ratio is stable
across CI runs. The assertion message logs the raw times and ratio so
a failure surfaces the actual numbers rather than just ``AssertionError``.
"""
from __future__ import annotations

import math
import random
import time

from pharos_engine.physics3_bridge import Body3D, World3D


_SEED = 20260707
_BODY_COUNT = 500
_RAY_COUNT = 200
_SPACE_HALF = 50.0  # random positions drawn from [-50, 50] per axis
_MIN_SPEEDUP = 3.0


def _seeded_box(rng: random.Random) -> Body3D:
    """Return a Body3D at a random position with a small random extent."""
    cx = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    cy = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    cz = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    hx = rng.uniform(0.2, 1.0)
    hy = rng.uniform(0.2, 1.0)
    hz = rng.uniform(0.2, 1.0)
    return Body3D(
        position=(cx, cy, cz),
        mass=0.0,
        shape_kind="box",
        shape_params={"half_extents": (hx, hy, hz)},
    )


def _seeded_ray(rng: random.Random) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    """Return a (origin, direction) pair. Direction is normalised."""
    ox = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    oy = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    oz = rng.uniform(-_SPACE_HALF, _SPACE_HALF)
    while True:
        dx = rng.uniform(-1.0, 1.0)
        dy = rng.uniform(-1.0, 1.0)
        dz = rng.uniform(-1.0, 1.0)
        n = math.sqrt(dx * dx + dy * dy + dz * dz)
        if n > 1e-4:
            break
    return (ox, oy, oz), (dx / n, dy / n, dz / n)


def _build_world() -> tuple[World3D, list[tuple[tuple[float, float, float], tuple[float, float, float]]]]:
    rng = random.Random(_SEED)
    world = World3D(backend="fallback")
    for _ in range(_BODY_COUNT):
        world.add_body(_seeded_box(rng))
    rays = [_seeded_ray(rng) for _ in range(_RAY_COUNT)]
    return world, rays


def test_bvh_raycast_beats_linear_by_at_least_3x() -> None:
    world, rays = _build_world()

    # Pre-build the BVH so first-call amortisation doesn't pollute the
    # BVH timing. The linear path has no such cache to warm.
    world.build_bvh()

    # Warmup both paths (JIT-agnostic — Python doesn't JIT, but the
    # attribute-lookup / method-dispatch caches still benefit).
    for origin, direction in rays[:5]:
        world.raycast(origin, direction, use_bvh=False)
        world.raycast(origin, direction, use_bvh=True)

    t0 = time.perf_counter()
    for origin, direction in rays:
        world.raycast(origin, direction, use_bvh=False)
    linear_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    for origin, direction in rays:
        world.raycast(origin, direction, use_bvh=True)
    bvh_time = time.perf_counter() - t0

    # Guard against zero-division / absurdly fast times on very fast
    # machines — treat sub-microsecond total wall-clock as a red flag.
    assert bvh_time > 0.0, (
        f"BVH raycast time non-positive ({bvh_time!r}s) — timer resolution?"
    )
    speedup = linear_time / bvh_time
    msg = (
        f"BVH raycast should be >= {_MIN_SPEEDUP}x faster than linear "
        f"over {_BODY_COUNT} bodies x {_RAY_COUNT} rays; got "
        f"linear={linear_time*1000.0:.2f}ms, bvh={bvh_time*1000.0:.2f}ms, "
        f"speedup={speedup:.2f}x"
    )
    assert speedup >= _MIN_SPEEDUP, msg
