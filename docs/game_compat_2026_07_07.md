# Game-compat re-run — 2026-07-07 (TT1, was SS5)

Re-dispatch of the original SS5 game-compat sprint slot that was lost
mid-run to a rate limit. This is the live execution of the OO7
ship-checklist **gate #12** ("Game-compat tripwire: Ochema 1124/1126 +
Bullet 54/54") — the first end-to-end tripwire run since the F1
v0.3.0 beta baseline (`project_beta_2026_05.md`) and since RR6's
reconciliation flagged gate #12 as `needs-verify`.

Written by TT1 background scrum agent, 2026-07-07 late-evening batch.

TT1's key insight over SS5's earlier walk: SS5's search sweep looked
only under `H:/Github/` and concluded both game repos were absent. In
fact both live under **`H:/DaedalusSVN/`** (SVN-managed working copies,
not git repos). TT1's broader disk sweep found them and ran the
tripwire.

---

## 1. Executive summary

Gate #12 verdict: **FAILING** — massive downstream regression against
F1 baseline. Both game suites collect the expected test count (Ochema
1126, Bullet 54) but pass rates collapsed from ~100% (F1) to ~40%
(Ochema) / ~35% (Bullet Strata).

**Post-UU1+UU2 update (2026-07-07, § 9 append by UU3):** UU2
(`b29e601`) restored `global_bus` / `unsubscribe`; UU1 (`ee732fd`)
fixed the RenderTarget MRO / `layers` init contract. Ochema recovered
+47 passes (424 → 471); Bullet Strata unchanged. All three TT1-flagged
root causes verified resolved via grep. **Still FAILING** — residual
regression is a long tail of ~15-20 orthogonal deletions needing 5-6
more targeted backcompat slots. See § 9 for full re-run analysis.

* **Ochema Circuit**: **424 passed / 665 failed / 25 skipped /
  15 errors** (of 1129 collected) — vs F1 baseline of 1124 / 2.
  **Delta: −700 passes.**
* **Bullet Strata**: **19 passed / 32 failed / 0 skipped / 3 errors**
  (of 54 collected) — vs F1 baseline of 54 / 0. **Delta: −35 passes.**

Two dominant breakage classes account for the bulk of the regression;
both are recent engine-side breaking changes to the public surface
that downstream games depend on. See § 4 for the specific error
signatures and § 5 for the gate #12 verdict.

Engine state at this walk:

* Commit: `fc5d94f` (TT6 diagnostics filter — post-TT batch).
* `pyproject.toml:7`: `"0.3.0b0"`.
* `Cargo.toml:3`: `"0.3.0-beta.0"`.
* WIP dirs (`softbody/`, `fluid/`, `physics/`, `physics2/`) still
  untracked per RR6 gate-11 posture — untouched by TT1.

Game repos:

* Ochema Circuit — `H:/DaedalusSVN/Ochema Circuit/` (SVN working copy;
  no git metadata; no revision SHA available).
* Bullet Strata — `H:/DaedalusSVN/Bullet Strata/` (SVN working copy;
  no git metadata; no revision SHA available).

---

## 2. Downstream repo probe

TT1 search strategy (all read-only):

