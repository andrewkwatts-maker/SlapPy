"""UU4 STUB-triage tests — round 22 of feature-map wiring.

Covers the five new action ids added by the UU4 sprint tick (round 22
after TT2's round-21 ``view.set_zoom`` / ``spawn.at_view_center`` /
``spawn.stamp_random`` / ``theme.reload_from_disk`` / ``layer.rename``
batch):

* ``spawn.at_origin_offset`` — drop the next spawn (or replay) at
  ``(0,0,0) + ctx["offset"]``. Sibling to QQ1's ``spawn.at_origin``
  (forced zero drop) and TT2's ``spawn.at_view_center`` (camera focus
  drop) — this verb is the "arm at origin plus explicit delta" flow.
* ``edit.flatten_selection`` — recursively unpack every group entity in
  the selection so a nested ``group(group(a, b), c)`` collapses to
  ``[a, b, c]`` in one gesture. Distinct from EE1's
  ``edit.ungroup_selection`` which only peels a single nesting level.
* ``snap.set_angle_snap`` — set the rotation-gizmo snap step in degrees.
  Distinct from OO1's position grid-size ladder + RR1's
  ``snap.toggle_incremental`` boolean gate.
* ``layer.move_up`` / ``layer.move_down`` — swap the active layer with
  its immediate Z-neighbour (Photoshop ``Ctrl+]`` / ``Ctrl+[``).
  Distinct from OO1's ``layer.merge_down`` which flattens two layers
  into one, and TT2's ``layer.rename`` which touches names not order.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / layer handles.
"""
from __future__ import annotations

