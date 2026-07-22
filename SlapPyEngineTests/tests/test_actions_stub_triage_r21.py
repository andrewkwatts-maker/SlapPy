"""TT2 STUB-triage tests — round 21 of feature-map wiring.

Covers the five new action ids added by the TT2 sprint tick (round 21
after SS1's round-20 ``content.reveal_in_explorer`` /
``content.duplicate_folder`` / ``view.increase_pixel_scale`` /
``view.decrease_pixel_scale`` / ``spawn.stamp_repeat`` batch):

* ``view.set_zoom`` — jump the viewport camera to an *absolute* zoom
  distance (distinct from Z7's ``view.zoom_in`` / ``view.zoom_out``
  which walk by a multiplicative step + Z7's ``view.zoom_reset`` which
  snaps to a hard-coded default; distinct from SS1's
  ``view.increase_pixel_scale`` / ``view.decrease_pixel_scale`` which
  step an integer framebuffer scale).
* ``spawn.at_view_center`` — arm the next spawn at the viewport's
  focal point (distinct from EE1's ``spawn.spawn_at_cursor`` at the
  mouse position + QQ1's ``spawn.at_origin`` at world zero).
* ``spawn.stamp_random`` — hold-and-stamp N copies where each copy's
  card+spec is drawn uniformly from the shell's stamp history palette
  (distinct from SS1's deterministic ``spawn.stamp_repeat``).
* ``theme.reload_from_disk`` — targeted single-theme hot-reload
  (distinct from FF1's ``theme.reload_all`` which flushes the whole
  registry + RR1's ``theme.reset_to_default`` which never touches
  disk).
* ``layer.rename`` — rename a Z-layer without mutating entities
  (distinct from PP1's ``edit.rename`` which renames entities + FF1's
  ``content.rename_asset`` which renames files on disk).

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up is exercised end-to-end. No DPG context — fixtures use
:class:`SimpleNamespace` stand-ins for shell / viewport handles.
"""
from __future__ import annotations

