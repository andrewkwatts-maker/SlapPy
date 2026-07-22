"""Regression tests for the BBB3 washi-tape decor pass.

Covers the 4-preset registry, the ``render_washi_tape`` renderer, the
torn-edge invariant, and the :class:`NotebookPanelDecor` title-bar wiring.
The washi-tape presets are the signature "teengirl_notebook" theme
flourish so these tests double as smoke tests for the notebook editor
render loop.
"""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# WASHI_TAPE_PRESETS registry
# ---------------------------------------------------------------------------


def test_washi_tape_presets_registry_has_four_entries() -> None:
    """The registry must expose exactly the 4 sprint-brief presets."""
    from pharos_engine.ui.theme.washi_tape import WASHI_TAPE_PRESETS

    assert len(WASHI_TAPE_PRESETS) == 4
    assert set(WASHI_TAPE_PRESETS) == {
        "pink_polka", "pastel_floral", "star_print", "plain",
    }


def test_washi_tape_presets_reexported_at_theme_top_level() -> None:
    """The top-level ``pharos_engine.ui.theme`` namespace exports the dict."""
    from pharos_engine.ui import theme as theme_pkg

    assert hasattr(theme_pkg, "WASHI_TAPE_PRESETS")
    assert hasattr(theme_pkg, "render_washi_tape")
    assert set(theme_pkg.WASHI_TAPE_PRESETS) == {
        "pink_polka", "pastel_floral", "star_print", "plain",
    }


def test_washi_tape_preset_metadata_fields() -> None:
    """Each preset carries a display name, base colour, and description."""
    from pharos_engine.ui.theme.washi_tape import WASHI_TAPE_PRESETS

    for preset in WASHI_TAPE_PRESETS.values():
        assert isinstance(preset.id, str) and preset.id
        assert isinstance(preset.display_name, str) and preset.display_name
        assert (
            isinstance(preset.base_color, tuple)
            and len(preset.base_color) == 3
        )
        assert all(0 <= c <= 255 for c in preset.base_color)
        assert isinstance(preset.description, str)


# ---------------------------------------------------------------------------
# render_washi_tape
# ---------------------------------------------------------------------------


def test_render_pink_polka_returns_expected_shape() -> None:
    """``render_washi_tape("pink_polka", (128, 32))`` returns RGBA ndarray."""
    from pharos_engine.ui.theme.washi_tape import render_washi_tape

    img = render_washi_tape("pink_polka", (128, 32))
    assert isinstance(img, np.ndarray)
    assert img.dtype == np.uint8
    # numpy convention: (H, W, C)
    assert img.shape == (32, 128, 4)


def test_render_all_four_presets_without_exception() -> None:
    """All 4 presets render at the sprint's default size without raising."""
    from pharos_engine.ui.theme.washi_tape import (
        WASHI_TAPE_PRESETS,
        render_washi_tape,
    )

    for preset_id in WASHI_TAPE_PRESETS:
        img = render_washi_tape(preset_id, (120, 32))
        assert img.shape == (32, 120, 4)
        assert img.dtype == np.uint8


def test_render_washi_tape_unknown_preset_raises() -> None:
    """Unknown preset ids raise ``KeyError`` with a listing of known ids."""
    from pharos_engine.ui.theme.washi_tape import render_washi_tape

    with pytest.raises(KeyError) as excinfo:
        render_washi_tape("not_a_preset", (32, 32))
    assert "pink_polka" in str(excinfo.value)


@pytest.mark.parametrize("bad_size", [(0, 32), (32, -1), "abc", (32,)])
def test_render_washi_tape_bad_size_raises(bad_size) -> None:
    """Malformed sizes raise ``ValueError``."""
    from pharos_engine.ui.theme.washi_tape import render_washi_tape

    with pytest.raises((ValueError, TypeError)):
        render_washi_tape("pink_polka", bad_size)


# ---------------------------------------------------------------------------
# Torn-edge invariant
# ---------------------------------------------------------------------------


