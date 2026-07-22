# Core Engine Module Audit — 2026-06-02

Read-only survey of `python/pharos_engine/` after two weeks of 7-agent sprint
work, plus one small structural fix. Scope: top-level `__init__.py` shape,
legacy compat-routed symbol usage, discoverability via `help()`, and drift
between `docs/api/*.md` and the actual subpackage `__all__` lists.

Per task constraints, `softbody/` and `fluid/` were NOT inspected and not
modified.

## 1. Top-level `__init__.py` audit

### 1a. Is the lazy-map still needed for every symbol?

**Yes** — the lazy-map is structurally load-bearing for two reasons:

1. The wheel ships a Rust `_core` extension and many top-level symbols
   transitively import `wgpu` or other heavy native deps. Eager-loading
   them would push `import pharos_engine` past a useful budget for CLI
   tooling (`slappy docs_gen`, etc.).
2. The `_LAZY_MAP` is also the contract surface that
   `SlapPyEngineTests/tests/test_init_lazy_map.py` and `SlapPyEngineTests/tests/test_game_compat_tripwire.py`
   walk to guarantee compat for Ochema Circuit / Bullet Strata / Stone Keep.

There is no reason to flatten or eager-load it. It is doing the work it
exists to do.

### 1b. Legacy `_compat`-routed symbols — are they actually used?

