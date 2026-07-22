"""YY4 STUB-triage tests — round 25 of feature-map wiring.

Covers the five new action ids added by the YY4 sprint tick (round 25
after WW4's round-24 ``view.toggle_axes`` / ``view.toggle_background`` /
``edit.select_by_tag`` / ``spawn.at_grid`` / ``layer.clear`` batch):

* ``view.toggle_snap_indicator`` — flip the snap-point hint overlay
  (Blender snap-element indicator / Unity snap-marker dot).
  Distinct from CC1's ``view.toggle_grid`` / ``view.toggle_gizmos``,
  QQ1's ``view.toggle_stats``, PP1's ``view.toggle_wireframe``,
  VV4's ``view.toggle_ruler``, and WW4's ``view.toggle_axes`` /
  ``view.toggle_background``.
* ``edit.select_parent``        — walk one step up the scene DAG
  from the current selection (Blender ``[`` / Unity Ctrl+Shift+Up).
  Sibling to FF1's ``edit.select_children`` (walks down) and PP2's
  ``edit.select_next`` / ``edit.select_previous`` (walk sideways).
* ``spawn.at_selection_center`` — arm next spawn at the centroid of
  the current selection (Blender ``Shift+S → Cursor to Selected``).
  Distinct from QQ1's ``spawn.at_origin``, TT2's
  ``spawn.at_view_center``, UU4's ``spawn.at_origin_offset``, VV4's
  ``spawn.at_last_position``, and WW4's ``spawn.at_grid``.
* ``layer.lock``                — toggle the lock flag on a Z-layer
  (Photoshop layer padlock icon). Distinct from CC1's
  ``edit.lock_selection`` (per-entity flag) and WW4's ``layer.clear``
  (wipes contents).
* ``snap.reset_defaults``       — reset every snap knob to canonical
  defaults (Blender Prefs → Snap → Reset). Sibling to OO1's
  ``snap.increase_grid_size``, VV4's ``snap.set_grid_size``, UU4's
  ``snap.set_angle_snap``, RR1's ``snap.toggle_incremental``.

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


def _make_layer(name: str, z: float, locked: bool = False) -> SimpleNamespace:
    return SimpleNamespace(name=name, z=z, locked=locked)


def _make_entity(
    position: tuple[float, ...] | None = None,
    parent: object | None = None,
) -> SimpleNamespace:
    ns = SimpleNamespace()
    if position is not None:
        ns.position = list(position)
    if parent is not None:
        ns.parent = parent
    return ns


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
    def test_view_toggle_snap_indicator_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("view.toggle_snap_indicator")

    def test_edit_select_parent_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("edit.select_parent")

    def test_spawn_at_selection_center_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_selection_center")

    def test_layer_lock_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.lock")

    def test_snap_reset_defaults_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.reset_defaults")

    def test_all_yy4_on_module_singleton(self) -> None:
        for aid in (
            "view.toggle_snap_indicator",
            "edit.select_parent",
            "spawn.at_selection_center",
            "layer.lock",
            "snap.reset_defaults",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_yy4_categories(self, router: ToolRouter) -> None:
        expected = {
            "view.toggle_snap_indicator": "view",
            "edit.select_parent": "edit",
            "spawn.at_selection_center": "spawn",
            "layer.lock": "layer",
            "snap.reset_defaults": "snap",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid

    def test_yy4_no_required_args(self, router: ToolRouter) -> None:
        # None of the YY4 actions have hard required-arg contracts —
        # each degrades to a ``no_*`` status when its lookups don't
        # resolve. That's asserted per-action below; here we just pin
        # the fact so a future contract change lands loudly.
        for aid in (
            "view.toggle_snap_indicator",
            "edit.select_parent",
            "spawn.at_selection_center",
            "layer.lock",
            "snap.reset_defaults",
        ):
            action = router.get(aid)
            assert action is not None, aid
            assert action.required_args == [], aid


# ---------------------------------------------------------------------------
# view.toggle_snap_indicator
# ---------------------------------------------------------------------------


class TestViewToggleSnapIndicator:
    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_snap_indicator", {})
        assert result == {"status": "no_shell"}

    def test_first_toggle_from_default_visible(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "view.toggle_snap_indicator", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "snap_indicator"
        # Default is visible=True — first toggle flips to False.
        assert result["previous"] is True
        assert result["visible"] is False
        assert shell._snap_indicator_visible is False

    def test_flip_hidden_to_visible(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_indicator_visible=False)
        result = router.dispatch(
            "view.toggle_snap_indicator", {"shell": shell},
        )
        assert result["previous"] is False
        assert result["visible"] is True
        assert shell._snap_indicator_visible is True

    def test_seed_bypasses_shell(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_snap_indicator", {"visible": False},
        )
        assert result["previous"] is False
        assert result["visible"] is True

    def test_hook_fired(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []
        shell = SimpleNamespace(
            _on_view_toggle=lambda attr, val: calls.append((attr, val)),
        )
        router.dispatch("view.toggle_snap_indicator", {"shell": shell})
        assert calls == [("_snap_indicator_visible", False)]


# ---------------------------------------------------------------------------
# edit.select_parent
# ---------------------------------------------------------------------------


class TestEditSelectParent:
    def test_no_selection(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "edit.select_parent", {},
        ) == {"status": "no_selection"}

    def test_root_returns_no_parent(self, router: ToolRouter) -> None:
        root = _make_entity()
        shell = SimpleNamespace(_selected_entities=[root])
        result = router.dispatch("edit.select_parent", {"shell": shell})
        assert result == {"status": "no_parent"}

    def test_walk_single_parent(self, router: ToolRouter) -> None:
        parent = _make_entity()
        child = _make_entity(parent=parent)
        shell = SimpleNamespace(_selected_entities=[child])
        result = router.dispatch("edit.select_parent", {"shell": shell})
        assert result["status"] == "walked"
        assert result["count"] == 1
        assert parent in result["parents"]
        assert result["selection"] == [parent]
        assert shell._selected_entities == [parent]

    def test_walk_dedupes_shared_parent(self, router: ToolRouter) -> None:
        parent = _make_entity()
        c1 = _make_entity(parent=parent)
        c2 = _make_entity(parent=parent)
        shell = SimpleNamespace(_selected_entities=[c1, c2])
        result = router.dispatch("edit.select_parent", {"shell": shell})
        assert result["count"] == 1
        assert result["parents"] == [parent]

    def test_mode_add_keeps_children(self, router: ToolRouter) -> None:
        parent = _make_entity()
        child = _make_entity(parent=parent)
        shell = SimpleNamespace(_selected_entities=[child])
        result = router.dispatch(
            "edit.select_parent", {"shell": shell, "mode": "add"},
        )
        # both child and parent should be in selection.
        assert child in result["selection"]
        assert parent in result["selection"]

    def test_private_parent_attr_fallback(
        self, router: ToolRouter,
    ) -> None:
        parent = SimpleNamespace()
        child = SimpleNamespace(_parent=parent)
        shell = SimpleNamespace(_selected_entities=[child])
        result = router.dispatch("edit.select_parent", {"shell": shell})
        assert result["status"] == "walked"
        assert result["parents"] == [parent]

    def test_explicit_selection_override(
        self, router: ToolRouter,
    ) -> None:
        parent = _make_entity()
        child = _make_entity(parent=parent)
        result = router.dispatch(
            "edit.select_parent", {"selection": [child]},
        )
        assert result["status"] == "walked"
        assert result["parents"] == [parent]


# ---------------------------------------------------------------------------
# spawn.at_selection_center
# ---------------------------------------------------------------------------


class TestSpawnAtSelectionCenter:
    def test_no_selection(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "spawn.at_selection_center", {},
        ) == {"status": "no_selection"}

    def test_no_position(self, router: ToolRouter) -> None:
        e = SimpleNamespace()  # no position attribute
        shell = SimpleNamespace(_selected_entities=[e])
        result = router.dispatch(
            "spawn.at_selection_center", {"shell": shell},
        )
        assert result == {"status": "no_position"}

    def test_centroid_of_three_entities(
        self, router: ToolRouter,
    ) -> None:
        e1 = _make_entity(position=(0.0, 0.0, 0.0))
        e2 = _make_entity(position=(6.0, 0.0, 0.0))
        e3 = _make_entity(position=(0.0, 3.0, 0.0))
        shell = SimpleNamespace(_selected_entities=[e1, e2, e3])
        result = router.dispatch(
            "spawn.at_selection_center", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["count"] == 3
        assert result["samples"] == 3
        # centroid = (2, 1, 0)
        assert result["position"] == (2.0, 1.0, 0.0)
        assert shell._pending_spawn_position == [2.0, 1.0, 0.0]

    def test_2vec_positions_pad_z(self, router: ToolRouter) -> None:
        e1 = _make_entity(position=(4.0, 2.0))
        e2 = _make_entity(position=(0.0, 0.0))
        shell = SimpleNamespace(_selected_entities=[e1, e2])
        result = router.dispatch(
            "spawn.at_selection_center", {"shell": shell},
        )
        assert result["position"] == (2.0, 1.0, 0.0)

    def test_mixed_positions_skips_missing(
        self, router: ToolRouter,
    ) -> None:
        e1 = _make_entity(position=(4.0, 4.0, 0.0))
        e2 = SimpleNamespace()  # no position — skipped
        e3 = _make_entity(position=(2.0, 2.0, 0.0))
        shell = SimpleNamespace(_selected_entities=[e1, e2, e3])
        result = router.dispatch(
            "spawn.at_selection_center", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["count"] == 3
        assert result["samples"] == 2
        assert result["position"] == (3.0, 3.0, 0.0)

    def test_transform_indirection(self, router: ToolRouter) -> None:
        e = SimpleNamespace(transform=SimpleNamespace(position=[1.0, 2.0, 3.0]))
        shell = SimpleNamespace(_selected_entities=[e])
        result = router.dispatch(
            "spawn.at_selection_center", {"shell": shell},
        )
        assert result["position"] == (1.0, 2.0, 3.0)

    def test_explicit_selection_override(
        self, router: ToolRouter,
    ) -> None:
        e = _make_entity(position=(5.0, 5.0, 5.0))
        result = router.dispatch(
            "spawn.at_selection_center", {"selection": [e]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (5.0, 5.0, 5.0)


# ---------------------------------------------------------------------------
# layer.lock
# ---------------------------------------------------------------------------


class TestLayerLock:
    def test_no_scene(self, router: ToolRouter) -> None:
        assert router.dispatch("layer.lock", {}) == {"status": "no_scene"}

    def test_no_layer_target(self, router: ToolRouter) -> None:
        scene = _make_scene()
        result = router.dispatch("layer.lock", {"scene": scene})
        assert result == {"status": "no_layer"}

    def test_first_toggle_locks(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=False)
        scene = _make_scene(layers=[a])
        result = router.dispatch(
            "layer.lock", {"scene": scene, "layer": a},
        )
        assert result["status"] == "toggled"
        assert result["target"] == "A"
        assert result["z"] == 0.0
        assert result["previous"] is False
        assert result["locked"] is True
        assert a.locked is True

    def test_second_toggle_unlocks(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=True)
        scene = _make_scene(layers=[a])
        result = router.dispatch(
            "layer.lock", {"scene": scene, "layer": a},
        )
        assert result["previous"] is True
        assert result["locked"] is False
        assert a.locked is False

    def test_by_layer_name(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        b = _make_layer("B", 1.0)
        scene = _make_scene(layers=[a, b])
        result = router.dispatch(
            "layer.lock", {"scene": scene, "layer_name": "B"},
        )
        assert result["target"] == "B"
        assert b.locked is True

    def test_uses_shell_active_layer(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0)
        scene = _make_scene(layers=[a])
        shell = SimpleNamespace(_scene=scene, _active_layer=a)
        result = router.dispatch("layer.lock", {"shell": shell})
        assert result["target"] == "A"
        assert a.locked is True

    def test_seed_bypasses_read(self, router: ToolRouter) -> None:
        a = _make_layer("A", 0.0, locked=False)
        scene = _make_scene(layers=[a])
        # seed says locked=True, so toggle produces locked=False.
        result = router.dispatch(
            "layer.lock", {"scene": scene, "layer": a, "locked": True},
        )
        assert result["previous"] is True
        assert result["locked"] is False
        assert a.locked is False

    def test_refresh_hook_fired(self, router: ToolRouter) -> None:
        calls: list[str] = []
        a = _make_layer("A", 0.0)
        scene = _make_scene(layers=[a])
        shell = SimpleNamespace(
            _scene=scene,
            _active_layer=a,
            _on_layer_lock_toggled=lambda: calls.append("lock"),
        )
        router.dispatch("layer.lock", {"shell": shell})
        assert calls == ["lock"]


# ---------------------------------------------------------------------------
# snap.reset_defaults
# ---------------------------------------------------------------------------


class TestSnapResetDefaults:
    def test_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch(
            "snap.reset_defaults", {},
        ) == {"status": "no_shell"}

    def test_reset_from_non_defaults(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _snap_grid_size=8.0,
            _snap_angle_deg=45.0,
            _snap_incremental=True,
        )
        result = router.dispatch("snap.reset_defaults", {"shell": shell})
        assert result["status"] == "reset"
        assert result["changed"] is True
        assert result["previous"] == {
            "grid_size": 8.0,
            "angle_deg": 45.0,
            "incremental": True,
        }
        assert result["new"] == {
            "grid_size": 1.0,
            "angle_deg": 15.0,
            "incremental": False,
        }
        assert shell._snap_grid_size == 1.0
        assert shell._snap_angle_deg == 15.0
        assert shell._snap_incremental is False

    def test_idempotent_no_op_when_already_default(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace(
            _snap_grid_size=1.0,
            _snap_angle_deg=15.0,
            _snap_incremental=False,
        )
        result = router.dispatch("snap.reset_defaults", {"shell": shell})
        assert result["changed"] is False

    def test_writes_all_mirror_attrs(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _snap_grid_size=8.0,
            _grid_size=8.0,
            grid_size=8.0,
            _snap_angle_deg=45.0,
            _snap_angle=45.0,
            _snap_incremental=True,
            _incremental_snap=True,
        )
        router.dispatch("snap.reset_defaults", {"shell": shell})
        assert shell._snap_grid_size == 1.0
        assert shell._grid_size == 1.0
        assert shell.grid_size == 1.0
        assert shell._snap_angle_deg == 15.0
        assert shell._snap_angle == 15.0
        assert shell._snap_incremental is False
        assert shell._incremental_snap is False

    def test_missing_previous_attrs_use_defaults(
        self, router: ToolRouter,
    ) -> None:
        # Bare shell — no snap attributes at all.
        shell = SimpleNamespace()
        result = router.dispatch("snap.reset_defaults", {"shell": shell})
        assert result["status"] == "reset"
        assert result["previous"] == {
            "grid_size": 1.0,
            "angle_deg": 15.0,
            "incremental": False,
        }
        # From-nothing to defaults is a no-op, semantically.
        assert result["changed"] is False
        # But the attributes are now set on the shell.
        assert shell._snap_grid_size == 1.0


# ---------------------------------------------------------------------------
# ctx validation — every YY4 action tolerates dispatch(id, None)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    @pytest.mark.parametrize(
        "aid",
        [
            "view.toggle_snap_indicator",
            "edit.select_parent",
            "spawn.at_selection_center",
            "layer.lock",
            "snap.reset_defaults",
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
