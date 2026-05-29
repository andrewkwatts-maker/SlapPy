"""Tests for ``tools/run_examples.py`` and ``tools/screenshot_grid.py``.

The grid composer is pure-PIL so most assertions are pixel-level checks
on the output PNG.  The run-examples smoke test only exercises two
demos to keep the wall time reasonable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Make ``tools`` importable in the test session.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.screenshot_grid import compose_grid  # noqa: E402
from tools import run_examples  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _solid_image(path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> Path:
    """Write a solid-colour PNG to ``path`` and return it."""
    Image.new("RGBA", size, color).save(path, format="PNG")
    return path


def _cell_region(arr: np.ndarray, row: int, col: int, cell: tuple[int, int]) -> np.ndarray:
    cw, ch = cell
    return arr[row * ch : (row + 1) * ch, col * cw : (col + 1) * cw]


# ── compose_grid tests ──────────────────────────────────────────────────────

def test_compose_grid_with_2_images(tmp_path: Path) -> None:
    a = _solid_image(tmp_path / "a.png", (200, 100), (255, 0, 0, 255))
    b = _solid_image(tmp_path / "b.png", (100, 200), (0, 255, 0, 255))
    out = tmp_path / "grid.png"

    cell = (320, 240)
    result = compose_grid([a, b], out, cell_size=cell)

    assert result == out
    assert out.is_file()
    with Image.open(out) as img:
        # ceil(sqrt(2)) = 2 cols, ceil(2/2) = 1 row → 640×240
        assert img.size == (cell[0] * 2, cell[1] * 1)
        assert img.mode in ("RGBA", "RGB")  # PNG may be saved as RGB by PIL

    # Letterboxed red and green should each leave a coloured band in their
    # cell.  Check the centre row of each cell has the expected dominant hue.
    with Image.open(out) as img:
        arr = np.asarray(img.convert("RGBA"))
    cell_a = _cell_region(arr, 0, 0, cell)
    cell_b = _cell_region(arr, 0, 1, cell)
    # Centre row.
    mid_a = cell_a[cell[1] // 2]
    mid_b = cell_b[cell[1] // 2]
    # Cell A should contain red pixels somewhere along its middle row.
    assert np.any((mid_a[:, 0] > 200) & (mid_a[:, 1] < 50) & (mid_a[:, 2] < 50))
    assert np.any((mid_b[:, 1] > 200) & (mid_b[:, 0] < 50) & (mid_b[:, 2] < 50))


def test_compose_grid_with_labels(tmp_path: Path) -> None:
    a = _solid_image(tmp_path / "a.png", (320, 240), (40, 40, 40, 255))
    b = _solid_image(tmp_path / "b.png", (320, 240), (40, 40, 40, 255))
    out = tmp_path / "labelled.png"

    cell = (320, 240)
    compose_grid([a, b], out, cell_size=cell, labels=["A", "B"])

    with Image.open(out) as img:
        arr = np.asarray(img.convert("RGBA"))

    # The label band sits along the bottom 18 px of each cell.  After the
    # composer paints black + white text it must contain at least one bright
    # pixel (the glyph).  Pure-dark cells without a label would be all black.
    band_h = 18
    for col_idx in (0, 1):
        cell_arr = _cell_region(arr, 0, col_idx, cell)
        label_band = cell_arr[-band_h:]
        # Bright pixels = label text rendered by PIL's default font.
        bright = np.any(label_band[:, :, :3] > 200, axis=-1)
        assert bright.any(), f"label band in cell {col_idx} appears all dark"


def test_compose_grid_with_failed_paths(tmp_path: Path) -> None:
    good = _solid_image(tmp_path / "good.png", (200, 200), (60, 60, 60, 255))
    bad = tmp_path / "definitely_not_there.png"
    out = tmp_path / "with_failed.png"

    cell = (320, 240)
    compose_grid([good, bad], out, cell_size=cell, labels=["good", "bad"])

    with Image.open(out) as img:
        arr = np.asarray(img.convert("RGBA"))
    failed_cell = _cell_region(arr, 0, 1, cell)

    # Excluding the label band, the failed cell must be dominantly red.
    body = failed_cell[: -20]
    r = body[:, :, 0].astype(np.int32)
    g = body[:, :, 1].astype(np.int32)
    b = body[:, :, 2].astype(np.int32)
    red_mask = (r > 150) & (g < 80) & (b < 80)
    assert red_mask.mean() > 0.5, (
        f"failed cell should be mostly red; red fraction = {red_mask.mean():.3f}"
    )


def test_compose_grid_rejects_empty_input(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        compose_grid([], tmp_path / "x.png")


def test_compose_grid_rejects_mismatched_labels(tmp_path: Path) -> None:
    a = _solid_image(tmp_path / "a.png", (100, 100), (128, 128, 128, 255))
    with pytest.raises(ValueError):
        compose_grid([a], tmp_path / "x.png", labels=["A", "B"])


# ── run_examples tests ──────────────────────────────────────────────────────

def test_run_examples_discovers_demos() -> None:
    demos = run_examples.discover_demos()
    assert demos, "expected at least one examples/hello_*.py file"
    assert demos == sorted(demos), "discover_demos must return a sorted list"
    names = {p.name for p in demos}
    assert "hello_rope.py" in names, f"hello_rope.py missing from discovery: {names}"


def test_run_examples_smoke_against_two_demos(tmp_path: Path) -> None:
    rope = REPO_ROOT / "examples" / "hello_rope.py"
    motor = REPO_ROOT / "examples" / "hello_motor.py"
    if not rope.is_file() or not motor.is_file():
        pytest.skip("hello_rope.py / hello_motor.py not present in this checkout")

    grid_path = tmp_path / "smoke_grid.png"
    grid, results = run_examples.run(
        out=grid_path,
        frames=20,         # keep it snappy
        timeout_s=60.0,
        demos=[rope, motor],
        keep_tmp=True,     # preserve PNGs so this test can re-open them
    )

    assert grid == grid_path
    assert grid_path.is_file()
    assert grid_path.stat().st_size > 0
    with Image.open(grid_path) as img:
        # ceil(sqrt(2)) = 2 cols, 1 row.
        assert img.size == (320 * 2, 240 * 1)

    by_name = {r.name: r for r in results}
    assert "hello_rope.py" in by_name and "hello_motor.py" in by_name
    for name, r in by_name.items():
        assert r.ok, f"{name} failed in smoke run: {r.error}"
        assert r.size_bytes > 0
        assert r.png is not None and r.png.exists()
