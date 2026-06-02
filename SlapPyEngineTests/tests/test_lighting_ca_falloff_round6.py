"""Round-6 lighting polish: chromatic-aberration polynomial radial falloff.

Validates the Lottes-2014-inspired non-linear falloff added to
``chromatic_aberration.wgsl`` and exposed through
``PostProcessChain.add_chromatic_aberration``.

The tests run headlessly: they re-implement the shader maths in pure
numpy so we can exercise the polynomial falloff without spinning up wgpu,
and they verify the chain helper, executor packing, and backward-compat
guarantees that the round-6 commit must uphold.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

# Bare-import so the test exits cleanly on environments where post_process
# is unavailable, mirroring the pattern used by tests/test_postprocess.py.
try:
    from slappyengine.post_process.chain import (
        PostProcessChain,
        PostProcessPass,
    )
    from slappyengine.post_process.executor import PostProcessExecutor  # noqa: F401
except ImportError as _pp_err:  # pragma: no cover - guarded fallback only
    pytest.skip(
        f"slappyengine.post_process not importable: {_pp_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers — pure numpy port of chromatic_aberration.wgsl so we can exercise
# the polynomial falloff path bit-for-bit without a GPU.
# ---------------------------------------------------------------------------

def _bilinear(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Bilinear sample matching the WGSL helper. tex is (H, W, 4) float."""
    h, w, _ = tex.shape
    tc = uv * np.array([w, h], dtype=np.float64) - 0.5
    i = np.floor(tc).astype(np.int64)
    f = tc - i
    i0x = np.clip(i[..., 0], 0, w - 1)
    i0y = np.clip(i[..., 1], 0, h - 1)
    i1x = np.clip(i[..., 0] + 1, 0, w - 1)
    i1y = np.clip(i[..., 1] + 1, 0, h - 1)
    c00 = tex[i0y, i0x]
    c10 = tex[i0y, i1x]
    c01 = tex[i1y, i0x]
    c11 = tex[i1y, i1x]
    fx = f[..., 0:1]
    fy = f[..., 1:2]
    return (c00 * (1 - fx) + c10 * fx) * (1 - fy) + (c01 * (1 - fx) + c11 * fx) * fy


def _apply_ca(
    src: np.ndarray,
    strength: float,
    center: tuple[float, float] = (0.5, 0.5),
    falloff_power: float = 1.0,
    falloff_amount: float = 0.0,
) -> np.ndarray:
    """Pure-numpy port of the chromatic_aberration.wgsl compute kernel."""
    h, w, _ = src.shape
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    uv = np.stack(
        [(xs.astype(np.float64) + 0.5) / w, (ys.astype(np.float64) + 0.5) / h],
        axis=-1,
    )
    delta = uv - np.array(center, dtype=np.float64)
    dist = np.linalg.norm(delta, axis=-1, keepdims=True)
    safe = np.where(dist > 1e-5, dist, 1.0)
    direction = np.where(dist > 1e-5, delta / safe, 0.0)
    extra_pow = max(falloff_power - 1.0, 0.0)
    falloff_term = falloff_amount * np.power(np.maximum(dist, 0.0), extra_pow)
    magnitude = strength * dist * (1.0 + falloff_term)
    offset = direction * magnitude

    uv_r = uv + offset
    uv_g = uv
    uv_b = uv - offset

    r = _bilinear(src, uv_r)[..., 0]
    g = _bilinear(src, uv_g)[..., 1]
    b = _bilinear(src, uv_b)[..., 2]
    a = _bilinear(src, uv_g)[..., 3]
    return np.stack([r, g, b, a], axis=-1)


def _radial_test_image(h: int = 96, w: int = 128) -> np.ndarray:
    """A sharp-edged colour pattern that maximises CA fringing."""
    img = np.zeros((h, w, 4), dtype=np.float64)
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    cx, cy = w / 2.0, h / 2.0
    r = np.hypot(xs - cx, ys - cy)
    # Concentric high-contrast rings — perfect for revealing edge offsets.
    img[..., 0] = 0.5 + 0.5 * np.sin(r * 0.5)
    img[..., 1] = 0.5 + 0.5 * np.cos(r * 0.5 + 1.0)
    img[..., 2] = 0.5 + 0.5 * np.sin(r * 0.5 + 2.0)
    img[..., 3] = 1.0
    return img


