"""CC1 STUB-triage tests — sixth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 CC1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"CC1 STUB-triage patch"):

* ``edit.select_by_name`` — walk the scene, match every entity whose
  ``name`` equals ``ctx["name"]``, and promote them onto the shell's
  selection slots.
* ``spawn.repeat_last`` — re-invoke the ``(card_id, spec)`` tuple that
  the last ``_on_spawn`` dispatch recorded via
  :func:`~pharos_engine.actions.spawn_history_actions.record_last_spawn`.
* ``view.toggle_grid`` — flip ``shell._grid_visible``.
* ``view.toggle_gizmos`` — flip ``shell._gizmos_visible``.
* ``content.copy_asset_path`` — route through the content browser's
  ``copy_path`` (or the pyperclip / tkinter fallback chain) so the
  asset path lands on the OS clipboard.

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised end-to-end.
No DPG context is required — the fixtures use :class:`SimpleNamespace`
stand-ins for the shell / scene / browser handles.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_engine.tool_router import (
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
    """Minimal entity substitute with a ``name`` and ``id`` attribute."""

    _next_id = 0

    def __init__(self, name: str) -> None:
        self.name = name
        _FakeEntity._next_id += 1
        self.id = f"ent_{_FakeEntity._next_id}"


class _FakeScene:
    """Scene that exposes both ``entities`` and ``find_by_name``.

    Mirrors :class:`pharos_engine.scene.Scene` closely enough that the
    action helpers exercise their preferred code paths (``find_by_name``
    then walk fallback).
    """

    def __init__(self, entities: list[_FakeEntity]) -> None:
        self._entities = {e.id: e for e in entities}

    def find_by_name(self, name: str) -> list[_FakeEntity]:
        return [e for e in self._entities.values() if e.name == name]

    @property
    def entities(self) -> list[_FakeEntity]:
        return list(self._entities.values())


def _shell(scene: _FakeScene | None = None) -> SimpleNamespace:
    """Headless shell stand-in — no DPG."""
    ns = SimpleNamespace()
    ns._selected_entity = None
    ns._selected_entities = []
    if scene is not None:
        ns._engine = SimpleNamespace(scene=scene)
    return ns


# ---------------------------------------------------------------------------
# Router registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 CC1 action ids are on the canonical router."""

    def test_edit_select_by_name_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.select_by_name")

    def test_spawn_repeat_last_registered(self, router: ToolRouter) -> None:
        assert router.has_action("spawn.repeat_last")

    def test_view_toggle_grid_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.toggle_grid")

    def test_view_toggle_gizmos_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.toggle_gizmos")

    def test_content_copy_asset_path_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("content.copy_asset_path")

    def test_all_cc1_on_module_singleton(self) -> None:
        for aid in (
            "edit.select_by_name",
            "spawn.repeat_last",
            "view.toggle_grid",
            "view.toggle_gizmos",
            "content.copy_asset_path",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# edit.select_by_name (6 tests)
# ---------------------------------------------------------------------------


class TestSelectByName:
    """Cover the edit.select_by_name wiring."""

    def test_selects_single_match(self, router: ToolRouter) -> None:
        alice = _FakeEntity("alice")
        bob = _FakeEntity("bob")
        scene = _FakeScene([alice, bob])
        shell = _shell(scene)

        result = router.dispatch(
            "edit.select_by_name",
            {"shell": shell, "name": "alice"},
        )
        assert result["status"] == "selected"
        assert result["count"] == 1
        assert result["name"] == "alice"
        assert shell._selected_entity is alice
        assert shell._selected_entities == [alice]

    def test_selects_multiple_matches(self, router: ToolRouter) -> None:
        e1 = _FakeEntity("clone")
        e2 = _FakeEntity("clone")
        scene = _FakeScene([e1, e2, _FakeEntity("other")])
        shell = _shell(scene)

        result = router.dispatch(
            "edit.select_by_name",
            {"shell": shell, "name": "clone"},
        )
        assert result["status"] == "selected"
        assert result["count"] == 2
        # Plural list gets every match, singular slot gets the first.
        assert len(shell._selected_entities) == 2
        assert shell._selected_entity in shell._selected_entities

    def test_not_found_returns_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([_FakeEntity("bob")])
        shell = _shell(scene)

        result = router.dispatch(
            "edit.select_by_name",
            {"shell": shell, "name": "ghost"},
        )
        assert result == {"status": "not_found", "name": "ghost"}
        assert shell._selected_entity is None

    def test_missing_name_short_circuits(self, router: ToolRouter) -> None:
        assert router.dispatch("edit.select_by_name", {}) == {
            "status": "missing_name",
        }
        assert router.dispatch(
            "edit.select_by_name",
            {"name": ""},
        ) == {"status": "missing_name"}

    def test_no_scene_returns_status(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "edit.select_by_name",
            {"name": "alice"},
        )
        assert result == {"status": "no_scene"}

    def test_entity_ids_populated(self, router: ToolRouter) -> None:
        alice = _FakeEntity("alice")
        scene = _FakeScene([alice])
        result = router.dispatch(
            "edit.select_by_name",
            {"scene": scene, "name": "alice"},
        )
        assert result["entity_ids"] == [alice.id]


# ---------------------------------------------------------------------------
# spawn.repeat_last (5 tests)
# ---------------------------------------------------------------------------


class TestRepeatLastSpawn:
    """Cover the spawn.repeat_last wiring."""

    def test_replays_shell_last_spawn(self, router: ToolRouter) -> None:
        called: list[tuple[str, dict]] = []

        def on_spawn(card_id: str, spec: dict) -> Any:
            called.append((card_id, dict(spec)))
            return "spawned"

        shell = _shell()
        shell._on_spawn = on_spawn
        shell._last_spawn = ("rope", {"length": 4.0})

        result = router.dispatch("spawn.repeat_last", {"shell": shell})
        assert result["status"] == "respawned"
        assert result["card_id"] == "rope"
        assert result["spec"] == {"length": 4.0}
        assert called == [("rope", {"length": 4.0})]

    def test_no_history_when_shell_has_nothing(
        self, router: ToolRouter,
    ) -> None:
        shell = _shell()
        result = router.dispatch("spawn.repeat_last", {"shell": shell})
        assert result == {"status": "no_history"}

    def test_no_shell_no_override(self, router: ToolRouter) -> None:
        assert router.dispatch("spawn.repeat_last", {}) == {
            "status": "no_shell",
        }

    def test_offset_applied_to_position(self, router: ToolRouter) -> None:
        shell = _shell()
        shell._on_spawn = lambda cid, spec: None
        shell._last_spawn = ("humanoid", {"position": [1.0, 2.0, 3.0]})

        result = router.dispatch(
            "spawn.repeat_last",
            {"shell": shell, "offset": [0.5, 0.0, 0.0]},
        )
        assert result["status"] == "respawned"
        assert result["spec"]["position"] == [1.5, 2.0, 3.0]

    def test_record_last_spawn_helper(self) -> None:
        from pharos_engine.actions.spawn_history_actions import (
            record_last_spawn,
        )
        shell = _shell()
        record_last_spawn(shell, "ragdoll", {"scale": 1.2})
        assert shell._last_spawn == ("ragdoll", {"scale": 1.2})
        # Reject bad inputs silently.
        record_last_spawn(shell, "", {"foo": "bar"})
        record_last_spawn(shell, "ok", "not a dict")  # type: ignore[arg-type]
        assert shell._last_spawn == ("ragdoll", {"scale": 1.2})


# ---------------------------------------------------------------------------
# view.toggle_grid / view.toggle_gizmos (7 tests)
# ---------------------------------------------------------------------------


class TestViewToggles:
    """Cover the view.toggle_grid + view.toggle_gizmos wiring."""

    def test_grid_toggle_on_shell_flips_true_to_false(
        self, router: ToolRouter,
    ) -> None:
        shell = _shell()
        shell._grid_visible = True
        result = router.dispatch("view.toggle_grid", {"shell": shell})
        assert result["status"] == "toggled"
        assert result["target"] == "grid"
        assert result["visible"] is False
        assert result["previous"] is True
        assert shell._grid_visible is False

    def test_grid_toggle_default_when_missing_attr(
        self, router: ToolRouter,
    ) -> None:
        shell = _shell()
        # Attribute not defined — helper treats missing as True (default).
        result = router.dispatch("view.toggle_grid", {"shell": shell})
        assert result["visible"] is False
        assert shell._grid_visible is False

    def test_grid_toggle_headless_seed(self, router: ToolRouter) -> None:
        result = router.dispatch("view.toggle_grid", {"visible": False})
        assert result["visible"] is True
        assert result["previous"] is False

    def test_gizmos_toggle_on_shell(self, router: ToolRouter) -> None:
        shell = _shell()
        shell._gizmos_visible = True
        result = router.dispatch(
            "view.toggle_gizmos", {"shell": shell},
        )
        assert result["target"] == "gizmos"
        assert result["visible"] is False
        assert shell._gizmos_visible is False

    def test_gizmos_toggle_headless_seed(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.toggle_gizmos", {"visible": True},
        )
        assert result["target"] == "gizmos"
        assert result["visible"] is False

    def test_toggle_grid_no_shell_no_seed(self, router: ToolRouter) -> None:
        assert router.dispatch("view.toggle_grid", {}) == {
            "status": "no_shell",
        }

    def test_view_toggle_fires_shell_hook(self, router: ToolRouter) -> None:
        calls: list[tuple[str, bool]] = []

        def hook(attr: str, value: bool) -> None:
            calls.append((attr, value))

        shell = _shell()
        shell._grid_visible = True
        shell._on_view_toggle = hook

        router.dispatch("view.toggle_grid", {"shell": shell})
        assert calls == [("_grid_visible", False)]


# ---------------------------------------------------------------------------
# content.copy_asset_path (5 tests)
# ---------------------------------------------------------------------------


class TestCopyAssetPath:
    """Cover the content.copy_asset_path wiring."""

    def test_routes_through_browser_copy_path(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        recorded: list[Any] = []

        def copy_path(p: Any) -> str:
            recorded.append(p)
            return str(p)

        browser = SimpleNamespace(copy_path=copy_path)
        result = router.dispatch(
            "content.copy_asset_path",
            {"browser": browser, "path": tmp_path / "asset.png"},
        )
        assert result["status"] == "copied"
        assert result["backend"] == "browser"
        assert result["path"] == str(tmp_path / "asset.png")
        assert recorded == [tmp_path / "asset.png"]

    def test_missing_path(self, router: ToolRouter) -> None:
        assert router.dispatch("content.copy_asset_path", {}) == {
            "status": "missing_path",
        }
        assert router.dispatch(
            "content.copy_asset_path", {"path": ""},
        ) == {"status": "missing_path"}

    def test_falls_back_when_no_browser(self, router: ToolRouter) -> None:
        # No shell / browser — the helper still runs the pyperclip /
        # tkinter chain (which typically fails on CI) and reports the
        # backend so tests can assert on the graceful degradation.
        result = router.dispatch(
            "content.copy_asset_path",
            {"path": "H:/some/asset.png"},
        )
        assert result["status"] == "copied"
        assert result["path"] == "H:/some/asset.png"
        assert result["backend"] in ("pyperclip", "tkinter", "noop")

    def test_shell_owned_browser_used(self, router: ToolRouter) -> None:
        captured: list[str] = []

        def copy_path(p: Any) -> str:
            captured.append(str(p))
            return str(p)

        shell = _shell()
        shell._content_browser = SimpleNamespace(copy_path=copy_path)
        result = router.dispatch(
            "content.copy_asset_path",
            {"shell": shell, "path": "H:/asset.wav"},
        )
        assert result["backend"] == "browser"
        assert captured == ["H:/asset.wav"]

    def test_browser_returning_non_string_falls_back(
        self, router: ToolRouter,
    ) -> None:
        # Browser returns None (e.g. clipboard write failed silently) —
        # helper falls through to the fallback chain.
        browser = SimpleNamespace(copy_path=lambda p: None)
        result = router.dispatch(
            "content.copy_asset_path",
            {"browser": browser, "path": "H:/orphan.tex"},
        )
        assert result["status"] == "copied"
        assert result["backend"] in ("pyperclip", "tkinter", "noop")


# ---------------------------------------------------------------------------
# TypeError guards on ctx (2 tests)
# ---------------------------------------------------------------------------


class TestCtxGuards:
    """Confirm the shared ``ensure_ctx`` guard fires on non-mapping input."""

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.select_by_name",
            "spawn.repeat_last",
            "view.toggle_grid",
            "view.toggle_gizmos",
            "content.copy_asset_path",
        ],
    )
    def test_none_ctx_raises(self, action_id: str) -> None:
        # ToolRouter.dispatch converts ``None`` to ``{}`` — call the
        # helper directly to reach the guard.
        from pharos_engine.actions.edit_by_name_actions import select_by_name
        from pharos_engine.actions.spawn_history_actions import repeat_last
        from pharos_engine.actions.view_toggle_actions import (
            toggle_grid,
            toggle_gizmos,
        )
        from pharos_engine.actions.content_shell_actions import copy_asset_path

        mapping = {
            "edit.select_by_name": select_by_name,
            "spawn.repeat_last": repeat_last,
            "view.toggle_grid": toggle_grid,
            "view.toggle_gizmos": toggle_gizmos,
            "content.copy_asset_path": copy_asset_path,
        }
        with pytest.raises(TypeError):
            mapping[action_id](None)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.select_by_name",
            "spawn.repeat_last",
            "view.toggle_grid",
            "view.toggle_gizmos",
            "content.copy_asset_path",
        ],
    )
    def test_list_ctx_raises(self, action_id: str) -> None:
        from pharos_engine.actions.edit_by_name_actions import select_by_name
        from pharos_engine.actions.spawn_history_actions import repeat_last
        from pharos_engine.actions.view_toggle_actions import (
            toggle_grid,
            toggle_gizmos,
        )
        from pharos_engine.actions.content_shell_actions import copy_asset_path

        mapping = {
            "edit.select_by_name": select_by_name,
            "spawn.repeat_last": repeat_last,
            "view.toggle_grid": toggle_grid,
            "view.toggle_gizmos": toggle_gizmos,
            "content.copy_asset_path": copy_asset_path,
        }
        with pytest.raises(TypeError):
            mapping[action_id](["not", "a", "mapping"])  # type: ignore[arg-type]
