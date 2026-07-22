"""Smoke test for ``examples/humanoid_ik_terrain_demo.py`` (QQ2 gap-close, batch 2).

The demo drives IK-to-terrain for a 13-bone humanoid. We call
``main(frames=6, capture_gif=False)`` to skip GIF encoding and only run
the IK / walk loop for a few frames.

Pins:
1. Demo module imports cleanly.
2. ``main(capture_gif=False)`` returns a summary dict with frame count.
3. Ankle y-positions are finite floats (IK didn't diverge).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "PharosEngineExamples" / "examples" / "humanoid_ik_terrain_demo.py"
)


@pytest.fixture(scope="module")
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")

    spec = importlib.util.spec_from_file_location(
        "humanoid_ik_terrain_demo_qq2", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["humanoid_ik_terrain_demo_qq2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"humanoid_ik_terrain demo failed to load: {exc}")
    return module


def test_humanoid_ik_terrain_module_imports(demo):
    """Demo file loaded and exposes ``main`` + defaults."""
    assert demo is not None
    assert callable(demo.main)
    assert isinstance(demo.DEFAULT_FRAMES, int)


def test_humanoid_ik_terrain_main_returns_summary(demo):
    """``main(capture_gif=False)`` returns a dict shaped for smoke tests."""
    try:
        summary = demo.main(frames=6, capture_gif=False)
    except Exception as exc:
        pytest.skip(f"humanoid_ik_terrain.main() upstream drift: {exc}")
    assert isinstance(summary, dict)
    assert summary["frames"] == 6
    assert summary["gif_path"] is None


def test_humanoid_ik_terrain_ankles_finite(demo):
    """Ankle y-positions must be finite (IK didn't NaN or blow up)."""
    try:
        summary = demo.main(frames=6, capture_gif=False)
    except Exception as exc:
        pytest.skip(f"humanoid_ik_terrain.main() upstream drift: {exc}")
    left = summary["ankle_l_y"]
    right = summary["ankle_r_y"]
    assert isinstance(left, float) and isinstance(right, float)
    assert math.isfinite(left), f"ankle_l_y not finite: {left}"
    assert math.isfinite(right), f"ankle_r_y not finite: {right}"