from types import SimpleNamespace

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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_spawn_at_origin_offset_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_origin_offset")

    def test_edit_flatten_selection_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.flatten_selection")

    def test_snap_set_angle_snap_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.set_angle_snap")

    def test_layer_move_up_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.move_up")

    def test_layer_move_down_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.move_down")

    def test_all_uu4_on_module_singleton(self) -> None:
        for aid in (
            "spawn.at_origin_offset",
            "edit.flatten_selection",
            "snap.set_angle_snap",
            "layer.move_up",
            "layer.move_down",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_uu4_categories(self, router: ToolRouter) -> None:
        expected = {
            "spawn.at_origin_offset": "spawn",
            "edit.flatten_selection": "edit",
            "snap.set_angle_snap": "snap",
            "layer.move_up": "layer",
            "layer.move_down": "layer",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# spawn.at_origin_offset
# ---------------------------------------------------------------------------


class TestSpawnAtOriginOffset:
    def test_no_shell_arm(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.at_origin_offset", {})
        assert result == {"status": "no_shell"}

    def test_arm_no_offset_defaults_to_origin(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin_offset", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["position"] == (0.0, 0.0, 0.0)
        assert result["offset"] == (0.0, 0.0, 0.0)
        assert shell._pending_spawn_position == [0.0, 0.0, 0.0]

    def test_arm_with_3vec_offset(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin_offset",
            {"shell": shell, "offset": [5.0, -2.0, 1.5]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (5.0, -2.0, 1.5)
        assert result["offset"] == (5.0, -2.0, 1.5)
        assert shell._pending_spawn_position == [5.0, -2.0, 1.5]

    def test_arm_with_2vec_offset_pads_z(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin_offset",
            {"shell": shell, "offset": (3.0, 4.0)},
        )
        assert result["position"] == (3.0, 4.0, 0.0)
        assert result["offset"] == (3.0, 4.0, 0.0)

    def test_malformed_offset_flagged(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin_offset",
            {"shell": shell, "offset": "not-a-vec"},
        )
        assert result["status"] == "armed"
        assert result["malformed_offset"] is True
        assert result["position"] == (0.0, 0.0, 0.0)

    def test_repeat_with_history(self, router: ToolRouter) -> None:
        landed: list[tuple[str, dict]] = []
        shell = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed.append((cid, spec)),
        )
        result = router.dispatch(
            "spawn.at_origin_offset",
            {
                "shell": shell,
                "offset": [2.0, 3.0, 4.0],
                "mode": "repeat",
                "last_spawn": ("rope", {"position": [0.0, 0.0, 0.0]}),
            },
        )
        assert result["status"] == "respawned"
        assert result["card_id"] == "rope"
        assert result["position"] == (2.0, 3.0, 4.0)
        assert landed[0][1]["position"] == [2.0, 3.0, 4.0]

    def test_repeat_without_history_falls_back_to_arm(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin_offset",
            {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "armed"


# ---------------------------------------------------------------------------
# edit.flatten_selection
# ---------------------------------------------------------------------------


def _make_scene(entities: list) -> SimpleNamespace:
    return SimpleNamespace(_entities=list(entities))


def _make_group(position, children, name="G"):
    return SimpleNamespace(
        position=list(position),
        children=list(children),
        is_group=True,
        name=name,
    )


def _make_leaf(position, name="leaf"):
    return SimpleNamespace(position=list(position), name=name)


class TestEditFlattenSelection:
    def test_no_selection(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.flatten_selection", {})
        assert result == {"status": "no_selection"}

    def test_no_groups(self, router: ToolRouter) -> None:
        leaf = _make_leaf([0.0, 0.0, 0.0])
        scene = _make_scene([leaf])
        result = router.dispatch(
            "edit.flatten_selection",
            {"selection": [leaf], "scene": scene},
        )
        assert result == {"status": "no_groups"}

    def test_no_scene(self, router: ToolRouter) -> None:
        group = _make_group([0.0, 0.0, 0.0], [_make_leaf([0.0, 0.0, 0.0])])
        result = router.dispatch(
            "edit.flatten_selection", {"selection": [group]},
        )
        assert result == {"status": "no_scene"}

    def test_single_level_flatten(self, router: ToolRouter) -> None:
        a = _make_leaf([1.0, 2.0, 0.0], "a")
        b = _make_leaf([3.0, 4.0, 0.0], "b")
        group = _make_group([10.0, 20.0, 0.0], [a, b], "g1")
        scene = _make_scene([group])
        result = router.dispatch(
            "edit.flatten_selection",
            {"selection": [group], "scene": scene},
        )
        assert result["status"] == "flattened"
        assert result["count"] == 2
        assert result["groups_removed"] == 1
        # Child positions moved into world space.
        assert a.position == [11.0, 22.0, 0.0]
        assert b.position == [13.0, 24.0, 0.0]
        # Scene now holds the leaves, not the group.
        assert group not in scene._entities
        assert a in scene._entities
        assert b in scene._entities

    def test_deep_flatten(self, router: ToolRouter) -> None:
        a = _make_leaf([1.0, 0.0, 0.0], "a")
        b = _make_leaf([2.0, 0.0, 0.0], "b")
        inner = _make_group([10.0, 0.0, 0.0], [a, b], "inner")
        c = _make_leaf([3.0, 0.0, 0.0], "c")
        outer = _make_group([100.0, 0.0, 0.0], [inner, c], "outer")
        scene = _make_scene([outer])
        result = router.dispatch(
            "edit.flatten_selection",
            {"selection": [outer], "scene": scene},
        )
        assert result["status"] == "flattened"
        assert result["count"] == 3
        assert result["groups_removed"] == 2
        # Positions cascaded: outer(100) + inner(10) + a(1) = 111
        assert a.position == [111.0, 0.0, 0.0]
        assert b.position == [112.0, 0.0, 0.0]
        assert c.position == [103.0, 0.0, 0.0]

    def test_selection_retargeted_to_leaves(
        self, router: ToolRouter,
    ) -> None:
        a = _make_leaf([0.0, 0.0, 0.0], "a")
        group = _make_group([0.0, 0.0, 0.0], [a], "g")
        scene = _make_scene([group])
        shell = SimpleNamespace(
            _scene=scene,
            _selected_entities=[group],
        )
        router.dispatch(
            "edit.flatten_selection", {"shell": shell},
        )
        assert shell._selected_entities == [a]
        assert shell._selected_entity is a


# ---------------------------------------------------------------------------
# snap.set_angle_snap
# ---------------------------------------------------------------------------


class TestSnapSetAngleSnap:
    def test_missing_degrees(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap", {"shell": shell},
        )
        assert result == {"status": "missing_degrees"}

    def test_non_finite_degrees(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": float("nan")},
        )
        assert result == {"status": "missing_degrees"}

    def test_no_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "snap.set_angle_snap", {"degrees": 45.0},
        )
        assert result == {"status": "no_shell"}

    def test_sets_canonical_value(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 45.0},
        )
        assert result["status"] == "set"
        assert result["new"] == 45.0
        assert result["canonical"] is True
        assert shell._snap_angle_deg == 45.0
        assert shell._snap_angle == 45.0

    def test_snaps_near_canonical(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 45.02},
        )
        assert result["new"] == 45.0
        assert result["canonical"] is True

    def test_non_canonical_value(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 12.5},
        )
        assert result["status"] == "set"
        assert result["new"] == 12.5
        assert result["canonical"] is False

    def test_clamps_above_max(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 500.0},
        )
        # Clamped to 180.0, which is canonical.
        assert result["new"] == 180.0

    def test_clamps_below_min(self, router: ToolRouter) -> None:
        # Start at a non-zero previous value so the clamp result of 0.0
        # is distinct from the previous and does not short-circuit to
        # "unchanged".
        shell = SimpleNamespace(_snap_angle_deg=45.0)
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": -10.0},
        )
        assert result["status"] == "set"
        assert result["new"] == 0.0
        assert result["previous"] == 45.0

    def test_unchanged(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_angle_deg=15.0)
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 15.0},
        )
        assert result == {"status": "unchanged", "value": 15.0}

    def test_records_previous(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_angle_deg=15.0)
        result = router.dispatch(
            "snap.set_angle_snap",
            {"shell": shell, "degrees": 90.0},
        )
        assert result["previous"] == 15.0
        assert result["new"] == 90.0


