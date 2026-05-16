"""fluid_sim.py — Scene-wide GPU fluid simulation (Navier-Stokes advection-diffusion).

Supports fog, water, air, smoke, and any fluid by tuning FluidSimConfig parameters.
Integrates with the lighting system for god rays and applies forces to physics entities.

Architecture
------------
- Two ping-pong texture pairs: velocity (rgba16float) and density (rgba8unorm).
- Advection shader (fluid_sim_advect.wgsl):  semi-Lagrangian step every frame.
- Projection shader (fluid_project.wgsl):    20 Jacobi iterations → divergence-free velocity.
- Noise-init shader (fluid_noise_init.wgsl): one-shot initial conditions.
- Render shader (fluid_render.wgsl):         overlay drawn after combine pass.
- LOD zone frame-skipping: zone N runs every 2^N frames.
- Extended buffer: sim textures are screen_size + 2*pad_pixels on each side.
- Border wrap: edge pixels lerp toward initial conditions each step.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import wgpu
    from playslap.gpu.context import GPUContext

_SHADER_DIR = Path(__file__).parent.parent.parent / "shaders"

# ── Noise mode constants (must match fluid_noise_init.wgsl) ──────────────────
_NOISE_MODE = {"fbm": 0, "worley": 1, "uniform": 2}

# ── Velocity readback cadence ────────────────────────────────────────────────
_VEL_READBACK_PERIOD = 8   # update CPU velocity cache every N frames

# ── Pressure Jacobi iteration count per simulation step ─────────────────────
_JACOBI_ITERATIONS = 20


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FluidSimConfig:
    """All parameters that define a fluid type and simulation fidelity.

    Preset shortcuts (copy these fields to recreate well-known fluids):
      fog:   viscosity=0.2, diffusion=0.04, buoyancy=0.05, density_decay=0.998
      water: viscosity=0.05, diffusion=0.01, buoyancy=0.0, gravity=9.8, density_decay=1.0
      smoke: viscosity=0.1, diffusion=0.02, buoyancy=0.15, density_decay=0.995
    """
    # Buffer layout
    pad_pixels: int = 64             # extra pixels on each side beyond screen

    # LOD / fidelity zones
    lod_mode: str = "exp"            # "exp" | "log" | "uniform"
    lod_zones: int = 4               # concentric zones; zone 0 = center (full rate)

    # Physics parameters
    viscosity: float = 0.1           # 0 = inviscid, 1 = very viscous
    diffusion: float = 0.02          # scalar field spread rate
    buoyancy: float = 0.0            # upward force on warmer fluid (smoke/fog)
    gravity: float = 0.0             # downward pull (set >0 for water/liquids)
    density_decay: float = 0.995     # per-frame density loss (evaporation)
    velocity_decay: float = 0.99     # per-frame velocity damping

    # Initial conditions
    init_mode: str = "noise"         # "noise" | "texture" | "zero"
    noise_type: str = "fbm"          # "fbm" | "worley" | "uniform"
    noise_scale: float = 0.003       # noise frequency
    noise_seed: int = 42
    init_texture_path: str = ""      # PNG path (used when init_mode="texture")

    # Lighting integration
    god_rays: bool = True            # feed density into directional light scattering
    caustics: bool = False           # generate caustic patterns (stub)

    # Entity forces
    force_strength: float = 50.0    # world-space force units per unit density

    # Render overlay
    render_tint: tuple[float, float, float] = (0.8, 0.9, 1.0)
    render_alpha_scale: float = 1.0


# ─────────────────────────────────────────────────────────────────────────────
#  Preset factories
# ─────────────────────────────────────────────────────────────────────────────

def fog_config() -> FluidSimConfig:
    return FluidSimConfig(viscosity=0.2, diffusion=0.04, buoyancy=0.05,
                          density_decay=0.998, render_tint=(0.8, 0.9, 1.0))

def water_config() -> FluidSimConfig:
    return FluidSimConfig(viscosity=0.05, diffusion=0.01, buoyancy=0.0,
                          gravity=9.8, density_decay=1.0,
                          render_tint=(0.2, 0.3, 0.7))

def smoke_config() -> FluidSimConfig:
    return FluidSimConfig(viscosity=0.1, diffusion=0.02, buoyancy=0.15,
                          density_decay=0.995, render_tint=(0.3, 0.3, 0.3))


# ─────────────────────────────────────────────────────────────────────────────
#  Main simulation class
# ─────────────────────────────────────────────────────────────────────────────

class GlobalFluidSim:
    """Scene-wide fluid simulation running in GPU world space.

    Lifetime
    --------
    1. Instantiated by ``Engine.enable_fluid_sim()``.
    2. ``initialize()`` is called immediately after construction.
    3. ``dispatch(encoder, dt, frame_index)`` is called from ``_draw()`` each frame.
    """

    def __init__(self, gpu: "GPUContext", screen_w: int, screen_h: int,
                 cfg: FluidSimConfig | None = None) -> None:
        self._gpu = gpu
        self._screen_w = screen_w
        self._screen_h = screen_h
        self.cfg = cfg or FluidSimConfig()

        pad = self.cfg.pad_pixels
        self._sim_w = screen_w + 2 * pad
        self._sim_h = screen_h + 2 * pad

        # GPU textures (created in initialize)
        self._vel_tex_a: "wgpu.GPUTexture | None" = None
        self._vel_tex_b: "wgpu.GPUTexture | None" = None
        self._den_tex_a: "wgpu.GPUTexture | None" = None
        self._den_tex_b: "wgpu.GPUTexture | None" = None
        self._initial_den_tex: "wgpu.GPUTexture | None" = None
        self._pressure_tex_a: "wgpu.GPUTexture | None" = None
        self._pressure_tex_b: "wgpu.GPUTexture | None" = None
        self._god_ray_buf: "wgpu.GPUBuffer | None" = None

        # Velocity readback
        self._vel_readback_buf: "wgpu.GPUBuffer | None" = None
        self._vel_cache: np.ndarray | None = None   # (sim_h, sim_w, 2) float32
        self._readback_pending: bool = False

        # Compute pipelines
        self._pipeline_advect = None
        self._pipeline_project = None
        self._pipeline_noise_init = None
        self._pipeline_render = None

        # Uniform buffers
        self._sim_params_buf: "wgpu.GPUBuffer | None" = None
        self._noise_params_buf: "wgpu.GPUBuffer | None" = None
        self._render_params_buf: "wgpu.GPUBuffer | None" = None
        self._project_params_buf: "wgpu.GPUBuffer | None" = None

        # Ping-pong state: which texture is the current "read" source
        self._ping = True   # True → A is read source, B is write; False → B→A

        self._initialized = False

    # ── Public API ────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create GPU textures, compile shaders, upload initial conditions."""
        import wgpu as _wgpu
        device = self._gpu.device

        sw, sh = self._sim_w, self._sim_h

        def make_tex(fmt, usage, label, w=sw, h=sh):
            return device.create_texture(
                size=(w, h, 1), format=fmt, usage=usage,
                mip_level_count=1, sample_count=1, label=label,
            )

        vel_fmt = _wgpu.TextureFormat.rgba16float
        den_fmt = _wgpu.TextureFormat.rgba8unorm
        prs_fmt = _wgpu.TextureFormat.r32float

        storage_rw = _wgpu.TextureUsage.STORAGE_BINDING
        tex_binding = _wgpu.TextureUsage.TEXTURE_BINDING
        copy_src = _wgpu.TextureUsage.COPY_SRC
        copy_dst = _wgpu.TextureUsage.COPY_DST

        vel_usage = storage_rw | copy_src | copy_dst
        den_usage = storage_rw | tex_binding | copy_src | copy_dst
        prs_usage = storage_rw

        self._vel_tex_a = make_tex(vel_fmt, vel_usage, "fluid_vel_a")
        self._vel_tex_b = make_tex(vel_fmt, vel_usage, "fluid_vel_b")
        self._den_tex_a = make_tex(den_fmt, den_usage, "fluid_den_a")
        self._den_tex_b = make_tex(den_fmt, den_usage, "fluid_den_b")

        # Initial density — sampled (not storage) so it can be a texture_2d in WGSL
        self._initial_den_tex = make_tex(den_fmt, tex_binding | copy_dst, "fluid_den_init")

        self._pressure_tex_a = make_tex(prs_fmt, prs_usage, "fluid_prs_a")
        self._pressure_tex_b = make_tex(prs_fmt, prs_usage, "fluid_prs_b")

        # God-ray storage buffer: one f32 per screen pixel
        self._god_ray_buf = device.create_buffer(
            size=self._screen_w * self._screen_h * 4,
            usage=_wgpu.BufferUsage.STORAGE | _wgpu.BufferUsage.COPY_DST,
            label="fluid_god_ray",
        )

        # Velocity readback buffer (MAP_READ, updated every 8 frames).
        # bytes_per_row must be 256-aligned; rgba16float = 8 bytes/pixel.
        _raw_bpr = sw * 8
        _aligned_bpr = (_raw_bpr + 255) & ~255
        self._vel_readback_buf = device.create_buffer(
            size=_aligned_bpr * sh,
            usage=_wgpu.BufferUsage.COPY_DST | _wgpu.BufferUsage.MAP_READ,
            label="fluid_vel_readback",
        )

        # Uniform buffers
        self._sim_params_buf = device.create_buffer(
            size=self._sim_params_size(),
            usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
            label="fluid_sim_params",
        )
        self._noise_params_buf = device.create_buffer(
            size=32,
            usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
            label="fluid_noise_params",
        )
        self._render_params_buf = device.create_buffer(
            size=48,
            usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
            label="fluid_render_params",
        )
        self._project_params_buf = device.create_buffer(
            size=32,
            usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
            label="fluid_project_params",
        )

        # Compile compute pipelines
        self._pipeline_advect  = self._compile("fluid_sim_advect.wgsl",  "advect_main",  "fluid_advect")
        self._pipeline_project = self._compile("fluid_project.wgsl",     "project_main", "fluid_project")
        self._pipeline_noise   = self._compile("fluid_noise_init.wgsl",  "noise_init_main", "fluid_noise_init")
        # NOTE: fluid_render.wgsl is compiled lazily when we have scene textures to bind.

        # Generate and upload initial conditions
        self._upload_initial_conditions()

        self._initialized = True

    def dispatch(self, encoder, dt: float, frame_index: int) -> None:
        """Run one simulation step. LOD zone skipping applied per zone."""
        if not self._initialized:
            return

        device = self._gpu.device
        sw, sh = self._sim_w, self._sim_h
        wg_x, wg_y = (sw + 7) // 8, (sh + 7) // 8

        for zone in range(self.cfg.lod_zones):
            zone_skip = 1 << zone  # zone 0=1, zone 1=2, zone 2=4, zone 3=8
            if (frame_index % zone_skip) != 0:
                continue  # skip this zone this frame

            # Write sim params for this zone
            self._write_sim_params(dt, zone, zone_skip)

            # ── Advection pass ──────────────────────────────────────────────
            vel_read, vel_write, den_read, den_write = self._ping_pong_textures()
            enc = device.create_command_encoder(label=f"fluid_advect_z{zone}")
            cp = enc.begin_compute_pass()
            cp.set_pipeline(self._pipeline_advect)
            bg = self._make_advect_bg(vel_read, vel_write, den_read, den_write)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()
            device.queue.submit([enc.finish()])
            self._flip_ping_pong()

            # ── Pressure projection (20 Jacobi iterations) ──────────────────
            self._run_projection(wg_x, wg_y)

        # ── Velocity readback (every _VEL_READBACK_PERIOD frames) ────────────
        if (frame_index % _VEL_READBACK_PERIOD) == 0:
            self._schedule_vel_readback()

    def apply_force(self, x: float, y: float, vx: float, vy: float,
                    radius: float = 20.0) -> None:
        """Inject a velocity impulse at world position (x, y).

        Called by the engine for physics entities or user scripts.
        The impulse is written directly to the velocity texture via queue.write_texture
        over a circular region of the given radius.
        """
        if not self._initialized:
            return

        import wgpu as _wgpu
        pad = self.cfg.pad_pixels
        device = self._gpu.device

        # Convert world coords → sim coords
        sim_cx = int(x) + pad
        sim_cy = int(y) + pad
        r = int(radius)

        # Build a small patch of rgba16float data centred at (sim_cx, sim_cy)
        patch_size = 2 * r + 1
        patch = np.zeros((patch_size, patch_size, 4), dtype=np.float16)
        # We'll blend additive velocity into existing pixels by overwriting only
        # those within the circle. For simplicity we read back current vel from
        # cache and add to it; for high-frequency forces a dedicated impulse
        # shader is preferred but this covers the common case.
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    px, py = dx + r, dy + r
                    # Read cached velocity if available
                    cx = sim_cx + dx
                    cy = sim_cy + dy
                    cur_vx, cur_vy = 0.0, 0.0
                    if (self._vel_cache is not None and
                            0 <= cy < self._sim_h and 0 <= cx < self._sim_w):
                        cur_vx = float(self._vel_cache[cy, cx, 0])
                        cur_vy = float(self._vel_cache[cy, cx, 1])
                    patch[py, px, 0] = np.float16(cur_vx + vx)
                    patch[py, px, 1] = np.float16(cur_vy + vy)
                    patch[py, px, 3] = np.float16(1.0)

        # Clamp origin to valid texture region
        x0 = max(0, sim_cx - r)
        y0 = max(0, sim_cy - r)
        x1 = min(self._sim_w, sim_cx + r + 1)
        y1 = min(self._sim_h, sim_cy + r + 1)
        pw = x1 - x0
        ph = y1 - y0
        if pw <= 0 or ph <= 0:
            return

        # Crop patch to valid region
        crop_x = x0 - (sim_cx - r)
        crop_y = y0 - (sim_cy - r)
        patch_crop = patch[crop_y:crop_y + ph, crop_x:crop_x + pw, :]

        # bytes_per_row must be 256-aligned for write_texture as well.
        raw_bpr = pw * 8  # 4×f16 = 8 bytes/pixel
        aligned_bpr = (raw_bpr + 255) & ~255

        if aligned_bpr > raw_bpr:
            # Pad each row of the crop to the aligned stride.
            padded = np.zeros((ph, aligned_bpr // 8, 4), dtype=np.float16)
            padded[:, :pw, :] = patch_crop
            upload_data = padded.tobytes()
        else:
            upload_data = patch_crop.tobytes()

        vel_write = self._vel_tex_b if self._ping else self._vel_tex_a
        device.queue.write_texture(
            {"texture": vel_write, "mip_level": 0, "origin": (x0, y0, 0)},
            upload_data,
            {"bytes_per_row": aligned_bpr, "rows_per_image": ph},
            (pw, ph, 1),
        )

    def sample_velocity(self, x: float, y: float) -> tuple[float, float]:
        """CPU readback of fluid velocity at world position.

        Returns cached value (updated every _VEL_READBACK_PERIOD frames).
        Returns (0.0, 0.0) if cache is not yet populated.
        """
        if self._vel_cache is None:
            return (0.0, 0.0)
        pad = self.cfg.pad_pixels
        cx = int(x) + pad
        cy = int(y) + pad
        cx = max(0, min(self._sim_w - 1, cx))
        cy = max(0, min(self._sim_h - 1, cy))
        vx = float(self._vel_cache[cy, cx, 0])
        vy = float(self._vel_cache[cy, cx, 1])
        return (vx, vy)

    @property
    def density_tex(self) -> "wgpu.GPUTexture":
        """Current density texture (rgba8unorm, R=density, G=temperature)."""
        return self._den_tex_a if self._ping else self._den_tex_b

    @property
    def velocity_tex(self) -> "wgpu.GPUTexture":
        """Current velocity texture (rgba16float, RG=vx/vy)."""
        return self._vel_tex_a if self._ping else self._vel_tex_b

    @property
    def god_ray_buf(self) -> "wgpu.GPUBuffer | None":
        """Storage buffer with per-screen-pixel god-ray attenuation (density²)."""
        return self._god_ray_buf

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compile(self, shader_file: str, entry_point: str, label: str):
        device = self._gpu.device
        src = (_SHADER_DIR / shader_file).read_text(encoding="utf-8")
        shader = device.create_shader_module(code=src, label=label)
        return device.create_compute_pipeline(
            layout="auto",
            compute={"module": shader, "entry_point": entry_point},
            label=label,
        )

    def _sim_params_size(self) -> int:
        # SimParams struct: 2×u32 + 2×u32 + 7×f32 + 2×u32 + 2×u32 = 15 fields × 4B = 60 → align to 64
        return 64

    def _write_sim_params(self, dt: float, zone: int, zone_skip: int) -> None:
        c = self.cfg
        # struct SimParams layout (from fluid_sim_advect.wgsl):
        # sim_w, sim_h, pad_x, pad_y,          (4×u32)
        # dt, viscosity, diffusion,             (3×f32)
        # buoyancy, gravity,                    (2×f32)
        # density_decay, velocity_decay,        (2×f32)
        # zone, zone_skip,                      (2×u32)
        # _pad: vec2<u32>                       (2×u32)
        data = struct.pack(
            "<4I 7f 4I",
            self._sim_w, self._sim_h, c.pad_pixels, c.pad_pixels,
            dt, c.viscosity, c.diffusion, c.buoyancy, c.gravity,
            c.density_decay, c.velocity_decay,
            zone, zone_skip, 0, 0,
        )
        self._gpu.device.queue.write_buffer(self._sim_params_buf, 0, data)

    def _ping_pong_textures(self):
        """Return (vel_read, vel_write, den_read, den_write) for current ping-pong state."""
        if self._ping:
            return self._vel_tex_a, self._vel_tex_b, self._den_tex_a, self._den_tex_b
        else:
            return self._vel_tex_b, self._vel_tex_a, self._den_tex_b, self._den_tex_a

    def _flip_ping_pong(self) -> None:
        self._ping = not self._ping

    def _make_advect_bg(self, vel_read, vel_write, den_read, den_write):
        import wgpu as _wgpu
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_advect.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._sim_params_buf}},
                {"binding": 1, "resource": vel_read.create_view(
                    format="rgba16float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 2, "resource": vel_write.create_view(
                    format="rgba16float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 3, "resource": den_read.create_view(
                    format="rgba8unorm",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 4, "resource": den_write.create_view(
                    format="rgba8unorm",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 5, "resource": self._initial_den_tex.create_view()},
            ],
        )

    def _run_projection(self, wg_x: int, wg_y: int) -> None:
        """Run 20 Jacobi pressure iterations then subtract gradient from velocity."""
        import wgpu as _wgpu
        device = self._gpu.device

        # Write project params: Jacobi pass (is_subtract_pass=0)
        self._write_project_params(is_subtract=False)

        prs_ping = True  # True → prs_a read, prs_b write

        for _ in range(_JACOBI_ITERATIONS):
            vel_read, vel_write, _, _ = self._ping_pong_textures()
            if prs_ping:
                prs_read, prs_write = self._pressure_tex_a, self._pressure_tex_b
            else:
                prs_read, prs_write = self._pressure_tex_b, self._pressure_tex_a

            enc = device.create_command_encoder(label="fluid_jacobi")
            cp = enc.begin_compute_pass()
            cp.set_pipeline(self._pipeline_project)
            bg = self._make_project_bg(vel_read, vel_write, prs_read, prs_write)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()
            device.queue.submit([enc.finish()])
            prs_ping = not prs_ping

        # Gradient subtraction pass
        self._write_project_params(is_subtract=True)
        vel_read, vel_write, _, _ = self._ping_pong_textures()
        if prs_ping:
            prs_read, prs_write = self._pressure_tex_a, self._pressure_tex_b
        else:
            prs_read, prs_write = self._pressure_tex_b, self._pressure_tex_a

        enc = device.create_command_encoder(label="fluid_grad_sub")
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self._pipeline_project)
        bg = self._make_project_bg(vel_read, vel_write, prs_read, prs_write)
        cp.set_bind_group(0, bg)
        cp.dispatch_workgroups(wg_x, wg_y, 1)
        cp.end()
        device.queue.submit([enc.finish()])
        self._flip_ping_pong()  # vel_write is now the new read source

    def _write_project_params(self, is_subtract: bool) -> None:
        data = struct.pack(
            "<2I f I 4I",
            self._sim_w, self._sim_h, 1.0, int(is_subtract),
            0, 0, 0, 0,
        )
        self._gpu.device.queue.write_buffer(self._project_params_buf, 0, data)

    def _make_project_bg(self, vel_read, vel_write, prs_read, prs_write):
        import wgpu as _wgpu
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_project.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._project_params_buf}},
                {"binding": 1, "resource": vel_read.create_view(
                    format="rgba16float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 2, "resource": vel_write.create_view(
                    format="rgba16float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 3, "resource": prs_read.create_view(
                    format="r32float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
                {"binding": 4, "resource": prs_write.create_view(
                    format="r32float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
            ],
        )

    def _upload_initial_conditions(self) -> None:
        """Generate and upload initial density field based on cfg.init_mode."""
        c = self.cfg
        device = self._gpu.device
        sw, sh = self._sim_w, self._sim_h

        if c.init_mode == "zero":
            data = np.zeros((sh, sw, 4), dtype=np.uint8)
            self._upload_den_data(data)

        elif c.init_mode == "texture" and c.init_texture_path:
            from PIL import Image
            img = Image.open(c.init_texture_path).convert("RGBA").resize((sw, sh))
            data = np.asarray(img, dtype=np.uint8)
            self._upload_den_data(data)

        else:
            # "noise" — run fluid_noise_init.wgsl on GPU
            # We write into a temporary storage-compatible texture, then copy to initial_den_tex.
            import wgpu as _wgpu

            # Temporary output texture with STORAGE_BINDING so shader can write to it.
            tmp_tex = device.create_texture(
                size=(sw, sh, 1),
                format=_wgpu.TextureFormat.rgba8unorm,
                usage=_wgpu.TextureUsage.STORAGE_BINDING | _wgpu.TextureUsage.COPY_SRC,
                mip_level_count=1, sample_count=1,
                label="fluid_noise_tmp",
            )

            # Write noise params
            noise_mode = _NOISE_MODE.get(c.noise_type, 0)
            data = struct.pack(
                "<2I 2I f 3f",
                sw, sh, noise_mode, c.noise_seed,
                c.noise_scale, 0.0, 0.0, 0.0,
            )
            device.queue.write_buffer(self._noise_params_buf, 0, data)

            bg = device.create_bind_group(
                layout=self._pipeline_noise.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": self._noise_params_buf}},
                    {"binding": 1, "resource": tmp_tex.create_view(
                        format="rgba8unorm",
                        usage=_wgpu.TextureUsage.STORAGE_BINDING,
                    )},
                ],
            )

            enc = device.create_command_encoder(label="fluid_noise_init")
            cp = enc.begin_compute_pass()
            cp.set_pipeline(self._pipeline_noise)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups((sw + 7) // 8, (sh + 7) // 8, 1)
            cp.end()
            # Copy noise output → initial_den_tex and density ping-pong textures
            enc.copy_texture_to_texture(
                {"texture": tmp_tex, "mip_level": 0, "origin": (0, 0, 0)},
                {"texture": self._initial_den_tex, "mip_level": 0, "origin": (0, 0, 0)},
                (sw, sh, 1),
            )
            enc.copy_texture_to_texture(
                {"texture": tmp_tex, "mip_level": 0, "origin": (0, 0, 0)},
                {"texture": self._den_tex_a, "mip_level": 0, "origin": (0, 0, 0)},
                (sw, sh, 1),
            )
            enc.copy_texture_to_texture(
                {"texture": tmp_tex, "mip_level": 0, "origin": (0, 0, 0)},
                {"texture": self._den_tex_b, "mip_level": 0, "origin": (0, 0, 0)},
                (sw, sh, 1),
            )
            device.queue.submit([enc.finish()])
            tmp_tex.destroy()
            return  # textures populated via copy

        # Upload initial data also into the ping-pong density textures
        self._upload_den_data_to_tex(data, self._den_tex_a)
        self._upload_den_data_to_tex(data, self._den_tex_b)

    def _upload_den_data(self, data: np.ndarray) -> None:
        """Upload numpy rgba8 array to initial_den_tex."""
        self._upload_den_data_to_tex(data, self._initial_den_tex)

    def _upload_den_data_to_tex(self, data: np.ndarray, tex) -> None:
        device = self._gpu.device
        sh, sw = data.shape[:2]
        raw_bpr = sw * 4  # rgba8unorm = 4 bytes/pixel
        aligned_bpr = (raw_bpr + 255) & ~255
        if aligned_bpr > raw_bpr:
            padded = np.zeros((sh, aligned_bpr // 4, 4), dtype=np.uint8)
            padded[:, :sw, :] = data[:, :sw, :]
            upload = padded.tobytes()
        else:
            upload = data.tobytes()
        device.queue.write_texture(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
            upload,
            {"bytes_per_row": aligned_bpr, "rows_per_image": sh},
            (sw, sh, 1),
        )

    def _schedule_vel_readback(self) -> None:
        """Copy velocity texture to MAP_READ buffer for CPU sampling."""
        if not self._initialized:
            return
        import wgpu as _wgpu
        device = self._gpu.device
        vel_tex = self.velocity_tex

        # bytes_per_row must be a multiple of 256 (WebGPU requirement).
        # rgba16float = 8 bytes/pixel.
        raw_bpr = self._sim_w * 8
        aligned_bpr = (raw_bpr + 255) & ~255

        # Readback buffer must accommodate the aligned stride.
        needed_size = aligned_bpr * self._sim_h
        if self._vel_readback_buf is None or self._vel_readback_buf.size < needed_size:
            if self._vel_readback_buf is not None:
                self._vel_readback_buf.destroy()
            self._vel_readback_buf = device.create_buffer(
                size=needed_size,
                usage=_wgpu.BufferUsage.COPY_DST | _wgpu.BufferUsage.MAP_READ,
                label="fluid_vel_readback",
            )

        enc = device.create_command_encoder(label="fluid_vel_readback")
        enc.copy_texture_to_buffer(
            {"texture": vel_tex, "mip_level": 0, "origin": (0, 0, 0)},
            {
                "buffer": self._vel_readback_buf,
                "offset": 0,
                "bytes_per_row": aligned_bpr,
                "rows_per_image": self._sim_h,
            },
            (self._sim_w, self._sim_h, 1),
        )
        device.queue.submit([enc.finish()])

        # Map synchronously (blocks briefly — acceptable at 8-frame cadence).
        try:
            self._vel_readback_buf.map_sync(mode=_wgpu.MapMode.READ)
            raw = self._vel_readback_buf.read_mapped()
            # The buffer has aligned_bpr bytes per row; each pixel is 4×f16 = 8 bytes.
            pixels_per_row = aligned_bpr // 8  # may be > sim_w due to alignment
            arr = np.frombuffer(raw, dtype=np.float16).reshape(
                self._sim_h, pixels_per_row, 4
            )
            # Trim to actual sim width and cache RG (vx, vy) as float32.
            self._vel_cache = arr[:, :self._sim_w, :2].astype(np.float32)
            self._vel_readback_buf.unmap()
        except Exception:
            pass  # headless or map unavailable — vel_cache stays stale
