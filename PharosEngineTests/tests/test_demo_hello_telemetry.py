"""Tests for the ``examples/hello_telemetry.py`` demo.

Pins five behaviours of the telemetry demo:

1. ``main()`` runs cleanly in-process and returns a structured summary.
2. The ``"physics.*"`` subscriber sees every ``physics.*`` emit and no
   spurious ones.
3. ``get_event_history(name_pattern="zone.*")`` returns exactly the five
   ``zone.enter`` records emitted by the 60-frame timeline.
4. The no-subscriber emit path costs less than 200 ns/emit measured over
   100,000 emits — guards the allocation-free fast path.
5. The rendered events-per-frame histogram reproduces a stable golden
   master via :func:`pharos_engine.testing.assert_scene_matches`.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import pharos_engine.telemetry as telemetry
from pharos_engine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_telemetry.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "hello_telemetry_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_telemetry_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(autouse=True)
def _isolate_telemetry():
    """Reset the global telemetry state around every test."""
    # Snapshot the handle list defensively — _subscribers mutates as we go.
    for h in list(telemetry._subscribers.keys()):
        telemetry.unsubscribe(h)
    telemetry.clear_history()
    telemetry.set_history_capacity(1000)
    yield
    for h in list(telemetry._subscribers.keys()):
        telemetry.unsubscribe(h)
    telemetry.clear_history()
    telemetry.set_history_capacity(1000)


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_telemetry_runs_without_error(demo, tmp_path):
    """``main()`` returns a populated summary and never raises."""
    summary = demo.main(
        frames=demo.DEFAULT_FRAMES,
        render=False,
        out=tmp_path / "ignored.png",
        bench_emits=10_000,  # keep CI cheap
    )
    assert summary["frames"] == demo.DEFAULT_FRAMES
    # 60 physics + 5 zone + 60 render + 1 thermal = 126 expected emits.
    assert summary["expected_events"] == 126
    assert summary["wildcard_count"] == summary["expected_events"]
    assert summary["history_zone_len"] == len(demo.ZONE_ENTER_FRAMES)
    assert summary["bench_idle_ns_per_emit"] > 0.0
    assert summary["bench_busy_ns_per_emit"] > 0.0


# ────────────────────────────────────────────────────────────────────────────
# Test 2: physics_logger only sees physics.* events
# ────────────────────────────────────────────────────────────────────────────

def test_subscribers_receive_matching_events(demo):
    """The ``"physics.*"`` subscriber must fire exactly once per physics emit
    and never on render/zone/thermal events. The wildcard subscriber must
    count every emit. The zone subscriber must collect exactly five
    records."""
    subs = demo.build_subscribers()
    trace = demo.run_timeline(
        frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )

    # One physics.step per frame.
    assert subs.physics_count == demo.DEFAULT_FRAMES
    # Five zone.enter events, all carrying the right zone name.
    assert len(subs.zone_events) == len(demo.ZONE_ENTER_FRAMES)
    assert all(
        ev["zone"] == demo.ZONE_NAME for ev in subs.zone_events
    )
    # Wildcard catches everything (physics + zone + render + thermal).
    expected = (
        trace["frames"]                      # physics.step
        + len(trace["zone_enter_frames"])    # zone.enter
        + trace["frames"]                    # render.frame
        + 1                                  # thermal.phase_change
    )
    assert subs.wildcard_count == expected

    subs.detach()


# ────────────────────────────────────────────────────────────────────────────
# Test 3: history pattern filter returns exactly 5 zone.enter records
# ────────────────────────────────────────────────────────────────────────────

def test_history_pattern_filter_returns_5_zone_enter(demo):
    """``get_event_history(pattern="zone.*")`` returns exactly five entries
    after the timeline runs."""
    subs = demo.build_subscribers()
    demo.run_timeline(
        frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )

    history = telemetry.get_event_history(name_pattern="zone.*")
    assert len(history) == 5
    # Every record is a zone.enter carrying the synthetic entity id.
    for ev in history:
        assert ev.name == "zone.enter"
        assert ev.payload["zone"] == demo.ZONE_NAME
        assert isinstance(ev.payload["entity_id"], int)

    subs.detach()


# ────────────────────────────────────────────────────────────────────────────
# Test 4: no-subscriber emit fast path budget
# ────────────────────────────────────────────────────────────────────────────

def test_no_subscriber_emit_under_budget_ns(demo):
    """The zero-subscriber, zero-history emit path stays under 200 ns/emit.

    Measured across 100,000 emits. We warm the CPU caches with a small
    burst first so the first-iteration JIT/branch-prediction noise does
    not poison the headline number.
    """
    # Ensure a truly idle bus.
    for h in list(telemetry._subscribers.keys()):
        telemetry.unsubscribe(h)
    telemetry.set_history_capacity(0)

    try:
        # Warm-up.
        for _ in range(1_000):
            telemetry.emit("warmup.event")

        emits = 100_000
        t0 = time.perf_counter_ns()
        for _ in range(emits):
            telemetry.emit("noop.event")
        t1 = time.perf_counter_ns()

        ns_per_emit = (t1 - t0) / emits
    finally:
        telemetry.set_history_capacity(1000)

    assert ns_per_emit < 200.0, (
        f"no-subscriber emit too slow: {ns_per_emit:.2f} ns/emit "
        f"(budget 200 ns)"
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_telemetry_visual_baseline(demo):
    """Render the histogram and diff against the committed baseline PNG.

    First run writes ``python/pharos_engine/testing/baselines/hello_telemetry.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    subs = demo.build_subscribers()
    trace = demo.run_timeline(
        frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT,
    )
    rendered = demo._render_histogram(trace)
    subs.detach()

    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_telemetry",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
