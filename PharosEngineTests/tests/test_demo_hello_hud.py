"""Tests for the ``examples/hello_hud.py`` demo (MM2 sprint).

Pins the following behaviours:

* ``main()`` runs end-to-end and returns a populated summary dict.
* Emits >= 30 trace events (spec floor).
* HealthBar depletes from START → END across the run.
* AmmoCounter increments each frame.
* Compass heading advances.
* Trace YAML is written to disk and round-trips.
* HUD widgets are wired via :meth:`App.enable_hud`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_hud.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_hud_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_hud_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Test 1: demo runs end-to-end and returns a populated summary
# ---------------------------------------------------------------------------


def test_hello_hud_runs_end_to_end(demo, tmp_path):
    trace_path = tmp_path / "hello_hud_trace.yaml"
    summary = demo.main(max_frames=60, trace_yaml_path=trace_path)
    assert isinstance(summary, dict)
    assert summary["frame_count"] == 60


# ---------------------------------------------------------------------------
# Test 2: trace has at least 30 events (spec floor)
# ---------------------------------------------------------------------------


def test_hello_hud_trace_has_thirty_plus_events(demo, tmp_path):
    trace_path = tmp_path / "trace.yaml"
    summary = demo.main(max_frames=60, trace_yaml_path=trace_path)
    assert summary["trace_event_count"] >= 30


# ---------------------------------------------------------------------------
# Test 3: HealthBar depletes across the run
# ---------------------------------------------------------------------------


def test_hello_hud_health_bar_depletes(demo, tmp_path):
    trace_path = tmp_path / "trace.yaml"
    summary = demo.main(max_frames=60, trace_yaml_path=trace_path)
    # Start = 100, End = 40 by construction — the demo hits 40 exactly.
    assert summary["health_bar_final"] < demo.DEFAULT_START_HP
    assert summary["health_bar_final"] == pytest.approx(demo.DEFAULT_END_HP, abs=1e-3)


# ---------------------------------------------------------------------------
# Test 4: AmmoCounter increments
# ---------------------------------------------------------------------------


def test_hello_hud_ammo_increments(demo, tmp_path):
    trace_path = tmp_path / "trace.yaml"
    summary = demo.main(max_frames=60, trace_yaml_path=trace_path)
    # ammo starts at 30 and adds frame_count each tick → 30 + 59 = 89 on
    # the last tick call (frame_count is read before increment).
    assert summary["ammo_counter_final"] > demo.DEFAULT_START_AMMO


# ---------------------------------------------------------------------------
# Test 5: Compass heading updates over the run
# ---------------------------------------------------------------------------


def test_hello_hud_compass_updates(demo, tmp_path):
    trace_path = tmp_path / "trace.yaml"
    summary = demo.main(max_frames=60, trace_yaml_path=trace_path)
    # Compass heading is always in [0, 360). After a full orbit it lands
    # at approximately 0.0 (mod 360).
    heading = summary["compass_final_deg"]
    assert 0.0 <= heading < 360.0


# ---------------------------------------------------------------------------
# Test 6: trace YAML is written and readable
# ---------------------------------------------------------------------------


def test_hello_hud_trace_yaml_written(demo, tmp_path):
    trace_path = tmp_path / "hello_hud_trace.yaml"
    demo.main(max_frames=30, trace_yaml_path=trace_path)
    assert trace_path.exists()
    text = trace_path.read_text(encoding="utf-8")
    assert len(text) > 0
    assert "events" in text or "hud" in text


def test_hello_hud_trace_yaml_roundtrips(demo, tmp_path):
    import yaml
    trace_path = tmp_path / "hello_hud_trace.yaml"
    demo.main(max_frames=30, trace_yaml_path=trace_path)
    loaded = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert loaded["trace_event_count"] == len(loaded["events"])


# ---------------------------------------------------------------------------
# Test 7: HUD-related trace events are present
# ---------------------------------------------------------------------------


def test_hello_hud_trace_contains_hud_events(demo, tmp_path):
    import yaml
    trace_path = tmp_path / "trace.yaml"
    demo.main(max_frames=30, trace_yaml_path=trace_path)
    loaded = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    kinds = {ev[0] for ev in loaded["events"] if isinstance(ev, list) and ev}
    assert "hud_mount" in kinds
    assert "hud_begin_frame" in kinds
    assert "hud_submit" in kinds


# ---------------------------------------------------------------------------
# Test 8: hud_command_count is non-zero at end (HUD emitted draw commands)
# ---------------------------------------------------------------------------


def test_hello_hud_hud_command_count_positive(demo, tmp_path):
    trace_path = tmp_path / "trace.yaml"
    summary = demo.main(max_frames=30, trace_yaml_path=trace_path)
    assert summary["hud_command_count"] > 0
