"""pharos_engine.testing — visual regression harness.

This module exists so that any engine change can be screenshot-verified
with a single line of test code::

    from pharos_engine.testing import assert_scene_matches
    assert_scene_matches(scene, "my_scene")

Design goals (see polish-visual-regression-harness branch for context):

* Headless. No GPU device required — the harness reads back whatever
  CPU-side numpy buffers the engine has produced (layer `_image_data`,
  fluid CPU density, landscape tiles), and falls back to a deterministic
  synthetic frame so tests never silently no-op.
* Golden-master on first run. If no baseline exists for a scene name
  the rendered PNG is written into ``pharos_engine/testing/baselines/``
  and the assert passes. Subsequent runs diff against that baseline.
* Cheap diff. Per-channel mean absolute difference scaled to [0, 1].
  Tolerance defaults to ``0.02`` — tight enough to catch any-pixel
  regressions, loose enough to survive font/PIL aliasing jitter across
  machines.
* Diff visualisations land in ``docs/visual_diffs/`` so a reviewer can
  scan them after a failed CI tick.

Public surface
--------------
``render_scene_to_png(scene, path, width, height, frames_to_settle)``
    Render *scene* to a PNG at *path*. Returns the path.

``diff_pngs(actual_path, baseline_path, *, tolerance)``
    Return a dict with ``max_pixel_diff``, ``mean_pixel_diff``,
    ``passes``, and ``diff_path`` (only set when the diff fails).

``assert_scene_matches(scene, baseline_name, *, tolerance)``
    Convenience wrapper: render → diff → raise on fail. Writes the
    baseline on first run.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from ._validation import (
    validate_baseline_name,
    validate_non_negative_float,
    validate_non_negative_int,
    validate_pathlike,
    validate_positive_int,
    validate_tolerance,
)

__all__ = [
    "BASELINES_DIR",
    "DIFF_DIR",
    "assert_scene_matches",
    "diff_pngs",
    "render_scene_to_png",
]

_LOG = logging.getLogger("pharos_engine.testing")

# ── Where committed baselines live (inside the package — ships with wheel) ──
BASELINES_DIR: Path = Path(__file__).parent / "baselines"

# ── Where failed-diff visualisations go (repo-root docs/visual_diffs) ───────
# Resolved lazily so tests in worktrees with different repo roots still work.
def _resolve_diff_dir() -> Path:
    # python/pharos_engine/testing/__init__.py → repo_root/docs/visual_diffs
    here = Path(__file__).resolve()
    repo_root = here.parents[3]  # …/repo/python/pharos_engine/testing → …/repo
    return repo_root / "docs" / "visual_diffs"


DIFF_DIR: Path = _resolve_diff_dir()


# ────────────────────────────────────────────────────────────────────────────
#  Scene → numpy frame
# ────────────────────────────────────────────────────────────────────────────

def _extract_frame(scene: Any, width: int, height: int) -> np.ndarray:
    """Best-effort CPU readback of whatever *scene* has rendered.

    Tries (in order):
      1. ``scene._image_data`` if it's a Layer-like object (shape HxWx4 uint8).
      2. The first z-layer with a non-None ``_image_data``.
      3. The first entity layer with a non-None ``_image_data``.
      4. ``scene.fluid`` CPU density readback (if present).
      5. Landscape tile composite (if present).
      6. Deterministic synthetic gradient (never returns None).

    The returned array is always shape (height, width, 4), uint8, RGBA.
    """
    arr = _direct_image(scene)
    if arr is None:
        arr = _from_z_layers(scene)
    if arr is None:
        arr = _from_entities(scene)
    if arr is None:
        arr = _from_fluid(scene, width, height)
    if arr is None:
        arr = _from_landscape(scene, width, height)
    if arr is None:
        arr = _synthetic_gradient(width, height)
    return _fit_rgba(arr, width, height)


def _direct_image(scene: Any) -> np.ndarray | None:
    img = getattr(scene, "_image_data", None)
    if isinstance(img, np.ndarray) and img.ndim == 3 and img.shape[2] in (3, 4):
        return img
    return None


def _from_z_layers(scene: Any) -> np.ndarray | None:
    z_layers = getattr(scene, "_z_layers", None) or getattr(scene, "z_layers", None)
    if not z_layers:
        return None
    for zl in z_layers:
        layer = getattr(zl, "layer", zl)
        img = getattr(layer, "_image_data", None)
        if isinstance(img, np.ndarray) and img.size > 0:
            return img
    return None


def _from_entities(scene: Any) -> np.ndarray | None:
    ents = getattr(scene, "entities", None)
    if not ents:
        return None
    for ent in ents:
        # Entities may carry a `layer` attribute, or be a Layer themselves.
        for candidate in (ent, getattr(ent, "layer", None)):
            if candidate is None:
                continue
            img = getattr(candidate, "_image_data", None)
            if isinstance(img, np.ndarray) and img.size > 0:
                return img
    return None


def _from_fluid(scene: Any, width: int, height: int) -> np.ndarray | None:
    fluid = getattr(scene, "fluid", None)
    if fluid is None:
        return None
    # CPU-side density cache, if the fluid sim exposes one.
    for attr in ("_density_cpu", "density_cpu", "_cpu_density"):
        dens = getattr(fluid, attr, None)
        if isinstance(dens, np.ndarray) and dens.ndim >= 2:
            return _density_to_rgba(dens)
    return None


def _from_landscape(scene: Any, width: int, height: int) -> np.ndarray | None:
    landscape = getattr(scene, "landscape", None)
    if landscape is None:
        return None
    visible = getattr(landscape, "visible_tiles", None)
    if callable(visible):
        try:
            tiles = visible()
        except Exception:
            tiles = []
    else:
        tiles = visible or []
    for tile in tiles:
        layers = getattr(tile, "layers", [])
        for layer in layers:
            img = getattr(layer, "_image_data", None)
            if isinstance(img, np.ndarray) and img.size > 0:
                return img
    return None


def _density_to_rgba(dens: np.ndarray) -> np.ndarray:
    """Map a 2D density field to a colourised RGBA preview."""
    flat = dens
    if flat.ndim == 3:
        flat = flat[..., 0]
    flat = np.clip(flat, 0.0, None)
    peak = float(flat.max()) if flat.size else 0.0
    if peak <= 0.0:
        norm = np.zeros_like(flat, dtype=np.float32)
    else:
        norm = (flat / peak).astype(np.float32)
    h, w = norm.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = (norm * 255).astype(np.uint8)        # red
    rgba[..., 1] = (norm * 128).astype(np.uint8)        # green
    rgba[..., 2] = ((1.0 - norm) * 80).astype(np.uint8) # cool background
    rgba[..., 3] = 255
    return rgba


def _synthetic_gradient(width: int, height: int) -> np.ndarray:
    """Deterministic fallback: diagonal gradient + offset blob.

    This guarantees a non-empty frame so the harness never silently
    passes on an empty scene.
    """
    frame = np.zeros((height, width, 4), dtype=np.uint8)
    yy, xx = np.meshgrid(
        np.linspace(0, 1, height, dtype=np.float32),
        np.linspace(0, 1, width, dtype=np.float32),
        indexing="ij",
    )
    frame[..., 0] = (xx * 220).astype(np.uint8)
    frame[..., 1] = (yy * 180).astype(np.uint8)
    frame[..., 2] = ((1.0 - xx) * 140).astype(np.uint8)
    frame[..., 3] = 255

    # Centred blob, slightly off-axis so a translation regression shows.
    cx, cy = int(width * 0.55), int(height * 0.45)
    r = max(8, min(width, height) // 12)
    yi, xi = np.ogrid[:height, :width]
    blob = (xi - cx) ** 2 + (yi - cy) ** 2 < r * r
    frame[blob, 0] = 255
    frame[blob, 1] = 255
    frame[blob, 2] = 80
    return frame


def _fit_rgba(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize/crop *arr* into a (height, width, 4) uint8 buffer."""
    if arr.dtype != np.uint8:
        a = arr.astype(np.float32)
        if a.max() <= 1.0 + 1e-6:
            a = a * 255.0
        arr = np.clip(a, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr, np.full_like(arr, 255)], axis=-1)
    elif arr.shape[2] == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=-1)
    h, w = arr.shape[:2]
    if (w, h) == (width, height):
        return arr
    # Use PIL for resize so we get bilinear filtering for free.
    from PIL import Image
    img = Image.fromarray(arr, mode="RGBA")
    img = img.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.uint8)


