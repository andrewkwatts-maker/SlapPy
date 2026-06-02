"""Tests for the ``examples/hello_audio.py`` demo.

Pins four behaviours of the audio fallback demo:

1. ``main(no_wait=True)`` runs cleanly in-process and never raises,
   regardless of whether ``sounddevice`` is installed.
2. ``audio_runtime.get_backend().is_real()`` returns a ``bool`` — either
   the real backend or the stub is always available.
3. Calling ``play_buffer`` with the synthesised samples does not raise
   on either backend.
4. The rendered waveform PNG reproduces a stable golden master via
   :func:`slappyengine.testing.assert_scene_matches`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from slappyengine import audio_runtime
from slappyengine.testing import assert_scene_matches

# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_audio.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "hello_audio_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_audio_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: demo runs cleanly with --no-wait (headless)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_audio_runs_without_error(demo, tmp_path):
    """``main(no_wait=True)`` returns a populated summary and never raises."""
    summary = demo.main(
        no_wait=True,
        render=False,
        out=tmp_path / "ignored.png",
    )
    assert summary["samples_len"] == int(
        round(demo.DEFAULT_SR * demo.DEFAULT_DURATION_S)
    )
    assert summary["sample_rate"] == demo.DEFAULT_SR
    assert summary["freq_hz"] == pytest.approx(demo.DEFAULT_FREQ_HZ)
    assert summary["no_wait"] is True
    # Whichever backend is in play, mode must be one of the two strings.
    assert summary["mode"] in {"played", "stubbed"}
    # No-wait path is fast — orders of magnitude under the buffer duration.
    assert summary["elapsed_s"] >= 0.0
    assert summary["elapsed_s"] < demo.DEFAULT_DURATION_S
    # is_real reflects the current backend selection.
    assert isinstance(summary["is_real"], bool)


# ────────────────────────────────────────────────────────────────────────────
# Test 2: backend is_real() returns a bool
# ────────────────────────────────────────────────────────────────────────────

def test_backend_is_either_real_or_stub():
    """``get_backend().is_real()`` must always return a ``bool``."""
    backend = audio_runtime.get_backend()
    result = backend.is_real()
    # Strict bool, not just truthy — the protocol promises a boolean.
    assert isinstance(result, bool)


# ────────────────────────────────────────────────────────────────────────────
# Test 3: play_buffer accepts synthesised samples without raising
# ────────────────────────────────────────────────────────────────────────────

def test_play_buffer_does_not_raise(demo):
    """``play_buffer`` must accept the synthesised float32 buffer cleanly.

    The real backend may swallow device errors internally; the stub is a
    no-op. Either way, no exception is allowed to escape.
    """
    samples = demo.synthesize_sine(
        freq_hz=demo.DEFAULT_FREQ_HZ,
        sample_rate=demo.DEFAULT_SR,
        duration_s=0.05,   # short — keep the test snappy even on the real path
    )
    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert samples.size == int(round(demo.DEFAULT_SR * 0.05))

    backend = audio_runtime.get_backend()
    # Must not raise on either backend.
    backend.play_buffer(samples, demo.DEFAULT_SR)
    backend.stop_all()


# ────────────────────────────────────────────────────────────────────────────
# Test 4: visual baseline (golden-master)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_audio_visual_baseline(demo):
    """Render the waveform visualisation and diff against the baseline PNG.

    First run writes ``python/slappyengine/testing/baselines/hello_audio.png``
    and passes; subsequent runs require a max per-channel diff <= 0.05.
    """
    samples = demo.synthesize_sine(
        freq_hz=demo.DEFAULT_FREQ_HZ,
        sample_rate=demo.DEFAULT_SR,
        duration_s=demo.DEFAULT_DURATION_S,
    )
    rendered = demo._render_waveform(samples, sample_rate=demo.DEFAULT_SR)
    assert rendered.dtype == np.uint8
    assert rendered.shape == (demo.RENDER_H, demo.RENDER_W, 4)

    scene = SimpleNamespace(_image_data=rendered)
    assert_scene_matches(
        scene,
        "hello_audio",
        tolerance=0.05,
        width=demo.RENDER_W,
        height=demo.RENDER_H,
    )
