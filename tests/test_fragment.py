"""Tests for slappyengine.physics.fragment — polygon-based shapes."""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.physics.fragment import (
    BUILTIN_FAMILIES,
    FragmentFamily,
    FragmentShape,
    MUD_FAMILY,
    ROCK_FAMILY,
    SAND_FAMILY,
    SHAPE_BOULDER,
    SHAPE_CIRCLE,
    SHAPE_FLAKE,
    SHAPE_ROUGH,
    SHAPE_SHARD,
    all_shapes,
)


# ── FragmentShape ──────────────────────────────────────────────────────


def test_circle_roughness_is_near_zero() -> None:
    assert SHAPE_CIRCLE.roughness < 0.01


def test_shard_is_rougher_than_circle() -> None:
    assert SHAPE_SHARD.roughness > SHAPE_CIRCLE.roughness * 10


def test_flake_has_high_roughness() -> None:
    # FLAKE has alternating 1.5 / 0.25 radii — should be very rough.
    assert SHAPE_FLAKE.roughness > 0.5


def test_circle_bounds_radius_is_one() -> None:
    assert abs(SHAPE_CIRCLE.bounds_radius - 1.0) < 1e-6


def test_circle_area_close_to_pi() -> None:
    # 16-gon inscribed in unit circle has area slightly < pi.
    assert 2.9 < SHAPE_CIRCLE.area < math.pi


def test_circle_radius_at_any_angle_is_one() -> None:
    for theta in (0.0, math.pi / 4, math.pi / 2, math.pi, 3 * math.pi / 2):
        assert abs(SHAPE_CIRCLE.radius_at(theta) - 1.0) < 0.05


def test_shard_has_directional_radius() -> None:
    # Shard's first vertex at angle 0 has radius 1.6.
    # Use radius_at to confirm angular asymmetry.
    r0 = SHAPE_SHARD.radius_at(0.0)
    r_quarter = SHAPE_SHARD.radius_at(math.pi / 2)
    # Should differ noticeably.
    assert abs(r0 - r_quarter) > 0.3


def test_kick_factor_is_zero_for_circle() -> None:
    # Circle's boundary slope is zero — no kick.
    for theta in (0.0, math.pi / 3, math.pi):
        assert SHAPE_CIRCLE.kick_factor(theta) < 0.1


def test_kick_factor_is_high_for_shard() -> None:
    # Shard has sharp angle transitions — high kick somewhere.
    kicks = [SHAPE_SHARD.kick_factor(theta) for theta in
             np.linspace(0, 2 * math.pi, 16, endpoint=False)]
    assert max(kicks) > 0.3


# ── bake_mask rasterisation ────────────────────────────────────────────


def test_bake_mask_size_scales_with_radius() -> None:
    m1 = SHAPE_CIRCLE.bake_mask(scale=1.0)
    m3 = SHAPE_CIRCLE.bake_mask(scale=3.0)
    assert m3.shape[0] > m1.shape[0]


def test_bake_mask_has_centre_pixel_set() -> None:
    m = SHAPE_CIRCLE.bake_mask(scale=3.0)
    cx = cy = m.shape[0] // 2
    assert m[cy, cx]


def test_bake_mask_circle_is_roughly_round() -> None:
    m = SHAPE_CIRCLE.bake_mask(scale=8.0)
    cy = cx = m.shape[0] // 2
    # Top, bottom, left, right edges should all be at similar distances.
    # Scan from centre to find boundary in each cardinal direction.
    def find_edge(dx, dy):
        x, y = cx, cy
        steps = 0
        while 0 <= x < m.shape[1] and 0 <= y < m.shape[0] and m[y, x]:
            x += dx; y += dy; steps += 1
        return steps
    r_right = find_edge(1, 0)
    r_up = find_edge(0, -1)
    r_left = find_edge(-1, 0)
    r_down = find_edge(0, 1)
    # All within 30% of each other.
    radii = [r_right, r_up, r_left, r_down]
    assert max(radii) <= min(radii) * 1.4


def test_bake_mask_shard_is_asymmetric() -> None:
    m = SHAPE_SHARD.bake_mask(scale=8.0)
    # Find the bounding box of set pixels — shard with vertex 0 at
    # radius 1.6 should extend further along x than along y.
    ys, xs = np.where(m)
    width = xs.max() - xs.min()
    height = ys.max() - ys.min()
    # Either width >> height or height >> width — point in some direction.
    assert max(width, height) > min(width, height) * 1.4


def test_bake_mask_rotation_changes_silhouette() -> None:
    m0 = SHAPE_SHARD.bake_mask(scale=8.0, rotation=0.0)
    m90 = SHAPE_SHARD.bake_mask(scale=8.0, rotation=math.pi / 2)
    # Rotated mask should differ from non-rotated.
    assert not np.array_equal(m0, m90)


# ── FragmentFamily ────────────────────────────────────────────────────


def test_sand_family_samples_circle_most_of_the_time() -> None:
    rng = np.random.default_rng(0)
    counts = {"circle": 0, "rough": 0}
    for _ in range(500):
        s = SAND_FAMILY.sample(rng)
        counts[s.name] += 1
    # weights=(0.7, 0.3) → circle dominant.
    assert counts["circle"] > counts["rough"] * 1.5


def test_rock_family_samples_both_boulder_and_shard() -> None:
    rng = np.random.default_rng(0)
    names = {SHAPE_BOULDER.name, SHAPE_SHARD.name}
    seen = set()
    for _ in range(200):
        s = ROCK_FAMILY.sample(rng)
        seen.add(s.name)
    assert seen == names


def test_mud_family_only_yields_blob() -> None:
    rng = np.random.default_rng(0)
    for _ in range(50):
        assert MUD_FAMILY.sample(rng).name == "blob"


def test_family_rejects_empty_shapes() -> None:
    with pytest.raises(ValueError):
        FragmentFamily("nope", ())


def test_family_rejects_mismatched_weights() -> None:
    with pytest.raises(ValueError):
        FragmentFamily("nope", (SHAPE_CIRCLE, SHAPE_ROUGH), weights=(1.0,))


def test_builtin_families_cover_expected_substances() -> None:
    names = {f.name for f in BUILTIN_FAMILIES}
    assert {"sand", "rock", "mud", "sloppy", "snow", "ice", "water"} <= names


def test_all_shapes_distinct_names() -> None:
    names = [s.name for s in all_shapes()]
    assert len(names) == len(set(names))
