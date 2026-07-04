"""Tests for the ``examples/hello_prefab.py`` demo (sprint Z4).

These tests pin the demo behaviour end-to-end:

1. ``main()`` runs without exception and returns a summary dict.
2. The library exposes the four expected baked prefabs.
3. Spawning produces the expected 12-entity total
   (crate=1 + ball=1 + chain=5 + windmill=5).
4. The step loop integrates without NaN leakage.
5. Progress prints emit ``[STEP i/frames]`` markers.
6. The final PNG is written to disk (or a stub when PIL is unavailable).
7. Ball prefab spawns at its expected position at t=0.
8. Prefabs land at or above the ground plane (ground clamp works).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_prefab.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_prefab_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_prefab_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: main() runs cleanly end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_main_runs_without_error(demo, tmp_path):
    """``main(frames=20)`` returns a summary and never raises."""
    out_png = tmp_path / "hello_prefab_final.png"
    summary = demo.main(frames=20, out=out_png, live=False, verbose=False)
    assert isinstance(summary, dict)
    assert summary["frames"] == 20
    assert summary["prefabs_spawned"] == 4
    assert Path(summary["png_path"]).exists()


# ────────────────────────────────────────────────────────────────────────────
# Test 2: baked palette exposes the four prefabs the demo expects
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_library_contains_expected_names(demo, tmp_path):
    """After ``build_library`` the four baked palette entries are loaded."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    names = set(lib.list_names())
    assert {"crate", "ball", "chain", "windmill"}.issubset(names)


# ────────────────────────────────────────────────────────────────────────────
# Test 3: entity count matches the 12-body target from the sprint brief
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_entity_count_is_12(demo, tmp_path):
    """crate=1 + ball=1 + chain=5 + windmill=5 = 12 gameplay entities."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, bodies_by_name = demo.build_world(library=lib)
    demo.step_world(world, frames=5, verbose=False)
    summary = demo.summarise(world, bodies_by_name, 5)
    assert summary["total_entities"] == 12
    assert summary["total_entities"] == demo.EXPECTED_ENTITY_COUNT


# ────────────────────────────────────────────────────────────────────────────
# Test 4: no NaN leakage from the solver during a full 120-frame run
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_no_nan_in_step(demo, tmp_path):
    """Every node position + velocity is finite after 120 frames."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, _ = demo.build_world(library=lib)
    demo.step_world(world, frames=120, verbose=False)
    assert np.all(np.isfinite(world.positions))
    assert np.all(np.isfinite(world.velocities))


# ────────────────────────────────────────────────────────────────────────────
# Test 5: progress prints emit [STEP i/frames] markers
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_progress_prints_every_20_steps(demo, tmp_path):
    """Verbose stepping prints ``[STEP 0/120]``, ``[STEP 20/120]``, ..."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, _ = demo.build_world(library=lib)
    buf = io.StringIO()
    with redirect_stdout(buf):
        demo.step_world(world, frames=40, verbose=True, progress_every=20)
    text = buf.getvalue()
    assert "[STEP 0/40]" in text
    assert "[STEP 20/40]" in text
    # Final frame should also print.
    assert "[STEP 39/40]" in text


# ────────────────────────────────────────────────────────────────────────────
# Test 6: final-frame PNG is written to disk
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_writes_final_png(demo, tmp_path):
    """``render_final_png`` writes a file whose size is non-zero."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, bodies_by_name = demo.build_world(library=lib)
    demo.step_world(world, frames=10, verbose=False)
    out_png = tmp_path / "final.png"
    written = demo.render_final_png(world, bodies_by_name, out_png)
    assert written.exists()
    assert written.stat().st_size > 0


# ────────────────────────────────────────────────────────────────────────────
# Test 7: prefabs spawn at the expected positions at t=0
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_ball_spawns_at_expected_position(demo, tmp_path):
    """The ball's node lands at its ``SPAWN_TABLE`` entry within a tight tol."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, bodies_by_name = demo.build_world(library=lib)
    # No stepping yet — positions should exactly match the spawn table.
    ball_body = bodies_by_name["ball"][0]
    ball_idx = ball_body.node_offset
    expected = dict(demo.SPAWN_TABLE)["ball"]
    got = world.positions[ball_idx]
    assert abs(float(got[0]) - expected[0]) < 1e-6
    assert abs(float(got[1]) - expected[1]) < 1e-6


# ────────────────────────────────────────────────────────────────────────────
# Test 8: ground clamp keeps every node at or above y=0
# ────────────────────────────────────────────────────────────────────────────

def test_hello_prefab_ground_clamp_holds(demo, tmp_path):
    """After a long run every node sits at y >= 0 (the ground clamp)."""
    lib = demo.build_library(user_dir=tmp_path / "prefabs")
    world, _, _ = demo.build_world(library=lib)
    demo.step_world(world, frames=120, verbose=False)
    ys = world.positions[:, 1]
    assert float(ys.min()) >= -1e-6, (
        f"ground clamp leaked: min y = {ys.min():.6f}"
    )
