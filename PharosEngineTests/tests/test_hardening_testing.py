"""Input-validation tests for the public ``pharos_engine.testing`` API.

Each test in this file exercises one rejection path with a precise
substring match. Positive paths live in :file:`tests/test_visual_smoke.py`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pharos_engine.testing import (
    assert_scene_matches,
    diff_pngs,
    render_scene_to_png,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def _make_blank_png(tmp_path: Path, name: str = "blank.png") -> Path:
    p = tmp_path / name
    arr = np.zeros((4, 4, 4), dtype=np.uint8)
    arr[..., 3] = 255
    Image.fromarray(arr, mode="RGBA").save(p)
    return p


# ---------------------------------------------------------------------------
# render_scene_to_png
# ---------------------------------------------------------------------------
def test_render_scene_to_png_rejects_non_pathlike_path():
    with pytest.raises(TypeError, match="path"):
        render_scene_to_png(None, 42)  # type: ignore[arg-type]


def test_render_scene_to_png_rejects_zero_width(tmp_path):
    with pytest.raises(ValueError, match="width"):
        render_scene_to_png(None, tmp_path / "x.png", width=0, height=16)


def test_render_scene_to_png_rejects_negative_height(tmp_path):
    with pytest.raises(ValueError, match="height"):
        render_scene_to_png(None, tmp_path / "x.png", width=16, height=-4)


def test_render_scene_to_png_rejects_float_width(tmp_path):
    """``PIL.Image.resize`` would silently cast — refuse at the boundary."""
    with pytest.raises(TypeError, match="width"):
        render_scene_to_png(  # type: ignore[arg-type]
            None, tmp_path / "x.png", width=16.0, height=16,
        )


def test_render_scene_to_png_rejects_negative_frames_to_settle(tmp_path):
    with pytest.raises(ValueError, match="frames_to_settle"):
        render_scene_to_png(
            None, tmp_path / "x.png", width=16, height=16, frames_to_settle=-1,
        )


def test_render_scene_to_png_rejects_bool_frames_to_settle(tmp_path):
    with pytest.raises(TypeError, match="frames_to_settle"):
        render_scene_to_png(  # type: ignore[arg-type]
            None, tmp_path / "x.png", width=16, height=16, frames_to_settle=True,
        )


# ---------------------------------------------------------------------------
# diff_pngs
# ---------------------------------------------------------------------------
def test_diff_pngs_rejects_non_pathlike_actual(tmp_path):
    baseline = _make_blank_png(tmp_path, "b.png")
    with pytest.raises(TypeError, match="actual_path"):
        diff_pngs(12345, baseline, tolerance=0.1)  # type: ignore[arg-type]


def test_diff_pngs_rejects_tolerance_above_one(tmp_path):
    a = _make_blank_png(tmp_path, "a.png")
    b = _make_blank_png(tmp_path, "b.png")
    with pytest.raises(ValueError, match="tolerance"):
        diff_pngs(a, b, tolerance=1.5)


def test_diff_pngs_rejects_negative_tolerance(tmp_path):
    a = _make_blank_png(tmp_path, "a.png")
    b = _make_blank_png(tmp_path, "b.png")
    with pytest.raises(ValueError, match="tolerance"):
        diff_pngs(a, b, tolerance=-0.01)


def test_diff_pngs_rejects_nan_tolerance(tmp_path):
    """NaN < x is always False, so a NaN tolerance would silently pass every
    diff. Refuse at the boundary."""
    a = _make_blank_png(tmp_path, "a.png")
    b = _make_blank_png(tmp_path, "b.png")
    with pytest.raises(ValueError, match="tolerance"):
        diff_pngs(a, b, tolerance=float("nan"))


def test_diff_pngs_rejects_bool_tolerance(tmp_path):
    a = _make_blank_png(tmp_path, "a.png")
    b = _make_blank_png(tmp_path, "b.png")
    with pytest.raises(TypeError, match="tolerance"):
        diff_pngs(a, b, tolerance=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assert_scene_matches — path-traversal protection
# ---------------------------------------------------------------------------
def test_assert_scene_matches_rejects_path_traversal():
    """``../../../etc/passwd`` must not be written outside BASELINES_DIR."""
    with pytest.raises(ValueError, match="baseline_name"):
        assert_scene_matches(None, "../escape", tolerance=0.02)


def test_assert_scene_matches_rejects_path_separator():
    with pytest.raises(ValueError, match="baseline_name"):
        assert_scene_matches(None, "sub/dir", tolerance=0.02)


def test_assert_scene_matches_rejects_empty_name():
    with pytest.raises(ValueError, match="baseline_name"):
        assert_scene_matches(None, "", tolerance=0.02)


def test_assert_scene_matches_rejects_whitespace_in_name():
    with pytest.raises(ValueError, match="baseline_name"):
        assert_scene_matches(None, "name with spaces", tolerance=0.02)


def test_assert_scene_matches_rejects_negative_tolerance():
    with pytest.raises(ValueError, match="tolerance"):
        assert_scene_matches(None, "ok_name", tolerance=-0.5)
