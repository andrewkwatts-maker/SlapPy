"""Tests for slappyengine.asset_import (HH5).

Covers the dispatcher, obj / texture importers, soft-import behaviour
for gltf, and stub behaviour for fbx/ply/stl.
"""
from __future__ import annotations

import io
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slappyengine.asset_import import (
    AssetImportDispatcher,
    ImportDependencyError,
    ImportResult,
    TextureData,
    import_asset,
    import_fbx,
    import_gltf,
    import_obj,
    import_ply,
    import_stl,
    import_texture,
    load_model,
    load_texture,
)
from slappyengine.asset_import.samples import TRIANGLE_OBJ


# ---------------------------------------------------------------------------
# Dispatcher — extension classification
# ---------------------------------------------------------------------------

def test_dispatcher_classifies_obj():
    d = AssetImportDispatcher()
    assert d.classify("model.obj") == "mesh"


def test_dispatcher_classifies_gltf():
    d = AssetImportDispatcher()
    assert d.classify("scene.gltf") == "mesh"
    assert d.classify("scene.glb") == "mesh"


def test_dispatcher_classifies_fbx_ply_stl():
    d = AssetImportDispatcher()
    assert d.classify("body.fbx") == "mesh"
    assert d.classify("pointcloud.ply") == "mesh"
    assert d.classify("part.stl") == "mesh"


def test_dispatcher_classifies_texture_extensions():
    d = AssetImportDispatcher()
    for ext in ("png", "jpg", "jpeg", "webp", "tga"):
        assert d.classify(f"tex.{ext}") == "texture", ext


def test_dispatcher_classifies_uppercase_extensions():
    """Extensions must be treated case-insensitively."""
    d = AssetImportDispatcher()
    assert d.classify("MODEL.OBJ") == "mesh"
    assert d.classify("Photo.PNG") == "texture"


def test_dispatcher_classifies_unknown():
    d = AssetImportDispatcher()
    assert d.classify("archive.zip") == "unknown"
    assert d.classify("doc.pdf") == "unknown"


def test_dispatcher_unknown_extension_raises(tmp_path):
    d = AssetImportDispatcher()
    p = tmp_path / "weird.xyz"
    p.write_bytes(b"not a real asset")
    with pytest.raises(ImportError) as ei:
        d.import_asset(p)
    assert ".xyz" in str(ei.value)
    # Message should list at least one supported extension.
    assert ".obj" in str(ei.value)


def test_dispatcher_missing_file_raises(tmp_path):
    d = AssetImportDispatcher()
    with pytest.raises(FileNotFoundError):
        d.import_asset(tmp_path / "nope.obj")


def test_dispatcher_supported_extensions_exposed():
    exts = set(AssetImportDispatcher.SUPPORTED_EXTENSIONS)
    for e in (".obj", ".gltf", ".glb", ".png", ".jpg", ".fbx", ".ply", ".stl"):
        assert e in exts, e


def test_dispatcher_register_custom_extension(tmp_path):
    d = AssetImportDispatcher()
    called = {}

    def fake(path):
        called["path"] = path
        return ImportResult(kind="mesh")

    d.register(".foo", fake)
    p = tmp_path / "x.foo"
    p.write_text("hi")
    r = d.import_asset(p)
    assert r.kind == "mesh"
    assert Path(called["path"]).name == "x.foo"


# ---------------------------------------------------------------------------
# import_obj
# ---------------------------------------------------------------------------

def test_import_obj_sample_triangle():
    """Ship-with-package triangle.obj: 3 verts, 1 tri."""
    r = import_obj(TRIANGLE_OBJ)
    assert r.kind == "mesh"
    assert len(r.meshes) == 1
    mesh = r.meshes[0]
    # Support both GpuMesh and dict-fallback outputs.
    if isinstance(mesh, dict):
        assert mesh["vertex_count"] == 3
        assert mesh["triangle_count"] == 1
    else:
        # GpuMesh — indices attr contains 3 items for 1 triangle.
        assert len(mesh._indices) == 3
        assert len(mesh._vertices) == 3
    assert r.metadata["position_count"] == 3
    assert r.metadata["source_path"].endswith("triangle.obj")


