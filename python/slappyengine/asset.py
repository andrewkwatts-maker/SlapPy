from __future__ import annotations
from typing import TYPE_CHECKING
from slappyengine.render_target import RenderTarget
from slappyengine.layer import Layer
from slappyengine.compute.asset_compute import AssetComputeAPI, PixelAPI

if TYPE_CHECKING:
    from slappyengine.material import MaterialMap
    from slappyengine.material.node_material import NodeMaterial


class Asset(RenderTarget):
    def __init__(self, name: str = "", position=(0.0, 0.0), size=(64, 64)):
        super().__init__(name=name, position=position, size=size)
        self.material_map: "MaterialMap | None" = None
        self.pixels: "PixelAPI | None" = None   # set after GPU init
        self.compute: "AssetComputeAPI | None" = None
        self.effects: list["NodeMaterial"] = []
        self._residency_mgr = None

    def add_effect(self, mat: "NodeMaterial", blend: str = "normal") -> None:
        mat.blend = blend
        if mat.wgsl is None:
            mat.compile()
        self.effects.append(mat)

    def add_layer(self, layer: Layer) -> Layer:
        return super().add_layer(layer)

    @classmethod
    def from_image(cls, path: str, name: str | None = None) -> "Asset":
        from pathlib import Path
        inst = cls(name=name or Path(path).stem)
        layer = Layer.from_image(path)
        inst.size = layer.size or (64, 64)
        inst.add_layer(layer)
        return inst

    def evict_to_ram(self) -> None:
        if self._residency_mgr:
            self._residency_mgr.evict_to_ram(self)

    def evict_to_disk(self) -> None:
        if self._residency_mgr:
            self._residency_mgr.evict_to_disk(self)

    def prefetch(self) -> None:
        if self._residency_mgr:
            self._residency_mgr.prefetch(self)

    def bake_data_layer(self, output_path: str | None = None) -> None:
        """
        Snapshot the current pixel/struct data for every layer to disk in .slap format
        without evicting GPU-resident data.

        Whatever CPU-side data is already present on each layer (``_image_data`` for
        visual pixels, ``_data_array`` / ``_pixel_data`` for struct floats) is written
        as-is by the slap format serialiser.  GPU readback must be triggered separately
        (e.g. via AssetComputeAPI) before calling this method if up-to-date struct data
        is required; full async readback integration is planned for M8.1.

        Parameters
        ----------
        output_path:
            Destination path for the .slap file.  Defaults to
            ``{asset.id}_baked.slap`` in the current working directory.
        """
        from pathlib import Path
        from slappyengine.residency.slap_format import write_asset_to_slap

        path = Path(output_path) if output_path else Path(f"{self.id}_baked.slap")
        write_asset_to_slap(path, self)
