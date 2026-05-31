"""Standalone thermal scaffold — per-particle + per-pixel temperatures.

This module is *not* wired into :class:`ParticleField` yet. It is a math
+ data-structure layer that the next pass can hand to the particle
field so each particle carries a temperature, each material decides how
that temperature relaxes toward ambient, and material ids flip when
thresholds are crossed (water → ice, lava → rock, …).

Three pieces:

* :class:`ThermalProfile` — frozen dataclass that holds the spawn /
  ambient temperature, the relaxation rate, and optional phase-change
  thresholds for one material. Six predefined profiles cover the demos
  the engine ships today (water, ice, lava, snow, sand, rock).
* :func:`step_temperatures` — vectorised per-particle relaxation
  ``T += (ambient - T) * decay * dt`` keyed by ``material_id``. Operates
  in place on the caller's array.
* :func:`detect_phase_changes` — vectorised threshold crossing test.
  Returns the new ``material_id`` for each particle. The caller is
  responsible for actually swapping the id and any colour / fragment
  side effects.
* :class:`TemperatureField` — 2-D temperature grid with stamping and
  diffusion. Wraps :class:`slappyengine.thermal.HeatField` so we reuse
  the conservative pairwise-flux solver that already ships in Phase B
  rather than rolling a new Laplacian here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from slappyengine.thermal import HeatField


__all__ = [
    "ThermalProfile",
    "WATER_THERMAL",
    "ICE_THERMAL",
    "LAVA_THERMAL",
    "SNOW_THERMAL",
    "SAND_THERMAL",
    "ROCK_THERMAL",
    "step_temperatures",
    "detect_phase_changes",
    "TemperatureField",
]


# ── Per-material thermal profile ────────────────────────────────────────────


@dataclass(frozen=True)
class ThermalProfile:
    """How temperature behaves for one material.

    Particles start at :attr:`initial_temperature`; each step their
    temperature relaxes toward :attr:`ambient_temperature` at rate
    :attr:`decay_per_sec`. Phase changes happen when temperature
    crosses :attr:`melt_at` (above → :attr:`melt_to_material`) or
    :attr:`freeze_at` (below → :attr:`freeze_to_material`).

    Parameters
    ----------
    initial_temperature
        Spawn temperature in degrees Celsius.
    ambient_temperature
        Equilibrium temperature the particle relaxes toward.
    decay_per_sec
        Fraction of the gap closed per second. ``0`` disables cooling;
        ``1`` produces near-instant equilibrium per integer second.
    melt_at, melt_to_material
        If ``melt_at`` is set, a particle whose temperature exceeds it
        flips to the material id named by ``melt_to_material``.
    freeze_at, freeze_to_material
        Symmetric — particle whose temperature drops below
        ``freeze_at`` flips to ``freeze_to_material``.
    """

    initial_temperature: float = 20.0
    ambient_temperature: float = 20.0
    decay_per_sec: float = 0.5

    melt_at: float | None = None
    melt_to_material: str | None = None
    freeze_at: float | None = None
    freeze_to_material: str | None = None


# Predefined profiles — calibrated to match the demo material set.
WATER_THERMAL = ThermalProfile(
    initial_temperature=20.0,
    ambient_temperature=20.0,
    decay_per_sec=0.3,
    freeze_at=0.0,
    freeze_to_material="ice",
)
ICE_THERMAL = ThermalProfile(
    initial_temperature=-5.0,
    ambient_temperature=20.0,
    decay_per_sec=0.2,
    melt_at=0.0,
    melt_to_material="water",
)
LAVA_THERMAL = ThermalProfile(
    initial_temperature=1200.0,
    ambient_temperature=20.0,
    decay_per_sec=0.05,
    freeze_at=700.0,
    freeze_to_material="rock",
)
SNOW_THERMAL = ThermalProfile(
    initial_temperature=-5.0,
    ambient_temperature=20.0,
    decay_per_sec=0.4,
    melt_at=2.0,
    melt_to_material="water",
)
SAND_THERMAL = ThermalProfile()  # thermally inert defaults; no phase changes
ROCK_THERMAL = ThermalProfile(
    initial_temperature=20.0,
    ambient_temperature=20.0,
)


# ── Vectorised per-particle ops ─────────────────────────────────────────────


def step_temperatures(
    particle_temperature: np.ndarray,
    particle_material_id: np.ndarray,
    profiles: Sequence[ThermalProfile],
    dt: float,
) -> np.ndarray:
    """Relax each particle's temperature toward its material's ambient.

    ``T += (ambient - T) * decay_per_sec * dt`` evaluated per material.
    Operates in place on ``particle_temperature`` and returns the same
    array for chaining.

    Parameters
    ----------
    particle_temperature
        ``(N,)`` float array, mutated in place.
    particle_material_id
        ``(N,)`` int array — index into ``profiles``.
    profiles
        One :class:`ThermalProfile` per material id.
    dt
        Seconds elapsed this step.
    """
    if particle_temperature.size == 0:
        return particle_temperature
    if dt <= 0.0:
        return particle_temperature

    ids = np.asarray(particle_material_id, dtype=np.int64)
    n_profiles = len(profiles)
    if n_profiles == 0:
        return particle_temperature

    ambients = np.array(
        [p.ambient_temperature for p in profiles], dtype=np.float64,
    )
    decays = np.array(
        [p.decay_per_sec for p in profiles], dtype=np.float64,
    )

    # Clamp out-of-range ids to 0 so we never index past the table; in
    # practice the particle field guarantees valid ids, but defensive
    # bounds keep the math from crashing on stale buffers.
    safe_ids = np.clip(ids, 0, max(0, n_profiles - 1))

    per_particle_ambient = ambients[safe_ids]
    per_particle_decay = decays[safe_ids]

    T = particle_temperature.astype(np.float64, copy=False)
    delta = (per_particle_ambient - T) * per_particle_decay * float(dt)
    particle_temperature[...] = (T + delta).astype(
        particle_temperature.dtype, copy=False,
    )
    return particle_temperature


def detect_phase_changes(
    particle_temperature: np.ndarray,
    particle_material_id: np.ndarray,
    profiles: Sequence[ThermalProfile],
    material_name_to_id: dict[str, int],
) -> np.ndarray:
    """Return the new material id for each particle after threshold checks.

    For every particle:

    * If its temperature is at or above its profile's ``melt_at`` and
      ``melt_to_material`` resolves via ``material_name_to_id``, the
      new id is the target material.
    * Else if its temperature is at or below ``freeze_at`` and
      ``freeze_to_material`` resolves, the new id is that target.
    * Otherwise the id is unchanged.

    Names that don't appear in ``material_name_to_id`` are silently
    treated as "no transition" — callers can omit ice's id from the map
    if ice isn't registered yet and water just stays liquid.

    Returns
    -------
    np.ndarray
        ``(N,)`` int32 array of new material ids.
    """
    n = particle_temperature.shape[0]
    out = np.asarray(particle_material_id, dtype=np.int32).copy()
    if n == 0:
        return out

    T = np.asarray(particle_temperature, dtype=np.float64)
    ids = out  # alias for readability; mutated below

    n_profiles = len(profiles)
    for material_id, profile in enumerate(profiles):
        if material_id >= n_profiles:
            break
        mask_this = ids == material_id
        if not mask_this.any():
            continue

        # Melt: T >= melt_at AND target known.
        if profile.melt_at is not None and profile.melt_to_material is not None:
            target = material_name_to_id.get(profile.melt_to_material)
            if target is not None:
                fire = mask_this & (T >= float(profile.melt_at))
                if fire.any():
                    ids[fire] = np.int32(target)
                    mask_this = ids == material_id  # refresh — some fired

        # Freeze: T <= freeze_at AND target known. Evaluated after melt
        # so the two thresholds can't both fire on the same particle.
        if (
            profile.freeze_at is not None
            and profile.freeze_to_material is not None
        ):
            target = material_name_to_id.get(profile.freeze_to_material)
            if target is not None:
                fire = mask_this & (T <= float(profile.freeze_at))
                if fire.any():
                    ids[fire] = np.int32(target)

    return out


# ── 2-D temperature field ───────────────────────────────────────────────────


@dataclass
class TemperatureField:
    """Per-pixel temperature grid backed by :class:`HeatField`.

    The grid lives at ``(height, width)`` shape — row-major like every
    other 2-D buffer in the engine. :meth:`stamp` paints a circular hot
    or cold region (lava puddle, campfire, ice block). :meth:`step`
    advances diffusion one frame. :meth:`sample` reads back a single
    pixel for the per-particle thermal coupling that the next pass will
    wire in.

    Reuses :class:`slappyengine.thermal.HeatField` for the diffusion
    math — same conservative pairwise-flux solver the fluid module uses.
    """

    width: int
    height: int
    ambient: float = 20.0
    diffusivity: float = 0.1
    grid: np.ndarray = field(init=False)
    _field: HeatField = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.width < 2 or self.height < 2:
            raise ValueError(
                "TemperatureField: width and height must each be ≥ 2; "
                f"got {self.width}x{self.height}"
            )
        self.grid = np.full(
            (self.height, self.width), float(self.ambient), dtype=np.float32,
        )
        # HeatField holds the grid by reference and mutates in place, so
        # writes to self.grid are visible to the solver and vice versa.
        self._field = HeatField(
            self.grid, conductivity=1.0, diffusivity=float(self.diffusivity),
        )

    # ----- stamping --------------------------------------------------------

    def stamp(self, x: int, y: int, radius: int, temperature: float) -> None:
        """Set a filled circle's temperature directly.

        Pixels strictly inside ``(x - cx)² + (y - cy)² ≤ radius²`` are
        overwritten with ``temperature``. No blending — the caller can
        run :meth:`step` afterwards to let the spot smear out.

        Out-of-bounds pixels are clipped silently.
        """
        if radius <= 0:
            # Treat radius 0 as "single pixel" so it's still visible to
            # the test harness rather than a silent no-op.
            if 0 <= x < self.width and 0 <= y < self.height:
                self.grid[y, x] = float(temperature)
            return

        x0 = max(0, x - radius)
        x1 = min(self.width, x + radius + 1)
        y0 = max(0, y - radius)
        y1 = min(self.height, y + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return

        ys = np.arange(y0, y1).reshape(-1, 1)
        xs = np.arange(x0, x1).reshape(1, -1)
        mask = (xs - x) ** 2 + (ys - y) ** 2 <= radius * radius
        self.grid[y0:y1, x0:x1][mask] = float(temperature)

    # ----- diffusion --------------------------------------------------------

    def step(self, dt: float) -> None:
        """Advance the temperature field by ``dt`` seconds of diffusion."""
        if dt <= 0.0:
            return
        # HeatField mutates self.grid in place via its held reference.
        self._field.step(float(dt), boundary="clamp")

    # ----- read-back -------------------------------------------------------

    def sample(self, x: int, y: int) -> float:
        """Return the temperature at pixel ``(x, y)``.

        Out-of-bounds samples return the ambient temperature so a
        particle wandering past the grid edge doesn't get a garbage
        reading.
        """
        if not (0 <= x < self.width and 0 <= y < self.height):
            return float(self.ambient)
        return float(self.grid[y, x])
