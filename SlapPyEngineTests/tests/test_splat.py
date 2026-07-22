"""Tests for the standalone splat deformation calculator."""
from __future__ import annotations

import math

import pytest

from pharos_engine.physics.splat import (
    SPLAT_MUD,
    SPLAT_NONE,
    SPLAT_WATER,
    SplatConfig,
    compute_splat,
)


# A speed comfortably inside the "full splat" plateau (> 50 + 200 = 250).
FAST = 400.0
# A speed inside the ramp but well above the floor.
MEDIUM = 200.0  # speed_factor = (200 - 50) / 200 = 0.75


def test_no_splat_when_squash_strength_zero() -> None:
    """SPLAT_NONE leaves the polygon unchanged regardless of impact."""
    sx, sy, rot = compute_splat(
        impact_vel=(0.0, FAST),
        current_fluidity=1.0,
        base_scale=3.0,
        base_rotation=0.42,
        cfg=SPLAT_NONE,
    )
    assert sx == pytest.approx(3.0)
    assert sy == pytest.approx(3.0)
    assert rot == pytest.approx(0.42)


def test_no_splat_when_fluidity_below_gate() -> None:
    """Below the fluidity gate the particle thuds — no deformation."""
    # Mud gate is 0.1; pick a current_fluidity below it.
    sx, sy, rot = compute_splat(
        impact_vel=(0.0, FAST),
        current_fluidity=0.05,
        base_scale=2.0,
        base_rotation=1.23,
        cfg=SPLAT_MUD,
    )
    assert sx == pytest.approx(2.0)
    assert sy == pytest.approx(2.0)
    assert rot == pytest.approx(1.23)


def test_squash_compresses_along_impact_direction() -> None:
    """Vertical impact + mud: polygon flattens (scale_y < scale_x)."""
    sx, sy, rot = compute_splat(
        impact_vel=(0.0, FAST),
        current_fluidity=1.0,
        base_scale=4.0,
        base_rotation=0.0,
        cfg=SPLAT_MUD,
    )
    assert sy < 4.0 < sx, f"expected scale_y < base < scale_x, got sx={sx} sy={sy}"
    # Vertical impact means no rotation applied (down axis already aligned).
    assert rot == pytest.approx(0.0, abs=1e-9)


def test_horizontal_impact_rotates_squash() -> None:
    """Horizontal impact: rotation aligns the squash axis with +x."""
    base_scale = 5.0
    sx, sy, rot = compute_splat(
        impact_vel=(FAST, 0.0),  # rightward impact
        current_fluidity=1.0,
        base_scale=base_scale,
        base_rotation=0.0,
        cfg=SPLAT_MUD,
    )
    # Rotation should be -pi/2: the rotated (0, 1) "down" axis maps to (1, 0).
    assert rot == pytest.approx(-math.pi / 2, abs=1e-9)
    # The returned scales themselves are the same magnitudes as a vertical
    # impact (scale_x = stretch, scale_y = squash); the rotation does the
    # geometric swap. So scale_y < base < scale_x still holds.
    assert sy < base_scale < sx

    # Cross-check: world-frame axis vectors after rotate + scale.
    # Bake_mask_xy applies rotation in unit space first then scales.
    # The unit "down" (0,1) becomes (-sin(rot), cos(rot)) = (1, 0),
    # then scaled by scale_y → world vector (sy, 0). That's the squashed
    # axis pointing along world-x — exactly the impact direction.
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    down_x = -sin_r * sy
    down_y = cos_r * sy
    assert down_x == pytest.approx(sy, abs=1e-9)
    assert down_y == pytest.approx(0.0, abs=1e-9)


def test_high_speed_impact_squashes_more_than_low_speed() -> None:
    """Faster impacts produce more aggressive squash within the ramp."""
    # MEDIUM (200) is in the ramp; FAST (400) saturates speed_factor=1.
    _, sy_slow, _ = compute_splat(
        impact_vel=(0.0, MEDIUM),
        current_fluidity=1.0,
        base_scale=3.0,
        base_rotation=0.0,
        cfg=SPLAT_MUD,
    )
    _, sy_fast, _ = compute_splat(
        impact_vel=(0.0, FAST),
        current_fluidity=1.0,
        base_scale=3.0,
        base_rotation=0.0,
        cfg=SPLAT_MUD,
    )
    assert sy_fast < sy_slow, (
        f"expected faster impact to squash harder; got sy_fast={sy_fast} "
        f"sy_slow={sy_slow}"
    )

    # And below the speed floor, the polygon shouldn't splat at all.
    sx_floor, sy_floor, rot_floor = compute_splat(
        impact_vel=(0.0, 10.0),
        current_fluidity=1.0,
        base_scale=3.0,
        base_rotation=0.55,
        cfg=SPLAT_MUD,
    )
    assert sx_floor == pytest.approx(3.0)
    assert sy_floor == pytest.approx(3.0)
    assert rot_floor == pytest.approx(0.55)


