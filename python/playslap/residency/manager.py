from __future__ import annotations
import math
from pathlib import Path
from typing import TYPE_CHECKING
from playslap.config import engine_config

if TYPE_CHECKING:
    from playslap.entity import Entity
    from playslap.asset import Asset
    from playslap.gpu.context import GPUContext
    from playslap.gpu.buffer_manager import BufferManager
    from playslap.gpu.texture_manager import TextureManager


class ResidencyManager:
    TIER_GPU  = "gpu"
    TIER_RAM  = "ram"
    TIER_DISK = "disk"

    def __init__(self, ctx=None, buf_mgr=None, tex_mgr=None, save_dir: str | Path = "."):
        cfg = engine_config().residency
        self.streaming_radius_gpu  = cfg.streaming_radius_gpu
        self.streaming_radius_ram  = cfg.streaming_radius_ram
        self.vram_budget_mb        = cfg.vram_budget_mb
        self.ram_budget_mb         = cfg.ram_budget_mb
        self._ctx     = ctx
        self._buf     = buf_mgr
        self._tex     = tex_mgr
        self._save_dir = Path(save_dir)
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._tiers: dict[str, str] = {}  # entity_id → tier

    def tier(self, entity) -> str:
        return self._tiers.get(entity.id, self.TIER_GPU)

    def update(self, camera_pos: tuple[float, float], entities: list) -> None:
        from playslap.asset import Asset
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
        if self.tier(entity) == self.TIER_GPU:
            self.evict_to_ram(entity)
        self._write_to_disk(entity)
        self._free_ram(entity)
        self._tiers[entity.id] = self.TIER_DISK

    def prefetch(self, entity) -> None:
        t = self.tier(entity)
        if t == self.TIER_DISK:
            self._promote_disk_to_ram(entity)
        self._promote_ram_to_gpu(entity)
        self._tiers[entity.id] = self.TIER_GPU

    def _write_to_disk(self, entity) -> None:
        from playslap.residency.slap_format import write_asset_to_slap
        slap_path = self._save_dir / f"{entity.id}.slap"
        write_asset_to_slap(slap_path, entity)

    def _free_ram(self, entity) -> None:
        for layer in entity.layers:
            layer._ram_pixel_data = None

    def _promote_disk_to_ram(self, entity) -> None:
        from playslap.residency.slap_format import read_asset_from_slap
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