# ---------------------------------------------------------------------------
# layer.move_up / layer.move_down
# ---------------------------------------------------------------------------


def _make_layered_scene(names_with_z: list[tuple[str, float]]) -> SimpleNamespace:
    layers = [
        SimpleNamespace(name=n, z=z) for n, z in names_with_z
    ]
    return SimpleNamespace(z_layers=layers)


class TestLayerMoveUpDown:
    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.move_up", {})
        assert result == {"status": "no_scene"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = SimpleNamespace(z_layers=[])
        result = router.dispatch(
            "layer.move_up", {"scene": scene},
        )
        assert result == {"status": "no_layers"}

    def test_single_layer(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("only", 0.0)])
        result = router.dispatch(
            "layer.move_up",
            {"scene": scene, "layer": scene.z_layers[0]},
        )
        assert result == {"status": "single_layer"}

    def test_no_target(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("bg", 0.0), ("fg", 1.0)])
        result = router.dispatch(
            "layer.move_up", {"scene": scene},
        )
        assert result == {"status": "no_layer"}

    def test_move_up_success(self, router: ToolRouter) -> None:
        scene = _make_layered_scene(
            [("bg", 0.0), ("mid", 1.0), ("fg", 2.0)],
        )
        result = router.dispatch(
            "layer.move_up",
            {"scene": scene, "layer": scene.z_layers[1]},
        )
        assert result["status"] == "moved"
        assert result["target"] == "mid"
        assert result["direction"] == "up"
        assert result["swapped_with"] == "fg"
        assert result["old_z"] == 1.0
        assert result["new_z"] == 2.0
        # mid now has z=2.0; fg now has z=1.0
        assert scene.z_layers[1].z == 2.0
        assert scene.z_layers[2].z == 1.0

    def test_move_up_at_top(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("bg", 0.0), ("fg", 1.0)])
        result = router.dispatch(
            "layer.move_up",
            {"scene": scene, "layer": scene.z_layers[1]},
        )
        assert result == {"status": "at_top", "target": "fg"}

    def test_move_down_success(self, router: ToolRouter) -> None:
        scene = _make_layered_scene(
            [("bg", 0.0), ("mid", 1.0), ("fg", 2.0)],
        )
        result = router.dispatch(
            "layer.move_down",
            {"scene": scene, "layer": scene.z_layers[1]},
        )
        assert result["status"] == "moved"
        assert result["target"] == "mid"
        assert result["direction"] == "down"
        assert result["swapped_with"] == "bg"
        assert result["old_z"] == 1.0
        assert result["new_z"] == 0.0

    def test_move_down_at_bottom(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("bg", 0.0), ("fg", 1.0)])
        result = router.dispatch(
            "layer.move_down",
            {"scene": scene, "layer": scene.z_layers[0]},
        )
        assert result == {"status": "at_bottom", "target": "bg"}

    def test_lookup_by_name(self, router: ToolRouter) -> None:
        scene = _make_layered_scene(
            [("bg", 0.0), ("mid", 1.0), ("fg", 2.0)],
        )
        result = router.dispatch(
            "layer.move_up",
            {"scene": scene, "layer_name": "mid"},
        )
        assert result["status"] == "moved"
        assert result["target"] == "mid"

    def test_active_layer_fallback(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("bg", 0.0), ("fg", 1.0)])
        shell = SimpleNamespace(
            _scene=scene, _active_layer=scene.z_layers[0],
        )
        result = router.dispatch(
            "layer.move_up", {"shell": shell},
        )
        assert result["status"] == "moved"
        assert result["target"] == "bg"

    def test_reorder_refresh_hook(self, router: ToolRouter) -> None:
        scene = _make_layered_scene([("bg", 0.0), ("fg", 1.0)])
        seen: list[int] = []
        shell = SimpleNamespace(
            _scene=scene,
            _active_layer=scene.z_layers[0],
            _on_layer_reordered=lambda: seen.append(1),
        )
        router.dispatch("layer.move_up", {"shell": shell})
        assert seen == [1]
