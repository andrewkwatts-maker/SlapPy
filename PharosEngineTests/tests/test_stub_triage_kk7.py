"""KK7 STUB-triage tests — thirteenth round of feature-map wiring.

Covers the five new action ids added by the 2026-07-05 KK7 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"KK7 STUB-triage patch"):

* ``edit.mirror_selection_x`` — Blender ``Ctrl+M X`` — reflect selection
  across the X axis.
* ``edit.mirror_selection_y`` — Blender ``Ctrl+M Y`` — reflect on Y.
* ``edit.mirror_selection_z`` — Blender ``Ctrl+M Z`` — reflect on Z
  (3D scenes).
* ``view.orbit_selection`` — Blender ``Numpad 4/6`` — camera orbit around
  the selection centroid.
* ``view.top_down_view`` — Blender ``Numpad 7`` — snap camera to
  top-down orthographic.

Every test dispatches through :class:`~pharos_editor.tool_router.ToolRouter`
so the wire-up (``action_id`` -> Python fallback) is exercised
end-to-end. No DPG context is required — the fixtures use
:class:`SimpleNamespace` stand-ins for shell / camera handles.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_editor.tool_router import (
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
    """3D-position entity (mutable list so mirror can write in place)."""

    def __init__(
        self,
        name: str,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        scale: tuple[float, float, float] | None = None,
    ) -> None:
        self.name = name
        self.position = list(position)
        if scale is not None:
            self.scale = list(scale)


class _Sprite2D:
    """2D-position + z_height entity (Nova2D convention)."""

    def __init__(
        self,
        name: str,
        position: tuple[float, float] = (0.0, 0.0),
        z_height: float = 0.0,
    ) -> None:
        self.name = name
        self.position = list(position)
        self.z_height = z_height


class _FakeCamera:
    """Minimal orbit-camera stand-in used by the view tests."""

    def __init__(self) -> None:
        self._cam_target = [0.0, 0.0, 0.0]
        self._cam_distance = 5.0
        self._cam_yaw = 0.0
        self._cam_pitch = 0.0
        self._cam_projection = "perspective"


# ---------------------------------------------------------------------------
# Registration checks (7 tests)
# ---------------------------------------------------------------------------


class TestRegistration:
    """Confirm the 5 KK7 action ids are on the canonical router."""

    def test_mirror_x_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.mirror_selection_x")

    def test_mirror_y_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.mirror_selection_y")

    def test_mirror_z_registered(self, router: ToolRouter) -> None:
        assert router.has_action("edit.mirror_selection_z")

    def test_orbit_selection_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.orbit_selection")

    def test_top_down_view_registered(self, router: ToolRouter) -> None:
        assert router.has_action("view.top_down_view")

    def test_all_kk7_on_module_singleton(self) -> None:
        for aid in (
            "edit.mirror_selection_x",
            "edit.mirror_selection_y",
            "edit.mirror_selection_z",
            "view.orbit_selection",
            "view.top_down_view",
        ):
            assert REGISTRY.has_action(aid), aid

    def test_kk7_action_categories(self, router: ToolRouter) -> None:
        edit_ids = (
            "edit.mirror_selection_x",
            "edit.mirror_selection_y",
            "edit.mirror_selection_z",
        )
        view_ids = ("view.orbit_selection", "view.top_down_view")
        for aid in edit_ids:
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == "edit", aid
        for aid in view_ids:
            action = router.get(aid)
            assert action is not None, aid
            assert action.category == "view", aid


# ---------------------------------------------------------------------------
# edit.mirror_selection_x (5 tests)
# ---------------------------------------------------------------------------


class TestMirrorX:
    def test_mirror_x_single_entity_around_centroid(
        self, router: ToolRouter,
    ) -> None:
        a = _Entity("a", position=(2.0, 3.0, 4.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch("edit.mirror_selection_x", {"shell": shell})
        assert result["status"] == "mirrored"
        assert result["axis"] == "x"
        # Centroid pivot = 2.0 -> reflected x stays 2.0.
        assert a.position[0] == pytest.approx(2.0)
        # Y and Z untouched.
        assert a.position[1] == pytest.approx(3.0)
        assert a.position[2] == pytest.approx(4.0)

    def test_mirror_x_multi_entity_around_centroid(
        self, router: ToolRouter,
    ) -> None:
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(10.0, 0.0, 0.0))
        shell = SimpleNamespace(_selected_entities=[a, b])
        result = router.dispatch("edit.mirror_selection_x", {"shell": shell})
        assert result["status"] == "mirrored"
        assert result["count"] == 2
        # Centroid = 5, so 0 -> 10 and 10 -> 0.
        assert a.position[0] == pytest.approx(10.0)
        assert b.position[0] == pytest.approx(0.0)

    def test_mirror_x_explicit_pivot(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(3.0, 1.0, 2.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch(
            "edit.mirror_selection_x",
            {"shell": shell, "pivot": 0.0},
        )
        assert result["status"] == "mirrored"
        assert a.position[0] == pytest.approx(-3.0)
        assert result["pivot"] == pytest.approx(0.0)

    def test_mirror_x_flips_scale_axis(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(1.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0))
        shell = SimpleNamespace(_selected_entity=a)
        router.dispatch(
            "edit.mirror_selection_x", {"shell": shell, "pivot": 0.0},
        )
        assert a.scale[0] == pytest.approx(-1.0)
        # Y / Z scale untouched.
        assert a.scale[1] == pytest.approx(1.0)
        assert a.scale[2] == pytest.approx(1.0)

    def test_mirror_x_no_selection(self, router: ToolRouter) -> None:
        shell = SimpleNamespace()
        result = router.dispatch("edit.mirror_selection_x", {"shell": shell})
        assert result == {"status": "no_selection"}


# ---------------------------------------------------------------------------
# edit.mirror_selection_y (3 tests)
# ---------------------------------------------------------------------------


class TestMirrorY:
    def test_mirror_y_around_zero(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(1.0, 5.0, 2.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch(
            "edit.mirror_selection_y", {"shell": shell, "pivot": 0.0},
        )
        assert result["status"] == "mirrored"
        assert result["axis"] == "y"
        assert a.position[0] == pytest.approx(1.0)
        assert a.position[1] == pytest.approx(-5.0)
        assert a.position[2] == pytest.approx(2.0)

    def test_mirror_y_2d_sprite_preserves_shape(
        self, router: ToolRouter,
    ) -> None:
        s = _Sprite2D("s", position=(3.0, 4.0), z_height=2.0)
        shell = SimpleNamespace(_selected_entity=s)
        result = router.dispatch(
            "edit.mirror_selection_y", {"shell": shell, "pivot": 0.0},
        )
        assert result["status"] == "mirrored"
        # 2D position stays length-2.
        assert len(s.position) == 2
        assert s.position[0] == pytest.approx(3.0)
        assert s.position[1] == pytest.approx(-4.0)
        # z_height untouched (mirror on Y not Z).
        assert s.z_height == pytest.approx(2.0)

    def test_mirror_y_pivot_tuple(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(0.0, 4.0, 0.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch(
            "edit.mirror_selection_y",
            {"shell": shell, "pivot": (0.0, 2.0, 0.0)},
        )
        assert result["status"] == "mirrored"
        # pivot.y = 2, so 4 -> 0.
        assert a.position[1] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# edit.mirror_selection_z (3 tests)
# ---------------------------------------------------------------------------


class TestMirrorZ:
    def test_mirror_z_3d_entity(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(0.0, 0.0, 5.0))
        shell = SimpleNamespace(_selected_entity=a)
        result = router.dispatch(
            "edit.mirror_selection_z", {"shell": shell, "pivot": 0.0},
        )
        assert result["status"] == "mirrored"
        assert result["axis"] == "z"
        assert a.position[2] == pytest.approx(-5.0)

    def test_mirror_z_2d_sprite_uses_z_height(
        self, router: ToolRouter,
    ) -> None:
        s = _Sprite2D("s", position=(1.0, 2.0), z_height=3.0)
        shell = SimpleNamespace(_selected_entity=s)
        result = router.dispatch(
            "edit.mirror_selection_z", {"shell": shell, "pivot": 0.0},
        )
        assert result["status"] == "mirrored"
        # z_height mirrored.
        assert s.z_height == pytest.approx(-3.0)
        # XY untouched.
        assert s.position[0] == pytest.approx(1.0)
        assert s.position[1] == pytest.approx(2.0)

    def test_mirror_z_flip_scale_disabled(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(0.0, 0.0, 3.0), scale=(1.0, 1.0, 1.0))
        shell = SimpleNamespace(_selected_entity=a)
        router.dispatch(
            "edit.mirror_selection_z",
            {"shell": shell, "pivot": 0.0, "flip_scale": False},
        )
        # Position mirrored but scale kept intact.
        assert a.position[2] == pytest.approx(-3.0)
        assert a.scale[2] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# view.orbit_selection (5 tests)
# ---------------------------------------------------------------------------


class TestOrbitSelection:
    def test_orbit_default_yaw_step(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(1.0, 2.0, 3.0))
        result = router.dispatch(
            "view.orbit_selection",
            {"camera": camera, "selection": a},
        )
        assert result["status"] == "orbited"
        assert result["yaw_deg"] == pytest.approx(15.0)
        assert result["pitch_deg"] == pytest.approx(0.0)
        # Camera target retargeted to entity centroid.
        assert camera._cam_target == [1.0, 2.0, 3.0]

    def test_orbit_explicit_yaw_and_pitch(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        result = router.dispatch(
            "view.orbit_selection",
            {
                "camera": camera,
                "selection": a,
                "yaw_deg": 45.0,
                "pitch_deg": 20.0,
            },
        )
        assert result["status"] == "orbited"
        assert result["yaw_deg"] == pytest.approx(45.0)
        assert result["pitch_deg"] == pytest.approx(20.0)
        assert camera._cam_yaw == pytest.approx(math.radians(45.0))
        assert camera._cam_pitch == pytest.approx(math.radians(20.0))

    def test_orbit_multi_selection_centroid(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        b = _Entity("b", position=(4.0, 6.0, 8.0))
        result = router.dispatch(
            "view.orbit_selection",
            {"camera": camera, "selection": [a, b]},
        )
        assert result["status"] == "orbited"
        assert result["target"] == [2.0, 3.0, 4.0]

    def test_orbit_pitch_clamped(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(0.0, 0.0, 0.0))
        # Massive pitch step — should clamp to ~π/2 - epsilon.
        result = router.dispatch(
            "view.orbit_selection",
            {"camera": camera, "selection": a, "pitch_deg": 500.0},
        )
        assert result["status"] == "orbited"
        # Pitch must be strictly less than π/2 (pole avoidance).
        assert camera._cam_pitch < math.pi * 0.5
        assert camera._cam_pitch > math.pi * 0.5 - math.radians(2.0)

    def test_orbit_no_selection(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        result = router.dispatch(
            "view.orbit_selection", {"camera": camera},
        )
        assert result == {"status": "no_selection"}

    def test_orbit_no_camera(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.orbit_selection",
            {"shell": SimpleNamespace(), "selection": _Entity("a")},
        )
        assert result == {"status": "no_camera"}


# ---------------------------------------------------------------------------
# view.top_down_view (5 tests)
# ---------------------------------------------------------------------------


class TestTopDownView:
    def test_top_down_writes_yaw_pitch_projection(
        self, router: ToolRouter,
    ) -> None:
        camera = _FakeCamera()
        result = router.dispatch(
            "view.top_down_view", {"camera": camera},
        )
        assert result["status"] == "snapped"
        assert result["view"] == "top_down"
        assert camera._cam_yaw == pytest.approx(0.0)
        assert camera._cam_pitch == pytest.approx(-math.pi * 0.5)
        assert camera._cam_projection == "ortho"

    def test_top_down_perspective_override(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        router.dispatch(
            "view.top_down_view",
            {"camera": camera, "projection": "perspective"},
        )
        assert camera._cam_projection == "perspective"

    def test_top_down_retargets_on_selection(self, router: ToolRouter) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(7.0, 8.0, 9.0))
        router.dispatch(
            "view.top_down_view",
            {"camera": camera, "selection": a},
        )
        assert camera._cam_target == [7.0, 8.0, 9.0]

    def test_top_down_keeps_target_when_no_selection(
        self, router: ToolRouter,
    ) -> None:
        camera = _FakeCamera()
        camera._cam_target = [1.0, 2.0, 3.0]
        router.dispatch("view.top_down_view", {"camera": camera})
        # Target untouched — orientation snaps, look-at stays.
        assert camera._cam_target == [1.0, 2.0, 3.0]

    def test_top_down_no_camera(self, router: ToolRouter) -> None:
        result = router.dispatch(
            "view.top_down_view", {"shell": SimpleNamespace()},
        )
        assert result == {"status": "no_camera"}


# ---------------------------------------------------------------------------
# Cross-cutting: ctx validation (5 tests)
# ---------------------------------------------------------------------------


class TestCtxValidation:
    """Silent-acceptance guard — every KK7 helper rejects None ctx."""

    def test_mirror_x_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.edit_mirror_actions import (
            mirror_selection_x,
        )
        with pytest.raises(TypeError):
            mirror_selection_x(None)  # type: ignore[arg-type]

    def test_mirror_y_rejects_list_ctx(self) -> None:
        from pharos_editor.actions.edit_mirror_actions import (
            mirror_selection_y,
        )
        with pytest.raises(TypeError):
            mirror_selection_y([])  # type: ignore[arg-type]

    def test_mirror_z_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.edit_mirror_actions import (
            mirror_selection_z,
        )
        with pytest.raises(TypeError):
            mirror_selection_z(None)  # type: ignore[arg-type]

    def test_orbit_selection_rejects_none_ctx(self) -> None:
        from pharos_editor.actions.view_orbit_actions import orbit_selection
        with pytest.raises(TypeError):
            orbit_selection(None)  # type: ignore[arg-type]

    def test_top_down_view_rejects_list_ctx(self) -> None:
        from pharos_editor.actions.view_snap_actions import top_down_view
        with pytest.raises(TypeError):
            top_down_view([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Cross-cutting: round-trip mirror (2 tests)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_mirror_x_twice_restores(self, router: ToolRouter) -> None:
        a = _Entity("a", position=(3.0, 5.0, 7.0))
        shell = SimpleNamespace(_selected_entity=a)
        router.dispatch(
            "edit.mirror_selection_x", {"shell": shell, "pivot": 0.0},
        )
        router.dispatch(
            "edit.mirror_selection_x", {"shell": shell, "pivot": 0.0},
        )
        assert a.position == [3.0, 5.0, 7.0]

    def test_orbit_then_top_down_snaps_orientation(
        self, router: ToolRouter,
    ) -> None:
        camera = _FakeCamera()
        a = _Entity("a", position=(1.0, 1.0, 1.0))
        # Orbit to change yaw / pitch.
        router.dispatch(
            "view.orbit_selection",
            {
                "camera": camera,
                "selection": a,
                "yaw_deg": 30.0,
                "pitch_deg": 10.0,
            },
        )
        assert camera._cam_yaw != 0.0
        assert camera._cam_pitch != 0.0
        # Snap top-down — yaw / pitch reset to canonical pose.
        router.dispatch(
            "view.top_down_view", {"camera": camera, "selection": a},
        )
        assert camera._cam_yaw == pytest.approx(0.0)
        assert camera._cam_pitch == pytest.approx(-math.pi * 0.5)
