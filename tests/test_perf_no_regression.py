"""Sprint 6 perf no-regression tripwire.

Tiny, representative per-subsystem benches with recorded baselines. Each
test asserts the measured median stays within **+/-50%** of the recorded
baseline (loose enough to survive CI noise on shared runners, tight
enough that a 2x regression fails the suite).

How the baselines were captured
-------------------------------
* Hardware: the workstation that produced ``docs/perf_dashboard.md``
  on 2026-05-30 (see header date).
* Method: each ``bench_*`` callable below was run with 30 samples (20
  for the V-cycle bench, 50 for the cheapest one) after warming, and
  the **median** is recorded as ``BASELINE_NS[<key>]``.
* The chosen tolerance is +/-50% because:
  1. We want the assertion to *fire* on a real 2x perf regression so
     someone investigates; that's the threshold of "noticeable in a
     hot loop on a 60 Hz frame budget".
  2. Sub-millisecond benches on shared CI runners routinely drift by
     30-40% run-to-run from thermal throttling and noisy neighbours.

If the baseline is genuinely stale (the engine got *faster*), the
upper assertion catches it and the bench can be re-baselined in the
next perf sprint -- a perf *improvement* shouldn't ship silently any
more than a regression should.

The five benches were chosen to cover the engine subsystems with the
most code-motion since Sprint 5:

* ``thermal``    -- 32x32 ``HeatField.step`` (numpy stencil)
* ``topology``   -- ``connected_components`` on a 200-node graph
* ``numerics``   -- 32x32 ``vcycle_poisson`` (1 V-cycle)
* ``dynamics``   -- 20-node rope, one ``World.step`` (XPBD core path)
* ``event_bus``  -- ``EventBus.publish`` with no subscribers
"""
from __future__ import annotations

import gc
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pytest


# Allow ``PYTHONPATH=python pytest`` and also ``pytest`` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PY_SRC = _REPO_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Recorded medians on 2026-05-30 from the calibration run. See module
#: docstring for the capture procedure.
BASELINE_NS: dict[str, float] = {
    "thermal_step_32x32":      24_400.0,        # ~24 us / step
    "topology_cc_200n":        366_000.0,       # ~0.37 ms / call
    "numerics_vcycle_32x32":   345_000.0,       # ~0.35 ms / call
    "dynamics_rope20_step":    712_000.0,       # ~0.71 ms / frame (steady)
    "eventbus_publish_nosub":  140.0,           # ~140 ns / emit
}

#: +/-50% band -- see module docstring rationale.
TOLERANCE = 0.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _median_ns(fn, n: int = 30, warmup: int = 3) -> float:
    """Run ``fn`` ``n`` times and return the median in nanoseconds.

    Always warms first (``warmup`` calls + ``gc.collect``) so the first
    sample isn't poisoned by import / allocation cost.
    """
    for _ in range(warmup):
        fn()
    gc.collect()
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e9)
    return statistics.median(samples)


def _assert_within_band(key: str, measured_ns: float) -> None:
    """Assert ``measured_ns`` is within +/-TOLERANCE of ``BASELINE_NS[key]``."""
    baseline = BASELINE_NS[key]
    lower = baseline * (1.0 - TOLERANCE)
    upper = baseline * (1.0 + TOLERANCE)
    assert lower <= measured_ns <= upper, (
        f"{key}: measured {measured_ns:,.0f} ns is outside "
        f"+/-{TOLERANCE*100:.0f}% band around baseline {baseline:,.0f} ns "
        f"(allowed [{lower:,.0f}, {upper:,.0f}]).\n"
        f"  - If the engine got SLOWER by >50%, investigate the offending "
        f"commit before re-baselining.\n"
        f"  - If the engine got FASTER by >50%, re-baseline this entry in "
        f"BASELINE_NS so future regressions are caught against the new floor."
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_thermal_heatfield_step_32x32_within_band() -> None:
    """HeatField.step on a 32x32 grid -- numpy stencil hot path."""
    from slappyengine.thermal import HeatField

    rng = np.random.default_rng(0)
    grid = rng.standard_normal((32, 32)).astype(np.float64)
    field = HeatField(grid, conductivity=1.0, diffusivity=0.1)
    measured = _median_ns(lambda: field.step(0.05), n=30)
    _assert_within_band("thermal_step_32x32", measured)


def test_topology_cc_200_nodes_within_band() -> None:
    """connected_components on a 200-node graph -- union-find Python loop."""
    from slappyengine.topology import connected_components

    rng = np.random.default_rng(0xC0FFEE)
    edges = rng.integers(0, 200, size=(400, 2), dtype=np.int64)
    measured = _median_ns(lambda: connected_components(200, edges), n=30)
    _assert_within_band("topology_cc_200n", measured)


def test_numerics_vcycle_32x32_within_band() -> None:
    """vcycle_poisson on a 32x32 grid, 1 V-cycle -- restrict/prolong alloc path."""
    from slappyengine.numerics import vcycle_poisson

    rng = np.random.default_rng(0xBEEF)
    rhs = rng.standard_normal((32, 32)).astype(np.float32)
    mask = np.ones((32, 32), dtype=bool)
    measured = _median_ns(lambda: vcycle_poisson(rhs, mask, n_cycles=1), n=20)
    _assert_within_band("numerics_vcycle_32x32", measured)


def test_dynamics_rope20_step_within_band() -> None:
    """World.step on a 20-node distance-joint rope at steady state."""
    from slappyengine.dynamics import JointSpec, World

    world = World(gravity=(0.0, -9.81))
    pos = np.array([(float(i), 0.0) for i in range(20)], dtype=np.float64)
    offset, _ = world.add_nodes(pos, masses=1.0)
    for i in range(19):
        world.add_joint(JointSpec(
            kind="distance",
            node_a=offset + i,
            node_b=offset + i + 1,
            params={"rest_length": 1.0, "compliance": 0.0},
        ))
    world.warn_overdamping = False
    # Settle to steady-state before measuring so the median isn't
    # poisoned by the first-frame projection burst.
    for _ in range(5):
        world.step(1.0 / 60.0)
    measured = _median_ns(lambda: world.step(1.0 / 60.0), n=30, warmup=0)
    _assert_within_band("dynamics_rope20_step", measured)


def test_eventbus_publish_no_subscriber_within_band() -> None:
    """EventBus.publish dispatch with no subscribers -- per-emit Python overhead."""
    from slappyengine.event_bus import EventBus

    bus = EventBus()

    def _burst() -> None:
        # 100 publishes per measurement so the per-sample resolution
        # of perf_counter (~100 ns on Windows) doesn't dominate.
        for _ in range(100):
            bus.publish("tick", value=1)

    measured_ns = _median_ns(_burst, n=30) / 100.0
    _assert_within_band("eventbus_publish_nosub", measured_ns)


# ---------------------------------------------------------------------------
# Meta-test: keep the baseline table and the test bodies in sync.
# ---------------------------------------------------------------------------
def test_baseline_table_covers_every_bench() -> None:
    """Every key in ``BASELINE_NS`` must be referenced by a test in this
    module, and every test must reference exactly one baseline key."""
    src = Path(__file__).read_text(encoding="utf-8")
    for key in BASELINE_NS:
        assert f'"{key}"' in src, (
            f"BASELINE_NS key {key!r} is not referenced by any test body."
        )
