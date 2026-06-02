"""Tests for slappyengine.physics.post_process."""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.post_process import (
    BloomPass,
    PostProcessChain,
    TonemapPass,
    default_post_process_chain,
)


# ---------------------------------------------------------------------------
# Tonemap
# ---------------------------------------------------------------------------


def test_tonemap_compresses_overbright():
    # Build a "would-clip" frame.  The input is already uint8 (max 255), but
    # we set the channel near the top so that after ACES the value falls
    # into a smooth shoulder rather than the hard 255 ceiling.
    frame = np.zeros((4, 4, 4), dtype=np.uint8)
    frame[..., 0] = 255  # red at the top of the uint8 range
    frame[..., 3] = 255

    # Using exposure > 1 simulates an "overbright" HDR input being mapped
    # into LDR via the ACES curve; the shoulder should keep the output
    # below the ceiling but still bright.
    out = TonemapPass(exposure=1.6).apply(frame)

    r = out[..., 0]
    # Smooth shoulder: not clipped to 255, but still in the bright range.
    assert (r < 255).all(), "ACES should compress overbright instead of clipping"
    assert (r > 200).all(), "Overbright red should still tonemap to a bright value"
    assert (r >= 210).all() and (r <= 245).all()


def test_tonemap_zero_input_zero_output():
    frame = np.zeros((8, 8, 4), dtype=np.uint8)
    frame[..., 3] = 255  # opaque black
    out = TonemapPass(exposure=1.0).apply(frame)
    assert (out[..., :3] == 0).all()


def test_tonemap_alpha_unchanged():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, size=(6, 7, 4), dtype=np.uint8)
    out = TonemapPass(exposure=1.2).apply(frame)
    assert np.array_equal(out[..., 3], frame[..., 3])


# ---------------------------------------------------------------------------
# Bloom
# ---------------------------------------------------------------------------


def test_bloom_no_effect_below_threshold():
    # Uniform dim frame well below threshold.
    frame = np.full((16, 16, 4), 50, dtype=np.uint8)
    frame[..., 3] = 255
    bloom = BloomPass(threshold=200.0, intensity=0.8, radius_px=4.0)
    out = bloom.apply(frame)
    # No bright pixels => no bloom contribution.
    assert np.array_equal(out[..., :3], frame[..., :3])
    assert np.array_equal(out[..., 3], frame[..., 3])


def test_bloom_brightens_pixels_near_hot_spot():
    h, w = 21, 21
    frame = np.zeros((h, w, 4), dtype=np.uint8)
    frame[..., 3] = 255
    frame[h // 2, w // 2, :3] = 255  # single white pixel

    bloom = BloomPass(threshold=200.0, intensity=1.0, radius_px=4.0)
    out = bloom.apply(frame)

    # The centre is still bright.
    assert int(out[h // 2, w // 2, 0]) >= 200

    # Adjacent pixels (which were pure black) should now have a non-zero
    # bloom contribution.
    neighbours = [
        out[h // 2, w // 2 + 1, :3],
        out[h // 2, w // 2 - 1, :3],
        out[h // 2 + 1, w // 2, :3],
        out[h // 2 - 1, w // 2, :3],
    ]
    for n in neighbours:
        assert int(n.sum()) > 0, "Bloom should leak into neighbouring pixels"


def test_bloom_radius_controls_spread():
    h, w = 41, 41
    frame = np.zeros((h, w, 4), dtype=np.uint8)
    frame[..., 3] = 255
    cy, cx = h // 2, w // 2
    # Use a small bright cluster (rather than a single pixel) so the
    # Gaussian halo retains enough energy at a moderate distance to be
    # measurable after the uint8 round-trip.
    frame[cy - 2 : cy + 3, cx - 2 : cx + 3, :3] = 255

    small = BloomPass(threshold=200.0, intensity=1.0, radius_px=2.0).apply(frame)
    large = BloomPass(threshold=200.0, intensity=1.0, radius_px=8.0).apply(frame)

    # Sample at a distance well outside the small-radius core but within
    # reach of the large-radius halo.
    dist = 8
    small_halo = int(small[cy, cx + dist, :3].sum())
    large_halo = int(large[cy, cx + dist, :3].sum())

    assert large_halo > small_halo, (
        f"Larger radius should produce a brighter halo at distance "
        f"{dist}: small={small_halo} vs large={large_halo}"
    )


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------


def test_chain_applies_in_order():
    rng = np.random.default_rng(42)
    # Mix dim and bright regions so bloom and tonemap both have something
    # to do, and order matters.
    frame = rng.integers(0, 256, size=(24, 24, 4), dtype=np.uint8).astype(np.uint8)
    frame[..., 3] = 255
    # Force a hot spot.
    frame[10:14, 10:14, :3] = 250

    bloom = BloomPass(threshold=200.0, intensity=1.0, radius_px=5.0)
    tonemap = TonemapPass(exposure=1.2)

    chain_a = PostProcessChain([bloom, tonemap])
    chain_b = PostProcessChain([tonemap, bloom])

    out_a = chain_a.apply(frame)
    out_b = chain_b.apply(frame)

    assert not np.array_equal(out_a, out_b), (
        "Chain order should be observable: bloom->tonemap and "
        "tonemap->bloom must differ"
    )


def test_chain_add_returns_self_and_appends():
    chain = PostProcessChain()
    result = chain.add(BloomPass()).add(TonemapPass())
    assert result is chain
    assert len(chain.passes) == 2
    assert isinstance(chain.passes[0], BloomPass)
    assert isinstance(chain.passes[1], TonemapPass)


def test_default_chain_factory():
    chain = default_post_process_chain()
    assert isinstance(chain, PostProcessChain)
    assert len(chain.passes) == 2
    assert isinstance(chain.passes[0], BloomPass)
    assert isinstance(chain.passes[1], TonemapPass)

    # Sanity-check end-to-end on a small frame.
    frame = np.zeros((8, 8, 4), dtype=np.uint8)
    frame[..., 3] = 255
    frame[4, 4, :3] = 255
    out = chain.apply(frame)
    assert out.shape == frame.shape
    assert out.dtype == np.uint8
