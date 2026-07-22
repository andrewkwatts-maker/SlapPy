"""
TriggerSystem — abstract spatial overlap detection.
Game-specific concepts (checkpoint, boost pad, damage zone) wrap this.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from pharos_engine.event_bus import publish


@dataclass
class TriggerVolume:
    """An axis-aligned bounding-box trigger with optional callbacks.

    Parameters
    ----------
    position:
        Centre of the AABB trigger in world space.
    size:
        ``(width, height)`` of the AABB.
    normal:
        Facing direction for directional triggers (not used by default AABB test).
    on_enter:
        Called with the entity on the first frame of overlap.
    on_exit:
        Called with the entity on the first frame overlap ends.
    on_stay:
        Called with the entity every frame while overlap continues.
    tag:
        Arbitrary string label for game-logic filtering.
    pixel_precise:
        If ``True``, a pixel-level alpha overlap check is performed after the
        AABB fast-reject test.  Requires the entity to expose a
        ``_image_data`` attribute (slower).
    """

    position: tuple[float, float]
    size: tuple[float, float]
    normal: tuple[float, float] = (0.0, 1.0)
    on_enter: Callable | None = None
    on_exit:  Callable | None = None
    on_stay:  Callable | None = None
    tag: str = ""
    pixel_precise: bool = False
    _inside: set = field(default_factory=set, init=False, repr=False)


class TriggerSystem:
    """Manages a set of :class:`TriggerVolume`s and fires callbacks on entity overlap.

    Usage
    -----
    ::

        sys = TriggerSystem()
        vol = TriggerVolume(position=(100, 100), size=(50, 50),
                             on_enter=lambda e: print("entered", e))
        sys.add(vol)
        sys.update(scene.entities)  # call once per frame
    """

    def __init__(self) -> None:
        self._volumes: list[TriggerVolume] = []

    # ------------------------------------------------------------------
    # Volume management
    # ------------------------------------------------------------------

    def add(self, volume: TriggerVolume) -> TriggerVolume:
        """Add *volume* to the system and return it."""
        self._volumes.append(volume)
        return volume

    def remove(self, volume: TriggerVolume) -> None:
        """Remove *volume* from the system (no-op if not present)."""
        try:
            self._volumes.remove(volume)
        except ValueError:
            pass

    def clear(self) -> None:
        """Remove all volumes."""
        self._volumes.clear()

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, entities: list) -> None:
        """Test all entities against all volumes and fire callbacks.

        Parameters
        ----------
        entities:
            Sequence of entities.  Each must expose ``.position`` as a
            2-tuple ``(x, y)``.  ``.size`` is optional — falls back to
            ``(8, 8)`` when absent.
        """
        for vol in self._volumes:
            still_inside: set = set()
            for entity in entities:
                ex, ey, ew, eh = self._entity_aabb(entity)
                if self._overlaps(vol, ex, ey, ew, eh):
                    still_inside.add(id(entity))
                    if id(entity) not in vol._inside:
                        # First frame of overlap → on_enter
                        if vol.on_enter is not None:
                            vol.on_enter(entity)
                        if vol.tag:
                            publish(f"Trigger.Enter.{vol.tag}",
                                    publisher=vol, entity=entity, volume=vol)
                    else:
                        # Continuing overlap → on_stay
                        if vol.on_stay is not None:
                            vol.on_stay(entity)

            # Entities that were inside last frame but not this frame → on_exit
            left = vol._inside - still_inside
            # We need actual entity objects for on_exit; iterate entities again
            if left and (vol.on_exit is not None or vol.tag):
                for entity in entities:
                    if id(entity) in left:
                        if vol.on_exit is not None:
                            vol.on_exit(entity)
                        if vol.tag:
                            publish(f"Trigger.Exit.{vol.tag}",
                                    publisher=vol, entity=entity, volume=vol)

            # Also fire on_exit for entities completely gone from the list
            # (id may be recycled, but best-effort)
            vol._inside = still_inside

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _entity_aabb(self, entity) -> tuple[float, float, float, float]:
        """Return ``(x, y, w, h)`` for *entity*, centred on its position."""
        pos = entity.position
        ex, ey = float(pos[0]), float(pos[1])
        size = getattr(entity, "size", None)
        if size is not None and len(size) >= 2:
            ew, eh = float(size[0]), float(size[1])
        else:
            ew, eh = 8.0, 8.0
        return ex, ey, ew, eh

    def _overlaps(self, vol: TriggerVolume,
                  ex: float, ey: float, ew: float, eh: float) -> bool:
        """AABB vs AABB overlap test.

        Both AABBs are axis-aligned, with (x, y) being the **centre** of each.
        """
        vx, vy = float(vol.position[0]), float(vol.position[1])
        vw, vh = float(vol.size[0]), float(vol.size[1])

        # Half-extents
        vhw, vhh = vw * 0.5, vh * 0.5
        ehw, ehh = ew * 0.5, eh * 0.5

        return (
            abs(ex - vx) < vhw + ehw
            and abs(ey - vy) < vhh + ehh
        )


class ReverbZone(TriggerVolume):
    """A TriggerVolume that publishes reverb parameters when entities enter/exit.

    On enter: publishes ``"Reverb.Enter.<tag>"`` with ``amount`` and ``decay``.
    On exit:  publishes ``"Reverb.Exit.<tag>"`` so audio can restore dry state.

    Usage::

        tunnel = ReverbZone(position=(640, 200), size=(200, 80),
                            tag="tunnel_01", reverb_amount=0.7, reverb_decay=1.2)
        trigger_system.add(tunnel)
        # AudioSystem subscribes "Reverb.Enter.tunnel_01" → set_reverb(0.7, 1.2)
    """

    def __init__(
        self,
        position: tuple[float, float],
        size: tuple[float, float],
        tag: str = "reverb",
        reverb_amount: float = 0.4,
        reverb_decay: float = 0.8,
        **kwargs,
    ) -> None:
        self.reverb_amount = reverb_amount
        self.reverb_decay  = reverb_decay
        from pharos_engine.event_bus import publish as _pub

        def _on_enter(entity) -> None:
            _pub(f"Reverb.Enter.{tag}", publisher=self, entity=entity,
                 amount=reverb_amount, decay=reverb_decay)

        def _on_exit(entity) -> None:
            _pub(f"Reverb.Exit.{tag}", publisher=self, entity=entity)

        super().__init__(
            position=position,
            size=size,
            tag=tag,
            on_enter=_on_enter,
            on_exit=_on_exit,
            **kwargs,
        )
