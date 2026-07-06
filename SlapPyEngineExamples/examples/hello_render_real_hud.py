"""hello_render_real_hud — combined bunny + game HUD + screenshot showcase.

OO3 sprint deliverable (2026-07-06): stitch three previously-independent
end-to-end features into a single 120-frame demo:

* **MM7** — real 3D scene: load ``assets/bunny_low.obj`` via
  :meth:`App.load_model`, spawn a key light + orbit camera.
* **MM2 / LL1** — enable the default game HUD via
  :meth:`App.enable_hud` so five widgets (HealthBar, StaminaBar,
  AmmoCounter, Compass, Crosshair) drive per-frame ``hud_begin_frame``
  + ``hud_submit`` trace events.
* **NN3** — call :meth:`App.take_screenshot` mid-run at frame 60 to
  prove the capture façade is wired.

Behaviour contract
------------------

* Headless-safe (``AppConfig(enable_gpu=False)``): the HUD folds through
  the :class:`slappyengine.hud_bridge._HUDStubRenderer` when the
  underlying renderer lacks ``submit_sprite``; the screenshot façade
  reports ``"capture_unavailable"`` on the stub — the demo records the
  event either way so tests can pin the wiring.
* Runs exactly ``max_frames`` frames (default 120). Rotates the bunny
  gently around Y each tick. Camera stays fixed.
* Writes a ``hello_render_real_hud_trace.yaml`` alongside the demo (or
  to a caller-supplied path) with:

  * ``model_load``     — one event.
  * ``hud_mount``      — one event with ``widget_count``.
  * ``rotation`` events — one per frame with ``(frame, angle_rad)``.
  * ``screenshot_saved`` — exactly one at frame 60 with the requested path.
  * ``hud_widget_count`` — one per frame with the live widget count.

Run
---

::

    python SlapPyEngineExamples/examples/hello_render_real_hud.py

Returns a summary dict with ``frame_count``, ``trace_event_count``,
``screenshot_path``, ``hud_widget_count`` and ``trace_path`` so manual
runs surface something interesting.
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
_BUNNY_OBJ = _THIS_DIR / "assets" / "bunny_low.obj"
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_render_real_hud_trace.yaml"
_DEFAULT_SHOT_PNG = _THIS_DIR / "hello_render_real_hud_screenshot.png"

DEFAULT_MAX_FRAMES = 120
DEFAULT_SCREENSHOT_FRAME = 60
DEFAULT_ROTATION_SPEED_RAD = 0.5  # rad/sec — gentle Y-axis spin.


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _bunny_path() -> str:
    """Return the absolute path to the bundled MM7 bunny mesh."""
    return str(_BUNNY_OBJ)


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` sized for a 1280x720 HUD."""
    import slappyengine

    return slappyengine.AppConfig(
        window_title="hello_render_real_hud",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        msaa_samples=4,
        clear_color=(0.85, 0.9, 0.95, 1.0),
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


# ---------------------------------------------------------------------------
# Trace YAML writer — same shape as hello_hud so tooling can grep alike.
# ---------------------------------------------------------------------------


def _write_trace_yaml(trace: list, path: Path) -> Path:
    """Serialise the trace stream to YAML for inspection / replay.

    Falls back to a repr() dump when PyYAML is missing so the demo
    stays functional on trimmed installs.
    """
    try:
        import yaml
    except Exception:  # pragma: no cover - trimmed env
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
    screenshot_frame: int = DEFAULT_SCREENSHOT_FRAME,
    screenshot_path: str | Path | None = None,
    trace_yaml_path: str | Path | None = None,
) -> dict:
    """Boot the combined MM7 + LL1 + NN3 showcase and return a summary dict.

    Parameters
    ----------
    max_frames:
        Frame cap (default 120).
    screenshot_frame:
        Which frame index triggers :meth:`App.take_screenshot`. Default
        is frame 60 — halfway through the default run.
    screenshot_path:
        Optional explicit PNG output. When ``None`` the default lives
        alongside the demo module.
    trace_yaml_path:
        Optional explicit YAML output. When ``None`` the default lives
        alongside the demo module.

    Returns
    -------
    dict
        Summary dict — see the module docstring for the keys.
    """
    import slappyengine

    # Where to write the mid-run screenshot. Resolve here so a caller
    # passing a ``tmp_path`` fixture gets the file where they expect.
    shot_out = Path(screenshot_path) if screenshot_path is not None else _DEFAULT_SHOT_PNG
    shot_out.parent.mkdir(parents=True, exist_ok=True)

    app = slappyengine.App(config=_headless_config())

    # 1. Load the MM7 bunny mesh + record a model_load event.
    bunny = app.load_model(_bunny_path())
    bunny.move_to(0.0, 0.0, 0.0)
    app.trace.append(("model_load", _bunny_path()))

    # 2. Framing — one key light + one orbit camera looking at the bunny.
    app.spawn_light((5.0, 8.0, 5.0), color=(1.0, 0.95, 0.85), intensity=1.5)
    app.spawn_camera((3.0, 2.0, 5.0), look_at=(0.0, 0.5, 0.0))

    # 3. Enable the LL1 default game HUD via NN3-era App façade.
    overlay = app.enable_hud()
    widget_count = len(overlay.widgets())

    # Mid-run capture bookkeeping — take_screenshot is only ever fired
    # once even if the caller sets ``screenshot_frame >= max_frames``
    # (in which case we skip cleanly to keep the "exactly one" contract).
    fired = {"screenshot": False}

    # 4. Per-frame tick: rotate the bunny + trigger the screenshot once.
    def on_tick(a: Any, dt: float) -> None:
        frame = a.frame_count
        angle = frame * DEFAULT_ROTATION_SPEED_RAD * dt
        bunny.rotate_to(0.0, angle, 0.0)
        a.trace.append(("rotation", int(frame), float(angle)))

        # Live widget-count snapshot per frame so the trace shows the HUD
        # stayed populated throughout.
        current_hud = getattr(a, "_hud_overlay", None)
        live_count = len(current_hud.widgets()) if current_hud is not None else 0
        a.trace.append(("hud_widget_count", int(frame), int(live_count)))

        # 5. NN3 screenshot fire — exactly once at ``screenshot_frame``.
        if not fired["screenshot"] and frame == screenshot_frame:
            result = a.take_screenshot(path=str(shot_out))
            a.trace.append((
                "screenshot_saved",
                str(shot_out),
                str(result.get("status", "unknown")),
            ))
            fired["screenshot"] = True

    def on_end(a: Any) -> None:
        # Recorded so tests / tooling can prove the on_end path fired
        # after the tick loop closed out cleanly.
        a.trace.append(("on_end", int(a.frame_count)))

    app.run(on_tick=on_tick, on_end=on_end, max_frames=max_frames)

    # 6. Persist the trace stream.
    out_trace = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(app.trace, out_trace)

    summary = {
        "frame_count": app.frame_count,
        "trace_event_count": len(app.trace),
        "hud_widget_count": widget_count,
        "screenshot_path": str(shot_out),
        "screenshot_fired": fired["screenshot"],
        "trace_path": str(out_trace),
    }

    print("=== hello_render_real_hud summary ===")
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
