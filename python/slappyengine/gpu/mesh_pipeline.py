"""3D mesh render pipeline — lazy-loaded only when a 3D Layer is instantiated."""
from __future__ import annotations
from pathlib import Path
import wgpu

SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


class MeshPipeline:
    """wgpu render pipeline for 3D mesh rendering with PBR shading.

    Created once per GpuContext; shared across all 3D layers.
    Has its own depth texture (recreated if viewport size changes).

    Vertex layout (48 bytes/vertex, all in slot 0, step_mode=vertex):
        @location(0) position : vec3<f32>   offset  0  (12 bytes)
        @location(1) normal   : vec3<f32>   offset 12  (12 bytes)
        @location(2) uv       : vec2<f32>   offset 24  ( 8 bytes)
        @location(3) tangent  : vec4<f32>   offset 32  (16 bytes)
                                                  ----
                                            total  48 bytes

    Bind-group layout:
        group(0) binding(0) — MeshUniforms (model + view + proj + normal_matrix,
                               4 × mat4x4<f32> = 256 bytes)
        group(1) binding(0) — PBR material uniform (48 bytes, see PbrMaterial.to_gpu_bytes)
    """

    def __init__(self, device: wgpu.GPUDevice, output_format: str) -> None:
        self._device = device
        self._output_format = output_format
        self._pipeline: wgpu.GPURenderPipeline | None = None
        self._camera_bgl: wgpu.GPUBindGroupLayout | None = None
        self._material_bgl: wgpu.GPUBindGroupLayout | None = None
        self._depth_texture: wgpu.GPUTexture | None = None
        self._depth_view: wgpu.GPUTextureView | None = None
        self._width = 0
        self._height = 0
        self._build_pipeline()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pipeline(self) -> None:
        """Compile shaders and create the render pipeline."""
        device = self._device

        vert_src = (SHADER_DIR / "mesh_vert_3d.wgsl").read_text(encoding="utf-8")
        frag_src = (SHADER_DIR / "mesh_frag_pbr.wgsl").read_text(encoding="utf-8")

        vert_mod = device.create_shader_module(code=vert_src, label="mesh_vert_3d")
        frag_mod = device.create_shader_module(code=frag_src, label="mesh_frag_pbr")

        # --- Bind group layout 0: MeshUniforms uniform ---------------------------
        # model + view + proj + normal_matrix = 4 × mat4x4<f32> = 256 bytes
        self._camera_bgl = device.create_bind_group_layout(
            label="mesh_camera_bgl",
            entries=[
                {
                    "binding": 0,
                    "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
                    "buffer": {"type": wgpu.BufferBindingType.uniform},
                },
            ],
        )

        # --- Bind group layout 1: PBR material uniform ----------------------------
        # PbrMaterial.to_gpu_bytes() → 48-byte std430 struct
        self._material_bgl = device.create_bind_group_layout(
            label="mesh_material_bgl",
            entries=[
                {
                    "binding": 0,
                    "visibility": wgpu.ShaderStage.FRAGMENT,
                    "buffer": {"type": wgpu.BufferBindingType.uniform},
                },
            ],
        )

        pipeline_layout = device.create_pipeline_layout(
            bind_group_layouts=[self._camera_bgl, self._material_bgl],
            label="mesh_pipeline_layout",
        )

        # --- Vertex buffer layout -------------------------------------------------
        # Single interleaved slot: position(12) + normal(12) + uv(8) + tangent(16)
        vertex_layout = [
            {
                "array_stride": 48,
                "step_mode": wgpu.VertexStepMode.vertex,
                "attributes": [
                    # position : vec3<f32>
                    {
                        "shader_location": 0,
                        "offset": 0,
                        "format": wgpu.VertexFormat.float32x3,
                    },
                    # normal : vec3<f32>
                    {
                        "shader_location": 1,
                        "offset": 12,
                        "format": wgpu.VertexFormat.float32x3,
                    },
                    # uv : vec2<f32>
                    {
                        "shader_location": 2,
                        "offset": 24,
                        "format": wgpu.VertexFormat.float32x2,
                    },
                    # tangent : vec4<f32>
                    {
                        "shader_location": 3,
                        "offset": 32,
                        "format": wgpu.VertexFormat.float32x4,
                    },
                ],
            },
        ]

        # --- Render pipeline ------------------------------------------------------
        # Color target: opaque (no blend); compositor blends 3D over 2D layers.
        # Depth: depth24plus, compare=less, write=true.
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
                "targets": [
                    {
                        "format": self._output_format,
                        "blend": None,  # opaque; compositor handles blending
                    },
                ],
            },
            primitive={
                "topology": wgpu.PrimitiveTopology.triangle_list,
                "cull_mode": wgpu.CullMode.back,
                "front_face": wgpu.FrontFace.ccw,
            },
            depth_stencil={
                "format": "depth24plus",
                "depth_write_enabled": True,
                "depth_compare": wgpu.CompareFunction.less,
                "stencil_front": {
                    "compare": wgpu.CompareFunction.always,
                    "fail_op": wgpu.StencilOperation.keep,
                    "depth_fail_op": wgpu.StencilOperation.keep,
                    "pass_op": wgpu.StencilOperation.keep,
                },
                "stencil_back": {
                    "compare": wgpu.CompareFunction.always,
                    "fail_op": wgpu.StencilOperation.keep,
                    "depth_fail_op": wgpu.StencilOperation.keep,
                    "pass_op": wgpu.StencilOperation.keep,
                },
                "stencil_read_mask": 0xFFFFFFFF,
                "stencil_write_mask": 0xFFFFFFFF,
                "depth_bias": 0,
                "depth_bias_slope_scale": 0.0,
                "depth_bias_clamp": 0.0,
            },
            multisample={"count": 1, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            label="mesh_pipeline",
        )

    # ------------------------------------------------------------------
    # Depth texture management
    # ------------------------------------------------------------------

    def ensure_depth_texture(self, width: int, height: int) -> None:
        """Recreate depth texture if the viewport size changed.

        Call this at the start of each frame before encoding a render pass.
        """
        if width == self._width and height == self._height:
            return
        if self._depth_texture is not None:
            self._depth_texture.destroy()
        self._depth_texture = self._device.create_texture(
            size=(width, height, 1),
            format="depth24plus",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
            label="mesh_depth_texture",
        )
        self._depth_view = self._depth_texture.create_view()
        self._width, self._height = width, height

    # ------------------------------------------------------------------
    # Bind group factories
    # ------------------------------------------------------------------

    def make_camera_bind_group(self, camera_buf: wgpu.GPUBuffer) -> wgpu.GPUBindGroup:
        """Create a bind group for group(0) — camera uniform buffer."""
        return self._device.create_bind_group(
            layout=self._camera_bgl,
            entries=[{"binding": 0, "resource": {"buffer": camera_buf}}],
            label="mesh_camera_bg",
        )

    def make_material_bind_group(self, material_buf: wgpu.GPUBuffer) -> wgpu.GPUBindGroup:
        """Create a bind group for group(1) — PBR material uniform buffer."""
        return self._device.create_bind_group(
            layout=self._material_bgl,
            entries=[{"binding": 0, "resource": {"buffer": material_buf}}],
            label="mesh_material_bg",
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pipeline(self) -> wgpu.GPURenderPipeline:
        """The compiled wgpu render pipeline. Available after construction."""
        if self._pipeline is None:
            raise RuntimeError("MeshPipeline construction failed — pipeline is None")
        return self._pipeline

    @property
    def depth_view(self) -> wgpu.GPUTextureView:
        """The depth texture view for the current viewport size.

        Raises RuntimeError if ensure_depth_texture() has not been called.
        """
        if self._depth_view is None:
            raise RuntimeError(
                "MeshPipeline.ensure_depth_texture(width, height) must be called "
                "before accessing depth_view."
            )
        return self._depth_view

    @property
    def camera_bgl(self) -> wgpu.GPUBindGroupLayout:
        """Bind group layout for the camera uniform (group 0)."""
        return self._camera_bgl

    @property
    def material_bgl(self) -> wgpu.GPUBindGroupLayout:
        """Bind group layout for the PBR material uniform (group 1)."""
        return self._material_bgl