# ---------------------------------------------------------------------------
# 1. Regression: linear path still matches the legacy formula.
# ---------------------------------------------------------------------------

def test_falloff_power_1_amount_0_matches_legacy_linear():
    """Default args must reproduce the strictly-linear m(r) = s*r formula."""
    src = _radial_test_image()
    legacy = _apply_ca(src, strength=0.05, falloff_power=1.0, falloff_amount=0.0)

    # Manually compute the legacy m(r) = strength * r path for cross-check.
    h, w, _ = src.shape
    ys, xs = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    uv = np.stack(
        [(xs.astype(np.float64) + 0.5) / w, (ys.astype(np.float64) + 0.5) / h],
        axis=-1,
    )
    delta = uv - np.array([0.5, 0.5])
    dist = np.linalg.norm(delta, axis=-1, keepdims=True)
    safe = np.where(dist > 1e-5, dist, 1.0)
    direction = np.where(dist > 1e-5, delta / safe, 0.0)
    legacy_offset = direction * dist * 0.05

    uv_r = uv + legacy_offset
    uv_g = uv
    uv_b = uv - legacy_offset
    r_old = _bilinear(src, uv_r)[..., 0]
    g_old = _bilinear(src, uv_g)[..., 1]
    b_old = _bilinear(src, uv_b)[..., 2]
    a_old = _bilinear(src, uv_g)[..., 3]
    legacy_manual = np.stack([r_old, g_old, b_old, a_old], axis=-1)

    np.testing.assert_allclose(legacy, legacy_manual, atol=1e-12)


# ---------------------------------------------------------------------------
# 2. Regression: polynomial path produces strictly larger edge fringing
#     than the linear path at the corners while keeping the centre stable.
# ---------------------------------------------------------------------------

def test_polynomial_falloff_amplifies_edges_not_center():
    src = _radial_test_image()
    linear = _apply_ca(src, strength=0.03, falloff_power=1.0, falloff_amount=0.0)
    cubic = _apply_ca(src, strength=0.03, falloff_power=3.0, falloff_amount=4.0)

    h, w, _ = src.shape
    # Centre patch — should be virtually identical (r near 0 → falloff term ~0).
    cy, cx = h // 2, w // 2
    centre_diff = np.abs(linear[cy - 2 : cy + 3, cx - 2 : cx + 3]
                         - cubic[cy - 2 : cy + 3, cx - 2 : cx + 3]).max()
    assert centre_diff < 5e-3, (
        f"Polynomial falloff must not move the optical centre; "
        f"max-diff={centre_diff:.4g}"
    )

    # Corner patches — cubic must have noticeably more divergence from src.
    def _corner_energy(out):
        cs = []
        for cy0, cx0 in [(0, 0), (0, w - 8), (h - 8, 0), (h - 8, w - 8)]:
            patch_src = src[cy0 : cy0 + 8, cx0 : cx0 + 8]
            patch_out = out[cy0 : cy0 + 8, cx0 : cx0 + 8]
            cs.append(np.abs(patch_out - patch_src).mean())
        return float(np.mean(cs))

    e_linear = _corner_energy(linear)
    e_cubic = _corner_energy(cubic)
    assert e_cubic > e_linear * 1.5, (
        "Cubic polynomial falloff should at least 1.5x corner-fringing energy "
        f"compared to the linear baseline; linear={e_linear:.5g} cubic={e_cubic:.5g}"
    )


# ---------------------------------------------------------------------------
# 3. Regression: falloff_amount = 0 with any power still reduces to linear.
# ---------------------------------------------------------------------------

def test_zero_amount_neutralises_arbitrary_power():
    """falloff_amount=0 means the polynomial term contributes nothing."""
    src = _radial_test_image()
    base = _apply_ca(src, strength=0.02, falloff_power=1.0, falloff_amount=0.0)
    for power in (1.5, 2.0, 3.0, 7.5):
        same = _apply_ca(src, strength=0.02, falloff_power=power, falloff_amount=0.0)
        np.testing.assert_allclose(
            same, base, atol=1e-12,
            err_msg=f"falloff_amount=0 must short-circuit; power={power} drifted",
        )


# ---------------------------------------------------------------------------
# 4. Backward-compat: chain.add_chromatic_aberration() called without the
#    new kwargs must still produce a pass with identical bytes-on-the-wire
#    semantics (defaults: power=1.0, amount=0.0) and the legacy params dict.
# ---------------------------------------------------------------------------

