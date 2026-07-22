from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import yaml

from .surface import (
    compute_density_normals,
    extract_isolines,
    sample_density_grid,
)
from .world import FluidWorld

_EPS = 1e-9


# Detect the Rust-backed raster kernels once at import time. Falls back to
# the pure-numpy paths if `_core` is absent or the symbols aren't present
# (older _core builds without ``raster.rs``).
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_RASTER = (
        hasattr(_native_core, "rasterize_circles")
        and hasattr(_native_core, "post_process_rgb")
    )
    _HAS_NATIVE_FLUID_SHADER = (
        _native_core is not None
        and hasattr(_native_core, "turbulence_foam_rs")
        and hasattr(_native_core, "refraction_warp_rs")
        and hasattr(_native_core, "godrays_rs")
        and hasattr(_native_core, "specular_pass_rs")
        and hasattr(_native_core, "draw_droplet_tails_rs")
    )
except ImportError:  # pragma: no cover - exercised in pure-Python envs
    _native_core = None  # type: ignore
    _HAS_NATIVE_RASTER = False
    _HAS_NATIVE_FLUID_SHADER = False


def _render_cfg() -> dict[str, Any]:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "fluid.yml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                section = raw.get("render") or {}
                return dict(section) if isinstance(section, dict) else {}
            except Exception:
                return {}
    return {}


@dataclass
class FluidRenderConfig:
    width: int = 320
    height: int = 240
    bg_top: tuple[int, int, int] = (4, 8, 22)
    bg_bottom: tuple[int, int, int] = (12, 18, 40)
    floor_color: tuple[int, int, int] = (70, 70, 80)
    wall_color: tuple[int, int, int] = (50, 55, 70)
    world_view: tuple[float, float, float, float] = (-1.0, -1.0, 1.0, 1.0)
    particle_radius_px: float = 2.4
    halo_radius_px: float = 4.0
    halo_alpha: float = 0.45
    tonemap_exposure: float = 1.0
    tonemap_gamma: float = 2.2
    # Surface render mode (marching-squares over a density grid).
    surface_mode: bool = False
    surface_isovalue_factor: float = 0.3
    surface_grid_cells_per_h: int = 2
    surface_outline_width_px: float = 1.5
    surface_fill_softness: float = 0.7   # how soft the fill edge is (smoothstep half-width as fraction of iso)
    surface_lambert_strength: float = 0.45
    surface_light_dir: tuple[float, float] = (-0.5, -0.85)
    # --- Watery surface polish (turbulence/refraction/godrays/specular) -----
    surface_turbulence_enabled: bool = True
    # Speed (m/s) at which a pixel is fully whitened toward foam.
    surface_turbulence_speed: float = 2.0
    # Max white bias (0..1). 0.85 means turbulent regions read as 85% foam.
    surface_turbulence_strength: float = 0.85
    surface_refraction_enabled: bool = True
    # World-units of UV warp per unit-density-gradient.
    surface_refraction_strength: float = 1.2
    surface_godrays_enabled: bool = True
    # Number of march steps from each pixel toward the light.
    surface_godray_steps: int = 6
    # Pixel step size (world-space cells) per march iteration.
    surface_godray_step_px: float = 2.5
    # Final additive intensity scale.
    surface_godray_strength: float = 0.55
    # Tight specular lobe width and intensity.
    surface_specular_enabled: bool = True
    surface_specular_strength: float = 0.85
    surface_specular_tint: tuple[int, int, int] = (230, 245, 255)
    # Dual-view mode — render surface AND droplet tails for sparse particles.
    # surface_mode must be True for this to engage.
    dual_view: bool = False
    # Density ratio below which a particle becomes a "droplet" with a tail.
    droplet_density_factor: float = 0.55
    # Tail length in screen-space pixels at full velocity.
    droplet_tail_px: float = 4.5
    # Tail tip alpha multiplier.
    droplet_tail_alpha: float = 0.75

    @classmethod
    def from_yaml(cls, overrides: dict[str, Any] | None = None) -> "FluidRenderConfig":
        data = _render_cfg()
        if overrides:
            data.update(overrides)
        return cls(
            width=int(data.get("width", cls.width)),
            height=int(data.get("height", cls.height)),
            bg_top=tuple(data.get("bg_top", cls.bg_top)),
            bg_bottom=tuple(data.get("bg_bottom", cls.bg_bottom)),
            floor_color=tuple(data.get("floor_color", cls.floor_color)),
            wall_color=tuple(data.get("wall_color", cls.wall_color)),
            particle_radius_px=float(data.get("particle_radius_px", cls.particle_radius_px)),
            halo_radius_px=float(data.get("halo_radius_px", cls.halo_radius_px)),
            halo_alpha=float(data.get("halo_alpha", cls.halo_alpha)),
            tonemap_exposure=float(data.get("tonemap_exposure", cls.tonemap_exposure)),
            tonemap_gamma=float(data.get("tonemap_gamma", cls.tonemap_gamma)),
            surface_mode=bool(data.get("surface_mode", cls.surface_mode)),
            surface_isovalue_factor=float(data.get("surface_isovalue_factor", cls.surface_isovalue_factor)),
            surface_grid_cells_per_h=int(data.get("surface_grid_cells_per_h", cls.surface_grid_cells_per_h)),
            surface_outline_width_px=float(data.get("surface_outline_width_px", cls.surface_outline_width_px)),
            surface_fill_softness=float(data.get("surface_fill_softness", cls.surface_fill_softness)),
            surface_lambert_strength=float(data.get("surface_lambert_strength", cls.surface_lambert_strength)),
            surface_light_dir=tuple(data.get("surface_light_dir", cls.surface_light_dir)),
            surface_turbulence_enabled=bool(data.get("surface_turbulence_enabled", cls.surface_turbulence_enabled)),
            surface_turbulence_speed=float(data.get("surface_turbulence_speed", cls.surface_turbulence_speed)),
            surface_turbulence_strength=float(data.get("surface_turbulence_strength", cls.surface_turbulence_strength)),
            surface_refraction_enabled=bool(data.get("surface_refraction_enabled", cls.surface_refraction_enabled)),
            surface_refraction_strength=float(data.get("surface_refraction_strength", cls.surface_refraction_strength)),
            surface_godrays_enabled=bool(data.get("surface_godrays_enabled", cls.surface_godrays_enabled)),
            surface_godray_steps=int(data.get("surface_godray_steps", cls.surface_godray_steps)),
            surface_godray_step_px=float(data.get("surface_godray_step_px", cls.surface_godray_step_px)),
            surface_godray_strength=float(data.get("surface_godray_strength", cls.surface_godray_strength)),
            surface_specular_enabled=bool(data.get("surface_specular_enabled", cls.surface_specular_enabled)),
            surface_specular_strength=float(data.get("surface_specular_strength", cls.surface_specular_strength)),
            surface_specular_tint=tuple(data.get("surface_specular_tint", cls.surface_specular_tint)),
            dual_view=bool(data.get("dual_view", cls.dual_view)),
            droplet_density_factor=float(data.get("droplet_density_factor", cls.droplet_density_factor)),
            droplet_tail_px=float(data.get("droplet_tail_px", cls.droplet_tail_px)),
            droplet_tail_alpha=float(data.get("droplet_tail_alpha", cls.droplet_tail_alpha)),
        )


