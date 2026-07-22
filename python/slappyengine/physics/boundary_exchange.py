"""Per-frame heat exchange across hierarchical-hull contact seams.

The hierarchical-hull solver diffuses heat *inside* each body via the
per-pixel kernel's Laplacian, but two touching bodies are otherwise thermal
islands — a lava ball pressed against an ice block keeps glowing forever
without ever warming its neighbour.

:class:`BoundaryExchange` closes that gap.  Each frame, for every contact
pair emitted by the broadphase / narrowphase, it identifies the strip of
cells on either side of the seam and applies a Fourier-style flux:

    q = thermal_conductance * (T_a_avg - T_b_avg) * dt

where ``thermal_conductance`` is the harmonic mean of the two materials'
:attr:`CellMaterial.thermal_k` (so an insulator on either side dominates
the rate, matching the physical series-resistor analogy).

Conservation invariant
----------------------
Mass-weighted heat ``Σ(m_cell * h_cell)`` is exactly preserved across the
exchange (modulo float rounding).  We compute one scalar energy quantum
``Q = q`` (heat × mass units) and redistribute it: subtract from A's strip
in proportion to each cell's mass-share of the strip, add to B's strip
likewise.  No cell mass enters or leaves the body — only heat.

Approximations / limitations
----------------------------
* Strip depth is a fixed ``STRIP_DEPTH = 3`` cells.  Deeper bodies see only
  this surface skin participate per frame; internal diffusion handles the
  rest.
* The contact normal from :class:`ContactPair` is the world-space ``a → b``
  axis.  We transform it into each body's local frame via the body's
  rotation (``angle``) but ignore stretch/shear — adequate for Sprint 1
  rigid bodies, where ``stretch == (1, 1)`` and ``shear == 0``.
* The strip is axis-aligned in body-local space: we project the local
  normal onto its dominant axis and take the 3 outermost cell rows/cols
  on that side.  This matches the AABB-aligned narrowphase normal exactly
  and avoids needing per-cell distance-to-plane queries.
* Cells whose density is effectively zero (silhouette holes) contribute
  zero mass and therefore no heat; they are skipped automatically.
* Bodies without a cell grid (T0 / T1 hulls, walls with ``b < 0``) are
  silently skipped.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from slappyengine._compat import CellMaterial
from slappyengine.physics.cell import CELL_GRID_SIZE, CellGridPool
from slappyengine.physics.hull import HullTree


# --- channel indices (must match CELL_PIXEL_STRUCT order in cell.py) -------
_IDX_DENSITY = 9
_IDX_HEAT = 12


# Depth (in cells) of the contact-zone strip on each side of the seam.
# Three cells deep matches the design-doc guidance for surface-skin
# coupling: thin enough that internal diffusion still has work to do,
# thick enough to absorb a single frame's flux without numerical
# saturation.
STRIP_DEPTH = 3


class BoundaryExchange:
    """Per-frame heat conduction across contact pairs.

    The class is a thin functional object: it borrows references to the
    cell pool, hull tree, and material lookup owned by
    :class:`PhysicsWorld`, and mutates the heat channel of each body's
    cell grid when :meth:`exchange` is invoked.

    Parameters
    ----------
    cell_pool:
        The world's :class:`CellGridPool`.  We index ``slot_view(slot_id)``
        to obtain ``(32, 32, C)`` views and write into the heat channel.
    hulls:
        The world's :class:`HullTree`.  We read ``cell_grid_id``,
        ``angle``, ``position``, ``cell_size_x/y``, and ``material_id``
        per hull.
    body_lookup:
        Mapping ``hull_id -> PhysicsBody``.  Currently unused for heat —
        all data we need lives on the hull tree and material lookup — but
        kept in the signature so Sprint 3's stress/mass coupling has a
        single import surface.
    material_lookup:
        Mapping ``material_id (uint16) -> CellMaterial``.  We pull
        ``thermal_k`` and ``density_rho`` from here.
    """

    def __init__(
        self,
        cell_pool: CellGridPool,
        hulls: HullTree,
        body_lookup: dict,
        material_lookup: dict,
    ) -> None:
        self.cell_pool = cell_pool
        self.hulls = hulls
        self.body_lookup = body_lookup
        self.material_lookup = material_lookup

    # ------------------------------------------------------------------ API

    def exchange(self, contacts: Iterable, dt: float) -> None:
        """Apply heat flux across every body-body contact in ``contacts``.

        Walls and self-contacts are skipped.  Contacts where either body
        lacks a cell grid (T0 / T1 hulls) are skipped.  ``dt <= 0`` is a
        no-op.

        Parameters
        ----------
        contacts:
            Iterable of :class:`ContactPair` (or any duck-typed object
            exposing ``a``, ``b``, and ``normal``).
        dt:
            Frame time-step in seconds.
        """
        if dt <= 0.0:
            return

        for pair in contacts:
            a = int(pair.a)
            b = int(pair.b)
            # Walls signal with b < 0 — no second body to exchange with.
            if a < 0 or b < 0 or a == b:
                continue
            self._exchange_pair(a, b, tuple(pair.normal), float(dt))

    # ------------------------------------------------------------- internals

    def _exchange_pair(
        self,
        a: int,
        b: int,
        normal: tuple[float, float],
        dt: float,
    ) -> None:
        """Transfer heat from body ``a`` to body ``b`` along ``normal``."""
        slot_a = int(self.hulls.cell_grid_id[a])
        slot_b = int(self.hulls.cell_grid_id[b])
        if slot_a < 0 or slot_b < 0:
            return

        mat_a = self._material(a)
        mat_b = self._material(b)
        if mat_a is None or mat_b is None:
            return

        cells_a = self.cell_pool.slot_view(slot_a)
        cells_b = self.cell_pool.slot_view(slot_b)

        # Contact normal is world-space, a → b.  Body a's near-contact
        # strip lies on its +n side; body b's lies on its -n side.
        nx, ny = normal
        # Normalise defensively (narrowphase already does, but caller
        # contracts vary).
        nlen = math.hypot(nx, ny)
        if nlen < 1e-12:
            return
        nx /= nlen
        ny /= nlen

        strip_a = self._strip_cells(a, cells_a, (nx, ny))
        strip_b = self._strip_cells(b, cells_b, (-nx, -ny))
        if strip_a is None or strip_b is None:
            return

        heat_a_view, mass_a, total_h_a, total_m_a = strip_a
        heat_b_view, mass_b, total_h_b, total_m_b = strip_b

        if total_m_a <= 0.0 or total_m_b <= 0.0:
            return

        # Mass-weighted mean temperatures over each strip.
        t_a = total_h_a / total_m_a
        t_b = total_h_b / total_m_b

        # Harmonic mean of thermal_k: insulator dominates (series resistors).
        # If either side has zero conductivity, no exchange happens.
        ka = float(mat_a.thermal_k)
        kb = float(mat_b.thermal_k)
        if ka <= 0.0 or kb <= 0.0:
            return
        k_harm = 2.0 * ka * kb / (ka + kb)

        # Heat-energy flux Q in units of (heat * mass).  ΔT = (t_a - t_b);
        # positive Q moves energy from a to b.
        q = k_harm * (t_a - t_b) * dt

        # Stability clamp: never overshoot equalisation.  The limiting
        # case is Q == (t_a - t_b) / (1/m_a + 1/m_b), which would set both
        # strips to the same final temperature.  Going past that flips
        # the sign of (t_a - t_b) and the system oscillates.
        m_eff = 1.0 / (1.0 / total_m_a + 1.0 / total_m_b)
        q_eq = (t_a - t_b) * m_eff
        if q_eq >= 0.0:
            q = min(q, q_eq)
            q = max(q, 0.0)
        else:
            q = max(q, q_eq)
            q = min(q, 0.0)

        if q == 0.0:
            return

        # Distribute Q in proportion to each cell's mass share of the strip.
        # Δh_cell = ∓Q * (m_cell / m_strip) / m_cell = ∓Q / m_strip
        # ⇒ uniform per-cell Δh across the strip, but only cells with
        # mass > 0 matter (zero-mass cells contribute no heat anyway).
        dh_a = -q / total_m_a
        dh_b = +q / total_m_b

        # Apply only to cells with non-zero mass so silhouette holes
        # stay at zero heat (their density was zero so heat had no
        # physical meaning there).
        nonzero_a = mass_a > 0.0
        nonzero_b = mass_b > 0.0
        heat_a_view[nonzero_a] += dh_a
        heat_b_view[nonzero_b] += dh_b

    # -----------------------------------------------------------------------

    def _material(self, hull_id: int) -> CellMaterial | None:
        """Resolve the :class:`CellMaterial` for ``hull_id``, or ``None``."""
        mid = int(self.hulls.material_id[hull_id])
        return self.material_lookup.get(mid)

    def _strip_cells(
        self,
        hull_id: int,
        cells: np.ndarray,
        world_normal: tuple[float, float],
    ) -> tuple[np.ndarray, np.ndarray, float, float] | None:
        """Return the ``STRIP_DEPTH``-deep strip on the +n side of the body.

        ``world_normal`` is the world-space direction pointing from this
        body's centre toward the contact.  We rotate it into body-local
        frame using the hull's ``angle``, then pick the dominant local
        axis to choose which 32×3 (or 3×32) slab of cells to expose.

        Returns
        -------
        (heat_view, mass_view, total_h, total_m) or None
            ``heat_view`` is a writable ``np.ndarray`` slice into the
            cell grid's heat channel.  ``mass_view`` is a read-only slice
            of per-cell mass (density × ρ × area).  ``total_h`` /
            ``total_m`` are mass-weighted heat and mass sums over the
            strip.  Returns ``None`` if the hull has no cell grid.
        """
        # Transform world normal → body-local normal.  Stretch/shear are
        # identity in Sprint 1; only angle matters.
        ang = float(self.hulls.angle[hull_id])
        c, s = math.cos(ang), math.sin(ang)
        # Inverse rotation: local = R(-angle) · world.
        local_nx = c * world_normal[0] + s * world_normal[1]
        local_ny = -s * world_normal[0] + c * world_normal[1]

        # Pick dominant axis.  Body-local axes: +x → east (cx increases),
        # +y → south (cy increases), matching the cells[cy, cx] indexing
        # used throughout silhouette_to_cells and the kernel.
        if abs(local_nx) >= abs(local_ny):
            axis = "x"
            positive = local_nx >= 0.0
        else:
            axis = "y"
            positive = local_ny >= 0.0

        n = CELL_GRID_SIZE
        depth = min(STRIP_DEPTH, n)
        if axis == "x":
            if positive:
                xs = slice(n - depth, n)  # rightmost columns
            else:
                xs = slice(0, depth)      # leftmost columns
            heat_slab = cells[:, xs, _IDX_HEAT]
            density_slab = cells[:, xs, _IDX_DENSITY]
        else:
            if positive:
                ys = slice(n - depth, n)  # bottom rows (south)
            else:
                ys = slice(0, depth)      # top rows
            heat_slab = cells[ys, :, _IDX_HEAT]
            density_slab = cells[ys, :, _IDX_DENSITY]

        mat = self._material(hull_id)
        if mat is None:
            return None
        csx = float(self.hulls.cell_size_x[hull_id])
        csy = float(self.hulls.cell_size_y[hull_id])
        cell_area = csx * csy
        # Per-cell mass: ρ_material * density_field * cell_area.
        mass_slab = (mat.density_rho * density_slab.astype(np.float64)) * cell_area

        total_m = float(mass_slab.sum())
        total_h = float((mass_slab * heat_slab.astype(np.float64)).sum())
        return heat_slab, mass_slab, total_h, total_m
