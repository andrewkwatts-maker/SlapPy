"""Tests for the ``examples/hello_composite.py`` demo.

Pins seven behaviours of the multi-subsystem composite demo:

1. ``main()`` runs cleanly in-process at a 60-frame quick path.
2. At least one defender's hp drops below the starting
   :data:`DEFENDER_HP` after the full 180-frame integration.
3. The foundry trigger zone fires at least one enter event.
4. ``topology.connected_components`` over the rope's joint edges stays
   equal to ``1`` for every frame in the integration window.
5. The arena heat field's max temperature ends between 200 and 300 K --
   the defender hot-spots are re-emitted each frame but diffusion
   spreads heat into the bulk, so the global max sits near (and at
   times right at) the defender clamp value.
6. No NaNs leak from positions / hp / temperatures during the run.
7. The rasterised composite scene reproduces the committed visual
   baseline via :func:`slappyengine.testing.assert_scene_matches`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine.testing import assert_scene_matches

# -- Load the demo as a module so we don't depend on examples/ being on path --
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_composite.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_composite_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_composite_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Test 1: demo runs cleanly
# ---------------------------------------------------------------------------


def test_hello_composite_runs_without_error(demo, tmp_path):
    """``main(frames=60, render=False)`` returns a summary and never raises."""
    summary = demo.main(frames=60, render=False, out=tmp_path / "ignored.png")
    assert summary["frames"] == 60
    assert isinstance(summary["zone_enter_count"], int)
    assert isinstance(summary["attackers_killed"], int)
    assert isinstance(summary["total_spawns"], int)
    assert summary["nan_seen"] is False
    for hp in summary["defender_hp"]:
        assert np.isfinite(hp)
    assert np.isfinite(summary["max_heat"])


# ---------------------------------------------------------------------------
# Test 2: at least one defender takes damage
# ---------------------------------------------------------------------------


def test_defenders_take_damage(demo):
    """By frame 180 at least one defender's hp drops below the starting value."""
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    summary = demo.summarise(scene, demo.DEFAULT_FRAMES)

    starting_hp = demo.DEFENDER_HP
    hp_values = summary["defender_hp"]
    assert any(hp < starting_hp for hp in hp_values), (
        f"no defender lost hp; hp_values={hp_values}, start={starting_hp}"
    )
    # The damage counter should agree with the hp delta for at least one defender.
    assert max(summary["damage_dealt_to"]) > 0.0


# ---------------------------------------------------------------------------
# Test 3: foundry zone fires on entry
# ---------------------------------------------------------------------------


def test_zone_fires_on_entry(demo):
    """The foundry trigger zone records at least one enter event by frame 180."""
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    summary = demo.summarise(scene, demo.DEFAULT_FRAMES)

    assert summary["zone_enter_count"] >= 1, (
        f"foundry zone never fired; enter_count={summary['zone_enter_count']}"
    )


# ---------------------------------------------------------------------------
# Test 4: rope stays connected every frame
# ---------------------------------------------------------------------------


def test_rope_stays_connected(demo):
    """connected_components over the rope's joint edges is 1 every frame."""
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    history = scene.rope_components_history
    assert len(history) == demo.DEFAULT_FRAMES, (
        f"expected {demo.DEFAULT_FRAMES} component-count samples; "
        f"got {len(history)}"
    )
    assert all(c == 1 for c in history), (
        f"rope split during the run; unique component counts = "
        f"{sorted(set(history))}"
    )


# ---------------------------------------------------------------------------
# Test 5: thermal field spreads heat into the bulk
# ---------------------------------------------------------------------------


def test_thermal_diffused(demo):
    """Final-frame max heat sits between 200 and 300 K.

    Defenders re-emit at exactly :data:`DEFENDER_TEMP` (300) every frame,
    so the max can land right at 300 when a defender cell is the hot
    spot. Diffusion spreads heat into the surrounding bulk so the
    inclusive lower bound is 200.
    """
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    summary = demo.summarise(scene, demo.DEFAULT_FRAMES)

    max_heat = summary["max_heat"]
    assert 200.0 <= max_heat <= 300.0, (
        f"max heat at frame {demo.DEFAULT_FRAMES} = {max_heat:.4f} "
        f"outside expected [200, 300] window"
    )

    # The field must also show diffusion -- i.e. neighbours of the
    # defender hot cells must have warmed above ambient.
    assert scene.heat_field is not None
    T = scene.heat_field.temperature
    assert T.mean() > demo.HEAT_AMBIENT + 1.0, (
        f"heat never spread out of the defender cells; mean T = {T.mean():.4f}"
    )


# ---------------------------------------------------------------------------
# Test 6: no NaNs anywhere
# ---------------------------------------------------------------------------


def test_no_nan_anywhere(demo):
    """No NaN values escape into positions / hp / temperatures."""
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    # Defenders.
    for d in scene.defenders:
        assert np.isfinite(d.pos[0]) and np.isfinite(d.pos[1]), (
            f"defender pos non-finite: {d.pos}"
        )
        assert np.isfinite(d.hp), f"defender hp non-finite: {d.hp}"

    # Attackers.
    for live in scene.attackers:
        assert np.isfinite(live.body.pos[0]) and np.isfinite(live.body.pos[1]), (
            f"attacker pos non-finite: {live.body.pos}"
        )
        assert np.isfinite(live.body.hp), (
            f"attacker hp non-finite: {live.body.hp}"
        )

    # Rope dynamics positions.
    assert scene.world is not None
    assert np.all(np.isfinite(scene.world.positions)), (
        "rope positions contain NaN / inf"
    )

    # Thermal field.
    assert scene.heat_field is not None
    assert np.all(np.isfinite(scene.heat_field.temperature)), (
        "heat field temperatures contain NaN / inf"
    )

    # Scene-level flag agrees.
    assert scene.nan_seen is False


# ---------------------------------------------------------------------------
# Test 7: visual baseline (golden-master)
# ---------------------------------------------------------------------------


def test_hello_composite_visual_baseline(demo):
    """Render the composite scene and diff against the committed baseline PNG.

    First run writes
    ``python/slappyengine/testing/baselines/hello_composite.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    scene = demo.build_scene()
    demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)

    rendered = demo._render_frame(scene)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene_obj = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene_obj,
        "hello_composite",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
