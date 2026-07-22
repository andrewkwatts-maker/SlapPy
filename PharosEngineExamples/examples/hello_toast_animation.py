"""hello_toast_animation — CC5 toast manager + CC6 camera animator walkthrough.

DD-batch sprint (2026-07-05) — task DD2. Ties the ``NotebookToastManager``
and ``CameraAnimator`` together in a scripted 6-second scene so a caller
(or CI) can watch a camera dance while diary-themed toasts pop over it.

What the demo does
------------------

The demo runs a scripted timeline in *simulated* milliseconds — no real
sleeps — driving ``toast_manager.tick(t_ms)`` and ``animator.tick(t_ms)``
at 60 FPS (frame delta ~= 16.667 ms). Each frame records the camera's
position, distance, active-tween count, and live toast count into a
trace log. A YAML dump lands next to the module and a table of key
milestones prints to stdout.

Scripted events (all ``t_ms`` are simulated):

* t=0     — toast INFO "Welcome! Watching the camera dance..."
* t=200   — start ``tween_to_position((5, 3, 0))`` over 1500 ms, ease_in_out
* t=500   — toast SUCCESS "Panning east..." sticker ">"
* t=1200  — start ``tween_to_zoom(2.0)`` over 800 ms, bounce
* t=1500  — toast WARN "Zoom overshooting - bounce curve" sticker "!"
* t=2500  — ``animator.stop_all()``, toast ERROR "Stopped abruptly" sticker "x"
* t=3000  — toast INFO "Restoring default view"
* t=3200  — ``focus_on_entity(mock_entity_at_origin, 1500ms, "ease_out")``
* t=5000  — toast SUCCESS "Focus complete" sticker "*"
* t=6000  — end

Headless contract
-----------------

The demo never touches DPG — the toast manager is headless-safe by
design and the animator only mutates duck-typed attributes on the
``MockCamera``. The whole thing runs inside CI without a viewport.

Run:
    python PharosEngineExamples/examples/hello_toast_animation.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pharos_editor.actions.camera_animation_actions import CameraAnimator
from pharos_editor.ui.editor.notebook_toast_manager import (
    NotebookToastManager,
    ToastLevel,
)


# ---------------------------------------------------------------------------
# Mock camera + mock entity
# ---------------------------------------------------------------------------


@dataclass
class MockCamera:
    """Duck-typed camera surface — ``_cam_target`` + ``_cam_distance``.

    Both attributes are the ones ``CameraAnimator`` reads/writes through
    ``_read_position`` / ``_write_position`` / ``_read_zoom`` /
    ``_write_zoom``. A plain dataclass mirrors what ``EditorShell``'s
    ``ViewportPanel`` exposes without pulling in the render stack.
    """

    _cam_target: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    _cam_distance: float = 5.0


@dataclass
class MockEntity:
    """Minimal ``focus_on_entity`` target — needs ``position`` (and AABB)."""

    id: str = "origin_beacon"
    name: str = "origin_beacon"
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def aabb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Zero-extent box around ``position`` — animator infers distance."""
        px, py, pz = self.position
        return ((px, py, pz), (px, py, pz))


# ---------------------------------------------------------------------------
# Trace recorder — mirrors hello_integrated_notebook.DemoTrace surface.
# ---------------------------------------------------------------------------


