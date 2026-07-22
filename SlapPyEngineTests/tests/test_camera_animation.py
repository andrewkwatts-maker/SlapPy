"""Tests for :mod:`pharos_editor.actions.camera_animation_actions` (CC6).

Covers all six easing curves (endpoints, monotonicity where applicable,
and the deliberate overshoot / oscillation of ``back`` / ``bounce``),
the non-blocking tween scheduler on :class:`CameraAnimator`, and the two
router actions ``view.focus_on_selection_animated`` and
``view.frame_all_animated``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "python"),
)

from pharos_editor.actions.camera_animation_actions import (  # noqa: E402
    CameraAnimator,
    CameraTweenState,
    EasingCurves,
    focus_on_selection_animated,
    frame_all_animated,
    get_module_animator,
)
from pharos_editor.tool_router import REGISTRY  # noqa: E402


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeCamera3D:
    """3D camera stub matching ViewportPanel's duck-typed surface."""

    def __init__(self) -> None:
        self._cam_target: list[float] = [0.0, 0.0, 0.0]
        self._cam_distance: float = 5.0


class FakeCamera2D:
    """2D camera stub — pan + zoom_level, no 3D distance."""

    def __init__(self) -> None:
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._zoom_level: float = 1.0


class FakeEntity:
    def __init__(self, position=(0.0, 0.0), z_height=0.0):
        self.position = position
        self.z_height = z_height


# ---------------------------------------------------------------------------
# EasingCurves — endpoints and characterising behaviour
# ---------------------------------------------------------------------------


def test_easing_curves_has_six_kinds():
    assert set(EasingCurves) == {
        "linear", "ease_in", "ease_out", "ease_in_out", "bounce", "back",
    }


@pytest.mark.parametrize("kind", ["linear", "ease_in", "ease_out",
                                   "ease_in_out", "bounce"])
def test_easing_endpoints_land_at_zero_and_one(kind):
    curve = EasingCurves[kind]
    assert curve(0.0) == pytest.approx(0.0, abs=1e-9)
    assert curve(1.0) == pytest.approx(1.0, abs=1e-6)


def test_back_endpoint_lands_at_one():
    # "back" is allowed to overshoot but must settle exactly at 1.0.
    curve = EasingCurves["back"]
    assert curve(1.0) == pytest.approx(1.0, abs=1e-6)
    assert curve(0.0) == pytest.approx(0.0, abs=1e-6)


def test_linear_is_identity():
    curve = EasingCurves["linear"]
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert curve(t) == pytest.approx(t)


def test_ease_in_is_monotonic():
    curve = EasingCurves["ease_in"]
    samples = [curve(t / 20.0) for t in range(21)]
    for a, b in zip(samples, samples[1:]):
        assert b >= a - 1e-9


def test_ease_out_is_monotonic():
    curve = EasingCurves["ease_out"]
    samples = [curve(t / 20.0) for t in range(21)]
    for a, b in zip(samples, samples[1:]):
        assert b >= a - 1e-9


def test_ease_in_out_is_monotonic():
    curve = EasingCurves["ease_in_out"]
    samples = [curve(t / 20.0) for t in range(21)]
    for a, b in zip(samples, samples[1:]):
        assert b >= a - 1e-9


def test_ease_in_starts_slow():
    curve = EasingCurves["ease_in"]
    # At t=0.5 an ease-in-quadratic gives 0.25 (below linear).
    assert curve(0.5) < 0.5


def test_ease_out_ends_slow():
    curve = EasingCurves["ease_out"]
    # At t=0.5 an ease-out-quadratic gives 0.75 (above linear).
    assert curve(0.5) > 0.5


def test_back_overshoots():
    # The "back" curve is designed to exceed 1.0 somewhere in the middle.
    curve = EasingCurves["back"]
    peak = max(curve(t / 100.0) for t in range(101))
    assert peak > 1.0


def test_bounce_oscillates():
    # The "bounce" curve isn't monotonic — it revisits lower values as
    # the ball bounces upward. Confirm at least one non-monotone step.
    curve = EasingCurves["bounce"]
    samples = [curve(t / 100.0) for t in range(101)]
    saw_dip = any(b < a - 1e-6 for a, b in zip(samples, samples[1:]))
    assert saw_dip


# ---------------------------------------------------------------------------
# CameraAnimator.tween_to_position
# ---------------------------------------------------------------------------


def test_tween_to_position_starts_and_returns_state():
    cam = FakeCamera3D()
    an = CameraAnimator()
    state = an.tween_to_position(cam, (10.0, 20.0, 0.0),
                                  duration_ms=500, easing="linear",
                                  now_ms=0.0)
    assert isinstance(state, CameraTweenState)
    assert state.from_pos == (0.0, 0.0, 0.0)
    assert state.to_pos == (10.0, 20.0, 0.0)
    assert state.duration_ms == 500.0
    assert state.easing_kind == "linear"
    assert an.active_count() == 1


