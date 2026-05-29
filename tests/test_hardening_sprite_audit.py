"""Input-validation tests for ``slappyengine.tools.sprite_audit``.

Each test exercises one rejection path. Positive paths live in
:file:`tests/test_sprite_audit_tool.py`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slappyengine.tools.sprite_audit import (
    SpriteInventoryEntry,
    assess_quality,
    inventory_sprites,
    make_before_after,
    render_zoom,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
def _make_sprite(tmp_path: Path, name: str = "s.png") -> Path:
    p = tmp_path / name
    arr = np.zeros((8, 8, 4), dtype=np.uint8)
    arr[..., :3] = 200
    arr[..., 3] = 255
    Image.fromarray(arr, mode="RGBA").save(p)
    return p


# ---------------------------------------------------------------------------
# inventory_sprites(root, patterns)
# ---------------------------------------------------------------------------
def test_inventory_sprites_rejects_non_pathlike_root():
    with pytest.raises(TypeError, match="root"):
        inventory_sprites(42, ["*.png"])  # type: ignore[arg-type]


def test_inventory_sprites_rejects_string_as_patterns(tmp_path):
    """A bare str would be iterated character-by-character — catch it."""
    with pytest.raises(TypeError, match="patterns"):
        inventory_sprites(tmp_path, "*.png")  # type: ignore[arg-type]


def test_inventory_sprites_rejects_non_string_pattern_element(tmp_path):
    with pytest.raises(TypeError, match="patterns"):
        inventory_sprites(tmp_path, ["*.png", 42])  # type: ignore[arg-type]


def test_inventory_sprites_rejects_tuple_patterns(tmp_path):
    """Tuple isn't list — refuse loudly to preserve type contract."""
    with pytest.raises(TypeError, match="patterns"):
        inventory_sprites(tmp_path, ("*.png",))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_zoom(image_path, zoom, output, bg_color)
# ---------------------------------------------------------------------------
def test_render_zoom_rejects_zero_zoom(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(ValueError, match="zoom"):
        render_zoom(src, 0, tmp_path / "out.png")


def test_render_zoom_rejects_negative_zoom(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(ValueError, match="zoom"):
        render_zoom(src, -2, tmp_path / "out.png")


def test_render_zoom_rejects_float_zoom(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(TypeError, match="zoom"):
        render_zoom(src, 2.5, tmp_path / "out.png")  # type: ignore[arg-type]


def test_render_zoom_rejects_bg_color_wrong_length(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(ValueError, match="bg_color"):
        render_zoom(
            src, 2, tmp_path / "out.png", bg_color=(10, 20, 30),  # type: ignore[arg-type]
        )


def test_render_zoom_rejects_bg_color_out_of_range(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(ValueError, match="bg_color"):
        render_zoom(
            src, 2, tmp_path / "out.png", bg_color=(0, 0, 0, 999),
        )


def test_render_zoom_rejects_bg_color_float_channel(tmp_path):
    src = _make_sprite(tmp_path, "src.png")
    with pytest.raises(TypeError, match="bg_color"):
        render_zoom(
            src, 2, tmp_path / "out.png",
            bg_color=(0.0, 0.0, 0.0, 255.0),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# make_before_after(old_path, new_path, output, zoom)
# ---------------------------------------------------------------------------
def test_make_before_after_rejects_zero_zoom(tmp_path):
    old = _make_sprite(tmp_path, "old.png")
    new = _make_sprite(tmp_path, "new.png")
    with pytest.raises(ValueError, match="zoom"):
        make_before_after(old, new, tmp_path / "out.png", zoom=0)


def test_make_before_after_rejects_non_pathlike_old(tmp_path):
    new = _make_sprite(tmp_path, "new.png")
    with pytest.raises(TypeError, match="old_path"):
        make_before_after(42, new, tmp_path / "out.png")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# assess_quality(entry)
# ---------------------------------------------------------------------------
def test_assess_quality_rejects_bare_dict():
    """Dict-shaped data has the keys but not attrs — refuse loudly."""
    with pytest.raises(TypeError, match="entry"):
        assess_quality(
            {"alpha_coverage": 0.5, "mean_rgb": (1, 2, 3), "width": 64, "height": 64},  # type: ignore[arg-type]
        )


def test_assess_quality_rejects_none():
    with pytest.raises(TypeError, match="entry"):
        assess_quality(None)  # type: ignore[arg-type]


def test_assess_quality_rejects_object_missing_fields():
    class Stub:
        alpha_coverage = 0.5

    with pytest.raises(TypeError, match="entry"):
        assess_quality(Stub())  # type: ignore[arg-type]
