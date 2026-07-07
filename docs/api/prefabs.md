<!-- handauthored: do not regenerate -->
# slappyengine.prefabs — API Reference

> Hand-written reference for the `prefabs` subpackage — reusable
> entity templates loadable from `.prefab.yaml` and spawnable into a
> :class:`slappyengine.dynamics.World`. Owns the on-disk YAML recipe,
> the `~/.slappyengine/prefabs/` bake-out mirror, and the 64x64
> diary-styled preview thumbnail generator. Does **not** own the
> underlying body / joint dataclasses (see
> [`dynamics.md`](dynamics.md)) or the notebook-editor spawn menu
> UI (see [`ui_editor.md`](ui_editor.md) — the spawn card widget
> consumes this subpackage's :class:`PrefabLibrary` and previews).

## Overview

A *prefab* is a small YAML recipe describing one entity (or a
composition of entities) so spawn cards, level authoring tools, and
gameplay code can share definitions. Every prefab bundles:

* A **body spec** — the shape passed to a
  :class:`slappyengine.dynamics.World` builder. Kind must be one of
  seven values: `point` / `circle` / `box` / `rope` / `ragdoll` /
  `chain` / `composite`.
* An optional list of **joint specs** wired between the primary
  body's nodes at spawn time.
* An optional list of **child prefab names** for composition.
* Free-form **metadata** for editor / gameplay tagging.

Prefabs deliberately store their spec as plain `dict` payloads so
the YAML round-trip is lossless without touching the dynamics-side
dataclass constructors. :meth:`Prefab.spawn` materialises the
recipe into a real world, returning the created
:class:`~slappyengine.dynamics.body.Body` handles.

:class:`PrefabLibrary` mirrors the
:class:`slappyengine.ui.theme.user_themes.UserThemeStore` pattern:
baked files ship inside the wheel at
`python/slappyengine/prefabs/baked/` and are copied into
`~/.slappyengine/prefabs/` on first use so downstream code can
edit them without touching the installed package.

:class:`PreviewBaker` renders a deterministic 64x64 top-down
projection of each body kind so the editor spawn menu shows a
recognisable glyph next to every entry — the render RNG is seeded
from the prefab name, so two bakes on two machines produce
byte-identical PNGs.

## Public surface

```python
from slappyengine.prefabs import (
    CATEGORIES,
    DIARY_PALETTE,
    Prefab,
    PrefabLibrary,
    PreviewBaker,
)
```

| Symbol | Role |
|---|---|
| `Prefab` | The YAML-backed recipe dataclass; owns `.spawn()`. |
| `PrefabLibrary` | Registry + on-disk loader (baked wheel dir + user dir). |
| `PreviewBaker` | Deterministic 64x64 PNG icon generator per body kind. |
| `CATEGORIES` | `("props", "characters", "vehicles", "particles", "structural")`. |
| `DIARY_PALETTE` | 8-colour pastel "diary tokens" palette used by previews. |

## Classes

### `Prefab`

_dataclass — defined in `slappyengine.prefabs.prefab`_

One reusable entity template.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Unique identifier the library keys on. Non-empty. |
| `category` | `str` | One of :data:`CATEGORIES`. |
| `body_spec` | `dict` | Must contain `"kind"` from the seven-kind whitelist. |
| `joint_specs` | `list[dict]` | Passed through `_wire_joint_dict` at spawn. |
| `child_prefabs` | `list[str]` | Names of composed prefabs (best-effort resolve). |
| `metadata` | `dict` | User tags — library never inspects. |

Validation happens in `__post_init__`: `TypeError` on wrong field
types, `ValueError` on empty name / unknown category / missing or
unknown body kind / empty child names.

#### Key methods

- `spawn(self, world, position, rotation=0.0, *, library=None) -> list[Body]`
  — materialise the prefab. Runs the body spec, wires the joint
  specs (interpreting their `node_a` / `node_b` as offsets into the
  primary body's node slice), then recursively spawns children if a
  library was passed. Raises `TypeError` / `ValueError` on invalid
  position or rotation.
- `entity_count` property (and `compute_entity_count(library=None)`) —
  gameplay entity count for spawn-card widget + HUD:
  `point`/`circle`/`box` = 1, `rope` = `segments`, `chain` = `links`,
  `ragdoll` = 7 (shipping humanoid skeleton), `composite` =
  recursive child sum (or `len(body_spec["nodes"])` fallback).
- `to_dict(self)` / `to_yaml(self)` — plain-dict + YAML export
  (round-trips through `from_dict` / `from_yaml`).
- `from_dict(cls, data)` / `from_yaml(cls, text)` — decoders; raise
  `TypeError` on non-dict / non-str input and `ValueError` on
  missing required keys.

### `PrefabLibrary`

_class — defined in `slappyengine.prefabs.library`_

In-memory registry of named :class:`Prefab` entries backed by
two on-disk directories.

| Class attribute | Value | Role |
|---|---|---|
| `SUFFIX` | `".prefab.yaml"` | File suffix scanners reuse. |
| `BAKED_DIR` | wheel `prefabs/baked/` | Read-only shipped prefabs. |
| `USER_DIR` | `~/.slappyengine/prefabs/` | Writable user overrides. |

#### Key methods

- `register(self, prefab) -> Prefab` — add / replace an entry.
  Raises `TypeError` if not a :class:`Prefab`, `ValueError` on empty
  name.
- `get(self, name) -> Prefab | None` — soft lookup.
- `load_from_dir(self, path)` — scan `path` for `*.prefab.yaml`
  files and register each. Skips malformed files with a logged
  warning rather than hard-failing (bake-out remains resilient to
  half-authored user edits).
- `load_baked(self)` — register everything in :attr:`BAKED_DIR`.
- `bake_defaults(self)` — copy every baked file into :attr:`USER_DIR`
  on first use, atomically via temp-file rename.
- `save_to_dir(self, path)` — write every registered prefab back to
  disk as `<name>.prefab.yaml`.

### `PreviewBaker`

_class — defined in `slappyengine.prefabs.preview_baker`_

Renders a 64x64 top-down PIL image per prefab, deterministically —
same prefab always hashes to the same palette slot and the internal
wobble RNG is seeded from the prefab name.

Render dispatch — one branch per body kind:

* `point` / `circle` → filled disk + highlight.
* `box` → wooden crate icon (5 grain lines + 2 nails).
* `rope` → 5-segment zigzag top-left to bottom-right.
* `ragdoll` → 4-limb stick figure (head / torso / arms / legs).
* `chain` → 5 linked ovals alternating orientation.
* `composite` → recursive layout of child glyphs around centre
  (fallback marker when no library / children resolve).

#### Key methods

- `bake_preview(self, prefab) -> PIL.Image` — 64x64 RGBA thumbnail.
- `bake_all_previews(self, library, out_dir)` — write every prefab
  in `library` to `<out_dir>/<name>.png`.

## Constants

### `CATEGORIES`

_`tuple[str, ...]` — defined in `slappyengine.prefabs.prefab`_

Value: `("props", "characters", "vehicles", "particles", "structural")`.
The five buckets the trading-card deck / spawn-menu tabs group
prefabs into.

### `DIARY_PALETTE`

_`tuple[tuple[int, int, int], ...]` — defined in
`slappyengine.prefabs.preview_baker`_

Fixed 8-colour pastel palette (coral / ochre / olive / sage / mint
/ sky / lavender / rose family) pairing with the notebook-editor
theme. Preview colour selection hashes the prefab name into this
tuple so the palette assignment is stable across bakes.

## Inner modules

- `slappyengine.prefabs.prefab` — :class:`Prefab` dataclass + the
  seven-kind `_spawn_body_spec` dispatcher.
- `slappyengine.prefabs.library` — :class:`PrefabLibrary` + on-disk
  YAML I/O + bake-out.
- `slappyengine.prefabs.preview_baker` — :class:`PreviewBaker` +
  :data:`DIARY_PALETTE`.
- `slappyengine.prefabs.baked/` — the 6 shipping `*.prefab.yaml`
  recipes + `previews/*.png` icon cache.

## Usage

```python
from slappyengine.dynamics import World
from slappyengine.prefabs import PrefabLibrary, PreviewBaker

# 1. Boot the library — register the 6 shipping prefabs.
lib = PrefabLibrary()
lib.load_baked()

# 2. Spawn a crate into a live world.
world = World(gravity=(0.0, -9.81))
crate = lib.get("crate")
bodies = crate.spawn(world, (0.0, 5.0))
assert len(bodies) >= 1

# 3. Bake preview thumbnails for a spawn menu.
baker = PreviewBaker()
icon = baker.bake_preview(crate)                # PIL.Image 64x64
icon.save("crate.png")

# 4. User overrides land in ~/.slappyengine/prefabs/ ; call
#    bake_defaults() once to seed the user dir from the wheel.
lib.bake_defaults()
```

## Skip the wrapper

`slappyengine.prefabs` is pure Python (plus `pyyaml` + `Pillow`) —
no runtime work lives in Rust. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `prefabs`
entry.

The prefabs' *downstream* consumers do call into Rust:
:meth:`Prefab.spawn` builds bodies via
:mod:`slappyengine.dynamics`, which routes distance-constraint
projection through the `softbody_solver` Rust module
(`RUST_MODULE_MAP["softbody_solver"]` — `src/softbody_solver.rs`).
Callers who need to hand-assemble a body without a prefab YAML can
call :func:`slappyengine.dynamics.build_rope` /
:func:`slappyengine.dynamics.build_ragdoll` directly — this
subpackage is the ergonomic authoring layer, not a required step.

## Conventions

- **YAML round-trip.** `Prefab.to_yaml` / `from_yaml` is the
  authoring contract; the dataclass never grows non-primitive
  fields that would need a custom YAML representer.
- **Soft child-resolution.** Missing / unknown child names during
  `spawn` log a warning and continue rather than raising — a
  half-authored composite still spawns its primary body.
- **Baked-vs-user precedence.** :attr:`BAKED_DIR` seeds
  :attr:`USER_DIR` on first `bake_defaults` call, then user
  overrides win for any name registered in both.
- **Deterministic previews.** :class:`PreviewBaker` seeds its
  wobble RNG from the prefab name, so two machines producing the
  same PNG bytes is a testable invariant.
- **Node offsets, not world indices.** Joint specs on a prefab
  address `node_a` / `node_b` as offsets into the primary body's
  node slice, not absolute world indices — the same recipe spawns
  cleanly at any world position.

## See also

- [`dynamics.md`](dynamics.md) — the body / joint / world layer
  the prefabs materialise into.
- [`ui_editor.md`](ui_editor.md) — the notebook-editor spawn menu +
  spawn-card widget that consume :class:`PrefabLibrary` and
  :class:`PreviewBaker`.
- [`ui_theme.md`](ui_theme.md) — the notebook theme palette family
  :data:`DIARY_PALETTE` pairs with.
- [`../feature_map_2026_06_03.md`](../feature_map_2026_06_03.md) —
  spawn menu + prefab library row in the engine feature map.
