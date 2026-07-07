"""QQ4 — App diagnostics-collector façade tests.

Exercises the five methods wired onto :class:`slappyengine.app.App` that
plug the OO6 :class:`~slappyengine.diagnostics.DiagnosticsCollector`
into the top-level app lifecycle:

* :meth:`App.enable_diagnostics`
* :meth:`App.disable_diagnostics`
* :meth:`App.get_diagnostics`
* :meth:`App.diagnostics_events`
* :meth:`App.diagnostics_stats`

The tests assert:

(a) all five methods exist on :class:`App`,
(b) ``enable_diagnostics`` installs a collector that captures a warning
    logged via the ``slappyengine`` root logger,
(c) subsequent calls are idempotent (same collector returned),
(d) ``disable_diagnostics`` uninstalls so post-disable warnings are NOT
    captured,
(e) enabling after ``enable_hud`` also mounts a diagnostics HUD widget,
(f) ``diagnostics_stats`` reports per-level counts.
"""
from __future__ import annotations

import logging

import pytest

from slappyengine.app import App, AppConfig
from slappyengine.diagnostics import DiagnosticEvent, DiagnosticsCollector


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> App:
    a = App(AppConfig(enable_gpu=False, max_frames=1))
    yield a
    # Always ensure the collector is torn down between tests so a
    # leaked handler doesn't leak WARNING records into subsequent
    # tests via the shared ``slappyengine`` root logger.
    try:
        a.disable_diagnostics()
    except Exception:
        pass
    a.close()


# ---------------------------------------------------------------------------
# (a) surface existence
# ---------------------------------------------------------------------------


def test_app_exposes_all_five_diagnostics_methods(app: App) -> None:
    for name in (
        "enable_diagnostics",
        "disable_diagnostics",
        "get_diagnostics",
        "diagnostics_events",
        "diagnostics_stats",
    ):
        assert hasattr(app, name), f"App missing method: {name}"
        assert callable(getattr(app, name)), f"App.{name} is not callable"


# ---------------------------------------------------------------------------
# (b) enable_diagnostics captures a warning
# ---------------------------------------------------------------------------


def test_enable_diagnostics_returns_collector_and_captures_warning(
    app: App,
) -> None:
    collector = app.enable_diagnostics()
    assert isinstance(collector, DiagnosticsCollector)
    assert collector.is_installed()

    logging.getLogger("slappyengine.audio_3d").warning("QQ4 test channel")

    events = app.diagnostics_events()
    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, DiagnosticEvent)
    assert evt.level == "WARNING"
    assert evt.subsystem == "audio_3d"
    assert "QQ4 test channel" in evt.message


def test_get_diagnostics_returns_none_before_enable(app: App) -> None:
    assert app.get_diagnostics() is None


def test_diagnostics_events_empty_before_enable(app: App) -> None:
    assert app.diagnostics_events() == []


def test_diagnostics_stats_empty_before_enable(app: App) -> None:
    assert app.diagnostics_stats() == {}


# ---------------------------------------------------------------------------
# (c) idempotence — second call returns the same collector
# ---------------------------------------------------------------------------


def test_enable_diagnostics_is_idempotent(app: App) -> None:
    first = app.enable_diagnostics()
    second = app.enable_diagnostics()
    assert first is second
    # And ``get_diagnostics`` agrees.
    assert app.get_diagnostics() is first


# ---------------------------------------------------------------------------
# (d) disable_diagnostics uninstalls
# ---------------------------------------------------------------------------


def test_disable_diagnostics_stops_capture(app: App) -> None:
    collector = app.enable_diagnostics()
    logging.getLogger("slappyengine.render.ssao").warning("pre-disable")
    assert len(collector.events()) == 1

    result = app.disable_diagnostics()
    assert result == {"status": "disabled"}
    assert app.get_diagnostics() is None

    # A warning after uninstall must NOT reach the (now-detached) buffer.
    logging.getLogger("slappyengine.render.ssao").warning("post-disable")
    # The old collector object is still queryable — it just doesn't grow.
    assert len(collector.events()) == 1


def test_disable_diagnostics_when_not_enabled(app: App) -> None:
    result = app.disable_diagnostics()
    assert result == {"status": "not_enabled"}


# ---------------------------------------------------------------------------
# (e) enabling after enable_hud attaches the diagnostics widget
# ---------------------------------------------------------------------------


def _overlay_widgets(overlay: object) -> list:
    """Return the current widget list from an HUDOverlay.

    ``HUDOverlay.widgets()`` is a method returning a tuple; fall back to
    the private ``_widgets`` list if the surface changes.
    """
    method = getattr(overlay, "widgets", None)
    if callable(method):
        try:
            return list(method())
        except Exception:
            pass
    return list(getattr(overlay, "_widgets", []))


def test_enable_diagnostics_after_hud_attaches_widget(app: App) -> None:
    # Mount the default HUD first.
    overlay = app.enable_hud()
    assert overlay is not None
    baseline_widget_count = len(_overlay_widgets(overlay))

    collector = app.enable_diagnostics()
    assert collector is not None

    # A diagnostics widget should now be attached — the widget count
    # grew by at least one.
    post_widget_count = len(_overlay_widgets(overlay))
    assert post_widget_count > baseline_widget_count, (
        "expected diagnostics widget attached to HUD overlay after "
        "enable_diagnostics; before=%d after=%d"
        % (baseline_widget_count, post_widget_count)
    )

    # And at least one of the widgets should reference the collector.
    has_diag = any(
        getattr(w, "collector", None) is collector
        for w in _overlay_widgets(overlay)
    )
    assert has_diag, "no diagnostics widget bound to our collector"


# ---------------------------------------------------------------------------
# (f) diagnostics_stats reports level counts
# ---------------------------------------------------------------------------


def test_diagnostics_stats_counts_levels(app: App) -> None:
    app.enable_diagnostics()

    logging.getLogger("slappyengine.render").warning("warn 1")
    logging.getLogger("slappyengine.render").warning("warn 2")
    logging.getLogger("slappyengine.audio_3d").error("err 1")

    stats = app.diagnostics_stats()
    assert isinstance(stats, dict)
    assert stats.get("total", 0) == 3
    assert stats.get("level:WARNING", 0) == 2
    assert stats.get("level:ERROR", 0) == 1
    # Subsystem counts also present.
    assert stats.get("subsystem:render", 0) == 2
    assert stats.get("subsystem:audio_3d", 0) == 1
