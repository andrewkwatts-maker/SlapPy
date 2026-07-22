"""Tests for :mod:`pharos_engine.hud_bridge` (MM2 sprint).

Pins the following behaviours end-to-end:

1. :func:`mount_hud` creates an :class:`HUDOverlay` bound to the app.
2. :func:`default_game_hud_widgets` returns a non-empty list of the
   five first-party widgets.
3. :meth:`App.enable_hud` populates ``self._hud_overlay``.
4. HUD ticks fire once per frame in ``App.run()`` (after_tick +
   before_frame_render).
5. :func:`unmount_hud` cleanly detaches hooks + clears the overlay
   reference.
6. The renderer shim :class:`_HUDStubRenderer` records every submission.
7. Multiple ``mount_hud`` calls are idempotent.
"""
from __future__ import annotations

import pytest

import pharos_engine
from pharos_engine.hud_bridge import (
    _HUDStubCamera2D,
    _HUDStubRenderer,
    default_game_hud_widgets,
    mount_hud,
    unmount_hud,
)
from pharos_editor.ui.runtime.hud_kit import (
    AmmoCounter,
    Compass,
    HealthBar,
    StaminaBar,
)
from pharos_editor.ui.runtime.hud_kit_extra import Crosshair
from pharos_editor.ui.runtime.hud_overlay import HUDOverlay


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _headless_app() -> pharos_engine.App:
    cfg = pharos_engine.AppConfig(
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
    )
    return pharos_engine.App(config=cfg)


@pytest.fixture
def app():
    a = _headless_app()
    yield a
    a.close()


# ---------------------------------------------------------------------------
# Test 1: mount_hud creates HUDOverlay bound to app
# ---------------------------------------------------------------------------


def test_mount_hud_creates_overlay(app):
    overlay = mount_hud(app)
    assert isinstance(overlay, HUDOverlay)
    assert app._hud_overlay is overlay
    assert overlay.renderer is not None
    assert overlay.camera_2d is not None


# ---------------------------------------------------------------------------
# Test 2: default widget list is non-empty and typed
# ---------------------------------------------------------------------------


def test_default_game_hud_widgets_non_empty():
    widgets = default_game_hud_widgets()
    assert isinstance(widgets, list)
    assert len(widgets) >= 5


def test_default_game_hud_widgets_types():
    widgets = default_game_hud_widgets()
    # The five first-party defaults must all be present.
    kinds = {type(w).__name__ for w in widgets}
    assert "HealthBar" in kinds
    assert "StaminaBar" in kinds
    assert "AmmoCounter" in kinds
    assert "Compass" in kinds
    assert "Crosshair" in kinds


def test_default_game_hud_widgets_are_fresh_instances():
    a = default_game_hud_widgets()
    b = default_game_hud_widgets()
    # Same kinds but distinct instances so callers can mutate safely.
    assert [type(x).__name__ for x in a] == [type(x).__name__ for x in b]
    for wa, wb in zip(a, b):
        assert wa is not wb


# ---------------------------------------------------------------------------
# Test 3: App.enable_hud sets _hud_overlay
# ---------------------------------------------------------------------------


def test_enable_hud_sets_overlay_attr(app):
    assert app._hud_overlay is None
    overlay = app.enable_hud()
    assert app._hud_overlay is overlay
    assert isinstance(overlay, HUDOverlay)


def test_enable_hud_returns_overlay_and_attaches_defaults(app):
    overlay = app.enable_hud()
    # Should have the five default widgets attached.
    assert overlay.widget_count >= 5


def test_enable_hud_layout_argument_accepted(app):
    # Unknown layouts must be silently accepted (forward-compat pin).
    overlay = app.enable_hud(layout="minimal")
    assert isinstance(overlay, HUDOverlay)