from pathlib import Path
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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_view_set_zoom_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.set_zoom")

    def test_spawn_at_view_center_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.at_view_center")

    def test_spawn_stamp_random_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("spawn.stamp_random")

    def test_theme_reload_from_disk_registered(
        self, router: ToolRouter,
    ) -> None:
        assert router.has_action("theme.reload_from_disk")

    def test_layer_rename_registered(self, router: ToolRouter) -> None:
        assert router.has_action("layer.rename")

    def test_all_tt2_on_module_singleton(self) -> None:
        for aid in (
            "view.set_zoom",
            "spawn.at_view_center",
            "spawn.stamp_random",
            "theme.reload_from_disk",
            "layer.rename",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_tt2_categories(self, router: ToolRouter) -> None:
        expected = {
            "view.set_zoom": "view",
            "spawn.at_view_center": "spawn",
            "spawn.stamp_random": "spawn",
            "theme.reload_from_disk": "theme",
            "layer.rename": "layer",
        }
        for aid, cat in expected.items():
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == cat, aid


# ---------------------------------------------------------------------------
# view.set_zoom
# ---------------------------------------------------------------------------


class TestViewSetZoom:
    def test_missing_distance(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_cam_distance=5.0)
        result = router.dispatch(
            "view.set_zoom", {"camera": camera},
        )
        assert result == {"status": "missing_distance"}

    def test_non_finite_distance(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_cam_distance=5.0)
        result = router.dispatch(
            "view.set_zoom",
            {"camera": camera, "distance": float("inf")},
        )
        assert result == {"status": "missing_distance"}

    def test_no_camera(self, router: ToolRouter) -> None:
        result = router.dispatch("view.set_zoom", {"distance": 12.0})
        assert result == {"status": "no_camera"}

    def test_set_3d_distance(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_cam_distance=5.0)
        result = router.dispatch(
            "view.set_zoom", {"camera": camera, "distance": 12.0},
        )
        assert result["status"] == "set"
        assert result["distance"] == 12.0
        assert result["previous"] == 5.0
        assert camera._cam_distance == 12.0

    def test_set_2d_zoom_level(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_zoom_level=1.0)
        result = router.dispatch(
            "view.set_zoom", {"camera": camera, "distance": 2.5},
        )
        assert result["status"] == "set"
        assert result["distance"] == 2.5
        assert camera._zoom_level == 2.5

    def test_clamps_max(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_cam_distance=5.0)
        result = router.dispatch(
            "view.set_zoom",
            {"camera": camera, "distance": 999999.0},
        )
        # clamp is 10000 for _cam_distance
        assert result["distance"] == 10000.0

    def test_clamps_min(self, router: ToolRouter) -> None:
        camera = SimpleNamespace(_cam_distance=5.0)
        result = router.dispatch(
            "view.set_zoom",
            {"camera": camera, "distance": 0.0},
        )
        assert result["distance"] == 0.05

    def test_via_shell_viewport_panel(self, router: ToolRouter) -> None:
        panel = SimpleNamespace(_cam_distance=5.0)
        shell = SimpleNamespace(_viewport_panel=panel)
        result = router.dispatch(
            "view.set_zoom", {"shell": shell, "distance": 3.0},
        )
        assert result["status"] == "set"
        assert result["path"] == "shell"
        assert panel._cam_distance == 3.0


# ---------------------------------------------------------------------------
# spawn.at_view_center
# ---------------------------------------------------------------------------


class TestSpawnAtViewCenter:
    def test_no_shell_no_override(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.at_view_center", {})
        assert result == {"status": "no_shell"}

    def test_arm_with_explicit_center(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_view_center",
            {"shell": shell, "view_center": [2.0, 3.0, 4.0]},
        )
        assert result["status"] == "armed"
        assert result["position"] == (2.0, 3.0, 4.0)
        assert shell._pending_spawn_position == [2.0, 3.0, 4.0]

    def test_arm_via_viewport_panel_target(
        self, router: ToolRouter,
    ) -> None:
        panel = SimpleNamespace(_cam_target=[1.0, 2.0, 0.0])
        shell = SimpleNamespace(_viewport_panel=panel)
        result = router.dispatch(
            "spawn.at_view_center", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["position"] == (1.0, 2.0, 0.0)

    def test_arm_falls_back_to_origin(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_view_center", {"shell": shell},
        )
        assert result["status"] == "armed"
        assert result["position"] == (0.0, 0.0, 0.0)

    def test_arm_via_getter(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            get_view_center_world_position=lambda: [7.0, 8.0, 9.0],
        )
        result = router.dispatch(
            "spawn.at_view_center", {"shell": shell},
        )
        assert result["position"] == (7.0, 8.0, 9.0)

    def test_repeat_with_history(self, router: ToolRouter) -> None:
        landed: list[tuple[str, dict]] = []
        shell = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed.append((cid, spec)),
        )
        template = {"position": [0.0, 0.0, 0.0]}
        result = router.dispatch(
            "spawn.at_view_center",
            {
                "shell": shell,
                "view_center": [4.0, 5.0, 6.0],
                "mode": "repeat",
                "last_spawn": ("rope", template),
            },
        )
        assert result["status"] == "respawned"
        assert result["card_id"] == "rope"
        assert result["position"] == (4.0, 5.0, 6.0)
        assert landed[0][1]["position"] == [4.0, 5.0, 6.0]

    def test_repeat_without_history_falls_back_to_arm(
        self, router: ToolRouter,
    ) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.at_view_center",
            {"shell": shell, "mode": "repeat"},
        )
        assert result["status"] == "armed"


# ---------------------------------------------------------------------------
# spawn.stamp_random
# ---------------------------------------------------------------------------


class TestSpawnStampRandom:
    def test_no_shell_no_palette(self, router: ToolRouter) -> None:
        result = router.dispatch("spawn.stamp_random", {})
        assert result == {"status": "no_shell"}

    def test_no_history_with_shell(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch(
            "spawn.stamp_random", {"shell": shell},
        )
        assert result == {"status": "no_history"}

    def test_zero_count(self, router: ToolRouter) -> None:
        shell = SimpleNamespace(
            _last_spawn=("rope", {"position": [0.0, 0.0, 0.0]}),
        )
        result = router.dispatch(
            "spawn.stamp_random", {"shell": shell, "count": 0},
        )
        assert result == {"status": "no_history"}

    def test_stamps_from_palette(self, router: ToolRouter) -> None:
        landed: list[tuple[str, dict]] = []
        shell = SimpleNamespace(
            _on_spawn=lambda cid, spec: landed.append((cid, spec)),
        )
        palette = [
            ("rope", {"position": [0.0, 0.0, 0.0]}),
            ("humanoid", {"position": [0.0, 0.0, 0.0]}),
        ]
        result = router.dispatch(
            "spawn.stamp_random",
            {
                "shell": shell,
                "palette": palette,
                "count": 4,
                "stride": (1.0, 0.0, 0.0),
                "seed": 42,
            },
        )
        assert result["status"] == "stamped"
        assert result["count"] == 4
        assert result["stride"] == (1.0, 0.0, 0.0)
        assert len(landed) == 4
        # every landed cid must be one from the palette
        for cid, _ in landed:
            assert cid in ("rope", "humanoid")

    def test_seed_deterministic(self, router: ToolRouter) -> None:
        palette = [
            ("rope", {"position": [0.0, 0.0, 0.0]}),
            ("humanoid", {"position": [0.0, 0.0, 0.0]}),
            ("ragdoll", {"position": [0.0, 0.0, 0.0]}),
        ]
        r1 = router.dispatch(
            "spawn.stamp_random",
            {
                "palette": palette,
                "count": 5,
                "stride": (1.0, 0.0, 0.0),
                "seed": 7,
            },
        )
        r2 = router.dispatch(
            "spawn.stamp_random",
            {
                "palette": palette,
                "count": 5,
                "stride": (1.0, 0.0, 0.0),
                "seed": 7,
            },
        )
        assert r1["picks"] == r2["picks"]

    def test_pulls_from_stamp_history(self, router: ToolRouter) -> None:
        history = [
            {
                "card_id": "humanoid",
                "count": 2,
                "specs": [
                    {"position": [0.0, 0.0, 0.0]},
                    {"position": [1.0, 0.0, 0.0]},
                ],
            },
        ]
        shell = SimpleNamespace(_stamp_history=history)
        result = router.dispatch(
            "spawn.stamp_random",
            {"shell": shell, "count": 3, "seed": 3},
        )
        assert result["status"] == "stamped"
        for cid, _ in result["picks"]:
            assert cid == "humanoid"

    def test_stride_applied(self, router: ToolRouter) -> None:
        palette = [("rope", {"position": [0.0, 0.0, 0.0]})]
        result = router.dispatch(
            "spawn.stamp_random",
            {
                "palette": palette,
                "count": 3,
                "stride": (2.0, 0.0, 0.0),
                "seed": 1,
            },
        )
        xs = [spec["position"][0] for _, spec in result["picks"]]
        assert xs == [0.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# theme.reload_from_disk
# ---------------------------------------------------------------------------


class TestThemeReloadFromDisk:
    def test_no_path(self, router: ToolRouter) -> None:
        result = router.dispatch("theme.reload_from_disk", {})
        assert result == {"status": "no_path"}

    def test_missing_file(self, router: ToolRouter, tmp_path: Path) -> None:
        stale = tmp_path / "ghost.theme.yaml"
        result = router.dispatch(
            "theme.reload_from_disk", {"path": str(stale)},
        )
        assert result["status"] == "missing"
        assert result["path"] == str(stale)

    def test_reloads_yaml_and_registers(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        pytest.importorskip("pharos_engine.ui.theme")
        from pharos_engine.ui.theme import (
            ThemeSpec,
            list_registered_themes,
        )
        themes = list_registered_themes()
        if not themes:
            pytest.skip("no themes registered — DPG-less env")
        # Round-trip the first registered theme to YAML then reload it.
        try:
            first = ThemeSpec.get_registered(themes[0])
        except Exception:
            pytest.skip("registry.get_registered unavailable")
        try:
            yaml_text = first.to_yaml()
        except Exception:
            pytest.skip("ThemeSpec.to_yaml unsupported")
        target = tmp_path / f"{first.name}.theme.yaml"
        target.write_text(yaml_text, encoding="utf-8")
        result = router.dispatch(
            "theme.reload_from_disk", {"path": str(target)},
        )
        assert result["status"] in {"reloaded", "error"}
        if result["status"] == "reloaded":
            assert result["theme"] == first.name
            assert result["path"] == str(target)

    def test_theme_name_lookup_via_shell(
        self, router: ToolRouter, tmp_path: Path,
    ) -> None:
        stale = tmp_path / "wanted.theme.yaml"
        shell = SimpleNamespace(_theme_paths={"wanted": str(stale)})
        result = router.dispatch(
            "theme.reload_from_disk",
            {"shell": shell, "theme_name": "wanted"},
        )
        # Path resolved via shell._theme_paths but file doesn't exist.
        assert result["status"] == "missing"
        assert result["path"] == str(stale)


# ---------------------------------------------------------------------------
# layer.rename
# ---------------------------------------------------------------------------


def _make_scene(layer_names: list[str]) -> SimpleNamespace:
    layers = [SimpleNamespace(name=n, visible=True) for n in layer_names]
    return SimpleNamespace(z_layers=layers)


class TestLayerRename:
    def test_missing_name(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {"scene": scene, "layer": scene.z_layers[0]},
        )
        assert result == {"status": "missing_name"}

    def test_invalid_name_slash(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer": scene.z_layers[0],
                "new_name": "a/b",
            },
        )
        assert result["status"] == "invalid_name"
        assert result["name"] == "a/b"

    def test_invalid_name_whitespace(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer": scene.z_layers[0],
                "new_name": "   ",
            },
        )
        assert result["status"] == "invalid_name"

    def test_no_scene(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "layer.rename", {"new_name": "abc"},
        )
        assert result == {"status": "no_scene"}

    def test_no_layer(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {"scene": scene, "new_name": "abc"},
        )
        assert result == {"status": "no_layer"}

    def test_no_layers(self, router: ToolRouter) -> None:
        scene = SimpleNamespace(z_layers=[])
        result = router.dispatch(
            "layer.rename",
            {"scene": scene, "new_name": "abc"},
        )
        assert result == {"status": "no_layers"}

    def test_renames(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer": scene.z_layers[0],
                "new_name": "sky",
            },
        )
        assert result["status"] == "renamed"
        assert result["target"] == "bg"
        assert result["new"] == "sky"
        assert result["collided"] is False
        assert scene.z_layers[0].name == "sky"

    def test_rename_collision_uniquifies(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer": scene.z_layers[0],
                "new_name": "fg",
            },
        )
        assert result["status"] == "renamed"
        assert result["new"] == "fg_2"
        assert result["collided"] is True
        assert scene.z_layers[0].name == "fg_2"

    def test_unchanged(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer": scene.z_layers[0],
                "new_name": "bg",
            },
        )
        assert result == {"status": "unchanged", "target": "bg"}

    def test_lookup_by_name(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg", "hud"])
        result = router.dispatch(
            "layer.rename",
            {
                "scene": scene,
                "layer_name": "fg",
                "new_name": "middle",
            },
        )
        assert result["status"] == "renamed"
        assert scene.z_layers[1].name == "middle"

    def test_active_layer_fallback(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg", "fg"])
        shell = SimpleNamespace(
            _scene=scene, _active_layer=scene.z_layers[1],
        )
        result = router.dispatch(
            "layer.rename",
            {"shell": shell, "new_name": "top"},
        )
        assert result["status"] == "renamed"
        assert result["target"] == "fg"
        assert scene.z_layers[1].name == "top"

    def test_fires_refresh_hook(self, router: ToolRouter) -> None:
        scene = _make_scene(["bg"])
        seen: list[int] = []
        shell = SimpleNamespace(
            _scene=scene,
            _active_layer=scene.z_layers[0],
            _on_layer_renamed=lambda: seen.append(1),
        )
        router.dispatch(
            "layer.rename",
            {"shell": shell, "new_name": "sky"},
        )
        assert seen == [1]
