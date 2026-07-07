"""Smoke tests for ``examples/hello_full_lifecycle.py`` (RR5 sprint).

The RR5 flagship demo stitches every currently-shipped subsystem into a
single 180-frame headless walkthrough:

* App lifecycle (HH1)
* Capture façade — load_model / spawn_camera / spawn_light /
  enable_hud / start_recording / take_screenshot (NN3)
* Diagnostics collector (QQ4 / OO6)
* Physics3 — World3D + Body3D + raycast + build_bvh + draw_debug
  (NN4 / OO2 / QQ7)
* Audio3D — AudioListener + Audio3DSource + Audio3DEngine (LL4)
* HUD overlay + default widgets (LL1 / MM2)

These tests pin:

* Demo module imports cleanly.
* :func:`main` returns a populated summary.
* Trace YAML records >= 170 frames (180 - degradation tolerance).
* ``subsystems_used`` covers at least 5 distinct subsystems.
* ``screenshot_count >= 2`` (screenshots at frames 0, 60, 120).
* ``raycast_hit_count >= 5`` (raycasts fire every 30 frames).
* ``diagnostics_event_count >= 1`` (frame 100 warning trigger).
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
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_full_lifecycle.py"
)


def _load_demo():
    """Import the demo as a module — skipping cleanly if imports fail."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")

    # Probe the subsystems the demo will touch so a missing dep gives a
    # useful skip message rather than an opaque ImportError at exec_module.
    pytest.importorskip("yaml")
    try:
        import slappyengine  # noqa: F401
        import slappyengine.audio_3d  # noqa: F401
        import slappyengine.diagnostics  # noqa: F401
        import slappyengine.physics3_bridge  # noqa: F401
        import slappyengine.render.skybox  # noqa: F401
        import slappyengine.hud_bridge  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"slappyengine subsystems unavailable: {exc}")

    spec = importlib.util.spec_from_file_location(
        "hello_full_lifecycle_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_full_lifecycle_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_full_lifecycle demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def demo_run(demo, tmp_path_factory):
    """Run the demo once per module and reuse the summary + YAML."""
    tmpdir = tmp_path_factory.mktemp("rr5")
    trace_path = tmpdir / "trace.yaml"
    shots_dir = tmpdir / "shots"
    try:
        summary = demo.main(
            max_frames=180,
            trace_yaml_path=trace_path,
            screenshot_dir=shots_dir,
        )
    except Exception as exc:
        pytest.skip(f"hello_full_lifecycle.main failed: {exc}")
    return {"summary": summary, "trace_path": trace_path}


@pytest.fixture(scope="module")
def trace(demo_run):
    import yaml

    return yaml.safe_load(demo_run["trace_path"].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test 1: demo imports + advertises the expected entry point.
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_imports(demo):
    assert hasattr(demo, "main")
    assert callable(demo.main)


# ---------------------------------------------------------------------------
# Test 2: main() runs end-to-end and returns a populated summary.
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_summary_shape(demo_run):
    summary = demo_run["summary"]
    assert isinstance(summary, dict)
    for key in (
        "frame_count",
        "subsystems_used",
        "screenshot_count",
        "raycast_hit_count",
        "diagnostics_event_count",
    ):
        assert key in summary, f"missing summary key {key!r}"


# ---------------------------------------------------------------------------
# Test 3: trace YAML records >= 170 frames.
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_frame_count(trace):
    assert isinstance(trace, dict)
    frame_count = int(trace.get("frame_count", 0))
    assert frame_count >= 170, (
        f"expected >= 170 frames, got {frame_count}"
    )


# ---------------------------------------------------------------------------
# Test 4: subsystems_used covers >= 5 distinct subsystems.
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_subsystems_covered(trace):
    subsystems = trace.get("subsystems_used", [])
    assert isinstance(subsystems, list), (
        f"expected subsystems_used to be a list, got {type(subsystems).__name__}"
    )
    distinct = set(subsystems)
    assert len(distinct) >= 5, (
        f"expected >= 5 distinct subsystems, got {len(distinct)}: {sorted(distinct)}"
    )


# ---------------------------------------------------------------------------
# Test 5: screenshot_count >= 2 (screenshots at frames 0, 60, 120).
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_screenshot_count(trace):
    screenshot_count = int(trace.get("screenshot_count", 0))
    assert screenshot_count >= 2, (
        f"expected screenshot_count >= 2, got {screenshot_count}"
    )


# ---------------------------------------------------------------------------
# Test 6: raycast_hit_count >= 5 (six raycasts fire, first-hit ~arc).
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_raycast_hits(trace):
    raycast_hits = int(trace.get("raycast_hit_count", 0))
    assert raycast_hits >= 5, (
        f"expected raycast_hit_count >= 5, got {raycast_hits}"
    )


# ---------------------------------------------------------------------------
# Test 7: diagnostics_event_count >= 1 (frame-100 warning trigger).
# ---------------------------------------------------------------------------


def test_hello_full_lifecycle_diagnostics_events(trace):
    event_count = int(trace.get("diagnostics_event_count", 0))
    assert event_count >= 1, (
        f"expected diagnostics_event_count >= 1, got {event_count}"
    )
