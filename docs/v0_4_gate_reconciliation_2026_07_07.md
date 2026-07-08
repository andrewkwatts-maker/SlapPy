# v0.4 Gate Reconciliation — 2026-07-07 (RR6)

Second-pass reconciliation of the OO7 v0.4 release readiness audit
(`docs/v0_4_release_readiness_2026_07_06.md`) after two intervening
sprint batches (PP + QQ) flipped or advanced gates. Consumes the QQ6
rollup (`docs/sprint_rollup_2026_07_07_r5.md`) as the intermediate
state and re-walks every gate against the live codebase at commit
`40a79bd`.

Written by RR6 background scrum agent, 2026-07-07 late evening.

---

## 1. Executive summary

OO7 rated v0.4 **YELLOW / needs 2 focused sprints** (6 GREEN /
4 FAILING / 5 needs-verify). QQ6 tracked one intermediate flip pass
(PP2 / PP3 / PP4 / PP6+PP7) to **8 GREEN + 1 DRAFT + 3 FAILING /
3 needs-verify / 1 deferred**. Live re-walk at RR6 confirms QQ6's
count, with the reconciliation adjustment that **gate 8 is now fully
GREEN by cross-check** (41 hello_* demos, 41 matching
`test_demo_hello_*.py` runners; PP4 + OO3 + OO5 + QQ2 + QQ5 batches
closed every gap that OO7 flagged). Remaining **P0 blockers reduce to
two**: gate 1 (version bump — still `0.3.0b0` in three files) and
gate 11 (softbody / fluid / physics / physics2 WIP dirs uncommitted).
Refreshed verdict: **PALE-YELLOW / CAN-SHIP-AFTER-RR-BATCH** — one
atomic version-bump commit + a user-gated WIP unfreeze closes the
gates that separate v0.4.0 from tag.

---

## 2. Refreshed 15-gate ship-checklist

Status column: **GREEN** = closed; **FAILING** = P0 blocker; **DRAFT**
= content authored but final flip pending tag sprint; **needs-verify**
= closed pre-QQ but needs a re-run before tag; **DEFERRED** = punted
to v0.4.1.

Evidence column: commit SHA, file path, or grep result.

