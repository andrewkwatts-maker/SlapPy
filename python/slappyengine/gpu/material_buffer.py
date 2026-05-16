from __future__ import annotations

import numpy as np
import wgpu
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.material import MaterialMap
    from slappyengine.gpu.context import GPUContext

# Layout: [r_min, r_max, g_min, g_max, b_min, b_max, material_index, _pad]
_FIELDS_PER_ENTRY = 8
_BYTES_PER_ENTRY = _FIELDS_PER_ENTRY * np.dtype(np.uint32).itemsize  # 32


class MaterialBuffer:
    def __init__(self, material_map: "MaterialMap", ctx: "GPUContext"):
        self._ctx = ctx
        self._buf: wgpu.GPUBuffer | None = None
        self._count = 0
        self._allocate(material_map)

    def _pack(self, material_map: "MaterialMap") -> np.ndarray:
        materials = material_map._materials
        n = max(1, len(materials))
        arr = np.zeros(n * _FIELDS_PER_ENTRY, dtype=np.uint32)
        for i, m in enumerate(materials):
            base = i * _FIELDS_PER_ENTRY
            cr = m.color_range
            arr[base + 0] = cr.r[0]
            arr[base + 1] = cr.r[1]
            arr[base + 2] = cr.g[0]
            arr[base + 3] = cr.g[1]
            arr[base + 4] = cr.b[0]
            arr[base + 5] = cr.b[1]
            arr[base + 6] = i
            # arr[base + 7] = 0  (padding, already zero)
        return arr

    def _allocate(self, material_map: "MaterialMap") -> None:
        materials = material_map._materials
        self._count = len(materials)
        size = max(1, self._count) * _BYTES_PER_ENTRY
        if self._buf is not None:
            self._buf.destroy()
        self._buf = self._ctx.device.create_buffer(
            size=size,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="material_buffer",
        )
        data = self._pack(material_map)
        self._ctx.queue.write_buffer(self._buf, 0, data.tobytes())

    @property
    def buffer(self) -> wgpu.GPUBuffer:
        return self._buf

    @property
    def count(self) -> int:
        return self._count

    def update(self, material_map: "MaterialMap") -> None:
        new_count = len(material_map._materials)
        if new_count != self._count:
            self._allocate(material_map)
        else:
            self._count = new_count
            data = self._pack(material_map)
            self._ctx.queue.write_buffer(self._buf, 0, data.tobytes())
