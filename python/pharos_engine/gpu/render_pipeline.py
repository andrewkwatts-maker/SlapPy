from __future__ import annotations
from pathlib import Path
import wgpu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pharos_engine.gpu.context import GPUContext

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


def _load_shader(name: str) -> str:
    return (_SHADER_DIR / name).read_text(encoding="utf-8")


class RenderPipeline:
    """Encapsulates the wgpu render pipeline for drawing entity quads."""

    def __init__(self, ctx: "GPUContext"):
        self._ctx = ctx
        self._pipeline: wgpu.GPURenderPipeline | None = None
        self._pipeline_array: wgpu.GPURenderPipeline | None = None
        self._camera_bgl: wgpu.GPUBindGroupLayout | None = None
        self._texture_bgl: wgpu.GPUBindGroupLayout | None = None

    def build(self) -> None:
        """Compile shaders and create the render pipeline. Call once after GPUContext.initialize()."""
        device = self._ctx.device

        vert_src = _load_shader("quad_vert.wgsl")
        frag_src = _load_shader("quad_frag.wgsl")
        frag_array_src = _load_shader("quad_frag_array.wgsl")

        vert_mod = device.create_shader_module(code=vert_src, label="quad_vert")
        frag_mod = device.create_shader_module(code=frag_src, label="quad_frag")
        frag_array_mod = device.create_shader_module(code=frag_array_src, label="quad_frag_array")

        # Bind group layout 0: Camera uniform
        self._camera_bgl = device.create_bind_group_layout(
            label="camera_bgl",
            entries=[{
                "binding": 0,
                "visibility": wgpu.ShaderStage.VERTEX,
                "buffer": {"type": wgpu.BufferBindingType.uniform},
            }],
        )

        # Bind group layout 1: texture_2d + sampler
        self._texture_bgl = device.create_bind_group_layout(
            label="texture_bgl",
            entries=[
                {
                    "binding": 0,
                    "visibility": wgpu.ShaderStage.FRAGMENT,
                    "texture": {
                        "sample_type": wgpu.TextureSampleType.float,
                        "view_dimension": wgpu.TextureViewDimension.d2,
                    },
                },
                {
                    "binding": 1,
                    "visibility": wgpu.ShaderStage.FRAGMENT,
                    "sampler": {"type": wgpu.SamplerBindingType.filtering},
                },
            ],
        )

        pipeline_layout = device.create_pipeline_layout(
            bind_group_layouts=[self._camera_bgl, self._texture_bgl],
            label="entity_layout",
        )

        # Vertex buffer layout: positions + UVs (slot 0) + instance data (slot 1)
        vertex_layout = [
            {   # slot 0: per-vertex
                "array_stride": 16,
                "step_mode": wgpu.VertexStepMode.vertex,
                "attributes": [
                    {"shader_location": 0, "offset": 0,  "format": wgpu.VertexFormat.float32x2},
                    {"shader_location": 1, "offset": 8,  "format": wgpu.VertexFormat.float32x2},
                ],
            },
            {   # slot 1: per-instance (world_pos, world_size, opacity, frame, _pad, _pad)
                "array_stride": 32,
                "step_mode": wgpu.VertexStepMode.instance,
                "attributes": [
                    {"shader_location": 2, "offset": 0,  "format": wgpu.VertexFormat.float32x2},
                    {"shader_location": 3, "offset": 8,  "format": wgpu.VertexFormat.float32x2},
                    {"shader_location": 4, "offset": 16, "format": wgpu.VertexFormat.float32},
                    {"shader_location": 5, "offset": 20, "format": wgpu.VertexFormat.float32},
                    {"shader_location": 6, "offset": 24, "format": wgpu.VertexFormat.float32},
                    {"shader_location": 7, "offset": 28, "format": wgpu.VertexFormat.float32},
                ],
            },
        ]

        blend = {
            "color": {
                "src_factor": wgpu.BlendFactor.src_alpha,
                "dst_factor": wgpu.BlendFactor.one_minus_src_alpha,
                "operation": wgpu.BlendOperation.add,
            },
            "alpha": {
                "src_factor": wgpu.BlendFactor.one,
                "dst_factor": wgpu.BlendFactor.one_minus_src_alpha,
                "operation": wgpu.BlendOperation.add,
            },
        }

        self._pipeline = device.create_render_pipeline(
            layout=pipeline_layout,
            vertex={
                "module": vert_mod,
                "entry_point": "vs_main",
                "buffers": vertex_layout,
            },
            fragment={
                "module": frag_mod,
                "entry_point": "fs_main",
                "targets": [{
                    "format": self._ctx.surface_format,
                    "blend": blend,
                }],
            },
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list},
            depth_stencil=None,
            multisample={"count": 1},
            label="entity_pipeline",
        )

    def make_camera_bind_group(self, camera_buf: wgpu.GPUBuffer) -> wgpu.GPUBindGroup:
        return self._ctx.device.create_bind_group(
            layout=self._camera_bgl,
            entries=[{"binding": 0, "resource": {"buffer": camera_buf}}],
            label="camera_bg",
        )

    def make_texture_bind_group(self, view: wgpu.GPUTextureView,
                                sampler: wgpu.GPUSampler) -> wgpu.GPUBindGroup:
        return self._ctx.device.create_bind_group(
            layout=self._texture_bgl,
            entries=[
                {"binding": 0, "resource": view},
                {"binding": 1, "resource": sampler},
            ],
            label="texture_bg",
        )

    @property
    def pipeline(self) -> wgpu.GPURenderPipeline:
        if self._pipeline is None:
            raise RuntimeError("RenderPipeline.build() has not been called")
        return self._pipeline
