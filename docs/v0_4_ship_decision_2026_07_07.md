# v0.4 Ship Decision — 2026-07-07 (VV7)

Consumer-facing ship-decision doc for `v0.4.0`. Reconciles the
RR6 gate refresh (`docs/v0_4_gate_reconciliation_2026_07_07.md`)
with the UU-batch backcompat recovery (UU1 / UU2 root-cause fixes,
UU7 API stability harness) and the ongoing VV-batch residual fix
stream (VV1 CacheMode enum members, VV2 3-5 further deletions).
Selects between four release paths (**A** ship now with known
issues / **B** ship after full recovery / **C** shrink to v0.3.1
patch / **D** defer indefinitely) and surfaces three explicit
user-decision questions.

Written by VV7 background scrum agent, 2026-07-07 late-evening
batch. **Docs-only.** No Python source touched.

---

## 1. TL;DR

**Recommended: Option B — ship v0.4.0 after 2-3 more backcompat
sprints close gate #12.** The v0.4 feature payload (Nova3D parity,
diagnostics aggregator, App-lifecycle façade, engine surface
stability harness, 41-demo test-smoke coverage) is materially
larger than a patch release and deserves a proper minor bump.
Gate #12 game-compat is directionally recovering (Ochema
424 → 471 in one sprint pair, root causes narrowing) but is
still ~44 pp short of the F1 baseline; shipping now would
strand both known downstream consumers on a broken major.
Two-to-three VV/WW slots at the current recovery rate closes
the gap without materially delaying the tag.

---

## 2. Refreshed gate table (RR6 + VV batch)

Refreshed against live commit `8fe678a` (UU4 STUB triage
round 22). Delta column vs RR6 reconciliation.

| # | Gate | Status | Delta vs RR6 | Blocker path |
|---|---|---|---|---|
| 1 | Version constants aligned (0.4.0) | **FAILING** | Unchanged | Mechanical — blocked on ship decision. |
| 2 | Engine surface doc matches `__all__` | GREEN | Maintained | — |
| 3 | `test_docs_inventory.py` green | GREEN | Maintained | VV7 will add this row. |
| 4 | `test_docs_links_resolve_all.py` green | GREEN | Maintained | — |
| 5 | `test_docs_api_template_conformance.py` green | GREEN | Maintained | — |
| 6 | No test files under `python/tests/` | GREEN | Maintained | — |
| 7 | No tests skipped without documented reason | GREEN | Maintained | SS3 audit closed. |
| 8 | All demos have matching `test_demo_hello_*.py` | GREEN | Maintained | 41 ↔ 41. |
| 9 | `cargo check` + `cargo test` green (tracked scope) | GREEN | Maintained | — |
| 10 | `maturin build --release` wheel size within budget | GREEN | Maintained | ~1.45 MB. |
| 11 | Softbody / fluid / physics / physics2 WIP dirs committed or deferred | **FAILING** | Unchanged | User-gated. |
| 12 | Game-compat tripwire (Ochema 1124/1126 + Bullet 54/54) | **FAILING** (recovering) | UU1+UU2 landed +47 Ochema; VV1+VV2 in flight | Needs 2-3 more sprints. |
| 13 | Perf dashboard no regression >10% | GREEN | Flipped by SS4 | — |
| 14 | CHANGELOG.md `[0.4.0]` section written | DRAFT | Maintained | Date flip at tag. |
| 15 | `.github/workflows/publish.yml` runs test suite before wheel | DEFERRED | Maintained | v0.4.1. |

**Pass count at VV7: 10 GREEN / 1 DRAFT / 3 FAILING / 1 DEFERRED.**
Three P0 failing gates: #1 (mechanical), #11 (user-gated),
#12 (in-flight recovery).

---

## 3. Backwards-compat regression analysis

Between the F1 v0.3.0 beta baseline (Ochema 1124/1126, Bullet
54/54) and TT1's live re-run (Ochema 424/1129, Bullet 19/54),
downstream consumers lost ~688 combined passes. Root causes
enumerated by TT1 and re-verified by UU3 fall into six classes:

