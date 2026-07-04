"""Z7 STUB-triage tests — third round of feature-map wiring.

Covers the five new action ids added by the 2026-07-04 Z7 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"Z7 STUB-triage patch"):

* ``tool.snap_to_grid`` — toggle the ``SnapManager.config.enable_grid``
  runtime flag (with a headless fallback for tests + notebook mode).
* ``view.zoom_in`` — divide the viewport-camera distance by
  ``ctx["step"]`` (default 1.2) with per-attribute clamping.
* ``view.zoom_out`` — mirror of ``view.zoom_in``; multiplies distance.
* ``view.zoom_reset`` — restore ``_cam_distance`` to the ViewportPanel
  ctor default (5.0), or ``_zoom_level`` to 1.0 for 2D shells.
* ``theme.export_current`` — write the active :class:`ThemeSpec` to a
  ctx-provided YAML path (or via the shell's ``prompt_save_path`` hook).

Every test dispatches through :class:`~slappyengine.tool_router.ToolRouter`
so the wire-up (``action_id`` → Python fallback) is exercised end-to-end.
No DPG context is required — everything routes through ``SimpleNamespace``
mocks so the suite is headless.
"""
from __future__ import annotations

from pathlib import Path
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
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture(autouse=True)
def _reset_snap_grid_and_registry() -> None:
    """Reset the module-level snap-grid flag before each test."""
    from slappyengine.actions.tool_settings_actions import (
        _reset_snap_grid_for_tests,
    )
    _reset_snap_grid_for_tests()


def _make_snap_manager() -> Any:
    """Return a bare object matching SnapManager's ``.config.enable_grid`` shape."""
    return SimpleNamespace(
        config=SimpleNamespace(enable_grid=False),
    )


def _make_camera(distance: float = 5.0) -> Any:
    """Return a bare 3D camera object with ``_cam_distance`` only."""
    return SimpleNamespace(_cam_distance=distance)


def _make_2d_camera(zoom: float = 1.0) -> Any:
    """Return a bare 2D camera object with ``_zoom_level`` only."""
    return SimpleNamespace(_zoom_level=zoom)


class _FakeTheme:
    """Minimal ThemeSpec stand-in exposing ``name`` and ``to_yaml``."""

    def __init__(self, name: str = "z7_theme", payload: str | None = None) -> None:
        self.name = name
        self._payload = payload or f"@theme {name} {{ }}\n"

    def to_yaml(self) -> str:
        return self._payload


# ---------------------------------------------------------------------------
# 1. Every Z7 action is registered on the router + module REGISTRY
# ---------------------------------------------------------------------------


def test_snap_to_grid_registered(router: ToolRouter) -> None:
    assert router.has_action("tool.snap_to_grid")


def test_zoom_in_registered(router: ToolRouter) -> None:
    assert router.has_action("view.zoom_in")


def test_zoom_out_registered(router: ToolRouter) -> None:
    assert router.has_action("view.zoom_out")


def test_zoom_reset_registered(router: ToolRouter) -> None:
    assert router.has_action("view.zoom_reset")


def test_export_current_theme_registered(router: ToolRouter) -> None:
    assert router.has_action("theme.export_current")


def test_module_registry_has_z7_actions() -> None:
    """The default REGISTRY must expose the new Z7 action ids."""
    ids = {a.action_id for a in REGISTRY.list_actions()}
    for aid in (
        "tool.snap_to_grid",
        "view.zoom_in",
        "view.zoom_out",
        "view.zoom_reset",
        "theme.export_current",
    ):
        assert aid in ids, f"{aid} missing from module-level REGISTRY"


def test_z7_actions_have_expected_categories() -> None:
    """Ensure the new ids landed in the right category buckets."""
    lookup = {a.action_id: a for a in REGISTRY.list_actions()}
    assert lookup["tool.snap_to_grid"].category == "tool"
    assert lookup["view.zoom_in"].category == "view"
    assert lookup["view.zoom_out"].category == "view"
    assert lookup["view.zoom_reset"].category == "view"
    assert lookup["theme.export_current"].category == "theme"


# ---------------------------------------------------------------------------
# 2. tool.snap_to_grid — toggles SnapManager.config.enable_grid
# ---------------------------------------------------------------------------


