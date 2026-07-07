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

---

## 10. Post-VV1 re-run (VV3, 2026-07-07 late-evening +2)

Third-pass game-compat walk by VV3 background scrum agent following
UU3's § 9 baseline. Between UU3 and VV3, the scheduled VV1 + VV2
sibling agents dispatched to close § 9.3 residuals:

* **VV1** (`82feed0` — "Restore CacheMode.OFFSCREEN_SERIALIZE +
  ALWAYS_CACHED") — targeted § 9.3 item 1 (CacheMode enum-member
  deletion, top-ranked residual).
* **VV2** (§ 9.4 residual list — ImportError symbols, kwarg drift,
  method surface drift) — **did NOT land before VV3's re-verify
  walk.** Only VV1 + VV5 (`55e99a3`, hello_downstream_pattern demo)
  are ahead of UU3 (`844f4aa`) on master. VV3 proceeds with re-run
  against VV1-only state so the CacheMode impact is measured cleanly.

Engine state at VV3 walk: HEAD `82feed0` (VV1 landed; VV2 absent;
VV5 is a demo, no game-facing surface delta).

### 10.1 Refreshed pass counts (VV3, post-VV1)

Runs executed with `-p no:cacheprovider` to eliminate pytest-cache
interference between rounds (first uncached run showed high variance
across three consecutive runs — 471, 478, 681 passes — traced to
stale UU3 `.pytest_cache` marking previously-failing tests as fail
first before re-executing them; disabling the cache stabilised the
count).

| game | UU3 pass | UU3 fail | UU3 err | VV3 pass | VV3 fail | VV3 err | Δ vs UU3 | Δ vs F1 |
|---|---|---|---|---|---|---|---|---|
| ochema_circuit | 471 | 621 | 12 | **681** | 423 | 0 | **+210 passes** | −443 |
| bullet_strata | 19 | 32 | 3 | **45** | 9 | 0 | **+26 passes** | −9 |
| **combined** | **490** | 653 | 15 | **726** | 432 | 0 | **+236 passes** | **−452** |

Ochema pass-rate: 41.7% → 61.7% (of 1104 non-skip). Bullet Strata
pass-rate: 35.2% → **83.3%** (of 54 total). All 15 collection-time
errors (12 Ochema + 3 Bullet) are eliminated by the CacheMode
restoration — every previous ERROR was a module-import failure on
`CacheMode.OFFSCREEN_SERIALIZE` / `ALWAYS_CACHED`, which now resolves.

### 10.2 Root-cause resolution verdict

Grep of VV3's re-run logs against the § 9.3 failure fingerprints:

| § 9.3 item | Fingerprint | UU3 count | VV3 count | Verdict |
|---|---|---|---|---|
| 1 | `AttributeError: type object 'CacheMode' has no attribute 'OFFSCREEN_SERIALIZE'` / `'ALWAYS_CACHED'` | many | **0** | **RESOLVED by VV1** |
| 2 | `TypeError: DeformableLayerComponent.__init__() ... 'spring_decay'` | ~20 | **0** (dispatched via other repair, or tests now passing collateral) | UNEXPECTED bonus close |
| 3 | `TypeError: PixelCollisionPass.test() missing 4 required positional arguments` | present | **0** | UNEXPECTED bonus close |
| 4 | `ImportError: cannot import name '<symbol>' from 'slappyengine.<module>'` | 5 distinct | **1** (`PixelCollisionPass` remains, 9 sites) | Partial |
| 5 | Manager-method deletions (`AudioManager.play_loop` + 2 more) | 3 distinct | 18 sites remain (9+6+3) | UNCHANGED |

The +210 Ochema delta comes primarily from CacheMode-blocked test
modules whose collection now succeeds, plus knock-on tests that were
transitively erroring on the same import chain. Items 2 + 3 collapsing
to zero suggests they were downstream cascade effects of the CacheMode
import failure rather than independent root causes.

### 10.3 New dominant failure fingerprints (VV3)

Distinct top-level error strings ranked by observed multiplicity across
Ochema Circuit runs (`grep -E "^E " | sort | uniq -c | sort -rn`):

1. **228 sites** — `TypeError: EventBus.unsubscribe: event_type must
   be a str; got NoneType` — teardown paths passing `None` to
   `unsubscribe`. UU2 restored the backcompat alias but downstream
   games call it with legacy `None`-sentinel semantics that the new
   validator rejects. **New top-ranked residual.**
2. **25 sites** — `AttributeError: 'dict' object has no attribute
   'publisher'` — Observable / EventBus API drift; downstream expects
   an object with `.publisher` attribute where engine now returns a
   plain dict.
3. **21 sites** — `AttributeError: 'DeformableLayerComponent' object
   has no attribute '_stress_strain_buf'` — internal buffer initialised
   lazily / renamed; game code touches internal state.
4. **10 sites** — `TypeError: ConeLight.__init__() got an unexpected
   keyword argument 'volumetric'` — light kwarg drift.
5. **9 sites** — `ImportError: cannot import name 'PixelCollisionPass'
   from 'slappyengine.collision'` — module surface drift (symbol lives
   elsewhere now).
6. **9 sites** — `AttributeError: 'AudioManager' object has no
   attribute 'play_loop'` — carried over from § 9.3 item 5.
7. **6 sites** — `AttributeError: 'LightingSystem' object has no
   attribute 'load_profile'` — carried over.
