# slappyengine.numerics — API Reference

> Hand-written reference. The auto-generator at
> `scripts/gen_subpackage_api_docs.py` skips this file because the public
> surface here is small, stable, and benefits from worked examples and
> complexity notes that introspection cannot synthesise.

`slappyengine.numerics` is the engine's home for generic numerical
kernels — solver / smoother / transfer primitives that are reusable
across physics flavours rather than tied to any one of them. Today the
package ships a single end-to-end solver (a 2-D multigrid V-cycle for
the Poisson equation `Δp = rhs` on a cell-centred grid with a binary
fluid/vacuum mask) plus its two underlying building blocks (a
Red-Black SOR smoother and a 5-point residual evaluator). The kernel
was lifted out of the old `slappyengine.physics.pressure_multigrid`
module during the Phase B repackage (see
`memory/project_phase_b_repackage.md`) so it can survive the Phase D
strip pass and serve as the canonical Poisson solver going forward.
Pure numpy — no scipy, no Rust, no GPU. The roadmap is to (a) port
`_sor_sweep` + `_restrict_*` to Rust under the same plan that landed
`slappyengine.dynamics`, and (b) grow companions for the heat
equation and divergence-cleaning passes that today live elsewhere.

## Functions

### `vcycle_poisson`

```python
vcycle_poisson(
    rhs: np.ndarray,
    mask: np.ndarray | None = None,
    iters_per_level: int = 2,
    levels: int = 3,
    *,
    n_cycles: int = 1,
    omega: float = 1.5,
    coarse_iters: int = 8,
    initial: np.ndarray | None = None,
    smooth_pre: int | None = None,
    smooth_post: int | None = None,
) -> np.ndarray
```

_defined in `slappyengine.numerics`_

Solve the discrete 2-D Poisson equation `Δp = rhs` with `n_cycles`
recursive multigrid V-cycles on a cell-centred grid. Each cycle
pre-smooths with Red-Black SOR, restricts the residual to a 2×-coarser
grid, recurses on the coarse correction problem, prolongs the
correction back via bilinear up-sampling, and post-smooths. The
operator is the standard 5-point stencil `Δp[i,j] = p_l + p_r + p_t +
p_b − 4·p[i,j]` restricted to live cells; vacuum cells contribute
nothing to neighbour sums and are clamped to zero before return.

#### Parameters

- `rhs : (H, W) ndarray` — Right-hand side. Values in vacuum cells are
  ignored (masked out before the first sweep) so callers don't have to
  zero them.
- `mask : (H, W) bool or float, optional` — Live-cell mask. Truthy ≥
  0.5 → fluid; else vacuum. Defaults to all-fluid.
- `iters_per_level : int, default 2` — Red-Black SOR sweeps before AND
  after the recursive correction at each level.
- `levels : int, default 3` — Maximum coarsening depth. Coarsening
  also stops automatically when the grid becomes too small (< 4
  cells) or odd in either dimension.
- `n_cycles : int, keyword-only, default 1` — Number of V-cycles. 2-3
  cycles are usually plenty; each cycle roughly halves the residual on
  the long-wavelength modes.
- `omega : float, keyword-only, default 1.5` — SOR over-relaxation
  factor; must lie in `(0, 2)`. `1.0` reduces to Gauss-Seidel.
- `coarse_iters : int, keyword-only, default 8` — SOR sweeps at the
  bottom of the V (where coarsening stopped).
- `initial : (H, W) ndarray, keyword-only, optional` — Warm-start
  guess. Defaults to zero; pass a previous solution to converge
  faster on tightly correlated frames.
- `smooth_pre`, `smooth_post : int, keyword-only, optional` —
  Back-compat shims for the legacy
  `slappyengine.physics.pressure_multigrid` call signature; both fold
  into `iters_per_level` via `max(...)`.

#### Returns

- `p : (H, W) float32` — Approximate solution. Vacuum cells are
  exactly zero; NaN / ±inf are scrubbed.

#### Raises

- `TypeError` — If `rhs` is not a 2-D numpy ndarray, or `mask` /
  `initial` are non-ndarray when provided, or `iters_per_level` /
  `levels` / `n_cycles` are not integers, or `omega` is not a real
  number.
- `ValueError` — If `rhs` is not 2-D, `mask` / `initial` shapes do not
  match `rhs`, the iteration counters are `< 1`, or `omega` is
  non-finite or outside `(0, 2)`.

#### Complexity

`O(N · n_cycles)` work and `O(N)` peak memory for a grid of `N = H·W`
cells. The geometric (`1 + 1/4 + 1/16 + …`) work tail across coarsened
levels keeps the constant under `4/3` of one fine-grid sweep — the
defining advantage of multigrid over flat SOR, which scales as
`O(N^1.5)` on the same problem.

#### Example

```python
import numpy as np
from slappyengine.numerics import vcycle_poisson

n = 64
yy, xx = np.indices((n, n), dtype=np.float32)
rhs = np.exp(-((xx - 32) ** 2 + (yy - 32) ** 2) / 32.0).astype(np.float32)
mask = ((xx - 32) ** 2 + (yy - 32) ** 2 <= 28 ** 2).astype(np.float32)
p = vcycle_poisson(rhs, mask, iters_per_level=2, levels=3, n_cycles=5)
print(float(np.abs(p).max()), float(p[~mask.astype(bool)].max()))
```

### `sor_smooth`

```python
sor_smooth(
    p: np.ndarray,
    rhs: np.ndarray,
    iters: int = 1,
    omega: float = 1.5,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray
```

_defined in `slappyengine.numerics`_

