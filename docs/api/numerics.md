<!-- handauthored: do not regenerate -->
# pharos_engine.numerics — API Reference

> Hand-written reference for the SS7 pass on the Pharos Engine numerical
> primitives. Owns the 2-D multigrid V-cycle Poisson solver, the
> Red-Black SOR smoother, and the masked 5-point Laplacian residual —
> nothing else. Sibling references: [`topology.md`](topology.md) is the
> paired graph-primitive subpackage;
> [`../numerics_design.md`](../numerics_design.md) is the design doc
> with the full performance audit, `p == p * mask` invariant, and
> Rust-migration story.

## Overview

`pharos_engine.numerics` was extracted from
`pharos_engine.physics.pressure_multigrid` during Phase B so long-lived
numerical kernels have a clean home decoupled from any particular
physics flavour. Today it ships a single class of solver — 2-D
multigrid Poisson on a regular cell-centred grid with a binary
fluid / vacuum mask — that will eventually back inflated-softbody
pressure projection and any future heat-equation work.

The public surface is three free functions:

* :func:`vcycle_poisson` — the batteries-included entry point. Runs
  `n_cycles` full multigrid V-cycles (pre-smooth → restrict residual →
  recurse → prolong correction → post-smooth) and returns a `float32`
  solution guaranteed to be zero outside the live mask and free of
  NaN / ±inf.
* :func:`sor_smooth` — the Red-Black SOR smoother without the V-cycle
  wrapping. Useful when a caller already has a residual + correction
  loop and only wants the smoothing kernel.
* :func:`compute_residual` — the masked 5-point Laplacian residual
  (`rhs − Δp`) as a free function, for callers that want to measure
  convergence or drive their own multigrid.

The implementation is pure numpy — **no** scipy, **no** GPU, **no**
Rust — and intentionally self-contained (does not import from
`pharos_engine.physics`) so it survives Phase D's strip pass and serves
as the canonical Poisson solver going forward.

**Load-bearing invariant.** All three entry points assume
`p == p * mask` on entry and preserve it on exit. Vacuum cells of the
solution are exactly zero, so the inner kernels drop the redundant
per-neighbour mask multiplications for a measurable smoother speedup
(see [`../numerics_design.md`](../numerics_design.md) for the audit).

## Public surface

```python
from pharos_engine.numerics import (
    compute_residual,
    sor_smooth,
    vcycle_poisson,
)
```

## Functions

### `vcycle_poisson(rhs, mask=None, iters_per_level=2, levels=3, *, n_cycles=1, omega=1.5, coarse_iters=8, initial=None, smooth_pre=None, smooth_post=None) -> np.ndarray`

_defined in `pharos_engine.numerics`_

Solve `Δp = rhs` with `n_cycles` multigrid V-cycles on a cell-centred
grid.

| Argument | Type | Default | Notes |
|----------|------|---------|-------|
| `rhs` | `np.ndarray` `(H, W)` | — | Right-hand side; vacuum cells zeroed automatically. |
| `mask` | `np.ndarray` `(H, W)`, bool or float, optional | `None` | Live-cell mask. Truthy ≥ 0.5 → fluid. `None` = all-ones. |
| `iters_per_level` | `int` | `2` | Red-Black SOR sweeps before AND after correction at each level. |
| `levels` | `int` | `3` | Max coarsening depth. Stops early on grids < 4 cells or odd dims. |
| `n_cycles` | `int`, kw-only | `1` | Number of V-cycles. 2-3 usually plenty. |
| `omega` | `float`, kw-only | `1.5` | SOR over-relaxation. Must be in `(0, 2)`. |
| `coarse_iters` | `int`, kw-only | `8` | SOR sweeps at the bottom of the V. |
| `initial` | `np.ndarray` `(H, W)` or `None`, kw-only | `None` | Optional warm-start guess. |
| `smooth_pre` / `smooth_post` | `int` or `None`, kw-only | `None` | Back-compat aliases; taken via `max()` into `iters_per_level`. |

Returns `float32` `(H, W)` with vacuum cells exactly zero and
NaN / ±inf scrubbed to zero (so the field is safe to persist across
frames).

**Raises:**

- `TypeError` — `rhs` is not a 2-D numpy ndarray, `mask` / `initial`
  are non-ndarray when provided, `iters_per_level` / `levels` /
  `n_cycles` are not integers, or `omega` is not a real number.
- `ValueError` — `rhs` is not 2-D, `mask` / `initial` shapes do not
  match `rhs`, iteration counters are `< 1`, or `omega` is non-finite
  or outside `(0, 2)`.

### `sor_smooth(p, rhs, iters=1, omega=1.5, *, mask=None) -> np.ndarray`

_defined in `pharos_engine.numerics`_

