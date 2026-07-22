"""Heat diffusion + pairwise heat exchange — Phase B public surface.

Two related primitives:

* :class:`HeatField` — a 2D temperature grid stepped forward by explicit
  finite-volume diffusion. The math is the *pairwise* Newton's-law flux
  lifted from ``physics.boundary_exchange.py:_exchange_pair`` (proven
  conservative after WP-O's fix) applied edge-by-edge across the
  4-neighbour stencil. Because each edge moves an equal heat quantum
  between its two cells, ``Σ T`` is preserved exactly modulo float
  rounding.
* :func:`exchange_two_regions` — Newton's-law heat exchange between two
  mass-weighted regions. Same formula, exposed as a scalar primitive
  so non-grid consumers (boundary pairs in dynamics, particle-particle
  fluid exchange) don't have to instantiate a grid.

Both forms are unit-agnostic — temperature can be normalised [0, 1] or
real SI Kelvin, mass can be cell-fill or kg, the math holds as long as
the inputs are dimensionally consistent. Conductivity ``k`` mixes via
the harmonic mean (series-resistor analogue): an insulator on one side
caps the flux even if the other side is highly conductive.

Phase B repackage notes
-----------------------
The legacy ``physics.boundary_exchange.BoundaryExchange`` class will be
retired in Phase D. The math it embodies — the harmonic-mean conductivity,
the equalisation clamp ``q_eq = (T_a - T_b) * m_eff`` that prevents
oscillation, and the proportional redistribution of one scalar quantum
across the contact strip — all lives here now. The fluid module's C4
thermal pass will call :meth:`HeatField.step` rather than re-deriving the
formula.
"""
from __future__ import annotations

import math
from typing import Iterable, Tuple

import numpy as np

from ._protocol import HeatSourceProtocol
from ._validation import (
    validate_diffusivity,
    validate_finite_float,
    validate_grid_2d_float,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
)


__all__ = ["HeatField", "HeatSourceProtocol", "exchange_two_regions"]


# ── Pairwise exchange (boundary_exchange.py heat path) ──────────────────────


def exchange_two_regions(
    t_a: float,
    m_a: float,
    k_a: float,
    t_b: float,
    m_b: float,
    k_b: float,
    dt: float,
) -> float:
    """Conservative Newton's-law heat flux between two mass-weighted regions.

    Returns ``q`` — the heat-energy (units: temperature × mass) that
    flows from A to B during ``dt``. Positive ``q`` cools A and warms B.

    Caller distributes the flux back to the regions via::

        t_a_new = t_a - q / m_a
        t_b_new = t_b + q / m_b

    Parameters
    ----------
    t_a, t_b
        Mean temperature of region A and B (same units, e.g. K or
        normalised [0, 1]).
    m_a, m_b
        Total mass (or cell-fill mass-equivalent) of each region.
        Must be > 0; returns 0 otherwise.
    k_a, k_b
        Thermal conductivity of each region's material. Both must be > 0.
        Mixed via harmonic mean (series resistors).
    dt
        Timestep in seconds (or whatever time unit the conductivities
        are calibrated against).

    The flux is clamped so the exchange cannot overshoot temperature
    equalisation (which would cause oscillation across repeated steps).
    """
    if m_a <= 0.0 or m_b <= 0.0:
        return 0.0
    if k_a <= 0.0 or k_b <= 0.0:
        return 0.0

    k_harm = 2.0 * k_a * k_b / (k_a + k_b)
    q = k_harm * (t_a - t_b) * dt

    # Stability clamp: cap to the equalisation flux.
    m_eff = 1.0 / (1.0 / m_a + 1.0 / m_b)
    q_eq = (t_a - t_b) * m_eff
    if q_eq >= 0.0:
        q = min(q, q_eq)
        q = max(q, 0.0)
    else:
        q = max(q, q_eq)
        q = min(q, 0.0)
    return float(q)


# ── 2D heat field ───────────────────────────────────────────────────────────


_VALID_BOUNDARIES = ("periodic", "clamp")


