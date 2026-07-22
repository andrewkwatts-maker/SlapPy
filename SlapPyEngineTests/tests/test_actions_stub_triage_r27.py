"""AAA4 STUB-triage tests — round 27 of feature-map wiring.

Covers the five new action ids added by the AAA4 sprint tick (round 27
after ZZ4's round-26 ``view.toggle_safe_area`` / ``edit.select_root`` /
``spawn.at_last_click`` / ``layer.unlock_all`` / ``snap.cycle_grid_size``
batch):

* ``view.toggle_camera_bounds``   — flip the camera-frame outline
  overlay drawn on top of the viewport. Blender's Camera →
  Passepartout / Unity's Camera Preview frame / Nova3D's camera-frame
  outline. Distinct from ZZ4's ``view.toggle_safe_area`` — the safe
  area draws the *inner* action-safe / title-safe outlines; this verb
  draws the *outer* camera-frame rectangle.
* ``edit.select_last_spawned``    — snap the selection onto the most
  recently spawned entity. Blender's ``Ctrl+.`` / Unity's
  Ctrl+Shift+Insert. Complement of the various spawn verbs — those
  *create*, this *re-selects* whatever was created last.
* ``spawn.at_previous_click``     — arm next spawn at the N-th
  previous viewport click (walk backwards through click history).
  Blender's Alt+Shift+S / Nova3D's viewport right-click "Drop at
  Previous Click". Distinct from ZZ4's ``spawn.at_last_click`` —
  that verb picks the *most recent* click; this one walks
  *backwards* through the click history.
* ``layer.sort_by_z``             — reorder every layer by ascending
  ``.z``. Photoshop's Layer → Arrange → Sort / Krita's Sort Layers by
  Depth / Nova3D's Layer-panel gear → Sort by Z. Complements UU4's
  single-layer ``layer.move_up`` / ``layer.move_down`` — bulk sort
  vs single shift.
* ``snap.toggle_pixel_perfect``   — flip a persistent pixel-perfect
  snap mode so every subsequent position write rounds to integer
  pixels. Aseprite's Snap to Pixel / Krita's Snap to Pixel Grid.
  Distinct from RR1's ``snap.toggle_incremental`` (incremental
  grid-cell stepping) and from CC1's one-shot ``edit.snap_to_grid``.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / entity handles.
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


def _make_layer(name: str, z: float) -> SimpleNamespace:
    return SimpleNamespace(name=name, z=z)


def _make_scene(layers: list | None = None) -> SimpleNamespace:
    scene = SimpleNamespace(_z_layers=list(layers or []))
    scene.z_layers = scene._z_layers
    return scene


def _make_entity(tag: str = "") -> SimpleNamespace:
    return SimpleNamespace(_tag=tag)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_view_toggle_camera_bounds_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_camera_bounds")

    def test_edit_select_last_spawned_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.select_last_spawned")

    def test_spawn_at_previous_click_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_previous_click")

    def test_layer_sort_by_z_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.sort_by_z")

    def test_snap_toggle_pixel_perfect_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.toggle_pixel_perfect")

    def test_all_aaa4_on_module_singleton(self) -> None:
        for aid in (
            "view.toggle_camera_bounds",
            "edit.select_last_spawned",
            "spawn.at_previous_click",
            "layer.sort_by_z",
            "snap.toggle_pixel_perfect",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_aaa4_categories(self, router: ToolRouter) -> None:
        expected = {
            "view.toggle_camera_bounds": "view",
            "edit.select_last_spawned": "edit",
            "spawn.at_previous_click": "spawn",
            "layer.sort_by_z": "layer",
            "snap.toggle_pixel_perfect": "snap",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid

    def test_aaa4_no_required_args(self, router: ToolRouter) -> None:
        # None of the AAA4 actions have hard required-arg contracts —
        # each degrades to a ``no_*`` status when its lookups don't
        # resolve.
        for aid in (
            "view.toggle_camera_bounds",
            "edit.select_last_spawned",
            "spawn.at_previous_click",
            "layer.sort_by_z",
            "snap.toggle_pixel_perfect",
        ):
            action = router.get(aid)
            assert action is not None, aid
            assert action.required_args == [], aid


# ---------------------------------------------------------------------------
# view.toggle_camera_bounds
# ---------------------------------------------------------------------------


class TestViewToggleCameraBounds:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_camera_bounds", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_hidden(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "view.toggle_camera_bounds", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "camera_bounds"
        # Default is hidden=False — first toggle flips to True.
        assert result["previous"] is False
        assert result["visible"] is True
        assert shell._camera_bounds_visible is True

    def test_flip_visible_to_hidden(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_camera_bounds_visible=True)
        result = router.dispatch(
            "view.toggle_camera_bounds", {"shell": shell},
        )
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._camera_bounds_visible is False

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_camera_bounds", {"visible": True},
        )
        assert result["previous"] is True
        assert result["visible"] is False

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_camera_bounds", {"shell": shell})
        assert calls == [("_camera_bounds_visible", True)]


# ---------------------------------------------------------------------------
# edit.select_last_spawned
# ---------------------------------------------------------------------------


class TestEditSelectLastSpawned:
    def test_no_spawn_history(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.select_last_spawned", {})
        assert result == {"status": "no_spawn_history"}

    def test_no_history_on_bare_shell(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell},
        )
        assert result == {"status": "no_spawn_history"}

    def test_shell_slot_wins(self, router: ToolRouter) -> None:
        last = _make_entity("A")
        shell = SimpleNamespace(_last_spawned_entity=last)
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell},
        )
        assert result["status"] == "selected"
        assert result["entity"] is last
        assert result["selection"] == [last]
        assert shell._selected_entity is last
        assert shell._selected_entities == [last]

    def test_history_fallback(self, router: ToolRouter) -> None:
        a = _make_entity("A")
        b = _make_entity("B")
        shell = SimpleNamespace(_spawn_history=[a, b])
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell},
        )
        # Last item in history wins.
        assert result["entity"] is b

    def test_scene_fallback(self, router: ToolRouter) -> None:
        last = _make_entity("A")
        scene = SimpleNamespace(_last_spawned=last)
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell},
        )
        assert result["entity"] is last

    def test_explicit_entity_override(self, router: ToolRouter) -> None:
        override = _make_entity("O")
        result = router.dispatch(
            "edit.select_last_spawned", {"entity": override},
        )
        assert result["status"] == "selected"
        assert result["entity"] is override

    def test_mode_add_appends(self, router: ToolRouter) -> None:
        existing = _make_entity("X")
        last = _make_entity("L")
        shell = SimpleNamespace(
            _selected_entities=[existing],
            _last_spawned_entity=last,
        )
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell, "mode": "add"},
        )
        assert result["selection"] == [existing, last]

    def test_mode_add_dedupes(self, router: ToolRouter) -> None:
        # If the last-spawned is already in the selection, mode=add
        # doesn't duplicate.
        last = _make_entity("L")
        shell = SimpleNamespace(
            _selected_entities=[last],
            _last_spawned_entity=last,
        )
        result = router.dispatch(
            "edit.select_last_spawned", {"shell": shell, "mode": "add"},
        )
        assert result["selection"] == [last]


# ---------------------------------------------------------------------------
# spawn.at_previous_click
# ---------------------------------------------------------------------------


class TestSpawnAtPreviousClick:
    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "spawn.at_previous_click", {},
        ) == {"status": "no_shell"}

    def test_no_history(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell},
        )
        assert result == {"status": "no_previous_click"}

    def test_single_click_no_previous(self, router: ToolRouter) -> None:
        # Only one click in history — no "previous" to walk to.
        shell = SimpleNamespace(_click_history=[[1.0, 2.0, 3.0]])
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell},
        )
        assert result == {"status": "no_previous_click"}

    def test_two_clicks_depth_one(self, router: ToolRouter) -> None:
        # depth=1 = previous click = second-to-last.
        shell = SimpleNamespace(
            _click_history=[[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]],
        )
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["position"] == (1.0, 2.0, 3.0)
        assert result["depth"] == 1
        assert result["source"] == "shell"
        assert shell._pending_spawn_position == [1.0, 2.0, 3.0]

    def test_depth_two_walks_further_back(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(
            _click_history=[
                [1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0],
            ],
        )
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell, "depth": 2},
        )
        assert result["position"] == (1.0, 1.0, 1.0)
        assert result["depth"] == 2

    def test_depth_exceeds_history(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _click_history=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        )
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell, "depth": 5},
        )
        assert result == {"status": "no_previous_click"}

    def test_2vec_pads_z(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _click_history=[[1.0, 2.0], [10.0, 20.0]],
        )
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell},
        )
        assert result["position"] == (1.0, 2.0, 0.0)

    def test_override_history_wins(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_previous_click",
            {"click_history": [[7.0, 8.0, 9.0], [70.0, 80.0, 90.0]]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (7.0, 8.0, 9.0)
        assert result["source"] == "override"

    def test_input_manager_fallback(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _input=SimpleNamespace(
                _click_history=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
            ),
        )
        result = router.dispatch(
            "spawn.at_previous_click", {"shell": shell},
        )
        assert result["source"] == "input_manager"
        assert result["position"] == (1.0, 2.0, 3.0)

    def test_offset_applied(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_previous_click",
            {
                "click_history": [[1.0, 1.0, 1.0], [9.0, 9.0, 9.0]],
                "offset": [0.5, 0.5, 0.0],
            },
        )
        assert result["position"] == (1.5, 1.5, 1.0)
        assert result["offset"] == (0.5, 0.5, 0.0)

    def test_malformed_offset_flag(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "spawn.at_previous_click",
            {
                "click_history": [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
                "offset": "nope",
            },
        )
        assert result.get("malformed_offset") is True
        assert result["offset"] == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# layer.sort_by_z
# ---------------------------------------------------------------------------


class TestLayerSortByZ:
    def test_no_scene(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "layer.sort_by_z", {},
        ) == {"status": "no_scene"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = _make_scene()
        result = router.dispatch("layer.sort_by_z", {"scene": scene})
        assert result == {"status": "no_layers"}

    def test_already_sorted_ascending(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 2.0)
        scene = _make_scene(layers=[a, b, c])
        result = router.dispatch(
            "layer.sort_by_z", {"scene": scene},
        )
        assert result["status"] == "already_sorted"
        assert result["count"] == 3
        assert result["order"] == ["A", "B", "C"]

    def test_unsorted_writes_new_order(self, router: ToolRouter) -> None:
        a = _make_layer("A", 5.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 3.0)
        scene = _make_scene(layers=[a, b, c])
        result = router.dispatch(
            "layer.sort_by_z", {"scene": scene},
        )
        assert result["status"] == "sorted"
        assert result["moved"] is True
        assert result["order"] == ["B", "C", "A"]
        # Scene state was reordered.
        assert [l.name for l in scene.z_layers] == ["B", "C", "A"]

    def test_descending_direction(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 2.0)
        scene = _make_scene(layers=[a, b, c])
        result = router.dispatch(
            "layer.sort_by_z",
            {"scene": scene, "direction": "descending"},
        )
        assert result["status"] == "sorted"
        assert result["order"] == ["C", "B", "A"]
        assert result["direction"] == "descending"

    def test_invalid_direction_defaults_to_ascending(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 5.0)
        b = _make_layer("B", 1.0)
        scene = _make_scene(layers=[a, b])
        result = router.dispatch(
            "layer.sort_by_z",
            {"scene": scene, "direction": "sideways"},
        )
        assert result["direction"] == "ascending"
        assert result["order"] == ["B", "A"]

    def test_stable_sort_for_equal_z(self, router: ToolRouter) -> None:
        # Two layers at same z stay in original order.
        a = _make_layer("A", 1.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 0.0)
        scene = _make_scene(layers=[a, b, c])
        result = router.dispatch(
            "layer.sort_by_z", {"scene": scene},
        )
        assert result["order"] == ["C", "A", "B"]

    def test_dry_run_reports_but_does_not_write(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 5.0)
        b = _make_layer("B", 1.0)
        scene = _make_scene(layers=[a, b])
        result = router.dispatch(
            "layer.sort_by_z", {"scene": scene, "dry_run": True},
        )
        assert result["status"] == "sorted"
        assert result["order"] == ["B", "A"]
        # Scene not mutated.
        assert [l.name for l in scene.z_layers] == ["A", "B"]

    def test_shell_scene_resolution(self, router: ToolRouter) -> None:
        a = _make_layer("A", 3.0)
        b = _make_layer("B", 1.0)
        scene = _make_scene(layers=[a, b])
        shell = SimpleNamespace(_scene=scene)
        result = router.dispatch(
            "layer.sort_by_z", {"shell": shell},
        )
        assert result["status"] == "sorted"
        assert [l.name for l in scene.z_layers] == ["B", "A"]

    def test_refresh_hook_fired(self, router: ToolRouter) -> None:
        calls: list[str] = []
        a = _make_layer("A", 3.0)
        b = _make_layer("B", 1.0)
        scene = _make_scene(layers=[a, b])
        shell = SimpleNamespace(
            _scene=scene,
            _on_layer_order_changed=lambda: calls.append("hook"),
        )
        router.dispatch("layer.sort_by_z", {"shell": shell})
        assert calls == ["hook"]


# ---------------------------------------------------------------------------
# snap.toggle_pixel_perfect
# ---------------------------------------------------------------------------


class TestSnapTogglePixelPerfect:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("snap.toggle_pixel_perfect", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_off(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.toggle_pixel_perfect", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "pixel_perfect_snap"
        assert result["previous"] is False
        assert result["enabled"] is True
        assert shell._pixel_perfect_snap is True

    def test_flip_enabled_to_disabled(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_pixel_perfect_snap=True)
        result = router.dispatch(
            "snap.toggle_pixel_perfect", {"shell": shell},
        )
        assert result["previous"] is True
        assert result["enabled"] is False
        assert shell._pixel_perfect_snap is False

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "snap.toggle_pixel_perfect", {"enabled": True},
        )
        assert result["previous"] is True
        assert result["enabled"] is False

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_snap_mode_changed=lambda attr, val: calls.append(
                (attr, val),
            ),
        )
        router.dispatch(
            "snap.toggle_pixel_perfect", {"shell": shell},
        )
        assert calls == [("_pixel_perfect_snap", True)]


# ---------------------------------------------------------------------------
# ctx validation — every AAA4 action tolerates dispatch(id, None)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    @pytest.mark.parametrize(
        "aid",
        [
            "view.toggle_camera_bounds",
            "edit.select_last_spawned",
            "spawn.at_previous_click",
            "layer.sort_by_z",
            "snap.toggle_pixel_perfect",
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
