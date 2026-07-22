"""hello_full_lifecycle — RR5 flagship 180-frame end-to-end integration demo.

Stitches every subsystem the engine currently ships into a single
lifecycle walkthrough so downstream users (and CI) have one canonical
"does the whole thing turn on?" smoke.

Subsystems exercised
--------------------

* **HH1 / App**       — ``pharos_engine.launch(on_begin, on_tick, on_end)``.
* **NN3 / capture**   — :meth:`App.load_model`, :meth:`App.spawn_light`,
                        :meth:`App.spawn_camera`, :meth:`App.enable_hud`,
                        :meth:`App.start_recording`,
                        :meth:`App.take_screenshot`.
* **QQ4 / OO6**       — :meth:`App.enable_diagnostics` +
                        :meth:`App.diagnostics_stats`.
* **NN4 / OO2 / QQ7** — :class:`World3D`, :meth:`World3D.build_bvh`,
                        :meth:`World3D.raycast`, :meth:`World3D.draw_debug`,
                        :meth:`World3D.debug_stats`.
* **LL4 / audio_3d**  — :class:`AudioListener` + :class:`Audio3DSource`
                        + :class:`Audio3DEngine`.
* **LL1 / MM2**       — HUD overlay + default game widgets +
                        (via ``enable_diagnostics``) diagnostics widget.

Behaviour contract
------------------

* Headless-safe (``AppConfig(enable_gpu=False)``): every subsystem has a
  "skip if unavailable" branch and records a note in the trace's
  ``degradation_notes`` list rather than raising.
* Runs exactly ``max_frames`` frames (default 180).
* Fires a raycast every 30 frames (frames 0, 30, 60, 90, 120, 150).
* Takes a screenshot every 60 frames (frames 0, 60, 120).
* Calls :meth:`World3D.draw_debug` every 90 frames (frames 0, 90).
* At frame 100 triggers a deliberate ``Skybox.render`` against a bare
  no-op renderer to fire the render-subsystem warning path — exercises
  the diagnostics collector wiring.

Output
------

* ``hello_full_lifecycle_trace.yaml`` next to the demo (or the caller's
  ``trace_yaml_path``) with:

    - ``frame_count``           — final frame count.
    - ``subsystems_used``       — sorted list of subsystem tags that ran.
    - ``screenshot_count``      — number of ``take_screenshot`` calls.
    - ``raycast_hit_count``     — number of raycasts that hit *something*.
    - ``raycast_total``         — number of raycast calls issued.
    - ``debug_draw_events``     — number of ``World3D.draw_debug`` calls.
    - ``diagnostics_event_count`` — total events in the collector at end.
    - ``diagnostics_stats``     — final :meth:`DiagnosticsCollector.stats`.
    - ``top_subsystems``        — top-N subsystems by warning count.
    - ``degradation_notes``     — list of features that had to skip.
    - ``audio_voice_id``        — the voice id returned by
                                  :meth:`Audio3DEngine.play` (or ``None``).
    - ``recording_started``     — bool: did ``start_recording`` succeed?
    - ``recording_stopped``     — bool: did ``stop_recording`` fire?

Run
---

::

    python SlapPyEngineExamples/examples/hello_full_lifecycle.py

Returns a summary dict.
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
_BUNNY_OBJ = _THIS_DIR / "assets" / "bunny_low.obj"
_TRIANGLE_OBJ = _THIS_DIR / "assets" / "triangle.obj"
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_full_lifecycle_trace.yaml"
_DEFAULT_SHOT_DIR = _THIS_DIR / "hello_full_lifecycle_shots"

DEFAULT_MAX_FRAMES: int = 180
RAYCAST_EVERY: int = 30
SCREENSHOT_EVERY: int = 60
DEBUG_DRAW_EVERY: int = 90
WARNING_TRIGGER_FRAME: int = 100

DEFAULT_ROTATION_SPEED_RAD: float = 0.5  # rad/sec
AUDIO_ORBIT_RADIUS: float = 4.0
AUDIO_ORBIT_PERIOD_FRAMES: int = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_path() -> str:
    """Return the best available bundled model, or ``""``."""
    if _BUNNY_OBJ.exists():
        return str(_BUNNY_OBJ)
    if _TRIANGLE_OBJ.exists():
        return str(_TRIANGLE_OBJ)
    return ""


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` sized for a 1280x720 HUD."""
    import pharos_engine

    return pharos_engine.AppConfig(
        window_title="hello_full_lifecycle",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        msaa_samples=4,
        clear_color=(0.08, 0.09, 0.12, 1.0),
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump the trace payload to YAML; falls back to ``repr`` if pyyaml missing."""
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a regular dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


class _NullDebugRenderer:
    """A renderer that captures ``World3D.draw_debug`` line output.

    ``World3D.draw_debug`` prefers a ``draw_line(p0, p1, color)`` method
    but falls back on ``draw_log.append(dict)`` when only that is
    present — we take the ``draw_log`` path so tests can count entries
    without needing a real renderer.
    """

    __slots__ = ("draw_log",)

    def __init__(self) -> None:
        self.draw_log: list[dict] = []


class _NoopSkyboxRenderer:
    """Bare renderer used to provoke the skybox warn-once path."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    trace_yaml_path: str | Path | None = None,
    screenshot_dir: str | Path | None = None,
    enable_recording: bool = True,
) -> Dict[str, Any]:
    """Boot the flagship 180-frame lifecycle demo.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 180).
    trace_yaml_path:
        Where to persist the summary YAML. ``None`` writes next to the
        demo module.
    screenshot_dir:
        Directory for per-shot PNGs. ``None`` uses a folder next to the
        demo module.
    enable_recording:
        When True, attempt to start an MP4 recording at ``on_begin`` and
        stop it at ``on_end``. Failures degrade to a ``degradation_notes``
        entry.
    """
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1 (got {max_frames})")

    import pharos_engine

    shots_dir = (
        Path(screenshot_dir) if screenshot_dir is not None else _DEFAULT_SHOT_DIR
    )
    shots_dir.mkdir(parents=True, exist_ok=True)

    # ---- Mutable state shared across lifecycle callbacks ------------------
    state: Dict[str, Any] = {
        "app": None,
        "model": None,
        "world": None,
        "audio_engine": None,
        "audio_source": None,
        "audio_voice_id": None,
        "subsystems_used": set(),
        "screenshot_count": 0,
        "screenshot_paths": [],
        "raycast_total": 0,
        "raycast_hit_count": 0,
        "raycast_log": [],
        "debug_draw_events": 0,
        "debug_lines_total": 0,
        "recording_started": False,
        "recording_stopped": False,
        "warning_triggered": False,
        "degradation_notes": [],
        "diagnostics_stats_final": {},
        "diagnostics_event_count": 0,
    }

    def _note(msg: str) -> None:
        state["degradation_notes"].append(str(msg))

    # ---- on_begin ---------------------------------------------------------
    def on_begin(a: Any) -> None:
        state["app"] = a
        state["subsystems_used"].add("app")

        # --- Model (NN3) ---
        model_path = _model_path()
        if model_path:
            try:
                model = a.load_model(model_path)
                state["model"] = model
                state["subsystems_used"].add("model")
                a.trace.append(("full_lifecycle_model_load", model_path))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"load_model failed: {exc!r}")
        else:
            _note("no bundled model asset available")

        # --- Camera + Light (NN3) ---
        try:
            a.spawn_camera(position=(3.0, 2.0, 6.0), look_at=(0.0, 0.5, 0.0))
            state["subsystems_used"].add("camera")
        except Exception as exc:  # pragma: no cover — API drift safety net
            _note(f"spawn_camera failed: {exc!r}")
        try:
            a.spawn_light((5.0, 8.0, 5.0), color=(1.0, 0.95, 0.85), intensity=1.5)
            state["subsystems_used"].add("light")
        except Exception as exc:  # pragma: no cover — API drift safety net
            _note(f"spawn_light failed: {exc!r}")

        # --- HUD (LL1 / MM2) ---
        try:
            overlay = a.enable_hud()
            widget_count = len(overlay.widgets()) if overlay is not None else 0
            state["subsystems_used"].add("hud")
            a.trace.append(("full_lifecycle_hud_mount", int(widget_count)))
        except Exception as exc:
            _note(f"enable_hud failed: {exc!r}")

        # --- Diagnostics (QQ4 / OO6) ---
        try:
            collector = a.enable_diagnostics(min_level="WARNING", max_events=500)
            # Fresh state per run — some test runners share process state.
            try:
                collector.clear()
            except Exception:  # pragma: no cover — defensive
                pass
            state["subsystems_used"].add("diagnostics")
            a.trace.append(("full_lifecycle_diagnostics_installed", True))
        except Exception as exc:
            _note(f"enable_diagnostics failed: {exc!r}")

        # --- Physics3 world (NN4 / OO2 / QQ7) ---
        try:
            from pharos_engine.physics3_bridge import Body3D, World3D

            world = World3D(gravity=(0.0, -9.81, 0.0), backend="fallback")
            # Five bodies laid out in a shallow arc so raycasts along +X
            # from behind (-X) reliably hit at least one.
            positions = [
                (-2.0, 0.5, 0.0),
                (-1.0, 0.5, 0.0),
                (0.0, 0.5, 0.0),
                (1.0, 0.5, 0.0),
                (2.0, 0.5, 0.0),
            ]
            for pos in positions:
                world.add_body(
                    Body3D(
                        position=pos,
                        mass=1.0,
                        shape_kind="sphere",
                        shape_params={"radius": 0.4},
                    )
                )
            try:
                world.build_bvh()
            except Exception as exc:  # pragma: no cover — bvh_3d missing
                _note(f"World3D.build_bvh failed: {exc!r}")
            state["world"] = world
            state["subsystems_used"].add("physics3")
            a.trace.append(("full_lifecycle_world_built", len(world)))
        except Exception as exc:
            _note(f"World3D setup failed: {exc!r}")

        # --- Audio (LL4) ---
        try:
            from pharos_engine.audio_3d import (
                Audio3DEngine,
                Audio3DSource,
                AudioListener,
                SoundBank,
            )

            listener = AudioListener(
                position=(0.0, 0.0, 0.0),
                forward=(0.0, 0.0, 1.0),
                up=(0.0, 1.0, 0.0),
                velocity=(0.0, 0.0, 0.0),
            )
            bank = SoundBank()
            bank.register("beacon", {"_stub": True, "name": "beacon"})
            source = Audio3DSource(
                sound_id="beacon",
                position=(AUDIO_ORBIT_RADIUS, 0.0, 0.0),
                velocity=(0.0, 0.0, 0.0),
                min_distance=1.0,
                max_distance=50.0,
                is_looping=True,
            )
            engine = Audio3DEngine(listener, bank)
            voice_id = engine.play(source)
            state["audio_engine"] = engine
            state["audio_source"] = source
            state["audio_voice_id"] = voice_id
            state["subsystems_used"].add("audio_3d")
            a.trace.append(("full_lifecycle_audio_online", voice_id))
        except Exception as exc:
            _note(f"Audio3D setup failed: {exc!r}")

        # --- Recording (NN3) — best-effort ---
        if enable_recording:
            try:
                mp4_path = shots_dir / "hello_full_lifecycle.mp4"
                result = a.start_recording(path=str(mp4_path), fps=60)
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                if status in ("recording", "started", "ok"):
                    state["recording_started"] = True
                    state["subsystems_used"].add("recording")
                    a.trace.append(("full_lifecycle_recording_started", str(mp4_path)))
                else:
                    _note(f"start_recording status={status!r}")
            except Exception as exc:
                _note(f"start_recording failed: {exc!r}")
        else:
            _note("recording disabled by caller")

    # ---- on_tick ---------------------------------------------------------
    def on_tick(a: Any, dt: float) -> None:
        frame = a.frame_count

        # 1. Rotate the model each frame.
        model = state["model"]
        if model is not None:
            try:
                angle = frame * DEFAULT_ROTATION_SPEED_RAD * dt
                model.rotate_to(0.0, angle, 0.0)
            except Exception:  # pragma: no cover — defensive
                pass

        # 2. Update audio source orbit.
        source = state["audio_source"]
        engine = state["audio_engine"]
        if source is not None and engine is not None:
            try:
                theta = (2.0 * math.pi * frame) / float(AUDIO_ORBIT_PERIOD_FRAMES)
                omega = (2.0 * math.pi) / (
                    float(AUDIO_ORBIT_PERIOD_FRAMES) * max(dt, 1e-6)
                )
                source.position = (
                    AUDIO_ORBIT_RADIUS * math.cos(theta),
                    0.0,
                    AUDIO_ORBIT_RADIUS * math.sin(theta),
                )
                source.velocity = (
                    -AUDIO_ORBIT_RADIUS * omega * math.sin(theta),
                    0.0,
                    AUDIO_ORBIT_RADIUS * omega * math.cos(theta),
                )
                engine.update(dt)
            except Exception:  # pragma: no cover — defensive
                pass

        # 3. Raycast every RAYCAST_EVERY frames.
        world = state["world"]
        if world is not None and frame % RAYCAST_EVERY == 0:
            try:
                # Fire along +X from behind the arc so we always hit the
                # nearest body.
                hit = world.raycast(
                    origin=(-5.0, 0.5, 0.0),
                    direction=(1.0, 0.0, 0.0),
                    max_distance=20.0,
                )
                state["raycast_total"] += 1
                if hit is not None:
                    state["raycast_hit_count"] += 1
                    state["raycast_log"].append(
                        {
                            "frame": int(frame),
                            "body_id": int(hit.body_id),
                            "distance": float(hit.distance),
                        }
                    )
                    a.trace.append(
                        (
                            "full_lifecycle_raycast_hit",
                            int(frame),
                            int(hit.body_id),
                            float(hit.distance),
                        )
                    )
                else:
                    a.trace.append(("full_lifecycle_raycast_miss", int(frame)))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"raycast frame={frame} failed: {exc!r}")

        # 4. Screenshot every SCREENSHOT_EVERY frames.
        if frame % SCREENSHOT_EVERY == 0:
            try:
                shot_path = shots_dir / f"frame_{int(frame):04d}.png"
                result = a.take_screenshot(path=str(shot_path))
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                state["screenshot_count"] += 1
                state["screenshot_paths"].append(str(shot_path))
                a.trace.append(
                    (
                        "full_lifecycle_screenshot",
                        int(frame),
                        str(shot_path),
                        status,
                    )
                )
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"take_screenshot frame={frame} failed: {exc!r}")

        # 5. draw_debug into a null renderer every DEBUG_DRAW_EVERY frames.
        if world is not None and frame % DEBUG_DRAW_EVERY == 0:
            try:
                renderer = _NullDebugRenderer()
                stats = world.draw_debug(renderer, show_aabbs=True)
                state["debug_draw_events"] += 1
                state["debug_lines_total"] += int(stats.get("line_count", 0))
                a.trace.append(
                    (
                        "full_lifecycle_debug_draw",
                        int(frame),
                        int(stats.get("aabbs_drawn", 0)),
                        int(stats.get("line_count", 0)),
                    )
                )
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"draw_debug frame={frame} failed: {exc!r}")

        # 6. Deliberate warning at WARNING_TRIGGER_FRAME to exercise
        #    diagnostics — skybox against a bare renderer with no
        #    ``submit_skybox`` / ``draw_skybox`` / ``draw_log``.
        if not state["warning_triggered"] and frame >= WARNING_TRIGGER_FRAME:
            try:
                from pharos_engine.render.skybox import (
                    Skybox,
                    procedural_gradient_sky,
                )

                sky = Skybox(cubemap=procedural_gradient_sky(resolution=8))
                sky.render(renderer=_NoopSkyboxRenderer(), camera=None)
                state["warning_triggered"] = True
                a.trace.append(("full_lifecycle_warning_triggered", int(frame)))
            except Exception as exc:  # pragma: no cover — defensive
                # Failure here is fine; diagnostics may still capture other
                # warnings from earlier subsystems.
                _note(f"warning trigger failed: {exc!r}")
                state["warning_triggered"] = True  # don't retry every frame

    # ---- on_end ----------------------------------------------------------
    def on_end(a: Any) -> None:
        # Snapshot diagnostics before we tear anything down.
        try:
            stats = a.diagnostics_stats() or {}
            events = a.diagnostics_events() or []
            state["diagnostics_stats_final"] = dict(stats)
            state["diagnostics_event_count"] = len(events)
        except Exception as exc:  # pragma: no cover — defensive
            _note(f"diagnostics snapshot failed: {exc!r}")

        # Stop recording if we started one.
        if state["recording_started"]:
            try:
                result = a.stop_recording()
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                state["recording_stopped"] = True
                a.trace.append(("full_lifecycle_recording_stopped", status))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"stop_recording failed: {exc!r}")

        a.trace.append(("full_lifecycle_on_end", int(a.frame_count)))

    # ---- Run --------------------------------------------------------------
    app = pharos_engine.launch(
        on_begin=on_begin,
        on_tick=on_tick,
        on_end=on_end,
        max_frames=max_frames,
        config=_headless_config(),
    )

    # ---- Roll up top_subsystems (by warning count) ------------------------
    top_subsystems: list[tuple[str, int]] = []
    for key, count in state["diagnostics_stats_final"].items():
        # Stats keys look like "subsystem:name" and "level:LEVEL"; we want
        # the subsystem breakdown ordered by descending count.
        if isinstance(key, str) and key.startswith("subsystem:"):
            top_subsystems.append((key[len("subsystem:") :], int(count)))
    top_subsystems.sort(key=lambda pair: (-pair[1], pair[0]))
    top_subsystems = top_subsystems[:5]

    subsystems_used_sorted = sorted(state["subsystems_used"])

    # ---- Persist trace YAML ---------------------------------------------
    payload: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "max_frames": int(max_frames),
        "subsystems_used": subsystems_used_sorted,
        "screenshot_count": int(state["screenshot_count"]),
        "screenshot_paths": list(state["screenshot_paths"]),
        "raycast_total": int(state["raycast_total"]),
        "raycast_hit_count": int(state["raycast_hit_count"]),
        "raycast_log": list(state["raycast_log"]),
        "debug_draw_events": int(state["debug_draw_events"]),
        "debug_lines_total": int(state["debug_lines_total"]),
        "diagnostics_event_count": int(state["diagnostics_event_count"]),
        "diagnostics_stats": dict(state["diagnostics_stats_final"]),
        "top_subsystems": [
            {"subsystem": name, "count": int(count)}
            for name, count in top_subsystems
        ],
        "audio_voice_id": state["audio_voice_id"],
        "recording_started": bool(state["recording_started"]),
        "recording_stopped": bool(state["recording_stopped"]),
        "warning_triggered": bool(state["warning_triggered"]),
        "degradation_notes": list(state["degradation_notes"]),
        "trace_event_count": len(app.trace),
    }
    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    summary: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "subsystems_used": subsystems_used_sorted,
        "screenshot_count": int(state["screenshot_count"]),
        "raycast_total": int(state["raycast_total"]),
        "raycast_hit_count": int(state["raycast_hit_count"]),
        "debug_draw_events": int(state["debug_draw_events"]),
        "diagnostics_event_count": int(state["diagnostics_event_count"]),
        "recording_started": bool(state["recording_started"]),
        "recording_stopped": bool(state["recording_stopped"]),
        "degradation_notes": list(state["degradation_notes"]),
        "trace_path": str(out_path),
    }

    print("=== hello_full_lifecycle summary ===")
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
