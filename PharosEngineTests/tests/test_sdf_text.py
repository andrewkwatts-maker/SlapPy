"""SDF text rendering — KK6 Nova3D parity Sprint 13."""
from __future__ import annotations

import numpy as np
import pytest

from pharos_engine.text import (
    SDF_TEXT_WGSL,
    SDFGlyph,
    SDFGlyphAtlas,
    SDFTextRenderer,
    TextMesh,
    pack_glyphs_into_atlas,
    sdf_from_bitmap,
)


# ---------------------------------------------------------------------------
# SDFGlyph dataclass
# ---------------------------------------------------------------------------


def test_sdfglyph_dataclass_fields():
    g = SDFGlyph(
        codepoint=65,
        atlas_uv=(0.0, 0.0, 0.5, 0.5),
        size_px=(16, 20),
        bearing=(1, 18),
        advance_px=17,
    )
    assert g.codepoint == 65
    assert g.atlas_uv == (0.0, 0.0, 0.5, 0.5)
    assert g.size_px == (16, 20)
    assert g.bearing == (1, 18)
    assert g.advance_px == 17


def test_sdfglyph_is_frozen():
    g = SDFGlyph(codepoint=65, atlas_uv=(0, 0, 1, 1), size_px=(1, 1), bearing=(0, 0), advance_px=1)
    with pytest.raises(Exception):
        g.codepoint = 66  # type: ignore[misc]


# ---------------------------------------------------------------------------
# sdf_from_bitmap
# ---------------------------------------------------------------------------


def test_sdf_signs_on_filled_square():
    # 16x16 bitmap with a filled 8x8 square in the middle
    bmp = np.zeros((16, 16), dtype=np.uint8)
    bmp[4:12, 4:12] = 1

    sdf = sdf_from_bitmap(bmp, radius_px=6)

    # Center of square must be *inside* (negative)
    assert sdf[8, 8] < 0.0
    # Corner of image must be *outside* (positive)
    assert sdf[0, 0] > 0.0
    # A boundary pixel — just inside — has |d| < 1
    assert abs(sdf[4, 4]) <= 1.0


def test_sdf_clamps_to_radius():
    bmp = np.zeros((32, 32), dtype=np.uint8)
    bmp[15:17, 15:17] = 1
    sdf = sdf_from_bitmap(bmp, radius_px=4)
    assert sdf.max() <= 4.0 + 1e-5
    assert sdf.min() >= -4.0 - 1e-5


def test_sdf_from_bitmap_rejects_bad_input():
    with pytest.raises(ValueError):
        sdf_from_bitmap(np.zeros((4, 4), dtype=np.uint8), radius_px=0)
    with pytest.raises(ValueError):
        sdf_from_bitmap(np.zeros((4, 4, 4), dtype=np.uint8), radius_px=4)


# ---------------------------------------------------------------------------
# pack_glyphs_into_atlas
# ---------------------------------------------------------------------------


def test_pack_glyphs_fits_all():
    rng = np.random.default_rng(0)
    glyphs = [rng.integers(0, 255, size=(8 + i % 4, 10 + i % 3), dtype=np.uint8) for i in range(24)]
    atlas, positions = pack_glyphs_into_atlas(glyphs, padding=1)
    assert len(positions) == len(glyphs)
    for (x, y, w, h), g in zip(positions, glyphs):
        assert atlas[y:y + h, x:x + w].shape == g.shape
        assert np.array_equal(atlas[y:y + h, x:x + w], g)


def test_pack_glyphs_no_overlap():
    glyphs = [np.full((6, 6), i + 1, dtype=np.uint8) for i in range(10)]
    _, positions = pack_glyphs_into_atlas(glyphs, padding=1)
    for i, (x1, y1, w1, h1) in enumerate(positions):
        for j, (x2, y2, w2, h2) in enumerate(positions):
            if i == j:
                continue
            no_overlap = (
                x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1
            )
            assert no_overlap, f"glyph {i} overlaps {j}"


def test_pack_glyphs_empty():
    atlas, positions = pack_glyphs_into_atlas([])
    assert positions == []
    assert atlas.shape == (1, 1)


# ---------------------------------------------------------------------------
# SDFGlyphAtlas
# ---------------------------------------------------------------------------


def test_atlas_generate_returns_hxwx4():
    atlas = SDFGlyphAtlas(font_path=None, size_px=16, sdf_radius=4,
                          codepoints=range(ord('A'), ord('F') + 1))
    tex = atlas.generate()
    assert tex.ndim == 3
    assert tex.shape[2] == 4
    assert tex.dtype == np.uint8


