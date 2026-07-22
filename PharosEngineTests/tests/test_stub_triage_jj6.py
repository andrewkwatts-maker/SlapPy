"""JJ6 STUB-triage tests — twelfth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 JJ6 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"JJ6 STUB-triage patch"):

* ``edit.hide_selection`` — Blender ``H`` — mark selected entities
  invisible.
* ``edit.show_all`` — Blender ``Alt+H`` — un-hide every entity.
* ``edit.lock_selection`` — Maya-style lock-layer — mark selected
  entities uneditable.
* ``edit.unlock_all`` — Maya ``Ctrl+Shift+L`` — clear the lock flag
  scene-wide.
* ``edit.select_by_prefab_kind`` — Blender ``Shift+G`` — select every
  entity whose ``kind`` matches the reference selection (or an explicit
  ``ctx["kind"]``).

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised
end-to-end. No DPG context is required — the fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene handles.
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
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    r = ToolRouter()
    register_default_actions(r)
    return r


class _FakeEntity:
    """Nova3D-style entity with a ``visible`` flag."""

    def __init__(
        self,
        name: str,
        kind: str | None = None,
        locked: bool = False,
        visible: bool = True,
    ) -> None:
        self.name = name
        self.kind = kind
        self.locked = locked
        self.visible = visible


class _LegacyEntity:
    """Ochema-style entity with a ``hidden`` flag (no ``visible``)."""

    def __init__(
        self,
        name: str,
        hidden: bool = False,
        locked: bool = False,
        prefab_kind: str | None = None,
    ) -> None:
        self.name = name
        self.hidden = hidden
        self.locked = locked
        if prefab_kind is not None:
            self.prefab_kind = prefab_kind


class _FakeScene:
    def __init__(self, entities: list[Any]) -> None:
        self.entities = entities


# ---------------------------------------------------------------------------
# Registration checks (7 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 JJ6 action ids are on the canonical router."""

    def test_edit_hide_selection_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.hide_selection")

    def test_edit_show_all_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.show_all")

    def test_edit_lock_selection_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.lock_selection")

    def test_edit_unlock_all_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.unlock_all")

    def test_edit_select_by_prefab_kind_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.select_by_prefab_kind")

    def test_all_jj6_on_module_singleton(self) -> None:
        for aid in (
            "edit.hide_selection",
            "edit.show_all",
            "edit.lock_selection",
            "edit.unlock_all",
            "edit.select_by_prefab_kind",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_all_jj6_categorised_as_edit(self, router: ToolRouter) -> None:
        for aid in (
            "edit.hide_selection",
            "edit.show_all",
            "edit.lock_selection",
            "edit.unlock_all",
            "edit.select_by_prefab_kind",
        ):
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == "edit", aid


# ---------------------------------------------------------------------------
# edit.hide_selection (5 tests)
# ---------------------------------------------------------------------------


class TestHideSelection:
    def test_hides_single_entity(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.hide_selection", {"shell": shell})
        assert result["status"] == "hidden"
        assert result["count"] == 1
        assert a.visible is False

    def test_hides_multi_selection(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        c = _FakeEntity("c")
        shell = SimpleNamespace(_selected_entities=[a, b, c])
        result = router.dispatch("edit.hide_selection", {"shell": shell})
        assert result["status"] == "hidden"
        assert result["count"] == 3
        assert a.visible is False
        assert b.visible is False
        assert c.visible is False

    def test_no_selection_returns_status(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("edit.hide_selection", {"shell": shell})
        assert result == {"status": "no_selection"}

    def test_already_hidden_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", visible=False)
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.hide_selection", {"shell": shell})
        assert result == {"status": "already_hidden"}

    def test_hides_legacy_entity_using_hidden_flag(
        self, router: ToolRouter,
    ) -> None:
        a = _LegacyEntity("a", hidden=False)
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.hide_selection", {"shell": shell})
        assert result["status"] == "hidden"
        assert a.hidden is True


# ---------------------------------------------------------------------------
# edit.show_all (4 tests)
# ---------------------------------------------------------------------------


class TestShowAll:
    def test_shows_hidden_entities(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", visible=False)
        b = _FakeEntity("b", visible=False)
        c = _FakeEntity("c", visible=True)
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.show_all", {"shell": shell})
        assert result["status"] == "shown"
        assert result["count"] == 2
        assert result["previous_hidden_count"] == 2
        assert a.visible is True
        assert b.visible is True
        assert c.visible is True

    def test_no_scene_returns_status(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("edit.show_all", {"shell": shell})
        assert result == {"status": "no_scene"}

    def test_empty_scene_returns_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.show_all", {"shell": shell})
        assert result == {"status": "empty_scene"}

    def test_all_visible_returns_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", visible=True)
        b = _FakeEntity("b", visible=True)
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.show_all", {"shell": shell})
        assert result == {"status": "all_visible"}

    def test_show_all_clears_legacy_hidden_flag(
        self, router: ToolRouter,
    ) -> None:
        a = _LegacyEntity("a", hidden=True)
        b = _LegacyEntity("b", hidden=True)
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.show_all", {"shell": shell})
        assert result["status"] == "shown"
        assert result["count"] == 2
        assert a.hidden is False
        assert b.hidden is False


# ---------------------------------------------------------------------------
# edit.lock_selection (4 tests)
# ---------------------------------------------------------------------------


class TestLockSelection:
    def test_locks_single_entity(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.lock_selection", {"shell": shell})
        assert result["status"] == "locked"
        assert result["count"] == 1
        assert a.locked is True

    def test_locks_multi_selection(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        shell = SimpleNamespace(_selected_entities=[a, b])
        result = router.dispatch("edit.lock_selection", {"shell": shell})
        assert result["status"] == "locked"
        assert result["count"] == 2
        assert a.locked is True
        assert b.locked is True

    def test_no_selection_status(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("edit.lock_selection", {"shell": shell})
        assert result == {"status": "no_selection"}

    def test_already_locked_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", locked=True)
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.lock_selection", {"shell": shell})
        assert result == {"status": "already_locked"}


# ---------------------------------------------------------------------------
# edit.unlock_all (4 tests)
# ---------------------------------------------------------------------------


class TestUnlockAll:
    def test_unlocks_scene_wide(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", locked=True)
        b = _FakeEntity("b", locked=True)
        c = _FakeEntity("c", locked=False)
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.unlock_all", {"shell": shell})
        assert result["status"] == "unlocked"
        assert result["count"] == 2
        assert result["previous_locked_count"] == 2
        assert a.locked is False
        assert b.locked is False

    def test_no_scene_status(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("edit.unlock_all", {"shell": shell})
        assert result == {"status": "no_scene"}

    def test_empty_scene_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.unlock_all", {"shell": shell})
        assert result == {"status": "empty_scene"}

    def test_all_unlocked_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch("edit.unlock_all", {"shell": shell})
        assert result == {"status": "all_unlocked"}


# ---------------------------------------------------------------------------
# edit.select_by_prefab_kind (6 tests)
# ---------------------------------------------------------------------------


class TestSelectByPrefabKind:
    def test_selects_by_explicit_kind(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", kind="rope")
        b = _FakeEntity("b", kind="softbody")
        c = _FakeEntity("c", kind="rope")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "rope"},
        )
        assert result["status"] == "selected"
        assert result["kind"] == "rope"
        assert result["count"] == 2
        assert set(id(e) for e in result["selection"]) == {id(a), id(c)}
        assert shell._selected_entities == [a, c]

    def test_derives_kind_from_current_selection(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a", kind="rope")
        b = _FakeEntity("b", kind="softbody")
        c = _FakeEntity("c", kind="rope")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_scene=scene, _selected_entity=a)
        result = router.dispatch(
            "edit.select_by_prefab_kind", {"shell": shell},
        )
        assert result["status"] == "selected"
        assert result["kind"] == "rope"
        assert result["count"] == 2

    def test_no_matches_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", kind="rope")
        scene = _FakeScene([a])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "softbody"},
        )
        assert result == {"status": "no_matches", "kind": "softbody"}

    def test_no_scene_status(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "rope"},
        )
        assert result == {"status": "no_scene"}

    def test_no_selection_when_kind_unset(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", kind="rope")
        scene = _FakeScene([a])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_by_prefab_kind", {"shell": shell},
        )
        assert result == {"status": "no_selection"}

    def test_add_mode_extends_selection(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", kind="rope")
        b = _FakeEntity("b", kind="softbody")
        c = _FakeEntity("c", kind="rope")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(
            _scene=scene,
            _selected_entity=b,
            _selected_entities=[b],
        )
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "rope", "mode": "add"},
        )
        assert result["status"] == "selected"
        # Original b + newly-added a, c.
        assert result["count"] == 3
        assert set(id(e) for e in result["selection"]) == {
            id(a), id(b), id(c),
        }

    def test_locked_entities_skipped_by_default(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a", kind="rope")
        b = _FakeEntity("b", kind="rope", locked=True)
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "rope"},
        )
        assert result["status"] == "selected"
        assert result["count"] == 1
        assert result["selection"] == [a]

    def test_prefab_kind_attribute_matches(self, router: ToolRouter) -> None:
        """Legacy entities carry ``prefab_kind`` not ``kind`` — both work."""
        a = _LegacyEntity("a", prefab_kind="rope")
        b = _LegacyEntity("b", prefab_kind="rope")
        c = _LegacyEntity("c", prefab_kind="softbody")
        scene = _FakeScene([a, b, c])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_by_prefab_kind",
            {"shell": shell, "kind": "rope"},
        )
        assert result["status"] == "selected"
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# Cross-cutting: ctx validation (2 tests)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    """Silent-acceptance guard — every JJ6 helper rejects None ctx."""

    def test_hide_selection_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.edit_hide_show_actions import hide_selection
        with pytest.raises(TypeError):
            hide_selection(None)  # type: ignore[arg-type]

    def test_show_all_rejects_list_ctx(self) -> None:
        from pharos_editor.actions.edit_hide_show_actions import show_all
        with pytest.raises(TypeError):
            show_all([])  # type: ignore[arg-type]

    def test_lock_selection_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.edit_lock_unlock_actions import (
            lock_selection,
        )
        with pytest.raises(TypeError):
            lock_selection(None)  # type: ignore[arg-type]

    def test_unlock_all_rejects_list_ctx(self) -> None:
        from pharos_editor.actions.edit_lock_unlock_actions import unlock_all
        with pytest.raises(TypeError):
            unlock_all([])  # type: ignore[arg-type]

    def test_select_by_prefab_kind_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.edit_select_by_kind_actions import (
            select_by_prefab_kind,
        )
        with pytest.raises(TypeError):
            select_by_prefab_kind(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cross-cutting: hide + show + lock + unlock round-trip (1 test)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_hide_then_show_restores(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene, _selected_entities=[a, b])
        # Hide both.
        r1 = router.dispatch("edit.hide_selection", {"shell": shell})
        assert r1["status"] == "hidden"
        assert a.visible is False
        assert b.visible is False
        # Show them again.
        r2 = router.dispatch("edit.show_all", {"shell": shell})
        assert r2["status"] == "shown"
        assert a.visible is True
        assert b.visible is True

    def test_lock_then_unlock_restores(self, router: ToolRouter) -> None:
        a = _FakeEntity("a")
        b = _FakeEntity("b")
        scene = _FakeScene([a, b])
        shell = SimpleNamespace(_scene=scene, _selected_entities=[a, b])
        # Lock both.
        r1 = router.dispatch("edit.lock_selection", {"shell": shell})
        assert r1["status"] == "locked"
        assert a.locked is True
        assert b.locked is True
        # Unlock scene-wide.
        r2 = router.dispatch("edit.unlock_all", {"shell": shell})
        assert r2["status"] == "unlocked"
        assert a.locked is False
        assert b.locked is False
