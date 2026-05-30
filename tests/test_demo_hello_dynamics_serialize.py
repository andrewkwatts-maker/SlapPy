"""Tests for examples/hello_dynamics_serialize.py — round-trip save/load."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Make examples/ importable as a top-level package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO_ROOT / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import hello_dynamics_serialize as demo  # type: ignore[import-not-found]  # noqa: E402

from slappyengine.testing import assert_scene_matches


def test_hello_serialize_runs_without_error() -> None:
    summary = demo.main(["--frames", "60"])
    assert summary["stepped_frames_per_phase"] == 60


def test_save_load_round_trip_byte_identical() -> None:
    summary = demo.main(["--frames", "60"])
    # XPBD solvers are deterministic so the post-load step should match the
    # pre-load continuation exactly. Tolerance covers the float-64 edge.
    assert summary["max_position_delta"] < 1e-9


def test_on_disk_size_reasonable() -> None:
    summary = demo.main(["--frames", "30"])
    # 16-node rope: should serialize to roughly 4-8 KB (JSON + base64).
    assert 1000 < summary["on_disk_size_bytes"] < 50_000


def test_no_nan_in_loaded_world() -> None:
    summary = demo.main(["--frames", "60"])
    assert summary["no_nan_a"]
    assert summary["no_nan_b"]


def test_hello_serialize_visual_baseline(tmp_path: Path) -> None:
    out = tmp_path / "hello_dynamics_serialize.png"
    demo.main(["--frames", "60", "--render", "--out", str(out)])
    assert out.exists()
    from PIL import Image
    arr = np.array(Image.open(out).convert("RGBA"))
    scene = type("S", (), {"_image_data": arr})()
    assert_scene_matches(scene, "hello_dynamics_serialize", tolerance=0.05)
