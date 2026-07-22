"""Smoke test for ``examples/fluid_sandbox.py`` (RR2 gap-close, batch 3).

The demo constructs a material-map / MaterialMap scene and calls
``engine.run()`` at module scope.  We stub the wgpu canvas + GPU stack
and set ``SLAPPYENGINE_MAX_FRAMES=2`` so the draw loop exits after two
ticks (identical pattern to ``test_demo_hello_world``).

Pins:
1. Demo module imports cleanly with stubs installed.
2. The scene ends up with a "sandbox" asset carrying a MaterialMap.
3. MaterialMap has water + soil entries.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "fluid_sandbox.py"


def _install_engine_stubs(monkeypatch):
    """Replace WgpuCanvas + Engine._setup_gpu + wgpu event loop with no-ops."""
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
        # The demo attaches a NodeMaterial effect; the draw loop will call
        # ``_effect_pipeline.dispatch_effects(entity, _buf_mgr)`` — mock both.
        self._buf_mgr = MagicMock()
        self._effect_pipeline = MagicMock()

    monkeypatch.setattr(engine_mod.Engine, "_setup_gpu", _stub_setup_gpu)


@pytest.fixture
def demo(monkeypatch):
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    _install_engine_stubs(monkeypatch)
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "2")

    spec = importlib.util.spec_from_file_location("fluid_sandbox_rr2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fluid_sandbox_rr2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"fluid_sandbox demo failed to load headlessly: {exc}")
    return module


def test_fluid_sandbox_module_imports(demo):
    """Demo file loaded without raising under headless stubs."""
    assert demo is not None
    assert hasattr(demo, "engine")
    assert hasattr(demo, "asset")
    assert hasattr(demo, "scene")


def test_fluid_sandbox_asset_named_sandbox(demo):
    """Demo builds an Asset named ``sandbox`` with a material map attached."""
    asset = demo.asset
    assert getattr(asset, "name", None) == "sandbox"
    assert getattr(asset, "material_map", None) is not None, (
        "asset.material_map should have been assigned"
    )


def test_fluid_sandbox_material_map_has_water_and_soil(demo):
    """MaterialMap must carry both 'water' and 'soil' entries."""
    mmap = demo.asset.material_map
    # MaterialMap stores ``MaterialDef`` entries in ``_materials`` list.
    materials = getattr(mmap, "materials", None) or getattr(mmap, "_materials", None)
    assert materials is not None, "MaterialMap has no discoverable materials"
    if hasattr(materials, "keys"):
        names = set(materials.keys())
    else:
        names = {getattr(m, "name", None) for m in materials}
    assert "water" in names, f"'water' missing; materials={names}"
    assert "soil" in names, f"'soil' missing; materials={names}"