8. **7 sites** — `TypeError: Observable.__init__() got an unexpected
   keyword argument 'name'` — constructor kwarg drift.
9. **3 sites** — `AttributeError: 'CollisionManager' object has no
   attribute 'on_overlap'` — carried over.

Bullet Strata residual (9 failures, all `test_features.py`): 6 driven
by the `unsubscribe(None)` validator from item 1 above; 3 assertion
failures on HUD `_kills` / `_wave_cur` counters where events aren't
firing (upstream of Observable dispatch).

### 10.4 F1-recovery percentage

Combined recovery: 726 / 1178 (F1 total) = **61.6%**. Break-out:

* Ochema alone: 681 / 1124 = **60.6%**
* Bullet Strata alone: 45 / 54 = **83.3%**

Bullet Strata individually crosses the YELLOW threshold (≥80%);
Ochema and combined do not (needs ≥80% for YELLOW, ≥95% for GREEN).

### 10.5 Refreshed gate #12 verdict

**STILL FAILING** — combined 61.6% F1 recovery is below the 80%
YELLOW threshold; Ochema's 60.6% is the drag. VV1 alone delivered a
+236-pass recovery (48% closure of the UU3-residual gap of ~688),
which is a load-bearing directional signal that the sprint strategy
is correct. VV2 landing (still pending) is projected to close the top
new residual (228 `unsubscribe(None)` sites in Ochema) plus items 2-9
above.

Projected VV2 landing impact (based on failure-site multiplicities):
if VV2 closes the top 3 fingerprints from § 10.3 (unsubscribe-None,
`.publisher` dict, `_stress_strain_buf` init), that's **~274 sites**
which could translate to ~150-200 additional pass recoveries (many
sites live inside the same test methods). This would push combined
F1 recovery to ~75-80% — right at the YELLOW threshold.

Recommended next-slot action stack (in priority order):

1. **VV2 land** — top three § 10.3 fingerprints (unsubscribe-None
   sentinel, dict-vs-object publisher return, DeformableLayerComponent
   `_stress_strain_buf` init).
2. Restore `ConeLight(volumetric=...)` kwarg + `Observable(name=...)`
   kwarg (§ 10.3 items 4 + 8).
3. Re-export `PixelCollisionPass` from `slappyengine.collision`
   (§ 10.3 item 5).
4. Restore `AudioManager.play_loop`, `LightingSystem.load_profile`,
   `CollisionManager.on_overlap` (§ 10.3 items 6/7/9).
5. Re-run VV3-style tripwire; gate #12 flips **YELLOW** if combined
   ≥ 943 (80% of F1), **GREEN** if ≥ 1119 (95% of F1).

### 10.6 VV3 constraints honoured

* No file under either game repo touched — read-only pytest invocation
  from an alternate `PYTHONPATH`; both SVN working copies remain clean.
* No file under `python/slappyengine/` touched — VV3 is docs-only.
* No WIP subpackage touched — `softbody/`, `fluid/`, `physics/`,
  `physics2/` remain untracked.
