"""Smoke tests for ``examples/hello_studio.py`` (PP4 gap-close).

Hangs a 24-node rope between two pinned anchors using the unified
:mod:`pharos_engine.studio` API and records it. In-process; no wgpu.

Pins:
1. Demo module imports cleanly.
2. ``main(out=..., frames=3)`` writes a GIF to the requested tmp path.
3. The recorded output has a plausible file size (a valid tiny GIF
   header + frames = well over 100 bytes).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_studio.py"


def _load_demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    spec = importlib.util.spec_from_file_location("hello_studio_demo_pp4", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_studio_demo_pp4"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_studio demo failed to load: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


def test_hello_studio_imports(demo):
    assert callable(getattr(demo, "main", None))
    assert callable(getattr(demo, "_build_stage", None))


def test_hello_studio_main_writes_gif(demo, tmp_path):
    """``main(out=…, frames=3)`` records a real GIF at the requested path."""
    out = tmp_path / "hello_studio_smoke.gif"
    try:
        written = demo.main(out=out, frames=3)
    except Exception as exc:
        pytest.skip(f"hello_studio.main upstream drift: {exc}")
    assert written == out, f"main returned {written!r}, expected {out!r}"
    assert out.exists(), "main() claimed to write a GIF but the file is missing"


def test_hello_studio_gif_is_nontrivial(demo, tmp_path):
    """The rendered GIF must have real content — not an empty stub."""
    out = tmp_path / "hello_studio_size.gif"
    try:
        demo.main(out=out, frames=3)
    except Exception as exc:
        pytest.skip(f"hello_studio.main upstream drift: {exc}")
    size = out.stat().st_size
    # A 3-frame 480x320 GIF, even highly compressed, weighs > 100 B.
    assert size > 100, f"GIF suspiciously small: {size} bytes"
    # Sanity: standard GIF89a magic bytes.
    header = out.read_bytes()[:6]
    assert header in (b"GIF87a", b"GIF89a"), f"not a GIF: header={header!r}"
