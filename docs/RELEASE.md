# Release checklist — Pharos Engine

The authoritative pre-release checklist. Every item must be green
before the maintainer signs off on a PyPI push.

## Pre-flight

- [ ] `cargo check --workspace` clean.
- [ ] `cargo test -p pharos_core --tests` green (9 tests as of v0.3.0).
- [ ] `cargo test -p pharos_render --tests` green (19 tests as of v0.3.0).
- [ ] `scripts/import_lint.py` clean.
- [ ] `scripts/errors_lint.py` clean.
- [ ] `pytest PharosEngineTests/tests/` green.
- [ ] `python tools/visual_capture/run.py --suite smoke` writes to `tests/visual_baseline/`.
- [ ] `python tools/visual_diff.py tests/visual_baseline/ tests/visual_baseline/` — 0 regressions.
- [ ] `python scripts/perf_gate.py --current <run>.json` passes (or `--update` a fresh baseline).
- [ ] `python scripts/wheel_size_audit.py dist/` passes.
- [ ] `.venv/Scripts/python scripts/build_wheel.py` builds cleanly.

## Version pins

Every version string in the tree must be aligned. Sprint 10 targets:

| Location                                     | Value        |
| -------------------------------------------- | ------------ |
| `python/pharos_engine/__init__.py`           | `0.3.0`      |
| `python/pharos_editor/__init__.py`           | `0.3.0`      |
| `pyproject.toml` `project.version`           | `0.3.0`      |
| `pyproject.toml` `editor = ["pharos-editor==..."]` | `0.3.0` |
| `pharos-editor/pyproject.toml` version       | `0.3.0`      |
| `pharos-editor/pyproject.toml` `pharos-engine==` | `0.3.0`  |
| `Cargo.toml` workspace version               | `0.3.0`      |
| `crates/pharos_c_abi/src/lib.rs` `ABI_MINOR` | bump on breaking C changes |

## Publish sequence

```bash
# Rust
cargo publish -p pharos_core

# Python — pharos-engine (maturin)
maturin publish  # from repo root; uses [tool.maturin] settings

# Python — pharos-editor (setuptools)
cd pharos-editor
python -m build
twine upload dist/*
```

## Post-flight

- [ ] `pip install pharos-engine==0.3.0` from a fresh venv works.
- [ ] `pip install pharos-editor==0.3.0` transitively installs `pharos-engine==0.3.0`.
- [ ] Docs deploy: `mkdocs gh-deploy` (or the CI equivalent) is green.

## Tag

```bash
git tag v0.3.0
# push only after human sign-off on the release:
git push origin v0.3.0
```

## Regression triage

If a metric regresses more than 5% between two runs:

1. `python scripts/perf_gate.py --current <fresh>.json` — confirm which metric.
2. `python tools/visual_diff.py tests/visual_baseline/ tests/visual_current/` — check whether pixels changed too.
3. Bisect with `git bisect run` against the failing metric.
