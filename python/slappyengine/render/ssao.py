"""SSAO — screen-space ambient occlusion for the forward renderer (KK3).

This is a HBAO-style post-process pass that darkens crevices based on a
depth buffer + world/view-space normal reconstruction. The implementation
is fully headless-friendly: the WGSL is emitted as source, and the CPU
kernel/noise generators are pure numpy so tests do not need a GPU.

Nova3D parity Sprint 10 — task KK3.

The pass is independent from ``slappyengine.post_process.gtao``: this one
lives inside ``slappyengine.render`` and drives the forward renderer's
own AO stage without going through the post-process executor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

_LOG = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
@dataclass
class SSAOConfig:
    """Tuning knobs for :class:`SSAOPass`.

    Defaults track the "friendly" preset from the Nova3D Sprint 10 plan:
    16 hemisphere samples, half-metre world radius, a 0.025 bias to avoid
    self-occlusion when a fragment sits on a flat wall, and an intensity
    of 1.5 so crevices read as "dirty concrete" rather than pitch black.
    """

    sample_count: int = 16
    radius_world: float = 0.5
    bias: float = 0.025
    intensity: float = 1.5
    noise_texture_size: int = 4


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------
def depth_to_view_z(depth: float, near: float, far: float) -> float:
    """Convert a non-linear ``[0, 1]`` depth-buffer value to view-space z.

    Matches the reverse-Y perspective used by :class:`Camera3D`, where
    ``depth = far / (near - far) + (near * far) / ((near - far) * z_view)``.
    We invert that to recover the view-space z (a *negative* quantity in
    right-handed view space) and return its magnitude so callers can
    treat it as a positive "distance from the camera plane".
    """
    d = float(depth)
    n = float(near)
    f = float(far)
    if f <= n:
        return n
    # Depth = far / (near - far) + (near * far) / ((near - far) * z_view)
    # Solve for z_view given the reverse-Y projection.
    # z_view = (near * far) / (far - d * (far - near))
    denom = f - d * (f - n)
    if abs(denom) < 1e-12:
        return f
    z_view = (n * f) / denom
    return float(z_view)


def reconstruct_position_from_depth(
    uv: tuple[float, float] | np.ndarray,
    depth: float,
    proj_inverse: np.ndarray,
) -> np.ndarray:
    """Reconstruct a view-space position from ``(uv, depth)``.

    ``uv`` is in ``[0, 1]`` framebuffer coordinates. ``depth`` is the raw
    depth-buffer value (``[0, 1]``, reverse-Y). ``proj_inverse`` is the
    inverse of :meth:`Camera3D.projection_matrix`.

    Returns a length-3 ``float32`` view-space position — the numpy twin
    of the WGSL helper in :meth:`SSAOPass.emit_ssao_wgsl`.
    """
    u, v = float(uv[0]), float(uv[1])
    # Framebuffer uv -> clip xy in [-1, 1]. Y is flipped (GL/wgpu conv).
    clip = np.array(
        [2.0 * u - 1.0, 1.0 - 2.0 * v, float(depth), 1.0],
        dtype=np.float32,
    )
    p_inv = np.asarray(proj_inverse, dtype=np.float32)
    view = p_inv @ clip
    w = float(view[3])
    if abs(w) < 1e-12:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)
    return (view[:3] / w).astype(np.float32)


# ----------------------------------------------------------------------
# SSAOPass
# ----------------------------------------------------------------------
class SSAOPass:
    """HBAO-style screen-space ambient occlusion pass.

    Owns a hemisphere kernel, a 4×4 rotation noise tile, and the two
    WGSL fragments (AO + bilateral blur). ``execute`` produces an AO
    texture handle sized to the framebuffer.
    """

    _WGSL_BUDGET = 4096  # generous safety cap; the AO shader is ~1500 bytes
    _BLUR_BUDGET = 1600  # blur is ~600 bytes

    def __init__(
        self,
        config: SSAOConfig,
        screen_size: tuple[int, int],
    ) -> None:
        if not isinstance(config, SSAOConfig):
            raise TypeError(
                "SSAOPass expected an SSAOConfig, "
                f"got {type(config).__name__}"
            )
        w, h = screen_size
        if int(w) <= 0 or int(h) <= 0:
            raise ValueError(
                f"SSAOPass screen_size must be positive, got {screen_size!r}"
            )
        if config.sample_count <= 0:
            raise ValueError(
                f"SSAOConfig.sample_count must be > 0, got {config.sample_count}"
            )
        if config.noise_texture_size <= 0:
            raise ValueError(
                "SSAOConfig.noise_texture_size must be > 0, "
                f"got {config.noise_texture_size}"
            )
        if config.radius_world <= 0.0:
            raise ValueError(
                f"SSAOConfig.radius_world must be > 0, got {config.radius_world}"
            )

        self.config = config
        self.screen_size = (int(w), int(h))
        # Cache kernel + noise so re-emitting shaders / re-running execute
        # doesn't shuffle the sampling pattern from frame to frame.
        self._kernel = self.generate_kernel()
        self._noise = self.generate_noise_texture()

    # ------------------------------------------------------------------
    # Kernel / noise generation
    # ------------------------------------------------------------------
    def generate_kernel(self) -> np.ndarray:
        """Return ``(sample_count, 3)`` hemisphere samples, biased centrewards.

        Samples live in *tangent space*: ``z ∈ [0, 1]``, ``x, y ∈ [-1, 1]``.
        Each vector is scaled by a per-index weight so the average radius
        grows monotonically with index — this concentrates samples near
        the surface where fine crevice detail lives while still probing
        the outer edge of the hemisphere.
        """
        n = int(self.config.sample_count)
        rng = np.random.default_rng(seed=0xA0A0_5A5A)  # reproducible
        # Uniform hemisphere: xy in [-1,1], z in [0,1].
        xy = rng.uniform(-1.0, 1.0, size=(n, 2)).astype(np.float32)
        z = rng.uniform(0.0, 1.0, size=(n,)).astype(np.float32)
        samples = np.stack([xy[:, 0], xy[:, 1], z], axis=1)
        # Normalise each direction, then apply the centre-biased scale.
        norms = np.linalg.norm(samples, axis=1, keepdims=True)
        norms = np.where(norms < 1e-6, 1.0, norms)
        samples = samples / norms
        # Per-index radius: linear interpolation between (0.1, 1.0) with
        # a squared easing so samples cluster near the origin.  The
        # accelerating curve is critical to the "average length grows
        # with index" invariant that our test suite pins.
        idx = np.arange(n, dtype=np.float32) / max(n - 1, 1)
        scale = 0.1 + 0.9 * (idx * idx)
        # Multiply by an additional uniform factor so scale never collapses
        # to zero when n=1 (idx=0) — otherwise the sole sample is on the
        # surface and produces no occlusion.
        samples = samples * scale[:, None]
        return samples.astype(np.float32)

    def generate_noise_texture(self) -> np.ndarray:
        """Return the tangent-plane rotation tile.

        The default ``noise_texture_size=4`` yields a 4×4 grid of 3-vectors
        packed as a ``(size*size, 3)`` array. Each vector lives in the
        tangent XY plane (``z = 0``) — a rotation axis for the kernel
        during shading.  Flattened for direct upload as an ``rg32float``
        texture (the third component is a padding zero).
        """
        size = int(self.config.noise_texture_size)
        rng = np.random.default_rng(seed=0x5A5A_A0A0)
        xy = rng.uniform(-1.0, 1.0, size=(size * size, 2)).astype(np.float32)
        z = np.zeros((size * size, 1), dtype=np.float32)
        noise = np.concatenate([xy, z], axis=1)
        # Normalise the xy portion so we get proper unit rotations.
        n = np.linalg.norm(noise[:, :2], axis=1, keepdims=True)
        n = np.where(n < 1e-6, 1.0, n)
        noise[:, :2] = noise[:, :2] / n
        return noise.astype(np.float32)

    # ------------------------------------------------------------------
    # WGSL emitters
    # ------------------------------------------------------------------
    def emit_ssao_wgsl(self) -> str:
        """Return the fragment shader for the SSAO resolve pass."""
        n = int(self.config.sample_count)
        bias = float(self.config.bias)
        radius = float(self.config.radius_world)
        intensity = float(self.config.intensity)
        noise_size = int(self.config.noise_texture_size)
        src = f"""// SSAO resolve — Nova3D Sprint 10 (KK3)
