"""Cascaded shadow maps — CSM math + PCF WGSL (JJ7).

Sprint 7 of the Nova3D parity plan (see ``docs/nova3d_parity_sprint_plan_
2026_07_05.md``). This module is **math + WGSL source strings only** — the
actual wgpu wiring lives in JJ1's ``renderer.py``. Producing a compiled
pipeline is a downstream concern.

Design highlights
-----------------
* Practical (weighted) PSSM split scheme (Engel/Zhang). ``lambda_ = 0``
  yields uniform splits, ``lambda_ = 1`` yields fully logarithmic splits.
* Directional light view is a right-handed ``look_at`` from a synthesised
  "eye" pointing along the (opposite) light direction.
* Orthographic bounds are computed by transforming the 8 view-frustum
  corners of each split into light space and taking the AABB.
* Stabilisation snaps the AABB origin to a texel-sized grid — kills
  shimmering as the camera moves.
* Depth pass shader is intentionally minimal: no fragment shader body
  needed because we render depth-only. WGSL still requires the marker so
  we emit a nominal ``@fragment`` stub returning ``vec4<f32>(0.0)`` to
  keep tooling happy on API-validation layers that reject depth-only
  pipelines without a ``fs_main`` symbol.
* Sample snippet supports 4 cascades, 3×3 PCF, ``texture_depth_2d_array``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ----------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------
@dataclass
class CascadeSplit:
    """A single cascade level for a directional light."""

    near_z: float
    far_z: float
    light_view_matrix: np.ndarray  # (4, 4) float32
    light_projection_matrix: np.ndarray  # (4, 4) float32
    light_view_projection: np.ndarray  # (4, 4) float32
    shadow_map_index: int  # 0..cascade_count-1


@dataclass
class ShadowMapConfig:
    """Configuration for the CSM system."""

    resolution: int = 2048  # per-cascade texture size (square).
    cascade_count: int = 4
    cascade_split_lambda: float = 0.5  # 0 = uniform, 1 = logarithmic.
    max_shadow_distance: float = 100.0
    stabilize_cascades: bool = True  # snap origin to texel to reduce shimmer.


# ----------------------------------------------------------------------
# CSMBuilder — the actual math
# ----------------------------------------------------------------------
class CSMBuilder:
    """Cascaded shadow map math for a directional light + perspective camera.

    All matrix conventions match ``render/camera.py``:

    * 4×4 float32.
    * ``M @ column_vector`` semantics.
    * Reverse-Y clip space with ``z ∈ [0, 1]`` after projection.
    """

    # ---- split scheme -------------------------------------------------
    @staticmethod
    def compute_cascade_splits(
        camera_near: float,
        camera_far: float,
        count: int,
        lambda_: float,
    ) -> list[tuple[float, float]]:
        """Practical PSSM split scheme (Engel/Zhang).

        Returns a list of ``(near, far)`` pairs, one per cascade, whose
        near/far cover the ``[camera_near, camera_far]`` range.

        * ``lambda_ = 0`` → uniform splits (equal linear distances).
        * ``lambda_ = 1`` → logarithmic splits (equal log-scale distances).
        * Values in between blend the two.
        """
        if count <= 0:
            return []
        if camera_far <= camera_near:
            raise ValueError(
                f"camera_far ({camera_far}) must be > camera_near ({camera_near})"
            )
        lambda_ = float(np.clip(lambda_, 0.0, 1.0))

        near = float(camera_near)
        far = float(camera_far)
        ratio = far / max(near, 1e-6)
        splits: list[float] = [near]
        for i in range(1, count + 1):
            p = i / count
            log = near * (ratio ** p)
            uni = near + (far - near) * p
            d = lambda_ * log + (1.0 - lambda_) * uni
            splits.append(d)
        return [(splits[i], splits[i + 1]) for i in range(count)]

    # ---- light view --------------------------------------------------
    @staticmethod
    def compute_light_view(directional_light) -> np.ndarray:
        """Return a 4×4 view matrix looking along the light's direction.

        The eye is synthesised at ``-direction * 1.0`` — the actual
        translation is baked into the ortho projection later, so any
        finite eye works for building the rotation basis.
        """
        d = np.asarray(directional_light.direction, dtype=np.float32)
        n = float(np.linalg.norm(d))
        if n < 1e-8:
            d = np.array([0.0, -1.0, 0.0], dtype=np.float32)
        else:
            d = d / n

        # Eye pulled back along -d so that we look *along* d.
        eye = -d
        target = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        # Pick a stable world-up that is not colinear with the direction.
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        if abs(float(np.dot(d, world_up))) > 0.99:
            world_up = np.array([0.0, 0.0, 1.0], dtype=np.float32)

        f = target - eye
        f = f / max(float(np.linalg.norm(f)), 1e-8)
        s = np.cross(f, world_up)
        s = s / max(float(np.linalg.norm(s)), 1e-8)
        u = np.cross(s, f)

        m = np.eye(4, dtype=np.float32)
        m[0, :3] = s
        m[1, :3] = u
        m[2, :3] = -f
        m[0, 3] = -float(np.dot(s, eye))
        m[1, 3] = -float(np.dot(u, eye))
        m[2, 3] = float(np.dot(f, eye))
        return m

    # ---- frustum corners --------------------------------------------
    @staticmethod
    def frustum_corners_world(view_projection: np.ndarray) -> np.ndarray:
        """Return the 8 world-space corners of the view frustum.

        Corners in NDC are the standard cube ``(±1, ±1, {0, 1})``. We
        invert ``view_projection`` and transform each corner, dividing
        by the perspective ``w``.
        """
        vp_inv = np.linalg.inv(view_projection.astype(np.float64))
        ndc = np.array(
            [
                [-1.0, -1.0, 0.0, 1.0],
                [ 1.0, -1.0, 0.0, 1.0],
                [-1.0,  1.0, 0.0, 1.0],
                [ 1.0,  1.0, 0.0, 1.0],
                [-1.0, -1.0, 1.0, 1.0],
                [ 1.0, -1.0, 1.0, 1.0],
                [-1.0,  1.0, 1.0, 1.0],
                [ 1.0,  1.0, 1.0, 1.0],
            ],
            dtype=np.float64,
        )
        world = (vp_inv @ ndc.T).T
        w = world[:, 3:4]
        w = np.where(np.abs(w) < 1e-8, 1.0, w)
        return (world[:, :3] / w).astype(np.float32)

    # ---- ortho bounds -----------------------------------------------
    @staticmethod
    def compute_ortho_bounds(
        view_projection: np.ndarray,
        light_view: np.ndarray,
    ) -> tuple[float, float, float, float, float, float]:
        """Return the light-space AABB ``(l, r, b, t, n, f)`` of the frustum.

        The 8 world-space frustum corners are transformed into light
        space via ``light_view``; the AABB is the shadow-camera ortho
        bounds.
        """
        corners_world = CSMBuilder.frustum_corners_world(view_projection)
        homog = np.concatenate(
            [corners_world, np.ones((8, 1), dtype=np.float32)], axis=1
        )
        light_space = (light_view @ homog.T).T[:, :3]
        mn = light_space.min(axis=0)
        mx = light_space.max(axis=0)
        # In our convention the shadow ortho projects along -z in light
        # space, so the "near/far" range covers the light-space z extent.
        # Pad slightly to include casters just outside the frustum.
        return (
            float(mn[0]),
            float(mx[0]),
            float(mn[1]),
            float(mx[1]),
            float(mn[2]),
            float(mx[2]),
        )

    # ---- stabilisation ----------------------------------------------
    @staticmethod
    def stabilize(
        bounds: tuple[float, float, float, float, float, float],
        resolution: int,
    ) -> tuple[float, float, float, float, float, float]:
        """Snap the light-space AABB to a texel-sized grid.

        Removes cascade shimmering by ensuring the ortho origin only
        moves in whole-texel increments as the camera slides.
        """
        l, r, b, t, n, f = bounds
        width = max(r - l, 1e-6)
        height = max(t - b, 1e-6)
        texel_x = width / float(max(resolution, 1))
        texel_y = height / float(max(resolution, 1))
        l_snap = math.floor(l / texel_x) * texel_x
        r_snap = l_snap + width
        b_snap = math.floor(b / texel_y) * texel_y
        t_snap = b_snap + height
        return (l_snap, r_snap, b_snap, t_snap, n, f)

    # ---- ortho projection --------------------------------------------
    @staticmethod
    def _ortho_matrix(
        l: float, r: float, b: float, t: float, n: float, f: float
    ) -> np.ndarray:
        """Build a reverse-Y orthographic projection ``z ∈ [n, f] → [0, 1]``.

        Uses the same handedness / clip conventions as ``Camera3D``.
        """
        m = np.zeros((4, 4), dtype=np.float32)
        rl = max(r - l, 1e-6)
        tb = max(t - b, 1e-6)
        fn = f - n
        if abs(fn) < 1e-6:
            fn = 1e-6 if fn >= 0 else -1e-6
        m[0, 0] = 2.0 / rl
        m[1, 1] = 2.0 / tb
        # Map light-space z ∈ [n, f] linearly to clip z ∈ [0, 1].
        m[2, 2] = 1.0 / fn
        m[2, 3] = -n / fn
        m[3, 3] = 1.0
        m[0, 3] = -(r + l) / rl
        m[1, 3] = -(t + b) / tb
        return m

    # ---- top-level build --------------------------------------------
    @staticmethod
    def build_cascades(camera, light, config: ShadowMapConfig) -> list[CascadeSplit]:
        """Full CSM setup for one directional light and one perspective camera."""
        far = min(float(camera.far), float(config.max_shadow_distance))
        near = float(camera.near)
        splits = CSMBuilder.compute_cascade_splits(
            near, far, config.cascade_count, config.cascade_split_lambda
        )
        light_view = CSMBuilder.compute_light_view(light)

        cascades: list[CascadeSplit] = []
        # Snapshot the "real" camera parameters we override per-cascade.
        original_near = camera.near
        original_far = camera.far
        try:
            for idx, (n_z, f_z) in enumerate(splits):
                camera.near = float(n_z)
                camera.far = float(f_z)
                vp_split = camera.view_projection().astype(np.float32)
                bounds = CSMBuilder.compute_ortho_bounds(vp_split, light_view)
                if config.stabilize_cascades:
                    bounds = CSMBuilder.stabilize(bounds, config.resolution)
                l, r, b, t, n_l, f_l = bounds
                # Extend the light-space z range so casters slightly
                # outside the split frustum still write depth.
                z_pad = max((f_l - n_l) * 0.5, 1.0)
                light_proj = CSMBuilder._ortho_matrix(
                    l, r, b, t, n_l - z_pad, f_l + z_pad
                )
                light_vp = (light_proj @ light_view).astype(np.float32)
                cascades.append(
                    CascadeSplit(
                        near_z=float(n_z),
                        far_z=float(f_z),
                        light_view_matrix=light_view.copy(),
                        light_projection_matrix=light_proj,
                        light_view_projection=light_vp,
                        shadow_map_index=idx,
                    )
                )
        finally:
            camera.near = original_near
            camera.far = original_far
        return cascades


# ----------------------------------------------------------------------
# UBO packing + cascade selection
# ----------------------------------------------------------------------
def pack_cascade_ubo(cascades: Sequence[CascadeSplit]) -> bytes:
    """Pack up to 4 ``light_view_projection`` matrices into a UBO blob.

    Layout: ``array<mat4x4<f32>, 4>`` = 4 × 64 B = **256 B**. Missing
    cascades are zero-filled — the shader's ``sample_shadow_cascade``
    treats a zero matrix as "no data" via the ``cascade_index`` selector.
    """
    arr = np.zeros((4, 4, 4), dtype=np.float32)
    for i, c in enumerate(cascades[:4]):
        arr[i] = c.light_view_projection.astype(np.float32)
    return arr.tobytes()


def find_cascade_for_world_pos(
    world_pos: Sequence[float], cascades: Sequence[CascadeSplit]
) -> int:
    """Pick the tightest cascade whose ``light_view_projection`` covers ``world_pos``.

    Iterates from cascade 0 (highest resolution near the camera) upward
    and returns the first one whose projected NDC lies inside the unit
    cube ``[-1, 1]²`` in XY and ``[0, 1]`` in Z. Returns the last
    cascade index as a fallback so fragments beyond the last split still
    sample something.
    """
    if not cascades:
        return -1
    p = np.array([world_pos[0], world_pos[1], world_pos[2], 1.0], dtype=np.float32)
    for c in cascades:
        clip = c.light_view_projection @ p
        w = clip[3] if abs(clip[3]) > 1e-8 else 1.0
        ndc = clip[:3] / w
        if (
            -1.0 <= ndc[0] <= 1.0
            and -1.0 <= ndc[1] <= 1.0
            and 0.0 <= ndc[2] <= 1.0
        ):
            return int(c.shadow_map_index)
    return int(cascades[-1].shadow_map_index)


# ----------------------------------------------------------------------
# WGSL sources
# ----------------------------------------------------------------------
# Depth-only pass — writes only depth, colour target disabled by the pipeline.
SHADOW_DEPTH_ONLY_WGSL = """// pharos_engine shadow_depth_only
struct ShadowCam { lvp: mat4x4<f32> };
struct Model { model: mat4x4<f32> };
@group(0) @binding(0) var<uniform> cam: ShadowCam;
@group(1) @binding(0) var<uniform> mdl: Model;
@vertex
fn vs_main(@location(0) position: vec3<f32>) -> @builtin(position) vec4<f32> {
    return cam.lvp * (mdl.model * vec4<f32>(position, 1.0));
}
@fragment
fn fs_main() -> @location(0) vec4<f32> { return vec4<f32>(0.0); }
"""


# Fragment-shader snippet that samples a 4-cascade shadow map array with
# 3×3 PCF. Consumers concatenate this into their lit shader.
SHADOW_SAMPLE_WGSL_SNIPPET = """// pharos_engine shadow_sample_snippet — 4-cascade CSM + 3x3 PCF
fn sample_shadow_cascade(
    cascade_index: u32,
    world_pos: vec3<f32>,
    cascades: array<mat4x4<f32>, 4>,
    shadow_map: texture_depth_2d_array,
    shadow_sampler: sampler_comparison,
) -> f32 {
    let idx: i32 = i32(cascade_index);
    let clip = cascades[cascade_index] * vec4<f32>(world_pos, 1.0);
    let ndc = clip.xyz / max(clip.w, 0.0001);
    if (ndc.x < -1.0 || ndc.x > 1.0 || ndc.y < -1.0 || ndc.y > 1.0
        || ndc.z < 0.0 || ndc.z > 1.0) { return 1.0; }
    let uv = vec2<f32>(ndc.x * 0.5 + 0.5, 1.0 - (ndc.y * 0.5 + 0.5));
    let depth_ref = ndc.z - 0.0015;
    let ts = vec2<f32>(textureDimensions(shadow_map, 0).xy);
    let texel = vec2<f32>(1.0 / ts.x, 1.0 / ts.y);
    var vis: f32 = 0.0;
    for (var dy: i32 = -1; dy <= 1; dy = dy + 1) {
        for (var dx: i32 = -1; dx <= 1; dx = dx + 1) {
            let off = vec2<f32>(f32(dx), f32(dy)) * texel;
            vis = vis + textureSampleCompareLevel(
                shadow_map, shadow_sampler, uv + off, idx, depth_ref);
        }
    }
    return vis / 9.0;
}
"""


# ----------------------------------------------------------------------
# Sampler descriptor for the shadow comparison sampler.
# ----------------------------------------------------------------------
SHADOW_SAMPLER_DESC: dict = {
    "compare": "less_equal",
    "mag_filter": "linear",
    "min_filter": "linear",
    "mipmap_filter": "nearest",
    "address_mode_u": "clamp-to-edge",
    "address_mode_v": "clamp-to-edge",
    "address_mode_w": "clamp-to-edge",
    "lod_min_clamp": 0.0,
    "lod_max_clamp": 0.0,
}


__all__ = [
    "CSMBuilder",
    "CascadeSplit",
    "SHADOW_DEPTH_ONLY_WGSL",
    "SHADOW_SAMPLE_WGSL_SNIPPET",
    "SHADOW_SAMPLER_DESC",
    "ShadowMapConfig",
    "find_cascade_for_world_pos",
    "pack_cascade_ubo",
]
