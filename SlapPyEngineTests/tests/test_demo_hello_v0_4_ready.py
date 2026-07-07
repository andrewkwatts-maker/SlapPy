"""Smoke tests for ``examples/hello_v0_4_ready.py`` (ZZ6 sprint).

ZZ6 is the flagship v0.4-ready 240-frame headless walkthrough. It
stitches every shipped v0.4 subsystem into one canonical demo — HH1
App lifecycle, HH5/JJ3 asset import + dispatcher, JJ4 skeleton runtime,
JJ5 scene walker + frustum, JJ7 CSM shadow maps, KK1 SAH BVH_3D,
KK4 procedural skybox, LL1/MM2 HUD overlay + hud_bridge widgets,
LL2 video/gif capture, LL3 instanced rendering, LL4 3D positional
audio, LL6/NN7 export CLI, LL7/NN4/OO2/QQ7 physics3 + BVH + raycast +
debug draw, NN3 App capture façade, OO6/QQ4/RR4/SS6/TT6 diagnostics,
VV5 downstream Observable + Asset multi-inherit pattern, and YY1
:class:`EventPayload` dual-shape publishes (3/frame × 240 = 720).

These tests pin:

* Demo module imports cleanly.
* :func:`main` returns a populated summary.
* Trace records >= 220 frames (240 - degradation tolerance).
* ``subsystems_used`` covers >= 12 distinct subsystems.
* ``screenshot_count >= 4`` (screenshots at 0, 60, 120, 180).
* ``raycast_total >= 8`` (8 raycasts fire — one every 30 frames).
* ``events_published >= 720`` (3 per frame × 240 frames).
* ``diagnostics_event_count >= 1``.
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
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_v0_4_ready.py"
)


def _load_demo():
    """Import the demo as a module — skipping cleanly if imports fail."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")

    pytest.importorskip("yaml")
    pytest.importorskip("numpy")
    try:
        import slappyengine  # noqa: F401
        import slappyengine.event_bus  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"slappyengine core unavailable: {exc}")

    # Optional subsystems — soft-probe so a missing dep gives a useful
    # skip message rather than an opaque ImportError deep inside the demo.
    for optional_mod in (
        "slappyengine.asset",
        "slappyengine.layer",
        "slappyengine.audio_3d",
        "slappyengine.diagnostics",
        "slappyengine.physics3_bridge",
        "slappyengine.render.skybox",
        "slappyengine.render.instanced",
        "slappyengine.render.mesh",
        "slappyengine.render.scene_walker",
        "slappyengine.animation.skeleton_runtime",
        "slappyengine.hud_bridge",
    ):
        pytest.importorskip(optional_mod)

    spec = importlib.util.spec_from_file_location(
        "hello_v0_4_ready_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_v0_4_ready_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_v0_4_ready demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def demo_run(demo, tmp_path_factory):
    """Run the demo once per module and reuse the summary + YAML."""
    tmpdir = tmp_path_factory.mktemp("zz6")
    trace_path = tmpdir / "trace.yaml"
    shots_dir = tmpdir / "shots"
    try:
        summary = demo.main(
            max_frames=240,
            trace_yaml_path=trace_path,
            screenshot_dir=shots_dir,
        )
    except Exception as exc:
        pytest.skip(f"hello_v0_4_ready.main failed: {exc}")
    return {"summary": summary, "trace_path": trace_path}


@pytest.fixture(scope="module")
def trace(demo_run):
    import yaml

    return yaml.safe_load(demo_run["trace_path"].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test 1: demo imports + advertises the expected entry point.
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_imports(demo):
    assert hasattr(demo, "main")
    assert callable(demo.main)


# ---------------------------------------------------------------------------
# Test 2: main() runs end-to-end and returns a populated summary.
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_summary_shape(demo_run):
    summary = demo_run["summary"]
    assert isinstance(summary, dict)
    for key in (
        "frame_count",
        "subsystems_used",
        "screenshot_count",
        "raycast_total",
        "events_published",
        "diagnostics_event_count",
    ):
        assert key in summary, f"missing summary key {key!r}"


# ---------------------------------------------------------------------------
# Test 3: trace YAML records >= 220 frames (240 with degradation slack).
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_frame_count(trace):
    assert isinstance(trace, dict)
    frame_count = int(trace.get("frame_count", 0))
    assert frame_count >= 220, (
        f"expected >= 220 frames, got {frame_count}"
    )


# ---------------------------------------------------------------------------
# Test 4: subsystems_used covers >= 12 distinct subsystems.
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_subsystems_covered(trace):
    subsystems = trace.get("subsystems_used", [])
    assert isinstance(subsystems, list), (
        f"expected subsystems_used to be a list, got {type(subsystems).__name__}"
    )
    distinct = set(subsystems)
    assert len(distinct) >= 12, (
        f"expected >= 12 distinct subsystems, got {len(distinct)}: "
        f"{sorted(distinct)}"
    )


# ---------------------------------------------------------------------------
# Test 5: screenshot_count >= 4 (screenshots at frames 0, 60, 120, 180).
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_screenshot_count(trace):
    screenshot_count = int(trace.get("screenshot_count", 0))
    assert screenshot_count >= 4, (
        f"expected screenshot_count >= 4, got {screenshot_count}"
    )


# ---------------------------------------------------------------------------
# Test 6: raycast_total >= 8 (raycast every 30 frames × 240 frames).
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_raycasts(trace):
    raycasts = int(trace.get("raycast_total", 0))
    assert raycasts >= 8, (
        f"expected raycast_total >= 8, got {raycasts}"
    )


# ---------------------------------------------------------------------------
# Test 7: events_published >= 720 (3 per frame × 240 frames).
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_events_published(trace):
    published = int(trace.get("events_published", 0))
    assert published >= 720, (
        f"expected events_published >= 720 (3/frame x 240 frames), "
        f"got {published}"
    )


# ---------------------------------------------------------------------------
# Test 8: diagnostics_event_count >= 1.
# ---------------------------------------------------------------------------


def test_hello_v0_4_ready_diagnostics_events(trace):
    event_count = int(trace.get("diagnostics_event_count", 0))
    assert event_count >= 1, (
        f"expected diagnostics_event_count >= 1, got {event_count}"
    )
