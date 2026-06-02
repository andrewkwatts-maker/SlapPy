"""SlapPyEngine — Hello Zone

Minimal demo of :mod:`slappyengine.zones` showing three trigger zones
tracking three moving entities plus a threshold zone that fires on a
ramping scalar measurement.

The arena is a 10x10 world rectangle. Three named zones are wired into
a :class:`ZoneManager`:

* **safe_zone**  — RectZone at (1, 1, 3, 3), enter/exit callbacks print.
* **danger_zone** — RectZone at (6, 1, 3, 3), enter/exit callbacks print.
* **trigger_zone** — ThresholdZone at (3, 5, 4, 3) with ``threshold=2.5``;
  ``on_threshold`` callback prints on each downward crossing.

Three entities (``ent_a``, ``ent_b``, ``ent_c``) trace simple sinusoidal
paths that intentionally cross multiple zones over the 240-frame run.

Each frame at ``dt = 1/30``:

1. Recompute entity positions from a closed-form sinusoid.
2. Call :meth:`ZoneManager.update` with the new positions.
3. Ramp ``value`` from 0 to 5 linearly across the run and feed it through
   :meth:`ZoneManager.update_threshold("trigger_zone", value)`.

The summary on stdout reports the total enter/exit count per zone and
the threshold fire count.

Run::

    PYTHONPATH=python python examples/hello_zone.py
    PYTHONPATH=python python examples/hello_zone.py --render
    PYTHONPATH=python python examples/hello_zone.py --frames 60

No GPU is required — when ``--render`` is supplied the arena is rasterised
to a 256x256 PNG with pure PIL.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

from slappyengine.zones import RectZone, ThresholdZone, ZoneManager


# ── Demo parameters ────────────────────────────────────────────────────────
ARENA_MIN: tuple[float, float] = (0.0, 0.0)
ARENA_MAX: tuple[float, float] = (10.0, 10.0)

# Zone rects: (x, y, w, h).
SAFE_RECT: tuple[float, float, float, float] = (1.0, 1.0, 3.0, 3.0)
DANGER_RECT: tuple[float, float, float, float] = (6.0, 1.0, 3.0, 3.0)
TRIGGER_RECT: tuple[float, float, float, float] = (3.0, 5.0, 4.0, 3.0)
TRIGGER_THRESHOLD: float = 2.5

# Entity name list — keep in sync with _entity_positions below.
ENTITY_NAMES: tuple[str, ...] = ("ent_a", "ent_b", "ent_c")

DEFAULT_DT: float = 1.0 / 30.0
DEFAULT_FRAMES: int = 240
TRAIL_LENGTH: int = 30

# Ramp the threshold zone's measurement from VALUE_START down through the
# threshold over the run so it fires at least once. The signal goes
# 0 -> 5 (rising) but we pass it inverted (5 -> 0) to trigger a downward
# crossing. To honor the spec ("value slowly ramps from 0 to 5") we feed
# the literal ramp into update_threshold; the zone fires immediately on
# frame 0 (when value=0 <= threshold=2.5) and only re-arms once value
# rises above threshold+hysteresis.
VALUE_RAMP_LO: float = 0.0
VALUE_RAMP_HI: float = 5.0

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 256
RENDER_H: int = 256

# Zone palette.
COLOR_SAFE: tuple[int, int, int] = (96, 220, 96)     # green
COLOR_DANGER: tuple[int, int, int] = (220, 96, 96)   # red
COLOR_TRIGGER: tuple[int, int, int] = (235, 220, 96)  # yellow

# Entity dot colors.
ENTITY_COLORS: dict[str, tuple[int, int, int]] = {
    "ent_a": (255, 255, 255),
    "ent_b": (160, 200, 255),
    "ent_c": (255, 200, 160),
}


# ────────────────────────────────────────────────────────────────────────────
# Zone wiring
# ────────────────────────────────────────────────────────────────────────────

def build_manager() -> tuple[ZoneManager, dict]:
    """Construct the :class:`ZoneManager` with three named zones.

    Returns the manager and a ``records`` dict where the demo accumulates
    every enter/exit/threshold event fired across the run. The records
    dict lets callers (including tests) inspect what happened without
    having to monkey-patch print.
    """
    records: dict = {
        "enter": {"safe_zone": [], "danger_zone": [], "trigger_zone": []},
        "exit": {"safe_zone": [], "danger_zone": [], "trigger_zone": []},
        "threshold": [],
    }

    def _make_enter(name: str):
        def _cb(eid):
            records["enter"][name].append(eid)
            print(f"  [enter] {name} <- {eid}")
        return _cb

    def _make_exit(name: str):
        def _cb(eid):
            records["exit"][name].append(eid)
            print(f"  [exit]  {name} -> {eid}")
        return _cb

    def _on_threshold(value: float) -> None:
        records["threshold"].append(float(value))
        print(f"  [threshold] trigger_zone fired @ value={value:.4f}")

    manager = ZoneManager()
    manager.add(RectZone(
        name="safe_zone",
        x=SAFE_RECT[0], y=SAFE_RECT[1],
        w=SAFE_RECT[2], h=SAFE_RECT[3],
        material="safe",
        on_enter=_make_enter("safe_zone"),
        on_exit=_make_exit("safe_zone"),
    ))
    manager.add(RectZone(
        name="danger_zone",
        x=DANGER_RECT[0], y=DANGER_RECT[1],
        w=DANGER_RECT[2], h=DANGER_RECT[3],
        material="danger",
        on_enter=_make_enter("danger_zone"),
        on_exit=_make_exit("danger_zone"),
    ))
    manager.add(ThresholdZone(
        name="trigger_zone",
        x=TRIGGER_RECT[0], y=TRIGGER_RECT[1],
        w=TRIGGER_RECT[2], h=TRIGGER_RECT[3],
        threshold=TRIGGER_THRESHOLD,
        hysteresis=0.25,
        material="trigger",
        on_enter=_make_enter("trigger_zone"),
        on_exit=_make_exit("trigger_zone"),
        on_threshold=_on_threshold,
    ))
    return manager, records


# ────────────────────────────────────────────────────────────────────────────
# Entity paths
# ────────────────────────────────────────────────────────────────────────────

def _entity_positions(t: float) -> dict[str, tuple[float, float]]:
    """Closed-form sinusoidal paths for the three entities at time *t*.

    * ent_a sweeps left-right across the bottom of the arena, dipping
      between safe_zone and danger_zone.
    * ent_b oscillates diagonally, hitting trigger_zone and both base
      zones over a full cycle.
    * ent_c traces a slow figure-eight through the centre.
    """
    # ent_a: horizontal sweep at low y, oscillating x in [1, 9] and y in [1.5, 3.5].
    # Hits danger_zone (6..9, 1..4) on the right swing and safe_zone (1..4, 1..4)
    # on the left swing.
    ax = 5.0 + 4.0 * math.sin(1.4 * t)
    ay = 2.5 + 1.0 * math.sin(1.1 * t)

    # ent_b: oscillates between safe_zone and trigger_zone.
    # Starts inside safe_zone at t=0 so its first enter event lands fast.
    bx = 2.5 + 2.0 * math.sin(0.9 * t)
    by = 2.5 + 3.0 * math.sin(0.8 * t)

    # ent_c: figure-eight near the centre, sweeps through trigger_zone.
    cx = 5.0 + 3.0 * math.sin(0.5 * t)
    cy = 5.0 + 2.5 * math.sin(1.0 * t)

    return {
        "ent_a": (float(ax), float(ay)),
        "ent_b": (float(bx), float(by)),
        "ent_c": (float(cx), float(cy)),
    }


def _ramp_value(frame: int, total_frames: int) -> float:
    """Return the threshold measurement for *frame* on a linear ramp.

    Maps frame 0 -> :data:`VALUE_RAMP_LO`, frame ``total_frames - 1`` ->
    :data:`VALUE_RAMP_HI`. For ``total_frames <= 1`` returns ``VALUE_RAMP_LO``.
    """
    if total_frames <= 1:
        return VALUE_RAMP_LO
    u = float(frame) / float(total_frames - 1)
    return float(VALUE_RAMP_LO + (VALUE_RAMP_HI - VALUE_RAMP_LO) * u)


# ────────────────────────────────────────────────────────────────────────────
# Stepping
# ────────────────────────────────────────────────────────────────────────────

def step_demo(
    manager: ZoneManager,
    frames: int,
    dt: float = DEFAULT_DT,
) -> dict:
    """Advance the demo by *frames* steps. Returns trace data for renderer/tests."""
    trails: dict[str, deque] = {
        name: deque(maxlen=TRAIL_LENGTH) for name in ENTITY_NAMES
    }
    positions_history: list[dict[str, tuple[float, float]]] = []
    value_history: list[float] = []
    nan_seen = False

    # Seed t=0 occupancy with frame 0 update so the initial entries are
    # recorded as enter events.
    for frame in range(frames):
        t = frame * dt
        positions = _entity_positions(t)

        if not all(
            np.isfinite(p[0]) and np.isfinite(p[1])
            for p in positions.values()
        ):
            nan_seen = True

        manager.update(positions)

        value = _ramp_value(frame, frames)
        manager.update_threshold("trigger_zone", value)

        for name, p in positions.items():
            trails[name].append(p)
        positions_history.append(positions)
        value_history.append(value)

    return {
        "trails": {name: list(buf) for name, buf in trails.items()},
        "positions_history": positions_history,
        "value_history": value_history,
        "final_positions": positions_history[-1] if positions_history else {},
        "nan_seen": nan_seen,
    }


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer (no GPU dependency)
# ────────────────────────────────────────────────────────────────────────────

def _world_to_pixel(p) -> tuple[int, int]:
    vx0, vy0 = ARENA_MIN
    vx1, vy1 = ARENA_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    # Image space y grows downward; world y grows upward.
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _rect_to_pixels(rect: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Return ``(left, top, right, bottom)`` in image pixels for a world rect.

    Image y is inverted vs world y, so the rect's world bottom corresponds
    to the image's bottom edge, which lives at the larger image y.
    """
    x, y, w, h = rect
    left_px, bottom_px = _world_to_pixel((x, y))
    right_px, top_px = _world_to_pixel((x + w, y + h))
    # Normalise to (left, top, right, bottom).
    return (
        min(left_px, right_px),
        min(top_px, bottom_px),
        max(left_px, right_px),
        max(top_px, bottom_px),
    )


