"""Lighting round 9 — DoF focus-transition smoothness polish.

Round 9 adds a ``focus_transition`` knob to ``DofPass``. The CPU
reference :meth:`DofPass.compute_coc` mirrors the GPU formula so tests
can run headlessly.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.post_process.dof import DofPass


def test_dof_backward_compat_linear_at_transition_1() -> None:
    """``focus_transition=1.0`` must reproduce the legacy linear ramp."""
    legacy = DofPass(focal_distance=0.5, focal_range=0.2,
                      max_coc_radius=10.0)
    depth = np.linspace(0.0, 1.0, 100, dtype=np.float32)
    coc = legacy.compute_coc(depth)
    # At focal_distance, CoC is zero.
    centre = legacy.compute_coc(np.array([0.5], dtype=np.float32))
    assert centre[0] == pytest.approx(0.0)
    # At focal_distance + focal_range, CoC saturates at max.
    edge = legacy.compute_coc(np.array([0.5 + 0.2], dtype=np.float32))
    assert edge[0] == pytest.approx(10.0)
    # In between, linear.
    mid = legacy.compute_coc(np.array([0.5 + 0.1], dtype=np.float32))
    assert mid[0] == pytest.approx(5.0, abs=1e-4)


def test_dof_sharp_focus_transition_below_1_concentrates_in_focus() -> None:
    """``focus_transition < 1`` should keep more pixels in focus near edge."""
    sharp = DofPass(focal_distance=0.5, focal_range=0.2,
                     max_coc_radius=10.0, focus_transition=0.5)
    legacy = DofPass(focal_distance=0.5, focal_range=0.2,
                      max_coc_radius=10.0)
    near_edge = np.array([0.5 + 0.18], dtype=np.float32)  # 90% into range
    assert sharp.compute_coc(near_edge)[0] > legacy.compute_coc(near_edge)[0]


def test_dof_soft_focus_transition_above_1_keeps_focus_longer() -> None:
    """``focus_transition > 1`` smoothsteps the ramp — middle values reduced."""
    soft = DofPass(focal_distance=0.5, focal_range=0.2,
                    max_coc_radius=10.0, focus_transition=2.0)
    legacy = DofPass(focal_distance=0.5, focal_range=0.2,
                      max_coc_radius=10.0)
    mid = np.array([0.5 + 0.1], dtype=np.float32)  # 50% into range
    # Smoothstep at t=0.5 -> 0.5 too, so the centre is unchanged. Test the
    # near-edge: smooth path keeps lower CoC because the curve is shaped
    # to start flat then rise.
    near = np.array([0.5 + 0.05], dtype=np.float32)  # 25% into range
    assert soft.compute_coc(near)[0] < legacy.compute_coc(near)[0]


def test_dof_zero_focus_transition_rejected() -> None:
    """``focus_transition <= 0`` is meaningless; refuse loudly."""
    with pytest.raises(ValueError, match="focus_transition must be > 0"):
        DofPass(focus_transition=0.0)
    with pytest.raises(ValueError, match="focus_transition must be > 0"):
        DofPass(focus_transition=-0.5)


def test_dof_coc_clamped_outside_range() -> None:
    """Depths far from focal_distance saturate at max_coc_radius regardless."""
    dp = DofPass(focal_distance=0.5, focal_range=0.1, max_coc_radius=15.0)
    very_far = np.array([0.0, 1.0, 0.95, 0.1], dtype=np.float32)
    coc = dp.compute_coc(very_far)
    assert np.allclose(coc, 15.0)


def test_dof_coc_monotonic_increasing_with_depth_distance() -> None:
    """Within the ramp, |depth - focal| ↑ → CoC ↑."""
    dp = DofPass(focal_distance=0.5, focal_range=0.2, max_coc_radius=10.0,
                  focus_transition=1.5)
    depths = np.array([0.5, 0.55, 0.6, 0.65, 0.7], dtype=np.float32)
    coc = dp.compute_coc(depths)
    # Monotone non-decreasing.
    assert np.all(np.diff(coc) >= 0)
