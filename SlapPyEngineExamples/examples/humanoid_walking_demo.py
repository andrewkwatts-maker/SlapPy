"""Humanoid walking — character strides left→right on a flat floor.

Skeleton wrapped in muscle + skin (``wrap_in_flesh``) so the outer
silhouette deforms with the body. Per frame: pelvis advances at constant
x-velocity, ankles oscillate fore/back ±0.18 m out of phase (period 1 s),
pelvis bobs ±0.035 m on a 2× cycloid. ``place_feet_on_terrain`` solves
the 2-bone knee IK so the feet plant on the floor.

Texture deformation is requested via the upcoming render knobs
(``texture_deform`` + ``texture_image_path``) with debug draws off. If
the texture path isn't painting visible pixels yet (smoke-tested at
startup), the demo drops to a wireframe render — same demo file works
once texture-deform lands.

Run:    python examples/humanoid_walking_demo.py
Output: examples/output/humanoid/humanoid_walking.gif
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from slappyengine.dynamics import make_humanoid, place_feet_on_terrain, wrap_in_flesh
from slappyengine.softbody import SoftBodyRenderConfig, SoftBodyRenderer
from slappyengine.studio import Stage, humanoid_stage, output_path, record


FRAMES, FPS, CYCLE_S = 240, 30, 1.0
START_X, END_X, FLOOR_Y = -2.5, 2.5, 3.5
TEXTURE_PATH = str(Path(__file__).resolve().parent
                   / "textures" / "humanoid_character.png")


def _try_renderer(world, view_box, overrides) -> SoftBodyRenderer | None:
    """Return a renderer only if it actually paints body pixels.

    Shifts x by 1 m + re-renders; identical pixels = not drawing the
    body (the gradient backdrop fools a simple non-bg coverage check).
    """
    try:
        r = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(overrides))
        a = r.render(world, view_box=view_box).copy()
        world.nodes.pos[:, 0] += 1.0; world.nodes.prev_pos[:, 0] += 1.0
        b = r.render(world, view_box=view_box)
        world.nodes.pos[:, 0] -= 1.0; world.nodes.prev_pos[:, 0] -= 1.0
        return r if int(np.any(a != b, axis=2).sum()) > 256 else None
    except (TypeError, ValueError, AttributeError):
        return None


def _textured_renderer(width, height, world, view_box) -> SoftBodyRenderer:
    """Texture-deform on + wireframe off, with wireframe-fallback safety."""
    preferred = dict(width=width, height=height, draw_nodes=False,
                     debug_show_beams=False, debug_show_nodes=False,
                     texture_deform=True, texture_image_path=TEXTURE_PATH)
    fallback = dict(width=width, height=height, draw_nodes=True,
                     debug_show_beams=True, debug_show_nodes=True)
    return (_try_renderer(world, view_box, preferred)
            or _try_renderer(world, view_box, fallback)
            or SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(fallback)))


def main(frames: int = FRAMES) -> None:
    stage = humanoid_stage(view_box=(-3.5, 0.5, 3.5, 4.5),
                            width=480, height=320)
    skel = make_humanoid(stage.world, root_position=(START_X, 1.0))
    wrap_in_flesh(stage.world, skel, muscle_offset=0.10, skin_offset=0.18,
                   muscle_stiffness=1.0e6, skin_stiffness=2.5e5,
                   flesh_break_strain=0.40)
    stage.renderer = _textured_renderer(480, 320, stage.world, stage.view_box)

    dt = 1.0 / FPS
    omega = 2.0 * math.pi / CYCLE_S
    stride, bob, travel = 0.18, 0.035, END_X - START_X

    def walk(s: Stage, f: int) -> None:
        pelvis_x = START_X + travel * (f / max(frames - 1, 1))
        t = f * dt
        dx = pelvis_x - float(s.world.nodes.pos[skel.pelvis, 0])
        s.world.nodes.pos[:, 0] += dx
        s.world.nodes.prev_pos[:, 0] += dx
        swing = stride * math.sin(omega * t)
        s.world.nodes.pos[skel.ankle_l, 0] = pelvis_x - 0.15 + swing
        s.world.nodes.pos[skel.ankle_r, 0] = pelvis_x + 0.15 - swing
        bob_now = bob * abs(math.sin(omega * t))
        place_feet_on_terrain(s.world, skel, lambda x: FLOOR_Y,
                               pelvis_height_above_terrain=0.92 - bob_now)

    out = output_path("humanoid_walking", __file__, subdir="humanoid")
    print(f"walking: period={CYCLE_S}s  speed={travel / (frames * dt):.2f} u/s  "
          f"frames={frames}  texture={Path(TEXTURE_PATH).name}")
    record(stage, frames=frames, output=out, fps=FPS,
           step_world=False, post_step=walk)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