def test_import_obj_v_vt_vn_indices(tmp_path):
    """f a/b/c d/e/f g/h/i — full triplets."""
    src = tmp_path / "tri.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 0 1 0
        vt 0 0
        vt 1 0
        vt 0 1
        vn 0 0 1
        vn 0 0 1
        vn 0 0 1
        f 1/1/1 2/2/2 3/3/3
    """))
    r = import_obj(src)
    mesh = r.meshes[0]
    tri_count = mesh["triangle_count"] if isinstance(mesh, dict) else len(mesh._indices) // 3
    assert tri_count == 1


def test_import_obj_ngon_quad_triangulation(tmp_path):
    """A quad face `f 1 2 3 4` should produce 2 tris."""
    src = tmp_path / "quad.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 1 1 0
        v 0 1 0
        f 1 2 3 4
    """))
    r = import_obj(src)
    mesh = r.meshes[0]
    tri_count = mesh["triangle_count"] if isinstance(mesh, dict) else len(mesh._indices) // 3
    assert tri_count == 2


def test_import_obj_ngon_pentagon_triangulation(tmp_path):
    """A pentagon face should produce 3 tris (fan triangulation)."""
    src = tmp_path / "pent.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 1.5 1 0
        v 0.5 2 0
        v -0.5 1 0
        f 1 2 3 4 5
    """))
    r = import_obj(src)
    mesh = r.meshes[0]
    tri_count = mesh["triangle_count"] if isinstance(mesh, dict) else len(mesh._indices) // 3
    assert tri_count == 3


def test_import_obj_position_only_face(tmp_path):
    """f 1 2 3 (no /uv/nrm) should still work."""
    src = tmp_path / "pos.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 0 1 0
        f 1 2 3
    """))
    r = import_obj(src)
    assert len(r.meshes) == 1


