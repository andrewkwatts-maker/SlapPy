"""DD1 STUB-triage tests — seventh round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 DD1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"DD1 STUB-triage patch"):

* ``edit.duplicate_layer`` — deep-copy the active ``ZLayer`` and add
  the clone to the scene.
* ``theme.cycle_reverse`` — walk the theme registry backwards; shares
  the cursor with ``theme.cycle``.
* ``panel.close_all`` — hide every visible panel; push the batch onto
  the shell's hidden-panel stack.
* ``panel.restore_last_hidden`` — pop the last batch off the stack
  and re-show every panel in it.
* ``spawn.repeat_last_batch`` — re-fire the most recent spawn N times
  in a grid, applying a per-cell offset so copies don't overlap.

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised end-to-end.
No DPG context is required — the fixtures use :class:`SimpleNamespace`
stand-ins for the shell / scene handles.
"""
from __future__ import annotations

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


class _FakeLayer:
    """Minimal ZLayer stand-in with the attributes we need."""

    def __init__(
        self,
        name: str,
        z: float = 0.0,
        parallax_x: float = 1.0,
        parallax_y: float = 1.0,
    ) -> None:
        self.name = name
        self.z = z
        self.parallax_x = parallax_x
        self.parallax_y = parallax_y
        self.is_shadow_receiver = True


class _FakeScene:
    """Scene stand-in exposing z_layers + add_z_layer semantics."""

    def __init__(self, layers: list[_FakeLayer] | None = None) -> None:
        self._z_layers: list[_FakeLayer] = list(layers or [])

    @property
    def z_layers(self) -> list[_FakeLayer]:
        return self._z_layers

    def add_z_layer(self, layer: _FakeLayer) -> None:
        self._z_layers.append(layer)


def _shell(scene: _FakeScene | None = None) -> SimpleNamespace:
    ns = SimpleNamespace()
    if scene is not None:
        ns._engine = SimpleNamespace(scene=scene)
    return ns


# ---------------------------------------------------------------------------
# Registration checks (6 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 DD1 action ids are on the canonical router."""

    def test_edit_duplicate_layer_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.duplicate_layer")

    def test_theme_cycle_reverse_registered(self, router: ToolRouter) -> None:
        assert router.has_action("theme.cycle_reverse")

    def test_panel_close_all_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.close_all")

    def test_panel_restore_last_hidden_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("panel.restore_last_hidden")

    def test_spawn_repeat_last_batch_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.repeat_last_batch")

    def test_all_dd1_on_module_singleton(self) -> None:
        for aid in (
            "edit.duplicate_layer",
            "theme.cycle_reverse",
            "panel.close_all",
            "panel.restore_last_hidden",
            "spawn.repeat_last_batch",
        ):
            assert REGISTRY.has_action(aid), aid


# ---------------------------------------------------------------------------
# edit.duplicate_layer (6 tests)
# ---------------------------------------------------------------------------


class TestDuplicateLayer:
    """Cover the edit.duplicate_layer wiring."""

    def test_duplicates_shell_active_layer(self, router: ToolRouter) -> None:
        layer = _FakeLayer("bg", z=1.5, parallax_x=0.5)
        scene = _FakeScene([layer])
        shell = _shell(scene)
        shell._active_layer = layer

        result = router.dispatch("edit.duplicate_layer", {"shell": shell})
        assert result["status"] == "duplicated"
        assert result["source_name"] == "bg"
        assert result["new_name"] == "bg copy"
        assert result["z"] == pytest.approx(1.5)
        # Scene now has two layers.
        assert len(scene.z_layers) == 2
        # The clone is a distinct object.
        assert scene.z_layers[-1] is not layer
        # Shell active-layer retargets to the clone.
        assert shell._active_layer is scene.z_layers[-1]

    def test_falls_back_to_last_scene_layer(self, router: ToolRouter) -> None:
        # No shell active-layer, no ctx["layer"] — helper uses the
        # last entry of scene.z_layers.
        top = _FakeLayer("top", z=5.0)
        bot = _FakeLayer("bot", z=0.0)
        scene = _FakeScene([bot, top])
        shell = _shell(scene)

        result = router.dispatch("edit.duplicate_layer", {"shell": shell})
        assert result["source_name"] == "top"

    def test_explicit_ctx_layer_wins(self, router: ToolRouter) -> None:
        layer_a = _FakeLayer("a")
        layer_b = _FakeLayer("b")
        scene = _FakeScene([layer_a, layer_b])
        shell = _shell(scene)
        shell._active_layer = layer_a  # would normally be picked

        result = router.dispatch(
            "edit.duplicate_layer",
            {"shell": shell, "layer": layer_b},
        )
        assert result["source_name"] == "b"

    def test_no_scene_returns_status(self, router: ToolRouter) -> None:
        assert router.dispatch("edit.duplicate_layer", {}) == {
            "status": "no_scene",
        }

    def test_no_layer_returns_status(self, router: ToolRouter) -> None:
        scene = _FakeScene([])
        shell = _shell(scene)
        assert router.dispatch(
            "edit.duplicate_layer", {"shell": shell},
        ) == {"status": "no_layer"}

    def test_name_bumps_on_collision(self, router: ToolRouter) -> None:
        # "bg copy" already exists — helper should pick "bg copy 2".
        base = _FakeLayer("bg")
        existing = _FakeLayer("bg copy")
        scene = _FakeScene([base, existing])
        shell = _shell(scene)
        shell._active_layer = base

        result = router.dispatch("edit.duplicate_layer", {"shell": shell})
        assert result["new_name"] == "bg copy 2"


