<!-- handauthored: do not regenerate -->
# slappyengine.thermal — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


## Overview

Heat diffusion + pairwise heat exchange — Phase B public surface.

## Classes

### `HeatField`

_class — defined in `slappyengine.thermal`_

A 2D temperature grid with explicit pairwise-flux diffusion.

#### Constructor signature

```python
HeatField(grid: 'np.ndarray', conductivity: 'float' = 1.0, diffusivity: 'float' = 0.1) -> 'None'
```

#### Methods

- `exchange_with(self, other: "'HeatField'", contact_pairs: 'Iterable[Tuple[Tuple[int, int], Tuple[int, int]]]', dt: 'float' = 1.0, *, conductivity: 'float | None' = None) -> 'float'` — Conservatively exchange heat with ``other`` across contact pairs.
- `step(self, dt: 'float', *, boundary: 'str' = 'periodic', substeps: 'int | None' = None) -> 'None'` — Advance the temperature field by ``dt`` via pairwise diffusion.
- `total_heat(self) -> 'float'` — Sum of cell temperatures — conservation-check hook for tests.

#### Raises

- `TypeError` — If ``grid`` is not a 2-D float numpy ndarray, or if ``conductivity`` / ``diffusivity`` are not real numbers.
- `ValueError` — If ``grid`` is smaller than 2x2, ``conductivity`` is negative, or ``diffusivity`` falls outside ``(0, 1]``.

## Functions

### `exchange_two_regions(t_a: 'float', m_a: 'float', k_a: 'float', t_b: 'float', m_b: 'float', k_b: 'float', dt: 'float') -> 'float'`

_defined in `slappyengine.thermal`_

Conservative Newton's-law heat flux between two mass-weighted regions.

## Constants

_(none)_

## Inner modules

_(none)_

## Design notes

The thermal subpackage surface is small (one `HeatField` class plus a
two-region exchange helper); no separate `thermal_design.md` ships.
The pairwise-flux explicit diffusion conventions, mass-weighted
exchange formula, and conservation-check `total_heat()` hook are
documented inline above plus in the source docstrings.

If a future sprint adds anisotropic conductivity, implicit time
stepping, or 3-D fields, promote that material to a dedicated
`thermal_design.md` and link both ways.

## See also

- [`zones.md`](zones.md) — thermal zones plug into the rect / threshold
  zone bookkeeping.
- [`../zones_design.md`](../zones_design.md) — the canonical design
  reference for the zone bookkeeping side.