Run `iters` full Red-Black SOR sweeps on `Δp = rhs`. Each sweep
updates the "red" sub-lattice (`(i+j) % 2 == 0`) using the current
"black" values, then the "black" sub-lattice using the freshly updated
red values, with relaxation factor `omega`. Vacuum cells are
guaranteed zero throughout via the invariant `p == p · mask` so the
inner loop allocates a single scratch buffer and no per-iter
temporaries.

#### Parameters

- `p : (H, W) ndarray` — Current solution estimate. Mutated and
  returned so calls can be chained.
- `rhs : (H, W) ndarray` — Right-hand side; must match `p` in shape.
- `iters : int, default 1` — Number of full Red-Black sweeps. `≥ 1`.
- `omega : float, default 1.5` — Over-relaxation factor in `(0, 2)`.
- `mask : (H, W) ndarray, keyword-only, optional` — Live-cell mask;
  defaults to all-ones.

#### Returns

- `p : (H, W) float32` — The mutated solution buffer.

#### Raises

- `TypeError` — If `p` or `rhs` is not a numpy ndarray, `iters` is not
  an integer, or `omega` is not a real number.
- `ValueError` — If shapes mismatch, `iters < 1`, or `omega` is
  outside `(0, 2)`.

#### Complexity

`O(iters · N)` work, `O(N)` peak memory. Each sweep is two strided
neighbour gathers + an in-place update; effective error damping per
sweep is bounded above by `1 − 2π² / N` on the smooth-mode spectrum,
which is precisely why a standalone SOR loop needs `O(N^0.5)` sweeps
to converge and why `vcycle_poisson` wraps this smoother inside a
multigrid hierarchy instead.

#### Example

```python
import numpy as np
from slappyengine.numerics import sor_smooth

p = np.zeros((32, 32), dtype=np.float32)
rhs = np.zeros((32, 32), dtype=np.float32)
rhs[16, 16] = 1.0
sor_smooth(p, rhs, iters=20, omega=1.5)
print(float(p[16, 16]), float(p.min()))
```

### `compute_residual`

```python
compute_residual(
    p: np.ndarray,
    rhs: np.ndarray,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray
```

_defined in `slappyengine.numerics`_

Return `rhs − Δp` on the masked 5-point Laplacian. The residual is
exactly the quantity a V-cycle restricts to the coarse grid and the
natural convergence diagnostic for callers that want to monitor
`||r||_2` between cycles.

#### Parameters

- `p : (H, W) ndarray` — Current solution estimate.
- `rhs : (H, W) ndarray` — Right-hand side; must match `p` in shape.
- `mask : (H, W) ndarray, keyword-only, optional` — Live-cell mask;
  defaults to all-ones.

#### Returns

- `residual : (H, W) float32` — Pointwise residual. Zero outside the
  live mask.

#### Raises

- `TypeError` — If `p` or `rhs` is not a numpy ndarray.
- `ValueError` — If `p` is not 2-D, or `rhs` / `mask` shapes do not
  match `p`.

#### Complexity

`O(N)` work, `O(N)` peak memory — four strided neighbour adds + one
fused multiply-subtract, no Python-level loops.

#### Example

```python
import numpy as np
from slappyengine.numerics import vcycle_poisson, compute_residual

rhs = np.zeros((32, 32), dtype=np.float32)
rhs[16, 16] = 1.0
p = vcycle_poisson(rhs, iters_per_level=2, levels=3, n_cycles=3)
r = compute_residual(p, rhs)
print(float(np.linalg.norm(r)))
```

## Algorithm provenance

The V-cycle implementation is the standard recursive multigrid
algorithm as taught in Briggs, Henson & McCormick — *A Multigrid
Tutorial*, 2nd ed., SIAM 2000 — and Trottenberg, Oosterlee & Schüller
— *Multigrid*, Academic Press 2001. The Red-Black smoothing pass and
2× full-weighting restriction follow §3 and §10 of Briggs; the
4× RHS scaling on the coarse correction problem accounts for the
doubled grid spacing `h → 2h` and the `1/h²` normalisation absorbed
into `rhs` (Trottenberg §2.4). The masked variant — coarsening the
mask via `max` rather than `mean` to preserve thin one-cell features
— is engine-specific and originates in the legacy
`slappyengine.physics.pressure_multigrid.vcycle_project_v` routine
this module replaces.

## Performance

The 64² / 5-cycle / 4-iters-per-level scenario lands at ~3 ms median
wall time on the dev box after the Phase B optimisations (drop
redundant neighbour-mask multiplications, hoist checkerboard weights
into `_v_cycle`, replace `reshape().mean / .max` in the restrictions
with strided slice arithmetic). The end-to-end speedup from the
pre-optimisation 256² / 5-cycle / 4-iters baseline was 2.4× (28.9 ms →
11.8 ms median). The CI tripwire at
[`tests/test_numerics_perf.py`](../../tests/test_numerics_perf.py)
asserts a 50 ms ceiling so a 2× Python-level regression in the hot
path fails the build. For the latest cross-package figures see
[`benchmarks/baseline_report.md`](../../benchmarks/baseline_report.md);
the in-package micro-bench harness is at `tools/bench_numerics.py`.

## See also

- `slappyengine.thermal.HeatField` — 2-D temperature grid stepped by
  explicit Euler. Today it does not share kernel code with
  `vcycle_poisson` (the heat equation is solved explicitly rather than
  by Poisson projection), but the planned implicit-step path will
  reuse `vcycle_poisson` directly via the same masked 5-point
  Laplacian operator.
- `slappyengine.dynamics` — XPBD substrate that consumes the
  multigrid Poisson solver inside its inflated-softbody pressure
  projection pass.
- [`examples/hello_numerics.py`](../../examples/hello_numerics.py) —
  3-panel demo: Gaussian source → multigrid solve → residual.
