from __future__ import annotations
import numpy as np
import wgpu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.layer import Layer
    from slappyengine.cube_array import CubeArray

class TextureManager:
    """Creates and manages wgpu textures for entity layers."""

    def __init__(self, ctx: "GPUContext"):
        self._ctx = ctx
        self._texture_cache: dict[int, wgpu.GPUTexture] = {}  # id(layer) → texture
        self._array_cache: dict[tuple, wgpu.GPUTexture] = {}  # ("array", id(cube_array)) → texture

    def upload_layer(self, layer: "Layer") -> wgpu.GPUTexture:
        """Upload layer._image_data to a GPU texture (RGBA8, 2D). Cached by identity."""
        cached = self._texture_cache.get(id(layer))
        if cached is not None:
            return cached

        if layer._image_data is None:
            layer._image_data = np.zeros((1, 1, 4), dtype=np.uint8)

        img = np.ascontiguousarray(layer._image_data, dtype=np.uint8)
        h, w = img.shape[:2]

        texture = self._ctx.device.create_texture(
            size=(w, h, 1),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            label=f"layer:{layer.name}",
        )
        self._ctx.queue.write_texture(
            {"texture": texture, "mip_level": 0, "origin": (0, 0, 0)},
            img.tobytes(),
            {"bytes_per_row": w * 4, "rows_per_image": h},
            (w, h, 1),
        )
        self._texture_cache[id(layer)] = texture
        return texture

    def upload_frame_array(self, layer: "Layer", frame_count: int,
                           frame_data: list[np.ndarray]) -> wgpu.GPUTexture:
        """Upload an animation frame array as a Texture2DArray. array_layer_count = frame_count."""
        if not frame_data:
            return self.upload_layer(layer)

        h, w = frame_data[0].shape[:2]
        texture = self._ctx.device.create_texture(
            size=(w, h, frame_count),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            dimension=wgpu.TextureDimension.d2,
            label=f"frames:{layer.name}",
        )
        for i, frame in enumerate(frame_data):
            arr = np.ascontiguousarray(frame, dtype=np.uint8)
            self._ctx.queue.write_texture(
                {"texture": texture, "mip_level": 0, "origin": (0, 0, i)},
                arr.tobytes(),
                {"bytes_per_row": w * 4, "rows_per_image": h},
                (w, h, 1),
            )
        self._texture_cache[id(layer)] = texture
        return texture

    def upload_layer_array(self, cube_array: "CubeArray") -> wgpu.GPUTexture:
        """Upload all CubeArray frames as a single Texture2DArray. Cached by cube_array id."""
        cache_key = ("array", id(cube_array))
        frame_count = cube_array.frame_count

        cached = self._array_cache.get(cache_key)
        if cached is not None:
            # Invalidate if the texture depth no longer matches the current frame count.
            if cached.size[2] == frame_count:
                return cached
            cached.destroy()

        W, H = cube_array.size

        texture = self._ctx.device.create_texture(
            size=(W, H, frame_count),
            format=wgpu.TextureFormat.rgba8unorm,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            dimension=wgpu.TextureDimension.d2,
            mip_level_count=1,
            sample_count=1,
            label=f"array:{cube_array.name}",
        )

        for i, layer in enumerate(cube_array.layers[:frame_count]):
            if layer._image_data is None:
                img = np.zeros((H, W, 4), dtype=np.uint8)
            else:
                img = np.ascontiguousarray(layer._image_data, dtype=np.uint8)
            self._ctx.device.queue.write_texture(
                {"texture": texture, "mip_level": 0, "origin": (0, 0, i)},
                img.tobytes(),
                {"offset": 0, "bytes_per_row": W * 4, "rows_per_image": H},
                (W, H, 1),
            )

        self._array_cache[cache_key] = texture
        return texture

    def create_array_view(self, texture: wgpu.GPUTexture) -> wgpu.GPUTextureView:
        """Return a 2d-array view of a Texture2DArray."""
        return texture.create_view(dimension=wgpu.TextureViewDimension.d2_array)

    def invalidate_array(self, cube_array: "CubeArray") -> None:
        """Remove the cached Texture2DArray for the given CubeArray."""
        self._array_cache.pop(("array", id(cube_array)), None)

    def create_view(self, texture: wgpu.GPUTexture,
                    dimension: str = "2d") -> wgpu.GPUTextureView:
        dim_map = {
            "2d": wgpu.TextureViewDimension.d2,
            "2d-array": wgpu.TextureViewDimension.d2_array,
        }
        return texture.create_view(dimension=dim_map.get(dimension, wgpu.TextureViewDimension.d2))

    def create_sampler(self, filter_mode: str = "nearest") -> wgpu.GPUSampler:
        filt = wgpu.FilterMode.nearest if filter_mode == "nearest" else wgpu.FilterMode.linear
        return self._ctx.device.create_sampler(
            mag_filter=filt,
            min_filter=filt,
            mipmap_filter=wgpu.MipmapFilterMode.nearest,
            address_mode_u=wgpu.AddressMode.clamp_to_edge,
            address_mode_v=wgpu.AddressMode.clamp_to_edge,
        )

    def invalidate(self, layer: "Layer") -> None:
        self._texture_cache.pop(id(layer), None)

    def destroy_all(self) -> None:
        for tex in self._texture_cache.values():
            tex.destroy()
        self._texture_cache.clear()
        for tex in self._array_cache.values():
            tex.destroy()
        self._array_cache.clear()