def test_snap_to_grid_headless_toggle(router: ToolRouter) -> None:
    """With no shell/manager reachable the fallback flag flips."""
    r1 = router.dispatch("tool.snap_to_grid", {})
    r2 = router.dispatch("tool.snap_to_grid", {})
    r3 = router.dispatch("tool.snap_to_grid", {})
    assert r1 == {"status": "toggled", "enabled": True, "path": "fallback"}
    assert r2 == {"status": "toggled", "enabled": False, "path": "fallback"}
    assert r3 == {"status": "toggled", "enabled": True, "path": "fallback"}


def test_snap_to_grid_shell_snap_manager_mutation(router: ToolRouter) -> None:
    """When ``shell._snap_manager`` is present the config field is toggled."""
    manager = _make_snap_manager()
    shell = SimpleNamespace(_snap_manager=manager)
    result = router.dispatch("tool.snap_to_grid", {"shell": shell})
    assert result["status"] == "toggled"
    assert result["enabled"] is True
    assert result["path"] == "shell"
    assert manager.config.enable_grid is True
    # Mirror flag on the shell for status-bar readouts.
    assert shell._snap_grid_enabled is True


def test_snap_to_grid_force_true(router: ToolRouter) -> None:
    """``force=True`` locks the flag ON regardless of current state."""
    manager = _make_snap_manager()
    manager.config.enable_grid = True
    shell = SimpleNamespace(_snap_manager=manager)
    result = router.dispatch(
        "tool.snap_to_grid", {"shell": shell, "force": True},
    )
    # Already True; force True keeps it True.
    assert result["enabled"] is True
    assert manager.config.enable_grid is True


def test_snap_to_grid_force_false(router: ToolRouter) -> None:
    """``force=False`` locks the flag OFF regardless of current state."""
    manager = _make_snap_manager()
    manager.config.enable_grid = True
    shell = SimpleNamespace(_snap_manager=manager)
    result = router.dispatch(
        "tool.snap_to_grid", {"shell": shell, "force": False},
    )
    assert result["enabled"] is False
    assert manager.config.enable_grid is False


def test_snap_to_grid_returns_new_state_string() -> None:
    """Direct import of the fallback returns the same dict shape."""
    from slappyengine.actions.tool_settings_actions import (
        toggle_snap_to_grid,
    )
    r = toggle_snap_to_grid({})
    assert set(r.keys()) == {"status", "enabled", "path"}
    assert isinstance(r["enabled"], bool)


# ---------------------------------------------------------------------------
# 3. view.zoom_in / view.zoom_out — 3D distance mutation
# ---------------------------------------------------------------------------


def test_zoom_in_no_camera_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("view.zoom_in", {})
    assert result == {"status": "no_camera"}


def test_zoom_out_no_camera_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("view.zoom_out", {})
    assert result == {"status": "no_camera"}


def test_zoom_in_reduces_cam_distance(router: ToolRouter) -> None:
    camera = _make_camera(distance=5.0)
    result = router.dispatch("view.zoom_in", {"camera": camera})
    assert result["status"] == "zoomed"
    assert result["distance"] == pytest.approx(5.0 / 1.2, rel=1e-6)
    assert camera._cam_distance == pytest.approx(5.0 / 1.2, rel=1e-6)
    # Delta should be negative (zoomed in => distance shrank).
    assert result["delta"] < 0


def test_zoom_out_increases_cam_distance(router: ToolRouter) -> None:
    camera = _make_camera(distance=5.0)
    result = router.dispatch("view.zoom_out", {"camera": camera})
    assert result["status"] == "zoomed"
    assert result["distance"] == pytest.approx(5.0 * 1.2, rel=1e-6)
    assert camera._cam_distance == pytest.approx(5.0 * 1.2, rel=1e-6)
    assert result["delta"] > 0


def test_zoom_in_shell_viewport_panel(router: ToolRouter) -> None:
    """A shell with ``_viewport_panel`` is treated as the camera source."""
    panel = _make_camera(distance=8.0)
    shell = SimpleNamespace(_viewport_panel=panel)
    result = router.dispatch("view.zoom_in", {"shell": shell})
    assert result["status"] == "zoomed"
    assert result["path"] == "shell"
    assert panel._cam_distance == pytest.approx(8.0 / 1.2, rel=1e-6)


def test_zoom_in_custom_step(router: ToolRouter) -> None:
    """The ``step`` override changes the multiplicative factor."""
    camera = _make_camera(distance=10.0)
    result = router.dispatch(
        "view.zoom_in", {"camera": camera, "step": 2.0},
    )
    assert result["distance"] == pytest.approx(5.0, rel=1e-6)
    assert camera._cam_distance == pytest.approx(5.0, rel=1e-6)


