"""Tests for :mod:`pharos_editor.ui.theme.page_linings`.

Covers:

* 15 registered styles + integrity of :data:`PAGE_LININGS`.
* WGSL source compiles-clean (< 1000 bytes, has ``fs_main`` entry).
* :func:`render_lining` returns valid RGBA per style.
* Numpy fallback works for every style even without wgpu.
* Tile continuity — last row/column matches first row/column at
  ``tile_size`` periods.
* Colour propagation from paper/ink overrides.
* :class:`ThemeSpec.background_shader` accepts a lining id + roundtrips
  through YAML.
"""
from __future__ import annotations

import numpy as np
import pytest

from pharos_editor.ui.theme.page_linings import (
    LiningStyle,
    PAGE_LININGS,
    bake_lining_texture,
    get_lining,
    has_wgpu,
    iter_linings,
    list_linings,
    render_lining,
)
from pharos_editor.ui.theme.page_linings.library import (
    PAGE_LININGS as _RAW_LININGS,
)


# ---------------------------------------------------------------------------
# Library sanity
# ---------------------------------------------------------------------------


def test_library_contains_at_least_15_styles():
    assert len(PAGE_LININGS) >= 15


def test_list_linings_is_sorted_and_matches_keys():
    ids = list_linings()
    assert ids == sorted(PAGE_LININGS.keys())
    assert set(ids) == set(PAGE_LININGS.keys())


def test_every_style_has_required_shape():
    """Each entry is a fully-populated :class:`LiningStyle`."""
    for style_id, style in PAGE_LININGS.items():
        assert isinstance(style, LiningStyle)
        assert style.style_id == style_id
        assert isinstance(style.source, str) and style.source
        tw, th = style.tile_size
        assert isinstance(tw, int) and tw > 0
        assert isinstance(th, int) and th > 0
        for name, rgb in (
            ("default_paper", style.default_paper),
            ("default_ink", style.default_ink),
        ):
            assert len(rgb) == 3, f"{style_id}.{name}: expected 3 channels"
            for ch in rgb:
                assert 0 <= ch <= 255, f"{style_id}.{name}: out of range"
        assert isinstance(style.description, str) and style.description


# ---------------------------------------------------------------------------
# WGSL source cost + compile hooks
# ---------------------------------------------------------------------------


def test_every_wgsl_source_under_1000_bytes():
    """Enforce the ≤ 1 KB per-shader budget from the sprint spec."""
    for style_id, style in PAGE_LININGS.items():
        n = len(style.source.encode("utf-8"))
        assert n <= 1000, f"{style_id}: WGSL source {n} bytes > 1000 cap"


def test_every_wgsl_source_declares_fs_main_entry():
    """Each shader must expose the ``fs_main`` fragment entry."""
    for style_id, style in PAGE_LININGS.items():
        assert "fs_main" in style.source, f"{style_id}: missing fs_main entry"
        assert "@fragment" in style.source, f"{style_id}: missing @fragment"


# ---------------------------------------------------------------------------
# get_lining / list_linings behaviour
# ---------------------------------------------------------------------------


def test_get_lining_returns_registered_style():
    style = get_lining("dot_grid")
    assert style.style_id == "dot_grid"
    assert style.tile_size == (24, 24)


def test_get_lining_rejects_unknown_id():
    with pytest.raises(KeyError) as exc:
        get_lining("nope")
    # The message must list the known ids so callers can recover.
    assert "known styles" in str(exc.value)


def test_get_lining_rejects_non_str():
    with pytest.raises(TypeError):
        get_lining(42)  # type: ignore[arg-type]


def test_iter_linings_yields_every_style_once():
    seen = [s.style_id for s in iter_linings()]
    assert seen == list_linings()
    assert len(seen) == len(set(seen))


# ---------------------------------------------------------------------------
# render_lining shape + dtype + alpha
# ---------------------------------------------------------------------------


def test_render_lining_returns_rgba_uint8_for_every_style():
    for style_id in list_linings():
        arr = render_lining(style_id, (48, 32), force_fallback=True)
        assert arr.shape == (32, 48, 4), f"{style_id}: bad shape {arr.shape}"
        assert arr.dtype == np.uint8, f"{style_id}: bad dtype {arr.dtype}"
        # Alpha is always 255 — page-lining paper is opaque.
        assert np.all(arr[..., 3] == 255), f"{style_id}: alpha not 255"


def test_render_lining_rejects_bad_size():
    with pytest.raises((TypeError, ValueError)):
        render_lining("dot_grid", (0, 32), force_fallback=True)
    with pytest.raises((TypeError, ValueError)):
        render_lining("dot_grid", (32,), force_fallback=True)


