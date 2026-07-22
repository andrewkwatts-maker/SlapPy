"""Texture generation and manipulation tools.

All functions require only Pillow + numpy; no wgpu context needed.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import PIL.Image


# ---------------------------------------------------------------------------
# generate_noise_texture
# ---------------------------------------------------------------------------

def generate_noise_texture(
    mode: str = "fbm",
    width: int = 512,
    height: int = 512,
    octaves: int = 4,
    seed: int = 0,
) -> "PIL.Image.Image":
    """Generate a noise texture using FBM or Worley noise.

    Parameters
    ----------
    mode:
        ``"fbm"`` for fractional Brownian motion (Perlin-like) or
        ``"worley"`` for cellular / Worley noise.
    width, height:
        Output image dimensions.
    octaves:
        Number of noise octaves (FBM only).
    seed:
        Random seed for reproducibility.

    Returns
    -------
    PIL.Image.Image
        Greyscale ``"L"`` mode image.
    """
    import numpy as np
    from PIL import Image

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    if mode == "fbm":
        data = _fbm_noise(width, height, octaves, np_rng)
    elif mode == "worley":
        data = _worley_noise(width, height, seed=seed)
    else:
        raise ValueError(f"Unknown noise mode {mode!r}. Use 'fbm' or 'worley'.")

    # Normalise to 0..255
    lo, hi = data.min(), data.max()
    if hi > lo:
        data = (data - lo) / (hi - lo)
    else:
        data = np.zeros_like(data)

    pixels = (data * 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="L")


def _fbm_noise(
    width: int,
    height: int,
    octaves: int,
    rng,
) -> "np.ndarray":
    """Fractional Brownian Motion using summed sinusoidal noise."""
    import numpy as np

    xs = np.linspace(0, 1, width, endpoint=False)
    ys = np.linspace(0, 1, height, endpoint=False)
    X, Y = np.meshgrid(xs, ys)
    result = np.zeros((height, width), dtype=np.float64)

    amplitude = 1.0
    frequency = 1.0
    total_amplitude = 0.0

    for _ in range(octaves):
        # Random phase offsets per octave
        phase_x = rng.random() * 2 * math.pi
        phase_y = rng.random() * 2 * math.pi
        angle = rng.random() * 2 * math.pi

        # Rotated coordinates for more variation
        Xr = X * math.cos(angle) - Y * math.sin(angle)
        Yr = X * math.sin(angle) + Y * math.cos(angle)

        result += amplitude * (
            np.sin(2 * math.pi * frequency * Xr + phase_x)
            * np.sin(2 * math.pi * frequency * Yr + phase_y)
        )
        total_amplitude += amplitude
        amplitude *= 0.5
        frequency *= 2.0

    return result / total_amplitude


def _worley_noise(width: int, height: int, seed: int = 0) -> "np.ndarray":
    """Worley (cellular) noise using random feature points."""
    import numpy as np

    rng = np.random.default_rng(seed)
    n_points = max(16, (width * height) // 2048)

    # Random feature points in [0, 1]
    pts = rng.random((n_points, 2))

    xs = np.linspace(0, 1, width, endpoint=False)
    ys = np.linspace(0, 1, height, endpoint=False)
    X, Y = np.meshgrid(xs, ys)
    coords = np.stack([X.ravel(), Y.ravel()], axis=1)  # (W*H, 2)

    # For each pixel find distance to nearest feature point
    min_dist = np.full(width * height, np.inf)
    for pt in pts:
        diff = coords - pt
        dist = np.sqrt((diff ** 2).sum(axis=1))
        np.minimum(min_dist, dist, out=min_dist)

    return min_dist.reshape(height, width)


# ---------------------------------------------------------------------------
# paint_decal
# ---------------------------------------------------------------------------

def paint_decal(
    target_png: str,
    decal_png: str,
    pos: tuple,
    radius: float,
    rotation: float,
    out_png: str,
) -> str:
    """Alpha-composite a decal onto a target image at *pos* with *rotation*.

    Parameters
    ----------
    target_png:
        Path to the base RGBA image.
    decal_png:
        Path to the decal RGBA image.
    pos:
        ``(x, y)`` centre position in target image pixels.
    radius:
        Scale the decal so its larger dimension fits within a circle of
        this pixel radius.
    rotation:
        Rotation of the decal in degrees (CCW).
    out_png:
        Output file path.

    Returns
    -------
    str
        Absolute path to the output file.
    """
    from PIL import Image

    target = Image.open(target_png).convert("RGBA")
    decal  = Image.open(decal_png).convert("RGBA")

    # Scale decal to fit within radius
    dw, dh = decal.size
    scale = (radius * 2.0) / max(dw, dh)
    new_w = max(1, int(dw * scale))
    new_h = max(1, int(dh * scale))
    decal = decal.resize((new_w, new_h), Image.LANCZOS)

    # Rotate
    decal = decal.rotate(rotation, resample=Image.BICUBIC, expand=True)

    # Paste at pos
    paste_x = int(pos[0] - decal.width  / 2)
    paste_y = int(pos[1] - decal.height / 2)
    target.paste(decal, (paste_x, paste_y), decal)

    out_file = Path(out_png)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    target.save(str(out_file))
    return str(out_file.resolve())


# ---------------------------------------------------------------------------
# generate_gradient
# ---------------------------------------------------------------------------

def generate_gradient(
    colors: list[tuple],
    width: int,
    height: int,
    direction: str = "horizontal",
) -> "PIL.Image.Image":
    """Generate a gradient image blending through *colors*.

    Parameters
    ----------
    colors:
        List of RGB or RGBA tuples.  At least two required.
    width, height:
        Output image dimensions.
    direction:
        ``"horizontal"`` (left→right) or ``"vertical"`` (top→bottom).

    Returns
    -------
    PIL.Image.Image
        RGBA gradient image.
    """
    import numpy as np
    from PIL import Image

    if len(colors) < 2:
        raise ValueError("At least two colors are required for a gradient.")

    # Normalise all colors to 4-channel float
    def _rgba(c):
        c = tuple(c)
        if len(c) == 3:
            c = c + (255,)
        return tuple(float(x) for x in c[:4])

    colors_f = [_rgba(c) for c in colors]
    n = len(colors_f) - 1  # number of segments
    length = width if direction == "horizontal" else height

    pixels = np.zeros((height, width, 4), dtype=np.float32)

    for i in range(length):
        t = i / max(length - 1, 1)              # 0..1 across full gradient
        seg = min(int(t * n), n - 1)            # which segment
        seg_t = t * n - seg                     # 0..1 within segment
        c0 = colors_f[seg]
        c1 = colors_f[seg + 1]
        blended = tuple(c0[ch] + (c1[ch] - c0[ch]) * seg_t for ch in range(4))

        if direction == "horizontal":
            pixels[:, i, :] = blended
        else:
            pixels[i, :, :] = blended

    return Image.fromarray(pixels.astype(np.uint8), "RGBA")
