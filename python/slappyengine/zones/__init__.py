"""slappyengine.zones — Generic zone primitives.

A *zone* is a named axis-aligned rectangle with optional material tag
and event callbacks. Zones are the canonical primitive for:

* **Damage zones** — threshold-based destruction (bumpers, hoods,
  windshields on vehicles; head/torso/legs on enemies).
* **Trigger volumes** — enter/exit events for game logic (pickups,
  region triggers, line-of-sight regions).
* **Spawn pads** — region anchors for entity spawning.

The design is intentionally minimal: the rect + threshold + material
data model from the legacy ``deform_zones.ZoneMap`` is preserved, but
the per-pixel-physics-only update path (integrity from image alpha) is
*not* re-exported here. Callers that need pixel-alpha integrity should
continue to use ``slappyengine.deform_zones.ZoneMap`` until Phase D
folds it in.

Public surface
--------------

* :class:`RectZone` — a named rect with optional enter/exit callbacks
  and a ``contains_point`` query.
* :class:`ThresholdZone` — a :class:`RectZone` plus a scalar threshold
  and ``on_threshold`` callback (fires once per crossing, re-arms when
  the measured value rises back above ``threshold + hysteresis``).
* :class:`ZoneManager` — tracks any mix of the two; :meth:`update`
  takes a list of entity positions and emits enter/exit; separate
  :meth:`update_threshold` feeds scalar measurements per-zone.

Example
-------

>>> from slappyengine.zones import RectZone, ZoneManager
>>> mgr = ZoneManager()
>>> def entered(eid): print("entered", eid)
>>> zone = RectZone("pad", x=0, y=0, w=10, h=10, on_enter=entered)
>>> mgr.add(zone)
>>> mgr.update({"player": (5, 5)})  # prints "entered player"
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Hashable, Iterable

from ._validation import (
    validate_finite_float,
    validate_non_negative_float,
    validate_positive_float,
)


__all__ = [
    "RectZone",
    "ThresholdZone",
    "ZoneManager",
]


# ── Type aliases ───────────────────────────────────────────────────────────


EntityId = Hashable
Position = tuple[float, float]
EnterExitCallback = Callable[[EntityId], None]
ThresholdCallback = Callable[[float], None]


# ── RectZone ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class RectZone:
    """An axis-aligned rectangular zone with optional enter/exit callbacks.

    Coordinates are *generic*: the manager makes no assumption about
    whether they are world, pixel, or screen units — callers are
    responsible for using a consistent space across all zones in a
    given :class:`ZoneManager`.

    Parameters
    ----------
    name:
        Stable identifier; used as the key in :class:`ZoneManager`.
    x, y, w, h:
        Rect corner + size. Half-open: a point at ``(x+w, y+h)`` is
        *outside* the zone.
    material:
        Optional free-form material tag (e.g. ``"glass"``, ``"metal"``).
        The zone manager does not interpret it; consumer code uses it
        to look up impact effects, damage multipliers, sound presets, …
    on_enter:
        Called as ``on_enter(entity_id)`` when an entity transitions
        from outside to inside the zone during a
        :meth:`ZoneManager.update` pass.
    on_exit:
        Called as ``on_exit(entity_id)`` on the reverse transition.
    """

    name: str
    x: float
    y: float
    w: float
    h: float
    material: str | None = None
    on_enter: EnterExitCallback | None = dataclasses.field(default=None, repr=False)
    on_exit: EnterExitCallback | None = dataclasses.field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate rect geometry at construction time.

        Raises
        ------
        TypeError
            If ``x`` / ``y`` / ``w`` / ``h`` are not real numbers.
        ValueError
            If ``w`` or ``h`` is not strictly positive, or any coordinate
            is non-finite.
        """
        self.x = validate_finite_float("x", "RectZone", self.x)
        self.y = validate_finite_float("y", "RectZone", self.y)
        self.w = validate_positive_float("w", "RectZone", self.w)
        self.h = validate_positive_float("h", "RectZone", self.h)

    # ── Geometry ──────────────────────────────────────────────────────────

    @property
    def rect(self) -> tuple[float, float, float, float]:
        """Return ``(x, y, w, h)`` as a tuple for serialisation/UI binding."""
        return (self.x, self.y, self.w, self.h)

    @rect.setter
    def rect(self, value: tuple[float, float, float, float]) -> None:
        self.x, self.y, self.w, self.h = (float(v) for v in value)

    def contains_point(self, px: float, py: float) -> bool:
        """Return True iff ``(px, py)`` falls inside this zone's half-open rect."""
        return (self.x <= px < self.x + self.w
                and self.y <= py < self.y + self.h)


