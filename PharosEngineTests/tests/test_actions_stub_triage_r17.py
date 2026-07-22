"""PP1 STUB-triage tests — round 17 of feature-map wiring.

Covers the five new action ids added by the PP1 sprint tick (round 17
after OO1's round-16 layer / selection / snap batch):

* ``selection.shrink`` — Blender ``Ctrl+Numpad-`` shrink-selection.
* ``selection.invert_by_type`` — Blender ``Select → All by Type``.
* ``view.toggle_wireframe`` — Blender ``Z → Wireframe`` overlay.
* ``edit.rename`` — Unity / Blender ``F2`` rename-entity.
* ``edit.duplicate_at_cursor`` — Blender ``Shift+D`` duplicate-to-cursor.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / entity handles.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pharos_editor.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    r = ToolRouter()
    register_default_actions(r)
    return r


class _Entity:
    def __init__(
        self,
        name: str,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        kind: str | None = None,
    ) -> None:
        self.name = name
        self.position = list(position)
        if kind is not None:
            self.kind = kind


class _Scene:
    def __init__(self) -> None:
        self.entities: list[_Entity] = []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_selection_shrink_registered(self, router: ToolRouter) -> None:
        assert router.has_action("selection.shrink")

    def test_selection_invert_by_type_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("selection.invert_by_type")

    def test_view_toggle_wireframe_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_wireframe")

    def test_edit_rename_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.rename")

    def test_edit_duplicate_at_cursor_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.duplicate_at_cursor")

    def test_all_pp1_on_module_singleton(self) -> None:
        for aid in (
            "selection.shrink",
            "selection.invert_by_type",
            "view.toggle_wireframe",
            "edit.rename",
            "edit.duplicate_at_cursor",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_pp1_categories(self, router: ToolRouter) -> None:
        expected: dict[str, str] = {
            "selection.shrink": "selection",
            "selection.invert_by_type": "selection",
            "view.toggle_wireframe": "view",
            "edit.rename": "edit",
            "edit.duplicate_at_cursor": "edit",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# selection.shrink
# ---------------------------------------------------------------------------


class TestSelectionShrink:
    def test_shrink_drops_boundary_entity(self, router: ToolRouter) -> None:
        # Layout: seed = [a, b], scene also has c near b. b is on
        # boundary (c is a nearby non-selected neighbour within radius),
        # a is interior (c is far outside radius).
        scene = _Scene()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(100.0, 0.0, 0.0))
        c = _Entity("c", position=(105.0, 0.0, 0.0))  # neighbour of b only
        scene.entities = [a, b, c]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[a, b])
        # radius=10.0 → c is within 10 of b (dist 5) but far from a (dist 105).
        result = router.dispatch(
            "selection.shrink", {"shell": shell, "radius": 10.0},
        )
        assert result["status"] == "shrunk"
        assert result["removed"] == 1
        assert b not in result["selection"]
        assert a in result["selection"]

    def test_shrink_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.shrink", {})
        assert result == {"status": "no_scene"}

    def test_shrink_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("selection.shrink", {"scene": scene})
        assert result["status"] == "no_selection"

    def test_shrink_unchanged_when_all_interior(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(10.0, 0.0, 0.0))
        far = _Entity("far", position=(1_000_000.0, 0.0, 0.0))
        scene.entities = [a, b, far]
        result = router.dispatch(
            "selection.shrink",
            {"scene": scene, "selection": [a, b], "radius": 20.0},
        )
        # far is not within radius of a or b — so neither has an
        # unselected neighbour. Both survive.
        assert result["status"] == "unchanged"
        assert a in result["selection"]
        assert b in result["selection"]

    def test_shrink_emptied_when_all_on_boundary(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(5.0, 0.0, 0.0))
        c = _Entity("c", position=(2.0, 0.0, 0.0))  # non-selected, near both
        scene.entities = [a, b, c]
        result = router.dispatch(
            "selection.shrink",
            {"scene": scene, "selection": [a, b], "radius": 100.0},
        )
        assert result["status"] == "emptied"
        assert result["previous_count"] == 2


# ---------------------------------------------------------------------------
# selection.invert_by_type
# ---------------------------------------------------------------------------


class TestSelectionInvertByType:
    def test_invert_grabs_matching_kinds(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope")
        r1 = _Entity("r1", kind="rope")
        r2 = _Entity("r2", kind="rope")
        other = _Entity("o", kind="humanoid")
        scene.entities = [seed, r1, r2, other]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch(
            "selection.invert_by_type", {"shell": shell},
        )
        assert result["status"] == "inverted"
        assert result["added"] == 2
        assert r1 in result["selection"]
        assert r2 in result["selection"]
        assert other not in result["selection"]
        # seed itself is excluded from the result.
        assert seed not in result["selection"]

    def test_invert_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.invert_by_type", {})
        assert result == {"status": "no_scene"}

    def test_invert_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch(
            "selection.invert_by_type", {"scene": scene},
        )
        assert result["status"] == "no_selection"

    def test_invert_no_matches(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope")
        other = _Entity("o", kind="humanoid")
        scene.entities = [seed, other]
        result = router.dispatch(
            "selection.invert_by_type",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "no_matches"
        assert result["kinds"] == ["rope"]

    def test_invert_falls_back_to_class_name(
        self, router: ToolRouter,
    ) -> None:
        # No kind attr — should group by type().__name__.
        scene = _Scene()
        a = _Entity("a")
        b = _Entity("b")
        scene.entities = [a, b]
        result = router.dispatch(
            "selection.invert_by_type",
            {"scene": scene, "selection": [a]},
        )
        assert result["status"] == "inverted"
        assert b in result["selection"]


# ---------------------------------------------------------------------------
# view.toggle_wireframe
# ---------------------------------------------------------------------------


class TestViewToggleWireframe:
    def test_toggle_off_to_on(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_wireframe_visible=False)
        result = router.dispatch("view.toggle_wireframe", {"shell": shell})
        assert result["status"] == "toggled"
        assert result["visible"] is True
        assert shell._wireframe_visible is True
        assert result["previous"] is False

    def test_toggle_on_to_off(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_wireframe_visible=True)
        result = router.dispatch("view.toggle_wireframe", {"shell": shell})
        assert result["visible"] is False
        assert shell._wireframe_visible is False

    def test_toggle_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_wireframe", {})
        assert result == {"status": "no_shell"}

    def test_toggle_visible_seed(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_wireframe", {"visible": True},
        )
        assert result["status"] == "toggled"
        assert result["visible"] is False

    def test_toggle_fires_view_hook(self, router: ToolRouter) -> None:
        seen: list[tuple[str, bool]] = []

        def hook(attr: str, val: bool) -> None:
            seen.append((attr, val))

        shell = SimpleNamespace(_wireframe_visible=False, _on_view_toggle=hook)
        router.dispatch("view.toggle_wireframe", {"shell": shell})
        assert seen == [("_wireframe_visible", True)]

    def test_toggle_target_field(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_wireframe_visible=False)
        result = router.dispatch("view.toggle_wireframe", {"shell": shell})
        assert result["target"] == "wireframe"


# ---------------------------------------------------------------------------
# edit.rename
# ---------------------------------------------------------------------------


class TestEditRename:
    def test_single_entity_rename(self, router: ToolRouter) -> None:
        e = _Entity("old")
        shell = SimpleNamespace(_selected_entity=e)
        result = router.dispatch(
            "edit.rename", {"shell": shell, "new_name": "new"},
        )
        assert result["status"] == "renamed"
        assert result["count"] == 1
        assert e.name == "new"

    def test_multi_entity_rename_appends_index(
        self, router: ToolRouter,
    ) -> None:
        a = _Entity("a")
        b = _Entity("b")
        c = _Entity("c")
        shell = SimpleNamespace(_selected_entities=[a, b, c])
        result = router.dispatch(
            "edit.rename", {"shell": shell, "new_name": "row"},
        )
        assert result["status"] == "renamed"
        assert result["count"] == 3
        assert a.name == "row_01"
        assert b.name == "row_02"
        assert c.name == "row_03"

    def test_missing_new_name(self, router: ToolRouter) -> None:
        e = _Entity("old")
        result = router.dispatch(
            "edit.rename", {"entity": e, "new_name": ""},
        )
        assert result == {"status": "missing_name"}

    def test_no_selection(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.rename", {"new_name": "x"})
        assert result["status"] == "no_selection"

    def test_invalid_name_rejects_path_separator(
        self, router: ToolRouter,
    ) -> None:
        e = _Entity("old")
        result = router.dispatch(
            "edit.rename", {"entity": e, "new_name": "foo/bar"},
        )
        assert result["status"] == "invalid_name"
        assert e.name == "old"

    def test_whitespace_only_rejected(self, router: ToolRouter) -> None:
        e = _Entity("old")
        result = router.dispatch(
            "edit.rename", {"entity": e, "new_name": "   "},
        )
        assert result["status"] == "invalid_name"

    def test_name_is_trimmed(self, router: ToolRouter) -> None:
        e = _Entity("old")
        router.dispatch(
            "edit.rename", {"entity": e, "new_name": "  fresh  "},
        )
        assert e.name == "fresh"


# ---------------------------------------------------------------------------
# edit.duplicate_at_cursor
# ---------------------------------------------------------------------------


class TestEditDuplicateAtCursor:
    def test_duplicate_places_clone_at_cursor(
        self, router: ToolRouter,
    ) -> None:
        # Reset the process-wide clipboard so prior tests don't leak.
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
        clip = get_active_clipboard()
        clip.clear()

        seed = _Entity("seed", position=(0.0, 0.0, 0.0))
        result = router.dispatch(
            "edit.duplicate_at_cursor",
            {"selection": [seed], "cursor": (100.0, 50.0, 0.0)},
        )
        assert result["status"] == "duplicated_at_cursor"
        assert result["count"] == 1
        assert result["cursor"] == (100.0, 50.0, 0.0)
        clone = result["clones"][0]
        # Snapshot round-trip — clone is a dict with position + name.
        assert clone["position"] == [100.0, 50.0, 0.0]

    def test_duplicate_preserves_relative_offset(
        self, router: ToolRouter,
    ) -> None:
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
        get_active_clipboard().clear()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(10.0, 5.0, 0.0))
        result = router.dispatch(
            "edit.duplicate_at_cursor",
            {"selection": [a, b], "cursor": (100.0, 0.0, 0.0)},
        )
        assert result["status"] == "duplicated_at_cursor"
        clones = result["clones"]
        assert len(clones) == 2
        # Anchor = a's original position (0,0,0). Cursor = (100,0,0).
        # a's clone lands at cursor. b's clone offsets by (10,5,0).
        assert clones[0]["position"] == [100.0, 0.0, 0.0]
        assert clones[1]["position"] == [110.0, 5.0, 0.0]

    def test_duplicate_no_selection(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.duplicate_at_cursor",
            {"cursor": (10.0, 10.0, 0.0)},
        )
        assert result["status"] == "no_selection"

    def test_duplicate_no_cursor(self, router: ToolRouter) -> None:
        seed = _Entity("seed", position=(0.0, 0.0, 0.0))
        result = router.dispatch(
            "edit.duplicate_at_cursor", {"selection": [seed]},
        )
        assert result["status"] == "no_cursor"

    def test_duplicate_cursor_2d_padded_to_3d(
        self, router: ToolRouter,
    ) -> None:
        from pharos_editor.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
        get_active_clipboard().clear()
        seed = _Entity("seed", position=(0.0, 0.0, 0.0))
        result = router.dispatch(
            "edit.duplicate_at_cursor",
            {"selection": [seed], "cursor": (42.0, 13.0)},
        )
        assert result["status"] == "duplicated_at_cursor"
        assert result["cursor"] == (42.0, 13.0, 0.0)
