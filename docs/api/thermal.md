# slappyengine.thermal — API Reference

> Hand-written Phase B subpackage reference. Source of truth for the
> public surface lives in `python/slappyengine/thermal/__init__.py`. Do
> NOT regenerate via `scripts/gen_subpackage_api_docs.py` — the prose,
> examples, and complexity annotations below are hand-curated.

## Overview

`slappyengine.thermal` is the engine's heat-diffusion + pairwise heat
exchange primitive. It exposes one class — `HeatField` — that wraps a 2D
temperature grid and steps it forward via an explicit conservative
finite-volume scheme, plus one scalar helper, `exchange_two_regions`,
that runs the same Newton's-law flux between two mass-weighted regions
without requiring a grid. The math is the pairwise flux lifted from
`physics.boundary_exchange.py:_exchange_pair` (proven conservative after
the WP-O fix): each edge moves an equal heat quantum between its two
cells, so the L1 sum of cell temperatures is preserved exactly modulo
float rounding. Both forms are unit-agnostic — temperatures may be
normalised [0, 1] or real SI Kelvin, masses may be cell-fill or kg —
as long as inputs stay dimensionally consistent.

## Numerical model

`HeatField.step` discretises the heat equation

> ∂T/∂t = α ∇²T

on a regular 2D grid (unit spacing) using a per-edge pairwise flux

> q = k_harm · (T_a − T_b) · dt        (clamped to (T_a − T_b) · m_eff)

where `k_harm = 2·k_a·k_b / (k_a + k_b)` is the harmonic-mean
conductivity (series-resistor analogue: an insulator on one side caps
the flux even if the other side is highly conductive), and the
equalisation clamp `m_eff = 1/(1/m_a + 1/m_b)` prevents the explicit
scheme from oscillating across repeated steps. The internal substep
count is chosen so the per-substep coupling `k·α·dt` stays at or below
the CFL-style cap `1/4` (with a 10% safety margin), matching the
stability bound for explicit four-neighbour finite-volume diffusion in
Strikwerda, *Finite Difference Schemes and Partial Differential
Equations* (SIAM, 2nd ed., §6) and Briggs, Henson, McCormick, *A
Multigrid Tutorial* (SIAM, 2nd ed., §2 — Jacobi/Gauss-Seidel CFL bound
for the 5-point Laplacian).

## Classes

### `HeatField`

_class — defined in `slappyengine.thermal`_

A 2D temperature grid stepped forward by explicit pairwise-flux
diffusion. The grid is held by reference and mutated in place by both
`step` and `exchange_with`, so the caller's `ndarray` sees the
temperature update without an extra copy.

#### Constructor signature

```python
HeatField(grid: np.ndarray,
          conductivity: float = 1.0,
          diffusivity:  float = 0.1)
```

#### Parameters

- `grid` — a 2D `np.ndarray` of float dtype (≥ 2×2). Held by reference.
- `conductivity` — per-cell thermal conductivity `k` (≥ 0).
- `diffusivity` — per-step coupling factor `α` ∈ (0, 1]. The effective
  per-step rate is `k · α · dt`; both knobs are exposed so the fluid
  module can vary `k` per-material while keeping a global `α` knob
  in YAML config.

#### Attributes

- `temperature: np.ndarray` — the wrapped grid (aliased; mutated in place).
- `shape: tuple[int, int]` — convenience accessor for `temperature.shape`.

#### Raises

- `TypeError` — if `grid` is not a 2D float `ndarray`, or `conductivity`
  / `diffusivity` are not real numbers.
- `ValueError` — if `grid` is smaller than 2×2, `conductivity` is
  negative, or `diffusivity` falls outside `(0, 1]`.

#### Example

```python
import numpy as np
from slappyengine.thermal import HeatField

T = np.full((64, 64), 20.0, dtype=np.float32)
T[32, 32] = 400.0                            # one hot spot
field = HeatField(T, conductivity=1.0, diffusivity=0.1)
for _ in range(60):
    field.step(1.0 / 60.0, boundary="clamp")
assert abs(field.total_heat() - (63 * 64 * 20.0 + 400.0)) < 1e-3
```

### `HeatField.step(dt, *, boundary='periodic', substeps=None)`

Advance the temperature field by `dt`. The 4-neighbour Laplacian is
decomposed into per-edge fluxes using the same formula as
`exchange_two_regions`; each edge moves an equal quantum between its
two cells so the cell-sum invariant ΣT is exactly preserved (per-step
residual typically < 1e-9 on f64 grids).

**Complexity**: O(N · substeps) where N is the cell count.
`substeps` defaults to `ceil(coupling / 0.225)` so the per-substep
coupling honours the CFL bound `1/4` with a 10% safety margin.

#### Parameters

- `dt` — step in time units; must be finite and `≥ 0`. `dt == 0` is a no-op.
- `boundary` — `"periodic"` (default) wraps into a torus; `"clamp"`
  enforces zero flux across the outer rectangle (Neumann-zero / adiabatic).
- `substeps` — optional manual override; pass an explicit integer when
  driving from an outer fixed-step solver and you want predictable cost.

#### Raises

- `TypeError` — if `dt` is not a real number, `boundary` is not a string,
  or `substeps` is not an integer.
