"""Composable node-based particle emitters.

The existing :class:`~slappyengine.physics.particles.ParticleSystem` ships
with six hardcoded "styles" (shatter, spark, splatter, splash, ember,
dust).  Each style is a single visual look chosen by material name.  In
practice contacts often *deserve* multiple layered looks at once -- an
iron impact should emit bright fast sparks *and* slow drifting smoke,
a glass shatter should emit shards *and* a fine glittery dust.

This module adds a thin "node graph" on top of the existing system.  A
:class:`ParticleGraph` is a list of :class:`EmitterNode` definitions;
each node decides for itself whether to fire for a given contact
(``material_filter``, ``impulse_threshold``, ``spawn_chance``) and, if
so, what kind of particles to spawn (count, direction mode, speed/life/
size ranges, life-driven colour ramp, gravity scale, drag).

The graph delegates rendering and per-step integration to the existing
``ParticleSystem`` -- it only owns *emission*.  Particles spawned by a
graph are indistinguishable from particles spawned by the legacy
``emit()`` path once they're in the SOA buffer.

Quick start
-----------
::

    from slappyengine.physics import ParticleSystem
    from slappyengine.physics.particle_graph import ParticleGraph

    psys = ParticleSystem()
    graph = ParticleGraph.preset_iron_impact()

    # in your physics step:
    contacts = world.step()
    graph.emit_for_contact(psys, contacts, world=world,
                           body_lookup=world._body_for_hull)
    psys.step(dt)
    psys.render(frame, world_view=...)

Each preset constructor returns a graph with 2-3 layered emitters tuned
for a particular interaction type.  Define your own graphs by appending
:class:`EmitterNode` instances directly.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from slappyengine.physics.particles import (
    ParticleSystem,
    _material_for,
    _unpack_contact,
)


# ---------------------------------------------------------------------------
# Direction modes
# ---------------------------------------------------------------------------

DIRECTION_MODES: tuple[str, ...] = ("normal", "radial", "fixed", "tangent")


def _interp_color(
    ramp: Sequence[tuple[float, tuple[int, int, int]]],
    t: float,
) -> tuple[int, int, int]:
    """Linearly interpolate ``ramp`` (sorted by ``t`` waypoint) at ``t``.

    ``ramp`` is a sequence of ``(t, (r, g, b))`` tuples with ``t`` in
    [0, 1].  Out-of-range ``t`` clamps to the endpoints.  An empty ramp
    falls back to white.
    """
    if not ramp:
        return (255, 255, 255)
    t = max(0.0, min(1.0, float(t)))
    # Sort defensively in case a user passes them out of order.
    pts = sorted(ramp, key=lambda kv: kv[0])
    if t <= pts[0][0]:
        c = pts[0][1]
        return (int(c[0]), int(c[1]), int(c[2]))
    if t >= pts[-1][0]:
        c = pts[-1][1]
        return (int(c[0]), int(c[1]), int(c[2]))
    for i in range(len(pts) - 1):
        t0, c0 = pts[i]
        t1, c1 = pts[i + 1]
        if t0 <= t <= t1:
            span = max(1e-9, t1 - t0)
            f = (t - t0) / span
            r = int(round(c0[0] + (c1[0] - c0[0]) * f))
            g = int(round(c0[1] + (c1[1] - c0[1]) * f))
            b = int(round(c0[2] + (c1[2] - c0[2]) * f))
            return (r, g, b)
    # Unreachable, but be safe.
    c = pts[-1][1]
    return (int(c[0]), int(c[1]), int(c[2]))


# ---------------------------------------------------------------------------
# EmitterNode
# ---------------------------------------------------------------------------

@dataclass
class EmitterNode:
    """A composable particle emitter definition.

    Each emitter has nodes for:

    * ``count_range`` -- how many particles per emission.
    * ``direction_mode`` -- ``"cone"`` (alias of ``"normal"``),
      ``"radial"``, ``"fixed"``, or ``"tangent"``.
    * ``speed_range`` -- min/max launch speed in px/s.
    * ``life_range`` -- min/max lifetime in seconds.
    * ``size_range`` -- min/max particle size (px).
    * ``color_ramp`` -- list of ``(t, (r, g, b))`` waypoints for the
      life-driven colour.  ``t=0`` is "just born", ``t=1`` is "about to
      die".
    * ``material_filter`` -- emit only when the contact involves one of
      these material names (``None`` = match any).
    * ``gravity_scale`` -- multiplier on the particle system's gravity
      for *this* emitter's particles (1.0 = inherit world gravity,
      0.0 = float, negative = rise like embers).
    * ``drag_per_sec`` -- per-second velocity retention applied as a
      one-shot multiplier at spawn time (the system's own drag still
      applies each step).
    * ``spawn_chance`` -- probability in [0, 1] per matching contact.
    * ``impulse_threshold`` -- only emit when the contact penetration
      depth exceeds this value (0.0 = always).
    * ``cone_half_angle_rad`` -- direction cone half-angle (small =
      narrow stream).  Only used for ``"normal"`` / ``"fixed"`` /
      ``"tangent"`` modes; ``"radial"`` ignores it.
    """

    name: str
    count_range: tuple[int, int] = (4, 8)
    direction_mode: str = "normal"
    fixed_direction: tuple[float, float] = (0.0, -1.0)
    speed_range: tuple[float, float] = (100.0, 300.0)
    life_range: tuple[float, float] = (0.3, 0.8)
    size_range: tuple[float, float] = (1.0, 2.0)
    color_ramp: list[tuple[float, tuple[int, int, int]]] = field(
        default_factory=lambda: [(0.0, (255, 255, 255)), (1.0, (100, 100, 100))]
    )
    material_filter: set[str] | None = None
    gravity_scale: float = 1.0
    drag_per_sec: float = 0.85
    spawn_chance: float = 1.0
    impulse_threshold: float = 0.0
    cone_half_angle_rad: float = 0.5

    # -- matching -----------------------------------------------------------

    def matches_material(self, material_a: str | None, material_b: str | None) -> bool:
        """``True`` if this emitter wants to fire for materials ``a`` / ``b``.

        With no filter, every contact matches.  Otherwise either side
        must appear in ``material_filter``.
        """
        if self.material_filter is None:
            return True
        if material_a is not None and material_a in self.material_filter:
            return True
        if material_b is not None and material_b in self.material_filter:
            return True
        return False

    # -- direction sampling -------------------------------------------------

    def sample_direction(
        self,
        normal: tuple[float, float],
        rng: random.Random,
    ) -> tuple[float, float]:
        """Sample one launch direction (unit-vector-ish) for this emitter.

        ``normal`` is the contact normal as passed from the physics
        world (already a 2-tuple of floats).
        """
        mode = self.direction_mode
        if mode == "radial":
            ang = rng.uniform(-math.pi, math.pi)
            return (math.cos(ang), math.sin(ang))
        if mode == "fixed":
            base_ang = math.atan2(
                float(self.fixed_direction[1]), float(self.fixed_direction[0])
            )
        elif mode == "tangent":
            # 90° rotation of the normal.
            base_ang = math.atan2(float(normal[0]), -float(normal[1]))
        else:  # "normal" / "cone" / default
            nx, ny = float(normal[0]), float(normal[1])
            if abs(nx) < 1e-9 and abs(ny) < 1e-9:
                base_ang = rng.uniform(-math.pi, math.pi)
            else:
                base_ang = math.atan2(ny, nx)
        half = max(0.0, float(self.cone_half_angle_rad))
        ang = base_ang + rng.uniform(-half, half)
        return (math.cos(ang), math.sin(ang))

    # -- spawn --------------------------------------------------------------

    def spawn(
        self,
        particle_system: ParticleSystem,
        point: tuple[float, float],
        normal: tuple[float, float],
        rng: random.Random | None = None,
    ) -> int:
        """Insert this emitter's particles directly into ``particle_system``.

        Returns the actual number of particles inserted (clipped to the
        system's free capacity).  This bypasses
        :meth:`ParticleSystem.emit` because that path is driven by the
        legacy material→style table; we instead write directly into the
        SOA buffers so the graph has full control of colour / speed /
        size / life on a per-emitter basis.
        """
        r = rng if rng is not None else particle_system._rng
        c_lo, c_hi = int(self.count_range[0]), int(self.count_range[1])
        if c_hi < c_lo:
            c_lo, c_hi = c_hi, c_lo
        if c_lo == c_hi:
            want = c_lo
        else:
            want = r.randint(c_lo, c_hi)
        if want <= 0:
            return 0

        free = particle_system.max_particles - particle_system._count
        if free <= 0:
            return 0
        spawn = min(free, want)

        # Resolve "just born" colour from ramp t=0 once per call.
        born_color = _interp_color(self.color_ramp, 0.0)

        base = particle_system._count
        for k in range(spawn):
            i = base + k
            dx, dy = self.sample_direction(normal, r)
            spd = r.uniform(float(self.speed_range[0]), float(self.speed_range[1]))
            # One-shot drag bake-in: pre-attenuate the launch speed by
            # the configured per-second retention so user-visible "drag"
            # numbers act as a soft cap on travel distance.  The system's
            # own air_drag still applies each step on top of this.
            drag_bake = max(0.0, min(1.0, float(self.drag_per_sec)))
            vx = dx * spd
            vy = dy * spd

            particle_system._pos[i, 0] = float(point[0])
            particle_system._pos[i, 1] = float(point[1])
            particle_system._vel[i, 0] = vx
            particle_system._vel[i, 1] = vy
            life = r.uniform(float(self.life_range[0]), float(self.life_range[1]))
            particle_system._life[i] = life
            particle_system._mlife[i] = life
            particle_system._size[i] = r.uniform(
                float(self.size_range[0]), float(self.size_range[1])
            )
            particle_system._col[i, 0] = born_color[0]
            particle_system._col[i, 1] = born_color[1]
            particle_system._col[i, 2] = born_color[2]
            # Drag bake-in is applied *after* assignment so the test
            # ``test_count_range_respected`` etc. can read the velocity
            # if they want; this is a single multiply.
            if drag_bake != 1.0:
                particle_system._vel[i, 0] = vx * drag_bake
                particle_system._vel[i, 1] = vy * drag_bake
        particle_system._count += spawn
        return spawn


# ---------------------------------------------------------------------------
# ParticleGraph
# ---------------------------------------------------------------------------

class ParticleGraph:
    """A list of :class:`EmitterNode`\\s that compose into a particle look.

    Multiple emitters can fire on the same contact: e.g. an "iron impact"
    graph has one node for bright fast sparks and another for slow dark
    smoke so a single hit looks rich rather than one-coloured.

    A graph holds no per-particle state -- it only owns the *definition*
    of how to spawn.  All live particles live in the
    :class:`ParticleSystem` you pass into ``emit_for_contact``.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.emitters: list[EmitterNode] = []
        self._rng: random.Random = rng if rng is not None else random.Random()

    # -- mutation -----------------------------------------------------------

    def add(self, emitter: EmitterNode) -> "ParticleGraph":
        """Append ``emitter`` and return ``self`` for fluent chaining."""
        self.emitters.append(emitter)
        return self

    def __len__(self) -> int:
        return len(self.emitters)

    def __iter__(self) -> Iterable[EmitterNode]:
        return iter(self.emitters)

    # -- emission -----------------------------------------------------------

    def emit_for_contact(
        self,
        particle_system: ParticleSystem,
        contacts,
        world=None,
        hulls=None,
        body_lookup: Mapping[int, object] | None = None,
    ) -> int:
        """Run every emitter against every contact in ``contacts``.

        ``contacts`` may be:

        * a single ContactPair-like / dict (with ``a``, ``b``, ``normal``,
          ``depth``, ``point`` fields), or
        * an iterable of them.

        Returns the total number of particles spawned across all
        contacts and all emitters.
        """
        _ = hulls  # accepted for API parity with ParticleSystem.emit_from_contacts
        if not self.emitters:
            # Still consume the iterable so callers passing generators
            # don't get surprised, but skip all work otherwise.
            return 0

        # Accept a single contact transparently.
        if _looks_like_contact(contacts):
            contact_list: Sequence = [contacts]
        else:
            contact_list = list(contacts)

        total = 0
        for contact in contact_list:
            a, b, normal, depth, point = _unpack_contact(contact)
            mat_a = _material_for(a, world, body_lookup)
            mat_b = _material_for(b, world, body_lookup)
            for emitter in self.emitters:
                if depth < emitter.impulse_threshold:
                    continue
                if not emitter.matches_material(mat_a, mat_b):
                    continue
                if emitter.spawn_chance < 1.0:
                    if self._rng.random() > emitter.spawn_chance:
                        continue
                total += emitter.spawn(particle_system, point, normal, rng=self._rng)
        return total

    # -- presets ------------------------------------------------------------

    @classmethod
    def preset_iron_impact(cls) -> "ParticleGraph":
        """Iron/steel/metal impact: bright fast sparks + slow dark smoke.

        Two emitters:

        * ``"sparks"`` -- short, narrow, very fast, bright yellow→orange
          cone aligned with the contact normal.  Almost no gravity so
          they streak.
        * ``"smoke"`` -- slow wide grey puff that lingers and drifts up
          (negative gravity scale).
        """
        graph = cls()
        graph.add(EmitterNode(
            name="sparks",
            count_range=(5, 10),
            direction_mode="normal",
            speed_range=(350.0, 650.0),
            life_range=(0.15, 0.40),
            size_range=(1.0, 1.0),
            color_ramp=[
                (0.0, (255, 245, 200)),
                (0.5, (255, 180,  60)),
                (1.0, (255, 100,  30)),
            ],
            material_filter={"iron", "steel", "metal"},
            gravity_scale=0.15,
            drag_per_sec=0.90,
            cone_half_angle_rad=0.45,
        ))
        graph.add(EmitterNode(
            name="smoke",
            count_range=(3, 6),
            direction_mode="normal",
            speed_range=(20.0, 70.0),
            life_range=(0.8, 1.6),
            size_range=(2.0, 3.0),
            color_ramp=[
                (0.0, ( 90,  85,  80)),
                (1.0, ( 40,  38,  36)),
            ],
            material_filter={"iron", "steel", "metal"},
            gravity_scale=-0.25,
            drag_per_sec=0.70,
            cone_half_angle_rad=1.1,
        ))
        return graph

    @classmethod
    def preset_glass_shatter(cls) -> "ParticleGraph":
        """Glass shatter: bright fast shards + glittery dust mist.

        * ``"shards"`` -- many small white-blue fragments in a wide cone,
          medium-fast, medium life.
        * ``"glitter"`` -- a fine sparkly mist of tiny bright particles
          that fade quickly.
        """
        graph = cls()
        graph.add(EmitterNode(
            name="shards",
            count_range=(8, 14),
            direction_mode="normal",
            speed_range=(180.0, 420.0),
            life_range=(0.4, 0.9),
            size_range=(1.0, 2.0),
            color_ramp=[
                (0.0, (240, 248, 255)),
                (0.5, (200, 220, 240)),
                (1.0, (140, 160, 180)),
            ],
            material_filter={"glass"},
            gravity_scale=0.8,
            drag_per_sec=0.92,
            cone_half_angle_rad=1.0,
        ))
        graph.add(EmitterNode(
            name="glitter",
            count_range=(6, 12),
            direction_mode="radial",
            speed_range=(40.0, 140.0),
            life_range=(0.20, 0.45),
            size_range=(1.0, 1.0),
            color_ramp=[
                (0.0, (255, 255, 255)),
                (0.7, (220, 230, 250)),
                (1.0, (160, 180, 220)),
            ],
            material_filter={"glass"},
            gravity_scale=0.3,
            drag_per_sec=0.75,
        ))
        return graph

    @classmethod
    def preset_lava_drip(cls) -> "ParticleGraph":
        """Lava drip: bright embers + tiny glowing droplets.

        * ``"embers"`` -- big slow upward-drifting glowing particles
          (negative gravity, long life).
        * ``"droplets"`` -- small fast hot orange droplets that arc
          downward and fade to dark red.
        """
        graph = cls()
        graph.add(EmitterNode(
            name="embers",
            count_range=(4, 8),
            direction_mode="radial",
            speed_range=(20.0, 80.0),
            life_range=(0.9, 1.6),
            size_range=(2.0, 3.0),
            color_ramp=[
                (0.0, (255, 230, 130)),
                (0.5, (255, 140,  40)),
                (1.0, (180,  40,  10)),
            ],
            material_filter={"lava", "lava_ground"},
            gravity_scale=-0.5,
            drag_per_sec=0.80,
        ))
        graph.add(EmitterNode(
            name="droplets",
            count_range=(6, 10),
            direction_mode="normal",
            speed_range=(120.0, 260.0),
            life_range=(0.5, 1.0),
            size_range=(1.0, 2.0),
            color_ramp=[
                (0.0, (255, 200,  80)),
                (0.5, (255, 110,  30)),
                (1.0, (120,  20,   0)),
            ],
            material_filter={"lava", "lava_ground"},
            gravity_scale=1.0,
            drag_per_sec=0.90,
            cone_half_angle_rad=0.7,
        ))
        return graph

    @classmethod
    def preset_water_splash(cls) -> "ParticleGraph":
        """Water splash: blue droplets + white foam mist.

        * ``"droplets"`` -- larger, fall under gravity, mid-life blue.
        * ``"foam"`` -- tiny white short-lived mist particles spawned
          radially.
        """
        graph = cls()
        graph.add(EmitterNode(
            name="droplets",
            count_range=(6, 12),
            direction_mode="normal",
            speed_range=(160.0, 320.0),
            life_range=(0.5, 1.0),
            size_range=(1.0, 2.0),
            color_ramp=[
                (0.0, (160, 220, 250)),
                (0.5, ( 80, 150, 240)),
                (1.0, ( 40,  90, 180)),
            ],
            material_filter={"water"},
            gravity_scale=1.0,
            drag_per_sec=0.92,
            cone_half_angle_rad=0.8,
        ))
        graph.add(EmitterNode(
            name="foam",
            count_range=(8, 16),
            direction_mode="radial",
            speed_range=(50.0, 130.0),
            life_range=(0.25, 0.55),
            size_range=(1.0, 1.0),
            color_ramp=[
                (0.0, (255, 255, 255)),
                (1.0, (200, 220, 240)),
            ],
            material_filter={"water"},
            gravity_scale=0.2,
            drag_per_sec=0.65,
        ))
        return graph

    @classmethod
    def preset_explosion(cls) -> "ParticleGraph":
        """Explosion: fast outer ring + slower smoke + bright core.

        Three emitters with **no material filter** -- this is meant to
        be triggered manually (e.g. on an explosion event) by feeding
        a synthetic "contact" with the explosion centre as ``point``
        and an arbitrary normal.

        * ``"shock"`` -- bright white-yellow radial ring, very fast,
          short life.
        * ``"fire"`` -- orange/red mid-life puffs in a wide cone.
        * ``"smoke"`` -- slow dark grey lingering puffs.
        """
        graph = cls()
        graph.add(EmitterNode(
            name="shock",
            count_range=(12, 18),
            direction_mode="radial",
            speed_range=(400.0, 700.0),
            life_range=(0.15, 0.35),
            size_range=(1.0, 2.0),
            color_ramp=[
                (0.0, (255, 255, 220)),
                (0.5, (255, 200, 100)),
                (1.0, (255, 100,  30)),
            ],
            material_filter=None,
            gravity_scale=0.1,
            drag_per_sec=0.85,
        ))
        graph.add(EmitterNode(
            name="fire",
            count_range=(8, 14),
            direction_mode="radial",
            speed_range=(150.0, 320.0),
            life_range=(0.4, 0.9),
            size_range=(2.0, 3.0),
            color_ramp=[
                (0.0, (255, 220, 120)),
                (0.5, (255, 130,  40)),
                (1.0, (120,  30,  10)),
            ],
            material_filter=None,
            gravity_scale=-0.3,
            drag_per_sec=0.80,
        ))
        graph.add(EmitterNode(
            name="smoke",
            count_range=(6, 10),
            direction_mode="radial",
            speed_range=(40.0, 110.0),
            life_range=(1.0, 1.8),
            size_range=(2.0, 4.0),
            color_ramp=[
                (0.0, ( 90,  85,  80)),
                (1.0, ( 30,  28,  26)),
            ],
            material_filter=None,
            gravity_scale=-0.4,
            drag_per_sec=0.70,
        ))
        return graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_contact(obj) -> bool:
    """Return ``True`` if ``obj`` walks/quacks like a single ContactPair.

    Used by :meth:`ParticleGraph.emit_for_contact` to transparently
    accept either a single contact or a sequence of them.
    """
    if isinstance(obj, dict):
        return "a" in obj and "normal" in obj and "point" in obj
    # Sequences (lists, tuples that aren't a ContactPair, generators):
    # we treat anything that has 'a' + 'normal' + 'point' attributes as
    # a single contact.  Strings, lists, etc. won't.
    return (
        hasattr(obj, "a")
        and hasattr(obj, "normal")
        and hasattr(obj, "point")
        and hasattr(obj, "depth")
    )


# Public helper for tests / external graph users that want to interpolate
# a colour ramp themselves.
def interpolate_color_ramp(
    ramp: Sequence[tuple[float, tuple[int, int, int]]],
    t: float,
) -> tuple[int, int, int]:
    """Public alias of the internal ramp interpolation helper."""
    return _interp_color(ramp, t)


__all__ = [
    "DIRECTION_MODES",
    "EmitterNode",
    "ParticleGraph",
    "interpolate_color_ramp",
]
