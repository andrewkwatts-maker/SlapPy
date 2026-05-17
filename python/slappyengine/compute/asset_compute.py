from __future__ import annotations
from typing import TYPE_CHECKING, Any
import wgpu

from slappyengine.compute.stats import StatsCompute, StatsResult
from slappyengine.compute.spatial import SpatialCompute, AABB
from slappyengine.compute.mutator import PixelMutator
from slappyengine.compute.pipeline import ComputePass, ComputePipeline

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.struct_registry import StructRegistry
    from slappyengine.shader_gen import ShaderGen
    from slappyengine.tags import TagRegistry
    from slappyengine.layer import Layer
    from slappyengine.asset import Asset


class AssetComputeAPI:
    """Real implementation of per-asset compute dispatch.

    Instantiated by the engine after GPU init and bound to an Asset.
    """

    def __init__(self, asset: "Asset", ctx: "GPUContext",
                 registry: "StructRegistry", shader_gen: "ShaderGen",
                 tag_registry: "TagRegistry | None" = None,
                 buffer_manager: Any = None):
        self._asset = asset
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tags = tag_registry
        self._buf_mgr = buffer_manager

        self._pipeline_mgr = ComputePipeline(ctx, registry, shader_gen, tag_registry)
        self._stats = StatsCompute(ctx, registry, shader_gen, tag_registry)
        self._spatial = SpatialCompute(ctx, registry, shader_gen, tag_registry)

    def _get_layer_and_buf(self, layer_idx: int = 0) -> tuple["Layer", wgpu.GPUBuffer]:
        if not self._asset.layers:
            raise RuntimeError(f"Asset '{self._asset.name}' has no layers")
        layer = self._asset.layers[layer_idx]
        if self._buf_mgr is None:
            raise RuntimeError("BufferManager not attached — engine must call bind_buffer_manager()")
        buf = self._buf_mgr.get_pixel_buffer(layer)
        if buf is None:
            buf = self._buf_mgr.create_pixel_buffer(layer)
        return layer, buf

    def _pixel_count(self, layer_idx: int = 0) -> int:
        layer = self._asset.layers[layer_idx]
        if layer.size is None:
            return 0
        w, h = layer.size
        return w * h

    def _width(self, layer_idx: int = 0) -> int:
        layer = self._asset.layers[layer_idx]
        if layer.size is None:
            return 1
        return layer.size[0]

    async def sum_channel(self, channel: str,
                          filter_tag: str | None = None,
                          layer: int = 0) -> float:
        lyr, buf = self._get_layer_and_buf(layer)
        self._pipeline_mgr.bind_layer(lyr, buf)
        return await self._pipeline_mgr.sum_channel(channel, filter_tag, layer)

    async def stats(self, channel: str, ops: list[str],
                    filter_tag: str | None = None,
                    bounds: AABB | None = None,
                    hull: list | None = None) -> StatsResult:
        lyr, buf = self._get_layer_and_buf(0)
        n = self._pixel_count()
        return await self._stats.compute_stats(
            buf, n, channel, ops,
            filter_tag=filter_tag, bounds=bounds, hull=hull,
        )

    async def bounds(self, filter_tag: str | None = None,
                     filter_channel: str | None = None,
                     threshold: float = 0.0,
                     layer: int = 0) -> AABB:
        lyr, buf = self._get_layer_and_buf(layer)
        n = self._pixel_count(layer)
        w = self._width(layer)
        return await self._spatial.bounds(buf, n, w,
                                          filter_tag=filter_tag,
                                          filter_channel=filter_channel,
                                          threshold=threshold)

    async def convex_hull(self, filter_channel: str | None = None,
                          threshold: float = 0.0,
                          filter_tag: str | None = None,
                          layer: int = 0) -> list[tuple[float, float]]:
        lyr, buf = self._get_layer_and_buf(layer)
        n = self._pixel_count(layer)
        w = self._width(layer)
        return await self._spatial.convex_hull(buf, n, w,
                                               filter_channel=filter_channel,
                                               threshold=threshold,
                                               filter_tag=filter_tag)

    async def dispatch(self, compute_pass: ComputePass,
                       readback_channels: list[str] | None = None,
                       layer: int = 0) -> dict:
        lyr, buf = self._get_layer_and_buf(layer)
        self._pipeline_mgr.bind_layer(lyr, buf)
        return await self._pipeline_mgr.dispatch(compute_pass, readback_channels)


class PixelAPI:
    """Real implementation of bulk pixel mutation for an asset."""

    def __init__(self, asset: "Asset", ctx: "GPUContext",
                 registry: "StructRegistry", shader_gen: "ShaderGen",
                 tag_registry: "TagRegistry | None" = None,
                 buffer_manager: Any = None):
        self._asset = asset
        self._mutator = PixelMutator(ctx, registry, shader_gen, tag_registry)
        self._buf_mgr = buffer_manager

    def _bind(self, layer_idx: int = 0) -> None:
        layer = self._asset.layers[layer_idx]
        buf = self._buf_mgr.get_pixel_buffer(layer)
        if buf is None:
            buf = self._buf_mgr.create_pixel_buffer(layer)
        self._mutator.bind_layer(layer, buf)

    def set(self, *, filter_tag: str | None = None, channel: str, value: float,
            layer: int = 0) -> None:
        self._bind(layer)
        self._mutator.set(filter_tag=filter_tag, channel=channel, value=value)

    def multiply(self, *, filter_tag: str | None = None, channel: str, factor: float,
                 layer: int = 0) -> None:
        self._bind(layer)
        self._mutator.multiply(filter_tag=filter_tag, channel=channel, factor=factor)

    def add(self, *, filter_tag: str | None = None,
            filter_channel_gt: tuple[str, float] | None = None,
            filter_channel_lt: tuple[str, float] | None = None,
            channel: str, delta: float, clamp: bool = False,
            layer: int = 0) -> None:
        self._bind(layer)
        self._mutator.add(
            filter_tag=filter_tag,
            filter_channel_gt=filter_channel_gt,
            filter_channel_lt=filter_channel_lt,
            channel=channel, delta=delta, clamp=clamp,
        )

    def apply(self, *, filter, mutation, target_channel: str,
              layer: int = 0) -> None:
        from slappyengine.compute.ast_compiler import compile_apply_shader, ASTCompilerError
        from pathlib import Path

        _SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"
        template = self._mutator._shader_gen.inject_into_shader(
            (_SHADER_DIR / "pixel_apply_expr.wgsl").read_text(encoding="utf-8")
        )
        try:
            wgsl_src = compile_apply_shader(
                self._mutator._registry, filter, mutation, target_channel, template
            )
        except ASTCompilerError as e:
            raise ValueError(f"Lambda compilation failed: {e}") from e

        pass_ = ComputePass.from_source(wgsl_src, label="apply_expr")

        lyr_obj = self._asset.layers[layer]
        buf = self._buf_mgr.get_pixel_buffer(lyr_obj)
        if buf is None:
            buf = self._buf_mgr.create_pixel_buffer(lyr_obj)

        pipeline = ComputePipeline(
            self._mutator._ctx, self._mutator._registry,
            self._mutator._shader_gen, self._mutator._tags,
        )
        pipeline.bind_layer(lyr_obj, buf)

        import asyncio
        asyncio.get_event_loop().run_until_complete(pipeline.dispatch(pass_))
