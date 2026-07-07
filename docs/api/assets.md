<!-- handauthored: do not regenerate -->
# slappyengine.assets — API Reference

> Hand-written reference for `slappyengine.assets` — the central
> asset registry with hot-reload and extensible import handlers.
> Sibling references: [`asset_import.md`](asset_import.md) is the
> load-time loader stack (`import_asset` / `load_model` /
> `load_texture` returning `ImportResult`); this doc is the
> registry / cache / watcher layer that sits *above* those loaders.

## Overview

`slappyengine.assets` is the "one place every runtime lookup goes" layer
of the asset stack. Where [`asset_import.md`](asset_import.md) owns the
per-format parsers, this subpackage owns the process-wide **cache** of
already-loaded assets, the **hot-reload** watcher that keeps that cache
consistent with the on-disk source, and the **extension → loader**
registry that lets projects (and downstream games like Ochema Circuit
and Bullet Strata) plug in custom file formats without patching the
engine.

The public surface is a single class — :class:`AssetDatabase` — held as
a process-wide singleton via :meth:`AssetDatabase.instance`. Every
attribute lookup on that class validates its inputs through
`slappyengine.assets._validation`, so authoring bugs (bad extension
form, empty path, non-callable loader) fail loudly with the canonical
`TypeError` / `ValueError` shape the rest of the engine uses.

Load-bearing behaviour:

* **mtime-based cache invalidation.** :meth:`AssetDatabase.load` checks
  `os.stat(...).st_mtime` against the cached record; the file is re-imported
  only when the mtime has moved (or `force_reload=True`).
