"""NN3 — App capture / screenshot / render-toggle façade tests.

Exercises the five methods added to :class:`slappyengine.app.App` by the
HH1 wire-up sprint tick:

* :meth:`App.start_recording`
* :meth:`App.stop_recording`
* :meth:`App.take_screenshot`
* :meth:`App.enable_ssao`
* :meth:`App.enable_shadows`

Each method is a one-liner over the LL2 / MM6 action helpers
(:mod:`slappyengine.actions.capture_actions` /
:mod:`slappyengine.actions.render_toggle_actions`). The tests assert
that:

(a) the App class exposes all five methods,
(b) each returns a dict matching the underlying action's return
    contract (status keys documented at the top of each helper), and
(c) each works headlessly — no wgpu, no window, no ffmpeg.

For capture we rely on the ``no_renderer`` / ``capture_unavailable``
paths so the tests stay green on machines without ffmpeg. For the
render toggles we lean on the shell-attribute fallback so tests still
pass when the stub renderer is bound.
"""
from __future__ import annotations

from typing import Any

import pytest

from slappyengine.app import App, AppConfig


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> App:
    a = App(AppConfig(enable_gpu=False, max_frames=1))
    yield a
    a.close()


# ---------------------------------------------------------------------------
# (a) surface existence
# ---------------------------------------------------------------------------


def test_app_exposes_all_five_methods(app: App) -> None:
    for name in (
        "start_recording",
        "stop_recording",
        "take_screenshot",
        "enable_ssao",
        "enable_shadows",
    ):
        assert hasattr(app, name), f"App missing method: {name}"
        assert callable(getattr(app, name)), f"App.{name} is not callable"


# ---------------------------------------------------------------------------
# (b + c) capture actions — headless return contracts
# ---------------------------------------------------------------------------


def test_start_recording_returns_dict_headless(app: App) -> None:
    result = app.start_recording()
    assert isinstance(result, dict)
    assert "status" in result
    # Two acceptable headless outcomes: ffmpeg missing or actually
    # recording (dev box with ffmpeg installed). Both are valid.
    assert result["status"] in {
        "recording",
        "capture_unavailable",
        "no_renderer",
    }


def test_start_recording_accepts_path_fps_resolution(app: App) -> None:
    result = app.start_recording(
        path="build/nn3_test_never_written.mp4",
        fps=30,
        resolution=(640, 480),
    )
    assert isinstance(result, dict)
    assert "status" in result
    # If ffmpeg lands, tear it down so state is clean for later tests.
    if result["status"] == "recording":
        app.stop_recording()


def test_stop_recording_returns_dict_when_idle(app: App) -> None:
    # No session started → the helper reports the missed toggle.
    result = app.stop_recording()
    assert isinstance(result, dict)
    assert result.get("status") == "not_recording"


def test_stop_recording_round_trip_when_session_synthesised(app: App) -> None:
    # Bypass the real backend to prove the shell-side session round-trips
    # through App.stop_recording without touching ffmpeg.
    class _FakeBackend:
        closed: bool = False

        def close(self) -> None:
            self.closed = True

    backend = _FakeBackend()
    app._capture_state = {
        "backend": backend,
        "path": "build/synthetic.mp4",
        "started_at": 0.0,
        "frames": 42,
        "fps": 60,
        "resolution": (640, 360),
    }
    result = app.stop_recording()
    assert isinstance(result, dict)
    assert result["status"] == "stopped"
    assert result["frames"] == 42
    assert backend.closed is True
    # Session should be cleared so the "already recording" gate resets.
    assert getattr(app, "_capture_state", None) is None


def test_take_screenshot_returns_dict(app: App) -> None:
    result = app.take_screenshot()
    assert isinstance(result, dict)
    assert "status" in result
    # Headless stub renderer has no frame buffer → the LL2 helper
    # returns capture_unavailable. If a real backend happens to be
    # bound we accept the captured path.
    assert result["status"] in {"captured", "capture_unavailable", "no_renderer"}


def test_take_screenshot_accepts_explicit_path(app: App) -> None:
    result = app.take_screenshot(path="build/nn3_screenshot.png")
    assert isinstance(result, dict)
    assert "status" in result


def test_take_screenshot_accepts_format_argument(app: App) -> None:
    # Only ``format`` given → helper should mint a default path with
    # that extension. We assert the return is still a well-formed dict.
    result = app.take_screenshot(format="jpg")
    assert isinstance(result, dict)
    assert "status" in result


# ---------------------------------------------------------------------------
# (b + c) render toggles — headless return contracts
# ---------------------------------------------------------------------------


def test_enable_ssao_returns_dict(app: App) -> None:
    # Turn it on: either toggled (fresh state) or unchanged (already on).
    result = app.enable_ssao(True)
    assert isinstance(result, dict)
    assert result.get("target") == "ssao"
    assert result.get("status") in {"toggled", "unchanged"}
    assert result.get("enabled") is True


def test_enable_ssao_default_argument_is_true(app: App) -> None:
    # Bare call defaults to enabled=True.
    result = app.enable_ssao()
    assert isinstance(result, dict)
    assert result.get("enabled") is True


def test_enable_ssao_off_after_on(app: App) -> None:
    app.enable_ssao(True)
    result = app.enable_ssao(False)
    assert isinstance(result, dict)
    assert result.get("target") == "ssao"
    assert result.get("enabled") is False


def test_enable_shadows_returns_dict(app: App) -> None:
    result = app.enable_shadows(True)
    assert isinstance(result, dict)
    assert result.get("target") == "shadows"
    assert result.get("status") in {"toggled", "unchanged"}
    assert result.get("enabled") is True


def test_enable_shadows_default_argument_is_true(app: App) -> None:
    result = app.enable_shadows()
    assert isinstance(result, dict)
    assert result.get("enabled") is True


def test_enable_shadows_off_after_on(app: App) -> None:
    app.enable_shadows(True)
    result = app.enable_shadows(False)
    assert isinstance(result, dict)
    assert result.get("target") == "shadows"
    assert result.get("enabled") is False


# ---------------------------------------------------------------------------
# (c) headless-safety: no wgpu / no window / no ffmpeg required
# ---------------------------------------------------------------------------


def test_all_methods_work_headless(app: App) -> None:
    """Every method must return a dict without raising when GPU is off."""
    assert app.is_headless is True

    calls: dict[str, Any] = {
        "start_recording": app.start_recording(),
        "stop_recording": app.stop_recording(),
        "take_screenshot": app.take_screenshot(),
        "enable_ssao": app.enable_ssao(True),
        "enable_shadows": app.enable_shadows(True),
    }
    for name, result in calls.items():
        assert isinstance(result, dict), f"{name} did not return a dict"
        assert "status" in result, f"{name} return dict missing 'status'"
