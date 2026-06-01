"""SlapPyEngine - Hello Studio

End-to-end demo of the unified :mod:`slappyengine.studio` API on top of the
dynamics substrate. A 24-node rope is hung between two pinned anchors and
recorded to ``examples/output/studio/hello_studio.gif`` with a single
``stage.record(...)`` call.

Run::

    PYTHONPATH=python python examples/hello_studio.py
"""
from __future__ import annotations

from pathlib import Path

from slappyengine import studio
from slappyengine.dynamics import RopeSpec, build_rope


SPAN: float = 4.0
ANCHOR_Y: float = 2.0
NODE_COUNT: int = 24
TOTAL_LENGTH: float = 6.0
FRAMES: int = 120


def main(out: Path | str | None = None) -> Path:
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

    if out is None:
        out = Path(__file__).resolve().parent / "output" / "studio" / "hello_studio.gif"
    return stage.record(out, frames=FRAMES, fps=30)


if __name__ == "__main__":
    print(f"hello_studio wrote {main()}")
