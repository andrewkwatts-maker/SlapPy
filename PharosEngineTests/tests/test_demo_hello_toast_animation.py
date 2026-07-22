"""Tests for :mod:`PharosEngineExamples.examples.hello_toast_animation`.

Exercises the scripted CC5 (toast manager) + CC6 (camera animator)
walkthrough end-to-end, verifying:

* The demo runs to completion and emits a trace on disk.
* The trace records at least 40 per-frame events.
* The camera position mutates over time.
* At least 5 toasts fire, and every level (INFO/SUCCESS/WARN/ERROR) is
  represented.
* The animator's ``active_count`` genuinely changes across the timeline.

Headless-safe — the demo never touches DPG, so no viewport fixture is
required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Make examples/ importable as a top-level package.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _REPO_ROOT / "PharosEngineExamples" / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import hello_toast_animation as demo  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def run_trace(tmp_path: Path):
    """Run the demo once and hand each test a fresh trace + YAML path."""
    trace_path = tmp_path / "hello_toast_animation_trace.yaml"
    trace = demo.run_demo(trace_path=trace_path)
    return trace, trace_path


@pytest.fixture()
def trace_events(run_trace):
    """Shortcut to the recorded event list."""
    trace, _ = run_trace
    return trace.events


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load the YAML trace, preferring pyyaml with a minimal fallback."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("- kind:"):
                events.append({"kind": stripped.split(":", 1)[1].strip()})
        return {"events": events, "event_count": len(events)}


# ---------------------------------------------------------------------------
# 1. Demo entrypoint + trace file
# ---------------------------------------------------------------------------


def test_demo_run_returns_trace(run_trace) -> None:
    trace, _ = run_trace
    assert isinstance(trace, demo.DemoTrace)
    assert trace.events, "trace should record at least one event"


def test_trace_yaml_written_to_disk(run_trace) -> None:
    _, trace_path = run_trace
    assert trace_path.exists(), "trace YAML should be written to disk"
    assert trace_path.stat().st_size > 0


def test_trace_starts_and_ends_cleanly(trace_events) -> None:
    kinds = [e["kind"] for e in trace_events]
    assert kinds[0] == "demo_start", (
        f"first event should be demo_start, got {kinds[0]!r}"
    )
    assert "demo_end" in kinds, "demo_end should be recorded"


# ---------------------------------------------------------------------------
# 2. Frame trace — ≥ 40 per-frame events
# ---------------------------------------------------------------------------


def test_trace_has_at_least_40_frame_events(trace_events) -> None:
    frames = [e for e in trace_events if e["kind"] == "frame"]
    assert len(frames) >= 40, (
        f"trace must record ≥ 40 frame events, got {len(frames)}"
    )


def test_frame_indices_are_monotonic(trace_events) -> None:
    """Every ``frame`` event must have a strictly increasing frame_idx."""
    frames = [e for e in trace_events if e["kind"] == "frame"]
    idxs = [e["frame_idx"] for e in frames]
    for prev, curr in zip(idxs, idxs[1:]):
        assert curr == prev + 1, (
            f"frame_idx non-monotonic: {prev} -> {curr}"
        )


def test_frame_t_ms_advances(trace_events) -> None:
    frames = [e for e in trace_events if e["kind"] == "frame"]
    times = [float(e["t_ms"]) for e in frames]
    # Every consecutive pair must advance.
    for prev, curr in zip(times, times[1:]):
        assert curr > prev, (
            f"frame t_ms non-monotonic: {prev} -> {curr}"
        )


# ---------------------------------------------------------------------------
# 3. Camera position mutation
# ---------------------------------------------------------------------------


def test_camera_position_mutates_over_time(trace_events) -> None:
    """The camera target should not remain the initial (0, 0, 0) forever."""
    frames = [e for e in trace_events if e["kind"] == "frame"]
    assert frames, "no frame events recorded"
    initial = tuple(frames[0]["cam_target"])
    later = [tuple(f["cam_target"]) for f in frames[1:]]
    # At least one later frame must differ from the initial position.
    changed = [p for p in later if p != initial]
    assert changed, (
        f"camera position never mutated — always {initial!r}"
    )
    # And the demo's terminal state should also differ from origin at
    # least once during the run (i.e. we hit non-zero x).
    xs = [f["cam_target"][0] for f in frames]
    assert max(xs) > 1.0, (
        f"camera never panned significantly east, max x = {max(xs)}"
    )


def test_camera_distance_mutates_over_time(trace_events) -> None:
    """The zoom slot mutates during the pan/zoom/focus sequence."""
    frames = [e for e in trace_events if e["kind"] == "frame"]
    dists = [float(f["cam_distance"]) for f in frames]
    assert min(dists) < 5.0 or max(dists) > 5.0, (
        f"cam_distance stayed pegged at initial 5.0 — min={min(dists)}, "
        f"max={max(dists)}"
    )


# ---------------------------------------------------------------------------
# 4. Toast firing — count + level coverage
# ---------------------------------------------------------------------------


def test_at_least_five_toasts_fired(trace_events) -> None:
    toasts = [e for e in trace_events if e["kind"] == "toast_shown"]
    assert len(toasts) >= 5, (
        f"expected ≥ 5 toasts, got {len(toasts)}"
    )


def test_every_toast_level_represented(trace_events) -> None:
    """INFO, SUCCESS, WARN, and ERROR must each appear in the trace."""
    toasts = [e for e in trace_events if e["kind"] == "toast_shown"]
    levels = {e["level"] for e in toasts}
    assert {"INFO", "SUCCESS", "WARN", "ERROR"} <= levels, (
        f"missing toast levels: "
        f"{ {'INFO', 'SUCCESS', 'WARN', 'ERROR'} - levels }"
    )


def test_toasts_carry_stickers_where_scripted(trace_events) -> None:
    """The SUCCESS/WARN/ERROR/SUCCESS_focus toasts all get stickers."""
    stickers = [
        e["sticker"] for e in trace_events
        if e["kind"] == "toast_shown" and "sticker" in e
    ]
    # 4 stickers in the scripted sequence: '>', '!', 'x', '*'.
    assert set(stickers) >= {">", "!", "x", "*"}, (
        f"missing scripted sticker glyphs, got {sorted(set(stickers))}"
    )


# ---------------------------------------------------------------------------
# 5. Animator activity — tween start + active_count movement
# ---------------------------------------------------------------------------


def test_two_tweens_started(trace_events) -> None:
    tweens = [e for e in trace_events if e["kind"] == "tween_started"]
    assert len(tweens) == 2, (
        f"expected 2 tween_started events (position + zoom), got {len(tweens)}"
    )
    kinds = {e["tween_kind"] for e in tweens}
    assert kinds == {"position", "zoom"}, (
        f"expected both position + zoom tweens, got {kinds}"
    )


def test_focus_on_entity_recorded(trace_events) -> None:
    focus = [e for e in trace_events if e["kind"] == "focus_started"]
    assert len(focus) == 1
    assert focus[0]["entity_id"] == "origin_beacon"
    assert focus[0]["success"] is True


def test_stop_all_recorded(trace_events) -> None:
    stops = [e for e in trace_events if e["kind"] == "tweens_stopped"]
    assert len(stops) == 1
    # cancelled may legitimately be 0 if the earlier tweens completed
    # before t=2500 — but the record must exist.
    assert "cancelled" in stops[0]


def test_animator_active_count_changes_over_time(trace_events) -> None:
    """The animator's ``active_count`` must not remain constant across the run.

    We hold at zero at t=0 (nothing scheduled), climb to 1 or 2 while the
    pan/zoom/focus tweens run, and settle back to 0 by demo_end. Assert
    at least two distinct values appear across the frame trace.
    """
    frames = [e for e in trace_events if e["kind"] == "frame"]
    counts = {int(f["active_tweens"]) for f in frames}
    assert len(counts) >= 2, (
        f"animator.active_count() never changed — always {counts}"
    )
    # And the peak must be at least 1 (something ran).
    assert max(counts) >= 1, (
        f"animator never had an active tween — counts = {counts}"
    )


# ---------------------------------------------------------------------------
# 6. Module surface + regression checks
# ---------------------------------------------------------------------------


def test_demo_exposes_run_demo() -> None:
    assert callable(getattr(demo, "run_demo", None))


def test_demo_exposes_mock_camera_defaults() -> None:
    cam = demo.MockCamera()
    assert cam._cam_target == [0.0, 0.0, 0.0]
    assert cam._cam_distance == 5.0


def test_demo_exposes_mock_entity_at_origin() -> None:
    ent = demo.MockEntity()
    assert ent.position == (0.0, 0.0, 0.0)
    box = ent.aabb()
    assert box == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