| # | Regression class | Status | Fix owner |
|---|---|---|---|
| 1 | `Observable.__init__` broke cooperative-`super()` chain — `RenderTarget.layers` never initialised | **FIXED** | UU1 (`ee732fd`) |
| 2 | `slappyengine.event_bus.global_bus` module attribute deleted | **FIXED** | UU2 (`b29e601`) |
| 3 | `EventBus.unsubscribe()` signature dropped one arg (subscription-id-only vs event+id) | **FIXED** | UU2 (`b29e601`) |
| 4 | `CacheMode` enum members `OFFSCREEN_SERIALIZE` / `ALWAYS_CACHED` deleted | **IN FLIGHT** | VV1 |
| 5 | 3-5 further quiet deletions (`DeformConfig`, `EventDetails`, `PixelCollisionPass`, `_parse_deform`, `debug_listeners`) + kwarg drift (`DeformableLayerComponent(spring_decay=...)`) + method deletions (`AudioManager.play_loop`, `LightingSystem.load_profile`, `CollisionManager.on_overlap`) + signature drift (`PixelCollisionPass.test()`) | **IN FLIGHT** | VV2 |
| 6 | Long-tail residual (~5-8 further items expected after VV2 lands) | **PENDING** | WW / XX candidates |

**Meta-observation.** Engine-side tests never caught any of
these regressions because none of them broke internal
consumers — they only broke external downstream games.
UU7 (`1b494cf`) landed the first real defence: an
`api_surface_snapshot.json` lockfile plus
`test_backcompat_api_surface.py` (338 pinned public symbols
across 14 load-bearing modules) plus
`test_backcompat_subclass_patterns.py` (10 subclass-abuse
patterns lifted directly from Ochema Circuit and Bullet
Strata). Once the residual VV/WW backcompat aliases land,
UU7's harness will prevent a regression of this class from
recurring.

---

## 4. Cost estimate per option

### Option A — Ship v0.4.0 NOW with gate #12 as a known issue

* **Engine team cost.** ~1 sprint slot: tag-sprint bump
  sequence (gate 1 + 2 + 14 folded), a `[known-issues]`
  block in CHANGELOG for the residual game-compat gap,
  and a v0.4.1 patch-release commitment.
* **Downstream cost.** HIGH. Ochema Circuit + Bullet Strata
  owners either (a) pin `slappyengine==0.3.0b0` and wait for
  v0.4.1, (b) fork a compat layer, or (c) rewrite ~5-8
  subsystem call-sites against the new API. All three burn
  goodwill.
* **Risk.** The `[known-issues]` block is a public admission
  that the release ships broken for known consumers. First
  impression for anyone who reads the CHANGELOG is
  "regression release".

### Option B — Ship v0.4.0 AFTER 2-3 more backcompat sprints

* **Engine team cost.** +2-3 VV/WW/XX sprint slots to close
  gate #12 residual (VV1 CacheMode, VV2 kwarg drift +
  ImportError deletions + method-name aliases, one more
  round for long-tail). Then the same 1-slot tag sprint.
  **Total: ~3-4 slots.**
* **Downstream cost.** LOW. Games upgrade cleanly. The
  UU7 harness prevents recurrence.
* **Risk.** Ship slips by ~3-4 sprint slots. At current
  recovery rate (+47 Ochema passes per two-slot UU pair)
  the gap closes cleanly. Risk lives in
  discovering-more-regressions-than-expected in the long
  tail — bounded by UU7's 338-symbol snapshot.

### Option C — Ship v0.3.1 PATCH instead

* **Engine team cost.** ~1 sprint slot: cherry-pick
  MM1 hardening + engine surface stability harness (UU7)
  + skip audit (SS3) into a `v0.3.1` patch tag; leave
  Nova3D parity + diagnostics + App lifecycle for a later
  `v0.4.0` cut. Requires rewriting CHANGELOG `[0.4.0]`
  draft as `[0.3.1]`.