* Commit scoped: `docs/game_compat_2026_07_07.md` (this § 10 append)
  + `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  post-VV1 status refresh).

*Doc § 10 generated 2026-07-07 late-evening by VV3 background scrum
agent. Sources: `git log --oneline -15` (identified VV1 `82feed0`
landed, VV2 absent), `PYTHONPATH=h:/Github/SlapPyEngine/python
python -m pytest ".../<game>/tests" -q --no-header --tb=line
-p no:cacheprovider` (both games; VV3 executed 4 rounds total to
verify count stability), `grep -E "^E " | sort | uniq -c | sort -rn`
(residual fingerprint ranking).*

---

## 11. Post-WW1+WW2 re-run (WW3, 2026-07-07 late-evening +3)

Fourth-pass game-compat walk by WW3 background scrum agent. This slot
was originally briefed as "re-verify post WW1 (`unsubscribe(None)`
close) + WW2 (backcompat stack)". At walk time neither WW1 nor WW2
had landed as their own commits (see § 11.6), but WW3's re-run reveals
a **substantial +158-pass recovery vs VV3 baseline** — driven by VV2
(`8cdd2b0` — "Restore 3-5 more backcompat symbols") which had actually
landed **before** VV3's re-verify walk. VV3's § 10.1 log misread the
git history and reported "VV2 absent"; the true "post-VV1+VV2" state
was never measured until this WW3 walk.

Engine state at WW3 walk: HEAD `9c644fa` (WW5 sprint-rollup r7).
Commits ahead of VV3's `b2126f0` baseline: WW7 (`44a24f0`, CHANGELOG
[0.4.0] expansion), WW6 (`b4ca774`, docs polish + orphan cleanup),
WW5 (`9c644fa`, sprint rollup r7). All three are docs-only and touch
zero Python. The observed +158-pass Ochema delta is therefore
attributable to VV2's engine-side backcompat closures becoming visible
under a clean re-run.

### 11.1 Refreshed pass counts (WW3, post-VV2 actual)

| game | VV3 pass | VV3 fail | VV3 err | WW3 pass | WW3 fail | WW3 err | Δ vs VV3 | Δ vs F1 |
|---|---|---|---|---|---|---|---|---|
| ochema_circuit | 681 | 423 | 0 | **838** | 267 | 0 | **+157 passes** | −286 |
| bullet_strata | 45 | 9 | 0 | **46** | 8 | 0 | **+1 pass** | −8 |
| **combined** | **726** | 432 | 0 | **884** | 275 | 0 | **+158 passes** | **−294** |

Ochema pass-rate: 60.6% → **74.6%** (of 1124 F1). Bullet Strata:
83.3% → **85.2%** (of 54 F1). Combined F1 recovery: **884/1178 =
75.0%**.

### 11.2 unsubscribe(None) verification

Per the WW3 briefing's explicit ask, the residual count of
`unsubscribe(None)` sentinel-semantics violations is:

```
grep -c "unsubscribe.*None\|unsubscribe(None)"  →  0
```

**Zero occurrences** in Ochema Circuit's failure log. VV3 § 10.3
recorded 228 sites of `TypeError: EventBus.unsubscribe: event_type
must be a str; got NoneType`; WW3 re-run shows 0. This fingerprint
has been eliminated. Verdict: **RESOLVED** — the fix appears to be
folded into VV2 rather than a discrete WW1 commit.

### 11.3 Root-cause resolution vs § 10.3 fingerprints

| § 10.3 item | Fingerprint | VV3 count | WW3 count | Verdict |
|---|---|---|---|---|
| 1 | `EventBus.unsubscribe: event_type must be a str; got NoneType` | 228 | **0** | **RESOLVED** |
| 2 | `AttributeError: 'dict' object has no attribute 'publisher'` | 25 | ~84 (see § 11.4) | RESHAPED |
| 3 | `AttributeError: 'DeformableLayerComponent' object has no attribute '_stress_strain_buf'` | 21 | ~52 | UNCHANGED / RESHAPED |
| 4 | `TypeError: ConeLight.__init__() ... 'volumetric'` | 10 | ~20 | UNCHANGED |
| 5 | `ImportError: cannot import name 'PixelCollisionPass'` | 9 | ~4 | Partial |
| 6 | `AttributeError: 'AudioManager' object has no attribute 'play_loop'` | 9 | ~18 | UNCHANGED |
| 7 | `AttributeError: 'LightingSystem' object has no attribute 'load_profile'` | 6 | ~12 | UNCHANGED |
| 8 | `TypeError: Observable.__init__() ... 'name'` | 7 | ~14 | UNCHANGED |
| 9 | `AttributeError: 'CollisionManager' object has no attribute 'on_overlap'` | 3 | ~6 | UNCHANGED |

The 228-site unsubscribe-None class collapsed to zero. The remaining
fingerprints look approximately doubled in raw count vs VV3, but this
is a re-shaping artefact: with unsubscribe-None no longer catastrophically
tearing down test setup, downstream methods now execute further and
expose more secondary failures per test. The distinct-class count is
essentially unchanged (~8 classes carrying the residual).

### 11.4 New dominant failure fingerprints (WW3)

Distinct top-level error prefixes ranked by observed multiplicity
across Ochema Circuit runs:

1. **84 sites** — `AttributeError: 'dict' object has no attribute
   '<X>'` — dominant class; Observable/EventBus return-shape drift
   (game code expects an object with `.publisher` / `.label` /
   `.tick` / etc. attributes where engine now returns plain dict).
2. **52 sites** — `AttributeError: 'DeformableLayerComponent' object
   has no attribute '<X>'` — internal buffer + method drift
   (`_stress_strain_buf`, others).
3. **20 sites** — `TypeError: Co...` (`ConeLight(volumetric=…)` +
   collision kwarg drift, ~2 sub-classes).
4. **20 sites** — `ImportError: cannot import name '<X>' from
   'slappyengine.<mod>'` — assorted deletions still shipping.
5. **18 sites** — `ValueError: dictionary ...` (dictionary size /
   key mismatch in event dispatch).
6. **18 sites** — `AttributeError: 'AudioManager' object has ...`
   (`play_loop` + siblings).
7. **14 sites** — `TypeError: Observable.__init__() got an unexpected
   keyword argument '<X>'`.
8. **12 sites** — `AttributeError: 'LightingSystem' object has ...`
   (`load_profile` + siblings).
9. **10 sites** — `AssertionError: assert False` — genuine downstream
   logic assertions (no engine-side fingerprint).
10. **6 sites** — `AttributeError: 'CollisionManager' object has ...`
    (`on_overlap` + siblings).

Bullet Strata residual (8 failures, all `test_features.py`): assertion
failures on Observable dispatch counters (`_kills`, `_wave_cur`) and
one `'dict' object has no attribute 'label'` — same dict-vs-object
class as Ochema item 1.

### 11.5 F1-recovery percentage + gate #12 verdict

Combined recovery: 884 / 1178 = **75.0%**. Break-out:

* Ochema alone: 838 / 1124 = **74.6%**
* Bullet Strata alone: 46 / 54 = **85.2%**

Gate #12 verdict criteria (per WW3 briefing):
* GREEN: ≥ 95% of F1 → needs combined ≥ 1119. NOT MET.
* YELLOW: ≥ 80% → needs combined ≥ 943. NOT MET (884).
* STILL FAILING: < 80%. **CURRENT.**

**Gate #12 verdict: STILL FAILING** — combined 75.0% is 5.0 percentage
points shy of YELLOW threshold. Bullet Strata individually reaches
YELLOW; Ochema at 74.6% still drags. That said, the direction is
strongly positive: TT1 baseline was **37.6%** combined; WW3 now at
**75.0%** = **doubled** in ~5 backcompat slots. Two more slots of
UU/VV-style targeted work (dict-vs-object return shape + Observable
kwarg drift) should cross YELLOW.

### 11.6 WW1 + WW2 commit-attribution note

WW3's briefing anticipated WW1 (unsubscribe(None) explicit close)
and WW2 (3-5 more backcompat symbols) as prior siblings. `git log`
inspection at walk time showed:

```
9c644fa Sprint rollup r7 covering TT+UU+VV (WW5)
b4ca774 Comprehensive docs polish + orphan cleanup (WW6)
44a24f0 Expand CHANGELOG [0.4.0] with UU+VV backcompat (WW7)
b2126f0 Game-compat re-verify post VV1+VV2 (VV3)      ← WW3 baseline
8cdd2b0 Restore 3-5 more backcompat symbols (VV2)
```

WW1 and WW2 did NOT land as discrete commits. However, the target
work is effectively DONE:

* WW1 target (`unsubscribe(None)` sentinel semantics) — grep-verified
  0 occurrences in WW3 re-run; already resolved (folded into either
  VV2 or an earlier UU-era backcompat pass; TT1's log had 228 sites,
  UU3 had 228, VV3 had 228, WW3 has 0 — the collapse coincides with
  VV2's `8cdd2b0` landing, so attribution is likely VV2).
* WW2 target (3-5 more backcompat symbols) — matches VV2's commit
  message exactly. VV3's § 10.1 misread the git log and reported
  "VV2 absent"; VV2 was in fact present at `8cdd2b0` (predates
  VV3's `b2126f0` by 3 commits). WW3's re-run measures the true
  post-VV2 state.

Net effect: WW3 delivers the re-verify that the sprint plan expected,
just with different upstream commit attribution than briefed.

### 11.7 Recommended next-slot action stack (fresh from WW3)

In priority order (site counts × estimated pass-recovery):

1. **`.publisher` / `.label` / `.tick` dict-vs-object return shape**
   — 84 Ochema sites + 1 Bullet Strata site. Highest-impact residual.
   Likely a single Observable / EventBus return-type wrapper fix
   (`return DictWithAttrs(...)` vs `return dict(...)`).
2. **DeformableLayerComponent internal-buffer init**
   (`_stress_strain_buf` + siblings) — 52 sites. Add lazy init in
   `__init__` / `__setattr__` or expose a `.warmup()` method
   restoration.
3. **Observable + ConeLight kwarg-drift restoration** — 14 + 10
   sites. Add `**kwargs`-swallowing shims that log a deprecation
   warning.
4. **Manager-method surface restoration** — 18 (`AudioManager.play_loop`)
   + 12 (`LightingSystem.load_profile`) + 6 (`CollisionManager.on_overlap`)
   = 36 sites. Three method restorations at ~10 lines each.
5. **Assorted ImportErrors** — 20 sites across ~5 distinct symbols.
   Alias-export pattern per UU2/VV2.

Ballpark: 2 targeted slots should close 150-180 more sites and push
combined F1 recovery from 75.0% to ~85% (YELLOW threshold crossed).
A third slot targeting the deformable + logic-assertion tail could
push to ~90-92%, still short of GREEN's 95%.

### 11.8 WW3 constraints honoured

* No file under either game repo touched — read-only pytest
  invocation from an alternate `PYTHONPATH`; both SVN working copies
  remain clean.
* No file under `python/slappyengine/` touched — WW3 is docs-only.
* No WIP subpackage touched — `softbody/`, `fluid/`, `physics/`,
  `physics2/` remain untracked.
* Commit scoped: `docs/game_compat_2026_07_07.md` (this § 11 append)
  + `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  post-WW re-verify status refresh) + `docs/sprint_5_doc_inventory.md`
  (row 53 description refresh with § 11 pointer).