def test_import_obj_position_and_normal_only(tmp_path):
    """f 1//1 2//2 3//3 — no UV."""
    src = tmp_path / "posnrm.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 0 1 0
        vn 0 0 1
        vn 0 0 1
        vn 0 0 1
        f 1//1 2//2 3//3
    """))
    r = import_obj(src)
    assert len(r.meshes) == 1


def test_import_obj_negative_indices(tmp_path):
    """Negative indices count backwards from the current list length."""
    src = tmp_path / "neg.obj"
    src.write_text(textwrap.dedent("""\
        v 0 0 0
        v 1 0 0
        v 0 1 0
        f -3 -2 -1
    """))
    r = import_obj(src)
    mesh = r.meshes[0]
    tri_count = mesh["triangle_count"] if isinstance(mesh, dict) else len(mesh._indices) // 3
    assert tri_count == 1


def test_import_obj_multiple_meshes_via_usemtl(tmp_path):
    """Two `usemtl` groups → two meshes."""
    src = tmp_path / "multi.obj"
    src.write_text(textwrap.dedent("""\
        mtllib scene.mtl
        v 0 0 0
        v 1 0 0
        v 0 1 0
        v 2 0 0
        v 3 0 0
        v 2 1 0
        usemtl red
        f 1 2 3
        usemtl blue
        f 4 5 6
    """))
    r = import_obj(src)
    assert len(r.meshes) == 2
    assert len(r.materials) == 2
    assert r.materials[0]["name"] == "red"
    assert r.materials[1]["name"] == "blue"
    assert r.materials[0]["mtllib"] == "scene.mtl"


def test_import_obj_ignores_comments_and_blank_lines(tmp_path):
    src = tmp_path / "cmt.obj"
    src.write_text(textwrap.dedent("""\
        # this is a comment

        v 0 0 0
        # another
        v 1 0 0

        v 0 1 0
        f 1 2 3
    """))
    r = import_obj(src)
    assert r.metadata["position_count"] == 3


def test_import_obj_metadata_timing(tmp_path):
    r = import_obj(TRIANGLE_OBJ)
    assert "load_ms" in r.metadata
    assert r.metadata["load_ms"] >= 0.0
    assert r.metadata["importer_used"] == "import_obj"


# ---------------------------------------------------------------------------
# import_texture
# ---------------------------------------------------------------------------

def _write_png(path: Path, w: int, h: int, mode: str = "RGBA", fill=(255, 128, 64, 255)):
    if mode == "RGB":
        Image.new("RGB", (w, h), fill[:3]).save(str(path))
    else:
        Image.new("RGBA", (w, h), fill).save(str(path))


def test_import_texture_rgba_png(tmp_path):
    p = tmp_path / "img.png"
    _write_png(p, 16, 8, "RGBA")
    r = import_texture(p)
    assert r.kind == "texture"
    assert len(r.textures) == 1
    tex = r.textures[0]
    assert tex.width == 16 and tex.height == 8
    assert tex.channels == 4
    assert tex.format == "RGBA"
    assert tex.pixels.shape == (8, 16, 4)
    assert tex.pixels.dtype == np.uint8


def test_import_texture_rgb_png(tmp_path):
    p = tmp_path / "img_rgb.png"
    _write_png(p, 4, 4, "RGB")
    r = import_texture(p)
    tex = r.textures[0]
    assert tex.channels == 3
    assert tex.format == "RGB"
    assert tex.pixels.shape == (4, 4, 3)


def test_import_texture_grayscale(tmp_path):
    p = tmp_path / "gray.png"
    Image.new("L", (5, 5), 128).save(str(p))
    r = import_texture(p)
    tex = r.textures[0]
    assert tex.channels == 1
    assert tex.format == "grayscale"


def test_import_texture_metadata(tmp_path):
    p = tmp_path / "meta.png"
    _write_png(p, 2, 3, "RGB")
    r = import_texture(p)
    assert r.metadata["source_path"] == str(p)
    assert r.metadata["importer_used"] == "import_texture"
    assert r.metadata["width"] == 2
    assert r.metadata["height"] == 3


# ---------------------------------------------------------------------------
# Dispatcher — end-to-end
# ---------------------------------------------------------------------------

def test_dispatcher_dispatches_obj_to_import_obj():
    r = import_asset(TRIANGLE_OBJ)
    assert r.kind == "mesh"
    assert r.metadata["importer_used"] == "import_obj"


def test_dispatcher_dispatches_png_to_import_texture(tmp_path):
    p = tmp_path / "d.png"
    _write_png(p, 2, 2)
    r = import_asset(p)
    assert r.kind == "texture"
    assert r.metadata["importer_used"] == "import_texture"


def test_load_model_returns_first_mesh():
    handle = load_model(TRIANGLE_OBJ)
    assert handle is not None
    # Handle should be usable — either GpuMesh or dict fallback.
    assert hasattr(handle, "_vertices") or (isinstance(handle, dict) and "vertices" in handle)


def test_load_texture_returns_first_texture(tmp_path):
    p = tmp_path / "lt.png"
    _write_png(p, 3, 3)
    tex = load_texture(p)
    assert isinstance(tex, TextureData)
    assert tex.width == 3


# ---------------------------------------------------------------------------
# ImportResult dataclass
# ---------------------------------------------------------------------------

def test_import_result_defaults():
    r = ImportResult(kind="mesh")
    assert r.meshes == []
    assert r.textures == []
    assert r.materials == []
    assert r.hierarchy == []
    assert r.metadata == {}


def test_import_result_primary_helpers():
    r = ImportResult(kind="mesh")
    assert r.primary_mesh is None
    assert r.primary_texture is None
    r.meshes.append("m0")
    r.textures.append(
        TextureData(np.zeros((1, 1, 3), dtype=np.uint8), 1, 1, 3, "RGB")
    )
    assert r.primary_mesh == "m0"
    assert isinstance(r.primary_texture, TextureData)


def test_texture_data_dataclass_normalises_channels():
    """If pixels shape disagrees with channels, __post_init__ fixes it."""
    px = np.zeros((4, 4, 4), dtype=np.uint8)
    tex = TextureData(pixels=px, width=4, height=4, channels=3, format="RGBA")
    # __post_init__ should have corrected channels to 4 to match shape.
    assert tex.channels == 4


# ---------------------------------------------------------------------------
# Stub importers (soft) — must not crash even without optional deps
# ---------------------------------------------------------------------------

def test_import_fbx_stub_does_not_crash(tmp_path, caplog):
    p = tmp_path / "empty.fbx"
    p.write_bytes(b"")
    r = import_fbx(p)
    # Even if no parser is present, we get a valid (empty) result.
    assert r.kind == "mesh"
    assert isinstance(r.meshes, list)
    assert r.metadata["importer_used"] == "import_fbx"


def test_import_ply_stub_does_not_crash(tmp_path):
    p = tmp_path / "empty.ply"
    p.write_bytes(b"")
    r = import_ply(p)
    assert r.kind == "mesh"
    assert r.metadata["importer_used"] == "import_ply"


def test_import_stl_stub_does_not_crash(tmp_path):
    p = tmp_path / "empty.stl"
    p.write_bytes(b"")
    r = import_stl(p)
    assert r.kind == "mesh"
    assert r.metadata["importer_used"] == "import_stl"


# ---------------------------------------------------------------------------
# gltf soft-import behaviour
# ---------------------------------------------------------------------------

def test_import_gltf_missing_dep_raises_helpfully(monkeypatch, tmp_path):
    """When pygltflib is unavailable we surface an ImportDependencyError
    with a pip-install hint."""
    # Remove pygltflib from the module cache and block re-import.
    monkeypatch.setitem(sys.modules, "pygltflib", None)
    p = tmp_path / "x.gltf"
    p.write_text('{"asset": {"version": "2.0"}}')
    try:
        import pygltflib as _real  # noqa: F401
        # pygltflib is genuinely installed — we can't easily fake its
        # absence past monkeypatching sys.modules. Skip cleanly.
        pytest.skip("pygltflib is installed; can't test missing-dep path")
    except ImportError:
        with pytest.warns(UserWarning, match="pygltflib"):
            with pytest.raises(ImportDependencyError) as ei:
                import_gltf(p)
        assert "pip install" in str(ei.value).lower()


def test_import_gltf_dispatch_dispatcher(tmp_path):
    """A .gltf path routes through the dispatcher regardless of whether
    pygltflib is installed. If it isn't, we get ImportDependencyError."""
    p = tmp_path / "d.gltf"
    p.write_text('{"asset": {"version": "2.0"}}')
    try:
        import pygltflib  # noqa: F401
    except ImportError:
        with pytest.raises(ImportDependencyError):
            import_asset(p)
        return
    # If pygltflib IS installed, a minimal empty gltf should parse into
    # an empty scene.
    r = import_asset(p)
    assert r.kind == "scene"


