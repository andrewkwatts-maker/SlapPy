<!-- handauthored: do not regenerate -->
# pharos_engine.projects — API Reference

> Hand-written reference for the `projects` subpackage — Nova3D-style
> multi-project management with persistent recents storage.
> Owns the on-disk `project.slap_proj` manifest format and the
> per-user `~/.pharos_engine/projects.yaml` registry. Does **not**
> own scene serialisation (see [`studio.md`](studio.md) for stage
> bundles) or asset databases (see runtime
> `pharos_engine.assets.AssetDatabase` — discoverable via the registry's
> opened-project paths, not duplicated here).

## Overview

A *project* is a self-contained directory on disk owned by an end-user
game. Every project carries a single manifest file at its root
(`project.slap_proj`, YAML) that records its display name, the engine
version it was created with, ISO 8601 created/last-opened timestamps,
and a few cosmetic fields (description, icon path, default editor
theme). The :class:`Project` dataclass is the in-memory handle the
editor passes around once a project has been opened; mutating
``self.metadata`` and calling :meth:`Project.save` round-trips the
manifest atomically.

The :class:`ProjectRegistry` persists a per-user "recently opened
projects" list to ``~/.pharos_engine/projects.yaml`` so the editor's
welcome screen can restore the user's session across launches. The
registry is *not* the canonical project record — the manifest in each
project directory is — it only tracks discovery state. Corrupt registry
YAML is treated as "empty registry" rather than a hard failure so the
editor bootstrap path stays resilient.

A small scaffolder lays down the default subdirectory tree
(``scenes/``, ``assets/``, ``scripts/`` plus seed files and a 64x64
placeholder icon) when a project is first created. The scaffolder is
*idempotent* — existing files are never overwritten — so re-scaffolding
a partially populated project preserves user content.

## Public surface

```python
from pharos_engine.projects import (
    Project,
    ProjectMetadata,
    ProjectRegistry,
    get_default_registry,
    read_project,
    write_project,
    is_project_dir,
    find_project_root,
    ProjectFormatError,
    PROJECT_FILE_NAME,
    scaffold_project,
)
```

| Symbol | Role |
|---|---|
| `Project` | In-memory project handle. Owns `path` (root dir) + `metadata`. |
| `ProjectMetadata` | YAML-backed manifest dataclass. |
| `ProjectRegistry` | Persistent recents tracker (`~/.pharos_engine/projects.yaml`). |
| `get_default_registry` | Lazy singleton accessor for the per-process registry. |
| `read_project` / `write_project` | Manifest I/O — atomic rename on write. |
| `is_project_dir` / `find_project_root` | Directory discovery helpers. |
| `ProjectFormatError` | Raised for malformed / missing manifest fields. |
| `PROJECT_FILE_NAME` | `"project.slap_proj"` — the canonical manifest filename. |
| `scaffold_project` | Lays down the default `scenes/` / `assets/` / `scripts/` tree. |

## Classes

### `ProjectMetadata`

_dataclass — defined in `pharos_engine.projects.project`_

Manifest fields written verbatim to `project.slap_proj`. Every field
is a plain Python primitive (string only — no `datetime` / `Path`
objects) so the dataclass round-trips through `yaml.safe_dump` /
`yaml.safe_load` without custom representers.

#### Constructor signature

```python
ProjectMetadata(
    name: str,
    version: str,
    created_at: str,        # ISO 8601 UTC
    last_opened_at: str,    # ISO 8601 UTC
    description: str = "",
    icon: str = "",         # relative to project root
    default_theme: str = "teengirl_notebook",
) -> None
```

#### Methods

- `to_dict() -> dict` — YAML-safe snapshot.
- `from_dict(cls, data: dict) -> ProjectMetadata` — classmethod;
  required fields `name` + `version`, missing optionals fall back to
  defaults, unknown keys ignored for forwards compatibility.

#### Raises

- `TypeError` — Any field of the wrong type at construction (`from_dict`
  re-raises validation errors as `ValueError`).
- `ValueError` — `name`, `version`, `created_at`, `last_opened_at`,
  or `default_theme` empty.
- `KeyError` — `from_dict` called without a required key.

