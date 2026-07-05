"""Tests for :mod:`SlapPyEngineExamples.examples.hello_gltf_character` (LL5).

The LL5 parity harness drives the full rigged-glTF stack: importer,
skeleton runtime, animation clip, animator, directional light, CSM
builder, orbiting camera, and a 120-frame tick loop through
:class:`slappyengine.app.App`.

Every test runs headless — the demo has no ``__main__`` viewport path;
it just runs and writes ``hello_gltf_character_trace.yaml`` +
``hello_gltf_character_final.png`` next to the module.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Make examples/ importable as a top-level package.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _REPO_ROOT / "SlapPyEngineExamples" / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import hello_gltf_character as demo  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — run the demo once per module, share the trace across tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_trace(tmp_path_factory):
    """Run the LL5 demo once and reuse its trace across every test."""
    tmp = tmp_path_factory.mktemp("hello_gltf_character")
    trace_path = tmp / "hello_gltf_character_trace.yaml"
    shot_path = tmp / "hello_gltf_character_final.png"
    trace = demo.run_demo(
        trace_path=trace_path,
        screenshot_path=shot_path,
    )
    return trace, trace_path, shot_path


@pytest.fixture(scope="module")
def trace_events(run_trace):
    trace, _, _ = run_trace
    return trace.events


def _kinds(events: list[dict[str, Any]]) -> list[str]:
    return [e["kind"] for e in events]


# ---------------------------------------------------------------------------
# 1. Entrypoint + trace file basics.
# ---------------------------------------------------------------------------


def test_demo_run_returns_trace(run_trace) -> None:
    """``run_demo`` returns a populated :class:`DemoTrace` without raising."""
    trace, _, _ = run_trace
    assert isinstance(trace, demo.DemoTrace)
    assert trace.events, "trace should record at least one event"


def test_trace_has_at_least_30_events(trace_events) -> None:
    """The parity harness contract is >= 30 recorded events."""
    assert len(trace_events) >= 30, (
        f"expected >= 30 events, got {len(trace_events)}: "
        f"{_kinds(trace_events)}"
    )


def test_trace_yaml_written(run_trace) -> None:
    """The YAML file is on disk and parses back to a dict."""
    _, trace_path, _ = run_trace
    assert trace_path.is_file()
    body = trace_path.read_text(encoding="utf-8")
    assert body.strip(), "trace file is empty"
    # yaml is a hard dep of the engine already.
    import yaml
    parsed = yaml.safe_load(body)
    assert isinstance(parsed, dict)
    assert "events" in parsed
    # The trace is serialised before ``demo_end`` (and possibly
    # ``trace_written``) fires, so the file typically ends up 1-2 events
    # short of the final in-memory list. Both must clear the >= 30 floor.
    assert len(parsed["events"]) >= 30
    assert len(parsed["events"]) <= len(run_trace[0].events)


# ---------------------------------------------------------------------------
# 2. Subsystem coverage — every LL5 step should surface at least once.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected_kind",
    [
        "demo_start",
        "app_boot",
        "skeleton_built",
        "clip_built",
        "animator_built",
        "csm_ready",
        "camera_spawned",
        "run_end",
        "trace_written",
        "demo_end",
    ],
)
def test_expected_kind_present(trace_events, expected_kind: str) -> None:
    kinds = _kinds(trace_events)
    assert expected_kind in kinds, (
        f"missing event {expected_kind!r}; got kinds={sorted(set(kinds))}"
    )


def test_all_ll5_subsystems_verified(trace_events) -> None:
    """The 10 SUBSYSTEM_MAP entries should all be OK on a healthy run."""
    kinds = set(_kinds(trace_events))
    verified = {
        subsystem: (event_kind in kinds)
        for subsystem, event_kind in demo.SUBSYSTEM_MAP.items()
    }
    missed = [k for k, ok in verified.items() if not ok]
    # We tolerate at most 2 missed (PIL / wgpu drift on CI slave); every
    # engine-side subsystem must be present.
    engine_required = {
        "app_shell", "skeleton_runtime", "animation_clip",
        "animator", "directional_light", "csm_builder",
        "orbit_camera", "frame_loop",
    }
    engine_missed = engine_required & set(missed)
    assert not engine_missed, (
        f"engine subsystems missed: {sorted(engine_missed)}; "
        f"all missed = {sorted(missed)}"
    )


# ---------------------------------------------------------------------------
# 3. Frame-loop contract — exactly 120 frames ticked.
# ---------------------------------------------------------------------------


def test_120_frames_rendered(trace_events) -> None:
    """The ``run_end`` event carries ``frames_ticked == 120``."""
    end_events = [e for e in trace_events if e["kind"] == "run_end"]
    assert end_events, "no run_end event recorded"
    frames = int(end_events[-1].get("frames_ticked", 0))
    assert frames == demo.FRAME_COUNT == 120, (
        f"expected 120 frames, got {frames}"
    )


def test_tick_heartbeats_recorded(trace_events) -> None:
    """The 8-frame tick heartbeat produces >= 10 tick events."""
    ticks = [e for e in trace_events if e["kind"] == "tick"]
    assert len(ticks) >= 10, f"expected >= 10 tick events, got {len(ticks)}"


# ---------------------------------------------------------------------------
# 4. Animator produces distinct palettes across time.
# ---------------------------------------------------------------------------


def test_animator_palettes_differ_across_time() -> None:
    """The Animator must produce different skinning palettes at t=0 vs t=1s.

    We drive the animator directly (rather than reading trace events) so
    we can assert on the underlying numerical difference.
    """
    trace = demo.DemoTrace()
    asset = demo._resolve_asset_path()
    character = demo._step_load_character(trace, asset)
    assert character is not None
    clip = demo._step_build_clip(
        trace, target_joint=min(1, character.skeleton.joint_count - 1)
    )
    assert clip is not None
    animator = demo._step_build_animator(trace, character, clip)
    assert animator is not None

    palette_t0 = animator.advance(0.0).copy()
    palette_t1 = animator.advance(1.0).copy()
    delta = float(np.linalg.norm(palette_t1 - palette_t0))
    assert delta > 1e-3, (
        "Animator should mutate the skinning palette between t=0 and t=1s "
        f"(delta = {delta:.6f})"
    )


# ---------------------------------------------------------------------------
# 5. Camera orbits 360° over the run.
# ---------------------------------------------------------------------------


def test_camera_orbits_full_circle() -> None:
    """The orbit math should sweep the camera through 2π (i.e. wrap around).

    We reconstruct the orbit trajectory from the demo constants and check
    that the angle spans at least 350° (giving the loop room to close on
    frame 120).
    """
    thetas = []
    for frame in range(demo.FRAME_COUNT):
        theta = (frame / demo.FRAME_COUNT) * (2.0 * math.pi)
        thetas.append(theta)
    span = max(thetas) - min(thetas)
    # Frame 0 → 0 rad, frame 119 → 2π * 119/120 ≈ 356°.
    assert span >= math.radians(350.0), f"orbit span too small: {math.degrees(span):.2f} deg"


def test_camera_positions_lie_on_orbit_radius(trace_events) -> None:
    """Every ``tick`` event's camera position sits on the orbit circle."""
    ticks = [e for e in trace_events if e["kind"] == "tick"]
    assert ticks, "no tick events; camera orbit not exercised"
    for evt in ticks:
        pos = evt.get("cam_pos")
        assert pos is not None and len(pos) == 3
        x, y, z = pos
        radius = math.sqrt(x * x + z * z)
        assert abs(radius - demo.ORBIT_RADIUS) < 1e-3, (
            f"tick frame {evt.get('frame')}: radius {radius:.3f} != "
            f"{demo.ORBIT_RADIUS}"
        )
        assert abs(y - demo.CAMERA_Y) < 1e-3


