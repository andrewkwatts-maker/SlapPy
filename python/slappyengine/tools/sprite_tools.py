"""Sprite manipulation tools — every function callable from Python or editor buttons.

All functions require only Pillow + numpy; no wgpu context needed.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# generate_tilt_sheet
# ---------------------------------------------------------------------------

def generate_tilt_sheet(
    source_png: str,
    out_dir: str,
    directions: int = 8,
    size: tuple = (128, 128),
) -> list[str]:
    """Generate directional tilt variants using PIL perspective transform.

    Parameters
    ----------
    source_png:
        Path to the source RGBA PNG.
    out_dir:
        Output directory.  Created if it does not exist.
    directions:
        Number of compass directions.  8 → N NE E SE S SW W NW (0° = up, CW).
    size:
        ``(width, height)`` of each output image.

    Returns
    -------
    list[str]
        Absolute paths to the generated files, one per direction.
    """
    from PIL import Image

    src = Image.open(source_png).convert("RGBA").resize(size, Image.LANCZOS)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    direction_names = [
        "N", "NE", "E", "SE", "S", "SW", "W", "NW",
        "N2", "NE2", "E2", "SE2", "S2", "SW2", "W2", "NW2",
    ]

    w, h = size
    cx, cy = w / 2.0, h / 2.0
    tilt_amount = 0.15  # perspective coefficient

    results: list[str] = []
    for i in range(directions):
        angle_deg = i * (360.0 / directions)
        angle_rad = math.radians(angle_deg)

        # Build an 8-tuple perspective transform coefficients
        # We simulate a gentle tilt by computing a projective transform that
        # shifts the top edge in the direction of travel and the bottom away.
        dx = math.sin(angle_rad) * tilt_amount * w
        dy = -math.cos(angle_rad) * tilt_amount * h

        # Original corners: TL, TR, BL, BR
        src_corners = [
            (0.0, 0.0),   # TL
            (w,   0.0),   # TR
            (0.0,  h),    # BL
            (w,     h),   # BR
        ]
        # Destination corners — shift top or bottom based on direction
        dst_corners = [
            (0.0 + dx,   0.0 + dy),   # TL shifted
            (w   + dx,   0.0 + dy),   # TR shifted
            (0.0 - dx,    h - dy),    # BL shifted
            (w   - dx,    h - dy),    # BR shifted
        ]

        coeffs = _find_perspective_coeffs(src_corners, dst_corners)
        tilted = src.transform(size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)

        name = direction_names[i] if i < len(direction_names) else f"dir{i}"
        stem = Path(source_png).stem
        out_file = out_path / f"{stem}_{name}.png"
        tilted.save(str(out_file))
        results.append(str(out_file.resolve()))

    return results


def _find_perspective_coeffs(
    src_points: list[tuple[float, float]],
    dst_points: list[tuple[float, float]],
) -> list[float]:
    """Compute the 8 perspective transform coefficients (PIL format)."""
    import numpy as np

    # Build system of 8 equations
    matrix = []
    for (sx, sy), (dx, dy) in zip(src_points, dst_points):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])

    A = np.array(matrix, dtype=np.float64)
    b = np.array([sx for (sx, sy) in src_points for _ in range(2)], dtype=np.float64)

    # Actually b should be the *source* values
    b2 = []
    for (sx, sy) in src_points:
        b2.append(sx)
        b2.append(sy)

    coeffs, _, _, _ = np.linalg.lstsq(A, np.array(b2), rcond=None)
    return list(coeffs)


# ---------------------------------------------------------------------------
# generate_rotation_strip
# ---------------------------------------------------------------------------

def generate_rotation_strip(
    source_png: str,
    out_png: str,
    frames: int = 16,
    size: tuple = (32, 32),
) -> str:
    """Generate a horizontal strip of *frames* rotated images (0°..360°).

    Parameters
    ----------
    source_png:
        Path to the source RGBA PNG.
    out_png:
        Output file path for the strip.
    frames:
        Number of evenly-spaced rotation frames.
    size:
        ``(width, height)`` of each individual frame.

    Returns
    -------
    str
        Absolute path to the output strip image.
    """
    from PIL import Image

    fw, fh = size
    src = Image.open(source_png).convert("RGBA").resize(size, Image.LANCZOS)
    strip = Image.new("RGBA", (fw * frames, fh), (0, 0, 0, 0))

    for i in range(frames):
        angle = -(i * 360.0 / frames)  # negative → CW rotation in PIL
        rotated = src.rotate(angle, resample=Image.BICUBIC, expand=False)
        strip.paste(rotated, (i * fw, 0), rotated)

    out_file = Path(out_png)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    strip.save(str(out_file))
    return str(out_file.resolve())


# ---------------------------------------------------------------------------
# recolor_sprite
# ---------------------------------------------------------------------------

def recolor_sprite(
    source_png: str,
    out_png: str,
    hue_shift: float,
    saturation_scale: float = 1.0,
) -> str:
    """Shift hue and scale saturation of all non-transparent pixels.

    Parameters
    ----------
    source_png:
        Source RGBA PNG path.
    out_png:
        Output PNG path.
    hue_shift:
        Hue rotation in degrees (0–360).
    saturation_scale:
        Saturation multiplier (1.0 = unchanged, 0.0 = grayscale).

    Returns
    -------
    str
        Absolute path to the output file.
    """
    import colorsys
    import numpy as np
    from PIL import Image

    img = Image.open(source_png).convert("RGBA")
    arr = np.array(img, dtype=np.float32)

    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

    # Process only non-transparent pixels
    mask = a > 0
    rnorm = r[mask] / 255.0
    gnorm = g[mask] / 255.0
    bnorm = b[mask] / 255.0

    shift_norm = hue_shift / 360.0
    new_r = np.zeros_like(rnorm)
    new_g = np.zeros_like(gnorm)
    new_b = np.zeros_like(bnorm)

    for idx in range(len(rnorm)):
        h, s, v = colorsys.rgb_to_hsv(rnorm[idx], gnorm[idx], bnorm[idx])
        h = (h + shift_norm) % 1.0
        s = min(1.0, s * saturation_scale)
        nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
        new_r[idx], new_g[idx], new_b[idx] = nr, ng, nb

    arr[mask, 0] = new_r * 255.0
    arr[mask, 1] = new_g * 255.0
    arr[mask, 2] = new_b * 255.0

    out_img = Image.fromarray(arr.astype(np.uint8), "RGBA")
    out_file = Path(out_png)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(str(out_file))
    return str(out_file.resolve())


# ---------------------------------------------------------------------------
# extract_spritesheet
# ---------------------------------------------------------------------------

def extract_spritesheet(
    source_png: str,
    out_dir: str,
    rows: int,
    cols: int,
    names: list[str] | None = None,
) -> list[str]:
    """Split a grid spritesheet into individual named PNGs.

    Cells are extracted in row-major order (left→right, top→bottom).

    Parameters
    ----------
    source_png:
        Path to the spritesheet PNG.
    out_dir:
        Output directory.  Created if it does not exist.
    rows:
        Number of rows in the spritesheet grid.
    cols:
        Number of columns in the spritesheet grid.
    names:
        Optional list of base names for output files.  If omitted,
        files are named ``{stem}_r{row}_c{col}.png``.

    Returns
    -------
    list[str]
        Absolute paths to the extracted files (``rows × cols`` entries).
    """
    from PIL import Image

    sheet = Image.open(source_png).convert("RGBA")
    sw, sh = sheet.size
    fw = sw // cols
    fh = sh // rows

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    stem = Path(source_png).stem

    results: list[str] = []
    idx = 0
    for row in range(rows):
        for col in range(cols):
            left  = col * fw
            upper = row * fh
            right = left + fw
            lower = upper + fh
            cell = sheet.crop((left, upper, right, lower))

            if names and idx < len(names):
                filename = f"{names[idx]}.png"
            else:
                filename = f"{stem}_r{row}_c{col}.png"

            out_file = out_path / filename
            cell.save(str(out_file))
            results.append(str(out_file.resolve()))
            idx += 1

    return results
