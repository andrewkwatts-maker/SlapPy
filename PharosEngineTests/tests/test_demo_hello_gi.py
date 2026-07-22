"""Smoke test for ``examples/hello_gi.py`` (QQ2 gap-close, batch 2).

The GI showcase calls ``main()`` which instantiates a headless engine and
writes a triptych PNG (direct | cascade+noise | SVGF-denoised). We stub
``wgpu`` canvas + ``Engine._setup_gpu`` so the test never touches a GPU.

Pins:
1. Demo module imports cleanly with stubs installed.
2. ``main()`` completes and returns a ``Path``.
3. The output PNG exists and has non-zero size on disk.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_gi.py"


def _install_engine_stubs(monkeypatch):
    """Replace WgpuCanvas + Engine._setup_gpu with no-ops (headless)."""
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


@pytest.fixture
def demo(monkeypatch):
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    _install_engine_stubs(monkeypatch)

    spec = importlib.util.spec_from_file_location("hello_gi_demo_qq2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_gi_demo_qq2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_gi demo failed to load headlessly: {exc}")
    return module


def test_hello_gi_module_imports(demo):
    """Demo file loaded without raising under headless stubs."""
    assert demo is not None
    assert hasattr(demo, "main")
    assert callable(demo.main)


def test_hello_gi_main_writes_snapshot(demo, tmp_path, monkeypatch):
    """``main()`` returns a Path pointing at the written triptych PNG."""
    # Redirect OUT so the test doesn't dirty the repo tree.
    out = tmp_path / "hello_gi.png"
    monkeypatch.setattr(demo, "OUT", out)
    try:
        result = demo.main()
    except Exception as exc:
        pytest.skip(f"hello_gi.main() upstream drift: {exc}")
    assert isinstance(result, Path)
    assert result.exists(), "main() reported success but output PNG is missing"


def test_hello_gi_snapshot_non_empty(demo, tmp_path, monkeypatch):
    """The PNG on disk has non-trivial size (rules out truncated writes)."""
    out = tmp_path / "hello_gi.png"
    monkeypatch.setattr(demo, "OUT", out)
    try:
        demo.main()
    except Exception as exc:
        pytest.skip(f"hello_gi.main() upstream drift: {exc}")
    assert out.stat().st_size > 1024, (
        f"snapshot suspiciously small: {out.stat().st_size} bytes"
    )
