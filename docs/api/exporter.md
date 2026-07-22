<!-- handauthored: do not regenerate -->
# pharos_engine.exporter — API Reference

> Hand-written reference for the LL6 cross-platform game exporter.
> Bundles a scaffolded Pharos Engine project into a distributable ZIP or a
> standalone PyInstaller binary. Sibling references: the CLI subcommand
> `slap export` (documented in [`../ONBOARDING.md`](../ONBOARDING.md) and
> registered in `python/pharos_engine/cli.py`) is the primary caller;
> [`../pyproject_extras_2026_07_05.md`](../pyproject_extras_2026_07_05.md)
> covers the pip-install shape the exported ZIP will boot into on a
> customer machine.

## Overview

`pharos_engine.exporter` is the Nova3D parity Sprint 18 landing (task
LL6), extended by NN7 with dry-run + verbose + exclude patterns +
`manifest.json`. It packages a scaffolded project (the tree produced by
`slap new`) into one of two shippable shapes:

* **ZIP bundle** — file-list walk of the project tree with a curated
  exclusion policy (`.git`, `__pycache__`, `.venv`, `build`, `dist`,
  `*.pyc`, `*.log`, `.DS_Store`). Optionally embeds an interpreter
  under `python/` plus a launcher script; otherwise ships a
  `PYTHON_SETUP.txt` explaining how the customer installs Python.
* **PyInstaller binary** — writes a `.spec` file next to `output_path`,
  invokes PyInstaller with per-platform flags (`--onefile` everywhere,
  `--strip` on linux, `--windowed` on macOS), and returns the produced
  executable path. Cleanly no-ops (with a warning) when PyInstaller is
  not installed.

Dispatch is by output extension: `output.suffix.lower() == ".zip"` →
`ZipBundler`; anything else → `BinaryExporter`. The
:func:`export_project` convenience wrapper is what the CLI calls.

## Public surface

```python
from pharos_engine.exporter import (
    BinaryExporter, BinaryExportResult,
    BundleResult,
    DEFAULT_EXCLUDES, REQUIRED_FILES,
    ExportResult,
    MANIFEST_FILENAME, MANIFEST_JSON_FILENAME,
    ProjectManifest, load_manifest,
    TARGETS, detect_current_platform, get_target,
    ZipBundler, build_bundle_manifest,
    export_project,
    pyinstaller_available,
)
```

## Classes

### `ZipBundler`

_class — defined in `pharos_engine.exporter.zip_bundler`_

Walks a scaffolded project tree and writes a filtered ZIP.

```python
ZipBundler(*, compression: int = zipfile.ZIP_DEFLATED)
```

Methods:

- `bundle(project_dir, output_zip, *, include_python=False, exclude_patterns=None, main_script="main.py", dry_run=False, verbose=False, write_manifest_json=False, manifest_targets=None, verbose_stream=None) -> BundleResult`

`dry_run=True` walks the tree without writing the zip (still runs the
exclusion filter and builds the preview manifest). `verbose=True`
prints one line per included / excluded file to *verbose_stream*
(defaults to `sys.stdout`). `exclude_patterns` extends the always-on
:data:`DEFAULT_EXCLUDES` tuple with fnmatch-style POSIX-relative
patterns.

Raises `TypeError` / `ValueError` on empty or wrong-typed arguments,
`FileNotFoundError` when *project_dir* does not exist.

### `BundleResult`

_dataclass — defined in `pharos_engine.exporter.zip_bundler`_

| Field | Type | Notes |
|-------|------|-------|
| `zip_path` | `Path` | Absolute path to the written zip. |
| `size_bytes` | `int` | Zip size on disk (0 in dry-run). |
| `included_files` | `list[str]` | POSIX-relative paths that landed inside the zip. |
| `excluded_files` | `list[str]` | Paths filtered out by :data:`DEFAULT_EXCLUDES` + caller patterns. |
| `warnings` | `list[str]` | Non-fatal issues (missing `main.py`, no embeddable interpreter). |
| `python_bundled` | `bool` | `True` when `include_python=True` succeeded. |
| `dry_run` | `bool` | Echoes the input flag. |
| `manifest` | `dict \| None` | Preview / written `manifest.json` payload. |

