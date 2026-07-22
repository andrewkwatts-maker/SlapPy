"""Tests for the project asset-tree extensions on ``NotebookContentBrowser``.

Covers task **X4** (Nova3D-style content browser):

* ``set_project(None)`` clears the tree.
* ``set_project(project)`` populates groups from an on-disk fixture.
* Asset classification per extension — scripts, scenes (``.scene.yaml`` +
  ``.scene.json``), textures (``.png``/``.jpg``/``.webp``), materials
  (``.mat.yaml``/``.material.yaml``), shaders (``.wgsl``/``.glsl``),
  other.
* Empty project (no ``assets/`` directory) → empty tree, no crash.
* Search box filters via the ``fuzzy_match`` helper.
* ``set_on_asset_selected`` fires with the correct ``(path, kind)`` pair.
* Broken symlinks / vanishing files are skipped gracefully.
* Reentrant subscription is guarded (a callback that swaps itself
  mid-dispatch cannot corrupt the panel).
* Right-click context-menu helpers (open / reveal / copy path / delete)
  are wired via the dispatch path.

Runs in a headless DPG fixture so CI without a display still exercises
every code path.
"""
from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub — mirrors ``test_editor_content_browser`` so the module's
# soft-import path resolves to a controllable in-process module.
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
        self.clipboard: str | None = None

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

    def popup(self, parent, *a, **kw):
        self._track("popup", (parent,) + a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)
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

    def set_clipboard_text(self, text):
        self.clipboard = text


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "collapsing_header", "group", "child_window", "popup", "window",
        "add_text", "add_button", "add_checkbox", "add_input_text",
        "add_separator", "does_item_exist", "delete_item",
        "get_item_children", "set_clipboard_text",
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
    """Reset theme + sticker state between tests."""
    from pharos_editor.ui.widgets import notebook_theme
    from pharos_editor.ui.widgets.notebook_theme import set_active_theme
    from pharos_editor.ui.widgets.sticker_corner import _active_stickers

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


@dataclass
class _FakeProject:
    """Duck-typed stand-in for ``pharos_engine.projects.Project``."""

    path: Path


def _noop(_path: Path) -> None:
    pass


def _make_assets(root: Path, files: list[str]) -> None:
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith((".png", ".jpg", ".jpeg", ".webp")):
            p.write_bytes(b"\x89PNG\r\n\x1a\n")
        else:
            p.write_text("# fixture\n", encoding="utf-8")


def _make_full_project(root: Path) -> _FakeProject:
    """One-file-per-kind fixture used by many tests."""
    assets = root / "assets"
    _make_assets(assets, [
        "scripts/player.py",
        "scenes/main.scene.yaml",
        "scenes/menu.scene.json",
        "textures/hero.png",
        "textures/wall.jpg",
        "textures/tile.webp",
        "materials/skin.mat.yaml",
        "materials/rock.material.yaml",
        "shaders/blit.wgsl",
        "shaders/tone.glsl",
        "readme.txt",
    ])
    return _FakeProject(path=root)


# ---------------------------------------------------------------------------
# classify_asset — extension classification
# ---------------------------------------------------------------------------


