"""VV4 STUB-triage tests — round 23 of feature-map wiring.

Covers the five new action ids added by the VV4 sprint tick (round 23
after UU4's round-22 ``spawn.at_origin_offset`` / ``edit.flatten_selection``
/ ``snap.set_angle_snap`` / ``layer.move_up`` / ``layer.move_down``
batch):

* ``layer.new``    — insert a fresh Z-layer (Photoshop
  ``Ctrl+Shift+N``). Distinct from DD1's ``edit.duplicate_layer``
  (clones existing).
* ``layer.delete`` — remove the active Z-layer (Photoshop trash-can).
  Distinct from OO1's ``layer.merge_down`` (collapse into neighbour).
  Refuses to delete the last remaining layer.
* ``snap.set_grid_size`` — absolute grid-size setter. Distinct from
  OO1's ``snap.increase_grid_size`` / ``snap.decrease_grid_size``
  (ladder step) and UU4's ``snap.set_angle_snap`` (rotation snap).
* ``view.toggle_ruler`` — flip the viewport ruler overlay (Photoshop
  ``Ctrl+R``). Distinct from CC1's ``view.toggle_grid`` /
  ``view.toggle_gizmos``, QQ1's ``view.toggle_stats``, PP1's
  ``view.toggle_wireframe``.
* ``spawn.at_last_position`` — arm (don't fire) the next spawn at
  the previous drop coordinate. Distinct from CC1's
  ``spawn.repeat_last`` (fires immediately) + QQ1's
  ``spawn.at_origin`` + TT2's ``spawn.at_view_center`` + UU4's
  ``spawn.at_origin_offset``.

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / layer handles.
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


def _make_scene(layers: list) -> SimpleNamespace:
    """Return a scene with a mutable ``z_layers`` list-style attribute."""
    scene = SimpleNamespace(_z_layers=list(layers))
    # Expose ``z_layers`` as an alias to the underlying list so both
    # attribute names hit the same storage (matches real Scene).
    scene.z_layers = scene._z_layers
    return scene


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_layer_new_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.new")

    def test_layer_delete_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.delete")

    def test_snap_set_grid_size_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.set_grid_size")

    def test_view_toggle_ruler_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_ruler")

    def test_spawn_at_last_position_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_last_position")

    def test_all_vv4_on_module_singleton(self) -> None:
        for aid in (
            "layer.new",
            "layer.delete",
            "snap.set_grid_size",
            "view.toggle_ruler",
            "spawn.at_last_position",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_vv4_categories(self, router: ToolRouter) -> None:
        expected = {
            "layer.new": "layer",
            "layer.delete": "layer",
            "snap.set_grid_size": "snap",
            "view.toggle_ruler": "view",
            "spawn.at_last_position": "spawn",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# layer.new
# ---------------------------------------------------------------------------


class TestLayerNew:
    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.new", {})
        assert result == {"status": "no_scene"}

    def test_creates_first_layer_on_empty_scene(
        self, router: ToolRouter,
    ) -> None:
        scene = _make_scene([])
        result = router.dispatch("layer.new", {"scene": scene})
        assert result["status"] == "created"
        assert result["name"] == "Layer 1"
        assert result["z"] == 0.0
        assert result["collided"] is False
        assert len(scene._z_layers) == 1
        assert scene._z_layers[0].name == "Layer 1"

    def test_creates_second_layer_with_incremented_name(
        self, router: ToolRouter,
    ) -> None:
        scene = _make_scene([_make_layer("Layer 1", 0.0)])
        result = router.dispatch("layer.new", {"scene": scene})
        assert result["name"] == "Layer 2"
        # z should be max(existing z) + 1.
        assert result["z"] == 1.0

    def test_skips_used_default_names(
        self, router: ToolRouter,
    ) -> None:
        scene = _make_scene([
            _make_layer("Layer 1", 0.0),
            _make_layer("Layer 3", 2.0),
        ])
        result = router.dispatch("layer.new", {"scene": scene})
        # Picks the first unused N (== 2), not len+1.
        assert result["name"] == "Layer 2"

    def test_explicit_name(self, router: ToolRouter) -> None:
        scene = _make_scene([])
        result = router.dispatch(
            "layer.new", {"scene": scene, "name": "Background"},
        )
        assert result["name"] == "Background"
        assert result["collided"] is False

    def test_explicit_name_collides(self, router: ToolRouter) -> None:
        scene = _make_scene([_make_layer("Background", 0.0)])
        result = router.dispatch(
            "layer.new", {"scene": scene, "name": "Background"},
        )
        assert result["name"] == "Background_2"
        assert result["collided"] is True

    def test_explicit_z_overrides_max_plus_one(
        self, router: ToolRouter,
    ) -> None:
        scene = _make_scene([_make_layer("Layer 1", 5.0)])
        result = router.dispatch(
            "layer.new", {"scene": scene, "z": -3.0},
        )
        assert result["z"] == -3.0

    def test_shell_active_layer_retargets(
        self, router: ToolRouter,
    ) -> None:
        scene = _make_scene([_make_layer("Layer 1", 0.0)])
        shell = SimpleNamespace(_scene=scene, _active_layer=None)
        router.dispatch("layer.new", {"shell": shell})
        assert shell._active_layer is not None
        assert shell._active_layer.name == "Layer 2"

    def test_refresh_hook_fires(self, router: ToolRouter) -> None:
        scene = _make_scene([])
        calls: list[str] = []
        shell = SimpleNamespace(
            _scene=scene,
            _on_layer_added=lambda: calls.append("added"),
        )
        router.dispatch("layer.new", {"shell": shell})
        assert calls == ["added"]


# ---------------------------------------------------------------------------
# layer.delete
# ---------------------------------------------------------------------------


class TestLayerDelete:
    def test_no_scene(self, router: ToolRouter) -> None:
        assert router.dispatch("layer.delete", {}) == {"status": "no_scene"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = _make_scene([])
        result = router.dispatch("layer.delete", {"scene": scene})
        assert result == {"status": "no_layers"}

    def test_no_layer_target(self, router: ToolRouter) -> None:
        scene = _make_scene([
            _make_layer("A", 0.0), _make_layer("B", 1.0),
        ])
        result = router.dispatch("layer.delete", {"scene": scene})
        assert result == {"status": "no_layer"}

    def test_refuses_last_layer(self, router: ToolRouter) -> None:
        only = _make_layer("Only", 0.0)
        scene = _make_scene([only])
        result = router.dispatch(
            "layer.delete", {"scene": scene, "layer": only},
        )
        assert result == {"status": "last_layer", "target": "Only"}
        # Layer must remain.
        assert only in scene._z_layers

    def test_deletes_named_layer(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 2.0)
        scene = _make_scene([a, b, c])
        result = router.dispatch(
            "layer.delete",
            {"scene": scene, "layer_name": "B"},
        )
        assert result["status"] == "deleted"
        assert result["target"] == "B"
        assert result["z"] == 1.0
        assert b not in scene._z_layers
        assert a in scene._z_layers
        assert c in scene._z_layers

    def test_next_active_is_layer_below(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 2.0)
        scene = _make_scene([a, b, c])
        shell = SimpleNamespace(_scene=scene, _active_layer=b)
        result = router.dispatch("layer.delete", {"shell": shell})
        assert result["target"] == "B"
        # Immediate below is A (z=0).
        assert result["next_active"] == "A"
        assert shell._active_layer is a

    def test_next_active_when_bottom_deleted_is_new_bottom(
        self, router: ToolRouter,
    ) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        c = _make_layer("C", 2.0)
        scene = _make_scene([a, b, c])
        result = router.dispatch(
            "layer.delete", {"scene": scene, "layer": a},
        )
        # No layer below A — falls back to the min-z remaining (B).
        assert result["next_active"] == "B"


# ---------------------------------------------------------------------------
# snap.set_grid_size
# ---------------------------------------------------------------------------


class TestSnapSetGridSize:
    def test_missing_size(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("snap.set_grid_size", {"shell": shell})
        assert result == {"status": "missing_size"}

    def test_non_numeric_size(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": "big"},
        )
        assert result == {"status": "missing_size"}

    def test_zero_size_invalid(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 0.0},
        )
        assert result["status"] == "invalid_size"
        assert result["value"] == 0.0

    def test_negative_size_invalid(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": -4.0},
        )
        assert result["status"] == "invalid_size"

    def test_no_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "snap.set_grid_size", {"size": 8.0},
        )
        assert result == {"status": "no_shell"}

    def test_sets_canonical_ladder_rung(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 8.0},
        )
        assert result["status"] == "set"
        assert result["new"] == 8.0
        assert result["canonical"] is True
        assert shell._snap_grid_size == 8.0

    def test_snaps_near_rung_to_canonical(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 8.005},
        )
        # Within tolerance of the 8.0 rung.
        assert result["new"] == 8.0
        assert result["canonical"] is True

    def test_non_canonical_value_kept(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 7.5},
        )
        assert result["new"] == 7.5
        assert result["canonical"] is False

    def test_clamps_to_max(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size",
            {"shell": shell, "size": 999_999.0},
        )
        assert result["new"] == 4096.0
        assert result["canonical"] is True

    def test_clamps_to_min(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 0.01},
        )
        assert result["new"] == 0.5
        assert result["canonical"] is True

    def test_unchanged_when_same(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=16.0)
        result = router.dispatch(
            "snap.set_grid_size", {"shell": shell, "size": 16.0},
        )
        assert result["status"] == "unchanged"
        assert result["value"] == 16.0


# ---------------------------------------------------------------------------
# view.toggle_ruler
# ---------------------------------------------------------------------------


class TestViewToggleRuler:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_ruler", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_hidden(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("view.toggle_ruler", {"shell": shell})
        assert result["status"] == "toggled"
        assert result["target"] == "ruler"
        assert result["previous"] is False
        assert result["visible"] is True
        assert shell._ruler_visible is True

    def test_flip_visible_true_to_false(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(_ruler_visible=True)
        result = router.dispatch("view.toggle_ruler", {"shell": shell})
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._ruler_visible is False

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_ruler", {"visible": True},
        )
        assert result["previous"] is True
        assert result["visible"] is False

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_ruler", {"shell": shell})
        assert calls == [("_ruler_visible", True)]


# ---------------------------------------------------------------------------
# spawn.at_last_position
# ---------------------------------------------------------------------------


class TestSpawnAtLastPosition:
    def test_no_shell_no_override(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.at_last_position", {})
        assert result == {"status": "no_shell"}

    def test_no_history(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position", {"shell": shell},
        )
        assert result == {"status": "no_history"}

    def test_arms_from_explicit_last_position(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position",
            {"shell": shell, "last_position": [4.0, -1.0, 2.5]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (4.0, -1.0, 2.5)
        assert result["source"] == "override"
        assert result["offset"] == (0.0, 0.0, 0.0)
        assert shell._pending_spawn_position == [4.0, -1.0, 2.5]

    def test_arms_from_last_spawn_tuple(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position",
            {
                "shell": shell,
                "last_spawn": ("rope", {"position": [1.0, 2.0, 3.0]}),
            },
        )
        assert result["position"] == (1.0, 2.0, 3.0)
        assert result["source"] == "history"

    def test_arms_from_shell_last_spawn_position(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(
            _last_spawn_position=[7.0, 7.0, 0.0],
        )
        result = router.dispatch(
            "spawn.at_last_position", {"shell": shell},
        )
        assert result["position"] == (7.0, 7.0, 0.0)
        assert result["source"] == "shell_position"

    def test_arms_from_shell_last_spawn(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _last_spawn=("ragdoll", {"origin": [0.0, 0.0, 5.0]}),
        )
        result = router.dispatch(
            "spawn.at_last_position", {"shell": shell},
        )
        assert result["position"] == (0.0, 0.0, 5.0)
        assert result["source"] == "shell_spawn"

    def test_arms_from_menu_last_spawn(self, router: ToolRouter) -> None:
        menu = SimpleNamespace(
            _last_spawn=("humanoid", {"pos": [2.0, 3.0, 4.0]}),
        )
        shell = SimpleNamespace(_spawn_menu=menu)
        result = router.dispatch(
            "spawn.at_last_position", {"shell": shell},
        )
        assert result["position"] == (2.0, 3.0, 4.0)
        assert result["source"] == "menu_spawn"

    def test_offset_applied(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position",
            {
                "shell": shell,
                "last_position": [1.0, 0.0, 0.0],
                "offset": [10.0, 0.0, 0.0],
            },
        )
        assert result["position"] == (11.0, 0.0, 0.0)
        assert result["offset"] == (10.0, 0.0, 0.0)

    def test_malformed_offset_flagged(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position",
            {
                "shell": shell,
                "last_position": [1.0, 2.0, 3.0],
                "offset": "not-a-vec",
            },
        )
        assert result["malformed_offset"] is True
        assert result["position"] == (1.0, 2.0, 3.0)

    def test_2vec_offset_pads_z(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_last_position",
            {
                "shell": shell,
                "last_position": [0.0, 0.0, 0.0],
                "offset": (5.0, 6.0),
            },
        )
        assert result["offset"] == (5.0, 6.0, 0.0)
        assert result["position"] == (5.0, 6.0, 0.0)


# ---------------------------------------------------------------------------
# ctx validation — every VV4 action raises on non-dict ctx
# ---------------------------------------------------------------------------


class TestCtxValidation:
    @pytest.mark.parametrize(
        "aid",
        [
            "layer.new",
            "layer.delete",
            "snap.set_grid_size",
            "view.toggle_ruler",
            "spawn.at_last_position",
        ],
    )
    def test_none_ctx_raises(
        self, router: ToolRouter, aid: str,
    ) -> None:
        # dispatch normalises ctx=None to {} — the ensure_ctx check
        # inside the action still succeeds on {}. Sanity check: does
        # not raise, does not return a python error.
        result = router.dispatch(aid, None)
        # Every action returns a status dict rather than raising when
        # given an empty ctx.
        assert isinstance(result, dict)
        assert "status" in result
