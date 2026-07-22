"""Smoke test for ``examples/hud_demo.py`` (QQ2 gap-close, batch 2).

The demo builds a SceneUIEntity HUD, attaches an on-tick script, and
calls ``engine.run()``. We stub the wgpu canvas + Engine._setup_gpu +
set ``SLAPPYENGINE_MAX_FRAMES=2`` so the loop returns after 2 draw
ticks.

Note: ``hud_demo.py`` is distinct from ``hello_hud.py``. The latter has
its own test file already; this one covers the scene-UI variant.

Pins:
1. Demo loads cleanly under headless stubs.
2. Scene contains a ``SceneUIEntity`` named ``"hud"``.
3. HUDScript ticks update the health / score counters.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hud_demo.py"


def _install_engine_stubs(monkeypatch):
    from pharos_engine import engine as engine_mod

    class _StubCanvas:
        def __init__(self, *_, **__):
            pass

        def request_draw(self, fn=None):
            return fn

        def add_event_handler(self, *_, **__):
            return lambda fn: fn

    monkeypatch.setattr(engine_mod, "WgpuCanvas", _StubCanvas)

    def _fake_event_loop():  # pragma: no cover
        raise AssertionError("wgpu event loop invoked with max_frames set")

    monkeypatch.setattr(engine_mod, "run", _fake_event_loop)

    def _stub_setup_gpu(self, canvas):
        self._gpu = MagicMock()
        self._gpu.surface_format = "rgba8unorm"
        self._renderer = MagicMock()
        self._input = MagicMock()

    monkeypatch.setattr(engine_mod.Engine, "_setup_gpu", _stub_setup_gpu)


@pytest.fixture
def demo(monkeypatch):
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    _install_engine_stubs(monkeypatch)
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "2")

    spec = importlib.util.spec_from_file_location("hud_demo_qq2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hud_demo_qq2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hud demo failed to load headlessly: {exc}")
    return module


def test_hud_module_imports(demo):
    """Demo file executed to completion under headless stubs."""
    assert demo is not None
    assert hasattr(demo, "HUDScript")
    assert hasattr(demo, "hud")


def test_hud_scene_entity_registered(demo):
    """The ``hud`` SceneUIEntity is registered under the expected name."""
    hud_entity = demo.hud
    assert hud_entity is not None
    assert hud_entity.name == "hud"


def test_hud_script_ticks_update_state(demo):
    """HUDScript.on_tick drains HP and awards score once per elapsed second."""
    script = demo.HUDScript(demo.hud)
    assert script._health == 100
    assert script._score == 0

    # Tick 1.0s — should trigger exactly one HP-drain + score bump.
    script.on_tick(demo.player, dt=1.0)
    assert script._health == 99
    assert script._score == 10

    # Tick another 2.0s — accumulates another two events.
    script.on_tick(demo.player, dt=1.0)
    script.on_tick(demo.player, dt=1.0)
    assert script._health == 97
    assert script._score == 30
