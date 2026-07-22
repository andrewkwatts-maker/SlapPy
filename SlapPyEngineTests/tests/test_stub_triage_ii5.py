"""II5 STUB-triage tests — eleventh round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 II5 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"II5 STUB-triage patch"):

* ``edit.select_next`` — Tab-through the scene entity roster (advance
  the cursor by one, wraps by default).
* ``edit.select_previous`` — Shift+Tab; retreats the cursor by one.
* ``edit.paste_at_original_position`` — Illustrator-style paste that
  preserves the source coordinate; distinct status string vs the plain
  paste path.
* ``spawn.spawn_batch_row`` — sibling to GG1's grid batch; lays down N
  copies in a single row (horizontal / vertical / arbitrary stride).
* ``content.duplicate_asset`` — Explorer-style ``_copy`` suffix
  duplicate; handles files (extension-preserving) and directories
  (recursive via ``shutil.copytree``).

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised
end-to-end. No DPG context is required — the fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / browser handles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_engine.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)
from pharos_engine.ui.editor.entity_clipboard import (
    get_active_clipboard,
    reset_active_clipboard,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture(autouse=True)
def _reset_clipboard() -> Any:
    reset_active_clipboard()
    yield
    reset_active_clipboard()


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


class _FakeBrowser:
    def __init__(self, root: Path) -> None:
        self.root_path = str(root)
        self.current_path = str(root)
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


class _SpawnRecorder:
    """Shell stand-in that records every _on_spawn call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._last_spawn: tuple[str, dict] | None = None

    def _on_spawn(self, card_id: str, spec: dict) -> None:
        self.calls.append((card_id, dict(spec)))


