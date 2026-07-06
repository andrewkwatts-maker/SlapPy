"""Complementary smoke tests for ``examples/hello_hud.py`` (NN1 sprint).

The main ``test_demo_hello_hud.py`` suite asserts on end-to-end demo
behaviour + trace payload. This suite takes a different angle: it pins
the HUD widget registry itself and the :meth:`App.enable_hud` mount
contract that :mod:`hello_hud` relies on.

Coverage
--------

* :func:`slappyengine.hud_bridge.default_game_hud_widgets` returns the
  documented 5-widget lineup (HealthBar / StaminaBar / AmmoCounter /
  Compass / Crosshair).
* :meth:`App.enable_hud` mounts that lineup by default and exposes the
  overlay via ``app._hud_overlay``.
* :meth:`App.enable_hud` accepts a custom widget iterable and mounts it
  in place of the default lineup.
* Repeated :meth:`enable_hud` calls are idempotent (mount_hud contract).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Load the demo to keep parity with the sibling test file's pattern. ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_hud.py"


def _load_demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo not present: {_DEMO_PATH}")
    spec = importlib.util.spec_from_file_location("hello_hud_smoke_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_hud_smoke_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


def _headless_app():
    """Boot an :class:`App` with the same headless config the demo uses."""
    import slappyengine

    config = slappyengine.AppConfig(
        window_title="hello_hud_smoke",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )
    return slappyengine.App(config=config)


# ---------------------------------------------------------------------------
# Test 1: hud_bridge exports default_game_hud_widgets + it returns 5 widgets.
# ---------------------------------------------------------------------------


def test_default_game_hud_widgets_lineup():
    hud_bridge = pytest.importorskip("slappyengine.hud_bridge")
    widgets = hud_bridge.default_game_hud_widgets()
    assert isinstance(widgets, list)
    # Documented lineup: HealthBar, StaminaBar, AmmoCounter, Compass, Crosshair.
    assert len(widgets) == 5

    class_names = {type(w).__name__ for w in widgets}
    # Widget classes may live in different sub-modules; assert on names
    # so we don't couple to import paths.
    for expected in ("HealthBar", "StaminaBar", "AmmoCounter", "Compass", "Crosshair"):
        assert expected in class_names, f"default HUD missing {expected}: {class_names}"


# ---------------------------------------------------------------------------
# Test 2: default_game_hud_widgets returns fresh instances each call.
# ---------------------------------------------------------------------------


def test_default_game_hud_widgets_returns_fresh_instances():
    hud_bridge = pytest.importorskip("slappyengine.hud_bridge")
    a = hud_bridge.default_game_hud_widgets()
    b = hud_bridge.default_game_hud_widgets()
    # No shared identity between calls — spooky-action-at-a-distance guard.
    for wa, wb in zip(a, b):
        assert wa is not wb


# ---------------------------------------------------------------------------
# Test 3: App.enable_hud mounts the default lineup by default.
# ---------------------------------------------------------------------------


def test_app_enable_hud_mounts_default_lineup():
    pytest.importorskip("slappyengine")
    app = _headless_app()
    overlay = app.enable_hud()
    assert overlay is not None
    # The overlay is stashed on the app for later inspection.
    assert getattr(app, "_hud_overlay", None) is overlay
    widgets = overlay.widgets()
    assert len(widgets) == 5
    class_names = {type(w).__name__ for w in widgets}
    for expected in ("HealthBar", "StaminaBar", "AmmoCounter", "Compass", "Crosshair"):
        assert expected in class_names


# ---------------------------------------------------------------------------
# Test 4: App.enable_hud accepts a custom widget iterable.
# ---------------------------------------------------------------------------


def test_app_enable_hud_accepts_custom_widgets():
    pytest.importorskip("slappyengine")
    from slappyengine.ui.runtime.hud_kit import HealthBar

    app = _headless_app()
    custom = [HealthBar(position=(8.0, 8.0), value=42.0, max_value=100.0, label="HP")]
    overlay = app.enable_hud(widgets=custom)
    widgets = overlay.widgets()
    # Only the custom widget mounted — no default lineup fallback.
    assert len(widgets) == 1
    assert isinstance(widgets[0], HealthBar)
    assert widgets[0].value == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# Test 5: App.enable_hud is idempotent — mount_hud reuses the overlay.
# ---------------------------------------------------------------------------


def test_app_enable_hud_is_idempotent():
    pytest.importorskip("slappyengine")
    app = _headless_app()
    first = app.enable_hud()
    second = app.enable_hud()
    assert first is second
    # Widget count stays at 5 (default lineup) after a re-mount.
    assert len(second.widgets()) == 5


# ---------------------------------------------------------------------------
# Test 6: hello_hud demo module loads + its default constants match hud_bridge.
# ---------------------------------------------------------------------------


def test_hello_hud_demo_defaults_are_consistent(demo):
    # The demo's HP window should straddle the range enforced by the
    # default HealthBar widget from hud_bridge.
    hud_bridge = pytest.importorskip("slappyengine.hud_bridge")
    widgets = hud_bridge.default_game_hud_widgets()
    health = next(w for w in widgets if type(w).__name__ == "HealthBar")

    assert 0.0 <= demo.DEFAULT_END_HP < demo.DEFAULT_START_HP <= health.max_value
    assert demo.DEFAULT_START_AMMO >= 0
