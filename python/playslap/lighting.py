"""Lighting system — directional, point, cone, shape, flash, and radiance-cascade lights.

All lights are managed by LightingSystem which is wired into the engine draw loop.
GPU dispatch uses a deferred accumulation pipeline:
  1. Clear accum buffer to zero
  2. Each light type additively contributes to the accum buffer
  3. Combine pass: scene_tex × (ambient + accum) → lit_tex (rgba8unorm)
  4. Fullscreen blit: lit_tex → swapchain render attachment
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import wgpu
    from playslap.gpu.context import GPUContext

from playslap.config import engine_config

_SHADER_DIR = Path(__file__).parent.parent.parent / "shaders"

# Buffer pool sizes
_MAX_DIR    = 8
_MAX_POINT  = 32   # covers point + flash lights
_MAX_CONE   = 16


@dataclass
class DirectionalLight:
    """Sun/moon light. Casts parallel shadows using Z-height offset."""
    direction: tuple[float, float] = (0.707, 0.707)  # normalised XY
    elevation: float = 0.785        # radians above horizon (π/4 = 45°)
    color: tuple[float, float, float] = (1.0, 1.0, 0.9)
    intensity: float = 1.0
    cast_shadows: bool = True
    tags: set = field(default_factory=set)


@dataclass
class PointLight:
    """Radial light with Z height for 3D distance attenuation."""
    position: tuple[float, float] = (0.0, 0.0)
    z: float = 100.0
    radius: float = 200.0
    color: tuple[float, float, float] = (1.0, 0.8, 0.6)
    intensity: float = 1.0
    cast_shadows: bool = False
    tags: set = field(default_factory=set)


@dataclass
class ConeLight:
    """Spotlight / vehicle headlight. Illuminates a cone sector."""
    position: tuple[float, float] = (0.0, 0.0)
    direction: tuple[float, float] = (1.0, 0.0)  # normalised XY
    z: float = 0.0
    half_angle: float = 0.35        # inner cone half-angle radians (~20°)
    outer_half_angle: float = 0.50  # outer cone (penumbra) half-angle
    radius: float = 300.0
    color: tuple[float, float, float] = (1.0, 0.95, 0.85)
    intensity: float = 2.0
    cast_shadows: bool = False
    tags: set = field(default_factory=set)


@dataclass
class ShapeLight:
    """Light shaped by a mask texture (PNG path)."""
    position: tuple[float, float] = (0.0, 0.0)
    mask_path: str = ""
    color: tuple[float, float, float] = (1.0, 1.0, 0.8)
    intensity: float = 1.0
    size: tuple[float, float] = (64.0, 64.0)   # world-space extents of the mask
    falloff: float = 1.0                         # falloff exponent (1=linear, 2=quadratic)
    tags: set = field(default_factory=set)


@dataclass
class FlashLight:
    """Short-lived point burst — muzzle flash, explosion. Auto-removed when expired."""
    position: tuple[float, float] = (0.0, 0.0)
    radius: float = 80.0
    color: tuple[float, float, float] = (1.0, 0.8, 0.4)
    intensity: float = 8.0
    duration: float = 0.06
    elapsed: float = 0.0
    _remaining: float = field(init=False, default=0.0)

    def trigger(self) -> None:
        self._remaining = self.duration
        self.elapsed = 0.0

    @property
    def active(self) -> bool:
        return self._remaining > 0.0

    def tick(self, dt: float) -> bool:
        """Advance the flash light by *dt* seconds.

        Returns ``True`` if the light has expired (``elapsed >= duration``),
        ``False`` otherwise.
        """
        self.elapsed += dt
        self._remaining = max(0.0, self._remaining - dt)
        return self.elapsed >= self.duration


@dataclass
class GravityWarpSource:
    """UV warp source for gravitational lensing / black hole effect."""
    position: tuple[float, float] = (0.0, 0.0)
    mass: float = 1.0           # warp strength; negative = repulsive
    radius: float = 20.0        # event horizon radius in pixels
    falloff: float = 5000.0     # attenuation: warp = mass / (dist² + falloff)
    _remaining: float = field(init=False, default=-1.0)  # -1 = permanent

    def set_duration(self, secs: float) -> None:
        self._remaining = secs

    @property
    def active(self) -> bool:
        return self._remaining < 0.0 or self._remaining > 0.0

    def tick(self, dt: float) -> None:
        if self._remaining > 0.0:
            self._remaining = max(0.0, self._remaining - dt)


@dataclass
class RadianceCascadeConfig:
    num_cascades: int = 4
    probe_spacing_px: int = 8
    rays_per_probe: int = 64
    max_ray_length_px: float = 512.0


class LightingContext:
    """Per-layer lighting configuration.

    When assigned to a Layer, overrides scene-level lighting for that layer only.
    Cross-layer bleeding is opt-in via mode="cross".
    """

    def __init__(
        self,
        ambient_color: tuple = (0.15, 0.15, 0.20),
        ambient_intensity: float = 0.15,
        mode: str = "local",   # "none" | "global" | "local" | "cross"
    ):
        self.ambient_color = ambient_color
        self.ambient_intensity = ambient_intensity
        self.mode = mode  # "none"=no lighting, "global"=use scene lights,
                          # "local"=own lights only, "cross"=own lights + bleed to neighbors
        self.lights: list = []

    def add_light(self, light) -> None:
        self.lights.append(light)

    def remove_light(self, light) -> None:
        self.lights.remove(light)

    def clear_lights(self) -> None:
        self.lights.clear()


class LightingSystem:
    """
    Manages all scene lights and dispatches the lighting compute pipeline each frame.

    Usage:
        engine.lighting.add_light(DirectionalLight(direction=(0.5, 0.8), intensity=1.2))
        engine.lighting.add_light(ConeLight(position=(100, 200), direction=(1, 0)))

    GPU pipeline per frame (called after frame_tex is rendered):
        clear accum → directional passes → point/flash passes → cone passes
        → combine (scene × accum) → fullscreen blit → swapchain
    """

    def __init__(self, gpu: "GPUContext", width: int, height: int):
        self._gpu = gpu
        self._width = width
        self._height = height
        self._lights: list = []
        self._gravity_warps: list[GravityWarpSource] = []
        self._ambient_color: tuple = (0.15, 0.15, 0.20)
        self._ambient_intensity: float = 0.15
        self._radiance_config: RadianceCascadeConfig | None = None
        self._emission_enabled: bool = True
        self._emission_threshold_k: float = 800.0

        # Fluid density texture reference (set by engine each frame when fluid sim is active).
        # Used for god-ray attenuation in directional light passes.
        self._fluid_density_tex = None

        # GPU resources — created lazily on first dispatch
        self._ready: bool = False
        self._scene_tex = None
        self._lit_tex = None
        self._accum_buf = None
        self._z_tex = None          # 1×1 dummy when no scene Z data available
        self._sampler = None
        self._pipeline_clear = None
        self._pipeline_dir = None
        self._pipeline_point = None
        self._pipeline_cone = None
        self._pipeline_combine = None
        self._blit_pipeline = None

        # Pre-allocated uniform buffer pools (one buffer per possible concurrent light)
        self._clear_params_buf = None
        self._combine_params_buf = None
        self._dir_param_bufs: list = []
        self._point_param_bufs: list = []
        self._cone_param_bufs: list = []

        # Clustered lighting resources (created lazily in _maybe_init_cluster)
        self._cluster_ready: bool = False
        self._cluster_lights_buf = None    # storage: 32 bytes × 256 lights
        self._cluster_count_buf = None     # storage: 4 × tiles_x × tiles_y (atomic u32)
        self._cluster_indices_buf = None   # storage: 4 × tiles_x × tiles_y × max_per_tile
        self._cluster_uniforms_buf = None  # uniform: 32 bytes (ClusterUniforms)
        self._cluster_accum_tex = None     # rgba16float storage texture for cluster path
        self._pipeline_cull = None         # compute, entry_point="cull_lights"
        self._pipeline_apply = None        # compute, entry_point="apply_cluster"
        self._pipeline_cluster_merge = None  # merges _cluster_accum_tex → _accum_buf

        # Radiance cascade system (created lazily in _dispatch_radiance_cascade)
        self._rc_system = None

    # ------------------------------------------------------------------ light management

    def add_light(self, light) -> None:
        self._lights.append(light)

    def remove_light(self, light) -> None:
        if light in self._lights:
            self._lights.remove(light)

    def add_gravity_warp(self, pos: tuple, mass: float = 1.0,
                         radius: float = 20.0, falloff: float = 5000.0,
                         duration: float = -1.0) -> GravityWarpSource:
        src = GravityWarpSource(position=pos, mass=mass, radius=radius, falloff=falloff)
        if duration > 0:
            src.set_duration(duration)
        self._gravity_warps.append(src)
        return src

    def set_ambient(self, color: tuple, intensity: float = 0.15) -> None:
        self._ambient_color = color
        self._ambient_intensity = intensity
        self._combine_params_buf = None  # force re-create on next dispatch

    def set_radiance_config(self, cfg: RadianceCascadeConfig) -> None:
        self._radiance_config = cfg

    def set_fluid_density(self, density_tex: "wgpu.GPUTexture | None") -> None:
        """Store a reference to the fluid density texture for god-ray scattering.

        Called by the engine each frame when a fluid simulation is active.
        The texture (rgba8unorm, R=density) is bound as binding 3 in the
        directional light bind group so the directional shader can attenuate
        transmittance along the shadow ray.
        """
        self._fluid_density_tex = density_tex

    def tick(self, dt: float) -> None:
        """Update timed :class:`GravityWarpSource` instances.

        Flash light expiry is handled by :meth:`tick_flash_lights`, which the
        engine draw loop calls separately each frame.
        """
        expired_warps = [w for w in self._gravity_warps if not w.active]
        for w in expired_warps:
            self._gravity_warps.remove(w)
        for w in self._gravity_warps:
            w.tick(dt)

    def tick_flash_lights(self, dt: float) -> int:
        """Advance all :class:`FlashLight` instances and remove expired ones.

        Parameters
        ----------
        dt:
            Frame delta time in seconds.

        Returns
        -------
        int
            The number of flash lights that were removed this tick.
        """
        to_remove: list[FlashLight] = []
        for light in self._lights:
            if isinstance(light, FlashLight):
                if light.tick(dt):
                    to_remove.append(light)
        for light in to_remove:
            self._lights.remove(light)
        return len(to_remove)

    # ------------------------------------------------------------------ typed accessors

    @property
    def directional_lights(self) -> list[DirectionalLight]:
        return [l for l in self._lights if isinstance(l, DirectionalLight)]

    @property
    def point_lights(self) -> list[PointLight]:
        return [l for l in self._lights if isinstance(l, PointLight)]

    @property
    def cone_lights(self) -> list[ConeLight]:
        return [l for l in self._lights if isinstance(l, ConeLight)]

    @property
    def flash_lights(self) -> list[FlashLight]:
        return [l for l in self._lights if isinstance(l, FlashLight) and l.active]

    @property
    def gravity_warps(self) -> list[GravityWarpSource]:
        return [w for w in self._gravity_warps if w.active]

    # ------------------------------------------------------------------ GPU dispatch

    def dispatch(self, frame_tex) -> None:
        """
        Apply lighting to frame_tex (the current swapchain texture) in-place.

        Must be called AFTER the frame encoder has been submitted so frame_tex
        contains the rendered scene. The swapchain surface must be configured
        with COPY_SRC usage (see GPUContext.initialize).
        """
        if not self._lights and not self._gravity_warps:
            return

        try:
            self._ensure_resources()
        except Exception:
            return  # GPU not ready yet (e.g. headless test)

        device = self._gpu.device
        w, h = self._width, self._height
        wg_x, wg_y = (w + 7) // 8, (h + 7) // 8

        # --- Step 1: copy swapchain → scene_tex (for compute shader input)
        copy_enc = device.create_command_encoder(label="lighting_copy_in")
        copy_enc.copy_texture_to_texture(
            {"texture": frame_tex, "mip_level": 0, "origin": (0, 0, 0)},
            {"texture": self._scene_tex, "mip_level": 0, "origin": (0, 0, 0)},
            (w, h, 1),
        )
        device.queue.submit([copy_enc.finish()])

        # Zero-clear the cluster accumulation texture so radiance cascade and
        # cluster apply contributions from previous frames do not bleed in.
        # Uses COPY_DST usage on the texture; write_texture is efficient here
        # because the zero region is write-combined by the driver.
        if getattr(self, '_cluster_accum_tex', None) is not None:
            try:
                zero_bytes = bytes(w * h * 8)  # rgba16float = 8 bytes per pixel
                device.queue.write_texture(
                    {"texture": self._cluster_accum_tex, "mip_level": 0, "origin": (0, 0, 0)},
                    zero_bytes,
                    {"bytes_per_row": w * 8, "rows_per_image": h},
                    (w, h, 1),
                )
            except Exception:
                pass

        # --- Step 2-6: accumulate all lights into accum buffer, then combine
        enc = device.create_command_encoder(label="lighting_compute")

        # Clear accum
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self._pipeline_clear)
        cp.set_bind_group(0, self._make_clear_bg())
        cp.dispatch_workgroups(wg_x, wg_y, 1)
        cp.end()

        # Directional lights
        for i, dl in enumerate(self.directional_lights[:_MAX_DIR]):
            self._write_dir_params(i, dl)
            cp = enc.begin_compute_pass()
            cp.set_pipeline(self._pipeline_dir)
            cp.set_bind_group(0, self._make_dir_bg(i))
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()

        # Point lights + active flash lights (share the same shader)
        #
        # When clustered lighting is ready and the light count exceeds 8, use
        # the two-pass tile-based path (cull_lights → apply_cluster).  Otherwise
        # fall back to the original per-light full-screen dispatches so that
        # scenes with a handful of lights pay no overhead.
        point_lights: list = list(self.point_lights) + list(self.flash_lights)
        if getattr(self, '_cluster_ready', False) and len(point_lights) > 8:
            self._dispatch_clustered(enc, point_lights)
        else:
            for i, pl in enumerate(point_lights[:_MAX_POINT]):
                self._write_point_params(i, pl)
                cp = enc.begin_compute_pass()
                cp.set_pipeline(self._pipeline_point)
                cp.set_bind_group(0, self._make_point_bg(i))
                cp.dispatch_workgroups(wg_x, wg_y, 1)
                cp.end()

        # Cone lights
        for i, cl in enumerate(self.cone_lights[:_MAX_CONE]):
            self._write_cone_params(i, cl)
            cp = enc.begin_compute_pass()
            cp.set_pipeline(self._pipeline_cone)
            cp.set_bind_group(0, self._make_cone_bg(i))
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()

        # Radiance cascade GI (adds indirect illumination into _cluster_accum_tex
        # which is subsequently merged into _accum_buf by the cluster-merge pass).
        # Must run before the combine pass so GI contribution is visible.
        self._dispatch_radiance_cascade(enc, self._scene_tex, self._accum_buf)

        # Combine: scene_tex × (ambient + accum) → lit_tex
        cp = enc.begin_compute_pass()
        cp.set_pipeline(self._pipeline_combine)
        cp.set_bind_group(0, self._make_combine_bg())
        cp.dispatch_workgroups(wg_x, wg_y, 1)
        cp.end()

        device.queue.submit([enc.finish()])

        # --- Step 7: fullscreen blit lit_tex → swapchain render attachment
        import wgpu as _wgpu
        blit_enc = device.create_command_encoder(label="lighting_blit")
        rp = blit_enc.begin_render_pass(
            color_attachments=[{
                "view": frame_tex.create_view(),
                "resolve_target": None,
                "clear_value": (0.0, 0.0, 0.0, 1.0),
                "load_op": _wgpu.LoadOp.clear,
                "store_op": _wgpu.StoreOp.store,
            }]
        )
        rp.set_pipeline(self._blit_pipeline)
        blit_bg = device.create_bind_group(
            layout=self._blit_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": self._lit_tex.create_view()},
                {"binding": 1, "resource": self._sampler},
            ],
        )
        rp.set_bind_group(0, blit_bg)
        rp.draw(3, 1, 0, 0)
        rp.end()
        device.queue.submit([blit_enc.finish()])

    def _dispatch_shape_lights(self, encoder, accum_tex) -> None:
        """Dispatch shape lights using lighting_shape.wgsl."""
        shape_lights = [l for l in self._lights if isinstance(l, ShapeLight)]
        if not shape_lights:
            return
        # TODO Sprint 4: wire GPU compute pass when texture management supports mask upload

    def _dispatch_clustered(self, enc, point_lights: list) -> None:
        """Two-pass tile-based clustered lighting for point + flash lights.

        Pass 1 (cull_lights): bins each light into its overlapping tiles.
        Pass 2 (apply_cluster): per-pixel accumulation over the binned lights.
        After both passes the per-tile results in _cluster_accum_tex are merged
        additively into _accum_buf by a lightweight inline compute pass so that
        the combine pass (which reads _accum_buf) sees all contributions.
        """
        try:
            import wgpu as _wgpu
            device = self._gpu.device
            w, h = self._width, self._height
            lc = engine_config().lighting
            tile_size = lc.cluster_tile_size
            max_per_tile = lc.max_lights_per_tile
            tiles_x = (w + tile_size - 1) // tile_size
            tiles_y = (h + tile_size - 1) // tile_size

            # --- Upload lights array (32 bytes per light: pos, radius, _pad0, color, intensity)
            # Struct layout (matches PointLightData in lighting_cluster.wgsl):
            #   offset  0 — pos      vec2<f32>  8 bytes
            #   offset  8 — radius   f32        4 bytes
            #   offset 12 — _pad0    f32        4 bytes
            #   offset 16 — color    vec3<f32> 12 bytes
            #   offset 28 — intensity f32       4 bytes
            # Total: 32 bytes
            _MAX_CLUSTER_LIGHTS = 256
            num_lights = min(len(point_lights), _MAX_CLUSTER_LIGHTS)
            lights_data = bytearray(32 * _MAX_CLUSTER_LIGHTS)
            for idx, pl in enumerate(point_lights[:num_lights]):
                if isinstance(pl, FlashLight):
                    px, py = pl.position
                    radius = pl.radius
                    cr, cg, cb = pl.color
                    intensity = pl.intensity
                else:
                    px, py = pl.position
                    radius = pl.radius
                    cr, cg, cb = pl.color
                    intensity = pl.intensity
                struct.pack_into(
                    "<4f 3f f",
                    lights_data, idx * 32,
                    px, py, radius, 0.0,   # pos.xy, radius, _pad0
                    cr, cg, cb, intensity, # color.rgb, intensity
                )
            device.queue.write_buffer(self._cluster_lights_buf, 0, bytes(lights_data))

            # --- Write ClusterUniforms (32 bytes):
            #   screen_size   vec2<u32>  8 bytes
            #   tile_size     u32        4 bytes
            #   num_lights    u32        4 bytes
            #   max_lights_per_tile u32  4 bytes
            #   _pad          vec3<u32> 12 bytes
            uniforms_data = struct.pack(
                "<5I 3I",
                w, h,
                tile_size,
                num_lights,
                max_per_tile,
                0, 0, 0,  # _pad
            )
            device.queue.write_buffer(self._cluster_uniforms_buf, 0, uniforms_data)

            # --- Zero-clear the tile count buffer before culling
            enc.clear_buffer(self._cluster_count_buf, 0, self._cluster_count_buf.size)

            # --- Pass 1: cull_lights — one thread per tile
            cull_wg_x = (tiles_x + 7) // 8
            cull_wg_y = (tiles_y + 7) // 8
            cp = enc.begin_compute_pass(label="cluster_cull")
            cp.set_pipeline(self._pipeline_cull)
            cp.set_bind_group(0, self._make_cluster_cull_bg())
            cp.dispatch_workgroups(cull_wg_x, cull_wg_y, 1)
            cp.end()

            # --- Pass 2: apply_cluster — one thread per pixel
            apply_wg_x = (w + 7) // 8
            apply_wg_y = (h + 7) // 8
            cp = enc.begin_compute_pass(label="cluster_apply")
            cp.set_pipeline(self._pipeline_apply)
            cp.set_bind_group(0, self._make_cluster_apply_bg())
            cp.dispatch_workgroups(apply_wg_x, apply_wg_y, 1)
            cp.end()

            # --- Merge pass: copy _cluster_accum_tex → _accum_buf (additive)
            # This keeps the combine pass (which reads _accum_buf) compatible
            # with both the clustered and non-clustered code paths.
            merge_wg_x = (w + 7) // 8
            merge_wg_y = (h + 7) // 8
            cp = enc.begin_compute_pass(label="cluster_merge")
            cp.set_pipeline(self._pipeline_cluster_merge)
            cp.set_bind_group(0, self._make_cluster_merge_bg())
            cp.dispatch_workgroups(merge_wg_x, merge_wg_y, 1)
            cp.end()

        except Exception:
            # Graceful degradation: if anything goes wrong (e.g. headless mode),
            # fall through silently — the combine pass will just see the accum
            # contributions from directional and cone lights only.
            pass

    def _dispatch_radiance_cascade(self, encoder, scene_tex, accum_tex) -> None:
        """4-level radiance cascade GI using RadianceCascadeSystem.

        Dispatches inject → merge → temporal → apply passes for one frame.
        Results are written into _cluster_accum_tex (the rgba16float storage
        texture), which the cluster-merge pass later folds into _accum_buf.
        If _radiance_config is None this method returns immediately.
        """
        if self._radiance_config is None:
            return
        # If no cluster accum texture exists (cluster path disabled), there is
        # nowhere to accumulate GI results — skip gracefully.
        if self._cluster_accum_tex is None:
            return
        try:
            from playslap.gi.cascade import RadianceCascadeSystem
            cfg = self._radiance_config
            if self._rc_system is None:
                self._rc_system = RadianceCascadeSystem(
                    width=self._width,
                    height=self._height,
                    num_cascades=cfg.num_cascades,
                    base_probe_spacing=cfg.probe_spacing_px,
                    rays_per_probe_l0=cfg.rays_per_probe,
                    temporal_blend=0.05,
                )
                self._rc_system.init_gpu(self._gpu)
            # The apply pass in RadianceCascadeSystem calls lighting_accumulator.create_view(),
            # so we supply the rgba16float _cluster_accum_tex (a real GPU texture).
            self._rc_system.dispatch(encoder, scene_tex, self._cluster_accum_tex)
        except Exception:
            # Headless or shader-missing: degrade silently.
            pass

    # ------------------------------------------------------------------ resource setup

    def _ensure_resources(self) -> None:
        if self._ready:
            return
        import wgpu as _wgpu
        device = self._gpu.device
        w, h = self._width, self._height
        surface_fmt = getattr(self._gpu, 'surface_format', _wgpu.TextureFormat.rgba8unorm)

        # Offscreen textures
        def _make_tex(fmt, usage, label):
            return device.create_texture(
                size=(w, h, 1),
                format=fmt,
                usage=usage,
                mip_level_count=1,
                sample_count=1,
                label=label,
            )

        tex_binding = _wgpu.TextureUsage.TEXTURE_BINDING
        copy_dst    = _wgpu.TextureUsage.COPY_DST
        copy_src    = _wgpu.TextureUsage.COPY_SRC
        storage     = _wgpu.TextureUsage.STORAGE_BINDING

        # scene_tex: copy of swapchain (must match surface format for copy compat)
        self._scene_tex = _make_tex(
            surface_fmt,
            tex_binding | copy_dst,
            "lighting_scene_tex",
        )

        # lit_tex: rgba8unorm required for storage write in WGSL
        self._lit_tex = _make_tex(
            _wgpu.TextureFormat.rgba8unorm,
            storage | tex_binding | copy_src,
            "lighting_lit_tex",
        )

        # Accumulation buffer: vec4<f32> per pixel = 16 bytes/px
        buf_size = w * h * 16
        self._accum_buf = device.create_buffer(
            size=buf_size,
            usage=_wgpu.BufferUsage.STORAGE | _wgpu.BufferUsage.COPY_DST,
            label="lighting_accum",
        )

        # Dummy 1×1 Z texture (r32float) — used when no scene Z data is available
        self._z_tex = device.create_texture(
            size=(1, 1, 1),
            format=_wgpu.TextureFormat.r32float,
            usage=tex_binding | copy_dst,
            mip_level_count=1,
            sample_count=1,
            label="lighting_z_dummy",
        )
        # Upload a single zero float
        device.queue.write_texture(
            {"texture": self._z_tex, "mip_level": 0, "origin": (0, 0, 0)},
            struct.pack("<f", 0.0),
            {"bytes_per_row": 4, "rows_per_image": 1},
            (1, 1, 1),
        )

        # Sampler for fullscreen blit
        self._sampler = device.create_sampler(
            min_filter="linear",
            mag_filter="linear",
            mipmap_filter="nearest",
            label="lighting_sampler",
        )

        # Compile pipelines
        self._pipeline_clear   = self._compile_compute("lighting_clear_accum.wgsl", "clear_accum")
        self._pipeline_dir     = self._compile_compute("lighting_directional.wgsl", "dir_light")
        self._pipeline_point   = self._compile_compute("lighting_point.wgsl",       "point_light")
        self._pipeline_cone    = self._compile_compute("lighting_cone.wgsl",        "cone_light")
        self._pipeline_combine = self._compile_compute("lighting_combine.wgsl",     "combine")
        self._blit_pipeline    = self._compile_blit(surface_fmt)

        self._maybe_init_cluster()

        # Pre-allocated uniform buffer pools (one per concurrent light)
        def _ub(size, label):
            return device.create_buffer(
                size=size,
                usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
                label=label,
            )

        self._clear_params_buf   = _ub(16, "ub_clear")
        self._combine_params_buf = _ub(32, "ub_combine")
        self._dir_param_bufs    = [_ub(48, f"ub_dir_{i}")   for i in range(_MAX_DIR)]
        self._point_param_bufs  = [_ub(48, f"ub_point_{i}") for i in range(_MAX_POINT)]
        self._cone_param_bufs   = [_ub(64, f"ub_cone_{i}")  for i in range(_MAX_CONE)]

        # Write static clear params (width/height never change)
        device.queue.write_buffer(
            self._clear_params_buf, 0,
            struct.pack("<4I", w, h, 0, 0),
        )

        self._ready = True

    def _maybe_init_cluster(self) -> None:
        """Create clustered-lighting GPU resources if enabled in config.

        Called from _ensure_resources() after the base pipelines are compiled.
        Sets self._cluster_ready = True on success, False if disabled or if GPU
        resource creation fails (e.g. headless/test environment).
        """
        try:
            import wgpu as _wgpu
            lc = engine_config().lighting
            if not lc.clustered_lighting:
                self._cluster_ready = False
                return

            device = self._gpu.device
            w, h = self._width, self._height
            tile_size = lc.cluster_tile_size
            max_per_tile = lc.max_lights_per_tile
            _MAX_CLUSTER_LIGHTS = 256

            tiles_x = (w + tile_size - 1) // tile_size
            tiles_y = (h + tile_size - 1) // tile_size
            num_tiles = tiles_x * tiles_y

            storage_rw = _wgpu.BufferUsage.STORAGE | _wgpu.BufferUsage.COPY_DST
            uniform_usage = _wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST

            # lights[] storage buffer: 32 bytes per PointLightData × 256 slots
            self._cluster_lights_buf = device.create_buffer(
                size=32 * _MAX_CLUSTER_LIGHTS,
                usage=storage_rw,
                label="cluster_lights",
            )
            # tile_light_count[] storage buffer: one atomic u32 per tile
            self._cluster_count_buf = device.create_buffer(
                size=4 * num_tiles,
                usage=storage_rw,
                label="cluster_count",
            )
            # tile_light_indices[] storage buffer: u32 per (tile × slot)
            self._cluster_indices_buf = device.create_buffer(
                size=4 * num_tiles * max_per_tile,
                usage=storage_rw,
                label="cluster_indices",
            )
            # ClusterUniforms uniform buffer: 32 bytes
            self._cluster_uniforms_buf = device.create_buffer(
                size=32,
                usage=uniform_usage,
                label="cluster_uniforms",
            )

            # rgba16float storage texture: cluster apply and RC passes write here;
            # the cluster_merge pass then adds these values into _accum_buf.
            self._cluster_accum_tex = device.create_texture(
                size=(w, h, 1),
                format=_wgpu.TextureFormat.rgba16float,
                usage=(
                    _wgpu.TextureUsage.STORAGE_BINDING
                    | _wgpu.TextureUsage.TEXTURE_BINDING
                    | _wgpu.TextureUsage.COPY_DST
                ),
                mip_level_count=1,
                sample_count=1,
                label="cluster_accum_tex",
            )

            # Compile cull + apply pipelines from lighting_cluster.wgsl
            cluster_src = (_SHADER_DIR / "lighting_cluster.wgsl").read_text(encoding="utf-8")
            cluster_mod = device.create_shader_module(code=cluster_src, label="lighting_cluster")

            self._pipeline_cull = device.create_compute_pipeline(
                layout="auto",
                compute={"module": cluster_mod, "entry_point": "cull_lights"},
                label="cluster_cull",
            )
            self._pipeline_apply = device.create_compute_pipeline(
                layout="auto",
                compute={"module": cluster_mod, "entry_point": "apply_cluster"},
                label="cluster_apply",
            )

            # Inline merge shader: reads each texel from cluster_accum_tex (rgba16float)
            # and adds it into the corresponding element of accum_buf (vec4<f32> per pixel).
            # This keeps the combine pass unchanged — it reads accum_buf as before.
            _MERGE_WGSL = """\
