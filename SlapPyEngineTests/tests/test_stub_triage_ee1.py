"""EE1 STUB-triage tests — eighth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 EE1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"EE1 STUB-triage patch"):

* ``edit.group_selection`` — bundle the current selection into a
  ``GroupEntity`` sitting at the selection centroid; retarget the shell's
  selection at the wrapper.
* ``edit.ungroup_selection`` — flatten a group, restoring absolute
  positions on the released children and clearing the group from the
  scene.
* ``theme.random`` — pick a random registered theme; deterministic under
  ``ctx["rng"]``; excludes the current theme by default so a click never
  no-ops.
* ``spawn.spawn_at_cursor`` — either arm the next spawn to the cursor
  position (default) or re-fire ``shell._last_spawn`` centered on the
  cursor (``mode="repeat"``).
* ``edit.snap_to_pixel_grid`` — round selected entity positions to
  integer pixels (or an arbitrary ``pixel_size`` grid).

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised end-to-end.
No DPG context is required — the fixtures use :class:`SimpleNamespace`
stand-ins for the shell / scene handles.
"""
from __future__ import annotations

import random
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
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


class _FakeEntity:
    """Minimal attribute-holding entity stand-in."""

    def __init__(self, name: str, position: list[float] | None = None) -> None:
        self.name = name
        self.position: list[float] = list(position or [0.0, 0.0, 0.0])

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"_FakeEntity(name={self.name!r}, position={self.position!r})"


class _FakeScene:
    """Scene stand-in exposing ``entities`` + add / remove semantics."""

    def __init__(self, entities: list[Any] | None = None) -> None:
        self._entities: list[Any] = list(entities or [])

    @property
    def entities(self) -> list[Any]:
        return self._entities

    def add_entity(self, entity: Any) -> None:
        self._entities.append(entity)

    def remove_entity(self, entity: Any) -> None:
        try:
            self._entities.remove(entity)
        except ValueError:
            pass


def _shell(scene: _FakeScene | None = None) -> SimpleNamespace:
    ns = SimpleNamespace()
    if scene is not None:
        ns._engine = SimpleNamespace(scene=scene)
    return ns


