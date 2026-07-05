"""IBL prefilter — GGX importance-sampled cubemap mip chain (KK5).

Sibling to :mod:`slappyengine.gpu.ibl`. Provides:

* ``PrefilterConfig`` — knobs for mip count / resolution / sample count.
* ``mip_roughness`` — mip index → roughness in [0, 1].
* ``hammersley_samples`` — quasi-random low-discrepancy 2D sequence.
* ``importance_sample_ggx`` — GGX / Trowbridge-Reitz half-vector sample.
* ``PrefilteredCubemap`` — the CPU-baked mip chain.
* ``prefilter_cubemap`` — reference numpy convolution (slow but correct).
* ``PREFILTER_WGSL`` / ``WGSL_PATH`` — GPU compute-shader payload.

The CPU path is used exclusively for tests and offline bakes; the GPU
path (via the WGSL shader) is what ships in :class:`IBLSystem`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import numpy as np


# ---------------------------------------------------------------------------
# Config + roughness curve
# ---------------------------------------------------------------------------

@dataclass
class PrefilterConfig:
    """Configuration for a GGX prefilter mip chain.

    Attributes
    ----------
    mip_count
        Number of mip levels (0 = mirror, ``mip_count-1`` = fully rough).
    base_resolution
        Face resolution of mip 0 in pixels.  Halved per mip.
    sample_count
        Monte-Carlo importance-sample count per output texel.
    roughness_curve
        Curve mapping mip index → roughness.  ``"linear"`` is the only
        supported value today; kept as a string for future ``"pow2"``,
        ``"gamma"`` variants without a breaking API change.
    """

    mip_count: int = 5
    base_resolution: int = 512
    sample_count: int = 512
    roughness_curve: str = "linear"


def mip_roughness(mip_index: int, mip_count: int) -> float:
    """Return roughness in ``[0, 1]`` for a given mip index.

    Mip 0 is a perfect mirror (roughness 0); the last mip is fully
    rough (roughness 1).  Monotonically increasing.
    """
    if mip_count <= 1:
        return 0.0
    return float(mip_index) / float(mip_count - 1)


# ---------------------------------------------------------------------------
# Sampling — Hammersley + GGX importance sampling
# ---------------------------------------------------------------------------

def _radical_inverse_vdc(bits: np.ndarray) -> np.ndarray:
    """Van der Corput radical inverse, base 2, bit-reversed (uint32 in)."""
    b = bits.astype(np.uint32)
    b = ((b << np.uint32(16)) | (b >> np.uint32(16))).astype(np.uint32)
    b = (((b & np.uint32(0x55555555)) << np.uint32(1)) |
         ((b & np.uint32(0xAAAAAAAA)) >> np.uint32(1))).astype(np.uint32)
    b = (((b & np.uint32(0x33333333)) << np.uint32(2)) |
         ((b & np.uint32(0xCCCCCCCC)) >> np.uint32(2))).astype(np.uint32)
    b = (((b & np.uint32(0x0F0F0F0F)) << np.uint32(4)) |
         ((b & np.uint32(0xF0F0F0F0)) >> np.uint32(4))).astype(np.uint32)
    b = (((b & np.uint32(0x00FF00FF)) << np.uint32(8)) |
         ((b & np.uint32(0xFF00FF00)) >> np.uint32(8))).astype(np.uint32)
    return b.astype(np.float64) * 2.3283064365386963e-10


def hammersley_samples(count: int) -> np.ndarray:
    """Return an ``(N, 2)`` array of Hammersley low-discrepancy samples.

    Each row lies in ``[0, 1) × [0, 1)``.  Column 0 is the linear index
    fraction, column 1 is the Van der Corput radical inverse.
    """
    if count <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    idx = np.arange(count, dtype=np.uint32)
    x = idx.astype(np.float64) / float(count)
    y = _radical_inverse_vdc(idx)
    return np.stack([x, y], axis=1).astype(np.float32)


def _build_tbn(n: np.ndarray) -> np.ndarray:
    """Return ``(3, 3)`` TBN matrix for a single unit normal ``n``."""
    n = n / (np.linalg.norm(n) + 1e-12)
    up = np.array([1.0, 0.0, 0.0]) if abs(n[1]) >= 0.999 else np.array([0.0, 1.0, 0.0])
    t = np.cross(up, n)
    t = t / (np.linalg.norm(t) + 1e-12)
    b = np.cross(n, t)
    return np.stack([t, b, n], axis=1)  # columns = t, b, n


def importance_sample_ggx(u: float, v: float, N: np.ndarray, roughness: float) -> np.ndarray:
    """Return the GGX-sampled world-space half-vector for noise ``(u, v)``.

    Parameters
    ----------
    u, v
        Uniform noise in ``[0, 1)`` (typically two components of a
        Hammersley pair).
    N
        Surface normal in world space (does not need to be normalised;
        function normalises internally).
    roughness
        GGX roughness in ``[0, 1]``.

    Returns
    -------
    np.ndarray
        A unit-length ``(3,)`` direction sampled from the GGX lobe
        aligned with ``N``.
    """
    a = float(roughness) * float(roughness)
    phi = 2.0 * np.pi * float(u)
    denom = max(1.0 + (a * a - 1.0) * float(v), 1e-6)
    cos_theta = np.sqrt((1.0 - float(v)) / denom)
    sin_theta = np.sqrt(max(1.0 - cos_theta * cos_theta, 0.0))
    h_local = np.array([
        np.cos(phi) * sin_theta,
        np.sin(phi) * sin_theta,
        cos_theta,
    ])
    tbn = _build_tbn(np.asarray(N, dtype=np.float64))
    h_world = tbn @ h_local
    return (h_world / (np.linalg.norm(h_world) + 1e-12)).astype(np.float32)


# ---------------------------------------------------------------------------
# CPU prefilter — reference implementation
# ---------------------------------------------------------------------------

@dataclass
class PrefilteredCubemap:
    """CPU-baked GGX prefilter chain.

    Attributes
    ----------
    mip_levels
        One ``(H, W, 4)`` float32 array per mip, halved per level.
    roughness_per_mip
        The roughness value convolved into each mip.
    """

    mip_levels: List[np.ndarray] = field(default_factory=list)
    roughness_per_mip: List[float] = field(default_factory=list)


# Face basis vectors for a unit cube — order: +X, -X, +Y, -Y, +Z, -Z.
# Each entry maps a face-local (u, v) in [-1, 1] to a world direction.
_FACE_AXES = (
    # +X: forward = +X, right = -Z, up = -Y
    (np.array([1, 0, 0]), np.array([0, 0, -1]), np.array([0, -1, 0])),
    # -X: forward = -X, right = +Z, up = -Y
    (np.array([-1, 0, 0]), np.array([0, 0, 1]), np.array([0, -1, 0])),
    # +Y: forward = +Y, right = +X, up = +Z
    (np.array([0, 1, 0]), np.array([1, 0, 0]), np.array([0, 0, 1])),
    # -Y: forward = -Y, right = +X, up = -Z
    (np.array([0, -1, 0]), np.array([1, 0, 0]), np.array([0, 0, -1])),
    # +Z: forward = +Z, right = +X, up = -Y
    (np.array([0, 0, 1]), np.array([1, 0, 0]), np.array([0, -1, 0])),
    # -Z: forward = -Z, right = -X, up = -Y
    (np.array([0, 0, -1]), np.array([-1, 0, 0]), np.array([0, -1, 0])),
)


def _sample_source_cubemap(src: np.ndarray, dir_world: np.ndarray) -> np.ndarray:
    """Nearest-neighbour lookup on a ``(6, H, W, C)`` cubemap.

    ``dir_world`` is a unit vector.
    """
    ax = float(dir_world[0])
    ay = float(dir_world[1])
    az = float(dir_world[2])
    aax, aay, aaz = abs(ax), abs(ay), abs(az)
    if aax >= aay and aax >= aaz:
        face = 0 if ax > 0 else 1
        ma = aax
        uc = -az if ax > 0 else az
        vc = -ay
    elif aay >= aax and aay >= aaz:
        face = 2 if ay > 0 else 3
        ma = aay
        uc = ax
        vc = az if ay > 0 else -az
    else:
        face = 4 if az > 0 else 5
        ma = aaz
        uc = ax if az > 0 else -ax
        vc = -ay
    u = 0.5 * (uc / ma + 1.0)
    v = 0.5 * (vc / ma + 1.0)
    _, H, W, _ = src.shape
    ix = int(np.clip(u * W, 0, W - 1))
    iy = int(np.clip(v * H, 0, H - 1))
    return src[face, iy, ix]


def prefilter_cubemap(source_cubemap: np.ndarray,
                      config: PrefilterConfig) -> PrefilteredCubemap:
    """Reference CPU prefilter — GGX Monte-Carlo per mip / face / texel.

    Parameters
    ----------
    source_cubemap
        ``(6, H, W, C)`` array, C in {3, 4}.  Any HDR range is fine.
    config
        A :class:`PrefilterConfig`.

    Returns
    -------
    PrefilteredCubemap
        6-face mip chain.  Each mip is ``(6, res, res, 4)`` float32
        with alpha forced to 1.
    """
    if source_cubemap.ndim != 4 or source_cubemap.shape[0] != 6:
        raise ValueError("source_cubemap must have shape (6, H, W, C)")

    # Promote to RGBA float32 for internal work.
    src = source_cubemap.astype(np.float32, copy=False)
    if src.shape[-1] == 3:
        alpha = np.ones(src.shape[:3] + (1,), dtype=np.float32)
        src = np.concatenate([src, alpha], axis=-1)

    chain = PrefilteredCubemap()
    samples = hammersley_samples(config.sample_count)

    for mip in range(config.mip_count):
        res = max(1, config.base_resolution >> mip)
        rough = mip_roughness(mip, config.mip_count)
        # Mirror mip: sample the source directly at the reflection direction.
        mip_data = np.zeros((6, res, res, 4), dtype=np.float32)
        for face_idx, (fwd, right, up) in enumerate(_FACE_AXES):
            for py in range(res):
                v = (py + 0.5) / res * 2.0 - 1.0
                for px in range(res):
                    u = (px + 0.5) / res * 2.0 - 1.0
                    n = fwd + right * u + up * v
                    n = n / (np.linalg.norm(n) + 1e-12)
                    if rough <= 1e-4:
                        rgb = _sample_source_cubemap(src, n)[:3]
                        mip_data[face_idx, py, px, :3] = rgb
                        mip_data[face_idx, py, px, 3] = 1.0
                        continue
                    accum = np.zeros(3, dtype=np.float64)
                    total_w = 0.0
                    for s in range(samples.shape[0]):
                        h_world = importance_sample_ggx(
                            float(samples[s, 0]), float(samples[s, 1]),
                            n, rough)
                        l = 2.0 * float(np.dot(n, h_world)) * h_world - n
                        l = l / (np.linalg.norm(l) + 1e-12)
                        n_dot_l = max(float(np.dot(n, l)), 0.0)
                        if n_dot_l > 0.0:
                            accum += _sample_source_cubemap(src, l)[:3] * n_dot_l
                            total_w += n_dot_l
                    if total_w > 0.0:
                        mip_data[face_idx, py, px, :3] = (accum / total_w).astype(np.float32)
                    else:
                        mip_data[face_idx, py, px, :3] = _sample_source_cubemap(src, n)[:3]
                    mip_data[face_idx, py, px, 3] = 1.0
        chain.mip_levels.append(mip_data)
        chain.roughness_per_mip.append(rough)

    return chain


# ---------------------------------------------------------------------------
# WGSL — GPU version
# ---------------------------------------------------------------------------

WGSL_PATH = Path(__file__).with_suffix(".wgsl")
PREFILTER_WGSL: str = WGSL_PATH.read_text(encoding="utf-8") if WGSL_PATH.exists() else ""


__all__ = [
    "PrefilterConfig",
    "mip_roughness",
    "hammersley_samples",
    "importance_sample_ggx",
    "PrefilteredCubemap",
    "prefilter_cubemap",
    "PREFILTER_WGSL",
    "WGSL_PATH",
]
