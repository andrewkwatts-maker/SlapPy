"""AnimationClip — sampled animation channels with SLERP + cubic spline.

An :class:`AnimationClip` bundles a list of :class:`AnimationChannel`
records — each channel targets exactly one property (``translation``,
``rotation``, ``scale``) on exactly one joint of a skeleton. Sampling a
clip at time ``t`` walks every channel, interpolates between its
enclosing keyframes, and writes the result into a live
:class:`~slappyengine.animation.skeleton_runtime.PoseState`.

Three interpolation modes match the glTF 2.0 spec:

* ``"step"``      — pick the previous keyframe verbatim.
* ``"linear"``    — linear interpolation for T/S; spherical (SLERP) for R.
* ``"cubicspline"`` — Hermite spline with in/out tangents. Values are
  laid out as ``[in_tangent, value, out_tangent]`` per keyframe.

Wraparound
----------
``AnimationClip.sample(t, pose)`` wraps ``t`` modulo ``duration_sec``
when ``loop=True`` (the default). When ``loop=False``, ``t`` is
clamped to ``[0, duration_sec]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Quaternion helpers — kept local for clarity (CC6 easing curves also
# have a quat lib but we want zero cross-module coupling here).
# ---------------------------------------------------------------------------

def quat_normalise(q: np.ndarray) -> np.ndarray:
    """Return a unit-length quaternion."""
    q = np.asarray(q, dtype=np.float32)
    n = float(np.linalg.norm(q))
    if n < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    return q / n


def quat_slerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation between two ``(x, y, z, w)`` quats.

    Falls back to a normalised lerp for antipodal-ish inputs to sidestep
    the numerical badlands near dot == +/-1.
    """
    q0 = np.asarray(q0, dtype=np.float32)
    q1 = np.asarray(q1, dtype=np.float32)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        # Flip q1 to take the short path.
        q1 = -q1
        dot = -dot
    # Very close — fall back to linear + normalise.
    if dot > 0.9995:
        result = q0 + t * (q1 - q0)
        return quat_normalise(result)
    theta_0 = float(np.arccos(np.clip(dot, -1.0, 1.0)))
    sin_theta_0 = float(np.sin(theta_0))
    theta = theta_0 * float(t)
    sin_theta = float(np.sin(theta))
    s0 = float(np.cos(theta)) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    result = s0 * q0 + s1 * q1
    return quat_normalise(result)


# ---------------------------------------------------------------------------
# Channel + Clip dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnimationChannel:
    """A single animation channel targeting one property of one joint.

    Parameters
    ----------
    target_joint_index
        Joint index in the target skeleton.
    target_property
        One of ``"translation"`` / ``"rotation"`` / ``"scale"``.
    keyframes
        ``(K,)`` float32 keyframe times, monotonically increasing.
    values
        ``(K, C)`` float32 values (``C = 3`` for T/S, ``C = 4`` for R).
        For ``interpolation == "cubicspline"`` the layout is
        ``(K, 3, C)`` — in-tangent, value, out-tangent per keyframe.
    interpolation
        ``"linear"`` (default) / ``"step"`` / ``"cubicspline"``.
    """
    target_joint_index: int
    target_property: str
    keyframes: np.ndarray
    values: np.ndarray
    interpolation: str = "linear"

    def __post_init__(self) -> None:
        if self.target_property not in ("translation", "rotation", "scale"):
            raise ValueError(
                "target_property must be translation/rotation/scale; "
                f"got {self.target_property!r}"
            )
        if self.interpolation not in ("linear", "step", "cubicspline"):
            raise ValueError(
                "interpolation must be linear/step/cubicspline; "
                f"got {self.interpolation!r}"
            )
        # Normalise dtype without copying if already float32.
        self.keyframes = np.asarray(self.keyframes, dtype=np.float32).ravel()
        self.values = np.asarray(self.values, dtype=np.float32)
        if self.keyframes.ndim != 1 or self.keyframes.size == 0:
            raise ValueError(
                "keyframes must be a non-empty 1-D array; "
                f"got shape {self.keyframes.shape}"
            )


