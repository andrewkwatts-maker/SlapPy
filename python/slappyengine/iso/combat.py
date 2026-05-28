"""SlapPyEngine.iso.combat — pure-logic combat primitives for iso games.

This module provides the small set of pure-logic primitives Stone Keep (the
engine's iso flagship game) needs to drive tower-defence-style waves and
attack resolution:

- :class:`Attacker` / :class:`Defender` dataclasses describing the two sides
  of a melee/ranged exchange in iso world coordinates.
- :func:`resolve_attack`, a deterministic, side-effect-free function that
  returns ``(damage_dealt, defender_alive)``.
- :class:`WaveSpec` / :class:`WaveSchedule` for scripting deterministic
  spawn waves. ``WaveSchedule.tick`` consumes a ``dt`` delta and emits any
  newly-spawned :class:`Defender` entities for that tick.

Design notes
------------
The module is engine-internal: it imports nothing from any game's source
tree, and it has zero rendering dependencies. It is pure Python + dataclasses
so it can be exercised from tests without a GPU, asset pipeline, or scene.

Determinism is a contract, not an aspiration:

- :func:`resolve_attack` uses no globals and no RNG.
- :class:`WaveSchedule` deterministically cycles through each wave's
  ``spawn_points`` via ``spawn_index % len(spawn_points)`` (round-robin),
  so identical ``(WaveSpec list, dt sequence)`` inputs always produce
  identical :class:`Defender` outputs (same positions, same hp, same order).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Attacker / Defender
# ---------------------------------------------------------------------------

@dataclass
class Attacker:
    """An entity that can deal damage in iso world space.

    Attributes
    ----------
    pos:
        Iso world coordinates ``(x, y)`` of the attacker.
    damage:
        Damage applied to a defender within :attr:`reach`. May be zero.
    reach:
        Maximum Euclidean distance (in iso world units) at which this
        attacker can hit a defender.
    team:
        Free-form team identifier. Combat resolution does not currently
        consult team membership; gameplay code may choose to filter
        attacker/defender pairs by team before calling
        :func:`resolve_attack`.
    """

    pos: Tuple[float, float]
    damage: float
    reach: float
    team: str = "player"


@dataclass
class Defender:
    """An entity that can receive damage in iso world space.

    Attributes
    ----------
    pos:
        Iso world coordinates ``(x, y)`` of the defender.
    hp:
        Current hit points. Becomes ``<= 0`` when the defender dies.
    team:
        Free-form team identifier (see :class:`Attacker`).
    """

    pos: Tuple[float, float]
    hp: float
    team: str = "enemy"


# ---------------------------------------------------------------------------
# resolve_attack — pure function
# ---------------------------------------------------------------------------

def resolve_attack(attacker: Attacker, defender: Defender) -> Tuple[float, bool]:
    """Resolve a single attack from ``attacker`` against ``defender``.

    Parameters
    ----------
    attacker:
        The attacking entity.
    defender:
        The defending entity. Its ``hp`` field will be mutated in place
        when damage is applied.

    Returns
    -------
    tuple[float, bool]
        ``(damage_dealt, defender_alive)``.

        - ``damage_dealt`` is the actual hp removed from the defender.
          It is ``0.0`` when the defender is out of reach.
        - ``defender_alive`` is ``True`` iff the defender's hp remains
          ``> 0`` after the exchange.

    Notes
    -----
    Pure: no globals, no RNG. The only side effect is mutating
    ``defender.hp``.
    """
    dx = defender.pos[0] - attacker.pos[0]
    dy = defender.pos[1] - attacker.pos[1]
    dist = hypot(dx, dy)

    if dist > attacker.reach:
        return 0.0, defender.hp > 0

    damage_dealt = attacker.damage
    defender.hp -= damage_dealt
    return damage_dealt, defender.hp > 0


# ---------------------------------------------------------------------------
# WaveSpec / WaveSchedule
# ---------------------------------------------------------------------------

@dataclass
class WaveSpec:
    """Describes a single wave of defenders to be spawned over time.

    Attributes
    ----------
    count:
        Total number of defenders to spawn for this wave.
    spawn_points:
        Iso world coordinates the wave cycles through (round-robin).
        Must be non-empty if ``count > 0``.
    hp_each:
        Initial hp value applied to every spawned defender.
    interval:
        Seconds between successive spawns within this wave.
    delay:
        Seconds to wait, from the moment this wave becomes active, before
        emitting the first spawn. Defaults to ``0.0`` for an immediate
        spawn on the first ``tick``.
    """

    count: int
    spawn_points: List[Tuple[float, float]]
    hp_each: float
    interval: float
    delay: float = 0.0


@dataclass
class _WaveState:
    """Internal book-keeping for one in-flight :class:`WaveSpec`."""

    spec: WaveSpec
    spawned: int = 0           # how many defenders have been emitted
    elapsed: float = 0.0       # seconds elapsed since this wave became active
    next_spawn_at: float = 0.0 # seconds-since-active when the next spawn fires

    def __post_init__(self) -> None:
        # First spawn happens after the wave's `delay`.
        self.next_spawn_at = self.spec.delay


class WaveSchedule:
    """Deterministic sequential scheduler for a list of :class:`WaveSpec`.

    Each wave runs to completion (all ``count`` defenders spawned) before
    the next wave becomes active. Within a wave, spawn points are visited
    round-robin: defender ``i`` of a wave uses
    ``spawn_points[i % len(spawn_points)]``.

    Determinism
    -----------
    Given the same ``waves`` argument and the same sequence of ``dt`` values
    passed to :meth:`tick`, ``WaveSchedule`` will always emit the same
    :class:`Defender` instances in the same order, with identical positions
    and hp. There is no RNG anywhere in the schedule.
    """

    def __init__(self, waves: List[WaveSpec]) -> None:
        self._waves: List[_WaveState] = [_WaveState(spec=w) for w in waves]
        self._active: int = 0  # index into self._waves of the wave that is "current"

    # ------------------------------------------------------------------ tick
    def tick(self, dt: float) -> List[Defender]:
        """Advance the schedule by ``dt`` seconds.

        Parameters
        ----------
        dt:
            Elapsed seconds since the previous call. Must be ``>= 0``.

        Returns
        -------
        list[Defender]
            Newly-spawned defenders for this tick, in spawn order.
            Empty when no spawns are due.

        Notes
        -----
        Multiple spawns can fire on a single tick if ``dt`` is large
        relative to a wave's ``interval``. The scheduler also rolls
        leftover ``dt`` into the next wave on a wave transition, so the
        same total dt always produces the same spawn pattern regardless
        of how it is sliced.
        """
        spawned: List[Defender] = []
        if dt < 0:
            return spawned

        remaining = dt
        # Loop until we've consumed `dt` AND emitted any spawns that are
        # already due at the current elapsed time. The `first_pass` flag
        # lets a zero-dt tick still fire spawns whose `next_spawn_at` was
        # reached on a prior tick (or is exactly 0.0 on the first tick).
        first_pass = True
        while (remaining > 0.0 or first_pass) and self._active < len(self._waves):
            first_pass = False
            state = self._waves[self._active]
            spec = state.spec

            # If this wave has already emitted everything, advance.
            if state.spawned >= spec.count:
                self._active += 1
                first_pass = True  # give the next wave a chance to fire at 0 dt
                continue

            # Walk forward in time within the current wave, emitting spawns
            # whose `next_spawn_at` is reached by `state.elapsed + remaining`.
            target_elapsed = state.elapsed + remaining
            emitted_this_pass = False
            while (
                state.spawned < spec.count
                and state.next_spawn_at <= target_elapsed
            ):
                # Consume time up to this spawn point.
                consumed = state.next_spawn_at - state.elapsed
                if consumed < 0:
                    consumed = 0.0
                state.elapsed = state.next_spawn_at
                remaining -= consumed

                # Emit the spawn (round-robin spawn-point indexing).
                idx = state.spawned % len(spec.spawn_points)
                point = spec.spawn_points[idx]
                spawned.append(Defender(pos=point, hp=spec.hp_each))
                state.spawned += 1
                emitted_this_pass = True

                # Schedule the next spawn for this wave.
                state.next_spawn_at += spec.interval

            if state.spawned >= spec.count:
                # Wave finished; advance to the next wave but carry remaining
                # dt forward so total-dt determinism holds across wave edges.
                self._active += 1
                first_pass = True  # next wave gets a fair shot at 0 dt
                continue

            # Still spawns left in this wave, but `remaining` doesn't reach
            # the next one — consume what's left of dt and stop.
            if remaining > 0.0:
                state.elapsed += remaining
                remaining = 0.0
            # Nothing more we can emit on this tick.
            if not emitted_this_pass:
                break

        return spawned

    # -------------------------------------------------------------- finished
    @property
    def finished(self) -> bool:
        """``True`` iff every wave has emitted all of its defenders."""
        return all(state.spawned >= state.spec.count for state in self._waves)


__all__ = [
    "Attacker",
    "Defender",
    "resolve_attack",
    "WaveSpec",
    "WaveSchedule",
]
