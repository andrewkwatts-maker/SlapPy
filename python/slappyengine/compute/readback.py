from __future__ import annotations
import asyncio
import numpy as np
import wgpu


class ReadbackBuffer:
    """Manages GPU→CPU buffer readback using wgpu staging buffer pattern.

    Pattern:
      1. copy storage_buf → staging_buf (COPY_DST | MAP_READ)
      2. submit command encoder
      3. staging_buf.map_sync(MapMode.READ)
      4. read_mapped() → numpy array, then unmap()
    """

    def __init__(self, device: wgpu.GPUDevice, size_bytes: int, label: str = ""):
        self._device = device
        self._size = size_bytes
        self._buf: wgpu.GPUBuffer = device.create_buffer(
            size=size_bytes,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
            label=label or "readback",
        )

    async def read_from(self, source: wgpu.GPUBuffer,
                        dtype: np.dtype = np.float32) -> np.ndarray:
        encoder = self._device.create_command_encoder()
        encoder.copy_buffer_to_buffer(source, 0, self._buf, 0, self._size)
        self._device.queue.submit([encoder.finish()])

        self._buf.map_sync(wgpu.MapMode.READ)
        result = np.frombuffer(self._buf.read_mapped(0, self._size), dtype=dtype).copy()
        self._buf.unmap()
        return result

    def destroy(self) -> None:
        self._buf.destroy()
