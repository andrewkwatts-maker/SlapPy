"""JJ4 — skeleton runtime + AnimationClip + Skinner tests.

Covers:

* :class:`PoseState` / :class:`PosedSkeleton` — bind-pose defaults,
  local mutation, global-matrix hierarchy walk, palette computation.
* :class:`AnimationClip` — step / linear / cubicspline sampling,
  loop and clamp modes, quaternion SLERP correctness.
* :class:`Skinner` / :class:`Animator` — 1- and 2-bone skinning
  correctness, palette plumbing, playback control.
* Perf smoke — skin 1000 verts under a wall-clock budget.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

from pharos_engine.animation.skeleton_runtime import (
    PosedSkeleton,
    PoseState,
    Skeleton,
    SkeletonNode,
    SkinnedMeshData,
    compose_trs,
)
from pharos_engine.animation.clip import (
    AnimationChannel,
    AnimationClip,
    quat_normalise,
    quat_slerp,
)
from pharos_engine.animation.skinner import Animator, Skinner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _identity_quat() -> np.ndarray:
    return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


def _quat_from_axis_angle(axis, angle_rad: float) -> np.ndarray:
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    s = math.sin(angle_rad * 0.5)
    c = math.cos(angle_rad * 0.5)
    return np.array([a[0] * s, a[1] * s, a[2] * s, c], dtype=np.float32)


def _two_bone_chain() -> Skeleton:
    """Root at origin, child at +X = 1."""
    nodes = [
        SkeletonNode(
            name="root",
            parent_index=-1,
            translation=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            scale=(1.0, 1.0, 1.0),
        ),
        SkeletonNode(
            name="child",
            parent_index=0,
            translation=(1.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            scale=(1.0, 1.0, 1.0),
        ),
    ]
    return Skeleton(nodes=nodes)


# ---------------------------------------------------------------------------
# PoseState / PosedSkeleton
# ---------------------------------------------------------------------------

def test_pose_state_zeros_defaults():
    ps = PoseState.zeros(3)
    assert ps.joint_translations.shape == (3, 3)
    assert ps.joint_rotations.shape == (3, 4)
    assert ps.joint_scales.shape == (3, 3)
    assert ps.joint_translations.dtype == np.float32
    np.testing.assert_array_equal(
        ps.joint_rotations,
        np.tile(_identity_quat(), (3, 1)),
    )
    np.testing.assert_array_equal(
        ps.joint_scales,
        np.ones((3, 3), dtype=np.float32),
    )
    assert ps.dirty is True


def test_posed_skeleton_defaults_match_bind_pose():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    np.testing.assert_allclose(
        ps.pose.joint_translations[1], [1.0, 0.0, 0.0], atol=1e-6
    )
    np.testing.assert_allclose(
        ps.pose.joint_rotations[1], [0.0, 0.0, 0.0, 1.0], atol=1e-6
    )
    np.testing.assert_allclose(
        ps.pose.joint_scales[1], [1.0, 1.0, 1.0], atol=1e-6
    )


def test_posed_skeleton_reject_bad_input():
    with pytest.raises(TypeError):
        PosedSkeleton(None)
    with pytest.raises(TypeError):
        PosedSkeleton("not a skeleton")


def test_compute_global_matrices_two_bone_identity():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    g = ps.compute_global_matrices()
    assert g.shape == (2, 4, 4)
    np.testing.assert_allclose(g[0], np.eye(4), atol=1e-6)
    # Child global == translate(1, 0, 0).
    expected = np.eye(4)
    expected[0, 3] = 1.0
    np.testing.assert_allclose(g[1], expected, atol=1e-6)


def test_compute_global_matrices_child_inherits_parent_translation():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    ps.set_joint_local(0, translation=(2.0, 0.0, 0.0))
    g = ps.compute_global_matrices()
    # Child global translation = 2 (parent) + 1 (child local) = 3.
    assert abs(float(g[1, 0, 3]) - 3.0) < 1e-5


def test_compute_global_matrices_trs_compose_correct():
    # Single-bone chain, verify M = T * R * S element-by-element.
    skel = Skeleton(
        nodes=[
            SkeletonNode(
                name="j",
                parent_index=-1,
                translation=(1.0, 2.0, 3.0),
                rotation=(0.0, 0.0, 0.0, 1.0),
                scale=(2.0, 3.0, 4.0),
            )
        ]
    )
    ps = PosedSkeleton(skel)
    g = ps.compute_global_matrices()
    expected = np.diag([2.0, 3.0, 4.0, 1.0])
    expected[0, 3] = 1.0
    expected[1, 3] = 2.0
    expected[2, 3] = 3.0
    np.testing.assert_allclose(g[0], expected, atol=1e-6)


def test_set_joint_local_mutates_pose():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    ps.set_joint_local(1, translation=(5.0, 0.0, 0.0))
    np.testing.assert_allclose(
        ps.pose.joint_translations[1], [5.0, 0.0, 0.0], atol=1e-6
    )
    assert ps.pose.dirty is True


def test_set_joint_local_out_of_range_raises():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    with pytest.raises(IndexError):
        ps.set_joint_local(5, translation=(0.0, 0.0, 0.0))


def test_reset_to_bind_pose_restores_bind_transforms():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    ps.set_joint_local(1, translation=(7.0, 0.0, 0.0))
    ps.reset_to_bind_pose()
    np.testing.assert_allclose(
        ps.pose.joint_translations[1], [1.0, 0.0, 0.0], atol=1e-6
    )


def test_compute_skinning_palette_bind_pose_is_identity():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    palette = ps.compute_skinning_palette()
    assert palette.shape == (2, 4, 4)
    np.testing.assert_allclose(palette[0], np.eye(4), atol=1e-5)
    np.testing.assert_allclose(palette[1], np.eye(4), atol=1e-5)


def test_compute_skinning_palette_translation_effect():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    ps.set_joint_local(0, translation=(5.0, 0.0, 0.0))
    palette = ps.compute_skinning_palette()
    # Root moved by 5 → root skinning matrix translates by 5.
    assert abs(float(palette[0, 0, 3]) - 5.0) < 1e-4
    # Child also moves by 5 because it's rigidly attached to root.
    assert abs(float(palette[1, 0, 3]) - 5.0) < 1e-4


def test_compute_global_matrices_dirty_cache():
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    g1 = ps.compute_global_matrices()
    g2 = ps.compute_global_matrices()  # cached
    assert g1 is g2
    ps.set_joint_local(1, translation=(10.0, 0.0, 0.0))
    g3 = ps.compute_global_matrices()
    assert g3 is not g1
    assert abs(float(g3[1, 0, 3]) - 10.0) < 1e-5


# ---------------------------------------------------------------------------
# Quaternion helpers
# ---------------------------------------------------------------------------

def test_quat_slerp_identity_returns_identity():
    q = _identity_quat()
    out = quat_slerp(q, q, 0.5)
    np.testing.assert_allclose(out, q, atol=1e-6)


def test_quat_slerp_90_degrees_midpoint_is_45():
    q0 = _identity_quat()
    q1 = _quat_from_axis_angle((0, 0, 1), math.pi / 2)
    mid = quat_slerp(q0, q1, 0.5)
    expected = _quat_from_axis_angle((0, 0, 1), math.pi / 4)
    np.testing.assert_allclose(mid, expected, atol=1e-4)


def test_quat_slerp_endpoints():
    q0 = _identity_quat()
    q1 = _quat_from_axis_angle((0, 1, 0), math.pi / 2)
    np.testing.assert_allclose(quat_slerp(q0, q1, 0.0), q0, atol=1e-5)
    np.testing.assert_allclose(quat_slerp(q0, q1, 1.0), q1, atol=1e-5)


def test_quat_slerp_takes_short_path():
    q0 = _identity_quat()
    # -q1 represents the same rotation as q1 but the antipode.
    q1 = _quat_from_axis_angle((0, 0, 1), math.pi / 2)
    q1_flipped = -q1
    out_flipped = quat_slerp(q0, q1_flipped, 1.0)
    # After the short-path fix these should agree up to sign.
    q_out = out_flipped if out_flipped[3] >= 0.0 else -out_flipped
    q_ref = q1 if q1[3] >= 0.0 else -q1
    np.testing.assert_allclose(q_out, q_ref, atol=1e-4)


def test_quat_normalise_zero_returns_identity():
    out = quat_normalise(np.zeros(4, dtype=np.float32))
    np.testing.assert_allclose(out, _identity_quat(), atol=1e-6)


# ---------------------------------------------------------------------------
# AnimationClip sampling
# ---------------------------------------------------------------------------

def test_animation_channel_rejects_bad_property():
    with pytest.raises(ValueError):
        AnimationChannel(
            target_joint_index=0,
            target_property="colour",
            keyframes=np.array([0.0], dtype=np.float32),
            values=np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        )


def test_animation_channel_rejects_bad_interpolation():
    with pytest.raises(ValueError):
        AnimationChannel(
            target_joint_index=0,
            target_property="translation",
            keyframes=np.array([0.0], dtype=np.float32),
            values=np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
            interpolation="quintic",
        )


def test_animation_clip_rejects_empty_name():
    with pytest.raises(ValueError):
        AnimationClip(name="", duration_sec=1.0, channels=[])


def test_animation_clip_rejects_bad_duration():
    with pytest.raises(ValueError):
        AnimationClip(name="x", duration_sec=0.0, channels=[])


def test_clip_sample_linear_translation_midpoint():
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="linear",
    )
    clip = AnimationClip(name="slide", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(0.5, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], [1.0, 0.0, 0.0], atol=1e-5
    )


def test_clip_sample_step_translation_picks_left_key():
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="step",
    )
    clip = AnimationClip(name="step", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(0.6, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], [0.0, 0.0, 0.0], atol=1e-6
    )


def test_clip_sample_cubicspline_linear_behaviour_at_endpoints():
    # With zero tangents cubic Hermite equals linear at the endpoints.
    times = np.array([0.0, 1.0], dtype=np.float32)
    # Layout: (K, 3, C) = [in_tangent, value, out_tangent].
    zero = np.zeros(3, dtype=np.float32)
    v0 = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    v1 = np.array([2.0, 0.0, 0.0], dtype=np.float32)
    values = np.stack(
        [
            np.stack([zero, v0, zero], axis=0),
            np.stack([zero, v1, zero], axis=0),
        ],
        axis=0,
    )
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=times,
        values=values,
        interpolation="cubicspline",
    )
    clip = AnimationClip(name="c", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(0.0, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], v0, atol=1e-6
    )
    clip.sample(1.0, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], v1, atol=1e-6
    )
    # Zero-tangent Hermite midpoint = 0.5 * (v0 + v1).
    clip.sample(0.5, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], (v0 + v1) * 0.5, atol=1e-5
    )


def test_clip_sample_rotation_slerp_midpoint():
    q0 = _identity_quat()
    q1 = _quat_from_axis_angle((0, 0, 1), math.pi / 2)
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="rotation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.stack([q0, q1], axis=0),
        interpolation="linear",
    )
    clip = AnimationClip(name="spin", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(0.5, ps.pose, loop=False)
    expected = _quat_from_axis_angle((0, 0, 1), math.pi / 4)
    np.testing.assert_allclose(
        ps.pose.joint_rotations[0], expected, atol=1e-4
    )


def test_clip_sample_loop_wraps_time():
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="linear",
    )
    clip = AnimationClip(name="loopy", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    # t = 2.5 wraps → 0.5 → midpoint.
    clip.sample(2.5, ps.pose, loop=True)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], [2.0, 0.0, 0.0], atol=1e-5
    )


def test_clip_sample_clamps_when_not_looping():
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="linear",
    )
    clip = AnimationClip(name="oneshot", duration_sec=1.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(5.0, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], [4.0, 0.0, 0.0], atol=1e-5
    )


def test_clip_sample_left_of_first_key_clamps_left():
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([1.0, 2.0], dtype=np.float32),
        values=np.array([[3.0, 0.0, 0.0], [7.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="linear",
    )
    clip = AnimationClip(name="clamp", duration_sec=3.0, channels=[channel])
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    clip.sample(0.5, ps.pose, loop=False)
    np.testing.assert_allclose(
        ps.pose.joint_translations[0], [3.0, 0.0, 0.0], atol=1e-5
    )


# ---------------------------------------------------------------------------
# Skinner — 1- and 2-bone chains
# ---------------------------------------------------------------------------

def _one_bone_skinned_mesh() -> SkinnedMeshData:
    positions = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    joints = np.array([[0, 0, 0, 0]], dtype=np.int32)
    weights = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    return SkinnedMeshData(
        positions=positions, joints=joints, weights=weights
    )


def test_skinner_one_bone_full_weight_follows_bone():
    mesh = _one_bone_skinned_mesh()
    skel = Skeleton(
        nodes=[SkeletonNode(name="root", parent_index=-1)]
    )
    ps = PosedSkeleton(skel)
    ps.set_joint_local(0, translation=(10.0, 0.0, 0.0))
    palette = ps.compute_skinning_palette()
    skinned = Skinner(mesh).skin(palette=palette)
    np.testing.assert_allclose(
        skinned[0], [11.0, 0.0, 0.0], atol=1e-5
    )


def test_skinner_two_bone_blend_weight_interpolates():
    # One vertex at midpoint between two joints; blend 50/50.
    mesh = SkinnedMeshData(
        positions=np.array([[0.5, 0.0, 0.0]], dtype=np.float32),
        joints=np.array([[0, 1, 0, 0]], dtype=np.int32),
        weights=np.array([[0.5, 0.5, 0.0, 0.0]], dtype=np.float32),
    )
    skel = _two_bone_chain()
    ps = PosedSkeleton(skel)
    ps.set_joint_local(0, translation=(0.0, 2.0, 0.0))  # root up 2
    ps.set_joint_local(
        1, translation=(1.0, 0.0, 0.0)
    )  # child stays at +X (rel to parent)
    palette = ps.compute_skinning_palette()
    skinned = Skinner(mesh).skin(palette=palette)
    # Both joints translate up by 2 (root moves, child inherits) → vertex y=2.
    assert abs(float(skinned[0, 1]) - 2.0) < 1e-4


def test_skinner_bind_pose_is_no_op():
    mesh = _one_bone_skinned_mesh()
    skel = Skeleton(
        nodes=[SkeletonNode(name="root", parent_index=-1)]
    )
    ps = PosedSkeleton(skel)
    palette = ps.compute_skinning_palette()
    skinned = Skinner(mesh).skin(palette=palette)
    np.testing.assert_allclose(
        skinned[0], [1.0, 0.0, 0.0], atol=1e-5
    )


def test_skinner_normal_transform():
    mesh = SkinnedMeshData(
        positions=np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        joints=np.array([[0, 0, 0, 0]], dtype=np.int32),
        weights=np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        normals=np.array([[0.0, 0.0, 1.0]], dtype=np.float32),
    )
    skel = Skeleton(
        nodes=[SkeletonNode(name="root", parent_index=-1)]
    )
    ps = PosedSkeleton(skel)
    # Rotate 90 deg around Y — flips +Z normal to +X.
    q = _quat_from_axis_angle((0, 1, 0), math.pi / 2)
    ps.set_joint_local(0, rotation=q)
    palette = ps.compute_skinning_palette()
    skinner = Skinner(mesh)
    normals = skinner.skin_normals(palette)
    assert normals is not None
    np.testing.assert_allclose(
        normals[0], [1.0, 0.0, 0.0], atol=1e-4
    )


def test_skinner_rejects_wrong_joint_shape():
    bad = SkinnedMeshData(
        positions=np.zeros((1, 3), dtype=np.float32),
        joints=np.zeros((1, 3), dtype=np.int32),  # only 3 influences
        weights=np.zeros((1, 3), dtype=np.float32),
    )
    with pytest.raises(ValueError):
        Skinner(bad)


def test_skinner_rejects_none_mesh():
    with pytest.raises(TypeError):
        Skinner(None)


def test_skinner_requires_palette():
    mesh = _one_bone_skinned_mesh()
    skinner = Skinner(mesh)
    with pytest.raises(TypeError):
        skinner.skin()


# ---------------------------------------------------------------------------
# Animator — playback control + palette output
# ---------------------------------------------------------------------------

def _make_animator() -> Animator:
    mesh = _one_bone_skinned_mesh()
    skel = Skeleton(
        nodes=[SkeletonNode(name="root", parent_index=-1)]
    )
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]], dtype=np.float32),
        interpolation="linear",
    )
    clip = AnimationClip(name="scoot", duration_sec=1.0, channels=[channel])
    return Animator(mesh, skel, {"scoot": clip})


def test_animator_play_unknown_clip_raises():
    a = _make_animator()
    with pytest.raises(KeyError):
        a.play("nope")


def test_animator_advance_produces_expected_palette():
    a = _make_animator()
    a.play("scoot", loop=False)
    palette = a.advance(0.5)
    assert palette.shape == (1, 4, 4)
    # At t=0.5 → root translated by 2.
    assert abs(float(palette[0, 0, 3]) - 2.0) < 1e-4


def test_animator_stop_freezes_time():
    a = _make_animator()
    a.play("scoot", loop=True)
    a.advance(0.25)
    a.stop()
    assert a.is_playing is False
    assert a.current_clip is None


def test_animator_set_time_moves_playhead():
    a = _make_animator()
    a.play("scoot", loop=True)
    a.set_time(0.75)
    palette = a.advance(0.0)
    assert abs(float(palette[0, 0, 3]) - 3.0) < 1e-4


def test_animator_non_loop_freezes_at_end():
    a = _make_animator()
    a.play("scoot", loop=False)
    a.advance(2.0)  # way past duration
    assert a.is_playing is False
    palette = a.advance(0.0)
    assert abs(float(palette[0, 0, 3]) - 4.0) < 1e-4


def test_animator_skin_matches_expected():
    a = _make_animator()
    a.play("scoot", loop=False)
    a.advance(0.5)
    skinned = a.skin()
    # bind position (1, 0, 0) shifted by 2 → (3, 0, 0).
    np.testing.assert_allclose(skinned[0], [3.0, 0.0, 0.0], atol=1e-4)


def test_animator_add_clip_after_construction():
    a = _make_animator()
    channel = AnimationChannel(
        target_joint_index=0,
        target_property="translation",
        keyframes=np.array([0.0, 1.0], dtype=np.float32),
        values=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
    )
    a.add_clip(AnimationClip(name="tiny", duration_sec=1.0, channels=[channel]))
    a.play("tiny", loop=True)
    palette = a.advance(0.5)
    assert abs(float(palette[0, 0, 3]) - 0.5) < 1e-4


# ---------------------------------------------------------------------------
# compose_trs sanity + perf smoke
# ---------------------------------------------------------------------------

def test_compose_trs_identity():
    t = np.zeros(3, dtype=np.float32)
    r = _identity_quat()
    s = np.ones(3, dtype=np.float32)
    np.testing.assert_allclose(compose_trs(t, r, s), np.eye(4), atol=1e-6)


def test_compose_trs_translation_only():
    t = np.array([2.0, 3.0, 4.0], dtype=np.float32)
    r = _identity_quat()
    s = np.ones(3, dtype=np.float32)
    m = compose_trs(t, r, s)
    expected = np.eye(4)
    expected[:3, 3] = t
    np.testing.assert_allclose(m, expected, atol=1e-6)


def test_skinner_1000_verts_perf_smoke():
    """Skin 1000 verts, 4 influences, one joint — under 100 ms on any laptop."""
    n_verts = 1000
    mesh = SkinnedMeshData(
        positions=np.random.rand(n_verts, 3).astype(np.float32),
        joints=np.zeros((n_verts, 4), dtype=np.int32),
        weights=np.tile([1.0, 0.0, 0.0, 0.0], (n_verts, 1)).astype(np.float32),
    )
    skel = Skeleton(
        nodes=[SkeletonNode(name="root", parent_index=-1)]
    )
    ps = PosedSkeleton(skel)
    palette = ps.compute_skinning_palette()
    skinner = Skinner(mesh)
    # Warmup.
    skinner.skin(palette=palette)
    t0 = time.perf_counter()
    for _ in range(10):
        out = skinner.skin(palette=palette)
    dt = time.perf_counter() - t0
    assert out.shape == (n_verts, 3)
    # 10 iterations × 1000 verts, single joint — trivial by numpy standards.
    assert dt < 1.0, (
        f"Skinner too slow: {dt:.3f}s for 10 iterations × 1000 verts"
    )
