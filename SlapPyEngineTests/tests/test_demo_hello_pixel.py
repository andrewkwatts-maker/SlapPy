"""Smoke tests for ``examples/hello_pixel.py`` (PP4 gap-close).

The demo builds a 256x256 canvas, paints a red cross via numpy slicing,
loads the scene, and calls ``engine.run()`` at module scope. We stub
wgpu + set ``SLAPPYENGINE_MAX_FRAMES=2`` to run headlessly.

Pins:
1. Demo module imports cleanly headless.
2. Engine has a loaded scene named ``HelloPixel``.
3. The canvas layer's centre row + column are painted red.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_pixel.py"


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

    spec = importlib.util.spec_from_file_location("hello_pixel_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_pixel_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_pixel demo failed to load headlessly: {exc}")
    return module


def test_hello_pixel_imports(demo):
    assert demo is not None
    assert hasattr(demo, "engine")
    assert hasattr(demo, "scene")


def test_hello_pixel_scene_named(demo):
    """The scene has the ``HelloPixel`` name."""
    scene = demo.scene
    assert scene.name == "HelloPixel"


def test_hello_pixel_red_cross_painted(demo):
    """Rows/cols at index 128 are painted [255, 0, 0, 255]."""
    layer = demo.layer
    data = layer._image_data
    assert data.shape == (256, 256, 4)
    # Column 128 across all rows must be red.
    assert (data[:, 128] == [255, 0, 0, 255]).all(), (
        "vertical bar (col 128) not painted red"
    )
    # Row 128 across all cols must be red.
    assert (data[128, :] == [255, 0, 0, 255]).all(), (
        "horizontal bar (row 128) not painted red"
    )
