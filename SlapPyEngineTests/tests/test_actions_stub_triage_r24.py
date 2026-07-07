"""WW4 STUB-triage tests — round 24 of feature-map wiring.

Covers the five new action ids added by the WW4 sprint tick (round 24
after VV4's round-23 ``layer.new`` / ``layer.delete`` /
``snap.set_grid_size`` / ``view.toggle_ruler`` /
``spawn.at_last_position`` batch):

* ``view.toggle_axes``       — flip the viewport world-axis overlay
  (Blender numpad axis widget / Unity scene view "Axes"). Distinct
  from CC1's ``view.toggle_gizmos`` / ``view.toggle_grid`` and VV4's
  ``view.toggle_ruler``.
* ``view.toggle_background`` — flip the viewport checker-background
  layer (Photoshop / Aseprite transparency board). Distinct from
  CC1's ``view.toggle_grid`` (grid *lines*).
* ``edit.select_by_tag``     — select every entity carrying a given
  tag (Unity ``CompareTag`` / Godot ``is_in_group``). Distinct from
  QQ1's ``selection.by_type`` (kind-based) and ``selection.by_layer``.
* ``spawn.at_grid``          — arm the next spawn at the nearest grid
  cell (Blender ``Shift+S → 1``). Distinct from QQ1's
  ``spawn.at_origin``, TT2's ``spawn.at_view_center``, UU4's
  ``spawn.at_origin_offset``, and VV4's ``spawn.at_last_position``.
* ``layer.clear``            — wipe entities on the active layer while
  preserving the layer entry. Distinct from VV4's ``layer.delete``
  (removes entry too) and OO1's ``layer.merge_down`` (moves entities).

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / entity handles.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from slappyengine.tool_router import (
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


def _make_entity(
    tags: tuple[str, ...] = (),
    layer: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(tags=set(tags), layer=layer)


def _make_scene(
    entities: list | None = None,
    layers: list | None = None,
) -> SimpleNamespace:
    scene = SimpleNamespace(
        _entities=list(entities or []),
        _z_layers=list(layers or []),
    )
    scene.entities = scene._entities
    scene.z_layers = scene._z_layers
    return scene


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_view_toggle_axes_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.toggle_axes")

    def test_view_toggle_background_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_background")

    def test_edit_select_by_tag_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.select_by_tag")

    def test_spawn_at_grid_registered(self, router: ToolRouter) -> None:
        assert router.has_action("spawn.at_grid")

    def test_layer_clear_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.clear")

    def test_all_ww4_on_module_singleton(self) -> None:
        for aid in (
            "view.toggle_axes",
            "view.toggle_background",
            "edit.select_by_tag",
            "spawn.at_grid",
            "layer.clear",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_ww4_categories(self, router: ToolRouter) -> None:
        expected = {
            "view.toggle_axes": "view",
            "view.toggle_background": "view",
            "edit.select_by_tag": "edit",
            "spawn.at_grid": "spawn",
            "layer.clear": "layer",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid

    def test_edit_select_by_tag_required_args(
        self, router: ToolRouter,
    ) -> None:
        action = router.get("edit.select_by_tag")
        assert action is not None
        assert "tag" in action.required_args


# ---------------------------------------------------------------------------
# view.toggle_axes
# ---------------------------------------------------------------------------


class TestViewToggleAxes:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_axes", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_visible(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("view.toggle_axes", {"shell": shell})
        assert result["status"] == "toggled"
        assert result["target"] == "axes"
        # Default is visible=True — first toggle flips to False.
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._axes_visible is False

    def test_flip_hidden_to_visible(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_axes_visible=False)
        result = router.dispatch("view.toggle_axes", {"shell": shell})
        assert result["previous"] is False
        assert result["visible"] is True
        assert shell._axes_visible is True

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_axes", {"visible": False},
        )
        assert result["previous"] is False
        assert result["visible"] is True

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_axes", {"shell": shell})
        assert calls == [("_axes_visible", False)]


# ---------------------------------------------------------------------------
# view.toggle_background
# ---------------------------------------------------------------------------


class TestViewToggleBackground:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_background", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_visible(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "view.toggle_background", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "background"
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._background_visible is False

    def test_flip_hidden_to_visible(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_background_visible=False)
        result = router.dispatch(
            "view.toggle_background", {"shell": shell},
        )
        assert result["previous"] is False
        assert result["visible"] is True

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_background", {"visible": True},
        )
        assert result["previous"] is True
        assert result["visible"] is False

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_background", {"shell": shell})
        assert calls == [("_background_visible", False)]


# ---------------------------------------------------------------------------
# edit.select_by_tag
# ---------------------------------------------------------------------------


class TestEditSelectByTag:
    def test_missing_tag(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.select_by_tag", {})
        assert result == {"status": "missing_tag"}

    def test_empty_tag(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.select_by_tag", {"tag": "   "},
        )
        assert result == {"status": "missing_tag"}

    def test_non_string_tag(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.select_by_tag", {"tag": 42},
        )
        assert result == {"status": "missing_tag"}

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.select_by_tag", {"tag": "enemy"},
        )
        assert result == {"status": "no_scene"}

    def test_no_match(self, router: ToolRouter) -> None:
        scene = _make_scene(entities=[
            _make_entity(tags=("hero",)),
            _make_entity(tags=("prop",)),
        ])
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_by_tag",
            {"scene": scene, "shell": shell, "tag": "enemy"},
        )
        assert result == {"status": "no_match", "tag": "enemy"}

    def test_matches_single_tag(self, router: ToolRouter) -> None:
        hero = _make_entity(tags=("hero",))
        e1 = _make_entity(tags=("enemy",))
        e2 = _make_entity(tags=("enemy", "flying"))
        prop = _make_entity(tags=("prop",))
        scene = _make_scene(entities=[hero, e1, e2, prop])
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_by_tag",
            {"scene": scene, "shell": shell, "tag": "enemy"},
        )
        assert result["status"] == "selected"
        assert result["tag"] == "enemy"
        assert result["matched"] == 2
        assert result["total"] == 4
        # SimpleNamespace with a mutable set attribute is unhashable —
        # compare by identity list membership instead.
        assert e1 in result["selection"]
        assert e2 in result["selection"]
        assert hero not in result["selection"]
        assert prop not in result["selection"]
        # Shell selection populated.
        assert e1 in shell._selected_entities
        assert e2 in shell._selected_entities

    def test_falls_back_to_private_tags_attr(
        self, router: ToolRouter,
    ) -> None:
        e = SimpleNamespace(_tags={"enemy"})
        scene = _make_scene(entities=[e])
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_by_tag",
            {"scene": scene, "shell": shell, "tag": "enemy"},
        )
        assert result["status"] == "selected"
        assert result["matched"] == 1

    def test_tag_compare_is_case_sensitive(
        self, router: ToolRouter,
    ) -> None:
        e = _make_entity(tags=("Enemy",))
        scene = _make_scene(entities=[e])
        shell = SimpleNamespace()
        result = router.dispatch(
            "edit.select_by_tag",
            {"scene": scene, "shell": shell, "tag": "enemy"},
        )
        assert result["status"] == "no_match"


# ---------------------------------------------------------------------------
# spawn.at_grid
# ---------------------------------------------------------------------------


class TestSpawnAtGrid:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.at_grid", {})
        assert result == {"status": "no_shell"}

    def test_snaps_explicit_position_to_grid(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_grid",
            {
                "shell": shell,
                "position": [3.4, -1.7, 2.2],
                "grid_size": 1.0,
            },
        )
        assert result["status"] == "armed"
        assert result["source"] == "override"
        assert result["grid_size"] == 1.0
        assert result["snapped_from"] == (3.4, -1.7, 2.2)
        # round-half-to-even; 3.4→3, -1.7→-2, 2.2→2.
        assert result["position"] == (3.0, -2.0, 2.0)
        assert shell._pending_spawn_position == [3.0, -2.0, 2.0]

    def test_uses_shell_grid_size(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=4.0)
        result = router.dispatch(
            "spawn.at_grid",
            {"shell": shell, "position": [5.0, 7.0, -6.0]},
        )
        assert result["grid_size"] == 4.0
        assert result["position"] == (4.0, 8.0, -8.0)

    def test_uses_cursor_when_no_position(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_grid",
            {"shell": shell, "cursor": (1.2, 3.8, 0.5), "grid_size": 1.0},
        )
        assert result["source"] == "cursor"
        assert result["position"] == (1.0, 4.0, 0.0)  # 0.5 → 0 (banker's)

    def test_uses_shell_cursor_position(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(
            _cursor_position=[2.7, 2.7, 0.0],
        )
        result = router.dispatch(
            "spawn.at_grid",
            {"shell": shell, "grid_size": 1.0},
        )
        assert result["source"] == "shell_cursor"
        assert result["position"] == (3.0, 3.0, 0.0)

    def test_origin_fallback_when_no_source(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_grid", {"shell": shell, "grid_size": 2.0},
        )
        assert result["source"] == "origin_fallback"
        assert result["position"] == (0.0, 0.0, 0.0)

    def test_zero_grid_size_falls_back_to_default(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_grid",
            {"shell": shell, "position": [1.4, 0.0, 0.0], "grid_size": 0.0},
        )
        assert result["grid_size"] == 1.0

    def test_2vec_position_pads_z(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_grid",
            {"shell": shell, "position": (2.7, 3.2), "grid_size": 1.0},
        )
        assert result["snapped_from"] == (2.7, 3.2, 0.0)
        assert result["position"] == (3.0, 3.0, 0.0)


# ---------------------------------------------------------------------------
# layer.clear
# ---------------------------------------------------------------------------


class TestLayerClear:
    def test_no_scene(self, router: ToolRouter) -> None:
        assert router.dispatch("layer.clear", {}) == {"status": "no_scene"}

    def test_no_layer_target(self, router: ToolRouter) -> None:
        scene = _make_scene(entities=[], layers=[_make_layer("A", 0.0)])
        result = router.dispatch("layer.clear", {"scene": scene})
        assert result == {"status": "no_layer"}

    def test_clears_entities_on_target_by_identity(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        e1 = _make_entity(layer=a)
        e2 = _make_entity(layer=a)
        e3 = _make_entity(layer=b)
        scene = _make_scene(entities=[e1, e2, e3], layers=[a, b])
        result = router.dispatch(
            "layer.clear", {"scene": scene, "layer": a},
        )
        assert result["status"] == "cleared"
        assert result["target"] == "A"
        assert result["z"] == 0.0
        assert result["removed"] == 2
        assert result["kept"] == 1
        assert e1 not in scene._entities
        assert e2 not in scene._entities
        assert e3 in scene._entities

    def test_clears_by_layer_name_lookup(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        e1 = _make_entity(layer=a)
        scene = _make_scene(entities=[e1], layers=[a, b])
        result = router.dispatch(
            "layer.clear", {"scene": scene, "layer_name": "A"},
        )
        assert result["status"] == "cleared"
        assert result["removed"] == 1

    def test_uses_shell_active_layer(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        e1 = _make_entity(layer=b)
        scene = _make_scene(entities=[e1], layers=[a, b])
        shell = SimpleNamespace(_scene=scene, _active_layer=b)
        result = router.dispatch("layer.clear", {"shell": shell})
        assert result["target"] == "B"
        assert result["removed"] == 1

    def test_target_with_no_entities_reports_zero(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        e = _make_entity(layer=b)
        scene = _make_scene(entities=[e], layers=[a, b])
        result = router.dispatch(
            "layer.clear", {"scene": scene, "layer": a},
        )
        assert result["status"] == "cleared"
        assert result["removed"] == 0
        assert result["kept"] == 1

    def test_matches_layer_stored_as_name_string(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        # entity stores just the name string on ``.layer``.
        e = SimpleNamespace(layer="A")
        scene = _make_scene(entities=[e], layers=[a])
        result = router.dispatch(
            "layer.clear", {"scene": scene, "layer": a},
        )
        assert result["removed"] == 1

    def test_uses_remove_entity_when_available(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        e = _make_entity(layer=a)
        removed: list = []
        scene = _make_scene(entities=[e], layers=[a])
        scene.remove_entity = lambda x: (removed.append(x), scene._entities.remove(x))
        result = router.dispatch(
            "layer.clear", {"scene": scene, "layer": a},
        )
        assert result["removed"] == 1
        assert removed == [e]


# ---------------------------------------------------------------------------
# ctx validation — every WW4 action tolerates dispatch(id, None)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    @pytest.mark.parametrize(
        "aid",
        [
            "view.toggle_axes",
            "view.toggle_background",
            "edit.select_by_tag",
            "spawn.at_grid",
            "layer.clear",
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
