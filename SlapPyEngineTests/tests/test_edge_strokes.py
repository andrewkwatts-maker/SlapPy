"""Tests for the preset-level edge-stroke API (BBB4).

Covers:

* Each of the four notebook presets renders without exception at both
  a horizontal (400x4) and a vertical (4x300) strip size.
* Stroke pixels are concentrated near the border of the thickness axis
  — mean alpha in the outer three pixels is at least ``2x`` the mean
  alpha of the centre band.
* :data:`EDGE_STROKE_PRESETS` has exactly four entries — the ship-set
  is fixed until the next theme sprint.
* :func:`render_edge_stroke` raises :class:`KeyError` for an unknown
  preset name.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_editor.ui.theme import (
    EDGE_STROKE_PRESETS,
    PanelDecorator,
    render_edge_stroke,
)


EXPECTED_PRESETS = {"pencil_scribble", "ink_thick", "ink_thin", "marker_bleed"}


class TestEdgeStrokePresets:
    def test_preset_registry_has_four_entries(self):
        """Ship-set is exactly the four notebook presets."""
        assert len(EDGE_STROKE_PRESETS) == 4
        assert set(EDGE_STROKE_PRESETS) == EXPECTED_PRESETS

    @pytest.mark.parametrize("preset", sorted(EXPECTED_PRESETS))
    @pytest.mark.parametrize("w,h", [(400, 4), (4, 300)])
    def test_render_shape_and_dtype(self, preset, w, h):
        """Each preset renders both horizontal + vertical strip sizes."""
        arr = render_edge_stroke(preset, w, h)
        assert arr.shape == (h, w, 4)
        assert arr.dtype == np.uint8

    @pytest.mark.parametrize("preset", sorted(EXPECTED_PRESETS))
    def test_horizontal_stroke_concentrated_near_border(self, preset):
        """Outer 3 rows of a horizontal strip carry ≥ 2x centre alpha."""
        # 20-row strip leaves a wide centre band clearly free of stroke
        # pixels even for the thickest preset (marker_bleed, ~8px).
        w, h = 400, 20
        arr = render_edge_stroke(preset, w, h)
        alpha = arr[..., 3].astype(np.float32)
        outer = np.concatenate([alpha[:3, :].ravel(), alpha[-3:, :].ravel()])
        centre = alpha[3:-3, :].ravel()
        outer_mean = float(outer.mean())
        centre_mean = float(centre.mean())
        # Centre should be alpha=0 for any of these presets — but we
        # allow a very small epsilon in case a future preset does an
        # interior watermark. The 2x rule from the sprint brief is the
        # hard requirement.
        assert outer_mean >= 2.0 * (centre_mean + 1e-3), (
            f"{preset}: outer_mean={outer_mean:.2f} vs "
            f"centre_mean={centre_mean:.2f}"
        )

    @pytest.mark.parametrize("preset", sorted(EXPECTED_PRESETS))
    def test_vertical_stroke_concentrated_near_border(self, preset):
        """Outer 3 cols of a vertical strip carry ≥ 2x centre alpha."""
        w, h = 20, 300
        arr = render_edge_stroke(preset, w, h)
        alpha = arr[..., 3].astype(np.float32)
        outer = np.concatenate([alpha[:, :3].ravel(), alpha[:, -3:].ravel()])
        centre = alpha[:, 3:-3].ravel()
        outer_mean = float(outer.mean())
        centre_mean = float(centre.mean())
        assert outer_mean >= 2.0 * (centre_mean + 1e-3), (
            f"{preset}: outer_mean={outer_mean:.2f} vs "
            f"centre_mean={centre_mean:.2f}"
        )

    def test_unknown_preset_raises_keyerror(self):
        with pytest.raises(KeyError):
            render_edge_stroke("bogus", 100, 4)

    def test_render_is_deterministic(self):
        """Same preset + same dims ⇒ same bytes."""
        a = render_edge_stroke("ink_thick", 200, 4)
        b = render_edge_stroke("ink_thick", 200, 4)
        assert np.array_equal(a, b)

    def test_ink_rgba_override(self):
        """Custom ink colour reaches the output."""
        arr = render_edge_stroke("ink_thick", 100, 4, ink_rgba=(255, 0, 0, 255))
        # Find pixels with alpha > 0 and check red channel dominates.
        painted = arr[arr[..., 3] > 0]
        assert painted.size > 0
        assert painted[..., 0].mean() >= 200  # r
        assert painted[..., 1].mean() <= 40   # g
        assert painted[..., 2].mean() <= 40   # b


class TestPanelDecorator:
    def test_defaults_are_valid(self):
        deco = PanelDecorator()
        overlay = deco.build_edge_overlay(300, 200)
        assert overlay.shape == (200, 300, 4)
        assert overlay.dtype == np.uint8

    def test_rejects_unknown_preset(self):
        with pytest.raises(KeyError):
            PanelDecorator(edge_stroke_preset="nope")

    def test_interior_is_transparent(self):
        deco = PanelDecorator(edge_stroke_preset="ink_thick", stroke_thickness_px=3)
        overlay = deco.build_edge_overlay(200, 120)
        # Middle 40 rows / 100 cols should be zero-alpha.
        interior = overlay[40:80, 50:150, 3]
        assert interior.max() == 0

    def test_build_edge_tiles_shapes(self):
        deco = PanelDecorator(edge_stroke_preset="ink_thin", stroke_thickness_px=2)
        tiles = deco.build_edge_tiles(300, 200)
        assert set(tiles) == {"top", "bottom", "left", "right"}
        assert tiles["top"].shape[0] <= 2
        assert tiles["left"].shape[1] <= 2
