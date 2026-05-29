"""Tests for ``slappyengine.tools.sprite_audit`` — the programmatic
counterpart of ``docs/sprite_audit_recipe.md``.

All tests are headless and synthesise their own sprite fixtures so they don't
depend on any downstream game's art tree.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from slappyengine.tools.sprite_audit import (
    SpriteInventoryEntry,
    assess_quality,
    first_hit,
    inventory_sprites,
    make_before_after,
    render_zoom,
    write_inventory_markdown,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _save_rgba(path: Path, arr: np.ndarray) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode="RGBA").save(path)


def _vivid_amber_sprite(size: int = 256, coverage: float = 0.85) -> np.ndarray:
    """A bright amber (#FFBE28) sprite with the requested alpha coverage.

    Pixels are placed in a contiguous block at the top so the coverage is
    exact and deterministic.
    """
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    n_opaque_rows = int(round(size * coverage))
    arr[:n_opaque_rows, :, 0] = 0xFF  # R
    arr[:n_opaque_rows, :, 1] = 0xBE  # G
    arr[:n_opaque_rows, :, 2] = 0x28  # B
    arr[:n_opaque_rows, :, 3] = 255
    return arr


def _washed_grey_sprite(size: int = 64, coverage: float = 0.40) -> np.ndarray:
    """A near-neutral grey sprite with low alpha coverage — the classic
    "chroma key bled into body" failure mode the audit targets.
    """
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    n_opaque_rows = int(round(size * coverage))
    # Near-neutral: max-min = 4, well below the 60 saturation cutoff.
    arr[:n_opaque_rows, :, 0] = 120
    arr[:n_opaque_rows, :, 1] = 118
    arr[:n_opaque_rows, :, 2] = 116
    arr[:n_opaque_rows, :, 3] = 255
    return arr


# ---------------------------------------------------------------------------
# inventory_sprites
# ---------------------------------------------------------------------------

def test_inventory_returns_metrics_for_real_sprites(tmp_path: Path):
    """Walk a directory of real PNG files and assert the returned entries
    have the expected dataclass shape and plausible metrics.

    The engine's own ``slappyengine/testing/baselines/`` is the canonical
    target downstream, but it is added on a parallel branch — so this test
    builds its own baseline directory of vivid amber sprites at varying
    coverages, which gives the same surface guarantees and is independent
    of branch state.
    """
    baselines = tmp_path / "baselines"
    _save_rgba(baselines / "vivid_85.png", _vivid_amber_sprite(128, 0.85))
    _save_rgba(baselines / "vivid_60.png", _vivid_amber_sprite(128, 0.60))
    _save_rgba(baselines / "vivid_30.png", _vivid_amber_sprite(128, 0.30))
    # Non-matching extension — should be ignored.
    (baselines / "notes.txt").write_text("hi", encoding="utf-8")

    entries = inventory_sprites(baselines, ["*.png"])

    assert len(entries) == 3
    for e in entries:
        assert isinstance(e, SpriteInventoryEntry)
        assert e.path.is_file()
        assert e.width == 128 and e.height == 128
        assert e.has_alpha is True
        assert 0.0 <= e.alpha_coverage <= 1.0
        assert e.file_size_bytes > 0
        # Mean RGB on opaque pixels should track our amber palette.
        assert e.mean_rgb[0] > 200
        assert e.mean_rgb[2] < 100

    # Sorted by alpha_coverage descending.
    covs = [e.alpha_coverage for e in entries]
    assert covs == sorted(covs, reverse=True)


def test_write_inventory_markdown_writes_table(tmp_path: Path):
    baselines = tmp_path / "src"
    _save_rgba(baselines / "a.png", _vivid_amber_sprite(64, 0.7))
    _save_rgba(baselines / "b.png", _vivid_amber_sprite(64, 0.5))

    entries = inventory_sprites(baselines, ["*.png"])
    out = tmp_path / "report" / "inventory.md"

    write_inventory_markdown(entries, out)

    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    # Header & one data row per sprite.
    assert "| path |" in text
    assert "alpha_coverage" in text
    assert text.count("| a.png |") + text.count("a.png") >= 1
    assert text.count("| b.png |") + text.count("b.png") >= 1


# ---------------------------------------------------------------------------
# assess_quality
# ---------------------------------------------------------------------------

def test_assess_quality_flags_desaturated_low_coverage(tmp_path: Path):
    p = tmp_path / "broken.png"
    _save_rgba(p, _washed_grey_sprite(size=64, coverage=0.40))
    entry = inventory_sprites(tmp_path, ["*.png"])[0]

    result = assess_quality(entry)

    assert "low_alpha_coverage" in result["flags"]
    assert "desaturated" in result["flags"]
    assert result["recommendation"] == "consider_re_extraction"
    assert 0.0 <= result["score"] < 1.0


def test_assess_quality_passes_a_vivid_sprite(tmp_path: Path):
    p = tmp_path / "good.png"
    _save_rgba(p, _vivid_amber_sprite(size=256, coverage=0.85))
    entry = inventory_sprites(tmp_path, ["*.png"])[0]

    result = assess_quality(entry)

    assert result["flags"] == []
    assert result["recommendation"] == "OK"
    assert result["score"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# first_hit
# ---------------------------------------------------------------------------

def test_first_hit_finds_first_match(tmp_path: Path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_c = tmp_path / "c"
    for d in (dir_a, dir_b, dir_c):
        d.mkdir()

    # "second.png" exists only in dir_b; "third.png" only in dir_c.
    (dir_b / "second.png").write_bytes(b"\x89PNG\r\n")
    (dir_c / "third.png").write_bytes(b"\x89PNG\r\n")

    # Chain: first.png (nowhere) -> second.png (b) -> third.png (c)
    hit = first_hit(
        ["first.png", "second.png", "third.png"],
        [dir_a, dir_b, dir_c],
    )
    assert hit == (dir_b / "second.png")


def test_first_hit_returns_none_when_no_match(tmp_path: Path):
    dir_a = tmp_path / "a"
    dir_a.mkdir()

    hit = first_hit(["missing.png", "also_missing.png"], [dir_a])

    assert hit is None


# ---------------------------------------------------------------------------
# render_zoom
# ---------------------------------------------------------------------------

def test_render_zoom_4x_produces_4x_image(tmp_path: Path):
    from PIL import Image

    src = tmp_path / "in.png"
    _save_rgba(src, _vivid_amber_sprite(size=32, coverage=0.8))

    out = tmp_path / "zoom" / "out.png"
    render_zoom(src, zoom=4, output=out)

    assert out.is_file()
    img = Image.open(out)
    # 32 -> 32*4 = 128 on each axis (no padding around the sprite itself,
    # the doc's "bg_color" forms the backdrop *inside* the sprite bounds).
    assert img.size == (128, 128)


# ---------------------------------------------------------------------------
# make_before_after
# ---------------------------------------------------------------------------

def test_make_before_after_produces_image(tmp_path: Path):
    from PIL import Image

    old = tmp_path / "old.png"
    new = tmp_path / "new.png"
    _save_rgba(old, _washed_grey_sprite(size=32, coverage=0.40))
    _save_rgba(new, _vivid_amber_sprite(size=32, coverage=0.85))

    out = tmp_path / "diff" / "before_after.png"
    make_before_after(old, new, out, zoom=4)

    assert out.is_file()
    img = Image.open(out)
    # Two panels side by side at 32 * 4 = 128 wide + gap + label strips,
    # so the composite must be wider than a single panel.
    assert img.width > 128
    assert img.height >= 128
