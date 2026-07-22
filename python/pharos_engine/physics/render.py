"""Physics scene → RGBA frame renderer.

Replaces the placeholder-only ``tests/visual/harness.py`` capture with a
real per-pixel visualiser of the hierarchical-hull simulator's cell state.
Mirrors the COMPOSITOR_WGSL shader from the legacy demo:

  * Per-material base colour
  * Heat → blackbody emissive glow (orange → yellow → white above melt)
  * Damage → darken
  * Displacement field advection at render time (material visibly moves
    along ``u`` away from its rest position)
  * Optional debug-channel view (any 3 cell fields as RGB)

CPU-only, numpy.  Fast enough for offline GIF emission; a GPU compositor
will follow when the GPU sim path lands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from pharos_engine.physics.cell import CELL_GRID_SIZE
from pharos_engine.physics.body import PhysicsBody
from pharos_engine.physics.world import PhysicsWorld


# --- per-material base colours (RGB 0..255) ---------------------------------
# Override-able from the user side via ``PhysicsRenderer.palette``.
DEFAULT_PALETTE: dict[str, tuple[int, int, int]] = {
    "steel":       (170, 175, 190),
    "iron":        (130, 130, 140),
    "stone":       (110, 105, 100),
    "glass":       (200, 220, 240),
    "wood":        (140,  95,  55),
    "rubber":      ( 50,  50,  55),
    "ice":         (200, 230, 250),
    "mud":         ( 95,  65,  40),
    "water":       ( 50, 100, 200),
    "sand":        (200, 175, 110),
    "clay":        (160, 110,  85),
    "lava_ground": (180,  60,  20),
    "lava":        (220,  80,  20),
    "metal":       (150, 155, 170),
    # --- additions covering the rest of MaterialPreset --------------------
    # Without these, materials like ``snow``/``concrete``/``magma`` fell
    # through the ``self.palette.get(..., (128, 128, 128))`` default and
    # rendered as featureless grey blobs.  Colours below are tuned so that
    # any two palette entries differ by at least 10 channels total — see
    # ``tests/test_palette_coverage.py``.
    "concrete":    (165, 175, 180),  # pale grey-blue (nudged off steel)
    "oil":         ( 40,  40,  35),  # very dark olive
    "slime":       ( 90, 220,  80),  # bright green
    "diamond":     (240, 245, 255),  # near-white with hint of blue
    "paper":       (230, 220, 195),  # off-white parchment
    "steam":       (210, 220, 235),  # pale blue-white
    "coral":       (220, 130, 110),  # pinkish orange
    "gold":        (235, 195,  60),  # warm yellow
    "magma":       (255, 120,  30),  # bright orange-red
    "snow":        (250, 252, 255),  # pure white (nudged off diamond)
    "cloth":       (200, 185, 165),  # neutral fabric beige
    "organic":     (130, 130,  90),  # earthy green-brown
}

# Channel indices (must match CELL_PIXEL_STRUCT in cell.py).
_IDX_U_X, _IDX_U_Y = 0, 1
_IDX_V_X, _IDX_V_Y = 2, 3
_IDX_DAMAGE = 8
_IDX_DENSITY = 9
_IDX_TEAR = 11
_IDX_HEAT = 12

# Bilinear advection scale: a u of 1.0 world unit shifts the rendered
# sample by 1 world pixel.  Fluid materials get a larger factor so
# splashes are visible.
_RIGID_ADVECT = 3.0
_FLUID_ADVECT = 10.0

# Oversample factor for the per-material noise overlay (Option 5 from
# docs/adaptive_simulation_strategies.md).  Higher = finer grain.  We
# pre-multiply integerised world coords by this before hashing so the
# noise pattern is finer than the cell grid.
_NOISE_OVERSAMPLE = 4


def _value_noise(
    x: np.ndarray,
    y: np.ndarray,
    t: int,
    seed: int = 0,
) -> np.ndarray:
    """Deterministic 32-bit value noise in ``[-1, 1]``.

    Inputs ``x`` and ``y`` are integer numpy arrays (any shape); ``t`` is
    a scalar frame index.  The hash mixes the inputs with three large
    primes, then applies two cheap shift-xor-multiply scramble rounds.
    Sufficient for "grainy texture" overlays — not a cryptographic hash.

    Returns a float32 array the same shape as ``x`` and ``y``.
    """
    # Promote to uint64 for the multiplies (avoids signed overflow weirdness
    # on 32-bit numpy builds).  Mask back to 32 bits after each step so the
    # arithmetic stays deterministic across platforms.
    mask = np.uint64(0xFFFFFFFF)
    xu = x.astype(np.int64).astype(np.uint64) & mask
    yu = y.astype(np.int64).astype(np.uint64) & mask
    tu = np.uint64(int(t) & 0xFFFFFFFF)
    su = np.uint64(int(seed) & 0xFFFFFFFF)

    h = (xu * np.uint64(374761393)
         + yu * np.uint64(668265263)
         + tu * np.uint64(1274126177)
         + su) & mask
    h = ((h ^ (h >> np.uint64(13))) * np.uint64(1274126177)) & mask
    h = (h ^ (h >> np.uint64(16))) & mask
    # Map [0, 2^32) → [-1, 1] in float32.
    return (h.astype(np.float32) / np.float32(0xFFFFFFFF)) * np.float32(2.0) - np.float32(1.0)


@dataclass
class PointLight:
    """A simple omnidirectional point light in world space.

    ``position`` is XY in world space; the renderer treats lights as living
    on the Z=0 plane same as cells.  ``color`` is RGB 0..255, ``intensity``
    is a scalar multiplier, and ``radius`` controls the inverse-square-ish
    falloff: brightness ~ intensity / (1 + (d/radius)^2).
    """
    position: tuple[float, float]
    color: tuple[float, float, float]
    intensity: float = 1.0
    radius: float = 200.0


@dataclass
class RenderConfig:
    width: int = 640
    height: int = 360
    bg_top: tuple[int, int, int] = (8, 8, 22)
    bg_bottom: tuple[int, int, int] = (24, 28, 52)
    world_view: tuple[float, float, float, float] = (-200.0, -100.0, 200.0, 250.0)
    # Bloom radius around hot pixels (cell-space). Set 0 to disable.
    heat_bloom_radius: int = 2
    # Heat -> emissive intensity gain; multiplied by heat / melt_point.
    heat_emission_gain: float = 2.0
    # Damage darkens the base colour by up to this fraction.
    damage_darken: float = 0.6
    # Whether to overlay a thin contact-flash on the highest-impact pixels.
    contact_flash: bool = True
    # --- lighting -----------------------------------------------------------
    # Empty list = legacy uniform shading.  When populated, surface normals
    # are reconstructed from the displacement field and Lambert-lit per cell.
    lights: list[PointLight] = field(default_factory=list)
    # Ambient term applied to base colour even without point lights.  Keeps
    # the unlit side of a body from going pitch-black.
    ambient_intensity: float = 0.25
    # Whether to reconstruct normals from u-field gradients at all.
    enable_normal_map: bool = True
    # Implicit "bulge toward camera" — higher values produce sphere-like
    # shading from a flat displacement field; 0 = flat surface.
    normal_curvature_bias: float = 0.3
    # FORWARD-SPLAT rendering: when True, each cell paints at
    # body.pos + (cell_local + u * splat_scale).  This is what makes
    # impact deformation VISIBLE — the body's silhouette bulges, squishes,
    # spreads in the direction of the displacement field.  False = legacy
    # backward sample (silhouette stays a circle; cells just show internal
    # flow).
    forward_splat: bool = True
    splat_scale: float = 5.0       # solids: how strongly u extends the silhouette
    splat_scale_fluid: float = 12.0  # fluids splash more
    splat_radius_px: int = 2        # per-cell splat footprint (1=tight, 2=blobby surface, 3=very soft)
    # --- temporal averaging (Option 3) -------------------------------------
    # Number of recent frames (including the current one) to average u_xy
    # and density over before painting the forward-splat path.  Default 1 =
    # no averaging = bit-identical to the prior renderer.  Larger values
    # smooth visual jitter from fast-moving cell deformation without
    # touching the solver.  Only the forward-splat path is averaged; the
    # legacy backward-sample / lighting path still paints the current
    # state.
    temporal_average_frames: int = 1


class PhysicsRenderer:
    """Render a :class:`PhysicsWorld` to a sequence of RGBA frames.

    The renderer is deliberately *separate* from the simulation: it reads
    cell state but never mutates it.  This lets the same renderer drive
    GIF emission, the visual-test harness, and (in future) a live view.
    """

    def __init__(
        self,
        config: RenderConfig | None = None,
        palette: Mapping[str, tuple[int, int, int]] | None = None,
    ) -> None:
        self.config = config or RenderConfig()
        self.palette = dict(DEFAULT_PALETTE)
        if palette:
            self.palette.update(palette)
        # Temporal-average history: list of per-frame snapshots, each a dict
        # mapping ``root_hull_id`` -> (ux_snapshot, uy_snapshot, density_snapshot).
        # Index 0 = oldest, index -1 = most recent.  Bounded by
        # ``config.temporal_average_frames``.  We snapshot at render-time so
        # bodies that disappear simply stop appearing in new snapshots; dead
        # entries naturally fall off the back as the deque advances.
        self._u_history: list[dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]] = []

    # --- core ---------------------------------------------------------------

    def render(self, world: PhysicsWorld) -> np.ndarray:
        """Return an (H, W, 4) uint8 RGBA frame for the current world state."""
        frame = self._background()
        # Snapshot current per-body u/density for the temporal average history,
        # then drop the oldest entries beyond the configured window.  We only
        # bother when averaging is actually enabled — keeps the default
        # (frames=1) path zero-overhead.
        if self.config.temporal_average_frames > 1:
            self._push_history(world)
        for body in world.iter_bodies():
            self._draw_body(frame, world, body)
        return frame

    def _push_history(self, world: PhysicsWorld) -> None:
        """Append a fresh snapshot of (ux, uy, density) per body to history,
        then trim to at most ``temporal_average_frames`` entries.

        Snapshots are keyed by ``id(body)`` — the Python object identity of
        the :class:`PhysicsBody` — rather than ``root_hull_id``.  Hull-id
        slots get recycled by the free-list when fragments die, so a new
        body can inherit a freshly-freed slot; keying on object identity
        prevents the new body from accidentally picking up the dead body's
        history.
        """
        snapshot: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for body in world.iter_bodies():
            cells = body.cells
            if cells is None:
                continue
            snapshot[id(body)] = (
                cells[..., _IDX_U_X].astype(np.float32).copy(),
                cells[..., _IDX_U_Y].astype(np.float32).copy(),
                cells[..., _IDX_DENSITY].astype(np.float32).copy(),
            )
        self._u_history.append(snapshot)
        # We store at most N-1 *past* snapshots; the current frame's live
        # cells supply the Nth value.  This keeps memory tight and matches
        # the spec: "averaging over the recent N snapshots".
        cap = max(1, self.config.temporal_average_frames - 1)
        while len(self._u_history) > cap:
            self._u_history.pop(0)

    def _averaged_state(
        self,
        body: PhysicsBody,
        ux_now: np.ndarray,
        uy_now: np.ndarray,
        d_now: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return temporally averaged (ux, uy, density) for ``body``.

        Falls back to ``(ux_now, uy_now, d_now)`` when:
          * temporal averaging is disabled (frames == 1)
          * there's no history yet (first frame)
          * this body has no entries in the history (newly spawned)
        Otherwise the mean of all history entries plus the current frame is
        returned.  Snapshots with mismatched shapes (e.g. cell grid
        re-allocated to a different size) are skipped defensively.
        """
        if self.config.temporal_average_frames <= 1 or not self._u_history:
            return ux_now, uy_now, d_now
        key = id(body)
        ux_acc = [ux_now]
        uy_acc = [uy_now]
        d_acc = [d_now]
        for snap in self._u_history:
            entry = snap.get(key)
            if entry is None:
                continue
            ux_p, uy_p, d_p = entry
            if ux_p.shape != ux_now.shape:
                continue
            ux_acc.append(ux_p)
            uy_acc.append(uy_p)
            d_acc.append(d_p)
        if len(ux_acc) == 1:
            # No prior history for this body (newly spawned).
            return ux_now, uy_now, d_now
        ux_mean = np.mean(np.stack(ux_acc, axis=0), axis=0)
        uy_mean = np.mean(np.stack(uy_acc, axis=0), axis=0)
        d_mean = np.mean(np.stack(d_acc, axis=0), axis=0)
        return ux_mean, uy_mean, d_mean

    def render_sequence(
        self,
        world: PhysicsWorld,
        frame_count: int,
        steps_per_frame: int = 1,
        step_dt: float | None = None,
    ) -> Iterable[np.ndarray]:
        """Yield ``frame_count`` frames, advancing the world ``steps_per_frame``
        times between each emitted frame.  Useful for GIFs/videos.
        """
        for _ in range(frame_count):
            for _ in range(steps_per_frame):
                world.step(step_dt)
            yield self.render(world)

    def save_gif(
        self,
        frames: list[np.ndarray],
        path: str | Path,
        fps: int = 30,
    ) -> Path:
        """Save a list of RGBA frames as a GIF.  Requires Pillow."""
        from PIL import Image
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        imgs = [Image.fromarray(f, mode="RGBA").convert("P", palette=Image.ADAPTIVE) for f in frames]
        imgs[0].save(
            path,
            save_all=True,
            append_images=imgs[1:],
            duration=int(1000 / fps),
            loop=0,
            optimize=True,
        )
        return path

    # --- internals ----------------------------------------------------------

    def _background(self) -> np.ndarray:
        h, w = self.config.height, self.config.width
        top = np.array(self.config.bg_top, dtype=np.float32)
        bot = np.array(self.config.bg_bottom, dtype=np.float32)
        t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        col = (top[None, :] * (1 - t) + bot[None, :] * t)[:, None, :]
        col = np.broadcast_to(col, (h, w, 3)).astype(np.uint8)
        frame = np.zeros((h, w, 4), dtype=np.uint8)
        frame[..., :3] = col
        frame[..., 3] = 255
        return frame

    def _world_to_screen(self, x: float, y: float) -> tuple[int, int]:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        sx = (x - wx0) / (wx1 - wx0) * cfg.width
        sy = (y - wy0) / (wy1 - wy0) * cfg.height
        return int(sx), int(sy)

    def _draw_body(self, frame: np.ndarray, world: PhysicsWorld, body: PhysicsBody) -> None:
        cells = body.cells
        if cells is None:
            return
        # Forward-splat path makes deformation actually visible by painting
        # each cell at world position (body.pos + cell_local + u * scale).
        # The body's silhouette bulges/squishes/spreads with the
        # displacement field.  Lighting/Lambert lives on the legacy path
        # for now, so when point lights are configured we fall back to
        # backward-sample so light direction still bites.
        if self.config.forward_splat and not self.config.lights:
            self._draw_body_forward_splat(frame, world, body)
            return
        hid = body.root_hull_id
        cs_x = float(world.hulls.cell_size_x[hid])
        cs_y = float(world.hulls.cell_size_y[hid])
        px = float(world.hulls.position[hid, 0])
        py = float(world.hulls.position[hid, 1])

        # Base colour from palette; fall back to medium grey.
        base = np.array(
            self.palette.get(body.material_name, (128, 128, 128)),
            dtype=np.float32,
        )

        # Pull channels we need from the cell field.
        d = cells[..., _IDX_DENSITY].astype(np.float32)
        damage = cells[..., _IDX_DAMAGE].astype(np.float32)
        tear = cells[..., _IDX_TEAR].astype(np.float32)
        heat = cells[..., _IDX_HEAT].astype(np.float32)
        ux = cells[..., _IDX_U_X].astype(np.float32)
        uy = cells[..., _IDX_U_Y].astype(np.float32)

        advect = _FLUID_ADVECT if body.material.is_fluid else _RIGID_ADVECT

        # For each screen pixel inside the body's AABB, compute the cell-
        # space sample location (with advection) and shade.
        cfg = self.config
        w_world = cs_x * CELL_GRID_SIZE
        h_world = cs_y * CELL_GRID_SIZE
        x0_world = px - w_world / 2.0
        y0_world = py - h_world / 2.0
        sx0, sy0 = self._world_to_screen(x0_world, y0_world)
        sx1, sy1 = self._world_to_screen(x0_world + w_world, y0_world + h_world)
        sx0 = max(0, min(cfg.width, sx0))
        sx1 = max(0, min(cfg.width, sx1))
        sy0 = max(0, min(cfg.height, sy0))
        sy1 = max(0, min(cfg.height, sy1))
        if sx1 <= sx0 or sy1 <= sy0:
            return

        # Build a grid of screen coords → cell sample coords (with advection).
        ys = np.arange(sy0, sy1, dtype=np.float32)
        xs = np.arange(sx0, sx1, dtype=np.float32)
        # Screen -> world.
        wx0, wy0, wx1, wy1 = cfg.world_view
        world_x = wx0 + xs / cfg.width * (wx1 - wx0)
        world_y = wy0 + ys / cfg.height * (wy1 - wy0)
        # World -> cell index (float).
        cx_f = (world_x - x0_world) / cs_x
        cy_f = (world_y - y0_world) / cs_y
        cx_grid, cy_grid = np.meshgrid(cx_f, cy_f)
        # Advect: shift the sample location *away* from the displacement
        # (backward sample, mass-conserving).
        cxi0 = np.clip(cx_grid.astype(np.int32), 0, CELL_GRID_SIZE - 1)
        cyi0 = np.clip(cy_grid.astype(np.int32), 0, CELL_GRID_SIZE - 1)
        u_here_x = ux[cyi0, cxi0]
        u_here_y = uy[cyi0, cxi0]
        cx_adv = cx_grid - u_here_x * advect / cs_x
        cy_adv = cy_grid - u_here_y * advect / cs_y
        cxi = np.clip(cx_adv.astype(np.int32), 0, CELL_GRID_SIZE - 1)
        cyi = np.clip(cy_adv.astype(np.int32), 0, CELL_GRID_SIZE - 1)

        d_s = d[cyi, cxi]
        damage_s = damage[cyi, cxi]
        tear_s = tear[cyi, cxi]
        heat_s = heat[cyi, cxi]

        # Inside-the-body mask: density above 5% AND silhouette not torn off.
        inside = d_s > 0.05

        # Base × (1 - damage_darken × damage) × (1 - 0.6 × tear cap)
        base_rgb = base[None, None, :] * (1.0 - cfg.damage_darken * damage_s[..., None])
        base_rgb = base_rgb * (1.0 - 0.6 * np.clip(tear_s[..., None], 0.0, 1.0))

        # --- point-light Lambert shading ----------------------------------
        # When no lights are configured we keep behaviour bit-identical to
        # the legacy uniform path.  With lights, the base is lit and we
        # then add emissive (glow/radiance) on top so lava still self-
        # emits even on the unlit side.
        if cfg.lights:
            lit_base = self._lambert_shade(
                base_rgb=base_rgb,
                ux=ux, uy=uy,
                d=d,
                cxi=cxi, cyi=cyi,
                cs_x=cs_x, cs_y=cs_y,
                world_x=world_x, world_y=world_y,
                lights=cfg.lights,
                ambient=cfg.ambient_intensity,
                curvature_bias=cfg.normal_curvature_bias if cfg.enable_normal_map else 0.0,
            )
            rgb = lit_base
        else:
            rgb = base_rgb

        # Blackbody-ish glow keyed off heat / melt_point — orange → white.
        melt = max(0.01, float(body.material.melt_point))
        t = np.clip(heat_s / melt, 0.0, 2.5)
        # Glow ramps in by t=0.3 and saturates by t=1.5.
        glow = np.clip((t - 0.3) / 1.2, 0.0, 1.0)
        glow_rgb = np.stack([
            255.0 * glow,
            150.0 * glow + 105.0 * np.clip(t - 1.0, 0.0, 1.0),
            60.0 * glow + 195.0 * np.clip(t - 1.5, 0.0, 1.0),
        ], axis=-1)
        rgb = rgb + glow_rgb * cfg.heat_emission_gain * 0.4

        # Lava-style radiance baseline (material self-emits).
        radiance = float(body.material.radiance)
        if radiance > 0.0:
            rgb = rgb + np.array(self.palette.get(body.material_name, (128, 64, 16)),
                                  dtype=np.float32)[None, None, :] * (radiance * 0.05)

        # Optional contact-flash overlay (small bright spike where heat just
        # spiked but the body hasn't cooled yet).
        if cfg.contact_flash:
            flash = np.clip((heat_s - melt * 0.5) / melt, 0.0, 1.0)[..., None]
            rgb = rgb + flash * np.array([255.0, 240.0, 200.0], dtype=np.float32)[None, None, :] * 0.5

        # Defensive cast: even with the kernel-side guard rails the cell field
        # can occasionally carry NaN/inf (e.g. a body whose cells were
        # externally mutated by a tool/test).  ``nan_to_num`` lets the clip+
        # uint8 cast remain warning-free without changing legitimate pixels.
        rgb = np.nan_to_num(rgb, nan=0.0, posinf=255.0, neginf=0.0)
        rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8)

        # Write to frame where inside.
        target_slice = frame[sy0:sy1, sx0:sx1]
        target_slice[inside, :3] = rgb[inside]
        # Alpha left at 255 (we composite onto the background only when inside).

    # --- forward-splat path ------------------------------------------------

    def _draw_body_forward_splat(
        self,
        frame: np.ndarray,
        world: PhysicsWorld,
        body: PhysicsBody,
    ) -> None:
        """Paint each cell at ``body.pos + cell_local + u * splat_scale``.

        Unlike the backward-sample path (which keeps the silhouette fixed
        and only shifts colour inside it), this lets the displacement
        field actually warp the body's outline — splat, squish, splash.
        """
        cfg = self.config
        cells = body.cells
        if cells is None:
            return
        hid = body.root_hull_id
        cs_x = float(world.hulls.cell_size_x[hid])
        cs_y = float(world.hulls.cell_size_y[hid])
        px = float(world.hulls.position[hid, 0])
        py = float(world.hulls.position[hid, 1])

        # Pull channels.
        d = cells[..., _IDX_DENSITY].astype(np.float32)
        damage = cells[..., _IDX_DAMAGE].astype(np.float32)
        tear = cells[..., _IDX_TEAR].astype(np.float32)
        heat = cells[..., _IDX_HEAT].astype(np.float32)
        ux = cells[..., _IDX_U_X].astype(np.float32)
        uy = cells[..., _IDX_U_Y].astype(np.float32)

        # Temporal averaging (Option 3): replace ux/uy/density with their
        # mean over the recent history window for this body.  ``damage``,
        # ``tear``, and ``heat`` are left alone — they shift slowly compared
        # to the displacement field and don't drive the visible jitter that
        # this feature targets.  The averaged density is what controls the
        # "inside" mask, so a body that's settling smoothly still resolves
        # its silhouette correctly.
        ux, uy, d = self._averaged_state(body, ux, uy, d)

        splat_scale = cfg.splat_scale_fluid if body.material.is_fluid else cfg.splat_scale

        # Cell-local coords (centred around 0): each cell at (cx - 15.5) * cs_x
        # in body-local x.  Then add u (the per-cell displacement, in world
        # units) scaled by splat_scale to make it visible.
        cy_idx, cx_idx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
        local_x = (cx_idx - (CELL_GRID_SIZE - 1) * 0.5) * cs_x + ux * splat_scale
        local_y = (cy_idx - (CELL_GRID_SIZE - 1) * 0.5) * cs_y + uy * splat_scale
        world_cx = local_x + px
        world_cy = local_y + py

        # Inside-the-body mask.
        inside = d > 0.05

        # Base colour per cell.
        base = np.array(
            self.palette.get(body.material_name, (128, 128, 128)),
            dtype=np.float32,
        )
        base_rgb = np.broadcast_to(base, (CELL_GRID_SIZE, CELL_GRID_SIZE, 3)).copy()
        # Damage darken.
        base_rgb *= (1.0 - cfg.damage_darken * damage[..., None])
        # Tear darken.
        base_rgb *= (1.0 - 0.6 * np.clip(tear, 0.0, 1.0)[..., None])

        # Heat glow.
        melt = max(0.01, float(body.material.melt_point))
        t = np.clip(heat / melt, 0.0, 2.5)
        glow = np.clip((t - 0.3) / 1.2, 0.0, 1.0)
        glow_rgb = np.stack([
            255.0 * glow,
            150.0 * glow + 105.0 * np.clip(t - 1.0, 0.0, 1.0),
            60.0 * glow + 195.0 * np.clip(t - 1.5, 0.0, 1.0),
        ], axis=-1)
        rgb = base_rgb + glow_rgb * cfg.heat_emission_gain * 0.4

        # Lava-style radiance baseline.
        radiance = float(body.material.radiance)
        if radiance > 0.0:
            rgb += base[None, None, :] * (radiance * 0.05)

        # Contact flash on hot cells.
        if cfg.contact_flash:
            flash = np.clip((heat - melt * 0.5) / melt, 0.0, 1.0)[..., None]
            rgb += flash * np.array([255.0, 240.0, 200.0], dtype=np.float32)[None, None, :] * 0.5

        # --- Fluid surface shading: foam at high-divergence regions + ripple
        # highlights modulated by |u_y|.  Gated on (is_fluid AND amplitude>0)
        # so non-fluids — and fluids that haven't opted in — pay zero cost.
        foam_amp = float(getattr(body.material, "foam_amplitude", 0.0) or 0.0)
        ripple_amp = float(getattr(body.material, "ripple_amplitude", 0.0) or 0.0)
        if body.material.is_fluid and (foam_amp > 0.0 or ripple_amp > 0.0):
            rgb = self._apply_fluid_surface(
                rgb=rgb,
                ux=ux,
                uy=uy,
                inside=inside,
                foam_amp=foam_amp,
                ripple_amp=ripple_amp,
                cs_x=cs_x,
                cs_y=cs_y,
            )

        # --- Option 5: opt-in per-material noise overlay --------------------
        # Default amplitude is 0.0, in which case this branch is skipped
        # entirely (no cost for materials that don't want noise).  Otherwise
        # the noise is keyed on the cell's WORLD position (so the texture
        # tracks the body as it moves) and the current frame index (so the
        # surface flickers/sparkles).
        amp = float(getattr(body.material, "noise_overlay_amplitude", 0.0) or 0.0)
        if amp > 0.0:
            # Sanitise the noise indices before the int32 cast.  Although
            # the kernel now clamps cell ``u``/``v`` to safe magnitudes, the
            # forward-splat math here multiplies by ``splat_scale`` and adds
            # ``px``, so an extreme outlier could still land outside int32
            # range.  ``nan_to_num`` + clip-by-cast keeps the hash inputs
            # well-defined without changing the visible noise pattern in
            # normal-range cases.
            nx_src = np.nan_to_num(world_cx * _NOISE_OVERSAMPLE, nan=0.0, posinf=2.1e9, neginf=-2.1e9)
            ny_src = np.nan_to_num(world_cy * _NOISE_OVERSAMPLE, nan=0.0, posinf=2.1e9, neginf=-2.1e9)
            nx_int = np.clip(nx_src, -2.1e9, 2.1e9).astype(np.int32)
            ny_int = np.clip(ny_src, -2.1e9, 2.1e9).astype(np.int32)
            frame_idx = int(getattr(world, "frame", 0)) & 0xFF
            noise = _value_noise(nx_int, ny_int, frame_idx)
            tint = np.asarray(
                getattr(body.material, "noise_overlay_color", (255, 255, 255)),
                dtype=np.float32,
            )
            # Two-part modulation:
            #   (1) Scalar brightness gain `(1 + amp * noise)` — exactly the
            #       form prescribed by docs/adaptive_simulation_strategies.md
            #       Option 5.  Produces grainy luma variance without shifting
            #       hue.
            #   (2) Additive tinted highlight `amp * noise * tint` — biases
            #       bright grains toward the material's chosen tint colour
            #       (e.g. yellow grit on sand, orange flicker on lava).
            #       Defaults to white tint, which simply reinforces (1).
            gain = 1.0 + amp * noise
            rgb = rgb * gain[..., None]
            rgb = rgb + amp * noise[..., None] * (tint[None, None, :] * 0.5)

        # Defensive cast: ``nan_to_num`` handles any NaN/inf that leaked past
        # the kernel's clamps (or were injected by tests).  ``np.clip`` then
        # gates the float→uint8 narrowing to the 0..255 range so the cast
        # never sees an out-of-range value (which is what triggered the
        # ``RuntimeWarning: invalid value encountered in cast`` reported in
        # the showcase run).  The noise-overlay branch is also guarded
        # because ``amp * noise`` can be negative; if ``rgb`` was zero in some
        # cells the additive term could otherwise yield negative components.
        rgb = np.nan_to_num(rgb, nan=0.0, posinf=255.0, neginf=0.0)
        rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8)

        # World → screen.
        wx0, wy0, wx1, wy1 = cfg.world_view
        sx = (world_cx - wx0) / (wx1 - wx0) * cfg.width
        sy = (world_cy - wy0) / (wy1 - wy0) * cfg.height
        # Defensive int32 cast: ``world_cx``/``world_cy`` carry whatever the
        # kernel produced for ``u``, and a NaN/inf there would propagate
        # straight into this projection (``NaN - wx0`` is NaN).
        # ``nan_to_num`` + finite clip stops the cast from raising
        # ``RuntimeWarning: invalid value encountered in cast``.
        sx = np.nan_to_num(sx, nan=0.0, posinf=float(cfg.width), neginf=0.0)
        sy = np.nan_to_num(sy, nan=0.0, posinf=float(cfg.height), neginf=0.0)
        sxi = np.clip(sx, -2.1e9, 2.1e9).astype(np.int32)
        syi = np.clip(sy, -2.1e9, 2.1e9).astype(np.int32)

        # Paint each cell as a QUAD spanning from itself to its east+south
        # neighbours.  Treating the 32×32 grid as a deformable mesh
        # eliminates the gaps that point-splats leave when adjacent cells
        # displace differently.  Quad-fill = no background bleed-through.
        h, w = cfg.height, cfg.width

        cyi_list, cxi_list = np.nonzero(inside)
        for k in range(cyi_list.size):
            cy = int(cyi_list[k]); cx = int(cxi_list[k])
            # Build a quad: (cy,cx) → (cy,cx+1) → (cy+1,cx+1) → (cy+1,cx).
            # Falls back to the cell's own corner where a neighbour is
            # outside the grid or below the density threshold.
            corners_x = [sxi[cy, cx]]
            corners_y = [syi[cy, cx]]
            for ny, nx in ((cy, min(cx + 1, CELL_GRID_SIZE - 1)),
                           (min(cy + 1, CELL_GRID_SIZE - 1), min(cx + 1, CELL_GRID_SIZE - 1)),
                           (min(cy + 1, CELL_GRID_SIZE - 1), cx)):
                if inside[ny, nx]:
                    corners_x.append(int(sxi[ny, nx]))
                    corners_y.append(int(syi[ny, nx]))
                else:
                    corners_x.append(int(sxi[cy, cx]))
                    corners_y.append(int(syi[cy, cx]))
            x0 = max(0, min(corners_x))
            x1 = min(w, max(corners_x) + 1)
            y0 = max(0, min(corners_y))
            y1 = min(h, max(corners_y) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            # Cheap fill: paint the bounding-box of the quad with the cell's
            # colour.  At splat_scale~5 with 32-cell grids the BB ≈ quad,
            # so the small overdraw is acceptable and gives us a continuous
            # surface.  A proper rasterised quad-fill would be tighter but
            # would need a per-pixel polygon test.
            frame[y0:y1, x0:x1, :3] = rgb[cy, cx]
            frame[y0:y1, x0:x1, 3] = 255

    # --- fluid surface shading --------------------------------------------

    def _apply_fluid_surface(
        self,
        *,
        rgb: np.ndarray,         # (CELL_GRID_SIZE, CELL_GRID_SIZE, 3) float32
        ux: np.ndarray,          # (CELL_GRID_SIZE, CELL_GRID_SIZE) float32
        uy: np.ndarray,          # (CELL_GRID_SIZE, CELL_GRID_SIZE) float32
        inside: np.ndarray,      # (CELL_GRID_SIZE, CELL_GRID_SIZE) bool
        foam_amp: float,
        ripple_amp: float,
        cs_x: float,
        cs_y: float,
    ) -> np.ndarray:
        """Layer foam (high-divergence whitening) and ripple highlights on top.

        The two effects are additive — foam blends toward white in turbulent
        zones (wave crests, splash sites) and ripple adds a sinusoidal
        sparkle modulated by ``|u_y|`` to suggest specular reflection.
        Both terms are gated by the body's ``inside`` mask so the
        background never gets foam'd.
        """
        out = rgb
        white = np.array([255.0, 255.0, 255.0], dtype=np.float32)

        # --- Foam: blend toward white where |div(u)| is high --------------
        if foam_amp > 0.0:
            # Central-difference divergence on the cell-grid.  Using
            # np.roll keeps the arithmetic shape-stable at the edges; the
            # wrap-around there is benign because edge cells with
            # density~0 are masked out by ``inside`` anyway.
            #   div_u = d(u_x)/dx + d(u_y)/dy
            # We work in *cell* units (Δx=Δy=1 cell) so the divergence
            # scale matches the magnitude of u in world units directly.
            ux_left = np.roll(ux, 1, axis=1)
            ux_right = np.roll(ux, -1, axis=1)
            uy_up = np.roll(uy, 1, axis=0)
            uy_down = np.roll(uy, -1, axis=0)
            div_u = 0.5 * ((ux_right - ux_left) + (uy_down - uy_up))
            # ``tanh`` saturates so even extreme divergence can't push
            # past full white.  ``foam_scale`` controls how quickly we
            # saturate; tuned so a div_u of ~0.3 world-units (a typical
            # wave-crest signal) reads as visible foam.
            foam_scale = 3.0
            foam_strength = foam_amp * np.tanh(np.abs(div_u) * foam_scale)
            foam_strength = np.clip(foam_strength, 0.0, 1.0)
            # Mask to body interior — no foam on background pixels.
            foam_strength = foam_strength * inside.astype(np.float32)
            blend = foam_strength[..., None]
            out = out * (1.0 - blend) + white[None, None, :] * blend

        # --- Ripple: sinusoidal highlight on |u_y| ------------------------
        if ripple_amp > 0.0:
            # The spec form: ripple = amp * sin(u_y * 4) * tanh(|u_y|).
            # Multiplying by tanh(|u_y|) ensures still water (u_y≈0) shows
            # no sparkle while moving wavefronts do.  The sin term wobbles
            # bright/dark so the surface reads as oscillating specular
            # highlight rather than a flat colour shift.
            ripple = ripple_amp * np.sin(uy * 4.0) * np.tanh(np.abs(uy))
            ripple = ripple * inside.astype(np.float32)
            # Scale to RGB.  255 is overkill — we let np.clip cap it at
            # the end of the pipeline.  Using ~120 here gives a visible
            # but not blown-out sparkle on top of the base colour.
            out = out + ripple[..., None] * (white[None, None, :] * 0.5)

        return out

    # --- lighting helpers --------------------------------------------------

    def _lambert_shade(
        self,
        *,
        base_rgb: np.ndarray,       # (H, W, 3) float32 — base palette × damage × tear
        ux: np.ndarray,             # (CELL_GRID_SIZE, CELL_GRID_SIZE) — body displacement X
        uy: np.ndarray,             # (CELL_GRID_SIZE, CELL_GRID_SIZE) — body displacement Y
        d: np.ndarray,              # (CELL_GRID_SIZE, CELL_GRID_SIZE) — body density (for body-curvature)
        cxi: np.ndarray,            # (H, W) int32 — cell-space sample x per screen pixel
        cyi: np.ndarray,            # (H, W) int32 — cell-space sample y per screen pixel
        cs_x: float,
        cs_y: float,
        world_x: np.ndarray,        # (W,) float32 — world X per screen column
        world_y: np.ndarray,        # (H,) float32 — world Y per screen row
        lights: list[PointLight],
        ambient: float,
        curvature_bias: float,
    ) -> np.ndarray:
        """Vectorised Lambert shading with normals from the u-field gradient
        plus an implicit body-curvature term driven by the density gradient.

        Returns base_rgb modulated by ``ambient + Σ (n·l) * attenuation *
        light_colour`` so each screen pixel inside the body gets a per-cell
        shaded colour.  Operates entirely on the strip already sampled in
        ``_draw_body``.

        Why density-gradient drives the "implicit body curvature": at rest
        the displacement field u is zero everywhere, so its gradient gives
        no shading information.  The density field, by contrast, is high
        in a body's interior and falls to zero just outside the silhouette;
        its gradient points outward at the boundary, so cells at the right
        edge of a circle get a normal tilted in +X, etc.  That's exactly
        the "sphere-like" curvature the spec is after.  u-gradient is
        layered on top so dynamic deformations also re-shade.
        """
        bias = float(curvature_bias)

        # u-field gradient (deformation-driven shading).  np.gradient
        # returns [d/dy, d/dx] for a 2D array.
        _, du_dx_x = np.gradient(ux)
        du_dy_y, _ = np.gradient(uy)
        du_dx_x = du_dx_x / max(cs_x, 1e-6)
        du_dy_y = du_dy_y / max(cs_y, 1e-6)

        # Density gradient (body-curvature shading).  At the silhouette
        # edge dd/dx points outward, so cells at the right edge have a
        # normal tilted in +X — the natural "sphere bulge."
        dd_dy, dd_dx = np.gradient(d)
        # Scale so a density change from 1→0 across one cell width
        # produces a noticeable tilt.  We deliberately keep this in
        # "per cell" units (not per world-distance) so the curvature
        # amount is invariant to cell_size choice.
        # The negative sign aligns the normal with the outward direction.

        # Sample both gradients at each screen pixel's cell.
        gx_u = du_dx_x[cyi, cxi]
        gy_u = du_dy_y[cyi, cxi]
        gx_d = dd_dx[cyi, cxi]
        gy_d = dd_dy[cyi, cxi]

        # Normal: -u_grad (deformation) + -d_grad (body curvature), Z=1.
        # The density gradient term is the dominant source of "bulge" for
        # an undeformed body.
        nx = (-gx_u - gx_d) * bias
        ny = (-gy_u - gy_d) * bias
        nz = np.ones_like(nx)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-8
        nx = nx / nlen
        ny = ny / nlen
        nz = nz / nlen

        # Build world-space pixel positions on the Z=0 plane.
        wx_grid = np.broadcast_to(world_x[None, :], nx.shape)
        wy_grid = np.broadcast_to(world_y[:, None], nx.shape)

        # Accumulate lit contribution from each point light.
        total_light = np.zeros((nx.shape[0], nx.shape[1], 3), dtype=np.float32)
        for L in lights:
            lx, ly = float(L.position[0]), float(L.position[1])
            lcol = np.asarray(L.color, dtype=np.float32) / 255.0
            radius = max(float(L.radius), 1e-3)
            inten = float(L.intensity)

            to_x = lx - wx_grid
            to_y = ly - wy_grid
            to_z = np.zeros_like(to_x)  # light & cell both on z=0
            # The "into-screen" Z=0 light direction gives n·l = nz (the
            # bulge term) at distance, which is exactly what we want for
            # a flat 2D Lambert: cells whose normal points toward the
            # light are bright.
            dist = np.sqrt(to_x * to_x + to_y * to_y + to_z * to_z) + 1e-6
            ldir_x = to_x / dist
            ldir_y = to_y / dist
            ldir_z = to_z / dist

            ndotl = nx * ldir_x + ny * ldir_y + nz * ldir_z
            ndotl = np.clip(ndotl, 0.0, 1.0)
            atten = inten / (1.0 + (dist / radius) ** 2)
            contrib = (ndotl * atten)[..., None] * lcol[None, None, :]
            total_light += contrib

        # Final: ambient term × base, plus per-light additive Lambert.
        # The light-colour multiply uses base_rgb directly so coloured
        # lights tint the material — a red light on grey steel reads red.
        lit = base_rgb * ambient + base_rgb * total_light
        return lit


def render_world_gif(
    world: PhysicsWorld,
    out_path: str | Path,
    *,
    frame_count: int = 90,
    fps: int = 30,
    steps_per_frame: int = 2,
    config: RenderConfig | None = None,
) -> Path:
    """Convenience: render a GIF of the world advancing for ``frame_count`` frames.

    Returns the written path.  Used by the visual test suite to produce
    per-scenario artefacts that *actually look different* per material.
    """
    r = PhysicsRenderer(config=config)
    frames = list(r.render_sequence(world, frame_count, steps_per_frame=steps_per_frame))
    return r.save_gif(frames, out_path, fps=fps)
