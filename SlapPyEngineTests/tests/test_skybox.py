"""Tests for slappyengine.render.skybox + asset_import.cubemap_importer (KK4).

Sprint 11 of the Nova3D parity plan. Covers CubemapData validity, the
procedural gradient sky generator, cubemap sampling, PNG-directory and
YAML-manifest import paths, WGSL surface, and the Skybox draw hook.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from slappyengine.asset_import import (
    AssetImportDispatcher,
    import_cubemap,
    import_hdr_cubemap,
)
from slappyengine.asset_import.cubemap_importer import FACE_KEYS
from slappyengine.render import (
    Camera3D,
    NullRenderer,
    SKYBOX_WGSL,
    CubeFace,
    CubemapData,
    Skybox,
    procedural_gradient_sky,
    sample_direction_from_cubemap,
)


# ---------------------------------------------------------------------------
# CubemapData basics
# ---------------------------------------------------------------------------
def test_cubemap_data_defaults():
    cm = CubemapData()
    assert cm.resolution == 1
    assert cm.format == "rgba8"
    assert set(cm.faces.keys()) == {
        CubeFace.POSX, CubeFace.NEGX,
        CubeFace.POSY, CubeFace.NEGY,
        CubeFace.POSZ, CubeFace.NEGZ,
    }
    for face_arr in cm.faces.values():
        assert face_arr.shape == (1, 1, 4)
        assert face_arr.dtype == np.uint8


def test_cubemap_data_rejects_non_square_face():
    bad = np.zeros((16, 8, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        CubemapData(faces={CubeFace.POSX: bad}, resolution=16)


def test_cubemap_data_rejects_wrong_channel_count():
    bad = np.zeros((4, 4, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        CubemapData(faces={CubeFace.POSX: bad}, resolution=4)


def test_cubemap_data_power_of_two_flag():
    assert CubemapData(resolution=256).is_power_of_two
    assert not CubemapData(resolution=100).is_power_of_two


# ---------------------------------------------------------------------------
# procedural_gradient_sky
# ---------------------------------------------------------------------------
def test_procedural_gradient_sky_returns_six_valid_faces():
    sky = procedural_gradient_sky(resolution=32)
    assert isinstance(sky, CubemapData)
    assert sky.resolution == 32
    assert len(sky.faces) == 6
    for face, arr in sky.faces.items():
        assert arr.shape == (32, 32, 4), f"face {face.name} bad shape {arr.shape}"
        assert arr.dtype == np.uint8
        # Alpha channel is always 255.
        assert np.all(arr[..., 3] == 255)


def test_procedural_gradient_sky_top_uses_top_color():
    top = (1.0, 0.0, 0.0)  # pure red
    horizon = (0.0, 1.0, 0.0)
    ground = (0.0, 0.0, 1.0)
    sky = procedural_gradient_sky(top, horizon, ground, resolution=32)
    r, g, b, _ = sample_direction_from_cubemap((0.0, 1.0, 0.0), sky)
    assert r > 0.9
    assert g < 0.1
    assert b < 0.1


def test_procedural_gradient_sky_ground_uses_ground_color():
    top = (1.0, 0.0, 0.0)
    horizon = (0.0, 1.0, 0.0)
    ground = (0.0, 0.0, 1.0)  # pure blue
    sky = procedural_gradient_sky(top, horizon, ground, resolution=32)
    r, g, b, _ = sample_direction_from_cubemap((0.0, -1.0, 0.0), sky)
    assert b > 0.9
    assert r < 0.1
    assert g < 0.1


def test_procedural_gradient_sky_zero_resolution_rejected():
    with pytest.raises(ValueError):
        procedural_gradient_sky(resolution=0)


# ---------------------------------------------------------------------------
# sample_direction_from_cubemap
# ---------------------------------------------------------------------------
def test_sample_direction_plus_x_hits_posx_face():
    # Paint POSX pure red, everything else black.
    faces = {face: np.zeros((4, 4, 4), dtype=np.uint8) for face in CubeFace}
    faces[CubeFace.POSX][..., 0] = 255
    faces[CubeFace.POSX][..., 3] = 255
    cm = CubemapData(faces=faces, resolution=4)
    r, g, b, a = sample_direction_from_cubemap((1.0, 0.0, 0.0), cm)
    assert r == 1.0
    assert g == 0.0
    assert b == 0.0
    assert a == 1.0


def test_sample_direction_minus_z_hits_negz_face():
    faces = {face: np.zeros((4, 4, 4), dtype=np.uint8) for face in CubeFace}
    faces[CubeFace.NEGZ][..., 1] = 255  # green
    faces[CubeFace.NEGZ][..., 3] = 255
    cm = CubemapData(faces=faces, resolution=4)
    r, g, b, _ = sample_direction_from_cubemap((0.0, 0.0, -1.0), cm)
    assert g == 1.0
    assert r == 0.0
    assert b == 0.0


def test_sample_direction_zero_vector_is_safe():
    cm = procedural_gradient_sky(resolution=8)
    result = sample_direction_from_cubemap((0.0, 0.0, 0.0), cm)
    assert len(result) == 4


# ---------------------------------------------------------------------------
# WGSL surface
# ---------------------------------------------------------------------------
def test_skybox_wgsl_has_vertex_and_fragment_entry_points():
    assert "@vertex" in SKYBOX_WGSL
    assert "@fragment" in SKYBOX_WGSL
    assert "vs_main" in SKYBOX_WGSL
    assert "fs_main" in SKYBOX_WGSL


def test_skybox_wgsl_samples_cubemap():
    assert "texture_cube" in SKYBOX_WGSL
    assert "textureSample" in SKYBOX_WGSL


def test_skybox_wgsl_under_budget():
    size = len(SKYBOX_WGSL.encode("utf-8"))
    # Spec says ~600 bytes. Give a comfortable ceiling below 1 KiB.
    assert size < 1024, f"SKYBOX_WGSL is {size} bytes, expected <1024"


def test_skybox_wgsl_pushes_depth_to_far_plane():
    # Vertex shader should force z = w so the resulting NDC z = 1.
    assert "c.z = c.w" in SKYBOX_WGSL or "clip.z = clip.w" in SKYBOX_WGSL


# ---------------------------------------------------------------------------
# Skybox class + NullRenderer draw hook
# ---------------------------------------------------------------------------
def test_skybox_geometry_has_twelve_triangles():
    sky = procedural_gradient_sky(resolution=8)
    box = Skybox(cubemap=sky)
    assert box.triangle_count == 12
    assert box.vertices.shape == (36, 3)


def test_skybox_view_matrix_no_translation_strips_position():
    cam = Camera3D(position=(10.0, 20.0, 30.0), look_at=(0.0, 0.0, 0.0))
    sky = procedural_gradient_sky(resolution=8)
    box = Skybox(cubemap=sky, camera=cam)
    v = box.view_matrix_no_translation()
    # Translation column should be zeroed.
    assert v[0, 3] == 0.0
    assert v[1, 3] == 0.0
    assert v[2, 3] == 0.0
    # Rotation block should still be non-trivial.
    rot = v[:3, :3]
    assert np.linalg.norm(rot) > 0.1


def test_skybox_render_records_draw_call_on_null_renderer():
    r = NullRenderer(window_size=(320, 240))
    cam = Camera3D(position=(0.0, 0.0, 5.0), look_at=(0.0, 0.0, 0.0))
    sky = procedural_gradient_sky(resolution=16)
    box = Skybox(cubemap=sky, camera=cam)

    r.begin_frame()
    box.render(r, cam)
    r.end_frame()

    skybox_calls = [c for c in r.draw_log if c.kind == "skybox"]
    assert len(skybox_calls) == 1
    payload = skybox_calls[0].payload
    assert payload["triangle_count"] == 12
    assert payload["resolution"] == 16
    assert payload["format"] == "rgba8"
    assert payload["depth_write"] is False


# ---------------------------------------------------------------------------
# Cubemap importer — 6-PNG directory
# ---------------------------------------------------------------------------
def _write_face_png(path: Path, colour: tuple[int, int, int, int], size: int = 8) -> None:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0] = colour[0]
    arr[..., 1] = colour[1]
    arr[..., 2] = colour[2]
    arr[..., 3] = colour[3]
    Image.fromarray(arr, mode="RGBA").save(str(path))


def test_import_cubemap_from_six_png_directory(tmp_path):
    colours = {
        "posx": (255, 0, 0, 255),
        "negx": (0, 255, 0, 255),
        "posy": (0, 0, 255, 255),
        "negy": (255, 255, 0, 255),
        "posz": (255, 0, 255, 255),
        "negz": (0, 255, 255, 255),
    }
    for name, colour in colours.items():
        _write_face_png(tmp_path / f"{name}.png", colour)

    cm = import_cubemap(tmp_path)
    assert cm.resolution == 8
    # POSX should be red.
    assert cm.face(CubeFace.POSX)[0, 0, 0] == 255
    assert cm.face(CubeFace.POSX)[0, 0, 1] == 0
    # NEGZ should be cyan (0, 255, 255).
    assert cm.face(CubeFace.NEGZ)[0, 0, 1] == 255
    assert cm.face(CubeFace.NEGZ)[0, 0, 2] == 255


def test_import_cubemap_missing_face_raises(tmp_path):
    for name in ("posx", "negx", "posy", "negy", "posz"):
        _write_face_png(tmp_path / f"{name}.png", (255, 255, 255, 255))
    # Missing negz.png
    with pytest.raises(FileNotFoundError):
        import_cubemap(tmp_path)


def test_import_cubemap_from_yaml_manifest(tmp_path):
    faces_dir = tmp_path / "faces"
    faces_dir.mkdir()
    colours = {
        "posx": (255, 0, 0, 255),
        "negx": (0, 255, 0, 255),
        "posy": (0, 0, 255, 255),
        "negy": (128, 128, 0, 255),
        "posz": (128, 0, 128, 255),
        "negz": (0, 128, 128, 255),
    }
    for name, colour in colours.items():
        _write_face_png(faces_dir / f"{name}.png", colour, size=4)

    manifest_data = {name: f"faces/{name}.png" for name in FACE_KEYS}
    manifest_path = tmp_path / "sky.cubemap.yaml"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(manifest_data, fh)

    cm = import_cubemap(manifest_path)
    assert cm.resolution == 4
    assert cm.face(CubeFace.POSX)[0, 0, 0] == 255


def test_dispatcher_routes_cubemap_yaml(tmp_path):
    faces_dir = tmp_path / "faces"
    faces_dir.mkdir()
    for name in FACE_KEYS:
        _write_face_png(faces_dir / f"{name}.png", (200, 200, 200, 255), size=4)

    manifest_data = {name: f"faces/{name}.png" for name in FACE_KEYS}
    manifest_path = tmp_path / "world.cubemap.yaml"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(manifest_data, fh)

    d = AssetImportDispatcher()
    assert d.classify(manifest_path) == "cubemap"
    result = d.import_asset(manifest_path)
    assert result.kind == "cubemap"
    assert "cubemap" in result.metadata
    assert result.metadata["cubemap"].resolution == 4


def test_import_hdr_cubemap_fallback_returns_procedural(tmp_path):
    # Create a minimal .hdr placeholder; imageio may not decode this,
    # in which case the importer should fall back to a procedural sky
    # rather than raising.
    fake = tmp_path / "fake.hdr"
    fake.write_bytes(b"not-really-hdr")
    cm = import_hdr_cubemap(fake)
    assert isinstance(cm, CubemapData)
    assert cm.resolution > 0
    assert len(cm.faces) == 6


def test_cubemap_data_alpha_full_after_procedural():
    sky = procedural_gradient_sky(resolution=16)
    for face_arr in sky.faces.values():
        assert np.all(face_arr[..., 3] == 255)