### `Project`

_dataclass — defined in `pharos_engine.projects.project`_

The in-memory handle the editor passes around once a project has been
opened. Binds the on-disk root directory to its loaded metadata. Path
helpers (`scenes_dir` / `assets_dir` / `scripts_dir`) return canonical
subdirectories under the root and do *not* assert they exist — so a
fresh `Project` can be constructed before scaffolding it.

#### Constructor signature

```python
Project(path: Path, metadata: ProjectMetadata) -> None
```

#### Classmethods

- `new(root, name, *, version=None, description="", scaffold=True) -> Project`
  — create a fresh project at `root`. Writes the manifest, optionally
  runs `scaffold_project`, and returns the handle. `version` defaults
  to the running `pharos_engine.__version__`.

#### Properties

| Property | Returns |
|---|---|
| `slap_proj_path` | `path / PROJECT_FILE_NAME` |
| `scenes_dir` | `path / "scenes"` |
| `assets_dir` | `path / "assets"` |
| `scripts_dir` | `path / "scripts"` |
| `icon_path` | `path / metadata.icon`, or `None` if `metadata.icon` is empty |

#### Methods

- `save() -> None` — atomic rewrite of `project.slap_proj` from
  `metadata`. Creates parent dirs if missing.
- `reload() -> None` — re-read manifest from disk, overwriting
  `metadata`. Useful after external edits.
- `touch_last_opened() -> None` — set `metadata.last_opened_at` to "now"
  and persist. Called by the registry on every `open()`.

### `ProjectRegistry`

_class — defined in `pharos_engine.projects.registry`_

Persistent recents tracker. Stores a per-user YAML list of
recently opened projects at `~/.pharos_engine/projects.yaml` (or any
override passed via `store_path`). All writes are atomic.

#### Constructor signature

```python
ProjectRegistry(store_path: Path | str | None = None) -> None
```

`store_path=None` resolves to `Path.home() / ".pharos_engine" /
"projects.yaml"` on first access. Existing data is loaded on
construction so `list_recent()` works out of the box.

#### Methods

- `list_recent(limit: int = 10) -> list[RegistryEntry]` — newest-first
  recents (entries with malformed timestamps land at the end).
- `entries() -> list[RegistryEntry]` — full untruncated list.
- `find(path) -> RegistryEntry | None` — lookup by canonical path.
- `register(project: Project) -> RegistryEntry` — add or refresh the
  entry for *project*. Persists immediately. Idempotent by canonical
  path.
- `unregister(path) -> bool` — drop the entry matching *path*. Returns
  `True` iff something was removed.
- `clear() -> None` — drop every entry and persist the empty list.
- `open(path) -> Project` — walk upward via `find_project_root`, open
  the located project, touch its `last_opened_at`, and re-register.
- `new(root, name, *, description="", scaffold=True) -> Project` —
  thin wrapper around `Project.new` + `register`.
- `save() -> None` — explicit persistence (auto-called by mutations).
- `reload() -> None` — discard in-memory state and re-read from disk.

Supports `len()` and `path in registry` membership. Membership accepts
`str` or `Path`; other types return `False` rather than raising.

#### Raises

- `TypeError` — `register` / `open` called with the wrong type;
  `list_recent` called with non-int limit.
- `ValueError` — `list_recent(limit < 1)`.
- `FileNotFoundError` — `open()` called on a path with no project
  ancestor.
- `ProjectFormatError` — `open()` resolves to a malformed manifest.

### `RegistryEntry`

_dataclass — defined in `pharos_engine.projects.registry`_

One row in the recents list — denormalised path + last-opened
timestamp + project name. Storing the name lets the welcome screen
render the recents list without opening every manifest, and lets the
registry recover gracefully from projects whose disk entry has been
moved or deleted.

```python
RegistryEntry(path: str, last_opened_at: str, name: str = "") -> None
```

## Functions

### `read_project(path) -> Project`

_defined in `pharos_engine.projects.format`_

Load a `Project` from a directory containing `project.slap_proj`.

Raises:

- `TypeError` — *path* is not a `str` / `Path`.
- `FileNotFoundError` — directory or manifest missing.
- `ProjectFormatError` — malformed YAML, non-mapping top level, empty
  file, or missing required field.

### `write_project(project) -> None`

_defined in `pharos_engine.projects.format`_

Atomically write `project`'s manifest to disk. Renders with
`yaml.safe_dump` and uses a temp-file + rename so a crash mid-write
never leaves a partially serialised manifest.

### `is_project_dir(path) -> bool`

_defined in `pharos_engine.projects.format`_

Pure filesystem check — `True` iff *path* is a directory containing a
file literally named `project.slap_proj`. Does not parse the manifest.

### `find_project_root(path) -> Path | None`

_defined in `pharos_engine.projects.format`_

Walk upward from *path* (or its parent if *path* is a file) looking
for an ancestor that contains `project.slap_proj`. Returns `None` if
no project root is found before the filesystem root. Safe across
symlink cycles via a resolved-path visited set.

### `scaffold_project(project) -> dict[str, Path]`

_defined in `pharos_engine.projects.scaffolding`_

Create the default directory tree under `project.path`:

```
<root>/
  project.slap_proj      # written separately by Project.save
  scenes/
    main.scene.yaml      # welcome scene mentioning the project name
  assets/
    README.md            # "drop your assets here" note
  scripts/
    main.py              # entry-point stub
  icon.png               # 64x64 placeholder (PIL if available)
```

Returns a dict mapping role keys (`scenes_dir`, `main_scene`, …) to
absolute paths so the editor can wire up follow-up actions
(e.g. open the welcome scene in the inspector immediately).

Idempotent — existing files are never overwritten.

### `get_default_registry() -> ProjectRegistry`

_defined in `pharos_engine.projects.registry`_

Return the process-wide singleton `ProjectRegistry`, lazy-constructed
on first call so importing `pharos_engine.projects` does not touch
`~/.pharos_engine/` (relevant for headless CI / sandboxed builds).
Tests that need a fresh registry should construct one directly with a
temp `store_path` rather than mutating the singleton.

## Constants

### `PROJECT_FILE_NAME`

_str — defined in `pharos_engine.projects.format`_

Value: `"project.slap_proj"`. The engine never tries alternates — no
`.yaml` / `.yml` ambiguity, no case folding. Editors should suggest
this filename verbatim when authoring outside the engine helpers.

## Inner modules

- `pharos_engine.projects.project` — `Project` / `ProjectMetadata`
  dataclasses, ISO 8601 helper.
- `pharos_engine.projects.format` — YAML I/O + directory-walk helpers.
- `pharos_engine.projects.registry` — `ProjectRegistry` +
  `RegistryEntry` + singleton accessor.
- `pharos_engine.projects.scaffolding` — default-tree scaffolder with
  PIL-soft icon rendering.

## Conventions

- **Validation.** All public entry points run their string / path
  arguments through `pharos_engine._validation` so malformed input
  surfaces a `TypeError` / `ValueError` at the boundary rather than
  inside the YAML parser.
- **Atomic writes.** Both `write_project` and `ProjectRegistry.save`
  go through a temp-file + `Path.replace` so a crash mid-write never
  leaves a half-rendered manifest on disk.
- **Resilient bootstrap.** A corrupt `~/.pharos_engine/projects.yaml`
  silently degrades to "empty registry" rather than raising — the
  editor must still launch even if the recents list is bad.
- **YAML safety.** All reads use `yaml.safe_load`; all writes use
  `yaml.safe_dump`. No custom representers — every manifest field is a
  plain string or scalar.
- **Idempotency.** `register` is idempotent by canonical path,
  `unregister` returns `False` (not raise) for absent entries, and
  `scaffold_project` skips files that already exist.

## See also

- [`studio.md`](studio.md) — `Stage` bundles and `record()` for the
  actual scene-running side of the editor's "Play" button.
- [`ui_editor.md`](ui_editor.md) — `EditorShell` + scene outliner that
  consume the registry's recents list on the welcome screen.
- [`testing.md`](testing.md) — `assert_scene_matches` for asserting
  the scaffolded `main.scene.yaml` renders correctly in golden-frame
  tests.