# ---------------------------------------------------------------------------
# theme.cycle_reverse (4 tests)
# ---------------------------------------------------------------------------


class TestCycleThemeReverse:
    """Cover the theme.cycle_reverse wiring."""

    def test_shell_reverse_hook_used(self, router: ToolRouter) -> None:
        shell = _shell()
        shell.cycle_theme_reverse = lambda: "dark"
        result = router.dispatch("theme.cycle_reverse", {"shell": shell})
        assert result["status"] == "cycled"
        assert result["theme"] == "dark"
        assert result["direction"] == "reverse"
        assert result["path"] == "shell"

    def test_fallback_walks_registry_backwards(
        self, router: ToolRouter,
    ) -> None:
        from pharos_engine.actions import theme_actions as ta

        # Seed the shared cursor at "b" — reverse should land on "a".
        ta._reset_theme_cursor_for_tests()
        ta._THEME_CURSOR = "b"

        result = router.dispatch(
            "theme.cycle_reverse",
            {"themes": ["a", "b", "c"]},
        )
        assert result["theme"] == "a"
        assert result["direction"] == "reverse"
        assert result["path"] == "fallback"

    def test_fallback_no_cursor_lands_on_tail(
        self, router: ToolRouter,
    ) -> None:
        from pharos_engine.actions import theme_actions as ta
        ta._reset_theme_cursor_for_tests()
        result = router.dispatch(
            "theme.cycle_reverse",
            {"themes": ["red", "green", "blue"]},
        )
        assert result["theme"] == "blue"

    def test_no_themes_returns_status(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "theme.cycle_reverse", {"themes": []},
        )
        # Empty override falls through to the real registry — accept
        # either the "no_themes" short-circuit or a successful cycle
        # with a real theme name.
        assert result["status"] in ("no_themes", "cycled")


# ---------------------------------------------------------------------------
# panel.close_all + panel.restore_last_hidden (7 tests)
# ---------------------------------------------------------------------------


class _FakePanelShell:
    """Shell with a canned panel-visibility map + setter/toggler."""

    def __init__(self, initial: dict[str, bool]) -> None:
        self._panel_layout_state: dict[str, Any] = {
            pid: SimpleNamespace(visible=vis, panel_id=pid)
            for pid, vis in initial.items()
        }
        self._panel_windows: dict[str, Any] = {}

    def set_panel_visible(self, panel_id: str, visible: bool) -> None:
        entry = self._panel_layout_state.setdefault(
            panel_id, SimpleNamespace(visible=True, panel_id=panel_id),
        )
        entry.visible = visible

    def panel_state(self, panel_id: str) -> bool:
        entry = self._panel_layout_state.get(panel_id)
        return bool(getattr(entry, "visible", True)) if entry else True


