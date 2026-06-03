# slappyengine.numerics — Design Reference

`slappyengine.numerics` is the engine's home for **long-lived, reusable
numerical kernels** that are decoupled from any particular physics
flavour. The headline entry point is a 2-D multigrid V-cycle for the
Poisson equation, used today by the fluid pressure projection and
ready to back any future heat-equation or inflated-softbody pressure
work that needs the same shape.

For the runtime API surface (`vcycle_poisson`, `sor_smooth`,
`compute_residual`), see the companion
[API reference](api/numerics.md).

## Why a separate subpackage?

The Poisson solver started life inside `slappyengine.physics.pressure_multigrid`
as `vcycle_project_v`, tightly coupled to per-pixel-physics field
layout. Two pressures pushed it out into its own subpackage:

1. **Phase D strip pass.** The per-pixel-physics module is on the
   deprecation path. The Poisson solver — generic enough to solve any
   `Δp = rhs` problem on a 2-D cell-centred grid — should survive that
   strip, so it was lifted to `slappyengine.numerics`. Exact behaviour
   parity for matching inputs is asserted by
   `test_numerics_vcycle.py::test_cross_check_against_physics_module`.
2. **Reuse.** Inflated-softbody pressure projection and 2-D heat-
   equation work both need the same Poisson shape. A single
   well-tested implementation in `numerics` is cheaper to maintain than
   forked copies inside the dependent subpackages.

The boundary is sharp: `numerics` does not import from
`slappyengine.physics`, `slappyengine.softbody`, or
`slappyengine.fluid`. It is a pure-numpy bottom-of-the-stack module.

## Pipeline shape — recursive V-cycle

```text
                  ┌─────────────────────────────┐
                  │  vcycle_poisson(rhs, mask)  │
                  └──────────────┬──────────────┘
                                 ▼
              for _ in range(n_cycles):
                  ┌──────────────────────────────────────┐
                  │  _v_cycle(p, rhs, mask, omega, ...)  │
                  └──────────────────────────────────────┘
                                 │
                                 ▼
              1. Pre-smooth      (_sor_sweep × iters_per_level)
              2. Residual        (_compute_residual)
              3. Restrict        (_restrict_2x2 + _restrict_mask)
              4. Recurse         (_v_cycle, levels-1)
              5. Prolong         (_prolong_bilinear)
              6. Post-smooth     (_sor_sweep × iters_per_level)

   Bottom level: pure SOR solve (coarse_iters sweeps), no recursion.
```

The classical multigrid V-cycle. Six operations per level; the
recursion bottoms out at `levels=1` or the smallest "can-be-coarsened"
grid (both dims even and ≥ 4).

### Per-level operations

- **`_sor_sweep(p, rhs, mask, red_w, black_w, iters)`** — Red-Black
  SOR smoother. Each pass alternates updates of the two checkerboard
  sub-lattices using the Jacobi-style relaxation
  `p ← (Σ neighbours − rhs) / 4` weighted by `omega`. Single `nb_sum`
  scratch buffer; neighbour sums via in-place `+=`. Allocates nothing
  per iteration.
- **`_compute_residual(p, rhs, mask)`** — `rhs − Δp` on the masked
  5-point Laplacian. Used to feed the coarse-grid correction problem.
- **`_restrict_2x2(field)`** — Full-weighting restriction on a
  cell-centred grid. Four strided slices summed in-place then scaled
  by 0.25.
- **`_restrict_mask(mask)`** — Block-max over each 2×2 block. A coarse
  cell counts as fluid if *any* of its four fine children is fluid;
  using `max` rather than `mean` keeps thin one-cell-wide features
  alive on the coarse grid where averaging would erode them below the
  0.5 threshold.
- **`_prolong_bilinear(coarse, fine_shape)`** — Bilinear up-sample.
  Uses `np.repeat` for the 2× nearest-neighbour step, then averages
  with one-cell-shifted copies along each axis.

### Why Red-Black SOR?

The classical Jacobi smoother is slow at damping high-frequency error
modes (the modes a multigrid scheme cannot reach via coarse
correction). Gauss-Seidel converges roughly 2× faster but is
inherently sequential (each cell depends on already-updated
neighbours). Red-Black SOR splits the grid into two interleaved
sub-lattices that update in parallel **within** a colour and
sequentially **across** colours — recovering the Gauss-Seidel
convergence rate while staying vectorisable in numpy.