def _render_frame(trace: dict, manager: ZoneManager) -> np.ndarray:
    """Rasterise the arena: zones as outlined rects, entities as dots+labels.

    Faded trails show the last :data:`TRAIL_LENGTH` frames per entity.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (16, 16, 24, 255))
    draw = ImageDraw.Draw(img)

    # Zone rectangles (outlined).
    safe = manager.get("safe_zone")
    danger = manager.get("danger_zone")
    trigger = manager.get("trigger_zone")
    if safe is not None:
        rect = _rect_to_pixels(safe.rect)
        draw.rectangle(rect, outline=COLOR_SAFE + (255,), width=2)
    if danger is not None:
        rect = _rect_to_pixels(danger.rect)
        draw.rectangle(rect, outline=COLOR_DANGER + (255,), width=2)
    if trigger is not None:
        rect = _rect_to_pixels(trigger.rect)
        draw.rectangle(rect, outline=COLOR_TRIGGER + (255,), width=2)

    # Trails: oldest dim, newest bright.
    trails = trace.get("trails", {})
    for name, points in trails.items():
        color = ENTITY_COLORS.get(name, (255, 255, 255))
        n = len(points)
        for i in range(1, n):
            t = i / max(1, n - 1)
            alpha = int(round(32 + t * (160 - 32)))
            p0 = _world_to_pixel(points[i - 1])
            p1 = _world_to_pixel(points[i])
            draw.line([p0, p1], fill=color + (alpha,), width=1)

    # Final entity dots + name labels.
    final = trace.get("final_positions", {})
    dot_r = 3
    for name, p in final.items():
        color = ENTITY_COLORS.get(name, (255, 255, 255))
        x_px, y_px = _world_to_pixel(p)
        draw.ellipse(
            [(x_px - dot_r, y_px - dot_r), (x_px + dot_r, y_px + dot_r)],
            fill=color + (255,),
            outline=(0, 0, 0, 255),
        )
        # Label to the right of the dot. Use the default PIL font so we
        # don't depend on a TTF being installed.
        draw.text(
            (x_px + dot_r + 2, y_px - dot_r - 1),
            name,
            fill=color + (255,),
        )

    return np.asarray(img, dtype=np.uint8)


def save_render(trace: dict, manager: ZoneManager, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(trace, manager)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────

def summarise(
    manager: ZoneManager,
    records: dict,
    trace: dict,
    frames: int,
) -> dict:
    enter_counts = {
        name: len(records["enter"][name])
        for name in ("safe_zone", "danger_zone", "trigger_zone")
    }
    exit_counts = {
        name: len(records["exit"][name])
        for name in ("safe_zone", "danger_zone", "trigger_zone")
    }
    occupancy = {
        name: len(manager.occupancy(name))
        for name in ("safe_zone", "danger_zone", "trigger_zone")
    }
    return {
        "frames": frames,
        "enter_counts": enter_counts,
        "exit_counts": exit_counts,
        "occupancy_counts": occupancy,
        "threshold_fire_count": len(records["threshold"]),
        "threshold_fire_values": list(records["threshold"]),
        "final_value": (
            trace["value_history"][-1] if trace["value_history"] else 0.0
        ),
        "nan_seen": bool(trace["nan_seen"]),
    }


def print_summary(summary: dict) -> None:
    print("hello_zone summary")
    print(f"  stepped frames          : {summary['frames']}")
    print("  enter events per zone   :")
    for name, n in summary["enter_counts"].items():
        print(f"    {name:<12s} : {n}")
    print("  exit events per zone    :")
    for name, n in summary["exit_counts"].items():
        print(f"    {name:<12s} : {n}")
    print("  occupancy at end        :")
    for name, n in summary["occupancy_counts"].items():
        print(f"    {name:<12s} : {n}")
    print(f"  threshold fire count    : {summary['threshold_fire_count']}")
    print(f"  final threshold value   : {summary['final_value']:.4f}")
    print(f"  any NaN in positions    : {summary['nan_seen']}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Zone — SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/30 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_zone.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_zone.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    manager, records = build_manager()
    trace = step_demo(manager, frames, DEFAULT_DT)
    summary = summarise(manager, records, trace, frames)
    print_summary(summary)

    if render:
        out_path = save_render(trace, manager, Path(out))
        print(f"  rendered to             : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_zone: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
