from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pharos_engine.gpu.context import GPUContext
    from pharos_engine.struct_registry import StructRegistry
    from pharos_engine.shader_gen import ShaderGen
    from pharos_engine.tags import TagRegistry
    from pharos_engine.gpu.buffer_manager import BufferManager
    from pharos_engine.asset import Asset


class EffectShader:
    def __init__(self, wgsl: str, blend: str = "normal", label: str = "effect"):
        self.wgsl = wgsl
        self.blend = blend
        self.label = label
        self._pipeline = None


class EffectPipeline:
    def __init__(self, ctx: "GPUContext", registry: "StructRegistry",
                 shader_gen: "ShaderGen", tag_registry: "TagRegistry | None" = None):
        self._ctx = ctx
        self._registry = registry
        self._shader_gen = shader_gen
        self._tag_registry = tag_registry

    def dispatch_effects(self, asset: "Asset", buf_mgr: "BufferManager") -> None:
        from pharos_engine.compute.pipeline import ComputePass, ComputePipeline

        for effect in asset.effects:
            if effect.wgsl is None:
                continue
            for layer in asset.layers:
                buf = buf_mgr.get_pixel_buffer(layer)
                if buf is None:
                    continue
                pass_ = ComputePass.from_source(effect.wgsl, label=effect.label)
                pipeline = ComputePipeline(
                    self._ctx, self._registry, self._shader_gen, self._tag_registry
                )
                pipeline.bind_layer(layer, buf)
                asyncio.get_event_loop().run_until_complete(pipeline.dispatch(pass_))
