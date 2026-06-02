"""Tests for the ``examples/hello_iso.py`` demo.

Pins five behaviours of the iso/wave/combat demo:

1. ``main()`` runs cleanly in-process at a 60-frame quick path.
2. After enough frames the wave schedule emits all 4 spawns.
3. After enough frames at least one defender's hp has dropped below the
   starting :data:`DEFENDER_HP`.
4. All positions (defenders + live attackers) remain finite throughout
   the integration — no NaNs leak out of the combat math.
5. The rasterised arena reproduces the committed visual baseline via
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
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_iso.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_iso_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_iso_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly
# ────────────────────────────────────────────────────────────────────────────

def test_hello_iso_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert isinstance(summary["total_spawns"], int)
    assert isinstance(summary["attackers_killed"], int)
    assert summary["nan_seen"] is False
    assert summary["positions_finite"] is True
    # Defender hp values are finite floats.
    for hp in summary["defender_hp"]:
        assert np.isfinite(hp)


# ────────────────────────────────────────────────────────────────────────────
# Test 2: full wave fires its 4 spawns
# ────────────────────────────────────────────────────────────────────────────

def test_hello_iso_attackers_spawn(demo):
    """After the full 360-frame integration the schedule emits all 4 spawns."""
    world = demo.build_world()
    demo.step_world(world, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    summary = demo.summarise(world, demo.DEFAULT_FRAMES)

    assert summary["total_spawns"] == demo.WAVE_COUNT == 4, (
        f"wave should have emitted {demo.WAVE_COUNT} spawns; "
        f"got total_spawns={summary['total_spawns']}"
    )
    assert summary["wave_finished"] is True


# ────────────────────────────────────────────────────────────────────────────
# Test 3: at least one defender takes damage
# ────────────────────────────────────────────────────────────────────────────

def test_hello_iso_defenders_take_damage(demo):
    """By the end of the full run at least one defender hp < starting hp."""
    world = demo.build_world()
    demo.step_world(world, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    summary = demo.summarise(world, demo.DEFAULT_FRAMES)

    starting_hp = demo.DEFENDER_HP
    hp_values = summary["defender_hp"]
    assert any(hp < starting_hp for hp in hp_values), (
        f"no defender lost hp; hp_values={hp_values}, start={starting_hp}"
    )
    # Damage counter should agree with hp delta on the most-damaged defender.
    assert max(summary["damage_dealt_to"]) > 0.0


# ────────────────────────────────────────────────────────────────────────────
# Test 4: no NaNs in any tracked position
# ────────────────────────────────────────────────────────────────────────────

def test_hello_iso_no_nan(demo):
    """All defender + attacker positions remain finite for the full run."""
    world = demo.build_world()
    demo.step_world(world, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    defenders = world["defenders"]
    attackers = world["attackers"]

    for d in defenders:
        assert np.isfinite(d.pos[0]) and np.isfinite(d.pos[1]), (
            f"defender position non-finite: {d.pos}"
        )
        assert np.isfinite(d.hp), f"defender hp non-finite: {d.hp}"

    for live in attackers:
        assert np.isfinite(live.body.pos[0]) and np.isfinite(live.body.pos[1]), (
            f"attacker position non-finite: {live.body.pos}"
        )
        assert np.isfinite(live.body.hp), (
            f"attacker hp non-finite: {live.body.hp}"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 5: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_iso_visual_baseline(demo):
    """Render the arena and diff against the committed baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_iso.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    world = demo.build_world()
    demo.step_world(world, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(world)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_iso",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
