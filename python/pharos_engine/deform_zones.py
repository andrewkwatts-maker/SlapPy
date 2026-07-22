"""pharos_engine.deform_zones — Pixel zone tagging for DeformableLayerComponent.

Zones are named sub-regions of a deformable layer. Each zone has its own
integrity threshold and event. When zone integrity drops below its threshold,
the zone fires its destroy event.

Game code defines zones at asset creation. Engine tracks them per-frame.

Example usage
-------------
    zone_map = ZoneMap(layer_width=128, layer_height=64)
    zone_map.add_rect_zone("front_bumper",
                           x=0, y=16, w=20, h=32,
                           threshold=0.4,
                           on_destroy="Vehicle.BumperLost",
                           strength_scale=0.7)
    zone_map.add_rect_zone("windshield",
                           x=40, y=8, w=48, h=20,
                           threshold=0.2,
                           on_destroy="Vehicle.WindshieldShattered",
                           material="glass",
                           strength_scale=0.3)

    # Per frame:
    zone_map.update(image_data, publisher=vehicle)
"""
from __future__ import annotations
import dataclasses
from typing import TYPE_CHECKING

import numpy as np

from pharos_engine.event_bus import publish

if TYPE_CHECKING:
    pass


@dataclasses.dataclass
class ZoneDef:
    """Definition of a named pixel zone."""
    name: str
    # Pixel rect (layer-local coordinates)
    x: int
    y: int
    w: int
    h: int
    # When zone integrity drops below this → fire on_destroy_event
    integrity_threshold: float = 0.0
    # Event name published on destruction
    on_destroy_event: str = "Deform.ZoneDestroyed"
    # Optional material preset name for this zone ("glass", "metal", etc.)
    material: str | None = None
    # Multiplier on elastic_threshold for this zone
    strength_scale: float = 1.0
    # Mask array (h x w uint8): if provided, only pixels where mask > 0 are tracked.
    # None means entire rect is the zone.
    mask: np.ndarray | None = dataclasses.field(default=None, repr=False)


class ZoneMap:
    """Tracks named pixel zones within a deformable layer.

    Parameters
    ----------
    layer_width, layer_height:
        Pixel dimensions of the target layer.
    """

    def __init__(self, layer_width: int, layer_height: int) -> None:
        self._w = layer_width
        self._h = layer_height
        self._zones: list[ZoneDef] = []
        # Per-zone state
        self._zone_integrity: dict[str, float] = {}
        self._zone_destroyed: dict[str, bool] = {}

    def add_rect_zone(
        self,
        name: str,
        x: int, y: int, w: int, h: int,
        threshold: float = 0.0,
        on_destroy: str = "Deform.ZoneDestroyed",
        material: str | None = None,
        strength_scale: float = 1.0,
        mask: np.ndarray | None = None,
    ) -> "ZoneMap":
        """Add a rectangular zone. Returns self for chaining."""
        zone = ZoneDef(
            name=name, x=x, y=y, w=w, h=h,
            integrity_threshold=threshold,
            on_destroy_event=on_destroy,
            material=material,
            strength_scale=strength_scale,
            mask=mask,
        )
        self._zones.append(zone)
        self._zone_integrity[name] = 1.0
        self._zone_destroyed[name] = False
        return self

    def update(self, image_data: np.ndarray, publisher: object = None) -> None:
        """Recompute per-zone integrity from image alpha channel.

        Call once per frame after the deform shader has run.

        Parameters
        ----------
        image_data:
            The layer's _image_data numpy array (h x w x 4, dtype uint8).
        publisher:
            Entity to pass as event publisher. Typically the vehicle entity.
        """
        if image_data is None or image_data.ndim != 3 or image_data.shape[2] < 4:
            return

        alpha = image_data[:, :, 3].astype(np.float32) / 255.0

        for zone in self._zones:
            x0 = max(0, zone.x)
            y0 = max(0, zone.y)
            x1 = min(self._w, zone.x + zone.w)
            y1 = min(self._h, zone.y + zone.h)
            if x1 <= x0 or y1 <= y0:
                continue

            region = alpha[y0:y1, x0:x1]

            if zone.mask is not None:
                mh = min(zone.mask.shape[0], region.shape[0])
                mw = min(zone.mask.shape[1], region.shape[1])
                valid = zone.mask[:mh, :mw] > 0
                if valid.any():
                    integrity = float(region[:mh, :mw][valid].mean())
                else:
                    integrity = 1.0
            else:
                integrity = float(region.mean()) if region.size > 0 else 1.0

            self._zone_integrity[zone.name] = integrity

            # Fire destroy event once when threshold crossed
            if (integrity <= zone.integrity_threshold
                    and not self._zone_destroyed.get(zone.name, False)):
                self._zone_destroyed[zone.name] = True
                publish(
                    zone.on_destroy_event,
                    publisher=publisher,
                    zone=zone.name,
                    integrity=integrity,
                    material=zone.material,
                )

            # Repair recovery: if integrity rose back above threshold, allow re-trigger
            elif integrity > zone.integrity_threshold + 0.05:
                self._zone_destroyed[zone.name] = False

    def integrity(self, zone_name: str) -> float:
        """Return current integrity [0..1] of a named zone. 1.0 if zone not found."""
        return self._zone_integrity.get(zone_name, 1.0)

    def is_destroyed(self, zone_name: str) -> bool:
        """Return True if zone has fired its destroy event."""
        return self._zone_destroyed.get(zone_name, False)

    def zone_names(self) -> list[str]:
        return [z.name for z in self._zones]

    def get_zone(self, name: str) -> ZoneDef | None:
        for z in self._zones:
            if z.name == name:
                return z
        return None

    def reset(self) -> None:
        """Reset all zone destruction flags (e.g., on repair/respawn)."""
        for name in self._zone_destroyed:
            self._zone_destroyed[name] = False
        for name in self._zone_integrity:
            self._zone_integrity[name] = 1.0