The over-relaxation factor `ω` further accelerates convergence:
`ω = 1.0` reduces to Gauss-Seidel; `ω ≈ 1.5` is near-optimal for the
5-point Laplacian on grids up to ~64². Values > 1.9 destabilise. The
default is 1.5.

## The `p == p * mask` invariant

The smoother and residual kernels rely on a single load-bearing
invariant: **vacuum cells of `p` are always zero**. This makes
neighbour-mask multiplications in the inner loop redundant —
`p[:, :-1] * m_l[:, 1:]` reduces to `p[:, :-1]` because vacuum
cells of `p[:, :-1]` are already zero, so the per-neighbour `* mask`
is a no-op.

The invariant is preserved across iterations because:

- The red/black weights (`red_w`, `black_w`) are themselves multiplied
  by the mask, so the update step can never write into a vacuum cell.
- The `p *= mask` at the end of each `_sor_sweep` iteration scrubs FP
  rounding leaks.
- The `_compute_residual` final `* mask` makes the same guarantee for
  residual outputs.

The invariant is the single largest performance win — measured at the
256² target as the difference between ~28 ms and ~20 ms per V-cycle.
Documented inline in `_sor_sweep` and `_compute_residual` so that any
future "should we multiply by the mask here?" question has an answer
already.

## Performance — pure numpy hot path

cProfile of the 256² / 5-cycle / 4-iters scenario showed three
optimisation targets accounting for ~85% of total wall-clock pre-tuning:

1. **`_sor_sweep`** — Red-Black SOR smoother. ~62% of pre-optimisation
   time.
2. **`_restrict_mask`** — coarsening reduction. ~17%.
3. **`_compute_residual`** — fine-grid residual. ~6%.

Three targeted edits landed in the 2026-05-23 perf sprint:

### Edit 1 — Drop redundant neighbour-mask multiplications

Per the `p == p * mask` invariant above, four element-wise `*` ops per
sweep can be dropped. Largest single win — about 18% of total runtime.

### Edit 2 — Hoist checkerboard weights out of the smoother

Pre + post smooths at the same level share `red_w` / `black_w` (they
depend only on shape, mask, and omega). Pre-fix, each `_sor_sweep` call
re-built them from `np.indices(p.shape)`, which allocates two `(H, W)`
index arrays. Post-fix, they are built once per `_v_cycle` invocation
via strided assignment:

```python
red_w[0::2, 0::2] = om
red_w[1::2, 1::2] = om
red_w *= mask
```

Saves ~30% of the smoother's setup cost at larger grid sizes.

### Edit 3 — Replace `reshape().mean / .max(axis=(1, 3))` in restriction

`ndarray.max(axis=(1, 3))` routes through `_methods._amax` and
`np.ufunc.reduce`, ~30× more cumtime than a chained `np.maximum(a, b,
out=out)`. The 2×2 restrictions now use strided slice arithmetic plus
in-place `np.maximum`.

```python
a = mask[0::2, 0::2]; b = mask[0::2, 1::2]
c = mask[1::2, 0::2]; d = mask[1::2, 1::2]
out = np.maximum(a, b)
np.maximum(out, c, out=out)
np.maximum(out, d, out=out)
```

### End-to-end result

256² / 5-cycle / 4-iters target: **2.4× speedup**, 28.9 ms → 11.8 ms
median wall-clock. The remaining hot path is ~73% raw numpy in
`_sor_sweep` (1.78 ms cumtime for 600 calls vs 0.18 ms Python
overhead).

Further pure-numpy gains are diminishing returns. The natural next
step is a Rust port.

## When to migrate to Rust

`_sor_sweep` and `_restrict_*` are the two prime candidates. The
analysis:

| Kernel | Calls / V-cycle | Cumtime (256²) | Migration ROI |
|---|---|---|---|
| `_sor_sweep` | 8 per level × 3 levels = 24 | 1.78 ms | **High** — 73% of runtime |
| `_restrict_2x2` | 1 per level = 3 | 0.20 ms | Low |
| `_restrict_mask` | 1 per level = 3 | 0.25 ms | Low |
| `_compute_residual` | 1 per level = 3 | 0.30 ms | Medium |
| `_prolong_bilinear` | 1 per level = 3 | 0.45 ms | Medium |