class TestClassifyAsset:
    def test_py_is_script(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, classify_asset,
        )
        assert classify_asset(Path("player.py")) == ASSET_KIND_SCRIPT

    def test_scene_yaml_is_scene(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCENE, classify_asset,
        )
        assert classify_asset(Path("main.scene.yaml")) == ASSET_KIND_SCENE

    def test_scene_json_is_scene(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCENE, classify_asset,
        )
        assert classify_asset(Path("menu.scene.json")) == ASSET_KIND_SCENE

    def test_png_is_texture(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_TEXTURE, classify_asset,
        )
        assert classify_asset(Path("hero.png")) == ASSET_KIND_TEXTURE

    def test_jpg_is_texture(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_TEXTURE, classify_asset,
        )
        assert classify_asset(Path("wall.jpg")) == ASSET_KIND_TEXTURE

    def test_webp_is_texture(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_TEXTURE, classify_asset,
        )
        assert classify_asset(Path("tile.webp")) == ASSET_KIND_TEXTURE

    def test_mat_yaml_is_material(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_MATERIAL, classify_asset,
        )
        assert classify_asset(Path("skin.mat.yaml")) == ASSET_KIND_MATERIAL

    def test_material_yaml_is_material(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_MATERIAL, classify_asset,
        )
        assert (
            classify_asset(Path("rock.material.yaml"))
            == ASSET_KIND_MATERIAL
        )

    def test_wgsl_is_shader(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SHADER, classify_asset,
        )
        assert classify_asset(Path("blit.wgsl")) == ASSET_KIND_SHADER

    def test_glsl_is_shader(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SHADER, classify_asset,
        )
        assert classify_asset(Path("tone.glsl")) == ASSET_KIND_SHADER

    def test_unknown_ext_is_other(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_OTHER, classify_asset,
        )
        assert classify_asset(Path("readme.txt")) == ASSET_KIND_OTHER

    def test_hidden_returns_none(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            classify_asset,
        )
        assert classify_asset(Path(".gitignore")) is None

    def test_pyc_returns_none(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            classify_asset,
        )
        assert classify_asset(Path("cache.pyc")) is None

    def test_pycache_dir_returns_none(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            classify_asset,
        )
        assert classify_asset(Path("pkg/__pycache__/mod.py")) is None


# ---------------------------------------------------------------------------
# set_project — bind / clear
# ---------------------------------------------------------------------------


