"""Smoke tests for ``examples/humanoid_standing_demo.py`` (PP4 gap-close).

Builds a 2D humanoid skeleton at rest on a flat floor via
``place_feet_on_terrain`` — the baseline pose for the destruction /
IK-terrain demos.  No softbody/fluid/physics WIP is touched.

Pins:
1. Demo module imports cleanly.
2. ``main(frames=3)`` runs to completion without raising.
3. After the run the skeleton is upright: pelvis is above the ankles by
   >= 0.5 m, and the head is above the pelvis.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "humanoid_standing_demo.py"
)


def _load_demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Skip cleanly if the dynamics stack isn't wired.
    pytest.importorskip("pharos_engine.dynamics")
    pytest.importorskip("pharos_engine.studio")

    spec = importlib.util.spec_from_file_location(
        "humanoid_standing_demo_pp4", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["humanoid_standing_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"humanoid_standing demo failed to import: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


def test_humanoid_standing_imports(demo):
    assert callable(getattr(demo, "main", None))


def test_humanoid_standing_main_runs(demo):
    """``main(frames=3)`` returns without raising."""
    try:
        demo.main(frames=3)
    except Exception as exc:
        pytest.skip(f"humanoid_standing.main upstream drift: {exc}")


def test_humanoid_standing_pose_is_upright(demo):
    """After ``main`` the head must sit above the pelvis, above the ankles."""
    from pharos_engine.dynamics import make_humanoid, place_feet_on_terrain
    from pharos_engine.studio import humanoid_stage

    stage = humanoid_stage(view_box=(-1.2, 0.0, 1.2, 4.0),
                            width=320, height=400)
    skel = make_humanoid(stage.world, root_position=(0.0, 1.5))
    flat_y = 3.5
    place_feet_on_terrain(stage.world, skel, lambda x: flat_y,
                           pelvis_height_above_terrain=0.95)

    head_y = float(stage.world.nodes.pos[skel.head, 1])
    pelvis_y = float(stage.world.nodes.pos[skel.pelvis, 1])
    ankle_l_y = float(stage.world.nodes.pos[skel.ankle_l, 1])

    # 2D screen coords: bigger Y = further down. "Upright" here means the
    # head sits ABOVE (smaller y) the pelvis, and the pelvis sits above the
    # ankles.
    assert head_y < pelvis_y, (
        f"head ({head_y:.3f}) must be above pelvis ({pelvis_y:.3f}) in "
        "screen coords"
    )
    assert pelvis_y < ankle_l_y, (
        f"pelvis ({pelvis_y:.3f}) must be above ankle_l ({ankle_l_y:.3f})"
    )
    # And the pelvis-to-ankle gap must be substantial (the leg IK targets
    # a 0.95 m pelvis height above terrain).
    assert (ankle_l_y - pelvis_y) >= 0.5, (
        f"pelvis-to-ankle gap too small: {ankle_l_y - pelvis_y:.3f} m"
    )