def test_tween_to_position_advances_at_midpoint():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (100.0, 200.0, 0.0),
                         duration_ms=1000, easing="linear", now_ms=0.0)
    an.tick(500.0)  # halfway.
    # Linear easing: expect ~50%.
    assert cam._cam_target[0] == pytest.approx(50.0, abs=1e-6)
    assert cam._cam_target[1] == pytest.approx(100.0, abs=1e-6)


def test_tween_completes_at_duration():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (7.0, 9.0, 3.0),
                         duration_ms=200, easing="linear", now_ms=0.0)
    an.tick(200.0)
    assert cam._cam_target == [7.0, 9.0, 3.0]
    assert an.active_count() == 0


def test_tween_completes_past_duration():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (1.0, 2.0, 3.0),
                         duration_ms=100, easing="linear", now_ms=0.0)
    an.tick(500.0)
    assert cam._cam_target == [1.0, 2.0, 3.0]


def test_tween_to_position_rejects_bad_camera():
    an = CameraAnimator()
    # Object with no _cam_target / _pan_x / _zoom_level slots.
    assert an.tween_to_position(object(), (0.0, 0.0)) is None


def test_tween_to_position_rejects_bad_target():
    cam = FakeCamera3D()
    an = CameraAnimator()
    assert an.tween_to_position(cam, "not-a-tuple") is None
    assert an.tween_to_position(cam, (1.0,)) is None


# ---------------------------------------------------------------------------
# tween_to_zoom
# ---------------------------------------------------------------------------


def test_tween_to_zoom_starts():
    cam = FakeCamera3D()
    an = CameraAnimator()
    state = an.tween_to_zoom(cam, 20.0, duration_ms=100,
                              easing="linear", now_ms=0.0)
    assert state is not None
    assert state.from_zoom == pytest.approx(5.0)
    assert state.to_zoom == pytest.approx(20.0)


def test_tween_to_zoom_completes():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_zoom(cam, 12.5, duration_ms=100, easing="linear",
                     now_ms=0.0)
    an.tick(100.0)
    assert cam._cam_distance == pytest.approx(12.5)


def test_tween_to_zoom_on_2d_camera_uses_zoom_level():
    cam = FakeCamera2D()
    an = CameraAnimator()
    an.tween_to_zoom(cam, 2.5, duration_ms=100, easing="linear",
                     now_ms=0.0)
    an.tick(100.0)
    assert cam._zoom_level == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# focus_on_entity
# ---------------------------------------------------------------------------


def test_focus_on_entity_handles_missing_entity():
    cam = FakeCamera3D()
    an = CameraAnimator()
    assert an.focus_on_entity(cam, None) is None


def test_focus_on_entity_handles_positionless_entity():
    class Bare:
        pass
    cam = FakeCamera3D()
    an = CameraAnimator()
    assert an.focus_on_entity(cam, Bare()) is None


def test_focus_on_entity_schedules_both_position_and_zoom():
    cam = FakeCamera3D()
    an = CameraAnimator()
    e = FakeEntity(position=(50.0, 60.0), z_height=0.0)
    state = an.focus_on_entity(cam, e, duration_ms=200,
                                easing="linear", now_ms=0.0)
    assert state is not None
    assert an.active_count() == 2
    # After ticking to completion, the camera lands on the centroid.
    an.tick(200.0)
    assert cam._cam_target[0] == pytest.approx(50.0)
    assert cam._cam_target[1] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# frame_all_animated
# ---------------------------------------------------------------------------


def test_frame_all_animated_empty_returns_none():
    cam = FakeCamera3D()
    an = CameraAnimator()
    assert an.frame_all_animated(cam, []) is None


def test_frame_all_animated_computes_centroid():
    cam = FakeCamera3D()
    an = CameraAnimator()
    ents = [
        FakeEntity(position=(0.0, 0.0)),
        FakeEntity(position=(10.0, 0.0)),
        FakeEntity(position=(0.0, 10.0)),
        FakeEntity(position=(10.0, 10.0)),
    ]
    state = an.frame_all_animated(cam, ents, duration_ms=100,
                                    easing="linear", now_ms=0.0)
    assert state is not None
    an.tick(100.0)
    assert cam._cam_target[0] == pytest.approx(5.0)
    assert cam._cam_target[1] == pytest.approx(5.0)
    # AABB diag = sqrt(200) ≈ 14.14; radius = 7.07; distance = radius*2*1.15.
    assert cam._cam_distance > 5.0


# ---------------------------------------------------------------------------
# Concurrent tweens
# ---------------------------------------------------------------------------


def test_concurrent_tweens_do_not_corrupt_state():
    cam = FakeCamera3D()
    an = CameraAnimator()
    # Position tween 0→100 over 1000 ms; zoom tween 5→15 over 500 ms.
    an.tween_to_position(cam, (100.0, 0.0, 0.0),
                          duration_ms=1000, easing="linear", now_ms=0.0)
    an.tween_to_zoom(cam, 15.0, duration_ms=500, easing="linear",
                     now_ms=0.0)
    an.tick(250.0)
    # 25% of position, 50% of zoom.
    assert cam._cam_target[0] == pytest.approx(25.0)
    assert cam._cam_distance == pytest.approx(10.0)
    an.tick(500.0)
    # Zoom completes, position still mid-flight.
    assert cam._cam_distance == pytest.approx(15.0)
    assert cam._cam_target[0] == pytest.approx(50.0)
    an.tick(1000.0)
    assert cam._cam_target[0] == pytest.approx(100.0)


