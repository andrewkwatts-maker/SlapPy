# Wheel Size Audit — 2026-06-02

Audit of the PyPI wheel produced by `maturin build --release` for
`slappy-engine` v0.3.0b0. Goal: stay well under PyPI's practical limits
(50 MB target, 60 MB soft cap, 100 MB hard cap per file).

## TL;DR

| Metric                       | Before          | After           |
|------------------------------|-----------------|-----------------|
| Wheel file size (compressed) | **1 482 181 B** (~1.45 MB) | **1 471 196 B** (~1.44 MB) |
| Uncompressed contents        | 4 451 KB        | 4 405 KB        |
| Entry count                  | 357             | 351             |
| `slappyengine/tests/` shipped| 7 files (~60 KB)| 0 (excluded)    |
| `_core.cp313-win_amd64.pyd`  | 798 KB          | 798 KB          |

Both numbers are GREEN — `1.5 MB << 30 MB yellow flag << 50 MB red`.
The memory note recording "actual wheel ~13 MB" from the editor sprint
was stale: with `strip = true` in `Cargo.toml`'s release profile and
maturin's pre-existing exclude list, the wheel never approached double
digits. This audit confirms the headroom and tightens a few remaining
leaks.

## Wheel command

```
.venv/Scripts/python.exe -m maturin build --release \
    --interpreter .venv/Scripts/python.exe
```

Output: `target/wheels/slappy_engine-0.3.0b0-cp313-cp313-win_amd64.whl`

## Top 10 files in the (post-prune) wheel

| Size (B) | Path                                                       |
|---------:|------------------------------------------------------------|
|  817 664 | `slappyengine/_core.cp313-win_amd64.pyd`                   |
|  160 448 | `slappyengine/physics/world.py`                            |
|  109 673 | `slappyengine/physics/particle_gpu.py`                     |
|  108 250 | `slappyengine/physics/particle_field.py`                   |
|   76 670 | `slappyengine/softbody/render.py`                          |
|   62 443 | `slappyengine/fluid/render.py`                             |
|   58 476 | `slappy_engine-0.3.0b0.dist-info/sboms/slappyengine.cyclonedx.json` |
|   57 748 | `slappyengine/engine.py`                                   |
|   51 721 | `slappyengine/deform_modes.py`                             |
|   49 745 | `slappyengine/physics/hull.py`                             |

The Rust `_core` extension dominates (818 KB / 55 % of compressed size),
exactly as expected. The other large entries are legitimate Python
modules in the public API.

## What was excluded this audit

`pyproject.toml` `[tool.maturin].exclude` was tightened. New patterns:

- `**/*.pdb`                   — Windows debug symbol files.
- `**/.mypy_cache`, `**/.ruff_cache` — lint/type-check caches.
- `python/slappyengine/tests` and `python/slappyengine/tests/**` —
  inner test subpackage. The `**/tests` wildcard alone didn't catch it
  reliably through maturin's globbing, so the explicit path was added.
- `_audit_snapshots`, `benchmarks`, `docs`, `examples`, `scripts`,
  `tools`, `target` (and their `/**` recursive forms) — repo-root
  artefacts that should never ship to PyPI.

These join the pre-existing excludes for `__pycache__`, `*.pyc`,
`*.pyo`, top-level `tests`/`examples`, and `.pytest_cache`.

## What was intentionally KEPT

- `slappyengine/_core.cp313-win_amd64.pyd` — the Rust extension.
- `slappyengine/testing/baselines/*.png` and `*.npy` (~240 KB) — these
  are **runtime data** for the public `slappyengine.testing` golden-
  master API. Downstream test suites (Ochema Circuit, Bullet Strata)
  call `assert_scene_matches(name)`; without the committed baselines
  on disk, every first run silently bootstraps a fresh baseline and
  asserts nothing. The `testing/__init__.py` docstring explicitly
  documents this contract ("inside the package — ships with wheel").
- `*.pyi` stub files, `*.wgsl` shaders, `*.html` editor templates —
  all consumed at runtime by the engine.
- `dist-info/sboms/slappyengine.cyclonedx.json` (58 KB) — SBOM is
  required by maturin's signed-wheel pipeline.

## Verification

Wheel was installed into a clean venv (`/tmp/slappy_test_venv`) and the
following checks passed:

```python
import slappyengine                      # OK
from slappyengine import Engine, Scene, Entity, Camera  # OK
from slappyengine import _core           # OK
from slappyengine import testing
assert testing.BASELINES_DIR.exists()    # True
assert len(list(testing.BASELINES_DIR.glob('*.png'))) == 23  # OK
import slappyengine.tests                # raises ModuleNotFoundError ✓
from slappyengine import studio          # OK
```

## File changed

- `pyproject.toml` — `[tool.maturin].exclude` expanded with the
  patterns documented above.

## Headroom

Current wheel: **1.44 MB**. PyPI red cap: 100 MB. We have **~98 MB**
of headroom — roughly 65× the current size. The audit is a maintenance
checkpoint, not a fire drill.
