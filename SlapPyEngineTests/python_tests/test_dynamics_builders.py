"""Tests for the higher-level dynamics builders: rope, ragdoll, IK."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.dynamics import (
    BoneSpec,
    IKChainSpec,
    RagdollSpec,
    RopeSpec,
    make_ragdoll,
    make_rope,
    solve_ik,
)
from slappyengine.softbody import SoftBodyWorld
from slappyengine.softbody.solver import step as softbody_step


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── Rope ────────────────────────────────────────────────────────────────────


def test_rope_creates_n_plus_one_nodes_and_n_segments():
    w = SoftBodyWorld()
    spec = RopeSpec(start=(0.0, 0.0), end=(2.0, 0.0), segment_count=8)
    n_s, n_e, beams = make_rope(w, spec)
    assert n_e - n_s == 9
    assert len(beams) == 8
    # Each beam is at the expected rest length ~ 0.25
    rest_lengths = w.beams.rest_length[beams]
    assert np.allclose(rest_lengths, 0.25, rtol=1e-5)


def test_rope_anchors_pin_endpoints():
    w = SoftBodyWorld()
    spec = RopeSpec(start=(0.0, 0.0), end=(0.0, 2.0), segment_count=4,
                    fix_start=True, fix_end=True)
    n_s, n_e, _ = make_rope(w, spec)
    assert w.nodes.fixed[n_s] is np.True_ or bool(w.nodes.fixed[n_s])
    assert bool(w.nodes.fixed[n_e - 1])
    # Middle nodes free
    assert not bool(w.nodes.fixed[n_s + 1])


def test_rope_sags_under_gravity():
    """A horizontal rope pinned at both ends should sag downward under
    gravity (catenary droop). Emits a GIF of the sag developing."""
    from python.tests._visual_snapshot import (
        output_dir,
        save_softbody_sequence,
    )
    from slappyengine.softbody import SoftBodyRenderConfig, SoftBodyRenderer

    w = SoftBodyWorld()
    # Softer rope + heavier nodes so the catenary droop is visible. The
    # original (stiffness=1e6, mass=0.1) gave only ~5 cm of sag — math-
    # valid but visually understated. Spring force is proportional to
    # stiffness * strain and gravity to mass*g; lowering the ratio
    # makes the sag dramatic.
    spec = RopeSpec(start=(0.0, 0.0), end=(2.0, 0.0), segment_count=14,
                    fix_start=True, fix_end=True,
                    segment_stiffness=2.0e4, mass_per_node=0.5,
                    segment_damping=0.20, node_damping=0.15)
    n_s, n_e, _ = make_rope(w, spec)
    w.config["gravity"] = [0.0, 9.81]
    w.config["contact"]["enabled"] = False
    w.config["floor_y"] = 100.0

    renderer = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(
        {"width": 320, "height": 200}))
    view_box = (-0.3, -0.3, 2.3, 1.5)
    frames = []
    for _ in range(120):
        softbody_step(w)
        frames.append(renderer.render(w, view_box=view_box))
    save_softbody_sequence(frames, output_dir("dynamics") / "rope_catenary.gif")

    mid_idx = n_s + (n_e - n_s) // 2
    mid_y = float(w.nodes.pos[mid_idx, 1])
    assert mid_y > 0.0, f"rope did not sag: middle y={mid_y:.4f}"
    assert mid_y < 2.0, f"rope fell off the world: y={mid_y}"


def test_rope_with_bend_stiffness_adds_extra_beams():
    w = SoftBodyWorld()
    spec = RopeSpec(start=(0.0, 0.0), end=(2.0, 0.0), segment_count=4,
                    bend_stiffness=1.0e4)
    _, _, beams = make_rope(w, spec)
    # 4 segments + 3 bend diagonals = 7 beams
    assert len(beams) == 7


# ── Ragdoll ─────────────────────────────────────────────────────────────────


def _humanoid_spec() -> RagdollSpec:
    """4-bone stick figure: torso, head, two arms."""
    return RagdollSpec(
        bones=[
            BoneSpec(name="torso", head=(0.0, 0.0), tail=(0.0, 1.0),
                     mass_head=2.0, mass_tail=3.0),
            BoneSpec(name="head", head=(0.0, 0.0), tail=(0.0, -0.4),
                     mass_head=1.0, mass_tail=0.8),
            BoneSpec(name="arm_l", head=(0.0, 0.2), tail=(-0.5, 0.5)),
            BoneSpec(name="arm_r", head=(0.0, 0.2), tail=(0.5, 0.5)),
        ],
        welds=[
            (0, "head", 1, "head"),    # torso top ↔ head base
            (0, "head", 2, "head"),    # torso top ↔ left arm root
            (0, "head", 3, "head"),    # torso top ↔ right arm root
        ],
    )


def test_ragdoll_creates_bones_and_welds():
    w = SoftBodyWorld()
    spec = _humanoid_spec()
    n_s, n_e, beams = make_ragdoll(w, spec)
    # 4 bones × 2 nodes = 8 nodes; 4 bones + 3 welds = 7 beams.
    assert n_e - n_s == 8
    assert len(beams) == 7


def test_ragdoll_anchor_pins_node():
    w = SoftBodyWorld()
    spec = _humanoid_spec()
    spec.anchors = [(0, "head")]   # anchor torso top
    n_s, _, _ = make_ragdoll(w, spec)
    assert bool(w.nodes.fixed[n_s + 0])  # node index 0 of bone 0 = head


def test_ragdoll_drops_without_blowing_up():
    """Standard sanity: ragdoll falls under gravity without joints exploding."""
    from python.tests._visual_snapshot import (
        output_dir,
        save_softbody_sequence,
    )
    from slappyengine.softbody import SoftBodyRenderConfig, SoftBodyRenderer

    w = SoftBodyWorld()
    spec = _humanoid_spec()
    n_s, n_e, beams = make_ragdoll(w, spec)
    w.config["floor_y"] = 5.0

    renderer = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(
        {"width": 320, "height": 240}))
    view_box = (-1.5, -1.0, 1.5, 5.3)
    frames = []
    for _ in range(60):
        softbody_step(w)
        frames.append(renderer.render(w, view_box=view_box))
    save_softbody_sequence(frames, output_dir("dynamics") / "ragdoll_drops.gif")

    assert np.all(np.isfinite(w.nodes.pos))
    n_broken = int(w.beams.broken[beams].sum())
    assert n_broken == 0, f"ragdoll broke {n_broken} beams on a 5m drop"


def test_ragdoll_rejects_empty_bones():
    with pytest.raises(ValueError):
        make_ragdoll(SoftBodyWorld(), RagdollSpec(bones=[]))


def test_ragdoll_rejects_bad_weld_end():
    w = SoftBodyWorld()
    spec = _humanoid_spec()
    spec.welds = [(0, "elbow", 1, "head")]  # invalid end name
    with pytest.raises(ValueError):
        make_ragdoll(w, spec)


# ── IK ──────────────────────────────────────────────────────────────────────


def _three_bone_arm(world: SoftBodyWorld) -> list[int]:
    """A 3-bone planar arm rooted at the origin, segments along +x.

    Returns the chain node indices (4 nodes for 3 bones).
    """
    pos = np.asarray([
        [0.0, 0.0],
        [1.0, 0.0],
        [2.0, 0.0],
        [3.0, 0.0],
    ], dtype=np.float32)
    mass = np.full(4, 1.0, dtype=np.float32)
    fixed = np.asarray([True, False, False, False], dtype=bool)
    damping = np.full(4, 0.05, dtype=np.float32)
    start = world.nodes.count
    world.nodes.append(pos=pos, mass=mass, body_id=0, layer=0,
                       damping=damping, fixed=fixed)
    return [start + i for i in range(4)]


def test_ik_converges_for_reachable_target():
    """Target safely inside the reachable workspace (max reach 3.0).

    CCD converges quickly for interior targets; targets on the workspace
    boundary need many iterations because the rotation angles shrink as
    the chain straightens. That's a CCD limitation, not a bug.

    Emits a GIF of the chain solving across a sweeping target.
    """
    from python.tests._visual_snapshot import output_dir, save_chain_render
    from slappyengine.media import save_frames
    from PIL import Image

    w = SoftBodyWorld()
    chain = _three_bone_arm(w)
    spec = IKChainSpec(chain_nodes=chain, target=(1.0, 2.0), iters=15,
                       tolerance=1.0e-4)
    iters_used = solve_ik(w, spec)
    assert iters_used <= 15
    tail = w.nodes.pos[chain[-1]]
    dist = float(np.linalg.norm(tail - np.asarray(spec.target)))
    assert dist < 0.02, f"IK did not converge: tail distance = {dist:.4f}"

    # Reset chain to initial straight pose, then sweep the target along
    # a small arc and snapshot each pose into a GIF.
    pos = np.asarray([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
                      dtype=np.float32)
    w.nodes.pos[chain] = pos
    frame_paths = []
    out_dir = output_dir("dynamics")
    pil_frames = []
    n_frames = 36
    for f in range(n_frames):
        theta = 0.5 + (f / n_frames) * (1.5)  # sweep from 0.5 to 2.0 rad
        target = (2.5 * float(np.cos(theta)), 2.5 * float(np.sin(theta)))
        spec_f = IKChainSpec(chain_nodes=chain, target=target, iters=8,
                              tolerance=1.0e-3)
        solve_ik(w, spec_f)
        tmp = out_dir / f"_ik_tmp_{f:03d}.png"
        save_chain_render(w.nodes.pos[chain], target, tmp,
                           view_box=(-3.5, -3.5, 3.5, 3.5))
        pil_frames.append(Image.open(tmp))
    save_frames(pil_frames, out_dir / "ik_chain_sweep.gif", fps=18)
    for tmp in out_dir.glob("_ik_tmp_*.png"):
        tmp.unlink()


def test_ik_preserves_segment_lengths():
    w = SoftBodyWorld()
    chain = _three_bone_arm(w)
    spec = IKChainSpec(chain_nodes=chain, target=(2.0, 2.0), iters=12)
    solve_ik(w, spec)
    # Each segment should still be ~1.0 long (the original spacing).
    for i in range(len(chain) - 1):
        a = w.nodes.pos[chain[i]]
        b = w.nodes.pos[chain[i + 1]]
        d = float(np.linalg.norm(b - a))
        assert abs(d - 1.0) < 0.02, (
            f"segment {i} length drifted: {d:.4f} vs expected ~1.0"
        )


def test_ik_unreachable_target_does_not_explode():
    w = SoftBodyWorld()
    chain = _three_bone_arm(w)
    # Total reach is 3.0; target at (10, 0) is unreachable.
    spec = IKChainSpec(chain_nodes=chain, target=(10.0, 0.0), iters=10)
    solve_ik(w, spec)
    assert np.all(np.isfinite(w.nodes.pos))
    # Tail should be near the chain's maximum reach in the +x direction.
    tail_x = float(w.nodes.pos[chain[-1], 0])
    assert tail_x > 2.5, f"unreachable target should stretch arm fully; got x={tail_x}"


def test_ik_rejects_short_chain():
    w = SoftBodyWorld()
    chain = _three_bone_arm(w)
    spec = IKChainSpec(chain_nodes=[chain[0]], target=(1.0, 0.0))
    with pytest.raises(ValueError):
        solve_ik(w, spec)