def test_new_position_tween_cancels_previous():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (100.0, 0.0, 0.0),
                          duration_ms=1000, easing="linear", now_ms=0.0)
    old_state = an.position_tween
    an.tween_to_position(cam, (200.0, 0.0, 0.0),
                          duration_ms=1000, easing="linear", now_ms=0.0)
    assert old_state is not None
    assert old_state.done is True
    assert an.active_count() == 1


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------


def test_stop_all_cancels_active_tweens():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (10.0, 20.0, 0.0), duration_ms=1000,
                          easing="linear", now_ms=0.0)
    an.tween_to_zoom(cam, 50.0, duration_ms=500, easing="linear",
                     now_ms=0.0)
    cancelled = an.stop_all()
    assert cancelled == 2
    assert an.active_count() == 0
    # A subsequent tick must be a no-op — nothing to advance.
    driven = an.tick(999_999.0)
    assert driven == 0


def test_stop_all_on_idle_animator_returns_zero():
    an = CameraAnimator()
    assert an.stop_all() == 0


# ---------------------------------------------------------------------------
# Router dispatch
# ---------------------------------------------------------------------------


def test_router_registers_focus_on_selection_animated():
    action = REGISTRY.get("view.focus_on_selection_animated")
    assert action is not None
    assert action.category == "view"
    assert action.python_fallback is not None


def test_router_registers_frame_all_animated():
    action = REGISTRY.get("view.frame_all_animated")
    assert action is not None
    assert action.category == "view"
    assert action.python_fallback is not None


def test_focus_on_selection_animated_no_selection():
    cam = FakeCamera3D()
    ctx = {"camera": cam, "selection": []}
    result = focus_on_selection_animated(ctx)
    assert result["status"] == "no_selection"


def test_focus_on_selection_animated_no_camera():
    ctx = {"selection": [FakeEntity(position=(1.0, 2.0))]}
    result = focus_on_selection_animated(ctx)
    assert result["status"] == "no_camera"


def test_focus_on_selection_animated_dispatches():
    cam = FakeCamera3D()
    an = CameraAnimator()
    ent = FakeEntity(position=(30.0, 40.0))
    result = focus_on_selection_animated({
        "camera": cam,
        "selection": [ent],
        "animator": an,
        "now_ms": 0.0,
    })
    assert result["status"] == "tween_started"
    assert result["duration_ms"] == 800.0
    assert result["easing"] == "ease_in_out"
    # target reflects the centroid (single-entity → the entity's pos).
    assert result["target"][0] == pytest.approx(30.0)
    assert result["target"][1] == pytest.approx(40.0)


def test_frame_all_animated_dispatches():
    cam = FakeCamera3D()
    an = CameraAnimator()
    ents = [FakeEntity(position=(0.0, 0.0)),
            FakeEntity(position=(20.0, 20.0))]
    result = frame_all_animated({
        "camera": cam,
        "entities": ents,
        "animator": an,
        "now_ms": 0.0,
    })
    assert result["status"] == "tween_started"
    assert result["duration_ms"] == 1200.0
    assert result["target"][0] == pytest.approx(10.0)


def test_frame_all_animated_empty():
    cam = FakeCamera3D()
    result = frame_all_animated({"camera": cam, "entities": []})
    assert result["status"] == "empty_scene"


def test_router_dispatch_via_registry():
    cam = FakeCamera3D()
    an = CameraAnimator()
    result = REGISTRY.dispatch(
        "view.focus_on_selection_animated",
        {
            "camera": cam,
            "selection": [FakeEntity(position=(5.0, 5.0))],
            "animator": an,
            "now_ms": 0.0,
        },
    )
    assert result is not None
    assert result["status"] == "tween_started"


def test_module_animator_singleton():
    a = get_module_animator()
    b = get_module_animator()
    assert a is b
    assert isinstance(a, CameraAnimator)


def test_ctx_type_error_on_non_mapping():
    with pytest.raises(TypeError):
        focus_on_selection_animated(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        frame_all_animated([])  # type: ignore[arg-type]


def test_tick_with_bad_now_ms_returns_zero():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (5.0, 5.0, 0.0), duration_ms=100,
                          easing="linear", now_ms=0.0)
    assert an.tick("not-a-number") == 0  # type: ignore[arg-type]


def test_tween_at_zero_time_does_not_move_camera():
    cam = FakeCamera3D()
    an = CameraAnimator()
    an.tween_to_position(cam, (100.0, 100.0, 0.0),
                          duration_ms=1000, easing="linear",
                          now_ms=0.0)
    an.tick(0.0)
    # At u=0 the camera is written to the from_pos snapshot (which
    # equals its starting position).
    assert cam._cam_target == [0.0, 0.0, 0.0]