# ── ThresholdZone ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class ThresholdZone(RectZone):
    """A :class:`RectZone` with a scalar measurement + threshold event.

    Used for damage / integrity / fill-level zones. The owner repeatedly
    feeds the latest measured value through
    :meth:`ZoneManager.update_threshold`; the zone fires
    :attr:`on_threshold` exactly once when the value first dips at or
    below :attr:`threshold`. The zone re-arms when the value rises back
    above ``threshold + hysteresis`` so it can fire again.

    Parameters
    ----------
    threshold:
        Trigger value. Crossing the threshold *downward* fires the event.
    hysteresis:
        Re-arm margin. Defaults to ``0.05``; matches the legacy
        ``deform_zones.ZoneMap`` policy.
    on_threshold:
        Called as ``on_threshold(value)`` on the first crossing.
    strength_scale:
        Damage-zone multiplier; e.g. on a vehicle, the windshield zone
        scales its parent layer's elastic_threshold by this value so
        glass breaks at a lower force than steel. The zone itself does
        not interpret it; consumer code does.
    on_destroy_event:
        Optional EventBus topic to publish on threshold crossing,
        for callers that prefer the engine-wide pub-sub channel over
        a direct callback. The :class:`ZoneManager` does *not* publish
        for you — it just stores the topic so the bridging code can
        read it. The direct ``on_threshold`` callback path is the
        canonical one.
    """

    threshold: float = 0.0
    hysteresis: float = 0.05
    on_threshold: ThresholdCallback | None = dataclasses.field(default=None, repr=False)
    strength_scale: float = 1.0
    on_destroy_event: str = "Zone.Destroyed"

    def __post_init__(self) -> None:
        """Validate rect geometry plus threshold/hysteresis.

        Raises
        ------
        TypeError
            If ``threshold`` / ``hysteresis`` are not real numbers (in
            addition to the rect-geometry checks inherited from
            :class:`RectZone`).
        ValueError
            If ``threshold`` is non-finite or ``hysteresis`` is negative.
        """
        super().__post_init__()
        self.threshold = validate_finite_float(
            "threshold", "ThresholdZone", self.threshold,
        )
        self.hysteresis = validate_non_negative_float(
            "hysteresis", "ThresholdZone", self.hysteresis,
        )


# ── ZoneManager ───────────────────────────────────────────────────────────