def test_render_lining_rejects_bad_style_id():
    with pytest.raises(KeyError):
        render_lining("bogus", (16, 16), force_fallback=True)


# ---------------------------------------------------------------------------
# Numpy fallback per style — same output whether or not wgpu is present
# ---------------------------------------------------------------------------


def test_numpy_fallback_matches_forced_path_for_every_style():
    """The GPU harness currently returns None so the two paths agree.

    This test guards the invariant that if a caller doesn't force the
    fallback the numpy path is still reached — which is the shipping
    behaviour today (GPU dispatch is deferred, see renderer.py).
    """
    for style_id in list_linings():
        style = get_lining(style_id)
        tw, th = style.tile_size
        forced = render_lining(style_id, (tw, th), force_fallback=True)
        auto = render_lining(style_id, (tw, th), force_fallback=False)
        # When wgpu is missing (the CI + headless default) the two paths
        # must produce identical output. When wgpu *is* installed but no
        # GPU context is live the GPU path also falls back — same result.
        if not has_wgpu():
            assert np.array_equal(forced, auto), (
                f"{style_id}: forced vs auto fallback mismatch"
            )
        else:  # pragma: no cover - only when wgpu is installed
            assert forced.shape == auto.shape


# ---------------------------------------------------------------------------
# Tile continuity — the core of "tileable design"
# ---------------------------------------------------------------------------


def _wraps_smoothly(edge_a: np.ndarray, edge_b: np.ndarray, tol: int = 8) -> bool:
    """Return True if two 1-D colour edges match within *tol* (0-255)."""
    diff = np.abs(edge_a.astype(np.int32) - edge_b.astype(np.int32))
    return bool(diff.max() <= tol)


def test_ruled_paper_tiles_vertically_at_24px():
    """ruled_paper repeats every 24 px vertically."""
    arr = render_lining("ruled_paper", (128, 48), force_fallback=True)
    # Row 0 and row 24 should match — pattern period.
    assert _wraps_smoothly(arr[0, :, :3], arr[24, :, :3])


def test_dot_grid_tiles_at_24_24():
    """dot_grid pattern period is 24 px in both axes."""
    arr = render_lining("dot_grid", (48, 48), force_fallback=True)
    assert _wraps_smoothly(arr[0, :, :3], arr[24, :, :3])
    assert _wraps_smoothly(arr[:, 0, :3], arr[:, 24, :3])


def test_graph_grid_tiles_at_10_10():
    arr = render_lining("graph_grid", (30, 30), force_fallback=True)
    assert _wraps_smoothly(arr[0, :, :3], arr[10, :, :3])
    assert _wraps_smoothly(arr[:, 0, :3], arr[:, 10, :3])


def test_polka_dot_soft_tiles_at_32_32():
    arr = render_lining("polka_dot_soft", (64, 64), force_fallback=True)
    assert _wraps_smoothly(arr[0, :, :3], arr[32, :, :3])
    assert _wraps_smoothly(arr[:, 0, :3], arr[:, 32, :3])


def test_notebook_college_tiles_at_16px_vertically():
    arr = render_lining("notebook_college", (96, 48), force_fallback=True)
    assert _wraps_smoothly(arr[0, :, :3], arr[16, :, :3])


# ---------------------------------------------------------------------------
# Colour propagation — paper + line overrides visibly reach the pixels
# ---------------------------------------------------------------------------


def test_colour_override_reaches_paper_pixels():
    """A neon paper colour should dominate the majority of a dot-grid tile."""
    neon = (255, 0, 128)
    arr = render_lining(
        "dot_grid", (48, 48), paper_color=neon, force_fallback=True,
    )
    # Sample far from any dot centre (dot_grid places dots at cell centres).
    corner = arr[0, 0, :3]
    # The neon paper colour must dominate — allow small noise from AA.
    assert corner[0] > 200 and corner[2] > 100
    # And the paper channel R must exceed G channel (magenta-ish).
    assert corner[0] > corner[1] + 40


def test_line_colour_override_reaches_line_pixels():
    """The ink override colour must appear on a ruled_paper horizontal rule."""
    ink = (10, 220, 30)
    arr = render_lining(
        "ruled_paper", (64, 48), line_color=ink, force_fallback=True,
    )
    # Row 23 (0-indexed) is where the WGSL `step(23.0, y % 24.0)` fires.
    row = arr[23, :, :3]
    # At least one pixel in that row should be dominated by G channel.
    green_dominant = np.sum(
        (row[:, 1] > row[:, 0] + 40) & (row[:, 1] > row[:, 2] + 40)
    )
    assert green_dominant > 5, f"expected green line pixels; got {green_dominant}"


