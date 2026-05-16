"""SDF raymarching pipeline manager — 3-pass compute pipeline for SDF scene rendering."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import numpy as np

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

# RaymarchUniforms buffer layout (96 bytes total)
#   cam_pos:   vec4<f32>  offset  0  (16 bytes)
#   cam_dir:   vec4<f32>  offset 16  (16 bytes)
#   cam_right: vec4<f32>  offset 32  (16 bytes)
#   cam_up:    vec4<f32>  offset 48  (16 bytes)
#   fov_y:     f32        offset 64  (4 bytes)
#   max_steps: u32        offset 68  (4 bytes)
#   max_dist:  f32        offset 72  (4 bytes)
#   hit_eps:   f32        offset 76  (4 bytes)
#   width:     u32        offset 80  (4 bytes)
#   height:    u32        offset 84  (4 bytes)
#   _pad0:     u32        offset 88  (4 bytes)
#   _pad1:     u32        offset 92  (4 bytes)
# Total = 4×16 + 4×4 + 4×4 = 64 + 16 + 16 = 96 bytes
RAYMARCH_UNIFORMS_SIZE = 96   # bytes — matches WGSL struct RaymarchUniforms

# SceneUniforms buffer layout (16 bytes total)
#   prim_count: u32  (4 bytes)
#   _pad0–2:   u32  (12 bytes)
SCENE_UNIFORMS_SIZE = 16   # bytes

# Default raymarching quality constants
_DEFAULT_MAX_DIST = 5000.0
_DEFAULT_HIT_EPS  = 0.001
_DEFAULT_FOV_Y    = 1.047   # ~60° in radians
_DEFAULT_MAX_STEPS = 128

# Minimum storage buffer size required by WebGPU spec
_MIN_STORAGE_BUF_SIZE = 16

# Workgroup tile size for all three compute passes
_WORKGROUP_W = 8
_WORKGROUP_H = 8


class SdfRenderer:
    """Manages the 3-pass SDF raymarching pipeline.

    Pass 1: sdf_raymarching     — trace rays, write hit_pos + hit_normal textures
    Pass 2: sdf_gbuffer_write   — composite hit data into g-buffer textures
    Pass 3: contact_shadows     — contact shadow integration (SDF occlusion)

    Usage::

        renderer = SdfRenderer(gpu, width=1280, height=720)
        renderer.update_scene(scene)          # scene: SdfScene or list[SdfPrimitive]
        renderer.dispatch(cam_pos, cam_dir, cam_right, cam_up, fov_y=1.047)
        gbuf = renderer.get_gbuffer_textures() # dict with 'albedo', 'normal', 'depth'
    """

    def __init__(self, gpu, width: int, height: int) -> None:
        self._gpu = gpu
        self._width = width
        self._height = height
        self._ready = False
        self._prim_count = 0

        # Intermediate raymarching output textures
        self._hit_pos_tex    = None   # rgba32float — world-space hit position
        self._hit_normal_tex = None   # rgba16float — surface normal

        # G-buffer output textures
        self._gbuf_albedo_tex = None  # rgba8unorm
        self._gbuf_normal_tex = None  # rgba16float
        self._gbuf_depth_tex  = None  # r32float

        # GPU buffers
        self._prims_buf             = None   # storage — serialised SdfPrimitive bytes
        self._scene_uniforms_buf    = None   # uniform — prim_count + padding
        self._raymarch_uniforms_buf = None   # uniform — camera params + dims

        # Compiled compute pipelines (lazy)
        self._pipeline_raymarch = None
        self._pipeline_gbuf     = None
        self._pipeline_shadows  = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_resources(self) -> None:
        """Create GPU textures, buffers, and compute pipelines on first use."""
        if self._ready:
            return
        try:
            import wgpu

            device = self._gpu.device
            w, h = self._width, self._height

            storage_sample = (
                wgpu.TextureUsage.STORAGE_BINDING
                | wgpu.TextureUsage.TEXTURE_BINDING
            )

            # --- Intermediate raymarching textures ---
            self._hit_pos_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.rgba32float,
                usage=storage_sample,
            )
            self._hit_normal_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.rgba16float,
                usage=storage_sample,
            )

            # --- G-buffer output textures ---
            self._gbuf_albedo_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.rgba8unorm,
                usage=wgpu.TextureUsage.STORAGE_BINDING,
            )
            self._gbuf_normal_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.rgba16float,
                usage=wgpu.TextureUsage.STORAGE_BINDING,
            )
            self._gbuf_depth_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.r32float,
                usage=wgpu.TextureUsage.STORAGE_BINDING,
            )

            # --- Uniform buffers ---
            self._scene_uniforms_buf = device.create_buffer(
                size=SCENE_UNIFORMS_SIZE,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )
            self._raymarch_uniforms_buf = device.create_buffer(
                size=RAYMARCH_UNIFORMS_SIZE,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )

            # Placeholder storage buffer (grows in update_scene)
            self._prims_buf = device.create_buffer(
                size=_MIN_STORAGE_BUF_SIZE,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )

            # --- Compile compute pipelines ---
            self._pipeline_raymarch = self._compile_pipeline(
                device, "sdf_raymarching.wgsl", "main"
            )
            self._pipeline_gbuf = self._compile_pipeline(
                device, "sdf_gbuffer_write.wgsl", "main"
            )
            self._pipeline_shadows = self._compile_pipeline(
                device, "contact_shadows.wgsl", "main"
            )

            self._ready = True
        except Exception as e:
            print(f"[SdfRenderer] GPU resource init failed (headless?): {e}")

    @staticmethod
    def _compile_pipeline(device, shader_filename: str, entry_point: str):
        """Compile a single compute pipeline; returns None if shader missing."""
        shader_path = _SHADER_DIR / shader_filename
        if not shader_path.exists():
            print(f"[SdfRenderer] shader not found, skipping: {shader_path}")
            return None
        try:
            module = device.create_shader_module(
                code=shader_path.read_text(encoding="utf-8")
            )
            return device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": entry_point},
            )
        except Exception as e:
            print(f"[SdfRenderer] pipeline compile failed ({shader_filename}): {e}")
            return None

    def _pack_scene_uniforms(self, prim_count: int) -> bytes:
        """Pack SceneUniforms: prim_count u32 + 3 × u32 padding = 16 bytes."""
        return np.array([prim_count, 0, 0, 0], dtype=np.uint32).tobytes()

    def _pack_raymarch_uniforms(
        self,
        camera_pos,
        camera_dir,
        camera_right,
        camera_up,
        fov_y: float,
        max_steps: int,
        max_dist: float,
        hit_eps: float,
    ) -> bytes:
        """Pack RaymarchUniforms into 96 bytes matching the WGSL struct layout."""
        def _vec4(v) -> np.ndarray:
            arr = np.asarray(v, dtype=np.float32).ravel()
            out = np.zeros(4, dtype=np.float32)
            out[: min(4, len(arr))] = arr[:4]
            return out

        buf = bytearray(RAYMARCH_UNIFORMS_SIZE)

        # Bytes 0–63: four vec4<f32> camera vectors
        buf[ 0:16] = _vec4(camera_pos).tobytes()
        buf[16:32] = _vec4(camera_dir).tobytes()
        buf[32:48] = _vec4(camera_right).tobytes()
        buf[48:64] = _vec4(camera_up).tobytes()

        # Bytes 64–79: fov_y(f32) max_steps(u32) max_dist(f32) hit_eps(f32)
        buf[64:68] = np.float32(fov_y).tobytes()
        buf[68:72] = np.uint32(max_steps).tobytes()
        buf[72:76] = np.float32(max_dist).tobytes()
        buf[76:80] = np.float32(hit_eps).tobytes()

        # Bytes 80–95: width(u32) height(u32) _pad0(u32) _pad1(u32)
        buf[80:84] = np.uint32(self._width).tobytes()
        buf[84:88] = np.uint32(self._height).tobytes()
        buf[88:92] = np.uint32(0).tobytes()
        buf[92:96] = np.uint32(0).tobytes()

        return bytes(buf)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_scene(self, scene) -> None:
        """Upload SdfScene primitives to the GPU storage buffer.

        Accepts either:
          - An ``SdfScene`` object with a ``to_gpu_bytes()`` method (Rust-backed).
          - A list/sequence of ``SdfPrimitive`` objects each with ``to_gpu_bytes()``.
        """
        if not self._ready:
            self._ensure_resources()
        if not self._ready:
            return
        try:
            import wgpu

            # Serialise to raw bytes
            if hasattr(scene, "to_gpu_bytes"):
                raw: bytes = scene.to_gpu_bytes()
                prim_count: int = getattr(scene, "prim_count", len(raw) // max(1, len(raw)))
                # Attempt to get the authoritative count attribute
                if hasattr(scene, "len"):
                    prim_count = scene.len()
                elif hasattr(scene, "__len__"):
                    prim_count = len(scene)
            else:
                # Sequence of primitives
                chunks = [p.to_gpu_bytes() for p in scene]
                raw = b"".join(chunks)
                prim_count = len(chunks)

            self._prim_count = prim_count

            if not raw:
                self._prim_count = 0
                return

            buf_size = max(_MIN_STORAGE_BUF_SIZE, len(raw))

            # Recreate buffer if size changed
            if self._prims_buf is None or self._prims_buf.size < buf_size:
                self._prims_buf = self._gpu.device.create_buffer(
                    size=buf_size,
                    usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
                )

            self._gpu.device.queue.write_buffer(self._prims_buf, 0, raw)

            # Update scene uniforms
            self._gpu.device.queue.write_buffer(
                self._scene_uniforms_buf, 0,
                self._pack_scene_uniforms(prim_count),
            )
        except Exception as e:
            print(f"[SdfRenderer] update_scene failed: {e}")

    def dispatch(
        self,
        camera_pos,
        camera_dir,
        camera_right,
        camera_up,
        fov_y:     float = _DEFAULT_FOV_Y,
        max_steps: int   = _DEFAULT_MAX_STEPS,
    ) -> None:
        """Run the 3-pass SDF raymarching pipeline.

        Gracefully no-ops when the GPU is not ready or the scene is empty.

        Pass 1 — sdf_raymarching:   trace rays → hit_pos + hit_normal textures
        Pass 2 — sdf_gbuffer_write: composite hit data → g-buffer textures
        Pass 3 — contact_shadows:   screen-space SDF contact shadow integration
        """
        if not self._ready:
            self._ensure_resources()
        if not self._ready or self._prim_count == 0:
            return

        try:
            # Upload per-frame camera uniforms
            raymarch_data = self._pack_raymarch_uniforms(
                camera_pos, camera_dir, camera_right, camera_up,
                fov_y, max_steps, _DEFAULT_MAX_DIST, _DEFAULT_HIT_EPS,
            )
            self._gpu.device.queue.write_buffer(
                self._raymarch_uniforms_buf, 0, raymarch_data
            )

            enc = self._gpu.device.create_command_encoder()

            self._pass_raymarching(enc)
            self._pass_gbuffer_write(enc)
            self._pass_contact_shadows(enc)

            self._gpu.device.queue.submit([enc.finish()])
        except Exception as e:
            print(f"[SdfRenderer] dispatch error: {e}")

    def get_gbuffer_textures(self) -> dict:
        """Return g-buffer texture handles keyed by 'albedo', 'normal', 'depth'."""
        return {
            "albedo": self._gbuf_albedo_tex,
            "normal": self._gbuf_normal_tex,
            "depth":  self._gbuf_depth_tex,
        }

    def resize(self, width: int, height: int) -> None:
        """Recreate all screen-size textures when the window dimensions change."""
        if width == self._width and height == self._height:
            return
        self._width  = width
        self._height = height
        self._ready  = False
        # Drop old resources — GC will release them; new ones allocated on next dispatch
        self._hit_pos_tex     = None
        self._hit_normal_tex  = None
        self._gbuf_albedo_tex = None
        self._gbuf_normal_tex = None
        self._gbuf_depth_tex  = None
        self._prims_buf             = None
        self._scene_uniforms_buf    = None
        self._raymarch_uniforms_buf = None
        self._pipeline_raymarch = None
        self._pipeline_gbuf     = None
        self._pipeline_shadows  = None

    # ------------------------------------------------------------------
    # Private per-pass dispatch helpers
    # ------------------------------------------------------------------

    def _pass_raymarching(self, encoder) -> None:
        """Pass 1: trace rays from camera, write world-space hit_pos and hit_normal."""
        if self._pipeline_raymarch is None:
            return
        try:
            bgl = self._pipeline_raymarch.get_bind_group_layout(0)
            bg = self._gpu.device.create_bind_group(
                layout=bgl,
                entries=[
                    # binding 0: primitives storage buffer
                    {
                        "binding": 0,
                        "resource": {
                            "buffer": self._prims_buf,
                            "offset": 0,
                            "size":   self._prims_buf.size,
                        },
                    },
                    # binding 1: scene uniforms (prim_count)
                    {
                        "binding": 1,
                        "resource": {
                            "buffer": self._scene_uniforms_buf,
                            "offset": 0,
                            "size":   SCENE_UNIFORMS_SIZE,
                        },
                    },
                    # binding 2: camera / raymarching uniforms
                    {
                        "binding": 2,
                        "resource": {
                            "buffer": self._raymarch_uniforms_buf,
                            "offset": 0,
                            "size":   RAYMARCH_UNIFORMS_SIZE,
                        },
                    },
                    # binding 3: hit_pos output texture (storage write)
                    {"binding": 3, "resource": self._hit_pos_tex.create_view()},
                    # binding 4: hit_normal output texture (storage write)
                    {"binding": 4, "resource": self._hit_normal_tex.create_view()},
                ],
            )
            wx = (self._width  + _WORKGROUP_W - 1) // _WORKGROUP_W
            wy = (self._height + _WORKGROUP_H - 1) // _WORKGROUP_H
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_raymarch)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wx, wy)
            cp.end()
        except Exception as e:
            print(f"[SdfRenderer] pass_raymarching error: {e}")

    def _pass_gbuffer_write(self, encoder) -> None:
        """Pass 2: read hit textures, write albedo / normal / depth g-buffer."""
        if self._pipeline_gbuf is None:
            return
        try:
            bgl = self._pipeline_gbuf.get_bind_group_layout(0)
            bg = self._gpu.device.create_bind_group(
                layout=bgl,
                entries=[
                    # binding 0: hit_pos texture (read)
                    {"binding": 0, "resource": self._hit_pos_tex.create_view()},
                    # binding 1: hit_normal texture (read)
                    {"binding": 1, "resource": self._hit_normal_tex.create_view()},
                    # binding 2: primitives storage (for material lookup)
                    {
                        "binding": 2,
                        "resource": {
                            "buffer": self._prims_buf,
                            "offset": 0,
                            "size":   self._prims_buf.size,
                        },
                    },
                    # binding 3: scene uniforms
                    {
                        "binding": 3,
                        "resource": {
                            "buffer": self._scene_uniforms_buf,
                            "offset": 0,
                            "size":   SCENE_UNIFORMS_SIZE,
                        },
                    },
                    # binding 4: g-buffer albedo output
                    {"binding": 4, "resource": self._gbuf_albedo_tex.create_view()},
                    # binding 5: g-buffer normal output
                    {"binding": 5, "resource": self._gbuf_normal_tex.create_view()},
                    # binding 6: g-buffer depth output
                    {"binding": 6, "resource": self._gbuf_depth_tex.create_view()},
                ],
            )
            wx = (self._width  + _WORKGROUP_W - 1) // _WORKGROUP_W
            wy = (self._height + _WORKGROUP_H - 1) // _WORKGROUP_H
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_gbuf)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wx, wy)
            cp.end()
        except Exception as e:
            print(f"[SdfRenderer] pass_gbuffer_write error: {e}")

    def _pass_contact_shadows(self, encoder) -> None:
        """Pass 3: integrate SDF-based contact shadows into the g-buffer depth."""
        if self._pipeline_shadows is None:
            return
        try:
            bgl = self._pipeline_shadows.get_bind_group_layout(0)
            bg = self._gpu.device.create_bind_group(
                layout=bgl,
                entries=[
                    # binding 0: hit_pos texture (read — position for occlusion rays)
                    {"binding": 0, "resource": self._hit_pos_tex.create_view()},
                    # binding 1: hit_normal texture (read)
                    {"binding": 1, "resource": self._hit_normal_tex.create_view()},
                    # binding 2: primitives storage (SDF eval for shadow rays)
                    {
                        "binding": 2,
                        "resource": {
                            "buffer": self._prims_buf,
                            "offset": 0,
                            "size":   self._prims_buf.size,
                        },
                    },
                    # binding 3: scene uniforms
                    {
                        "binding": 3,
                        "resource": {
                            "buffer": self._scene_uniforms_buf,
                            "offset": 0,
                            "size":   SCENE_UNIFORMS_SIZE,
                        },
                    },
                    # binding 4: raymarch uniforms (light dir / params)
                    {
                        "binding": 4,
                        "resource": {
                            "buffer": self._raymarch_uniforms_buf,
                            "offset": 0,
                            "size":   RAYMARCH_UNIFORMS_SIZE,
                        },
                    },
                    # binding 5: g-buffer depth (read-write — shadow factor written here)
                    {"binding": 5, "resource": self._gbuf_depth_tex.create_view()},
                ],
            )
            wx = (self._width  + _WORKGROUP_W - 1) // _WORKGROUP_W
            wy = (self._height + _WORKGROUP_H - 1) // _WORKGROUP_H
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_shadows)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wx, wy)
            cp.end()
        except Exception as e:
            print(f"[SdfRenderer] pass_contact_shadows error: {e}")