def test_zoom_in_clamps_to_min_distance(router: ToolRouter) -> None:
    """Repeated zoom-in must clamp at the lower bound (0.05)."""
    camera = _make_camera(distance=0.1)
    # Big step so we blow past the floor in one call.
    router.dispatch("view.zoom_in", {"camera": camera, "step": 1e6})
    assert camera._cam_distance == pytest.approx(0.05, abs=1e-9)


def test_zoom_out_clamps_to_max_distance(router: ToolRouter) -> None:
    """Repeated zoom-out must clamp at the upper bound (10000)."""
    camera = _make_camera(distance=1000.0)
    router.dispatch("view.zoom_out", {"camera": camera, "step": 1e6})
    assert camera._cam_distance == pytest.approx(10000.0, abs=1e-6)


def test_zoom_in_on_2d_camera(router: ToolRouter) -> None:
    """A 2D camera surface uses ``_zoom_level`` and zooms *in* by *multiplying*."""
    camera = _make_2d_camera(zoom=1.0)
    result = router.dispatch("view.zoom_in", {"camera": camera})
    # 2D zoom-in => zoom_level grows (things look bigger).
    assert result["distance"] == pytest.approx(1.2, rel=1e-6)
    assert camera._zoom_level == pytest.approx(1.2, rel=1e-6)


def test_zoom_out_on_2d_camera(router: ToolRouter) -> None:
    """2D camera zoom-out shrinks the zoom_level."""
    camera = _make_2d_camera(zoom=1.2)
    result = router.dispatch("view.zoom_out", {"camera": camera})
    assert result["distance"] == pytest.approx(1.0, rel=1e-6)
    assert camera._zoom_level == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 4. view.zoom_reset — restore default zoom level
# ---------------------------------------------------------------------------


def test_zoom_reset_no_camera_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("view.zoom_reset", {})
    assert result == {"status": "no_camera"}


def test_zoom_reset_restores_default_cam_distance(router: ToolRouter) -> None:
    """Reset always writes back the ViewportPanel default (5.0)."""
    camera = _make_camera(distance=17.3)
    result = router.dispatch("view.zoom_reset", {"camera": camera})
    assert result["status"] == "reset"
    assert result["distance"] == pytest.approx(5.0, rel=1e-6)
    assert result["previous"] == pytest.approx(17.3, rel=1e-6)
    assert camera._cam_distance == pytest.approx(5.0, rel=1e-6)


def test_zoom_reset_accepts_distance_override(router: ToolRouter) -> None:
    """``ctx["distance"]`` lets callers reset to a bounding-box-aware value."""
    camera = _make_camera(distance=100.0)
    result = router.dispatch(
        "view.zoom_reset", {"camera": camera, "distance": 12.5},
    )
    assert result["distance"] == pytest.approx(12.5, rel=1e-6)
    assert camera._cam_distance == pytest.approx(12.5, rel=1e-6)


def test_zoom_reset_on_2d_camera(router: ToolRouter) -> None:
    """2D reset writes ``_zoom_level`` back to 1.0."""
    camera = _make_2d_camera(zoom=3.5)
    result = router.dispatch("view.zoom_reset", {"camera": camera})
    assert result["distance"] == pytest.approx(1.0, rel=1e-6)
    assert camera._zoom_level == pytest.approx(1.0, rel=1e-6)


# ---------------------------------------------------------------------------
# 5. theme.export_current — YAML round-trip
# ---------------------------------------------------------------------------


def test_export_current_theme_no_theme_returns_status(router: ToolRouter) -> None:
    """With no active theme and no override, the fallback bails cleanly."""
    # Force the "no active theme" path by resetting the theme registry
    # before dispatch.
    from slappyengine.ui.theme import _reset_registry_for_tests
    _reset_registry_for_tests()
    result = router.dispatch("theme.export_current", {})
    assert result == {"status": "no_theme"}


def test_export_current_theme_no_path_returns_status(
    router: ToolRouter,
) -> None:
    """A supplied theme without a path override or prompt hook bails."""
    theme = _FakeTheme(name="pathless")
    result = router.dispatch("theme.export_current", {"theme": theme})
    assert result == {"status": "no_path"}