- `ValueError` — if `dt < 0`, `boundary` is not one of `{"periodic",
  "clamp"}`, or `substeps < 1`.

#### Example

```python
import numpy as np
from slappyengine.thermal import HeatField

T = np.zeros((128, 128), dtype=np.float64)
T[60:68, 60:68] = 1.0
field = HeatField(T, conductivity=1.0, diffusivity=0.2)
e0 = field.total_heat()
for _ in range(120):
    field.step(1.0 / 60.0, boundary="periodic")
assert abs(field.total_heat() - e0) < 1e-9       # conservative
```

### `HeatField.exchange_with(other, contact_pairs, dt=1.0, *, conductivity=None)`

Conservatively exchange heat with a second `HeatField` across an
iterable of `((iy, ix), (jy, jx))` cell-index contact pairs. Returns the
total heat moved from `self` to `other` (positive if `self` was hotter
on net). Total energy `self.total_heat() + other.total_heat()` is
preserved to float tolerance; out-of-bounds indices are silently skipped.

**Complexity**: O(P) per call where P is the number of contact pairs.

#### Parameters

- `other` — second `HeatField`. May be the same instance for self-coupling.
- `contact_pairs` — iterable of `((iy, ix), (jy, jx))`. Each entry says
  "cell `(iy, ix)` on *this* field touches cell `(jy, jx)` on `other`".
- `dt` — time step (default `1.0` so callers can hand-tune per-pair
  rates by sweeping `conductivity` directly).
- `conductivity` — override the harmonic conductivity used for these
  pairs. Defaults to the harmonic mean of the two fields' `.conductivity`.

#### Raises

- `TypeError` — if `other` is not a `HeatField`, `contact_pairs` is not
  iterable, or `dt` / `conductivity` are not real numbers.
- `ValueError` — if `dt < 0` or `conductivity < 0`.

#### Example

```python
import numpy as np
from slappyengine.thermal import HeatField

a = HeatField(np.full((32, 32), 400.0, dtype=np.float64),
              conductivity=2.0, diffusivity=0.1)
b = HeatField(np.full((32, 32), 20.0,  dtype=np.float64),
              conductivity=0.5, diffusivity=0.1)
pairs = [((16, 0), (16, 31)), ((16, 31), (16, 0))]
e0 = a.total_heat() + b.total_heat()
for _ in range(240):
    a.step(1 / 60, boundary="clamp")
    b.step(1 / 60, boundary="clamp")
    a.exchange_with(b, pairs, dt=1 / 60)
assert abs((a.total_heat() + b.total_heat()) - e0) < 1e-6
```

## Functions

### `exchange_two_regions(t_a, m_a, k_a, t_b, m_b, k_b, dt) -> float`

Conservative Newton's-law heat flux between two mass-weighted regions.
Returns the scalar heat quantum `q` that flows from A to B during `dt`
(positive `q` cools A and warms B). The caller redistributes the flux:

```python
t_a_new = t_a - q / m_a
t_b_new = t_b + q / m_b
```

Returns `0.0` if either mass or either conductivity is non-positive
(silent guard so this can be folded into a per-pair sweep without
defensive branches at every call site). The clamp `q_eq = (t_a − t_b) ·
m_eff` caps the flux at the equalisation point so the explicit scheme
cannot oscillate.

**Complexity**: O(1).

#### Example

```python
from slappyengine.thermal import exchange_two_regions

# Two contacting cells, asymmetric mass + conductivity.
q = exchange_two_regions(t_a=400.0, m_a=1.0, k_a=2.0,
                         t_b=20.0,  m_b=4.0, k_b=0.5, dt=0.05)
t_a_new = 400.0 - q / 1.0
t_b_new = 20.0  + q / 4.0
assert t_a_new > t_b_new                # cannot overshoot equalisation
assert t_a_new * 1.0 + t_b_new * 4.0 == 400.0 + 20.0 * 4.0
```

## Consumer tests

- `tests/test_hardening_thermal.py` — input-validation matrix for
  `HeatField.__init__`, `.step`, and `.exchange_with`.
- `tests/test_thermal_physics.py` — physical correctness: per-grid
  conservation under both boundary modes, equalisation under repeated
  exchange, the CFL-cap substep auto-selector.
- `tests/test_demo_hello_thermal.py` — smoke test wrapping
  `examples/hello_thermal.py`.

## Future consumer

The fluid module's planned C4 thermal pass (future
`python/slappyengine/fluid/thermal_step.py`, WIP) will call
`HeatField.step` rather than re-deriving the formula, and will use
`HeatField.exchange_with` to couple the SPH/PBF particle thermal field
to the surrounding solid-cell grid. Until that pass lands the only
in-tree consumer is `examples/hello_thermal.py`.

## References

- Strikwerda, J. C. *Finite Difference Schemes and Partial Differential
  Equations*, SIAM (2nd ed., 2004), §6 — stability bound for the
  explicit 5-point Laplacian.
- Briggs, W. L., Henson, V. E., McCormick, S. F. *A Multigrid Tutorial*,
  SIAM (2nd ed., 2000), §2 — Jacobi/Gauss-Seidel CFL bound for the
  5-point Laplacian.

## Inner modules

- `slappyengine.thermal._validation` — internal O(1) numeric checks
  (`validate_diffusivity` encodes the `(0, 1]` stability range).