def test_torn_edges_have_low_alpha_on_outermost_row() -> None:
    """Outermost row/col has alpha < 128 so tape blends into the panel."""
    from pharos_engine.ui.theme.washi_tape import (
        WASHI_TAPE_PRESETS,
        render_washi_tape,
    )

    for preset_id in WASHI_TAPE_PRESETS:
        img = render_washi_tape(preset_id, (128, 32))
        # Row 0 and row -1 should be well below fully-opaque (torn edge).
        # Ramp is 0 + up to 15 px of sine jitter, so max ≈ 15 → << 128.
        top_row_alpha = img[0, :, 3]
        bot_row_alpha = img[-1, :, 3]
        assert top_row_alpha.max() < 128, (
            f"{preset_id}: top row alpha max = {top_row_alpha.max()}"
        )
        assert bot_row_alpha.max() < 128, (
            f"{preset_id}: bottom row alpha max = {bot_row_alpha.max()}"
        )


def test_tape_body_is_fully_opaque_in_the_middle() -> None:
    """Middle rows are fully opaque so the pattern reads clearly."""
    from pharos_engine.ui.theme.washi_tape import render_washi_tape

    img = render_washi_tape("plain", (128, 32))
    # Middle row (16) should be alpha=255 across all columns.
    mid_alpha = img[16, :, 3]
    assert mid_alpha.min() == 255


# ---------------------------------------------------------------------------
# NotebookPanelDecor wiring
# ---------------------------------------------------------------------------


def test_notebook_panel_decor_title_tape_shape() -> None:
    """``NotebookPanelDecor.title_tape`` returns a rotated RGBA array.

    Rotation enlarges the canvas so the tape's rotated corners fit; the
    output is therefore >= the pre-rotation size on both axes.
    """
    from pharos_engine.ui.editor.notebook_panel_decor import NotebookPanelDecor

    decor = NotebookPanelDecor()
    tape = decor.title_tape("outliner")
    assert isinstance(tape, np.ndarray)
    assert tape.dtype == np.uint8
    assert tape.ndim == 3 and tape.shape[2] == 4
    assert tape.shape[0] >= 32 and tape.shape[1] >= 32


def test_notebook_panel_decor_preset_and_rotation_are_deterministic() -> None:
    """Same panel name → same preset + rotation across runs."""
    from pharos_engine.ui.editor.notebook_panel_decor import (
        preset_for_panel,
        rotation_for_panel,
    )

    for name in ("outliner", "inspector", "toolbar", "code_panel"):
        assert preset_for_panel(name) == preset_for_panel(name)
        assert rotation_for_panel(name) == rotation_for_panel(name)
        # Rotation lands in the ±8 deg budget the sprint calls for.
        assert -8.0 <= rotation_for_panel(name) <= 8.0


def test_notebook_panel_decor_specs_covers_all_panels() -> None:
    """``.specs()`` returns one :class:`TitleTapeSpec` per requested name."""
    from pharos_engine.ui.editor.notebook_panel_decor import NotebookPanelDecor

    decor = NotebookPanelDecor()
    names = ["outliner", "inspector", "toolbar"]
    specs = decor.specs(names)
    assert len(specs) == 3
    for spec, name in zip(specs, names):
        assert spec.panel_name == name
        assert spec.preset in {
            "pink_polka", "pastel_floral", "star_print", "plain",
        }
        assert spec.corner == "TL"
        assert spec.rotation_deg != 0.0  # hand-placed feel


def test_notebook_panel_decor_cache_reuses_render() -> None:
    """Repeated calls for the same panel hit the internal cache."""
    from pharos_engine.ui.editor.notebook_panel_decor import NotebookPanelDecor

    decor = NotebookPanelDecor()
    _ = decor.title_tape("inspector")
    key = ("pink_polka", 120, 32)
    # Not asserting the exact key — the preset is picked deterministically
    # but we don't want the test to break if the hash mapping ever
    # changes. Just assert *some* entry exists.
    assert len(decor._cache) == 1
    _ = decor.title_tape("inspector")
    assert len(decor._cache) == 1  # still one — cache hit