### `BinaryExporter`

_class — defined in `pharos_engine.exporter.binary_exporter`_

PyInstaller-backed executable builder.

```python
BinaryExporter(*, hidden_imports: Sequence[str] | None = None)
```

Default hidden imports are `["pharos_engine", "pharos_engine._core",
"yaml"]` so PyInstaller's static analysis picks up the C-extension +
YAML dependencies.

- `export(project_dir, output_path, *, platform="auto", console=False, icon=None, dry_run=False, main_script="main.py", name=None) -> BinaryExportResult`

Writes a `.spec` file even in dry-run mode so downstream tools can
introspect the intended build. `platform="auto"` resolves to the host
via :func:`detect_current_platform`; cross-compiling is not supported
(PyInstaller limitation) and returns an error result.

### `BinaryExportResult`

_dataclass — defined in `pharos_engine.exporter.binary_exporter`_

Fields: `binary_path`, `spec_path`, `size_bytes`, `log`, `warnings`,
`errors`, `succeeded`, `skipped_reason`.

### `ProjectManifest`

_dataclass — defined in `pharos_engine.exporter.manifest`_

Ship-time project metadata (`pharosproject.yaml`).

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | `"untitled"` |
| `version` | `str` | `"0.1.0"` |
| `author` | `str` | `""` |
| `main_script` | `str` | `"main.py"` |
| `assets_dirs` | `list[str]` | `["assets", "scenes"]` |
| `python_requires` | `str` | `">=3.10"` |

Class methods:

- `load(project_dir) -> ProjectManifest` — read `pharosproject.yaml`
  or fall back to `_from_project_dir(...)` which synthesises defaults
  from `config.yaml` + folder conventions.
- `from_yaml(text) -> ProjectManifest`
- `write(project_dir) -> Path`
- `to_dict() -> dict` / `to_yaml() -> str`

### `ExportResult`

_dataclass — defined in `pharos_engine.exporter`_

Unified return type for :func:`export_project`.

| Field | Type | Notes |
|-------|------|-------|
| `path` | `Path \| None` | Zip / binary / spec path; `None` on failure or dry-run. |
| `size_bytes` | `int` | 0 when nothing was written. |
| `manifest` | `ProjectManifest \| None` | Loaded manifest (or synthesised default). |
| `warnings` / `errors` | `list[str]` | Non-fatal / fatal messages. |
| `kind` | `str` | `"zip"` or `"binary"`. |
| `included_files` | `list[str]` | Populated for zip exports. |
| `python_bundled` | `bool` | Echoes `ZipBundler` state. |
| `pyinstaller_available` | `bool` | Snapshot at call time. |

`succeeded -> bool` is a property returning
`not errors and path is not None`.

## Functions

### `export_project(project_dir, output, *, platform="auto", include_python=False, icon=None, console=False, dry_run=False, verbose=False, exclude_patterns=None, write_manifest_json=True, manifest_targets=None, verbose_stream=None) -> ExportResult`

_defined in `pharos_engine.exporter`_

Convenience wrapper. Validates that *project_dir* exists and contains
either `main.py` or `pharosproject.yaml`, loads the manifest, then
dispatches on `output.suffix.lower()` — `.zip` calls :class:`ZipBundler`
otherwise :class:`BinaryExporter`.

### `build_bundle_manifest(project_dir, included_files, *, targets=None) -> dict`

_defined in `pharos_engine.exporter.zip_bundler`_

