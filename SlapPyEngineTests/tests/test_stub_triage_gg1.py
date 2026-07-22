"""GG1 STUB-triage tests — tenth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 GG1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"GG1 STUB-triage patch"):

* ``content.delete_asset`` — modal-confirm + on-disk delete for the
  content browser (flips row 243 from STUB to WIRED).
* ``panel.tile_grid`` — auto-tile every visible panel into a
  near-square grid.
* ``panel.cascade`` — cascade every visible panel into an offset
  staircase.
* ``edit.invert_selection`` — select every scene entity that is not
  currently selected.
* ``view.fullscreen`` — hide chrome + non-viewport panels and maximise
  the viewport rectangle; toggle / enter / exit modes.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised
end-to-end. No DPG context is required — the fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / browser handles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_editor.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    r = ToolRouter()
    register_default_actions(r)
    return r


class _FakeBrowser:
    """Content-browser stand-in with a refresh counter."""

    def __init__(self, root: Path) -> None:
        self.root_path = str(root)
        self.current_path = str(root)
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


class _FakeEntity:
    def __init__(
        self,
        name: str,
        locked: bool = False,
        visible: bool = True,
    ) -> None:
        self.name = name
        self.locked = locked
        self.visible = visible

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"_FakeEntity(name={self.name!r})"


class _FakeScene:
    def __init__(self, entities: list[_FakeEntity]) -> None:
        self.entities = entities


class _PanelWrapper:
    """Fake movable-panel wrapper with visible + rect fields."""

    def __init__(self, visible: bool = True) -> None:
        self._visible = visible
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0

    def is_visible(self) -> bool:
        return self._visible


def _panel_shell(visible_ids: list[str]) -> SimpleNamespace:
    """Return a shell with a movable-panel wrapper per id in *visible_ids*."""
    ns = SimpleNamespace()
    ns._panel_windows = {pid: _PanelWrapper() for pid in visible_ids}
    ns._panel_layout_state = None
    ns._hidden_panel_stack = []
    ns.set_panel_visible_log: list[tuple[str, bool]] = []

    def set_panel_visible(pid: str, visible: bool) -> None:
        ns.set_panel_visible_log.append((pid, visible))
        wrapper = ns._panel_windows.get(pid)
        if wrapper is not None:
            wrapper._visible = visible

    ns.set_panel_visible = set_panel_visible
    return ns


# ---------------------------------------------------------------------------
# Registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 GG1 action ids are on the canonical router."""

    def test_content_delete_asset_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("content.delete_asset")

    def test_panel_tile_grid_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.tile_grid")

    def test_panel_cascade_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.cascade")

    def test_edit_invert_selection_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.invert_selection")

    def test_view_fullscreen_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.fullscreen")

    def test_all_gg1_on_module_singleton(self) -> None:
        for aid in (
            "content.delete_asset",
            "panel.tile_grid",
            "panel.cascade",
            "edit.invert_selection",
            "view.fullscreen",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# content.delete_asset (5 tests)
# ---------------------------------------------------------------------------


class TestDeleteAsset:
    """Cover the content.delete_asset wiring."""

    def test_confirm_required_by_default(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "art.png"
        src.write_bytes(b"pixels")
        result = router.dispatch(
            "content.delete_asset", {"path": str(src)},
        )
        assert result["status"] == "confirm_required"
        assert result["kind"] == "file"
        assert "prompt" in result and "art.png" in result["prompt"]
        # File must still exist — we didn't opt in.
        assert src.exists()

    def test_confirmed_deletes_file(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "art.png"
        src.write_bytes(b"pixels")
        result = router.dispatch(
            "content.delete_asset",
            {"path": str(src), "confirmed": True},
        )
        assert result["status"] == "deleted"
        assert result["kind"] == "file"
        assert result["size"] == len(b"pixels")
        assert not src.exists()

    def test_confirmed_deletes_directory_recursively(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        folder = tmp_path / "Sprites"
        folder.mkdir()
        (folder / "hero.png").write_bytes(b"aaa")
        (folder / "villain.png").write_bytes(b"bb")
        result = router.dispatch(
            "content.delete_asset",
            {"path": str(folder), "confirmed": True},
        )
        assert result["status"] == "deleted"
        assert result["kind"] == "dir"
        assert result["size"] == 5  # 3 + 2 bytes
        assert not folder.exists()

    def test_missing_path(self, router: ToolRouter) -> None:
        assert router.dispatch("content.delete_asset", {}) == {
            "status": "missing_path",
        }

    def test_not_found(self, router: ToolRouter, tmp_path: Path) -> None:
        result = router.dispatch(
            "content.delete_asset",
            {"path": str(tmp_path / "does_not_exist.png"),
             "confirmed": True},
        )
        assert result["status"] == "not_found"

    def test_confirmed_refreshes_browser(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "art.png"
        src.write_bytes(b"pixels")
        browser = _FakeBrowser(tmp_path)
        shell = SimpleNamespace(_content_browser=browser)
        result = router.dispatch(
            "content.delete_asset",
            {"path": str(src), "confirmed": True, "shell": shell},
        )
        assert result["status"] == "deleted"
        assert browser.refresh_count == 1


# ---------------------------------------------------------------------------
# panel.tile_grid (4 tests)
# ---------------------------------------------------------------------------


class TestTileGrid:
    """Cover the panel.tile_grid wiring."""

    def test_tiles_visible_panels(self, router: ToolRouter) -> None:
        shell = _panel_shell(["outliner", "inspector", "content_browser"])
        result = router.dispatch(
            "panel.tile_grid",
            {
                "shell": shell,
                "panels": ["outliner", "inspector", "content_browser"],
                "viewport_size": (1200, 800),
            },
        )
        assert result["status"] == "tiled"
        assert result["count"] == 3
        # 3 panels → 2 cols × 2 rows.
        assert result["cols"] == 2
        assert result["rows"] == 2
        # First panel at (0, 0) with width/height = cell size.
        first = shell._panel_windows["outliner"]
        assert first.x == 0
        assert first.y == 0
        assert first.width == 600  # 1200 / 2 cols
        assert first.height == 400  # 800 / 2 rows

    def test_tile_single_panel_fills_viewport(
        self, router: ToolRouter,
    ) -> None:
        shell = _panel_shell(["outliner"])
        result = router.dispatch(
            "panel.tile_grid",
            {
                "shell": shell,
                "panels": ["outliner"],
                "viewport_size": (800, 600),
            },
        )
        assert result["cols"] == 1
        assert result["rows"] == 1
        wrapper = shell._panel_windows["outliner"]
        assert wrapper.width == 800
        assert wrapper.height == 600

    def test_no_visible_panels(self, router: ToolRouter) -> None:
        shell = _panel_shell(["outliner"])
        # Hide the only panel so the visible-set is empty.
        shell._panel_windows["outliner"]._visible = False
        result = router.dispatch(
            "panel.tile_grid",
            {"shell": shell, "panels": ["outliner"]},
        )
        assert result["status"] == "no_visible_panels"

    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("panel.tile_grid", {}) == {
            "status": "no_shell",
        }


# ---------------------------------------------------------------------------
# panel.cascade (3 tests)
# ---------------------------------------------------------------------------


class TestCascade:
    """Cover the panel.cascade wiring."""

    def test_cascades_visible_panels(self, router: ToolRouter) -> None:
        shell = _panel_shell(["outliner", "inspector", "code"])
        result = router.dispatch(
            "panel.cascade",
            {
                "shell": shell,
                "panels": ["outliner", "inspector", "code"],
                "offset": (30, 30),
                "panel_size": (500, 400),
                "viewport_size": (1600, 900),
            },
        )
        assert result["status"] == "cascaded"
        assert result["count"] == 3
        assert result["offset"] == (30, 30)
        first = shell._panel_windows["outliner"]
        second = shell._panel_windows["inspector"]
        third = shell._panel_windows["code"]
        assert (first.x, first.y) == (0, 0)
        assert (second.x, second.y) == (30, 30)
        assert (third.x, third.y) == (60, 60)
        # All panels share the panel_size.
        assert first.width == 500
        assert first.height == 400

    def test_cascade_clamps_to_viewport(self, router: ToolRouter) -> None:
        shell = _panel_shell(["outliner", "inspector", "code"])
        # Force offset large enough to walk past a tiny viewport.
        result = router.dispatch(
            "panel.cascade",
            {
                "shell": shell,
                "panels": ["outliner", "inspector", "code"],
                "offset": (400, 400),
                "panel_size": (500, 400),
                "viewport_size": (800, 600),
            },
        )
        assert result["status"] == "cascaded"
        third = shell._panel_windows["code"]
        # 800 - 500 = 300 max X.
        assert third.x <= 300
        # 600 - 400 = 200 max Y.
        assert third.y <= 200

    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("panel.cascade", {}) == {
            "status": "no_shell",
        }


# ---------------------------------------------------------------------------
# edit.invert_selection (5 tests)
# ---------------------------------------------------------------------------


class TestInvertSelection:
    """Cover the edit.invert_selection wiring."""

    def test_inverts_selection(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        c = _FakeEntity("c")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(
            _selected_entity=a,
            _selected_entities=[a],
            _scene=scene,
        )
        result = router.dispatch(
            "edit.invert_selection", {"shell": shell},
        )
        assert result["status"] == "inverted"
        assert result["count"] == 2
        assert result["previous_count"] == 1
        assert set(result["selection"]) == {b, c}
        assert shell._selected_entities == result["selection"]

    def test_no_scene(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        assert router.dispatch(
            "edit.invert_selection", {"shell": shell},
        ) == {"status": "no_scene"}

    def test_empty_scene(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = SimpleNamespace(_scene=scene)
        assert router.dispatch(
            "edit.invert_selection", {"shell": shell},
        ) == {"status": "empty_scene"}

    def test_all_selected(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(
            _selected_entities=[a, b],
            _scene=scene,
        )
        assert router.dispatch(
            "edit.invert_selection", {"shell": shell},
        ) == {"status": "all_selected"}

    def test_locked_entities_skipped_by_default(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b", locked=True)
        c = _FakeEntity("c")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(
            _selected_entity=a,
            _selected_entities=[a],
            _scene=scene,
        )
        result = router.dispatch(
            "edit.invert_selection", {"shell": shell},
        )
        assert result["count"] == 1  # b (locked) is filtered out.
        assert result["selection"] == [c]

    def test_include_locked_opts_in(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b", locked=True)
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(
            _selected_entity=a,
            _selected_entities=[a],
            _scene=scene,
        )
        result = router.dispatch(
            "edit.invert_selection",
            {"shell": shell, "include_locked": True},
        )
        assert result["count"] == 1
        assert result["selection"] == [b]


# ---------------------------------------------------------------------------
# view.fullscreen (5 tests)
# ---------------------------------------------------------------------------


class TestFullscreen:
    """Cover the view.fullscreen wiring."""

    def _fs_shell(self) -> SimpleNamespace:
        ns = _panel_shell(["outliner", "inspector"])
        ns._menu_bar_visible = True
        ns._toolbar_visible = True
        ns._status_bar_visible = True
        ns._fullscreen_snapshot = None
        return ns

    def test_enter_hides_chrome_and_panels(
        self, router: ToolRouter,
    ) -> None:
        shell = self._fs_shell()
        result = router.dispatch(
            "view.fullscreen",
            {
                "shell": shell,
                "mode": "enter",
                "chrome": ["menu_bar", "toolbar", "status_bar"],
                "panels": ["outliner", "inspector"],
            },
        )
        assert result["status"] == "entered"
        assert set(result["chrome_hidden"]) == {
            "menu_bar", "toolbar", "status_bar",
        }
        assert set(result["panels_hidden"]) == {"outliner", "inspector"}
        assert shell._menu_bar_visible is False
        assert shell._toolbar_visible is False
        assert shell._fullscreen_snapshot is not None

    def test_exit_restores_previous_state(
        self, router: ToolRouter,
    ) -> None:
        shell = self._fs_shell()
        router.dispatch(
            "view.fullscreen",
            {
                "shell": shell,
                "mode": "enter",
                "chrome": ["menu_bar", "toolbar", "status_bar"],
                "panels": ["outliner", "inspector"],
            },
        )
        result = router.dispatch(
            "view.fullscreen",
            {"shell": shell, "mode": "exit"},
        )
        assert result["status"] == "exited"
        assert set(result["chrome_shown"]) == {
            "menu_bar", "toolbar", "status_bar",
        }
        assert set(result["panels_shown"]) == {"outliner", "inspector"}
        # Snapshot cleared.
        assert shell._fullscreen_snapshot is None
        # Chrome restored.
        assert shell._menu_bar_visible is True
        assert shell._toolbar_visible is True

    def test_toggle_round_trip(self, router: ToolRouter) -> None:
        shell = self._fs_shell()
        first = router.dispatch(
            "view.fullscreen",
            {
                "shell": shell,
                "chrome": ["menu_bar"],
                "panels": ["outliner"],
            },
        )
        assert first["status"] == "entered"
        second = router.dispatch(
            "view.fullscreen", {"shell": shell},
        )
        assert second["status"] == "exited"

    def test_already_fullscreen(self, router: ToolRouter) -> None:
        shell = self._fs_shell()
        router.dispatch(
            "view.fullscreen",
            {
                "shell": shell,
                "mode": "enter",
                "chrome": ["menu_bar"],
                "panels": ["outliner"],
            },
        )
        result = router.dispatch(
            "view.fullscreen",
            {
                "shell": shell,
                "mode": "enter",
                "chrome": ["menu_bar"],
                "panels": ["outliner"],
            },
        )
        assert result == {"status": "already_fullscreen"}

    def test_not_fullscreen_on_exit(self, router: ToolRouter) -> None:
        shell = self._fs_shell()
        result = router.dispatch(
            "view.fullscreen",
            {"shell": shell, "mode": "exit"},
        )
        assert result == {"status": "not_fullscreen"}

    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("view.fullscreen", {}) == {
            "status": "no_shell",
        }


# ---------------------------------------------------------------------------
# ensure_ctx guardrail (1 test)
# ---------------------------------------------------------------------------


class TestCtxGuardrail:
    """Confirm non-dict ctx raises through the router."""

    def test_ctx_must_be_dict(self, router: ToolRouter) -> None:
        with pytest.raises(TypeError):
            # dispatch rejects non-dict at the router layer.
            router.dispatch("view.fullscreen", [])  # type: ignore[arg-type]
