"""Clustered 2D lighting pipeline — tile-based light culling for 100+ lights."""
from __future__ import annotations
from pathlib import Path
import numpy as np

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


class ClusterPipeline:
    """Wires the already-implemented lighting_cluster.wgsl into the render loop.

    Replaces the O(L) per-light loop in lighting.py for scenes with > 16 lights.

    Cluster grid: TILE_W × TILE_H pixel tiles (default 8×8).
    Two passes: cull_lights (assign lights to tiles), apply_cluster (shade per tile).
    """

    TILE_W = 8
    TILE_H = 8

    def __init__(self):
        self._gpu = None
        self._initialized = False
        self._width = 0
        self._height = 0
        self._tiles_x = 0
        self._tiles_y = 0
        # GPU resources
        self._cluster_lights_buf = None   # per-tile light index list
        self._cluster_count_buf = None    # per-tile light count
        self._cluster_indices_buf = None  # compact light indices
        self._cluster_uniforms_buf = None # dims + tile size
        self._pipeline_cull = None
        self._pipeline_apply = None

    def init_gpu(self, gpu, width: int, height: int) -> None:
        self._gpu = gpu
        self._width = width
        self._height = height
        self._tiles_x = (width + self.TILE_W - 1) // self.TILE_W
        self._tiles_y = (height + self.TILE_H - 1) // self.TILE_H

        shader_path = _SHADER_DIR / "lighting_cluster.wgsl"
        if not shader_path.exists():
            print(f"[ClusterPipeline] shader not found: {shader_path}")
            return

        try:
            import wgpu
            source = shader_path.read_text(encoding="utf-8")
            module = gpu.device.create_shader_module(code=source)

            n_tiles = self._tiles_x * self._tiles_y
            MAX_LIGHTS_PER_TILE = 64

            # Cluster storage buffers
            self._cluster_lights_buf = gpu.device.create_buffer(
                size=n_tiles * MAX_LIGHTS_PER_TILE * 4,  # u32 per light index
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )
            self._cluster_count_buf = gpu.device.create_buffer(
                size=n_tiles * 4,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )
            self._cluster_uniforms_buf = gpu.device.create_buffer(
                size=32,  # 4 × u32: width, height, tiles_x, tiles_y + tile_w, tile_h, max_lights, pad
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )

            # Write static uniforms
            uniforms = np.array([
                width, height, self._tiles_x, self._tiles_y,
                self.TILE_W, self.TILE_H, MAX_LIGHTS_PER_TILE, 0,
            ], dtype=np.uint32)
            gpu.device.queue.write_buffer(self._cluster_uniforms_buf, 0, uniforms)

            # Compile pipelines (two entry points in the same shader)
            try:
                self._pipeline_cull = gpu.device.create_compute_pipeline(
                    layout="auto",
                    compute={"module": module, "entry_point": "cull_lights"},
                )
            except Exception:
                pass
            try:
                self._pipeline_apply = gpu.device.create_compute_pipeline(
                    layout="auto",
                    compute={"module": module, "entry_point": "apply_cluster"},
                )
            except Exception:
                pass

            self._initialized = True
        except Exception as e:
            print(f"[ClusterPipeline] init_gpu failed: {e}")

    def cull_lights(self, encoder, light_buf, n_lights: int) -> None:
        """Pass 1: assign lights to tiles. Must run before apply_cluster."""
        if not self._initialized or self._pipeline_cull is None:
            return
        try:
            import wgpu
            # Reset counts
            encoder.clear_buffer(self._cluster_count_buf)
            bg = self._gpu.device.create_bind_group(
                layout=self._pipeline_cull.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": light_buf, "offset": 0, "size": light_buf.size}},
                    {"binding": 1, "resource": {"buffer": self._cluster_lights_buf, "offset": 0, "size": self._cluster_lights_buf.size}},
                    {"binding": 2, "resource": {"buffer": self._cluster_count_buf, "offset": 0, "size": self._cluster_count_buf.size}},
                    {"binding": 3, "resource": {"buffer": self._cluster_uniforms_buf, "offset": 0, "size": self._cluster_uniforms_buf.size}},
                ],
            )
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_cull)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(self._tiles_x, self._tiles_y)
            cp.end()
        except Exception:
            pass

    def apply_cluster(self, encoder, light_buf, scene_tex, output_tex) -> None:
        """Pass 2: shade each tile using its assigned lights."""
        if not self._initialized or self._pipeline_apply is None:
            return
        try:
            bg = self._gpu.device.create_bind_group(
                layout=self._pipeline_apply.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": light_buf, "offset": 0, "size": light_buf.size}},
                    {"binding": 1, "resource": {"buffer": self._cluster_lights_buf, "offset": 0, "size": self._cluster_lights_buf.size}},
                    {"binding": 2, "resource": {"buffer": self._cluster_count_buf, "offset": 0, "size": self._cluster_count_buf.size}},
                    {"binding": 3, "resource": {"buffer": self._cluster_uniforms_buf, "offset": 0, "size": self._cluster_uniforms_buf.size}},
                    {"binding": 4, "resource": scene_tex.create_view()},
                    {"binding": 5, "resource": output_tex.create_view()},
                ],
            )
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._pipeline_apply)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(self._tiles_x, self._tiles_y)
            cp.end()
        except Exception:
            pass
