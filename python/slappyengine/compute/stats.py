from __future__ import annotations
import struct
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
import numpy as np
import wgpu

from slappyengine.compute.readback import ReadbackBuffer

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.struct_registry import StructRegistry
    from slappyengine.shader_gen import ShaderGen
    from slappyengine.tags import TagRegistry

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

@dataclass
class StatsResult:
    mean: float = 0.0
    sum: float = 0.0
    min: float = 0.0
    max: float = 0.0
    count: int = 0
    std: float = 0.0
    mode: float = 0.0
    requested_ops: list[str] = field(default_factory=list)


class StatsCompute:
    """Dispatches GPU stats reduction shaders and returns StatsResult."""

    def __init__(self, ctx: "GPUContext", registry: "StructRegistry",
                 shader_gen: "ShaderGen", tag_registry: "TagRegistry | None" = None):
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tags = tag_registry
        self._pipeline_cache: dict[str, wgpu.GPUComputePipeline] = {}

    def _compile(self, template_name: str) -> wgpu.GPUComputePipeline:
        if template_name not in self._pipeline_cache:
            src = self._shader_gen.inject_into_shader(
                (_SHADER_DIR / template_name).read_text(encoding="utf-8")
            )
            module = self._ctx.device.create_shader_module(code=src)
            pipeline = self._ctx.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            self._pipeline_cache[template_name] = pipeline
        return self._pipeline_cache[template_name]

    async def compute_stats(
        self, pixel_buf: wgpu.GPUBuffer, pixel_count: int,
        channel: str, ops: list[str],
        filter_tag: str | None = None,
        bounds=None,         # AABB or None
        hull=None,
    ) -> StatsResult:
        layout = self._registry._compute_layout()
        if channel not in layout:
            raise KeyError(f"Channel '{channel}' not in struct registry")

        ch_offset_u32 = layout[channel] // 4
        stride_u32s = self._registry.stride_bytes() // 4
        tag_mask = 0
        if filter_tag and self._tags and filter_tag in self._tags:
            tag_mask = self._tags[filter_tag]

        # Bounds
        min_x = min_y = max_x = max_y = 0.0
        width = 1
        if bounds is not None:
            min_x, min_y, max_x, max_y = bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y
            # width must be passed — we approximate from pixel_count sqrt
            import math
            width = int(math.sqrt(pixel_count))

        params_data = struct.pack(
            "4I4f2I2I",
            pixel_count, ch_offset_u32, tag_mask, stride_u32s,
            min_x, min_y, max_x, max_y,
            width, 0, 0, 0,
        )
        params_buf = self._ctx.create_buffer(
            size=len(params_data),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._ctx.write_buffer(params_buf, np.frombuffer(params_data, dtype=np.uint8))

        out_sum = self._ctx.create_buffer(size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST)
        out_min = self._ctx.create_buffer(size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST)
        out_max = self._ctx.create_buffer(size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST)
        out_count = self._ctx.create_buffer(size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST)

        # Init min to large positive, max to large negative via u32 bit-cast
        import struct as st
        large = st.pack("f", 1e38)
        neg_large = st.pack("f", -1e38)
        self._ctx.write_buffer(out_sum,   np.zeros(1, dtype=np.uint32))
        self._ctx.write_buffer(out_min,   np.frombuffer(large, dtype=np.uint8))
        self._ctx.write_buffer(out_max,   np.frombuffer(neg_large, dtype=np.uint8))
        self._ctx.write_buffer(out_count, np.zeros(1, dtype=np.uint32))

        pipeline = self._compile("stats_reduction.wgsl")
        bgl = pipeline.get_bind_group_layout(0)
        bg = self._ctx.device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": pixel_buf}},
                {"binding": 1, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_data)}},
                {"binding": 2, "resource": {"buffer": out_sum,   "offset": 0, "size": 4}},
                {"binding": 3, "resource": {"buffer": out_min,   "offset": 0, "size": 4}},
                {"binding": 4, "resource": {"buffer": out_max,   "offset": 0, "size": 4}},
                {"binding": 5, "resource": {"buffer": out_count, "offset": 0, "size": 4}},
            ],
        )

        encoder = self._ctx.create_encoder("stats")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        wg = 64
        cp.dispatch_workgroups(max(1, (pixel_count + wg - 1) // wg))
        cp.end()
        self._ctx.submit(encoder)

        # Readback all four results
        rb_sum   = ReadbackBuffer(self._ctx.device, 4)
        rb_min   = ReadbackBuffer(self._ctx.device, 4)
        rb_max   = ReadbackBuffer(self._ctx.device, 4)
        rb_count = ReadbackBuffer(self._ctx.device, 4)

        raw_sum, raw_min, raw_max, raw_count = await asyncio.gather(
            rb_sum.read_from(out_sum,   dtype=np.uint32),
            rb_min.read_from(out_min,   dtype=np.float32),
            rb_max.read_from(out_max,   dtype=np.float32),
            rb_count.read_from(out_count, dtype=np.uint32),
        )
        for rb in (rb_sum, rb_min, rb_max, rb_count):
            rb.destroy()

        total_sum   = float(raw_sum[0]) / 1000.0
        total_min   = float(raw_min[0])
        total_max   = float(raw_max[0])
        total_count = int(raw_count[0])
        mean = total_sum / total_count if total_count > 0 else 0.0

        result = StatsResult(
            mean=mean, sum=total_sum, min=total_min,
            max=total_max, count=total_count,
            requested_ops=ops,
        )
        return result
