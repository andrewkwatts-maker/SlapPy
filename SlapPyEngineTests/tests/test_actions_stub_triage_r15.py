"""NN2 STUB-triage tests — round 15 of feature-map wiring.

Covers the five new action ids added by the NN2 sprint tick (round 15
after r14's ``capture_actions`` + ``render_toggle_actions`` landings):

* ``view.frame_selected`` — Blender ``.`` / Maya ``F`` frame-current-
  selection gesture. Pans AND zooms — distinct from
  ``view.center_on_selection`` (pan only) and ``view.frame_all``
  (whole scene).
* ``view.reset_view`` — Blender ``Home`` / Unreal ``End`` restore-home
  camera pose. Distinct from ``view.zoom_reset`` (zoom only).
* ``panel.dock_left`` — dock a named panel to the left edge.
* ``panel.dock_right`` — dock a named panel to the right edge.
* ``theme.hot_swap`` — apply a named theme directly (distinct from
  ``theme.cycle`` / ``theme.random`` / ``theme.reload_all``).

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / camera / panel handles.
"""
from __future__ import annotations

import math
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
    r = ToolRouter()
    register_default_actions(r)
    return r


class _Entity:
    """3D-position entity."""

    def __init__(
        self,
        name: str,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        self.name = name
        self.position = list(position)


class _FakeCamera:
    """Minimal orbit-camera stand-in used by the view tests."""

    def __init__(self) -> None:
        self._cam_target = [0.0, 0.0, 0.0]
        self._cam_distance = 5.0
        self._cam_yaw = 0.0
        self._cam_pitch = 0.0
        self._cam_projection = "perspective"


class _PanelRect:
    """Placeholder for MovablePanel-style geometry state."""

    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.width = 100
        self.height = 100
        self._visible = True

    def is_visible(self) -> bool:
        return self._visible


class _LayoutEntry:
    def __init__(self) -> None:
        self.x = 0
        self.y = 0
        self.width = 100
        self.height = 100
        self.visible = True


# ---------------------------------------------------------------------------
# Registration (7 checks — mirrors the KK7 pattern)
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_frame_selected_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.frame_selected")

    def test_reset_view_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.reset_view")

    def test_dock_left_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.dock_left")

    def test_dock_right_registered(self, router: ToolRouter) -> None:
        assert router.has_action("panel.dock_right")

    def test_hot_swap_registered(self, router: ToolRouter) -> None:
        assert router.has_action("theme.hot_swap")

    def test_all_nn2_on_module_singleton(self) -> None:
        for aid in (
            "view.frame_selected",
            "view.reset_view",
            "panel.dock_left",
            "panel.dock_right",
            "theme.hot_swap",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_nn2_action_categories(self, router: ToolRouter) -> None:
        expected: dict[str, str] = {
            "view.frame_selected": "view",
            "view.reset_view": "view",
            "panel.dock_left": "panel",
            "panel.dock_right": "panel",
            "theme.hot_swap": "theme",
        }
        for aid, category in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == category, aid


# ---------------------------------------------------------------------------
# view.frame_selected
# ---------------------------------------------------------------------------


class TestFrameSelected:
    def test_frame_single_entity_centers_target(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        a = _Entity("a", position=(3.0, 4.0, 5.0))
        shell = SimpleNamespace(_viewport_panel=cam, _selected_entity=a)
        result = router.dispatch("view.frame_selected", {"shell": shell})
        assert result["status"] == "framed"
        assert result["count"] == 1
        assert cam._cam_target == pytest.approx([3.0, 4.0, 5.0])

    def test_frame_multi_entity_uses_aabb_center(
        self, router: ToolRouter,
    ) -> None:
        cam = _FakeCamera()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(10.0, 0.0, 0.0))
        shell = SimpleNamespace(_viewport_panel=cam, _selected_entities=[a, b])
        result = router.dispatch("view.frame_selected", {"shell": shell})
        assert result["status"] == "framed"
        assert cam._cam_target == pytest.approx([5.0, 0.0, 0.0])
        # AABB radius = 5, distance = 2 * r * margin = 2 * 5 * 1.15 = 11.5
        assert cam._cam_distance == pytest.approx(11.5)

    def test_frame_no_camera(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(1.0, 2.0, 3.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("view.frame_selected", {"shell": shell})
        assert result == {"status": "no_camera"}

    def test_frame_no_selection(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        shell = SimpleNamespace(_viewport_panel=cam)
        result = router.dispatch("view.frame_selected", {"shell": shell})
        assert result == {"status": "no_selection"}

    def test_frame_custom_margin(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(10.0, 0.0, 0.0))
        shell = SimpleNamespace(_viewport_panel=cam, _selected_entities=[a, b])
        result = router.dispatch(
            "view.frame_selected", {"shell": shell, "margin": 2.0},
        )
        # 2 * 5 * 2.0 = 20
        assert cam._cam_distance == pytest.approx(20.0)
        assert result["margin"] == pytest.approx(2.0)

    def test_frame_selection_override(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        shell = SimpleNamespace(_viewport_panel=cam)
        a = _Entity("a", position=(1.0, 2.0, 3.0))
        result = router.dispatch(
            "view.frame_selected",
            {"shell": shell, "selection": [a]},
        )
        assert result["status"] == "framed"
        assert cam._cam_target == pytest.approx([1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# view.reset_view
# ---------------------------------------------------------------------------


class TestResetView:
    def test_reset_restores_home_pose(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        cam._cam_target = [10.0, 20.0, 30.0]
        cam._cam_distance = 42.0
        cam._cam_yaw = 1.23
        cam._cam_pitch = -0.5
        shell = SimpleNamespace(_viewport_panel=cam)
        result = router.dispatch("view.reset_view", {"shell": shell})
        assert result["status"] == "reset"
        assert cam._cam_target == pytest.approx([0.0, 0.0, 0.0])
        assert cam._cam_distance == pytest.approx(5.0)
        assert cam._cam_yaw == pytest.approx(0.0)
        assert cam._cam_pitch == pytest.approx(0.0)

    def test_reset_no_camera(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("view.reset_view", {"shell": shell})
        assert result == {"status": "no_camera"}

    def test_reset_custom_target(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        shell = SimpleNamespace(_viewport_panel=cam)
        router.dispatch(
            "view.reset_view",
            {"shell": shell, "target": (1.0, 2.0, 3.0)},
        )
        assert cam._cam_target == pytest.approx([1.0, 2.0, 3.0])

    def test_reset_custom_distance_clamped(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        shell = SimpleNamespace(_viewport_panel=cam)
        router.dispatch(
            "view.reset_view", {"shell": shell, "distance": 99999.0},
        )
        # Clamped to _MAX_DISTANCE = 10000.
        assert cam._cam_distance == pytest.approx(10000.0)

    def test_reset_projection_written(self, router: ToolRouter) -> None:
        cam = _FakeCamera()
        cam._cam_projection = "ortho"
        shell = SimpleNamespace(_viewport_panel=cam)
        result = router.dispatch("view.reset_view", {"shell": shell})
        assert cam._cam_projection == "perspective"
        assert result["projection"] == "perspective"


# ---------------------------------------------------------------------------
# panel.dock_left + panel.dock_right
# ---------------------------------------------------------------------------


def _make_shell_with_panels(*ids: str) -> SimpleNamespace:
    windows = {name: _PanelRect() for name in ids}
    state = {name: _LayoutEntry() for name in ids}
    return SimpleNamespace(
        _panel_windows=windows,
        _panel_layout_state=state,
        _viewport_size=(1280, 720),
    )


class TestDockLeft:
    def test_dock_left_writes_rect(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("outliner")
        result = router.dispatch(
            "panel.dock_left",
            {"shell": shell, "panel_id": "outliner"},
        )
        assert result["status"] == "docked"
        assert result["side"] == "left"
        # Default ratio 0.25 * 1280 = 320.
        assert result["rect"] == (0, 0, 320, 720)
        assert shell._panel_windows["outliner"].x == 0
        assert shell._panel_windows["outliner"].width == 320

    def test_dock_left_no_shell(self, router: ToolRouter) -> None:
        result = router.dispatch("panel.dock_left", {"panel_id": "outliner"})
        assert result == {"status": "no_shell"}

    def test_dock_left_no_panel_id(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("outliner")
        result = router.dispatch("panel.dock_left", {"shell": shell})
        assert result == {"status": "no_panel_id"}

    def test_dock_left_unknown_panel(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("outliner")
        result = router.dispatch(
            "panel.dock_left",
            {"shell": shell, "panel_id": "ghost"},
        )
        assert result["status"] == "unknown_panel"
        assert result["panel_id"] == "ghost"

    def test_dock_left_absolute_width(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("inspector")
        result = router.dispatch(
            "panel.dock_left",
            {"shell": shell, "panel_id": "inspector", "width_px": 400},
        )
        assert result["rect"] == (0, 0, 400, 720)


class TestDockRight:
    def test_dock_right_writes_rect(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("inspector")
        result = router.dispatch(
            "panel.dock_right",
            {"shell": shell, "panel_id": "inspector"},
        )
        assert result["status"] == "docked"
        assert result["side"] == "right"
        # 1280 - 320 = 960, dock_w = 320, height = 720.
        assert result["rect"] == (960, 0, 320, 720)
        assert shell._panel_windows["inspector"].x == 960

    def test_dock_right_records_last_side(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("outliner")
        router.dispatch(
            "panel.dock_right",
            {"shell": shell, "panel_id": "outliner"},
        )
        assert shell._last_dock_side == "right"
        assert shell._last_docked_panel == "outliner"

    def test_dock_right_viewport_override(self, router: ToolRouter) -> None:
        shell = _make_shell_with_panels("outliner")
        result = router.dispatch(
            "panel.dock_right",
            {
                "shell": shell,
                "panel_id": "outliner",
                "viewport_size": (2000, 1000),
                "width_ratio": 0.20,
            },
        )
        # 2000 * 0.20 = 400 wide; x = 1600.
        assert result["rect"] == (1600, 0, 400, 1000)


# ---------------------------------------------------------------------------
# theme.hot_swap
# ---------------------------------------------------------------------------


class TestThemeHotSwap:
    def test_hot_swap_no_theme(self, router: ToolRouter) -> None:
        result = router.dispatch("theme.hot_swap", {})
        assert result == {"status": "no_theme"}

    def test_hot_swap_unknown_theme(self, router: ToolRouter) -> None:
        # A name guaranteed not to exist. We accept either
        # "unknown_theme" (registry loaded fine) or "error" (registry
        # module import failed on the CI env) — either signals a safe
        # non-swap.
        result = router.dispatch(
            "theme.hot_swap", {"theme": "__nn2_definitely_not_a_theme__"},
        )
        assert result["status"] in {"unknown_theme", "error"}
        if result["status"] == "unknown_theme":
            assert result["theme"] == "__nn2_definitely_not_a_theme__"
            assert isinstance(result["available"], list)

    def test_hot_swap_known_theme(
        self, router: ToolRouter, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Inject a fake theme so the test doesn't depend on the shell
        # having pre-baked its default roster.
        try:
            import pharos_engine.ui.theme as theme_mod
        except Exception:  # noqa: BLE001
            pytest.skip("pharos_engine.ui.theme not importable in this env")
        applied: list[str] = []
        target = "__nn2_stub_theme_ok__"
        monkeypatch.setattr(
            theme_mod, "list_registered_themes", lambda: [target],
        )
        monkeypatch.setattr(
            theme_mod, "apply_theme", lambda name: applied.append(name),
        )
        shell = SimpleNamespace()
        result = router.dispatch(
            "theme.hot_swap", {"shell": shell, "theme": target},
        )
        assert result["status"] == "swapped"
        assert result["theme"] == target
        assert getattr(shell, "_active_theme", None) == target
        # Path is either "theme_module" (module apply_theme fired) or
        # "shell" (fake shell has no apply_theme, so module fallback wins).
        assert result["path"] in {"theme_module", "shell"}

    def test_hot_swap_non_string_theme_is_no_theme(
        self, router: ToolRouter,
    ) -> None:
        # A non-string ``theme`` key is treated as "no theme" rather than
        # raising — matches how the other action modules coerce input.
        result = router.dispatch("theme.hot_swap", {"theme": 12345})
        assert result == {"status": "no_theme"}
        result = router.dispatch("theme.hot_swap", {"theme": "   "})
        assert result == {"status": "no_theme"}

    def test_hot_swap_shell_apply_theme_hook(
        self, router: ToolRouter, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A shell that intercepts apply_theme wins over the module fallback.
        try:
            import pharos_engine.ui.theme as theme_mod
        except Exception:  # noqa: BLE001
            pytest.skip("pharos_engine.ui.theme not importable in this env")
        target = "__nn2_stub_theme_hook__"
        monkeypatch.setattr(
            theme_mod, "list_registered_themes", lambda: [target],
        )

        applied: list[str] = []

        class _Shell:
            def apply_theme(self, name: str) -> None:
                applied.append(name)

        shell = _Shell()
        result = router.dispatch(
            "theme.hot_swap", {"shell": shell, "theme": target},
        )
        assert result["status"] == "swapped"
        assert applied == [target]
        assert result["path"] == "shell"