# ---------------------------------------------------------------------------
# Top-level module exports (HH1 coordination)
# ---------------------------------------------------------------------------

def test_top_level_load_model_export():
    """slappyengine.load_model should exist and delegate correctly."""
    import slappyengine
    handle = slappyengine.load_model(TRIANGLE_OBJ)
    assert handle is not None


def test_top_level_load_texture_export(tmp_path):
    """slappyengine.load_texture should exist and delegate correctly.

    HH1's App-level load_texture returns a TextureHandle wrapper; HH5's
    dispatcher-level import_texture returns TextureData. Both surfaces
    co-exist; users pick which they want. The top-level slappyengine
    shim currently exposes HH1's TextureHandle (registered first).
    """
    import slappyengine
    p = tmp_path / "tlt.png"
    _write_png(p, 4, 4)
    tex = slappyengine.load_texture(p)
    # Accept either surface (HH1 TextureHandle or HH5 TextureData).
    assert tex is not None
    assert hasattr(tex, "path") or hasattr(tex, "pixels")


def test_top_level_import_asset_export():
    import slappyengine
    r = slappyengine.import_asset(TRIANGLE_OBJ)
    assert isinstance(r, ImportResult)


def test_top_level_dispatcher_class_export():
    import slappyengine
    d = slappyengine.AssetImportDispatcher()
    assert d.classify("x.obj") == "mesh"


# ---------------------------------------------------------------------------
# ImportResult "handle" semantics — user asked for move/position/update
# ---------------------------------------------------------------------------

def test_mesh_handle_is_reusable():
    """Two calls to load_model should return independent handles."""
    a = load_model(TRIANGLE_OBJ)
    b = load_model(TRIANGLE_OBJ)
    assert a is not b


def test_texture_data_pixels_are_numpy(tmp_path):
    """pixels is a numpy array — HH4 renderer needs this contract."""
    p = tmp_path / "np.png"
    _write_png(p, 8, 8)
    tex = load_texture(p)
    assert isinstance(tex.pixels, np.ndarray)
    assert tex.pixels.dtype == np.uint8
