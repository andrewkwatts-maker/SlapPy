"""FF1 STUB-triage tests — ninth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 FF1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"FF1 STUB-triage patch"):

* ``content.new_folder`` — create a new sub-directory beneath the
  content-browser's current path; auto-uniquify on collision.
* ``content.rename_asset`` — rename a file or folder on disk;
  preserves the source extension unless the new name carries one.
* ``panel.close_others`` — solo the currently-focused panel by hiding
  every other visible panel (uses the DD1 ``_hidden_panel_stack`` so
  ``panel.restore_last_hidden`` still undoes the operation).
* ``edit.select_children`` — expand the selection to include every
  descendant (add / replace modes).
* ``theme.reload_all`` — clear + re-bake + re-scan the process-wide
  theme registry; re-applies the previously-active theme.

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised
end-to-end. No DPG context is required — the fixtures use
:class:`SimpleNamespace` stand-ins for the shell / scene / browser
handles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from slappyengine.tool_router import (
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
    """Content-browser stand-in with a refresh counter + root path."""

    def __init__(self, root: Path) -> None:
        self.root_path = str(root)
        self.current_path = str(root)
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


class _FakeEntity:
    """Attribute-holding entity stand-in with a ``.children`` list."""

    def __init__(self, name: str, children: list[Any] | None = None) -> None:
        self.name = name
        self.children: list[Any] = list(children or [])

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"_FakeEntity(name={self.name!r})"


def _shell_with_stack() -> SimpleNamespace:
    """Return a shell that owns a `_hidden_panel_stack` list."""
    ns = SimpleNamespace()
    ns._hidden_panel_stack = []
    ns._panel_windows = None
    ns._panel_layout_state = None
    ns.set_panel_visible_log: list[tuple[str, bool]] = []

    def set_panel_visible(pid: str, visible: bool) -> None:
        ns.set_panel_visible_log.append((pid, visible))

    ns.set_panel_visible = set_panel_visible
    return ns


# ---------------------------------------------------------------------------
# Registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 FF1 action ids are on the canonical router."""

    def test_content_new_folder_registered(self, router: ToolRouter) -> None:
        assert router.has_action("content.new_folder")

    def test_content_rename_asset_registered(self, router: ToolRouter) -> None:
        assert router.has_action("content.rename_asset")

    def test_panel_close_others_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.close_others")

    def test_edit_select_children_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.select_children")

    def test_theme_reload_all_registered(self, router: ToolRouter) -> None:
        assert router.has_action("theme.reload_all")

    def test_all_ff1_on_module_singleton(self) -> None:
        for aid in (
            "content.new_folder",
            "content.rename_asset",
            "panel.close_others",
            "edit.select_children",
            "theme.reload_all",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# content.new_folder (5 tests)
# ---------------------------------------------------------------------------


class TestNewFolder:
    """Cover the content.new_folder wiring."""

    def test_creates_default_folder(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        result = router.dispatch(
            "content.new_folder", {"parent": str(tmp_path)},
        )
        assert result["status"] == "created"
        assert result["name"] == "New Folder"
        assert (tmp_path / "New Folder").is_dir()

    def test_creates_named_folder(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        result = router.dispatch(
            "content.new_folder",
            {"parent": str(tmp_path), "name": "Assets"},
        )
        assert result["status"] == "created"
        assert result["name"] == "Assets"
        assert (tmp_path / "Assets").is_dir()

    def test_uniquifies_on_collision(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        (tmp_path / "Sprites").mkdir()
        result = router.dispatch(
            "content.new_folder",
            {"parent": str(tmp_path), "name": "Sprites"},
        )
        assert result["status"] == "created"
        assert result["name"] == "Sprites (2)"
        # A third call should uniquify to (3).
        again = router.dispatch(
            "content.new_folder",
            {"parent": str(tmp_path), "name": "Sprites"},
        )
        assert again["name"] == "Sprites (3)"

    def test_no_parent_returns_status(self, router: ToolRouter) -> None:
        assert router.dispatch("content.new_folder", {}) == {
            "status": "no_parent",
        }

    def test_uses_browser_root_and_refreshes(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        browser = _FakeBrowser(tmp_path)
        shell = SimpleNamespace(_content_browser=browser)
        result = router.dispatch(
            "content.new_folder", {"shell": shell, "name": "SFX"},
        )
        assert result["status"] == "created"
        assert result["parent"] == str(tmp_path)
        assert browser.refresh_count == 1


# ---------------------------------------------------------------------------
# content.rename_asset (5 tests)
# ---------------------------------------------------------------------------


class TestRenameAsset:
    """Cover the content.rename_asset wiring."""

    def test_renames_file_preserving_extension(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "old.png"
        src.write_bytes(b"pixels")
        result = router.dispatch(
            "content.rename_asset",
            {"path": str(src), "new_name": "new"},
        )
        assert result["status"] == "renamed"
        assert result["new_name"] == "new.png"
        assert (tmp_path / "new.png").exists()
        assert not src.exists()

    def test_rename_folder_no_extension_appended(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "OldFolder"
        src.mkdir()
        result = router.dispatch(
            "content.rename_asset",
            {"path": str(src), "new_name": "NewFolder"},
        )
        assert result["status"] == "renamed"
        assert (tmp_path / "NewFolder").is_dir()
        assert result["new_name"] == "NewFolder"

    def test_collision_without_overwrite(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "a.txt"
        dst = tmp_path / "b.txt"
        src.write_text("A")
        dst.write_text("B")
        result = router.dispatch(
            "content.rename_asset",
            {"path": str(src), "new_name": "b.txt"},
        )
        assert result["status"] == "collision"
        # Source should still exist because rename was rejected.
        assert src.exists()

    def test_missing_path(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "content.rename_asset", {"new_name": "foo"},
        ) == {"status": "missing_path"}

    def test_invalid_name_with_separator(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "safe.txt"
        src.write_text("x")
        result = router.dispatch(
            "content.rename_asset",
            {"path": str(src), "new_name": "sub/dir.txt"},
        )
        assert result["status"] == "invalid_name"
        assert src.exists()


# ---------------------------------------------------------------------------
# panel.close_others (4 tests)
# ---------------------------------------------------------------------------


class TestCloseOthers:
    """Cover the panel.close_others wiring."""

    def test_solos_inspector(self, router: ToolRouter) -> None:
        shell = _shell_with_stack()
        shell._active_panel_id = "inspector"
        result = router.dispatch(
            "panel.close_others",
            {
                "shell": shell,
                "panels": ["outliner", "inspector", "content_browser"],
            },
        )
        assert result["status"] == "closed"
        assert result["kept"] == "inspector"
        assert set(result["panels"]) == {"outliner", "content_browser"}
        # DD1 stack should now hold the closed batch.
        assert shell._hidden_panel_stack == [
            list(result["panels"]),
        ]

    def test_explicit_keep_overrides_shell(
        self, router: ToolRouter,
    ) -> None:
        shell = _shell_with_stack()
        shell._active_panel_id = "inspector"
        result = router.dispatch(
            "panel.close_others",
            {
                "shell": shell,
                "keep": "outliner",
                "panels": ["outliner", "inspector"],
            },
        )
        assert result["kept"] == "outliner"
        assert result["panels"] == ["inspector"]

    def test_no_target_when_no_focus(self, router: ToolRouter) -> None:
        shell = _shell_with_stack()
        assert router.dispatch(
            "panel.close_others", {"shell": shell},
        ) == {"status": "no_target"}

    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("panel.close_others", {}) == {
            "status": "no_shell",
        }


# ---------------------------------------------------------------------------
# panel.close_others + restore_last_hidden round-trip (1 test)
# ---------------------------------------------------------------------------


class TestCloseOthersRoundTrip:
    """Confirm DD1 restore actually pops the FF1 close-others batch."""

    def test_restore_reverses_close_others(self, router: ToolRouter) -> None:
        shell = _shell_with_stack()
        shell._active_panel_id = "code"
        panels = ["outliner", "inspector", "code"]
        router.dispatch(
            "panel.close_others",
            {"shell": shell, "panels": panels},
        )
        # DD1 pop should un-hide the batch.
        result = router.dispatch(
            "panel.restore_last_hidden", {"shell": shell},
        )
        assert result["status"] == "restored"
        assert set(result["panels"]) == {"outliner", "inspector"}
        # Stack drained.
        assert shell._hidden_panel_stack == []


# ---------------------------------------------------------------------------
# edit.select_children (5 tests)
# ---------------------------------------------------------------------------


class TestSelectChildren:
    """Cover the edit.select_children wiring."""

    def test_expands_direct_children(self, router: ToolRouter) -> None:
        c1 = _FakeEntity("c1")
        c2 = _FakeEntity("c2")
        parent = _FakeEntity("parent", [c1, c2])
        shell = SimpleNamespace(_selected_entity=parent)
        result = router.dispatch(
            "edit.select_children", {"shell": shell},
        )
        assert result["status"] == "expanded"
        assert result["count"] == 2
        assert result["added"] == [c1, c2]
        # Add mode keeps the root in the selection.
        assert result["selection"] == [parent, c1, c2]
        assert shell._selected_entities == [parent, c1, c2]

    def test_recursive_walk(self, router: ToolRouter) -> None:
        grandchild = _FakeEntity("grand")
        child = _FakeEntity("child", [grandchild])
        root = _FakeEntity("root", [child])
        shell = SimpleNamespace(_selected_entity=root)
        result = router.dispatch(
            "edit.select_children", {"shell": shell},
        )
        assert result["count"] == 2
        assert child in result["added"]
        assert grandchild in result["added"]

    def test_replace_mode_drops_roots(self, router: ToolRouter) -> None:
        c = _FakeEntity("c")
        root = _FakeEntity("root", [c])
        shell = SimpleNamespace(_selected_entity=root)
        result = router.dispatch(
            "edit.select_children",
            {"shell": shell, "mode": "replace"},
        )
        assert result["selection"] == [c]

    def test_no_selection(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        assert router.dispatch(
            "edit.select_children", {"shell": shell},
        ) == {"status": "no_selection"}

    def test_no_children(self, router: ToolRouter) -> None:
        leaf = _FakeEntity("leaf")
        shell = SimpleNamespace(_selected_entity=leaf)
        assert router.dispatch(
            "edit.select_children", {"shell": shell},
        ) == {"status": "no_children"}


# ---------------------------------------------------------------------------
# theme.reload_all (4 tests)
# ---------------------------------------------------------------------------


class TestReloadThemes:
    """Cover the theme.reload_all wiring."""

    def test_reload_returns_theme_list(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "theme.reload_all", {"skip_bake": True},
        )
        assert result["status"] == "reloaded"
        assert "themes" in result
        assert isinstance(result["themes"], list)
        assert result["count"] == len(result["themes"])

    def test_reload_reactivates_previous(
        self, router: ToolRouter,
    ) -> None:
        # Seed a theme + activate it before reload, then confirm reload
        # captures the active name before flushing. We poke the module
        # registry directly rather than construct a full ThemeSpec so
        # this test stays independent of ThemeSpec's ctor signature.
        import slappyengine.ui.theme as theme_pkg

        class _FakeTheme:
            name = "reload-test"

        theme_pkg._REGISTRY.clear()
        fake = _FakeTheme()
        theme_pkg._REGISTRY["reload-test"] = fake
        theme_pkg._ACTIVE = fake

        # Reload skipping bake so we don't disturb the process-wide
        # baked default themes.
        result = router.dispatch(
            "theme.reload_all", {"skip_bake": True},
        )
        assert result["status"] == "reloaded"
        # `active` was captured before the flush.
        assert result["active"] == "reload-test"

    def test_reload_with_shell_broadcast(
        self, router: ToolRouter,
    ) -> None:
        recorded: list[list[str]] = []

        shell = SimpleNamespace()

        def on_themes_reloaded(themes: list[str]) -> None:
            recorded.append(list(themes))

        shell.on_themes_reloaded = on_themes_reloaded
        result = router.dispatch(
            "theme.reload_all",
            {"shell": shell, "skip_bake": True},
        )
        assert result["status"] == "reloaded"
        assert len(recorded) == 1
        assert recorded[0] == result["themes"]

    def test_reload_resets_theme_cursor(
        self, router: ToolRouter,
    ) -> None:
        from slappyengine.actions import theme_actions
        theme_actions._THEME_CURSOR = "some-old-cursor"
        router.dispatch("theme.reload_all", {"skip_bake": True})
        assert theme_actions._THEME_CURSOR is None