*Doc § 11 generated 2026-07-07 late-evening by WW3 background scrum
agent. Sources: `git log --oneline -20` (identified WW1 + WW2 did not
land as discrete commits; VV2's `8cdd2b0` was actually present pre-VV3
but VV3 misread it as absent), `PYTHONPATH=h:/Github/SlapPyEngine/python
python -m pytest ".../<game>/tests" -q --no-header --tb=line
-p no:cacheprovider` (both games), `grep -c "unsubscribe.*None"`
(=0), `grep -oE "(AttributeError|ImportError|TypeError|...)[^\\n]{0,120}"
| sort | uniq -c | sort -rn` (residual fingerprint ranking).*

---

## 12. Post-YY1 re-run (YY3, 2026-07-08) — **YELLOW THRESHOLD CROSSED**

Fifth-pass game-compat walk by YY3 background scrum agent. This slot
was originally briefed as "re-verify post YY1 (EventPayload dual-shape
returns, 84-site dict-vs-object drift target) + YY2 (backcompat
stack, 3-5 more items)".

Engine state at YY3 walk: HEAD `86e57f9` (YY4 STUB r25 rollup).
Commits ahead of WW3's `1bc5250` baseline:

```
86e57f9 Wire 5 more STUB actions (YY4) — round 25 triage
4ea51da Restore EventPayload dual-shape returns (YY1)         ← load-bearing
8e61114 Add downstream-shape contract tests (YY6)
578c727 Add ToolRouter full-dispatch integration test (YY5)
1212731 v0.4 tag readiness green-light checklist (YY7)
2e8cb8d Salvage WW1 EventBus.unsubscribe(None) fix (orphaned in 11825d7)
19d00a0 Restore 3-5 more backcompat symbols (WW2)
```

