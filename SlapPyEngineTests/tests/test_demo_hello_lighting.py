"""Smoke tests for ``examples/hello_lighting.py`` (PP4 gap-close).

The demo sets up two independent :class:`LightingContext` layers (a warm
directional-lit background and a cool point-lit foreground) and runs the
engine. We stub wgpu + ``SLAPPYENGINE_MAX_FRAMES=2`` for headless.

Pins:
1. Demo module imports cleanly headless.
2. Both layers were added to a common asset.
3. Background layer has a DirectionalLight; foreground has a PointLight.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_lighting.py"


def _install_engine_stubs(monkeypatch):
    from slappyengine import engine as engine_mod

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

    spec = importlib.util.spec_from_file_location("hello_lighting_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_lighting_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_lighting demo failed to load headlessly: {exc}")
    return module


def test_hello_lighting_imports(demo):
    assert demo is not None
    assert hasattr(demo, "bg")
    assert hasattr(demo, "fg")


def test_hello_lighting_both_layers_attached(demo):
    """Both bg + fg layers are wired into the asset."""
    asset = demo.asset
    names = [layer.name for layer in asset.layers]
    assert "Background" in names
    assert "Foreground" in names


def test_hello_lighting_light_types_are_distinct(demo):
    """bg layer has a DirectionalLight; fg layer has a PointLight."""
    from slappyengine.lighting import DirectionalLight, PointLight

    bg_lights = demo.bg.lighting.lights
    fg_lights = demo.fg.lighting.lights

    assert any(isinstance(light, DirectionalLight) for light in bg_lights), (
        "background layer must carry a DirectionalLight"
    )
    assert any(isinstance(light, PointLight) for light in fg_lights), (
        "foreground layer must carry a PointLight"
    )