| # | Gate | Status (RR6) | Delta vs OO7 | Evidence |
|---|---|---|---|---|
| 1 | Version constants aligned | **FAILING** | Unchanged | `pyproject.toml:7 = "0.3.0b0"`, `Cargo.toml:3 = "0.3.0-beta.0"`, `python/slappyengine/__init__.py:103 = "0.3.0b0"`. Bump audit `docs/version_bump_audit_2026_07_07.md` enumerates the 8-step commit sequence but has not been executed. |
| 2 | Engine surface doc matches `__all__` | **GREEN** | **Flipped by TT5** | `docs/engine_surface_v030.md` re-generated 2026-07-07 via `scripts/gen_engine_surface_doc.py`; 91 top-level names + 25 subpackages; 9 tripwire tests pass (`test_docs_engine_surface_complete.py` + `test_docs_inventory.py`). Delta since NN6: +3 top-level (`DiagnosticEvent`, `DiagnosticsCollector`, `get_global_collector`) + 3 subpackage-set entries (`math`, `visual_scripting`, live-parse count). App runtime surface documented for NN3/QQ4/SS6 additions. Re-regen needed after gate 1 tag-sprint version bump but is a one-command loop. |
| 3 | `test_docs_inventory.py` green | **GREEN** | Maintained | Every new r5 doc indexed via `40a79bd` (RR6 will add this doc). |
| 4 | `test_docs_links_resolve_all.py` green | **GREEN** | Maintained | Last confirmed at NN6 close. |
| 5 | `test_docs_api_template_conformance.py` green | **GREEN** | Maintained | PP5 (6 refs) + QQ3 (4 refs) both follow `_template.md`. |
| 6 | No test files under `python/tests/` | **GREEN** | Flipped by PP2 | `python/tests/` filesystem check: does not exist. `cf64daa` deleted 241 byte-identical shadow files. |
| 7 | No tests skipped without documented reason | **GREEN** | **Flipped by SS3** | Skip-audit sweep landed 2026-07-07 (`docs/skip_audit_2026_07_07.md`): 291 skip sites walked (230 `pytest.skip` + 45 `importorskip` + 11 `skipif` + 4 `mark.skip` + 1 `mark.xfail`); **0 silent-acceptance**; every site carries reason string. Breakdown: 133 legit-env, 88 legit-dep, 65 legit-upstream-drift, 3 legit-locked-sibling, 1 legit-roadmap-gap, 4 legit-baseline-write. |
| 8 | All demos have matching `test_demo_hello_*.py` | **GREEN** | **Upgraded** from OO7 FAILING + QQ6 GREEN | Live cross-check: 41 `hello_*.py` demos ↔ 41 `test_demo_hello_*.py` runners; **zero gap**. Closures: OO3 (`hello_render_real_hud`), OO5 (`hello_export_cli`), PP4 (8 legacy), PP7 (`hello_rust_bypass`), QQ2 (5 batch-2 closures), QQ5 (`hello_diagnostics_hud`). |
| 9 | `cargo check` + `cargo test` green (tracked scope) | **GREEN** | Flipped by PP3 | `git ls-files "src/*.rs"` = 14 files; `grep '^mod ' src/lib.rs` = 14 declarations; zero lag. F1 four untracked files re-scope to gate 11. |
| 10 | `maturin build --release` wheel size within budget | **GREEN** | Maintained | ~1.45 MB (well under 50 MB) per `docs/wheel_size_audit_2026_06_02.md`. |
| 11 | Softbody / fluid / physics / physics2 WIP dirs committed or deferred | **DEFERRED** | **Flipped by AAA5** 2026-07-08 | User answered VV7 Q3 verbatim: "Keep frozen with docs deferral." Formalised in [`docs/wip_subpackages_deferral_2026_07_08.md`](wip_subpackages_deferral_2026_07_08.md). WIP trees + 4 Rust source files remain untracked and out of the v0.4.0 wheel; roadmap for un-freeze targets v0.5 (softbody + fluid), v0.6 (physics2), v1.0 (physics — marked for removal). Gate #11 no longer blocks the v0.4.0 tag. |
| 12 | Game-compat tripwire (Ochema 1124/1126 + Bullet 54/54) | **YELLOW at 93.3% F1** (Bullet Strata **100%** fully recovered; reaffirmed by AAA3 2026-07-08 +2) | **YELLOW sustained across 3 re-verify ticks** (YY3 91.8% → ZZ3 92.4% → **AAA3 93.3%**); AAA1/AAA2/AAA6/AAA7 did not land, but ZZ2 (`c758122`) quietly closed Bullet Strata's last 4 sites → Bullet Strata now 54/54. AAA3 Ochema 1045/68/13 (93.0% F1); combined 1099/1178 = 93.3% F1. Full AAA3 analysis: `docs/game_compat_2026_07_07.md` § 14. Gap to GREEN (95%) = 20 passes; one BB batch (BB1+BB2 numeric-tail + BB7 Observable subscribe-handle) projects to cross. | Live re-tripwire executed 2026-07-08 by YY3 against HEAD `86e57f9` (YY4 STUB r25). YY1 (`4ea51da`, "Restore EventPayload dual-shape returns") is the load-bearing commit; landed mid-YY3-walk. YY2 (backcompat stack) did NOT land as a discrete commit; that work is effectively covered by WW2 (`19d00a0`, "Restore 3-5 more backcompat symbols") + `2e8cb8d` (WW1 salvage — unsubscribe(None) explicit close) which arrived between WW3's baseline and YY3's walk. YY3 results vs WW3 baseline: Ochema **1032 pass / 77 fail / 17 skip / 0 err** (+194 passes), Bullet Strata **50/4/0** (+4 passes). Combined **+198 passes** (recovery = **1082/1178 = 91.8% of F1**; only −96 vs F1 baseline). Ochema alone 91.8%, Bullet Strata alone **92.6%** (both individually YELLOW; both above 90%). YY3 grep-verified: **0** `'dict' object has no attribute` fingerprints (was 84 in WW3 — collapsed by YY1). All § 11.4 top residuals eliminated or reduced except Observable-kwarg drift (7 sites remain) and DeformableLayerComponent method surface (7 sites). YY1 alone contributed **+198 passes / +16.8 pp** — the largest single-slot delta of the recovery arc. Full YY3 analysis in `docs/game_compat_2026_07_07.md` § 12. **Ship-blocker status LIFTED to YELLOW** — v0.4.0 can now ship-at-YELLOW per refreshed `docs/v0_4_ship_decision_2026_07_07.md` § 8; one more targeted slot (Observable kwarg shim + 3 DeformableLayerComponent method aliases = ~18 sites) could push to ~93-94% (near-GREEN). Combined recovery arc: TT1 37.6% → UU3 41.7% → VV3 61.6% → WW3 75.0% → **YY3 91.8%** across 6 backcompat slots (UU1/UU2/VV1/VV2/WW1-salvage+WW2/YY1). |
| 13 | Perf dashboard no regression >10% | needs-verify | Unchanged | Baseline unchanged; re-run needed post-parity. |
| 14 | CHANGELOG.md `[0.4.0]` section written | **DRAFT** | Flipped by PP7 | `CHANGELOG.md:8 = "## [0.4.0] — YYYY-MM-DD (UNRELEASED)"`. Date flip happens in tag sprint. |
| 15 | `.github/workflows/publish.yml` runs test suite before wheel | **DEFERRED** | Unchanged | Punted to v0.4.1. |