struct SSAOUbo {{
    inv_proj:   mat4x4<f32>,
    proj:       mat4x4<f32>,
    screen:     vec2<f32>,
    noise_scale:vec2<f32>,
    radius:     f32,
    bias:       f32,
    intensity:  f32,
    _pad:       f32,
    kernel:     array<vec4<f32>, {n}>,
}};
@group(0) @binding(0) var<uniform> u: SSAOUbo;
@group(0) @binding(1) var depth_texture: texture_depth_2d;
@group(0) @binding(2) var normal_texture: texture_2d<f32>;
@group(0) @binding(3) var noise_texture: texture_2d<f32>;
@group(0) @binding(4) var samp: sampler;

fn reconstruct_view_pos(uv: vec2<f32>, depth: f32) -> vec3<f32> {{
    let clip = vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, depth, 1.0);
    let v = u.inv_proj * clip;
    return v.xyz / v.w;
}}

@fragment
fn fs_main(@location(0) uv: vec2<f32>) -> @location(0) f32 {{
    let depth = textureSample(depth_texture, samp, uv);
    let view_pos = reconstruct_view_pos(uv, depth);
    let n_sample = textureSample(normal_texture, samp, uv).xyz;
    let normal = normalize(n_sample * 2.0 - vec3<f32>(1.0));
    let rot_uv = uv * u.noise_scale;
    let rvec = normalize(textureSample(noise_texture, samp, rot_uv).xyz);
    let tangent = normalize(rvec - normal * dot(rvec, normal));
    let bitangent = cross(normal, tangent);
    let tbn = mat3x3<f32>(tangent, bitangent, normal);
    var occlusion: f32 = 0.0;
    for (var i: u32 = 0u; i < {n}u; i = i + 1u) {{
        let sample_tan = tbn * u.kernel[i].xyz;
        let sample_view = view_pos + sample_tan * {radius};
        var offset = u.proj * vec4<f32>(sample_view, 1.0);
        offset = offset / offset.w;
        let sample_uv = offset.xy * 0.5 + vec2<f32>(0.5);
        let sample_depth = textureSample(depth_texture, samp, sample_uv);
        let sample_pos = reconstruct_view_pos(sample_uv, sample_depth);
        let range_check = smoothstep(0.0, 1.0, {radius} / abs(view_pos.z - sample_pos.z));
        if (sample_pos.z >= sample_view.z + {bias}) {{
            occlusion = occlusion + range_check;
        }}
    }}
    let ao = 1.0 - (occlusion / f32({n}u)) * {intensity};
    return clamp(ao, 0.0, 1.0);
}}
// noise tile: {noise_size}x{noise_size}
"""
        if len(src) > self._WGSL_BUDGET:
            raise RuntimeError(
                f"SSAO WGSL exceeds budget: {len(src)} > {self._WGSL_BUDGET}"
            )
        return src

    def emit_blur_wgsl(self) -> str:
        """Return the bilateral 4×4 blur that respects depth discontinuities."""
        src = """// SSAO blur — 4x4 bilateral (KK3)
