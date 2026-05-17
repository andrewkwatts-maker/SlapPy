from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

__all__: list[str] = ["Layer", "Layer2D", "Layer3D", "LayerDataBuffer"]

class Layer:
    name: str
    mode: str
    entity: Any | None  # Entity | None
    visual_texture: Any
    data_buffer: Any
    blend_mode: str
    alpha_threshold: float
    visible: bool
    opacity: float
    channel_map: dict[str, str]
    lighting: Any | None  # LightingContext | None
    mesh_geometry: Any | None  # GpuMesh | None
    mesh_material: Any | None  # PbrMaterial | None

    def __init__(self, name: str = "Layer", mode: str = "2D") -> None: ...

    @classmethod
    def from_image(cls, path: str | Path, name: str | None = None) -> Layer: ...

    @classmethod
    def blank(cls, width: int, height: int, name: str = "Layer", **kwargs: Any) -> Layer: ...

    @property
    def size(self) -> tuple[int, int] | None: ...

    def tick(self, dt: float) -> None: ...
    def attach_script(self, script: Any) -> None: ...

    def bake_to_2d(self, size: tuple[int, int], camera: Any = None) -> Layer: ...
    def apply_heightmap(self, layer_2d: Layer, scale: float = 1.0) -> None: ...
    def apply_normal_map(self, layer_2d: Layer) -> None: ...
    def apply_albedo(self, layer_2d: Layer) -> None: ...


class Layer2D(Layer):
    def __init__(
        self,
        name: str = "layer",
        width: int = 64,
        height: int = 64,
    ) -> None: ...

    @classmethod
    def from_image(cls, path: Any, name: str | None = None) -> Layer2D: ...  # type: ignore[override]

    @classmethod
    def blank(cls, width: int, height: int, name: str = "layer") -> Layer2D: ...  # type: ignore[override]


class Layer3D(Layer):
    def __init__(self, name: str = "layer") -> None: ...

    @property
    def mesh(self) -> Any | None: ...  # GpuMesh | None
    @mesh.setter
    def mesh(self, value: Any) -> None: ...

    @property
    def material(self) -> Any | None: ...  # PbrMaterial | None
    @material.setter
    def material(self, value: Any) -> None: ...


class LayerDataBuffer(Layer2D):
    struct_fields: list[str]

    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        struct_fields: list[str],
    ) -> None: ...

    def get_field(self, field: str) -> Any: ...  # np.ndarray slice
    def set_field(self, field: str, values: Any) -> None: ...
