from __future__ import annotations
import math
import numpy as np
import wgpu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.gpu.texture_manager import TextureManager
    from slappyengine.gpu.buffer_manager import BufferManager
    from slappyengine.gpu.render_pipeline import RenderPipeline
    from slappyengine.scene import Scene
    from slappyengine.render_target import RenderTarget
    from slappyengine.camera import Camera


class EntityRenderer:
    """Renders all visible RenderTarget entities in the scene, sorted by z_order."""

    def __init__(self, ctx: "GPUContext", texture_mgr: "TextureManager",
                 buffer_mgr: "BufferManager", pipeline: "RenderPipeline"):
        self._ctx = ctx
        self._tex = texture_mgr
        self._buf = buffer_mgr
        self._pipeline = pipeline

        self._vbuf: wgpu.GPUBuffer | None = None
        self._ibuf: wgpu.GPUBuffer | None = None
        self._camera_buf: wgpu.GPUBuffer | None = None
        self._camera_bg: wgpu.GPUBindGroup | None = None
        self._sampler: wgpu.GPUSampler | None = None

    def initialize(self) -> None:
        """Create shared GPU resources (quad geometry, camera uniform, sampler)."""
        self._vbuf, self._ibuf = self._buf.create_quad_geometry()
        # Camera uniform: 4×4 float32 matrix = 64 bytes
        self._camera_buf = self._buf.create_uniform_buffer("camera", 64)
        self._camera_bg = self._pipeline.make_camera_bind_group(self._camera_buf)
        self._sampler = self._tex.create_sampler("nearest")

    def update_camera(self, camera: "Camera") -> None:
        """Upload the camera view-projection matrix to the uniform buffer."""
        mat = np.array(camera.view_matrix(), dtype=np.float32)
        self._buf.update_uniform("camera", mat.tobytes())

    def render(self, scene: "Scene", pass_enc: wgpu.GPURenderPassEncoder) -> None:
        """Issue all entity draw calls into an already-begun render pass."""
        from slappyengine.render_target import RenderTarget

        # Collect visible entities sorted by z_order
        entities = [
            e for e in scene.entities
            if isinstance(e, RenderTarget) and e.visible and e.layers
        ]
        entities.sort(key=lambda e: e.z_order)

        pass_enc.set_pipeline(self._pipeline.pipeline)
        pass_enc.set_bind_group(0, self._camera_bg)
        pass_enc.set_index_buffer(self._ibuf, wgpu.IndexFormat.uint16)
        pass_enc.set_vertex_buffer(0, self._vbuf)

        for entity in entities:
            self._draw_entity(entity, pass_enc)

        # Draw landscape tiles
        if hasattr(scene, 'landscape') and scene.landscape is not None:
            for tile in scene.landscape.visible_tiles:
                if tile.visible and tile.layers:
                    self._draw_entity(tile, pass_enc)

    def _draw_entity(self, entity: "RenderTarget",
                     pass_enc: wgpu.GPURenderPassEncoder) -> None:
        from slappyengine.cube_array import CubeArray

        is_anim = isinstance(entity, CubeArray)
        frame = float(entity.current_frame) if is_anim else 0.0

        # Get camera position for parallax calculation
        cam_x, cam_y = 0.0, 0.0
        if hasattr(entity, '_scene') and entity._scene is not None:
            cam = getattr(entity._scene, 'camera', None)
            if cam is not None:
                cam_x, cam_y = cam.position[0], cam.position[1]

        # Apply parallax if entity has a z_layer
        px_x, px_y = entity.position
        z_layer = getattr(entity, 'z_layer', None)
        if z_layer is not None:
            offset_x = (px_x - cam_x) * (z_layer.parallax_x - 1.0)
            offset_y = (px_y - cam_y) * (z_layer.parallax_y - 1.0)
            px_x += offset_x
            px_y += offset_y

        x, y = px_x, px_y
        w, h = entity.size

        # Apply angle-sprite blend if entity has an angle map
        if hasattr(entity, '_angle_map') and entity._angle_map is not None:
            state = getattr(entity, '_angle_sprite_state', "")
            entity._angle_map.apply(entity, state_tag=state)

        if is_anim:
            if entity.layers and 0 <= entity.current_frame < len(entity.layers):
                layers_to_draw = [entity.layers[entity.current_frame]]
            else:
                return
        else:
            # Exclude 3D-mode layers — they are handled by Engine._draw_3d_layer_to_texture.
            # getattr default "2D" keeps backward compatibility with Layer objects
            # that predate the mode attribute.
            layers_to_draw = [
                l for l in entity.layers
                if l.visible and getattr(l, "mode", "2D") == "2D"
            ]

        for layer in layers_to_draw:

            # Ensure layer texture is uploaded
            texture = self._tex.upload_layer(layer)
            view = self._tex.create_view(texture)

            # Bind group for this layer's texture
            tex_bg = self._pipeline.make_texture_bind_group(view, self._sampler)
            pass_enc.set_bind_group(1, tex_bg)

            # Instance data: world_pos, world_size, opacity, frame, rotation_rad, scale
            rotation_rad = math.radians(getattr(entity, "rotation", 0.0))
            scale = float(getattr(entity, "scale", 1.0))
            inst = np.array([x, y, float(w), float(h),
                             layer.opacity, frame, rotation_rad, scale], dtype=np.float32)
            inst_buf = self._ctx.device.create_buffer(
                size=inst.nbytes,
                usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST,
                label=f"inst:{entity.name}:{layer.name}",
            )
            self._ctx.device.queue.write_buffer(inst_buf, 0, inst)

            pass_enc.set_vertex_buffer(1, inst_buf)
            pass_enc.draw_indexed(6, 1, 0, 0, 0)
