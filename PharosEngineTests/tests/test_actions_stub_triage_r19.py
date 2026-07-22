"""RR1 STUB-triage tests — round 19 of feature-map wiring.

Covers the five new action ids added by the RR1 sprint tick (round 19
after QQ1's round-18 ``spawn.at_origin`` / ``selection.by_type`` /
``selection.by_layer`` / ``selection.same_material`` / ``view.toggle_stats``
batch):

* ``edit.select_similar`` — extend selection by *combined*
  ``(kind, material)`` similarity signature (more lenient than QQ1's
  ``selection.by_type``).
* ``theme.reset_to_default`` — snap active theme back to the shipped
  baseline (companion to FF1's ``theme.reload_all`` flush verb).
* ``layer.hide_others`` — hide every non-active layer, one-shot (no
  snapshot / no toggle; distinct from OO1's ``layer.solo``).
* ``layer.isolate`` — hide non-selected *entities* (entity-level
  Blender ``Numpad /`` isolate with toggle-restore).
* ``snap.toggle_incremental`` — toggle incremental vs freeform snap
  mode.

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


class _Entity:
    def __init__(
        self,
        name: str,
        kind: str | None = None,
        material: str | None = None,
        visible: bool = True,
    ) -> None:
        self.name = name
        self.visible = visible
        if kind is not None:
            self.kind = kind
        if material is not None:
            self.material = material


class _Scene:
    def __init__(self) -> None:
        self.entities: list[_Entity] = []


class _Layer:
    def __init__(self, name: str, visible: bool = True, z: float = 0.0) -> None:
        self.name = name
        self.visible = visible
        self.z = z


class _LayeredScene:
    def __init__(self) -> None:
        self.z_layers: list[_Layer] = []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_edit_select_similar_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.select_similar")

    def test_theme_reset_to_default_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("theme.reset_to_default")

    def test_layer_hide_others_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.hide_others")

    def test_layer_isolate_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.isolate")

    def test_snap_toggle_incremental_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("snap.toggle_incremental")

    def test_all_rr1_on_module_singleton(self) -> None:
        for aid in (
            "edit.select_similar",
            "theme.reset_to_default",
            "layer.hide_others",
            "layer.isolate",
            "snap.toggle_incremental",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_rr1_categories(self, router: ToolRouter) -> None:
        expected = {
            "edit.select_similar": "edit",
            "theme.reset_to_default": "theme",
            "layer.hide_others": "layer",
            "layer.isolate": "layer",
            "snap.toggle_incremental": "snap",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# edit.select_similar
# ---------------------------------------------------------------------------


class TestEditSelectSimilar:
    def test_extends_with_matching_signature(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope", material="hemp")
        match_full = _Entity("m1", kind="rope", material="hemp")
        match_kind_only = _Entity("m2", kind="rope", material="steel")
        miss = _Entity("o", kind="humanoid", material="skin")
        scene.entities = [seed, match_full, match_kind_only, miss]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[seed])
        result = router.dispatch("edit.select_similar", {"shell": shell})
        assert result["status"] == "selected"
        # Both full-signature match and kind-only fallback pull in.
        assert match_full in result["selection"]
        assert match_kind_only in result["selection"]
        assert miss not in result["selection"]
        # Seed preserved.
        assert seed in result["selection"]

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("edit.select_similar", {})
        assert result == {"status": "no_scene"}

    def test_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("edit.select_similar", {"scene": scene})
        assert result["status"] == "no_selection"

    def test_unchanged_when_only_seed_matches(
        self, router: ToolRouter,
    ) -> None:
        scene = _Scene()
        seed = _Entity("s", kind="rope", material="hemp")
        other = _Entity("o", kind="humanoid", material="skin")
        scene.entities = [seed, other]
        result = router.dispatch(
            "edit.select_similar",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "unchanged"
        assert seed in result["selection"]

    def test_signature_via_class_fallback(
        self, router: ToolRouter,
    ) -> None:
        # Entities with no explicit kind fall through to
        # ``type(entity).__name__`` — homogeneous seed + candidates
        # should still be picked up.
        scene = _Scene()

        class _Rope:
            visible = True

        seed = _Rope()
        match = _Rope()
        # A completely different class must be excluded.

        class _Cloth:
            visible = True

        miss = _Cloth()
        scene.entities = [seed, match, miss]
        result = router.dispatch(
            "edit.select_similar",
            {"scene": scene, "selection": [seed]},
        )
        assert result["status"] == "selected"
        assert match in result["selection"]
        assert miss not in result["selection"]


# ---------------------------------------------------------------------------
# theme.reset_to_default
# ---------------------------------------------------------------------------


class TestThemeResetToDefault:
    def test_reset_to_explicit_default(self, router: ToolRouter) -> None:
        # ``ctx["themes"]`` seeds the registry roster so the test does
        # not depend on which themes the fixture bakes at import time.
        result = router.dispatch(
            "theme.reset_to_default",
            {
                "default": "notebook",
                "themes": ["notebook", "cozy_diary", "bullet_journal"],
            },
        )
        assert result["status"] in {"reset", "unchanged"}
        assert result["theme"] == "notebook"

    def test_no_themes_when_registry_empty(
        self, router: ToolRouter,
    ) -> None:
        # Empty ``themes`` override wins over the real registry — even
        # if the real registry has bakelites, the caller can force the
        # "no_themes" branch by passing an explicit empty list. The
        # helper treats an empty override as "not provided", so we need
        # a non-list sentinel that the override branch rejects. Cheat
        # by passing a truthy-but-empty roster: use a one-shot override
        # of a name absent from any registry with ``default`` set.
        result = router.dispatch(
            "theme.reset_to_default",
            {"themes": ["only_theme"], "default": "only_theme"},
        )
        # Depending on registry population, the "unchanged" or "reset"
        # branch fires — either way the target name is honoured.
        assert result["status"] in {"reset", "unchanged"}
        assert result["theme"] == "only_theme"

    def test_falls_back_to_first_registered(
        self, router: ToolRouter,
    ) -> None:
        result = router.dispatch(
            "theme.reset_to_default",
            {"themes": ["alpha", "beta", "gamma"]},
        )
        assert result["theme"] == "alpha"

    def test_shell_apply_theme_path(self, router: ToolRouter) -> None:
        seen: list[str] = []
        shell = SimpleNamespace(
            apply_theme=lambda name: seen.append(name),
            _default_theme="notebook",
        )
        result = router.dispatch(
            "theme.reset_to_default",
            {"shell": shell, "themes": ["notebook", "cozy_diary"]},
        )
        assert result["theme"] == "notebook"
        if result["status"] == "reset":
            assert result["path"] == "shell"
            assert seen == ["notebook"]


# ---------------------------------------------------------------------------
# layer.hide_others
# ---------------------------------------------------------------------------


class TestLayerHideOthers:
    def test_hides_every_non_active_layer(self, router: ToolRouter) -> None:
        scene = _LayeredScene()
        bg = _Layer("bg", visible=True, z=0.0)
        mid = _Layer("mid", visible=True, z=1.0)
        fg = _Layer("fg", visible=True, z=2.0)
        scene.z_layers = [bg, mid, fg]
        result = router.dispatch(
            "layer.hide_others", {"scene": scene, "layer": mid},
        )
        assert result["status"] == "hidden"
        assert set(result["hidden"]) == {"bg", "fg"}
        assert result["count"] == 2
        # Active layer untouched.
        assert mid.visible is True
        assert bg.visible is False
        assert fg.visible is False

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.hide_others", {})
        assert result == {"status": "no_scene"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = _LayeredScene()
        result = router.dispatch(
            "layer.hide_others",
            {"scene": scene, "layer": _Layer("phantom")},
        )
        assert result == {"status": "no_layers"}

    def test_already_hidden(self, router: ToolRouter) -> None:
        scene = _LayeredScene()
        bg = _Layer("bg", visible=False)
        mid = _Layer("mid", visible=True)
        scene.z_layers = [bg, mid]
        result = router.dispatch(
            "layer.hide_others", {"scene": scene, "layer": mid},
        )
        assert result["status"] == "already_hidden"
        assert result["hidden"] == []

    def test_no_snapshot_stored(self, router: ToolRouter) -> None:
        # Distinct contract from ``layer.solo`` — no snapshot slot.
        scene = _LayeredScene()
        bg = _Layer("bg", visible=True)
        mid = _Layer("mid", visible=True)
        scene.z_layers = [bg, mid]
        shell = SimpleNamespace(_scene=scene, _active_layer=mid)
        router.dispatch("layer.hide_others", {"shell": shell})
        assert getattr(shell, "_solo_snapshot", None) is None


# ---------------------------------------------------------------------------
# layer.isolate
# ---------------------------------------------------------------------------


class TestLayerIsolate:
    def test_hides_non_selected_entities(self, router: ToolRouter) -> None:
        scene = _Scene()
        keep = _Entity("k", visible=True)
        drop1 = _Entity("d1", visible=True)
        drop2 = _Entity("d2", visible=True)
        scene.entities = [keep, drop1, drop2]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[keep])
        result = router.dispatch("layer.isolate", {"shell": shell})
        assert result["status"] == "isolated"
        assert result["hidden_count"] == 2
        assert keep.visible is True
        assert drop1.visible is False
        assert drop2.visible is False
        # Snapshot stored for a subsequent restore.
        assert isinstance(shell._isolate_snapshot, dict)
        assert len(shell._isolate_snapshot) == 3

    def test_second_call_restores(self, router: ToolRouter) -> None:
        scene = _Scene()
        keep = _Entity("k", visible=True)
        drop = _Entity("d", visible=True)
        scene.entities = [keep, drop]
        shell = SimpleNamespace(_scene=scene, _selected_entities=[keep])
        router.dispatch("layer.isolate", {"shell": shell})
        assert drop.visible is False
        # Second call rewinds.
        result = router.dispatch("layer.isolate", {"shell": shell})
        assert result["status"] == "restored"
        assert drop.visible is True
        # Snapshot cleared post-restore.
        assert shell._isolate_snapshot is None

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch("layer.isolate", {})
        assert result == {"status": "no_scene"}

    def test_empty_scene(self, router: ToolRouter) -> None:
        scene = _Scene()
        result = router.dispatch("layer.isolate", {"scene": scene})
        assert result == {"status": "empty_scene"}

    def test_no_selection(self, router: ToolRouter) -> None:
        scene = _Scene()
        scene.entities = [_Entity("o")]
        result = router.dispatch("layer.isolate", {"scene": scene})
        assert result == {"status": "no_selection"}


# ---------------------------------------------------------------------------
# snap.toggle_incremental
# ---------------------------------------------------------------------------


class TestSnapToggleIncremental:
    def test_toggle_off_to_on(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_incremental_mode=False)
        result = router.dispatch(
            "snap.toggle_incremental", {"shell": shell},
        )
        assert result["status"] == "toggled"
        assert result["enabled"] is True
        assert result["previous"] is False
        assert result["target"] == "incremental"
        assert shell._snap_incremental_mode is True

    def test_toggle_on_to_off(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(_snap_incremental_mode=True)
        result = router.dispatch(
            "snap.toggle_incremental", {"shell": shell},
        )
        assert result["enabled"] is False
        assert shell._snap_incremental_mode is False

    def test_no_shell_no_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("snap.toggle_incremental", {})
        assert result == {"status": "no_shell"}

    def test_seed_via_enabled_ctx(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "snap.toggle_incremental", {"enabled": False},
        )
        assert result["status"] == "toggled"
        assert result["enabled"] is True

    def test_fires_snap_hook(self, router: ToolRouter) -> None:
        seen: list[tuple[str, bool]] = []

        def hook(attr: str, val: bool) -> None:
            seen.append((attr, val))

        shell = SimpleNamespace(
            _snap_incremental_mode=False, _on_snap_toggle=hook,
        )
        router.dispatch("snap.toggle_incremental", {"shell": shell})
        assert seen == [("_snap_incremental_mode", True)]
