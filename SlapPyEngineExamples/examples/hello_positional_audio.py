"""hello_positional_audio — 3D positional audio (LL4) showcase.

NN5 sprint deliverable (2026-07-06): showcase the newly landed
:mod:`pharos_engine.audio_3d` module — the LL4 landing that added
:class:`AudioListener`, :class:`Audio3DSource`, :class:`SoundBank`, and
:class:`Audio3DEngine` with equal-power stereo pan + doppler pitch
shift.

Scene
-----

* A single :class:`AudioListener` at the world origin, facing ``+Z``
  with head-up ``+Y``.
* Two :class:`Audio3DSource` handles orbiting the listener in the ``XZ``
  plane:

    - **Source A** (``"beacon_a"``) at radius 3.0, angular velocity
      1× full orbit over 60 frames.
    - **Source B** (``"beacon_b"``) at radius 5.0, angular velocity
      2× (twice around during the run), phase-offset by ``π/2``.

Each frame the demo:

1. Advances the orbit angle for each source.
2. Updates :attr:`Audio3DSource.position` on the mounted voice and sets
   :attr:`Audio3DSource.velocity` to the analytic tangent of the orbit
   (so doppler shifts fire).
3. Calls :meth:`Audio3DEngine.update` to refresh gain / pitch / pan
   for every live voice.
4. Reads the per-voice state via :meth:`Audio3DEngine.voice_state` and
   appends a compact frame record to an in-memory trace.

At the end the trace is serialised to
``hello_positional_audio_trace.yaml`` next to the demo so the smoke test
(and any curious human) can inspect the pan / gain / pitch curves.

Run
---

::

    python SlapPyEngineExamples/examples/hello_positional_audio.py

Headless-safe — no wgpu required, no window opened. Uses the same
lambda-based launcher pattern as :mod:`hello_render`; if the underlying
audio backend isn't installed the DSP math still runs and the trace is
still written.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_positional_audio_trace.yaml"

DEFAULT_MAX_FRAMES: int = 60
DEFAULT_DT: float = 1.0 / 60.0

# Orbit geometry — elliptical (a ≠ b) so the tangent velocity has a
# *radial* component and doppler_shift() actually swings. A perfectly
# circular orbit keeps velocity always perpendicular to the
# source→listener axis, which pins the pitch multiplier at 1.0 and
# makes the doppler assertion in the smoke test vacuous.
#
# Values chosen so both sources sweep the full pan range (front →
# right → back → left → front) at least once during the run.
SOURCE_A_A: float = 3.0   # X-axis semi-axis
SOURCE_A_B: float = 5.0   # Z-axis semi-axis
SOURCE_A_ORBITS: float = 1.0  # full loop across max_frames

SOURCE_B_A: float = 6.0
SOURCE_B_B: float = 4.0
SOURCE_B_ORBITS: float = 2.0  # two loops across max_frames
SOURCE_B_PHASE: float = math.pi / 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig`.

    Nothing about the audio pipeline needs a window, but we launch via
    :func:`pharos_engine.launch` for parity with the ``hello_render``
    demos — so we still hand a stub config in.
    """
    import pharos_engine

    return pharos_engine.AppConfig(
        window_title="hello_positional_audio",
        window_size=(320, 240),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


def _orbit_position(
    a: float, b: float, angle: float
) -> tuple[float, float, float]:
    """Return the ``(x, y, z)`` point on an elliptical horizontal orbit.

    Uses ``(a*sin θ, 0, b*cos θ)``. Angle 0 places the source directly
    *in front* of the listener (``+Z``); angle ``π/2`` swings the source
    to ``+X`` (which is the world-*left* channel given the listener's
    default ``forward=+Z`` / ``up=+Y`` — see
    :func:`pharos_engine.audio_3d.stereo_pan`).
    """
    return (a * math.sin(angle), 0.0, b * math.cos(angle))


def _orbit_velocity(
    a: float, b: float, angle: float, angular_speed: float
) -> tuple[float, float, float]:
    """Analytic tangent velocity for an elliptical horizontal orbit.

    ``d/dt (a*sin θ, 0, b*cos θ) = (a*ω*cos θ, 0, -b*ω*sin θ)``.

    With ``a ≠ b`` this velocity is **not** perpendicular to the radial
    direction, so :func:`pharos_engine.audio_3d.doppler_shift` produces
    a non-trivial pitch multiplier at every step of the orbit.
    """
    return (
        a * angular_speed * math.cos(angle),
        0.0,
        -b * angular_speed * math.sin(angle),
    )


def _pan_signed(pan: tuple[float, float]) -> float:
    """Collapse ``(left_gain, right_gain)`` to a single signed value.

    ``+1`` = full right, ``-1`` = full left, ``0`` = centred.
    """
    left, right = pan
    return float(right) - float(left)


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump the frame trace to YAML — degrades gracefully if pyyaml is missing."""
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a regular dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    dt: float = DEFAULT_DT,
    trace_yaml_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Run the positional-audio demo and return a summary dict.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 60).
    dt:
        Simulation timestep in seconds (default 1/60).
    trace_yaml_path:
        Where to write the frame-trace YAML. Pass ``None`` for the
        default location next to the demo, or an explicit path for tests.
    """
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1 (got {max_frames})")
    if dt <= 0:
        raise ValueError(f"dt must be > 0 (got {dt})")

    import pharos_engine
    from pharos_engine.audio_3d import (
        Audio3DEngine,
        Audio3DSource,
        AudioListener,
        SoundBank,
    )

    # ---- Build the audio scene ------------------------------------------
    listener = AudioListener(
        position=(0.0, 0.0, 0.0),
        forward=(0.0, 0.0, 1.0),
        up=(0.0, 1.0, 0.0),
        velocity=(0.0, 0.0, 0.0),
    )
    bank = SoundBank()
    # Register stub handles so we don't need real .wav fixtures on disk.
    bank.register("beacon_a", {"_stub": True, "name": "beacon_a"})
    bank.register("beacon_b", {"_stub": True, "name": "beacon_b"})

    engine = Audio3DEngine(listener, bank)

    # Angular speeds derived from the frame budget so we hit the target
    # number of orbits *exactly* across ``max_frames`` — the smoke test
    # relies on the pan sweeping both extremes.
    total_time = max_frames * dt
    omega_a = (SOURCE_A_ORBITS * 2.0 * math.pi) / total_time
    omega_b = (SOURCE_B_ORBITS * 2.0 * math.pi) / total_time

    source_a = Audio3DSource(
        sound_id="beacon_a",
        position=_orbit_position(SOURCE_A_A, SOURCE_A_B, 0.0),
        velocity=_orbit_velocity(SOURCE_A_A, SOURCE_A_B, 0.0, omega_a),
        min_distance=1.0,
        max_distance=50.0,
        is_looping=True,
    )
    source_b = Audio3DSource(
        sound_id="beacon_b",
        position=_orbit_position(SOURCE_B_A, SOURCE_B_B, SOURCE_B_PHASE),
        velocity=_orbit_velocity(SOURCE_B_A, SOURCE_B_B, SOURCE_B_PHASE, omega_b),
        min_distance=1.0,
        max_distance=50.0,
        is_looping=True,
    )

    voice_a = engine.play(source_a)
    voice_b = engine.play(source_b)

    trace: List[Dict[str, Any]] = []

    # ---- Per-frame lambda ------------------------------------------------
    #
    # We stash all mutable state on a closure dict so the tick lambda
    # stays a real lambda (rather than a nested def) — matching the
    # style of ``hello_render.minimal``.
    state: Dict[str, Any] = {"frame": 0}

    def _tick(app: Any, _dt: float) -> None:
        frame = state["frame"]
        angle_a = omega_a * frame * dt
        angle_b = omega_b * frame * dt + SOURCE_B_PHASE

        # Update source pose + velocity in-place, then let the engine
        # refresh DSP for every live voice.
        source_a.position = _orbit_position(SOURCE_A_A, SOURCE_A_B, angle_a)
        source_a.velocity = _orbit_velocity(SOURCE_A_A, SOURCE_A_B, angle_a, omega_a)
        source_b.position = _orbit_position(SOURCE_B_A, SOURCE_B_B, angle_b)
        source_b.velocity = _orbit_velocity(SOURCE_B_A, SOURCE_B_B, angle_b, omega_b)

        engine.update(dt)

        state_a = engine.voice_state(voice_a) or {}
        state_b = engine.voice_state(voice_b) or {}

        trace.append({
            "frame": frame,
            "angle_a": float(angle_a),
            "angle_b": float(angle_b),
            "source_a": {
                "position": list(source_a.position),
                "gain": float(state_a.get("gain", 0.0)),
                "pitch": float(state_a.get("pitch", 1.0)),
                "pan_left": float(state_a.get("pan", (0.5, 0.5))[0]),
                "pan_right": float(state_a.get("pan", (0.5, 0.5))[1]),
                "pan_signed": _pan_signed(state_a.get("pan", (0.5, 0.5))),
            },
            "source_b": {
                "position": list(source_b.position),
                "gain": float(state_b.get("gain", 0.0)),
                "pitch": float(state_b.get("pitch", 1.0)),
                "pan_left": float(state_b.get("pan", (0.5, 0.5))[0]),
                "pan_right": float(state_b.get("pan", (0.5, 0.5))[1]),
                "pan_signed": _pan_signed(state_b.get("pan", (0.5, 0.5))),
            },
        })
        state["frame"] = frame + 1

    # ---- Launch via the same lambda pattern as hello_render.minimal -----
    pharos_engine.launch(
        on_begin=lambda app: None,
        on_tick=_tick,
        on_end=lambda app: None,
        max_frames=max_frames,
        config=_headless_config(),
    )

    # ---- Roll up summary + write YAML ------------------------------------
    pans_a = [ev["source_a"]["pan_signed"] for ev in trace]
    pans_b = [ev["source_b"]["pan_signed"] for ev in trace]
    pitches_a = [ev["source_a"]["pitch"] for ev in trace]
    pitches_b = [ev["source_b"]["pitch"] for ev in trace]

    peak_left_pan = min(pans_a + pans_b) if trace else 0.0
    peak_right_pan = max(pans_a + pans_b) if trace else 0.0
    pitch_range_a = (max(pitches_a) - min(pitches_a)) if pitches_a else 0.0
    pitch_range_b = (max(pitches_b) - min(pitches_b)) if pitches_b else 0.0

    payload: Dict[str, Any] = {
        "frame_count": len(trace),
        "listener": {
            "position": list(listener.position),
            "forward": list(listener.forward),
            "up": list(listener.up),
        },
        "sources": {
            "beacon_a": {
                "semi_a": SOURCE_A_A,
                "semi_b": SOURCE_A_B,
                "orbits": SOURCE_A_ORBITS,
                "voice_id": voice_a,
            },
            "beacon_b": {
                "semi_a": SOURCE_B_A,
                "semi_b": SOURCE_B_B,
                "orbits": SOURCE_B_ORBITS,
                "voice_id": voice_b,
                "phase": SOURCE_B_PHASE,
            },
        },
        "summary": {
            "peak_left_pan": float(peak_left_pan),
            "peak_right_pan": float(peak_right_pan),
            "pitch_range_a": float(pitch_range_a),
            "pitch_range_b": float(pitch_range_b),
        },
        "frames": trace,
    }

    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    summary: Dict[str, Any] = {
        "frame_count": len(trace),
        "voice_a": voice_a,
        "voice_b": voice_b,
        "peak_left_pan": float(peak_left_pan),
        "peak_right_pan": float(peak_right_pan),
        "pitch_range_a": float(pitch_range_a),
        "pitch_range_b": float(pitch_range_b),
        "trace_path": str(out_path),
    }

    print("=== hello_positional_audio summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    main()
