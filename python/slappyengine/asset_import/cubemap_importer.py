"""Cubemap importer — 6-PNG directory or ``.cubemap.yaml`` manifest (KK4).

Sprint 11 of the Nova3D parity plan. Bridges HH5's asset-import
convention with KK4's :class:`slappyengine.render.skybox.CubemapData`.

Two layouts are supported:

1. **Directory layout** — pass a directory that contains six PNG files
   named ``posx.png``, ``negx.png``, ``posy.png``, ``negy.png``,
   ``posz.png``, ``negz.png``. Case-insensitive.

2. **YAML manifest** — pass a path to a ``.cubemap.yaml`` file whose
   contents look like::

       posx: sky_right.png
       negx: sky_left.png
       posy: sky_top.png
       negy: sky_bottom.png
       posz: sky_front.png
       negz: sky_back.png

   Relative paths are resolved against the manifest's directory.

An HDR path via :func:`import_hdr_cubemap` is soft-imported through
``imageio`` when available and otherwise falls back to a procedural
gradient sky so downstream code never crashes.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

_LOG = logging.getLogger(__name__)

from ..render.skybox import (
    ALL_FACES,
    CubeFace,
    CubemapData,
    procedural_gradient_sky,
)
from .texture_importer import _import_pil


FACE_KEYS: tuple[str, ...] = ("posx", "negx", "posy", "negy", "posz", "negz")
_KEY_TO_FACE: dict[str, CubeFace] = {
    "posx": CubeFace.POSX,
    "negx": CubeFace.NEGX,
    "posy": CubeFace.POSY,
    "negy": CubeFace.NEGY,
    "posz": CubeFace.POSZ,
    "negz": CubeFace.NEGZ,
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _load_face_pixels(path: Path) -> np.ndarray:
    """Load a single face PNG through PIL, return (H, W, 4) uint8."""
    Image = _import_pil()
    img = Image.open(str(path))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"{path.name}: expected RGBA image, got shape {arr.shape}")
    return arr


def _resolve_face_files(base_dir: Path, mapping: dict[str, str | Path]) -> dict[CubeFace, Path]:
    resolved: dict[CubeFace, Path] = {}
    for key in FACE_KEYS:
        if key not in mapping:
            raise ValueError(
                f"Cubemap manifest missing key {key!r}; expected all of {FACE_KEYS}"
            )
        rel = Path(str(mapping[key]))
        candidate = rel if rel.is_absolute() else (base_dir / rel)
        if not candidate.exists():
            raise FileNotFoundError(f"Cubemap face file not found: {candidate}")
        resolved[_KEY_TO_FACE[key]] = candidate
    return resolved


def _resolve_directory(dir_path: Path) -> dict[CubeFace, Path]:
    """Case-insensitive scan for posx.png … negz.png in a directory."""
    # Build a lookup of lower(stem) -> Path for PNGs in the dir.
    stems: dict[str, Path] = {}
    for entry in dir_path.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".png":
            stems[entry.stem.lower()] = entry
    resolved: dict[CubeFace, Path] = {}
    for key in FACE_KEYS:
        if key not in stems:
            raise FileNotFoundError(
                f"Cubemap directory {dir_path!s} missing {key}.png"
            )
        resolved[_KEY_TO_FACE[key]] = stems[key]
    return resolved


def _pack_faces(face_files: dict[CubeFace, Path]) -> CubemapData:
    face_arrays: dict[CubeFace, np.ndarray] = {}
    resolution: int | None = None
    for face in ALL_FACES:
        pixels = _load_face_pixels(face_files[face])
        h, w = pixels.shape[:2]
        if h != w:
            raise ValueError(
                f"Cubemap face {face.name} must be square, got {w}x{h}"
            )
        if resolution is None:
            resolution = h
        elif h != resolution:
            raise ValueError(
                f"Cubemap face {face.name} resolution {h} doesn't match {resolution}"
            )
        face_arrays[face] = pixels
    assert resolution is not None
    return CubemapData(faces=face_arrays, resolution=resolution, format="rgba8")


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def import_cubemap(dir_or_yaml_path: str | Path) -> CubemapData:
    """Import a cubemap from a directory or a ``.cubemap.yaml`` manifest.

    Parameters
    ----------
    dir_or_yaml_path
        Either a directory containing six PNGs (``posx.png``,
        ``negx.png``, …, ``negz.png``) *or* a file ending in
        ``.cubemap.yaml`` that maps face keys to relative PNG paths.

    Returns
    -------
    CubemapData
        Fully populated cubemap with six RGBA8 faces.

    Raises
    ------
    FileNotFoundError
        If the directory / manifest — or any face file it references —
        does not exist.
    ValueError
        If any face is missing, non-square, or a different resolution
        than the others.
    """
    if not isinstance(dir_or_yaml_path, (str, Path)):
        raise TypeError(
            "import_cubemap: dir_or_yaml_path must be str or Path; "
            f"got {type(dir_or_yaml_path).__name__}"
        )
    if isinstance(dir_or_yaml_path, str) and not dir_or_yaml_path:
        raise ValueError("import_cubemap: dir_or_yaml_path must be non-empty")
    path = Path(dir_or_yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Cubemap source not found: {path}")

    if path.is_dir():
        face_files = _resolve_directory(path)
        return _pack_faces(face_files)

    # File path — accept ``.cubemap.yaml`` or any ``.yaml`` file whose
    # contents contain the six face keys.
    if not path.suffix.lower() in (".yaml", ".yml"):
        raise ValueError(
            f"Cubemap manifest must be a directory or .cubemap.yaml; got {path.name}"
        )

    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "PyYAML is required to load .cubemap.yaml manifests. "
            "Install with: pip install pyyaml"
        ) from e

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must be a YAML mapping, got {type(raw).__name__}")

    # Normalise keys to lower-case.
    mapping = {str(k).lower(): v for k, v in raw.items()}
    face_files = _resolve_face_files(path.parent, mapping)
    return _pack_faces(face_files)


def import_hdr_cubemap(path: str | Path) -> CubemapData:
    """Soft-import an ``.hdr`` equirectangular / cube image.

    ``imageio`` is soft-imported; when missing (or when the file can't be
    parsed) we fall back to a :func:`procedural_gradient_sky` so scenes
    keep rendering.
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(
            f"import_hdr_cubemap: path must be str or Path; got {type(path).__name__}"
        )
    if isinstance(path, str) and not path:
        raise ValueError("import_hdr_cubemap: path must be non-empty")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"HDR cubemap source not found: {p}")

    try:
        import imageio.v3 as iio  # noqa: PLC0415
    except ImportError:
        return procedural_gradient_sky()

    try:
        data = iio.imread(str(p))
    except Exception:  # pragma: no cover - defensive
        return procedural_gradient_sky()

    arr = np.asarray(data)
    if arr.ndim < 2:
        return procedural_gradient_sky()
    # Normalise to (H, W, 4) uint8 by clipping to [0, 1] and scaling.
    if arr.dtype in (np.float16, np.float32, np.float64):
        # Simple Reinhard tonemap so the fallback preview is viewable.
        arr = arr / (1.0 + arr)
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0 + 0.5).astype(np.uint8)
    else:
        arr = arr.astype(np.uint8)

    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.shape[2] == 3:
        arr = np.concatenate(
            [arr, np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)], axis=-1
        )

    # Crop to a square that fits, then replicate to all six faces as a
    # simple fallback (real equirect->cube unwrap is out of scope for
    # KK4 — that will land in a follow-up sprint).
    h, w = arr.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    face = arr[y0:y0 + side, x0:x0 + side]
    faces = {f: face.copy() for f in ALL_FACES}
    return CubemapData(faces=faces, resolution=side, format="rgba8")


__all__ = [
    "FACE_KEYS",
    "import_cubemap",
    "import_hdr_cubemap",
]
