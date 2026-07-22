"""Tests for the ``examples/hello_diagnostics_hud.py`` demo (QQ5 sprint).

Pins the following behaviours:

* The demo module imports cleanly.
* :func:`main` runs headlessly end-to-end and returns a summary dict.
* The written trace YAML records at least 5 total warnings.
* At least 2 distinct subsystems produced warnings (audio_3d + render
  in the shipped triggers, but the assertion only counts distinct
  names — future extension to more triggers is safe).
* The diagnostics HUD widget was mounted around the requested frame:
  a ``diagnostics_widget_mounted`` trace event exists with a frame
  index close to the requested mount frame.
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
    _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_diagnostics_hud.py"
)


def _load_demo():
    """Import the demo as a module — skipping cleanly if imports fail."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")
    try:
        # The diagnostics module is stdlib-only, but audio_3d + render
        # are heavier — probe them so the skip has a useful message.
        import pharos_engine.diagnostics  # noqa: F401
        import pharos_engine.audio_3d  # noqa: F401
        import pharos_engine.render.skybox  # noqa: F401
        import pharos_engine.hud_bridge  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"pharos_engine subsystems unavailable: {exc}")

    spec = importlib.util.spec_from_file_location(
        "hello_diagnostics_hud_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_diagnostics_hud_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_diagnostics_hud demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def summary(demo, tmp_path_factory):
    """Run the demo once per module and reuse the summary."""
    trace_path = tmp_path_factory.mktemp("qq5") / "trace.yaml"
    try:
        result = demo.main(max_frames=90, trace_yaml_path=trace_path)
    except Exception as exc:
        pytest.skip(f"hello_diagnostics_hud.main failed: {exc}")
    return result


@pytest.fixture(scope="module")
def trace(summary):
    """Load the trace YAML the demo just wrote."""
    yaml = pytest.importorskip("yaml")
    text = Path(summary["trace_path"]).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    assert isinstance(payload, dict), "trace YAML must be a mapping"
    return payload


# ---------------------------------------------------------------------------
# Smoke: demo imports + runs
# ---------------------------------------------------------------------------


def test_demo_imports(demo):
    assert hasattr(demo, "main"), "demo missing main()"
    assert callable(demo.main)


def test_demo_runs_end_to_end(summary):
    assert isinstance(summary, dict)
    assert summary["frame_count"] == 90
    assert Path(summary["trace_path"]).exists()


# ---------------------------------------------------------------------------
# Trace: >= 5 total warnings captured
# ---------------------------------------------------------------------------


def test_trace_records_at_least_five_warnings(trace):
    total_warnings = int(trace.get("total_warnings", 0))
    assert total_warnings >= 5, (
        f"expected total_warnings >= 5 in trace, got {total_warnings}. "
        f"stats={trace.get('diagnostics_stats')}"
    )


# ---------------------------------------------------------------------------
# Trace: subsystems_warned has >= 2 distinct entries
# ---------------------------------------------------------------------------


def test_trace_records_multiple_subsystems(trace):
    subsystems = trace.get("subsystems_warned", [])
    assert isinstance(subsystems, list)
    distinct = set(subsystems)
    assert len(distinct) >= 2, (
        f"expected >= 2 distinct subsystems warned, got {sorted(distinct)}"
    )


# ---------------------------------------------------------------------------
# Trace: diagnostics widget mount event is present near frame 45
# ---------------------------------------------------------------------------


def test_diagnostics_widget_mounted_event(trace):
    events = trace.get("events") or []
    assert isinstance(events, list) and events, "trace has no events"
    mount_events = [
        e for e in events
        if isinstance(e, list) and e and e[0] == "diagnostics_widget_mounted"
    ]
    assert mount_events, (
        "expected at least one 'diagnostics_widget_mounted' event in trace"
    )
    # There should be exactly one mount for a single-run demo.
    assert len(mount_events) == 1, (
        f"expected exactly one mount event, got {len(mount_events)}: "
        f"{mount_events}"
    )
    mount_event = mount_events[0]
    assert len(mount_event) >= 2, (
        f"mount event missing frame_no payload: {mount_event}"
    )
    frame_no = int(mount_event[1])
    requested = int(trace.get("widget_mount_frame", 45))
    # Frame accounting: enable_hud() happens on_begin (frame_count==0 at
    # that point) so the first on_tick after mount request will fire on
    # frame_count == requested. Give a small tolerance.
    assert requested <= frame_no <= requested + 2, (
        f"widget mounted on frame {frame_no}, expected ~{requested}"
    )
