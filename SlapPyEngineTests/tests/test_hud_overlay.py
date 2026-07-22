"""Tests for the runtime HUD overlay (LL1) — Nova3D parity Sprint 14.

Covers:
    * :class:`HUDOverlay` lifecycle (begin_frame / end_frame /
      submit_to_renderer).
    * Widget attach / detach + visibility toggling.
    * :class:`HUDRegistry` pre-registration + custom factory.
    * Extra widgets: Crosshair, ScoreCounter, ObjectiveMarker.
    * DrawCommand → sprite / text bridging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from pharos_engine.render.camera import Camera2D, Camera3D
from pharos_engine.ui.runtime.draw_command import DrawCommand
from pharos_engine.ui.runtime.hud_kit import HealthBar, StaminaBar, Toast
from pharos_engine.ui.runtime.hud_kit_extra import (
    Crosshair,
    ObjectiveMarker,
    ScoreCounter,
)
from pharos_engine.ui.runtime.hud_overlay import (
    HUDOverlay,
    SpriteSubmission,
    hud_command_to_sprite,
    hud_command_to_text,
)
from pharos_engine.ui.runtime.hud_registry import HUDRegistry


# ---------------------------------------------------------------------------
# Fake renderer that records submissions.
# ---------------------------------------------------------------------------


@dataclass
class _FakeRenderer:
    sprites: list[tuple[object, np.ndarray, tuple[float, float, float, float]]] = field(
        default_factory=list
    )
    lines: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)
    texts: list[tuple[object, tuple[float, float, float, float]]] = field(
        default_factory=list
    )

    def submit_sprite(self, texture, transform_2d, tint=(1.0, 1.0, 1.0, 1.0)):
        self.sprites.append(
            (
                texture,
                np.asarray(transform_2d, dtype=np.float32).copy(),
                tuple(float(x) for x in tint),
            )
        )

    def submit_lines(self, vertices, colors):
        self.lines.append(
            (
                np.asarray(vertices, dtype=np.float32).copy(),
                np.asarray(colors, dtype=np.float32).copy(),
            )
        )

    def submit_text(self, mesh, color):
        self.texts.append((mesh, tuple(float(x) for x in color)))


@dataclass
class _NoTextRenderer:
    """Renderer without a submit_text hook — text is silently skipped."""

    sprites: list = field(default_factory=list)

    def submit_sprite(self, texture, transform_2d, tint=(1.0, 1.0, 1.0, 1.0)):
        self.sprites.append((texture, transform_2d, tint))


def _make_overlay(**kwargs) -> tuple[HUDOverlay, _FakeRenderer, Camera2D]:
    fake = _FakeRenderer()
    cam = Camera2D(viewport_size=(800, 600))
    hud = HUDOverlay(fake, cam, **kwargs)
    return hud, fake, cam


# ---------------------------------------------------------------------------
# HUDOverlay — construction
# ---------------------------------------------------------------------------


def test_hud_overlay_requires_renderer():
    with pytest.raises(ValueError):
        HUDOverlay(None, Camera2D())


def test_hud_overlay_requires_camera():
    with pytest.raises(ValueError):
        HUDOverlay(_FakeRenderer(), None)


def test_hud_overlay_starts_visible_and_empty():
    hud, _, _ = _make_overlay()
    assert hud.visible is True
    assert hud.widget_count == 0
    assert hud.command_count == 0


# ---------------------------------------------------------------------------
# HUDOverlay — attach / detach
# ---------------------------------------------------------------------------


def test_attach_adds_widget():
    hud, _, _ = _make_overlay()
    bar = HealthBar()
    hud.attach(bar)
    assert hud.widget_count == 1
    assert bar in hud.widgets()


def test_attach_rejects_none():
    hud, _, _ = _make_overlay()
    with pytest.raises(ValueError):
        hud.attach(None)


def test_attach_rejects_non_widget():
    hud, _, _ = _make_overlay()
    with pytest.raises(TypeError):
        hud.attach(object())


def test_detach_removes_widget():
    hud, _, _ = _make_overlay()
    bar = HealthBar()
    hud.attach(bar)
    hud.detach(bar)
    assert hud.widget_count == 0


def test_detach_missing_widget_is_silent():
    hud, _, _ = _make_overlay()
    # detach a widget that was never attached — must not raise.
    hud.detach(HealthBar())


def test_clear_detaches_all():
    hud, _, _ = _make_overlay()
    for _ in range(3):
        hud.attach(HealthBar())
    hud.clear()
    assert hud.widget_count == 0


# ---------------------------------------------------------------------------
# HUDOverlay — lifecycle
# ---------------------------------------------------------------------------


def test_begin_and_end_frame_returns_command_list():
    hud, _, _ = _make_overlay()
    hud.attach(HealthBar(value=50, max_value=100))
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    assert isinstance(cmds, list)
    # HealthBar emits at least a progress-bar background + fill + label.
    assert len(cmds) >= 3


def test_begin_frame_twice_raises():
    hud, _, _ = _make_overlay()
    hud.begin_frame(0.016)
    with pytest.raises(RuntimeError):
        hud.begin_frame(0.016)


def test_end_frame_without_begin_raises():
    hud, _, _ = _make_overlay()
    with pytest.raises(RuntimeError):
        hud.end_frame()


def test_begin_frame_accepts_input_state():
    hud, _, _ = _make_overlay()
    hud.begin_frame(
        0.016,
        input_state={"mouse": (100.0, 200.0), "mouse_down": True, "keys_down": {"w"}},
    )
    hud.end_frame()  # smoke test — no exceptions


def test_attached_widget_builds_into_hud():
    hud, _, _ = _make_overlay()
    hud.attach(HealthBar(value=25, max_value=100))
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    # HealthBar builds via ui.progress_bar (2 rects) + ui.label (1 text).
    kinds = [c.kind for c in cmds]
    assert "rect" in kinds
    assert "text" in kinds


def test_detached_widget_stops_rendering():
    hud, _, _ = _make_overlay()
    bar = HealthBar()
    hud.attach(bar)
    hud.begin_frame(0.016)
    with_attached = len(hud.end_frame())
    hud.detach(bar)
    hud.begin_frame(0.016)
    without = len(hud.end_frame())
    assert with_attached > without
    assert without == 0


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


def test_set_visible_false_produces_no_commands():
    hud, _, _ = _make_overlay()
    hud.attach(HealthBar())
    hud.set_visible(False)
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    assert cmds == []


def test_set_visible_false_submits_nothing():
    hud, fake, _ = _make_overlay()
    hud.attach(HealthBar())
    hud.set_visible(False)
    hud.begin_frame(0.016)
    hud.end_frame()
    submitted = hud.submit_to_renderer()
    assert submitted == 0
    assert fake.sprites == []


def test_set_visible_true_restores_output():
    hud, _, _ = _make_overlay()
    hud.attach(HealthBar())
    hud.set_visible(False)
    hud.begin_frame(0.016)
    hud.end_frame()
    hud.set_visible(True)
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    assert len(cmds) > 0


# ---------------------------------------------------------------------------
# submit_to_renderer
# ---------------------------------------------------------------------------


def test_submit_to_renderer_forwards_rects_as_sprites():
    hud, fake, _ = _make_overlay()
    hud.attach(HealthBar(value=50, max_value=100))
    hud.begin_frame(0.016)
    hud.end_frame()
    submitted = hud.submit_to_renderer()
    assert submitted >= 2  # bg + fill rects
    assert len(fake.sprites) >= 2


def test_submit_to_renderer_batches_lines():
    hud, fake, _ = _make_overlay()
    hud.attach(Crosshair())
    hud.begin_frame(0.016)
    hud.end_frame()
    hud.submit_to_renderer()
    # Crosshair emits 4 line commands → one batched submit_lines call.
    assert len(fake.lines) == 1
    verts, cols = fake.lines[0]
    assert verts.shape == (8, 2)  # 4 segments × 2 endpoints
    assert cols.shape == (8, 4)


def test_submit_to_renderer_skips_text_without_atlas():
    hud, fake, _ = _make_overlay()
    hud.attach(HealthBar())  # emits a text label
    hud.begin_frame(0.016)
    hud.end_frame()
    hud.submit_to_renderer()
    # No SDF atlas → text commands silently skipped, no text submissions.
    assert fake.texts == []


# ---------------------------------------------------------------------------
# hud_command_to_sprite
# ---------------------------------------------------------------------------


def test_hud_command_to_sprite_maps_rect():
    cmd = DrawCommand(
        kind="rect",
        position=(10.0, 20.0),
        size=(100.0, 50.0),
        color=(1.0, 0.5, 0.25, 1.0),
    )
    sub = hud_command_to_sprite(cmd)
    assert isinstance(sub, SpriteSubmission)
    assert sub.texture_id is None
    assert sub.tint == (1.0, 0.5, 0.25, 1.0)
    # Transform: 3x3 affine, position in column 2, scale on diag.
    assert sub.transform_2d.shape == (3, 3)
    assert sub.transform_2d[0, 0] == 100.0
    assert sub.transform_2d[1, 1] == 50.0
    assert sub.transform_2d[0, 2] == 10.0
    assert sub.transform_2d[1, 2] == 20.0


def test_hud_command_to_sprite_maps_textured_quad():
    cmd = DrawCommand(
        kind="textured_quad",
        position=(5.0, 6.0),
        size=(64.0, 64.0),
        color=(1.0, 1.0, 1.0, 1.0),
        texture_id=42,
    )
    sub = hud_command_to_sprite(cmd)
    assert sub.texture_id == 42


def test_hud_command_to_sprite_rejects_bad_kind():
    cmd = DrawCommand(kind="line", position=(0, 0), size=(1, 1), color=(1, 1, 1, 1))
    with pytest.raises(ValueError):
        hud_command_to_sprite(cmd)


def test_hud_command_to_sprite_expands_fullscreen_zero_size():
    cmd = DrawCommand(
        kind="rect", position=(0, 0), size=(0, 0), color=(0, 0, 0, 1)
    )
    sub = hud_command_to_sprite(cmd)
    # (0, 0) size becomes 1×1 so the renderer still gets a valid quad.
    assert sub.transform_2d[0, 0] == 1.0
    assert sub.transform_2d[1, 1] == 1.0


# ---------------------------------------------------------------------------
# hud_command_to_text
# ---------------------------------------------------------------------------


def test_hud_command_to_text_returns_none_without_atlas():
    cmd = DrawCommand(
        kind="text",
        position=(0, 0),
        size=(80, 14),
        color=(1, 1, 1, 1),
        text="hi",
    )
    assert hud_command_to_text(cmd, None) is None


def test_hud_command_to_text_rejects_bad_kind():
    cmd = DrawCommand(kind="rect", position=(0, 0), size=(1, 1), color=(1, 1, 1, 1))
    with pytest.raises(ValueError):
        hud_command_to_text(cmd, None)


# ---------------------------------------------------------------------------
# HUDRegistry
# ---------------------------------------------------------------------------


_PRE_REGISTERED = (
    "health_bar",
    "stamina_bar",
    "ammo_counter",
    "compass",
    "minimap",
    "toast",
    "crosshair",
    "score_counter",
    "objective_marker",
)


def test_registry_has_nine_prewired_widgets():
    reg = HUDRegistry()
    names = reg.list_available()
    assert len(names) == 9
    for expected in _PRE_REGISTERED:
        assert expected in names


def test_registry_create_returns_correct_type():
    reg = HUDRegistry()
    bar = reg.create("health_bar", {"value": 42})
    assert isinstance(bar, HealthBar)
    assert bar.value == 42


def test_registry_create_missing_raises():
    reg = HUDRegistry()
    with pytest.raises(KeyError):
        reg.create("does_not_exist")


def test_registry_register_custom_factory():
    reg = HUDRegistry()

    def make_custom(cfg):
        return HealthBar(**{k: v for k, v in cfg.items() if k in {"value"}})

    reg.register("custom_hp", make_custom)
    assert "custom_hp" in reg
    made = reg.create("custom_hp", {"value": 77})
    assert made.value == 77


def test_registry_register_rejects_empty_name():
    reg = HUDRegistry()
    with pytest.raises(ValueError):
        reg.register("", lambda cfg: HealthBar())


def test_registry_register_rejects_non_callable():
    reg = HUDRegistry()
    with pytest.raises(TypeError):
        reg.register("bad", "not-callable")  # type: ignore[arg-type]


def test_registry_unregister_returns_bool():
    reg = HUDRegistry()
    assert reg.unregister("health_bar") is True
    assert reg.unregister("health_bar") is False


def test_registry_create_applies_config_to_widget():
    reg = HUDRegistry()
    tt = reg.create("toast", {"message": "Level Up!", "duration_s": 3.0})
    assert isinstance(tt, Toast)
    assert tt.message == "Level Up!"
    assert tt.duration_s == 3.0


# ---------------------------------------------------------------------------
# Crosshair
# ---------------------------------------------------------------------------


def test_crosshair_emits_four_line_segments():
    hud, _, _ = _make_overlay()
    hud.attach(Crosshair(center=(400.0, 300.0), gap=4.0, length=8.0))
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    lines = [c for c in cmds if c.kind == "line"]
    assert len(lines) == 4


def test_crosshair_segments_have_expected_lengths():
    hud, _, _ = _make_overlay()
    hud.attach(Crosshair(center=(400.0, 300.0), gap=4.0, length=8.0))
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    lines = [c for c in cmds if c.kind == "line"]
    # Two horizontal (size[0]=8, size[1]=0) + two vertical (size[0]=0, size[1]=8).
    horiz = [c for c in lines if c.size == (8.0, 0.0)]
    vert = [c for c in lines if c.size == (0.0, 8.0)]
    assert len(horiz) == 2
    assert len(vert) == 2


# ---------------------------------------------------------------------------
# ScoreCounter
# ---------------------------------------------------------------------------


def test_score_counter_starts_at_zero():
    counter = ScoreCounter()
    assert counter.displayed_value == 0.0
    assert counter.value == 0


def test_score_counter_set_value_starts_animation():
    counter = ScoreCounter(animation_speed=500.0)
    counter.set_value(1000)
    assert counter.value == 1000
    assert counter.displayed_value == 0.0  # not yet ticked
    assert counter.is_animating()


def test_score_counter_animates_on_build():
    hud, _, _ = _make_overlay()
    counter = ScoreCounter(animation_speed=500.0)
    counter.set_value(1000)
    hud.attach(counter)
    # Tick 1 frame at 0.1 s → +50 units.
    hud.begin_frame(0.1)
    hud.end_frame()
    assert 40.0 <= counter.displayed_value <= 60.0


def test_score_counter_reaches_target_eventually():
    hud, _, _ = _make_overlay()
    counter = ScoreCounter(animation_speed=1000.0)
    counter.set_value(100)
    hud.attach(counter)
    # 100 units at 1000/s → 0.1s to converge; give it 0.2s.
    hud.begin_frame(0.2)
    hud.end_frame()
    assert counter.displayed_value == 100.0
    assert not counter.is_animating()


def test_score_counter_counts_down():
    hud, _, _ = _make_overlay()
    counter = ScoreCounter(displayed_value=500.0, value=500, animation_speed=1000.0)
    counter.set_value(0)
    hud.attach(counter)
    hud.begin_frame(0.1)
    hud.end_frame()
    assert counter.displayed_value < 500.0


# ---------------------------------------------------------------------------
# ObjectiveMarker
# ---------------------------------------------------------------------------


def test_objective_marker_projects_to_center_without_camera():
    marker = ObjectiveMarker(viewport_size=(800, 600))
    (sx, sy), on_screen = marker.project()
    assert (sx, sy) == (400.0, 300.0)
    assert on_screen is True


def test_objective_marker_projects_with_camera():
    cam = Camera3D(
        position=(0.0, 0.0, 5.0),
        look_at=(0.0, 0.0, 0.0),
        aspect=800.0 / 600.0,
    )
    marker = ObjectiveMarker(
        world_pos=(0.0, 0.0, 0.0),
        viewport_size=(800, 600),
        view_matrix=cam.view_matrix(),
        projection_matrix=cam.projection_matrix(),
    )
    (sx, sy), on_screen = marker.project()
    # Objective sits at the origin → maps to viewport centre.
    assert abs(sx - 400.0) < 1.0
    assert abs(sy - 300.0) < 1.0
    assert on_screen is True


def test_objective_marker_off_screen_clamps_to_edge():
    cam = Camera3D(
        position=(0.0, 0.0, 5.0),
        look_at=(0.0, 0.0, 0.0),
        aspect=800.0 / 600.0,
        fov_degrees=45.0,
    )
    # Objective way off to the side of the camera → off-screen.
    marker = ObjectiveMarker(
        world_pos=(100.0, 0.0, 0.0),
        viewport_size=(800, 600),
        view_matrix=cam.view_matrix(),
        projection_matrix=cam.projection_matrix(),
    )
    (sx, sy), on_screen = marker.project()
    assert on_screen is False
    # Clamped inside the viewport (with icon-size margin).
    assert 0.0 <= sx <= 800.0
    assert 0.0 <= sy <= 600.0


def test_objective_marker_build_emits_rect():
    hud, _, _ = _make_overlay()
    marker = ObjectiveMarker(viewport_size=(800, 600), label="Boss")
    hud.attach(marker)
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    rects = [c for c in cmds if c.kind == "rect"]
    assert len(rects) >= 1
    # Label emits when on-screen.
    texts = [c for c in cmds if c.kind == "text"]
    assert any(t.text == "Boss" for t in texts)


# ---------------------------------------------------------------------------
# End-to-end integration
# ---------------------------------------------------------------------------


def test_end_to_end_multi_widget_hud():
    hud, fake, _ = _make_overlay()
    hud.attach(HealthBar(value=80, max_value=100))
    hud.attach(StaminaBar(value=60, max_value=100))
    hud.attach(Crosshair(center=(400.0, 300.0)))
    hud.attach(ScoreCounter(value=250))
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    assert len(cmds) > 4
    hud.submit_to_renderer()
    assert len(fake.sprites) > 0
    assert len(fake.lines) == 1  # Crosshair batch


def test_command_count_property_matches_last_frame():
    hud, _, _ = _make_overlay()
    hud.attach(HealthBar())
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    assert hud.command_count == len(cmds)


def test_widget_count_property():
    hud, _, _ = _make_overlay()
    for _ in range(5):
        hud.attach(HealthBar())
    assert hud.widget_count == 5


def test_widget_exception_does_not_break_frame():
    class BrokenWidget:
        def build(self, ui):
            raise RuntimeError("boom")

    hud, _, _ = _make_overlay()
    hud.attach(BrokenWidget())
    hud.attach(HealthBar())
    hud.begin_frame(0.016)
    cmds = hud.end_frame()
    # HealthBar still emits despite the broken sibling.
    assert any(c.kind == "text" for c in cmds)


def test_no_text_renderer_hook_still_submits_sprites():
    fake = _NoTextRenderer()
    cam = Camera2D(viewport_size=(800, 600))
    hud = HUDOverlay(fake, cam)
    hud.attach(HealthBar())
    hud.begin_frame(0.016)
    hud.end_frame()
    submitted = hud.submit_to_renderer()
    assert submitted >= 2  # rects still forwarded
