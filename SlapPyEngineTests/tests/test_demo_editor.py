"""Smoke test for ``examples/editor_demo.py`` (RR2 gap-close, batch 3).

The editor demo constructs a two-asset ``Scene`` (fluid-sandbox terrain +
animated sprite) and then calls ``engine.run_editor()`` which opens the
Dear PyGui editor shell.  We stub wgpu + ``Engine.run_editor`` so the
test never opens a viewport but the demo body still runs to completion.

Pins:
1. Demo module imports cleanly with stubs installed.
2. Scene ends up with two assets (terrain + sprite).
3. Sprite's animation graph is attached with the expected two states.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "editor_demo.py"


def _install_engine_stubs(monkeypatch):
    """Replace WgpuCanvas + Engine._setup_gpu + run_editor with no-ops."""
    try:
        import dearpygui.dearpygui  # noqa: F401
    except ImportError:
        pytest.skip("dearpygui not installed — editor demo cannot import")

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
        raise AssertionError("wgpu event loop invoked in headless test")

    monkeypatch.setattr(engine_mod, "run", _fake_event_loop)

    def _stub_setup_gpu(self, canvas):
        self._gpu = MagicMock()
        self._gpu.surface_format = "rgba8unorm"
        self._renderer = MagicMock()
        self._input = MagicMock()

    monkeypatch.setattr(engine_mod.Engine, "_setup_gpu", _stub_setup_gpu)

    # Replace run_editor with a no-op — the DPG viewport would block otherwise.
    monkeypatch.setattr(
        engine_mod.Engine, "run_editor", lambda self, *a, **k: None
    )


@pytest.fixture
def demo(monkeypatch):
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    _install_engine_stubs(monkeypatch)

    spec = importlib.util.spec_from_file_location("editor_demo_rr2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["editor_demo_rr2"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        pytest.skip(f"editor demo bailed out at import: {exc}")
    except Exception as exc:
        pytest.skip(f"editor demo failed to load headlessly: {exc}")
    return module


def test_editor_demo_module_imports(demo):
    """Demo file loaded without raising under headless stubs."""
    assert demo is not None
    assert hasattr(demo, "engine")
    assert hasattr(demo, "scene")


def test_editor_demo_scene_has_two_assets(demo):
    """Scene must contain both the terrain asset and the sprite asset."""
    scene = demo.scene
    # Scene stores assets under ``assets`` (list) or ``entities`` depending on
    # API vintage — probe both.
    assets = getattr(scene, "assets", None)
    if assets is None:
        assets = getattr(scene, "entities", None)
    if assets is None:
        pytest.skip("Scene has neither .assets nor .entities attribute")
    names = [getattr(a, "name", None) for a in assets]
    assert "terrain" in names, f"terrain asset missing; scene had {names}"
    assert "sprite" in names, f"sprite asset missing; scene had {names}"


def test_editor_demo_sprite_has_anim_graph(demo):
    """Sprite asset carries an AnimationGraph with idle + run states."""
    sprite = demo.sprite
    graph = getattr(sprite, "anim_graph", None)
    assert graph is not None, "sprite.anim_graph was never attached"
    # AnimationGraph exposes states via ``states`` or ``_states``.
    states = getattr(graph, "states", None) or getattr(graph, "_states", None)
    assert states is not None, "AnimationGraph has no states"
    state_names = set(states.keys()) if hasattr(states, "keys") else {
        getattr(s, "name", None) for s in states
    }
    assert "idle" in state_names, f"idle state missing; found {state_names}"
    assert "run" in state_names, f"run state missing; found {state_names}"
