"""Smoke tests for ``examples/hello_render_real_hud.py`` (OO3 sprint).

The combined MM7 + LL1 + NN3 demo:

* Loads the procedural bunny mesh via :meth:`App.load_model`.
* Mounts the default game HUD via :meth:`App.enable_hud`.
* Fires :meth:`App.take_screenshot` exactly once at frame 60.
* Runs 120 headless frames and writes a YAML trace stream.

These tests pin:

* Demo imports cleanly.
* ``main()`` runs headlessly to 120 frames.
* Trace YAML has >= 120 frames of ``rotation`` events.
* Trace records a single ``hud_mount`` event with >= 5 widgets.
* Trace records exactly one ``screenshot_saved`` event.

Skips cleanly when the bunny asset is missing (e.g. someone stripped
``examples/assets/`` from the checkout).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_render_real_hud.py"
)
_BUNNY_OBJ = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "assets" / "bunny_low.obj"
)


def _load_demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo not present: {_DEMO_PATH}")
    if not _BUNNY_OBJ.is_file():
        pytest.skip(f"bunny asset missing: {_BUNNY_OBJ}")
    spec = importlib.util.spec_from_file_location(
        "hello_render_real_hud_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_render_real_hud_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Test 1: demo imports + advertises the expected entry point.
# ---------------------------------------------------------------------------


def test_hello_render_real_hud_imports(demo):
    assert hasattr(demo, "main")
    assert callable(demo.main)


# ---------------------------------------------------------------------------
# Test 2: main() runs end-to-end and returns a populated summary.
# ---------------------------------------------------------------------------


def test_hello_render_real_hud_runs_end_to_end(demo, tmp_path):
    trace_path = tmp_path / "hello_render_real_hud_trace.yaml"
    shot_path = tmp_path / "bunny_hud_screenshot.png"
    summary = demo.main(
        max_frames=120,
        screenshot_frame=60,
        screenshot_path=shot_path,
        trace_yaml_path=trace_path,
    )
    assert isinstance(summary, dict)
    assert summary["frame_count"] == 120
    assert summary["screenshot_fired"] is True
    assert summary["hud_widget_count"] >= 5


# ---------------------------------------------------------------------------
# Test 3: trace YAML has >= 120 frames of rotation events.
# ---------------------------------------------------------------------------


def test_hello_render_real_hud_trace_has_120_frames(demo, tmp_path):
    import yaml

    trace_path = tmp_path / "trace.yaml"
    shot_path = tmp_path / "bunny.png"
    demo.main(
        max_frames=120,
        screenshot_frame=60,
        screenshot_path=shot_path,
        trace_yaml_path=trace_path,
    )
    loaded = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    rotation_events = [
        ev for ev in loaded["events"]
        if isinstance(ev, list) and ev and ev[0] == "rotation"
    ]
    assert len(rotation_events) >= 120, (
        f"expected >= 120 rotation events, got {len(rotation_events)}"
    )


# ---------------------------------------------------------------------------
# Test 4: trace records a hud_mount event with >= 5 widgets.
# ---------------------------------------------------------------------------


def test_hello_render_real_hud_records_hud_mount(demo, tmp_path):
    import yaml

    trace_path = tmp_path / "trace.yaml"
    shot_path = tmp_path / "bunny.png"
    demo.main(
        max_frames=120,
        screenshot_frame=60,
        screenshot_path=shot_path,
        trace_yaml_path=trace_path,
    )
    loaded = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    mounts = [
        ev for ev in loaded["events"]
        if isinstance(ev, list) and ev and ev[0] == "hud_mount"
    ]
    assert len(mounts) == 1, f"expected exactly one hud_mount event, got {len(mounts)}"
    # Second slot is the widget count from hud_bridge.mount_hud.
    assert int(mounts[0][1]) >= 5


# ---------------------------------------------------------------------------
# Test 5: trace records exactly one screenshot_saved event.
# ---------------------------------------------------------------------------


def test_hello_render_real_hud_records_one_screenshot(demo, tmp_path):
    import yaml

    trace_path = tmp_path / "trace.yaml"
    shot_path = tmp_path / "bunny.png"
    demo.main(
        max_frames=120,
        screenshot_frame=60,
        screenshot_path=shot_path,
        trace_yaml_path=trace_path,
    )
    loaded = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    shots = [
        ev for ev in loaded["events"]
        if isinstance(ev, list) and ev and ev[0] == "screenshot_saved"
    ]
    assert len(shots) == 1, (
        f"expected exactly one screenshot_saved event, got {len(shots)}"
    )
    # First payload slot is the requested screenshot path.
    assert str(shot_path) in str(shots[0][1])