class TestPanelVisibility:
    """Cover panel.close_all + panel.restore_last_hidden."""

    def test_close_all_hides_visible_panels(self, router: ToolRouter) -> None:
        shell = _FakePanelShell({
            "outliner": True,
            "inspector": True,
            "content_browser": True,
        })
        result = router.dispatch(
            "panel.close_all",
            {"shell": shell, "panels": [
                "outliner", "inspector", "content_browser",
            ]},
        )
        assert result["status"] == "closed"
        assert set(result["panels"]) == {
            "outliner", "inspector", "content_browser",
        }
        assert result["count"] == 3
        # All three panels are now hidden.
        for pid in ("outliner", "inspector", "content_browser"):
            assert shell.panel_state(pid) is False

    def test_close_all_skips_already_hidden(self, router: ToolRouter) -> None:
        shell = _FakePanelShell({
            "outliner": False,  # already hidden
            "inspector": True,
        })
        result = router.dispatch(
            "panel.close_all",
            {"shell": shell, "panels": ["outliner", "inspector"]},
        )
        assert result["panels"] == ["inspector"]

    def test_close_all_pushes_to_stack(self, router: ToolRouter) -> None:
        shell = _FakePanelShell({"outliner": True, "inspector": True})
        router.dispatch(
            "panel.close_all",
            {"shell": shell, "panels": ["outliner", "inspector"]},
        )
        stack = getattr(shell, "_hidden_panel_stack", None)
        assert isinstance(stack, list)
        assert stack[-1] == ["outliner", "inspector"]

    def test_close_all_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("panel.close_all", {}) == {
            "status": "no_shell",
        }

    def test_restore_last_hidden_pops_batch(self, router: ToolRouter) -> None:
        shell = _FakePanelShell({"outliner": True, "inspector": True})
        router.dispatch(
            "panel.close_all",
            {"shell": shell, "panels": ["outliner", "inspector"]},
        )
        # Sanity — both hidden after close_all.
        assert shell.panel_state("outliner") is False
        assert shell.panel_state("inspector") is False

        result = router.dispatch(
            "panel.restore_last_hidden", {"shell": shell},
        )
        assert result["status"] == "restored"
        assert set(result["panels"]) == {"outliner", "inspector"}
        # And the panels are visible again.
        assert shell.panel_state("outliner") is True
        assert shell.panel_state("inspector") is True

    def test_restore_last_hidden_empty_stack(
        self, router: ToolRouter,
    ) -> None:
        shell = _FakePanelShell({"outliner": True})
        assert router.dispatch(
            "panel.restore_last_hidden", {"shell": shell},
        ) == {"status": "empty_stack"}

    def test_restore_last_hidden_no_shell(self, router: ToolRouter) -> None:
        assert router.dispatch("panel.restore_last_hidden", {}) == {
            "status": "no_shell",
        }


# ---------------------------------------------------------------------------
# spawn.repeat_last_batch (7 tests)
# ---------------------------------------------------------------------------