struct MergeParams { width: u32, height: u32, _pad0: u32, _pad1: u32 }
@group(0) @binding(0) var<uniform>             params:     MergeParams;
@group(0) @binding(1) var                      src_tex:    texture_2d<f32>;
@group(0) @binding(2) var<storage, read_write> dst_buf:    array<vec4<f32>>;
@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if gid.x >= params.width || gid.y >= params.height { return; }
    let idx = gid.y * params.width + gid.x;
    let src = textureLoad(src_tex, vec2<i32>(gid.xy), 0);
    dst_buf[idx] = dst_buf[idx] + src;
}
"""
            _merge_buf = device.create_buffer(
                size=16,  # MergeParams: 4 × u32
                usage=uniform_usage,
                label="cluster_merge_params",
            )
            device.queue.write_buffer(
                _merge_buf, 0,
                struct.pack("<4I", w, h, 0, 0),
            )
            self._cluster_merge_params_buf = _merge_buf

            merge_mod = device.create_shader_module(code=_MERGE_WGSL, label="cluster_merge")
            self._pipeline_cluster_merge = device.create_compute_pipeline(
                layout="auto",
                compute={"module": merge_mod, "entry_point": "main"},
                label="cluster_merge",
            )

            self._cluster_ready = True

        except Exception:
            # Headless mode or GPU init failure — disable clustered path silently.
            self._cluster_ready = False

    def _compile_compute(self, shader_file: str, label: str):
        device = self._gpu.device
        src = (_SHADER_DIR / shader_file).read_text(encoding="utf-8")
        shader = device.create_shader_module(code=src, label=label)
        return device.create_compute_pipeline(
            layout="auto",
            compute={"module": shader, "entry_point": "main"},
            label=label,
        )

    def _make_cluster_cull_bg(self):
        """Bind group for Pass 1 (cull_lights): bindings 0-3 only.

        Bindings 4-5 (scene_tex, accum_tex) are not needed by cull_lights and
        are intentionally omitted; the pipeline layout is derived via "auto" so
        wgpu only enforces the bindings actually declared in that entry point.
        """
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_cull.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._cluster_uniforms_buf}},
                {"binding": 1, "resource": {"buffer": self._cluster_lights_buf}},
                {"binding": 2, "resource": {"buffer": self._cluster_count_buf}},
                {"binding": 3, "resource": {"buffer": self._cluster_indices_buf}},
            ],
        )

    def _make_cluster_apply_bg(self):
        """Bind group for Pass 2 (apply_cluster): all 6 bindings."""
        import wgpu as _wgpu
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_apply.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._cluster_uniforms_buf}},
                {"binding": 1, "resource": {"buffer": self._cluster_lights_buf}},
                {"binding": 2, "resource": {"buffer": self._cluster_count_buf}},
                {"binding": 3, "resource": {"buffer": self._cluster_indices_buf}},
                {"binding": 4, "resource": self._scene_tex.create_view()},
                {"binding": 5, "resource": self._cluster_accum_tex.create_view(
                    format="rgba16float",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
            ],
        )

    def _make_cluster_merge_bg(self):
        """Bind group for the inline merge pass (cluster_accum_tex → accum_buf)."""
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_cluster_merge.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._cluster_merge_params_buf}},
                {"binding": 1, "resource": self._cluster_accum_tex.create_view()},
                {"binding": 2, "resource": {"buffer": self._accum_buf}},
            ],
        )

    def _compile_blit(self, surface_format):
        import wgpu as _wgpu
        device = self._gpu.device
        src = (_SHADER_DIR / "fullscreen_blit.wgsl").read_text(encoding="utf-8")
        shader = device.create_shader_module(code=src, label="blit")
        return device.create_render_pipeline(
            layout="auto",
            vertex={"module": shader, "entry_point": "vs_main"},
            fragment={
                "module": shader,
                "entry_point": "fs_main",
                "targets": [{"format": surface_format}],
            },
            primitive={"topology": _wgpu.PrimitiveTopology.triangle_list},
            label="blit_pipeline",
        )

    # ------------------------------------------------------------------ bind group helpers

    def _make_clear_bg(self):
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_clear.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._clear_params_buf}},
                {"binding": 1, "resource": {"buffer": self._accum_buf}},
            ],
        )

    def _write_dir_params(self, i: int, dl: DirectionalLight) -> None:
        dx, dy = dl.direction
        cr, cg, cb = dl.color
        w, h = self._width, self._height
        data = struct.pack(
            "<7fI f 2I I",
            dx, dy, dl.elevation, dl.intensity,
            cr, cg, cb,
            1 if dl.cast_shadows else 0,
            engine_config().z_height.shadow_z_scale,  # screen-pixels of shadow offset per z-unit per radian
            w, h, 0,
        )
        self._gpu.device.queue.write_buffer(self._dir_param_bufs[i], 0, data)

    def _make_dir_bg(self, i: int):
        import wgpu as _wgpu
        device = self._gpu.device

        # Binding 3: fluid density texture for god-ray scattering.
        # If no fluid sim is active, bind a 1×1 zero dummy so the shader layout
        # stays consistent.  The directional shader reads density along the shadow
        # ray and attenuates transmittance: transmittance *= exp(-density * coeff).
        if self._fluid_density_tex is not None:
            density_view = self._fluid_density_tex.create_view()
        else:
            # Reuse the 1×1 z_tex as a dummy; it has TEXTURE_BINDING usage and
            # the shader treats zero density as full transmittance (no attenuation).
            density_view = self._z_tex.create_view()

        return device.create_bind_group(
            layout=self._pipeline_dir.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._dir_param_bufs[i]}},
                {"binding": 1, "resource": self._z_tex.create_view()},
                {"binding": 2, "resource": {"buffer": self._accum_buf}},
                {"binding": 3, "resource": density_view},
            ],
        )

    def _write_point_params(self, i: int, light) -> None:
        # Works for both PointLight and FlashLight (flash has radius/color/intensity)
        if isinstance(light, FlashLight):
            px, py = light.position
            z      = 0.0
            radius = light.radius
            cr, cg, cb = light.color
            intensity  = light.intensity
        else:
            px, py = light.position
            z      = light.z
            radius = light.radius
            cr, cg, cb = light.color
            intensity  = light.intensity
        w, h = self._width, self._height
        data = struct.pack("<8f 2I 2I", px, py, z, radius, cr, cg, cb, intensity, w, h, 0, 0)
        self._gpu.device.queue.write_buffer(self._point_param_bufs[i], 0, data)

    def _make_point_bg(self, i: int):
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_point.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._point_param_bufs[i]}},
                {"binding": 1, "resource": {"buffer": self._accum_buf}},
            ],
        )

    def _write_cone_params(self, i: int, cl: ConeLight) -> None:
        px, py = cl.position
        dx, dy = cl.direction
        cr, cg, cb = cl.color
        w, h = self._width, self._height
        data = struct.pack(
            "<12f 2I 2f",
            px, py, dx, dy,
            cl.half_angle, cl.outer_half_angle, cl.radius,
            cr, cg, cb, cl.intensity, 0.0,
            w, h,
            0.0, 0.0,
        )
        self._gpu.device.queue.write_buffer(self._cone_param_bufs[i], 0, data)

    def _make_cone_bg(self, i: int):
        device = self._gpu.device
        return device.create_bind_group(
            layout=self._pipeline_cone.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._cone_param_bufs[i]}},
                {"binding": 1, "resource": {"buffer": self._accum_buf}},
            ],
        )

    def _make_combine_bg(self):
        import wgpu as _wgpu
        device = self._gpu.device
        ar, ag, ab = self._ambient_color
        ai = self._ambient_intensity
        w, h = self._width, self._height
        data = struct.pack("<4f 4I", ar, ag, ab, ai, w, h, 0, 0)
        device.queue.write_buffer(self._combine_params_buf, 0, data)
        return device.create_bind_group(
            layout=self._pipeline_combine.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": self._combine_params_buf}},
                {"binding": 1, "resource": self._scene_tex.create_view()},
                {"binding": 2, "resource": {"buffer": self._accum_buf}},
                {"binding": 3, "resource": self._lit_tex.create_view(
                    format="rgba8unorm",
                    usage=_wgpu.TextureUsage.STORAGE_BINDING,
                )},
            ],
        )
