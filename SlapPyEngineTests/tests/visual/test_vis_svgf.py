"""Visual test: SVGF denoiser — PSNR/variance reduction over noisy GI input.

Builds a deterministic reference irradiance image (smooth gradient over a
sphere on a plane), perturbs it with Poisson-style noise as a stand-in for a
ReSTIR draw, runs ``SVGFDenoiser.denoise_numpy`` for several temporal frames,
and asserts PSNR > floor and variance reduction > floor. Saves side-by-side
PNG output.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slappyengine.gi.svgf import SVGFDenoiser
from tests.visual.harness import make_test_output_dir

TEST_NAME = "svgf"
W, H = 256, 192
N_FRAMES = 8
SEED = 1234

PSNR_FLOOR_DB = 18.0
VAR_REDUCTION_FLOOR = 0.50


def _reference_scene():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy, r = W * 0.5, H * 0.5, min(W, H) * 0.3
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    sphere = np.clip(1.0 - d / r, 0.0, 1.0)
    z = np.sqrt(np.maximum(0.0, 1.0 - (np.clip(d / r, 0.0, 1.0)) ** 2))
    nx = (xx - cx) / np.maximum(r, 1.0) * sphere
    ny = (yy - cy) / np.maximum(r, 1.0) * sphere
    nz = z * sphere + (1.0 - sphere)
    norm = np.stack([nx, ny, nz], axis=-1)
    n_len = np.linalg.norm(norm, axis=-1, keepdims=True) + 1e-6
    normal = norm / n_len
    depth = 10.0 - sphere * 2.0
    L = np.array([0.4, -0.6, 0.7], dtype=np.float32)
    L /= np.linalg.norm(L)
    ndotl = np.clip((normal * L).sum(-1), 0.0, 1.0)
    bg = 0.15 + 0.05 * (yy / H)
    irradiance = sphere * (0.2 + 0.8 * ndotl) + (1.0 - sphere) * bg
    color = np.stack([
        irradiance * 1.0,
        irradiance * 0.85,
        irradiance * 0.7,
    ], axis=-1).astype(np.float32)
    return color, normal.astype(np.float32), depth.astype(np.float32)


def _add_noise(rng: np.random.Generator, color: np.ndarray, sigma: float) -> np.ndarray:
    noise = rng.normal(0.0, sigma, color.shape).astype(np.float32)
    return np.clip(color + noise, 0.0, 4.0)


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a - b) ** 2))
    if mse <= 1e-10:
        return 99.0
    peak = float(np.max(b)) if np.max(b) > 0 else 1.0
    return 10.0 * np.log10((peak ** 2) / mse)


def _to_u8(img: np.ndarray) -> np.ndarray:
    return np.clip(img * 255.0, 0.0, 255.0).astype(np.uint8)


def test_svgf_denoises_noisy_gi():
    out_dir = make_test_output_dir(TEST_NAME)
    ref_color, normal, depth = _reference_scene()
    rng = np.random.default_rng(SEED)
    den = SVGFDenoiser(W, H)
    den.reset_history()

    noisy_last = None
    denoised_last = None
    for _ in range(N_FRAMES):
        noisy = _add_noise(rng, ref_color, sigma=0.18)
        denoised = den.denoise_numpy(noisy, normal, depth)
        noisy_last = noisy
        denoised_last = denoised

    psnr_noisy = _psnr(noisy_last, ref_color)
    psnr_denoised = _psnr(denoised_last, ref_color)
    assert psnr_denoised > psnr_noisy, (
        f"SVGF made image worse: noisy={psnr_noisy:.2f}dB denoised={psnr_denoised:.2f}dB"
    )
    assert psnr_denoised > PSNR_FLOOR_DB, (
        f"denoised PSNR {psnr_denoised:.2f}dB below floor {PSNR_FLOOR_DB}dB"
    )

    var_noisy = float(np.var(noisy_last - ref_color))
    var_denoised = float(np.var(denoised_last - ref_color))
    reduction = 1.0 - var_denoised / max(var_noisy, 1e-10)
    assert reduction > VAR_REDUCTION_FLOOR, (
        f"variance reduction {reduction:.2%} below floor {VAR_REDUCTION_FLOOR:.0%}"
    )

    side = np.concatenate([_to_u8(noisy_last), _to_u8(denoised_last), _to_u8(ref_color)], axis=1)
    Image.fromarray(side, mode="RGB").save(out_dir / "svgf_noisy_denoised_ref.png")
    Image.fromarray(_to_u8(noisy_last), mode="RGB").save(out_dir / "noisy.png")
    Image.fromarray(_to_u8(denoised_last), mode="RGB").save(out_dir / "denoised.png")
    Image.fromarray(_to_u8(ref_color), mode="RGB").save(out_dir / "reference.png")
    (out_dir / "metrics.txt").write_text(
        f"psnr_noisy_db={psnr_noisy:.3f}\n"
        f"psnr_denoised_db={psnr_denoised:.3f}\n"
        f"variance_reduction={reduction:.4f}\n",
        encoding="utf-8",
    )


def test_svgf_history_reset_clears_temporal_state():
    den = SVGFDenoiser(W, H)
    color, normal, depth = _reference_scene()
    rng = np.random.default_rng(SEED)
    for _ in range(3):
        den.denoise_numpy(_add_noise(rng, color, 0.1), normal, depth)
    assert den._cpu_history is not None
    den.reset_history()
    assert den._cpu_history is None


def test_svgf_singleton_frame_does_not_explode():
    den = SVGFDenoiser(W, H)
    color, normal, depth = _reference_scene()
    rng = np.random.default_rng(SEED)
    out = den.denoise_numpy(_add_noise(rng, color, 0.2), normal, depth)
    assert out.shape == color.shape
    assert np.isfinite(out).all()
    assert float(out.mean()) > 0.0
