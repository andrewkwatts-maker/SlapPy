"""3D clustered lighting pipeline manager — build + cull passes."""
from __future__ import annotations

import struct
from pathlib import Path

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

TILES_X = 16
TILES_Y = 9
TILES_Z = 24
TOTAL_CLUSTERS = TILES_X * TILES_Y * TILES_Z   # 3456
MAX_LIGHTS = 256
MAX_LIGHTS_PER_CLUSTER = 64

# Buffer size constants
_AABB_STRIDE = 32          # ClusterAABB = 2 × vec4<f32>
_LIGHT_STRIDE = 32         # GpuLight3D  = 2 × vec4<f32>
_GRID_STRIDE  = (MAX_LIGHTS_PER_CLUSTER + 1) * 4  # u32s per cluster

_BUILD_UNIFORMS_SIZE = 96  # 16×4 (inv_proj) + 4×4 (screen_w/h, near, far) + 4×4 (tiles x/y/z + pad)
_CULL_UNIFORMS_SIZE  = 80  # 16×4 (view mat4) + 4×4 (light_count + 3 pad)


class Cluster3DSystem:
    """Manages the 3-pass 3D clustered lighting pipeline.

    Pass 1 — cluster_build_3d: build view-space AABBs (run once per camera change)
    Pass 2 — cluster_cull_3d: sphere-AABB light culling (run per frame)

    The result buffers (light_grid, light_count_grid) are bound to the
    mesh_frag_clustered_pbr.wgsl shader at group(2) by the render pipeline.
    """

    def __init__(self, gpu, width: int, height: int) -> None:
        self._gpu = gpu
        self._width = width
        self._height = height
        self._ready = False

        # GPU buffers
        self._cluster_aabb_buf   = None  # ClusterAABB × TOTAL_CLUSTERS (32 bytes each)
        self._light_buf          = None  # GpuLight3D  × MAX_LIGHTS      (32 bytes each)
        self._light_grid_buf     = None  # u32 × TOTAL_CLUSTERS × (MAX_LIGHTS_PER_CLUSTER+1)
        self._light_count_buf    = None  # atomic u32 × TOTAL_CLUSTERS
        self._build_uniforms_buf = None  # ClusterBuildUniforms  (96 bytes)
        self._cull_uniforms_buf  = None  # ClusterCullUniforms   (80 bytes)

        # Pipelines
        self._pipeline_build = None
        self._pipeline_cull  = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_resources(self) -> None:
        """Lazily allocate GPU buffers and compile compute pipelines."""
        if self._ready:
            return

        build_path = _SHADER_DIR / "cluster_build_3d.wgsl"
        cull_path  = _SHADER_DIR / "cluster_cull_3d.wgsl"

        missing = [p for p in (build_path, cull_path) if not p.exists()]
        if missing:
            for p in missing:
                print(f"[Cluster3DSystem] shader not found: {p}")
            return

        try:
            import wgpu

            device = self._gpu.device

            # ── Storage buffers ────────────────────────────────────────
            self._cluster_aabb_buf = device.create_buffer(
                size=TOTAL_CLUSTERS * _AABB_STRIDE,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )
            self._light_buf = device.create_buffer(
                size=MAX_LIGHTS * _LIGHT_STRIDE,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )
            self._light_grid_buf = device.create_buffer(
                size=TOTAL_CLUSTERS * _GRID_STRIDE,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )
            self._light_count_buf = device.create_buffer(
                size=TOTAL_CLUSTERS * 4,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )

            # ── Uniform buffers ────────────────────────────────────────
            self._build_uniforms_buf = device.create_buffer(
                size=_BUILD_UNIFORMS_SIZE,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )
            self._cull_uniforms_buf = device.create_buffer(
                size=_CULL_UNIFORMS_SIZE,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )

            # ── Compile shaders ────────────────────────────────────────
            build_src = build_path.read_text(encoding="utf-8")
            cull_src  = cull_path.read_text(encoding="utf-8")

            build_module = device.create_shader_module(code=build_src)
            cull_module  = device.create_shader_module(code=cull_src)

            try:
                self._pipeline_build = device.create_compute_pipeline(
                    layout="auto",
                    compute={"module": build_module, "entry_point": "main"},
                )
            except Exception as exc:
                print(f"[Cluster3DSystem] build pipeline compile failed: {exc}")

            try:
                self._pipeline_cull = device.create_compute_pipeline(
                    layout="auto",
                    compute={"module": cull_module, "entry_point": "main"},
                )
            except Exception as exc:
                print(f"[Cluster3DSystem] cull pipeline compile failed: {exc}")

            self._ready = True

        except Exception as exc:
            print(f"[Cluster3DSystem] _ensure_resources failed: {exc}")

    def _pack_build_uniforms(
        self,
        inv_proj: list[float],
        near: float,
        far: float,
    ) -> bytes:
        """Pack ClusterBuildUniforms into 96 bytes.

        Layout (matches cluster_build_3d.wgsl ClusterBuildUniforms):
          offset  0: mat4x4<f32>  inv_proj        (64 bytes, 16 × f32)
          offset 64: f32          screen_w
          offset 68: f32          screen_h
          offset 72: f32          near
          offset 76: f32          far
          offset 80: u32          tiles_x
          offset 84: u32          tiles_y
          offset 88: u32          tiles_z
          offset 92: u32          _pad
        """
        mat = struct.pack("16f", *inv_proj)
        rest = struct.pack(
            "4f4I",
            float(self._width), float(self._height), near, far,
            TILES_X, TILES_Y, TILES_Z, 0,
        )
        return mat + rest

    def _pack_cull_uniforms(self, view_matrix: list[float], light_count: int) -> bytes:
        """Pack ClusterCullUniforms into 80 bytes.

        Layout (matches cluster_cull_3d.wgsl ClusterCullUniforms):
          offset  0: mat4x4<f32>  view            (64 bytes, 16 × f32)
          offset 64: u32          light_count
          offset 68: u32          _pad0
          offset 72: u32          _pad1
          offset 76: u32          _pad2
        """
        mat = struct.pack("16f", *view_matrix)
        rest = struct.pack("4I", light_count, 0, 0, 0)
        return mat + rest

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_clusters(self, inv_proj: list[float], near: float, far: float) -> None:
        """Pass 1: build cluster AABBs from camera projection.

        inv_proj: 16 floats (column-major mat4x4, inverse of projection matrix).
        Call whenever camera projection changes.

        Dispatches (1, 1, TILES_Z) workgroups of size (16, 9, 1), one thread
        per XY tile, iterated over all 24 Z slices.
        """
        self._ensure_resources()
        if not self._ready or self._pipeline_build is None:
            return

        try:
            device = self._gpu.device

            # Upload uniforms
            uniforms_data = self._pack_build_uniforms(inv_proj, near, far)
            device.queue.write_buffer(self._build_uniforms_buf, 0, uniforms_data)

            # Build bind group  (group 0 of cluster_build_3d.wgsl)
            #   binding(0) — ClusterBuildUniforms  (uniform)
            #   binding(1) — clusters[]            (storage, read_write)
            bg = device.create_bind_group(
                layout=self._pipeline_build.get_bind_group_layout(0),
                entries=[
                    {
                        "binding": 0,
                        "resource": {
                            "buffer": self._build_uniforms_buf,
                            "offset": 0,
                            "size": _BUILD_UNIFORMS_SIZE,
                        },
                    },
                    {
                        "binding": 1,
                        "resource": {
                            "buffer": self._cluster_aabb_buf,
                            "offset": 0,
                            "size": self._cluster_aabb_buf.size,
                        },
                    },
                ],
            )

            encoder = device.create_command_encoder()
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_build)
            cp.set_bind_group(0, bg)
            # Dispatch (1, 1, TILES_Z) — workgroup size is (16, 9, 1)
            cp.dispatch_workgroups(1, 1, TILES_Z)
            cp.end()
            device.queue.submit([encoder.finish()])

        except Exception as exc:
            print(f"[Cluster3DSystem] build_clusters failed: {exc}")

    def cull_lights(self, lights: list, view_matrix: list[float]) -> None:
        """Pass 2: bin lights into clusters.

        lights: list of objects with pos (xyz), radius (float),
                color (xyz), intensity (float).
        view_matrix: 16 floats (column-major mat4x4, world→view).

        Dispatches ceil(len(lights) / 64) workgroups of size (64, 1, 1).
        Must be called after build_clusters() has completed.
        """
        self._ensure_resources()
        if not self._ready or self._pipeline_cull is None:
            return

        n_lights = min(len(lights), MAX_LIGHTS)
        if n_lights == 0:
            return

        try:
            device = self._gpu.device

            # Pack light data into GpuLight3D structs (32 bytes each)
            light_bytes = bytearray(MAX_LIGHTS * _LIGHT_STRIDE)
            for i, light in enumerate(lights[:n_lights]):
                pos    = light.pos    if hasattr(light, "pos")    else (0.0, 0.0, 0.0)
                radius = float(light.radius) if hasattr(light, "radius") else 1.0
                color  = light.color  if hasattr(light, "color")  else (1.0, 1.0, 1.0)
                inten  = float(light.intensity) if hasattr(light, "intensity") else 1.0
                offset = i * _LIGHT_STRIDE
                struct.pack_into(
                    "8f",
                    light_bytes,
                    offset,
                    float(pos[0]), float(pos[1]), float(pos[2]), radius,
                    float(color[0]), float(color[1]), float(color[2]), inten,
                )

            device.queue.write_buffer(self._light_buf, 0, bytes(light_bytes))

            # Pack and upload cull uniforms
            cull_data = self._pack_cull_uniforms(view_matrix, n_lights)
            device.queue.write_buffer(self._cull_uniforms_buf, 0, cull_data)

            # Build bind group  (group 0 of cluster_cull_3d.wgsl)
            #   binding(0) — ClusterCullUniforms  (uniform)
            #   binding(1) — lights[]             (storage, read)
            #   binding(2) — clusters[]           (storage, read)
            #   binding(3) — light_grid[]         (storage, read_write)
            #   binding(4) — light_count_grid[]   (storage, read_write, atomic<u32>)
            bg = device.create_bind_group(
                layout=self._pipeline_cull.get_bind_group_layout(0),
                entries=[
                    {
                        "binding": 0,
                        "resource": {
                            "buffer": self._cull_uniforms_buf,
                            "offset": 0,
                            "size": _CULL_UNIFORMS_SIZE,
                        },
                    },
                    {
                        "binding": 1,
                        "resource": {
                            "buffer": self._light_buf,
                            "offset": 0,
                            "size": self._light_buf.size,
                        },
                    },
                    {
                        "binding": 2,
                        "resource": {
                            "buffer": self._cluster_aabb_buf,
                            "offset": 0,
                            "size": self._cluster_aabb_buf.size,
                        },
                    },
                    {
                        "binding": 3,
                        "resource": {
                            "buffer": self._light_grid_buf,
                            "offset": 0,
                            "size": self._light_grid_buf.size,
                        },
                    },
                    {
                        "binding": 4,
                        "resource": {
                            "buffer": self._light_count_buf,
                            "offset": 0,
                            "size": self._light_count_buf.size,
                        },
                    },
                ],
            )

            # Clear light_count_grid before culling so stale counts don't persist
            encoder = device.create_command_encoder()
            encoder.clear_buffer(self._light_count_buf)
            encoder.clear_buffer(self._light_grid_buf)

            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_cull)
            cp.set_bind_group(0, bg)
            # Dispatch ceil(n_lights / 64) workgroups of size (64, 1, 1)
            wg_count = (n_lights + 63) // 64
            cp.dispatch_workgroups(wg_count, 1, 1)
            cp.end()
            device.queue.submit([encoder.finish()])

        except Exception as exc:
            print(f"[Cluster3DSystem] cull_lights failed: {exc}")

    def get_cluster_buffers(self) -> dict:
        """Return buffer handles for binding in the render pipeline.

        Returns: {'light_grid': buf, 'light_count_grid': buf, 'lights': buf}

        These map to group(2) in mesh_frag_clustered_pbr.wgsl:
          binding(0) — lights[]
          binding(1) — light_grid[]
          binding(2) — light_count_grid[]
        """
        self._ensure_resources()
        return {
            "lights":           self._light_buf,
            "light_grid":       self._light_grid_buf,
            "light_count_grid": self._light_count_buf,
        }

    def resize(self, width: int, height: int) -> None:
        """Notify the system that the framebuffer dimensions changed.

        Invalidates the current cluster AABBs — call build_clusters() again
        after resize to recompute them for the new aspect ratio.
        """
        if width == self._width and height == self._height:
            return
        self._width  = width
        self._height = height
        # AABBs are now stale; _ready stays True (buffers are reusable) but
        # the caller must invoke build_clusters() with the new projection.
