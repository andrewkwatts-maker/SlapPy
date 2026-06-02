"""Smoke + behaviour tests for ``examples/physics_vehicle_demo.py``."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader — examples/ isn't on sys.path by default.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "examples" / "legacy" / "physics_vehicle_demo.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location(
        "physics_vehicle_demo_under_test", _DEMO_PATH,
    )
    assert spec is not None and spec.loader is not None, (
        f"Could not load demo at {_DEMO_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo_summary(tmp_path_factory):
    """Run the demo exactly once for the module; share the summary + GIF
    path across tests so we don't pay the multi-second render twice."""
    mod = _load_demo_module()
    out_dir = tmp_path_factory.mktemp("vehicle_demo")
    gif_path = out_dir / "physics_vehicle_demo.gif"
    summary = mod.run_demo(output_path=gif_path)
    return summary


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_demo_runs_to_completion(demo_summary):
    """The demo must produce a non-trivial GIF, register contacts, and
    finish without raising."""
    gif_path = Path(demo_summary["output_path"])
    assert gif_path.exists(), f"Expected GIF at {gif_path}"
    size = gif_path.stat().st_size
    assert size > 50 * 1024, (
        f"GIF at {gif_path} is suspiciously small ({size} bytes); "
        f"the render probably bailed out early."
    )
    assert demo_summary["frame_count"] == 240
    assert demo_summary["total_contacts"] > 0, (
        "No contacts recorded — vehicle never touched the terrain."
    )


def test_chassis_moves_forward(demo_summary):
    """Sprint 1 has no joints, so the wheel/chassis pair fights itself,
    but with an initial +X velocity the chassis must still travel a
    meaningful distance along the terrain."""
    start_x = demo_summary["chassis_start_x"]
    end_x = demo_summary["chassis_end_x"]
    assert end_x > start_x + 50.0, (
        f"Chassis didn't drive forward enough: "
        f"start={start_x:.1f}, end={end_x:.1f}, Δ={end_x - start_x:.1f}"
    )