class TestRepeatLastBatch:
    """Cover the spawn.repeat_last_batch wiring."""

    def test_batches_default_count_four(self, router: ToolRouter) -> None:
        calls: list[tuple[str, dict]] = []

        shell = _shell()
        shell._on_spawn = lambda cid, spec: calls.append((cid, dict(spec)))
        shell._last_spawn = ("rope", {"position": [0.0, 0.0, 0.0]})

        result = router.dispatch(
            "spawn.repeat_last_batch", {"shell": shell},
        )
        assert result["status"] == "batched"
        assert result["card_id"] == "rope"
        assert result["count"] == 4
        # Default count=4 => 2x2 grid.
        assert result["columns"] == 2
        # And the _on_spawn hook fired four times.
        assert len(calls) == 4

    def test_grid_offsets_applied(self, router: ToolRouter) -> None:
        shell = _shell()
        shell._on_spawn = lambda cid, spec: None
        shell._last_spawn = ("cube", {"position": [10.0, 20.0, 0.0]})

        result = router.dispatch(
            "spawn.repeat_last_batch",
            {"shell": shell, "count": 4, "columns": 2, "spacing": [1.0, 2.0]},
        )
        positions = [tuple(s["position"]) for s in result["specs"]]
        # 2x2 grid, spacing (1, 2) in xy — origin is (10, 20, 0).
        assert positions == [
            (10.0, 20.0, 0.0),
            (11.0, 20.0, 0.0),
            (10.0, 22.0, 0.0),
            (11.0, 22.0, 0.0),
        ]

    def test_zero_count_returns_no_history(self, router: ToolRouter) -> None:
        shell = _shell()
        shell._last_spawn = ("rope", {"position": [0.0, 0.0]})
        assert router.dispatch(
            "spawn.repeat_last_batch", {"shell": shell, "count": 0},
        ) == {"status": "no_history"}

    def test_no_history(self, router: ToolRouter) -> None:
        shell = _shell()
        assert router.dispatch(
            "spawn.repeat_last_batch", {"shell": shell},
        ) == {"status": "no_history"}

    def test_no_shell_returns_status(self, router: ToolRouter) -> None:
        assert router.dispatch("spawn.repeat_last_batch", {}) == {
            "status": "no_shell",
        }

    def test_explicit_last_spawn_override(self, router: ToolRouter) -> None:
        # Headless caller — no shell, no dispatch, but a spec list back.
        result = router.dispatch(
            "spawn.repeat_last_batch",
            {
                "last_spawn": ("ragdoll", {"position": [0.0, 0.0]}),
                "count": 2,
                "spacing": [3.0, 3.0],
            },
        )
        assert result["status"] == "batched"
        assert result["count"] == 2
        assert result["specs"][0]["position"] == [0.0, 0.0]
        assert result["specs"][1]["position"] == [3.0, 0.0]

    def test_last_spawn_updated_to_final_cell(
        self, router: ToolRouter,
    ) -> None:
        # After a batch, the shell's _last_spawn slot should point at
        # the final cell so a subsequent spawn.repeat_last continues
        # the grid rather than restarting at origin.
        shell = _shell()
        shell._on_spawn = lambda cid, spec: None
        shell._last_spawn = ("cube", {"position": [0.0, 0.0]})
        router.dispatch(
            "spawn.repeat_last_batch",
            {"shell": shell, "count": 2, "columns": 2, "spacing": [1.0, 1.0]},
        )
        card_id, spec = shell._last_spawn
        assert card_id == "cube"
        # Second cell in a 2-col row-0 grid => (1.0, 0.0).
        assert spec["position"] == [1.0, 0.0]


# ---------------------------------------------------------------------------
# ctx-guards (2 tests)
# ---------------------------------------------------------------------------


class TestCtxGuards:
    """Confirm the shared ``ensure_ctx`` guard fires on non-mapping input."""

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.duplicate_layer",
            "theme.cycle_reverse",
            "panel.close_all",
            "panel.restore_last_hidden",
            "spawn.repeat_last_batch",
        ],
    )
    def test_none_ctx_raises(self, action_id: str) -> None:
        from pharos_engine.actions.layer_duplicate_actions import (
            duplicate_layer,
        )
        from pharos_engine.actions.theme_cycle_reverse_actions import (
            cycle_theme_reverse,
        )
        from pharos_engine.actions.panel_visibility_actions import (
            close_all_panels,
            restore_last_hidden_panel,
        )
        from pharos_engine.actions.spawn_batch_actions import (
            repeat_last_batch,
        )

        mapping = {
            "edit.duplicate_layer": duplicate_layer,
            "theme.cycle_reverse": cycle_theme_reverse,
            "panel.close_all": close_all_panels,
            "panel.restore_last_hidden": restore_last_hidden_panel,
            "spawn.repeat_last_batch": repeat_last_batch,
        }
        with pytest.raises(TypeError):
            mapping[action_id](None)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "action_id",
        [
            "edit.duplicate_layer",
            "theme.cycle_reverse",
            "panel.close_all",
            "panel.restore_last_hidden",
            "spawn.repeat_last_batch",
        ],
    )
    def test_list_ctx_raises(self, action_id: str) -> None:
        from pharos_engine.actions.layer_duplicate_actions import (
            duplicate_layer,
        )
        from pharos_engine.actions.theme_cycle_reverse_actions import (
            cycle_theme_reverse,
        )
        from pharos_engine.actions.panel_visibility_actions import (
            close_all_panels,
            restore_last_hidden_panel,
        )
        from pharos_engine.actions.spawn_batch_actions import (
            repeat_last_batch,
        )

        mapping = {
            "edit.duplicate_layer": duplicate_layer,
            "theme.cycle_reverse": cycle_theme_reverse,
            "panel.close_all": close_all_panels,
            "panel.restore_last_hidden": restore_last_hidden_panel,
            "spawn.repeat_last_batch": repeat_last_batch,
        }
        with pytest.raises(TypeError):
            mapping[action_id](["not", "a", "mapping"])  # type: ignore[arg-type]
