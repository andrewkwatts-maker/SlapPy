"""Tests for the ``examples/hello_zone.py`` demo.

Pins six behaviours of the trigger-zone demo:

1. ``main()`` runs cleanly in-process (default 240-frame path).
2. After a full run every zone has at least 1 recorded enter event.
3. The threshold zone fires at least once across the run.
4. Per zone, exit_count == enter_count - len(occupancy), i.e. nothing
   gets lost or double-counted by the manager.
5. Every entity position emitted by the path closed-form is finite.
6. The rendered arena reproduces a stable golden master via
   :func:`slappyengine.testing.assert_scene_matches`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_zone.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_zone_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_zone_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_runs_without_error(demo, tmp_path):
    """``main(frames=240, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=240, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 240
    assert set(summary["enter_counts"].keys()) == {
        "safe_zone", "danger_zone", "trigger_zone",
    }
    assert set(summary["exit_counts"].keys()) == {
        "safe_zone", "danger_zone", "trigger_zone",
    }
    assert summary["threshold_fire_count"] >= 0
    assert summary["nan_seen"] is False


# ────────────────────────────────────────────────────────────────────────────
# Test 2: at least one enter event per zone
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_entries_recorded(demo):
    """Each of the three named zones must see at least one enter event.

    The sinusoidal paths are tuned so within 240 frames every zone is
    crossed at least once. A regression here means an entity path no
    longer crosses a zone — either the path frequencies drifted or the
    zone geometry changed.
    """
    manager, records = demo.build_manager()
    demo.step_demo(manager, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    for name in ("safe_zone", "danger_zone", "trigger_zone"):
        n_enters = len(records["enter"][name])
        assert n_enters >= 1, (
            f"zone {name!r} saw no enter events across "
            f"{demo.DEFAULT_FRAMES} frames"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 3: threshold zone fires at least once
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_threshold_fired(demo):
    """The trigger_zone threshold callback must fire >= 1 time.

    The demo ramps ``value`` from 0 to 5 and the threshold sits at 2.5
    with hysteresis 0.25; frame 0 (value=0) already crosses downward,
    so this guards against the ramp/threshold/hysteresis wiring being
    broken.
    """
    manager, records = demo.build_manager()
    demo.step_demo(manager, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    assert len(records["threshold"]) >= 1


# ────────────────────────────────────────────────────────────────────────────
# Test 4: enter/exit counts balance against occupancy
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_enter_exit_pairs_balanced(demo):
    """For every zone: ``exit_count == enter_count - currently_inside_count``.

    The ZoneManager's per-frame diff guarantees that each entity contributes
    matched enter/exit pairs except for the ones still inside at the
    final frame. So:

        enter_count - exit_count == |occupancy|
    """
    manager, records = demo.build_manager()
    demo.step_demo(manager, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    for name in ("safe_zone", "danger_zone", "trigger_zone"):
        n_enter = len(records["enter"][name])
        n_exit = len(records["exit"][name])
        n_inside = len(manager.occupancy(name))
        assert n_exit == n_enter - n_inside, (
            f"zone {name!r} unbalanced: "
            f"enter={n_enter}, exit={n_exit}, occupancy={n_inside} "
            f"(expected exit == enter - occupancy)"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: no NaN in any entity position emitted by the demo
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_no_nan(demo):
    """Every (x, y) the closed-form path generates is finite."""
    manager, _records = demo.build_manager()
    trace = demo.step_demo(manager, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    assert trace["nan_seen"] is False
    for frame_positions in trace["positions_history"]:
        for name, (x, y) in frame_positions.items():
            assert np.isfinite(x), f"non-finite x for {name!r}: {x!r}"
            assert np.isfinite(y), f"non-finite y for {name!r}: {y!r}"


# ────────────────────────────────────────────────────────────────────────────
# Test 6: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_zone_visual_baseline(demo):
    """Render the arena and diff against the committed baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_zone.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    manager, _records = demo.build_manager()
    trace = demo.step_demo(manager, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(trace, manager)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_zone",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
