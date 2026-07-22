"""Tests for slappyengine.thermal — 2D heat field + pairwise exchange."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.thermal import HeatField, exchange_two_regions


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── Pairwise exchange ──────────────────────────────────────────────────────


def test_exchange_zero_when_temperatures_equal():
    q = exchange_two_regions(t_a=5.0, m_a=1.0, k_a=1.0,
                             t_b=5.0, m_b=1.0, k_b=1.0, dt=0.1)
    assert q == 0.0


def test_exchange_flows_hot_to_cold():
    q = exchange_two_regions(t_a=10.0, m_a=1.0, k_a=1.0,
                             t_b=0.0, m_b=1.0, k_b=1.0, dt=0.01)
    assert q > 0.0  # A is hotter → q > 0 means heat leaves A
    q2 = exchange_two_regions(t_a=0.0, m_a=1.0, k_a=1.0,
                              t_b=10.0, m_b=1.0, k_b=1.0, dt=0.01)
    assert q2 < 0.0


def test_exchange_conserves_total_heat_after_apply():
    """A→B exchange: t_a*m_a + t_b*m_b should be invariant."""
    t_a, m_a, k_a = 10.0, 2.0, 1.0
    t_b, m_b, k_b = 0.0, 3.0, 1.0
    total_before = t_a * m_a + t_b * m_b
    q = exchange_two_regions(t_a, m_a, k_a, t_b, m_b, k_b, dt=0.1)
    t_a_new = t_a - q / m_a
    t_b_new = t_b + q / m_b
    total_after = t_a_new * m_a + t_b_new * m_b
    assert abs(total_after - total_before) < 1e-9


def test_exchange_clamps_to_equalisation():
    """A huge dt shouldn't overshoot equalisation and reverse the gradient."""
    t_a, m_a, k_a = 100.0, 1.0, 1000.0
    t_b, m_b, k_b = 0.0, 1.0, 1000.0
    q = exchange_two_regions(t_a, m_a, k_a, t_b, m_b, k_b, dt=10.0)
    t_a_new = t_a - q / m_a
    t_b_new = t_b + q / m_b
    # After exchange the gradient may be zero but never inverted.
    assert t_a_new >= t_b_new
    # And exactly at equalisation in the limit.
    assert abs(t_a_new - t_b_new) < 0.01


def test_exchange_zero_for_invalid_inputs():
    # Zero / negative mass
    assert exchange_two_regions(1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.1) == 0.0
    assert exchange_two_regions(1.0, 1.0, 1.0, 0.0, -0.1, 1.0, 0.1) == 0.0
    # Zero / negative conductivity → no exchange (insulator)
    assert exchange_two_regions(10.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.1) == 0.0
    assert exchange_two_regions(10.0, 1.0, 1.0, 0.0, 1.0, -0.1, 0.1) == 0.0


def test_exchange_harmonic_mean_caps_at_insulator():
    """Series-resistor mixing: an insulator on one side limits the flux."""
    # With k_a = 100, k_b = 0.01, the harmonic mean ≈ 0.02 — close to k_b.
    q_high = exchange_two_regions(10.0, 1.0, 100.0, 0.0, 1.0, 100.0, dt=0.001)
    q_low = exchange_two_regions(10.0, 1.0, 100.0, 0.0, 1.0, 0.01, dt=0.001)
    assert q_low < q_high * 0.05, (
        "low-k insulator on one side should drastically reduce flux"
    )


# ── HeatField — diffusion ───────────────────────────────────────────────────


def test_heat_field_zero_initial_is_zero_after_diffusion():
    f = HeatField(shape=(16, 16))
    f.step(0.1)
    assert (f.temperature == 0.0).all()