class ZoneManager:
    """Tracks a collection of zones and dispatches lifecycle events.

    The manager owns two independent streams of update events:

    * :meth:`update` — takes an iterable of ``(entity_id, position)``
      pairs (or a dict). For every :class:`RectZone`, it computes the
      delta against the previous frame's occupancy and fires
      ``on_enter`` / ``on_exit`` callbacks. Both :class:`RectZone` and
      :class:`ThresholdZone` participate (a threshold zone is *also* a
      rect zone).
    * :meth:`update_threshold` — takes ``zone_name`` + measured value.
      For :class:`ThresholdZone`, fires ``on_threshold`` on the first
      downward crossing and re-arms on recovery. RectZones ignore it.

    Splitting the two streams keeps positional tracking and integrity
    tracking independent — a damage zone can be threshold-only with no
    entities tracked, and a spawn pad can be enter/exit-only with no
    threshold measurement.
    """

    def __init__(self) -> None:
        self._zones: dict[str, RectZone] = {}
        # Per-zone set of entity ids currently inside the zone.
        self._occupancy: dict[str, set[EntityId]] = {}
        # Threshold-zone destruction state (re-arms on recovery).
        self._fired: dict[str, bool] = {}

    # ── Authoring ──────────────────────────────────────────────────────────

    def add(self, zone: RectZone) -> RectZone:
        """Register *zone*. Returns the zone for chaining."""
        if zone.name in self._zones:
            raise ValueError(f"duplicate zone name: {zone.name!r}")
        self._zones[zone.name] = zone
        self._occupancy[zone.name] = set()
        self._fired[zone.name] = False
        return zone

    def remove(self, name: str) -> bool:
        """Drop a zone by name. Returns True iff it was present."""
        if name not in self._zones:
            return False
        del self._zones[name]
        self._occupancy.pop(name, None)
        self._fired.pop(name, None)
        return True

    def get(self, name: str) -> RectZone | None:
        """Return the zone with this name, or ``None``."""
        return self._zones.get(name)

    def names(self) -> list[str]:
        return list(self._zones)

    def zones(self) -> list[RectZone]:
        return list(self._zones.values())

    # ── Per-frame entry/exit tracking ──────────────────────────────────────

    def update(
        self,
        positions: dict[EntityId, Position] | Iterable[tuple[EntityId, Position]],
    ) -> None:
        """Update entity occupancy across all rect zones.

        For each zone, compute the set of currently-inside entities and
        diff against the previous occupancy. Fire ``on_enter`` for new
        arrivals and ``on_exit`` for departures.

        Parameters
        ----------
        positions:
            A dict ``{entity_id: (x, y)}`` or an iterable of
            ``(entity_id, (x, y))`` pairs.

        Raises
        ------
        TypeError
            If ``positions`` is a scalar / string / bytes (i.e. not a dict
            nor a non-string iterable of pairs).
        """
        if isinstance(positions, dict):
            items = list(positions.items())
        elif isinstance(positions, (str, bytes)) or not hasattr(
            positions, "__iter__"
        ):
            raise TypeError(
                "ZoneManager.update: positions must be a dict or iterable "
                f"of (id, (x, y)) pairs; got {type(positions).__name__}"
            )
        else:
            items = list(positions)

        for name, zone in self._zones.items():
            prev = self._occupancy[name]
            now: set[EntityId] = set()
            for eid, pos in items:
                if zone.contains_point(pos[0], pos[1]):
                    now.add(eid)

            entered = now - prev
            exited = prev - now

            if zone.on_enter is not None:
                for eid in entered:
                    zone.on_enter(eid)
            if zone.on_exit is not None:
                for eid in exited:
                    zone.on_exit(eid)

            self._occupancy[name] = now

    def occupancy(self, name: str) -> set[EntityId]:
        """Return the set of entities currently inside the named zone."""
        return set(self._occupancy.get(name, ()))

    # ── Threshold tracking ────────────────────────────────────────────────

    def update_threshold(self, name: str, value: float) -> None:
        """Feed a scalar measurement to a :class:`ThresholdZone`.

        Fires ``on_threshold(value)`` on the first downward crossing
        (``value <= zone.threshold`` while the zone is armed). Re-arms
        when ``value > zone.threshold + zone.hysteresis``.

        Calling for a non-threshold zone or unknown name is a no-op
        (so this can be folded into a generic update loop).
        """
        zone = self._zones.get(name)
        if not isinstance(zone, ThresholdZone):
            return

        fired = self._fired.get(name, False)
        if value <= zone.threshold and not fired:
            self._fired[name] = True
            if zone.on_threshold is not None:
                zone.on_threshold(value)
        elif value > zone.threshold + zone.hysteresis and fired:
            self._fired[name] = False

    def is_fired(self, name: str) -> bool:
        """Return True if a threshold zone has fired and not yet re-armed."""
        return self._fired.get(name, False)

    # ── Reset ─────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all occupancy and re-arm every threshold zone."""
        for name in self._zones:
            self._occupancy[name] = set()
            self._fired[name] = False