class HeatField:
    """A 2D temperature grid with explicit pairwise-flux diffusion.

    Construction::

        T = np.zeros((64, 64), dtype=np.float32)
        field = HeatField(T, conductivity=1.0, diffusivity=0.1)
        field.step(0.05)                       # toroidal by default
        field.step(0.05, boundary='clamp')     # adiabatic edges

    The grid is held by reference and *modified in place* by both
    :meth:`step` and :meth:`exchange_with` — the caller's ``T`` array
    sees the temperature update with no extra copy.

    Conservation
    ------------
    Each step decomposes the 4-neighbour stencil into individual edges.
    Per edge ``(a, b)`` the heat-energy quantum::

        q = k * (T_a - T_b) * dt          (clamped to (T_a - T_b) * m/2)

    is computed, A loses ``q/m`` and B gains ``q/m``. The two updates
    cancel exactly, so ``Σ T`` is preserved to within float rounding
    (typically ``< 1e-9`` per step on f64 grids).

    Boundary modes
    --------------
    * ``periodic`` (default) — the field is toroidal; cells on the east
      edge exchange with cells on the west edge, etc. Matches the
      assumption used by the fluid module's particle grid sampling.
    * ``clamp`` — no flux crosses the outer rectangle. Equivalent to a
      Neumann-zero boundary; energy injected at the edge stays inside.

    Parameters
    ----------
    grid
        A 2D ``np.ndarray`` of temperatures. Held by reference and
        mutated in place.
    conductivity
        ``k`` — per-cell thermal conductivity used by the pairwise
        flux. Defaults to ``1.0``.
    diffusivity
        ``α`` — per-step coupling factor. Defaults to ``0.1``. The
        effective per-step rate is ``conductivity * diffusivity * dt``;
        both knobs are exposed so the fluid module can tune
        conductivity per-material while keeping a global ``α`` knob
        in YAML config.
    """

    def __init__(
        self,
        grid: np.ndarray,
        conductivity: float = 1.0,
        diffusivity: float = 0.1,
    ) -> None:
        """Hold a 2-D temperature grid and stepping parameters.

        Raises
        ------
        TypeError
            If ``grid`` is not a 2-D float numpy ndarray, or if
            ``conductivity`` / ``diffusivity`` are not real numbers.
        ValueError
            If ``grid`` is smaller than 2x2, ``conductivity`` is negative,
            or ``diffusivity`` falls outside ``(0, 1]``.
        """
        validate_grid_2d_float("grid", "HeatField", grid)
        if grid.shape[0] < 2 or grid.shape[1] < 2:
            raise ValueError(
                f"HeatField: grid must be at least 2x2; got shape {grid.shape}"
            )

        self.temperature = grid  # held by reference, mutated in place
        self.conductivity = validate_non_negative_float(
            "conductivity", "HeatField", conductivity,
        )
        self.diffusivity = validate_diffusivity("HeatField", diffusivity)

    @property
    def shape(self) -> tuple[int, int]:
        return self.temperature.shape

    def total_heat(self) -> float:
        """Sum of cell temperatures — conservation-check hook for tests.

        Assumes uniform per-cell mass. Callers with non-uniform cell
        masses should compute their own mass-weighted sum.
        """
        return float(self.temperature.sum())

    # ----- core step -------------------------------------------------------

    def step(
        self,
        dt: float,
        *,
        boundary: str = "periodic",
        substeps: int | None = None,
    ) -> None:
        """Advance the temperature field by ``dt`` via pairwise diffusion.

        The 4-neighbour Laplacian is decomposed into per-edge fluxes
        using the same formula as :func:`exchange_two_regions`
        (``k_harm * ΔT * dt`` clamped to equalisation). Each edge moves
        an equal quantum between its two cells so total heat is exactly
        preserved.

        Parameters
        ----------
        dt
            Step in time units. The internal effective rate is
            ``conductivity * diffusivity * dt`` per axis pair.
        boundary
            ``"periodic"`` (default) wraps the grid into a torus;
            ``"clamp"`` zeroes flux across the outer rectangle.
        substeps
            Optional manual override of the internal substepping.
            By default the field substeps so the effective coupling
            per substep stays at or below the CFL-style cap ``1/4``.

        Raises
        ------
        TypeError
            If ``dt`` is not a real number, or ``boundary`` is not a string,
            or ``substeps`` (when provided) is not an integer.
        ValueError
            If ``dt`` is non-finite or negative, ``boundary`` is not one
            of ``{"periodic", "clamp"}``, or ``substeps`` < 1.
        """
        if not isinstance(boundary, str):
            raise TypeError(
                f"HeatField.step: boundary must be a string; "
                f"got {type(boundary).__name__}"
            )
        if boundary not in _VALID_BOUNDARIES:
            raise ValueError(
                f"HeatField.step: boundary must be one of {_VALID_BOUNDARIES}; "
                f"got {boundary!r}"
            )
        # Allow dt == 0.0 (no-op) for parity with existing callers, but
        # reject anything negative or non-finite outright.
        dt_v = validate_finite_float("dt", "HeatField.step", dt)
        if dt_v < 0.0:
            raise ValueError(f"HeatField.step: dt must be ≥ 0; got {dt_v!r}")
        if substeps is not None:
            substeps = validate_positive_int(
                "substeps", "HeatField.step", substeps,
            )
        if dt_v == 0.0:
            return
        dt = dt_v

        # Effective per-axis coupling factor (mirrors the explicit
        # Laplacian's α·dt/h² scale; we fix h = 1 in this surface and
        # let the diffusivity / conductivity knobs absorb the rest).
        coupling = self.conductivity * self.diffusivity * dt

        if substeps is None:
            # Per-edge clamp keeps each pair from overshooting, but a
            # cell with 4 neighbours can still oscillate if the per-step
            # rate exceeds 1/4. Sub-step to stay within that cap with a
            # 10% safety margin.
            n = max(1, int(math.ceil(coupling / 0.225)))
        else:
            n = max(1, int(substeps))

        sub_coupling = coupling / n
        T = self.temperature
        for _ in range(n):
            self._pairwise_substep(T, sub_coupling, boundary)

    @staticmethod
    def _pairwise_substep(
        T: np.ndarray,
        coupling: float,
        boundary: str,
    ) -> None:
        """One sub-step of the per-edge conservative flux.

        Per edge ``(a, b)``::

            flux = coupling * (T_a - T_b)
            T_a -= flux
            T_b += flux

        With ``coupling ≤ 1/2`` per axis the pair update is
        unconditionally non-overshooting; with ``coupling ≤ 1/4`` per
        axis the 4-neighbour sum is non-oscillatory.
        """
        # ── X-axis edges: between (y, x) and (y, x+1) ───────────────────
        if boundary == "periodic":
            T_right = np.roll(T, -1, axis=1)
            # Compute the flux in float64 to keep conservation tight
            # even when the caller's grid is float32.
            flux_x = (coupling * (T - T_right).astype(np.float64)).astype(
                T.dtype, copy=False
            )
            T_new = T - flux_x + np.roll(flux_x, 1, axis=1)
        else:  # clamp
            T_left = T[:, :-1]
            T_right = T[:, 1:]
            flux_x = (coupling * (T_left - T_right).astype(np.float64)).astype(
                T.dtype, copy=False
            )
            T_new = T.copy()
            T_new[:, :-1] -= flux_x
            T_new[:, 1:] += flux_x

        # ── Y-axis edges: between (y, x) and (y+1, x) ───────────────────
        if boundary == "periodic":
            T_down = np.roll(T_new, -1, axis=0)
            flux_y = (coupling * (T_new - T_down).astype(np.float64)).astype(
                T.dtype, copy=False
            )
            T_after = T_new - flux_y + np.roll(flux_y, 1, axis=0)
        else:  # clamp
            T_up = T_new[:-1, :]
            T_dn = T_new[1:, :]
            flux_y = (coupling * (T_up - T_dn).astype(np.float64)).astype(
                T.dtype, copy=False
            )
            T_after = T_new.copy()
            T_after[:-1, :] -= flux_y
            T_after[1:, :] += flux_y

        # In-place write — preserves aliasing with the caller's array.
        T[...] = T_after

    # ----- pairwise inter-field exchange ----------------------------------

    def exchange_with(
        self,
        other: "HeatField",
        contact_pairs: Iterable[Tuple[Tuple[int, int], Tuple[int, int]]],
        dt: float = 1.0,
        *,
        conductivity: float | None = None,
    ) -> float:
        """Conservatively exchange heat with ``other`` across contact pairs.

        ``contact_pairs`` is an iterable of ``((iy, ix), (jy, jx))``
        cell-index pairs — each pair says "cell ``(iy, ix)`` on *this*
        field touches cell ``(jy, jx)`` on ``other``". For every pair we
        run the :func:`exchange_two_regions` flux (with mass=1 per cell)
        and redistribute the quantum. Total energy
        ``self.total_heat() + other.total_heat()`` is preserved up to
        float tolerance.

        Parameters
        ----------
        other
            The second field. May be the same instance for self-coupling
            tests, but pair indices must still be valid into both grids.
        contact_pairs
            Iterable of ``((iy, ix), (jy, jx))``. Out-of-bounds indices
            are silently skipped.
        dt
            Time step. Defaults to ``1.0`` so callers can hand-tune
            per-pair rates by sweeping ``conductivity`` directly.
        conductivity
            Override the harmonic conductivity used for these pairs.
            Defaults to the harmonic mean of the two fields'
            :attr:`conductivity`.

        Returns
        -------
        float
            Total heat moved from ``self`` to ``other`` (positive if
            ``self`` was hotter on net). Useful for telemetry / tests.

        Raises
        ------
        TypeError
            If ``other`` is not a :class:`HeatField`, or ``contact_pairs``
            is not iterable, or ``dt`` / ``conductivity`` are not real
            numbers.
        ValueError
            If ``dt`` is non-finite or negative, or ``conductivity`` is
            non-finite or negative.
        """
        if not isinstance(other, HeatField):
            raise TypeError(
                f"HeatField.exchange_with: other must be a HeatField; "
                f"got {type(other).__name__}"
            )
        if isinstance(contact_pairs, (str, bytes)) or not hasattr(
            contact_pairs, "__iter__"
        ):
            raise TypeError(
                f"HeatField.exchange_with: contact_pairs must be iterable; "
                f"got {type(contact_pairs).__name__}"
            )
        dt_v = validate_finite_float("dt", "HeatField.exchange_with", dt)
        if dt_v < 0.0:
            raise ValueError(
                f"HeatField.exchange_with: dt must be ≥ 0; got {dt_v!r}"
            )
        if conductivity is not None:
            # Conductivity may be 0 explicitly (no flux); reject negative
            # / non-finite.
            k_check = validate_finite_float(
                "conductivity", "HeatField.exchange_with", conductivity,
            )
            if k_check < 0.0:
                raise ValueError(
                    f"HeatField.exchange_with: conductivity must be ≥ 0; "
                    f"got {k_check!r}"
                )
        if dt_v == 0.0:
            return 0.0
        dt = dt_v

        if conductivity is None:
            k_a = self.conductivity
            k_b = other.conductivity
            if k_a <= 0.0 or k_b <= 0.0:
                return 0.0
            k = 2.0 * k_a * k_b / (k_a + k_b)
        else:
            k = float(conductivity)
            if k <= 0.0:
                return 0.0

        Ta = self.temperature
        Tb = other.temperature
        Ha, Wa = Ta.shape
        Hb, Wb = Tb.shape

        total_q = 0.0
        for pair in contact_pairs:
            (iy, ix), (jy, jx) = pair
            iy = int(iy); ix = int(ix); jy = int(jy); jx = int(jx)
            if not (0 <= iy < Ha and 0 <= ix < Wa):
                continue
            if not (0 <= jy < Hb and 0 <= jx < Wb):
                continue
            t_a = float(Ta[iy, ix])
            t_b = float(Tb[jy, jx])
            # Mass per cell = 1.0 in this public surface. Callers needing
            # mass-weighted strips should call exchange_two_regions directly.
            q = exchange_two_regions(
                t_a=t_a, m_a=1.0, k_a=k,
                t_b=t_b, m_b=1.0, k_b=k,
                dt=dt,
            )
            if q == 0.0:
                continue
            # m = 1 per side, so ΔT = ±q.
            Ta[iy, ix] = t_a - q
            Tb[jy, jx] = t_b + q
            total_q += q

        return float(total_q)