def test_heat_field_central_hotspot_diffuses_outward():
    """A point source spreads heat; peak drops, total heat conserved.
    Emits a GIF of the diffusion."""
    from python.tests._visual_snapshot import output_dir, save_heatmap
    from PIL import Image
    from slappyengine.media import save_frames

    f = HeatField(shape=(32, 32), diffusivity=0.5, cell_size=1.0)
    f.inject(16, 16, 100.0)
    initial_total = f.total_heat()
    initial_peak = float(f.temperature.max())

    out_dir = output_dir("thermal")
    pil_frames = []
    for i in range(50):
        f.step(0.05)
        tmp = out_dir / f"_heat_tmp_{i:03d}.png"
        # Per-frame auto-range so the diffusion fade stays visible — a
        # fixed vmax tied to initial_peak crushes late frames to black
        # once the peak drops below vmax/256.
        cur_peak = max(float(f.temperature.max()), 1e-6)
        save_heatmap(f.temperature, tmp, vmin=0.0, vmax=cur_peak,
                      cmap="hot", upscale=6)
        pil_frames.append(Image.open(tmp))
    save_frames(pil_frames, out_dir / "heat_diffusion.gif", fps=15)
    for tmp in out_dir.glob("_heat_tmp_*.png"):
        tmp.unlink()

    final_peak = float(f.temperature.max())
    assert final_peak < initial_peak * 0.9
    final_total = f.total_heat()
    assert abs(final_total - initial_total) < 0.01 * initial_total


def test_heat_field_cfl_substepping_keeps_stable():
    """Asking for a too-large dt should substep, not blow up."""
    f = HeatField(shape=(16, 16), diffusivity=1.0, cell_size=1.0)
    f.inject(8, 8, 50.0)
    # Step with dt that would violate the CFL bound (α·dt/h² = 5 > 0.25)
    # if applied directly — the HeatField should substep internally.
    f.step(5.0)
    assert np.all(np.isfinite(f.temperature))
    # Heat hasn't gone wildly negative or NaN.
    assert float(f.temperature.min()) >= -1e-3


def test_heat_field_mask_isolates_disconnected_regions():
    """Two hotspots in disconnected masked regions don't share heat."""
    mask = np.ones((16, 16), dtype=np.float32)
    # Carve a vertical wall down the middle of the field.
    mask[:, 7:9] = 0.0
    f = HeatField(shape=(16, 16), mask=mask, diffusivity=0.5)
    f.inject(2, 8, 50.0)   # Left region
    f.inject(13, 8, 0.0)   # Right region (always 0)
    for _ in range(40):
        f.step(0.05)
    # Right side should remain near 0 because the wall isolates it.
    right_side = f.temperature[:, 10:]
    assert float(right_side.max()) < 0.5


def test_heat_field_radiate_to_ambient_decays_temperature():
    f = HeatField(shape=(8, 8), ambient=0.0)
    f.set_temperature(np.full((8, 8), 10.0, dtype=np.float32))
    f.radiate_to_ambient(rate=2.0, dt=0.5)
    # Implicit decay: T_new = T/(1 + rate*dt) = 10 / 2 = 5
    assert float(f.temperature.mean()) == pytest.approx(5.0, abs=1e-4)


def test_heat_field_radiate_warms_toward_ambient_when_cold():
    f = HeatField(shape=(8, 8), ambient=10.0)
    f.set_temperature(np.zeros((8, 8), dtype=np.float32))
    f.radiate_to_ambient(rate=1.0, dt=1.0)
    # T_new = (0 + 1*10) / 2 = 5
    assert float(f.temperature.mean()) == pytest.approx(5.0, abs=1e-4)


def test_heat_field_set_temperature_shape_check():
    f = HeatField(shape=(8, 8))
    with pytest.raises(ValueError):
        f.set_temperature(np.zeros((4, 8), dtype=np.float32))


def test_heat_field_rejects_tiny_grids():
    with pytest.raises(ValueError):
        HeatField(shape=(1, 16))


def test_heat_field_mask_shape_check():
    with pytest.raises(ValueError):
        HeatField(shape=(8, 8), mask=np.ones((4, 4), dtype=np.float32))