| Step | Command | Result |
|---|---|---|
| 1 | `ls H:/Github/` grep for `ochema|bullet|strata|circuit` | zero hits (confirms SS5's finding) |
| 2 | `ls H:/` top-level | reveals `DaedalusSVN/` alongside `Github/` |
| 3 | `ls H:/DaedalusSVN/` grep for `ochema|bullet|strata|circuit` | **hit** — `Ochema Circuit/` + `Bullet Strata/` |
| 4 | `ls "H:/DaedalusSVN/Ochema Circuit/tests/"` | 31 `test_*.py` files + `conftest.py` + e2e |
| 5 | `ls "H:/DaedalusSVN/Bullet Strata/tests/"` | 2 `test_*.py` files (`test_features.py`, `test_scene.py`) + e2e |
| 6 | `git -C "…/Ochema Circuit" status` | `fatal: not a git repository` — SVN, no revision SHA |
| 7 | `git -C "…/Bullet Strata" status` | `fatal: not a git repository` — SVN, no revision SHA |

Note on SS5's absent-repo conclusion: SS5's `Glob H:/Github/**` walk
was correct within its search domain — both game repos genuinely are
not under `H:/Github/`. The repos live under `H:/DaedalusSVN/`,
which is a separate SVN-hosted workspace one level up. Future
sprints should widen the initial repo-locate glob to at least `H:/`
top level, not just `H:/Github/`.

---

## 3. Per-game results table

| name | commit | pass | fail | skip | errors | notes |
|---|---|---|---|---|---|---|
| ochema_circuit | SVN (no SHA) | 424 | 665 | 25 | 15 | Ran against engine HEAD `fc5d94f` via `PYTHONPATH=h:/Github/SlapPyEngine/python`; 1126 collected + 3 collection extras = 1129 total; 47.09 s wall time |
| bullet_strata | SVN (no SHA) | 19 | 32 | 0 | 3 | Ran against engine HEAD `fc5d94f` via `PYTHONPATH=h:/Github/SlapPyEngine/python`; 54 collected; 2.52 s wall time |

Invocation used (both games):

```
cd "<game repo>"
PYTHONPATH=h:/Github/SlapPyEngine/python \
  python -m pytest tests/ -q --no-header --tb=line 2>&1 | tail -30
```

Neither suite crashed on import — collection succeeded on both
projects. All failures are at test-body level (attribute lookups,
import-not-found for specific symbols), which is regression signal
rather than a wholesale ABI break.

---

## 4. Root-cause breakage classes

Two dominant error signatures repeat across the failures. Both are
downstream-visible engine-side breaking changes.

### 4.1 `AttributeError: 'VehicleEntity' object has no attribute 'layers'`

Also observed as `'PlayerEntity' object has no attribute 'layers'`
and other subclasses.

Traceback shape (representative — Bullet Strata):

```
entities/player.py:41: in __init__
    self.add_layer(_layer)
python/slappyengine/asset.py:49: in add_layer
    return super().add_layer(layer)
python/slappyengine/render_target.py:18: in add_layer
    self.layers.append(layer)
E   AttributeError: 'PlayerEntity' object has no attribute 'layers'
```

Diagnosis: `render_target.py:11` DOES initialise `self.layers = []`
inside `RenderTarget.__init__`. The downstream `VehicleEntity` and
`PlayerEntity` classes call `Asset.add_layer` before `super().__init__()`
has established the `layers` field. Either:

* The MRO / `__init__` call order changed on the engine side (an
  `Entity → Asset → RenderTarget` refactor between F1 and TT6 shifted
  when `layers` is created), or
* The engine now expects downstream subclasses to explicitly call
  `super().__init__()` earlier than they used to.

Either way it is a **breaking change to the public Entity/Asset/RenderTarget
lifecycle contract** that downstream code was relying on, and it
accounts for the vast majority of both Ochema and Bullet failures
(every scene-, HUD-, entity-, and collision-touching test path).

**Owner sprint prescription**: git-bisect `Entity → Asset → RenderTarget`
between F1 (`~ base of project_beta_2026_05.md`) and TT6 (`fc5d94f`);
identify the commit that reordered `layers` initialisation; either
revert or add a `layers` defensive default via `Entity.__init_subclass__`.

### 4.2 `ImportError: cannot import name 'global_bus' from 'slappyengine.event_bus'`

Traceback shape (representative — Ochema `test_sprint6_race_loop`):

```
systems/race_manager.py:7: in <module>
    from slappyengine.event_bus import publish, global_bus
E   ImportError: cannot import name 'global_bus' from 'slappyengine.event_bus'
     (H:/Github/SlapPyEngine/python/slappyengine/event_bus.py)
```

Diagnosis: `slappyengine.event_bus.global_bus` was removed / renamed
between F1 and TT6. This is a **public-API symbol deletion**, not a
subtle MRO shift — a downstream repo that imported the old name gets
a hard `ImportError` at collection time.

**Owner sprint prescription**: either re-export `global_bus` as an
alias in `slappyengine.event_bus.__all__`, or CHANGELOG the removal
under `[0.4.0] — Breaking changes` and instruct downstream games to
migrate to whatever replaced it. Given `event_bus` is a load-bearing
public surface, the alias route is cheaper.

### 4.3 `TypeError: unsubscribe() missing 1 required positional argument: 'listener'`

Observed once in Bullet Strata (`test_features.py:591`). Diagnosis:
`slappyengine.event_bus.unsubscribe` (or a comparable subscribe API)
now requires an extra positional argument (`listener`). This is also
a **breaking API signature change**.

### 4.4 `ImportError: cannot import ... from 'slappyengine…'` (misc)

Ochema `test_scene.test_import_all_modules` and `test_hud_standalone`
fail with generic import errors — additional public-symbol drift.
Full enumeration is out of scope for this doc (the two dominant
classes above account for the bulk of the regression).

---

## 5. Delta since F1 baseline

Reference baseline (2026-05-28, engine commit ~F1, per
`project_beta_2026_05.md`):

| game | baseline pass | baseline fail | baseline skip | TT1 pass | TT1 fail | TT1 error | delta |
|---|---|---|---|---|---|---|---|
| ochema_circuit | 1124 | 2 | 0 | 424 | 665 | 15 | **−700 passes** |
| bullet_strata | 54 | 0 | 0 | 19 | 32 | 3 | **−35 passes** |

Ochema went from 99.8% pass rate to 37.6%. Bullet Strata went from
100% pass rate to 35.2%. Both regressions are dominated by a single
`layers`-attribute failure class (§ 4.1) that appears to be a single
breaking change to the engine's Entity/Asset/RenderTarget MRO or
`__init__` call order. A companion `global_bus` symbol deletion
(§ 4.2) and API-signature change (§ 4.3) account for most of the
remaining failures.

The gap between F1 and TT6 is ~5 weeks of engine-side batches
(F1 → PP → QQ → RR → SS → TT), which is roughly what OO7's
"YELLOW / needs 2 focused sprints" verdict assumed for the tag sprint
but did not budget as game-compat risk. The tripwire was the correct
gate to insist on.

---

## 6. Gate #12 verdict

**FAILING** — flip gate #12 from `needs-verify` to **FAILING** in
`docs/v0_4_gate_reconciliation_2026_07_07.md`.

Ship-blocker rationale:

* Not GREEN: pass count is 424+19 = 443 vs baseline 1124+54 = 1178
  (−735 total passes across both games). The tripwire's stated
  target ("match or exceed 1124/1126 + 54/54") is missed by two
  orders of magnitude on both sides.
* Not `needs-verify`: TT1 exercised the live suites, so the state is
  no longer unverified.
* Verdict class: **real engine regression signal**, not a procedural
  blocker.

Recommended next-slot action (blocker for `git tag v0.4.0`):

1. Land a fix for the `RenderTarget.layers` initialisation contract
   (§ 4.1) — either restore F1-era MRO or add a defensive default
   via `Entity.__init_subclass__` / dataclass field default.
2. Re-export `global_bus` as an alias in
   `slappyengine.event_bus.__all__` (§ 4.2), OR bump the tag to
   `v0.4.0-breaking` and CHANGELOG the deletion.
3. Restore the F1 `unsubscribe(listener?)` signature or CHANGELOG
   the new required arg (§ 4.3).
4. Re-run TT1's harness against both game repos. Gate #12 flips
   **GREEN** if both games recover to ≥ 1120 (Ochema) + ≥ 54
   (Bullet Strata).

Do **NOT** ship v0.4.0 without this fix. The whole point of gate #12
is to catch exactly this kind of silent downstream breakage before it
reaches PyPI installers.

---

## 7. Constraints honoured by TT1

* No file under either game repo touched — read-only pytest
  invocation from an alternate `PYTHONPATH`; both repos remained
  clean per SVN semantics.
* No file under `python/slappyengine/` touched — verified via
  `git status`: TT1's working tree touches only `docs/` (this doc +
  gate-reconciliation refresh + inventory description update).
