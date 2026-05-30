from __future__ import annotations
import math
from pathlib import Path
from typing import TYPE_CHECKING
from slappyengine.config import engine_config
from slappyengine.residency._validation import (
    validate_entity,
    validate_entity_list,
    validate_finite_2tuple,
    validate_save_dir,
)

if TYPE_CHECKING:
    from slappyengine.entity import Entity
    from slappyengine.asset import Asset
    from slappyengine.gpu.context import GPUContext
    from slappyengine.gpu.buffer_manager import BufferManager
    from slappyengine.gpu.texture_manager import TextureManager


import enum


class CacheMode(enum.Enum):
    """Asset residency tier. Games (Ochema Circuit, Bullet Strata) read
    ``Asset.cache_mode`` to decide eviction priority and lazy-load policy."""
    GPU = "gpu"
    RAM = "ram"
    DISK = "disk"


class ResidencyManager:
    TIER_GPU  = "gpu"
    TIER_RAM  = "ram"
    TIER_DISK = "disk"

    def __init__(self, ctx=None, buf_mgr=None, tex_mgr=None, save_dir: str | Path = "."):
        """Construct a residency manager rooted at ``save_dir``.

        Raises
        ------
        TypeError
            If ``save_dir`` is neither ``str`` nor ``pathlib.Path``.
        ValueError
            If ``save_dir`` is the empty string.
        """
        cfg = engine_config().residency
        self.streaming_radius_gpu  = cfg.streaming_radius_gpu
        self.streaming_radius_ram  = cfg.streaming_radius_ram
        self.vram_budget_mb        = cfg.vram_budget_mb
        self.ram_budget_mb         = cfg.ram_budget_mb
        self._ctx     = ctx
        self._buf     = buf_mgr
        self._tex     = tex_mgr
        self._save_dir = validate_save_dir("save_dir", "ResidencyManager", save_dir)
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._tiers: dict[str, str] = {}  # entity_id → tier

    def tier(self, entity) -> str:
        """Return the current tier (``"gpu"``/``"ram"``/``"disk"``).

        Raises
        ------
        TypeError
            If ``entity`` is ``None`` or lacks ``.id`` / ``.layers``.
        """
        validate_entity("entity", "ResidencyManager.tier", entity)
        return self._tiers.get(entity.id, self.TIER_GPU)

    def update(self, camera_pos: tuple[float, float], entities: list) -> None:
        """Re-tier ``entities`` against ``camera_pos``.

        Raises
        ------
        TypeError
            If ``camera_pos`` isn't a 2-element sequence of real numbers, or
            ``entities`` isn't a list/tuple.
        ValueError
            If ``camera_pos`` has wrong length or contains NaN/inf.
        """
        from slappyengine.asset import Asset
        camera_pos = validate_finite_2tuple(
            "camera_pos", "ResidencyManager.update", camera_pos,
        )
        entities = validate_entity_list(
            "entities", "ResidencyManager.update", entities,
        )
        cx, cy = camera_pos
        for entity in entities:
            if not isinstance(entity, Asset):
                continue
            ex, ey = entity.position
            dist = math.sqrt((ex - cx) ** 2 + (ey - cy) ** 2)
            current = self.tier(entity)
            if dist <= self.streaming_radius_gpu:
                if current == self.TIER_DISK:
                    self._promote_disk_to_ram(entity)
                    self._promote_ram_to_gpu(entity)
                elif current == self.TIER_RAM:
                    self._promote_ram_to_gpu(entity)
                self._tiers[entity.id] = self.TIER_GPU
            elif dist <= self.streaming_radius_ram:
                if current == self.TIER_DISK:
                    self._promote_disk_to_ram(entity)
                elif current == self.TIER_GPU:
                    self.evict_to_ram(entity)
                self._tiers[entity.id] = self.TIER_RAM
            else:
                if current == self.TIER_GPU:
                    self.evict_to_disk(entity)
                elif current == self.TIER_RAM:
                    self._write_to_disk(entity)
                    self._free_ram(entity)
                self._tiers[entity.id] = self.TIER_DISK

    def evict_to_ram(self, entity) -> None:
        """Evict ``entity`` from GPU back to RAM.

        Raises
        ------
        TypeError
            If ``entity`` is ``None`` or lacks ``.id`` / ``.layers``.
        """
        validate_entity("entity", "ResidencyManager.evict_to_ram", entity)
        for layer in entity.layers:
            if self._buf is not None:
                buf = self._buf.get_pixel_buffer(layer)
                if buf is not None:
                    if layer._gpu_texture is not None and hasattr(self._ctx, 'readback_buffer_sync'):
                        try:
                            layer._ram_pixel_data = self._ctx.readback_buffer_sync(layer._gpu_texture)
                        except Exception:
                            layer._ram_pixel_data = None
                    else:
                        layer._ram_pixel_data = None
                    self._buf.release_pixel_buffer(layer)
            if self._tex is not None:
                self._tex.invalidate(layer)
        self._tiers[entity.id] = self.TIER_RAM

    def evict_to_disk(self, entity) -> None:
        """Evict ``entity`` all the way to disk (writes a ``.slap`` file).

        Raises
        ------
        TypeError
            If ``entity`` is ``None`` or lacks ``.id`` / ``.layers``.
        """
        validate_entity("entity", "ResidencyManager.evict_to_disk", entity)
        if self.tier(entity) == self.TIER_GPU:
            self.evict_to_ram(entity)
        self._write_to_disk(entity)
        self._free_ram(entity)
        self._tiers[entity.id] = self.TIER_DISK

    def prefetch(self, entity) -> None:
        """Promote ``entity`` to GPU regardless of current tier.

        Raises
        ------
        TypeError
            If ``entity`` is ``None`` or lacks ``.id`` / ``.layers``.
        """
        validate_entity("entity", "ResidencyManager.prefetch", entity)
        t = self.tier(entity)
        if t == self.TIER_DISK:
            self._promote_disk_to_ram(entity)
        self._promote_ram_to_gpu(entity)
        self._tiers[entity.id] = self.TIER_GPU

    def _write_to_disk(self, entity) -> None:
        from slappyengine.residency.slap_format import write_asset_to_slap
        slap_path = self._save_dir / f"{entity.id}.slap"
        write_asset_to_slap(slap_path, entity)

    def _free_ram(self, entity) -> None:
        for layer in entity.layers:
            layer._ram_pixel_data = None

    def _promote_disk_to_ram(self, entity) -> None:
        from slappyengine.residency.slap_format import read_asset_from_slap
        slap_path = self._save_dir / f"{entity.id}.slap"
        if not slap_path.exists():
            return
        data = read_asset_from_slap(slap_path)
        for i, ldata in enumerate(data.get("layers", [])):
            if i < len(entity.layers):
                img = ldata.get("image_data")
                if img is not None:
                    entity.layers[i]._image_data = img

    def _promote_ram_to_gpu(self, entity) -> None:
        if self._tex is None:
            return
        for layer in entity.layers:
            if layer._image_data is not None:
                self._tex.upload_layer(layer)