def test_atlas_generate_idempotent():
    atlas = SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=3,
                          codepoints=range(ord('A'), ord('D') + 1))
    a = atlas.generate()
    b = atlas.generate()
    assert a is b  # cached


def test_atlas_get_glyph_ascii():
    atlas = SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=3,
                          codepoints=range(ord('A'), ord('J') + 1))
    atlas.generate()
    g = atlas.get_glyph(ord('A'))
    if g is None:
        pytest.skip("PIL default font could not rasterise ASCII 'A'")
    assert isinstance(g, SDFGlyph)
    assert g.codepoint == ord('A')
    u0, v0, u1, v1 = g.atlas_uv
    assert 0.0 <= u0 < u1 <= 1.0
    assert 0.0 <= v0 < v1 <= 1.0


def test_atlas_get_glyph_missing_returns_none():
    atlas = SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=3,
                          codepoints=range(ord('A'), ord('B') + 1))
    atlas.generate()
    assert atlas.get_glyph(0x1F600) is None  # emoji not in the set


def test_atlas_text_bounds_monotonic():
    atlas = SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=3,
                          codepoints=range(ord('A'), ord('Z') + 1))
    atlas.generate()
    w1, _ = atlas.text_bounds("A")
    w2, _ = atlas.text_bounds("AB")
    w3, _ = atlas.text_bounds("ABC")
    assert w1 < w2 < w3


def test_atlas_text_bounds_empty():
    atlas = SDFGlyphAtlas(font_path=None, size_px=14, sdf_radius=3,
                          codepoints=range(ord('A'), ord('C') + 1))
    w, h = atlas.text_bounds("")
    assert w == 0
    assert h == 14


def test_atlas_ctor_validation():
    with pytest.raises(ValueError):
        SDFGlyphAtlas(font_path=None, size_px=0)
    with pytest.raises(ValueError):
        SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=0)


# ---------------------------------------------------------------------------
# SDFTextRenderer
# ---------------------------------------------------------------------------


def test_text_mesh_vertex_count():
    atlas = SDFGlyphAtlas(font_path=None, size_px=16, sdf_radius=4,
                          codepoints=range(ord('A'), ord('Z') + 1))
    atlas.generate()
    r = SDFTextRenderer()
    mesh = r.build_text_mesh("HELLO", (10.0, 20.0), 16, atlas)
    assert isinstance(mesh, TextMesh)
    assert mesh.positions.shape == (4 * 5, 2)
    assert mesh.uvs.shape == (4 * 5, 2)
    assert mesh.indices.shape == (6 * 5,)


def test_text_mesh_empty_string():
    atlas = SDFGlyphAtlas(font_path=None, size_px=12, sdf_radius=3,
                          codepoints=range(ord('A'), ord('C') + 1))
    r = SDFTextRenderer()
    mesh = r.build_text_mesh("", (0.0, 0.0), 12, atlas)
    assert mesh.positions.shape == (0, 2)
    assert mesh.indices.shape == (0,)


def test_text_mesh_indices_are_valid():
    atlas = SDFGlyphAtlas(font_path=None, size_px=16, sdf_radius=4,
                          codepoints=range(ord('A'), ord('Z') + 1))
    atlas.generate()
    r = SDFTextRenderer()
    mesh = r.build_text_mesh("ABC", (0.0, 0.0), 16, atlas)
    assert mesh.indices.max() < len(mesh.positions)


# ---------------------------------------------------------------------------
# WGSL shader
# ---------------------------------------------------------------------------


def test_wgsl_has_fragment_and_smoothstep():
    assert "@fragment" in SDF_TEXT_WGSL
    assert "smoothstep" in SDF_TEXT_WGSL


def test_wgsl_has_vertex_entry():
    assert "@vertex" in SDF_TEXT_WGSL
    assert "vs_main" in SDF_TEXT_WGSL
    assert "fs_main" in SDF_TEXT_WGSL


def test_wgsl_byte_budget():
    # ~800 byte budget — accept ±50%.
    n = len(SDF_TEXT_WGSL.encode("utf-8"))
    assert 400 <= n <= 1200, f"WGSL size {n} outside budget"


def test_wgsl_samples_atlas():
    assert "textureSample" in SDF_TEXT_WGSL
    assert "texture_2d" in SDF_TEXT_WGSL
