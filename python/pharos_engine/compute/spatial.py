from __future__ import annotations
import struct as _struct
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING
import numpy as np
import wgpu

from pharos_engine.compute.readback import ReadbackBuffer

if TYPE_CHECKING:
    from pharos_engine.gpu.context import GPUContext
    from pharos_engine.struct_registry import StructRegistry
    from pharos_engine.shader_gen import ShaderGen
    from pharos_engine.tags import TagRegistry

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


@dataclass
class AABB:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def width(self) -> float:
        return self.max_x - self.min_x

    def height(self) -> float:
        return self.max_y - self.min_y

    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y


class SpatialCompute:
    def __init__(self, ctx: "GPUContext", registry: "StructRegistry",
                 shader_gen: "ShaderGen", tag_registry: "TagRegistry | None" = None):
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tags = tag_registry
        self._bounds_pipeline: wgpu.GPUComputePipeline | None = None

    def _get_bounds_pipeline(self) -> wgpu.GPUComputePipeline:
        if self._bounds_pipeline is None:
            src = self._shader_gen.inject_into_shader(
                (_SHADER_DIR / "bounds_reduction.wgsl").read_text(encoding="utf-8")
            )
            module = self._ctx.device.create_shader_module(code=src)
            self._bounds_pipeline = self._ctx.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
        return self._bounds_pipeline

    async def bounds(self, pixel_buf: wgpu.GPUBuffer, pixel_count: int,
                     width: int, filter_tag: str | None = None,
                     filter_channel: str | None = None,
                     threshold: float = 0.0) -> AABB:
        layout = self._registry._compute_layout()
        stride_u32s = self._registry.stride_bytes() // 4
        tag_mask = 0
        if filter_tag and self._tags and filter_tag in self._tags:
            tag_mask = self._tags[filter_tag]

        ch_offset = 0
        use_threshold = 0
        if filter_channel and filter_channel in layout:
            ch_offset = layout[filter_channel] // 4
            use_threshold = 1

        params = _struct.pack(
            "3I I f I I I",
            pixel_count, tag_mask, stride_u32s, ch_offset,
            threshold, use_threshold, width, 0,
        )
        params_buf = self._ctx.create_buffer(
            size=len(params),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._ctx.write_buffer(params_buf, np.frombuffer(params, dtype=np.uint8))

        # Init bounds: min=large positive, max=0 (will be replaced by atomicMax of bit-cast)
        large_f32 = _struct.pack("f", 1e38)
        zero = _struct.pack("f", -1e38)
        init = np.array([
            np.frombuffer(large_f32, dtype=np.uint32)[0],
            np.frombuffer(large_f32, dtype=np.uint32)[0],
            np.frombuffer(zero,      dtype=np.uint32)[0],
            np.frombuffer(zero,      dtype=np.uint32)[0],
        ], dtype=np.uint32)

        out_buf = self._ctx.create_buffer(
            size=16,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
        )
        self._ctx.write_buffer(out_buf, init)

        pipeline = self._get_bounds_pipeline()
        bgl = pipeline.get_bind_group_layout(0)
        bg = self._ctx.device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": pixel_buf}},
                {"binding": 1, "resource": {"buffer": params_buf, "offset": 0, "size": len(params)}},
                {"binding": 2, "resource": {"buffer": out_buf, "offset": 0, "size": 16}},
            ],
        )
        encoder = self._ctx.create_encoder("bounds")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        cp.dispatch_workgroups(max(1, (pixel_count + 63) // 64))
        cp.end()
        self._ctx.submit(encoder)

        rb = ReadbackBuffer(self._ctx.device, 16)
        raw = await rb.read_from(out_buf, dtype=np.float32)
        rb.destroy()
        return AABB(min_x=float(raw[0]), min_y=float(raw[1]),
                    max_x=float(raw[2]), max_y=float(raw[3]))

    async def convex_hull(self, pixel_buf: wgpu.GPUBuffer, pixel_count: int,
                          width: int, filter_channel: str | None = None,
                          threshold: float = 0.0,
                          filter_tag: str | None = None) -> list[tuple[float, float]]:
        # Get AABB first to scope the point collection
        aabb = await self.bounds(pixel_buf, pixel_count, width,
                                 filter_tag=filter_tag,
                                 filter_channel=filter_channel,
                                 threshold=threshold)

        # Read back the full pixel buffer to CPU (only edge pixels needed)
        # For large assets, a GPU-side edge extraction pass would be better (M9 optimisation)
        rb = ReadbackBuffer(self._ctx.device, pixel_buf.size)
        raw = await rb.read_from(pixel_buf, dtype=np.float32)
        rb.destroy()

        layout = self._registry._compute_layout()
        stride_floats = self._registry.stride_bytes() // 4
        ch_offset = None
        if filter_channel and filter_channel in layout:
            ch_offset = layout[filter_channel] // 4
        tag_offset = layout.get("tag", None)
        if tag_offset is not None:
            tag_offset //= 4

        tag_mask = 0
        if filter_tag and self._tags and filter_tag in self._tags:
            tag_mask = self._tags[filter_tag]

        points = []
        for i in range(pixel_count):
            base = i * stride_floats
            if ch_offset is not None:
                val = raw[base + ch_offset]
                if val <= threshold:
                    continue
            if tag_mask and tag_offset is not None:
                tag = int(np.frombuffer(raw[base + tag_offset:base + tag_offset + 1].tobytes(),
                                       dtype=np.uint32)[0])
                if not (tag & tag_mask):
                    continue
            px = float(i % width)
            py = float(i // width)
            points.append((px, py))

        if not points:
            return []

        try:
            from pharos_engine import _core
            return _core.convex_hull(points)
        except ImportError:
            # Pure-Python fallback (slow, for testing only)
            return _python_convex_hull(points)


def _python_convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    pts = sorted(points)
    lower: list = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]

def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
