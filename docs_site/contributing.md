# Contributing

See [`docs/CONTRIBUTING.md`](../docs/CONTRIBUTING.md) in the source
tree for the contributor conventions (hardening pattern, doc markers,
naming, post-process pass authoring).

## Local build

```bash
pip install maturin
maturin develop --extras dev
pytest PharosEngineTests/tests/
```

## Lints

```bash
python scripts/import_lint.py
python scripts/errors_lint.py
```

## Editor

```bash
python -c "import pharos_engine as pe; pe.Engine().run_editor()"
```