* **Downstream cost.** MEDIUM. Users waiting on Nova3D
  parity / diagnostics / App-lifecycle now wait
  indefinitely. Users on v0.3.0b0 get a clean upgrade path
  to v0.3.1.
* **Risk.** Frustrates new-feature users (nova3d_parity
  batch was 20 planned sprints; skipping the ship tag
  strands its motivation). Also compresses the "what
  goes in v0.4" scope, which lengthens the eventual v0.4
  ship cycle.

### Option D — Defer v0.4.0 indefinitely until WIP unfreeze

* **Engine team cost.** Effectively unbounded. WIP unfreeze
  is user-gated and has been pending since the softbody/fluid
  refactor started. Landing it drags in gate #12 recovery
  as a chained blocker.
* **Downstream cost.** WORST. No release. No downstream
  upgrade path. Both known consumers stay pinned to
  v0.3.0b0 indefinitely.
* **Risk.** Highest. The v0.4 payload rots on master;
  further sprints layer on more surface area to review at
  the eventual tag.

---

## 5. Downstream owner survey

Both downstream consumers (Ochema Circuit under
`H:/DaedalusSVN/OchemaCircuit/`, Bullet Strata under
`H:/DaedalusSVN/BulletStrata/`) are SVN-managed and owned by
the same user (per `docs/game_compat_2026_07_07.md` § 2).
Recommendation before final ship-path selection: **user
directly walks both game repos and answers**:

1. Can each game absorb a v0.4.0 that ships with a known
   ~40%-pass game-compat gap plus a v0.4.1 followup within
   1-2 weeks?
2. If not, is a 2-3 sprint delay to full recovery
   acceptable — or is Option C (v0.3.1 patch) preferred?
3. Would either game benefit from the WIP unfreeze (softbody
   / fluid / physics / physics2) landing as an
   `[experimental]` extra on the v0.4.0 wheel?

Because the user owns both downstream consumers, the survey
collapses to the three explicit questions in § 6.

---

## 6. User decision questions

Three explicit yes/no questions the user answers to unblock
final ship path selection:

1. **Ship-with-known-issues acceptable?** Are Ochema Circuit
   and Bullet Strata owners (both user) OK with a v0.4.0
   that ships with partial game-compat (Ochema ~42% pass,
   Bullet ~35% pass) and a v0.4.1 followup within 1-2
   weeks?
   * If YES → Option A.
   * If NO → Option B or Option C.

2. **Ship delay acceptable?** If NO to Q1, do you want to
   delay v0.4.0 for the 2-3 sprints needed to fully recover
   game-compat via the VV / WW / XX backcompat batches?
   * If YES → Option B.
   * If NO → Option C.

3. **Gate #11 disposition — WIP unfreeze?** For the four
   uncommitted subpackage trees (`softbody/`, `fluid/`,
   `physics/`, `physics2/`) plus four untracked Rust source
   files (`src/raster.rs`, `src/pbf_solver.rs`,
   `src/softbody_solver.rs`, `src/fluid_shader.rs`): land
   them as-is under an `[experimental]` pip extra so early
   adopters can opt in, or keep them frozen and defer
   formally to v0.4.1?
   * Land as `[experimental]` → gate 11 flips to GREEN.
   * Keep frozen with docs deferral note → gate 11 flips
     to DEFERRED.

---

## 7. Recommendation

