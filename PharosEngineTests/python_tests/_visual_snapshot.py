"""Tiny visual-snapshot helpers for the system-test PNGs.

Each simulation test can call one of these to drop a fresh PNG/GIF
into ``tests/output/<subsystem>/`` so the user can see the current
engine state at a glance. Pure helpers — they don't change test
assertions, just emit visual debris.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_ROOT = _REPO_ROOT / "tests" / "output"


def output_dir(subsystem: str) -> Path:
    """``tests/output/<subsystem>/`` — created on first call."""
    d = _OUTPUT_ROOT / subsystem
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_softbody_state(world, path: Path, *,
                        view_box: tuple[float, float, float, float] | None = None,
                        width: int = 320, height: int = 240) -> Path:
    """Render a softbody world's current state to a PNG via SoftBodyRenderer."""
    from pharos_engine.softbody import SoftBodyRenderConfig, SoftBodyRenderer
    cfg = SoftBodyRenderConfig.from_yaml({"width": width, "height": height})
    if view_box is None:
        n = world.nodes
        if n.count > 0:
            pad = 0.5
            x0 = float(n.pos[:, 0].min()) - pad
            x1 = float(n.pos[:, 0].max()) + pad
            y0 = float(n.pos[:, 1].min()) - pad
            y1 = float(world.config.get("floor_y", 5.0)) + 0.2
            view_box = (x0, y0, x1, y1)
        else:
            view_box = (-2.0, 0.0, 2.0, 5.0)
    arr = SoftBodyRenderer(config=cfg).render(world, view_box=view_box)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode="RGBA").convert("RGB").save(path)
    return path


def save_softbody_sequence(frames: Iterable[np.ndarray], path: Path,
                            fps: int = 30) -> Path:
    """Save a GIF from a list of RGBA frame arrays."""
    pil = [Image.fromarray(a, mode="RGBA").convert("RGB") for a in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    from pharos_engine.media import save_frames
    save_frames(pil, path, fps=fps)
    return path


def save_heatmap(field: np.ndarray, path: Path, *,
                  vmin: float | None = None, vmax: float | None = None,
                  cmap: str = "hot", upscale: int = 4) -> Path:
    """Save a 2D scalar field as a PNG heatmap (hot / cool / grey / fire)."""
    a = np.asarray(field, dtype=np.float32)
    if vmin is None:
        vmin = float(a.min())
    if vmax is None:
        vmax = float(a.max())
    rng = max(vmax - vmin, 1e-9)
    t = np.clip((a - vmin) / rng, 0.0, 1.0)
    if cmap == "hot":
        # hot: black → red → orange → yellow → white
        r = np.clip(t * 3.0, 0.0, 1.0)
        g = np.clip(t * 3.0 - 1.0, 0.0, 1.0)
        b = np.clip(t * 3.0 - 2.0, 0.0, 1.0)
    elif cmap == "cool":
        r = t
        g = 1.0 - t
        b = np.ones_like(t)
    elif cmap == "fire":
        # cold-blue → red → orange → yellow → white
        r = np.clip(t * 2.0, 0.0, 1.0)
        g = np.clip(t * 2.0 - 0.5, 0.0, 1.0)
        b = np.clip(0.5 + (0.5 - t), 0.0, 1.0) * (t < 0.5)
        b = np.where(t < 0.5, 1.0 - t * 2.0, 0.0)
        b += np.clip(t * 2.0 - 1.5, 0.0, 1.0)
    else:  # grey
        r = g = b = t
    rgb = np.stack([r, g, b], axis=2)
    rgb_u8 = (np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    img = Image.fromarray(rgb_u8, mode="RGB")
    if upscale > 1:
        h, w = field.shape
        img = img.resize((w * upscale, h * upscale), Image.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def save_chain_render(chain_positions: np.ndarray, target: tuple[float, float],
                       path: Path, *,
                       width: int = 320, height: int = 240,
                       view_box: tuple[float, float, float, float] | None = None) -> Path:
    """Render an IK chain + target marker as a PNG.

    chain_positions : (N, 2) float, sequence of node positions root→tail.
    target          : world-space target the IK was solving for.
    """
    pos = np.asarray(chain_positions, dtype=np.float32)
    if view_box is None:
        pad = 0.8
        x0 = min(float(pos[:, 0].min()), target[0]) - pad
        x1 = max(float(pos[:, 0].max()), target[0]) + pad
        y0 = min(float(pos[:, 1].min()), target[1]) - pad
        y1 = max(float(pos[:, 1].max()), target[1]) + pad
        view_box = (x0, y0, x1, y1)
    wx0, wy0, wx1, wy1 = view_box

    def w2s(p):
        x = (p[0] - wx0) / max(wx1 - wx0, 1e-6) * width
        y = (p[1] - wy0) / max(wy1 - wy0, 1e-6) * height
        return int(x), int(y)

    img = Image.new("RGB", (width, height), (24, 28, 40))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)

    # Chain segments
    for i in range(len(pos) - 1):
        a = w2s(pos[i])
        b = w2s(pos[i + 1])
        draw.line([a, b], fill=(200, 220, 240), width=3)
    # Chain nodes
    for p in pos:
        cx, cy = w2s(p)
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255))
    # Target marker (cross)
    tx, ty = w2s(target)
    draw.line([(tx - 8, ty), (tx + 8, ty)], fill=(255, 100, 80), width=2)
    draw.line([(tx, ty - 8), (tx, ty + 8)], fill=(255, 100, 80), width=2)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