Run `iters` full Red-Black SOR sweeps on `Δp = rhs`. Public wrapper
around the internal `_sor_sweep`. Returns the mutated buffer as
`float32` so calls can be chained. Enforces the
`p == p * mask` invariant on entry.

**Raises:**

- `TypeError` — `p` or `rhs` is not a numpy ndarray, `iters` is not an
  integer, or `omega` is not a real number.
- `ValueError` — shapes mismatch, `iters < 1`, or `omega` is outside
  `(0, 2)`.

### `compute_residual(p, rhs, *, mask=None) -> np.ndarray`

_defined in `pharos_engine.numerics`_

Return `rhs − Δp` on the masked 5-point Laplacian. Public wrapper
around the internal `_compute_residual`. Returns a `float32` array;
zero outside the live mask.

**Raises:**

- `TypeError` — `p` or `rhs` is not a numpy ndarray.
- `ValueError` — `p` is not 2-D, or `rhs` / `mask` shapes do not match
  `p`.

## Usage

```python
import numpy as np
from pharos_engine.numerics import (
    compute_residual, sor_smooth, vcycle_poisson,
)

# 32x32 unit-density source, all-fluid mask.
H = W = 32
rhs = np.zeros((H, W), dtype=np.float32)
rhs[H // 2, W // 2] = 1.0
mask = np.ones((H, W), dtype=np.float32)

# One-shot multigrid solve.
p = vcycle_poisson(rhs, mask, n_cycles=2)
assert p.shape == (H, W)
assert p.dtype == np.float32
assert np.isfinite(p).all()

# Manual loop: alternate smoothing + residual measurement.
p2 = np.zeros_like(rhs)
for _ in range(4):
    p2 = sor_smooth(p2, rhs, iters=2, omega=1.5, mask=mask)
    res = compute_residual(p2, rhs, mask=mask)
    if float(np.abs(res).max()) < 1e-4:
        break

# Vacuum cells are exactly zero — safe to persist across frames.
mask_partial = mask.copy()
mask_partial[:4, :] = 0.0  # top four rows are vacuum
p3 = vcycle_poisson(rhs, mask_partial)
assert (p3[:4, :] == 0.0).all()
```

## Skip the wrapper

`pharos_engine.numerics` is pure numpy today. Grep of
`pharos_engine._core_facade.RUST_MODULE_MAP` shows **no** `numerics`
entry — the hot path is currently the Red-Black SOR smoother
(`_sor_sweep`), which is ~62% of wall-clock at 256² per the perf audit
in [`../numerics_design.md`](../numerics_design.md).

A Rust port of `_sor_sweep` + `_restrict_2x2` / `_restrict_mask` is on
the roadmap under
[`../rust_migration_plan.md`](../rust_migration_plan.md) Step 7 and
would yield an estimated 3-5x smoother speedup. Until it lands, the
subpackage stays pure numpy so it survives Phase D's strip pass with
no compiled dependency.

Callers who already own a lower-level Poisson solver (AMGCL, PETSc,
CUDA) can bypass :func:`vcycle_poisson` entirely and reuse
:func:`sor_smooth` / :func:`compute_residual` as building blocks — they
are stateless numpy kernels with no hidden state or lazy imports.

## Conventions

- **Cell-centred grid.** All three functions assume a uniform
  cell-centred 2-D grid. Off-grid neighbour contributions in the
  5-point stencil implicitly zero via slice geometry — no ghost
  cells, no explicit boundary parameter.
- **`p == p * mask` invariant.** Vacuum cells of the solution are
  always zero. The inner kernels rely on this to drop redundant
  neighbour-mask multiplications; the public wrappers re-enforce it on
  entry (`p32 *= mask_f`) so hostile inputs cannot break the invariant.
- **`float32` throughout.** All internal buffers are `float32`. Inputs
  in wider dtypes are converted via `np.asarray(..., dtype=np.float32)`
  on entry. Return arrays are always `float32`.
- **`omega` band.** SOR over-relaxation is clamped to `(0, 2)`. `1.5`
  is near-optimal for the 5-point Laplacian on grids up to ~64²;
  values > 1.9 destabilise.

## See also

- [`topology.md`](topology.md) — sibling generic-primitive subpackage
  (connected components / union-find).
- [`../numerics_design.md`](../numerics_design.md) — full design doc:
  multigrid V-cycle architecture, Red-Black SOR audit,
  `p == p * mask` invariant, the 2.4x speedup edits, Rust-migration
  Step 7 plan.
- [`gi.md`](gi.md) — the GI denoiser sits on top of the Laplacian /
  multigrid helpers exposed here.
- [`../rust_migration_plan.md`](../rust_migration_plan.md) — Step 7
  covers the `_sor_sweep` Rust port plan and its estimated speedup.
