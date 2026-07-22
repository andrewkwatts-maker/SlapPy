"""SlapPyEngine -- Hello Joint

Side-by-side demo of four :class:`pharos_engine.dynamics.JointSpec` kinds.

Four mini-scenes are built in a single :class:`~pharos_engine.dynamics.World`
and arranged along the x-axis so that one render shows them all at once:

* **Scene A** (x = 0..2): ``kind="distance"`` -- two nodes, one pinned at the
  top, one dangling below. A distance joint with ``rest_length = 2`` should
  hold the pair rigidly so the bottom node swings like a fixed-length
  pendulum without any visible stretch.
* **Scene B** (x = 3..5): ``kind="weld"`` -- a 3-node rigid bar
  ``A--B--C``. The top node is pinned; the two welds keep the spacing
  identical so the bar behaves as a single rigid object.
* **Scene C** (x = 6..8): ``kind="ball"`` -- two nodes connected by a ball
  joint (rest length forced to 0 by the resolver). The pinned node sits at
  the top, the dangling node starts offset to the side so the relative
  angle at the pivot is high; under gravity it swings freely.
* **Scene D** (x = 9..11): ``kind="hinge"`` -- a hinge with explicit
  ``min_angle`` / ``max_angle`` of ``+-pi/4``. The angle between the
  reference arm and the swinging arm oscillates inside the limit band
  but never exceeds it.

Each scene is stepped with the same ``World.step`` loop at ``dt = 1/60`` for
240 frames under gravity ``g = 9.81`` (downward). After the run the demo
prints per-scene diagnostics: max distance violation, max joint angle (where
applicable), and a no-NaN check.

Run::

    PYTHONPATH=python python examples/hello_joint.py
    PYTHONPATH=python python examples/hello_joint.py --render
    PYTHONPATH=python python examples/hello_joint.py --frames 60

No GPU is required -- when ``--render`` is supplied all four scenes are
rasterised side-by-side into a single PNG using pure PIL.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from pharos_engine.dynamics import JointSpec, World


# -- Demo parameters --------------------------------------------------------
GRAVITY: tuple[float, float] = (0.0, -9.81)
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 240
SOLVER_ITERATIONS: int = 16

# Layout: each scene occupies a 3-unit-wide slot along x.
SCENE_SLOT: float = 3.0
SCENE_TOP_Y: float = 3.0          # y position of every pinned anchor
SCENE_DROP: float = 2.0           # initial distance from anchor to the bottom

# Joint tuning that applies to every scene unless overridden below.
# Solver tuning: keep ``iters * damping <= 0.3`` so the over-damp warning in
# :mod:`pharos_engine.dynamics.world` (threshold 0.5 on effective per-step
# damping) never fires. With ``iters=16`` we pick ``damping=0.018`` giving a
# product of 0.288 and effective per-step damping
# ``1 - (1 - 0.018)^16 ≈ 0.253`` — well under the 0.5 threshold. Mirrors the
# X2 (hello_rope) and W1 (hello_ragdoll) fix pattern.
RIGID_STIFFNESS: float = 1.0e8    # distance / weld -- nearly rigid
RIGID_DAMPING: float = 0.018
BALL_STIFFNESS: float = 1.0e7
BALL_DAMPING: float = 0.018
HINGE_STIFFNESS: float = 1.0e7
HINGE_DAMPING: float = 0.018
HINGE_LIMIT: float = math.pi / 4.0

# Aggregate damping used by tests and the summary print — the maximum of
# the per-kind damping constants so any over-damp regression is visible.
DAMPING: float = max(RIGID_DAMPING, BALL_DAMPING, HINGE_DAMPING)

# Per-scene tunables -- kept here so tests can import them.
SCENE_A_REST_LENGTH: float = SCENE_DROP                         # 2.0
SCENE_B_SEGMENT: float = 1.0                                    # 3 nodes spaced 1 apart
SCENE_C_BALL_OFFSET: float = 1.4                                # horizontal start offset for swinging bob
SCENE_D_ARM_LENGTH: float = 1.5
# Initial bob offset chosen so the angle starts *past* the +pi/4 hinge limit:
# anchor->ref = (0, -1.5), anchor->bob = (1.8, -1.5) gives an angle of
# ``atan2(1.8 * 1.5, 1.5 * 1.5) = atan2(1.2, 1.0) ~= 0.876 rad`` which is
# above ``pi/4 ~ 0.785``. The hinge clamp engages on frame 0 and pulls the
# bob back to the +pi/4 boundary, after which gravity drives an oscillation
# that repeatedly tickles the limit -- the behaviour the test pins.
SCENE_D_BOB_OFFSET: float = 1.8

# Distance-violation tolerance used in stdout summaries.
DISTANCE_TOL: float = 0.02


# -- Render parameters ------------------------------------------------------
RENDER_W: int = 1280
RENDER_H: int = 720
VIEW_MIN: tuple[float, float] = (-1.0, -1.0)
VIEW_MAX: tuple[float, float] = (12.0, 4.0)
LABEL_OFFSET_PX: int = 18


# ---------------------------------------------------------------------------
#  World / joint construction
# ---------------------------------------------------------------------------

def _scene_x(slot_idx: int) -> float:
    """Return the centre-x of the *slot_idx*-th scene (0..3)."""
    return SCENE_SLOT * slot_idx + 1.0


def build_world() -> tuple[World, dict]:
    """Construct the world + all four scenes.

    Returns ``(world, info)`` where ``info`` carries the absolute node
    indices for every scene so the caller can inspect them without having
    to recompute the layout.
    """
    world = World(gravity=GRAVITY)
    world.solver_iterations = SOLVER_ITERATIONS

    info: dict = {}

    # -- Scene A: distance joint ------------------------------------------
    a_anchor = world.add_node((_scene_x(0), SCENE_TOP_Y), mass=0.0)
    a_node = world.add_node(
        (_scene_x(0), SCENE_TOP_Y - SCENE_DROP), mass=1.0,
    )
    world.add_joint(
        JointSpec(
            kind="distance",
            node_a=a_anchor,
            node_b=a_node,
            rest_length=SCENE_A_REST_LENGTH,
            stiffness=RIGID_STIFFNESS,
            damping=RIGID_DAMPING,
        )
    )
    info["scene_a"] = {
        "kind": "distance",
        "anchor": a_anchor,
        "node": a_node,
        "rest_length": SCENE_A_REST_LENGTH,
    }

    # -- Scene B: two welds making a 3-node rigid bar ---------------------
    b_top = world.add_node((_scene_x(1), SCENE_TOP_Y), mass=0.0)
    b_mid = world.add_node(
        (_scene_x(1), SCENE_TOP_Y - SCENE_B_SEGMENT), mass=1.0,
    )
    b_bot = world.add_node(
        (_scene_x(1), SCENE_TOP_Y - 2.0 * SCENE_B_SEGMENT), mass=1.0,
    )
    world.add_joint(
        JointSpec(
            kind="weld",
            node_a=b_top,
            node_b=b_mid,
            rest_length=SCENE_B_SEGMENT,
            stiffness=RIGID_STIFFNESS,
            damping=RIGID_DAMPING,
        )
    )
    world.add_joint(
        JointSpec(
            kind="weld",
            node_a=b_mid,
            node_b=b_bot,
            rest_length=SCENE_B_SEGMENT,
            stiffness=RIGID_STIFFNESS,
            damping=RIGID_DAMPING,
        )
    )
    info["scene_b"] = {
        "kind": "weld",
        "top": b_top,
        "mid": b_mid,
        "bot": b_bot,
        "segment": SCENE_B_SEGMENT,
    }

    # -- Scene C: ball joint (zero rest length) ---------------------------
    # The ball joint forces ``|node_b - node_a| -> 0``. We start the bob
    # offset horizontally so the angle between the pivot and the bob is
    # large at frame 0; the relative angle then evolves as the bob swings
    # in toward the pinned pivot under gravity. This is the classic
    # "free-rotation pivot" demonstration: there is no angular limit, the
    # bob can sweep through any orientation around the pivot.
    c_pivot = world.add_node((_scene_x(2), SCENE_TOP_Y), mass=0.0)
    c_bob = world.add_node(
        (_scene_x(2) + SCENE_C_BALL_OFFSET, SCENE_TOP_Y), mass=1.0,
    )
    world.add_joint(
        JointSpec(
            kind="ball",
            node_a=c_pivot,
            node_b=c_bob,
            rest_length=0.0,                  # ignored by the resolver, documented
            stiffness=BALL_STIFFNESS,
            damping=BALL_DAMPING,
        )
    )
    info["scene_c"] = {
        "kind": "ball",
        "pivot": c_pivot,
        "bob": c_bob,
    }

    # -- Scene D: hinge with angle limit +-pi/4 ---------------------------
    # Layout:
    #   * d_anchor  -- pinned pivot (the hinge "anchor" used by
    #                  ``_resolve_hinge`` for angle clamping).
    #   * d_ref     -- pinned reference end. The angle is measured between
    #                  ``anchor->ref`` and ``anchor->bob``; pinning ref
    #                  freezes the reference direction so the bob has a
    #                  well-defined limit band.
    #   * d_bob     -- the free swinging end. Starts offset to one side so
    #                  gravity drives it into the +pi/4 limit; it
    #                  oscillates inside the [-pi/4, +pi/4] band.
    d_anchor = world.add_node((_scene_x(3), SCENE_TOP_Y), mass=0.0)
    d_ref = world.add_node(
        (_scene_x(3), SCENE_TOP_Y - SCENE_D_ARM_LENGTH), mass=0.0,
    )
    d_bob = world.add_node(
        (_scene_x(3) + SCENE_D_BOB_OFFSET,
         SCENE_TOP_Y - SCENE_D_ARM_LENGTH),
        mass=1.0,
    )
    # The hinge holds d_ref<->d_bob at a fixed segment length so the bob
    # orbits ref; the angle limit then constrains how far the
    # ``anchor->bob`` vector can rotate away from ``anchor->ref``.
    ref_bob_rest = float(
        np.linalg.norm(world.positions[d_bob] - world.positions[d_ref])
    )
    world.add_joint(
        JointSpec(
            kind="hinge",
            node_a=d_ref,
            node_b=d_bob,
            rest_length=ref_bob_rest,
            stiffness=HINGE_STIFFNESS,
            damping=HINGE_DAMPING,
            params={
                "anchor": d_anchor,
                "min_angle": -HINGE_LIMIT,
                "max_angle": +HINGE_LIMIT,
            },
        )
    )
    info["scene_d"] = {
        "kind": "hinge",
        "anchor": d_anchor,
        "ref": d_ref,
        "bob": d_bob,
        "min_angle": -HINGE_LIMIT,
        "max_angle": +HINGE_LIMIT,
    }

    return world, info


# ---------------------------------------------------------------------------
#  Stepping + per-frame diagnostics
# ---------------------------------------------------------------------------

def _distance(world: World, a: int, b: int) -> float:
    return float(np.linalg.norm(world.positions[a] - world.positions[b]))


def _signed_angle_at(world: World, anchor: int, a: int, b: int) -> float:
    """Return signed angle from ``anchor->a`` to ``anchor->b`` in radians."""
    va = world.positions[a] - world.positions[anchor]
    vb = world.positions[b] - world.positions[anchor]
    return float(math.atan2(
        float(va[0]) * float(vb[1]) - float(va[1]) * float(vb[0]),
        float(va[0]) * float(vb[0]) + float(va[1]) * float(vb[1]),
    ))


def step_world(
    world: World,
    info: dict,
    frames: int,
    dt: float = DEFAULT_DT,
) -> dict:
    """Run the world for *frames* steps and record per-frame metrics.

    Returns a dict with one entry per scene containing the time series the
    summary / tests need: distance violations and (where defined) joint
    angles. Also records whether any NaN ever appeared in ``positions``.
    """
    sa = info["scene_a"]
    sb = info["scene_b"]
    sc = info["scene_c"]
    sd = info["scene_d"]

    a_violations: list[float] = []
    b_violations_top: list[float] = []
    b_violations_bot: list[float] = []
    c_distances: list[float] = []
    c_angles: list[float] = []
    d_angles: list[float] = []
    d_distances: list[float] = []
    nan_seen = False

    def record() -> None:
        nonlocal nan_seen
        a_violations.append(
            abs(_distance(world, sa["anchor"], sa["node"]) - sa["rest_length"])
        )
        b_violations_top.append(
            abs(_distance(world, sb["top"], sb["mid"]) - sb["segment"])
        )
        b_violations_bot.append(
            abs(_distance(world, sb["mid"], sb["bot"]) - sb["segment"])
        )
        c_distances.append(_distance(world, sc["pivot"], sc["bob"]))
        # Angle of bob relative to straight-down from pivot; use a tiny
        # virtual reference vector along ``-y`` so we get a well-defined
        # signed angle even when the ball joint pulls the bob onto the
        # pivot.
        pivot_pos = world.positions[sc["pivot"]]
        bob_pos = world.positions[sc["bob"]]
        rel = bob_pos - pivot_pos
        # atan2(x, -y) gives 0 when bob is straight below the pivot and
        # grows with horizontal offset.
        c_angles.append(float(math.atan2(float(rel[0]), -float(rel[1]))))
        d_angles.append(
            _signed_angle_at(world, sd["anchor"], sd["ref"], sd["bob"])
        )
        d_distances.append(_distance(world, sd["ref"], sd["bob"]))
        if not nan_seen and not np.all(np.isfinite(world.positions)):
            nan_seen = True

    # Only post-step frames are recorded; the unsolved initial state may
    # legitimately sit outside angle / distance limits and the user's
    # contract is "the solver respects the constraint" -- which is a claim
    # about what comes *out* of ``World.step``.
    for _ in range(frames):
        world.step(dt)
        record()

    return {
        "a_violations": a_violations,
        "b_violations_top": b_violations_top,
        "b_violations_bot": b_violations_bot,
        "c_distances": c_distances,
        "c_angles": c_angles,
        "d_angles": d_angles,
        "d_distances": d_distances,
        "nan_seen": nan_seen,
    }


# ---------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------

def summarise(world: World, info: dict, trace: dict, frames: int) -> dict:
    """Roll the per-frame trace up into the dict the demo prints."""
    a_viol = np.asarray(trace["a_violations"], dtype=np.float64)
    b_viol = np.maximum(
        np.asarray(trace["b_violations_top"], dtype=np.float64),
        np.asarray(trace["b_violations_bot"], dtype=np.float64),
    )
    c_ang = np.asarray(trace["c_angles"], dtype=np.float64)
    d_ang = np.asarray(trace["d_angles"], dtype=np.float64)
    return {
        "frames": frames,
        "scene_a": {
            "kind": "distance",
            "max_violation": float(np.max(a_viol)),
            "rest_length": info["scene_a"]["rest_length"],
        },
        "scene_b": {
            "kind": "weld",
            "max_violation": float(np.max(b_viol)),
            "segment": info["scene_b"]["segment"],
        },
        "scene_c": {
            "kind": "ball",
            "max_angle": float(np.max(np.abs(c_ang))),
            "final_distance": float(trace["c_distances"][-1]),
        },
        "scene_d": {
            "kind": "hinge",
            "max_angle": float(np.max(np.abs(d_ang))),
            "min_angle": info["scene_d"]["min_angle"],
            "max_angle_limit": info["scene_d"]["max_angle"],
        },
        "nan_seen": bool(trace["nan_seen"]),
        "iters_x_damping": SOLVER_ITERATIONS * DAMPING,
    }


def print_summary(summary: dict) -> None:
    print("hello_joint summary")
    print(f"  frames                : {summary['frames']}")
    a = summary["scene_a"]
    print(
        f"  Scene A (distance)    : max violation = {a['max_violation']:.5f}"
        f"  (rest={a['rest_length']:.3f})"
    )
    b = summary["scene_b"]
    print(
        f"  Scene B (weld)        : max violation = {b['max_violation']:.5f}"
        f"  (segment={b['segment']:.3f})"
    )
    c = summary["scene_c"]
    print(
        f"  Scene C (ball)        : max |angle|   = {c['max_angle']:.5f} rad"
        f"  (final dist={c['final_distance']:.5f})"
    )
    d = summary["scene_d"]
    print(
        f"  Scene D (hinge)       : max |angle|   = {d['max_angle']:.5f} rad"
        f"  (limit=+-{d['max_angle_limit']:.5f})"
    )
    print(f"  any NaN in positions  : {summary['nan_seen']}")
    print(
        f"  iters * damping       : {summary['iters_x_damping']:.3f}"
        f" (<= 0.3 OK)"
    )


# ---------------------------------------------------------------------------
#  Pure-PIL renderer (no GPU dependency)
# ---------------------------------------------------------------------------

def _world_to_pixel(p) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _draw_node(draw, p, radius_px: int, fill, outline=None) -> None:
    cx, cy = _world_to_pixel(p)
    draw.ellipse(
        [(cx - radius_px, cy - radius_px), (cx + radius_px, cy + radius_px)],
        fill=fill,
        outline=outline if outline is not None else fill,
    )


def _draw_label(draw, slot_idx: int, text: str, color) -> None:
    """Place a label centred over the slot at the top of the render area."""
    cx_world = _scene_x(slot_idx)
    px, _ = _world_to_pixel((cx_world, SCENE_TOP_Y))
    # Lift the label above the anchor row by a fixed pixel offset.
    label_y_world = SCENE_TOP_Y + 0.6
    _, py = _world_to_pixel((cx_world, label_y_world))
    # The default PIL font is small but doesn't require any system file --
    # it ships with Pillow so the demo stays self-contained.
    draw.text((px - 60, py), text, fill=color)


def _render_frame(world: World, info: dict) -> np.ndarray:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Thin separators between the four slots so the eye can group them.
    for slot in range(1, 4):
        x_world = SCENE_SLOT * slot
        px_top, py_top = _world_to_pixel((x_world, VIEW_MAX[1]))
        px_bot, py_bot = _world_to_pixel((x_world, VIEW_MIN[1]))
        draw.line(
            [(px_top, py_top), (px_bot, py_bot)],
            fill=(40, 40, 60, 255),
            width=1,
        )

    # -- Scene A: distance --------------------------------------------------
    sa = info["scene_a"]
    pa_anchor = world.positions[sa["anchor"]]
    pa_node = world.positions[sa["node"]]
    draw.line(
        [_world_to_pixel(pa_anchor), _world_to_pixel(pa_node)],
        fill=(255, 220, 120, 255),
        width=3,
    )
    _draw_node(draw, pa_anchor, 6, (255, 255, 255, 255))
    _draw_node(draw, pa_node, 10, (255, 220, 120, 255))
    _draw_label(draw, 0, "distance", (255, 220, 120, 255))

    # -- Scene B: weld bar --------------------------------------------------
    sb = info["scene_b"]
    pb_top = world.positions[sb["top"]]
    pb_mid = world.positions[sb["mid"]]
    pb_bot = world.positions[sb["bot"]]
    draw.line(
        [_world_to_pixel(pb_top), _world_to_pixel(pb_mid)],
        fill=(120, 220, 255, 255),
        width=4,
    )
    draw.line(
        [_world_to_pixel(pb_mid), _world_to_pixel(pb_bot)],
        fill=(120, 220, 255, 255),
        width=4,
    )
    _draw_node(draw, pb_top, 6, (255, 255, 255, 255))
    _draw_node(draw, pb_mid, 8, (120, 220, 255, 255))
    _draw_node(draw, pb_bot, 8, (120, 220, 255, 255))
    _draw_label(draw, 1, "weld", (120, 220, 255, 255))

    # -- Scene C: ball ------------------------------------------------------
    sc = info["scene_c"]
    pc_pivot = world.positions[sc["pivot"]]
    pc_bob = world.positions[sc["bob"]]
    draw.line(
        [_world_to_pixel(pc_pivot), _world_to_pixel(pc_bob)],
        fill=(220, 120, 220, 255),
        width=3,
    )
    _draw_node(draw, pc_pivot, 6, (255, 255, 255, 255))
    _draw_node(draw, pc_bob, 10, (220, 120, 220, 255))
    _draw_label(draw, 2, "ball", (220, 120, 220, 255))

    # -- Scene D: hinge -----------------------------------------------------
    sd = info["scene_d"]
    pd_anchor = world.positions[sd["anchor"]]
    pd_ref = world.positions[sd["ref"]]
    pd_bob = world.positions[sd["bob"]]
    # Reference arm: anchor -> ref (always pinned, straight down).
    draw.line(
        [_world_to_pixel(pd_anchor), _world_to_pixel(pd_ref)],
        fill=(100, 100, 100, 255),
        width=2,
    )
    # Hinge segment: ref -> bob (the constrained pair).
    draw.line(
        [_world_to_pixel(pd_ref), _world_to_pixel(pd_bob)],
        fill=(180, 255, 160, 255),
        width=3,
    )
    # And anchor -> bob just so the reader can see the swept angle.
    draw.line(
        [_world_to_pixel(pd_anchor), _world_to_pixel(pd_bob)],
        fill=(80, 140, 80, 255),
        width=1,
    )
    _draw_node(draw, pd_anchor, 6, (255, 255, 255, 255))
    _draw_node(draw, pd_ref, 5, (160, 160, 160, 255))
    _draw_node(draw, pd_bob, 10, (180, 255, 160, 255))
    _draw_label(draw, 3, "hinge", (180, 255, 160, 255))

    return np.asarray(img, dtype=np.uint8)


def save_render(world: World, info: dict, out_path: Path) -> Path:
    from PIL import Image

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = _render_frame(world, info)
    Image.fromarray(arr, mode="RGBA").save(out_path)
    return out_path


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Joint -- SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="rasterise the final frame to a PNG (pure PIL, no GPU)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("out/hello_joint.png"),
        help="output PNG path when --render is supplied",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    render: bool = False,
    out: Path | str = Path("out/hello_joint.png"),
) -> dict:
    """Run the demo end-to-end. Returns the summary dict for tests."""
    world, info = build_world()
    trace = step_world(world, info, frames, DEFAULT_DT)
    summary = summarise(world, info, trace, frames)
    print_summary(summary)

    if render:
        out_path = save_render(world, info, Path(out))
        print(f"  rendered to           : {out_path}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(frames=args.frames, render=args.render, out=args.out)
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_joint: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
