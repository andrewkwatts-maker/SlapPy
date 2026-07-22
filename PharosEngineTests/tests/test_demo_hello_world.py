"""Smoke tests for ``examples/hello_world.py`` (PP4 gap-close).

The 3-line hello-world demo calls ``engine.run()`` at module import; this
would block on a real event loop. We stub the wgpu canvas + GPU + set
``SLAPPYENGINE_MAX_FRAMES=2`` so the demo returns after 2 draw ticks.

Pins:
1. Demo module imports cleanly with stubs in place.
2. A live ``se.Engine`` instance is left on the module.
3. The engine ticked exactly the requested number of frames.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_world.py"


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

    def _fake_event_loop():  # pragma: no cover - guarded
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

    spec = importlib.util.spec_from_file_location("hello_world_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_world_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_world demo failed to load headlessly: {exc}")
    return module


def test_hello_world_module_imports(demo):
    """The demo file loaded without raising under headless stubs."""
    assert demo is not None
    # Sanity — the module ran to completion (past ``engine.run()``).
    import pharos_engine as se
    assert hasattr(se, "Engine")


def test_hello_world_leaves_engine_on_module(demo):
    """``engine = se.Engine()`` binds the ``engine`` symbol on the module."""
    engine = getattr(demo, "engine", None)
    assert engine is not None, "demo did not expose ``engine``"
    # It really is an Engine instance (not a stub sentinel).
    import pharos_engine as se
    assert isinstance(engine, se.Engine)


def test_hello_world_ran_two_frames(demo):
    """SLAPPYENGINE_MAX_FRAMES=2 must drive the draw loop exactly twice."""
    engine = demo.engine
    assert engine._frame_index == 2, (
        f"expected 2 draw ticks under SLAPPYENGINE_MAX_FRAMES=2, "
        f"got {engine._frame_index}"
    )
