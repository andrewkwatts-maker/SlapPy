"""Compose a grid of screenshots into a single PNG.

Pure-PIL helper used by ``tools/run_examples.py`` and reusable for any
``N``-up grid composition (e.g. visual baselines, README hero shots).

The composition is deterministic given the same inputs — there are no
timestamps, embedded paths, or randomness in the output bytes.

Layout
------
``ceil(sqrt(n))`` columns; rows grow as needed.  Each cell holds:

  * the source image, letterboxed to fit ``cell_size`` while preserving
    aspect ratio (background filled with black),
  * a 1-pixel black border around the cell,
  * an optional white label string drawn at the bottom of the cell.

If a source path does not exist or cannot be opened, the cell is filled
with a solid red colour and the word ``FAILED`` is written across it.
This lets the runner produce a grid even when some demos crashed.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


# ── Cell appearance ──────────────────────────────────────────────────────────
_BG_COLOR: tuple[int, int, int, int] = (0, 0, 0, 255)
_FAIL_COLOR: tuple[int, int, int, int] = (200, 30, 30, 255)
_FAIL_TEXT_COLOR: tuple[int, int, int, int] = (255, 255, 255, 255)
_LABEL_COLOR: tuple[int, int, int, int] = (255, 255, 255, 255)
_BORDER_COLOR: tuple[int, int, int, int] = (0, 0, 0, 255)
_LABEL_BAND_HEIGHT: int = 18
_BORDER_WIDTH: int = 1


def _load_font() -> ImageFont.ImageFont:
    """Return PIL's default bitmap font.

    We deliberately avoid TrueType lookup so the rendered text is
    pixel-deterministic across machines.
    """
    return ImageFont.load_default()


def _fit_image(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Letterbox ``img`` into a ``target``-sized RGBA canvas."""
    tw, th = target
    canvas = Image.new("RGBA", target, _BG_COLOR)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return canvas
    scale = min(tw / iw, th / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    ox = (tw - nw) // 2
    oy = (th - nh) // 2
    canvas.paste(resized, (ox, oy), resized)
    return canvas


def _draw_label(cell: Image.Image, label: str) -> None:
    """Draw a small white label band along the bottom of ``cell``."""
    if not label:
        return
    draw = ImageDraw.Draw(cell)
    font = _load_font()
    cw, ch = cell.size

    # Black band at the bottom for legibility.
    band_top = ch - _LABEL_BAND_HEIGHT
    draw.rectangle([(0, band_top), (cw, ch)], fill=(0, 0, 0, 255))

    # Measure text and centre it.
    try:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except AttributeError:  # pragma: no cover - very old PIL
        tw, th = font.getsize(label)  # type: ignore[attr-defined]
    tx = max(2, (cw - tw) // 2)
    ty = band_top + max(1, (_LABEL_BAND_HEIGHT - th) // 2)
    draw.text((tx, ty), label, fill=_LABEL_COLOR, font=font)


def _render_failed_cell(target: tuple[int, int], label: str | None) -> Image.Image:
    """Solid-red cell with FAILED text for demos that did not produce a PNG."""
    cell = Image.new("RGBA", target, _FAIL_COLOR)
    draw = ImageDraw.Draw(cell)
    font = _load_font()
    text = "FAILED"
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except AttributeError:  # pragma: no cover
        tw, th = font.getsize(text)  # type: ignore[attr-defined]
    cw, ch = target
    tx = max(2, (cw - tw) // 2)
    ty = max(2, (ch - th) // 2 - _LABEL_BAND_HEIGHT // 2)
    draw.text((tx, ty), text, fill=_FAIL_TEXT_COLOR, font=font)
    if label:
        _draw_label(cell, label)
    return cell


def _render_image_cell(
    src: Path, target: tuple[int, int], label: str | None
) -> Image.Image:
    """Letterbox the source image into the cell and optionally label it."""
    with Image.open(src) as img:
        img.load()
        cell = _fit_image(img, target)
    if label:
        _draw_label(cell, label)
    return cell


def _add_border(cell: Image.Image) -> Image.Image:
    """Draw a 1-pixel black border around ``cell`` (in-place style)."""
    draw = ImageDraw.Draw(cell)
    cw, ch = cell.size
    for i in range(_BORDER_WIDTH):
        draw.rectangle(
            [(i, i), (cw - 1 - i, ch - 1 - i)],
            outline=_BORDER_COLOR,
        )
    return cell


def compose_grid(
    image_paths: Sequence[Path],
    output: Path,
    cell_size: tuple[int, int] = (320, 240),
    labels: Sequence[str] | None = None,
) -> Path:
    """Compose ``image_paths`` into a single PNG grid at ``output``.

    Parameters
    ----------
    image_paths
        Iterable of source PNG paths.  Missing or unreadable paths are
        rendered as red FAILED cells.
    output
        Destination PNG path.  Parent directories are created.
    cell_size
        ``(width, height)`` of each cell in pixels.  Defaults to 320×240.
    labels
        Optional per-cell label strings.  When provided the length must
        equal ``len(image_paths)``.

    Returns
    -------
    Path
        The ``output`` path (for convenient chaining).
    """
    paths = [Path(p) for p in image_paths]
    n = len(paths)
    if n == 0:
        raise ValueError("compose_grid requires at least one image path")

    if labels is not None:
        labels = list(labels)
        if len(labels) != n:
            raise ValueError(
                f"labels length {len(labels)} does not match image count {n}"
            )

    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))
    cw, ch = cell_size

    grid = Image.new("RGBA", (cols * cw, rows * ch), _BG_COLOR)

    for idx, src in enumerate(paths):
        label = labels[idx] if labels is not None else None
        if src.exists() and src.is_file():
            try:
                cell = _render_image_cell(src, cell_size, label)
            except Exception:
                cell = _render_failed_cell(cell_size, label)
        else:
            cell = _render_failed_cell(cell_size, label)
        _add_border(cell)
        r, c = divmod(idx, cols)
        grid.paste(cell, (c * cw, r * ch), cell)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    grid.save(out, format="PNG", optimize=True)
    return out
