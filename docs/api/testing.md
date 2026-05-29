# slappyengine.testing — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


slappyengine.testing — visual regression harness.

## Classes

_(none)_

## Functions

### `assert_scene_matches(scene: 'Any', baseline_name: 'str', *, tolerance: 'float' = 0.02, width: 'int' = 1280, height: 'int' = 720) -> 'None'`

_defined in `slappyengine.testing`_

Render *scene*, compare to the named baseline, raise on mismatch.

#### Raises

- `TypeError` — if ``baseline_name`` is not a ``str``, or ``tolerance`` / ``width`` / ``height`` are not numeric.
- `ValueError` — if ``baseline_name`` contains path separators or disallowed characters (only ``[A-Za-z0-9_-]+`` accepted to prevent path traversal), or ``tolerance`` < 0, or ``width`` / ``height`` < 1.

### `diff_pngs(actual_path: 'str | Path', baseline_path: 'str | Path', *, tolerance: 'float' = 0.02) -> 'dict'`

_defined in `slappyengine.testing`_

Compare two PNGs and return diff metrics.

#### Raises

- `TypeError` — if ``actual_path`` / ``baseline_path`` are not str / os.PathLike, or ``tolerance`` is not a real number.
- `ValueError` — if ``tolerance`` is NaN/inf or outside ``[0, 1]``.

### `render_scene_to_png(scene: 'Any', path: 'str | Path', width: 'int' = 1280, height: 'int' = 720, frames_to_settle: 'int' = 2) -> 'Path'`

_defined in `slappyengine.testing`_

Render *scene* to a PNG at *path* and return the path.

#### Raises

- `TypeError` — if ``path`` is not str / os.PathLike, or ``width`` / ``height`` / ``frames_to_settle`` are not plain ints.
- `ValueError` — if ``width`` or ``height`` < 1, or ``frames_to_settle`` < 0.

## Constants

### `BASELINES_DIR`

_WindowsPath — defined in `pathlib._local`_

Value: `<repo>/python/slappyengine/testing/baselines`

### `DIFF_DIR`

_WindowsPath — defined in `pathlib._local`_

Value: `<repo>/docs/visual_diffs`

## Inner modules

_(none)_