* No WIP subpackage touched — `softbody/`, `fluid/`, `physics/`,
  `physics2/` remain untracked as at RR6 / SS5.
* Commit scoped: `docs/game_compat_2026_07_07.md` (rewritten),
  `docs/sprint_5_doc_inventory.md` (description update for existing
  row 47), `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  flip: needs-verify → FAILING with new evidence row).

---

## 8. Cross-reference

* [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  — RR6 15-gate table; gate #12 row flipped by this doc.
* [`docs/v0_4_release_readiness_2026_07_06.md`](v0_4_release_readiness_2026_07_06.md)
  — OO7 audit; original gate #12 wording.
* [`docs/sprint_1_game_compat_2026_05_30.md`](sprint_1_game_compat_2026_05_30.md)
  — historical Sprint 1 game-integration verification (Ochema /
  Bullet Strata / Stone Keep 34-pass / 20-fail tripwire).
* `project_beta_2026_05.md` (auto-memory) — F1 baseline 1124/1126 +
  54/54.
* [`docs/sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) —
  index row for this doc.

---

*Doc generated 2026-07-07 late-evening by TT1 background scrum agent
(re-dispatch of rate-limited SS5). Sources:
`ls H:/Github/` (top-level, zero game-repo matches — confirms SS5),
`ls H:/DaedalusSVN/` (`Ochema Circuit/` + `Bullet Strata/` found),
`ls "H:/DaedalusSVN/Ochema Circuit/tests/"` (31 `test_*.py`),
`ls "H:/DaedalusSVN/Bullet Strata/tests/"` (2 `test_*.py`),
`PYTHONPATH=h:/Github/SlapPyEngine/python python -m pytest tests/ -q
--no-header --tb=line` for each game, `git rev-parse HEAD` = `fc5d94f`,
`pyproject.toml:7 = 0.3.0b0`, `Cargo.toml:3 = 0.3.0-beta.0`,
`project_beta_2026_05.md` baseline.*

