"""Tests for CCC3 — asset import drop panel + type router.

Covers:

* :func:`import_by_extension` dispatches correctly for each of the 8
  extension families the router recognises (textures, HDR, cubemap,
  shader, OBJ mesh, glTF scene, MTL library, YAML, script).
* Unsupported extensions produce ``kind="unsupported"`` without raising.
* Thumbnail generators return ``(128, 128, 4)`` uint8 ndarrays.
* :class:`AssetImportPanel` builds under a headless DPG stub.
* Dropping a mock PNG produces one thumbnail card.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Sample assets shipped under pharos_engine.asset_import.samples
# ---------------------------------------------------------------------------

from pharos_engine.asset_import.samples import (
    TRIANGLE_MTL,
    TRIANGLE_OBJ,
)
from pharos_engine.asset_import.type_router import (
    THUMBNAIL_SIZE,
    ImportRouteResult,
    ScriptHandle,
    ShaderHandle,
    generic_thumbnail,
    import_by_extension,
    material_thumbnail,
    mesh_thumbnail,
    shader_thumbnail,
    supported_extensions,
    texture_thumbnail,
)


# ---------------------------------------------------------------------------
# Fixture: a small PNG on disk. Uses PIL because that's what the
# existing importer uses too — the test-suite already depends on it.
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_png(tmp_path):
    from PIL import Image

    p = tmp_path / "tiny.png"
    Image.new("RGBA", (4, 4), (200, 100, 50, 255)).save(p)
    return p


@pytest.fixture
def tiny_shader(tmp_path):
    p = tmp_path / "unlit.wgsl"
    p.write_text(
        "@vertex fn vs_main() -> @builtin(position) vec4<f32> {\n"
        "    return vec4<f32>(0.0, 0.0, 0.0, 1.0);\n"
        "}\n"
        "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "    return vec4<f32>(1.0, 0.5, 0.0, 1.0);\n"
        "}\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def tiny_yaml_material(tmp_path):
    p = tmp_path / "asphalt.material.yaml"
    p.write_text(
        "kind: material\nbaseColor: [0.3, 0.3, 0.3]\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def tiny_script(tmp_path):
    p = tmp_path / "helper.py"
    p.write_text("def hello():\n    return 'ok'\n", encoding="utf-8")
    return p


@pytest.fixture
def tiny_hdr(tmp_path):
    # No imageio dep — write a stub .hdr; router will fall back gracefully.
    p = tmp_path / "sky.hdr"
    p.write_bytes(b"NOT A REAL HDR")
    return p


@pytest.fixture
def tiny_ktx2(tmp_path):
    p = tmp_path / "sky.ktx2"
    p.write_bytes(b"NOT A REAL KTX2")
    return p


# ---------------------------------------------------------------------------
# type_router — extension dispatch.
# ---------------------------------------------------------------------------


class TestSupportedExtensions:
    def test_supported_extension_families_present(self):
        exts = supported_extensions()
        for ext in (
            ".png", ".jpg", ".jpeg", ".bmp", ".tga",
            ".hdr", ".exr",
            ".ktx2",
            ".wgsl",
            ".obj",
            ".gltf", ".glb",
            ".mtl",
            ".yaml", ".yml",
            ".py",
        ):
            assert ext in exts, ext


class TestImportByExtension:
    def test_dispatches_png(self, tiny_png):
        result = import_by_extension(tiny_png)
        assert result.kind == "texture"
        assert result.handle is not None
        assert result.thumbnail.shape == (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4)
        assert result.error == ""

    def test_dispatches_obj(self):
        result = import_by_extension(TRIANGLE_OBJ)
        assert result.kind == "mesh"
        assert result.thumbnail.shape == (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4)

    def test_dispatches_mtl(self):
        result = import_by_extension(TRIANGLE_MTL)
        assert result.kind == "material_library"
        assert isinstance(result.handle, dict)

    def test_dispatches_wgsl(self, tiny_shader):
        result = import_by_extension(tiny_shader)
        assert result.kind == "shader"
        assert isinstance(result.handle, ShaderHandle)
        assert "vertex" in result.handle.entry_points
        assert "fragment" in result.handle.entry_points

    def test_dispatches_yaml_material(self, tiny_yaml_material):
        result = import_by_extension(tiny_yaml_material)
        assert result.kind == "material"
        assert isinstance(result.handle, dict)
        assert result.handle["baseColor"] == [0.3, 0.3, 0.3]

    def test_dispatches_py_script(self, tiny_script):
        result = import_by_extension(tiny_script)
        assert result.kind == "script"
        assert isinstance(result.handle, ScriptHandle)
        assert result.handle.module_name == "helper"

    def test_dispatches_hdr_gracefully(self, tiny_hdr):
        # imageio is optional; this must never raise. If imageio can't
        # decode the placeholder bytes the router still returns a
        # well-formed HDR result envelope with a thumbnail.
        result = import_by_extension(tiny_hdr)
        assert result.kind == "hdr_texture"
        assert result.thumbnail.shape == (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4)

    def test_dispatches_ktx2_gracefully(self, tiny_ktx2):
        result = import_by_extension(tiny_ktx2)
        assert result.kind == "cubemap"
        assert result.thumbnail.shape == (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4)

    def test_dispatches_glb_extension_registered(self):
        # We don't need a real .glb to prove routing; the router should
        # fall through to _route_gltf which raises → captured as error.
        result = import_by_extension("does_not_exist.glb")
        # Either "error" (importer raised) or "scene" — never
        # "unsupported": the point is the extension is *known*.
        assert result.kind in ("scene", "error")

    def test_unsupported_extension(self, tmp_path):
        p = tmp_path / "archive.zip"
        p.write_bytes(b"pk")
        result = import_by_extension(p)
        assert result.kind == "unsupported"
        assert "unsupported" in result.error.lower()
        # Router must not crash — thumbnail is still shaped.
        assert result.thumbnail.shape == (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4)


# ---------------------------------------------------------------------------
# Thumbnail generators — shape + dtype invariant.
# ---------------------------------------------------------------------------


class TestThumbnails:
    def test_generic_thumbnail_shape(self):
        thumb = generic_thumbnail()
        assert thumb.shape == (128, 128, 4)
        assert thumb.dtype == np.uint8

    def test_shader_thumbnail_shape(self):
        thumb = shader_thumbnail("WGSL")
        assert thumb.shape == (128, 128, 4)
        assert thumb.dtype == np.uint8

    def test_material_thumbnail_shape(self):
        thumb = material_thumbnail((0.4, 0.7, 0.2))
        assert thumb.shape == (128, 128, 4)
        assert thumb.dtype == np.uint8
        # The border is dark; the interior carries the swatch colour.
        center = thumb[64, 64]
        assert center[0] > 50 and center[1] > 100 and center[2] > 20

    def test_texture_thumbnail_from_ndarray(self):
        src = np.full((32, 32, 4), 128, dtype=np.uint8)
        thumb = texture_thumbnail(src)
        assert thumb.shape == (128, 128, 4)
        assert thumb.dtype == np.uint8

    def test_mesh_thumbnail_from_result(self):
        result = import_by_extension(TRIANGLE_OBJ)
        thumb = mesh_thumbnail(result.handle)
        assert thumb.shape == (128, 128, 4)


# ---------------------------------------------------------------------------
# AssetImportPanel — headless DPG stub build + drop behaviour.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}

    def _track(self, name, args, kwargs):
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM(self.calls, "child_window")

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM(self.calls, "group")

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM(self.calls, "popup")

    def file_dialog(self, *a, **kw):
        self._track("file_dialog", a, kw)
        return _StubCM(self.calls, "file_dialog")

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_menu_item(self, *a, **kw):
        self._track("add_menu_item", a, kw)

    def add_file_extension(self, *a, **kw):
        self._track("add_file_extension", a, kw)

    def add_image(self, *a, **kw):
        self._track("add_image", a, kw)

    def add_static_texture(self, *a, **kw):
        self._track("add_static_texture", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def add_texture_registry(self, *a, **kw):
        self._track("add_texture_registry", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        if isinstance(tag, str):
            self.values[tag] = value

    def set_clipboard_text(self, *a, **kw):
        self._track("set_clipboard_text", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name: str):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "child_window", "group", "popup", "file_dialog",
        "add_text", "add_button", "add_menu_item", "add_file_extension",
        "add_image", "add_static_texture", "add_texture_registry",
        "set_value", "set_clipboard_text",
        "does_item_exist", "delete_item",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


try:
    from pharos_editor.ui.editor.asset_import_panel import (
        AssetImportPanel,
        ImportedAssetCard,
        type_badge,
    )
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"AssetImportPanel not importable: {_err}",
        allow_module_level=True,
    )


class TestPanelConstruction:
    def test_constructs_without_dpg(self):
        panel = AssetImportPanel()
        assert panel.TITLE == "Asset Import"
        assert panel.cards == []

    def test_supported_extensions_exposed(self):
        panel = AssetImportPanel()
        exts = panel.get_supported_extensions()
        assert ".png" in exts
        assert ".wgsl" in exts

    def test_type_badge_lookup(self):
        assert type_badge("texture") == "TEX"
        assert type_badge("shader") == "WGSL"
        assert type_badge("unsupported") == "?"


class TestPanelBuild:
    def test_build_runs_without_dpg_errors(self, stub_dpg):
        panel = AssetImportPanel()
        panel.build("parent_x")
        # The root child_window tag is registered.
        assert panel._panel_tag in stub_dpg.items
        # Drop-zone + status + grid all constructed.
        assert panel._drop_zone_tag in stub_dpg.items
        assert panel._grid_tag in stub_dpg.items


class TestPanelDrop:
    def test_drop_single_png_produces_one_card(self, stub_dpg, tiny_png):
        panel = AssetImportPanel(asset_database=_FakeDB())
        panel.build("parent_x")
        cards = panel.on_paths_dropped([tiny_png])
        assert len(cards) == 1
        assert cards[0].kind == "texture"
        assert cards[0].thumbnail.shape == (128, 128, 4)
        assert len(panel.cards) == 1

    def test_drop_batch_survives_unsupported(self, stub_dpg, tiny_png, tmp_path):
        weird = tmp_path / "thing.zip"
        weird.write_bytes(b"pk")
        panel = AssetImportPanel(asset_database=_FakeDB())
        panel.build("parent_x")
        cards = panel.on_paths_dropped([tiny_png, weird])
        assert len(cards) == 2
        assert cards[0].kind == "texture"
        assert cards[1].kind == "unsupported"

    def test_remove_card(self, stub_dpg, tiny_png):
        panel = AssetImportPanel(asset_database=_FakeDB())
        panel.build("parent_x")
        [card] = panel.on_paths_dropped([tiny_png])
        assert panel.remove_card(card.card_id) is True
        assert panel.cards == []

    def test_clear_empties_grid(self, stub_dpg, tiny_png, tiny_shader):
        panel = AssetImportPanel(asset_database=_FakeDB())
        panel.build("parent_x")
        panel.on_paths_dropped([tiny_png, tiny_shader])
        assert len(panel.cards) == 2
        panel.clear()
        assert panel.cards == []

    def test_add_to_scene_callback_fires(self, stub_dpg, tiny_png):
        received: list[ImportedAssetCard] = []
        panel = AssetImportPanel(
            asset_database=_FakeDB(),
            on_add_to_scene=received.append,
        )
        panel.build("parent_x")
        [card] = panel.on_paths_dropped([tiny_png])
        panel._add_to_scene(card)
        assert received == [card]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeDB:
    """Minimal AssetDatabase stand-in for tests."""

    def __init__(self):
        self._handlers: dict[str, Any] = {}
        self.loaded: list[str] = []

    def register_handler(self, ext, loader):
        self._handlers[ext] = loader

    def load(self, path):
        self.loaded.append(str(path))
        return None