# ---------------------------------------------------------------------------
# Registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 II5 action ids are on the canonical router."""

    def test_edit_select_next_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.select_next")

    def test_edit_select_previous_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.select_previous")

    def test_edit_paste_at_original_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.paste_at_original_position")

    def test_spawn_batch_row_registered(self, router: ToolRouter) -> None:
        assert router.has_action("spawn.spawn_batch_row")

    def test_content_duplicate_asset_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("content.duplicate_asset")

    def test_all_ii5_on_module_singleton(self) -> None:
        for aid in (
            "edit.select_next",
            "edit.select_previous",
            "edit.paste_at_original_position",
            "spawn.spawn_batch_row",
            "content.duplicate_asset",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# edit.select_next / edit.select_previous (7 tests)
# ---------------------------------------------------------------------------


class TestSelectNextPrevious:
    """Cover the Tab-through selection wiring."""

    def test_select_next_advances_cursor(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        c = _FakeEntity("c")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_selected_entity=a, _scene=scene)
        result = router.dispatch(
            "edit.select_next", {"shell": shell},
        )
        assert result["status"] == "selected"
        assert result["entity"] is b
        assert result["index"] == 1
        assert result["previous_index"] == 0
        assert result["count"] == 3
        assert shell._selected_entity is b

    def test_select_next_wraps_at_end(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_selected_entity=b, _scene=scene)
        result = router.dispatch(
            "edit.select_next", {"shell": shell},
        )
        assert result["entity"] is a
        assert result["index"] == 0

    def test_select_next_no_wrap_returns_at_end(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_selected_entity=b, _scene=scene)
        result = router.dispatch(
            "edit.select_next", {"shell": shell, "wrap": False},
        )
        assert result == {"status": "at_end"}
        # Selection unchanged.
        assert shell._selected_entity is b

    def test_select_previous_retreats_cursor(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        c = _FakeEntity("c")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_selected_entity=c, _scene=scene)
        result = router.dispatch(
            "edit.select_previous", {"shell": shell},
        )
        assert result["entity"] is b
        assert result["index"] == 1

    def test_select_previous_wraps_at_start(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_selected_entity=a, _scene=scene)
        result = router.dispatch(
            "edit.select_previous", {"shell": shell},
        )
        assert result["entity"] is b
        assert result["index"] == 1

    def test_select_next_from_empty_lands_on_first(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_selected_entity=None, _scene=scene)
        result = router.dispatch(
            "edit.select_next", {"shell": shell},
        )
        assert result["entity"] is a
        assert result["previous_index"] == -1

    def test_select_next_no_scene(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        assert router.dispatch(
            "edit.select_next", {"shell": shell},
        ) == {"status": "no_scene"}

    def test_select_next_empty_scene(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = SimpleNamespace(_scene=scene)
        assert router.dispatch(
            "edit.select_next", {"shell": shell},
        ) == {"status": "empty_scene"}

    def test_select_next_skips_locked(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b", locked=True)
        c = _FakeEntity("c")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_selected_entity=a, _scene=scene)
        result = router.dispatch(
            "edit.select_next", {"shell": shell},
        )
        # b is locked → filtered from the roster; next after a is c.
        assert result["entity"] is c


# ---------------------------------------------------------------------------
# edit.paste_at_original_position (4 tests)
# ---------------------------------------------------------------------------


class TestPasteAtOriginalPosition:
    """Cover the Illustrator-style paste wiring."""

    def test_empty_clipboard(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.paste_at_original_position", {},
        )
        assert result == {"status": "empty_clipboard"}

    def test_pastes_at_original_positions(
        self, router: ToolRouter,
    ) -> None:
        # Seed the clipboard via the process singleton so the router
        # dispatch picks it up.
        clipboard = get_active_clipboard()
        clipboard._snapshots = [
            {"name": "hero", "position": [10.0, 20.0, 0.0]},
            {"name": "villain", "position": [30.0, 40.0, 0.0]},
        ]
        result = router.dispatch(
            "edit.paste_at_original_position", {},
        )
        assert result["status"] == "pasted_at_original"
        assert result["count"] == 2
        # Positions preserved.
        assert result["clones"][0]["position"] == [10.0, 20.0, 0.0]
        assert result["clones"][1]["position"] == [30.0, 40.0, 0.0]
        # Default suffix is " (copy)".
        assert result["clones"][0]["name"] == "hero (copy)"

    def test_custom_suffix(self, router: ToolRouter) -> None:
        clipboard = get_active_clipboard()
        clipboard._snapshots = [
            {"name": "widget", "position": [1.0, 2.0, 3.0]},
        ]
        result = router.dispatch(
            "edit.paste_at_original_position",
            {"name_suffix": ""},
        )
        assert result["clones"][0]["name"] == "widget"
        # Positions still preserved.
        assert result["clones"][0]["position"] == [1.0, 2.0, 3.0]

    def test_adds_to_scene_when_reachable(
        self, router: ToolRouter,
    ) -> None:
        added: list[dict] = []

        class _Scene:
            def add_entity(self, ent: dict) -> None:
                added.append(ent)

        clipboard = get_active_clipboard()
        clipboard._snapshots = [
            {"name": "pickup", "position": [0.0, 0.0, 0.0]},
        ]
        result = router.dispatch(
            "edit.paste_at_original_position",
            {"scene": _Scene()},
        )
        assert result["added"] == 1
        assert len(added) == 1
        assert added[0]["name"] == "pickup (copy)"


# ---------------------------------------------------------------------------
# spawn.spawn_batch_row (5 tests)
# ---------------------------------------------------------------------------


class TestSpawnBatchRow:
    """Cover the row-batch spawn wiring."""

    def test_horizontal_row_default(self, router: ToolRouter) -> None:
        recorder = _SpawnRecorder()
        recorder._last_spawn = (
            "hero_card",
            {"position": [0.0, 0.0, 0.0]},
        )
        result = router.dispatch(
            "spawn.spawn_batch_row",
            {"shell": recorder, "count": 4},
        )
        assert result["status"] == "batched_row"
        assert result["count"] == 4
        assert result["stride"] == (1.0, 0.0, 0.0)
        # Row layout: X grows, Y/Z stay.
        positions = [c["position"] for c in result["specs"]]
        assert positions == [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
        ]
        # Each dispatched through the shell's _on_spawn.
        assert len(recorder.calls) == 4
        assert recorder.calls[0][0] == "hero_card"

    def test_vertical_direction(self, router: ToolRouter) -> None:
        recorder = _SpawnRecorder()
        recorder._last_spawn = (
            "pickup",
            {"position": [5.0, 5.0, 0.0]},
        )
        result = router.dispatch(
            "spawn.spawn_batch_row",
            {
                "shell": recorder,
                "count": 3,
                "direction": "vertical",
                "spacing": 2.0,
            },
        )
        assert result["stride"] == (0.0, 2.0, 0.0)
        positions = [c["position"] for c in result["specs"]]
        assert positions == [
            [5.0, 5.0, 0.0],
            [5.0, 7.0, 0.0],
            [5.0, 9.0, 0.0],
        ]

    def test_explicit_stride_overrides_direction(
        self, router: ToolRouter,
    ) -> None:
        recorder = _SpawnRecorder()
        recorder._last_spawn = (
            "torch",
            {"position": [0.0, 0.0, 0.0]},
        )
        result = router.dispatch(
            "spawn.spawn_batch_row",
            {
                "shell": recorder,
                "count": 2,
                "stride": (1.5, 2.5, 3.5),
            },
        )
        assert result["stride"] == (1.5, 2.5, 3.5)
        assert result["specs"][1]["position"] == [1.5, 2.5, 3.5]

    def test_no_shell_returns_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("spawn.spawn_batch_row", {}) == {
            "status": "no_shell",
        }

    def test_no_history(self, router: ToolRouter) -> None:
        recorder = _SpawnRecorder()
        # No _last_spawn assigned.
        assert router.dispatch(
            "spawn.spawn_batch_row", {"shell": recorder},
        ) == {"status": "no_history"}

    def test_count_zero_short_circuits(self, router: ToolRouter) -> None:
        recorder = _SpawnRecorder()
        recorder._last_spawn = ("x", {"position": [0.0, 0.0, 0.0]})
        assert router.dispatch(
            "spawn.spawn_batch_row",
            {"shell": recorder, "count": 0},
        ) == {"status": "no_history"}

    def test_last_spawn_slot_updated_to_final(
        self, router: ToolRouter,
    ) -> None:
        recorder = _SpawnRecorder()
        recorder._last_spawn = (
            "card_id",
            {"position": [0.0, 0.0, 0.0]},
        )
        result = router.dispatch(
            "spawn.spawn_batch_row",
            {"shell": recorder, "count": 3, "spacing": 1.0},
        )
        # Final cell was at X=2.
        assert result["specs"][-1]["position"] == [2.0, 0.0, 0.0]
        # Last-spawn slot bumped to the final cell.
        assert recorder._last_spawn is not None
        assert recorder._last_spawn[1]["position"] == [2.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# content.duplicate_asset (5 tests)
# ---------------------------------------------------------------------------


class TestDuplicateAsset:
    """Cover the content.duplicate_asset wiring."""

    def test_duplicates_file_with_copy_suffix(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "hero.png"
        src.write_bytes(b"pixels")
        result = router.dispatch(
            "content.duplicate_asset", {"path": str(src)},
        )
        assert result["status"] == "duplicated"
        assert result["kind"] == "file"
        assert result["name"] == "hero_copy.png"
        dst = tmp_path / "hero_copy.png"
        assert dst.exists()
        assert dst.read_bytes() == b"pixels"
        # Source is untouched.
        assert src.exists()
        assert result["size"] == len(b"pixels")

    def test_duplicates_directory_recursively(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        folder = tmp_path / "Sprites"
        folder.mkdir()
        (folder / "hero.png").write_bytes(b"aaa")
        (folder / "villain.png").write_bytes(b"bb")
        result = router.dispatch(
            "content.duplicate_asset", {"path": str(folder)},
        )
        assert result["status"] == "duplicated"
        assert result["kind"] == "dir"
        assert result["name"] == "Sprites_copy"
        dst = tmp_path / "Sprites_copy"
        assert dst.is_dir()
        assert (dst / "hero.png").read_bytes() == b"aaa"
        assert (dst / "villain.png").read_bytes() == b"bb"
        # Source untouched.
        assert (folder / "hero.png").exists()
        assert result["size"] == 5  # 3 + 2 bytes

    def test_repeated_duplicate_auto_uniquifies(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "art.png"
        src.write_bytes(b"1")
        first = router.dispatch(
            "content.duplicate_asset", {"path": str(src)},
        )
        assert first["name"] == "art_copy.png"
        # Duplicate again — first collides, uniquify picks _2.
        second = router.dispatch(
            "content.duplicate_asset", {"path": str(src)},
        )
        assert second["name"] == "art_copy_2.png"
        assert (tmp_path / "art_copy.png").exists()
        assert (tmp_path / "art_copy_2.png").exists()

    def test_missing_path(self, router: ToolRouter) -> None:
        assert router.dispatch("content.duplicate_asset", {}) == {
            "status": "missing_path",
        }

    def test_not_found(self, router: ToolRouter, tmp_path: Path) -> None:
        result = router.dispatch(
            "content.duplicate_asset",
            {"path": str(tmp_path / "does_not_exist.png")},
        )
        assert result["status"] == "not_found"

    def test_refreshes_browser(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "prop.png"
        src.write_bytes(b"x")
        browser = _FakeBrowser(tmp_path)
        shell = SimpleNamespace(_content_browser=browser)
        result = router.dispatch(
            "content.duplicate_asset",
            {"path": str(src), "shell": shell},
        )
        assert result["status"] == "duplicated"
        assert browser.refresh_count == 1

    def test_custom_suffix(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        src = tmp_path / "hero.png"
        src.write_bytes(b"pixels")
        result = router.dispatch(
            "content.duplicate_asset",
            {"path": str(src), "suffix": "_backup"},
        )
        assert result["name"] == "hero_backup.png"
        assert (tmp_path / "hero_backup.png").exists()


# ---------------------------------------------------------------------------
# ensure_ctx guardrail (1 test)
# ---------------------------------------------------------------------------


class TestCtxGuardrail:
    """Confirm non-dict ctx raises through the router."""

    def test_ctx_must_be_dict(self, router: ToolRouter) -> None:
        with pytest.raises(TypeError):
            router.dispatch("edit.select_next", [])  # type: ignore[arg-type]