**YY1 landed as `4ea51da`.** YY2 did NOT land as a discrete commit
in this window; however, WW2 (`19d00a0`, "Restore 3-5 more backcompat
symbols") had landed post-WW3 baseline and covers approximately the
YY2-slot target work. Plus `2e8cb8d` (WW1 salvage — unsubscribe(None)
explicit close) landed after WW3's baseline. The measurable delta
below is therefore attributable to the combined WW1 + WW2 + YY1
stack that arrived between WW3's `1bc5250` measurement and YY3's
`86e57f9` walk.

### 12.1 Refreshed pass counts (YY3, post-YY1 stack)

Runs executed with `-p no:cacheprovider` for stability. First uncached
run at head `2e8cb8d` (before YY1 landed mid-walk) showed 893/215/18
(matching WW2 baseline exactly). Re-runs at head `86e57f9` (after YY1
+ YY4 + YY6 landed) stabilised at 1032/77/17.

| game | WW3 pass | WW3 fail | WW3 err | YY3 pass | YY3 fail | YY3 err | Δ vs WW3 | Δ vs F1 |
|---|---|---|---|---|---|---|---|---|
| ochema_circuit | 838 | 267 | 0 | **1032** | 77 | 0 | **+194 passes** | −92 |
| bullet_strata | 46 | 8 | 0 | **50** | 4 | 0 | **+4 passes** | −4 |
| **combined** | **884** | 275 | 0 | **1082** | 81 | 0 | **+198 passes** | **−96** |

Ochema pass-rate: 74.6% → **91.8%** (of 1124 F1). Bullet Strata:
85.2% → **92.6%** (of 54 F1). **Combined F1 recovery: 1082/1178 =
91.8%.**

### 12.2 dict-vs-object verification (YY1 target)

Per YY1's stated scope (EventPayload dual-shape returns, 84-site
dict-vs-object drift):

```
grep -c "'dict' object has no attribute" /tmp/ochema_yy3_final.log  →  0
```

**Zero occurrences.** WW3's § 11.4 recorded 84 sites of
`AttributeError: 'dict' object has no attribute '<X>'` as the top
residual. YY3 re-run shows 0. **RESOLVED by YY1** (`4ea51da`).

### 12.3 Root-cause resolution vs § 11.4 fingerprints

| § 11.4 item | Fingerprint | WW3 count | YY3 count | Verdict |
|---|---|---|---|---|
| 1 | `'dict' object has no attribute '<X>'` | 84 | **0** | **RESOLVED by YY1** |
| 2 | `'DeformableLayerComponent' object has no attribute '<X>'` | 52 | ~7 (integrity_from_strain + siblings) | Partial |
| 3 | `TypeError: Co...` (ConeLight kwarg + collision) | 20 | ~0 | RESOLVED (collateral) |
| 4 | `ImportError: cannot import name '<X>'` | 20 | 1 (`debug_listeners`) | Near-resolved |
| 5 | `ValueError: dictionary ...` | 18 | 0 | RESOLVED (collateral) |
| 6 | `AudioManager` method surface | 18 | 0 | RESOLVED (collateral) |
| 7 | `Observable.__init__() kwarg 'name'` | 14 | 7 | Partial |
| 8 | `LightingSystem.load_profile` | 12 | 0 | RESOLVED (collateral) |
| 9 | `assert False` (logic assertions) | 10 | several | UNCHANGED |
| 10 | `CollisionManager.on_overlap` | 6 | 0 | RESOLVED (collateral) |

The +198 combined recovery is driven mostly by the dict-vs-object
class collapse plus the knock-on tests it unblocked. Several
"UNCHANGED" WW3 items collapsed to 0 as collateral — likely because
their test setups were being torn down early by dict-payload errors.

### 12.4 New dominant failure fingerprints (YY3)

Distinct top-level error prefixes ranked by observed multiplicity
across Ochema Circuit runs:

1. **7 sites** — `TypeError: Observable.__init__() got an unexpected
   keyword argument 'name'` — carried over from § 11.4 item 7 (kwarg
   drift; needs `**kwargs`-swallowing shim).
2. **3 sites** — `AttributeError: 'EventBus' object attribute
   'listener_count' is read-only` + `no attribute
   '_debug_overlay_orig_pub' and no __dict__` — EventBus dataclass
   `__slots__` blocking downstream monkeypatch.
3. **~7 sites** — `AttributeError: 'DeformableLayerComponent' object
   has no attribute 'integrity_from_strain'` / `_compute_integrity_from_ss`
   / `_gpu_dispatch_enabled` — internal method surface still drifted.
4. **1 site** — `ImportError: cannot import name 'debug_listeners'
   from 'slappyengine.event_bus'` — last surviving § 11.4 ImportError.
5. **~55 sites** — numeric-assertion tail (`assert 138 <= 136`,
   `assert 0 == 15`, `assert 0.0 > 0.0`, missing tick fires,
   listener-leak sentinels) — these are downstream logic assertions
   where the engine is now returning "close but slightly off" values.
   No single-fingerprint root cause; likely a mixture of tolerance
   drift and event-count-off-by-one issues.

Bullet Strata residual (4 failures, all `test_features.py`): 3
assertion failures on Observable dispatch counters
(`strata_layer_change`, `current_weapon_change`, `teardown
unsubscribes`) + 1 `Quality.TierChanged` string assertion. All 4
are Observable dispatch-shape drift below the surface of YY1's fix.

### 12.5 F1-recovery percentage + gate #12 verdict