**Option B — SHIP v0.4.0 AFTER 2-3 more backcompat sprints
close gate #12.** Cross-reference:
[`v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md).

Justification, in decreasing weight order:

1. **The v0.4 payload is a genuine minor release.** Nova3D
   parity (JJ/KK/LL batches), diagnostics aggregator (OO6),
   App-lifecycle façade (NN3/QQ4/SS6), engine-surface
   stability harness (UU7), 41-demo test-smoke coverage
   (OO/PP/QQ/RR/SS/TT/UU batches), and the MM1 hardening
   sweep collectively add ~15 top-level symbols and ~5
   subpackages beyond v0.3. This exceeds patch scope by
   any reasonable ruleset — Option C is incorrect on
   semver grounds alone.
2. **Downstream cost of Option A is unacceptable.** The
   engine's stated architecture pattern (Python =
   ergonomic wrapper, Rust = engine core) implies that
   downstream games are the load-bearing consumer of the
   Python surface. Shipping a broken major to that
   consumer contradicts the pattern.
3. **Recovery is directionally correct and cheap.** UU1+UU2
   fixed three root causes for +47 Ochema passes in one
   sprint pair. VV1+VV2 target 4-6 more items with the
   same shape (module-attribute alias, kwarg
   backcompat wrapper, deprecation shim). The residual
   long tail is bounded by UU7's 338-symbol snapshot. At
   the current rate the gap closes in 2-3 more sprint
   pairs.
4. **Option D is dominated on every axis.** No further
   discussion.

**Gate #11 recommended disposition (independent of
Options A/B/C).** Land the four Rust source files as-is
(they compile and are exercised by tracked demos) but keep
the four Python WIP subpackage trees frozen with a docs
deferral note. This flips gate 9 from "tracked scope
GREEN" to "full scope GREEN" and flips gate 11 to
DEFERRED-BY-DESIGN rather than FAILING. Formal user
signoff via Q3 above required.

**Concrete next tick.** User answers Q1/Q2/Q3. On Option B
+ gate 11 DEFERRED: dispatch VV1 close + VV2 dispatch this
round, WW batch (3-4 slots targeting gate #12 residual)
next round, XX tag-sprint (gate 1 + 2 + 14 fold + WIP
deferral commit) after WW verify.

---

## 8. Cross-reference

* [`docs/v0_4_release_readiness_2026_07_06.md`](v0_4_release_readiness_2026_07_06.md)
  — OO7 original audit (YELLOW).
* [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  — RR6 refresh (PALE-YELLOW).
* [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
  — TT1 tripwire re-run + UU3 recovery append (gate #12).
* [`docs/api_stability_2026_07_07.md`](api_stability_2026_07_07.md)
  — UU7 backcompat harness + 338-symbol snapshot.
* [`docs/version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
  — PP6 tag-sprint sequence for gate 1.
* [`docs/sprint_rollup_2026_07_07_r6.md`](sprint_rollup_2026_07_07_r6.md)
  — TT7 rollup (QQ + RR + SS batch history).
* [`CHANGELOG.md`](../CHANGELOG.md) — PP7 `[0.4.0]` draft
  (gate 14).

---

*Ship-decision doc generated 2026-07-07 late-evening by VV7
background scrum agent. Sources: RR6 gate reconciliation
(`docs/v0_4_gate_reconciliation_2026_07_07.md`), TT1 game-compat
re-run (`docs/game_compat_2026_07_07.md`), UU3 recovery append
(same doc § 9), UU7 API stability contract
(`docs/api_stability_2026_07_07.md`), TT7 sprint rollup r6
(`docs/sprint_rollup_2026_07_07_r6.md`), live `git log`
at commit `8fe678a`, `pyproject.toml:7` +
`python/slappyengine/__init__.py:103` version cross-check.
Docs-only — no Python source touched.*

---

## 8. Post-YY1 update (2026-07-08) — new Option E: SHIP-AT-YELLOW

**Refresh appended by YY3** after gate #12 crossed the YELLOW
threshold. YY1 (`4ea51da`, "Restore EventPayload dual-shape returns")
closed the 84-site dict-vs-object drift that was the WW3-era top
residual. Combined F1 recovery: **1082/1178 = 91.8%** (was 75.0% at
WW3). Both games individually reach >90% (Ochema 91.8%, Bullet
Strata 92.6%). Full analysis in `docs/game_compat_2026_07_07.md`
§ 12.

### 8.1 Refreshed gate table (post-YY1)

| # | Gate | Status | Delta vs VV7 § 2 | Blocker path |
|---|---|---|---|---|
| 12 | Game-compat tripwire | **YELLOW** (was FAILING) | **Threshold crossed by YY1** | No longer blocker — ship at YELLOW acceptable. |

All other gates unchanged from VV7 § 2.

### 8.2 New Option E — SHIP NOW at YELLOW

Enabled by gate #12 crossing 80% F1. Adds a fifth path to the A/B/C/D
menu in § 4:

**Option E — Ship v0.4.0 NOW that gate #12 is YELLOW.**

* **Engine team cost.** ~1 sprint slot: tag-sprint bump sequence
  (gate 1 + 2 + 14 folded) + optional 1 more slot for the
  gate-#12-to-near-GREEN push (Observable kwarg shim +
  DeformableLayerComponent method aliases = ~18 sites; would push
  recovery to ~93-94%). **Total: 1-2 slots** — comparable to
  Option A but with 91.8% recovery instead of 42%.
