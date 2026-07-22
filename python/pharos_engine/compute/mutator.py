from __future__ import annotations
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any
import numpy as np
import wgpu

if TYPE_CHECKING:
    from pharos_engine.gpu.context import GPUContext
    from pharos_engine.struct_registry import StructRegistry
    from pharos_engine.shader_gen import ShaderGen
    from pharos_engine.tags import TagRegistry
    from pharos_engine.layer import Layer

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

_FILTER_OP_TAG  = 0
_FILTER_OP_GT   = 1
_FILTER_OP_LT   = 2
_FILTER_OP_EQ   = 3


class PixelMutator:
    """GPU-accelerated bulk pixel mutation using parameterized WGSL templates.

    Each operation (set/multiply/add) compiles a shader template once and
    re-dispatches with different uniform params on subsequent calls.
    """

    def __init__(self, ctx: "GPUContext", registry: "StructRegistry",
                 shader_gen: "ShaderGen", tag_registry: "TagRegistry | None" = None):
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tags = tag_registry
        self._pipeline_cache: dict[str, wgpu.GPUComputePipeline] = {}
        self._layer: "Layer | None" = None
        self._pixel_buf: wgpu.GPUBuffer | None = None

    def bind_layer(self, layer: "Layer", pixel_buf: wgpu.GPUBuffer) -> None:
        self._layer = layer
        self._pixel_buf = pixel_buf

    def _pixel_count(self) -> int:
        if self._layer is None or self._layer.size is None:
            return 0
        w, h = self._layer.size
        return w * h

    def _get_pipeline(self, shader_name: str) -> wgpu.GPUComputePipeline:
        if shader_name not in self._pipeline_cache:
            src = self._shader_gen.inject_into_shader(
                (_SHADER_DIR / shader_name).read_text(encoding="utf-8")
            )
            module = self._ctx.device.create_shader_module(code=src)
            pipeline = self._ctx.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            self._pipeline_cache[shader_name] = pipeline
        return self._pipeline_cache[shader_name]

    def _resolve_tag_mask(self, filter_tag: str | None) -> int:
        if not filter_tag:
            return 0
        if self._tags and filter_tag in self._tags:
            return self._tags[filter_tag]
        return 0

    def _resolve_channel(self, channel: str) -> int:
        layout = self._registry._compute_layout()
        if channel not in layout:
            raise KeyError(f"Channel '{channel}' not registered in StructRegistry")
        return layout[channel] // 4  # u32 offset

    def _make_params_buf(self, pixel_count: int, tag_mask: int,
                         stride_u32s: int, channel_offset: int,
                         value: float, filter_op: int = 0,
                         filter_ch_off: int = 0, filter_value: float = 0.0,
                         extra_u32s: tuple[int, ...] = ()) -> wgpu.GPUBuffer:
        base = struct.pack(
            "3I I f I I f",
            pixel_count, tag_mask, stride_u32s, channel_offset,
            value, filter_op, filter_ch_off, filter_value,
        )
        extra = struct.pack(f"{len(extra_u32s)}I", *extra_u32s) if extra_u32s else b""
        data = base + extra
        # Round up to 16 bytes
        if len(data) % 16:
            data += b"\x00" * (16 - len(data) % 16)
        buf = self._ctx.create_buffer(
            size=len(data),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._ctx.write_buffer(buf, np.frombuffer(data, dtype=np.uint8))
        return buf

    def _dispatch(self, pipeline: wgpu.GPUComputePipeline,
                  params_buf: wgpu.GPUBuffer, params_size: int) -> None:
        if self._pixel_buf is None:
            raise RuntimeError("bind_layer() must be called before mutation")
        bgl = pipeline.get_bind_group_layout(0)
        bg = self._ctx.device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": self._pixel_buf}},
                {"binding": 1, "resource": {"buffer": params_buf,
                                             "offset": 0, "size": params_size}},
            ],
        )
        encoder = self._ctx.create_encoder("pixel_mutate")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        n = self._pixel_count()
        cp.dispatch_workgroups(max(1, (n + 63) // 64))
        cp.end()
        self._ctx.submit(encoder)

    def set(self, *, filter_tag: str | None = None, channel: str, value: float) -> None:
        n = self._pixel_count()
        if not n:
            return
        tag_mask = self._resolve_tag_mask(filter_tag)
        ch_off = self._resolve_channel(channel)
        stride = self._registry.stride_bytes() // 4
        params_buf = self._make_params_buf(n, tag_mask, stride, ch_off, value)
        pipeline = self._get_pipeline("pixel_set.wgsl")
        self._dispatch(pipeline, params_buf, 32)

    def multiply(self, *, filter_tag: str | None = None, channel: str, factor: float) -> None:
        n = self._pixel_count()
        if not n:
            return
        tag_mask = self._resolve_tag_mask(filter_tag)
        ch_off = self._resolve_channel(channel)
        stride = self._registry.stride_bytes() // 4
        params_buf = self._make_params_buf(n, tag_mask, stride, ch_off, factor)
        pipeline = self._get_pipeline("pixel_multiply.wgsl")
        self._dispatch(pipeline, params_buf, 32)

    def add(self, *, filter_tag: str | None = None,
            filter_channel_gt: tuple[str, float] | None = None,
            filter_channel_lt: tuple[str, float] | None = None,
            channel: str, delta: float, clamp: bool = False) -> None:
        n = self._pixel_count()
        if not n:
            return
        tag_mask = self._resolve_tag_mask(filter_tag)
        ch_off = self._resolve_channel(channel)
        stride = self._registry.stride_bytes() // 4

        filter_op = _FILTER_OP_TAG
        filter_ch_off = 0
        filter_val = 0.0
        if filter_channel_gt:
            filter_op = _FILTER_OP_GT
            filter_ch_off = self._resolve_channel(filter_channel_gt[0])
            filter_val = filter_channel_gt[1]
        elif filter_channel_lt:
            filter_op = _FILTER_OP_LT
            filter_ch_off = self._resolve_channel(filter_channel_lt[0])
            filter_val = filter_channel_lt[1]

        clamp_u32 = 1 if clamp else 0
        params_buf = self._make_params_buf(
            n, tag_mask, stride, ch_off, delta,
            filter_op, filter_ch_off, filter_val,
            extra_u32s=(clamp_u32, 0, 0, 0),
        )
        pipeline = self._get_pipeline("pixel_add.wgsl")
        self._dispatch(pipeline, params_buf, 48)
