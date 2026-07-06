"""OO1 STUB-triage tests — round 16 of feature-map wiring.

Covers the five new action ids added by the OO1 sprint tick (round 16
after NN2's round-15 view / panel / theme batch):

* ``layer.solo`` — Photoshop / Krita "solo this layer" gesture.
* ``layer.merge_down`` — Photoshop ``Ctrl+E`` merge-down flow.
* ``selection.grow`` — Blender ``Ctrl+Numpad+`` grow-selection.
* ``snap.increase_grid_size`` — Blender numpad ``+`` (snap active).
* ``snap.decrease_grid_size`` — Blender numpad ``-`` (snap active).

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / scene / layer handles.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

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


class _Layer:
    def __init__(self, name: str, z: float = 0.0, visible: bool = True) -> None:
        self.name = name
        self.z = float(z)
        self.visible = visible
        self.entities: list[Any] = []


class _Entity:
    def __init__(
        self,
        name: str,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        layer: Any = None,
    ) -> None:
        self.name = name
        self.position = list(position)
        self.layer = layer
        self.z = float(position[2])


class _Scene:
    def __init__(self) -> None:
        self.z_layers: list[_Layer] = []
        self.entities: list[_Entity] = []

    def add_z_layer(self, layer: _Layer) -> None:
        self.z_layers.append(layer)

    def remove_z_layer(self, layer: _Layer) -> None:
        try:
            self.z_layers.remove(layer)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_layer_solo_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.solo")

    def test_layer_merge_down_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.merge_down")

    def test_selection_grow_registered(self, router: ToolRouter) -> None:
        assert router.has_action("selection.grow")

    def test_snap_increase_registered(self, router: ToolRouter) -> None:
        assert router.has_action("snap.increase_grid_size")

    def test_snap_decrease_registered(self, router: ToolRouter) -> None:
        assert router.has_action("snap.decrease_grid_size")

    def test_all_oo1_on_module_singleton(self) -> None:
        for aid in (
            "layer.solo",
            "layer.merge_down",
            "selection.grow",
            "snap.increase_grid_size",
            "snap.decrease_grid_size",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_oo1_categories(self, router: ToolRouter) -> None:
        expected: dict[str, str] = {
            "layer.solo": "layer",
            "layer.merge_down": "layer",
            "selection.grow": "selection",
            "snap.increase_grid_size": "snap",
            "snap.decrease_grid_size": "snap",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# layer.solo
# ---------------------------------------------------------------------------


class TestLayerSolo:
    def test_solo_hides_other_layers(self, router: ToolRouter) -> None:
        scene = _Scene()
        a = _Layer("bg", z=0.0)
        b = _Layer("mid", z=1.0)
        c = _Layer("fg", z=2.0)
        scene.z_layers = [a, b, c]
        shell = SimpleNamespace(_scene=scene, _active_layer=b)
        result = router.dispatch("layer.solo", {"shell": shell})
        assert result["status"] == "soloed"
        assert result["target"] == "mid"
        assert a.visible is False
        assert b.visible is True
        assert c.visible is False
        assert "bg" in result["hidden"] and "fg" in result["hidden"]

    def test_solo_toggle_restores(self, router: ToolRouter) -> None:
        scene = _Scene()
        a = _Layer("bg", z=0.0, visible=True)
        b = _Layer("mid", z=1.0, visible=True)
        scene.z_layers = [a, b]
        shell = SimpleNamespace(_scene=scene, _active_layer=b)
        router.dispatch("layer.solo", {"shell": shell})
        assert a.visible is False
        # Second call with the same target restores.
        result = router.dispatch("layer.solo", {"shell": shell})
        assert result["status"] == "restored"
        assert a.visible is True
        assert b.visible is True

    def test_solo_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.solo", {})
        assert result == {"status": "no_scene"}

    def test_solo_no_layer(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("layer.solo", {"scene": scene})
        assert result["status"] in {"no_layer", "no_layers"}

    def test_solo_explicit_layer_override(self, router: ToolRouter) -> None:
        scene = _Scene()
        a = _Layer("bg", z=0.0)
        b = _Layer("fg", z=1.0)
        scene.z_layers = [a, b]
        result = router.dispatch(
            "layer.solo", {"scene": scene, "layer": a},
        )
        assert result["status"] == "soloed"
        assert result["target"] == "bg"
        assert b.visible is False


# ---------------------------------------------------------------------------
# layer.merge_down
# ---------------------------------------------------------------------------


class TestLayerMergeDown:
    def test_merge_down_moves_entities(self, router: ToolRouter) -> None:
        scene = _Scene()
        bottom = _Layer("bottom", z=0.0)
        top = _Layer("top", z=1.0)
        e1 = _Entity("a", layer=top)
        e2 = _Entity("b", layer=top)
        top.entities = [e1, e2]
        scene.z_layers = [bottom, top]
        shell = SimpleNamespace(_scene=scene, _active_layer=top)
        result = router.dispatch("layer.merge_down", {"shell": shell})
        assert result["status"] == "merged"
        assert result["source_name"] == "top"
        assert result["dest_name"] == "bottom"
        assert result["moved"] == 2
        assert top not in scene.z_layers
        assert bottom.entities == [e1, e2]
        assert shell._active_layer is bottom

    def test_merge_down_no_layer_below(self, router: ToolRouter) -> None:
        scene = _Scene()
        only = _Layer("only", z=0.0)
        scene.z_layers = [only]
        shell = SimpleNamespace(_scene=scene, _active_layer=only)
        result = router.dispatch("layer.merge_down", {"shell": shell})
        assert result["status"] == "no_layer_below"
        assert result["name"] == "only"
        # Layer stays.
        assert only in scene.z_layers

    def test_merge_down_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.merge_down", {})
        assert result == {"status": "no_scene"}

    def test_merge_down_no_layer(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("layer.merge_down", {"scene": scene})
        assert result["status"] == "no_layer"

    def test_merge_down_explicit_layer(self, router: ToolRouter) -> None:
        scene = _Scene()
        a = _Layer("a", z=0.0)
        b = _Layer("b", z=1.0)
        c = _Layer("c", z=2.0)
        e = _Entity("x", layer=b)
        b.entities = [e]
        scene.z_layers = [a, b, c]
        result = router.dispatch(
            "layer.merge_down", {"scene": scene, "layer": b},
        )
        assert result["status"] == "merged"
        assert result["dest_name"] == "a"
        assert e.layer is a


# ---------------------------------------------------------------------------
# selection.grow
# ---------------------------------------------------------------------------


class TestSelectionGrow:
    def test_grow_pulls_in_neighbours(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = _Entity("seed", position=(0.0, 0.0, 0.0))
        near = _Entity("near", position=(10.0, 0.0, 0.0))
        far = _Entity("far", position=(500.0, 0.0, 0.0))
        scene.entities = [seed, near, far]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch("selection.grow", {"shell": shell})
        assert result["status"] == "grown"
        assert result["added"] == 1
        assert near in result["selection"]
        assert far not in result["selection"]
        # shell selection updated.
        assert near in shell._selected_entities

    def test_grow_custom_radius_reaches_far(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", position=(0.0, 0.0, 0.0))
        far = _Entity("f", position=(500.0, 0.0, 0.0))
        scene.entities = [seed, far]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch(
            "selection.grow", {"shell": shell, "radius": 1000.0},
        )
        assert result["status"] == "grown"
        assert far in result["selection"]
        assert result["radius"] == pytest.approx(1000.0)

    def test_grow_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.grow", {})
        assert result == {"status": "no_scene"}

    def test_grow_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("selection.grow", {"scene": scene})
        assert result["status"] == "no_selection"

    def test_grow_unchanged_when_nothing_nearby(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", position=(0.0, 0.0, 0.0))
        far = _Entity("f", position=(1_000_000.0, 0.0, 0.0))
        scene.entities = [seed, far]
        result = router.dispatch(
            "selection.grow",
            {"scene": scene, "selection": [seed], "radius": 1.0},
        )
        assert result["status"] == "unchanged"
        assert result["previous_count"] == 1


# ---------------------------------------------------------------------------
# snap.increase_grid_size + snap.decrease_grid_size
# ---------------------------------------------------------------------------


class TestSnapGridSize:
    def test_increase_from_8_doubles_to_16(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=8.0)
        result = router.dispatch("snap.increase_grid_size", {"shell": shell})
        assert result["status"] == "stepped"
        assert result["previous"] == pytest.approx(8.0)
        assert result["new"] == pytest.approx(16.0)
        assert shell._snap_grid_size == pytest.approx(16.0)

    def test_decrease_from_8_halves_to_4(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=8.0)
        result = router.dispatch("snap.decrease_grid_size", {"shell": shell})
        assert result["status"] == "stepped"
        assert result["previous"] == pytest.approx(8.0)
        assert result["new"] == pytest.approx(4.0)
        assert shell._snap_grid_size == pytest.approx(4.0)

    def test_increase_at_max_clamps(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=4096.0)
        result = router.dispatch("snap.increase_grid_size", {"shell": shell})
        assert result["status"] == "at_limit"
        assert result["new"] == pytest.approx(4096.0)

    def test_decrease_at_min_clamps(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=0.5)
        result = router.dispatch("snap.decrease_grid_size", {"shell": shell})
        assert result["status"] == "at_limit"
        assert result["new"] == pytest.approx(0.5)

    def test_grid_size_override_wins(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=8.0)
        result = router.dispatch(
            "snap.increase_grid_size",
            {"shell": shell, "grid_size": 32.0},
        )
        assert result["previous"] == pytest.approx(32.0)
        assert result["new"] == pytest.approx(64.0)

    def test_increase_without_shell_uses_default(
        self, router: ToolRouter,
    ) -> None:
        # No shell → starts at _DEFAULT_GRID (8.0) and steps to 16.0.
        result = router.dispatch("snap.increase_grid_size", {})
        assert result["status"] == "stepped"
        assert result["previous"] == pytest.approx(8.0)
        assert result["new"] == pytest.approx(16.0)

    def test_direction_field_present(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_grid_size=8.0)
        up = router.dispatch("snap.increase_grid_size", {"shell": shell})
        assert up["direction"] == "up"
        shell2 = SimpleNamespace(_snap_grid_size=8.0)
        down = router.dispatch("snap.decrease_grid_size", {"shell": shell2})
        assert down["direction"] == "down"
