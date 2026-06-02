"""IK skeleton — a 4-bone chain reaching for a moving target.

The chain root is fixed at the origin; the tail is dragged by an
IK target that orbits in a circle. Each frame, ``solve_ik`` adjusts
joint angles so the tail tracks the target. The XPBD distance
constraints in the underlying ``SoftBodyWorld`` re-enforce segment
lengths between frames so the pose looks like a real articulated
limb, not a floppy rope.

Run:
    python examples/ik_skeleton_demo.py [--frames N]

Output:
    examples/output/character/ik_skeleton.gif
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine.dynamics import IKChainSpec, make_distance, resolve_joint_specs, solve_ik
from slappyengine.media import save_frames
from slappyengine.softbody import (
    SoftBodyRenderConfig,
    SoftBodyRenderer,
    SoftBodyWorld,
    step as softbody_step,
)


def _build_chain(world: SoftBodyWorld, n_bones: int = 4, seg_len: float = 0.50,
                 origin: tuple[float, float] = (0.0, 2.5)) -> list[int]:
    n_nodes = n_bones + 1
    pos = np.stack([
        np.full(n_nodes, origin[0], dtype=np.float32),
        np.array([origin[1] + i * seg_len for i in range(n_nodes)], dtype=np.float32),
    ], axis=1)
    mass = np.full(n_nodes, 1.0, dtype=np.float32)
    fixed = np.zeros(n_nodes, dtype=bool)
    fixed[0] = True
    damping = np.full(n_nodes, 0.10, dtype=np.float32)
    start = world.nodes.count
    world.nodes.append(pos=pos, mass=mass, body_id=0, layer=2,
                       damping=damping, fixed=fixed)
    chain = [start + i for i in range(n_nodes)]
    # Rigid distance joints between adjacent chain nodes
    specs = [make_distance(chain[i], chain[i + 1], rest_length=seg_len,
                            stiffness=1.0e10, damping=0.05)
             for i in range(n_bones)]
    # resolve_joint_specs auto-routes distance specs into the softbody beam
    # SoA so ``softbody_step`` enforces the segment lengths each frame.
    resolve_joint_specs(world, specs)
    return chain


def main(out_path: Path | None = None, frames: int = 240) -> Path:
    out_path = out_path or Path(__file__).parent / "output" / "character" / "ik_skeleton.gif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    world = SoftBodyWorld()
    world.config["floor_y"] = 5.0
    world.config["gravity"] = [0.0, 0.0]
    world.config["contact"]["enabled"] = False
    chain = _build_chain(world, n_bones=4, seg_len=0.50, origin=(0.0, 2.5))

    renderer = SoftBodyRenderer(
        config=SoftBodyRenderConfig.from_yaml({"width": 360, "height": 270})
    )
    view_box = (-2.5, 0.5, 2.5, 4.5)

    # IK target orbits in a circle around the root.
    root = np.asarray([0.0, 2.5], dtype=np.float32)
    orbit_radius = 1.6   # inside the 4-bone reach of 2.0
    pil_frames: list[Image.Image] = []
    n_unreachable = 0

    for f in range(frames):
        theta = (f / 60.0) * 2.0 * np.pi   # 60 frames per revolution
        target = (root[0] + orbit_radius * float(np.cos(theta)),
                  root[1] + orbit_radius * float(np.sin(theta)))
        # Run a few CCD iters per frame so the chain tracks smoothly.
        spec = IKChainSpec(node_indices=chain, target=target)
        solve_ik(spec, world, iterations=8, tolerance=1e-3)
        # XPBD step keeps the segment lengths rigid between IK solves.
        softbody_step(world)
        # Diagnostic
        tail = world.nodes.pos[chain[-1]]
        dist = float(np.linalg.norm(tail - np.asarray(target)))
        if dist > 0.05:
            n_unreachable += 1
        arr = renderer.render(world, view_box=view_box)
        pil_frames.append(Image.fromarray(arr, mode="RGBA").convert("RGB"))

    save_frames(pil_frames, out_path, fps=30)
    print(f"wrote {out_path}")
    print(f"frames where IK tail >0.05m from target: {n_unreachable}/{frames}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=240,
                        help="number of frames to render (default: 240)")
    args = parser.parse_args()
    main(frames=args.frames)
