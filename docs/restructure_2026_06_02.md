# Repo restructure — 2026-06-02

The top-level layout was reorganised so the project core stays focused on
the shippable engine, while developer-only artefacts (test suites and
example scripts) live under clearly-named top-level directories.

## New layout

```
H:/Github/SlapPyEngine/
├── python/pharos_engine/   ← core engine (unchanged)
├── src/                   ← Rust source (unchanged)
├── shaders/               ← WGSL (unchanged)
├── docs/                  ← documentation (unchanged)
├── benchmarks/            ← perf scripts (unchanged)
├── scripts/               ← tooling (unchanged)
├── tools/                 ← tooling (unchanged)
├── pyproject.toml         ← updated testpaths + maturin excludes
├── Cargo.toml             ← unchanged
├── SlapPyEngineTests/
│   ├── tests/             ← was repo-root tests/
│   └── python_tests/      ← was python/tests/
├── SlapPyEngineExamples/
│   └── examples/          ← was repo-root examples/ (output/ kept inside)
```

`SlapPyEngineTests/python_tests/` was renamed from the inner `python/tests/`
(which held a single empty `__init__.py`) so the two test roots no longer
collide.

## Path-translation table

| Before                         | After                                              |
|--------------------------------|----------------------------------------------------|
| `tests/foo.py`                 | `SlapPyEngineTests/tests/foo.py`                   |
| `python/tests/`                | `SlapPyEngineTests/python_tests/`                  |
| `tests/visual/reference/`      | `SlapPyEngineTests/tests/visual/reference/`        |
| `tests/visual/output/`         | `SlapPyEngineTests/tests/visual/output/`           |
| `examples/foo.py`              | `SlapPyEngineExamples/examples/foo.py`             |
| `examples/output/foo.gif`      | `SlapPyEngineExamples/examples/output/foo.gif`    |
| `examples/textures/foo.png`    | `SlapPyEngineExamples/examples/textures/foo.png`  |
| `examples/legacy/`             | `SlapPyEngineExamples/examples/legacy/`            |

Downstream consumers (Ochema Circuit, Bullet Strata) only consume the
PyPI wheel — they import `pharos_engine.testing` and call
`assert_scene_matches(...)`, which still works because the
`python/pharos_engine/testing/baselines/` data is unchanged and is still
shipped in the wheel. **No public Python API surface changed.**

## Commands that moved

| Before                                 | After                                                     |
|---------------------------------------|-----------------------------------------------------------|
| `pytest tests/`                       | `pytest SlapPyEngineTests/tests/`                         |
| `python examples/hello_rope.py`       | `python SlapPyEngineExamples/examples/hello_rope.py`     |
| `PYTHONPATH=python pytest tests/`     | `PYTHONPATH=python pytest SlapPyEngineTests/tests/`       |

The default `pytest` invocation also still works because
`[tool.pytest.ini_options].testpaths` was updated to point at
`SlapPyEngineTests/tests`.

## What was updated

* `pyproject.toml`
  - `testpaths = ["SlapPyEngineTests/tests"]`
  - `[tool.maturin].exclude` now lists `SlapPyEngineTests/**` and
    `SlapPyEngineExamples/**` (keeps the unchanged `**/tests` /
    `**/examples` globs as defence-in-depth)
* `.gitignore` — every `tests/output/`, `tests/visual/output/`,
  `examples/output/**`, `examples/legacy/output/` rule rewritten with the
  new prefix; PNG/GIF re-include rules also updated.
* `README.md` — install / quick-start / examples links pointed at the
  new paths.
* `tools/run_examples.py` — `EXAMPLES_DIR` repointed.
* 37 `docs/*.md` files — `](examples/...)` / `](tests/...)` /
  inline-code `` `examples/...` `` / `` `tests/...` `` substitutions for
  both relative (`../examples/`) and root-relative link forms.
* 31 test files using `Path(__file__).resolve().parents[1]` bumped to
  `parents[2]` (the test root moved one directory deeper).
* 27 test files using `Path(__file__).resolve().parent.parent` bumped to
  `parent.parent.parent` for the same reason.
* 20 test files using `_REPO_ROOT / "examples"` rewritten to
  `_REPO_ROOT / "SlapPyEngineExamples" / "examples"`.
* `SlapPyEngineTests/tests/test_sprint_2_sprite_audit.py` —
  `_VISUAL_REF_DIR` rewritten to include the new prefix.

## What was NOT touched

* `python/pharos_engine/softbody/` and `python/pharos_engine/fluid/` are
  uncommitted WIP and were left alone per the restructure brief.
* The Rust crate (`src/`, `Cargo.toml`) is unchanged.
* The public Python API surface (`python/pharos_engine/__init__.py`
  exports, `pharos_engine.testing.assert_scene_matches`, etc.).

## Verification

* **Pre-baseline** (before any moves):
  `2740 passed, 28 skipped, 10 xfailed`
* **Post-restructure**:
  `2740 passed, 28 skipped, 10 xfailed` — exact match.
* **Wheel** (`maturin build --release`):
  - 1.5 MB
  - 351 entries
  - 0 entries touching `SlapPyEngineTests/` or `SlapPyEngineExamples/`
    (verified by zip scan).
* `tools/run_examples.py discover_demos()` and the demo-smoke test
  battery (`test_examples_3d_smoke`, every `test_demo_hello_*`,
  `test_tools_run_examples`) all green against the new paths.

## Halt-and-revert events

None — the restructure completed in a single pass. A stale
`__pycache__` triggered a transient cluster of 22 false-positive
failures on the first post-move pytest run; they evaporated after
`rm -rf SlapPyEngineTests/**/__pycache__ .pytest_cache` and were never
indicative of a real regression.
