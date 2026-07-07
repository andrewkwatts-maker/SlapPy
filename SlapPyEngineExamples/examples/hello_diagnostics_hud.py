"""hello_diagnostics_hud — OO6 diagnostics + LL1 HUD end-to-end showcase.

QQ5 sprint deliverable: run a 90-frame headless demo that deliberately
provokes warnings from real subsystems (``audio_3d`` + ``render``), lets
the :class:`~slappyengine.DiagnosticsCollector` capture them, then at
frame 45 mounts the diagnostics HUD widget so the last few events appear
in-viewport.

Scene
-----

* A 3D scene with a triangle model + camera + light so the render path
  ticks (identical to :mod:`hello_hud`).
* On ``on_begin``: the module-level :class:`DiagnosticsCollector` is
  installed via :func:`get_global_collector`, and the default game HUD
  is mounted via :meth:`App.enable_hud`.
* On every ``on_tick``:

    - :class:`SoundBank.load` is called against a bogus filesystem path
      to hit MM1's ``OSError`` warn path in ``slappyengine.audio_3d``
      (this actually emits *two* warnings per call — one for the
      ``OSError`` and one for the ``None`` handle fallback).
    - A fresh :class:`~slappyengine.render.skybox.Skybox` is rendered
      against a fresh no-op renderer that lacks
      ``draw_log`` / ``submit_skybox`` / ``draw_skybox`` — hitting the
      warn-once fallback in ``slappyengine.render.skybox``. The renderer
      is fresh each frame so each frame produces a new subsystem warning
      (the module dedupes on ``id(renderer)``).

* At frame 45: :func:`slappyengine.hud_bridge.add_diagnostics_widget` is
  called against the app; the trace records a
  ``("diagnostics_widget_mounted", frame_no)`` event so the smoke test
  can assert on the wiring.

Output
------

* ``hello_diagnostics_hud_trace.yaml`` next to the demo:

    - ``frame_count`` — final frame count
    - ``total_warnings`` / ``total_errors`` — collector totals at end
    - ``subsystems_warned`` — sorted list of unique subsystem names
    - ``diagnostics_stats`` — final :meth:`DiagnosticsCollector.stats`
      snapshot
    - ``diagnostics_widget_mounted_frame`` — frame the widget landed on
    - ``events`` — the app trace stream (as ``[kind, *args]`` lists)

Run
---

::

    python SlapPyEngineExamples/examples/hello_diagnostics_hud.py

Headless-safe (``AppConfig(enable_gpu=False)``). No wgpu / audio hardware
required.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_TRIANGLE_OBJ = _THIS_DIR / "assets" / "triangle.obj"
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_diagnostics_hud_trace.yaml"

DEFAULT_MAX_FRAMES: int = 90
DIAGNOSTICS_WIDGET_MOUNT_FRAME: int = 45


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _triangle_path() -> str:
    """Return the absolute path to the bundled triangle model, or ``""``."""
    return str(_TRIANGLE_OBJ) if _TRIANGLE_OBJ.exists() else ""


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` sized for a 1280x720 HUD."""
    import slappyengine

    return slappyengine.AppConfig(
        window_title="hello_diagnostics_hud",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


class _NoopRenderer:
    """A minimal renderer that lacks ``draw_log`` / ``submit_skybox``.

    :class:`Skybox.render` will fall through to its warn-once branch when
    handed one of these; we use a fresh instance per frame so each frame
    produces a new warning (the module dedupes on ``id(renderer)``).
    """

    __slots__ = ()


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump the trace payload to YAML; falls back to ``repr`` if pyyaml missing."""
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
    trace_yaml_path: str | Path | None = None,
    widget_mount_frame: int = DIAGNOSTICS_WIDGET_MOUNT_FRAME,
) -> Dict[str, Any]:
    """Run the diagnostics-HUD demo and return a summary dict.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 90).
    trace_yaml_path:
        Where to write the trace YAML. ``None`` = default next to demo.
    widget_mount_frame:
        Frame index on which the diagnostics HUD widget is mounted
        (default 45).
    """
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1 (got {max_frames})")
    if widget_mount_frame < 0 or widget_mount_frame >= max_frames:
        raise ValueError(
            f"widget_mount_frame must be in [0, max_frames) — got "
            f"{widget_mount_frame} with max_frames={max_frames}"
        )

    import slappyengine
    from slappyengine import get_global_collector, hud_bridge
    from slappyengine.audio_3d import SoundBank
    from slappyengine.render.skybox import (
        Skybox,
        procedural_gradient_sky,
    )

    # ---- Fresh collector state -----------------------------------------
    #
    # Some test runners share a process and may leave events from prior
    # runs. Grab the singleton, clear its buffer, and install the handler.
    collector = get_global_collector()
    collector.clear()
    collector.install()

    # Cache one skybox — cheap, and its state is idempotent between
    # render calls; only the *renderer* argument needs to be fresh
    # per frame to bypass the warn-once dedupe.
    skybox = Skybox(cubemap=procedural_gradient_sky(resolution=8))

    # SoundBank persists across ticks so the internal warn path is
    # invoked each frame (not memoised).
    bank = SoundBank()

    # ``launch`` builds its own :class:`App`; stash a reference here in
    # ``on_begin`` so we can serialise ``app.trace`` after it returns.
    state: Dict[str, Any] = {
        "app": None,
        "widget_mounted": False,
        "widget": None,
        "widget_mounted_frame": None,
    }

    # ---- Lifecycle callbacks -------------------------------------------

    def on_begin(a: Any) -> None:
        state["app"] = a

        # Best-effort scene setup so the render tick has substance.
        tri_path = _triangle_path()
        if tri_path:
            try:
                a.load_model(tri_path)
            except Exception:  # pragma: no cover — best-effort
                pass
        try:
            a.spawn_camera(position=(0.0, 0.0, 3.0), look_at=(0.0, 0.0, 0.0))
        except Exception:  # pragma: no cover — API drift safety net
            pass
        try:
            a.spawn_light((5.0, 5.0, 5.0))
        except Exception:  # pragma: no cover — API drift safety net
            pass

        # Mount the HUD (records ``hud_mount`` in the app trace).
        a.enable_hud()
        # Record that the collector is installed so downstream tools can
        # see the ordering.
        a.trace.append(("diagnostics_installed", bool(collector.is_installed())))

    def on_tick(a: Any, _dt: float) -> None:
        frame = a.frame_count

        # --- Trigger 1: audio_3d subsystem (2 warnings per call) --------
        # A path that will not exist across any sane OS. This exercises
        # the ``OSError → warn`` branch AND the ``handle-is-None →
        # register stub`` warn branch in :meth:`SoundBank.load`.
        bogus_path = f"/no/such/path/frame_{frame}.wav"
        try:
            bank.load(f"beacon_frame_{frame}", bogus_path)
        except Exception:  # pragma: no cover — SoundBank returns, no raise
            pass

        # --- Trigger 2: render subsystem (1 warning per fresh renderer) -
        # Fresh renderer each frame so the module-level dedupe set
        # doesn't swallow subsequent calls.
        skybox.render(renderer=_NoopRenderer(), camera=None)

        # --- Frame 45: mount the diagnostics widget ---------------------
        if not state["widget_mounted"] and frame >= widget_mount_frame:
            widget = hud_bridge.add_diagnostics_widget(a, collector=collector)
            state["widget"] = widget
            state["widget_mounted"] = True
            state["widget_mounted_frame"] = frame
            a.trace.append(("diagnostics_widget_mounted", int(frame)))

    def on_end(a: Any) -> None:
        # Emit a final marker so tests can distinguish "on_end fired" from
        # "loop exited abnormally".
        a.trace.append(("diagnostics_demo_end", int(a.frame_count)))

    # ---- Run ------------------------------------------------------------
    app = slappyengine.launch(
        on_begin=on_begin,
        on_tick=on_tick,
        on_end=on_end,
        max_frames=max_frames,
        config=_headless_config(),
    )

    # ---- Roll up stats --------------------------------------------------
    stats = collector.stats()
    events = collector.events()
    total_warnings = int(stats.get("level:WARNING", 0))
    total_errors = int(stats.get("level:ERROR", 0)) + int(
        stats.get("level:CRITICAL", 0)
    )
    subsystems_warned: List[str] = sorted(
        {evt.subsystem for evt in events if evt.level == "WARNING"}
    )

    # ---- Persist trace + collector summary ------------------------------
    trace_events = [list(ev) for ev in app.trace]
    payload: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "max_frames": int(max_frames),
        "widget_mount_frame": int(widget_mount_frame),
        "diagnostics_widget_mounted_frame": state["widget_mounted_frame"],
        "total_warnings": total_warnings,
        "total_errors": total_errors,
        "subsystems_warned": subsystems_warned,
        "diagnostics_stats": dict(stats),
        "trace_event_count": len(trace_events),
        "events": trace_events,
    }

    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    summary: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "total_warnings": total_warnings,
        "total_errors": total_errors,
        "subsystems_warned": subsystems_warned,
        "diagnostics_widget_mounted_frame": state["widget_mounted_frame"],
        "trace_path": str(out_path),
        "trace_event_count": len(trace_events),
    }

    print("=== hello_diagnostics_hud summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    # Leave the collector installed so subsequent code can inspect it.
    # Tests that want a clean slate can call ``collector.clear()`` /
    # ``collector.uninstall()`` themselves.
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
