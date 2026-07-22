"""hello_hud — rotating 3D scene with a live game HUD overlay.

MM2 sprint deliverable (2026-07-05): showcase the newly wired
:func:`pharos_engine.hud_bridge.mount_hud` glue by booting an :class:`App`,
loading a real 3D model, enabling the default game HUD via
:meth:`App.enable_hud`, then running a 60-frame tick loop that:

* Depletes the ``HealthBar`` value from 100 → 0 over the run.
* Increments the ``AmmoCounter.current`` field every tick.
* Rotates the active camera around the model on a horizontal orbit.
* Advances the ``Compass.heading_deg`` in sync with the camera orbit.
* Emits a rich trace stream (target: >= 30 events) so the demo test can
  assert on end-to-end HUD activity.

Run
---

::

    python SlapPyEngineExamples/examples/hello_hud.py

The demo is headless-safe (``AppConfig(enable_gpu=False)``) — the HUD
plumbs into :class:`pharos_engine.hud_bridge._HUDStubRenderer` when the
real renderer lacks the ``submit_sprite`` surface, so trace assertions
still fire in CI.

Output
------

* ``hello_hud_trace.yaml`` next to the demo — the full app trace stream
  serialised for inspection / replay.
* A summary dict returned from :func:`main` with the frame count, final
  HUD widget state, and the trace event count.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_TRIANGLE_OBJ = _THIS_DIR / "assets" / "triangle.obj"
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_hud_trace.yaml"

# Frames + loop parameters. Kept as module-level constants so tests can
# import and assert on them without duplicating magic numbers.
DEFAULT_MAX_FRAMES = 60
DEFAULT_START_HP = 100.0
DEFAULT_END_HP = 40.0
DEFAULT_START_AMMO = 30
DEFAULT_CAMERA_RADIUS = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _triangle_path() -> str:
    """Return the absolute path to the bundled triangle model."""
    return str(_TRIANGLE_OBJ)


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` sized for a 1280x720 HUD."""
    import pharos_engine

    return pharos_engine.AppConfig(
        window_title="hello_hud",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


def _write_trace_yaml(trace: list, path: Path) -> Path:
    """Serialise the trace stream to YAML for inspection / replay.

    Each event tuple is coerced to a list so PyYAML emits a stable
    sequence. Falls back to a plain repr() when PyYAML is unavailable so
    the demo never crashes on a stripped install.
    """
    try:
        import yaml
    except Exception:  # pragma: no cover
        path.write_text("\n".join(repr(t) for t in trace), encoding="utf-8")
        return path
    payload = {
        "trace_event_count": len(trace),
        "events": [list(event) for event in trace],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    trace_yaml_path: str | Path | None = None,
) -> dict:
    """Boot the demo, run the tick loop, and return a summary dict.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 60).
    trace_yaml_path:
        Path to write the trace YAML to. Pass ``None`` for the default
        location next to the demo, or an explicit path for tests.

    Returns
    -------
    dict
        Summary with keys ``frame_count``, ``trace_event_count``,
        ``health_bar_final``, ``ammo_counter_final``,
        ``compass_final_deg``, ``hud_command_count``, ``trace_path``.
    """
    import pharos_engine

    app = pharos_engine.App(config=_headless_config())

    # 1. Load a real 3D model via HH5.
    model = app.load_model(_triangle_path())

    # 2. Spawn a camera + light so the scene has framing.
    camera = app.spawn_camera(
        position=(0.0, 0.0, DEFAULT_CAMERA_RADIUS),
        look_at=(0.0, 0.0, 0.0),
    )
    app.spawn_light((5.0, 5.0, 5.0))

    # 3. Enable the default game HUD.
    overlay = app.enable_hud()
    widgets = overlay.widgets()

    # Locate the widgets we want to drive each frame. The default set is
    # ordered [HealthBar, StaminaBar, AmmoCounter, Compass, Crosshair].
    from pharos_engine.ui.runtime.hud_kit import (
        AmmoCounter,
        Compass,
        HealthBar,
        StaminaBar,
    )
    from pharos_engine.ui.runtime.hud_kit_extra import Crosshair

    health_bar: HealthBar = next(w for w in widgets if isinstance(w, HealthBar))
    stamina_bar: StaminaBar = next(w for w in widgets if isinstance(w, StaminaBar))
    ammo: AmmoCounter = next(w for w in widgets if isinstance(w, AmmoCounter))
    compass: Compass = next(w for w in widgets if isinstance(w, Compass))
    _crosshair: Crosshair = next(w for w in widgets if isinstance(w, Crosshair))

    # 4. Drive HUD state + camera orbit each frame.
    def on_tick(a: Any, dt: float) -> None:
        """Deplete HP, bump ammo, orbit the camera, spin the compass."""
        frame = a.frame_count
        progress = min(1.0, frame / max(1, max_frames - 1))

        # HealthBar depletes linearly from START → END over the run.
        health_bar.value = DEFAULT_START_HP - (DEFAULT_START_HP - DEFAULT_END_HP) * progress

        # StaminaBar wobbles between 40 and 100 so we can eyeball animation.
        stamina_bar.value = 70.0 + 30.0 * math.sin(frame * 0.15)

        # AmmoCounter ticks +1 each frame (mostly).
        ammo.current = DEFAULT_START_AMMO + frame

        # Compass tracks the camera bearing.
        theta = 2.0 * math.pi * progress
        compass.heading_deg = math.degrees(theta) % 360.0

        # Orbit the camera around the model on a horizontal ring.
        camera.move_to(
            DEFAULT_CAMERA_RADIUS * math.sin(theta),
            0.0,
            DEFAULT_CAMERA_RADIUS * math.cos(theta),
        )

        # Rotate the model too so the render trace has motion regardless
        # of the HUD path.
        model.rotate_by(0.0, dt, 0.0)

    app.run(on_tick=on_tick, max_frames=max_frames)

    # 5. Persist the trace stream for inspection / replay.
    out_path = Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    _write_trace_yaml(app.trace, out_path)

    summary = {
        "frame_count": app.frame_count,
        "trace_event_count": len(app.trace),
        "health_bar_final": float(health_bar.value),
        "ammo_counter_final": int(ammo.current),
        "compass_final_deg": float(compass.heading_deg),
        "hud_command_count": overlay.command_count,
        "trace_path": str(out_path),
    }

    # 6. Print the summary so manual runs surface something interesting.
    print("=== hello_hud summary ===")
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