Tracked-master ripgrep for direct `from pharos_engine import X` /
`pharos_engine.X` references (excluding `.claude/worktrees/**` and the
symbols' own definition / `_compat` / `__init__.py` sites):

| Symbol               | Direct top-level callers on master                | Verdict                |
|----------------------|---------------------------------------------------|------------------------|
| `MaterialPreset`     | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `CrackMode`          | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `SimState`           | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `SimFrequencyBudget` | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `DeformController`   | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `ZoneMap`            | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `CellMaterial`       | 0 direct `from pharos_engine` imports              | **compat surface only** |
| `cell_material_for`  | 0 direct `from pharos_engine` imports              | **compat surface only** |

**But every one of these symbols is exercised by**:

- `SlapPyEngineTests/tests/test_game_compat_tripwire.py` — the multi-game tripwire walks each
  per-game contract and asserts the symbol resolves off `pharos_engine`.
  The Bullet Strata contract explicitly requires `MaterialPreset`,
  `ZoneMap`, `DeformController`, `SimFrequencyBudget`, `CrackMode`; the
  Ochema contract explicitly requires `SimFrequencyBudget`, `SimState`,
  `DeformController`.
- `SlapPyEngineTests/tests/test_game_smoke_instantiation.py` — parametrised test
  `test_missing_module_residual_gap` asserts each was historically a Phase C
  gap that "has been closed; removing it again would re-break game-team
  installs."
- `SlapPyEngineTests/tests/test_compat_cell_material.py` (CellMaterial / cell_material_for).
- `SlapPyEngineTests/tests/test_init_lazy_map.py` — pins the `ZoneMap is ZoneManager` alias.

**Conclusion**: zero deletions warranted today. The compat symbols are
zero-callers on master but the tripwire test makes their continued export
a ship requirement. Document for the next major version (1.0): when the
three flagship games migrate to canonical names (`zones.ZoneManager` etc.),
remove these from `_compat.py` together with the corresponding entries in
`_LAZY_MAP` and the three test files.

Recommended migration target labels (for the v1.0 changelog):

- `MaterialPreset.X` → bare string `"x"` against
  `softbody.material.MATERIALS`.
- `CrackMode` → retire (no replacement; feature removed Phase B).
- `SimState` / `SimFrequencyBudget` → retire (rebuild solver dispatches
  every step; no state machine, no budget allocator).
- `DeformController` → `softbody.body_builders.make_layered_creature`.
- `ZoneMap` → `pharos_engine.zones.ZoneManager` (mechanical rename).
- `CellMaterial` / `cell_material_for` → host on the physics subpackage
  itself once `deform_modes.py` is deleted.

## 2. Subpackage discoverability — `help(pharos_engine)`

**Before fix**: top-level docstring was a one-liner:

```
"""SlapPyEngine — compute-shader-driven 2D game engine."""
```

`help(pharos_engine)` listed the version + the lazy `__all__` symbols, but
**none of the 19 subpackages** showed up in any tour. A user typing
`help(pharos_engine)` had no way to discover `pharos_engine.studio`,
`pharos_engine.dynamics`, `pharos_engine.thermal`, or any of the other
subpackages without already knowing they exist.

**After fix** (this commit): the top-level module docstring now hosts a
sectioned tour with 21 subpackages grouped into Simulation / Rendering /
Authoring / Game-compat, plus a 5-line Quickstart and a Lifecycle Flags
note. See the file change to `python/pharos_engine/__init__.py`.

This is the structural fix landed by this commit (see §4).

## 3. Public-surface drift — `docs/api/*.md` vs `__all__`

Method: read each `docs/api/<subpackage>.md`, compare against the actual
`__all__` of `python/pharos_engine/<subpackage>/__init__.py` (or single-file
module).

| Subpackage     | Doc lists exports?       | Drift?                                                  |
|----------------|--------------------------|---------------------------------------------------------|
| `dynamics`     | Class-by-class reference | none material; doc covers all top-level `__all__` entries |
| `topology`     | Yes                      | clean (3 items match)                                   |
| `numerics`     | Yes                      | clean (3 items match)                                   |
| `zones`        | Yes                      | clean (3 items match)                                   |
| `thermal`      | Yes                      | clean (2 items match)                                   |
| `gi`           | Yes                      | clean (3 items match)                                   |
| `post_process` | Yes — calls out `cinematic_chain` / `arcade_chain` / `iso_strategy_chain` plus `__all__` | clean (all 11 items match) |
| `iso`          | Yes                      | clean (7 items match `__all__`)                         |
| `studio`       | Yes — `Stage`, `record`, 5 stage factories, 4 BodyMeta helpers, `terrain_overlay`, `output_path` | clean (13 items match) |
| `material`     | Yes                      | clean (17 items match)                                  |
| `compute`      | Yes                      | clean (9 items match — `__all__` and doc align)         |
| `audio_runtime`| Yes                      | clean (doc lists `AudioBackend` + `get_backend` as public; module has no `__all__` but doc is honest about that, listing both `_RealBackend` / `_StubBackend` / `_BACKEND` / `_STUB_WARNING` as "private but inspectable") |
| `ext`          | Module-by-module catalog | clean (9 items match `__all__`)                         |
| `gpu`          | Yes                      | clean (15 items match)                                  |
| `residency`    | Yes                      | clean — `__all__` exposes `ResidencyManager`, `CacheMode`, `SLAP_MAGIC`, `SLAP_VERSION`; doc covers all four |
| `telemetry`    | Yes                      | clean (9 items match)                                   |
| `testing`      | Yes                      | clean (5 items match)                                   |
| `animation`    | Yes                      | clean (6 items match)                                   |
| `ui_editor`    | Yes                      | clean (11 items match) — doc additionally calls out `SceneOutliner` + `SpawnMenu` as "module surface, not in `__all__`" which is accurate |

**Verdict: zero drift detected.** The hand-authored API docs in
`docs/api/` are accurate against current `__all__` lists. Whoever has been
running the sprint discipline on this has been keeping the docs and the
code aligned commit-by-commit. No follow-ups needed.

Two ancillary notes:

* `audio_runtime` has **no `__all__`** because it is a single file with
  one protocol + one accessor; the doc is honest about the `_Real` /
  `_Stub` / `_BACKEND` privacy contract. If a future commit grows the
  module past 2 public names, add `__all__ = ["AudioBackend", "get_backend"]`
  for symmetry with the other subpackages.
* `studio` `__all__` was alphabetised in a prior sprint; `dynamics`
  `__all__` is grouped by feature (joints, springs, motors, ropes,
  ragdolls, humanoids, IK, world, serialize) which reads better than alpha
  order — leave as-is.

## 4. Structural fix landed

**Pick**: rewrite `pharos_engine.__doc__` so `help(pharos_engine)` is
actually informative. This was the highest-value smallest fix from the
audit:

* zero behavioural change — pure docstring
* zero test risk — no module-level code modified
* directly addresses task #2 (subpackage discoverability)
* makes the README and `docs/architecture_overview.md` redundant for the
  "what is in this package" question — `pydoc pharos_engine` now answers it

The new docstring is ~95 lines and groups the 21 subpackages into:

* **Simulation** — softbody, fluid, dynamics, physics, thermal, topology,
  numerics, zones
* **Rendering + GPU** — gpu, gi, post_process, material, compute, residency
* **Authoring + tooling** — studio, iso, animation, ui (+ ui.editor),
  input, audio_runtime, testing, telemetry, tools, ext
* **Game-compat / misc** — modules, ai, assets, net

Plus a 5-line Quickstart snippet and a Lifecycle Flags note about
`HAS_NATIVE` and `engine_config`.

Verified by `python -c "import pharos_engine; print(len(pharos_engine.__doc__))"`
→ 4475 chars, no import error, no regression in `__all__`.

## 5. Forward-looking notes

* The `_LAZY_MAP` has a duplicate key — `"CacheMode": ".residency.manager"`
  appears at line 152 and again at line 192 of `__init__.py`. Harmless
  (Python dict-literal semantics: last write wins, both point to the same
  value), but worth tidying in a future sweep.
* `_LAZY_MAP` has a `"thermal"` entry that points to `.thermal` — but
  `thermal` is already in the `_subpackages` set in `__getattr__`. The
  lazy-map entry is dead code (the `_subpackages` fast-path returns first).
  Drop in a future cleanup commit.
* The compat tripwire ceiling is `_KNOWN_BROKEN_MAX = 20` with 20 entries
  currently — at the ratchet limit. The next dropped compat name would
  require either landing the underlying module or bumping the ceiling.
  Worth flagging on the v1.0 plan.

---

End of audit. Survey took ~30 minutes; the structural fix is a one-edit
docstring rewrite landing alongside this report in one commit.
