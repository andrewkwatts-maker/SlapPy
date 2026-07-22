from __future__ import annotations

from typing import Any

from pharos_engine.entity import Entity
from pharos_engine.layer import Layer

__all__: list[str] = ["Asset"]

class Asset(Entity):
    size: tuple[int, int]
    layers: list[Layer]
    visible: bool
    z_order: float
    post_process: Any | None  # PostProcessChain | None
    material_map: Any | None  # MaterialMap | None
    pixels: Any | None  # PixelAPI | None
    compute: Any | None  # AssetComputeAPI | None
    effects: list[Any]  # list[NodeMaterial]

    def __init__(
        self,
        name: str = "",
        position: tuple[float, float] = (0.0, 0.0),
        size: tuple[int, int] = (64, 64),
    ) -> None: ...

    @classmethod
    def from_image(cls, path: str, name: str | None = None) -> Asset: ...

    def add_layer(self, layer: Layer) -> Layer: ...
    def remove_layer(self, layer: Layer) -> None: ...

    def add_effect(self, mat: Any, blend: str = "normal") -> None: ...

    def evict_to_ram(self) -> None: ...
    def evict_to_disk(self) -> None: ...
    def prefetch(self) -> None: ...
    def bake_data_layer(self, output_path: str | None = None) -> None: ...
