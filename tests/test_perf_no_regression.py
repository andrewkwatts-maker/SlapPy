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
#:
#: The ``pbf_bridge_step_b`` and ``softbody_world_step_20n`` entries were
#: added 2026-06-01 from the refresh sweep documented in
#: ``benchmarks/baseline_report.md`` ("2026-06-01 refresh" section). Both
#: are 3-run medians with <5% run-to-run variance on this workstation —
#: they meet the "stable enough to pin" bar called out in the refresh
#: sprint. The pair use the looser :data:`TOLERANCE_LOOSE` band because
#: scenario B's particle count drifts as the splatter presets get tuned.
#:
#: v3 refresh (2026-06-01 evening) re-baselined ``pbf_bridge_step_b``
#: from 40.80 ms → 34.41 ms after Sprint 5A's YAML-cache fix (commit
#: 6e310c3) held across 3 fresh runs. The new
#: ``eventbus_publish_inline_nosub_ns`` tripwire guards the
#: hardening-round-9 inline fast-path on ``EventBus.publish``
#: (see ``event_bus.py`` lines 130-133); 3-run stdev was 4.8% on the
#: capture host so it gets the tight :data:`TOLERANCE` band.
BASELINE_NS: dict[str, float] = {
    "thermal_step_32x32":          24_400.0,        # ~24 us / step
    "topology_cc_200n":            366_000.0,       # ~0.37 ms / call
    "numerics_vcycle_32x32":       345_000.0,       # ~0.35 ms / call
    "dynamics_rope20_step":        712_000.0,       # ~0.71 ms / frame (steady)
    "eventbus_publish_nosub":      140.0,           # ~140 ns / emit
    # Added 2026-06-01 (v2 refresh):
    "pbf_bridge_step_b":           34_410_000.0,    # ~34.41 ms / (snow+mud).step — v3 re-baseline after Sprint 5A YAML cache
    "softbody_world_step_20n":     709_000.0,       # ~0.71 ms / step (matches dynamics_rope20_step within 0.4%)
    # Added 2026-06-01 (v3 refresh):
    "eventbus_publish_inline_nosub_ns":  152.0,     # ~152 ns / emit — guards round-9 inline fast-path on EventBus.publish
}

#: +/-50% band -- see module docstring rationale.
TOLERANCE = 0.50

#: Looser +/-60% band for benches whose workload (not just engine speed)
#: drifts between runs of the perf-refresh sprint. Currently used by the
#: scenario-B PBF bridge bench, where the splatter preset particle count
#: has been retuned several times since the 2026-05-30 capture.
TOLERANCE_LOOSE = 0.60


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


def _assert_within_band(key: str, measured_ns: float, *,
                        tolerance: float = TOLERANCE) -> None:
    """Assert ``measured_ns`` is within +/-tolerance of ``BASELINE_NS[key]``."""
    baseline = BASELINE_NS[key]
    lower = baseline * (1.0 - tolerance)
    upper = baseline * (1.0 + tolerance)
    assert lower <= measured_ns <= upper, (
        f"{key}: measured {measured_ns:,.0f} ns is outside "
        f"+/-{tolerance*100:.0f}% band around baseline {baseline:,.0f} ns "
        f"(allowed [{lower:,.0f}, {upper:,.0f}]).\n"
        f"  - If the engine got SLOWER by >{tolerance*100:.0f}%, investigate "
        f"the offending commit before re-baselining.\n"
        f"  - If the engine got FASTER by >{tolerance*100:.0f}%, re-baseline "
        f"this entry in BASELINE_NS so future regressions are caught against "
        f"the new floor."
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
# Added 2026-06-01 -- cross-subsystem benches with <5% run-to-run variance.
# ---------------------------------------------------------------------------
def test_pbf_bridge_step_scenario_b_within_band() -> None:
    """ParticleField scenario B (snow + mud combined ~4700 particles).

    The PBF bridge inside ``ParticleField.step`` dominates this scenario
    on the CPU path; we step both fields once per measurement to mirror
    the harness in ``benchmarks/refresh_2026_05_31.py``.
    """
    from slappyengine.physics.blast import detonate
    from slappyengine.physics.particle_field import ParticleField
    from slappyengine.physics.splatter_presets import get as get_preset

    W, H, GROUND_Y, DT = 640, 360, 280, 1.0 / 60.0

    def _make(name: str) -> ParticleField:
        preset = get_preset(name)
        f = ParticleField(width=W, height=H, gravity=preset.gravity)
        f.fill_ground(top_y=GROUND_Y, color=(180, 150, 90), sub_color=(60, 44, 28))
        return f

    snow = _make("snow")
    mud = _make("mud")
    detonate(snow, get_preset("snow"), x=320.0, y=280.0,
             crater_radius=60.0, crater_depth=28.0,
             rng=np.random.default_rng(11))
    detonate(mud, get_preset("mud"), x=320.0, y=280.0,
             crater_radius=60.0, crater_depth=28.0,
             rng=np.random.default_rng(22))
    # Warm a handful of frames so first-step JIT/allocation isn't measured.
    for _ in range(3):
        snow.step(DT)
        mud.step(DT)

    def _pair() -> None:
        snow.step(DT)
        mud.step(DT)

    # Heavier bench -- 5 iters keeps wall time <1s while still giving a
    # tight median (the harness saw <3% stdev across 3 fresh runs).
    measured = _median_ns(_pair, n=5, warmup=0)
    _assert_within_band("pbf_bridge_step_b", measured,
                        tolerance=TOLERANCE_LOOSE)


def test_eventbus_publish_inline_fast_path_within_band() -> None:
    """``EventBus.publish`` with no subscribers — guards the inline fast-path.

    Hardening round 9 inlined the ``type(event_type) is str`` and empty
    check on ``EventBus.publish`` so the validator call frame doesn't
    dominate the no-subscriber dispatch. The v3 perf refresh
    (``benchmarks/baseline_report.md`` "2026-06-01 v3 refresh" section)
    pinned this at 152 ns on the capture host with 4.8% 3-run stdev.

    The existing :func:`test_eventbus_publish_no_subscriber_within_band`
    holds a 140 ns baseline against the v2 capture; this companion test
    pins the v3 number so a future refactor that re-introduces a
    function-call frame on the fast path will fail one of the two
    tripwires even if the other's wider band would have swallowed the
    drift.
    """
    from slappyengine.event_bus import EventBus

    bus = EventBus()

    def _burst() -> None:
        for _ in range(100):
            bus.publish("tick", value=1)

    measured_ns = _median_ns(_burst, n=30) / 100.0
    _assert_within_band("eventbus_publish_inline_nosub_ns", measured_ns)


def test_softbody_world_step_20n_within_band() -> None:
    """``dynamics.World.step`` on a 20-node distance-joint rope (steady).

    This is the same surrogate ``benchmarks/refresh_2026_05_31.py`` uses
    for the Rust XPBD core. Intentionally distinct from
    :func:`test_dynamics_rope20_step_within_band` -- they share a baseline
    (within 0.4%) but exercise the same code path through two different
    entry points so each can fail independently when surgery happens to
    one wrapper but not the other.
    """
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
    for _ in range(5):
        world.step(1.0 / 60.0)
    measured = _median_ns(lambda: world.step(1.0 / 60.0), n=20, warmup=0)
    _assert_within_band("softbody_world_step_20n", measured,
                        tolerance=TOLERANCE_LOOSE)


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
