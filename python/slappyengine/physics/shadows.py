"""Soft shadow + ambient-occlusion passes for the PhysicsRenderer.

This module supplies two screen-space post-effects that consume a frame
already rendered by :class:`slappyengine.physics.render.PhysicsRenderer`
and the :class:`slappyengine.physics.world.PhysicsWorld` that produced it.

ShadowPass:
    Projects each body's cell silhouette along a directional light vector
    in world space, accumulates per-pixel shadow density on a (H, W) map,
    Gaussian-softens it, and darkens the input frame's RGB channels by
    ``opacity * shadow_density``.

AOPass:
    Darkens regions near "cracked" cells (cells whose neighbour bonds
    have dropped below an intactness threshold).  This makes fracture
    lines and torn edges visually pop without requiring a full SSAO.

Both passes are pure-CPU numpy and follow the ``render(frame, world)``
post-process convention, so they may be added to a
:class:`PostProcessChain` or invoked standalone.

Limitations
-----------
* A single directional light: no point lights, no per-pixel light cookie.
* Shadows fall on the *background* only; bodies receive no self-shadow
  or shadow-on-body (no depth buffer, no per-body Z-sort).
* The projection is screen-space — extremely oblique light vectors will
  alias along the projection ray; raise ``shadow_samples`` to soften.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from slappyengine.physics.cell import CELL_GRID_SIZE
from slappyengine.physics.world import PhysicsWorld


# Default screen <-> world mapping; matches ``RenderConfig`` defaults so
# the passes "just work" against an unmodified ``PhysicsRenderer``.
_DEFAULT_WORLD_VIEW: tuple[float, float, float, float] = (-200.0, -100.0, 200.0, 250.0)

# Cell channels we sample (must match ``CELL_PIXEL_STRUCT`` in cell.py).
_IDX_DENSITY = 9
_IDX_BOND_N = 13
_IDX_BOND_E = 14
_IDX_BOND_S = 15

# Occluder threshold for shadow casting (density above this counts as solid).
_OCCLUDER_DENSITY_THRESHOLD = 0.5

# Bond intactness threshold for AO (any bond below this == "cracked").
_AO_CRACKED_BOND_THRESHOLD = 0.2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _world_to_screen_arrays(
    wx: np.ndarray,
    wy: np.ndarray,
    world_view: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised world-to-screen mapping mirroring PhysicsRenderer."""
    wx0, wy0, wx1, wy1 = world_view
    sx = (wx - wx0) / (wx1 - wx0) * width
    sy = (wy - wy0) / (wy1 - wy0) * height
    return sx, sy