**Pass count at RR6**: **8 GREEN + 1 DRAFT + 2 FAILING + 3 needs-verify
+ 1 deferred**. Down from QQ6's `8 GREEN + 1 DRAFT + 3 FAILING + 3
needs-verify + 1 deferred` because gate 8 is now confirmed live-GREEN
(QQ6 had it as GREEN in table but noted 8-count gap in text — the QQ
batches OO3/OO5/PP4/PP7/QQ2/QQ5 closed every remaining runner-less
demo).

**Post-TT5 (2026-07-07) update**: Gate 2 flipped from `needs-verify` to
**GREEN** after TT5 regenerated `engine_surface_v030.md` and confirmed
9 tripwire tests pass. Refreshed pass count was **9 GREEN + 1 DRAFT +
2 FAILING + 2 needs-verify + 1 deferred**.

**Post-TT1 (2026-07-07) update**: Gate 12 flipped from `needs-verify`
(SS5 BLOCKED) to **FAILING** after TT1 located both game repos under
`H:/DaedalusSVN/` and ran the live tripwire against engine HEAD
`fc5d94f`. Ochema regressed from 1124/1126 to **424/1129** and Bullet
Strata regressed from 54/54 to **19/54**; the two dominant breakage
classes are enumerated in `docs/game_compat_2026_07_07.md` § 4 and
are real engine-side regressions, not test-harness artefacts.
Refreshed pass count is **9 GREEN + 1 DRAFT + 3 FAILING +
1 needs-verify + 1 deferred**. Gate 12 is now a ship-blocker for
v0.4.0 alongside gates 1 (version bump) and 11 (WIP unfreeze). Only
gate 13 (perf dashboard) remains open verification.

**Post-UU1+UU2+UU3 (2026-07-07 late-evening +1) update**: UU2
(`b29e601`) landed the event_bus `global_bus` + `unsubscribe`
backcompat aliases. UU1 (`ee732fd`) landed the RenderTarget MRO fix
(`Observable.__init__` cooperative-`super()` chain restore +
defensive-`hasattr` fallback in `add_layer` / `remove_layer`). UU3
re-ran the tripwire against HEAD `ee732fd`: Ochema **471 pass /
621 fail / 22 skip / 12 err** (+47 vs TT1); Bullet Strata **19/32/3**
(unchanged). All three TT1-flagged root cause fingerprints
(`layers`, `global_bus`, `unsubscribe`-missing-arg) grep-verified as
zero occurrences. Residual dominated by 5 orthogonal breakage classes
(`CacheMode` enum-member deletions, `DeformableLayerComponent`
kwarg drift, `PixelCollisionPass.test()` signature drift, 5 further
ImportError deletions, 3 manager-method deletions) enumerated in
`docs/game_compat_2026_07_07.md` § 9.3. Gate 12 status **STILL
FAILING** — needs 5-6 more UU1/UU2-style backcompat slots to reach
the ≥ 95%-of-F1 threshold (Ochema ≥ 1068, Bullet Strata ≥ 51). Pass
count unchanged at **9 GREEN + 1 DRAFT + 3 FAILING + 1 needs-verify
+ 1 deferred** (Gate 12 remains FAILING; recovery direction is
correct but insufficient magnitude to flip).

**Post-VV1+VV3 (2026-07-07 late-evening +2) update**: VV1 (`82feed0`)
landed CacheMode.OFFSCREEN_SERIALIZE + ALWAYS_CACHED restoration.
VV2 was scheduled for the § 9.4 residual list but **did NOT land**
before VV3's re-verify walk (only VV1 + VV5 demo are ahead of UU3
on master). VV3 re-ran the tripwire against HEAD `82feed0` with
`-p no:cacheprovider` (first uncached rounds showed high variance
441→478→681 from stale pytest-cache; disabling cache stabilised):
Ochema **681 pass / 423 fail / 22 skip / 0 err** (+210 vs UU3);
Bullet Strata **45/9/0** (+26 vs UU3). Combined **+236 passes**;
F1 recovery = **726/1178 = 61.6%**. Bullet Strata individually
reaches **83.3%** (would be YELLOW alone); Ochema at **60.6%** is
the drag. All 15 UU3 collection-time errors eliminated. VV1 grep-
verified: 0 `CacheMode` fingerprints. New top residual: **228 sites**
of `EventBus.unsubscribe: event_type must be a str; got NoneType`
(legacy `unsubscribe(None)` sentinel semantics — UU2's backcompat
alias added a str-required validator that downstream teardown paths
violate). Full residual fingerprints + fix-stack in
`docs/game_compat_2026_07_07.md` § 10.3-§ 10.5. Gate 12 verdict
**STILL FAILING** (<80% combined). Pass count unchanged at **9 GREEN
+ 1 DRAFT + 3 FAILING + 1 needs-verify + 1 deferred**. Projected VV2
landing impact: ~150-200 pass recoveries pushing combined to ~75-80%
YELLOW threshold.

**Post-AAA5 (2026-07-08) update — gate #11 DEFERRED**: User answered
VV7 Q3 verbatim: "Keep frozen with docs deferral." AAA5 landed the
formal deferral doc `docs/wip_subpackages_deferral_2026_07_08.md`
enumerating all four WIP subpackage trees (`softbody/`, `fluid/`,
`physics/`, `physics2/`) + four Rust source modules (`src/raster.rs`,
`src/pbf_solver.rs`, `src/softbody_solver.rs`, `src/fluid_shader.rs`)
that are held out of the v0.4.0 wheel, plus a per-subpackage roadmap
for un-freeze (softbody + fluid → v0.5 paired physics reconcile;
physics2 → v0.6; physics → v1.0 marked for removal). Gate #11 row
above flipped from **FAILING** to **DEFERRED**. Refreshed pass count
after AAA5 land: **9 GREEN + 1 DRAFT + 1 FAILING + 1 YELLOW +
1 needs-verify + 2 deferred** — only gate #1 (version bump) remains
FAILING among P0 blockers. Gate #12 (game-compat) ships-at-YELLOW per
VV7 Option E/F. Practical effect: tag ceremony pre-flight in
`docs/v0_4_tag_rehearsal_2026_07_08.md` § 3 can proceed on gate #1
+ gate #12 threshold alone.

**Post-AAA re-verify update (2026-07-08 +2) — YELLOW at 93.3% F1,
Bullet Strata FULLY RECOVERED**: AAA3 re-verified gate #12 against
HEAD `c758122` (ZZ2's own "Restore 3-5 more backcompat symbols"
commit). None of the four projected AAA-batch commits (AAA1 numeric
tail batch 1, AAA2 numeric tail batch 2, AAA6 Bullet Strata residual,
AAA7 Ochema test-module residual sweep) landed as discrete commits;
`git log --oneline --all -30 | grep AAA` returns zero AAA-numbered
sprint hits. However, ZZ2's `c758122` (which landed after ZZ3's
addendum) quietly closed Bullet Strata's last 4 residuals plus several
Ochema sites. AAA3 re-run: Ochema **1045/68/13** (+6 vs ZZ3 post-race
1039); Bullet Strata **54/0/0** (+4 vs ZZ3; **fully recovered — 100%
of F1**). Combined **1099/1178 = 93.3% F1 recovery** (+10 vs ZZ3
post-race 1089; +1 vs brief-cited ZZ2 baseline 1098). Gate #12 verdict:
**YELLOW sustained across 3 re-verify ticks** (YY3 91.8% → ZZ3 92.4%
→ AAA3 93.3%) with mild upward drift. Ochema at **93.0%** individually
(20 passes from GREEN); Bullet Strata **100.0%** individually (fully
green). Ship posture: Option F "SHIP-AT-YELLOW-NOW" recommendation
strengthened, not weakened. AAA6 briefed scope is now moot — Bullet
Strata is 54/54. GREEN threshold (95% = 1119 combined) still needs +20
passes; projected BB1+BB2 (numeric tail, ~20 sites) + BB7 (Observable
subscribe-handle shape, ~7 sites) closes gate #12 at GREEN next tick.
Full AAA3 analysis in `docs/game_compat_2026_07_07.md` § 14.

**Post-ZZ re-verify update (2026-07-08 +1/+2) — YELLOW at 92.4% F1
after late-landing ZZ1**: ZZ3's initial walk against HEAD `c5b00e1`
(YY3's own commit) measured ZZ1/ZZ2 as absent and reported no delta
vs YY3 (Ochema 1032, Bullet 50, combined 1082 = 91.8% F1). During
commit-race with sibling ZZ5's rollup, ZZ1 (`7990501` — "Fix Observable
kwarg-swallow") landed on master; ZZ3's post-race re-run against
HEAD `4e4c2dd` measured **Ochema 1039/70/17 (+7 vs YY3)**, Bullet
Strata **50/4/0** (±0), combined **1089/1178 = 92.4% F1** (up 0.6 pp
from YY3). Gate #12 verdict: **YELLOW sustained at 92.4%** — still
27-30 passes short of GREEN's 1119 threshold. ZZ1's +7 pass delta
addressed Observable constructor kwarg drift; the 4 Bullet Strata
Observable dispatch counters (Quality-tier, strata_layer_change,
current_weapon_change, teardown-unsubscribes) plus 3 new Ochema
`test_q8_results_polish.py` `handle_unsubscribed_on_destroy` failures
persist as the AA-batch residual. Ship posture unchanged (VV7 § 8
Option E, formalised as Option F "SHIP-AT-YELLOW-NOW" per refreshed
ship-decision doc § 9). Next-tick guidance: re-dispatch AA1 (Observable
dispatch payload-shape / str-vs-enum for remaining 7 sites) + AA2
(DeformableLayerComponent repair/method surface, ~7 sites) + AA3
(EventBus __slots__ + debug_listeners, ~4 sites) = combined ~18 more
passes projected → ~1107/1178 = 94% (just shy of GREEN). Full ZZ3
analysis + § 13.7 addendum in `docs/game_compat_2026_07_07.md`.

**Post-YY1 update (2026-07-08) — YELLOW CROSSED**: YY3 re-verified
gate #12 against HEAD `86e57f9`. YY1 (`4ea51da`, "Restore EventPayload
dual-shape returns") landed mid-YY3-walk and closed the 84-site
`'dict' object has no attribute` residual class that WW3 flagged as
top blocker. YY2 (backcompat stack) did not land discretely; that
work is covered by WW2 (`19d00a0`) + `2e8cb8d` (WW1 salvage). YY3
re-run: Ochema **1032/77/17/0** (+194 passes vs WW3); Bullet Strata
**50/4/0** (+4 passes vs WW3). Combined **+198 passes** — the largest
single-slot recovery of the entire arc. F1 recovery = **1082/1178 =
91.8%** (up from WW3's 75.0%). Both games individually cross 90%:
Ochema **91.8%**, Bullet Strata **92.6%**. Gate #12 verdict: **YELLOW
(≥ 80% threshold crossed by +139 combined passes)** — first gate #12
non-FAILING status since TT1's 2026-07-07 tripwire. Refreshed pass
count: **9 GREEN + 1 DRAFT + 2 FAILING + 1 YELLOW + 1 needs-verify +
1 deferred**. **Ship-blocker status lifted** — v0.4.0 can now ship at
YELLOW per `docs/v0_4_ship_decision_2026_07_07.md` § 8 refresh. One
more targeted slot (Observable kwarg shim + DeformableLayerComponent
method aliases = ~14-18 sites) could push to ~93-94%. New top residual:
Observable-kwarg-drift (7 sites), DeformableLayerComponent method
surface (7 sites), numeric-assertion tail (~55 sites — no single fix,
downstream test tolerance investigation deferrable to v0.4.1). See
`docs/game_compat_2026_07_07.md` § 12 for full YY3 analysis.

**Post-WW-batch (2026-07-07 late-evening +3) update**: WW3 re-verified
gate #12 against HEAD `9c644fa`. WW1 (`unsubscribe(None)` explicit
close) + WW2 (further backcompat) did NOT land as discrete commits;
their target work is folded into VV2 (`8cdd2b0`, which VV3's § 10.1
had incorrectly reported as "absent" — VV2 was in fact present pre-VV3
by 3 commits). Only WW5/WW6/WW7 docs commits landed between VV3 and
WW3. WW3 re-ran tripwire (again with `-p no:cacheprovider`): Ochema
**838/267/21/0** (+157 passes vs VV3); Bullet Strata **46/8/0**
(+1 pass vs VV3). Combined **+158 passes**; F1 recovery = **884/1178
= 75.0%** (up from VV3's 61.6%). Bullet Strata individually reaches
**85.2%** (YELLOW). WW3 grep-verified: **0** `unsubscribe(None)`
fingerprints (was 228 in VV3 — collapsed by VV2). New top residual:
**84 sites** `AttributeError: 'dict' object has no attribute '<X>'`
(Observable/EventBus return-shape drift). Gate 12 verdict **STILL
FAILING** (75.0% is 5.0 percentage points shy of YELLOW). Pass count
unchanged at **9 GREEN + 1 DRAFT + 3 FAILING + 1 needs-verify +
1 deferred**. Combined F1 recovery has doubled from TT1's 37.6% →
75.0% across 5 backcompat slots (UU1 + UU2 + VV1 + VV2 + folded-in
WW work). Projected next-2-slot impact: dict-vs-object return-shape
shim + kwarg-drift restore = ~150-180 more sites → ~85% (YELLOW
crossed). Third slot (deformable + method-surface restore) →
~90-92%, still short of 95% GREEN. See `docs/game_compat_2026_07_07.md`
§ 11 for full WW3 re-run analysis.

---

## 3. What flipped since 2026-07-06

Attribution table for every OO7 gate that moved.

| Gate | Flipped by | Commit | Batch |
|---|---|---|---|
| 6 (`python/tests/` shadow) | PP2 | `cf64daa` | PP |
| 8 (demo test-smoke) | OO3 (`hello_render_real_hud`) + OO5 (`hello_export_cli`) + PP4 (8-demo bundle) + PP7 (`hello_rust_bypass`) + QQ2 (5-demo batch-2) + QQ5 (`hello_diagnostics_hud`) | `a28db30`, `758ec21`, `38ebf65`, `4eecb0a`, `9d57e81`, `03ac323` | OO + PP + QQ |
| 9 (F1 Rust mod-decl, tracked scope) | PP3 | `a08b805` | PP |
| 14 (CHANGELOG draft) | PP7 | `4eecb0a` | PP |

Additionally, docs coverage progressed (not a ship-gate flip, but
material for gate 5): PP5 landed 6 API refs (`animation_skeleton`,
`asset_import`, `capture`, `render_bvh_3d`, `render_scene_walker`,
`render_shadows`) and QQ3 landed 4 more (`audio_3d`, `physics3_bridge`,
`render_instanced`, `render_skybox`). Total `docs/api/*.md` count now
**40** entries (was 30 at OO7 close).

---

## 4. Remaining P0 gates

Only two ship-gates remain FAILING:

### 4.1 Gate 1 — Version bump

**One atomic commit** flips three files:
* `pyproject.toml` line 7: `"0.3.0b0"` → `"0.4.0"`.
* `Cargo.toml` line 3: `"0.3.0-beta.0"` → `"0.4.0"`.
* `python/slappyengine/__init__.py` line 103: `"0.3.0b0"` → `"0.4.0"`.

PP6's audit (`docs/version_bump_audit_2026_07_07.md`) documents an
8-step atomic tag-sprint sequence that folds this bump together with
downstream regen tasks (engine-surface doc regen — gate 2; CHANGELOG
date flip — gate 14; `test_version_consistency.py` re-run;
`test_projects.py` fixture bump; docs pass across README / quickstart /
getting_started / roadmap / demo_gallery / CONTRIBUTING). One sprint
slot end-to-end.

### 4.2 Gate 11 — WIP unfreeze

Still user-gated. The five WIP trees:
* `python/slappyengine/softbody/` (BeamNG-style lattice XPBD).
* `python/slappyengine/fluid/` (PBF solver refactor).
* `python/slappyengine/physics/` (hierarchical-hull per-pixel — v1.0
  candidate; can defer with docs note rather than land).
* `python/slappyengine/physics2/` (second-gen scratch — deletable /
  archivable).
* Four untracked Rust source files (`src/raster.rs`, `src/pbf_solver.rs`,
  `src/softbody_solver.rs`, `src/fluid_shader.rs`).

Two viable paths:

1. **User greenlights the unfreeze** — one landing sprint commits the
   four subpackage trees + the four Rust source files, then runs full
   Ochema Circuit + Bullet Strata regression to close gate 12
   concurrently.
2. **User signs a formal deferral** — physics + physics2 explicitly
   punt to v1.0 (already OO7 § 6.3 and § 6.4 posture); softbody + fluid
   punt to v0.4.1 with a docs note. Under this path gate 11 flips to
   **DEFERRED** rather than **GREEN**, and gate 9 stays at "tracked
   scope GREEN" instead of upgrading to "full scope GREEN".

---

## 5. Refreshed verdict

**PALE-YELLOW / CAN-SHIP-AFTER-RR-BATCH.**

OO7's "YELLOW / needs 2 focused sprints" verdict has been fully
absorbed. Two sprints (OO stabilisation + PP tag-prep) landed, plus
one additional QQ batch that closed follow-up gaps (r18 STUB triage,
diagnostics HUD demo, 5 more demo test closures, 4 more API refs,
diagnostics lifecycle wiring, World3D debug helpers). All
docs / tests / API refs / demo-smoke coverage that OO7 flagged as
FAILING has flipped to GREEN. The remaining 2 P0 gates are procedural
(one atomic version-bump commit + a user greenlight) rather than
capability gaps.

Downstream posture: after gate 1 flips, gates 2 (engine-surface
regen) + 14 (CHANGELOG date flip) fall together in the same tag-sprint
commit; gates 7 (skip audit), 12 (game-compat re-run — SS5 walked
2026-07-07 late-evening, found both game repos absent from disk, doc
at `game_compat_2026_07_07.md`, unblock via clone or sign v0.4.1
deferral), and 13 (perf dashboard re-baseline) each need a one-slot
verification pass but are not FAILING under any evidence RR6 + SS5
collected. Gate 15 remains DEFERRED to v0.4.1 by design.

Do **NOT** ship v0.4 as-is: the version drift (gate 1) would embarrass
a first-time installer, and shipping without an explicit WIP-tree
disposition (gate 11) leaves the softbody/fluid refactor branches
orphaned. Do **NOT** shrink to v0.3.1 patch: the Nova3D parity
landings + engine-surface delta already exceed patch-scope.

---

## 6. Recommended next batch scope

**One RR-batch closer sprint (~5 slots) + user decision on gate 11.**
Slot 1: execute PP6's 8-step atomic tag-sprint sequence — bump three
version constants, regenerate `engine_surface_v030.md` (rename to
`_v040.md` if the doc's title bakes the version), flip CHANGELOG date
from `YYYY-MM-DD` to `2026-07-07`, update `test_projects.py` fixtures,
re-run `test_version_consistency.py` — closes gates 1, 2, 14.
Slot 2: skip audit sweep (`grep -rn "pytest.mark.skip\|pytest.skip\|
@skipif" SlapPyEngineTests/tests/`) → docs entry per hit → closes
gate 7. Slot 3: game-compat tripwire re-run (Ochema 1124/1126 + Bullet
54/54) → closes gate 12. **Prerequisite** (per SS5 walk 2026-07-07):
clone both game repos onto the workstation first; see
`docs/game_compat_2026_07_07.md` § 5 for the two follow-up paths. Slot 4: perf-dashboard re-baseline via
6-hot-path harness → closes gate 13. Slot 5: user decision on gate 11
(either WIP unfreeze landing sprint OR docs deferral note). After all
five slots land: **`git tag v0.4.0`** and push to PyPI.

---

## 7. Cross-reference

* [`docs/v0_4_release_readiness_2026_07_06.md`](v0_4_release_readiness_2026_07_06.md)
  — OO7 audit (original 15-gate list).
* [`docs/sprint_rollup_2026_07_07_r5.md`](sprint_rollup_2026_07_07_r5.md)
  — QQ6 rollup (intermediate flip state).
* [`docs/version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
  — PP6 atomic tag-sprint sequence for gate 1.
* [`CHANGELOG.md`](../CHANGELOG.md) — PP7 `[0.4.0]` draft (gate 14).
* [`docs/sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) —
  updated to index this reconciliation.

---

*Reconciliation generated 2026-07-07 late evening by RR6 background
scrum agent. Sources: `docs/v0_4_release_readiness_2026_07_06.md`
(OO7), `docs/sprint_rollup_2026_07_07_r5.md` (QQ6),
`docs/sprint_5_doc_inventory.md` (95 entries at RR6 walk),
live `git status` + `git log --oneline -30` + `git ls-files "src/*.rs"`
(14 tracked) + `grep '^mod ' src/lib.rs` (14 declarations) +
`pyproject.toml:7` + `Cargo.toml:3` + `python/slappyengine/__init__.py:103`
+ demo/test cross-count (41 ↔ 41) at commit `40a79bd`.*

---

## Commit-attribution note

Content of this reconciliation doc was authored by RR6 background scrum
agent as part of the RR-batch dispatch (2026-07-07 late evening). Due
to a working-tree race with RR5's `hello_full_lifecycle` demo landing,
the initial file additions (this doc + `sprint_5_doc_inventory.md`
index row + `v0_4_release_readiness_2026_07_06.md` cross-link
appendix) were absorbed into RR5's `ba9cbd5` commit. This footer
addendum is the load-bearing RR6-attributed commit; RR3's `60bbdf0`
concurrently supplied the three orphan API refs (`api/diagnostics.md`,
`api/exporter.md`, `api/hud_overlay.md`) that RR6's inventory rows
depend on, so `test_docs_inventory.py` stays 4/4 green after all
three commits land.
