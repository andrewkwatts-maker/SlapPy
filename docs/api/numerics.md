<!-- handauthored: do not regenerate -->
# slappyengine.numerics — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


Generic numerical primitives.

## Classes

_(none)_

## Functions

### `compute_residual(p: 'np.ndarray', rhs: 'np.ndarray', *, mask: 'np.ndarray | None' = None) -> 'np.ndarray'`

_defined in `slappyengine.numerics`_

Return ``rhs − Δp`` on the masked 5-point Laplacian.

#### Raises

- `TypeError` — If ``p`` or ``rhs`` is not a numpy ndarray.
- `ValueError` — If ``p`` is not 2-D, or ``rhs`` / ``mask`` shapes do not match ``p``.

### `sor_smooth(p: 'np.ndarray', rhs: 'np.ndarray', iters: 'int' = 1, omega: 'float' = 1.5, *, mask: 'np.ndarray | None' = None) -> 'np.ndarray'`

_defined in `slappyengine.numerics`_

Run ``iters`` Red-Black SOR sweeps on ``Δp = rhs``.

#### Raises

- `TypeError` — If ``p`` or ``rhs`` is not a numpy ndarray, or ``iters`` is not an integer, or ``omega`` is not a real number.
- `ValueError` — If shapes mismatch, ``iters < 1``, or ``omega`` is outside ``(0, 2)``.

### `vcycle_poisson(rhs: 'np.ndarray', mask: 'np.ndarray | None' = None, iters_per_level: 'int' = 2, levels: 'int' = 3, *, n_cycles: 'int' = 1, omega: 'float' = 1.5, coarse_iters: 'int' = 8, initial: 'np.ndarray | None' = None, smooth_pre: 'int | None' = None, smooth_post: 'int | None' = None) -> 'np.ndarray'`

_defined in `slappyengine.numerics`_

Solve ``Δp = rhs`` with ``n_cycles`` multigrid V-cycles.

#### Raises

- `TypeError` — If ``rhs`` is not a 2-D numpy ndarray, or ``mask`` / ``initial`` are non-ndarray when provided, or ``iters_per_level`` / ``levels`` / ``n_cycles`` are not integers, or ``omega`` is not a real number.
- `ValueError` — If ``rhs`` is not 2-D, ``mask`` / ``initial`` shapes do not match ``rhs``, the iteration counters are < 1, or ``omega`` is non-finite or outside ``(0, 2)``.

## Constants

_(none)_

## Inner modules

_(none)_
