# API stability contract & backcompat harness — 2026-07-07 (UU7)

Owner: agent UU7 (parallel-sprint), 2026-07-07.

Sibling to [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
(TT1 game-compat re-run) — TT1 caught three silent breaking changes
that engine-side tests never tripped; this doc records the harness that
prevents recurrence.

Sibling owners: UU1 (RenderTarget MRO fix) + UU2 (event_bus API
restoration) land the actual API repairs. UU7 only adds the harness
that would have caught the drift.

---

## 1. What TT1 uncovered

Between the F1 v0.3.0 beta baseline (2026-05-28) and TT6 (2026-07-07,
commit `fc5d94f`), three public-surface breaks slipped past every
engine-side test:

| # | Break | Downstream cost |
|---|---|---|
| 1 | `RenderTarget.__init__` MRO shift — subclass `add_layer` before base init raised `AttributeError: 'layers'`. | ~665 Ochema + ~32 Bullet Strata test fails. |
| 2 | `slappyengine.event_bus.global_bus` symbol removed. | Every downstream module that did `from slappyengine.event_bus import global_bus` failed at import. |
| 3 | `EventBus.unsubscribe(event_type, callback)` began requiring two args. | Legacy 1-arg `bus.unsubscribe("topic")` in game code raised `TypeError`. |

Common root cause: engine tests never exercise **downstream subclass
patterns** or **module-level symbol presence**. The changes look clean
in-tree but tripwire externally.

---

## 2. The backcompat harness (this doc's payload)

Two paired test files plus a snapshot lock-file:

* [`SlapPyEngineTests/tests/test_backcompat_api_surface.py`](../SlapPyEngineTests/tests/test_backcompat_api_surface.py)
  — pins every public symbol on 14 load-bearing modules against a
  snapshot; deletions fail loudly, additions warn.
* [`SlapPyEngineTests/tests/test_backcompat_subclass_patterns.py`](../SlapPyEngineTests/tests/test_backcompat_subclass_patterns.py)
  — exercises the "subclass abuse" patterns downstream games actually
  use: `add_layer` before / after / instead-of `super().__init__()`,
  override + super delegation, extra-positional-kwarg subclass
  signatures, script tick after subclass re-init.
* [`SlapPyEngineTests/tests/data/api_surface_snapshot.json`](../SlapPyEngineTests/tests/data/api_surface_snapshot.json)
  — locked snapshot; 338 public symbols across the 14 modules at time
  of freeze.

Pinned modules (14):

```
slappyengine                      slappyengine.event_bus
slappyengine.entity               slappyengine.layer
slappyengine.render_target        slappyengine.asset
slappyengine.app                  slappyengine.dynamics
slappyengine.physics3_bridge      slappyengine.diagnostics
slappyengine.hud_bridge           slappyengine.audio_3d
slappyengine.capture              slappyengine.exporter
```

The 14-module cut is the set called out in the UU7 sprint spec.
Extension is trivial — add module names to `MODULES` in
[`scripts/refresh_api_surface_snapshot.py`](../scripts/refresh_api_surface_snapshot.py)
and re-run the refresh.

### 2.1 What "public surface" means

For every module *except* the top-level `slappyengine` package:

> Every module-level name that does not start with `_`. Same set as
> would be visible to `from mod import *` if `__all__` were absent.

For the `slappyengine` package itself:

> The contents of `__all__`. Necessary because the package uses PEP 562
> lazy-load (`__getattr__`) and `dir()` doesn't enumerate un-touched
> lazy names.

### 2.2 Failure signals

| Signal | Meaning | Fix |
|---|---|---|
| `pytest test_no_public_symbol_deleted[<mod>]` fails | A pinned symbol was deleted or renamed. | Either restore the symbol / add a deprecation alias, or if the removal is intentional, follow § 3 deletion policy. |
| `pytest test_new_symbols_are_informational` emits `UserWarning` | The API grew since the snapshot. | Optional: refresh the snapshot to lock the new surface (see § 3). |
| `pytest test_snapshot_total_symbol_count_reasonable` fails | The snapshot fell below 250 symbols. | Almost certainly a bad snapshot commit — regenerate against a healthy build. |
| Any subclass-pattern test fails | A subclass MRO / init-order regression landed. | Same class as break #1 — restore the defensive path in the base class. |

---

## 3. Deletion policy for v0.4+

Removing a symbol from a pinned module requires **all three** of:

1. A CHANGELOG entry naming the deleted symbol under a
   `Breaking changes` heading in the release notes for the next
   minor version.
2. One minor-version deprecation cycle: the symbol must first ship
   with a `warnings.warn(..., DeprecationWarning)` shim for at least
   one full minor version before the actual removal.
3. A refresh of the snapshot lock-file via:

   ```
   python scripts/refresh_api_surface_snapshot.py
   ```

   ...committed alongside the removal in the same PR. The script
   prints the exact per-module add/remove diff so reviewers can
   sanity-check what was pinned or unpinned.

Renames count as delete-plus-add and must follow the same three
gates. Additions are unrestricted — the harness treats them as
informational.

### 3.1 What is NOT covered

The harness pins *names*, not *signatures*. A function whose
signature changes in a breaking way (e.g. TT1 break #3, `unsubscribe`)
will not be caught by the surface test. Signature stability is
policed by:

* the paired subclass-pattern test file for the small set of
  MRO / init-order patterns, and
* end-to-end game-compat runs against Ochema Circuit + Bullet
  Strata per the gate #12 tripwire in
  [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md).

A future sprint can add signature pinning (e.g. `inspect.signature` +
snapshot) if TT-class regressions continue to happen at the argument
level. UU7 scoped only to name-level pinning + the subclass-pattern
sample, per the sprint spec.

---

## 4. Cross-references

* [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md) — TT1
  game-compat re-run that motivated this harness.
* [`docs/engine_surface_v030.md`](engine_surface_v030.md) — the
  hand-authored v0.3 top-level surface reference (91 names). The
  harness's `slappyengine` entry pins the same set plus HH1 App +
  OO6 diagnostics.
* [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  — v0.4 ship gates; gate #12 (game-compat) motivates this harness.
* [`SlapPyEngineTests/tests/test_ochema_api_surface.py`](../SlapPyEngineTests/tests/test_ochema_api_surface.py)
  — narrower race-scene tripwire that predates this doc. Kept
  separately because it exercises *lazy-load* resolution (does
  `slappyengine.CatmullRomSpline` still resolve?) which is orthogonal
  to the module-scan approach here.
* [`SlapPyEngineTests/tests/test_event_bus_backcompat.py`](../SlapPyEngineTests/tests/test_event_bus_backcompat.py)
  — pre-existing event_bus-specific tripwire.

---

## 5. Operator recipes

**When adding a new public symbol** — do nothing. The harness will emit
a `UserWarning` on next test run. Refresh the snapshot when convenient
(preferably in the same PR as the addition) to lock the new surface.

**When intentionally removing a symbol** — follow § 3 deletion policy:
CHANGELOG + one deprecation cycle + snapshot refresh.

**When accidentally breaking a game-compat contract** — the harness
fails the specific parametrized case; the message tells you exactly
which module and which pinned names went missing. Restore or
re-alias.

**When adding a new load-bearing module to pin** — add its name to
`MODULES` in `scripts/refresh_api_surface_snapshot.py`, run the
refresh, and add the module to the required-coverage set in
`test_snapshot_covers_declared_modules` inside
`test_backcompat_api_surface.py`.

---

*Doc landed 2026-07-07 by agent UU7 as part of the sibling UU1 + UU2
+ UU7 API-stability sprint. UU1/UU2 fix the specific TT1 breaks;
UU7 adds the tripwire that prevents the next such class of drift.*
