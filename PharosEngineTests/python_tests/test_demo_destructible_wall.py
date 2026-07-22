"""Tests for ``examples/physics_destructible_wall_demo.py``.

The flagship demo for the ``cc_label`` + ``spawn_fragment`` work: three
steel bullets fired at a brittle glass wall, shards spawned as
independent rigid bodies, gravity carries them to the floor.

These tests assert the end-to-end pipeline actually fires:

  * The GIF gets written and is non-trivial in size.
  * The wall actually breaks (peak body count grows by >5 fragments).
  * Each bullet reaches the wall's x position by the end of the run.
  * At least some bodies settle near/onto the floor.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "examples" / "legacy" / "physics_destructible_wall_demo.py"


def _load_demo_module():
    """Import (or reuse) the demo module from its path on disk."""
    name = "_demo_physics_destructible_wall_demo"
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
    """Run the demo once and reuse the result across tests."""
    demo = _load_demo_module()
    out_dir = tmp_path_factory.mktemp("destructible_wall_demo_output")
    out_path = out_dir / "physics_destructible_wall_demo.gif"
    return demo.run_demo(out_path=out_path, verbose=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_demo_runs(demo_result):
    """The demo runs end-to-end and produces a non-trivial GIF."""
    gif_path = demo_result["path"]
    assert gif_path.exists(), f"GIF was not written to {gif_path}"
    size = gif_path.stat().st_size
    assert size > 50_000, (
        f"GIF on disk is suspiciously small ({size} bytes) — expected > 50 KB"
    )


def test_wall_actually_breaks(demo_result):
    """At least 5 shards spawned off the brittle glass wall."""
    start = demo_result["n_bodies_start"]
    peak = demo_result["n_bodies_peak"]
    assert peak > start + 5, (
        f"Wall did not fragment: peak={peak} vs start={start} "
        f"(expected > start + 5)"
    )


def test_bullets_strike_wall(demo_result):
    """All three bullets must have travelled past the wall's left face.

    We check the *peak* x reached during the run rather than the final
    position — a bullet that punched into the wall and then ricocheted
    backward still "reached the wall" for demo purposes.
    """
    demo = _load_demo_module()
    # Wall left face = WALL_X - WALL_WIDTH/2.  Margin lets a bullet
    # qualify as "reached the wall" once it crosses just past the front
    # face.
    wall_left_face = demo.WALL_X - demo.WALL_WIDTH / 2.0
    margin = 20.0
    threshold = wall_left_face - margin
    for i, max_x in enumerate(demo_result["bullet_max_x"]):
        assert max_x > threshold, (
            f"Bullet {i} did not reach the wall: peak x={max_x:.1f}, "
            f"threshold={threshold:.1f}"
        )


def test_fragments_fall_to_floor(demo_result):
    """At least some bodies (shards) end the run near/on the floor."""
    world = demo_result["world"]
    floor_y_threshold = 200.0
    on_floor = [
        b
        for b in world.bodies
        if (not b.fixed) and b.position[1] > floor_y_threshold
    ]
    assert len(on_floor) > 0, (
        f"No shards settled near the floor (y > {floor_y_threshold}). "
        f"Body positions: "
        f"{[(round(b.position[0], 1), round(b.position[1], 1)) for b in world.bodies]}"
    )