* **Default handlers wired at construction.** Common image extensions
  (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.tga`, `.webp`) resolve to
  :class:`slappyengine.layer.Layer.from_image`; YAML extensions
  (`.yml`, `.yaml`) resolve to `yaml.safe_load`; the engine-native
  `.slap` container resolves to `slappyengine.asset.Asset.load`.
* **`watchdog` is a soft dependency.** :meth:`AssetDatabase.watch`
  installs a filesystem observer when the `watchdog` package is
  present and silently no-ops when it is not — headless CI keeps the
  same call sites as the interactive editor.

The subpackage `__init__.py` is empty on purpose. Import from the
canonical submodule to avoid pulling in the (heavier) `layer.Layer`
import chain until you actually need it.

## Public surface

```python
from slappyengine.assets.database import AssetDatabase, AssetRecord

db = AssetDatabase.instance()             # process-wide singleton
layer = db.load("Content/Assets/hero.png") # returns Layer2D
```

* :class:`AssetDatabase` — process-wide registry + cache + watcher.
* :class:`AssetRecord` — cached entry: path, live asset, size, mtime.

## Classes

### `AssetDatabase`

_class — defined in `slappyengine.assets.database`_

Process-wide singleton. Never construct directly; go through
:meth:`AssetDatabase.instance`.

#### Class methods

- `AssetDatabase.instance() -> AssetDatabase` — return (and lazily
  create) the shared process-wide database. Idempotent; safe to call
  from any subsystem that needs to resolve an asset path.

#### Public methods

| Method | Purpose |
|--------|---------|
| `load(path, force_reload=False) -> Any` | Load or return the cached asset at `path`. Cache hit is decided by `os.stat.st_mtime` against the record; `force_reload=True` bypasses the cache. |
| `register_handler(ext, loader)` | Attach a custom loader for extension `ext` (must start with `.`). Overrides any prior handler for the same extension. |
| `watch(directory)` | Install a filesystem watcher on `directory` so subsequent modifications trigger a background re-import. No-op when `watchdog` is not installed. |
| `all_records() -> list[AssetRecord]` | Snapshot the cache as a list. Cheap; used by editor thumbnail panels. |
| `get_record(path) -> AssetRecord \| None` | Return the cached record for `path` without triggering a load. |

**Validation contract (all public methods).** `path` / `directory`
must be a non-empty `str` or `Path` (validated via the shared
`slappyengine._validation.validate_path_like` helper);
`force_reload` must be exactly a `bool`; `ext` must be a non-empty
lowercase extension starting with `.`, with no path separator and no
whitespace; `loader` must be callable. Violations raise `TypeError`
or `ValueError` with a `AssetDatabase.<method>: <arg> must be ...`
message.

**Raises (`load`):**

- `TypeError` — non-`str`/`Path` `path`, non-`bool` `force_reload`.
- `ValueError` — empty `path`, or extension has no registered
  handler (message points at `register_handler`).

### `AssetRecord`

_class — defined in `slappyengine.assets.database`_

Cache entry. `__slots__`-based so a mid-size project (a few thousand
records) stays under a megabyte of registry overhead.

Fields:

| Field | Type | Notes |
|-------|------|-------|
| `path` | `str` | Absolute path of the source file. |
| `asset` | `Any` | Live asset object (Layer2D / dict / Asset / user-defined). |
| `asset_type` | `str` | Lower-cased extension without the leading `.` (e.g. `"png"`, `"yaml"`). |
| `size_bytes` | `int` | `os.stat.st_size` at load time. |
| `last_modified` | `float` | `os.stat.st_mtime` used for cache invalidation. |
| `thumbnail_path` | `str \| None` | Optional editor-generated preview path; `None` until the thumbnail pipeline populates it. |

## Usage

```python
from slappyengine.assets.database import AssetDatabase

# Grab the singleton and load a PNG (image handler is default-wired).
db = AssetDatabase.instance()
tile = db.load("Content/Assets/tiles/grass.png")

# Register a custom loader for .tmx tile maps. Loader signature is
# ``(abs_path: str) -> Any``; the return value is what ``load()`` gives
# callers on cache miss and hit alike.
def load_tmx(path: str) -> dict:
    with open(path) as f:
        return {"raw": f.read()}
db.register_handler(".tmx", load_tmx)
level = db.load("Content/Levels/pit.tmx")

# Force a reload after an out-of-band edit.
tile2 = db.load("Content/Assets/tiles/grass.png", force_reload=True)

# Introspect the cache — editor thumbnail panels iterate this.
for rec in db.all_records():
    print(rec.path, rec.asset_type, rec.size_bytes)

# Optional: watch a directory for filesystem changes. No-op when the
# `watchdog` package is not installed; the call is safe to make in
# headless CI unconditionally.
db.watch("Content/")
```

## Skip the wrapper

`slappyengine.assets` is Python-only. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `assets`
entry — the registry is a plain `dict[str, AssetRecord]` and the cache
hot-path is a single `os.stat` call plus a dictionary lookup, both
already O(1). Rewriting in Rust would move no measurable frame-time
needle.

Callers who want to bypass the singleton entirely can build their own
`AssetDatabase()` (the constructor is public) — for example, an editor
project switcher that keeps a per-project registry rather than sharing
the process-wide one. The default handler wiring is done in
`_register_defaults`; subclass and override it if you want a completely
different default set.

If a future sprint adds a heavy on-disk cache format (LZ4 blob store,
sqlite index of millions of assets), promote that pipeline to its own
module and revisit the Rust-migration question against
[`../rust_migration_plan.md`](../rust_migration_plan.md) at that
point — today the numpy / PIL loaders themselves dominate load-time
cost, not the registry layer.

## Conventions

- **Singleton via `instance()`.** Every subsystem that resolves an
  asset path shares one `AssetDatabase`. Don't instantiate directly
  unless you are building an editor project switcher or a headless
  test fixture.
- **Absolute path canonicalisation.** Every public method calls
  `Path(...).resolve()` on the input so cache lookups are invariant
  to relative-path form. This is why `load("./x.png")` and
  `load("x.png")` from the same cwd share a cache entry.
- **Silent watcher fallback.** `watch` swallows `ImportError` when
  `watchdog` is not installed — the same call site works for the
  editor (interactive, watchdog present) and CI (headless, no watchdog)
  without a guard.
- **Default handlers register at construction.** Overriding the
  default set means either calling `register_handler` after
  `instance()` or subclassing and replacing `_register_defaults`.

## See also

- [`asset_import.md`](asset_import.md) — the load-time loader stack
  this registry sits on top of. Loaders returning
  `ImportResult` can be adapted into `register_handler` callbacks.
- [`residency.md`](residency.md) — the three-tier GPU / RAM / DISK
  residency manager. Complementary layer: `AssetDatabase` owns the
  identity mapping (path → asset), `residency` owns the where-it-lives
  budget.
- [`material.md`](material.md) — one common target of `.slap` container
  loads (materials round-trip through `Asset`).
- [`../pyproject_extras_2026_07_05.md`](../pyproject_extras_2026_07_05.md)
  — the `watchdog` soft-dep is documented as part of the
  editor / dev extras.
