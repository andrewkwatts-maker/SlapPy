"""MeshRenderer — dispatches per-mesh draw calls for 3D-mode layers."""
from __future__ import annotations
from typing import TYPE_CHECKING
import struct

from slappyengine.gpu._validation import (
    validate_matrix16,
    validate_output_format,
    validate_positive_int,
)

if TYPE_CHECKING:
    import wgpu
    from slappyengine.gpu.context import GPUContext
    from slappyengine.gpu.mesh_pipeline import MeshPipeline
    from slappyengine.gpu.mesh import GpuMesh
    from slappyengine.gpu.pbr_material import PbrMaterial

# 4 mat4x4<f32> matrices × 64 bytes each = 256 bytes
# (model + view + proj + normal_matrix)
CAMERA_UB_SIZE = 256


class MeshRenderer:
    """Handles draw submission for a single 3D-mode Layer.

    One MeshRenderer per Layer(mode="3D"). The MeshPipeline is shared across
    all renderers and created once per GpuContext.

    Typical usage::

        renderer = MeshRenderer(gpu, pipeline)
        renderer.set_mesh(GpuMesh.unit_cube())
        renderer.set_material(PbrMaterial(metallic=0.0, roughness=0.5))
        renderer.update_camera(model, view, proj, normal_matrix)
        # Inside a render pass:
        renderer.draw(render_pass)
    """

    def __init__(self, gpu: "GPUContext", pipeline: "MeshPipeline") -> None:
        self._gpu = gpu
        self._pipeline = pipeline
        # Uniform buffers (allocated lazily on first write)
        self._camera_ub = None   # wgpu.GPUBuffer — 256 bytes: model+view+proj+normal
        self._material_ub = None  # wgpu.GPUBuffer — PbrMaterial uniform (48 bytes)
        # Bind groups (rebuilt whenever the underlying buffer changes)
        self._camera_bg = None   # wgpu.GPUBindGroup — group(0)
        self._material_bg = None  # wgpu.GPUBindGroup — group(1)
        self._mesh: "GpuMesh | None" = None
        self._material: "PbrMaterial | None" = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_mesh(self, mesh: "GpuMesh") -> None:
        """Upload mesh to GPU if needed and store reference.

        Calls :meth:`GpuMesh.upload` which is idempotent — safe to call
        multiple times with the same mesh.

        Raises
        ------
        TypeError
            If ``mesh`` is ``None``.
        """
        if mesh is None:
            raise TypeError("MeshRenderer.set_mesh: mesh must not be None")
        self._mesh = mesh
        mesh.upload(self._gpu.device)

    def set_material(self, material: "PbrMaterial") -> None:
        """Upload PBR material uniform buffer and (re)create bind group.

        Allocates the GPU buffer on the first call.  Subsequent calls with
        a different material reuse the same buffer and just overwrite its
        contents.
        """
        import wgpu  # noqa: PLC0415 — deferred to keep module importable without wgpu

        self._material = material
        data = material.to_gpu_bytes()

        if self._material_ub is None:
            self._material_ub = self._gpu.device.create_buffer(
                size=len(data),
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
                label="mesh_material_ub",
            )
        self._gpu.queue.write_buffer(self._material_ub, 0, data)
        self._material_bg = self._pipeline.make_material_bind_group(self._material_ub)

    def update_camera(
        self,
        model: list[float],         # 16 floats, column-major mat4x4
        view: list[float],          # 16 floats, column-major mat4x4
        proj: list[float],          # 16 floats, column-major mat4x4
        normal_matrix: list[float], # 16 floats — transpose(inverse(model))
    ) -> None:
        """Write camera/transform matrices to the camera uniform buffer.

        All four matrices are packed contiguously as 64 × f32 values
        (256 bytes) matching the ``MeshUniforms`` struct in the vertex shader.

        Allocates the GPU buffer on the first call.

        Raises
        ------
        TypeError
            If any matrix is not a sequence of finite floats.
        ValueError
            If any matrix length is not exactly 16.
        """
        import wgpu  # noqa: PLC0415

        model = validate_matrix16("model", "MeshRenderer.update_camera", model)
        view = validate_matrix16("view", "MeshRenderer.update_camera", view)
        proj = validate_matrix16("proj", "MeshRenderer.update_camera", proj)
        normal_matrix = validate_matrix16(
            "normal_matrix", "MeshRenderer.update_camera", normal_matrix,
        )
        data = struct.pack("64f", *model, *view, *proj, *normal_matrix)

        if self._camera_ub is None:
            self._camera_ub = self._gpu.device.create_buffer(
                size=CAMERA_UB_SIZE,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
                label="mesh_camera_ub",
            )
        self._gpu.queue.write_buffer(self._camera_ub, 0, data)
        self._camera_bg = self._pipeline.make_camera_bind_group(self._camera_ub)

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def draw(self, render_pass: "wgpu.GPURenderPassEncoder") -> None:
        """Record draw commands into an active render pass.

        A no-op if any required resource (mesh, camera bind group, or
        material bind group) is not yet set up.
        """
        if self._mesh is None or self._camera_bg is None or self._material_bg is None:
            return
        if self._mesh.vertex_buffer is None or self._mesh.index_buffer is None:
            return

        render_pass.set_pipeline(self._pipeline.pipeline)
        render_pass.set_bind_group(0, self._camera_bg)
        render_pass.set_bind_group(1, self._material_bg)
        render_pass.set_vertex_buffer(0, self._mesh.vertex_buffer)
        render_pass.set_index_buffer(self._mesh.index_buffer, "uint32")
        render_pass.draw_indexed(self._mesh.index_count)

    # ------------------------------------------------------------------
    # Offscreen render (for baking / thumbnails)
    # ------------------------------------------------------------------

    def render_to_texture(
        self,
        width: int,
        height: int,
        output_format: str = "rgba8unorm",
    ) -> "wgpu.GPUTexture":
        """Render this mesh to a new texture (used by Layer.bake_to_2d).

        Creates a temporary colour render target of the given *width* ×
        *height*, runs a single draw call, and returns the ``GPUTexture``.
        The caller is responsible for destroying the returned texture when
        it is no longer needed.

        :meth:`update_camera` and :meth:`set_mesh` / :meth:`set_material`
        must have been called before invoking this method.

        Raises
        ------
        TypeError
            If ``width`` / ``height`` are not plain ints or ``output_format``
            is not a non-empty str.
        ValueError
            If ``width`` or ``height`` is < 1.
        """
        import wgpu  # noqa: PLC0415

        width = validate_positive_int("width", "MeshRenderer.render_to_texture", width)
        height = validate_positive_int(
            "height", "MeshRenderer.render_to_texture", height,
        )
        output_format = validate_output_format(
            "output_format", "MeshRenderer.render_to_texture", output_format,
        )
        device = self._gpu.device

        color_tex = device.create_texture(
            size=(width, height, 1),
            format=output_format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
            label="mesh_render_to_texture_color",
        )
        color_view = color_tex.create_view()

        # Ensure depth texture matches the requested dimensions.
        self._pipeline.ensure_depth_texture(width, height)

        encoder = device.create_command_encoder(label="mesh_render_to_texture_enc")
        rp = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": color_view,
                    "resolve_target": None,
                    "load_op": "clear",
                    "store_op": "store",
                    "clear_value": (0.0, 0.0, 0.0, 0.0),
                }
            ],
            depth_stencil_attachment={
                "view": self._pipeline.depth_view,
                "depth_load_op": "clear",
                "depth_store_op": "discard",
                "depth_clear_value": 1.0,
                "stencil_load_op": "load",
                "stencil_store_op": "discard",
            },
        )
        try:
            self.draw(rp)
        finally:
            rp.end()

        self._gpu.queue.submit([encoder.finish()])
        return color_tex
