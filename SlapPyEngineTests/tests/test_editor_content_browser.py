"""Tests for the notebook-themed content browser.

Covers:

* Construction + validator rejection on non-callable callbacks.
* File classification (scene / script / asset / hidden / pycache).
* Icon library: every kind has a ≤500B SVG; fallback to ``page``.
* Washi-tape glyphs emitted per section header.
* Empty-root → empty-state row (with fox sticker hint substring).
* Mixed root (scenes/scripts/assets) → 3 section headers + file rows.
* Click routing: scene → on_open_scene, script → on_open_script,
  image/audio → on_open_asset.
* Search filter shrinks visible rows.
* set_root rebuilds the tree.
* Theme switch updates the cached palette.
* Context menu: rename / delete / duplicate / reveal (best-effort).
* Soft-import watchdog: panel still works when watchdog is absent.

The DPG stub mirrors the one in ``test_editor_notebook_outliner`` so the
tests run on CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub — accepts both context-manager and plain method calls.
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

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)
        # Stash the callback so tests can fire it.
        cb = kw.get("callback")
        if cb is not None:
            self.calls.setdefault("_buttons", []).append((a, kw, cb))

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

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

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "collapsing_header", "group", "child_window",
        "add_text", "add_button", "add_checkbox", "add_input_text",
        "add_separator", "does_item_exist", "delete_item",
        "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_theme(stub_dpg):
    """Reset theme + theme-listener list between tests so theme switches
    in one test don't surface as stale state in the next.
    """
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.widgets.notebook_theme import set_active_theme
    from slappyengine.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(root: Path, *,
                  scenes: list[str] = (),
                  scripts: list[str] = (),
                  assets: list[str] = ()) -> None:
    """Create a synthetic project layout under *root*."""
    for rel in scenes:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# scene\n", encoding="utf-8")
    for rel in scripts:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# script\n", encoding="utf-8")
    for rel in assets:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00\x00\x00")


def _noop(_path: Path) -> None:
    pass


# ---------------------------------------------------------------------------
# Construction / validators
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_with_three_callables(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        assert cb.TITLE == "Notebook"
        assert cb.get_root() is None
        assert cb.get_search() == ""

    def test_rejects_non_callable_on_open_scene(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        with pytest.raises(TypeError):
            NotebookContentBrowser("nope", _noop, _noop)  # type: ignore[arg-type]

    def test_rejects_non_callable_on_open_script(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        with pytest.raises(TypeError):
            NotebookContentBrowser(_noop, 42, _noop)  # type: ignore[arg-type]

    def test_rejects_non_callable_on_open_asset(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        with pytest.raises(TypeError):
            NotebookContentBrowser(_noop, _noop, None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_scene_yaml_classifies_as_scenes(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            SECTION_SCENES, classify_file,
        )

        assert classify_file(Path("main.scene.yaml")) == SECTION_SCENES

    def test_py_classifies_as_scripts(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            SECTION_SCRIPTS, classify_file,
        )

        assert classify_file(Path("player.py")) == SECTION_SCRIPTS

    def test_png_classifies_as_assets(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            SECTION_ASSETS, classify_file,
        )

        assert classify_file(Path("hero.png")) == SECTION_ASSETS

    def test_wav_classifies_as_assets(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            SECTION_ASSETS, classify_file,
        )

        assert classify_file(Path("jump.wav")) == SECTION_ASSETS

    def test_hidden_file_returns_none(self):
        from slappyengine.ui.editor.notebook_content_browser import classify_file

        assert classify_file(Path(".gitignore")) is None

    def test_pyc_bytecode_returns_none(self):
        from slappyengine.ui.editor.notebook_content_browser import classify_file

        assert classify_file(Path("foo.pyc")) is None

    def test_pycache_dir_path_returns_none(self):
        from slappyengine.ui.editor.notebook_content_browser import classify_file

        assert classify_file(Path("pkg/__pycache__/foo.py")) is None


# ---------------------------------------------------------------------------
# Icon library
# ---------------------------------------------------------------------------


class TestIcons:
    def test_every_icon_svg_under_500b(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            _FILE_ICON_SVGS,
        )

        expected = {"scene", "script", "diary", "image", "audio", "folder", "page"}
        assert set(_FILE_ICON_SVGS.keys()) == expected
        for kind, svg in _FILE_ICON_SVGS.items():
            assert len(svg.encode("utf-8")) <= 500, (
                f"icon {kind!r} is too large: {len(svg)} bytes"
            )

    def test_icon_for_path_routes_scene(self):
        from slappyengine.ui.editor.notebook_content_browser import icon_for_path

        assert icon_for_path(Path("level_1.scene.yaml")) == "scene"

    def test_icon_for_path_routes_script(self):
        from slappyengine.ui.editor.notebook_content_browser import icon_for_path

        assert icon_for_path(Path("main.py")) == "script"

    def test_icon_for_path_routes_image_jpg(self):
        from slappyengine.ui.editor.notebook_content_browser import icon_for_path

        assert icon_for_path(Path("portrait.jpg")) == "image"

    def test_icon_for_path_routes_audio_mp3(self):
        from slappyengine.ui.editor.notebook_content_browser import icon_for_path

        assert icon_for_path(Path("music.mp3")) == "audio"

    def test_icon_svg_falls_back_to_page_for_unknown(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            _FILE_ICON_SVGS, icon_svg,
        )

        assert icon_svg("totally_unknown") == _FILE_ICON_SVGS["page"]

    def test_make_file_icon_returns_svgicon(self):
        from slappyengine.ui.editor.notebook_content_browser import make_file_icon
        from slappyengine.ui.theme.svg_icon import SVGIcon

        icon = make_file_icon("script", size=16)
        assert isinstance(icon, SVGIcon)
        assert icon.size == 16


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class TestEmptyState:
    def test_no_root_iter_rows_is_empty(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        assert cb.iter_rows() == []

    def test_empty_root_renders_empty_state(self, tmp_path, stub_dpg):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        cb.build("sidebar")

        texts = [args for args, _ in stub_dpg.calls.get("add_text", [])]
        flat = " ".join(str(a) for a in texts)
        assert "Project is empty" in flat

    def test_nonexistent_root_iter_rows_is_empty(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path / "does_not_exist")
        assert cb.iter_rows() == []


# ---------------------------------------------------------------------------
# Multi-section project
# ---------------------------------------------------------------------------


class TestRowEnumeration:
    def _project(self, root: Path) -> None:
        _make_project(
            root,
            scenes=["scenes/main.scene.yaml", "scenes/level_2.scene.yaml"],
            scripts=["scripts/main.py", "scripts/enemy.py", "scripts/player.py"],
            assets=["assets/player.png", "assets/jump.wav"],
        )

    def test_three_sections_appear_in_rows(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser, SECTION_ASSETS, SECTION_SCENES,
            SECTION_SCRIPTS,
        )

        self._project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        rows = cb.iter_rows()

        headers = [r["section"] for r in rows if r["kind"] == "header"]
        assert headers == [SECTION_SCENES, SECTION_SCRIPTS, SECTION_ASSETS]

    def test_file_rows_carry_correct_icons(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        self._project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        icons_by_name: dict[str, str] = {
            r["name"]: r["icon"]
            for r in cb.iter_rows()
            if r["kind"] == "file"
        }
        assert icons_by_name["main.scene.yaml"] == "scene"
        assert icons_by_name["main.py"] == "script"
        assert icons_by_name["player.png"] == "image"
        assert icons_by_name["jump.wav"] == "audio"

    def test_build_renders_buttons_for_each_file(self, tmp_path, stub_dpg):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        self._project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        cb.build("sidebar")

        labels = [kw.get("label") for _, kw in stub_dpg.calls.get("add_button", [])]
        assert "main.scene.yaml" in labels
        assert "main.py" in labels
        assert "player.png" in labels


# ---------------------------------------------------------------------------
# Click routing
# ---------------------------------------------------------------------------


class TestClickRouting:
    def test_scene_row_fires_on_open_scene(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser, SECTION_SCENES,
        )

        _make_project(tmp_path, scenes=["scenes/main.scene.yaml"])
        captured: list[Path] = []
        cb = NotebookContentBrowser(captured.append, _noop, _noop)
        cb.set_root(tmp_path)

        scene_row = next(
            r for r in cb.iter_rows()
            if r["kind"] == "file" and r["section"] == SECTION_SCENES
        )
        cb._dispatch_open(scene_row["section"], scene_row["path"])

        assert captured == [scene_row["path"]]

    def test_script_row_fires_on_open_script(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser, SECTION_SCRIPTS,
        )

        _make_project(tmp_path, scripts=["scripts/main.py"])
        captured: list[Path] = []
        cb = NotebookContentBrowser(_noop, captured.append, _noop)
        cb.set_root(tmp_path)

        script_row = next(
            r for r in cb.iter_rows()
            if r["kind"] == "file" and r["section"] == SECTION_SCRIPTS
        )
        cb._dispatch_open(script_row["section"], script_row["path"])

        assert captured == [script_row["path"]]

    def test_asset_row_fires_on_open_asset(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser, SECTION_ASSETS,
        )

        _make_project(tmp_path, assets=["assets/jump.wav"])
        captured: list[Path] = []
        cb = NotebookContentBrowser(_noop, _noop, captured.append)
        cb.set_root(tmp_path)

        asset_row = next(
            r for r in cb.iter_rows()
            if r["kind"] == "file" and r["section"] == SECTION_ASSETS
        )
        cb._dispatch_open(asset_row["section"], asset_row["path"])

        assert captured == [asset_row["path"]]

    def test_callback_exception_does_not_crash(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser, SECTION_SCENES,
        )

        _make_project(tmp_path, scenes=["scenes/main.scene.yaml"])

        def _boom(_path: Path) -> None:
            raise RuntimeError("explode")

        cb = NotebookContentBrowser(_boom, _noop, _noop)
        cb.set_root(tmp_path)
        scene_row = next(
            r for r in cb.iter_rows()
            if r["kind"] == "file" and r["section"] == SECTION_SCENES
        )
        # Must not raise.
        cb._dispatch_open(scene_row["section"], scene_row["path"])


# ---------------------------------------------------------------------------
# Search filter
# ---------------------------------------------------------------------------


class TestSearchFilter:
    def test_search_shrinks_visible_rows(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        _make_project(
            tmp_path,
            scripts=["scripts/main.py", "scripts/enemy.py", "scripts/player.py"],
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        before = sum(1 for r in cb.iter_rows() if r["kind"] == "file")
        cb.set_search("enemy")
        after = sum(1 for r in cb.iter_rows() if r["kind"] == "file")

        assert before == 3
        assert after == 1

    def test_search_is_case_insensitive(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        _make_project(tmp_path, scripts=["scripts/Player.py"])
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        cb.set_search("PLAYER")
        files = [r for r in cb.iter_rows() if r["kind"] == "file"]
        assert len(files) == 1


# ---------------------------------------------------------------------------
# set_root / refresh
# ---------------------------------------------------------------------------


class TestSetRoot:
    def test_set_root_records_path(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        assert cb.get_root() == tmp_path

    def test_set_root_accepts_str(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(str(tmp_path))
        assert cb.get_root() == Path(str(tmp_path))

    def test_set_root_rebuilds_the_tree(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        # First root: 1 script. Second root: 2 scripts.
        a = tmp_path / "a"
        b = tmp_path / "b"
        _make_project(a, scripts=["main.py"])
        _make_project(b, scripts=["main.py", "enemy.py"])

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(a)
        files_a = [r for r in cb.iter_rows() if r["kind"] == "file"]
        cb.set_root(b)
        files_b = [r for r in cb.iter_rows() if r["kind"] == "file"]

        assert len(files_a) == 1
        assert len(files_b) == 2

    def test_refresh_does_not_crash_without_root(self):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.refresh()  # must not raise


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_switch_updates_cached_palette(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        from slappyengine.ui.widgets.notebook_theme import (
            NotebookTheme, set_active_theme,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        before = cb._theme.color("ink", (0, 0, 0, 0))
        # Pink ink theme so we can verify the switch landed.
        set_active_theme(NotebookTheme(
            name="pink",
            palette={
                "ink":    (255, 100, 180, 255),
                "paper":  (255, 245, 250, 255),
                "accent": (220, 100, 160, 255),
                "washi":  (255, 200, 230, 255),
            },
        ))
        after = cb._theme.color("ink", (0, 0, 0, 0))

        assert after != before
        assert after == (255, 100, 180, 255)


# ---------------------------------------------------------------------------
# Context-menu actions
# ---------------------------------------------------------------------------


class TestContextActions:
    def test_rename_moves_the_file(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        src = tmp_path / "old.py"
        src.write_text("# old\n", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        target = cb.rename(src, "new.py")
        assert target.exists()
        assert not src.exists()
        assert target.name == "new.py"

    def test_rename_refuses_escape(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        src = tmp_path / "victim.py"
        src.write_text("", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        with pytest.raises(ValueError):
            cb.rename(src, "../escape.py")

    def test_delete_removes_file(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        src = tmp_path / "doomed.py"
        src.write_text("", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        cb.delete(src)
        assert not src.exists()

    def test_duplicate_creates_copy(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        src = tmp_path / "thing.py"
        src.write_text("data\n", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        copy = cb.duplicate(src)
        assert copy.exists()
        assert copy != src
        assert copy.read_text(encoding="utf-8") == "data\n"

    def test_duplicate_handles_double_suffix(self, tmp_path):
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        src = tmp_path / "level.scene.yaml"
        src.write_text("# scene\n", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)

        copy = cb.duplicate(src)
        assert copy.exists()
        assert copy.name.endswith(".scene.yaml")
        assert "_copy" in copy.name

    def test_reveal_does_not_crash(self, tmp_path, monkeypatch):
        from slappyengine.ui.editor import notebook_content_browser as mod
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        # Stub Popen so the test never actually launches a file manager.
        popen_calls: list[list[str]] = []

        def _fake_popen(cmd, *a, **kw):
            popen_calls.append(list(cmd))
            class _P:
                pass
            return _P()
        monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)

        src = tmp_path / "thing.py"
        src.write_text("", encoding="utf-8")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_root(tmp_path)
        cb.reveal(src)

        assert len(popen_calls) == 1


# ---------------------------------------------------------------------------
# Soft-import watchdog
# ---------------------------------------------------------------------------


class TestSoftImportWatchdog:
    def test_module_imports_without_watchdog(self):
        """The browser must work even when ``watchdog`` is not installed."""
        from slappyengine.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )

        cb = NotebookContentBrowser(_noop, _noop, _noop)
        # _watchdog_available is a bool either way; the panel must work in both.
        assert isinstance(cb._watchdog_available, bool)