Compute a `manifest.json` payload: SHA-256 hashes over each included
file, project name / version from `pharosproject.yaml`, ISO-8601 build
timestamp, and the list of intended platform targets. Written into the
zip when `write_manifest_json=True`.

### `load_manifest(project_dir) -> ProjectManifest`

_defined in `pharos_engine.exporter.manifest`_

Thin wrapper over :meth:`ProjectManifest.load`.

### `detect_current_platform() -> str`

_defined in `pharos_engine.exporter.platform_targets`_

Returns `"windows"`, `"macos"`, or `"linux"` per `sys.platform`.

### `get_target(name) -> dict`

_defined in `pharos_engine.exporter.platform_targets`_

Return the :data:`TARGETS` descriptor for *name*. `"auto"` resolves to
the host. Raises `ValueError` on unknown names.

### `pyinstaller_available() -> bool`

_defined in `pharos_engine.exporter.binary_exporter`_

`True` when `import PyInstaller` succeeds. Callers should branch on
this before scheduling a binary export.

## Constants

### `MANIFEST_FILENAME`

_str — `"pharosproject.yaml"`_

### `MANIFEST_JSON_FILENAME`

_str — `"manifest.json"`_

Written into the zip root when `write_manifest_json=True`.

### `DEFAULT_EXCLUDES`

_tuple[str, ...] — defined in `pharos_engine.exporter.zip_bundler`_

Always-on fnmatch exclusion patterns. Includes `.git`,
`__pycache__`, `*.pyc`, `.venv`, `venv`, `build`, `dist`,
`.pharos/temp`, `*.log`, `.DS_Store`.

### `REQUIRED_FILES`

_tuple[str, ...] — `("main.py", "begin.py", "tick.py", "end.py", "config.yaml")`_

Files whose absence triggers a `BundleResult.warnings` entry (never a
hard failure — the customer may have a non-standard entry point).

### `TARGETS`

_dict[str, dict] — defined in `pharos_engine.exporter.platform_targets`_

Per-platform descriptors under keys `"windows"`, `"linux"`, `"macos"`.
Each entry carries `executable_ext`, `launcher_ext`,
`launcher_template`, `pyinstaller_flags`, `requires_native`.

## Usage

```python
from pathlib import Path
from pharos_engine.exporter import export_project

result = export_project(
    project_dir=Path("scaffold_out/my_game"),
    output=Path("dist/my_game.zip"),
    include_python=False,
    dry_run=True,           # walk the tree, do not write the zip
    verbose=False,
    exclude_patterns=["notes/*", "*.psd"],
    write_manifest_json=True,
    manifest_targets=["windows", "linux"],
)

assert result.kind == "zip"
assert result.manifest is not None
assert not result.errors
# result.included_files lists every file that WOULD land in the zip.
```

For a real ship-time build drop `dry_run=True` and inspect
`result.size_bytes` + `result.warnings`. The
`pharos_engine.cli.cmd_export` command drives exactly this call site
under the hood.

## Skip the wrapper

`pharos_engine.exporter` is Python-only. Grep of
`pharos_engine._core_facade.RUST_MODULE_MAP` shows **no** `exporter`
entry — the export path is bounded by disk I/O (zip write, PyInstaller
subprocess), so pushing it into Rust would not move any measurable
needle.

Callers who need finer-grained control than :func:`export_project`
should reach for :class:`ZipBundler` / :class:`BinaryExporter` directly
— the wrapper is a dispatch convenience, not a policy layer.

## See also

- [`../ONBOARDING.md`](../ONBOARDING.md) — the `slap export` CLI is
  the top-level driver for this subpackage.
- [`../pyproject_extras_2026_07_05.md`](../pyproject_extras_2026_07_05.md)
  — pip-install variants a shipped ZIP will bootstrap into.
- [`residency.md`](residency.md) — on-disk format used by the
  bundled asset payload.
- [`projects.md`](projects.md) — `Project` scaffolder that produces
  the tree consumed by this subpackage.
