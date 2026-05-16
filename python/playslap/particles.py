"""
Particle system — CPU-simulated and GPU-simulated variants.

CPU variant (ParticleEmitter):
    emitter = ParticleEmitter(max_particles=200)
    emitter.emit(count=20, speed_range=(50, 200), color=(255, 100, 50),
                 lifetime=0.8, spread_angle=360.0)
    # in tick:
    emitter.tick(dt)
    # emitter.texture_data is a 64×64 RGBA uint8 array (shape (64, 64, 4))
    # suitable for pushing to a Layer._image_data

GPU variant (GpuParticleSystem):
    ps = GpuParticleSystem(ctx, max_particles=10_000)
    ps.set_emitter(pos=(640, 360), vel=(0, -100), spread=30,
                   lifetime=2.0, rate=500)
    # in tick:
    ps.tick(dt)
    # ps.particles_buf is a wgpu STORAGE buffer of Particle structs
"""
from __future__ import annotations

import math
import struct
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import wgpu
    from playslap.gpu.context import GPUContext


class ParticleEmitter:
    """CPU-simulated particle emitter that renders into a numpy texture."""

    def __init__(self, max_particles: int = 256, texture_size: int = 64):
        self._max = max_particles
        self._tex_size = texture_size

        # Parallel arrays — one slot per particle
        self._pos_x   = np.zeros(max_particles, dtype=np.float32)
        self._pos_y   = np.zeros(max_particles, dtype=np.float32)
        self._vel_x   = np.zeros(max_particles, dtype=np.float32)
        self._vel_y   = np.zeros(max_particles, dtype=np.float32)
        self._life    = np.zeros(max_particles, dtype=np.float32)   # <= 0 means dead
        self._max_life = np.ones(max_particles, dtype=np.float32)
        self._r       = np.zeros(max_particles, dtype=np.uint8)
        self._g       = np.zeros(max_particles, dtype=np.uint8)
        self._b       = np.zeros(max_particles, dtype=np.uint8)
        self._size    = np.ones(max_particles, dtype=np.int32)      # pixels

        # Output texture — shape (H, W, 4) uint8
        self._texture_data = np.zeros(
            (texture_size, texture_size, 4), dtype=np.uint8
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(
        self,
        count: int,
        position: tuple[float, float] = (0.0, 0.0),
        speed_range: tuple[float, float] = (50.0, 150.0),
        color: tuple[int, int, int] = (255, 255, 255),
        lifetime: float = 1.0,
        spread_angle: float = 360.0,
        gravity: float = 0.0,
    ) -> None:
        """Spawn up to *count* new particles from the dead-particle pool."""
        dead_idx = np.where(self._life <= 0)[0]
        slots = dead_idx[:count]
        if slots.size == 0:
            return

        n = slots.size
        # Random angle within the spread cone (centred on -Y / "up")
        half = math.radians(spread_angle * 0.5)
        angles = np.random.uniform(-half, half, size=n).astype(np.float32)

        speeds = np.random.uniform(
            speed_range[0], speed_range[1], size=n
        ).astype(np.float32)

        self._pos_x[slots] = float(position[0])
        self._pos_y[slots] = float(position[1])
        self._vel_x[slots] = np.sin(angles) * speeds
        self._vel_y[slots] = -np.cos(angles) * speeds  # -Y = upward in screen space
        self._life[slots]     = float(lifetime)
        self._max_life[slots] = float(lifetime)
        self._r[slots] = int(color[0])
        self._g[slots] = int(color[1])
        self._b[slots] = int(color[2])
        self._size[slots] = 2  # default 2 px square

        # Store gravity per-particle as a vel_y increment per tick.
        # gravity is applied each tick; we don't store it per particle —
        # the caller is expected to pass the same gravity to tick().

    def tick(self, dt: float, gravity: float = 0.0) -> None:
        """Advance simulation by *dt* seconds and rebuild the texture."""
        alive = self._life > 0
        if not np.any(alive):
            self._texture_data[:] = 0
            return

        # Integrate alive particles (vectorised)
        self._life[alive]  -= dt
        self._pos_x[alive] += self._vel_x[alive] * dt
        self._pos_y[alive] += self._vel_y[alive] * dt
        self._vel_y[alive] += gravity * dt

        # Kill particles whose life just ran out
        self._life[self._life < 0] = 0.0

        # Rebuild texture
        self._build_texture()

    @property
    def texture_data(self) -> np.ndarray:
        """64×64 RGBA uint8 numpy array (shape (H, W, 4))."""
        return self._texture_data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_texture(self) -> None:
        """Rasterise alive particles into _texture_data."""
        size = self._tex_size
        tex = self._texture_data
        tex[:] = 0  # clear

        alive_idx = np.where(self._life > 0)[0]
        if alive_idx.size == 0:
            return

        # Map world-space positions into texture coordinates via modulo wrap
        px = self._pos_x[alive_idx].astype(np.int32) % size
        py = self._pos_y[alive_idx].astype(np.int32) % size
        alphas = ((self._life[alive_idx] / self._max_life[alive_idx]) * 255).astype(np.uint8)
        rs = self._r[alive_idx]
        gs = self._g[alive_idx]
        bs = self._b[alive_idx]
        sizes = self._size[alive_idx]

        for i in range(len(alive_idx)):
            x, y = px[i], py[i]
            a = int(alphas[i])
            r, g, b = int(rs[i]), int(gs[i]), int(bs[i])
            half_s = max(1, int(sizes[i]) // 2)
            # Draw a small square; clamp to texture bounds
            y0 = max(0, y - half_s)
            y1 = min(size, y + half_s + 1)
            x0 = max(0, x - half_s)
            x1 = min(size, x + half_s + 1)
            tex[y0:y1, x0:x1, 0] = r
            tex[y0:y1, x0:x1, 1] = g
            tex[y0:y1, x0:x1, 2] = b
            tex[y0:y1, x0:x1, 3] = a


# ---------------------------------------------------------------------------
# Emitter shape / config types  (binding 3 + 4 in particle_simulate.wgsl)
# ---------------------------------------------------------------------------

class EmitterShape(IntEnum):
    POINT  = 0
    SPHERE = 1
    BOX    = 2
    CONE   = 3


class TurbulenceConfig:
    def __init__(self, strength: float = 0.0, speed: float = 1.0, scale: float = 0.003):
        self.strength = strength
        self.speed    = speed
        self.scale    = scale

    def to_bytes(self) -> bytes:
        return struct.pack("<4f", self.strength, self.speed, self.scale, 0.0)


class EmitterConfig:
    """Configuration for the particle emitter.

    Maps directly to the WGSL EmitterConfig uniform at binding 3.
    """

    def __init__(
        self,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        shape: EmitterShape = EmitterShape.POINT,
        extents: tuple[float, float, float] = (32.0, 32.0, 32.0),
        cone_height: float = 100.0,
        direction: tuple[float, float, float] = (0.0, 1.0, 0.0),
        speed_min: float = 50.0,
        speed_max: float = 150.0,
        spread_angle: float = 0.3,
    ):
        self.position     = position
        self.shape        = shape
        self.extents      = extents
        self.cone_height  = cone_height
        self.direction    = direction
        self.speed_min    = speed_min
        self.speed_max    = speed_max
        self.spread_angle = spread_angle

    def to_bytes(self) -> bytes:
        px, py, pz = self.position
        ex, ey, ez = self.extents
        dx, dy, dz = self.direction
        return struct.pack(
            "<16f",
            px, py, pz, float(int(self.shape)),
            ex, ey, ez, self.cone_height,
            dx, dy, dz, self.speed_min,
            self.speed_max, self.spread_angle, 0.0, 0.0,
        )


# ---------------------------------------------------------------------------
# GPU particle system
# ---------------------------------------------------------------------------

# Each Particle struct is 64 bytes (see shaders/particle_simulate.wgsl).
_PARTICLE_STRIDE = 64

# SimParams uniform buffer size: 19 × f32 + 5 × u32 = 96 bytes.
# Field order matches the WGSL struct exactly.
_SIM_PARAMS_FMT = "<" + "f" * 6 + "2I" + "f" * 13 + "3I"
_SIM_PARAMS_SIZE = struct.calcsize(_SIM_PARAMS_FMT)  # must be 96
assert _SIM_PARAMS_SIZE == 96, f"SimParams size mismatch: {_SIM_PARAMS_SIZE}"

# EmitterConfig uniform: 4 × vec4<f32> = 64 bytes (binding 3).
_EMITTER_CONFIG_SIZE = 64
# TurbulenceConfig uniform: 4 × f32 = 16 bytes (binding 4).
_TURBULENCE_CONFIG_SIZE = 16

# Resolve shader path at import time:
#   python/playslap/particles.py  →  shaders/particle_simulate.wgsl
_SHADER_PATH = (
    Path(__file__).parent.parent.parent / "shaders" / "particle_simulate.wgsl"
)


class GpuParticleSystem:
    """GPU-simulated particle system using a compute shader.

    All particle physics (gravity, drag, wind, age/lifetime) run on the GPU.
    The CPU only writes a 96-byte uniform buffer each frame and issues one
    compute dispatch.  Spawning is handled inside the shader — dead particle
    slots are re-initialised using per-thread pseudo-random hashing.

    Parameters
    ----------
    ctx:
        The active :class:`~playslap.gpu.context.GPUContext`.
    max_particles:
        Maximum number of simultaneously live particles.  The GPU buffer is
        allocated once at construction time.

    Attributes
    ----------
    particles_buf:
        ``wgpu.GPUBuffer`` (STORAGE | COPY_SRC) containing ``max_particles``
        ``Particle`` structs (64 bytes each).  Bind this to a render pipeline
        as a read-only storage buffer to draw the particles.
    """

    def __init__(self, ctx: "GPUContext", max_particles: int = 10_000) -> None:
        import wgpu  # noqa: PLC0415 — deferred so module is importable without wgpu

        self._ctx = ctx
        self.max_particles: int = max_particles

        device: "wgpu.GPUDevice" = ctx.device

        # ── Particle storage buffer ──────────────────────────────────────────
        self.particles_buf: "wgpu.GPUBuffer" = device.create_buffer(
            size=max_particles * _PARTICLE_STRIDE,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC,
            label="particle_buf",
        )

        # ── SimParams uniform buffer ─────────────────────────────────────────
        self.params_buf: "wgpu.GPUBuffer" = device.create_buffer(
            size=_SIM_PARAMS_SIZE,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="particle_params_buf",
        )

        # ── Dead-particle counter (1 × atomic<u32>) ──────────────────────────
        self.dead_buf: "wgpu.GPUBuffer" = device.create_buffer(
            size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="particle_dead_buf",
        )

        # ── EmitterConfig uniform buffer (binding 3, 64 bytes) ───────────────
        self.emitter_config_buf: "wgpu.GPUBuffer" = device.create_buffer(
            size=_EMITTER_CONFIG_SIZE,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="particle_emitter_config_buf",
        )

        # ── TurbulenceConfig uniform buffer (binding 4, 16 bytes) ────────────
        self.turbulence_buf: "wgpu.GPUBuffer" = device.create_buffer(
            size=_TURBULENCE_CONFIG_SIZE,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="particle_turbulence_buf",
        )

        # ── High-level emitter / turbulence config objects ───────────────────
        self.emitter_config: EmitterConfig = EmitterConfig()
        self.turbulence: TurbulenceConfig = TurbulenceConfig()

        # ── Lazy pipeline / bind-group ───────────────────────────────────────
        self._pipeline: "wgpu.GPUComputePipeline | None" = None
        self._bind_group: "wgpu.GPUBindGroup | None" = None

        # ── Emitter settings ─────────────────────────────────────────────────
        self._emitter: dict = {
            "pos":        (0.0, 0.0),
            "vel":        (0.0, 0.0),
            "spread":     10.0,
            "vel_spread": 50.0,
            "lifetime":   2.0,
            "rate":       200.0,
            "size":       4.0,
            "color":      (1.0, 1.0, 1.0, 1.0),
            "active":     False,
        }

        # ── World physics ────────────────────────────────────────────────────
        self.gravity: tuple[float, float] = (0.0, 98.0)  # pixels/s² downward
        self.wind: tuple[float, float] = (0.0, 0.0)
        self.drag: float = 0.5

        self._frame_index: int = 0

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def set_emitter(
        self,
        pos: tuple[float, float],
        vel: tuple[float, float] = (0.0, 0.0),
        spread: float = 10.0,
        vel_spread: float = 50.0,
        lifetime: float = 2.0,
        rate: float = 200.0,
        size: float = 4.0,
        color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ) -> None:
        """Configure (or update) the particle emitter.

        Parameters
        ----------
        pos:
            Emitter origin in world-space pixels ``(x, y)``.
        vel:
            Base emission velocity ``(vx, vy)`` in pixels/second.
        spread:
            Radius of the position scatter disk around *pos*.
        vel_spread:
            Half-range of random velocity scatter added to *vel*.
        lifetime:
            Seconds each spawned particle lives.
        rate:
            Target spawn rate in particles per second (informational; actual
            throughput depends on available dead slots each frame).
        size:
            Initial particle size in pixels.
        color:
            RGBA tuple (premultiplied), each component in ``[0, 1]``.
        """
        self._emitter.update(
            pos=tuple(pos),
            vel=tuple(vel),
            spread=float(spread),
            vel_spread=float(vel_spread),
            lifetime=float(lifetime),
            rate=float(rate),
            size=float(size),
            color=tuple(color),
            active=True,
        )

    def stop_emitter(self) -> None:
        """Disable the spawner; particles already alive continue to age out."""
        self._emitter["active"] = False

    def tick(self, dt: float) -> None:
        """Run one simulation step on the GPU.

        Writes the SimParams uniform buffer, resets the dead-particle counter,
        and dispatches the compute shader (one thread per particle slot).

        Parameters
        ----------
        dt:
            Frame delta time in seconds.
        """
        self._ensure_pipeline()

        device = self._ctx.device
        queue = self._ctx.queue

        # Reset dead counter to 0 before the sim pass.
        queue.write_buffer(self.dead_buf, 0, struct.pack("<I", 0))

        # Upload SimParams.
        queue.write_buffer(self.params_buf, 0, self._pack_sim_params(dt))

        # Upload EmitterConfig and TurbulenceConfig uniforms.
        queue.write_buffer(self.emitter_config_buf, 0, self.emitter_config.to_bytes())
        queue.write_buffer(self.turbulence_buf, 0, self.turbulence.to_bytes())

        # Dispatch: workgroup size 64, one thread per particle slot.
        workgroups = max(1, (self.max_particles + 63) // 64)
        encoder = device.create_command_encoder(label="particle_sim_enc")
        with encoder.begin_compute_pass(label="particle_sim_pass") as cp:
            cp.set_pipeline(self._pipeline)
            cp.set_bind_group(0, self._bind_group)
            cp.dispatch_workgroups(workgroups)
        queue.submit([encoder.finish()])

        self._frame_index = (self._frame_index + 1) & 0xFFFF_FFFF

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _pack_sim_params(self, dt: float) -> bytes:
        """Pack SimParams into 96 bytes matching the WGSL uniform struct."""
        em = self._emitter
        px, py = em["pos"]
        vx, vy = em["vel"]
        cr, cg, cb, ca = em["color"]

        return struct.pack(
            _SIM_PARAMS_FMT,
            # 6 floats — per-frame physics
            float(dt),
            float(self.gravity[0]),
            float(self.gravity[1]),
            float(self.drag),
            float(self.wind[0]),
            float(self.wind[1]),
            # 2 u32 — spawn control
            1 if em["active"] else 0,  # spawn_active
            self.max_particles,        # num_particles
            # 4 floats — spawn position / rate / spread
            float(px),
            float(py),
            float(em["rate"]),
            float(em["spread"]),
            # 5 floats — spawn velocity / lifetime / size
            float(vx),
            float(vy),
            float(em["vel_spread"]),
            float(em["lifetime"]),
            float(em["size"]),
            # 4 floats — spawn colour
            float(cr),
            float(cg),
            float(cb),
            float(ca),
            # 3 u32 — frame seed + two padding words
            self._frame_index,
            0,  # _pad
            0,  # _pad2
        )

    def _ensure_pipeline(self) -> None:
        """Lazily create the compute pipeline and bind group on first use."""
        if self._pipeline is not None:
            return

        import wgpu  # noqa: PLC0415

        device = self._ctx.device

        # ── Load and compile shader ──────────────────────────────────────────
        shader_src = _SHADER_PATH.read_text(encoding="utf-8")
        shader_module = device.create_shader_module(
            label="particle_simulate_shader",
            code=shader_src,
        )

        # ── Bind-group layout ────────────────────────────────────────────────
        bgl = device.create_bind_group_layout(
            label="particle_bgl",
            entries=[
                {
                    "binding":    0,
                    "visibility": wgpu.ShaderStage.COMPUTE,
                    "buffer":     {"type": wgpu.BufferBindingType.uniform},
                },
                {
                    "binding":    1,
                    "visibility": wgpu.ShaderStage.COMPUTE,
                    "buffer":     {"type": wgpu.BufferBindingType.storage},
                },
                {
                    "binding":    2,
                    "visibility": wgpu.ShaderStage.COMPUTE,
                    "buffer":     {"type": wgpu.BufferBindingType.storage},
                },
                {
                    "binding":    3,
                    "visibility": wgpu.ShaderStage.COMPUTE,
                    "buffer":     {"type": wgpu.BufferBindingType.uniform},
                },
                {
                    "binding":    4,
                    "visibility": wgpu.ShaderStage.COMPUTE,
                    "buffer":     {"type": wgpu.BufferBindingType.uniform},
                },
            ],
        )

        # ── Pipeline layout ──────────────────────────────────────────────────
        pipeline_layout = device.create_pipeline_layout(
            label="particle_pipeline_layout",
            bind_group_layouts=[bgl],
        )

        # ── Compute pipeline ─────────────────────────────────────────────────
        self._pipeline = device.create_compute_pipeline(
            label="particle_simulate_pipeline",
            layout=pipeline_layout,
            compute={
                "module":      shader_module,
                "entry_point": "simulate",
            },
        )

        # ── Bind group ───────────────────────────────────────────────────────
        self._bind_group = device.create_bind_group(
            label="particle_bg",
            layout=bgl,
            entries=[
                {
                    "binding": 0,
                    "resource": {
                        "buffer": self.params_buf,
                        "offset": 0,
                        "size":   _SIM_PARAMS_SIZE,
                    },
                },
                {
                    "binding": 1,
                    "resource": {
                        "buffer": self.particles_buf,
                        "offset": 0,
                        "size":   self.max_particles * _PARTICLE_STRIDE,
                    },
                },
                {
                    "binding": 2,
                    "resource": {
                        "buffer": self.dead_buf,
                        "offset": 0,
                        "size":   4,
                    },
                },
                {
                    "binding": 3,
                    "resource": {
                        "buffer": self.emitter_config_buf,
                        "offset": 0,
                        "size":   _EMITTER_CONFIG_SIZE,
                    },
                },
                {
                    "binding": 4,
                    "resource": {
                        "buffer": self.turbulence_buf,
                        "offset": 0,
                        "size":   _TURBULENCE_CONFIG_SIZE,
                    },
                },
            ],
        )
