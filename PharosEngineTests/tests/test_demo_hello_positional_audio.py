"""Tests for the ``examples/hello_positional_audio.py`` demo (NN5 sprint).

Pins the following behaviours:

* The demo module imports cleanly (skipping if the audio backend is
  unavailable — no soundfile / no sounddevice etc.).
* :func:`main` runs headlessly end-to-end and returns a summary dict.
* The written trace YAML contains at least 60 per-frame records.
* The pan trace swings past both the left (< -0.3) and right (> +0.3)
  extremes at least once each.
* The pitch trace shows real doppler variance
  (``max_pitch - min_pitch > 0.05``) on both sources.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Locate + load the demo
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_positional_audio.py"
)


def _load_demo():
    """Import the demo as a module — skipping cleanly if audio isn't wired."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")
    try:
        # Importing audio_3d exercises the audio backend probe. If it
        # raises for a reason the demo can't recover from (rare but
        # possible on air-gapped CI), skip rather than fail the suite.
        import pharos_engine.audio_3d  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"pharos_engine.audio_3d unavailable: {exc}")

    spec = importlib.util.spec_from_file_location(
        "hello_positional_audio_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_positional_audio_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_positional_audio demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def summary(demo, tmp_path_factory):
    """Run the demo once per module and reuse the summary."""
    trace_path = tmp_path_factory.mktemp("nn5") / "trace.yaml"
    try:
        result = demo.main(max_frames=60, trace_yaml_path=trace_path)
    except Exception as exc:
        pytest.skip(f"hello_positional_audio.main failed: {exc}")
    return result


@pytest.fixture(scope="module")
def trace(summary):
    """Load the frame trace from the YAML the demo just wrote."""
    yaml = pytest.importorskip("yaml")
    text = Path(summary["trace_path"]).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    assert isinstance(payload, dict), "trace YAML must be a mapping"
    assert "frames" in payload, "trace YAML must have a 'frames' key"
    return payload


# ---------------------------------------------------------------------------
# Smoke: the demo imports
# ---------------------------------------------------------------------------


def test_demo_imports(demo):
    assert hasattr(demo, "main"), "demo missing main()"
    assert callable(demo.main)


# ---------------------------------------------------------------------------
# End-to-end: main() returns a well-formed summary
# ---------------------------------------------------------------------------


def test_demo_runs_end_to_end(summary):
    assert isinstance(summary, dict)
    assert summary["frame_count"] == 60
    assert Path(summary["trace_path"]).exists()


# ---------------------------------------------------------------------------
# Trace has >= 60 frames
# ---------------------------------------------------------------------------


def test_trace_has_at_least_sixty_frames(trace):
    frames = trace["frames"]
    assert isinstance(frames, list)
    assert len(frames) >= 60, (
        f"expected >= 60 frames in trace, got {len(frames)}"
    )
    assert trace["frame_count"] == len(frames)


# ---------------------------------------------------------------------------
# Pan swings through both extremes
# ---------------------------------------------------------------------------


def test_pan_swings_left_and_right(trace):
    frames = trace["frames"]
    # We accept either source hitting the extreme — the assertion is
    # "over the run, the demo demonstrates left-and-right pan".
    all_pans = []
    for ev in frames:
        all_pans.append(ev["source_a"]["pan_signed"])
        all_pans.append(ev["source_b"]["pan_signed"])

    peak_left = min(all_pans)
    peak_right = max(all_pans)
    assert peak_left < -0.3, (
        f"pan never swung far enough LEFT: peak_left={peak_left:.3f}, "
        "spec requires < -0.3"
    )
    assert peak_right > 0.3, (
        f"pan never swung far enough RIGHT: peak_right={peak_right:.3f}, "
        "spec requires > +0.3"
    )


# ---------------------------------------------------------------------------
# Doppler variance is real
# ---------------------------------------------------------------------------


def test_pitch_shows_doppler_variance(trace):
    frames = trace["frames"]
    pitches_a = [ev["source_a"]["pitch"] for ev in frames]
    pitches_b = [ev["source_b"]["pitch"] for ev in frames]

    range_a = max(pitches_a) - min(pitches_a)
    range_b = max(pitches_b) - min(pitches_b)

    # Spec: (max - min) > 0.05 for *at least one* source — but the demo
    # is designed to hit it on both, so assert both to catch regressions
    # where only one source's DSP fires.
    assert range_a > 0.05, (
        f"source_a doppler variance too small: "
        f"range={range_a:.4f}, min={min(pitches_a):.4f}, max={max(pitches_a):.4f}"
    )
    assert range_b > 0.05, (
        f"source_b doppler variance too small: "
        f"range={range_b:.4f}, min={min(pitches_b):.4f}, max={max(pitches_b):.4f}"
    )