def test_export_current_theme_writes_yaml(
    router: ToolRouter, tmp_path: Path,
) -> None:
    """The happy path writes the YAML payload to ``ctx["path"]``."""
    theme = _FakeTheme(name="written_theme", payload="@theme written {}\n")
    dest = tmp_path / "custom.theme.yaml"
    result = router.dispatch(
        "theme.export_current",
        {"theme": theme, "path": str(dest)},
    )
    assert result["status"] == "exported"
    assert result["theme"] == "written_theme"
    assert result["path"] == str(dest)
    assert result["size_bytes"] == len("@theme written {}\n".encode("utf-8"))
    assert dest.read_text(encoding="utf-8") == "@theme written {}\n"


def test_export_current_theme_uses_shell_prompt(
    router: ToolRouter, tmp_path: Path,
) -> None:
    """A shell exposing ``prompt_save_path`` is invoked for the destination."""
    theme = _FakeTheme(name="prompt_theme")
    dest = tmp_path / "prompted.theme.yaml"
    prompt_calls: list[str] = []

    def prompt(default_name: str) -> str:
        prompt_calls.append(default_name)
        return str(dest)

    shell = SimpleNamespace(prompt_save_path=prompt)
    result = router.dispatch(
        "theme.export_current", {"theme": theme, "shell": shell},
    )
    assert result["status"] == "exported"
    assert prompt_calls == ["prompt_theme.theme.yaml"]
    assert dest.exists()


def test_export_current_theme_prompt_cancelled(router: ToolRouter) -> None:
    """A ``prompt_save_path`` returning empty string is a user cancel."""
    theme = _FakeTheme(name="cancelled")
    shell = SimpleNamespace(prompt_save_path=lambda default: "")
    result = router.dispatch(
        "theme.export_current", {"theme": theme, "shell": shell},
    )
    assert result == {"status": "no_path"}


def test_export_current_theme_bad_to_yaml_returns_error(
    router: ToolRouter, tmp_path: Path,
) -> None:
    """A theme whose ``to_yaml`` blows up surfaces via the error status."""

    class BrokenTheme:
        name = "broken"

        def to_yaml(self) -> str:
            raise RuntimeError("yaml serializer down")

    result = router.dispatch(
        "theme.export_current",
        {"theme": BrokenTheme(), "path": str(tmp_path / "broken.yaml")},
    )
    assert result["status"] == "error"


def test_export_current_theme_from_active_registry(
    router: ToolRouter, tmp_path: Path,
) -> None:
    """When no ``theme`` override is passed, the active registry is queried."""
    from slappyengine.ui.theme import (
        _reset_registry_for_tests,
        apply_theme,
    )
    try:
        from slappyengine.ui.theme.themes import (
            TEENGIRL_NOTEBOOK,
            register_all_themes,
        )
    except Exception:  # noqa: BLE001
        pytest.skip("built-in themes not importable")

    _reset_registry_for_tests()
    register_all_themes()
    apply_theme(TEENGIRL_NOTEBOOK.name)

    dest = tmp_path / "active.theme.yaml"
    result = router.dispatch(
        "theme.export_current", {"path": str(dest)},
    )
    if result.get("status") == "error" and "PyYAML" in result.get(
        "message", "",
    ):
        pytest.skip("PyYAML not available")
    assert result["status"] == "exported"
    assert result["theme"] == TEENGIRL_NOTEBOOK.name
    assert dest.exists()


# ---------------------------------------------------------------------------
# 6. Direct-import smoke tests — bypass ToolRouter
# ---------------------------------------------------------------------------


def test_direct_import_toggle_snap_to_grid() -> None:
    """Every new helper is importable from ``slappyengine.actions``."""
    from slappyengine.actions import toggle_snap_to_grid
    r = toggle_snap_to_grid({})
    assert r["status"] == "toggled"


def test_direct_import_zoom_in_out_reset() -> None:
    from slappyengine.actions import zoom_in, zoom_out, zoom_reset
    camera = _make_camera(distance=5.0)
    assert zoom_in({"camera": camera})["status"] == "zoomed"
    assert zoom_out({"camera": camera})["status"] == "zoomed"
    assert zoom_reset({"camera": camera})["status"] == "reset"


def test_direct_import_export_current_theme(tmp_path: Path) -> None:
    from slappyengine.actions import export_current_theme
    theme = _FakeTheme(name="direct_import")
    dest = tmp_path / "direct.theme.yaml"
    result = export_current_theme({"theme": theme, "path": str(dest)})
    assert result["status"] == "exported"
    assert dest.exists()