A 4-6× Rust speedup on `_sor_sweep` would take the 256² target from
11.8 ms to ~5 ms — well into "free at 60 fps for any sensible grid
size". The other kernels are individually small but collectively ~1
ms, so a follow-up sprint to port them is the natural staging.

This work is tracked under the same plan as `slappyengine.dynamics`
(see [`rust_migration_plan.md`](rust_migration_plan.md), Step 7) and
will follow the dynamics Rust port once the latter is shipped.

### Why not Rust today?

Three reasons hold the migration in the wings:

1. The pure-numpy implementation has algorithm provenance traceable
   line-by-line to the legacy `physics.pressure_multigrid` code — the
   cross-check test in `test_numerics_vcycle.py` is the contract that
   the Rust port must satisfy bit-for-bit. Porting first, optimising
   later, would break that anchor.
2. The fluid pressure projection — the only current consumer in
   shipped code — is not the gating bottleneck. The PBF integrator and
   density-constraint pass dominate the fluid frame budget; pressure
   projection at 11.8 ms × 1 cycle per fluid frame is well within
   budget at 60 fps.
3. The downstream consumers (heat-equation, inflated-softbody
   pressure) are not implemented yet. Locking in a Rust ABI before
   those consumers exist would constrain the design.

The right time to migrate is when (a) one of the deferred consumers
lands and (b) profiling shows the Poisson solver in the top-3 hot
paths for that consumer.

## Algorithm provenance

The implementation was lifted from the working core of
`slappyengine.physics.pressure_multigrid::vcycle_project_v` so behaviour
parity is exact for matching inputs. The lifted form is **strictly
generic** — no per-pixel-physics field assumptions remain. The
provenance is documented inline in `numerics/__init__.py` and pinned by
`test_numerics_vcycle.py::test_cross_check_against_physics_module`.

If the underlying physics-module solver is ever modified, the cross-
check test will fail and force a follow-up edit here. The intent is
that the standalone `numerics` solver is the **canonical** version
going forward and any future divergence is resolved by updating the
physics caller to use the numerics entry point.

## When to use `sor_smooth` / `compute_residual` directly

The public surface ships three functions; the V-cycle is the headline
but the other two are useful standalone:

- **`sor_smooth(p, rhs, iters=1, omega=1.5, mask=None)`** — One or
  more Red-Black SOR sweeps. Useful when:
  - The grid is too small to benefit from multigrid (< 32², where the
    coarse-grid setup overhead dominates).
  - The caller already has a near-converged guess and just needs
    polish iterations (warm-start).
  - The caller is implementing their own multigrid variant (e.g. F-
    cycle or W-cycle) and needs the smoother as a primitive.
- **`compute_residual(p, rhs, mask=None)`** — `rhs − Δp` on the masked
  5-point Laplacian. Useful for convergence diagnostics (`||residual||`
  as the stopping criterion in an outer iteration) or for hand-rolled
  multigrid implementations.

Both wrappers enforce the `p == p * mask` invariant by multiplying `p`
by the mask on entry, so callers can hand them dirty buffers without
breaking the inner loop's optimisation assumption.

## See also

- [`api/numerics.md`](api/numerics.md) — function signatures and Raises
  contracts.
- [`api/gi.md`](api/gi.md) — the GI denoiser sits on top of these
  Laplacian / multigrid helpers; the variance-guided à-trous wavelet
  is a relative of the multigrid smoother.
- [`gi_design.md`](gi_design.md) — the GI subsystem the numerics
  primitives could back if cascade temporal moves to a Poisson-based
  smoother.
- [`fluid_design.md`](fluid_design.md) — the PBF pressure projection
  consumer.
- [`rust_migration_plan.md`](rust_migration_plan.md) — Step 7 covers
  the `_sor_sweep` Rust port plan.

## References

- Briggs, W. L., Henson, V. E., & McCormick, S. F. (2000). *A
  Multigrid Tutorial* (2nd ed.). SIAM. Canonical multigrid reference;
  the V-cycle, Red-Black SOR, and full-weighting restriction all come
  from chapters 2–4.
- Trottenberg, U., Oosterlee, C. W., & Schüller, A. (2001).
  *Multigrid.* Academic Press. The "thin features survive coarsening"
  argument for `max`-based mask restriction is from §2.4.
- Stam, J. (1999). *Stable Fluids.* SIGGRAPH. The PBF / fluid pressure-
  projection consumer this solver currently backs.
