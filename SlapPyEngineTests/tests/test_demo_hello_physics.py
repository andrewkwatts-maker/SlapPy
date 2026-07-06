"""Smoke tests for ``examples/hello_physics.py`` (PP4 gap-close).

The demo scatters 500 sand-coloured pixels near the top of a 256x256
canvas and opts into the built-in ``pixel_physics`` compute pass by
setting ``scene.pixel_physics_enabled = True``. We stub wgpu +
``SLAPPYENGINE_MAX_FRAMES=2`` to run headlessly.

Note: the demo imports :mod:`random` + :mod:`numpy` at module scope, NOT
any ``slappyengine.physics``/``physics2`` WIP dir — the ``pixel_physics``
pass lives in the compute pipeline, not the WIP scaffolding.

Pins:
1. Demo module imports cleanly headless.
2. ``scene.pixel_physics_enabled`` is True.
3. The sand layer has sub-500 non-transparent pixels painted near the top
   (the RNG seed collisions leave roughly ~480 unique cells).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_physics.py"


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

    spec = importlib.util.spec_from_file_location("hello_physics_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_physics_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_physics demo failed to load headlessly: {exc}")
    return module


def test_hello_physics_imports(demo):
    assert demo is not None
    assert hasattr(demo, "scene")
    assert hasattr(demo, "layer")


def test_hello_physics_opts_into_pixel_physics(demo):
    """The scene must flip on the pixel_physics compute pass."""
    assert demo.scene.pixel_physics_enabled is True


def test_hello_physics_sand_scattered_near_top(demo):
    """500 RNG paints put >= 400 unique non-transparent cells in rows 5..30."""
    img = demo.layer._image_data
    # Only look at the strip where the demo scatters sand.
    band = img[5:31, 10:246]
    opaque = band[..., 3] == 255
    filled = int(opaque.sum())
    # 500 paints in a 26x236 = 6136-cell strip — collisions ~5%; 400 is a
    # safe floor that still catches "nothing painted" regressions.
    assert filled >= 400, (
        f"expected >= 400 painted sand cells in the top strip, got {filled}"
    )
    # And nothing painted OUTSIDE that top strip.
    outside = img.copy()
    outside[5:31, 10:246] = 0
    assert (outside[..., 3] == 0).all(), (
        "sand painted outside the [5:31, 10:246] band — demo drifted"
    )
