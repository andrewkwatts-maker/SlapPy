"""Pharos Engine — Hello Telemetry

Minimal demo of :mod:`pharos_engine.telemetry`.

The demo wires three subscribers to the engine bus:

* ``physics_logger`` — pattern ``"physics.*"``; counts every physics event.
* ``zone_watcher``   — pattern ``"zone.enter"``; appends payloads to a list.
* ``wildcard``       — pattern ``"*"``; full event counter.

It then drives a 60-frame timeline. Each frame emits ``physics.step`` and
``render.frame``. On selected frames (10/20/30/40/50) it also emits
``zone.enter`` carrying a synthetic entity id, and on frame 25 it emits a
single ``thermal.phase_change`` event. After the timeline the demo queries
``get_event_history(name_pattern="zone.*")`` and asserts the buffer holds
exactly five records.

A small benchmark closes out: 100,000 emits with zero subscribers (the
allocation-free fast path) and 100,000 emits with the three subscribers
plus 100 spurious ``zone.*`` subscribers attached. The measured ns/emit
for both arms is printed.

Run::

    PYTHONPATH=python python examples/hello_telemetry.py
    PYTHONPATH=python python examples/hello_telemetry.py --render
    PYTHONPATH=python python examples/hello_telemetry.py --frames 60 --render --out out/

When ``--render`` is supplied the demo rasterises a small histogram of
events-per-second across the 60 timeline frames with pure PIL — no GPU.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

import pharos_engine.telemetry as telemetry


# ── Demo parameters ────────────────────────────────────────────────────────
DEFAULT_FRAMES: int = 60
DEFAULT_DT: float = 1.0 / 60.0

ZONE_ENTER_FRAMES: Tuple[int, ...] = (10, 20, 30, 40, 50)
THERMAL_PHASE_FRAME: int = 25
ZONE_NAME: str = "test_zone"

BENCH_EMITS: int = 100_000
BENCH_EXTRA_ZONE_SUBS: int = 100

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 1280
RENDER_H: int = 720
RENDER_BG: Tuple[int, int, int, int] = (12, 14, 22, 255)
RENDER_FG: Tuple[int, int, int, int] = (240, 240, 240, 255)
RENDER_AXIS: Tuple[int, int, int, int] = (100, 110, 130, 255)
BAR_COLOR: Tuple[int, int, int, int] = (90, 180, 240, 255)
HIGHLIGHT_COLOR: Tuple[int, int, int, int] = (240, 140, 60, 255)


# ────────────────────────────────────────────────────────────────────────────
# Telemetry plumbing
# ────────────────────────────────────────────────────────────────────────────

class Subscribers:
    """Container for the three live counters wired in :func:`build_subscribers`."""

    def __init__(self) -> None:
        self.physics_count: int = 0
        self.zone_events: List[Dict[str, Any]] = []
        self.wildcard_count: int = 0
        self._handles: List[int] = []

    def physics_logger(self, event: telemetry.TelemetryEvent) -> None:
        self.physics_count += 1

    def zone_watcher(self, event: telemetry.TelemetryEvent) -> None:
        # Copy the payload so downstream consumers can mutate freely.
        self.zone_events.append(dict(event.payload))

    def wildcard(self, event: telemetry.TelemetryEvent) -> None:
        self.wildcard_count += 1

    def attach(self) -> None:
        self._handles.append(
            telemetry.subscribe("physics.*", self.physics_logger)
        )
        self._handles.append(
            telemetry.subscribe("zone.enter", self.zone_watcher)
        )
        self._handles.append(telemetry.subscribe("*", self.wildcard))

    def detach(self) -> None:
        while self._handles:
            telemetry.unsubscribe(self._handles.pop())


def build_subscribers() -> Subscribers:
    """Wire the three demo subscribers and return the live container."""
    subs = Subscribers()
    subs.attach()
    return subs


# ────────────────────────────────────────────────────────────────────────────
# 60-frame scenario
# ────────────────────────────────────────────────────────────────────────────

def run_timeline(
    frames: int = DEFAULT_FRAMES,
    dt: float = DEFAULT_DT,
) -> Dict[str, Any]:
    """Drive the 60-frame demo timeline and return a per-frame events trace.

    Returns
    -------
    dict
        ``events_per_frame``  : list[int] — count of emits per frame
        ``zone_enter_frames`` : list[int] — frames that fired ``zone.enter``
        ``thermal_frame``     : int       — frame that fired the phase change
        ``frames``            : int       — total frames stepped
        ``dt``                : float     — simulation timestep
    """
    events_per_frame: List[int] = []
    zone_enter_frames: List[int] = []
    thermal_frame: int = -1

    zone_set = set(ZONE_ENTER_FRAMES)
    for frame in range(frames):
        n = 0
        telemetry.emit("physics.step", frame=frame, dt=dt)
        n += 1
        if frame in zone_set:
            telemetry.emit("zone.enter", zone=ZONE_NAME, entity_id=frame)
            zone_enter_frames.append(frame)
            n += 1
        telemetry.emit("render.frame", frame=frame)
        n += 1
        if frame == THERMAL_PHASE_FRAME:
            telemetry.emit(
                "thermal.phase_change",
                phase="solid->liquid",
                temperature=373.15,
            )
            thermal_frame = frame
            n += 1
        events_per_frame.append(n)

    return {
        "events_per_frame": events_per_frame,
        "zone_enter_frames": zone_enter_frames,
        "thermal_frame": thermal_frame,
        "frames": frames,
        "dt": dt,
    }


# ────────────────────────────────────────────────────────────────────────────
# Benchmarks
# ────────────────────────────────────────────────────────────────────────────

def bench_no_subscribers(emits: int = BENCH_EMITS) -> Dict[str, float]:
    """Measure ns/emit on the zero-subscriber, zero-history fast path."""
    # Drop history so emit() truly returns at the top.
    saved_capacity = telemetry._history_capacity  # snapshot for restore
    saved_history = list(telemetry._history)
    telemetry.set_history_capacity(0)
    try:
        # Use perf_counter_ns for ns-resolution.
        t0 = time.perf_counter_ns()
        for _ in range(emits):
            telemetry.emit("noop.event")
        t1 = time.perf_counter_ns()
    finally:
        # Restore the default ring buffer so later tests see a sane state.
        telemetry.set_history_capacity(max(1, saved_capacity or 1000))
        for ev in saved_history:
            telemetry._history.append(ev)

    total_ns = t1 - t0
    return {
        "emits": int(emits),
        "total_ns": float(total_ns),
        "ns_per_emit": float(total_ns) / float(emits),
    }


def bench_with_subscribers(
    emits: int = BENCH_EMITS,
    extra_zone_subs: int = BENCH_EXTRA_ZONE_SUBS,
) -> Dict[str, float]:
    """Measure ns/emit with the 3 demo subs + ``extra_zone_subs`` zone subs.

    The extra subscribers all match ``zone.*`` but the benchmarked emit
    is ``physics.step``, so the test exercises the per-emit dispatch
    loop's pattern-filter cost (every callback is *checked*, not fired).
    """
    subs = build_subscribers()

    extras: List[int] = []
    sink: List[int] = [0]  # accumulator that escapes optimisation

    def _zone_sink(event: telemetry.TelemetryEvent) -> None:
        sink[0] += 1

    for i in range(extra_zone_subs):
        # Vary the pattern slightly so the bucket index (if enabled) does
        # not degenerate to a single entry, but every pattern still fails
        # to match the benchmarked ``physics.step`` event.
        extras.append(telemetry.subscribe(f"zone.sub_{i}", _zone_sink))

    try:
        # Clear the deque so capacity ticks during benchmark don't extend
        # the lock-held region time.
        telemetry.clear_history()
        t0 = time.perf_counter_ns()
        for _ in range(emits):
            telemetry.emit("physics.step", frame=0, dt=DEFAULT_DT)
        t1 = time.perf_counter_ns()
    finally:
        for h in extras:
            telemetry.unsubscribe(h)
        subs.detach()
        telemetry.clear_history()

    total_ns = t1 - t0
    return {
        "emits": int(emits),
        "subscriber_count": int(3 + extra_zone_subs),
        "total_ns": float(total_ns),
        "ns_per_emit": float(total_ns) / float(emits),
    }


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _render_histogram(trace: Dict[str, Any]) -> np.ndarray:
    """Render an events-per-frame bar chart to an (H, W, 4) uint8 buffer.

    The output is deterministic given the same trace, so the visual
    baseline can pin the exact pixel layout.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), RENDER_BG)
    draw = ImageDraw.Draw(img, "RGBA")

    events = list(trace["events_per_frame"])
    n = len(events)
    if n == 0:
        return np.asarray(img, dtype=np.uint8)

    peak = max(events)
    if peak <= 0:
        peak = 1

    # Layout: 80px left margin, 60px right, 60px top, 120px bottom.
    margin_l, margin_r = 80, 60
    margin_t, margin_b = 60, 120
    plot_w = RENDER_W - margin_l - margin_r
    plot_h = RENDER_H - margin_t - margin_b
    x0 = margin_l
    y0 = margin_t
    x1 = x0 + plot_w
    y1 = y0 + plot_h

    # Axes.
    draw.rectangle([(x0 - 1, y0), (x0, y1)], fill=RENDER_AXIS)
    draw.rectangle([(x0, y1), (x1, y1 + 1)], fill=RENDER_AXIS)

    # Y-axis ticks at 0, peak/2, peak.
    for frac in (0.0, 0.5, 1.0):
        ty = int(round(y1 - frac * plot_h))
        draw.line([(x0 - 5, ty), (x0, ty)], fill=RENDER_AXIS, width=1)

    # Bars.
    if n > 0:
        # Integer bar width to keep the rasterisation deterministic.
        bar_w = max(1, plot_w // n)
        gap = max(0, (plot_w - bar_w * n) // 2)
        for i, count in enumerate(events):
            # Highlight frames that fired more than the baseline 2 events
            # (zone.enter or thermal.phase_change frames).
            color = HIGHLIGHT_COLOR if count > 2 else BAR_COLOR
            bar_h = int(round((count / peak) * plot_h))
            bx0 = x0 + gap + i * bar_w
            bx1 = bx0 + max(1, bar_w - 1)  # 1px gap between bars
            by0 = y1 - bar_h
            by1 = y1
            draw.rectangle([(bx0, by0), (bx1, by1)], fill=color)

    # Title bar (just a coloured strip; no text because PIL font loading
    # is not always available on CI workers).
    draw.rectangle(
        [(margin_l, 20), (margin_l + 220, 32)], fill=RENDER_FG
    )
    # Legend swatches: blue for "regular frame", orange for "special".
    draw.rectangle(
        [(RENDER_W - margin_r - 220, 20), (RENDER_W - margin_r - 200, 32)],
        fill=BAR_COLOR,
    )
    draw.rectangle(
        [(RENDER_W - margin_r - 180, 20), (RENDER_W - margin_r - 160, 32)],
        fill=HIGHLIGHT_COLOR,
    )

    # Footer strip — peak indicator.
    draw.rectangle(
        [(margin_l, RENDER_H - 60), (margin_l + 4, RENDER_H - 40)],
        fill=RENDER_FG,
    )

    return np.asarray(img, dtype=np.uint8)


def save_render(trace: Dict[str, Any], out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_histogram(trace)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(
    subs: Subscribers,
    trace: Dict[str, Any],
    history_zone: List[telemetry.TelemetryEvent],
    history_physics: List[telemetry.TelemetryEvent],
    history_all: List[telemetry.TelemetryEvent],
    bench_idle: Dict[str, float],
    bench_busy: Dict[str, float],
) -> Dict[str, Any]:
    expected_events = (
        trace["frames"]                                  # physics.step
        + len(trace["zone_enter_frames"])                # zone.enter
        + trace["frames"]                                # render.frame
        + (1 if trace["thermal_frame"] >= 0 else 0)      # thermal.phase_change
    )
    return {
        "frames": int(trace["frames"]),
        "physics_count": int(subs.physics_count),
        "zone_event_count": int(len(subs.zone_events)),
        "wildcard_count": int(subs.wildcard_count),
        "expected_events": int(expected_events),
        "history_zone_len": int(len(history_zone)),
        "history_physics_len": int(len(history_physics)),
        "history_all_len": int(len(history_all)),
        "bench_idle_ns_per_emit": float(bench_idle["ns_per_emit"]),
        "bench_busy_ns_per_emit": float(bench_busy["ns_per_emit"]),
        "bench_idle_total_ns": float(bench_idle["total_ns"]),
        "bench_busy_total_ns": float(bench_busy["total_ns"]),
        "bench_idle_emits": int(bench_idle["emits"]),
        "bench_busy_emits": int(bench_busy["emits"]),
        "bench_busy_subscriber_count": int(bench_busy["subscriber_count"]),
    }


def print_summary(summary: Dict[str, Any]) -> None:
    print("hello_telemetry summary")
    print(f"  frames stepped              : {summary['frames']}")
    print(f"  physics_logger calls        : {summary['physics_count']}")
    print(f"  zone_watcher records        : {summary['zone_event_count']}")
    print(f"  wildcard calls (all events) : {summary['wildcard_count']}")
    print(f"  expected total events       : {summary['expected_events']}")
    print(f"  history(zone.*)  length     : {summary['history_zone_len']}")
    print(f"  history(physics.*) length   : {summary['history_physics_len']}")
    print(f"  history(*) length           : {summary['history_all_len']}")
    print("  benchmarks")
    print(
        f"    no-subscriber emit        : "
        f"{summary['bench_idle_ns_per_emit']:8.2f} ns/emit "
        f"({summary['bench_idle_emits']:,} emits, "
        f"{summary['bench_idle_total_ns']/1e6:.2f} ms total)"
    )
    print(
        f"    with {summary['bench_busy_subscriber_count']:>3d} subscribers : "
        f"{summary['bench_busy_ns_per_emit']:8.2f} ns/emit "
        f"({summary['bench_busy_emits']:,} emits, "
        f"{summary['bench_busy_total_ns']/1e6:.2f} ms total)"
    )


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hello Telemetry — Pharos Engine demo"
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of timeline frames (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the events-per-frame histogram to a PNG (pure PIL)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_telemetry.png"),
        help="output PNG path when --render is supplied",
    )
    parser.add_argument(
        "--bench-emits", type=int, default=BENCH_EMITS,
        help=f"emits per benchmark arm (default: {BENCH_EMITS:,})",
    )
    return parser.parse_args(argv)


def _reset_telemetry_state() -> None:
    """Drop any subscribers/history lingering from a previous demo run.

    Tests may invoke ``main()`` multiple times in the same process; the
    telemetry module is global state so we hard-reset before each run.
    """
    # Snapshot the handles defensively — the dict mutates as we iterate.
    handles = list(telemetry._subscribers.keys())
    for h in handles:
        telemetry.unsubscribe(h)
    telemetry.clear_history()
    telemetry.set_history_capacity(1000)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_telemetry.png"),
    bench_emits: int = BENCH_EMITS,
) -> Dict[str, Any]:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    _reset_telemetry_state()

    subs = build_subscribers()

    trace = run_timeline(frames=frames, dt=DEFAULT_DT)

    history_zone = telemetry.get_event_history(name_pattern="zone.*")
    history_physics = telemetry.get_event_history(name_pattern="physics.*")
    history_all = telemetry.get_event_history(name_pattern="*")

    assert len(history_zone) == len(trace["zone_enter_frames"]), (
        f"history(zone.*) returned {len(history_zone)} events, "
        f"expected {len(trace['zone_enter_frames'])}"
    )

    # Detach the demo subscribers before benchmarking so bench arm 1 sees
    # the true zero-subscriber fast path.
    subs.detach()

    bench_idle = bench_no_subscribers(emits=bench_emits)
    bench_busy = bench_with_subscribers(emits=bench_emits)

    summary = summarise(
        subs, trace,
        history_zone, history_physics, history_all,
        bench_idle, bench_busy,
    )
    print_summary(summary)

    if render:
        out_path = save_render(trace, Path(out))
        print(f"  rendered to                 : {out_path}")

    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(
            frames=args.frames,
            render=args.render,
            out=args.out,
            bench_emits=args.bench_emits,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_telemetry: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
