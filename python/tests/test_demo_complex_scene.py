"""Tests for ``examples/physics_complex_scene_demo.py``.

The complex-scene demo combines the Phase C water pool, the lava + ice
boundary-exchange heat conduction, the glass-fracture pipeline, and the
joint solver (PinConstraint between two floating ice blocks) into a
single 240-frame run.  These tests assert each major pipeline actually
fires.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "examples" / "legacy" / "physics_complex_scene_demo.py"


def _load_demo_module():
    """Import (or reuse) the demo module from its path on disk."""
    name = "_demo_physics_complex_scene_demo"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _DEMO_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Cannot locate demo at {_DEMO_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo_result(tmp_path_factory):
    """Run the demo once and reuse the metrics across tests."""
    demo = _load_demo_module()
    out_dir = tmp_path_factory.mktemp("complex_scene_demo_output")
    out_path = out_dir / "physics_complex_scene_demo.gif"
    return demo.run_demo(out_path=out_path, save_gif=True, verbose=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_demo_runs(demo_result):
    """The demo runs end-to-end and writes a non-trivial GIF (> 200 KB)."""
    out = demo_result["output_path"]
    assert out is not None, "demo did not return an output path"
    assert Path(out).exists(), f"expected GIF at {out}"
    size_kb = Path(out).stat().st_size / 1024.0
    assert size_kb > 200.0, (
        f"GIF too small ({size_kb:.1f} KB); expected > 200 KB"
    )
    # Sanity check the frame buffer was actually populated.
    frames = demo_result["frames"]
    assert len(frames) == demo_result["frame_count"]
    assert frames[0].ndim == 3 and frames[0].shape[-1] == 4


def test_glass_shatters(demo_result):
    """At least 3 fragments must have been spawned during the run.

    The steel ball strikes the brittle glass barrier, driving its
    bond field below the fracture threshold; ``cc_label`` finds the
    disjoint shards and ``HullTree.spawn_fragment`` splits them off as
    independent rigid bodies.  Fewer than 3 fragments means the
    fracture pipeline silently regressed.
    """
    spawned = demo_result["fragments_spawned"]
    assert spawned >= 3, (
        f"glass barrier did not shatter enough: only {spawned} fragments "
        f"spawned (expected >= 3)"
    )


def test_water_visibly_moves(demo_result):
    """Peak water |u_y| during the run exceeds 0.5.

    The lava drop landing + the steel ball striking the glass nearby
    both perturb the pool; Phase C's pressure projection propagates
    those impulses through the fluid so cells visibly slosh.
    """
    peak = demo_result["peak_water_uy"]
    assert peak > 0.5, (
        f"water did not visibly slosh: peak |u_y| was {peak:.4f} "
        f"(expected > 0.5)"
    )


def test_lava_cools(demo_result):
    """Lava's max heat must decrease over the run.

    Cross-body :class:`BoundaryExchange` conducts heat out of the lava
    blob into the cooler ice / water it lands on.  If the boundary
    pipeline ever stops firing the lava blob's max heat stays pinned
    at its initial value (12.0 for the ``lava`` material preset).
    """
    start = demo_result["lava_heat_start"]
    minimum = demo_result["lava_heat_min"]
    assert minimum < start, (
        f"lava failed to cool: min heat {minimum:.4f} >= start {start:.4f}. "
        f"BoundaryExchange must not be firing."
    )


def test_no_tunnel_events(demo_result):
    """No body's centre may jump by more than 50 px in a single frame.

    A larger jump is a smoking gun for a body tunnelling through a wall
    or being snapped by a constraint blow-up.  This catches CCD or
    constraint regressions that would otherwise pass the visual eye
    test.
    """
    max_jump = demo_result["max_frame_jump_px"]
    assert max_jump <= 50.0, (
        f"tunnelling detected: max single-frame jump was {max_jump:.2f} px "
        f"(expected <= 50.0 px)"
    )
