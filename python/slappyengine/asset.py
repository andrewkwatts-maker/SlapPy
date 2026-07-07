from __future__ import annotations
from typing import TYPE_CHECKING
from slappyengine.render_target import RenderTarget
from slappyengine.layer import Layer
from slappyengine.compute.asset_compute import AssetComputeAPI, PixelAPI
from slappyengine._asset_validation import (
    validate_blend,
    validate_existing_file_path,
    validate_finite_2tuple,
    validate_layer_arg,
    validate_name,
    validate_node_material,
    validate_optional_name,
    validate_optional_output_path,
    validate_positive_size_2tuple,
)

if TYPE_CHECKING:
    from slappyengine.material import MaterialMap
    from slappyengine.material.node_material import NodeMaterial


class Asset(RenderTarget):
    def __init__(self, name: str = "", position=(0.0, 0.0), size=(64, 64)):
        name = validate_name("name", "Asset.__init__", name)
        position = validate_finite_2tuple(
            "position", "Asset.__init__", position,
        )
        size = validate_positive_size_2tuple(
            "size", "Asset.__init__", size,
        )
        super().__init__(name=name, position=position, size=size)
        self.material_map: "MaterialMap | None" = None
        self.pixels: "PixelAPI | None" = None   # set after GPU init
        self.compute: "AssetComputeAPI | None" = None
        self.effects: list["NodeMaterial"] = []
        self._residency_mgr = None
        # Backwards-compat: Ochema Circuit's asset-caching tests
        # (tests/test_asset_caching.py:107-118) and scenes/race.py:111
        # rely on ``Asset.cache_mode`` defaulting to
        # ``CacheMode.OFFSCREEN_SERIALIZE`` and being freely reassignable to
        # other ``CacheMode`` values. F1's Asset carried the attribute
        # inline; the modern residency manager pushed the concept behind
        # the tier() API but downstream games still reach for the field
        # directly. Import is deferred to avoid a residency-manager circular
        # (CacheMode lives in residency/manager.py, which imports
        # ``engine_config`` which imports ``slappyengine`` which imports
        # ``asset``). See docs/game_compat_2026_07_07.md § 11.4.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        from slappyengine.residency.manager import CacheMode as _CacheMode
        self.cache_mode = _CacheMode.OFFSCREEN_SERIALIZE

    def add_effect(self, mat: "NodeMaterial", blend: str = "normal") -> None:
        mat = validate_node_material("mat", "Asset.add_effect", mat)
        blend = validate_blend("blend", "Asset.add_effect", blend)
        mat.blend = blend
        if mat.wgsl is None:
            mat.compile()
        self.effects.append(mat)

    def add_layer(self, layer: Layer) -> Layer:
        layer = validate_layer_arg("layer", "Asset.add_layer", layer)
        return super().add_layer(layer)

    @classmethod
    def from_image(cls, path: str, name: str | None = None) -> "Asset":
        from pathlib import Path
        p = validate_existing_file_path("path", "Asset.from_image", path)
        name = validate_optional_name("name", "Asset.from_image", name)
        inst = cls(name=name or Path(p).stem)
        layer = Layer.from_image(p)
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

        validated = validate_optional_output_path(
            "output_path", "Asset.bake_data_layer", output_path,
        )
        path = validated if validated is not None else Path(f"{self.id}_baked.slap")
        write_asset_to_slap(path, self)
