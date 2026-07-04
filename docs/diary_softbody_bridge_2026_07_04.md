# Diary Softbody Import — Investigation + Shim (AA3)

*Filed 2026-07-04 by AA3 scrum agent for the AA-batch retry sprint.
Baseline: `docs/feature_map_delta_2026_07_04.md` (Y-batch delta —
rows 80 + 223 still flagged **BROKEN**).*

---

## 1. The bug in one paragraph

`python/slappyengine/ui/editor/notebook_diary_page.py::NotebookDiaryPage.tick`
runs a per-tick `from slappyengine.softbody import step as softbody_step`
after checking `stage.softbody is not None`. On a **fresh checkout of
master**, `slappyengine.softbody` does not exist — the entire
`python/slappyengine/softbody/` tree is uncommitted WIP (see `git
status`; `git ls-files` returns 0 rows for that path). The import raises
`ImportError`, `tick` catches it via `_record_exception`, and the diary
runner reports the exception to the status bar every frame. Row 80 is
therefore recorded as **BROKEN** in `docs/engine_feature_map_2026_07_04.md`.

Row 223 (`engine.open_diary_picker` hook) is a separate no-op path but
is tracked together with row 80 by the feature map because both cliffs
show up on "Run Diary" and "Open Diary" respectively. This document
covers row 80 (the softbody import); row 223 is out of scope for AA3.

## 2. Exact STUB callsite

```
python/slappyengine/ui/editor/notebook_diary_page.py:609-611
    if stage.softbody is not None:
        from slappyengine.softbody import step as softbody_step
        softbody_step(stage.softbody)
```

The symbol being imported is `slappyengine.softbody.step` — a
module-level function that advances one softbody-world tick. A second
call site at `notebook_diary_page.py:539` calls
`studio.softbody_stage()`, which internally does
`from .softbody import (SoftBodyRenderConfig, SoftBodyRenderer,
SoftBodyWorld)`. The same ImportError surfaces there as well, but is
caught inside `_start_script` via `_record_exception`, so at least the
message lands in the status bar cleanly and no diary tick ever runs.

## 3. Does `slappyengine.softbody` exist on tracked master?

**No.** Cross-checks:

* `git ls-files python/slappyengine/softbody/` — 0 rows.
* `git log --all --oneline -- python/slappyengine/softbody/__init__.py`
  — 0 commits (never tracked).
* Directory contents on disk are WIP-only (`__init__.py`, `beam.py`,
  `body_builders.py`, `collision.py`, `material.py`, `node.py`,
  `render.py`, `solver.py`, `vehicle.py`, `world.py`), all uncommitted
  and pinned read-only by the AA-batch sprint plan.

## 4. Tracked alternative

`slappyengine.dynamics` is fully tracked, imported by 25+ tests
(`test_dynamics_*`), and exposes the exact surface the diary needs:

| Diary need | Tracked substitute |
|------------|---------------------|
| Softbody world constructor | `slappyengine.dynamics.SoftBodyWorld` (alias for `dynamics.World`) |
| Per-tick step | `world.step(dt)` (method, not module-level) |
| Body handle | `slappyengine.dynamics.Body` (dataclass) |
| Body serialisation | `slappyengine.dynamics.body_from_dict` / `body_to_dict` |
| Full-world serialisation | `slappyengine.dynamics.load_world` / `world_from_dict` |

The dynamics `SoftBodyWorld` is XPBD-based (not the same lattice as the
WIP `slappyengine.softbody`), but for the diary "run script + step one
world" use-case they're interchangeable: the diary tick only needs a
world with a `.step(dt)` method, which both types satisfy.

## 5. Recommended fix

Ship a small bridge module at `python/slappyengine/ui/editor/diary_softbody_bridge.py`
with two functions:

1. **`resolve_softbody_class()`** — try `slappyengine.softbody.SoftBodyWorld`
   first (so a wheel-shipped or installed engine keeps working), then
   fall back to `slappyengine.dynamics.SoftBodyWorld`. Raise a friendly
   `ImportError` naming both paths only if both fail.

2. **`import_softbody_file(path, world)`** — read a `.softbody.yaml` or
   `.softbody.json` file describing a single body, decode it via
   `slappyengine.dynamics.body_from_dict` when possible (JSON), or a
   minimal YAML loader otherwise, and register it into `world` via
   `world.register_body` (dynamics) or `world.bodies.append` (softbody
   duck-type fallback). Return the registered body.

The bridge is **stand-alone** — it does not patch the diary panel
directly, since `notebook_diary_page.py` is pinned read-only by the AA3
sprint constraints. Once the next un-pinned diary sprint lands, the
per-tick import at line 610 can be replaced with a single call to
`diary_softbody_bridge.step_stage(stage)` (a thin helper that dispatches
between `world.step(dt)` and the legacy `softbody.step(world)`
signature) with no other diary-side change.

**Status flip preview**: after the diary panel is un-pinned and the two
call sites (line 539 for stage construction, line 610 for the tick
step) are rewired through this bridge, rows 80 and 223 in
`docs/engine_feature_map_2026_07_04.md` can be flipped from **BROKEN**
to **WIRED** on the next delta re-audit.

## 6. Deferred scope

This ticket **does not**:

* Modify `notebook_diary_page.py` (pinned read-only).
* Modify `python/slappyengine/softbody/` (uncommitted WIP; pinned).
* Modify `python/slappyengine/studio.py` (would flip several other
  diary paths — larger blast radius; deferred to a subsequent sprint).
* Flip rows 80/223 in the feature map (defer to the sprint that
  actually rewires the two diary call sites).

What we **do** ship in this ticket:

* This investigation doc.
* `diary_softbody_bridge.py` shim (2 public functions + 1 helper).
* 8 tests in `SlapPyEngineTests/tests/test_diary_softbody_bridge.py`
  covering both resolve paths, the friendly-error path, and end-to-end
  file import for `.softbody.yaml` and `.softbody.json`.

## 7. Test surface

The test file targets 8 named test cases:

1. `resolve_softbody_class` returns a callable on any-path-works.
2. `resolve_softbody_class` prefers `slappyengine.softbody` when both
   present.
3. `resolve_softbody_class` falls back to `slappyengine.dynamics` when
   the softbody path is missing.
4. `resolve_softbody_class` raises a friendly `ImportError` naming both
   paths when both are absent.
5. `import_softbody_file` round-trips a `.softbody.json` fixture.
6. `import_softbody_file` round-trips a `.softbody.yaml` fixture.
7. `import_softbody_file` raises `FileNotFoundError` for a missing
   path.
8. `import_softbody_file` raises `ValueError` for a wrong-extension
   path.

*End of investigation.*
