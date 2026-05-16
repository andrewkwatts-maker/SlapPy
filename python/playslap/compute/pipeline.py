from __future__ import annotations
import hashlib
import struct
from pathlib import Path
from typing import Any, TYPE_CHECKING
import numpy as np
import wgpu

from playslap.compute.readback import ReadbackBuffer

if TYPE_CHECKING:
    from playslap.gpu.context import GPUContext
    from playslap.struct_registry import StructRegistry
    from playslap.shader_gen import ShaderGen
    from playslap.layer import Layer
    from playslap.tags import TagRegistry

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


class ComputePass:
    def __init__(self, source: str, entry_point: str = "main", label: str = ""):
        self.source = source
        self.entry_point = entry_point
        self.label = label

    @classmethod
    def from_wgsl(cls, path: str | Path, entry_point: str = "main") -> "ComputePass":
        src = Path(path).read_text(encoding="utf-8")
        return cls(source=src, entry_point=entry_point, label=str(path))

    @classmethod
    def from_source(cls, source: str, entry_point: str = "main", label: str = "") -> "ComputePass":
        return cls(source=source, entry_point=entry_point, label=label)


class ComputePipeline:
    """Manages compute dispatch for an asset's storage buffers."""

    def __init__(self, ctx: "GPUContext", registry: "StructRegistry",
                 shader_gen: "ShaderGen", tag_registry: "TagRegistry | None" = None):
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tags = tag_registry
        self._pipeline_cache: dict[str, wgpu.GPUComputePipeline] = {}
        # Current layer being operated on — set by AssetComputeAPI
        self._layer: "Layer | None" = None
        self._pixel_buf: wgpu.GPUBuffer | None = None

    def bind_layer(self, layer: "Layer", pixel_buf: wgpu.GPUBuffer) -> None:
        self._layer = layer
        self._pixel_buf = pixel_buf

    def _compile(self, source: str, entry_point: str) -> wgpu.GPUComputePipeline:
        key = hashlib.sha256(source.encode()).hexdigest()
        if key not in self._pipeline_cache:
            module = self._ctx.device.create_shader_module(code=source)
            pipeline = self._ctx.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": entry_point},
            )
            self._pipeline_cache[key] = pipeline
        return self._pipeline_cache[key]

    def _inject_struct(self, template: str) -> str:
        return self._shader_gen.inject_into_shader(template)

    def _pixel_count(self) -> int:
        if self._layer is None or self._layer.size is None:
            return 0
        w, h = self._layer.size
        return w * h

    async def dispatch(self, pass_: "ComputePass",
                       readback_channels: list[str] | None = None) -> dict:
        if self._pixel_buf is None:
            raise RuntimeError("bind_layer() must be called before dispatch()")

        injected_src = self._inject_struct(pass_.source)
        pipeline = self._compile(injected_src, pass_.entry_point)

        encoder = self._ctx.create_encoder(f"compute:{pass_.label}")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, self._ctx.device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": {"buffer": self._pixel_buf}}],
        ))
        pixel_count = self._pixel_count()
        workgroup_size = 64
        n_groups = max(1, (pixel_count + workgroup_size - 1) // workgroup_size)
        cp.dispatch_workgroups(n_groups)
        cp.end()
        self._ctx.submit(encoder)

        result: dict = {}
        if readback_channels:
            stride = self._registry.stride_bytes()
            layout = self._registry._compute_layout()
            rb = ReadbackBuffer(self._ctx.device, self._pixel_buf.size)
            raw = await rb.read_from(self._pixel_buf, dtype=np.float32)
            rb.destroy()
            stride_floats = stride // 4
            for ch in readback_channels:
                if ch not in layout:
                    continue
                offset = layout[ch] // 4
                result[ch] = raw[offset::stride_floats].copy()
        return result

    async def sum_channel(self, channel: str,
                          filter_tag: str | None = None,
                          layer: int = 0) -> float:
        if self._pixel_buf is None:
            raise RuntimeError("bind_layer() must be called before sum_channel()")

        template = (_SHADER_DIR / "health_sum.wgsl").read_text(encoding="utf-8")
        src = self._inject_struct(template)
        pipeline = self._compile(src, "main")

        pixel_count = self._pixel_count()
        tag_mask = 0
        if filter_tag and self._tags and filter_tag in self._tags:
            tag_mask = self._tags[filter_tag]

        params_data = struct.pack("4I", pixel_count, tag_mask, 0, 0)
        params_buf = self._ctx.create_buffer(
            size=16, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._ctx.write_buffer(params_buf, np.frombuffer(params_data, dtype=np.uint8))

        result_buf = self._ctx.create_buffer(
            size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
        )
        # Clear result to 0
        self._ctx.write_buffer(result_buf, np.zeros(1, dtype=np.uint32))

        bgl = pipeline.get_bind_group_layout(0)
        bg = self._ctx.device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": self._pixel_buf}},
                {"binding": 1, "resource": {"buffer": params_buf,
                                             "offset": 0, "size": 16}},
                {"binding": 2, "resource": {"buffer": result_buf,
                                             "offset": 0, "size": 4}},
            ],
        )

        encoder = self._ctx.create_encoder("sum_channel")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        workgroup_size = 64
        n_groups = max(1, (pixel_count + workgroup_size - 1) // workgroup_size)
        cp.dispatch_workgroups(n_groups)
        cp.end()
        self._ctx.submit(encoder)

        rb = ReadbackBuffer(self._ctx.device, 4)
        raw = await rb.read_from(result_buf, dtype=np.uint32)
        rb.destroy()

        # Convert from fixed-point (×1000) back to float
        return float(raw[0]) / 1000.0
