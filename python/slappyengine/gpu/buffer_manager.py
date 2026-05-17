from __future__ import annotations
import numpy as np
import struct
import wgpu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.struct_registry import StructRegistry
    from slappyengine.layer import Layer
    from slappyengine.material import MaterialMap
    from slappyengine.gpu.material_buffer import MaterialBuffer


class BufferManager:
    """Creates and manages GPU buffers: storage (pixel data), uniform (camera/params), vertex/index."""

    def __init__(self, ctx: "GPUContext", registry: "StructRegistry"):
        self._ctx = ctx
        self._registry = registry
        self._storage_cache: dict[int, wgpu.GPUBuffer] = {}  # id(layer) → buffer
        self._uniform_buffers: dict[str, wgpu.GPUBuffer] = {}
        self._material_buffer: "MaterialBuffer | None" = None

    # --- Storage buffers (pixel data) ---

    def create_pixel_buffer(self, layer: "Layer") -> wgpu.GPUBuffer:
        """Allocate and initialize a storage buffer for one layer's pixel data.

        Buffer size = width × height × stride_bytes. Each pixel is initialized
        to the StructRegistry's default values for each channel.
        """
        if layer.size is None:
            raise ValueError(f"Layer '{layer.name}' has no size — load image data first")

        w, h = layer.size
        stride = self._registry.stride_bytes()
        size_bytes = w * h * stride
        # Align to 16 bytes (wgpu minimum)
        size_bytes = (size_bytes + 15) & ~15

        # Build initial data: fill channels with their defaults
        data = self._build_default_pixel_data(w * h, stride)

        buf = self._ctx.device.create_buffer(
            size=size_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
            label=f"pixels:{layer.name}",
        )
        self._ctx.queue.write_buffer(buf, 0, data.tobytes())

        cached_buf = self._storage_cache.get(id(layer))
        if cached_buf is not None:
            cached_buf.destroy()
        self._storage_cache[id(layer)] = buf
        return buf

    def _build_default_pixel_data(self, pixel_count: int, stride: int) -> np.ndarray:
        """Return a flat byte array with per-channel defaults for pixel_count pixels."""
        channels = self._registry.channels
        layout = self._registry._compute_layout()

        # stride in floats/u32 units — treat all fields as f32 (u32 also 4 bytes)
        stride_floats = stride // 4
        arr = np.zeros(pixel_count * stride_floats, dtype=np.float32)

        for name, typ in channels:
            offset_bytes = layout[name]
            offset_idx = offset_bytes // 4
            default = self._registry.default_for_channel(name)
            # Set default for every pixel
            arr[offset_idx::stride_floats] = default

        return arr

    def get_pixel_buffer(self, layer: "Layer") -> wgpu.GPUBuffer | None:
        return self._storage_cache.get(id(layer))

    def release_pixel_buffer(self, layer: "Layer") -> None:
        buf = self._storage_cache.pop(id(layer), None)
        if buf is not None:
            buf.destroy()

    def update_pixel_buffer(self, layer: "Layer", data: np.ndarray) -> None:
        buf = self._storage_cache.get(id(layer))
        if buf is None:
            raise KeyError(f"No pixel buffer for layer '{layer.name}' — call create_pixel_buffer first")
        self._ctx.queue.write_buffer(buf, 0, data.tobytes())

    # --- Uniform buffers ---

    def create_uniform_buffer(self, name: str, size_bytes: int) -> wgpu.GPUBuffer:
        # Round up to 256 bytes (wgpu uniform alignment requirement)
        aligned = (size_bytes + 255) & ~255
        buf = self._ctx.device.create_buffer(
            size=aligned,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label=f"uniform:{name}",
        )
        self._uniform_buffers[name] = buf
        return buf

    def get_uniform_buffer(self, name: str) -> wgpu.GPUBuffer | None:
        return self._uniform_buffers.get(name)

    def update_uniform(self, name: str, data: bytes | np.ndarray) -> None:
        buf = self._uniform_buffers.get(name)
        if buf is None:
            raise KeyError(f"Uniform buffer '{name}' not found")
        raw = data if isinstance(data, (bytes, bytearray)) else data.tobytes()
        self._ctx.queue.write_buffer(buf, 0, raw)

    # --- Vertex/index buffers ---

    def create_quad_geometry(self) -> tuple[wgpu.GPUBuffer, wgpu.GPUBuffer]:
        """Unit quad: 4 vertices (pos + uv), 6 indices (2 triangles).

        Vertex layout: [x: f32, y: f32, u: f32, v: f32] = 16 bytes/vertex
        Vertices span [0,0] to [1,1] so the vertex shader can scale by entity size.
        """
        vertices = np.array([
            # x,   y,   u,   v
            [0.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 1.0, 0.0],
            [1.0, 1.0, 1.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
        ], dtype=np.float32)

        indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)

        vbuf = self._ctx.device.create_buffer(
            size=vertices.nbytes,
            usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST,
            label="quad:vertices",
        )
        ibuf = self._ctx.device.create_buffer(
            size=indices.nbytes,
            usage=wgpu.BufferUsage.INDEX | wgpu.BufferUsage.COPY_DST,
            label="quad:indices",
        )
        self._ctx.queue.write_buffer(vbuf, 0, vertices.tobytes())
        self._ctx.queue.write_buffer(ibuf, 0, indices.tobytes())
        return vbuf, ibuf

    # --- Material buffer ---

    def create_material_buffer(self, material_map: "MaterialMap") -> "MaterialBuffer":
        from slappyengine.gpu.material_buffer import MaterialBuffer
        self._material_buffer = MaterialBuffer(material_map, self._ctx)
        return self._material_buffer

    def get_material_buffer(self) -> "MaterialBuffer | None":
        return self._material_buffer

    def destroy_all(self) -> None:
        for buf in self._storage_cache.values():
            buf.destroy()
        for buf in self._uniform_buffers.values():
            buf.destroy()
        self._storage_cache.clear()
        self._uniform_buffers.clear()
