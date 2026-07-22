"""Fragment shapes — polygon-based footprints for solid particles.

A :class:`FragmentShape` is a 2D polygon (counter-clockwise vertex list
in unit space, typical radius ≈ 1.0). At spawn, the shape is scaled by
the particle's radius and (optionally) rotated. Each shape derives:

* a bake mask (via scanline rasterise) — the silhouette stamped into
  the world's per-pixel mask when the particle settles
* a roughness metric — std-dev of vertex distances over mean, drives
  the tumble kick
* a kick factor at a given contact angle — the slope of the boundary
  at that angle, which generates a vertical impulse when the fragment
  rolls/lands

A :class:`FragmentFamily` is a weighted collection of shapes that one
material samples from. SAND_FAMILY is mostly circles + a few rough
shapes; ROCK_FAMILY is boulder + shard; MUD_FAMILY is one blob shape.

This is the *hierarchical* fragment solution: Material → FragmentFamily
→ FragmentShape → polygon vertices. Each layer is a clean abstraction
with its own concerns (material physics ≠ shape geometry ≠ raster ops).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw


# ── FragmentShape ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class FragmentShape:
    """A 2D polygon footprint in unit space.

    ``vertices`` is a tuple of (x, y) pairs roughly inscribed in the
    unit circle. The polygon should be simple (non-self-intersecting)
    and wound counter-clockwise. The first vertex is at angle 0 by
    convention; the remaining vertices wrap around.
    """

    name: str
    vertices: tuple[tuple[float, float], ...]

    # ── Derived geometric stats ──────────────────────────────────────

    @property
    def n(self) -> int:
        return len(self.vertices)

    @property
    def bounds_radius(self) -> float:
        """Max distance from origin to any vertex (the bounding circle)."""
        return max(math.hypot(x, y) for x, y in self.vertices)

    @property
    def area(self) -> float:
        """Polygon area via the shoelace formula."""
        s = 0.0
        n = self.n
        for i in range(n):
            x0, y0 = self.vertices[i]
            x1, y1 = self.vertices[(i + 1) % n]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2.0

    @property
    def roughness(self) -> float:
        """Std-dev of vertex distances / mean. 0 = perfect circle;
        > 0 = irregular fragment. Drives the tumble kick strength."""
        rs = [math.hypot(x, y) for x, y in self.vertices]
        mean = sum(rs) / len(rs)
        if mean <= 0.0:
            return 0.0
        var = sum((r - mean) ** 2 for r in rs) / len(rs)
        return math.sqrt(var) / mean

    def radius_at(self, theta_rad: float) -> float:
        """Distance from origin to the polygon edge at angle theta.

        Interpolates between the two adjacent vertex radii. Useful
        for asking "what's the radius in this contact direction?"
        """
        # Sample vertex radii at their angles, then interpolate.
        n = self.n
        verts_theta_r = [
            (math.atan2(y, x) % (2 * math.pi), math.hypot(x, y))
            for x, y in self.vertices
        ]
        verts_theta_r.sort(key=lambda tr: tr[0])
        target = theta_rad % (2 * math.pi)
        # Find the pair straddling target.
        for i in range(n):
            t0, r0 = verts_theta_r[i]
            t1, r1 = verts_theta_r[(i + 1) % n]
            if t1 < t0:
                t1 += 2 * math.pi
            tt = target
            if i == n - 1 and target < t0:
                tt = target + 2 * math.pi
            if t0 <= tt <= t1:
                frac = (tt - t0) / (t1 - t0) if t1 > t0 else 0.0
                return r0 + frac * (r1 - r0)
        return verts_theta_r[0][1]  # fallback

    def kick_factor(self, contact_angle_rad: float) -> float:
        """Slope of the boundary at the contact angle, normalised.

        Pointy fragments (large radius difference between neighbour
        angles) give large kicks; round fragments give small kicks.
        Returns roughly in [0, 1].
        """
        eps = 0.05
        r1 = self.radius_at(contact_angle_rad + eps)
        r0 = self.radius_at(contact_angle_rad - eps)
        mean = max(1e-6, (r0 + r1) * 0.5)
        return min(1.0, abs(r1 - r0) / (mean * eps * 2))

    # ── Rasterisation to a stamp mask ────────────────────────────────

    def bake_mask(self, scale: float = 1.0, rotation: float = 0.0) -> np.ndarray:
        """Rasterise the shape at the given (uniform) scale and rotation.
        Returns a ``(size, size)`` bool ndarray centred on the polygon's
        origin. Uses PIL scanline fill.
        """
        return self.bake_mask_xy(scale, scale, rotation)

    def bake_mask_xy(
        self,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        rotation: float = 0.0,
    ) -> np.ndarray:
        """Rasterise with separate x/y scales — drives splat
        deformation. ``scale_x > scale_y`` stretches the polygon
        horizontally and squashes vertically (the natural "splat
        against the ground" shape).
        """
        sx = max(0.1, scale_x)
        sy = max(0.1, scale_y)
        R = max(1, int(math.ceil(self.bounds_radius * max(sx, sy))) + 1)
        size = 2 * R + 1
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        pts = []
        for x, y in self.vertices:
            # Rotation applied in unit space, then non-uniform scale,
            # so the splat direction is fixed in world frame regardless
            # of the polygon's own rotation.
            xr = x * cos_r - y * sin_r
            yr = x * sin_r + y * cos_r
            pts.append((xr * sx + R, yr * sy + R))
        im = Image.new("1", (size, size), 0)
        ImageDraw.Draw(im).polygon(pts, fill=1)
        return np.array(im, dtype=bool)


# ── Predefined shapes ──────────────────────────────────────────────────


def _ngon(n: int, radii: Sequence[float] | float = 1.0) -> tuple[tuple[float, float], ...]:
    """Build an n-gon with given per-vertex radii (or constant)."""
    if isinstance(radii, (int, float)):
        radii_seq = [float(radii)] * n
    else:
        radii_seq = list(radii)
        assert len(radii_seq) == n
    verts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        r = radii_seq[i]
        verts.append((r * math.cos(theta), r * math.sin(theta)))
    return tuple(verts)


SHAPE_CIRCLE = FragmentShape("circle", _ngon(16, 1.0))
SHAPE_ROUGH = FragmentShape(
    "rough", _ngon(12, [1.0, 1.1, 0.85, 1.0, 1.15, 0.9, 1.05, 0.8, 1.0, 1.2, 0.9, 1.0]),
)
SHAPE_SHARD = FragmentShape(
    "shard", _ngon(8, [1.6, 0.5, 0.35, 0.5, 0.4, 0.5, 0.35, 0.5]),
)
SHAPE_BOULDER = FragmentShape(
    "boulder", _ngon(10, [1.1, 0.85, 1.2, 0.75, 1.05, 1.25, 0.9, 1.1, 0.8, 1.0]),
)
SHAPE_FLAKE = FragmentShape(
    "flake", _ngon(8, [1.5, 0.25, 1.2, 0.25, 1.4, 0.25, 1.3, 0.25]),
)
# Blob: smooth-ish but slightly irregular (sin-based perturbation).
SHAPE_BLOB = FragmentShape(
    "blob",
    _ngon(16, [1.0 + 0.12 * math.sin(i * 2.3) for i in range(16)]),
)


# ── FragmentFamily ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class FragmentFamily:
    """A weighted collection of shapes that one material can produce.

    Materials reference a single family. On spawn, each particle picks
    a shape via :meth:`sample`. Weights default to uniform; supply them
    to bias toward certain shapes (e.g. sand is mostly circles + the
    odd rough grain).
    """

    name: str
    shapes: tuple[FragmentShape, ...]
    weights: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not self.shapes:
            raise ValueError(f"FragmentFamily {self.name!r} needs at least one shape")
        if self.weights is not None and len(self.weights) != len(self.shapes):
            raise ValueError(
                f"weights length ({len(self.weights)}) != shapes length ({len(self.shapes)})"
            )

    def sample_index(self, rng: np.random.Generator) -> int:
        if self.weights is None:
            return int(rng.integers(0, len(self.shapes)))
        w = np.asarray(self.weights, dtype=np.float64)
        p = w / w.sum()
        return int(rng.choice(len(self.shapes), p=p))

    def sample(self, rng: np.random.Generator) -> FragmentShape:
        return self.shapes[self.sample_index(rng)]


SAND_FAMILY = FragmentFamily(
    "sand", (SHAPE_CIRCLE, SHAPE_ROUGH), weights=(0.7, 0.3),
)
ROCK_FAMILY = FragmentFamily(
    "rock", (SHAPE_BOULDER, SHAPE_SHARD), weights=(0.7, 0.3),
)
MUD_FAMILY = FragmentFamily(
    "mud", (SHAPE_BLOB,),
)
SLOPPY_FAMILY = FragmentFamily(
    "sloppy", (SHAPE_BLOB, SHAPE_BOULDER), weights=(0.8, 0.2),
)
SNOW_FAMILY = FragmentFamily(
    "snow", (SHAPE_FLAKE, SHAPE_CIRCLE), weights=(0.8, 0.2),
)
ICE_FAMILY = FragmentFamily(
    "ice", (SHAPE_SHARD,),
)
WATER_FAMILY = FragmentFamily(
    "water", (SHAPE_CIRCLE,),
)


BUILTIN_FAMILIES: tuple[FragmentFamily, ...] = (
    SAND_FAMILY, ROCK_FAMILY, MUD_FAMILY, SLOPPY_FAMILY,
    SNOW_FAMILY, ICE_FAMILY, WATER_FAMILY,
)


# ── Shape registry / helpers ────────────────────────────────────────────


def all_shapes() -> tuple[FragmentShape, ...]:
    """Every predefined shape — useful for tests / introspection."""
    return (
        SHAPE_CIRCLE, SHAPE_ROUGH, SHAPE_SHARD,
        SHAPE_BOULDER, SHAPE_FLAKE, SHAPE_BLOB,
    )


__all__ = [
    "FragmentShape",
    "FragmentFamily",
    "SHAPE_CIRCLE", "SHAPE_ROUGH", "SHAPE_SHARD",
    "SHAPE_BOULDER", "SHAPE_FLAKE", "SHAPE_BLOB",
    "SAND_FAMILY", "ROCK_FAMILY", "MUD_FAMILY", "SLOPPY_FAMILY",
    "SNOW_FAMILY", "ICE_FAMILY", "WATER_FAMILY",
    "BUILTIN_FAMILIES",
    "all_shapes",
]