class DemoTrace:
    """Scripted event log — dumped to YAML at demo end."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, /, **payload: Any) -> None:
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

    def as_yaml(self) -> str:
        """Serialise to YAML. Falls back to a hand-rolled dumper if pyyaml is missing."""
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(
                {"events": self.events, "event_count": len(self.events)},
                sort_keys=False,
            )
        except Exception:
            return _hand_yaml(
                {"events": self.events, "event_count": len(self.events)}
            )


def _hand_yaml(data: Any, indent: int = 0) -> str:
    """Minimal YAML dumper covering nested dicts / lists / scalars."""
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}\n"
        out = ""
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                out += f"{pad}{k}:\n{_hand_yaml(v, indent + 1)}"
            else:
                out += f"{pad}{k}: {_scalar_yaml(v)}\n"
        return out
    if isinstance(data, list):
        if not data:
            return f"{pad}[]\n"
        out = ""
        for item in data:
            if isinstance(item, dict):
                lines = _hand_yaml(item, indent + 1).splitlines()
                if lines:
                    first = lines[0].lstrip()
                    out += f"{pad}- {first}\n"
                    for line in lines[1:]:
                        out += f"{line}\n"
            else:
                out += f"{pad}- {_scalar_yaml(item)}\n"
        return out
    return f"{pad}{_scalar_yaml(data)}\n"


def _scalar_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(c in text for c in ":#\n") or text in ("", "null", "true", "false"):
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    return text


# ---------------------------------------------------------------------------
# Scripted event schedule — a plain list of (t_ms, action) callbacks.
# ---------------------------------------------------------------------------


FRAME_DT_MS: float = 1000.0 / 60.0  # 60 FPS ~= 16.667 ms/frame
TOTAL_DURATION_MS: float = 6000.0


def _build_schedule(
    toast: NotebookToastManager,
    animator: CameraAnimator,
    camera: MockCamera,
    entity: MockEntity,
    trace: DemoTrace,
) -> list[tuple[float, Any]]:
    """Return the scripted (t_ms, callable) pairs.

    Each callable receives ``t_ms`` (the simulated time it was fired at)
    so it can log the event with the exact timestamp.
    """

    def welcome(t: float) -> None:
        tid = toast.show(
            "Welcome! Watching the camera dance...",
            level=ToastLevel.INFO,
        )
        trace.record(
            "toast_shown", t_ms=t, level="INFO", toast_id=tid,
            message="Welcome! Watching the camera dance...",
        )

    def start_pan(t: float) -> None:
        state = animator.tween_to_position(
            camera, (5.0, 3.0, 0.0),
            duration_ms=1500.0, easing="ease_in_out", now_ms=t,
        )
        trace.record(
            "tween_started", t_ms=t, tween_kind="position",
            target=[5.0, 3.0, 0.0], duration_ms=1500.0, easing="ease_in_out",
            success=state is not None,
        )

    def toast_pan_success(t: float) -> None:
        tid = toast.show(
            "Panning east...",
            level=ToastLevel.SUCCESS, sticker=">",
        )
        trace.record(
            "toast_shown", t_ms=t, level="SUCCESS", sticker=">",
            toast_id=tid, message="Panning east...",
        )

    def start_zoom(t: float) -> None:
        state = animator.tween_to_zoom(
            camera, 2.0,
            duration_ms=800.0, easing="bounce", now_ms=t,
        )
        trace.record(
            "tween_started", t_ms=t, tween_kind="zoom",
            target=2.0, duration_ms=800.0, easing="bounce",
            success=state is not None,
        )

    def toast_zoom_warn(t: float) -> None:
        tid = toast.show(
            "Zoom overshooting - bounce curve",
            level=ToastLevel.WARN, sticker="!",
        )
        trace.record(
            "toast_shown", t_ms=t, level="WARN", sticker="!",
            toast_id=tid, message="Zoom overshooting - bounce curve",
        )

    def stop_all(t: float) -> None:
        cancelled = animator.stop_all()
        trace.record("tweens_stopped", t_ms=t, cancelled=cancelled)
        tid = toast.show(
            "Stopped abruptly",
            level=ToastLevel.ERROR, sticker="x",
        )
        trace.record(
            "toast_shown", t_ms=t, level="ERROR", sticker="x",
            toast_id=tid, message="Stopped abruptly",
        )

    def restore_info(t: float) -> None:
        tid = toast.show(
            "Restoring default view",
            level=ToastLevel.INFO,
        )
        trace.record(
            "toast_shown", t_ms=t, level="INFO",
            toast_id=tid, message="Restoring default view",
        )

    def focus_entity(t: float) -> None:
        state = animator.focus_on_entity(
            camera, entity,
            duration_ms=1500.0, easing="ease_out", now_ms=t,
        )
        trace.record(
            "focus_started", t_ms=t, entity_id=entity.id,
            duration_ms=1500.0, easing="ease_out",
            success=state is not None,
        )

    def focus_success(t: float) -> None:
        tid = toast.show(
            "Focus complete",
            level=ToastLevel.SUCCESS, sticker="*",
        )
        trace.record(
            "toast_shown", t_ms=t, level="SUCCESS", sticker="*",
            toast_id=tid, message="Focus complete",
        )

    return [
        (0.0,    welcome),
        (200.0,  start_pan),
        (500.0,  toast_pan_success),
        (1200.0, start_zoom),
        (1500.0, toast_zoom_warn),
        (2500.0, stop_all),
        (3000.0, restore_info),
        (3200.0, focus_entity),
        (5000.0, focus_success),
    ]


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


def run_demo(
    *,
    trace_path: Path | str | None = None,
    frame_dt_ms: float = FRAME_DT_MS,
    total_duration_ms: float = TOTAL_DURATION_MS,
) -> DemoTrace:
    """Run the scripted demo end-to-end and return the trace.

    Parameters
    ----------
    trace_path:
        Where to write the YAML trace. Defaults to
        ``hello_toast_animation_trace.yaml`` next to this file.
    frame_dt_ms:
        Frame delta in ms. Defaults to 60 FPS (~16.667 ms).
    total_duration_ms:
        Simulated wall time to run for. Defaults to 6000 ms.
    """
    trace = DemoTrace()
    trace.record(
        "demo_start", python=sys.version.split()[0],
        frame_dt_ms=frame_dt_ms, total_duration_ms=total_duration_ms,
    )

    camera = MockCamera(_cam_target=[0.0, 0.0, 0.0], _cam_distance=5.0)
    entity = MockEntity()
    toast = NotebookToastManager()
    animator = CameraAnimator()

    trace.record(
        "setup",
        cam_target=list(camera._cam_target),
        cam_distance=float(camera._cam_distance),
        entity_id=entity.id,
    )

    schedule = _build_schedule(toast, animator, camera, entity, trace)
    schedule_idx = 0

    t_ms = 0.0
    frame_idx = 0
    while t_ms <= total_duration_ms + 1e-6:
        # Fire any scheduled callbacks whose t_ms has been reached.
        while (
            schedule_idx < len(schedule)
            and schedule[schedule_idx][0] <= t_ms + 1e-6
        ):
            fire_t, cb = schedule[schedule_idx]
            cb(fire_t)
            schedule_idx += 1

        # Drive both subsystems.
        toast_progress = toast.tick(t_ms)
        driven = animator.tick(t_ms)

        # Snapshot per frame.
        trace.record(
            "frame",
            frame_idx=frame_idx,
            t_ms=round(t_ms, 3),
            cam_target=[round(v, 4) for v in camera._cam_target],
            cam_distance=round(float(camera._cam_distance), 4),
            active_tweens=animator.active_count(),
            driven=driven,
            active_toasts=len(toast.active_toasts()),
            visible_toast_progress=len(toast_progress),
        )

        frame_idx += 1
        t_ms += frame_dt_ms

    # Terminal state snapshot.
    trace.record(
        "demo_end",
        frames=frame_idx,
        final_cam_target=list(camera._cam_target),
        final_cam_distance=float(camera._cam_distance),
        final_active_tweens=animator.active_count(),
        final_active_toasts=len(toast.active_toasts()),
        total_events=len(trace.events) + 1,
    )

    out_path = Path(trace_path) if trace_path is not None else (
        Path(__file__).with_name("hello_toast_animation_trace.yaml")
    )
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(trace.as_yaml(), encoding="utf-8")
        trace.record("trace_written", path=str(out_path), events=len(trace.events))
    except Exception as exc:  # pragma: no cover — disk failure paths
        trace.record("trace_write_failed", error=str(exc))

    return trace


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(trace: DemoTrace) -> None:
    """Print a small table of milestones to stdout."""
    toast_events = [e for e in trace.events if e["kind"] == "toast_shown"]
    tween_events = [e for e in trace.events if e["kind"] == "tween_started"]
    focus_events = [e for e in trace.events if e["kind"] == "focus_started"]
    stop_events = [e for e in trace.events if e["kind"] == "tweens_stopped"]
    frames = [e for e in trace.events if e["kind"] == "frame"]

    print("hello_toast_animation — summary")
    print("-" * 60)
    print(f"  frames recorded       : {len(frames)}")
    print(f"  toasts fired          : {len(toast_events)}")
    print(f"  tweens started        : {len(tween_events)}")
    print(f"  focus_on_entity calls : {len(focus_events)}")
    print(f"  stop_all calls        : {len(stop_events)}")

    print("-" * 60)
    print("  timeline (toast_shown / tween_started / stop / focus):")
    print("  t_ms      kind             detail")
    for e in trace.events:
        if e["kind"] in ("toast_shown", "tween_started",
                         "tweens_stopped", "focus_started"):
            detail = ""
            if e["kind"] == "toast_shown":
                detail = f"{e['level']}: {e['message'][:36]}"
            elif e["kind"] == "tween_started":
                detail = (
                    f"tween_kind={e.get('tween_kind')} "
                    f"target={e.get('target')} ease={e.get('easing')}"
                )
            elif e["kind"] == "focus_started":
                detail = f"entity={e['entity_id']} ease={e['easing']}"
            elif e["kind"] == "tweens_stopped":
                detail = f"cancelled={e['cancelled']}"
            print(f"  {e.get('t_ms', 0):>8.1f}  {e['kind']:<16} {detail}")
    print("-" * 60)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover — CLI convenience
    trace = run_demo()
    _print_summary(trace)


if __name__ == "__main__":  # pragma: no cover
    main()
