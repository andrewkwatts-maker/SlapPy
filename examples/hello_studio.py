"""SlapPyEngine - Hello Studio

End-to-end demo of the unified :mod:`slappyengine.studio` API on top of the
dynamics substrate. A 24-node rope is hung between two pinned anchors and
recorded to ``examples/output/studio/hello_studio.gif`` with a single
``stage.record(...)`` call.

Run::

    PYTHONPATH=python python examples/hello_studio.py
    PYTHONPATH=python python examples/hello_studio.py --frames 60 --no-gif
"""
from __future__ import annotations

import sys
from pathlib import Path

from slappyengine import studio
from slappyengine.dynamics import RopeSpec, build_rope
from slappyengine.examples_common import (
    build_demo_arg_parser, record_or_smoke,
)


SPAN: float = 4.0
ANCHOR_Y: float = 2.0
NODE_COUNT: int = 24
TOTAL_LENGTH: float = 6.0
FRAMES: int = 120


def _build_stage() -> studio.Stage:
    stage = studio.dynamics_stage(
        gravity=(0.0, -9.81),
        solver_iterations=16,
        view_box=(-3.0, -3.0, 3.0, 3.0),
        width=480,
        height=320,
        floor_y=-3.0,
    )
    spec = RopeSpec(
        node_count=NODE_COUNT,
        total_length=TOTAL_LENGTH,
        mass_per_node=0.05,
        stiffness=2.0e6,
        damping=0.018,  # 16 iters * 0.018 = 0.288 < 0.3 over-damp threshold
        anchor_a_pinned=True,
        anchor_b_pinned=True,
    )
    build_rope(spec, stage.dynamics,
               anchor_a=(-SPAN / 2.0, ANCHOR_Y),
               anchor_b=(+SPAN / 2.0, ANCHOR_Y))
    return stage


def _default_out() -> Path:
    return Path(__file__).resolve().parent / "output" / "studio" / "hello_studio.gif"


def main(out: Path | str | None = None, frames: int = FRAMES) -> Path:
    """In-process entry point (kept for back-compat with downstream callers)."""
    stage = _build_stage()
    out_path = Path(out) if out is not None else _default_out()
    return stage.record(out_path, frames=frames, fps=30)


def _cli(argv: list[str] | None = None) -> int:
    parser = build_demo_arg_parser(
        "Hello Studio - SlapPyEngine demo",
        default_frames=FRAMES,
    )
    args = parser.parse_args(argv)
    try:
        written = record_or_smoke(_build_stage(), args, default_out=_default_out())
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_studio: error: {exc}", file=sys.stderr)
        return 1
    if written is not None:
        print(f"hello_studio wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
