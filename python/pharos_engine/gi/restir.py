"""ReSTIR GI — reservoir-based importance sampling for 1000+ SPP quality."""
from __future__ import annotations
from pathlib import Path
import numpy as np

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

# Reservoir struct: 8 × f32 = 32 bytes per pixel
# light_index(u32 as f32), weight_sum, W, M, sample_pos.x, sample_pos.y, sample_n.x, sample_n.y
_RESERVOIR_STRIDE = 32


class ReSTIRSystem:
    """4-pass ReSTIR GI: initial RIS → temporal reuse → spatial reuse → final shade."""

    def __init__(self, width: int = 0, height: int = 0, max_candidates: int = 32):
        self.width = width
        self.height = height
        self.max_candidates = max_candidates
        self._initialized = False
        self._gpu = None
        self._frame = 0

    def init_gpu(self, gpu, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._gpu = gpu
        try:
            import wgpu
            buf_size = width * height * _RESERVOIR_STRIDE
            # Ping-pong reservoir buffers
            self._res_a = gpu.device.create_buffer(
                size=buf_size,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
            )
            self._res_b = gpu.device.create_buffer(
                size=buf_size,
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
            )
            self._initialized = True
        except Exception as e:
            print(f"[ReSTIRSystem] GPU init failed: {e}")

    def dispatch(self, encoder, gbuffer_pos, gbuffer_normal, gbuffer_albedo,
                 light_buf, output_tex, frame_count: int = 0) -> None:
        """Dispatch 4 ReSTIR passes."""
        if not self._initialized:
            return
        curr_res = self._res_a if frame_count % 2 == 0 else self._res_b
        prev_res = self._res_b if frame_count % 2 == 0 else self._res_a
        self._pass_initial(encoder, gbuffer_pos, gbuffer_normal, gbuffer_albedo, light_buf, curr_res, frame_count)
        self._pass_temporal(encoder, curr_res, prev_res, gbuffer_pos, gbuffer_normal)
        self._pass_spatial(encoder, curr_res, gbuffer_pos, gbuffer_normal)
        self._pass_final(encoder, curr_res, gbuffer_pos, gbuffer_normal, gbuffer_albedo, light_buf, output_tex)

    def _run_pass(self, encoder, shader_name: str, bind_entries: list, wx: int, wy: int) -> None:
        shader_path = _SHADER_DIR / shader_name
        if not shader_path.exists():
            return
        try:
            import wgpu
            module = self._gpu.device.create_shader_module(
                code=shader_path.read_text(encoding="utf-8"))
            pipeline = self._gpu.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            bg = self._gpu.device.create_bind_group(
                layout=pipeline.get_bind_group_layout(0),
                entries=bind_entries,
            )
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wx, wy)
            cp.end()
        except Exception:
            pass

    def _pass_initial(self, encoder, pos, normal, albedo, lights, reservoirs, frame):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        self._run_pass(encoder, "restir_initial.wgsl", [
            {"binding": 0, "resource": pos.create_view()},
            {"binding": 1, "resource": normal.create_view()},
            {"binding": 2, "resource": albedo.create_view()},
            {"binding": 3, "resource": {"buffer": lights, "offset": 0, "size": lights.size}},
            {"binding": 4, "resource": {"buffer": reservoirs, "offset": 0, "size": reservoirs.size}},
        ], wx, wy)

    def _pass_temporal(self, encoder, curr, prev, pos, normal):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        self._run_pass(encoder, "restir_temporal.wgsl", [
            {"binding": 0, "resource": {"buffer": curr, "offset": 0, "size": curr.size}},
            {"binding": 1, "resource": {"buffer": prev, "offset": 0, "size": prev.size}},
            {"binding": 2, "resource": pos.create_view()},
            {"binding": 3, "resource": normal.create_view()},
        ], wx, wy)

    def _pass_spatial(self, encoder, reservoirs, pos, normal):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        self._run_pass(encoder, "restir_spatial.wgsl", [
            {"binding": 0, "resource": {"buffer": reservoirs, "offset": 0, "size": reservoirs.size}},
            {"binding": 1, "resource": pos.create_view()},
            {"binding": 2, "resource": normal.create_view()},
        ], wx, wy)

    def _pass_final(self, encoder, reservoirs, pos, normal, albedo, lights, output):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        self._run_pass(encoder, "restir_final.wgsl", [
            {"binding": 0, "resource": {"buffer": reservoirs, "offset": 0, "size": reservoirs.size}},
            {"binding": 1, "resource": pos.create_view()},
            {"binding": 2, "resource": normal.create_view()},
            {"binding": 3, "resource": albedo.create_view()},
            {"binding": 4, "resource": {"buffer": lights, "offset": 0, "size": lights.size}},
            {"binding": 5, "resource": output.create_view()},
        ], wx, wy)
