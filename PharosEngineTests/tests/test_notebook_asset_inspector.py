"""Tests for :class:`NotebookAssetInspector` (CC3).

Covers:

* Construction + defaults + editor ``__init__`` lazy hook.
* :meth:`set_asset_path` swaps layout by kind.
* Each asset kind renders without crash under a stub DPG.
* YAML parse handles corrupt files gracefully.
* Script preview respects ``max_preview_lines``.
* Texture preview via PIL (soft-imported).
* Refresh re-reads the file.
* Copy Path invokes the clipboard shim.
* Empty path shows placeholder text.
* :meth:`set_content_browser` routes selection through the browser slot.
* Material "Open in editor" callback fires.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors the Z1 / Z2 / BB3 test rigs).
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, object] = {}
        self.clipboard_text: str | None = None

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, tag, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        self.values[tag] = value

    def set_clipboard_text(self, text, *a, **kw):
        self._track("set_clipboard_text", (text,), kw)
        self.clipboard_text = text


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_input_text", "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value", "set_clipboard_text",
    ):
        setattr(mod, name, getattr(stub, name))
    mod.__slappy_stub__ = True

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_panel():
    from pharos_editor.ui.editor.notebook_asset_inspector import (
        NotebookAssetInspector,
    )

    def _factory(**kwargs):
        return NotebookAssetInspector(**kwargs)

    return _factory


@pytest.fixture
def script_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.py"
    lines = [
        "# top-level comment",
        "import os",
        "",
        "def greet(name):",
        "    # inline comment",
        "    return f'hello {name}'",
        "",
        "class Widget:",
        "    def __init__(self):",
        "        self.value = 0",
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


@pytest.fixture
def large_script_file(tmp_path: Path) -> Path:
    p = tmp_path / "large.py"
    p.write_text(
        "\n".join(f"x = {i}" for i in range(100)),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def scene_file(tmp_path: Path) -> Path:
    p = tmp_path / "level.scene.yaml"
    p.write_text(
        "entities:\n"
        "  - {name: hero, kind: player}\n"
        "  - {name: enemy1, kind: goblin}\n"
        "  - {name: enemy2, kind: goblin}\n"
        "layers:\n"
        "  - background\n"
        "  - main\n"
        "camera:\n"
        "  position: [1.0, 2.0, 3.0]\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def corrupt_scene(tmp_path: Path) -> Path:
    p = tmp_path / "broken.scene.yaml"
    p.write_text(
        "entities:\n  - name: hero\n    kind: player: garbage: [",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def texture_file(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.png"
    try:
        from PIL import Image
    except Exception:
        pytest.skip("PIL not available")
    img = Image.new("RGBA", (8, 8), (255, 0, 128, 255))
    img.save(p)
    return p


@pytest.fixture
def material_file(tmp_path: Path) -> Path:
    p = tmp_path / "brick.mat.yaml"
    p.write_text(
        "shader: standard_pbr\n"
        "name: brick\n"
        "wgsl: |\n"
        "  @fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "      return vec4<f32>(0.5, 0.3, 0.2, 1.0);\n"
        "  }\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def shader_file(tmp_path: Path) -> Path:
    p = tmp_path / "washi.wgsl"
    p.write_text(
        "@fragment\n"
        "fn fs_main() -> @location(0) vec4<f32> {\n"
        "    return vec4<f32>(1.0, 0.7, 0.8, 1.0);\n"
        "}\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def prefab_file(tmp_path: Path) -> Path:
    p = tmp_path / "crate.prefab.yaml"
    p.write_text(
        "name: crate\n"
        "nodes:\n"
        "  - {id: root, kind: box}\n"
        "  - {id: cap, kind: box}\n"
        "joints:\n"
        "  - {a: root, b: cap}\n"
        "bounding_box: [-1.0, -1.0, 1.0, 1.0]\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def other_file(tmp_path: Path) -> Path:
    p = tmp_path / "data.bin"
    p.write_bytes(bytes(range(70)))
    return p


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults(self, make_panel):
        panel = make_panel()
        assert panel.path is None
        assert panel.kind is None
        assert panel.max_preview_lines == 40
        assert panel.preview is None
        assert panel.is_empty is True

    def test_initial_path_binds(self, make_panel, script_file):
        panel = make_panel(path=script_file)
        assert panel.path == script_file
        assert panel.kind == "script"
        assert panel.preview is not None

    def test_rejects_bad_max_preview_lines(self, make_panel):
        with pytest.raises(ValueError):
            make_panel(max_preview_lines=0)
        with pytest.raises(ValueError):
            make_panel(max_preview_lines=-3)
        with pytest.raises(ValueError):
            make_panel(max_preview_lines="ten")

    def test_rejects_bad_on_open_material(self, make_panel):
        with pytest.raises(TypeError):
            make_panel(on_open_material="not-callable")

    def test_rejects_bad_clipboard_shim(self, make_panel):
        with pytest.raises(TypeError):
            make_panel(clipboard_shim=42)

    def test_title_and_min_size_constants(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            NotebookAssetInspector,
        )
        assert NotebookAssetInspector.TITLE == "Asset Inspector"
        assert NotebookAssetInspector.MIN_WIDTH >= 200
        assert NotebookAssetInspector.MIN_HEIGHT >= 200


# ===========================================================================
# Editor __init__ registration
# ===========================================================================


class TestEditorRegistration:
    def test_lazy_import_via_editor_init(self):
        from pharos_editor.ui.editor import NotebookAssetInspector
        panel = NotebookAssetInspector()
        assert panel.path is None

    def test_all_contains_asset_inspector_alphabetically(self):
        import pharos_editor.ui.editor as ed
        assert "NotebookAssetInspector" in ed.__all__
        # Between NodeGraphPanel and NotebookAutosavePanel.
        i_ng = ed.__all__.index("NodeGraphPanel")
        i_ai = ed.__all__.index("NotebookAssetInspector")
        i_av = ed.__all__.index("NotebookAutosavePanel")
        assert i_ng < i_ai < i_av

    def test_lazy_map_contains_module_path(self):
        from pharos_editor.ui.editor import _LAZY_MAP
        assert _LAZY_MAP["NotebookAssetInspector"] == (
            ".notebook_asset_inspector"
        )


# ===========================================================================
# Kind classification
# ===========================================================================


class TestClassifyAssetKind:
    def test_script(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("foo.py")) == "script"

    def test_scene(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("level.scene.yaml")) == "scene"
        assert classify_asset_kind(Path("level.scene.json")) == "scene"

    def test_texture(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("t.png")) == "texture"
        assert classify_asset_kind(Path("t.jpg")) == "texture"
        assert classify_asset_kind(Path("t.webp")) == "texture"

    def test_material(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("b.mat.yaml")) == "material"
        assert classify_asset_kind(Path("b.material.yaml")) == "material"

    def test_shader(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("s.wgsl")) == "shader"
        assert classify_asset_kind(Path("s.glsl")) == "shader"

    def test_prefab(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("c.prefab.yaml")) == "prefab"

    def test_other(self):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            classify_asset_kind,
        )
        assert classify_asset_kind(Path("readme.md")) == "other"
        assert classify_asset_kind(Path("data.bin")) == "other"


# ===========================================================================
# set_asset_path — dispatch by kind
# ===========================================================================


class TestSetAssetPath:
    def test_clears_on_none(self, make_panel, script_file):
        panel = make_panel(path=script_file)
        panel.set_asset_path(None)
        assert panel.path is None
        assert panel.preview is None
        assert panel.is_empty is True

    def test_rejects_bad_type(self, make_panel):
        panel = make_panel()
        with pytest.raises(TypeError):
            panel.set_asset_path(42)

    def test_script_populates_script_preview(self, make_panel, script_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            ScriptPreview,
        )
        panel = make_panel(path=script_file)
        assert isinstance(panel.preview, ScriptPreview)
        assert panel.preview.total_lines == 10
        assert not panel.preview.truncated

    def test_scene_populates_scene_preview(self, make_panel, scene_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            ScenePreview,
        )
        panel = make_panel(path=scene_file)
        assert isinstance(panel.preview, ScenePreview)
        assert panel.preview.entity_count == 3
        assert panel.preview.layer_count == 2
        assert panel.preview.camera_pos == (1.0, 2.0, 3.0)
        assert "hero" in panel.preview.entity_names

    def test_corrupt_scene_captures_error(self, make_panel, corrupt_scene):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            ScenePreview,
        )
        panel = make_panel(path=corrupt_scene)
        preview = panel.preview
        assert isinstance(preview, ScenePreview)
        assert preview.error is not None

    def test_texture_populates_texture_preview(self, make_panel, texture_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            TexturePreview,
        )
        panel = make_panel(path=texture_file)
        assert isinstance(panel.preview, TexturePreview)
        assert panel.preview.width == 8
        assert panel.preview.height == 8
        assert panel.preview.mode == "RGBA"

    def test_material_populates_material_preview(self, make_panel, material_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            MaterialPreview,
        )
        panel = make_panel(path=material_file)
        assert isinstance(panel.preview, MaterialPreview)
        assert panel.preview.shader_name == "standard_pbr"
        assert panel.preview.wgsl_bytes > 0

    def test_shader_populates_shader_preview(self, make_panel, shader_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            ShaderPreview,
        )
        panel = make_panel(path=shader_file)
        assert isinstance(panel.preview, ShaderPreview)
        assert panel.preview.byte_count > 0
        assert "fs_main" in panel.preview.source

    def test_prefab_populates_prefab_preview(self, make_panel, prefab_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            PrefabPreview,
        )
        panel = make_panel(path=prefab_file)
        assert isinstance(panel.preview, PrefabPreview)
        assert panel.preview.node_count == 2
        assert panel.preview.joint_count == 1
        assert panel.preview.bounding_box == (-1.0, -1.0, 1.0, 1.0)

    def test_other_populates_other_preview(self, make_panel, other_file):
        from pharos_editor.ui.editor.notebook_asset_inspector import (
            OtherPreview,
        )
        panel = make_panel(path=other_file)
        assert isinstance(panel.preview, OtherPreview)
        assert panel.preview.size_bytes == 70
        assert "00 01 02" in panel.preview.hex_dump

    def test_missing_file_captures_error(self, make_panel, tmp_path):
        panel = make_panel()
        panel.set_asset_path(tmp_path / "nonexistent.py")
        assert panel.preview_error is not None


# ===========================================================================
# max_preview_lines
# ===========================================================================


class TestMaxPreviewLines:
    def test_script_preview_respects_cap(self, make_panel, large_script_file):
        panel = make_panel(path=large_script_file, max_preview_lines=15)
        assert len(panel.preview.lines) == 15
        assert panel.preview.truncated is True
        assert panel.preview.total_lines == 100

    def test_set_max_preview_lines_reads_new_cap(
        self, make_panel, large_script_file,
    ):
        panel = make_panel(path=large_script_file, max_preview_lines=5)
        assert len(panel.preview.lines) == 5
        panel.set_max_preview_lines(20)
        assert panel.max_preview_lines == 20
        assert len(panel.preview.lines) == 20

    def test_rejects_bad_max_preview_lines(self, make_panel):
        panel = make_panel()
        with pytest.raises(ValueError):
            panel.set_max_preview_lines(0)
        with pytest.raises(ValueError):
            panel.set_max_preview_lines(-1)
        with pytest.raises(ValueError):
            panel.set_max_preview_lines(True)


# ===========================================================================
# Copy Path
# ===========================================================================


class TestCopyPath:
    def test_copy_path_none_when_empty(self, make_panel):
        panel = make_panel()
        assert panel.copy_path() is None

    def test_copy_path_invokes_shim(self, make_panel, script_file):
        captured: list[str] = []
        panel = make_panel(
            path=script_file, clipboard_shim=captured.append,
        )
        result = panel.copy_path()
        assert result == str(script_file)
        assert captured == [str(script_file)]

    def test_copy_path_stub_dpg_fallback(
        self, stub_dpg, make_panel, script_file,
    ):
        panel = make_panel(path=script_file)
        panel.copy_path()
        assert stub_dpg.clipboard_text == str(script_file)


# ===========================================================================
# Refresh
# ===========================================================================


class TestRefresh:
    def test_refresh_re_reads_the_file(self, make_panel, tmp_path):
        p = tmp_path / "s.py"
        p.write_text("x = 1\n", encoding="utf-8")
        panel = make_panel(path=p)
        assert panel.preview.total_lines == 1
        p.write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
        panel.refresh()
        assert panel.preview.total_lines == 3

    def test_refresh_with_no_path_is_noop(self, make_panel):
        panel = make_panel()
        panel.refresh()  # must not crash
        assert panel.preview is None


# ===========================================================================
# Build + body render
# ===========================================================================


class TestBuild:
    def test_build_empty_shows_placeholder(self, stub_dpg, make_panel):
        panel = make_panel()
        panel.build(parent_tag="parent")
        # empty-state tag should exist
        assert panel._EMPTY_TAG in stub_dpg.items

    def test_build_script_renders(self, stub_dpg, make_panel, script_file):
        panel = make_panel(path=script_file)
        panel.build(parent_tag="parent")
        # add_text calls should include some of our source lines.
        text_calls = stub_dpg.calls.get("add_text", [])
        assert len(text_calls) > 3

    def test_build_scene_renders(self, stub_dpg, make_panel, scene_file):
        panel = make_panel(path=scene_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        # There should be a row containing "Entities:" prefix.
        found = any(
            args and isinstance(args[0], str) and args[0].startswith("Entities:")
            for args, _kw in text_calls
        )
        assert found

    def test_build_texture_renders(self, stub_dpg, make_panel, texture_file):
        panel = make_panel(path=texture_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        assert any(
            args and isinstance(args[0], str) and args[0].startswith("Size:")
            for args, _kw in text_calls
        )

    def test_build_material_renders(self, stub_dpg, make_panel, material_file):
        panel = make_panel(path=material_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        # Shader row + WGSL bytes row.
        assert any(
            args and isinstance(args[0], str) and args[0].startswith("Shader:")
            for args, _kw in text_calls
        )
        # Open button.
        buttons = stub_dpg.calls.get("add_button", [])
        assert any(
            kw.get("label") == "Open in Material Editor"
            for _args, kw in buttons
        )

    def test_build_shader_renders(self, stub_dpg, make_panel, shader_file):
        panel = make_panel(path=shader_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        assert any(
            args and isinstance(args[0], str) and args[0].startswith("Bytes:")
            for args, _kw in text_calls
        )

    def test_build_prefab_renders(self, stub_dpg, make_panel, prefab_file):
        panel = make_panel(path=prefab_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        assert any(
            args and isinstance(args[0], str) and args[0].startswith("Nodes:")
            for args, _kw in text_calls
        )

    def test_build_other_renders(self, stub_dpg, make_panel, other_file):
        panel = make_panel(path=other_file)
        panel.build(parent_tag="parent")
        text_calls = stub_dpg.calls.get("add_text", [])
        assert any(
            args and isinstance(args[0], str) and args[0].startswith("Size:")
            for args, _kw in text_calls
        )

    def test_header_renders_refresh_and_copy_buttons(
        self, stub_dpg, make_panel, script_file,
    ):
        panel = make_panel(path=script_file)
        panel.build(parent_tag="parent")
        buttons = stub_dpg.calls.get("add_button", [])
        labels = {kw.get("label") for _args, kw in buttons}
        assert "Refresh" in labels
        assert "Copy Path" in labels


# ===========================================================================
# Content-browser subscription
# ===========================================================================


class _FakeBrowser:
    def __init__(self) -> None:
        self._on_asset_selected = None

    def set_on_asset_selected(self, cb):
        self._on_asset_selected = cb


class TestContentBrowser:
    def test_set_content_browser_subscribes(
        self, make_panel, script_file,
    ):
        panel = make_panel()
        browser = _FakeBrowser()
        panel.set_content_browser(browser)
        assert callable(browser._on_asset_selected)
        # Fire the browser's callback → the panel should now bind the path.
        browser._on_asset_selected(script_file, "script")
        assert panel.path == script_file

    def test_set_content_browser_none_unhooks(
        self, make_panel, script_file,
    ):
        panel = make_panel()
        browser = _FakeBrowser()
        panel.set_content_browser(browser)
        panel.set_content_browser(None)
        # After unhooking, firing the old callback still routes to the
        # panel — but the panel no longer holds a browser handle.
        assert panel._content_browser is None

    def test_swapping_browser_unhooks_prev(self, make_panel):
        panel = make_panel()
        b1 = _FakeBrowser()
        b2 = _FakeBrowser()
        panel.set_content_browser(b1)
        panel.set_content_browser(b2)
        assert panel._content_browser is b2


# ===========================================================================
# Material open callback
# ===========================================================================


class TestOpenMaterial:
    def test_open_material_editor_fires_callback(
        self, make_panel, material_file,
    ):
        captured: list[Path] = []
        panel = make_panel(
            path=material_file, on_open_material=captured.append,
        )
        assert panel.open_material_editor() is True
        assert captured == [material_file]

    def test_open_material_editor_skipped_for_script(
        self, make_panel, script_file,
    ):
        captured: list[Path] = []
        panel = make_panel(
            path=script_file, on_open_material=captured.append,
        )
        assert panel.open_material_editor() is False
        assert captured == []

    def test_open_material_no_callback(self, make_panel, material_file):
        panel = make_panel(path=material_file)
        assert panel.open_material_editor() is False


# ===========================================================================
# Destroy
# ===========================================================================


class TestDestroy:
    def test_destroy_clears_browser_subscription(
        self, make_panel,
    ):
        panel = make_panel()
        browser = _FakeBrowser()
        panel.set_content_browser(browser)
        panel.destroy()
        assert panel._content_browser is None


# ===========================================================================
# Breadcrumb + call log
# ===========================================================================


class TestBreadcrumb:
    def test_empty_breadcrumb(self, make_panel):
        panel = make_panel()
        assert panel.breadcrumb_segments() == []

    def test_breadcrumb_has_filename(self, make_panel, script_file):
        panel = make_panel(path=script_file)
        segments = panel.breadcrumb_segments()
        assert script_file.name in segments


class TestCallLog:
    def test_set_asset_path_logs(self, make_panel, script_file):
        panel = make_panel()
        panel.set_asset_path(script_file)
        assert ("set_asset_path", str(script_file)) in panel.call_log

    def test_refresh_logs(self, make_panel, script_file):
        panel = make_panel(path=script_file)
        panel.call_log.clear()
        panel.refresh()
        assert any(entry[0] == "refresh" for entry in panel.call_log)
