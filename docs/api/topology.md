<!-- handauthored: do not regenerate -->
# slappyengine.topology — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


Generic graph topology primitives.

## Classes

_(none)_

## Functions

### `connected_components(n_nodes: 'int', edges: 'np.ndarray', active: 'np.ndarray | None' = None, node_mask: 'np.ndarray | None' = None) -> 'tuple[np.ndarray, int]'`

_defined in `slappyengine.topology`_

Label connected components on an edge-list graph.

#### Raises

- `TypeError` — If ``n_nodes`` is not an int, ``edges`` is not a numpy ndarray of integral dtype, or ``active`` / ``node_mask`` are not bool ndarrays.
- `ValueError` — If ``n_nodes`` is negative, ``edges`` is not ``(E, 2)``, any edge endpoint falls outside ``[0, n_nodes)``, or ``active`` / ``node_mask`` have the wrong length.

### `connected_components_grid(density: 'np.ndarray', bond_e: 'np.ndarray', bond_s: 'np.ndarray', density_threshold: 'float' = 0.1, bond_threshold: 'float' = 0.05) -> 'tuple[np.ndarray, int]'`

_defined in `slappyengine.topology`_

Legacy 2-D grid form (kept for backward compat with old physics).

## Constants

### `BACKGROUND_LABEL`

_int — defined in `slappyengine.topology`_

Value: `-1`

## Inner modules

_(none)_