def test_default_paper_reaches_pixels_when_no_override():
    """Blank cream should be predominantly cream-coloured."""
    style = get_lining("blank_cream")
    arr = render_lining("blank_cream", (32, 32), force_fallback=True)
    # Average colour should be within noise range of default_paper.
    mean = arr[..., :3].mean(axis=(0, 1))
    for i, channel in enumerate(style.default_paper):
        # ±8 tolerance accounts for the ±0.02 noise term in the shader.
        assert abs(mean[i] - channel) < 8, (
            f"channel {i}: mean {mean[i]} vs anchor {channel}"
        )


# ---------------------------------------------------------------------------
# bake_lining_texture convenience wrapper
# ---------------------------------------------------------------------------


def test_bake_lining_texture_accepts_named_uniforms():
    arr = bake_lining_texture(
        "graph_grid",
        (30, 30),
        paper_color=(200, 210, 220),
        line_color=(10, 20, 30),
        force_fallback=True,
    )
    assert arr.shape == (30, 30, 4)
    assert arr.dtype == np.uint8


def test_bake_lining_texture_ignores_unknown_uniforms():
    """Unknown uniform keys should be logged + skipped, not raised."""
    arr = bake_lining_texture(
        "dot_grid",
        (24, 24),
        force_fallback=True,
        u_time=1.5,  # unknown — dropped
        u_size=(24, 24),  # unknown — dropped
    )
    assert arr.shape == (24, 24, 4)


# ---------------------------------------------------------------------------
# ThemeSpec integration
# ---------------------------------------------------------------------------


def _make_semantic():
    from pharos_editor.ui.theme.theme_spec import (
        Color, Gradient, SemanticTokens,
    )
    primary = Color(120, 180, 240, 1.0)
    return SemanticTokens(
        primary=primary,
        primary_gradient=Gradient(start=primary, end=Color(200, 220, 250), angle_deg=135.0),
        secondary=Color(80, 120, 200, 1.0),
        accent=Color(255, 180, 0, 1.0),
        background=Color(20, 20, 28, 1.0),
        surface=Color(28, 28, 36, 0.95),
        surface_hover=Color(36, 36, 48, 0.95),
        border=Color(60, 60, 70, 1.0),
        text_primary=Color(240, 240, 245, 1.0),
        text_secondary=Color(180, 180, 190, 1.0),
        text_disabled=Color(120, 120, 130, 1.0),
        success=Color(0, 200, 100, 1.0),
        warning=Color(255, 180, 0, 1.0),
        error=Color(220, 60, 60, 1.0),
        info=Color(80, 160, 220, 1.0),
        focus_ring=Color(255, 180, 0, 1.0),
        glass_bg=Color(255, 255, 255, 0.1),
        glass_blur_px=8.0,
    )


def test_theme_spec_accepts_lining_id_as_background_shader():
    from pharos_editor.ui.theme.theme_spec import ThemeSpec
    theme = ThemeSpec(
        name="lining-demo",
        semantic=_make_semantic(),
        background_shader="ruled_paper",
    )
    assert theme.background_shader == "ruled_paper"


def test_theme_spec_rejects_unknown_lining_id():
    from pharos_editor.ui.theme.theme_spec import ThemeSpec
    with pytest.raises(ValueError) as exc:
        ThemeSpec(
            name="bad-lining",
            semantic=_make_semantic(),
            background_shader="not_registered",
        )
    assert "not registered" in str(exc.value) or "not\nregistered" in str(exc.value)


def test_theme_spec_lining_id_serialises_through_helper():
    """The background-shader serialisation helper tags lining ids so
    :meth:`ThemeSpec.from_dict` can recover the id on reload.
    """
    from pharos_editor.ui.theme.theme_spec import (
        _deserialise_background_shader,
        _serialise_background_shader,
    )
    payload = _serialise_background_shader("hex_grid")
    assert payload == {"kind": "lining", "style_id": "hex_grid"}
    restored = _deserialise_background_shader(payload)
    assert restored == "hex_grid"
    # A raw str passes through untouched — legacy YAML files that
    # stored the id as a bare string still load cleanly.
    assert _deserialise_background_shader("dot_grid") == "dot_grid"


def test_resolve_background_dispatches_lining_id():
    from pharos_editor.ui.theme.wgsl_backgrounds import resolve_background
    arr = resolve_background("music_staff")
    assert isinstance(arr, np.ndarray)
    # music_staff tile_size (64, 48) → 2× → 128×96
    assert arr.shape == (96, 128, 4)


# ---------------------------------------------------------------------------
# Registry equality
# ---------------------------------------------------------------------------


def test_public_alias_matches_library_registry():
    """The public :data:`PAGE_LININGS` is the same object as library's."""
    assert PAGE_LININGS is _RAW_LININGS
