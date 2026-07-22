"""ZZ4 STUB-triage tests — round 26 of feature-map wiring.

Covers the five new action ids added by the ZZ4 sprint tick (round 26
after YY4's round-25 ``view.toggle_snap_indicator`` / ``edit.select_parent``
/ ``spawn.at_selection_center`` / ``layer.lock`` / ``snap.reset_defaults``
batch):

* ``view.toggle_safe_area``  — flip the safe-area (action-safe /
  title-safe) composition overlay (Blender's Camera → Safe Areas /
  Unity's Camera Preview safe-area gizmo). Distinct from CC1's
  ``view.toggle_grid`` / ``view.toggle_gizmos``, QQ1's
  ``view.toggle_stats``, PP1's ``view.toggle_wireframe``, VV4's
  ``view.toggle_ruler``, WW4's ``view.toggle_axes`` /
  ``view.toggle_background``, and YY4's ``view.toggle_snap_indicator``.
* ``edit.select_root``       — walk *all the way up* the scene DAG
  from the current selection (Blender ``]`` / Unity Ctrl+Shift+Home).
  Distinct from YY4's ``edit.select_parent`` (one-step walk); this
  verb walks to the outermost ancestor. Cycle-guarded, depth-capped.
* ``spawn.at_last_click``    — arm next spawn at the last recorded
  viewport click (Blender Shift+S → Cursor to Last Click). Distinct
  from VV4's ``spawn.at_last_position`` — that verb targets the last
  *spawn drop*; this targets the last *cursor click*.
* ``layer.unlock_all``       — clear the lock flag on every Z-layer
  (Photoshop Layer → Unlock All Layers). Distinct from CC1's
  ``edit.unlock_all`` (per-entity flag) and YY4's ``layer.lock``
  (single-target toggle).
* ``snap.cycle_grid_size``   — cycle grid size through the canonical
  rungs, wrapping at the top. Distinct from OO1's
  ``snap.increase_grid_size`` — that verb clamps at the ceiling; this
  verb wraps.

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / entity handles.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pharos_engine.tool_router import (
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


def _make_layer(name: str, z: float, locked: bool = False) -> SimpleNamespace:
    return SimpleNamespace(name=name, z=z, locked=locked)


def _make_entity(parent: object | None = None) -> SimpleNamespace:
    ns = SimpleNamespace()
    if parent is not None:
        ns.parent = parent
    return ns


def _make_scene(layers: list | None = None) -> SimpleNamespace:
    scene = SimpleNamespace(_z_layers=list(layers or []))
    scene.z_layers = scene._z_layers
    return scene


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_view_toggle_safe_area_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_safe_area")

    def test_edit_select_root_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.select_root")

    def test_spawn_at_last_click_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_last_click")

    def test_layer_unlock_all_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.unlock_all")

    def test_snap_cycle_grid_size_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.cycle_grid_size")

    def test_all_zz4_on_module_singleton(self) -> None:
        for aid in (
            "view.toggle_safe_area",
            "edit.select_root",
            "spawn.at_last_click",
            "layer.unlock_all",
            "snap.cycle_grid_size",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_zz4_categories(self, router: ToolRouter) -> None:
        expected = {
            "view.toggle_safe_area": "view",
            "edit.select_root": "edit",
            "spawn.at_last_click": "spawn",
            "layer.unlock_all": "layer",
            "snap.cycle_grid_size": "snap",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid

    def test_zz4_no_required_args(self, router: ToolRouter) -> None:
        # None of the ZZ4 actions have hard required-arg contracts —
        # each degrades to a ``no_*`` status when its lookups don't
        # resolve. That's asserted per-action below; here we just pin
        # the fact so a future contract change lands loudly.
        for aid in (
            "view.toggle_safe_area",
            "edit.select_root",
            "spawn.at_last_click",
            "layer.unlock_all",
            "snap.cycle_grid_size",
        ):
            action = router.get(aid)
            assert action is not None, aid
            assert action.required_args == [], aid


# ---------------------------------------------------------------------------
# view.toggle_safe_area
# ---------------------------------------------------------------------------


class TestViewToggleSafeArea:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_safe_area", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_hidden(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "view.toggle_safe_area", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "safe_area"
        # Default is hidden=False — first toggle flips to True.
        assert result["previous"] is False
        assert result["visible"] is True
        assert shell._safe_area_visible is True

    def test_flip_visible_to_hidden(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_safe_area_visible=True)
        result = router.dispatch(
            "view.toggle_safe_area", {"shell": shell},
        )
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._safe_area_visible is False

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_safe_area", {"visible": True},
        )
        assert result["previous"] is True
        assert result["visible"] is False

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_safe_area", {"shell": shell})
        assert calls == [("_safe_area_visible", True)]


# ---------------------------------------------------------------------------
# edit.select_root
# ---------------------------------------------------------------------------


class TestEditSelectRoot:
    def test_no_selection(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "edit.select_root", {},
        ) == {"status": "no_selection"}

    def test_root_returns_self(self, router: ToolRouter) -> None:
        # Selection is a root — the walker resolves to itself.
        root = _make_entity()
        shell = SimpleNamespace(_selected_entities=[root])
        result = router.dispatch("edit.select_root", {"shell": shell})
        assert result["status"] == "walked"
        assert result["count"] == 1
        assert result["roots"] == [root]

    def test_walk_two_levels_deep(self, router: ToolRouter) -> None:
        root = _make_entity()
        mid = _make_entity(parent=root)
        leaf = _make_entity(parent=mid)
        shell = SimpleNamespace(_selected_entities=[leaf])
        result = router.dispatch("edit.select_root", {"shell": shell})
        assert result["status"] == "walked"
        assert result["roots"] == [root]
        assert shell._selected_entities == [root]

    def test_walk_dedupes_shared_root(self, router: ToolRouter) -> None:
        root = _make_entity()
        a = _make_entity(parent=root)
        b = _make_entity(parent=root)
        shell = SimpleNamespace(_selected_entities=[a, b])
        result = router.dispatch("edit.select_root", {"shell": shell})
        assert result["count"] == 1
        assert result["roots"] == [root]

    def test_mode_add_keeps_original_picks(
        self, router: ToolRouter,
    ) -> None:
        root = _make_entity()
        leaf = _make_entity(parent=root)
        shell = SimpleNamespace(_selected_entities=[leaf])
        result = router.dispatch(
            "edit.select_root", {"shell": shell, "mode": "add"},
        )
        assert leaf in result["selection"]
        assert root in result["selection"]

    def test_private_parent_attr_fallback(
        self, router: ToolRouter,
    ) -> None:
        root = SimpleNamespace()
        mid = SimpleNamespace(_parent=root)
        leaf = SimpleNamespace(_parent=mid)
        shell = SimpleNamespace(_selected_entities=[leaf])
        result = router.dispatch("edit.select_root", {"shell": shell})
        assert result["status"] == "walked"
        assert result["roots"] == [root]

    def test_cycle_guard_returns_effective_root(
        self, router: ToolRouter,
    ) -> None:
        # a → b → a (cycle) — walker should stop, not infinite-loop.
        # Use plain object() so SimpleNamespace's deep-eq machinery is
        # not triggered on a cyclic reference.
        class _E:
            parent = None
        a = _E()
        b = _E()
        b.parent = a
        a.parent = b
        shell = SimpleNamespace(_selected_entities=[a])
        result = router.dispatch("edit.select_root", {"shell": shell})
        assert result["status"] == "walked"
        assert result["count"] == 1
        # First walk step reveals b, second step would revisit a → stop.
        # Use identity comparison, not equality, to dodge SimpleNamespace
        # __eq__ walking parent chains.
        root = result["roots"][0]
        assert root is a or root is b

    def test_explicit_selection_override(
        self, router: ToolRouter,
    ) -> None:
        root = _make_entity()
        leaf = _make_entity(parent=root)
        result = router.dispatch(
            "edit.select_root", {"selection": [leaf]},
        )
        assert result["status"] == "walked"
        assert result["roots"] == [root]


# ---------------------------------------------------------------------------
# spawn.at_last_click
# ---------------------------------------------------------------------------


class TestSpawnAtLastClick:
    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "spawn.at_last_click", {},
        ) == {"status": "no_shell"}

    def test_no_click_recorded(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_click", {"shell": shell},
        )
        assert result == {"status": "no_click"}

    def test_override_wins(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_last_click", {"last_click": [1.0, 2.0, 3.0]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (1.0, 2.0, 3.0)
        assert result["source"] == "override"

    def test_2vec_pads_z(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_last_click_position=[4.0, 5.0])
        result = router.dispatch(
            "spawn.at_last_click", {"shell": shell},
        )
        assert result["position"] == (4.0, 5.0, 0.0)
        assert result["source"] == "shell_click"
        assert shell._pending_spawn_position == [4.0, 5.0, 0.0]

    def test_cursor_fallback(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_last_cursor_position=[7.0, 8.0, 9.0])
        result = router.dispatch(
            "spawn.at_last_click", {"shell": shell},
        )
        assert result["source"] == "shell_cursor"
        assert result["position"] == (7.0, 8.0, 9.0)

    def test_input_manager_fallback(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _input=SimpleNamespace(_last_click=[10.0, 11.0, 12.0]),
        )
        result = router.dispatch(
            "spawn.at_last_click", {"shell": shell},
        )
        assert result["source"] == "input_click"
        assert result["position"] == (10.0, 11.0, 12.0)

    def test_offset_applied(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_last_click",
            {"last_click": [1.0, 1.0, 1.0], "offset": [0.5, 0.5, 0.0]},
        )
        assert result["position"] == (1.5, 1.5, 1.0)
        assert result["offset"] == (0.5, 0.5, 0.0)

    def test_malformed_offset_flag(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_last_click",
            {"last_click": [1.0, 1.0, 1.0], "offset": "nope"},
        )
        assert result.get("malformed_offset") is True
        assert result["offset"] == (0.0, 0.0, 0.0)

    def test_click_position_alias_override(
        self, router: ToolRouter,
    ) -> None:
        result = router.dispatch(
            "spawn.at_last_click", {"click_position": [9.0, 9.0]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (9.0, 9.0, 0.0)
        assert result["source"] == "override"


# ---------------------------------------------------------------------------
# layer.unlock_all
# ---------------------------------------------------------------------------


class TestLayerUnlockAll:
    def test_no_scene(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "layer.unlock_all", {},
        ) == {"status": "no_scene"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = _make_scene()
        result = router.dispatch(
            "layer.unlock_all", {"scene": scene},
        )
        assert result == {"status": "no_layers"}

    def test_already_unlocked_is_no_op(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=False)
        b = _make_layer("B", 1.0, locked=False)
        scene = _make_scene(layers=[a, b])
        result = router.dispatch(
            "layer.unlock_all", {"scene": scene},
        )
        assert result["status"] == "already_unlocked"
        assert result["count"] == 0
        assert result["targets"] == []

    def test_unlocks_locked_layers(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=True)
        b = _make_layer("B", 1.0, locked=False)
        c = _make_layer("C", 2.0, locked=True)
        scene = _make_scene(layers=[a, b, c])
        result = router.dispatch(
            "layer.unlock_all", {"scene": scene},
        )
        assert result["status"] == "unlocked"
        assert result["count"] == 2
        assert set(result["targets"]) == {"A", "C"}
        assert a.locked is False
        assert b.locked is False
        assert c.locked is False

    def test_dry_run_reports_but_does_not_write(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0, locked=True)
        scene = _make_scene(layers=[a])
        result = router.dispatch(
            "layer.unlock_all", {"scene": scene, "dry_run": True},
        )
        assert result["status"] == "unlocked"
        assert result["count"] == 1
        assert a.locked is True  # not written

    def test_shell_scene_resolution(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=True)
        scene = _make_scene(layers=[a])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "layer.unlock_all", {"shell": shell},
        )
        assert result["status"] == "unlocked"
        assert a.locked is False

    def test_refresh_hook_fired_once(self, router: ToolRouter) -> None:
        calls: list[str] = []
        a = _make_layer("A", 0.0, locked=True)
        scene = _make_scene(layers=[a])
        shell = SimpleNamespace(
            _scene=scene,
            _on_layer_lock_toggled=lambda: calls.append("hook"),
        )
        router.dispatch("layer.unlock_all", {"shell": shell})
        assert calls == ["hook"]

    def test_no_hook_fired_on_no_op(self, router: ToolRouter) -> None:
        calls: list[str] = []
        a = _make_layer("A", 0.0, locked=False)
        scene = _make_scene(layers=[a])
        shell = SimpleNamespace(
            _scene=scene,
            _on_layer_lock_toggled=lambda: calls.append("hook"),
        )
        router.dispatch("layer.unlock_all", {"shell": shell})
        assert calls == []


# ---------------------------------------------------------------------------
# snap.cycle_grid_size
# ---------------------------------------------------------------------------


class TestSnapCycleGridSize:
    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "snap.cycle_grid_size", {},
        ) == {"status": "no_shell"}

    def test_step_up_one_rung(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=1.0)
        result = router.dispatch(
            "snap.cycle_grid_size", {"shell": shell},
        )
        assert result["status"] == "cycled"
        assert result["previous"] == 1.0
        assert result["new"] == 2.0
        assert result["direction"] == "up"
        assert result["wrapped"] is False
        assert shell._snap_grid_size == 2.0

    def test_wraps_at_top(self, router: ToolRouter) -> None:
        # 256.0 is the top rung; a further "up" step wraps to 0.5.
        shell = SimpleNamespace(_snap_grid_size=256.0)
        result = router.dispatch(
            "snap.cycle_grid_size", {"shell": shell},
        )
        assert result["new"] == 0.5
        assert result["wrapped"] is True

    def test_step_down_one_rung(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=4.0)
        result = router.dispatch(
            "snap.cycle_grid_size",
            {"shell": shell, "direction": "down"},
        )
        assert result["new"] == 2.0
        assert result["direction"] == "down"
        assert result["wrapped"] is False

    def test_wraps_at_bottom_going_down(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=0.5)
        result = router.dispatch(
            "snap.cycle_grid_size",
            {"shell": shell, "direction": "down"},
        )
        assert result["new"] == 256.0
        assert result["wrapped"] is True

    def test_off_ladder_value_snaps_to_nearest_first(
        self, router: ToolRouter,
    ) -> None:
        # 3.14 rounds to nearest rung (4.0), then step up → 8.0.
        shell = SimpleNamespace(_snap_grid_size=3.14)
        result = router.dispatch(
            "snap.cycle_grid_size", {"shell": shell},
        )
        assert result["previous"] == 3.14
        assert result["new"] == 8.0

    def test_grid_size_override(self, router: ToolRouter) -> None:
        # Override wins over shell attr, and shell attr is still updated.
        shell = SimpleNamespace(_snap_grid_size=64.0)
        result = router.dispatch(
            "snap.cycle_grid_size",
            {"shell": shell, "grid_size": 1.0},
        )
        assert result["previous"] == 1.0
        assert result["new"] == 2.0
        assert shell._snap_grid_size == 2.0

    def test_invalid_direction_defaults_to_up(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(_snap_grid_size=1.0)
        result = router.dispatch(
            "snap.cycle_grid_size",
            {"shell": shell, "direction": "sideways"},
        )
        assert result["direction"] == "up"
        assert result["new"] == 2.0


# ---------------------------------------------------------------------------
# ctx validation — every ZZ4 action tolerates dispatch(id, None)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    @pytest.mark.parametrize(
        "aid",
        [
            "view.toggle_safe_area",
            "edit.select_root",
            "spawn.at_last_click",
            "layer.unlock_all",
            "snap.cycle_grid_size",
        ],
    )
    def test_none_ctx_normalises(
        self, router: ToolRouter, aid: str,
    ) -> None:
        # dispatch normalises ctx=None to {} — the ensure_ctx check
        # inside the action still succeeds on {}. Every action returns
        # a status dict rather than raising.
        result = router.dispatch(aid, None)
        assert isinstance(result, dict)
        assert "status" in result