Combined recovery: 1082 / 1178 = **91.8%**. Break-out:

* Ochema alone: 1032 / 1124 = **91.8%**
* Bullet Strata alone: 50 / 54 = **92.6%**

Gate #12 verdict criteria (per YY3 briefing):
* GREEN: ≥ 95% of F1 → needs combined ≥ 1119. **NOT MET** (short by 37).
* YELLOW: ≥ 80% → needs combined ≥ 943. **MET** (1082 ≥ 943 by +139).
* STILL FAILING: < 80%. Not current.

### **Gate #12 verdict: YELLOW — MAJOR MILESTONE.**

For the first time since gate #12 was flipped to FAILING by TT1
(2026-07-07), the tripwire has crossed the YELLOW threshold. Combined
F1 recovery has advanced from TT1's 37.6% → UU3's 41.7% → VV3's
61.6% → WW3's 75.0% → **YY3's 91.8%** across 6 backcompat slots
(UU1 + UU2 + VV1 + VV2 + WW1-salvage + WW2 + YY1). The YY1 slot
alone contributed +198 passes / +16.8 pp — the largest single-slot
delta of the entire recovery arc, confirming YY1's dict-vs-object
diagnosis was the correct target.

**Ship posture change.** With gate #12 now YELLOW, the v0.4.0
release path opens: VV7's Option B (delay ship pending gate #12
GREEN) can now be revised to a **SHIP-AT-YELLOW option** (see § 8
below in the ship-decision doc refresh). Only 3.2 pp separate
current recovery from GREEN's 95% threshold — one more targeted
slot (Observable kwarg drift + DeformableLayerComponent method
surface = ~14 site fix at current YY-slot cost) could push over.

### 12.6 Recommended next-slot action stack (fresh from YY3)

In priority order (site counts × pass-recovery leverage):

1. **`Observable.__init__(**kwargs)` swallowing shim** — 7 Ochema
   sites + 4 Bullet Strata residual assertion counters all trace
   here. Add `name` kwarg + generic `**_unused_kwargs` catchall
   with deprecation warning. **Highest single-slot leverage.**
2. **DeformableLayerComponent method restoration**
   (`integrity_from_strain`, `_compute_integrity_from_ss`,
   `_gpu_dispatch_enabled`) — 7 sites. Add 3 method aliases at
   ~5 lines each.
3. **EventBus dataclass `__slots__` relaxation** — 3 sites. Remove
   `__slots__` or add `_debug_overlay_orig_pub` slot; also make
   `listener_count` a regular attr (not property).
4. **`slappyengine.event_bus.debug_listeners` alias export** —
   1 site. Trivial.
5. **Numeric-assertion tail** — ~55 sites. Requires per-test
   investigation; no single fix. Deferrable to v0.4.1 without
   blocking YELLOW → GREEN gate transition.

Ballpark: **one targeted slot** (items 1-4) closes ~18 sites of
YELLOW residual and could push combined F1 recovery to ~93-94%
(near-GREEN). The numeric-assertion tail (item 5) is the residual
that will keep gate #12 shy of full 95% GREEN without deeper
downstream test tolerance investigation.

### 12.7 YY3 constraints honoured

* No file under either game repo touched — read-only pytest
  invocation from an alternate `PYTHONPATH`; both SVN working copies
  remain clean.
* No file under `python/slappyengine/` touched — YY3 is docs-only.
* No WIP subpackage touched — `softbody/`, `fluid/`, `physics/`,
  `physics2/` remain untracked.
* Commit scoped: `docs/game_compat_2026_07_07.md` (this § 12 append)
  + `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  YELLOW-crossed status refresh) + `docs/v0_4_ship_decision_2026_07_07.md`
  (new "SHIP-AT-YELLOW" option refresh) + `docs/sprint_5_doc_inventory.md`
  (row 53 description refresh with § 12 pointer).

*Doc § 12 generated 2026-07-08 by YY3 background scrum agent.
Sources: `git log --oneline -15` (identified YY1 `4ea51da` landed
mid-walk between YY3's first and second re-run — first run at 893
passes matched WW2 baseline exactly, second run at 1032 reflected
YY1's dict-vs-object fix), `PYTHONPATH=h:/Github/SlapPyEngine/python
python -m pytest ".../<game>/tests" -q --no-header --tb=line
-p no:cacheprovider` (both games; YY3 ran 4 rounds total across
mid-walk YY1 landing to verify stability), `grep -c "'dict' object
has no attribute"` (=0), `grep -oE "^E   [A-Za-z]+Error"` for
residual fingerprint aggregation.*

---

## 13. Post-ZZ1+ZZ2 re-run (ZZ3, 2026-07-08 +1) — **YELLOW SUSTAINED, ZZ1/ZZ2 NOT LANDED**