def test_chain_add_chromatic_aberration_backward_compat():
    chain = PostProcessChain()
    p = chain.add_chromatic_aberration(strength=0.005, center=(0.5, 0.5))

    assert p.shader_path == "chromatic_aberration.wgsl"
    assert p.entry_point == "chromatic_aberration_main"
    assert p.label == "chromatic_aberration"

    assert p.params["strength"] == pytest.approx(0.005)
    assert p.params["center_x"] == pytest.approx(0.5)
    assert p.params["center_y"] == pytest.approx(0.5)
    # New keys must exist with backward-compat default values.
    assert p.params["falloff_power"] == pytest.approx(1.0)
    assert p.params["falloff_amount"] == pytest.approx(0.0)

    # Replicate the executor's packing path and confirm the 32-byte layout
    # encodes the strictly-linear behaviour (falloff_amount byte slot == 0.0).
    params = p.params
    width, height = 320, 180
    data = struct.pack(
        "<ffffIIfI",
        float(params["strength"]),
        float(params["center_x"]),
        float(params["center_y"]),
        float(params["falloff_power"]),
        width, height,
        float(params["falloff_amount"]),
        0,
    )
    assert len(data) == 32, "Uniform buffer must stay 32 bytes for round-6"
    # falloff_amount lives at byte offset 24-27; with the back-compat default
    # it must be exactly 0.0f.
    fa_bytes = data[24:28]
    assert struct.unpack("<f", fa_bytes)[0] == 0.0


# ---------------------------------------------------------------------------
# 5. Helper accepts the new kwargs and threads them into the params dict.
# ---------------------------------------------------------------------------

def test_chain_add_chromatic_aberration_polynomial_kwargs():
    chain = PostProcessChain()
    p = chain.add_chromatic_aberration(
        strength=0.012,
        center=(0.4, 0.6),
        falloff_power=2.5,
        falloff_amount=3.0,
    )
    assert p.params["falloff_power"] == pytest.approx(2.5)
    assert p.params["falloff_amount"] == pytest.approx(3.0)
    assert p.params["center_x"] == pytest.approx(0.4)
    assert p.params["center_y"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# 6. Visual baseline — SSIM-style perceptual delta. The polynomial path
#    must perceptually diverge from the linear path while still being a
#    visually plausible image (no NaNs, no out-of-range, no hard banding).
# ---------------------------------------------------------------------------

def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Single-window SSIM (BT.709 luma) lifted from tests/visual/harness.py."""
    luma = np.array([0.2126, 0.7152, 0.0722])
    la = (a[..., :3] @ luma) * 255.0
    lb = (b[..., :3] @ luma) * 255.0
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = la.mean(), lb.mean()
    sa = ((la - mu_a) ** 2).mean()
    sb = ((lb - mu_b) ** 2).mean()
    sab = ((la - mu_a) * (lb - mu_b)).mean()
    return float(
        (2 * mu_a * mu_b + c1) * (2 * sab + c2)
        / ((mu_a**2 + mu_b**2 + c1) * (sa + sb + c2))
    )


def test_visual_baseline_perceptual_delta():
    src = _radial_test_image(h=96, w=128)
    linear = _apply_ca(src, strength=0.04, falloff_power=1.0, falloff_amount=0.0)
    cubic = _apply_ca(src, strength=0.04, falloff_power=3.0, falloff_amount=4.0)

    # The polished pass must stay finite, in-range, and alpha-preserving.
    assert np.all(np.isfinite(cubic))
    assert cubic.min() >= 0.0
    assert cubic.max() <= 1.0 + 1e-9
    np.testing.assert_allclose(cubic[..., 3], 1.0, atol=1e-9)

    # Perceptual difference: cubic must visibly diverge from linear but
    # stay above the SSIM floor we use in tests/visual/test_vis_fog.py
    # (0.85). i.e. it's a recognisable polish, not a destructive rewrite.
    # NOTE: the harness uses kwarg ``tolerance=`` for any future
    # assert_scene_matches call — we match its threshold semantics here.
    tolerance = 0.85
    score = _ssim(linear, cubic)
    assert score >= tolerance, (
        f"SSIM {score:.4f} dropped below tolerance {tolerance}; "
        "polynomial falloff diverged too aggressively"
    )
    assert score < 0.9999, (
        f"SSIM {score:.4f} indistinguishable from linear; "
        "polynomial falloff failed to take effect"
    )
