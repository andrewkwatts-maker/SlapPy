"""Particle-spawn helpers + headless Sim-field stub.

Game scripts (Ochema Circuit, Bullet Strata) consume two things from
this module:

* :class:`ParticleTemplate` — value-object passed into
  ``smoke_field.spawn(pos, count, template)``. Pure data.
* :class:`SimField` — Navier-Stokes-style fog / smoke grid. The
  real GPU implementation lives in the (private) particle pipeline;
  this stub gives headless tests + games-running-without-wgpu a
  no-op surface that doesn't crash. All accessors return sensible
  default values; no rendering happens.

If you need real fluid simulation, use :mod:`pharos_engine.fluid`
(Position-Based Fluids) instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Tuple


VelocityRange = Tuple[Tuple[float, float], Tuple[float, float]]
AngularRange = Tuple[float, float]
ColorRGBA = Tuple[int, int, int, int]


@dataclass
class ParticleTemplate:
    """Description of one spawn burst.

    Every field has a sensible default so scripts can override only what
    matters. Fields are intentionally permissive to keep the shim small —
    strict typing happens on the GPU side when real spawning runs.
    """
    velocity_range: VelocityRange = ((-1.0, 1.0), (-1.0, 1.0))
    lifetime: float = 1.0
    angular_vel_range: AngularRange = (0.0, 0.0)
    z: float = 0.0
    spread_angle: float = 0.0
    color: ColorRGBA = (255, 255, 255, 255)
    size: int = 4
    extra: dict = field(default_factory=dict)


class SimField:
    """Headless Sim-field stub.

    Implements every method Ochema's ``fog_system.py`` / ``smoke``
    pipeline calls. All operations are O(1) bookkeeping — no actual
    Navier-Stokes happens. Use :class:`SimField.atmosphere` to build a
    fog instance; ``size`` is a ``(w, h)`` tuple.
    """

    def __init__(self, size: tuple[int, int] | None = None,
                 gpu: Any = None) -> None:
        # ``gpu`` is accepted for API parity — bare ``SimField(gpu=None)``
        # is the headless-construction path used by tests and games that
        # haven't picked a grid size yet. Default to a small placeholder
        # grid so accessors stay sane.
        if size is None:
            size = (64, 64)
        self.size = (int(size[0]), int(size[1]))
        self.gpu = gpu
        self._next_handle = 0
        self._displacers: dict[int, dict[str, Any]] = {}
        # Forces are stored as a flat list so callers can iterate / filter
        # ``[f for f in sf._forces if f["id"] == handle]``. Each entry is a
        # dict carrying at least an ``"id"`` key.
        self._forces: list[dict[str, Any]] = []
        self._density = 0.0
        # CPU-mode density grid — populated lazily by ``atmosphere`` so
        # tests can probe ``sf._cpu_density is not None``. None on GPU.
        self._cpu_density: Any = None
        self._cpu_velocity: Any = None
        self._max_particles: int = 0
        # Phase-transition state for particle fields (rain hitting ground,
        # snow settling, etc.). Tests probe these directly.
        self._phase_z: float | None = None
        self._ground_damping: float = 0.0

    # ----- factories ---------------------------------------------------------
    @classmethod
    def atmosphere(cls, gpu: Any = None,
                   size: tuple[int, int] = (64, 64),
                   cfg: Any = None) -> "SimField":
        """Build an atmosphere field. ``gpu`` and ``cfg`` are accepted for
        API parity with the real implementation. In CPU mode (``gpu=None``)
        a numpy density grid + velocity field are allocated lazily so
        callers can sample / inspect the state without a GPU device."""
        f = cls(size=size)
        if gpu is None:
            try:
                import numpy as np
                w, h = f.size
                f._cpu_density = np.zeros((h, w), dtype=np.float32)
                f._cpu_velocity = np.zeros((h, w, 2), dtype=np.float32)
            except Exception:
                pass
        return f

    @classmethod
    def particles(cls, gpu: Any = None,
                  max_particles: int = 1024,
                  cfg: Any = None) -> "SimField":
        """Build a particle field (rain / snow / debris). ``max_particles``
        is stored on the instance under both ``max_particles`` and
        ``_max_particles`` (the latter is what some game tests probe)."""
        f = cls(size=(int(max_particles), 1))
        f.max_particles = int(max_particles)
        f._max_particles = int(max_particles)
        return f

    # ----- helpers -----------------------------------------------------------
    def _alloc_handle(self) -> int:
        h = self._next_handle
        self._next_handle += 1
        return h

    # ----- mutating ops ------------------------------------------------------
    def inject(self, position: tuple[float, float] = (0.0, 0.0),
               radius: float = 0.0, channel: str = "density",
               amount: float | None = None, *args: Any, **kwargs: Any) -> None:
        """Inject density / heat into the field over a small radius.

        Operates on the CPU density grid when present (gpu=None init).
        Falls through to no-op when running on GPU (the real
        implementation handles that via compute shader).

        ``value=`` is accepted as an alias for ``amount=`` — game scripts
        and tests use both spellings interchangeably.
        """
        if amount is None:
            amount = float(kwargs.pop("value", 0.0))
        if self._cpu_density is None:
            return
        try:
            import numpy as np
            h, w = self._cpu_density.shape
            cx, cy = float(position[0]), float(position[1])
            r = max(float(radius), 1.0)
            yy, xx = np.ogrid[:h, :w]
            mask = ((xx - cx) ** 2 + (yy - cy) ** 2) <= (r * r)
            self._cpu_density[mask] = np.maximum(
                self._cpu_density[mask], float(amount))
        except Exception:
            pass

    def sample(self, world_pos: tuple[float, float]) -> dict[str, float]:
        """Sample channels at a world / grid point. Returns a dict so
        callers can extract specific channels (``density`` / ``velocity``
        / ``temperature``) without unpacking magic; CPU-mode reads from
        the density grid + velocity field; GPU mode returns zeros (the
        real impl would async-readback)."""
        # Both long (``velocity_x``) and short (``vx``) keys are populated
        # so callers can use either spelling.
        out = {"density": 0.0, "vx": 0.0, "vy": 0.0,
               "velocity_x": 0.0, "velocity_y": 0.0}
        if self._cpu_density is None:
            return out
        try:
            x = int(world_pos[0]); y = int(world_pos[1])
            h, w = self._cpu_density.shape
            if 0 <= x < w and 0 <= y < h:
                out["density"] = float(self._cpu_density[y, x])
                if self._cpu_velocity is not None:
                    vx = float(self._cpu_velocity[y, x, 0])
                    vy = float(self._cpu_velocity[y, x, 1])
                    out["vx"] = vx
                    out["vy"] = vy
                    out["velocity_x"] = vx
                    out["velocity_y"] = vy
        except Exception:
            pass
        return out

    def seed_noise(self, mode: str = "perlin", octaves: int = 4,
                   seed: int = 0) -> None:
        """Pre-fill the density field with deterministic noise."""
        if self._cpu_density is None:
            return
        try:
            import numpy as np
            rng = np.random.default_rng(int(seed))
            h, w = self._cpu_density.shape
            base = rng.random((h, w), dtype=np.float32)
            self._cpu_density[:] = base * 0.5 + 0.25
        except Exception:
            pass

    def update(self, dt: float, encoder: Any = None,
               frame_index: int = 0) -> None:
        """Advance the simulation by ``dt`` seconds.

        Performs a proper Eulerian fog step on the CPU grid:
          1. Apply registered uniform forces to the velocity field.
          2. Semi-Lagrangian advect velocity along itself (self-advection).
          3. Semi-Lagrangian advect density along velocity.
          4. Cheap 5-point Laplacian diffusion on density.
          5. Light ambient decay (atmosphere always tends toward clear).
        Velocity/density wrap at the edges so the grid tiles cleanly
        across the world when ``as_density_layer().tile`` is honoured by
        the compositor. This is intentionally a small, numpy-only
        kernel — the real GPU implementation runs the same equations
        via compute shaders.
        """
        if self._cpu_density is None:
            return
        try:
            import numpy as np
            dt_s = float(dt) if dt is not None else 0.0
            if dt_s <= 0.0:
                return
            d = self._cpu_density
            v = self._cpu_velocity
            h, w = d.shape

            # 1. apply uniform forces (wind / convection) to velocity
            if v is not None and self._forces:
                fx = 0.0
                fy = 0.0
                for f in self._forces:
                    if f.get("kind") == "uniform":
                        fx += float(f.get("vx", 0.0))
                        fy += float(f.get("vy", 0.0))
                if fx != 0.0 or fy != 0.0:
                    v[..., 0] += fx * dt_s
                    v[..., 1] += fy * dt_s

            # build wrap-around source-coordinate arrays once
            yy, xx = np.meshgrid(
                np.arange(h, dtype=np.float32),
                np.arange(w, dtype=np.float32),
                indexing="ij",
            )

            if v is not None:
                # 2. self-advect velocity (semi-Lagrangian, periodic)
                sx = (xx - v[..., 0] * dt_s) % w
                sy = (yy - v[..., 1] * dt_s) % h
                x0 = sx.astype(np.int32); x1 = (x0 + 1) % w
                y0 = sy.astype(np.int32); y1 = (y0 + 1) % h
                tx = sx - x0; ty = sy - y0
                vx = v[..., 0]
                vy = v[..., 1]
                new_vx = (vx[y0, x0] * (1.0 - tx) * (1.0 - ty)
                          + vx[y0, x1] * tx * (1.0 - ty)
                          + vx[y1, x0] * (1.0 - tx) * ty
                          + vx[y1, x1] * tx * ty)
                new_vy = (vy[y0, x0] * (1.0 - tx) * (1.0 - ty)
                          + vy[y0, x1] * tx * (1.0 - ty)
                          + vy[y1, x0] * (1.0 - tx) * ty
                          + vy[y1, x1] * tx * ty)
                v[..., 0] = new_vx * 0.99   # mild viscosity
                v[..., 1] = new_vy * 0.99

                # 3. advect density along velocity (semi-Lagrangian)
                sx = (xx - v[..., 0] * dt_s) % w
                sy = (yy - v[..., 1] * dt_s) % h
                x0 = sx.astype(np.int32); x1 = (x0 + 1) % w
                y0 = sy.astype(np.int32); y1 = (y0 + 1) % h
                tx = sx - x0; ty = sy - y0
                d_new = (d[y0, x0] * (1.0 - tx) * (1.0 - ty)
                         + d[y0, x1] * tx * (1.0 - ty)
                         + d[y1, x0] * (1.0 - tx) * ty
                         + d[y1, x1] * tx * ty)
                d[:] = d_new

            # 4. 5-point Laplacian diffusion (toroidal)
            diff = 0.05 * float(min(dt_s * 60.0, 1.0))
            if diff > 0.0:
                lap = (np.roll(d, 1, 0) + np.roll(d, -1, 0)
                       + np.roll(d, 1, 1) + np.roll(d, -1, 1)
                       - 4.0 * d)
                d += diff * 0.25 * lap

            # 5. mild ambient decay so the world doesn't fog over forever
            d *= 0.998
            np.clip(d, 0.0, 1.0, out=d)
        except Exception:
            # On any numpy hiccup fall back to the old decay so callers
            # still see *some* time evolution — we never want update() to
            # raise into the game loop.
            try:
                self._cpu_density *= 0.995
            except Exception:
                pass

    def spawn(self, position: tuple[float, float], count: int,
              template: ParticleTemplate) -> int:
        """Emit a burst of particles. Increments the live count so
        ``sf.particle_count`` reflects emission. Returns a handle."""
        self._particle_count = getattr(self, "_particle_count", 0) + int(count)
        return self._alloc_handle()

    @property
    def particle_count(self) -> int:
        """Observable live-particle count (sum of spawn calls)."""
        return int(getattr(self, "_particle_count", 0))

    # ----- displacers --------------------------------------------------------
    def add_displacer(self, entity: Any, radius: float = 1.0,
                      strength: float = 1.0) -> int:
        h = self._alloc_handle()
        self._displacers[h] = {"entity": entity, "radius": float(radius),
                                "strength": float(strength)}
        return h

    def remove_displacer(self, handle: int) -> None:
        self._displacers.pop(handle, None)

    # ----- forces ------------------------------------------------------------
    def add_force_uniform(self, vx: float, vy: float) -> int:
        h = self._alloc_handle()
        self._forces.append({"id": h, "kind": "uniform",
                              "vx": float(vx), "vy": float(vy)})
        return h

    def add_force_radial(self, center: tuple[float, float],
                          strength: float = 1.0,
                          radius: float = 0.0) -> int:
        """Register a radial push/pull force at ``center``. Positive
        strength repels (explosion), negative attracts (vortex). The CPU
        update path treats radials as bookkeeping-only for now — full
        radial advection lives in the GPU compute path."""
        h = self._alloc_handle()
        self._forces.append({"id": h, "kind": "radial",
                              "cx": float(center[0]), "cy": float(center[1]),
                              "strength": float(strength),
                              "radius": float(radius)})
        return h

    def remove_force(self, handle: int) -> None:
        self._forces = [f for f in self._forces if f.get("id") != handle]

    # ----- phase transition --------------------------------------------------
    def set_phase_transition(self, z_threshold: float = 0.0,
                              ground_damping: float = 0.0) -> None:
        """Configure rain/snow ground-impact behaviour. Particles whose
        ``z`` drops below ``z_threshold`` get their velocity scaled by
        ``(1 - ground_damping)`` so they settle instead of bouncing. The
        real GPU pipeline reads ``_phase_z`` / ``_ground_damping`` from
        the field; CPU mode just stores them for inspection."""
        self._phase_z = float(z_threshold)
        self._ground_damping = float(ground_damping)

    # ----- accessors ---------------------------------------------------------
    def as_density_layer(self) -> Any:
        """Return a renderable density layer.

        The returned ``Layer2D`` is tagged for **global tiling** — fog is a
        world-spanning phenomenon, not a small sprite at the origin.
        Compositors that honour ``layer.tile`` repeat-sample the density
        grid across the camera rect using ``wrap_mode="repeat"``; the
        ``world_scale`` field tells them how many world units one full
        repeat covers (defaults to the grid size in pixels, which makes
        per-cell ≈ per-pixel for unscaled cameras).

        The pixel data follows the AAA fog convention: RGB = white,
        alpha = density. The game-side fog system multiplies its tint
        colour into the white layer when compositing; if the layer
        carried density in RGB too the result reads as a flat grey haze
        instead of the configured fog colour.
        """
        try:
            from pharos_engine.layer import Layer2D
            import numpy as np
            w, h = self.size
            layer = Layer2D(name="sim_field_density", width=w, height=h)
            # Global-tiling hint: fog should blanket the camera, not draw
            # as a 64x64 sprite at world origin.
            layer.tile = True
            layer.wrap_mode = "repeat"
            layer.world_scale = (float(w), float(h))
            if self._cpu_density is not None:
                arr = np.zeros((h, w, 4), dtype=np.uint8)
                d = np.clip(self._cpu_density, 0.0, 1.0)
                a = (d * 255.0).astype(np.uint8)
                arr[..., 0] = 255
                arr[..., 1] = 255
                arr[..., 2] = 255
                arr[..., 3] = a
                layer._image_data = arr
            return layer
        except Exception:
            return None

__all__ = ["ParticleTemplate", "SimField"]
