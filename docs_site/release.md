# Release checklist

See [`docs/RELEASE.md`](../docs/RELEASE.md) in the source tree for the
authoritative version.

## Pre-flight

- [ ] `cargo check --workspace` clean.
- [ ] `cargo test -p pharos_core` + `cargo test -p pharos_render` green.
- [ ] `scripts/import_lint.py` + `scripts/errors_lint.py` clean.
- [ ] `pytest PharosEngineTests/tests/` green.
- [ ] `python tools/visual_capture/run.py --suite smoke` writes baselines.
- [ ] `python tools/visual_diff.py tests/visual_baseline/ tests/visual_baseline/` reports 0 regressions.
- [ ] `python scripts/perf_gate.py --current out/perf_run.json` passes.
- [ ] `python scripts/wheel_size_audit.py dist/` passes.
- [ ] Version pins updated everywhere (root `pyproject.toml`,
      `pharos-editor/pyproject.toml`, `Cargo.toml`,
      `python/pharos_engine/__init__.py`,
      `python/pharos_editor/__init__.py`,
      `crates/pharos_c_abi/src/lib.rs` if the ABI changes).

## Publish

```bash
maturin publish
cd pharos-editor && python -m build && twine upload dist/*
cargo publish -p pharos_core
```

## Tag

```bash
git tag v0.3.0
# push tag only after human sign-off.
```