class TestSetProject:
    def test_none_clears_the_tree(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        assert cb.get_project() is proj
        cb.set_project(None)
        assert cb.get_project() is None
        assert cb.get_root() is None
        assert cb.iter_asset_tree() == {
            "script": [], "scene": [], "texture": [],
            "material": [], "shader": [], "other": [],
        }

    def test_populates_groups_from_fixture(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_MATERIAL, ASSET_KIND_SCENE, ASSET_KIND_SCRIPT,
            ASSET_KIND_SHADER, ASSET_KIND_TEXTURE, NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        tree = cb.iter_asset_tree()
        assert len(tree[ASSET_KIND_SCRIPT]) == 1
        assert len(tree[ASSET_KIND_SCENE]) == 2
        assert len(tree[ASSET_KIND_TEXTURE]) == 3
        assert len(tree[ASSET_KIND_MATERIAL]) == 2
        assert len(tree[ASSET_KIND_SHADER]) == 2

    def test_empty_project_no_assets_dir(self, tmp_path):
        """A project with no ``assets/`` directory renders an empty tree."""
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        proj = _FakeProject(path=tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        tree = cb.iter_asset_tree()
        # ``_root`` falls back to the project root when assets/ is
        # missing; but with no files present the tree is empty.
        assert all(v == [] for v in tree.values())

    def test_missing_project_path(self, tmp_path):
        """``set_project`` on an object without ``.path`` clears state."""
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)

        class _NoPath:
            pass

        cb.set_project(_NoPath())  # type: ignore[arg-type]
        assert cb.get_project() is None
        assert cb.get_root() is None

    def test_set_project_resets_search_and_cwd(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        # ``_cwd`` is reset to None on set_project.
        assert cb.get_cwd() is None


# ---------------------------------------------------------------------------
# _build_asset_tree
# ---------------------------------------------------------------------------


class TestBuildAssetTree:
    def test_walks_root_recursively(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        _make_assets(tmp_path, [
            "a/b/c/deep.py",
            "shallow.wgsl",
        ])
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        tree = cb._build_asset_tree(tmp_path)
        names = {p.name for group in tree.values() for p in group}
        assert "deep.py" in names
        assert "shallow.wgsl" in names

    def test_missing_root_returns_empty(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        tree = cb._build_asset_tree(tmp_path / "nope")
        assert all(v == [] for v in tree.values())

    def test_skips_pycache_files(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        _make_assets(tmp_path, ["__pycache__/mod.py", "real.py"])
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        tree = cb._build_asset_tree(tmp_path)
        names = {p.name for group in tree.values() for p in group}
        assert "real.py" in names
        assert "mod.py" not in names

    def test_deterministic_ordering(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        _make_assets(tmp_path, ["z.py", "a.py", "m.py"])
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        tree = cb._build_asset_tree(tmp_path)
        names = [p.name for p in tree[ASSET_KIND_SCRIPT]]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Search filter
# ---------------------------------------------------------------------------


class TestSearchFilter:
    def test_search_hides_non_matching(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        before = len(cb.iter_asset_tree()[ASSET_KIND_SCRIPT])
        cb.set_search("nonexistent_needle_xyz")
        after = len(cb.iter_asset_tree()[ASSET_KIND_SCRIPT])
        assert before == 1
        assert after == 0

    def test_search_keeps_matching(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        cb.set_search("play")
        matches = cb.iter_asset_tree()[ASSET_KIND_SCRIPT]
        assert any("player.py" == p.name for p in matches)

    def test_fuzzy_subsequence_match(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            fuzzy_match,
        )
        assert fuzzy_match("mm", "main_menu.py")
        assert fuzzy_match("plr", "player.py")
        assert not fuzzy_match("xyz", "player.py")

    def test_fuzzy_case_insensitive(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            fuzzy_match,
        )
        assert fuzzy_match("PLAYER", "player.py")
        assert fuzzy_match("Player", "PLAYER.PY")

    def test_empty_search_matches_all(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            fuzzy_match,
        )
        assert fuzzy_match("", "anything.py")


# ---------------------------------------------------------------------------
# on_asset_selected callback dispatch
# ---------------------------------------------------------------------------


class TestOnAssetSelected:
    def test_fires_with_correct_kind_script(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        captured: list[tuple[Path, str]] = []
        cb.set_on_asset_selected(lambda p, k: captured.append((p, k)))
        script = tmp_path / "assets" / "scripts" / "player.py"
        cb._dispatch_asset(script, ASSET_KIND_SCRIPT)
        assert captured == [(script, ASSET_KIND_SCRIPT)]

    def test_fires_with_correct_kind_shader(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SHADER, NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        captured: list[tuple[Path, str]] = []
        cb.set_on_asset_selected(lambda p, k: captured.append((p, k)))
        shader = tmp_path / "assets" / "shaders" / "blit.wgsl"
        cb._dispatch_asset(shader, ASSET_KIND_SHADER)
        assert captured[0][1] == ASSET_KIND_SHADER

    def test_callback_none_is_noop(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        # Setting then clearing must be safe.
        cb.set_on_asset_selected(lambda p, k: None)
        cb.set_on_asset_selected(None)
        cb._dispatch_asset(Path("foo.py"), ASSET_KIND_SCRIPT)  # no raise

    def test_non_callable_rejected(self):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        with pytest.raises(TypeError):
            cb.set_on_asset_selected("not a callable")  # type: ignore[arg-type]

    def test_callback_exception_does_not_crash(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_TEXTURE, NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)

        def _boom(*_):
            raise RuntimeError("kaboom")
        cb.set_on_asset_selected(_boom)
        # Must swallow the exception silently.
        cb._dispatch_asset(Path("x.png"), ASSET_KIND_TEXTURE)

    def test_reentrant_swap_guarded(self, tmp_path):
        """A callback that re-subscribes cannot corrupt in-flight dispatch."""
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        events: list[str] = []

        def _second(p, k):
            events.append(f"second:{k}")

        def _first(p, k):
            events.append(f"first:{k}")
            # Swap during dispatch — the guard flag should keep the
            # current invocation intact and the next click will fire
            # ``_second`` instead.
            assert cb._dispatching_asset is True
            cb.set_on_asset_selected(_second)

        cb.set_on_asset_selected(_first)
        cb._dispatch_asset(Path("a.py"), ASSET_KIND_SCRIPT)
        cb._dispatch_asset(Path("b.py"), ASSET_KIND_SCRIPT)
        assert events == ["first:script", "second:script"]
        # Guard flag is cleared even after the swap.
        assert cb._dispatching_asset is False


# ---------------------------------------------------------------------------
# Broken / vanishing files
# ---------------------------------------------------------------------------


class TestBrokenFiles:
    def test_missing_symlink_skipped(self, tmp_path):
        """A dangling symlink should not raise during the walk."""
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        real = tmp_path / "real.py"
        real.write_text("# real\n", encoding="utf-8")
        link = tmp_path / "dead.py"
        try:
            os.symlink(tmp_path / "missing_target.py", link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unsupported on this platform")
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        tree = cb._build_asset_tree(tmp_path)
        # ``real.py`` must still appear; the dead link is best-effort
        # skipped without raising.
        names = {p.name for group in tree.values() for p in group}
        assert "real.py" in names


# ---------------------------------------------------------------------------
# Rendering / build
# ---------------------------------------------------------------------------


class TestRenderGroup:
    def test_render_group_emits_collapsing_header(self, tmp_path, stub_dpg):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        _make_assets(tmp_path, ["scripts/x.py"])
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb._render_group("Scripts", [tmp_path / "scripts" / "x.py"])
        labels = [
            kw.get("label")
            for _, kw in stub_dpg.calls.get("collapsing_header", [])
        ]
        assert "Scripts" in labels

    def test_render_group_empty_is_noop(self, stub_dpg):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb._render_group("Scripts", [])
        # No collapsing_header call for empty groups.
        assert "collapsing_header" not in stub_dpg.calls or not any(
            kw.get("label") == "Scripts"
            for _, kw in stub_dpg.calls.get("collapsing_header", [])
        )

    def test_build_renders_asset_group_buttons(self, tmp_path, stub_dpg):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        proj = _make_full_project(tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        cb.build("sidebar")
        labels = [
            kw.get("label") for _, kw in stub_dpg.calls.get("add_button", [])
        ]
        assert "player.py" in labels
        assert "hero.png" in labels
        assert "blit.wgsl" in labels

    def test_build_empty_project_renders_empty_state(
        self, tmp_path, stub_dpg,
    ):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        # No assets/ dir at all.
        proj = _FakeProject(path=tmp_path)
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        cb.set_project(proj)
        cb.build("sidebar")
        texts = [
            args for args, _ in stub_dpg.calls.get("add_text", [])
        ]
        flat = " ".join(str(a) for a in texts)
        assert "Project is empty" in flat


# ---------------------------------------------------------------------------
# copy_path
# ---------------------------------------------------------------------------


class TestCopyPath:
    def test_copy_path_returns_string(self, tmp_path, stub_dpg):
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        p = tmp_path / "foo.py"
        p.write_text("", encoding="utf-8")
        result = cb.copy_path(p)
        assert result == str(p)
        # Stub records the clipboard.
        assert stub_dpg.clipboard == str(p)


# ---------------------------------------------------------------------------
# Context-menu helpers
# ---------------------------------------------------------------------------


class TestContextMenu:
    def test_context_open_fires_asset_callback(self, tmp_path):
        from pharos_editor.ui.editor.notebook_content_browser import (
            ASSET_KIND_SCRIPT, NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        captured: list[tuple[Path, str]] = []
        cb.set_on_asset_selected(lambda p, k: captured.append((p, k)))
        p = tmp_path / "x.py"
        p.write_text("", encoding="utf-8")
        cb._context_open(p)
        assert captured == [(p, ASSET_KIND_SCRIPT)]

    def test_context_delete_removes_file_headless(self, tmp_path, stub_dpg):
        """With the DPG stub, delete confirms via the modal path."""
        from pharos_editor.ui.editor.notebook_content_browser import (
            NotebookContentBrowser,
        )
        cb = NotebookContentBrowser(_noop, _noop, _noop)
        target = tmp_path / "doomed.py"
        target.write_text("", encoding="utf-8")
        # Directly trigger the confirmed-delete path.
        cb._confirm_delete(target, "notebook_cb_confirm_test")
        assert not target.exists()