def test_splat_strengths_sum_proportionally_to_fluidity() -> None:
    """Within the active range, squash + stretch deformation scales
    linearly with current_fluidity."""
    base_scale = 1.0

    # All three fluidity values are above the water gate (0.0), so they
    # all activate. Speed factor saturates at 1.0 (FAST = 400).
    cfg = SPLAT_WATER
    out_low = compute_splat((0.0, FAST), 0.25, base_scale, 0.0, cfg)
    out_mid = compute_splat((0.0, FAST), 0.50, base_scale, 0.0, cfg)
    out_high = compute_splat((0.0, FAST), 1.00, base_scale, 0.0, cfg)

    # Squash deformation: (base - scale_y) should scale linearly with fluidity.
    squash_low = base_scale - out_low[1]
    squash_mid = base_scale - out_mid[1]
    squash_high = base_scale - out_high[1]
    # squash_mid / squash_low == 2.0 (fluidity 0.50 / 0.25)
    assert squash_mid == pytest.approx(2.0 * squash_low, rel=1e-6)
    # squash_high / squash_low == 4.0 (fluidity 1.00 / 0.25)
    assert squash_high == pytest.approx(4.0 * squash_low, rel=1e-6)

    # Stretch deformation: (scale_x - base) should scale linearly too.
    stretch_low = out_low[0] - base_scale
    stretch_mid = out_mid[0] - base_scale
    stretch_high = out_high[0] - base_scale
    assert stretch_mid == pytest.approx(2.0 * stretch_low, rel=1e-6)
    assert stretch_high == pytest.approx(4.0 * stretch_low, rel=1e-6)

    # And the absolute magnitudes match the documented formulas at full
    # fluidity + full speed.
    assert squash_high == pytest.approx(cfg.squash_strength * 1.0)
    assert stretch_high == pytest.approx(cfg.stretch_strength * 1.0)


def test_predefined_configs_have_expected_shape() -> None:
    """Sanity check: the three built-in configs hold the documented knobs."""
    assert SPLAT_NONE.squash_strength == 0.0
    assert SPLAT_NONE.stretch_strength == 0.0

    assert SPLAT_MUD.squash_strength == pytest.approx(0.5)
    assert SPLAT_MUD.stretch_strength == pytest.approx(0.4)
    assert SPLAT_MUD.fluidity_gate == pytest.approx(0.1)

    assert SPLAT_WATER.squash_strength == pytest.approx(0.7)
    assert SPLAT_WATER.stretch_strength == pytest.approx(0.5)
    assert SPLAT_WATER.fluidity_gate == pytest.approx(0.0)


def test_can_compose_with_fragmentshape_bake_mask_xy() -> None:
    """Smoke test: the returned tuple plugs into bake_mask_xy without
    blowing up, and a real squash produces a wider-than-tall raster
    for a vertical impact."""
    from pharos_engine.physics.fragment import SHAPE_BLOB

    sx, sy, rot = compute_splat(
        impact_vel=(0.0, FAST),
        current_fluidity=1.0,
        base_scale=8.0,
        base_rotation=0.0,
        cfg=SPLAT_WATER,
    )
    mask = SHAPE_BLOB.bake_mask_xy(scale_x=sx, scale_y=sy, rotation=rot)
    assert mask.dtype == bool
    # Squashed horizontally: rows (y extent) should be fewer than cols (x extent)
    # that contain True.
    rows_with_fill = int(mask.any(axis=1).sum())
    cols_with_fill = int(mask.any(axis=0).sum())
    assert cols_with_fill > rows_with_fill, (
        f"expected splat to be wider than tall, got "
        f"cols={cols_with_fill} rows={rows_with_fill}"
    )
