"""Contact-driven visual particle system.

This module implements :class:`ParticleSystem`, a *pure-visual* particle
effect emitter that listens to physics contacts and spits out sparks,
dust, shards, splatter, splashes, or embers depending on the materials
involved.  Particles do **not** feed back into the simulation -- they
exist only as decoration on top of the rendered frame.

Why a separate module?  The physics solver (``world.py``), hull manager
(``hull.py``), and main renderer (``render.py``) are intentionally
agnostic of cosmetic effects.  Keeping the particle system fully
self-contained lets it consume contact data without coupling back into
those hot paths and lets it be swapped or disabled at runtime.

Emission model
--------------
Each material name maps to a *style* (``shatter``, ``spark``,
``splatter``, ``splash``, ``ember``, or ``dust``).  Each style picks
particle colour, base speed, life, and pixel size from a small table.
Particles fan out in a cone aligned with the contact impulse vector
(if any) and otherwise inherit a random isotropic spread.

The system keeps a single ring-buffer-style numpy SOA: vectorised
gravity + drag + life decay each step.  ``render`` rasterises the live
particles into the supplied RGBA frame as small filled disks
(brightened by remaining-life fraction so they fade out).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Per-style emission tables
# ---------------------------------------------------------------------------

# (color_choices, base_speed_range, life_range, size_range, count_multiplier)
# Colours are RGB 0-255 ints.  Particles randomly sample one of the
# colour swatches per spawn.
_STYLES: dict[str, dict] = {
    "shatter": {
        "colors": [
            (235, 235, 240),
            (210, 210, 215),
            (180, 180, 185),
            (160, 160, 165),
        ],
        "speed": (200.0, 400.0),
        "life":  (0.30, 0.80),
        "size":  (1.0, 2.0),
        "count_mul": 1.0,
        "cone_deg": 80.0,
    },
    "spark": {
        "colors": [
            (255, 230, 120),
            (255, 180,  60),
            (255, 120,  40),
            (255, 245, 200),
        ],
        "speed": (300.0, 600.0),
        "life":  (0.20, 0.40),
        "size":  (1.0, 1.0),
        "count_mul": 1.2,
        "cone_deg": 60.0,
    },
    "splatter": {
        "colors": [
            ( 95,  65,  40),
            (110,  75,  45),
            ( 80,  55,  35),
            ( 70,  45,  30),
        ],
        "speed": ( 50.0, 150.0),
        "life":  (0.80, 1.50),
        "size":  (2.0, 4.0),
        "count_mul": 1.0,
        "cone_deg": 90.0,
    },
    "splash": {
        "colors": [
            ( 80, 150, 240),
            (120, 200, 250),
            ( 50, 100, 200),
            (160, 220, 250),
        ],
        "speed": (150.0, 300.0),
        "life":  (0.50, 1.00),
        "size":  (1.0, 2.0),
        "count_mul": 1.0,
        "cone_deg": 75.0,
    },
    "ember": {
        # R > 220 keeps these bloom-friendly for any HDR-style pass.
        "colors": [
            (255, 140,  40),
            (255, 200,  80),
            (250, 100,  30),
            (255, 230, 130),
        ],
        "speed": (200.0, 500.0),
        "life":  (0.50, 1.00),
        "size":  (2.0, 3.0),
        "count_mul": 1.1,
        "cone_deg": 70.0,
    },
    "dust": {
        "colors": [
            (160, 155, 150),
            (190, 180, 165),
            (140, 135, 130),
            (175, 165, 145),
        ],
        "speed": ( 30.0, 100.0),
        "life":  (0.70, 1.20),
        "size":  (1.0, 2.0),
        "count_mul": 0.9,
        "cone_deg": 110.0,
    },
}


# Map material name → style.  Unknown materials fall back to ``dust``.
_MATERIAL_TO_STYLE: dict[str, str] = {
    "stone":       "shatter",
    "glass":       "shatter",
    "concrete":    "shatter",
    "ice":         "shatter",
    "iron":        "spark",
    "steel":       "spark",
    "metal":       "spark",
    "mud":         "splatter",
    "clay":        "splatter",
    "water":       "splash",
    "lava":        "ember",
    "lava_ground": "ember",
    "sand":        "dust",
    "wood":        "dust",
    "rubber":      "dust",
}


def style_for_material(name: str) -> str:
    """Return the particle style key for a material name.

    Unknown names default to ``"dust"``.
    """
    return _MATERIAL_TO_STYLE.get(name, "dust")


# ---------------------------------------------------------------------------
# Particle dataclass (returned by ``iter_particles`` for inspection)
# ---------------------------------------------------------------------------

@dataclass
class Particle:
    """A single live particle.

    The :class:`ParticleSystem` keeps its data in flat numpy arrays for
    speed; this class is the readable per-element view used by tests
    and tooling (via :meth:`ParticleSystem.iter_particles`).
    """
    position: tuple[float, float]
    velocity: tuple[float, float]
    color: tuple[int, int, int]
    life: float
    max_life: float
    size: float


# ---------------------------------------------------------------------------
# ParticleSystem
# ---------------------------------------------------------------------------

class ParticleSystem:
    """Pure-visual particles emitted at contact events.

    Materials configure emission style:

    * ``stone`` / ``glass`` / ``concrete`` / ``ice``   → ``shatter``
      (cone of small white-ish shards).
    * ``iron`` / ``steel`` / ``metal``                 → ``spark``
      (bright orange-red sparks).
    * ``mud`` / ``clay``                               → ``splatter``
      (medium-size brown blobs).
    * ``water``                                        → ``splash``
      (blue droplets).
    * ``lava`` / ``lava_ground``                       → ``ember``
      (glowing red-orange with heat).
    * ``sand`` / ``wood`` / ``rubber`` / default       → ``dust``
      (small grey particles).

    Particles obey gravity and air-drag (configurable) but never
    interact with hulls or each other.
    """

    def __init__(
        self,
        gravity: tuple[float, float] = (0.0, 196.0),
        air_drag: float = 0.95,
        max_particles: int = 2048,
        rng: random.Random | None = None,
        memory_budget: "object | None" = None,
    ) -> None:
        if max_particles <= 0:
            raise ValueError("max_particles must be positive")
        self.gravity: tuple[float, float] = (float(gravity[0]), float(gravity[1]))
        # ``air_drag`` here is the per-second velocity *retention* factor,
        # i.e. ``v *= air_drag ** dt`` each step.  0.95 means a particle
        # retains 95% of its velocity per second (gentle damping).
        self.air_drag: float = float(air_drag)
        self.max_particles: int = int(max_particles)
        # Optional MemoryBudget hook (Sprint 7).  When set, every
        # :meth:`emit` call checks the prospective live-particle count
        # against ``memory.max_particle_count`` and warns / raises via
        # :class:`MemoryBudgetExceeded` as configured.
        self.memory_budget = memory_budget
        self._rng: random.Random = rng if rng is not None else random.Random()

        n = self.max_particles
        self._pos:   np.ndarray = np.zeros((n, 2), dtype=np.float32)
        self._vel:   np.ndarray = np.zeros((n, 2), dtype=np.float32)
        self._col:   np.ndarray = np.zeros((n, 3), dtype=np.uint8)
        self._life:  np.ndarray = np.zeros(n,      dtype=np.float32)
        self._mlife: np.ndarray = np.zeros(n,      dtype=np.float32)
        self._size:  np.ndarray = np.zeros(n,      dtype=np.float32)
        self._count: int = 0

    # -- inspection ---------------------------------------------------------

    @property
    def count(self) -> int:
        """Number of live particles currently held by the system."""
        return self._count

    def __len__(self) -> int:
        return self._count

    def iter_particles(self) -> Iterable[Particle]:
        """Yield each live particle as a :class:`Particle` view.

        Provided for tests and editor tooling -- the renderer itself
        uses the flat numpy arrays directly.
        """
        for i in range(self._count):
            yield Particle(
                position=(float(self._pos[i, 0]), float(self._pos[i, 1])),
                velocity=(float(self._vel[i, 0]), float(self._vel[i, 1])),
                color=(int(self._col[i, 0]), int(self._col[i, 1]), int(self._col[i, 2])),
                life=float(self._life[i]),
                max_life=float(self._mlife[i]),
                size=float(self._size[i]),
            )

    def clear(self) -> None:
        """Drop every live particle."""
        self._count = 0

    # -- emission -----------------------------------------------------------

    def emit(
        self,
        world_point: tuple[float, float],
        impulse: tuple[float, float],
        material_name: str,
        count: int = 6,
    ) -> int:
        """Spawn ``count`` particles at ``world_point``.

        The emission cone is aligned with ``impulse``; a zero-vector
        impulse fans isotropically.  The style table (selected via
        ``material_name``) controls colour, speed, life, and size.

        Returns the number of particles actually spawned (may be
        clipped by ``max_particles``).
        """
        style_key = style_for_material(material_name)
        style = _STYLES[style_key]

        # Adjust requested count by the style's multiplier.
        want = max(0, int(round(count * style["count_mul"])))
        free = self.max_particles - self._count
        if free <= 0 or want <= 0:
            return 0
        spawn = min(free, want)

        # Memory-budget gate (Sprint 7).  When a budget is attached, the
        # prospective post-emit live-particle count is checked against
        # ``memory.max_particle_count``: warn at ``warn_at_fraction``,
        # raise ``MemoryBudgetExceeded`` past the cap.
        budget = self.memory_budget
        if budget is not None and spawn > 0:
            budget.check_particle_alloc(self._count + spawn)

        # Direction from impulse (points *out* of the surface).  If the
        # impulse is ~zero we just pick a random isotropic direction
        # per particle.
        ix, iy = float(impulse[0]), float(impulse[1])
        imag = math.hypot(ix, iy)
        if imag > 1e-6:
            dir_angle = math.atan2(iy, ix)
            isotropic = False
        else:
            dir_angle = 0.0
            isotropic = True
        half_cone = math.radians(float(style["cone_deg"])) * 0.5

        speed_lo, speed_hi = style["speed"]
        life_lo, life_hi   = style["life"]
        size_lo, size_hi   = style["size"]
        colors             = style["colors"]

        rng = self._rng
        base = self._count
        for k in range(spawn):
            i = base + k
            if isotropic:
                ang = rng.uniform(-math.pi, math.pi)
            else:
                ang = dir_angle + rng.uniform(-half_cone, half_cone)
            spd = rng.uniform(speed_lo, speed_hi)
            self._pos[i, 0] = float(world_point[0])
            self._pos[i, 1] = float(world_point[1])
            self._vel[i, 0] = math.cos(ang) * spd
            self._vel[i, 1] = math.sin(ang) * spd
            life = rng.uniform(life_lo, life_hi)
            self._life[i]  = life
            self._mlife[i] = life
            self._size[i]  = rng.uniform(size_lo, size_hi)
            c = colors[rng.randrange(len(colors))]
            self._col[i, 0] = c[0]
            self._col[i, 1] = c[1]
            self._col[i, 2] = c[2]
        self._count += spawn
        return spawn

    # -- emission from physics ---------------------------------------------

    def emit_from_contacts(
        self,
        contacts: Sequence,
        world=None,
        hulls=None,
        body_lookup: Mapping[int, object] | None = None,
        intensity_scale: float = 1.0,
    ) -> int:
        """Emit particles for every contact pair this frame.

        Parameters
        ----------
        contacts:
            Iterable of :class:`~pharos_engine.physics.world.ContactPair`-like
            objects exposing ``a``, ``b``, ``normal``, ``depth``, and
            ``point`` attributes (or the same names as dict keys).
        world:
            Optional :class:`PhysicsWorld`; used to look up the
            material name for hull ids ``a``/``b``.  If omitted, the
            system relies on ``body_lookup`` (mapping hull id to an
            object with a ``material_name`` attribute) instead.
        hulls:
            Reserved for future expansion -- unused for now but kept in
            the signature so callers don't have to change later.
        body_lookup:
            Optional mapping hull-id → body-like object (must expose
            ``material_name``).  Falls back to ``world._materials`` if
            provided.

        Returns the total number of particles spawned.
        """
        _ = hulls  # currently unused but reserved (see docstring).
        total = 0
        for contact in contacts:
            a, b, normal, depth, point = _unpack_contact(contact)
            # Heuristic count: penetration + a small floor.  Caps so a
            # single huge overlap can't spam the buffer.
            base_count = int(min(20, 4 + depth * 2.0) * intensity_scale)
            if base_count <= 0:
                continue

            mat_a = _material_for(a, world, body_lookup)
            mat_b = _material_for(b, world, body_lookup)

            # Side A: impulse vector points opposite contact normal
            # (away from B → out of A's surface, into the gap).
            imp_a = (-normal[0], -normal[1])
            imp_b = ( normal[0],  normal[1])

            # Spawn for each side with its own material; if a side
            # has no material we still emit dust so contacts always
            # leave a mark.
            total += self.emit(point, imp_a, mat_a or "", count=base_count // 2 or 1)
            total += self.emit(point, imp_b, mat_b or "", count=base_count // 2 or 1)
        return total

    # -- per-step update ---------------------------------------------------

    def step(self, dt: float) -> None:
        """Advance every live particle by ``dt`` seconds.

        Applies gravity (additive), drag (multiplicative
        ``air_drag**dt``), and life decay.  Dead particles are culled
        by swapping the last live particle into their slot -- O(N) and
        allocation-free.
        """
        if dt <= 0.0 or self._count == 0:
            return
        n = self._count
        # Drag: per-second retention raised to dt.
        if self.air_drag != 1.0:
            decay = float(self.air_drag) ** float(dt)
            self._vel[:n] *= decay
        # Gravity.
        self._vel[:n, 0] += float(self.gravity[0]) * dt
        self._vel[:n, 1] += float(self.gravity[1]) * dt
        # Position integration.
        self._pos[:n] += self._vel[:n] * dt
        # Life decay.
        self._life[:n] -= dt

        # Compact dead particles out.  ``alive`` mask is built once;
        # then we move the surviving rows to the front of every array.
        alive = self._life[:n] > 0.0
        live = int(alive.sum())
        if live < n:
            idx = np.nonzero(alive)[0]
            self._pos[:live]   = self._pos[idx]
            self._vel[:live]   = self._vel[idx]
            self._col[:live]   = self._col[idx]
            self._life[:live]  = self._life[idx]
            self._mlife[:live] = self._mlife[idx]
            self._size[:live]  = self._size[idx]
            self._count = live

    # -- rendering ---------------------------------------------------------

    def render(
        self,
        frame: np.ndarray,
        world_view: tuple[float, float, float, float],
    ) -> np.ndarray:
        """Composite live particles onto ``frame`` (RGB or RGBA uint8).

        ``world_view`` is ``(x0, y0, x1, y1)`` -- the world-space
        rectangle covered by the frame, matching ``RenderConfig``'s
        convention in ``render.py``.

        Each particle is drawn as a filled square (effectively a tiny
        disk for size ≤ 2 px) whose intensity scales with the
        remaining-life fraction so it fades out smoothly.  The same
        frame buffer is returned for convenience.
        """
        if self._count == 0:
            return frame
        h, w = frame.shape[:2]
        wx0, wy0, wx1, wy1 = world_view
        if wx1 == wx0 or wy1 == wy0:
            return frame
        scale_x = w / (wx1 - wx0)
        scale_y = h / (wy1 - wy0)

        n = self._count
        # World → pixel mapping.
        sx = ((self._pos[:n, 0] - wx0) * scale_x).astype(np.int32)
        sy = ((self._pos[:n, 1] - wy0) * scale_y).astype(np.int32)
        rad = np.maximum(0, self._size[:n].astype(np.int32))

        # Fade factor in [0, 1].
        with np.errstate(divide="ignore", invalid="ignore"):
            fade = np.where(self._mlife[:n] > 0.0,
                            np.clip(self._life[:n] / self._mlife[:n], 0.0, 1.0),
                            0.0)

        col = self._col[:n].astype(np.float32) * fade[:, None]
        col = np.clip(col, 0.0, 255.0).astype(np.uint8)

        has_alpha = (frame.ndim == 3 and frame.shape[2] == 4)
        for i in range(n):
            x, y, r = int(sx[i]), int(sy[i]), int(rad[i])
            if x + r < 0 or y + r < 0 or x - r >= w or y - r >= h:
                continue
            x0 = max(0, x - r)
            x1 = min(w, x + r + 1)
            y0 = max(0, y - r)
            y1 = min(h, y + r + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            frame[y0:y1, x0:x1, 0] = col[i, 0]
            frame[y0:y1, x0:x1, 1] = col[i, 1]
            frame[y0:y1, x0:x1, 2] = col[i, 2]
            if has_alpha:
                frame[y0:y1, x0:x1, 3] = 255
        return frame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unpack_contact(contact):
    """Accept either a ContactPair-like object or a dict; return the fields.

    ``contact`` may be:
      * a ``ContactPair`` (or any object with the matching attributes), or
      * a dict with the keys ``a``, ``b``, ``normal``, ``depth``, ``point``.
    """
    if isinstance(contact, dict):
        a = int(contact["a"])
        b = int(contact["b"])
        normal = tuple(contact["normal"])
        depth = float(contact["depth"])
        point = tuple(contact["point"])
    else:
        a = int(getattr(contact, "a"))
        b = int(getattr(contact, "b"))
        normal = tuple(getattr(contact, "normal"))
        depth = float(getattr(contact, "depth"))
        point = tuple(getattr(contact, "point"))
    if len(normal) != 2:
        raise ValueError("contact normal must be 2D")
    if len(point) != 2:
        raise ValueError("contact point must be 2D")
    return a, b, (float(normal[0]), float(normal[1])), depth, (float(point[0]), float(point[1]))


def _material_for(hull_id: int, world, body_lookup) -> str | None:
    """Best-effort hull-id → material name resolution.

    Tries ``body_lookup[hull_id].material_name`` first, then falls back
    to ``world``'s internal material-id table (``_material_ids``
    reversed).  Returns ``None`` if neither is available.
    """
    if body_lookup is not None:
        body = body_lookup.get(hull_id)
        if body is not None:
            name = getattr(body, "material_name", None)
            if name:
                return str(name)
    if world is not None:
        try:
            mid = int(world.hulls.material_id[hull_id])
        except (AttributeError, IndexError, TypeError):
            mid = None
        if mid is not None:
            ids = getattr(world, "_material_ids", None)
            if isinstance(ids, dict):
                for name, val in ids.items():
                    if val == mid:
                        return str(name)
    return None


__all__ = [
    "Particle",
    "ParticleSystem",
    "style_for_material",
]
