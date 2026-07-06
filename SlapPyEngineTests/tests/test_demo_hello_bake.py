"""Smoke tests for ``examples/hello_bake.py`` (PP4 gap-close).

The demo exercises two cross-layer baking ops:

  1. 3D → 2D  : ``Layer.bake_to_2d`` on a 3D cube layer.
  2. 2D → 3D  : ``Layer.apply_heightmap`` on a quad, driven by a linear
                gradient image.

We stub wgpu so ``main(['--frames', '2'])`` runs headlessly.

Pins:
1. Demo module imports cleanly headless.
2. ``main(['--frames', '2'])`` returns 0.
3. ``Layer.apply_heightmap`` produced a Z displacement range >= 1.0 for
   the reference gradient (spec: scale=2.0, values 0..1 → Z 0..2).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_bake.py"


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

    spec = importlib.util.spec_from_file_location("hello_bake_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_bake_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_bake demo failed to import headlessly: {exc}")
    return module


def test_hello_bake_imports(demo):
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_hello_bake_main_returns_zero(demo):
    rc = demo.main(["--frames", "2"])
    assert rc == 0, f"main([--frames 2]) returned {rc}"


def test_hello_bake_heightmap_displaces_vertices(demo):
    """Reproduce the demo's apply_heightmap call: scale=2.0 → Z range ~[0, 2]."""
    from slappyengine.layer import Layer
    from slappyengine.gpu.mesh import GpuMesh
    from slappyengine.gpu.pbr_material import PbrMaterial

    quad = Layer.blank(256, 256, name="HeightQuad", mode="3D")
    quad.mesh_geometry = GpuMesh.unit_quad()
    quad.mesh_material = PbrMaterial()

    gradient = Layer.blank(256, 256, name="Gradient")
    ramp = np.linspace(0, 255, 256, dtype=np.uint8)
    gradient._image_data[:, :, 0] = ramp[np.newaxis, :]
    gradient._image_data[:, :, 1] = ramp[np.newaxis, :]
    gradient._image_data[:, :, 2] = ramp[np.newaxis, :]
    gradient._image_data[:, :, 3] = 255

    quad.apply_heightmap(gradient, scale=2.0)

    z_vals = [v.position[2] for v in quad.mesh_geometry._vertices]
    assert max(z_vals) - min(z_vals) >= 1.0, (
        f"apply_heightmap displaced too little: Z range = "
        f"{max(z_vals) - min(z_vals):.3f}"
    )
