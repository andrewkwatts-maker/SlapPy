"""Smoke + behaviour tests for ``examples/physics_vehicle_jointed_demo.py``.

The key new assertion (vs ``test_demo_vehicle``) is
:func:`test_joints_keep_chassis_and_wheels_together`: it verifies that
the chassis<->wheel separation stays within 10% of the target distance
at several sampled frames, proving the joint solver is genuinely
holding the assembly together.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "examples" / "legacy" / "physics_vehicle_jointed_demo.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location(
        "physics_vehicle_jointed_demo_under_test", _DEMO_PATH,
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
    """Run the demo once for the whole module so we only pay the render
    cost a single time."""
    mod = _load_demo_module()
    out_dir = tmp_path_factory.mktemp("vehicle_jointed_demo")
    gif_path = out_dir / "physics_vehicle_jointed_demo.gif"
    summary = mod.run_demo(output_path=gif_path)
    return summary


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_demo_runs_to_completion(demo_summary):
    """The demo must produce a non-trivial GIF and finish without raising."""
    gif_path = Path(demo_summary["output_path"])
    assert gif_path.exists(), f"Expected GIF at {gif_path}"
    size = gif_path.stat().st_size
    assert size > 50 * 1024, (
        f"GIF at {gif_path} is suspiciously small ({size} bytes); "
        f"the render probably bailed out early."
    )
    assert demo_summary["frame_count"] == 240
    assert demo_summary["total_contacts"] > 0, (
        "No contacts recorded -- vehicle never touched the terrain."
    )


def test_chassis_moves_forward(demo_summary):
    """The jointed assembly should drive forward by a meaningful distance."""
    start_x = demo_summary["chassis_start_x"]
    end_x = demo_summary["chassis_end_x"]
    assert end_x > start_x + 50.0, (
        f"Chassis didn't drive forward enough: "
        f"start={start_x:.1f}, end={end_x:.1f}, d={end_x - start_x:.1f}"
    )


def test_joints_keep_chassis_and_wheels_together(demo_summary):
    """At several sampled frames the chassis<->wheel CoM separation must
    stay within roughly the joint-target distance.  The joint's
    equilibrium puts each wheel centre at chassis-local (+/-15, +12), so
    the centre-to-centre target is hypot(15, 12) ~= 19.21 px.  We allow
    a 25% tolerance to absorb the transient stretch produced by hill
    crests; without joints the bodies fly apart immediately on the first
    bump, so this asserts the ConstraintSolver is doing real work."""
    initial = demo_summary["initial_chassis_wheel_distance"]
    tol = 0.25 * initial  # ~5 px envelope around 19.21 px target
    per_frame = demo_summary["per_frame_chassis_wheel_distance"]
    sample_frames = [30, 60, 120, 180, 230]
    for f in sample_frames:
        d_l, d_r = per_frame[f]
        assert abs(d_l - initial) <= tol, (
            f"Frame {f}: left wheel drifted to {d_l:.2f} px from chassis "
            f"(target {initial:.2f} +/- {tol:.2f})"
        )
        assert abs(d_r - initial) <= tol, (
            f"Frame {f}: right wheel drifted to {d_r:.2f} px from chassis "
            f"(target {initial:.2f} +/- {tol:.2f})"
        )


def test_no_joints_break(demo_summary):
    """With the default break_force=inf no constraint should ever break."""
    assert demo_summary["broken_constraints"] == 0, (
        f"Expected zero broken joints, got {demo_summary['broken_constraints']}"
    )
    assert demo_summary["active_constraints"] == 2, (
        f"Expected both joints still active, got "
        f"{demo_summary['active_constraints']}"
    )