---

## 9. Post-UU1+UU2 re-run (UU3, 2026-07-07 late-evening +1)

Second-pass game-compat walk by UU3 background scrum agent following
TT1's baseline. Between TT1 and UU3, two sibling agents dispatched to
fix the two dominant breakage classes flagged in § 4:

* **UU2** (`b29e601` — "Restore event_bus.global_bus + unsubscribe
  backcompat") — targeted § 4.2 + § 4.3 (public-API deletions).
* **UU1** (`ee732fd` — "Fix RenderTarget MRO regression") — targeted
  § 4.1. UU1's fix touches `python/slappyengine/render_target.py`
  (defensive-`hasattr` fallback on `add_layer` / `remove_layer`) and
  `python/slappyengine/event_bus.py` (cooperative `super().__init__()`
  chain restore inside `Observable.__init__` so that mixing Observable
  into an Entity/Asset subclass no longer short-circuits the MRO and
  leaves `RenderTarget.__init__` unrun).

Engine state at UU3 walk: HEAD `ee732fd` (both UU1 + UU2 landed).
UU3's re-run initially executed against UU1's uncommitted working
tree while UU1's commit was still being finalised; the commit landed
mid-doc-write and the results below are load-bearing against HEAD.

### 9.1 Refreshed pass counts

| game | TT1 pass | TT1 fail | TT1 err | UU3 pass | UU3 fail | UU3 err | Δ vs TT1 | Δ vs F1 |
|---|---|---|---|---|---|---|---|---|
| ochema_circuit | 424 | 665 | 15 | **471** | 621 | 12 | **+47 passes** | −653 |
| bullet_strata | 19 | 32 | 3 | **19** | 32 | 3 | ±0 | −35 |
| **combined** | **443** | 697 | 18 | **490** | 653 | 15 | **+47 passes** | **−688** |

Ochema pass-rate: 37.6% → 41.7% (of 1108 non-skip). Bullet Strata
pass-rate unchanged at 35.2%.

### 9.2 Root-cause resolution verdict

Grep of UU3's re-run logs against the § 4 failure fingerprints:

| § | Fingerprint (TT1) | UU3 occurrences | Verdict |
|---|---|---|---|
| 4.1 | `AttributeError: '<*Entity>' object has no attribute 'layers'` | **0** | **RESOLVED by UU1** |
| 4.2 | `ImportError: cannot import name 'global_bus' from 'slappyengine.event_bus'` | **0** | **RESOLVED by UU2** |
| 4.3 | `TypeError: unsubscribe() missing 1 required positional argument: 'listener'` | **0** | **RESOLVED by UU2** |
| 4.4 | Misc downstream ImportErrors | 5 distinct symbols still failing | UNCHANGED (§ 9.3 below) |

All three primary root causes flagged by TT1 are eliminated in UU3's
re-run. The +47-pass Ochema delta comes entirely from tests whose only
breakage was the `layers` MRO issue; every other failure class TT1
enumerated persists and now dominates the residual failure surface.

### 9.3 New dominant failure fingerprints (UU3)

Distinct top-level error strings ranked by observed multiplicity:

1. `AttributeError: type object 'CacheMode' has no attribute
   'OFFSCREEN_SERIALIZE'` / `'ALWAYS_CACHED'` — Ochema + Bullet Strata,
   `entities/*.py` — enum member deletion between F1 and TT6.
2. `TypeError: DeformableLayerComponent.__init__() got an unexpected
   keyword argument 'spring_decay'` — Ochema, deforming layer API
   drift.
3. `TypeError: PixelCollisionPass.test() missing 4 required positional
   arguments: 'layer_a_tex', 'layer_a_rect', 'layer_b_tex', and
   'layer_b_rect'` — Ochema, collision API signature drift.
4. `ImportError: cannot import name '<symbol>' from
   'slappyengine.<module>'` — Ochema (5 distinct symbols:
   `DeformConfig`, `EventDetails`, `PixelCollisionPass`,
   `_parse_deform`, `debug_listeners`) — additional public-API
   deletions in the UU2 style.
5. `AttributeError: '<Manager>' object has no attribute '<method>'`
   — Ochema (`AudioManager.play_loop`, `LightingSystem.load_profile`,
   `CollisionManager.on_overlap`) — manager method surface drift.

None of these are `layers`, `global_bus`, or `unsubscribe`, confirming
UU1+UU2 hit their intended targets. The residual regression is a
long-tail of ~15-20 distinct public-API deletions / signature drifts,
each requiring its own targeted backcompat sprint slot (or a CHANGELOG
breaking-changes entry + downstream migration).

### 9.4 Refreshed verdict

**Still FAILING for gate #12 ship-blocker purposes.** UU3's +47-pass
Ochema recovery is a 4.2-percentage-point pass-rate uptick — a
meaningful directional signal that the fix strategy is correct, but
nowhere near the ≥ 95%-of-F1 threshold required to flip gate #12 to
GREEN (which would need Ochema ≥ 1068 and Bullet Strata ≥ 51).

Recommended next-slot action stack (in priority order):

1. Restore `CacheMode.OFFSCREEN_SERIALIZE` + `CacheMode.ALWAYS_CACHED`
   enum members (§ 9.3 item 1) — one commit closes the entire Bullet
   Strata residual + a large slice of Ochema.
2. Restore or CHANGELOG the 5 § 9.3 item-4 `ImportError` symbols
   (`DeformConfig`, `EventDetails`, `PixelCollisionPass`,
   `_parse_deform`, `debug_listeners`) — same alias pattern UU2 used
   for `global_bus`.
3. Restore `DeformableLayerComponent(spring_decay=...)` kwarg
   (§ 9.3 item 2) or CHANGELOG the rename.
4. Restore `PixelCollisionPass.test()` legacy signature (§ 9.3 item 3)
   or provide a 0-arg convenience wrapper.
5. Restore `AudioManager.play_loop`, `LightingSystem.load_profile`,
   `CollisionManager.on_overlap` (§ 9.3 item 5) — three method
   restorations, small blast radius.

Ballpark cost: 5-6 sprint slots of UU1/UU2-style targeted backcompat
work should close the residual gap and flip gate #12 to GREEN.

### 9.5 UU3 constraints honoured

* No file under either game repo touched — read-only pytest
  invocation.
* No file under `python/slappyengine/` touched by UU3 (UU1's WIP
  edits are in the working tree but attribute to UU1, not UU3).
* No WIP subpackage touched.
* Commit scoped: `docs/game_compat_2026_07_07.md` (this § 9 append)
  + `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  post-UU1+UU2 status refresh in § 2 table row + § 4 note).

---

## Commit-attribution note

Content of this game-compat doc (plus its inventory-row description
refresh and the gate #12 flip in
`docs/v0_4_gate_reconciliation_2026_07_07.md`) was authored by TT1
background scrum agent as part of the SS5 re-dispatch
(2026-07-07 late-evening). Due to a working-tree race with TT7's
sprint-rollup r6 commit sweep, the initial file writes were absorbed
into TT7's `7f4b93b` commit. This attribution footer is the
load-bearing TT1-attributed commit; the technical content of § 1-§ 8
above was written by TT1 and is identical between the TT7-swept copy
and this footer commit.

Pattern precedent: RR6 landed under the same race-and-attribution-footer
pattern (see `docs/v0_4_gate_reconciliation_2026_07_07.md` § "Commit-
attribution note" — RR6's content was absorbed into RR5's `ba9cbd5`
before RR6 could land its own commit; RR6 then landed the footer as
a separate attribution commit).