def _gaussian_blur(buf: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur of a 2D float buffer.

    Avoids a SciPy dependency.  Uses a fixed kernel radius of
    ``ceil(3 * sigma)``; for ``sigma <= 0`` returns ``buf`` unchanged.
    """
    if sigma <= 0.0:
        return buf
    radius = max(1, int(np.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    kernel /= float(kernel.sum())

    h, w = buf.shape
    # Horizontal pass with edge replication via clamping.
    padded = np.pad(buf, ((0, 0), (radius, radius)), mode="edge")
    tmp = np.zeros_like(buf)
    for i, k in enumerate(kernel):
        tmp += k * padded[:, i : i + w]

    padded = np.pad(tmp, ((radius, radius), (0, 0)), mode="edge")
    out = np.zeros_like(buf)
    for i, k in enumerate(kernel):
        out += k * padded[i : i + h, :]
    return out


def _body_cell_world_centers(
    world: PhysicsWorld,
    hid: int,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return world-space (xx, yy) centres for a body's 32x32 cell grid.

    Also returns ``(cell_size_x, cell_size_y)`` so callers can size the
    "shadow stamp" they paint per cell.
    """
    cs_x = float(world.hulls.cell_size_x[hid])
    cs_y = float(world.hulls.cell_size_y[hid])
    px = float(world.hulls.position[hid, 0])
    py = float(world.hulls.position[hid, 1])
    w_world = cs_x * CELL_GRID_SIZE
    h_world = cs_y * CELL_GRID_SIZE
    x0 = px - w_world / 2.0
    y0 = py - h_world / 2.0
    yy_idx, xx_idx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
    cx_world = x0 + (xx_idx + 0.5) * cs_x
    cy_world = y0 + (yy_idx + 0.5) * cs_y
    return cx_world, cy_world, cs_x, cs_y


# ---------------------------------------------------------------------------
# ShadowLight (multi-light support)
# ---------------------------------------------------------------------------


@dataclass
class ShadowLight:
    """One additional light source for :class:`ShadowPass`.

    Attributes
    ----------
    direction:
        2D world-space vector pointing *from* the light *toward* the
        scene (i.e. the direction shadows extend).  Normalised internally.
    length:
        Maximum length of the cast shadow in world units.
    opacity:
        Peak darkening fraction at full density.
    softness:
        Gaussian sigma (in screen pixels) applied to this light's shadow
        density before compositing.
    color:
        RGB tuple in 0..255 that the shadow region is *lerped toward* at
        full density.  ``(0, 0, 0)`` = pure black shadow, ``(80, 0, 0)``
        = a moody red-tinted shadow that *adds* red bias while still
        reducing overall luminance.
    shadow_samples:
        Per-light sample count along the light ray.  More samples =
        smoother falloff at higher cost.  Defaults to 8 to match
        ``ShadowPass.shadow_samples``.
    """

    direction: tuple[float, float] = (0.3, 1.0)
    length: float = 80.0
    opacity: float = 0.55
    softness: float = 4.0
    color: tuple[int, int, int] = (0, 0, 0)
    shadow_samples: int = 8


# ---------------------------------------------------------------------------
# ShadowPass
# ---------------------------------------------------------------------------


@dataclass
class ShadowPass:
    """Directional soft shadow projected from each body's silhouette.

    Attributes
    ----------
    light_direction:
        2D world-space vector pointing *from* the light *toward* the
        scene (i.e. the direction shadows extend).  Need not be unit-
        length; it is normalised internally.
    shadow_length:
        Maximum length of the cast shadow in world units.  Pixels beyond
        this distance from any occluder receive no contribution.
    opacity:
        Peak darkening applied where the shadow density saturates to 1.
        ``opacity=0`` is a no-op and leaves the frame unchanged.
    softness_px:
        Gaussian blur sigma (in screen pixels) applied to the raw shadow
        density before compositing.  Higher = softer edge.
    shadow_samples:
        Number of cast samples per occluder cell along the light ray.
        More samples = smoother falloff; ``8`` is a good default.
    world_view:
        Screen-space world rectangle; must match the renderer's
        ``RenderConfig.world_view`` for shadows to line up correctly.
    """

    light_direction: tuple[float, float] = (0.3, 1.0)
    shadow_length: float = 80.0
    opacity: float = 0.55
    softness_px: float = 4.0
    shadow_samples: int = 8
    world_view: tuple[float, float, float, float] = _DEFAULT_WORLD_VIEW
    # NEW (backwards-compatible) — additional lights with per-light
    # direction / length / opacity / softness / color.
    additional_lights: list = field(default_factory=list)
    # NEW — if True, the primary (legacy) light is skipped entirely and only
    # ``additional_lights`` are rendered.  Used by ``MultiLightShadowPass``
    # so callers can render *just* a list of ``ShadowLight``s (including the
    # empty-list no-op case) without inheriting the legacy defaults.
    _skip_primary: bool = False

    def render(self, frame: np.ndarray, world: PhysicsWorld) -> np.ndarray:
        """Darken ``frame`` (an (H, W, 4) uint8 array) by projected shadows.

        Returns a new (H, W, 4) uint8 array; ``frame`` is not mutated.
        """
        if frame.ndim != 3 or frame.shape[2] != 4:
            raise ValueError(f"frame must be (H, W, 4); got {frame.shape}")

        # Collect all lights to render this frame: primary (if enabled and
        # non-zero opacity) plus any additional lights.
        lights: list[ShadowLight] = []
        if (not self._skip_primary) and self.opacity > 0.0:
            lights.append(
                ShadowLight(
                    direction=self.light_direction,
                    length=self.shadow_length,
                    opacity=self.opacity,
                    softness=self.softness_px,
                    color=(0, 0, 0),
                    shadow_samples=self.shadow_samples,
                ),
            )
        for light in self.additional_lights:
            if light.opacity > 0.0:
                lights.append(light)

        # No active lights → return an exact copy of the input.
        if not lights:
            return frame.copy()

        h, w = frame.shape[:2]

        # Cache projected occluder geometry by (direction, length, samples)
        # so multiple lights sharing a direction reuse the projection work
        # and only re-blur per softness/color.
        geom_cache: dict[
            tuple[float, float, float, int], np.ndarray
        ] = {}

        rgb = frame[..., :3].astype(np.float32)

        for light in lights:
            lx, ly, ok = self._normalise_dir(light.direction)
            if not ok:
                continue
            key = (
                round(lx, 6),
                round(ly, 6),
                float(light.length),
                int(max(1, light.shadow_samples)),
            )
            raw = geom_cache.get(key)
            if raw is None:
                raw = self._build_density_map(
                    world, h, w,
                    direction_normalised=(lx, ly),
                    shadow_length=float(light.length),
                    n_samples=int(max(1, light.shadow_samples)),
                )
                geom_cache[key] = raw
            if raw.max() <= 0.0:
                continue

            density = _gaussian_blur(raw, float(light.softness))
            density = np.clip(density, 0.0, 1.0)

            # Compose this light onto the working rgb buffer:
            #   out_c = rgb_c * (1 - opacity * density)
            #         + (opacity * density) * color_c
            # That is: lerp(rgb_c, color_c, opacity * density).
            # For color=(0,0,0) this reduces to the legacy
            # ``rgb *= (1 - opacity * density)``.
            mix = float(light.opacity) * density  # (H, W)
            inv_mix = 1.0 - mix
            color_arr = np.asarray(light.color, dtype=np.float32)
            # Broadcast: rgb (H,W,3), mix (H,W,1), color_arr (3,)
            rgb = rgb * inv_mix[..., None] + mix[..., None] * color_arr

        out = np.empty_like(frame)
        out[..., :3] = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
        out[..., 3] = frame[..., 3]
        return out

    # ----- internals -------------------------------------------------------

    @staticmethod
    def _normalise_dir(
        direction: tuple[float, float],
    ) -> tuple[float, float, bool]:
        """Return (lx, ly, ok). ``ok`` is False for zero-length vectors."""
        lx, ly = float(direction[0]), float(direction[1])
        n = float(np.hypot(lx, ly))
        if n < 1e-6:
            return 0.0, 0.0, False
        return lx / n, ly / n, True

    def _build_density_map(
        self,
        world: PhysicsWorld,
        height: int,
        width: int,
        *,
        direction_normalised: tuple[float, float] | None = None,
        shadow_length: float | None = None,
        n_samples: int | None = None,
    ) -> np.ndarray:
        """Accumulate occluder contributions into a (H, W) float32 buffer."""
        density = np.zeros((height, width), dtype=np.float32)

        # Defaults mirror the dataclass fields so legacy callers (none in
        # the codebase but possible externally) still work.
        if direction_normalised is None:
            lx, ly, ok = self._normalise_dir(self.light_direction)
            if not ok:
                return density
        else:
            lx, ly = direction_normalised

        if shadow_length is None:
            shadow_length = float(self.shadow_length)
        if n_samples is None:
            n_samples = max(1, int(self.shadow_samples))

        step = float(shadow_length) / n_samples
        if step <= 0.0:
            return density

        # Per-sample weight: linear falloff with distance (closer = darker).
        # Sum of weights == 1 across n_samples so a fully covered pixel
        # reaches density ~1 from a single occluder ray.
        sample_weights = np.linspace(1.0, 0.2, n_samples, dtype=np.float32)
        sample_weights /= float(sample_weights.sum())

        for body in world.iter_bodies():
            cells = body.cells
            if cells is None:
                continue
            d = cells[..., _IDX_DENSITY]
            occ_mask = d > _OCCLUDER_DENSITY_THRESHOLD
            if not occ_mask.any():
                continue
            cx_world, cy_world, cs_x, cs_y = _body_cell_world_centers(
                world, body.root_hull_id,
            )
            occ_x = cx_world[occ_mask]
            occ_y = cy_world[occ_mask]

            # Project along the light ray for ``n_samples`` steps.
            for s in range(n_samples):
                t = (s + 1) * step  # start one step out from the cell
                wx = occ_x + lx * t
                wy = occ_y + ly * t
                sx, sy = _world_to_screen_arrays(
                    wx, wy, self.world_view, width, height,
                )
                # Stamp each projected sample as a small box equal in size
                # to one cell in screen pixels, so big bodies cast wide
                # shadows even when shadow_samples is low.
                self._stamp(
                    density,
                    sx, sy,
                    cs_x, cs_y,
                    sample_weights[s],
                )
        return density

    def _stamp(
        self,
        density: np.ndarray,
        sx: np.ndarray,
        sy: np.ndarray,
        cs_x: float,
        cs_y: float,
        weight: float,
    ) -> None:
        """Add ``weight`` to ``density`` at the integer pixels nearest
        each (sx, sy), splatted across a cell-sized footprint.

        We compute the footprint in *screen* pixels by scaling cs_x/cs_y
        through the world-view; the screen-space mapping is uniform, so
        a single multiplier per axis suffices.
        """
        h, w = density.shape
        wx0, wy0, wx1, wy1 = self.world_view
        px_per_wx = w / (wx1 - wx0)
        px_per_wy = h / (wy1 - wy0)
        foot_w = max(1, int(round(cs_x * px_per_wx)))
        foot_h = max(1, int(round(cs_y * px_per_wy)))

        sxi = np.rint(sx).astype(np.int32)
        syi = np.rint(sy).astype(np.int32)

        # Convert (sxi, syi) to footprint top-left.
        x0 = sxi - foot_w // 2
        y0 = syi - foot_h // 2

        for dy in range(foot_h):
            yy = y0 + dy
            for dx in range(foot_w):
                xx = x0 + dx
                in_bounds = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
                if not in_bounds.any():
                    continue
                # Use np.add.at for scatter-add safety on duplicate coords.
                xs = xx[in_bounds]
                ys = yy[in_bounds]
                np.add.at(density, (ys, xs), weight)


# ---------------------------------------------------------------------------
# AOPass
# ---------------------------------------------------------------------------


@dataclass
class AOPass:
    """Cheap screen-space AO that darkens regions near torn/cracked bonds.

    Attributes
    ----------
    radius_px:
        Gaussian sigma (in screen pixels) controlling how far AO bleeds
        away from each cracked cell.  Larger = wider halo.
    intensity:
        Peak darkening fraction at the centre of an AO blob.
    world_view:
        Screen-space world rectangle; must match the renderer's
        ``RenderConfig.world_view`` for AO to land in the right place.
    """

    radius_px: float = 8.0
    intensity: float = 0.4
    world_view: tuple[float, float, float, float] = _DEFAULT_WORLD_VIEW

    def render(self, frame: np.ndarray, world: PhysicsWorld) -> np.ndarray:
        """Return a copy of ``frame`` with AO applied around cracked cells."""
        if frame.ndim != 3 or frame.shape[2] != 4:
            raise ValueError(f"frame must be (H, W, 4); got {frame.shape}")

        if self.intensity <= 0.0:
            return frame.copy()

        h, w = frame.shape[:2]
        crack_map = self._build_crack_map(world, h, w)
        if crack_map.max() <= 0.0:
            return frame.copy()

        # Gaussian-spread the impulses, then normalise so the peak is 1.
        spread = _gaussian_blur(crack_map, self.radius_px)
        peak = float(spread.max())
        if peak > 0.0:
            spread = spread / peak
        spread = np.clip(spread, 0.0, 1.0)

        rgb = frame[..., :3].astype(np.float32)
        attenuation = 1.0 - self.intensity * spread
        rgb *= attenuation[..., None]
        out = np.empty_like(frame)
        out[..., :3] = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
        out[..., 3] = frame[..., 3]
        return out

    # ----- internals -------------------------------------------------------

    def _build_crack_map(
        self, world: PhysicsWorld, height: int, width: int,
    ) -> np.ndarray:
        """Mark cells whose neighbour bonds dropped below the intact line."""
        crack_map = np.zeros((height, width), dtype=np.float32)
        for body in world.iter_bodies():
            cells = body.cells
            if cells is None:
                continue
            d = cells[..., _IDX_DENSITY]
            bond_e = cells[..., _IDX_BOND_E]
            bond_s = cells[..., _IDX_BOND_S]
            # Only consider cracks inside the body — empty cells default to
            # bond_*=1.0 from the pool, but density==0 means "not there".
            present = d > 0.05
            cracked = present & (
                (bond_e < _AO_CRACKED_BOND_THRESHOLD)
                | (bond_s < _AO_CRACKED_BOND_THRESHOLD)
            )
            if not cracked.any():
                continue
            cx_world, cy_world, _cs_x, _cs_y = _body_cell_world_centers(
                world, body.root_hull_id,
            )
            sx, sy = _world_to_screen_arrays(
                cx_world[cracked], cy_world[cracked],
                self.world_view, width, height,
            )
            sxi = np.rint(sx).astype(np.int32)
            syi = np.rint(sy).astype(np.int32)
            in_bounds = (sxi >= 0) & (sxi < width) & (syi >= 0) & (syi < height)
            if not in_bounds.any():
                continue
            xs = sxi[in_bounds]
            ys = syi[in_bounds]
            np.add.at(crack_map, (ys, xs), 1.0)
        return crack_map


# ---------------------------------------------------------------------------
# MultiLightShadowPass
# ---------------------------------------------------------------------------


def MultiLightShadowPass(
    lights: list[ShadowLight] | None = None,
    *,
    world_view: tuple[float, float, float, float] = _DEFAULT_WORLD_VIEW,
) -> ShadowPass:
    """Build a :class:`ShadowPass` that renders only ``lights``.

    The legacy primary light is suppressed; pass ``lights=[]`` for an
    explicit no-op pass that returns a copy of its input.

    Parameters
    ----------
    lights:
        List of :class:`ShadowLight` to project.  ``None`` is treated
        as the empty list (no-op).
    world_view:
        Screen-space world rectangle; forwarded to the underlying
        ``ShadowPass.world_view`` so projections line up with the
        renderer.
    """
    return ShadowPass(
        opacity=0.0,  # belt-and-braces: ignored due to _skip_primary
        additional_lights=list(lights or []),
        world_view=world_view,
        _skip_primary=True,
    )


__all__ = ["ShadowPass", "AOPass", "ShadowLight", "MultiLightShadowPass"]