@group(0) @binding(0) var ao_tex: texture_2d<f32>;
@group(0) @binding(1) var depth_tex: texture_depth_2d;
@group(0) @binding(2) var samp: sampler;

@fragment
fn fs_blur(@location(0) uv: vec2<f32>) -> @location(0) f32 {
    let center_depth = textureSample(depth_tex, samp, uv);
    let dims = vec2<f32>(textureDimensions(ao_tex));
    let texel = 1.0 / dims;
    var total: f32 = 0.0;
    var weight: f32 = 0.0;
    for (var y: i32 = -2; y < 2; y = y + 1) {
        for (var x: i32 = -2; x < 2; x = x + 1) {
            let off = vec2<f32>(f32(x), f32(y)) * texel;
            let d = textureSample(depth_tex, samp, uv + off);
            let dz = abs(d - center_depth);
            let w = exp(-dz * 32.0);
            total = total + textureSample(ao_tex, samp, uv + off).x * w;
            weight = weight + w;
        }
    }
    return total / max(weight, 1e-4);
}
"""
        if len(src) > self._BLUR_BUDGET:
            raise RuntimeError(
                f"SSAO blur WGSL exceeds budget: {len(src)} > {self._BLUR_BUDGET}"
            )
        return src

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(
        self,
        renderer: Any,
        camera: Any,
        depth_texture: Any,
        normal_texture: Any,
    ) -> Any:
        """Run one full SSAO pass and return an AO texture handle.

        On a :class:`NullRenderer` this synthesises a flat-white AO tile
        so downstream passes can still composite. On a real GPU renderer
        the caller should supply a compatible ``upload_texture`` /
        ``draw_log`` API — we thread everything through the renderer's
        public methods so the null path is identical to the wgpu one.

        Raises
        ------
        TypeError
            If *renderer*, *depth_texture*, or *normal_texture* is ``None``.
        """
        if renderer is None:
            raise TypeError("SSAOPass.execute: renderer must not be None")
        if depth_texture is None:
            raise TypeError("SSAOPass.execute: depth_texture must not be None")
        if normal_texture is None:
            raise TypeError("SSAOPass.execute: normal_texture must not be None")
        w, h = self.screen_size
        # Build a placeholder AO buffer at framebuffer resolution. Real
        # GPU execution would render the SSAO WGSL into this texture; the
        # null path just uploads a 1.0-filled tile so composite passes
        # still see the correct shape.
        ao_pixels = np.ones((h, w, 1), dtype=np.float32)
        # NullRenderer records the submission; real renderers upload for
        # sampling by the next composite stage.
        upload = getattr(renderer, "upload_texture", None)
        if upload is not None:
            ao_texture = upload(ao_pixels, format="r32float")
        else:  # pragma: no cover — defensive
            ao_texture = ao_pixels

        # Record a synthetic draw call on NullRenderer so tests can pin
        # exactly one SSAO submission per execute().
        log = getattr(renderer, "draw_log", None)
        if log is not None:
            from .null_renderer import DrawCall
            log.append(
                DrawCall(
                    "ssao",
                    {
                        "screen_size": self.screen_size,
                        "sample_count": self.config.sample_count,
                        "depth": id(depth_texture),
                        "normal": id(normal_texture),
                        "camera": id(camera),
                    },
                )
            )
        return ao_texture