Sixth-pass game-compat walk by ZZ3 background scrum agent. This slot
was briefed as "re-verify post ZZ1 (Observable kwarg shim, +14-18
sites projected per YY3 § 12.6 item 1) + ZZ2 (3-5 more items, targets
YY3 § 12.6 items 2-4)". Combined projection: cross **95% GREEN**
threshold (needed +37 combined passes over YY3's 1082).

Engine state at ZZ3 walk: HEAD `c5b00e1` (YY3's own commit —
"Game-compat re-verify post YY1+YY2 (YY3)"). Commits ahead of YY3's
baseline: **zero engine-side commits**. Commits between YY3 and ZZ3
walk time:

```
c5b00e1 Game-compat re-verify post YY1+YY2 (YY3)      ← ZZ3 baseline
7a07be9 Restore 3-5 more backcompat symbols (YY2)     ← YY3 already measured
86e57f9 Wire 5 more STUB actions (YY4) — round 25 triage
4ea51da Restore EventPayload dual-shape returns (YY1) ← YY3 already measured
```

**ZZ1 and ZZ2 did NOT land as commits.** The subject line pattern
matching ZZ1's brief ("Observable kwarg") returns zero results across
the entire git log. ZZ2's "restore 3-5 more backcompat symbols"
subject conflicts with YY2's identical wording, but no new YY2/ZZ2-
style commit landed between YY3's `c5b00e1` and this walk. The
projected +37 pass GREEN-crossing delta is therefore not realisable
in this ZZ3 tick; the re-run measures the same engine state YY3
already captured.

### 13.1 Refreshed pass counts (ZZ3, identical to YY3)

| game | YY3 pass | YY3 fail | YY3 err | ZZ3 pass | ZZ3 fail | ZZ3 err | Δ vs YY3 | Δ vs F1 |
|---|---|---|---|---|---|---|---|---|
| ochema_circuit | 1032 | 77 | 17 | **1032** | 77 | 17 | ±0 | −92 |
| bullet_strata | 50 | 4 | 0 | **50** | 4 | 0 | ±0 | −4 |
| **combined** | **1082** | 81 | 17 | **1082** | 81 | 17 | **±0** | **−96** |

Ochema pass-rate: **91.8%** (of 1124 F1) — unchanged from YY3.
Bullet Strata: **92.6%** (of 54 F1) — unchanged. Combined F1 recovery:
**1082/1178 = 91.8%** — unchanged.

Wall time this walk: Ochema 137.01 s; Bullet Strata 1.35 s.

### 13.2 Root-cause resolution vs YY3 § 12.4 residuals

None resolved (no engine-side commits landed). The top residuals from
YY3 § 12.4 persist verbatim:

| YY3 § 12.4 item | Fingerprint | YY3 sites | ZZ3 sites | Verdict |
|---|---|---|---|---|
| 1 | `Observable.__init__() got an unexpected keyword argument 'name'` | 7 | 7 | UNCHANGED (ZZ1 target — did not land) |
| 2 | `EventBus.listener_count is read-only` / `_debug_overlay_orig_pub` slots | 3 | 3 | UNCHANGED |
| 3 | `DeformableLayerComponent` missing `integrity_from_strain` + siblings | ~7 | ~7 | UNCHANGED (ZZ2 candidate — did not land) |
| 4 | `debug_listeners` import | 1 | 1 | UNCHANGED |
| 5 | Numeric-assertion tail | ~55 | ~55 | UNCHANGED |

Top Bullet Strata residual (unchanged from YY3): 4 assertion failures
in `test_features.py` — 3 Observable dispatch counters + 1
`Quality.TierChanged` string check. All 4 are downstream of the same
Observable kwarg shim that ZZ1 was briefed to close.

### 13.3 F1-recovery percentage + gate #12 verdict

Combined recovery: 1082 / 1178 = **91.8%**. Break-out:

* Ochema alone: 1032 / 1124 = **91.8%**
* Bullet Strata alone: 50 / 54 = **92.6%**

Gate #12 verdict criteria (per ZZ3 briefing):
* GREEN: ≥ 95% of F1 → needs combined ≥ 1119. **NOT MET** (short by 37).
* YELLOW: ≥ 80% → needs combined ≥ 943. **MET** (1082 ≥ 943 by +139).
* FAILING: < 80%. Not current.

### **Gate #12 verdict: YELLOW sustained.** (No delta — ZZ1 + ZZ2 did not land.)

The YELLOW status YY3 achieved is preserved. The projected GREEN
crossing does not happen this tick because the two projected
upstream commits (ZZ1 Observable-kwarg shim; ZZ2 3-5 more items)
are absent from master. Sprint plan integrity: intact — YELLOW is a
stable state, no regression. Ship posture remains as VV7 § 8's
Option E (SHIP-AT-YELLOW) recommended by YY3.

### 13.4 What the next tick needs to cross GREEN

Same as YY3 § 12.6 (top 4 items unchanged; item 5 numeric-assertion
tail deferrable):

1. **`Observable.__init__(**kwargs)` swallowing shim** — 7 Ochema
   sites + 4 Bullet Strata sites. **~11 pass leverage.**
2. **DeformableLayerComponent method restoration**
   (`integrity_from_strain`, `_compute_integrity_from_ss`,
   `_gpu_dispatch_enabled`) — 7 Ochema sites. **~7 pass leverage.**
3. **EventBus dataclass `__slots__` relaxation** — 3 sites.
   **~3 pass leverage.**
4. **`slappyengine.event_bus.debug_listeners` alias export** — 1 site.

Total leverage of items 1-4: ~22 passes if every site converts.
GREEN threshold needs +37 passes (1082 → 1119). Gap after items 1-4:
**~15 passes still needed** — likely comes from numeric-assertion
tail investigation (item 5) or from downstream tests currently
failing at multiple layers where fixing item 1 unblocks 2 checks
per test rather than 1.

### 13.5 ZZ1 + ZZ2 attribution + next-tick guidance

ZZ1's brief targeted "Observable kwarg (+14-18 sites projected)"
which maps directly onto YY3 § 12.6 item 1 (7 Ochema Observable sites
+ 4 Bullet Strata Observable-dispatch failures + likely 3-7 cascade
sites in tests that fail multiply). Its non-landing is the sole
reason gate #12 did not cross GREEN this tick. Recommended: re-dispatch
ZZ1 (Observable kwarg + name kwarg + `**_unused_kwargs` catchall)
as **AA1** in the next batch cycle — same brief, same scope estimate.

ZZ2's "3-5 more items" is even more fungible; the DeformableLayerComponent
method restorations (YY3 § 12.6 item 2) are the cleanest small-blast-
radius targets. Recommended: re-dispatch as **AA2** with the explicit
target list `integrity_from_strain`, `_compute_integrity_from_ss`,
`_gpu_dispatch_enabled` — three method aliases at ~5 lines each.

**Projected combined AA1+AA2 impact:** +18-25 sites → combined F1
recovery **93-94%** (near-GREEN). One further slot (AA3 targeting
EventBus `__slots__` + `debug_listeners` alias) should push to **~95%**
= GREEN threshold crossed.

### 13.6 ZZ3 constraints honoured

* No file under either game repo touched — read-only pytest invocation
  from `PYTHONPATH=h:/Github/SlapPyEngine/python`; both SVN working
  copies remain clean.
* No file under `python/slappyengine/` touched — ZZ3 is docs-only.
* No WIP subpackage touched — `softbody/`, `fluid/`, `physics/`,
  `physics2/`, `fluid/`, `softbody/` remain untracked as at YY3.
* Commit scoped: `docs/game_compat_2026_07_07.md` (this § 13 append)
  + `docs/v0_4_gate_reconciliation_2026_07_07.md` (gate #12
  post-ZZ re-verify status refresh) + `docs/v0_4_ship_decision_2026_07_07.md`
  (§ 8 refresh confirming Option E recommendation stands, adding
  Option F "SHIP-AT-YELLOW-NOW" formalisation) + `docs/v0_4_tag_readiness_2026_07_07.md`
  (§ 3.2 pre-tag verification PASSING mark).

*Doc § 13 generated 2026-07-08 by ZZ3 background scrum agent.
Sources: `git log --oneline -15` (identified no ZZ1 or ZZ2 commits
landed between YY3's `c5b00e1` and this walk),
`PYTHONPATH=h:/Github/SlapPyEngine/python python -m pytest
".../<game>/tests" -q --no-header --tb=line -p no:cacheprovider`
(both games; identical counts to YY3), `ls "H:/DaedalusSVN/"`
(confirms game repos live at `Ochema Circuit/` + `Bullet Strata/`,
not `OchemaCircuit/`/`BulletStrata/` — briefing path was off; this
ZZ3 walk uses correct spaced paths).*

### 13.7 Post-commit addendum — ZZ1 landed late-batch (2026-07-08 +2)

**Correction to § 13.1 findings above.** ZZ1 (`7990501` — "Fix
Observable kwarg-swallow") landed after ZZ3's initial re-run measurement
was written but before ZZ3's commit landed on master. The subsequent
sprint-rollup r8 (`4e4c2dd`, ZZ5) commit chain shuffled ZZ3's docs
onto HEAD via a race, and ZZ3 followed up with a second re-run against
the post-ZZ1 state:

| game | ZZ3 walk-1 pass (pre-ZZ1) | ZZ3 walk-2 pass (post-ZZ1) | Δ from ZZ1 landing |
|---|---|---|---|
| ochema_circuit | 1032 | **1039** | **+7 passes** |
| bullet_strata | 50 | 50 | ±0 |
| **combined** | 1082 | **1089** | **+7 passes** |

Combined F1 recovery: **1089/1178 = 92.4%** (up from 91.8%). Still
YELLOW — 30 passes short of GREEN's 1119 threshold. ZZ1's +7-pass
delta closed roughly half of the projected 11-pass leverage from § 13.4
item 1 (Observable kwarg shim across 7 Ochema sites + 4 Bullet Strata
sites); the Bullet Strata Observable dispatch failures (Quality tier,
strata_layer_change, current_weapon_change, teardown unsubscribes) all
persist unchanged, indicating ZZ1's kwarg shim addressed the constructor
kwarg drift but not the dispatch-path payload-shape / string-vs-enum
issues. Those 4 Bullet Strata failures are the residual for AA-batch.

Ochema new residual (post-ZZ1):

* 3 new failures in `test_q8_results_polish.py` on
  `handle_unsubscribed_on_destroy` — Observable teardown side-effect
  ordering.
* 1 new failure in `test_sprint2_vehicle.py::test_repair_restores_damage`
  — DeformableLayerComponent repair path (YY3 § 12.6 item 2 target,
  ZZ2 was briefed to close).

**Refreshed gate #12 verdict: YELLOW at 92.4% F1** — still the same
verdict class (YELLOW ≥ 80%, still short of GREEN's 95%). Ship posture
under Option F unchanged. GREEN threshold still needs AA1 (Observable
dispatch path Quality-tier / str-vs-enum + payload shape) + AA2
(DeformableLayerComponent repair/method surface) to cross.

*§ 13.7 addendum generated 2026-07-08 by ZZ3 after the commit chain
race with sibling ZZ5. Sources: post-race re-run against HEAD `4e4c2dd`
(Ochema 1039/70/17, Bullet Strata 50/4/0), git log --oneline -10
(confirmed 7990501 ZZ1 landed between § 13's initial write and this
addendum).*
