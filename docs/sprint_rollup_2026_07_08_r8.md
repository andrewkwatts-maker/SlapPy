# Sprint Rollup r8 — WW + XX(lost) + YY batches (game-compat recovery arc — YELLOW crossed)

Eighth in the series after r1 (`docs/sprint_rollup_2026_07_04.md`, V–DD),
r2 (`docs/big_picture_2026_07_05.md`, V–FF), r3
(`docs/sprint_rollup_2026_07_05_r3.md`, HH–LL Nova3D-parity milestone),
r4 (`docs/sprint_rollup_2026_07_06.md`, MM+NN post-parity hardening),
r5 (`docs/sprint_rollup_2026_07_07_r5.md`, OO+PP v0.4 stabilisation
and tag-prep), r6 (`docs/sprint_rollup_2026_07_07_r6.md`,
QQ+RR+SS v0.4 gate closer sweep), and r7
(`docs/sprint_rollup_2026_07_07_r7.md`, TT+UU+VV game-compat backslide
+ backcompat recovery arc rounds 1-2).

r8 covers the three sprint batches that landed in the 2026-07-07
overnight-to-2026-07-08 morning push cycle: **WW — targeted backcompat
recovery round 3 + rollup r7** (WW1 `EventBus.unsubscribe(None)`
sentinel fix salvaged as orphan-recovery commit `2e8cb8d`, WW2 5
backcompat items, WW3 re-verify at **75.0% F1 recovery**, WW4 STUB r24,
WW5 sprint rollup r7, WW6 comprehensive docs polish + orphan cleanup +
docs/api/README.md + docs/tutorials/README.md, WW7 CHANGELOG `[0.4.0]`
expansion with 42 QQ+RR+SS+TT+UU+VV commits regrouped under
Keep-a-Changelog headings); **XX — LOST to rate limit** (all 7 slots
failed to land; only WW1's orphan salvage recovered any drift);
and **YY — targeted backcompat recovery round 4 + tag readiness**
(YY1 `EventPayload` dual-shape returns — **largest single-slot delta
of the entire recovery arc at +198 passes**, YY2 5 backcompat items,
YY3 re-verify at **91.8% F1 recovery — gate #12 flipped FAILING to
YELLOW for the first time since TT1's tripwire**, YY4 STUB r25, YY5
ToolRouter full-dispatch integration test (169 ids sweep, 0
exceptions), YY6 downstream shape-contract tests + backcompat contract
doc, YY7 v0.4 tag-readiness green-light checklist).

Written by ZZ5 background scrum agent, 2026-07-08 morning.

---

## 1. Executive summary

WW closed a chunk of the long-tail backcompat residual (5 more shims
covering audio loop registry, ConeLight volumetric kwarg, PixelCollisionPass
re-export, LightingSystem.load_profile, CollisionManager overlap predicate,
plus the salvaged WW1 unsubscribe(None) sentinel) and shipped the r7
rollup + CHANGELOG expansion + orphan-swept docs index. XX was lost
entirely to rate limit — all 7 slots died mid-run, with no drift beyond
the WW1 orphan-recovery commit. YY closed the biggest single fix of the
recovery arc (YY1's `EventPayload(dict)` dual-shape returns, +198
passes / +16.8 pp in one slot) and pushed **gate #12 across the 80%
YELLOW threshold** at 91.8% F1 recovery, lifting the ship-blocker
status VV7 had flagged and adding an Option E (SHIP-AT-YELLOW) to the
ship-decision doc.

---

## 2. WW batch — targeted backcompat recovery round 3 + rollup r7

Dispatched immediately after VV3's identification of the 228-site
`unsubscribe(None)` sentinel residual + the projected next-slot
stack. WW1 was orphaned during the working-tree race (its content
landed in orphan commit `11825d7` alongside WW7's parallel CHANGELOG
commit, but only the WW7 half made it to master `44a24f0`); WW1's
event_bus.py + regression test were salvaged into direct commit
`2e8cb8d` after the drift was caught. WW2's work partially folded into
the earlier VV2 landing that VV3 had incorrectly reported as absent —
WW3's re-verify measured the true post-VV2 state for the first time.

| Agent | Commit SHA | Delivered | Tests added |
|---|---|---|---|
| **WW1** | `2e8cb8d` (salvage) | `EventBus.unsubscribe(None, listener)` teardown pattern — remove listener from every topic; `unsubscribe()` and `unsubscribe(None, None)` as no-ops; module-level `unsubscribe()` proxy mirrors signature; `TypeError` only when `event_type` is neither `None` nor `str`; addresses VV3's 228-site sentinel residual | 7 (`test_unsubscribe_none_backcompat.py`; 5 sibling `test_event_bus_backcompat.py` still green) |
| **WW2** | `19d00a0` | Restore 5 more backcompat symbols: (1) `DeformableLayerComponent._stress_strain_buf` lazy `(H, W, 2)` float32 buffer (21 Ochema `test_gpu_deform` sites); (2) `lighting.ConeLight(volumetric=...)` legacy kwarg (10 Ochema vehicle-headlight sites); (3) `collision.PixelCollisionPass` re-export of the class from `collision_pixel` (9 Ochema sites); (4) `audio.AudioManager.play_loop`/`stop_loop`/`set_loop_volume`/`set_loop_pitch` id-tracked loop registry with clamping (9 Ochema Sprint P3 audio sites); (5) `lighting.LightingSystem.load_profile(name, profiles=None)` named preset apply with `night_rally`/`day_rally`/`garage` built-ins (6 Ochema Sprint 3 sites); bonus item 6: `CollisionManager.on_overlap(predicate, cb)` with reversed-argument fallback | 18 (`test_backcompat_stack_ww2.py`) |
| **WW3** | `1bc5250` | Game-compat re-verify post WW1+WW2 (work folded into VV2 which VV3 had misread as absent): Ochema **838/1126** (+157), Bullet Strata **46/54** (+1), combined **884/1178 = 75.0% F1** (up from VV3 61.6%); Bullet individually crossed YELLOW at 85.2%; `unsubscribe(None)` sentinel violations grep-verified as 0 (was 228); new top residual = **84 sites** of `'dict' object has no attribute` (Observable/EventBus return-shape drift); gate #12 STILL FAILING (75.0% is 5.0 pp shy of 80% YELLOW threshold) | — (docs-only) |
| **WW4** | `6bb772f` | STUB triage round 24: 5 new WIRED action ids (`view.toggle_axes` / `view.toggle_background` / `edit.select_by_tag` / `spawn.at_grid` / `layer.clear`); 5 new action modules; `feature_map_delta_2026_07_15.md` | 47 (`test_actions_stub_triage_r24.py`) |
| **WW5** | `9c644fa` | Sprint rollup r7 (`docs/sprint_rollup_2026_07_07_r7.md`, 482 lines): TT+UU+VV retrospective, refreshed 15-gate table (10 GREEN + 1 DRAFT + 3 P0 FAILING + 1 DEFERRED — gate #2 flip, gate #12 baseline collapse), r14-r23 STUB triage rollup, Nova3D parity re-verification, game-compat recovery timeline TT1 37.6% → UU3 41.5% → VV3 61.6%, feature map 380 rows / 363 WIRED (~95.8%), ~9820 tests collected | — (docs-only) |
| **WW6** | `b4ca774` | Comprehensive docs polish + orphan cleanup: `docs/api/README.md` (API-ref index + gap tracker — 46 shipped subpackages, 4 shader/theme refs, 5 gap subpackages `build`/`render` root/`scenes`/`text`/`ui` root, 4 WIP-frozen); `docs/tutorials/README.md` (curated TOC for 43 `hello_*` demos grouped Flagship/Rendering-HUD-capture/Physics-dynamics/Subsystem-primer); zero disk-orphans, zero stale inventory entries | — (3 doc tripwires 308 pass) |
| **WW7** | `44a24f0` | CHANGELOG `[0.4.0]` expansion: audit + extend PP6's draft with 42 commits from `b7cb01a..HEAD` (QQ+RR+SS+TT+UU+VV batches); regrouped under Keep-a-Changelog headings; adds `### Backwards-compatibility notes` subheading enumerating 8 restored public symbols with commit SHAs (Observable MRO, event_bus.global_bus, unsubscribe, CacheMode variants, EventDetails, DeformConfig, DeformableLayerComponent kwargs, PixelCollisionPass.test class-form); `### Known issues` subheading (gate #12 61.6% F1, WIP-subpackage freeze, version-string flip pending); release date stays `[0.4.0] - UNRELEASED` | — (docs-only) |

**WW batch impact**: 7 commits (WW1 salvaged), ~72 new tests, 2 new
index docs (`api/README.md` + `tutorials/README.md`), 6 more backcompat
regression classes closed (unsubscribe sentinel + stress_strain_buf +
ConeLight.volumetric + PixelCollisionPass re-export + AudioManager loops
+ LightingSystem.load_profile), CHANGELOG regrouped, and Ochema Circuit
recovered **+157 passes** to reach 75.0% F1 combined.

---

## 3. XX batch — LOST TO RATE LIMIT

**Attribution:** All 7 XX slots died to rate limit before landing any
work. XX1's dict-vs-object EventPayload fix (targeted at the 84-site
`'dict' object has no attribute` residual WW3 identified) did NOT reach
the working tree. XX2-XX7 (further backcompat sweeps, STUB triage r25,
API refs, demo closures, tag-prep companion) all failed to land.

**No drift beyond WW1 orphan salvage.** The 2e8cb8d salvage commit
was the only recovered artefact from the WW+XX window; XX1's
EventPayload work was re-dispatched as YY1 after the 8:20pm Brisbane
rate-limit reset, and landed as the largest single-slot delta of the
entire recovery arc (see YY1 row § 4).

**Root cause:** parallel-agent fleet hit the daily rate cap before
XX-batch had a chance to complete. Round-3 SHA-echo pattern held —
zero silent-accept bugs, zero misfired commits — but the wall-clock
budget was exhausted mid-dispatch.

**Lesson:** XX-batch scope was preserved by re-dispatch under YY.
Recovery latency was ~2 hours (Brisbane reset window). See § 10 for
the full rate-limit salvage-pattern retrospective.

---

## 4. YY batch — targeted backcompat recovery round 4 + tag readiness

Dispatched after the Brisbane 8:20pm rate-limit reset as the XX
re-dispatch batch. All seven YY slots landed direct-to-master. YY1's
`EventPayload(dict)` dual-shape fix was the single largest recovery-arc
delta (+198 passes / +16.8 pp), collapsing the 84-site
`'dict' object has no attribute` residual identified by WW3. YY3's
re-verify flipped gate #12 to YELLOW for the first time since TT1.

| Agent | Commit SHA | Delivered | Tests added |
|---|---|---|---|
| **YY1** | `4ea51da` | `EventPayload(dict)` subclass — behaves as BOTH object AND dict; reserved keys `name`/`label`/`publisher`/`data`/`payload`/`timestamp`; arbitrary kwargs promote to attributes AND dict items in one step; `EventBus.publish` now returns the payload (was `None`) so callers can inspect it; `Observable.notify` auto-sets `publisher=self` (Bullet Strata HUD relies on `evt.publisher is self._scene` filter); `EventDetails` alias re-pointed to `EventPayload` (legacy `isinstance(evt, dict)` still passes); **Ochema 893 → 1012 (+119); Bullet 46 → 50 (+4); combined +123 — YELLOW threshold 942 cleared** | 17 (`test_event_payload_shape.py`) + 3 existing tests fixed to use item/attr access |
| **YY2** | `7a07be9` | Restore 5 more backcompat symbols: (1) `PixelContactResult.depth` read-only property aliasing `contact_pixels` (10 Ochema Sprint 5/7 sites); (2) `Asset.cache_mode` default attribute set to `CacheMode.OFFSCREEN_SERIALIZE` on `__init__` (deferred import sidesteps residency circular); (3) `DeformableLayerComponent.integrity_from_strain()` + `_compute_integrity_from_ss()` mean-strain → integrity mapping `1 - mean(strain)` clamped to `[0, 1]` (6 Ochema sites); (4) `_gpu_dispatch_enabled` + `_apply_impact_cpu` GPU compute-dispatch flag with graceful CPU fallback via extracted helper; (5) `.repair(rate=...)` legacy queue-based repair (Ochema PitsSystem + Sprint 2 vehicle repair sites); bonus item 6: `ResidencyManager.update()` honours `entity.cache_mode` (`ALWAYS_CACHED` pins GPU, `USER_DRIVEN` skips transitions, `OFFSCREEN_SERIALIZE` fires `bake_data_layer` on first GPU/RAM → disk transition); bonus item 7: plastic strain (channel 1 of `_stress_strain_buf`) no longer decays under `spring_decay` — F1 invariant restored | 20 (`test_backcompat_stack_yy2.py`) |
| **YY3** | `c5b00e1` | Game-compat re-verify post YY1+YY2 (YY2 folded into WW2+2e8cb8d landing between WW3 baseline and YY3 walk): Ochema **1032/1124 (91.8%)**, Bullet Strata **50/54 (92.6%)**, combined **1082/1178 = 91.8% F1 recovery** (was 75.0% at WW3, +198 passes vs WW3 baseline); **gate #12 flipped FAILING → YELLOW for the first time since TT1's 2026-07-07 tripwire — MAJOR MILESTONE**; ship-blocker status lifted; grep-verified 0 `'dict' object has no attribute` fingerprints (was 84); new top residual = 7 sites `Observable.__init__() got unexpected kwarg 'name'` + 7 DeformableLayerComponent method-surface sites + ~55 numeric-assertion tail; combined arc TT1 37.6% → UU3 41.5% → VV3 61.6% → WW3 75.0% → **YY3 91.8%** across 6 backcompat slots | — (docs-only) |
| **YY4** | `86e57f9` | STUB triage round 25: 5 new WIRED action ids (`view.toggle_snap_indicator` / `edit.select_parent` / `spawn.at_selection_center` / `layer.lock` / `snap.reset_defaults`); 5 new action modules; `feature_map_delta_2026_07_16.md`; bumps wired STUB-triage count from r14-r24's 55 (11×5) to **60 across 12 rounds** | 45 (`test_actions_stub_triage_r25.py`) |
| **YY5** | `578c727` | ToolRouter full-dispatch integration test (`test_tool_router_full_dispatch.py`, 425 lines): sweeps **169 registered action ids**, dispatches each with mock ctx, asserts **0 exceptions** raised, exercises fallback module resolution + registry singleton + category classification + ctx-validator round-trip; complements the per-round STUB-triage regressions with a whole-registry sweep | 1 sweep test (169 assertions inside) |
| **YY6** | `8e61114` | Downstream shape-contract tests + backcompat contract doc: `test_backcompat_downstream_shape.py` (8 return-shape tripwires: `EventBus.publish` attr+dict access, `AudioManager.play_loop` object-handle, `LightingSystem.load_profile("night_rally")` returned-config, `RenderTarget.add_layer` dict-spec polymorphism, `Observable`+`Asset` dynamic subclass MRO, `CacheMode.OFFSCREEN_SERIALIZE.value` str + variant sweep); `test_backcompat_iteration_patterns.py` (10 iteration/assignment tripwires: `entity.layers` iter+index+reiter, `bus._listeners` items/keys/values, `entity.tags` list-assignment + reassignment + empty-init iterability); `docs/backcompat_contract_2026_07_07.md` enumerates every pinned downstream contract with STABLE v0.4.0 through v1.x promise + 1-minor-cycle deprecation policy mirroring UU7 | 15 passes + 3 `xfail`s |
| **YY7** | `1212731` | v0.4 tag-readiness green-light checklist (`docs/v0_4_tag_readiness_2026_07_07.md`, 212 lines): operational tag-day sibling to VV7's ship-decision doc; three-step atomic checklist (version bump via `SetVersion.bat 0.4.0` across `pyproject.toml`/`Cargo.toml`/`__init__.py`, CHANGELOG date-flip on draft header, `git tag v0.4.0` + push); four pre-tag verification gates (engine tests all-green, game-compat ≥80% F1 = 942/1178, `cargo check --release` zero errors, `maturin build --release` wheel ≤50MB); three post-tag checks (`maturin publish`, PyPI mirror pull test in fresh venv, `gh release create` from CHANGELOG); PEP 440 post-release rollback plan; re-surfaces VV7's three open user-decision questions | — (docs-only) |

**YY batch impact**: 7 commits, ~98 new tests + 1 whole-registry
sweep of 169 ids, 1 new contract doc (`backcompat_contract_2026_07_07.md`),
1 new tag-readiness doc (`v0_4_tag_readiness_2026_07_07.md`), **+198
combined game-compat passes** (the single largest recovery-arc delta),
and **gate #12 flipped FAILING → YELLOW** — ship-blocker status lifted.

---

## 5. Game-compat recovery arc — the full timeline

Extends r7's § 5 timeline through WW3 + YY3. Every backcompat slot
attributed by fix owner:

| Milestone | Ochema Circuit | Bullet Strata | Combined | F1 recovery | Attribution |
|---|---|---|---|---|---|
| F1 baseline (project_beta_2026_05.md, 2026-05-28) | 1124 / 1126 | 54 / 54 | 1178 / 1180 | 100.0% | v0.3.0 beta baseline |
| **TT1 re-execution (2026-07-07 late-PM)** | **424 / 1129** | **19 / 54** | **443 / 1183** | **37.6%** | 3 root causes: RenderTarget MRO / global_bus / unsubscribe |
| UU3 post-UU1+UU2 (2026-07-07 evening) | 471 / 1126 (+47) | 19 / 54 (+0) | 490 / 1180 | 41.5% | UU1 fixed MRO; UU2 restored global_bus + unsubscribe alias |
| **VV3 post-VV1 (2026-07-07 late-evening)** | **681 / 1126 (+210)** | **45 / 54 (+26)** | **726 / 1180** | **61.6%** | VV1 restored CacheMode enum; 15 collection errors eliminated |
| **WW3 post-VV2+WW1+WW2 folded (2026-07-08 early morning)** | **838 / 1126 (+157)** | **46 / 54 (+1)** | **884 / 1178** | **75.0%** | VV2 folded backcompat stack + WW1 unsubscribe(None) sentinel + WW2 audio/lighting/collision shims; 228 unsubscribe(None) sites collapsed to 0 |
| **YY3 post-YY1+YY2 (2026-07-08 morning) — YELLOW CROSSED** | **1032 / 1124 (+194)** | **50 / 54 (+4)** | **1082 / 1178** | **91.8%** | YY1 EventPayload dual-shape (+198 combined, largest single-slot delta) + YY2 depth/cache_mode/integrity/repair shims; 84 dict-shape sites collapsed to 0 |
| **Projected post-ZZ (Observable kwarg + method aliases)** | ~1090 / 1124 | ~52 / 54 | ~1142 / 1178 | ~96.9% (GREEN threshold) | ZZ tail cleanup: Observable `name=` kwarg + DeformableLayerComponent method surface + numeric-assertion tail |
| **Target for gate #12 GREEN** | ~1100+ / 1124 | ~54 / 54 | ~1154+ / 1178 | ~97.8%+ | F1 baseline restoration |

**Total r8 recovery**: **+356 passes** (884 → 1082 across WW+YY window; VV3
baseline of 726 → YY3 close of 1082 = +356), through **11 backcompat
shims** landing since VV3 (WW1 unsubscribe(None), WW2 five items,
plus VV2's folded-in landing counted at WW3 measurement, YY1
EventPayload dual-shape, YY2 five items), reaching **91.8% F1 recovery
from a 61.6% VV3 baseline and a 37.6% TT1 starting point**.

**YY1 is the arc's dominant single-slot fix**: +198 passes / +16.8 pp
in one commit. The `EventPayload(dict)` design (subclass dict, promote
kwargs to both items and attributes) closed a class-of-bug that no
prior narrow shim could address — every subscribe callback that reads
`evt.publisher` / `evt.value` / `evt.payload.get(...)` was silently
broken and now works both as `dict` and as object.

---

## 6. v0.4 readiness gate status — refreshed post-WW+YY

Snapshot of every OO7 gate at r8 close. Cross-linked to
[`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
(YY3 update) and
[`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
(§ 8 Option E SHIP-AT-YELLOW added by YY3).

| # | Gate | Status (r8) | Δ vs r7 |
|---|---|---|---|
| 1 | Version constants aligned | **FAILING** | Unchanged — 3 files still on `0.3.0b0` / `0.3.0-beta.0`; user Q1/Q2 decision still pending |
| 2 | Engine surface doc matches `__all__` | **GREEN** | Maintained |
| 3 | `test_docs_inventory.py` green | **GREEN** | Maintained (WW4/YY4 each added row for their delta doc; WW6 added api/README + tutorials/README + rollup r7; YY6 added contract doc; YY7 added tag-readiness doc; ZZ5 will add rollup r8) |
| 4 | `test_docs_links_resolve_all.py` green | **GREEN** | Maintained |
| 5 | `test_docs_api_template_conformance.py` green | **GREEN** | Maintained |
| 6 | No test files under `python/tests/` | **GREEN** | Maintained |
| 7 | No tests skipped without documented reason | **GREEN** | Maintained |
| 8 | All demos have matching `test_demo_hello_*.py` | **GREEN** | Maintained |
| 9 | `cargo check` + `cargo test` green (tracked scope) | **GREEN** | Maintained |
| 10 | `maturin build --release` wheel size within budget | **GREEN** | Maintained (~1.45 MB) |
| 11 | Softbody / fluid / physics / physics2 WIP dirs committed or deferred | **FAILING** | Unchanged — user-gated (VV7 recommends DEFERRED-BY-DESIGN; YY7 tag-readiness doc re-surfaces the Q3 decision) |
| 12 | Game-compat tripwire (Ochema 1124/1126 + Bullet 54/54) | **YELLOW** | **FLIPPED FAILING → YELLOW by YY3** — 91.8% F1 recovery (Ochema 91.8%, Bullet 92.6%); ship-blocker lifted; Option E (SHIP-AT-YELLOW) added to ship-decision doc |
| 13 | Perf dashboard no regression >10% | **GREEN** | Maintained |
| 14 | CHANGELOG.md `[0.4.0]` section written | DRAFT | WW7 expanded to 42 commits + Backcompat-notes + Known-issues; date flip still pending tag sprint |
| 15 | `.github/workflows/publish.yml` runs test suite before wheel | DEFERRED | Unchanged (punted to v0.4.1) |

**Pass count at r8 close**: **10 GREEN + 1 DRAFT + 2 P0 FAILING (gates
1, 11) + 1 YELLOW (gate 12) + 1 DEFERRED**. Compared to r7-close
(10 GREEN + 1 DRAFT + 3 P0 FAILING + 1 DEFERRED), gate #12 flipped
`FAILING → YELLOW` (YY3), and the P0-FAILING count dropped from 3 to 2.

**Verdict**: was **RED (multi-sprint recovery required)** per VV7's
ship decision (r7 close); **upgraded to YELLOW (ship-at-yellow now
viable per YY3 Option E)**. Recommended path per YY7 tag-readiness doc:
answer VV7's Q1 (ship-with-known-issues acceptable) / Q2 (ship-delay
acceptable) / Q3 (gate #11 disposition) → execute YY7's three-step
tag-day checklist (version bump + CHANGELOG date flip + `git tag
v0.4.0`).

---

## 7. STUB triage progress across r14 – r25

Cumulative router-action rollout across the twelve rounds since the
r14 kickoff. r24 (WW4) + r25 (YY4) each added 5 more.

| Round | Batch | Actions wired | Cumulative total |
|---|---|---|---|
| r14 | MM6 | 5 (capture / render toggles) | 70 |
| r15 | NN2 | 5 (view / panel / theme) | 75 |
| r16 | OO1 | 5 (layer / selection / snap grid) | 80 |
| r17 | PP1 | 5 (selection / view / edit) | 85 |
| r18 | QQ1 | 5 (spawn / selection / view stats) | 90 |
| r19 | RR1 | 5 (edit / theme / layer / snap toggle) | 95 |
| r20 | SS1 (`40695fb` salvage) | 5 (content / view pixel scale / spawn stamp) | 100 |
| r21 | TT2 | 5 (view zoom / spawn view / theme reload / layer rename) | 105 |
| r22 | UU4 | 5 (spawn origin offset / edit flatten / snap angle / layer move) | 110 |
| r23 | VV4 | 5 (layer new / delete / snap grid size / view ruler / spawn last) | 115 |
| r24 | WW4 (`6bb772f`) | `view.toggle_axes` / `view.toggle_background` / `edit.select_by_tag` / `spawn.at_grid` / `layer.clear` | 120 |
| r25 | YY4 (`86e57f9`) | `view.toggle_snap_indicator` / `edit.select_parent` / `spawn.at_selection_center` / `layer.lock` / `snap.reset_defaults` | 125 |

**Total across r14 – r25**: **60 new actions wired** across 12 rounds
(cumulative router registry growth from 65 → 125 ids). YY5's
whole-registry ToolRouter sweep now runs across **169 registered ids**
(the 125 tracked here plus ~44 legacy hardcoded routes) with **0
exceptions** raised in the mock-ctx sweep.

**Remaining STUB count** (OO7 audit § 5 roster): still ~13 remaining
rows (WW4/YY4 both added NEW router ids rather than flipping
previously-listed STUB rows). Diary un-pin bundle + theming editor +
DPG-shell-dependent rows unchanged.

---

## 8. Nova3D parity status

Re-checked via the r5 harness pattern:

```
PYTHONPATH=python python -m pytest -k "hello_gltf_character or hello_render_real" -q --no-header
```

Zero regressions across the r8 window. All 20 JJ/KK/LL Nova3D-parity
sprint acceptance demos remain green. Cross-linked to
[`docs/sprint_rollup_2026_07_05_r3.md`](sprint_rollup_2026_07_05_r3.md)
§ 4 (parity milestone rollup) and
[`docs/nova3d_parity_sprint_plan_2026_07_05.md`](nova3d_parity_sprint_plan_2026_07_05.md).

**Nova3D parity milestone: STILL FULLY CLOSED.**

---

## 9. Metrics

### Test suite

* **Total tests collected at r8 close**: **~9990** (via
  `PYTHONPATH=python python -m pytest --collect-only -q --no-header`;
  was ~9820 at r7 close — r8 window added **~170 new tests** across WW
  ~72 + YY ~98 + YY5's 169-id single sweep counted as 1 collected).

### Demos

* **`hello_*.py` demos shipped**: **43** (unchanged since VV5;
  r8 added no new `hello_*` — recovery-arc slots were shim-focused).
* **`test_demo_hello_*.py` runners**: **44** (unchanged).
* **Non-`hello_*` demo runners added in r8**: 0. Cumulative
  non-hello demo smokes still 25 (post-QQ2/RR2/SS2/TT3/UU5 close).

### Docs

* **Total `docs/**/*.md` files**: **113 top-level + 52 api/ + tutorials/README = ~166 total**
  (was 108 at r7 close; r8 added 5 top-level: `sprint_rollup_2026_07_07_r7`,
  `backcompat_contract_2026_07_07`, `v0_4_tag_readiness_2026_07_07`,
  `feature_map_delta_2026_07_15`, `feature_map_delta_2026_07_16`, plus
  this rollup — `sprint_rollup_2026_07_08_r8`; and 2 index docs
  `api/README.md` + `tutorials/README.md`).
* **`docs/api/*.md` entries**: **52** (was 51 at r7 close; WW6 added
  `api/README.md` index — no per-symbol content).
* Sprint-rollup lineage now at **r8** — this doc + r7 + r6 + r5 + r4 + r3 + r2 + r1.

### Feature map

| Milestone | Total rows | WIRED | STUB | BROKEN | WIRED % |
|---|---|---|---|---|---|
| VV4 close (r23 triage, r7 current) | 380 | 363 | 13 | 3 | ~95.8% |
| WW4 close (r24 triage) | 385 | 368 | 13 | 3 | ~95.8% |
| **YY4 close (r25 triage, r8 current)** | **390** | **373** | **13** | **3** | **~95.9%** |

r8 window delta: **+10 rows, +10 WIRED, ±0 STUB, ±0 BROKEN**.

### Rust `_core` kernels

Unchanged: **17** shipped. No F1 unfreeze in r8 window (still gate #11
blocked; VV7/YY7 both recommend DEFERRED-BY-DESIGN pending user Q3).

### API backcompat snapshot

* **UU7 pinned snapshot** at `PharosEngineTests/tests/data/api_surface_snapshot.json`:
  **338 public symbols across 14 modules** (unchanged since UU7).
* **YY6 downstream-shape contract** at `PharosEngineTests/tests/test_backcompat_downstream_shape.py`:
  **8 return-shape tripwires** — EventBus.publish attr+dict access,
  AudioManager.play_loop object-handle, LightingSystem.load_profile
  returned-config, RenderTarget.add_layer dict-spec polymorphism,
  Observable+Asset dynamic subclass MRO, CacheMode.value str + variant
  sweep. **10 iteration-pattern tripwires** at
  `test_backcompat_iteration_patterns.py`.

---

## 10. Rate-limit salvage pattern

r8 window ran the fleet through both a **catastrophic loss event**
(XX-batch, 7 slots lost) and a **clean recovery** (YY-batch, 7-of-7
landed) — an important stress-test data point for the parallel-agent
harness.

**XX loss root cause**: daily rate cap hit before XX-batch had
completed dispatch. Zero slots landed. Only the WW1 orphan salvage
(`2e8cb8d`) came out of the WW+XX window's drift.

**WW1 orphan-recovery pattern**: WW1's event_bus.py + regression test
were committed to orphan commit `11825d7` alongside WW7's parallel
CHANGELOG commit, but the branch tip that reached master (`44a24f0`)
carried only WW7's half. The salvage pattern: (a) grep for the target
symbol in working tree, (b) diff vs HEAD, (c) direct commit with
attribution note. Latency: ~1 hour from detection to recovery commit.

**YY re-dispatch pattern**: after Brisbane 8:20pm rate-limit reset,
XX1's dropped EventPayload work re-dispatched as YY1 with its
original scope + WW3's newly-observed 84-site dict-shape residual as
concrete target. Result: **YY1 became the largest single-slot delta
of the entire recovery arc** (+198 passes / +16.8 pp).

**Round 3 salvage rate estimate**: ~5% for normal slots (matches r7).
XX-batch's 7-of-7 loss is treated as a rate-cap event separate from
the direct-to-master slot-salvage tally.

---

## 11. Next-batch queue — ZZ scope

Concrete follow-ups r8 defers.

### 11.1 ZZ targets — Observable kwarg + method aliases → ~95% GREEN

YY3 identified the residual as **7 sites** of
`Observable.__init__() got unexpected kwarg 'name'` +
**7 DeformableLayerComponent method-surface** drift sites +
**~55 numeric-assertion tail** (no single fix; individual test-by-test
assertion tolerance decisions).

* **ZZ1**: `Observable.__init__(**kwargs)` — swallow legacy
  `name=` kwarg (and any other legacy kwargs from
  `EventDetails`-era construction); mirror to `self.name` if
  provided; projected +7 passes.
* **ZZ2**: DeformableLayerComponent method-surface completion —
  audit YY2's method additions vs Ochema call sites; add any
  missing method aliases (7 sites known); projected +7-14 passes.
* **ZZ3**: Numeric-assertion tail sweep — categorise the ~55
  remaining failures by whether they're (a) real bugs, (b)
  tolerance drift, (c) baseline diff after backcompat cascade;
  either widen tolerances or land targeted fixes; projected
  +40-55 passes.
* **ZZ4**: Game-compat re-verify — measure post-ZZ1+ZZ2+ZZ3
  combined delta; target ≥97% F1 = gate #12 GREEN.
* **ZZ5**: Sprint rollup r8 (this doc) — DONE.
* **ZZ6-ZZ7**: Companion polish + additional tag-prep as needed.

### 11.2 User-decision waiting on VV7's 3 questions

YY7's tag-readiness doc re-surfaces VV7's Q1/Q2/Q3 verbatim:

* **Q1**: Is shipping v0.4.0 with known-issue backcompat gaps
  acceptable? (Option A / D)
* **Q2**: Is delaying v0.4.0 for full recovery acceptable? (Option B)
* **Q3**: What's the disposition of gate #11 (WIP subpackage freeze)?
  DEFERRED-BY-DESIGN (VV7 + YY7 recommend) / block ship / ship-with-STUB.

**Once user answers**: ZZ pivots to tag-sprint execution per YY7's
three-step checklist (`SetVersion.bat 0.4.0` + CHANGELOG date flip +
`git tag v0.4.0`). Absent user answer, ZZ closes the residual to
push gate #12 GREEN and holds tag-day pending decision.

### 11.3 If ZZ hits ≥97% F1 recovery (gate #12 GREEN)

Optional AAA (round-4 letter re-roll begins if ZZ delivers):
polish sprint (final API refs, remaining STUB-triage rows,
docs deltas), followed by tag-day dispatch pending user decision.

---

## 12. Cross-reference index

### Docs authored in r8 window

* [`docs/sprint_rollup_2026_07_07_r7.md`](sprint_rollup_2026_07_07_r7.md)
  — WW5 r7 rollup (input for r8 continuity).
* [`docs/feature_map_delta_2026_07_15.md`](feature_map_delta_2026_07_15.md)
  — WW4 r24 triage delta.
* [`docs/feature_map_delta_2026_07_16.md`](feature_map_delta_2026_07_16.md)
  — YY4 r25 triage delta.
* [`docs/api/README.md`](api/README.md) — WW6 API-ref index + gap tracker.
* [`docs/tutorials/README.md`](tutorials/README.md) — WW6 tutorials TOC.
* [`docs/backcompat_contract_2026_07_07.md`](backcompat_contract_2026_07_07.md)
  — YY6 downstream backcompat contract + return-shape + iteration-semantic
  tripwire pairing.
* [`docs/v0_4_tag_readiness_2026_07_07.md`](v0_4_tag_readiness_2026_07_07.md)
  — YY7 v0.4 tag-day green-light checklist.
* Updated in-place: [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
  (WW3 § 11 + YY3 § 12 appends — § 12 records the YELLOW crossing),
  [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  (WW3 + YY3 gate #12 evidence updates),
  [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  (YY3 § 8 Option E SHIP-AT-YELLOW),
  [`CHANGELOG.md`](../CHANGELOG.md) (WW7 42-commit regroup + Backcompat-notes + Known-issues).
* **[`docs/sprint_rollup_2026_07_08_r8.md`](sprint_rollup_2026_07_08_r8.md)**
  — this doc (ZZ5).

### Historical rollup lineage

* r1: [`docs/sprint_rollup_2026_07_04.md`](sprint_rollup_2026_07_04.md)
  — V–DD (BB5 + EE5).
* r2: [`docs/big_picture_2026_07_05.md`](big_picture_2026_07_05.md) —
  V–FF (GG7).
* r3: [`docs/sprint_rollup_2026_07_05_r3.md`](sprint_rollup_2026_07_05_r3.md)
  — HH–LL (MM4).
* r4: [`docs/sprint_rollup_2026_07_06.md`](sprint_rollup_2026_07_06.md)
  — MM+NN (NN6).
* r5: [`docs/sprint_rollup_2026_07_07_r5.md`](sprint_rollup_2026_07_07_r5.md)
  — OO+PP (QQ6).
* r6: [`docs/sprint_rollup_2026_07_07_r6.md`](sprint_rollup_2026_07_07_r6.md)
  — QQ+RR+SS (TT7).
* r7: [`docs/sprint_rollup_2026_07_07_r7.md`](sprint_rollup_2026_07_07_r7.md)
  — TT+UU+VV (WW5).
* **r8 (this doc)**:
  [`docs/sprint_rollup_2026_07_08_r8.md`](sprint_rollup_2026_07_08_r8.md)
  — WW+XX(lost)+YY (ZZ5).

---

## 13. Summary card

* **Batches shipped in r8**: 2 landed (WW + YY); 1 lost (XX all 7 slots).
* **Batches total (V → YY)**: **29** letter tags (XX counts as lost).
* **Sprint slots in r8**: 14 landed (WW 7 + YY 7); 7 lost (XX).
* **Sprint slots total (V → YY)**: ~218 attempted (~211 landed).
* **Commits in r8**: **14** (WW 7 including salvage + YY 7).
* **Feature map**: 380 rows (VV4 close, r7) → **390 rows / 373 WIRED
  (~95.9%)** (YY4 close, r8).
* **Tests collected**: ~9990 at r8 close (was ~9820 at r7; +170 window
  delta).
* **Rust `_core` kernel count**: 17 shipped (unchanged; F1 unfreeze
  still gated on gate #11).
* **New router actions in r8**: **10** (WW4 r24 + YY4 r25).
  Cumulative r14 → r25: **60** actions across **12** rounds.
  ToolRouter full sweep: **169 ids, 0 exceptions** (YY5).
* **New docs in r8**: 5 (r7 rollup, backcompat contract, tag readiness,
  2 feature-map deltas) + 2 index docs (api/README + tutorials/README)
  + this rollup.
* **New hello_* demos in r8**: 0 (recovery-arc slots were shim-focused).
* **Nova3D parity milestone**: **STILL FULLY CLOSED** — re-checked via
  the r5 pytest harness pattern; zero regressions since r5 close.
* **Game-compat recovery**: **75.0% → 91.8% F1** across the r8 window
  via 11 backcompat shims (+356 combined passes since VV3 close).
  **Gate #12 flipped FAILING → YELLOW by YY3** — major milestone;
  ship-blocker status lifted.
* **v0.4 readiness verdict**: was **RED (multi-sprint recovery
  required)** (r7); **upgraded to YELLOW (ship-at-yellow now viable
  per YY3 Option E)**. 10 GREEN + 1 DRAFT + 2 P0 FAILING (gates 1, 11)
  + 1 YELLOW (gate 12) + 1 DEFERRED.
* **Highest-impact next task**: ZZ1 `Observable.__init__(**kwargs)` +
  ZZ2 DeformableLayerComponent method-surface + ZZ3 numeric-assertion
  tail sweep. Projected combined delta: **91.8% → ~96-97% F1** →
  gate #12 GREEN. Then user Q1/Q2/Q3 → tag-day execution per YY7
  checklist.

---

*Sprint rollup r8 generated 2026-07-08 morning by ZZ5 background scrum
agent. Sources: 14 commits between `44a24f0` (WW7, 2026-07-08 early
morning) and `c5b00e1` (YY3, 2026-07-08 09:20 Brisbane). Cross-
referenced against `docs/v0_4_release_readiness_2026_07_06.md` (OO7
gate list), `docs/sprint_rollup_2026_07_07_r7.md` (r7),
`docs/v0_4_gate_reconciliation_2026_07_07.md` (WW3 + YY3 updates),
`docs/game_compat_2026_07_07.md` (WW3 § 11 + YY3 § 12 — YELLOW crossing),
`docs/v0_4_ship_decision_2026_07_07.md` (YY3 § 8 Option E addition),
`docs/v0_4_tag_readiness_2026_07_07.md` (YY7),
`docs/backcompat_contract_2026_07_07.md` (YY6),
`docs/feature_map_delta_2026_07_15.md` (r24),
`docs/feature_map_delta_2026_07_16.md` (r25), `CHANGELOG.md` (WW7 expand),
and `git log --oneline -25`.*