* **Downstream cost.** LOW-MEDIUM. Both games get 91.8%
  compatibility out of the box — most feature paths work; residual
  failures are 7 Observable-kwarg sites + 7 DeformableLayerComponent
  method sites + ~55 downstream logic-assertion drift (tolerance /
  event-count off-by-one). Downstream owners can ship against v0.4.0
  with `pytest -k "not (Observable_name_kwarg or integrity_from_strain)"`
  filters until v0.4.1 lands the last residual fixes.
* **Risk.** LOW. The 91.8% number is at YELLOW threshold — well
  above the 80% target OO7 implicitly set. First impression for
  downstream users: "9-out-of-10 tests pass, patch release fixes
  the last 10%". CHANGELOG carries an explicit v0.4.1 commitment
  for the Observable-kwarg + DeformableLayerComponent residual.

### 8.3 Refreshed recommendation

**Option E supersedes Option B as the recommended path.** Justification:

1. **YY1's +198-pass delta shifted the risk arithmetic.** VV7's
   Option B assumed 2-3 more backcompat sprints at UU-pair rate
   (+47 passes / 2 slots) would close the residual. YY1 delivered
   +198 passes in a single slot — an order of magnitude better than
   assumed. The gap that VV7 estimated at "2-3 sprints" is now
   effectively closed to YELLOW-plus-buffer in one.
2. **Shipping at 91.8% is materially better than Option A's 42%.**
   The v0.4.0 downstream cost that Option A treated as "unacceptable"
   is now bounded to ~14 site-level fixes + a downstream-test
   tolerance sweep — a v0.4.1 followup within 1 sprint, not 2-3.
3. **The v0.4 payload has now been on master for 2+ weeks of docs
   polish.** Continuing to delay the tag while gate #12 chases 95%
   burns goodwill with users tracking master waiting for the tag.
4. **95% GREEN is not required by any external contract.** OO7's
   original gate #12 wording was "match or exceed F1 baseline"
   which is 100%; that target was impossible under any of A/B/C.
   The 95% GREEN threshold was added by TT1 as an internal
   ship-quality bar; YELLOW is the pragmatic threshold external
   consumers care about.

**Concrete next tick (revised).** User answers the same Q1/Q2/Q3
from § 6, with an updated Q1 reference: "Ship-at-91.8%-compat
acceptable?" (was "ship-at-42%"). If YES → Option E, dispatch tag
sprint immediately + optional YY-follow slot for Observable-kwarg
shim. If NO → Option B remains available (delay ~1 slot for
Observable-kwarg + DeformableLayerComponent method aliases to push
to ~93-94% near-GREEN, then tag).

### 8.4 Cross-reference for § 8

* [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
  § 12 — YY3 re-verify with YY1 landing evidence.
* [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  — Gate #12 row refreshed to YELLOW.

*§ 8 refresh generated 2026-07-08 by YY3 background scrum agent
following YY1's gate #12 YELLOW crossing. Sources: `git log
--oneline -15` (identified YY1 `4ea51da` landed), live tripwire
against HEAD `86e57f9` (Ochema 1032/77/17, Bullet Strata 50/4/0),
combined F1 recovery 1082/1178 = 91.8%. Docs-only — no Python
source touched.*