class FluidRenderer:
    def __init__(self, config: FluidRenderConfig | None = None) -> None:
        self.config = config or FluidRenderConfig.from_yaml()
        self._softbody_renderer = None

    def attach_softbody(self, softbody_renderer) -> None:
        self._softbody_renderer = softbody_renderer

    def render(self, world: FluidWorld,
               view_box: tuple[float, float, float, float] | None = None,
               softbody=None) -> np.ndarray:
        cfg = self.config
        if view_box is None:
            view_box = self._infer_view(world)
        cfg.world_view = view_box

        # Native fast-path: route the splat hot path (particles) and the
        # bloom + tonemap chain through Rust kernels. We keep the entire
        # pipeline (background, walls, floor, splats, post) on a shared
        # u8 RGB bytearray to avoid float allocations.
        #
        # The path is gated on:
        #   * The Rust kernels being present at import time.
        #   * Disc-splat (non-surface) mode — marching-squares surface is
        #     numpy-only and already efficient.
        #   * No softbody overlay — that draws thin lines via the float
        #     ``_line`` helper which doesn't have a native shim here.
        if (
            _HAS_NATIVE_RASTER
            and not cfg.surface_mode
            and softbody is None
        ):
            return self._render_native(world)

        hdr = self._background()
        self._draw_walls(hdr, world)
        self._draw_floor(hdr, world)
        if softbody is not None and softbody.nodes.count > 0:
            self._draw_softbody_overlay(hdr, softbody)
        if cfg.surface_mode:
            # _draw_surface returns the per-pixel density grid (or None on
            # empty world). dual_view uses it to crossfade droplet tails
            # against the surface fill.
            density_screen = self._draw_surface(hdr, world)
            if cfg.dual_view and density_screen is not None:
                self._draw_droplet_tails(hdr, world, density_screen)
        else:
            self._draw_particles(hdr, world)
        rgb = self._post_process(hdr)
        out = np.zeros((cfg.height, cfg.width, 4), dtype=np.uint8)
        out[..., :3] = rgb
        out[..., 3] = 255
        return out

    def _render_native(self, world: FluidWorld) -> np.ndarray:
        """Rust-backed disc-splat path.

        Builds a u8 RGB bytearray, stamps background/floor/walls/particles
        via native kernels, runs ``post_process_rgb``, then interleaves
        into the (H, W, 4) RGBA output. Matches the softbody renderer's
        native pipeline pattern.
        """
        cfg = self.config
        H, W = cfg.height, cfg.width

        bg = self._background_u8()
        buf = getattr(self, "_u8_buf_persistent", None)
        if buf is None or len(buf) != len(bg):
            buf = bytearray(len(bg))
            self._u8_buf_persistent = buf
        buf[:] = bg
        self._u8_buf = buf

        # Walls + floor are single-pixel rows/columns — stamp them directly
        # into the u8 buffer.
        self._draw_walls_u8(world)
        self._draw_floor_u8(world)

        # Particles: halo pass first, then core pass on top (last writer
        # wins, which mirrors the alpha-over behaviour at the disc centre).
        self._draw_particles_u8(world)

        _native_core.post_process_rgb(
            self._u8_buf,
            int(W), int(H),
            0,                                  # bloom_radius (fluid path has no bloom)
            0.0,                                # bloom_strength
            1.0,                                # bloom_threshold (unused)
            float(cfg.tonemap_exposure),
            float(cfg.tonemap_gamma),
        )

        out = np.empty((H, W, 4), dtype=np.uint8)
        out[..., :3] = np.frombuffer(self._u8_buf, dtype=np.uint8).reshape(H, W, 3)
        out[..., 3] = 255
        self._u8_buf = None
        return out

    def render_sequence(self, world: FluidWorld, frame_count: int,
                        step_fn, steps_per_frame: int = 1,
                        view_box: tuple[float, float, float, float] | None = None
                        ) -> Iterable[np.ndarray]:
        for _ in range(frame_count):
            for _ in range(steps_per_frame):
                step_fn(world)
            yield self.render(world, view_box=view_box)

    def save_gif(self, frames: Sequence[np.ndarray], path: str | Path, fps: int = 30) -> Path:
        from PIL import Image
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        imgs = [Image.fromarray(f, mode="RGBA").convert("P", palette=Image.ADAPTIVE) for f in frames]
        imgs[0].save(path, save_all=True, append_images=imgs[1:],
                     duration=int(1000 / max(fps, 1)), loop=0, optimize=True)
        return path

    def _infer_view(self, world: FluidWorld) -> tuple[float, float, float, float]:
        pad = 0.15
        if world.particles.count == 0:
            return (-1.0, -1.0, 1.0, 1.0)
        pos = world.particles.pos
        x0 = float(pos[:, 0].min()); x1 = float(pos[:, 0].max())
        y0 = float(pos[:, 1].min()); y1 = float(world.floor_y)
        w = max(x1 - x0, 1.0); h = max(y1 - y0, 1.0)
        return (x0 - w * pad, y0 - h * pad, x1 + w * pad, y1 + h * pad)

    def _background(self) -> np.ndarray:
        cfg = self.config
        h, w = cfg.height, cfg.width
        key = (h, w, cfg.bg_top, cfg.bg_bottom)
        cached = getattr(self, "_bg_f32_cache", None)
        if cached is None or cached[0] != key:
            top = np.asarray(cfg.bg_top, dtype=np.float32)
            bot = np.asarray(cfg.bg_bottom, dtype=np.float32)
            t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
            col = top[None, None, :] * (1.0 - t) + bot[None, None, :] * t
            bg = np.broadcast_to(col, (h, w, 3)).astype(np.float32)
            # Store an immutable canonical bytes; each render copies it.
            self._bg_f32_cache = (key, bg.tobytes())
            cached = self._bg_f32_cache
        # frombuffer over a bytes object yields a read-only ndarray —
        # caller mutates `hdr` in place, so make a writeable copy.
        return np.frombuffer(cached[1], dtype=np.float32).reshape(h, w, 3).copy()

    def _background_u8(self) -> bytes:
        """Return the cached u8 background bytes (read-only).

        Same shape as ``_background()`` but pre-quantised to u8 and cached
        keyed on (h, w, bg_top, bg_bottom). The native path writes directly
        into a u8 bytearray so we just need the immutable starting state.
        """
        cfg = self.config
        h, w = cfg.height, cfg.width
        key = (h, w, cfg.bg_top, cfg.bg_bottom)
        cached = getattr(self, "_bg_u8_cache", None)
        if cached is None or cached[0] != key:
            top = np.asarray(cfg.bg_top, dtype=np.float32)
            bot = np.asarray(cfg.bg_bottom, dtype=np.float32)
            t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
            col = top[None, None, :] * (1.0 - t) + bot[None, None, :] * t
            bg = np.broadcast_to(col, (h, w, 3))
            bg_u8 = np.clip(bg, 0.0, 255.0).astype(np.uint8).tobytes()
            self._bg_u8_cache = (key, bg_u8)
            cached = self._bg_u8_cache
        return cached[1]

    def _world_to_screen(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        sx = (x - wx0) / max(wx1 - wx0, _EPS) * cfg.width
        sy = (y - wy0) / max(wy1 - wy0, _EPS) * cfg.height
        return sx.astype(np.float32), sy.astype(np.float32)

    def _draw_floor(self, hdr: np.ndarray, world: FluidWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        fy = world.floor_y
        if not (wy0 <= fy <= wy1):
            return
        _, sy = self._world_to_screen(np.zeros(1, dtype=np.float32),
                                      np.full(1, fy, dtype=np.float32))
        y = int(np.clip(float(sy[0]), 0, cfg.height - 1))
        hdr[y, :, :] = np.asarray(cfg.floor_color, dtype=np.float32)

    def _draw_floor_u8(self, world: FluidWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        fy = world.floor_y
        if not (wy0 <= fy <= wy1):
            return
        _, sy = self._world_to_screen(np.zeros(1, dtype=np.float32),
                                      np.full(1, fy, dtype=np.float32))
        y = int(np.clip(float(sy[0]), 0, cfg.height - 1))
        # Stamp one floor-coloured row directly into the u8 buffer.
        row_off = y * cfg.width * 3
        r, g, b = (int(c) & 0xff for c in cfg.floor_color)
        floor_row = bytes((r, g, b)) * cfg.width
        self._u8_buf[row_off:row_off + cfg.width * 3] = floor_row

    def _draw_walls(self, hdr: np.ndarray, world: FluidWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        col = np.asarray(cfg.wall_color, dtype=np.float32)
        for wall_x in (world.wall_x_min, world.wall_x_max):
            if not (wx0 <= wall_x <= wx1):
                continue
            sx, _ = self._world_to_screen(np.full(1, wall_x, dtype=np.float32),
                                          np.zeros(1, dtype=np.float32))
            x = int(np.clip(float(sx[0]), 0, cfg.width - 1))
            hdr[:, x, :] = col

    def _draw_walls_u8(self, world: FluidWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        r, g, b = (int(c) & 0xff for c in cfg.wall_color)
        W = cfg.width
        H = cfg.height
        buf = self._u8_buf
        for wall_x in (world.wall_x_min, world.wall_x_max):
            if not (wx0 <= wall_x <= wx1):
                continue
            sx, _ = self._world_to_screen(np.full(1, wall_x, dtype=np.float32),
                                          np.zeros(1, dtype=np.float32))
            x = int(np.clip(float(sx[0]), 0, W - 1))
            # Stamp a single-pixel-wide column. Loop in Python over H is
            # cheap at 240 rows — well under 0.1 ms.
            for y in range(H):
                off = (y * W + x) * 3
                buf[off] = r
                buf[off + 1] = g
                buf[off + 2] = b

    def _draw_particles(self, hdr: np.ndarray, world: FluidWorld) -> None:
        cfg = self.config
        p = world.particles
        if p.count == 0:
            return
        sx, sy = self._world_to_screen(p.pos[:, 0], p.pos[:, 1])

        # Resolve per-particle colors via the material_id table. OOB ids
        # fall back to id 0 to match the pre-batch behavior.
        n_mats = len(world.materials)
        if n_mats == 0:
            return
        halo_table = np.asarray(
            [m.halo_color for m in world.materials], dtype=np.float32)
        core_table = np.asarray(
            [m.render_color for m in world.materials], dtype=np.float32)
        mids = np.asarray(p.material_id, dtype=np.int64)
        mids = np.where((mids >= 0) & (mids < n_mats), mids, 0)
        halo_cols = halo_table[mids]   # (N, 3)
        core_cols = core_table[mids]   # (N, 3)

        # Halo + core fused into one tile composite per particle: one
        # distance computation, one scatter pass.  Equivalent to halo-then-
        # core blending because we apply them in alpha-over order against a
        # local per-particle accumulator before mixing into hdr.
        self._batch_splat_two_pass(
            hdr, sx, sy,
            halo_cols, cfg.halo_radius_px, cfg.halo_alpha,
            core_cols, cfg.particle_radius_px, 1.0,
        )

    def _draw_particles_u8(self, world: FluidWorld) -> None:
        """Native disc-splat path: halo pass + core pass via Rust.

        Two ``rasterize_circles`` calls write directly into the shared u8
        bytearray.  Halo first (pre-blended with halo_alpha against the
        background), then core on top (last-writer-wins at the disc
        centre, which mirrors the alpha-over chain in
        ``_batch_splat_two_pass``).
        """
        cfg = self.config
        p = world.particles
        if p.count == 0:
            return
        n_mats = len(world.materials)
        if n_mats == 0:
            return

        sx, sy = self._world_to_screen(p.pos[:, 0], p.pos[:, 1])

        # Per-particle color tables. Cache the LUTs keyed by the material
        # registry's identity tuple — for a static scene this collapses to
        # one dict lookup per frame.
        mat_ids = tuple(id(m) for m in world.materials)
        cached = getattr(self, "_mat_lut_cache", None)
        if cached is None or cached[0] != mat_ids:
            halo_table = np.asarray(
                [m.halo_color for m in world.materials], dtype=np.float32)
            core_table = np.asarray(
                [m.render_color for m in world.materials], dtype=np.float32)
            self._mat_lut_cache = (mat_ids, halo_table, core_table)
            cached = self._mat_lut_cache
        halo_table = cached[1]
        core_table = cached[2]

        mids = np.asarray(p.material_id, dtype=np.int64)
        mids = np.where((mids >= 0) & (mids < n_mats), mids, 0)

        # Pre-blend halo color with halo_alpha against the background top
        # color (cheap approximation — exact alpha-over against the live
        # gradient would require a per-pixel float blend that defeats the
        # whole purpose of the native path). For the typical halo_alpha
        # ~0.45 + the dark blue background, the result is visually nearly
        # identical because the splatted core overwrites the disc centre.
        bg_top = np.asarray(cfg.bg_top, dtype=np.float32)
        a = float(cfg.halo_alpha)
        halo_blended = halo_table * a + bg_top * (1.0 - a)
        halo_cols = halo_blended[mids]
        core_cols = core_table[mids]

        halo_u8 = np.clip(halo_cols, 0.0, 255.0).astype(np.uint8)
        core_u8 = np.clip(core_cols, 0.0, 255.0).astype(np.uint8)

        sx_b = np.ascontiguousarray(sx, dtype=np.float32).tobytes()
        sy_b = np.ascontiguousarray(sy, dtype=np.float32).tobytes()

        r_halo = max(int(round(cfg.halo_radius_px)), 1)
        r_core = max(int(round(cfg.particle_radius_px)), 1)

        W, H = cfg.width, cfg.height
        # Halo pass first.
        _native_core.rasterize_circles(
            self._u8_buf,
            int(W), int(H),
            sx_b, sy_b,
            halo_u8.tobytes(),
            int(r_halo),
        )
        # Core on top.
        _native_core.rasterize_circles(
            self._u8_buf,
            int(W), int(H),
            sx_b, sy_b,
            core_u8.tobytes(),
            int(r_core),
        )

    def _batch_splat_two_pass(self, hdr: np.ndarray,
                              sx: np.ndarray, sy: np.ndarray,
                              colors_halo: np.ndarray, r_halo: float, alpha_halo: float,
                              colors_core: np.ndarray, r_core: float, alpha_core: float
                              ) -> None:
        """Composite the halo and core discs into a single tile, then
        scatter to the HDR image with one slice-write per particle.

        Both discs share the same centre, so we compute the per-pixel
        distance ONCE (sized to the larger of the two radii) and derive
        both alphas from it.  The resulting blended (color, alpha) is
        applied to hdr with standard porter-duff "over" — equivalent to
        the prior two sequential passes.
        """
        cfg = self.config
        H, W = cfg.height, cfg.width
        N = sx.shape[0]
        if N == 0:
            return
        r = max(r_halo, r_core, 0.5)
        half = int(np.ceil(r)) + 1
        size = 2 * half + 1
        ix = np.floor(sx).astype(np.int32)
        iy = np.floor(sy).astype(np.int32)
        tile_x0 = ix - half
        tile_y0 = iy - half
        fx = sx - ix.astype(np.float32)
        fy = sy - iy.astype(np.float32)

        # (N, size, size) squared distance.
        local = np.arange(size, dtype=np.float32) - float(half)
        dx = local[None, None, :] - fx[:, None, None]
        dy = local[None, :, None] - fy[:, None, None]
        d = dx * dx + dy * dy
        np.sqrt(d, out=d)

        # Halo alpha: clip(1 - (d - (r_halo-1))/1.4, 0, 1) * alpha_halo.
        a_halo = (1.0 - (d - (r_halo - 1.0)) / 1.4)
        np.clip(a_halo, 0.0, 1.0, out=a_halo)
        if alpha_halo != 1.0:
            a_halo *= alpha_halo

        # Core alpha (same falloff, smaller radius, opaque).
        a_core = (1.0 - (d - (r_core - 1.0)) / 1.4)
        np.clip(a_core, 0.0, 1.0, out=a_core)
        if alpha_core != 1.0:
            a_core *= alpha_core

        # Composite halo OVER bg, then core OVER (halo OVER bg).  Express
        # as: out_color = halo*ah*(1-ac) + core*ac, out_alpha =
        # ah*(1-ac) + ac.  Then blend into hdr with out_alpha.
        a_h_eff = a_halo * (1.0 - a_core)                              # (N, h, w)
        # Combined "color * alpha" buffer (pre-multiplied alpha form).
        c_buf = (colors_halo[:, None, None, :] * a_h_eff[..., None]
                 + colors_core[:, None, None, :] * a_core[..., None])  # (N, h, w, 3)
        a_total = a_h_eff + a_core                                     # (N, h, w)
        one_minus = 1.0 - a_total

        # Pre-compute scatter indices in pure numpy.
        x1 = tile_x0 + size; y1 = tile_y0 + size
        sx0 = np.maximum(tile_x0, 0)
        sy0 = np.maximum(tile_y0, 0)
        sx1 = np.minimum(x1, W)
        sy1 = np.minimum(y1, H)
        tx0 = sx0 - tile_x0
        ty0 = sy0 - tile_y0
        on_screen = (sx1 > sx0) & (sy1 > sy0)
        if not on_screen.any():
            return

        sx0_l = sx0.tolist(); sy0_l = sy0.tolist()
        sx1_l = sx1.tolist(); sy1_l = sy1.tolist()
        tx0_l = tx0.tolist(); ty0_l = ty0.tolist()
        for i in np.flatnonzero(on_screen):
            ix0 = sx0_l[i]; iy0 = sy0_l[i]
            ix1 = sx1_l[i]; iy1 = sy1_l[i]
            jx0 = tx0_l[i]; jy0 = ty0_l[i]
            jx1 = jx0 + (ix1 - ix0); jy1 = jy0 + (iy1 - iy0)
            region = hdr[iy0:iy1, ix0:ix1]
            region *= one_minus[i, jy0:jy1, jx0:jx1, None]
            region += c_buf[i, jy0:jy1, jx0:jx1]

    def _draw_softbody_overlay(self, hdr: np.ndarray, softbody) -> None:
        nodes = softbody.nodes
        beams = softbody.beams
        if beams.count == 0:
            return
        a = beams.node_a.astype(np.int64)
        b = beams.node_b.astype(np.int64)
        pa = nodes.pos[a]
        pb = nodes.pos[b]
        sxa, sya = self._world_to_screen(pa[:, 0], pa[:, 1])
        sxb, syb = self._world_to_screen(pb[:, 0], pb[:, 1])
        col = np.asarray((180, 180, 200), dtype=np.float32)
        for i in range(beams.count):
            if beams.broken[i]:
                continue
            self._line(hdr, float(sxa[i]), float(sya[i]),
                       float(sxb[i]), float(syb[i]), col, 1.4)

    def _primary_material(self, world: FluidWorld):
        p = world.particles
        if p.count == 0:
            return world.materials[0]
        ids = p.material_id
        counts = np.bincount(ids, minlength=len(world.materials))
        return world.materials[int(np.argmax(counts))]

    def _draw_surface(self, hdr: np.ndarray, world: FluidWorld) -> np.ndarray | None:
        """Marching-squares + watery shader passes.

        Returns the screen-space density field (or None if the world is
        empty). The dual-view path reuses it to crossfade droplet tails
        against surface fill alpha.
        """
        cfg = self.config
        p = world.particles
        if p.count == 0:
            return None

        mat = self._primary_material(world)
        h = float(mat.kernel_radius)
        wx0, wy0, wx1, wy1 = cfg.world_view

        cells_per_h = max(int(cfg.surface_grid_cells_per_h), 1)
        cell_size = max(h / cells_per_h, _EPS)
        # Pad the grid one kernel radius around the view so blobs touching the
        # edge of the camera don't get a hard truncation.
        pad = h
        gx0 = wx0 - pad
        gy0 = wy0 - pad
        nx = int(np.ceil((wx1 - wx0 + 2 * pad) / cell_size)) + 1
        ny = int(np.ceil((wy1 - wy0 + 2 * pad) / cell_size)) + 1
        nx = max(nx, 4)
        ny = max(ny, 4)

        density = sample_density_grid(
            p.pos, p.mass, h, (gx0, gy0), (nx, ny), cell_size,
        )
        if density.size == 0 or float(density.max()) <= 0.0:
            return None

        d_max = float(density.max())
        iso = d_max * float(cfg.surface_isovalue_factor)
        H, W = cfg.height, cfg.width

        core_col = np.asarray(mat.render_color, dtype=np.float32)
        halo_col = np.asarray(mat.halo_color, dtype=np.float32)

        # Light dir (unit). Used by lambert + refraction + specular.
        ldx, ldy = cfg.surface_light_dir
        llen = float(np.hypot(ldx, ldy)) or 1.0
        ldx, ldy = ldx / llen, ldy / llen
        softness = float(cfg.surface_fill_softness)

        all_native = _HAS_NATIVE_FLUID_SHADER and hasattr(_native_core, "surface_base_shade_rs")
        col_ba: bytearray | None = None
        d_screen_ba: bytearray | None = None
        alpha_ba: bytearray | None = None
        if all_native:
            # Fused Rust path: resample density -> d_screen + alpha + rim
            # + gradients + normals + base col, all in one parallel pass.
            # The downstream polish kernels re-derive gradients/normals/rim
            # from `d_screen` directly, so we ask Rust to fill these
            # buffers into scratch sinks we never read in Python.
            density_bytes = np.ascontiguousarray(density, dtype=np.float32).tobytes()
            # Persistent bytearrays — re-used frame to frame to avoid the
            # 3-5 MB of fresh allocations per render.
            need_key = (H, W)
            cache = getattr(self, "_surface_ba_cache", None)
            if cache is None or cache[0] != need_key:
                cache = (
                    need_key,
                    bytearray(H * W * 3 * 4),     # col
                    bytearray(H * W * 4),         # d_screen
                    bytearray(H * W * 4),         # alpha
                    bytearray(H * W * 4),         # scratch 1
                    bytearray(H * W * 4),         # scratch 2
                    bytearray(H * W * 4),         # scratch 3
                    bytearray(H * W * 4),         # scratch 4
                    bytearray(H * W * 4),         # scratch 5
                    bytearray(H * W * 3 * 4),     # hdr_ba
                    bytearray(H * W * 4),         # speed_screen
                )
                self._surface_ba_cache = cache
            (_, col_ba, d_screen_ba, alpha_ba,
             scratch1, scratch2, scratch3, scratch4, scratch5,
             hdr_ba_cached, speed_ba_cached) = cache
            _native_core.surface_base_shade_rs(
                density_bytes, int(nx), int(ny),
                float(gx0), float(gy0), float(cell_size),
                float(wx0), float(wy0), float(wx1), float(wy1),
                int(W), int(H),
                float(iso), float(softness),
                float(cfg.surface_lambert_strength),
                float(ldx), float(ldy),
                float(core_col[0]), float(core_col[1]), float(core_col[2]),
                float(halo_col[0]), float(halo_col[1]), float(halo_col[2]),
                col_ba, d_screen_ba, alpha_ba,
                scratch1, scratch2, scratch3, scratch4, scratch5,
            )
            col = None  # type: ignore  — bytearrays are canonical now
            d_screen = None  # type: ignore
            alpha = None  # type: ignore
            gx_d = gy_d = nx_v = ny_v = rim2d = None  # type: ignore
            I0g = J0g = I1g = J1g = FXg = FYg = None  # type: ignore
        else:
            # Resample density to screen via bilinear interpolation.
            col_idx = np.arange(W, dtype=np.float32) + 0.5
            row_idx = np.arange(H, dtype=np.float32) + 0.5
            wxs = wx0 + col_idx * (wx1 - wx0) / max(W, 1)
            wys = wy0 + row_idx * (wy1 - wy0) / max(H, 1)
            # Map world -> grid fractional cell coords (cell *centres* at i+0.5)
            gx_f = (wxs - gx0) / cell_size - 0.5
            gy_f = (wys - gy0) / cell_size - 0.5
            i0 = np.clip(np.floor(gx_f).astype(np.int32), 0, nx - 2)
            j0 = np.clip(np.floor(gy_f).astype(np.int32), 0, ny - 2)
            fx = (gx_f - i0).astype(np.float32)
            fy = (gy_f - j0).astype(np.float32)
            I0g, J0g = np.meshgrid(i0, j0, indexing="xy")
            I1g = I0g + 1
            J1g = J0g + 1
            FXg, FYg = np.meshgrid(fx, fy, indexing="xy")

            d00 = density[J0g, I0g]
            d10 = density[J0g, I1g]
            d01 = density[J1g, I0g]
            d11 = density[J1g, I1g]
            d_screen = (
                d00 * (1.0 - FXg) * (1.0 - FYg)
                + d10 * FXg * (1.0 - FYg)
                + d01 * (1.0 - FXg) * FYg
                + d11 * FXg * FYg
            ).astype(np.float32)

            # Smoothstep alpha mask: 0 below iso*(1-softness/2), 1 above iso*(1+softness/2)
            edge0 = iso * max(1.0 - softness * 0.5, 0.05)
            edge1 = iso * (1.0 + softness * 0.5)
            denom = max(edge1 - edge0, _EPS)
            t = np.clip((d_screen - edge0) / denom, 0.0, 1.0)
            alpha2d = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
            alpha = alpha2d[..., None]

            # Screen-space density gradient (used by Lambert + refraction + rim).
            gx_d = np.zeros_like(d_screen, dtype=np.float32)
            gy_d = np.zeros_like(d_screen, dtype=np.float32)
            gx_d[:, 1:-1] = (d_screen[:, 2:] - d_screen[:, :-2]) * 0.5
            gy_d[1:-1, :] = (d_screen[2:, :] - d_screen[:-2, :]) * 0.5

            if cfg.surface_lambert_strength > 0.0:
                mag = np.sqrt(gx_d * gx_d + gy_d * gy_d)
                safe = mag > _EPS
                nx_v = np.zeros_like(gx_d)
                ny_v = np.zeros_like(gy_d)
                nx_v[safe] = -gx_d[safe] / mag[safe]
                ny_v[safe] = -gy_d[safe] / mag[safe]
                lambert = np.clip(-(nx_v * ldx + ny_v * ldy), 0.0, 1.0)
                shade = 1.0 + cfg.surface_lambert_strength * lambert[..., None]
            else:
                nx_v = np.zeros_like(gx_d)
                ny_v = np.zeros_like(gy_d)
                shade = np.ones((H, W, 1), dtype=np.float32)

            # Brighter rim near the surface (where d_screen ≈ iso).
            rim2d = np.exp(-((d_screen - iso) ** 2) / max((iso * 0.25) ** 2, _EPS)).astype(np.float32)
            rim = rim2d[..., None]
            col = core_col[None, None, :] * shade + (halo_col - core_col)[None, None, :] * rim * 0.4

        # --- Polish chain (turbulence/refraction/specular) ---------------
        # Hot path: route each pass through Rust when available. The Rust
        # kernels operate in-place on a bytearray view of the float32 RGB
        # buffer; we materialise that once at the start of the polish chain
        # and convert back to numpy after for the alpha composite step.
        use_native_polish = (
            _HAS_NATIVE_FLUID_SHADER
            and (
                cfg.surface_turbulence_enabled
                or cfg.surface_refraction_enabled
                or cfg.surface_specular_enabled
            )
        )
        if all_native:
            # Bytearrays are canonical — no numpy roundtrips during polish.
            assert col_ba is not None and d_screen_ba is not None
            pass
        elif use_native_polish:
            col_ba = bytearray(np.ascontiguousarray(col, dtype=np.float32).tobytes())
            d_screen_ba = bytearray(np.ascontiguousarray(d_screen, dtype=np.float32).tobytes())

        # --- Turbulence-driven white foam --------------------------------
        # Per-pixel velocity field via the same kernel-density splat, weighted
        # by particle |v|. Speed sampled the same way density was, then biases
        # the colour toward white where the fluid is fast.
        if cfg.surface_turbulence_enabled and cfg.surface_turbulence_strength > 0.0:
            speed_screen = self._sample_speed_screen(
                p, h, (gx0, gy0), (nx, ny), cell_size,
                I0g, J0g, I1g, J1g, FXg, FYg, density,
            )
            if use_native_polish:
                speed_bytes = np.ascontiguousarray(speed_screen, dtype=np.float32).tobytes()
                _native_core.turbulence_foam_rs(
                    col_ba, speed_bytes, int(W), int(H),
                    float(cfg.surface_turbulence_speed),
                    float(cfg.surface_turbulence_strength),
                )
            else:
                v_ref = max(float(cfg.surface_turbulence_speed), _EPS)
                foam_t = np.clip(speed_screen / v_ref, 0.0, 1.0).astype(np.float32)
                # smoothstep
                foam_t = foam_t * foam_t * (3.0 - 2.0 * foam_t)
                foam_w = (foam_t * float(cfg.surface_turbulence_strength))[..., None]
                # HDR-overbright white so the post-tonemap "x/(1+x)" path still
                # reads as ~white instead of saturating to mid-grey. Tonemap
                # of 800 ≈ 0.99 → 248 after gamma.
                white = np.full((1, 1, 3), 800.0, dtype=np.float32)
                col = col * (1.0 - foam_w) + white * foam_w

        # --- Refraction warp via density gradient ------------------------
        # Nearest-neighbour gather (single fancy-index pass) — bilinear was
        # ~7ms at 280×220 while this is ~2ms. Refraction is small-amplitude
        # noise so the visual cost of NN is negligible.
        if cfg.surface_refraction_enabled and cfg.surface_refraction_strength > 0.0:
            if use_native_polish:
                # Rust path: re-derive density gradient from d_screen and
                # apply NN gather in one pass. Requires a second bytearray
                # of equal size (the "src" of the gather).
                col_src_bytes = bytes(col_ba)
                _native_core.refraction_warp_rs(
                    col_src_bytes, col_ba, bytes(d_screen_ba),
                    int(W), int(H),
                    float(d_max), float(cfg.surface_refraction_strength),
                )
            else:
                inv = 1.0 / max(d_max, _EPS)
                # Round offsets directly to int to skip the fractional math.
                dx_px = (gx_d * inv) * cfg.surface_refraction_strength
                dy_px = (gy_d * inv) * cfg.surface_refraction_strength
                np.clip(dx_px, -3.0, 3.0, out=dx_px)
                np.clip(dy_px, -3.0, 3.0, out=dy_px)
                xs_idx = (np.arange(W, dtype=np.float32)[None, :] + dx_px)
                ys_idx = (np.arange(H, dtype=np.float32)[:, None] + dy_px)
                np.clip(xs_idx, 0.0, W - 1.0, out=xs_idx)
                np.clip(ys_idx, 0.0, H - 1.0, out=ys_idx)
                x0i = xs_idx.astype(np.int32)
                y0i = ys_idx.astype(np.int32)
                col = col[y0i, x0i]

        # --- Specular highlight along the rim normal --------------------
        if cfg.surface_specular_enabled and cfg.surface_specular_strength > 0.0:
            if use_native_polish:
                tint = cfg.surface_specular_tint
                _native_core.specular_pass_rs(
                    col_ba, bytes(d_screen_ba), int(W), int(H),
                    float(iso), float(ldx), float(ldy),
                    float(tint[0]), float(tint[1]), float(tint[2]),
                    float(cfg.surface_specular_strength),
                )
            else:
                # Half-vector spec: light dir vs upward-pointing surface normal.
                # nx_v/ny_v already point outward (-grad). Tight lobe via pow(8).
                spec_dot = np.clip(-(nx_v * ldx + ny_v * ldy), 0.0, 1.0)
                spec = (spec_dot ** 8.0) * rim2d
                spec_tint = np.asarray(cfg.surface_specular_tint, dtype=np.float32)
                # 2.5× HDR overdrive so the post-tonemap chain reads as a
                # bright white-cyan glint rather than a muted highlight.
                spec_w = (spec * float(cfg.surface_specular_strength) * 2.5)[..., None]
                col = col + spec_tint[None, None, :] * spec_w

        # ---- Composite + godrays + outline path ---------------------------
        # When in the all-native path, keep hdr as a bytearray throughout
        # to avoid numpy roundtrips. We've been operating on `hdr` numpy
        # which was passed in — copy it into a bytearray, do remaining
        # passes natively, then copy back at the very end.
        if all_native and _HAS_NATIVE_FLUID_SHADER and hasattr(_native_core, "alpha_composite_hdr_rs"):
            # Re-use the persistent hdr bytearray; copy from the numpy hdr.
            hdr_ba = hdr_ba_cached
            hdr_ba[:] = np.ascontiguousarray(hdr, dtype=np.float32).tobytes()
            _native_core.alpha_composite_hdr_rs(
                hdr_ba, bytes(col_ba), bytes(alpha_ba),
                int(W), int(H),
            )
            if cfg.surface_godrays_enabled and cfg.surface_godray_strength > 0.0:
                _native_core.godrays_rs(
                    hdr_ba, bytes(d_screen_ba), int(W), int(H),
                    float(iso), float(ldx), float(ldy),
                    int(max(cfg.surface_godray_steps, 1)),
                    float(cfg.surface_godray_step_px),
                    float(cfg.surface_godray_strength),
                )

            # Outline pass on hdr_ba (still in native float).
            segments = extract_isolines(density, iso, (gx0, gy0), cell_size)
            if segments.shape[0] > 0:
                outline_col = (halo_col * 1.15).clip(0.0, 255.0)
                sxa, sya = self._world_to_screen(segments[:, 0, 0], segments[:, 0, 1])
                sxb, syb = self._world_to_screen(segments[:, 1, 0], segments[:, 1, 1])
                _native_core.rasterize_lines_hdr_rs(
                    hdr_ba,
                    np.ascontiguousarray(sxa, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(sya, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(sxb, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(syb, dtype=np.float32).tobytes(),
                    float(outline_col[0]), float(outline_col[1]), float(outline_col[2]),
                    int(W), int(H), float(cfg.surface_outline_width_px),
                )

            # Single round-trip back to the numpy hdr the caller expects.
            hdr[:] = np.frombuffer(bytes(hdr_ba), dtype=np.float32).reshape(H, W, 3)
            # Return a numpy view of d_screen for downstream dual_view path.
            d_screen_np = np.frombuffer(bytes(d_screen_ba), dtype=np.float32).reshape(H, W).copy()
            return d_screen_np

        # Mixed-mode fallback (some kernels missing). Round-trip col_ba/d
        # back to numpy where they get composited via numpy.
        if use_native_polish and not all_native:
            col = np.frombuffer(bytes(col_ba), dtype=np.float32).reshape(H, W, 3).copy()

        # Composite the surface onto the HDR background.
        hdr[:] = hdr * (1.0 - alpha) + col * alpha

        # --- Godrays — cheap fake screen-space god-rays toward light -----
        if cfg.surface_godrays_enabled and cfg.surface_godray_strength > 0.0:
            if _HAS_NATIVE_FLUID_SHADER:
                hdr_ba = bytearray(np.ascontiguousarray(hdr, dtype=np.float32).tobytes())
                d_bytes = (
                    bytes(d_screen_ba) if d_screen_ba is not None else
                    np.ascontiguousarray(d_screen, dtype=np.float32).tobytes()
                )
                _native_core.godrays_rs(
                    hdr_ba, d_bytes, int(W), int(H),
                    float(iso), float(ldx), float(ldy),
                    int(max(cfg.surface_godray_steps, 1)),
                    float(cfg.surface_godray_step_px),
                    float(cfg.surface_godray_strength),
                )
                hdr[:] = np.frombuffer(bytes(hdr_ba), dtype=np.float32).reshape(H, W, 3)
            else:
                ray = self._compute_godrays(d_screen, iso, ldx, ldy)
                if ray is not None:
                    # Add atop the HDR — godrays are additive light, so they fade
                    # over the background regardless of alpha. Scale by a soft
                    # mask so rays only show in the immediate vicinity of fluid.
                    hdr[:] = np.clip(hdr + ray[..., None] * 60.0, 0.0, 4095.0)

        # Crisp outline via marching squares
        segments = extract_isolines(density, iso, (gx0, gy0), cell_size)
        if segments.shape[0] > 0:
            outline_col = (halo_col * 1.15).clip(0.0, 255.0)
            sxa, sya = self._world_to_screen(segments[:, 0, 0], segments[:, 0, 1])
            sxb, syb = self._world_to_screen(segments[:, 1, 0], segments[:, 1, 1])
            if _HAS_NATIVE_FLUID_SHADER and hasattr(_native_core, "rasterize_lines_hdr_rs"):
                # Native batched outline pass — one call rasterises every
                # segment with shared colour + thickness, avoiding the
                # 48-call Python loop.
                hdr_ba = bytearray(np.ascontiguousarray(hdr, dtype=np.float32).tobytes())
                _native_core.rasterize_lines_hdr_rs(
                    hdr_ba,
                    np.ascontiguousarray(sxa, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(sya, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(sxb, dtype=np.float32).tobytes(),
                    np.ascontiguousarray(syb, dtype=np.float32).tobytes(),
                    float(outline_col[0]), float(outline_col[1]), float(outline_col[2]),
                    int(W), int(H), float(cfg.surface_outline_width_px),
                )
                hdr[:] = np.frombuffer(bytes(hdr_ba), dtype=np.float32).reshape(H, W, 3)
            else:
                for i in range(segments.shape[0]):
                    self._line(hdr, float(sxa[i]), float(sya[i]),
                               float(sxb[i]), float(syb[i]),
                               outline_col, cfg.surface_outline_width_px)

        return d_screen

    def _sample_speed_screen(
        self,
        p,
        h: float,
        grid_origin: tuple[float, float],
        n_cells: tuple[int, int],
        cell_size: float,
        I0g: np.ndarray | None, J0g: np.ndarray | None,
        I1g: np.ndarray | None, J1g: np.ndarray | None,
        FXg: np.ndarray | None, FYg: np.ndarray | None,
        density_grid: np.ndarray,
    ) -> np.ndarray:
        """Bilinearly-sample particle speed onto screen pixels.

        Returns a (H, W) float32 array of per-pixel particle speed (m/s),
        only meaningful where the density grid is non-trivial.
        """
        cfg = self.config
        H, W = cfg.height, cfg.width
        nx, ny = int(n_cells[0]), int(n_cells[1])
        gx0, gy0 = grid_origin
        speed = np.linalg.norm(p.vel, axis=1).astype(np.float32)
        # Reuse the same kernel splat but weighted by speed.
        sp_grid = sample_density_grid(
            p.pos, speed, h, grid_origin, n_cells, cell_size,
        )
        if _HAS_NATIVE_FLUID_SHADER and hasattr(_native_core, "speed_screen_rs"):
            sp_grid_b = np.ascontiguousarray(sp_grid, dtype=np.float32).tobytes()
            density_b = np.ascontiguousarray(density_grid, dtype=np.float32).tobytes()
            out_ba = bytearray(H * W * 4)
            wx0, wy0, wx1, wy1 = cfg.world_view
            _native_core.speed_screen_rs(
                sp_grid_b, density_b, out_ba,
                int(nx), int(ny),
                float(gx0), float(gy0), float(cell_size),
                float(wx0), float(wy0), float(wx1), float(wy1),
                int(W), int(H),
            )
            return np.frombuffer(bytes(out_ba), dtype=np.float32).reshape(H, W).copy()

        denom = density_grid + 1.0e-3
        sp_norm = (sp_grid / denom).astype(np.float32)
        sp00 = sp_norm[J0g, I0g]
        sp10 = sp_norm[J0g, I1g]
        sp01 = sp_norm[J1g, I0g]
        sp11 = sp_norm[J1g, I1g]
        sp_screen = (
            sp00 * (1.0 - FXg) * (1.0 - FYg)
            + sp10 * FXg * (1.0 - FYg)
            + sp01 * (1.0 - FXg) * FYg
            + sp11 * FXg * FYg
        ).astype(np.float32)
        return sp_screen

    def _compute_godrays(self, d_screen: np.ndarray, iso: float,
                         ldx: float, ldy: float) -> np.ndarray | None:
        """Cheap screen-space god-rays from the directional light.

        Marches N taps from each pixel toward the light and accumulates
        density-weighted brightness. Bright streaks emerge where the
        light passes through fluid.
        """
        cfg = self.config
        H, W = d_screen.shape
        steps = max(int(cfg.surface_godray_steps), 1)
        if steps <= 0:
            return None
        step_px = float(cfg.surface_godray_step_px)
        # March OPPOSITE the light dir to look toward the source.
        sx = -float(ldx) * step_px
        sy = -float(ldy) * step_px
        xs_base = np.arange(W, dtype=np.float32)[None, :]
        ys_base = np.arange(H, dtype=np.float32)[:, None]
        accum = np.zeros((H, W), dtype=np.float32)
        iso_inv = 1.0 / max(iso, _EPS)
        for k in range(1, steps + 1):
            xi = np.clip(xs_base + sx * k, 0.0, W - 1.0001)
            yi = np.clip(ys_base + sy * k, 0.0, H - 1.0001)
            x0i = xi.astype(np.int32)
            y0i = yi.astype(np.int32)
            # Nearest-neighbour sample is good enough for additive rays.
            sample = d_screen[y0i, x0i]
            # Weight: only contribute where density >= iso, fall off with k.
            mask = np.maximum(sample - iso, 0.0) * iso_inv
            accum += mask * (1.0 / float(k))
        accum *= float(cfg.surface_godray_strength) / max(steps, 1)
        # Modulate by distance from any fluid (fade rays away from blob).
        # Use the screen-density itself as a proxy "fluid is nearby" gate.
        nearby = np.clip(d_screen * iso_inv * 0.7, 0.0, 1.0)
        # Rays should be VISIBLE in front of the fluid too — multiply by
        # (1 - alpha_like) so they don't get washed by the surface fill.
        return accum * nearby

    def _draw_droplet_tails(self, hdr: np.ndarray, world: FluidWorld,
                            d_screen: np.ndarray) -> None:
        """Render sparsely-distributed particles as droplets with motion tails.

        Particles in HIGH-density regions are already drawn by the surface
        fill — their tails are suppressed (alpha 0). Particles in LOW-density
        regions (isolated splashes / fly-aways the marching-squares iso
        ignores) get a short velocity-aligned streak so the user sees them
        as droplets instead of disappearing.
        """
        cfg = self.config
        p = world.particles
        if p.count == 0:
            return

        # Sample d_screen at each particle's screen position to get its
        # local "blob-membership" weight.
        sx, sy = self._world_to_screen(p.pos[:, 0], p.pos[:, 1])
        H, W = cfg.height, cfg.width
        in_view = (sx >= 0) & (sx < W - 1) & (sy >= 0) & (sy < H - 1)
        if not np.any(in_view):
            return
        sx_v = sx[in_view]
        sy_v = sy[in_view]
        vel_v = p.vel[in_view]
        mids_v = p.material_id[in_view]

        ix = sx_v.astype(np.int32)
        iy = sy_v.astype(np.int32)
        local_density = d_screen[iy, ix]
        d_max = float(d_screen.max()) if d_screen.size > 0 else 0.0
        if d_max <= 0.0:
            return
        ratio = local_density / d_max  # 0..1
        thresh = float(cfg.droplet_density_factor)
        # Inverse smoothstep: alpha 1 below thresh*0.5, alpha 0 above thresh.
        t = np.clip((thresh - ratio) / max(thresh * 0.5, _EPS), 0.0, 1.0)
        droplet_alpha = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
        active = droplet_alpha > 0.02
        if not np.any(active):
            return

        sx_a = sx_v[active]
        sy_a = sy_v[active]
        vel_a = vel_v[active]
        a_a = droplet_alpha[active]
        mids_a = mids_v[active]

        # Tail direction: opposite to velocity (trailing behind motion).
        speed = np.linalg.norm(vel_a, axis=1)
        speed_norm = np.maximum(speed, _EPS)
        # Velocity in world-space → screen-space (sign-flip if axes differ).
        # _world_to_screen is just an affine scale, so velocity scales the
        # same way: scale by (W / view_w, H / view_h).
        wx0, wy0, wx1, wy1 = cfg.world_view
        scale_x = W / max(wx1 - wx0, _EPS)
        scale_y = H / max(wy1 - wy0, _EPS)
        vx_screen = vel_a[:, 0] * scale_x
        vy_screen = vel_a[:, 1] * scale_y
        v_screen_mag = np.hypot(vx_screen, vy_screen)
        # Tail length scales with speed but capped.
        tail_len = np.minimum(v_screen_mag * 0.04, float(cfg.droplet_tail_px))
        # Unit tail dir (backwards = -velocity).
        v_safe = np.maximum(v_screen_mag, _EPS)
        tdx = -vx_screen / v_safe
        tdy = -vy_screen / v_safe
        tail_x0 = sx_a
        tail_y0 = sy_a
        tail_x1 = sx_a + tdx * tail_len
        tail_y1 = sy_a + tdy * tail_len

        # Per-droplet colour from the material LUT.
        n_mats = len(world.materials)
        if n_mats == 0:
            return
        core_table = np.asarray(
            [m.render_color for m in world.materials], dtype=np.float32)
        halo_table = np.asarray(
            [m.halo_color for m in world.materials], dtype=np.float32)
        mids = np.asarray(mids_a, dtype=np.int64)
        mids = np.where((mids >= 0) & (mids < n_mats), mids, 0)
        core_cols = core_table[mids]
        halo_cols = halo_table[mids]

        # Render tails + heads. Tail is a line with alpha = a * tail_alpha
        # fading along its length; head is a small dot.
        tail_alpha_max = float(cfg.droplet_tail_alpha)
        active_idx = np.flatnonzero(active)
        N_active = active_idx.shape[0]
        if N_active == 0:
            return

        if _HAS_NATIVE_FLUID_SHADER:
            # Native path: marshal per-droplet arrays once and rasterise in
            # Rust. The Rust kernel handles the per-droplet "tail_len > 0.5"
            # gate via a streak-length check and writes both streak + head.
            tail_xy0 = np.column_stack([tail_x0, tail_y0]).astype(np.float32, copy=False)
            tail_xy1 = np.column_stack([tail_x1, tail_y1]).astype(np.float32, copy=False)
            head_xy = np.column_stack([sx_a, sy_a]).astype(np.float32, copy=False)
            head_cols_f = np.ascontiguousarray(core_cols, dtype=np.float32)
            halo_cols_f = np.ascontiguousarray(halo_cols, dtype=np.float32)
            alpha_arr = np.ascontiguousarray(a_a, dtype=np.float32)

            hdr_ba = bytearray(np.ascontiguousarray(hdr, dtype=np.float32).tobytes())
            _native_core.draw_droplet_tails_rs(
                hdr_ba,
                np.ascontiguousarray(tail_xy0).tobytes(),
                np.ascontiguousarray(tail_xy1).tobytes(),
                np.ascontiguousarray(head_xy).tobytes(),
                head_cols_f.tobytes(),
                halo_cols_f.tobytes(),
                alpha_arr.tobytes(),
                float(tail_alpha_max),
                int(W), int(H),
                float(cfg.particle_radius_px),
            )
            hdr[:] = np.frombuffer(bytes(hdr_ba), dtype=np.float32).reshape(H, W, 3)
            return

        for k in range(N_active):
            a = float(a_a[k])
            # Tail (motion-blur streak)
            if tail_len[k] > 0.5:
                self._tail_streak(
                    hdr,
                    float(tail_x0[k]), float(tail_y0[k]),
                    float(tail_x1[k]), float(tail_y1[k]),
                    halo_cols[k], a * tail_alpha_max,
                )
            # Head
            self._splat_dot(
                hdr, float(sx_a[k]), float(sy_a[k]),
                core_cols[k], cfg.particle_radius_px, a,
            )

    def _tail_streak(self, hdr: np.ndarray, x0: float, y0: float,
                     x1: float, y1: float, color: np.ndarray,
                     alpha_scale: float) -> None:
        """Anti-aliased line with linear-fade alpha from x0/y0 (full) to x1/y1 (0).

        Like _line but with a one-pixel-radius thickness and a length-aware
        alpha falloff so the trailing tip dissolves smoothly.
        """
        cfg = self.config
        H, W = cfg.height, cfg.width
        r = 1.2
        xmin = int(np.clip(np.floor(min(x0, x1) - r), 0, W - 1))
        xmax = int(np.clip(np.ceil(max(x0, x1) + r), 0, W - 1))
        ymin = int(np.clip(np.floor(min(y0, y1) - r), 0, H - 1))
        ymax = int(np.clip(np.ceil(max(y0, y1) + r), 0, H - 1))
        if xmax <= xmin or ymax <= ymin:
            return
        ys, xs = np.mgrid[ymin:ymax + 1, xmin:xmax + 1].astype(np.float32)
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy + _EPS
        t = ((xs - x0) * dx + (ys - y0) * dy) / L2
        t_clip = np.clip(t, 0.0, 1.0)
        px = x0 + t_clip * dx
        py = y0 + t_clip * dy
        d = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
        # Distance falloff (anti-aliased line) + length-aware tip fade.
        d_alpha = np.clip(1.0 - d / max(r, 0.5), 0.0, 1.0)
        length_alpha = np.clip(1.0 - t_clip, 0.0, 1.0)
        alpha = (d_alpha * length_alpha * alpha_scale)[..., None]
        region = hdr[ymin:ymax + 1, xmin:xmax + 1]
        region[:] = region * (1.0 - alpha) + color[None, None, :] * alpha

    def _splat_dot(self, hdr: np.ndarray, x: float, y: float,
                   color: np.ndarray, radius: float, alpha_scale: float) -> None:
        cfg = self.config
        H, W = cfg.height, cfg.width
        r = max(radius, 0.5)
        xmin = int(np.clip(np.floor(x - r), 0, W - 1))
        xmax = int(np.clip(np.ceil(x + r), 0, W - 1))
        ymin = int(np.clip(np.floor(y - r), 0, H - 1))
        ymax = int(np.clip(np.ceil(y + r), 0, H - 1))
        if xmax <= xmin or ymax <= ymin:
            return
        ys, xs = np.mgrid[ymin:ymax + 1, xmin:xmax + 1].astype(np.float32)
        d = np.sqrt((xs - x) ** 2 + (ys - y) ** 2)
        alpha = np.clip(1.0 - (d - (r - 1.0)) / 1.4, 0.0, 1.0) * alpha_scale
        alpha = alpha[..., None]
        region = hdr[ymin:ymax + 1, xmin:xmax + 1]
        region[:] = region * (1.0 - alpha) + color[None, None, :] * alpha

    def _line(self, hdr: np.ndarray, x0: float, y0: float, x1: float, y1: float,
              color: np.ndarray, thickness: float) -> None:
        cfg = self.config
        H, W = cfg.height, cfg.width
        r = max(thickness, 0.5)
        xmin = int(np.clip(np.floor(min(x0, x1) - r), 0, W - 1))
        xmax = int(np.clip(np.ceil(max(x0, x1) + r), 0, W - 1))
        ymin = int(np.clip(np.floor(min(y0, y1) - r), 0, H - 1))
        ymax = int(np.clip(np.ceil(max(y0, y1) + r), 0, H - 1))
        if xmax <= xmin or ymax <= ymin:
            return
        ys, xs = np.mgrid[ymin:ymax + 1, xmin:xmax + 1].astype(np.float32)
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy + _EPS
        t = ((xs - x0) * dx + (ys - y0) * dy) / L2
        t = np.clip(t, 0.0, 1.0)
        px = x0 + t * dx; py = y0 + t * dy
        d = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
        alpha = np.clip(1.0 - (d - (r - 1.0)) / 1.5, 0.0, 1.0)[..., None]
        region = hdr[ymin:ymax + 1, xmin:xmax + 1]
        region[:] = region * (1.0 - alpha) + color[None, None, :] * alpha

    def _post_process(self, hdr: np.ndarray) -> np.ndarray:
        cfg = self.config
        H, W = cfg.height, cfg.width
        if _HAS_NATIVE_FLUID_SHADER and hasattr(_native_core, "post_process_hdr_rs"):
            hdr_bytes = np.ascontiguousarray(hdr, dtype=np.float32).tobytes()
            out_ba = bytearray(H * W * 3)
            _native_core.post_process_hdr_rs(
                hdr_bytes, out_ba, int(W), int(H),
                float(cfg.tonemap_exposure), float(cfg.tonemap_gamma),
            )
            return np.frombuffer(bytes(out_ba), dtype=np.uint8).reshape(H, W, 3)
        x = hdr.astype(np.float32) / 255.0
        x = x * cfg.tonemap_exposure
        x = x / (1.0 + x)
        x = np.power(np.clip(x, 0.0, 1.0), 1.0 / max(cfg.tonemap_gamma, _EPS))
        x = np.clip(x * 255.0, 0.0, 255.0)
        x = np.nan_to_num(x, nan=0.0, posinf=255.0, neginf=0.0)
        return x.astype(np.uint8)


def render_world_gif(world: FluidWorld, out_path: str | Path, *,
                     step_fn=None, frame_count: int = 90, fps: int = 30,
                     steps_per_frame: int = 1,
                     config: FluidRenderConfig | None = None,
                     view_box: tuple[float, float, float, float] | None = None) -> Path:
    if step_fn is None:
        from .solver import pbf_step
        step_fn = pbf_step
    r = FluidRenderer(config=config)
    frames = list(r.render_sequence(world, frame_count, step_fn,
                                    steps_per_frame=steps_per_frame, view_box=view_box))
    return r.save_gif(frames, out_path, fps=fps)


__all__ = ["FluidRenderConfig", "FluidRenderer", "render_world_gif"]