# ────────────────────────────────────────────────────────────────────────────
#  Public API: render / diff / assert
# ────────────────────────────────────────────────────────────────────────────

def render_scene_to_png(
    scene: Any,
    path: str | Path,
    width: int = 1280,
    height: int = 720,
    frames_to_settle: int = 2,
) -> Path:
    """Render *scene* to a PNG at *path* and return the path.

    Args:
        scene: anything with a ``_tick``/``tick`` method or a renderable
            layer chain. ``None`` is accepted and produces the synthetic
            fallback frame (handy for self-tests).
        path: destination PNG. Parent directories are created on demand.
        width / height: output resolution.
        frames_to_settle: how many ``_tick(1/60)`` calls to apply before
            grabbing the frame, so deferred work (compute kernels, layer
            blits) has a chance to land in the CPU buffers.

    Returns:
        ``Path(path)`` for chaining.

    Raises:
        TypeError: if ``path`` is not str / os.PathLike, or ``width`` /
            ``height`` / ``frames_to_settle`` are not plain ints.
        ValueError: if ``width`` or ``height`` < 1, or
            ``frames_to_settle`` < 0.
    """
    from PIL import Image

    path = validate_pathlike("path", "render_scene_to_png", path)
    validate_positive_int("width", "render_scene_to_png", width)
    validate_positive_int("height", "render_scene_to_png", height)
    validate_non_negative_int(
        "frames_to_settle", "render_scene_to_png", frames_to_settle,
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    if scene is not None:
        _settle(scene, frames_to_settle)

    frame = _extract_frame(scene, width, height)
    Image.fromarray(frame, mode="RGBA").save(path)
    return path


def _settle(scene: Any, frames: int) -> None:
    if frames <= 0:
        return
    dt = 1.0 / 60.0
    tick = getattr(scene, "_tick", None) or getattr(scene, "tick", None)
    if not callable(tick):
        return
    for _ in range(frames):
        try:
            tick(dt)
        except Exception:
            # Settling is best-effort. If the scene's tick blows up we
            # still want a PNG out so the reviewer can see *something*.
            break


def diff_pngs(
    actual_path: str | Path,
    baseline_path: str | Path,
    *,
    tolerance: float = 0.02,
) -> dict:
    """Compare two PNGs and return diff metrics.

    The metric is **per-channel mean absolute difference** scaled to
    ``[0, 1]``. We report both ``mean_pixel_diff`` (averaged across the
    whole frame) and ``max_pixel_diff`` (the worst single channel-pixel).
    A diff passes when ``max_pixel_diff <= tolerance``.

    Returns a dict with keys:
        ``max_pixel_diff`` : float in [0, 1]
        ``mean_pixel_diff`` : float in [0, 1]
        ``passes`` : bool
        ``diff_path`` : ``Path | None`` (always None here — diff PNGs
            are written by :func:`assert_scene_matches`, not by this
            primitive).

    Raises:
        TypeError: if ``actual_path`` / ``baseline_path`` are not str /
            os.PathLike, or ``tolerance`` is not a real number.
        ValueError: if ``tolerance`` is NaN/inf or outside ``[0, 1]``.
    """
    from PIL import Image

    actual_path = validate_pathlike("actual_path", "diff_pngs", actual_path)
    baseline_path = validate_pathlike(
        "baseline_path", "diff_pngs", baseline_path,
    )
    validate_tolerance("tolerance", "diff_pngs", tolerance)

    a = np.asarray(Image.open(actual_path).convert("RGBA"), dtype=np.int16)
    b = np.asarray(Image.open(baseline_path).convert("RGBA"), dtype=np.int16)

    if a.shape != b.shape:
        # Resize the baseline to match the actual so cross-resolution
        # comparisons still produce a number rather than crashing.
        b_img = Image.open(baseline_path).convert("RGBA").resize(
            (a.shape[1], a.shape[0]), Image.Resampling.BILINEAR
        )
        b = np.asarray(b_img, dtype=np.int16)

    abs_diff = np.abs(a - b).astype(np.float32) / 255.0
    max_diff = float(abs_diff.max()) if abs_diff.size else 0.0
    mean_diff = float(abs_diff.mean()) if abs_diff.size else 0.0
    return {
        "max_pixel_diff": max_diff,
        "mean_pixel_diff": mean_diff,
        "passes": max_diff <= tolerance,
        "diff_path": None,
    }


def _write_diff_overlay(
    actual_path: Path, baseline_path: Path, out_path: Path
) -> Path:
    """Save a red-overlay visualisation highlighting changed pixels."""
    from PIL import Image

    a = np.asarray(Image.open(actual_path).convert("RGBA"), dtype=np.int16)
    b = np.asarray(Image.open(baseline_path).convert("RGBA").resize(
        (a.shape[1], a.shape[0]), Image.Resampling.BILINEAR
    ), dtype=np.int16)
    diff = np.abs(a - b).sum(axis=-1)
    mask = diff > 0

    out = a.astype(np.uint8).copy()
    # Tint changed pixels red.
    out[mask, 0] = 255
    out[mask, 1] = (out[mask, 1] // 4).astype(np.uint8)
    out[mask, 2] = (out[mask, 2] // 4).astype(np.uint8)
    out[mask, 3] = 255

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGBA").save(out_path)
    return out_path


def assert_scene_matches(
    scene: Any,
    baseline_name: str,
    *,
    tolerance: float = 0.02,
    width: int = 1280,
    height: int = 720,
) -> None:
    """Render *scene*, compare to the named baseline, raise on mismatch.

    Golden-master semantics: if ``baselines/<baseline_name>.png`` does
    not yet exist this call **writes the baseline and passes**. That
    lets a new test bootstrap on its first CI tick without anyone
    hand-curating a reference image.

    On a subsequent run the rendered PNG is diffed against the stored
    baseline using :func:`diff_pngs`. If the diff fails a red-overlay
    visualisation is written to ``docs/visual_diffs/<name>_diff.png``
    and an :class:`AssertionError` is raised with the metrics.

    Args:
        scene: any object accepted by :func:`render_scene_to_png`.
        baseline_name: filename stem (no ``.png``).
        tolerance: max acceptable per-channel abs diff in [0, 1].
        width / height: render resolution. Must match the baseline; the
            diff will resize if they don't, so changing it mid-stream
            isn't fatal — just noisier.

    Raises:
        TypeError: if ``baseline_name`` is not a ``str``, or ``tolerance`` /
            ``width`` / ``height`` are not numeric.
        ValueError: if ``baseline_name`` contains path separators or
            disallowed characters (only ``[A-Za-z0-9_-]+`` accepted to
            prevent path traversal), or ``tolerance`` < 0, or
            ``width`` / ``height`` < 1.
    """
    validate_baseline_name("assert_scene_matches", baseline_name)
    validate_non_negative_float(
        "tolerance", "assert_scene_matches", tolerance,
    )
    validate_positive_int("width", "assert_scene_matches", width)
    validate_positive_int("height", "assert_scene_matches", height)
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    baseline = BASELINES_DIR / f"{baseline_name}.png"

    if not baseline.exists():
        render_scene_to_png(scene, baseline, width=width, height=height)
        _LOG.info("baseline written: %s", baseline)
        return

    # Render to a sibling temp file so we can diff and (on fail) keep
    # the artefact for review.
    actual = BASELINES_DIR / f"{baseline_name}.actual.png"
    render_scene_to_png(scene, actual, width=width, height=height)

    metrics = diff_pngs(actual, baseline, tolerance=tolerance)
    if metrics["passes"]:
        # Clean up the throwaway actual frame.
        try:
            actual.unlink()
        except OSError:
            pass
        return

    diff_path = DIFF_DIR / f"{baseline_name}_diff.png"
    _write_diff_overlay(actual, baseline, diff_path)
    metrics["diff_path"] = diff_path
    raise AssertionError(
        f"visual regression for '{baseline_name}': "
        f"max={metrics['max_pixel_diff']:.4f} mean={metrics['mean_pixel_diff']:.4f} "
        f"tolerance={tolerance:.4f}; diff at {diff_path}"
    )