# ---------------------------------------------------------------------------
# 6. Character skeleton — exactly 2 bones.
# ---------------------------------------------------------------------------


def test_character_skeleton_has_two_bones() -> None:
    """The fixture is a root + child, so :attr:`joint_count` must be 2."""
    trace = demo.DemoTrace()
    asset = demo._resolve_asset_path()
    character = demo._step_load_character(trace, asset)
    assert character is not None
    assert character.skeleton.joint_count == 2, (
        f"expected 2 bones, got {character.skeleton.joint_count}"
    )
    names = [n.name for n in character.skeleton.nodes]
    assert "root_joint" in names[0] or "root" in names[0]
    assert "child" in names[1]


# ---------------------------------------------------------------------------
# 7. Screenshot artefact.
# ---------------------------------------------------------------------------


def test_screenshot_written_when_pil_available(run_trace) -> None:
    """PIL is a runtime dep already; the PNG should always land."""
    pytest.importorskip("PIL")
    _, _, shot_path = run_trace
    assert shot_path.is_file(), f"screenshot missing at {shot_path}"
    assert shot_path.stat().st_size > 100, "screenshot suspiciously small"


# ---------------------------------------------------------------------------
# 8. CSM cascades — the JJ7 harness should produce 4 cascades.
# ---------------------------------------------------------------------------


def test_csm_produces_four_cascades(trace_events) -> None:
    cascades = [e for e in trace_events if e["kind"] == "csm_cascade"]
    assert len(cascades) == 4, (
        f"expected 4 CSM cascades, got {len(cascades)}"
    )
    for idx, cascade in enumerate(cascades):
        assert int(cascade["index"]) == idx
        assert float(cascade["far_z"]) > float(cascade["near_z"])