# ---------------------------------------------------------------------------
# Registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 EE1 action ids are on the canonical router."""

    def test_edit_group_selection_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.group_selection")

    def test_edit_ungroup_selection_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.ungroup_selection")

    def test_theme_random_registered(self, router: ToolRouter) -> None:
        assert router.has_action("theme.random")

    def test_spawn_at_cursor_registered(self, router: ToolRouter) -> None:
        assert router.has_action("spawn.spawn_at_cursor")

    def test_snap_to_pixel_grid_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.snap_to_pixel_grid")

    def test_all_ee1_on_module_singleton(self) -> None:
        for aid in (
            "edit.group_selection",
            "edit.ungroup_selection",
            "theme.random",
            "spawn.spawn_at_cursor",
            "edit.snap_to_pixel_grid",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# edit.group_selection (5 tests)
# ---------------------------------------------------------------------------


class TestGroupSelection:
    """Cover the edit.group_selection wiring."""

    def test_groups_multiple_entities(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", [0.0, 0.0, 0.0])
        b = _FakeEntity("b", [10.0, 0.0, 0.0])
        scene = _FakeScene([a, b])
        shell = _shell(scene)
        shell._selected_entities = [a, b]

        result = router.dispatch(
            "edit.group_selection", {"shell": shell},
        )
        assert result["status"] == "grouped"
        assert result["count"] == 2
        # Centroid of (0,0,0) + (10,0,0) is (5,0,0).
        assert result["centroid"] == (5.0, 0.0, 0.0)
        # Scene now holds only the group.
        assert len(scene.entities) == 1
        group = scene.entities[0]
        assert result["group"] is group
        assert group.position == [5.0, 0.0, 0.0]
        # Children have been re-parented relative to the centroid.
        assert a.position == [-5.0, 0.0, 0.0]
        assert b.position == [5.0, 0.0, 0.0]
        # Shell selection retargets at the group.
        assert shell._selected_entity is group

    def test_no_selection_returns_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = _shell(scene)
        assert router.dispatch(
            "edit.group_selection", {"shell": shell},
        ) == {"status": "no_selection"}

    def test_no_scene_returns_status(self, router: ToolRouter) -> None:
        assert router.dispatch("edit.group_selection", {}) == {
            "status": "no_scene",
        }

    def test_explicit_selection_override(self, router: ToolRouter) -> None:
        # Shell has one entity selected, but ctx["selection"] overrides.
        a = _FakeEntity("a", [1.0, 2.0, 3.0])
        b = _FakeEntity("b", [3.0, 4.0, 5.0])
        scene = _FakeScene([a, b])
        shell = _shell(scene)
        shell._selected_entity = a

        result = router.dispatch(
            "edit.group_selection",
            {"shell": shell, "selection": [a, b], "name": "team"},
        )
        assert result["status"] == "grouped"
        assert result["group"].name == "team"

    def test_dict_entity_supported(self, router: ToolRouter) -> None:
        # Dict-shaped entities still round-trip through the group flow.
        a = {"position": [0.0, 0.0, 0.0], "name": "a"}
        b = {"position": [4.0, 0.0, 0.0], "name": "b"}
        scene = _FakeScene([a, b])
        shell = _shell(scene)
        shell._selected_entities = [a, b]

        result = router.dispatch(
            "edit.group_selection", {"shell": shell},
        )
        assert result["status"] == "grouped"
        assert result["centroid"] == (2.0, 0.0, 0.0)
        # Children re-parented in-place.
        assert a["position"] == [-2.0, 0.0, 0.0]
        assert b["position"] == [2.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# edit.ungroup_selection (4 tests)
# ---------------------------------------------------------------------------


class TestUngroupSelection:
    """Cover the edit.ungroup_selection wiring."""

    def test_ungroup_restores_absolute_positions(
        self, router: ToolRouter,
    ) -> None:
        # Build a group by hand: centroid (5,0,0), two children at
        # (-5,0,0) and (5,0,0) — matches what group_selection would emit.
        a = _FakeEntity("a", [-5.0, 0.0, 0.0])
        b = _FakeEntity("b", [5.0, 0.0, 0.0])
        from slappyengine.actions.edit_group_actions import _GroupEntity

        group = _GroupEntity(position=[5.0, 0.0, 0.0], children=[a, b])
        scene = _FakeScene([group])
        shell = _shell(scene)
        shell._selected_entity = group

        result = router.dispatch(
            "edit.ungroup_selection", {"shell": shell},
        )
        assert result["status"] == "ungrouped"
        assert result["count"] == 2
        # Children now sit in the scene at absolute positions.
        assert group not in scene.entities
        assert a in scene.entities
        assert b in scene.entities
        assert a.position == [0.0, 0.0, 0.0]
        assert b.position == [10.0, 0.0, 0.0]
        # Shell selection retargets at the released children.
        assert shell._selected_entities == [a, b]

    def test_no_selection_returns_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = _shell(scene)
        assert router.dispatch(
            "edit.ungroup_selection", {"shell": shell},
        ) == {"status": "no_selection"}

    def test_not_a_group_returns_status(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", [1.0, 2.0, 3.0])
        scene = _FakeScene([a])
        shell = _shell(scene)
        shell._selected_entity = a
        assert router.dispatch(
            "edit.ungroup_selection", {"shell": shell},
        ) == {"status": "not_a_group"}

    def test_no_scene_returns_status(self, router: ToolRouter) -> None:
        assert router.dispatch("edit.ungroup_selection", {}) == {
            "status": "no_scene",
        }


# ---------------------------------------------------------------------------
# theme.random (5 tests)
# ---------------------------------------------------------------------------


class TestRandomTheme:
    """Cover the theme.random wiring."""

    def test_picks_from_registry_via_rng(self, router: ToolRouter) -> None:
        rng = random.Random(42)  # deterministic
        result = router.dispatch(
            "theme.random",
            {"themes": ["dark", "light", "sunset"], "rng": rng,
             "exclude_current": False},
        )
        assert result["status"] == "randomised"
        assert result["theme"] in ("dark", "light", "sunset")
        assert result["path"] == "fallback"

    def test_shell_hook_used_when_present(self, router: ToolRouter) -> None:
        applied: list[str] = []
        shell = _shell()
        shell.set_theme = lambda name: applied.append(name)
        rng = random.Random(1)
        result = router.dispatch(
            "theme.random",
            {"shell": shell, "themes": ["a", "b", "c"], "rng": rng,
             "exclude_current": False},
        )
        assert result["path"] == "shell"
        assert applied == [result["theme"]]

    def test_excludes_current_theme_by_default(
        self, router: ToolRouter,
    ) -> None:
        # Seed the theme cursor at "dark" so the exclude filter kicks in.
        from slappyengine.actions import theme_actions as ta
        ta._reset_theme_cursor_for_tests()
        ta._THEME_CURSOR = "dark"

        # With only ["dark", "light"], random must land on "light".
        rng = random.Random(0)
        result = router.dispatch(
            "theme.random",
            {"themes": ["dark", "light"], "rng": rng},
        )
        assert result["theme"] == "light"

    def test_single_theme_short_circuits(self, router: ToolRouter) -> None:
        from slappyengine.actions import theme_actions as ta
        ta._reset_theme_cursor_for_tests()
        ta._THEME_CURSOR = "only"
        result = router.dispatch(
            "theme.random",
            {"themes": ["only"]},
        )
        assert result == {"status": "single_theme", "theme": "only"}

    def test_no_themes_returns_status(self, router: ToolRouter) -> None:
        # Empty override falls through to the real registry — accept
        # either the "no_themes" short-circuit or a successful randomise.
        result = router.dispatch(
            "theme.random", {"themes": []},
        )
        assert result["status"] in ("no_themes", "randomised", "single_theme")


# ---------------------------------------------------------------------------
# spawn.spawn_at_cursor (5 tests)
# ---------------------------------------------------------------------------


class TestSpawnAtCursor:
    """Cover the spawn.spawn_at_cursor wiring."""

    def test_arms_shell_pending_position(self, router: ToolRouter) -> None:
        shell = _shell()
        shell._cursor_world_position = [12.0, 34.0, 0.0]
        result = router.dispatch(
            "spawn.spawn_at_cursor", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["position"] == (12.0, 34.0, 0.0)
        # Shell now carries the coordinate for the next spawn to consume.
        assert shell._pending_spawn_position == [12.0, 34.0, 0.0]

    def test_repeat_mode_dispatches_at_cursor(
        self, router: ToolRouter,
    ) -> None:
        calls: list[tuple[str, dict]] = []
        shell = _shell()
        shell._cursor_world_position = [7.0, 8.0, 0.0]
        shell._on_spawn = lambda cid, spec: calls.append((cid, dict(spec)))
        shell._last_spawn = ("cube", {"position": [0.0, 0.0, 0.0]})

        result = router.dispatch(
            "spawn.spawn_at_cursor",
            {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "respawned"
        assert result["card_id"] == "cube"
        assert result["position"] == (7.0, 8.0, 0.0)
        # _on_spawn actually fired with the cursor-centered spec.
        assert len(calls) == 1
        assert calls[0][1]["position"] == [7.0, 8.0, 0.0]

    def test_repeat_falls_back_to_arm(self, router: ToolRouter) -> None:
        # No history — repeat mode should degrade to arm.
        shell = _shell()
        shell._cursor_world_position = [1.0, 2.0]
        result = router.dispatch(
            "spawn.spawn_at_cursor",
            {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "armed"
        assert result["position"] == (1.0, 2.0, 0.0)

    def test_no_cursor_returns_status(self, router: ToolRouter) -> None:
        shell = _shell()
        assert router.dispatch(
            "spawn.spawn_at_cursor", {"shell": shell},
        ) == {"status": "no_cursor"}

    def test_ctx_cursor_override(self, router: ToolRouter) -> None:
        # Headless caller — no shell, explicit cursor.
        result = router.dispatch(
            "spawn.spawn_at_cursor",
            {"cursor": [3.5, 4.5, 5.5]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (3.5, 4.5, 5.5)


# ---------------------------------------------------------------------------
# edit.snap_to_pixel_grid (5 tests)
# ---------------------------------------------------------------------------


class TestSnapToPixelGrid:
    """Cover the edit.snap_to_pixel_grid wiring."""

    def test_snaps_selection_to_integer_pixels(
        self, router: ToolRouter,
    ) -> None:
        a = _FakeEntity("a", [1.4, 2.6, 0.0])
        b = _FakeEntity("b", [3.5, 4.5, 0.0])
        shell = _shell()
        shell._selected_entities = [a, b]

        result = router.dispatch(
            "edit.snap_to_pixel_grid", {"shell": shell},
        )
        assert result["status"] == "snapped"
        assert result["count"] == 2
        assert result["moved"] == 2
        # 1.4 -> 1, 2.6 -> 3; 3.5 -> 4 (banker's rounding); 4.5 -> 4.
        assert a.position == [1.0, 3.0, 0.0]
        assert b.position == [4.0, 4.0, 0.0]

    def test_integer_positions_are_no_op(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", [1.0, 2.0, 0.0])
        shell = _shell()
        shell._selected_entity = a

        result = router.dispatch(
            "edit.snap_to_pixel_grid", {"shell": shell},
        )
        assert result["status"] == "snapped"
        assert result["count"] == 1
        assert result["moved"] == 0
        assert a.position == [1.0, 2.0, 0.0]

    def test_custom_pixel_size(self, router: ToolRouter) -> None:
        # A 32-pixel tilemap: positions snap to multiples of 32.
        a = _FakeEntity("a", [15.0, 40.0, 0.0])
        shell = _shell()
        shell._selected_entity = a

        result = router.dispatch(
            "edit.snap_to_pixel_grid",
            {"shell": shell, "pixel_size": 32},
        )
        assert result["status"] == "snapped"
        # 15 -> 0, 40 -> 32.
        assert a.position == [0.0, 32.0, 0.0]

    def test_no_selection_returns_status(self, router: ToolRouter) -> None:
        shell = _shell()
        assert router.dispatch(
            "edit.snap_to_pixel_grid", {"shell": shell},
        ) == {"status": "no_selection"}

    def test_all_flag_walks_scene(self, router: ToolRouter) -> None:
        a = _FakeEntity("a", [0.7, 0.7, 0.0])
        b = _FakeEntity("b", [2.2, 2.2, 0.0])
        scene = _FakeScene([a, b])
        shell = _shell(scene)
        # No selection on purpose — the "all" flag ignores the selection.

        result = router.dispatch(
            "edit.snap_to_pixel_grid",
            {"shell": shell, "all": True},
        )
        assert result["status"] == "snapped"
        assert result["count"] == 2
        assert a.position == [1.0, 1.0, 0.0]
        assert b.position == [2.0, 2.0, 0.0]


# ---------------------------------------------------------------------------
# ctx-guards (2 tests × 5 action ids)
# ---------------------------------------------------------------------------


class TestCtxGuards:
    """Confirm the shared ``ensure_ctx`` guard fires on non-mapping input."""

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.group_selection",
            "edit.ungroup_selection",
            "theme.random",
            "spawn.spawn_at_cursor",
            "edit.snap_to_pixel_grid",
        ],
    )
    def test_none_ctx_raises(self, action_id: str) -> None:
        from slappyengine.actions.edit_group_actions import (
            group_selection,
            ungroup_selection,
        )
        from slappyengine.actions.theme_random_actions import random_theme
        from slappyengine.actions.spawn_cursor_actions import spawn_at_cursor
        from slappyengine.actions.edit_snap_pixel_actions import (
            snap_to_pixel_grid,
        )

        mapping = {
            "edit.group_selection": group_selection,
            "edit.ungroup_selection": ungroup_selection,
            "theme.random": random_theme,
            "spawn.spawn_at_cursor": spawn_at_cursor,
            "edit.snap_to_pixel_grid": snap_to_pixel_grid,
        }
        with pytest.raises(TypeError):
            mapping[action_id](None)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.group_selection",
            "edit.ungroup_selection",
            "theme.random",
            "spawn.spawn_at_cursor",
            "edit.snap_to_pixel_grid",
        ],
    )
    def test_list_ctx_raises(self, action_id: str) -> None:
        from slappyengine.actions.edit_group_actions import (
            group_selection,
            ungroup_selection,
        )
        from slappyengine.actions.theme_random_actions import random_theme
        from slappyengine.actions.spawn_cursor_actions import spawn_at_cursor
        from slappyengine.actions.edit_snap_pixel_actions import (
            snap_to_pixel_grid,
        )

        mapping = {
            "edit.group_selection": group_selection,
            "edit.ungroup_selection": ungroup_selection,
            "theme.random": random_theme,
            "spawn.spawn_at_cursor": spawn_at_cursor,
            "edit.snap_to_pixel_grid": snap_to_pixel_grid,
        }
        with pytest.raises(TypeError):
            mapping[action_id](["not", "a", "mapping"])  # type: ignore[arg-type]
