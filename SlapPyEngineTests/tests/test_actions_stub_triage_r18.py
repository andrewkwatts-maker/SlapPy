"""QQ1 STUB-triage tests — round 18 of feature-map wiring.

Covers the five new action ids added by the QQ1 sprint tick (round 18
after PP1's round-17 ``selection.shrink`` / ``selection.invert_by_type``
/ ``view.toggle_wireframe`` / ``edit.rename`` / ``edit.duplicate_at_cursor``
batch):

* ``spawn.at_origin`` — arm the next spawn to land at world (0,0,0).
* ``selection.by_type`` — extend selection by matching kind (inclusive
  variant of PP1's ``selection.invert_by_type``).
* ``selection.by_layer`` — extend selection by shared layer id.
* ``selection.same_material`` — extend selection by shared material.
* ``view.toggle_stats`` — toggle the FPS / entity-count HUD overlay.

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


class _Entity:
    def __init__(
        self,
        name: str,
        kind: str | None = None,
        layer: str | None = None,
        material: str | None = None,
    ) -> None:
        self.name = name
        if kind is not None:
            self.kind = kind
        if layer is not None:
            self.layer = layer
        if material is not None:
            self.material = material


class _Scene:
    def __init__(self) -> None:
        self.entities: list[_Entity] = []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_spawn_at_origin_registered(self, router: ToolRouter) -> None:
        assert router.has_action("spawn.at_origin")

    def test_selection_by_type_registered(self, router: ToolRouter) -> None:
        assert router.has_action("selection.by_type")

    def test_selection_by_layer_registered(self, router: ToolRouter) -> None:
        assert router.has_action("selection.by_layer")

    def test_selection_same_material_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("selection.same_material")

    def test_view_toggle_stats_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.toggle_stats")

    def test_all_qq1_on_module_singleton(self) -> None:
        for aid in (
            "spawn.at_origin",
            "selection.by_type",
            "selection.by_layer",
            "selection.same_material",
            "view.toggle_stats",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_qq1_categories(self, router: ToolRouter) -> None:
        expected = {
            "spawn.at_origin": "spawn",
            "selection.by_type": "selection",
            "selection.by_layer": "selection",
            "selection.same_material": "selection",
            "view.toggle_stats": "view",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# spawn.at_origin
# ---------------------------------------------------------------------------


class TestSpawnAtOrigin:
    def test_arm_writes_pending_spawn_position(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("spawn.at_origin", {"shell": shell})
        assert result["status"] == "armed"
        assert result["position"] == (0.0, 0.0, 0.0)
        assert shell._pending_spawn_position == [0.0, 0.0, 0.0]

    def test_no_shell_no_repeat(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.at_origin", {})
        assert result == {"status": "no_shell"}

    def test_repeat_dispatches_last_spawn_at_origin(
        self, router: ToolRouter,
    ) -> None:
        seen: list[tuple[str, dict]] = []

        def on_spawn(card_id: str, spec: dict) -> None:
            seen.append((card_id, spec))

        shell = SimpleNamespace(
            _on_spawn=on_spawn,
            _last_spawn=("rope", {"position": [42.0, 42.0, 42.0]}),
        )
        result = router.dispatch(
            "spawn.at_origin", {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "respawned"
        assert result["card_id"] == "rope"
        assert result["position"] == (0.0, 0.0, 0.0)
        assert seen[0][1]["position"] == [0.0, 0.0, 0.0]

    def test_repeat_falls_back_to_arm_when_no_history(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_origin", {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "armed"

    def test_repeat_via_explicit_last_spawn_ctx(
        self, router: ToolRouter,
    ) -> None:
        seen: list[tuple[str, dict]] = []
        shell = SimpleNamespace(
            _on_spawn=lambda cid, spec: seen.append((cid, spec)),
        )
        result = router.dispatch(
            "spawn.at_origin",
            {
                "shell": shell,
                "mode": "repeat",
                "last_spawn": ("cube", {"position": [9.0, 9.0, 9.0]}),
            },
        )
        assert result["status"] == "respawned"
        assert seen[0][1]["position"] == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# selection.by_type
# ---------------------------------------------------------------------------


class TestSelectionByType:
    def test_extends_with_matching_kinds(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope")
        r1 = _Entity("r1", kind="rope")
        r2 = _Entity("r2", kind="rope")
        other = _Entity("o", kind="humanoid")
        scene.entities = [seed, r1, r2, other]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch("selection.by_type", {"shell": shell})
        assert result["status"] == "selected"
        assert result["added"] == 2
        assert result["total"] == 3
        # Seed preserved (unlike PP1's invert_by_type).
        assert seed in result["selection"]
        assert r1 in result["selection"]
        assert r2 in result["selection"]
        assert other not in result["selection"]

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.by_type", {})
        assert result == {"status": "no_scene"}

    def test_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("selection.by_type", {"scene": scene})
        assert result["status"] == "no_selection"

    def test_unchanged_when_only_seed_matches(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope")
        other = _Entity("o", kind="humanoid")
        scene.entities = [seed, other]
        result = router.dispatch(
            "selection.by_type",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "unchanged"
        assert seed in result["selection"]

    def test_multi_kind_seed(self, router: ToolRouter) -> None:
        scene = _Scene()
        rope_seed = _Entity("rs", kind="rope")
        cloth_seed = _Entity("cs", kind="cloth")
        r_other = _Entity("r2", kind="rope")
        c_other = _Entity("c2", kind="cloth")
        misc = _Entity("m", kind="metal")
        scene.entities = [rope_seed, cloth_seed, r_other, c_other, misc]
        result = router.dispatch(
            "selection.by_type",
            {"scene": scene, "selection": [rope_seed, cloth_seed]},
        )
        assert result["status"] == "selected"
        assert result["added"] == 2
        assert set(result["kinds"]) == {"rope", "cloth"}


# ---------------------------------------------------------------------------
# selection.by_layer
# ---------------------------------------------------------------------------


class TestSelectionByLayer:
    def test_extends_with_same_layer(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = _Entity("s", layer="bg")
        b1 = _Entity("b1", layer="bg")
        fg = _Entity("fg", layer="fg")
        scene.entities = [seed, b1, fg]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch("selection.by_layer", {"shell": shell})
        assert result["status"] == "selected"
        assert result["added"] == 1
        assert b1 in result["selection"]
        assert fg not in result["selection"]
        assert result["layers"] == ["bg"]

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.by_layer", {})
        assert result == {"status": "no_scene"}

    def test_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("selection.by_layer", {"scene": scene})
        assert result["status"] == "no_selection"

    def test_default_layer_fallback(self, router: ToolRouter) -> None:
        # Entities without any layer attr should all collapse to the
        # implicit "default" layer, so they select each other.
        scene = _Scene()
        seed = _Entity("s")
        other = _Entity("o")
        scene.entities = [seed, other]
        result = router.dispatch(
            "selection.by_layer",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "selected"
        assert result["layers"] == ["default"]
        assert other in result["selection"]

    def test_layer_via_tag_dict(self, router: ToolRouter) -> None:
        scene = _Scene()
        seed = SimpleNamespace(tags={"layer": "midground"})
        match = SimpleNamespace(tags={"layer": "midground"})
        miss = SimpleNamespace(tags={"layer": "foreground"})
        scene.entities = [seed, match, miss]
        result = router.dispatch(
            "selection.by_layer",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "selected"
        assert match in result["selection"]
        assert miss not in result["selection"]


# ---------------------------------------------------------------------------
# selection.same_material
# ---------------------------------------------------------------------------


class TestSelectionSameMaterial:
    def test_extends_with_matching_material(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", material="steel")
        m1 = _Entity("m1", material="steel")
        wood = _Entity("w", material="wood")
        scene.entities = [seed, m1, wood]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch(
            "selection.same_material", {"shell": shell},
        )
        assert result["status"] == "selected"
        assert result["added"] == 1
        assert m1 in result["selection"]
        assert wood not in result["selection"]
        assert result["materials"] == ["steel"]

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("selection.same_material", {})
        assert result == {"status": "no_scene"}

    def test_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch(
            "selection.same_material", {"scene": scene},
        )
        assert result["status"] == "no_selection"

    def test_no_materials_when_seed_untagged(
        self, router: ToolRouter,
    ) -> None:
        # Bare entities without any material carry return no_materials.
        scene = _Scene()
        seed = _Entity("s")
        other = _Entity("o", material="steel")
        scene.entities = [seed, other]
        result = router.dispatch(
            "selection.same_material",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "no_materials"
        assert result["previous_count"] == 1

    def test_material_via_object_with_name(
        self, router: ToolRouter,
    ) -> None:
        # Some entities carry a material *object* — the helper should
        # pull `.name` off it when resolving the key.
        mat_obj = SimpleNamespace(name="rubber")
        scene = _Scene()
        seed = SimpleNamespace(material=mat_obj)
        match = SimpleNamespace(material="rubber")
        miss = SimpleNamespace(material="metal")
        scene.entities = [seed, match, miss]
        result = router.dispatch(
            "selection.same_material",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "selected"
        assert match in result["selection"]
        assert miss not in result["selection"]
        assert result["materials"] == ["rubber"]


# ---------------------------------------------------------------------------
# view.toggle_stats
# ---------------------------------------------------------------------------


class TestViewToggleStats:
    def test_toggle_off_to_on(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_stats_visible=False)
        result = router.dispatch("view.toggle_stats", {"shell": shell})
        assert result["status"] == "toggled"
        assert result["visible"] is True
        assert result["previous"] is False
        assert result["target"] == "stats"
        assert shell._stats_visible is True

    def test_toggle_on_to_off(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_stats_visible=True)
        result = router.dispatch("view.toggle_stats", {"shell": shell})
        assert result["visible"] is False
        assert shell._stats_visible is False

    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_stats", {})
        assert result == {"status": "no_shell"}

    def test_seed_via_visible_ctx(self, router: ToolRouter) -> None:
        # Explicit ``visible`` seed lets tests run without a shell.
        result = router.dispatch("view.toggle_stats", {"visible": False})
        assert result["status"] == "toggled"
        assert result["visible"] is True

    def test_fires_view_hook(self, router: ToolRouter) -> None:
        seen: list[tuple[str, bool]] = []

        def hook(attr: str, val: bool) -> None:
            seen.append((attr, val))

        shell = SimpleNamespace(_stats_visible=False, _on_view_toggle=hook)
        router.dispatch("view.toggle_stats", {"shell": shell})
        assert seen == [("_stats_visible", True)]