@dataclass
class AnimationClip:
    """A named animation clip — one or more channels sharing a duration.

    Parameters
    ----------
    name
        Human-readable clip name (matches glTF ``animation.name``).
    duration_sec
        Total clip duration.
    channels
        The animation channels the clip drives.
    """
    name: str
    duration_sec: float
    channels: list[AnimationChannel] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(
                f"AnimationClip.name must be a non-empty str; "
                f"got {self.name!r}"
            )
        if not (self.duration_sec > 0):
            raise ValueError(
                f"AnimationClip.duration_sec must be > 0; "
                f"got {self.duration_sec!r}"
            )
        if not isinstance(self.channels, list):
            raise TypeError(
                "AnimationClip.channels must be a list; "
                f"got {type(self.channels).__name__}"
            )

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample_channel(
        self, channel: AnimationChannel, time: float
    ) -> np.ndarray:
        """Interpolate a single channel at ``time`` (already clamped)."""
        keys = channel.keyframes
        vals = channel.values
        n = keys.size
        # Left-edge clamp.
        if time <= float(keys[0]):
            return _channel_value_at(channel, 0)
        # Right-edge clamp.
        if time >= float(keys[-1]):
            return _channel_value_at(channel, n - 1)
        # searchsorted returns the insertion index — the keyframe
        # index >= time. We want the pair (i-1, i).
        idx_right = int(np.searchsorted(keys, time, side="right"))
        idx_left = max(idx_right - 1, 0)
        idx_right = min(idx_right, n - 1)
        t0 = float(keys[idx_left])
        t1 = float(keys[idx_right])
        if t1 == t0:
            return _channel_value_at(channel, idx_left)
        u = (time - t0) / (t1 - t0)
        if channel.interpolation == "step":
            return _channel_value_at(channel, idx_left)
        if channel.interpolation == "linear":
            if channel.target_property == "rotation":
                return quat_slerp(
                    _channel_value_at(channel, idx_left),
                    _channel_value_at(channel, idx_right),
                    u,
                )
            v0 = _channel_value_at(channel, idx_left)
            v1 = _channel_value_at(channel, idx_right)
            return (v0 + (v1 - v0) * u).astype(np.float32)
        # Cubic spline (glTF Hermite form).
        return _cubicspline_sample(channel, idx_left, idx_right, t0, t1, u)

    def sample(
        self, time_sec: float, pose_state, loop: bool = True
    ) -> None:
        """Write clip pose at ``time_sec`` into ``pose_state``.

        Handles loop wrap when ``loop=True``; clamps otherwise. Every
        channel is applied; joints not covered by the clip retain
        whatever value they had going in.

        Raises
        ------
        TypeError
            If ``pose_state`` is ``None`` or lacks the required
            ``joint_translations`` / ``joint_rotations`` /
            ``joint_scales`` attributes.
        """
        if pose_state is None:
            raise TypeError("AnimationClip.sample: pose_state must not be None")
        for attr in ("joint_translations", "joint_rotations", "joint_scales"):
            if not hasattr(pose_state, attr):
                raise TypeError(
                    "AnimationClip.sample: pose_state must expose "
                    f"'{attr}'; got {type(pose_state).__name__}"
                )
        if not self.channels:
            return
        t = float(time_sec)
        if loop:
            t = t % self.duration_sec
        else:
            if t < 0.0:
                t = 0.0
            elif t > self.duration_sec:
                t = self.duration_sec
        for channel in self.channels:
            value = self.sample_channel(channel, t)
            j = channel.target_joint_index
            if channel.target_property == "translation":
                pose_state.joint_translations[j] = value
            elif channel.target_property == "rotation":
                pose_state.joint_rotations[j] = value
            else:
                pose_state.joint_scales[j] = value
        pose_state.dirty = True


# ---------------------------------------------------------------------------
# Internals — value-at-keyframe accessor + cubic Hermite eval
# ---------------------------------------------------------------------------

def _channel_value_at(channel: AnimationChannel, key_idx: int) -> np.ndarray:
    """Fetch the value at a single keyframe index (mode-aware layout)."""
    if channel.interpolation == "cubicspline":
        # values shape: (K, 3, C) → the middle slice is the actual value.
        if channel.values.ndim == 3:
            return channel.values[key_idx, 1].copy()
        # Fallback for callers who packed it flat (K, 3*C).
        c = channel.values.shape[-1] // 3
        return channel.values[key_idx, c:2 * c].copy()
    return channel.values[key_idx].copy()


def _cubicspline_sample(
    channel: AnimationChannel,
    i_left: int,
    i_right: int,
    t0: float,
    t1: float,
    u: float,
) -> np.ndarray:
    """Evaluate a glTF Hermite spline segment at parameter ``u ∈ [0, 1]``."""
    dt = t1 - t0
    # glTF stores per-key: [in_tangent, value, out_tangent].
    if channel.values.ndim == 3:
        vL = channel.values[i_left, 1]
        aL = channel.values[i_left, 2]  # out-tangent of left key
        vR = channel.values[i_right, 1]
        bR = channel.values[i_right, 0]  # in-tangent of right key
    else:
        c = channel.values.shape[-1] // 3
        vL = channel.values[i_left, c:2 * c]
        aL = channel.values[i_left, 2 * c:3 * c]
        vR = channel.values[i_right, c:2 * c]
        bR = channel.values[i_right, 0:c]
    u2 = u * u
    u3 = u2 * u
    # glTF cubic Hermite basis functions.
    h00 = 2.0 * u3 - 3.0 * u2 + 1.0
    h10 = u3 - 2.0 * u2 + u
    h01 = -2.0 * u3 + 3.0 * u2
    h11 = u3 - u2
    result = h00 * vL + h10 * dt * aL + h01 * vR + h11 * dt * bR
    if channel.target_property == "rotation":
        # Renormalise interpolated quaternion.
        return quat_normalise(result.astype(np.float32))
    return result.astype(np.float32)