def test_enable_hud_with_custom_widgets(app):
    custom = [HealthBar(value=42.0), Crosshair()]
    overlay = app.enable_hud(widgets=custom)
    assert overlay.widget_count == 2
    hp = next(w for w in overlay.widgets() if isinstance(w, HealthBar))
    assert hp.value == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# Test 4: HUD ticks per frame in run() loop
# ---------------------------------------------------------------------------


def test_hud_ticks_per_frame_in_run(app):
    overlay = app.enable_hud()
    app.run(max_frames=10)
    begin_events = [e for e in app.trace if e[0] == "hud_begin_frame"]
    submit_events = [e for e in app.trace if e[0] == "hud_submit"]
    assert len(begin_events) == 10
    assert len(submit_events) == 10


def test_hud_mount_records_trace_event(app):
    app.enable_hud()
    assert any(e[0] == "hud_mount" for e in app.trace)


def test_hud_submit_uses_stub_renderer_when_gpu_off(app):
    overlay = app.enable_hud()
    # The bound renderer must be our HUD stub because the app renderer
    # doesn't expose submit_sprite.
    assert isinstance(overlay.renderer, _HUDStubRenderer)
    app.run(max_frames=5)
    # At least the crosshair emits four line segments per frame.
    assert len(overlay.renderer.lines) > 0


# ---------------------------------------------------------------------------
# Test 5: unmount_hud detaches cleanly
# ---------------------------------------------------------------------------


def test_unmount_hud_detaches(app):
    app.enable_hud()
    assert app._hud_overlay is not None
    ok = unmount_hud(app)
    assert ok is True
    assert app._hud_overlay is None
    assert any(e[0] == "hud_unmount" for e in app.trace)


def test_unmount_hud_is_idempotent(app):
    assert unmount_hud(app) is False


def test_unmount_hud_removes_hooks_from_run_loop(app):
    app.enable_hud()
    unmount_hud(app)
    app.run(max_frames=5)
    # No hud_begin_frame / hud_submit should be recorded after unmount.
    assert not any(e[0] == "hud_begin_frame" for e in app.trace)
    assert not any(e[0] == "hud_submit" for e in app.trace)


# ---------------------------------------------------------------------------
# Test 6: mount_hud is idempotent — a second call returns the same overlay
# ---------------------------------------------------------------------------


def test_mount_hud_is_idempotent(app):
    overlay_a = mount_hud(app)
    overlay_b = mount_hud(app)
    assert overlay_a is overlay_b


# ---------------------------------------------------------------------------
# Test 7: _HUDStubRenderer records submissions
# ---------------------------------------------------------------------------


def test_hud_stub_renderer_records_sprite():
    stub = _HUDStubRenderer()
    stub.submit_sprite("tex", "xform", (1.0, 0.0, 0.0, 1.0))
    assert len(stub.sprites) == 1
    assert stub.total_submissions == 1


def test_hud_stub_renderer_records_lines_and_clear():
    stub = _HUDStubRenderer()
    stub.submit_lines("verts", "cols")
    stub.submit_text("mesh", (1.0, 1.0, 1.0, 1.0))
    assert stub.total_submissions == 2
    stub.clear()
    assert stub.total_submissions == 0


def test_hud_stub_camera_2d_default_viewport():
    cam = _HUDStubCamera2D()
    assert cam.viewport_size == (1280, 720)


# ---------------------------------------------------------------------------
# Test 8: mount_hud rejects None app
# ---------------------------------------------------------------------------


def test_mount_hud_rejects_none_app():
    with pytest.raises(ValueError):
        mount_hud(None)


# ---------------------------------------------------------------------------
# Test 9: HealthBar depletion over a run loop is observable
# ---------------------------------------------------------------------------


def test_health_bar_depletes_during_run(app):
    hp = HealthBar(value=100.0, max_value=100.0)
    app.enable_hud(widgets=[hp])

    def deplete(a, dt):
        hp.value = max(0.0, hp.value - 2.0)

    app.run(on_tick=deplete, max_frames=20)
    assert hp.value < 100.0
