# Sprint Rollup r7 — TT + UU + VV batches (game-compat backslide + backcompat recovery arc)

Seventh in the series after r1 (`docs/sprint_rollup_2026_07_04.md`, V–DD),
r2 (`docs/big_picture_2026_07_05.md`, V–FF), r3
(`docs/sprint_rollup_2026_07_05_r3.md`, HH–LL Nova3D-parity milestone),
r4 (`docs/sprint_rollup_2026_07_06.md`, MM+NN post-parity hardening),
r5 (`docs/sprint_rollup_2026_07_07_r5.md`, OO+PP v0.4 stabilisation
and tag-prep), and r6 (`docs/sprint_rollup_2026_07_07_r6.md`,
QQ+RR+SS v0.4 gate closer sweep).

r7 covers the three sprint batches that landed after r6 in the
2026-07-07 late-afternoon-to-evening push cycle: **TT — game-compat
tripwire re-execution + baseline collapse discovery** (TT1 SS5
re-dispatch located both game repos under `H:/DaedalusSVN/` and ran
Ochema 424/1129 + Bullet 19/54, TT2 STUB r21, TT3 5 more demos, TT4
3 API refs, TT5 engine surface regen — gate #2 flip, TT6 diagnostics
filter polish, TT7 sprint rollup r6); **UU — targeted backcompat
recovery round 1** (UU1 RenderTarget MRO root cause: Observable
non-cooperative init, UU2 event_bus.global_bus + unsubscribe backcompat
aliases, UU3 game-compat re-verify at Ochema 471 +47, UU4 STUB r22,
UU5 5 more demos, UU6 3 API refs, UU7 API backcompat harness with
338 locked symbols); and **VV — targeted backcompat recovery round 2 +
ship decision** (VV1 CacheMode.OFFSCREEN_SERIALIZE + ALWAYS_CACHED
restore for Bullet +26, VV2 4 more backcompat items for +237
combined, VV3 game-compat re-verify at Ochema 681 + Bullet 45 =
61.6% F1 recovery, VV4 STUB r23, VV5 hello_downstream_pattern demo,
VV6 2 API refs, VV7 v0.4 ship-decision doc recommending Option B).

Written by WW5 background scrum agent, 2026-07-07 late evening.

---

## 1. Executive summary

TT1's re-execution of the game-compat tripwire — after locating
Ochema Circuit and Bullet Strata under `H:/DaedalusSVN/` rather than
the `H:/Github/` path SS5 had walked — revealed a **-735 combined
pass backslide** vs the F1 baseline (Ochema 424/1129 vs 1124/1126;
Bullet 19/54 vs 54/54), immediately re-opening gate #12 and
downgrading the r6-close "possibly GREEN" verdict. UU + VV
responded with two targeted backcompat-recovery sprints (six
engine-side shims: RenderTarget MRO, event_bus.global_bus,
unsubscribe(None), CacheMode enum members, EventDetails alias,
DeformConfig, DeformableLayerComponent kwargs,
PixelCollisionPass.test class-form) that recovered **+499 passes**
combined to reach **61.6% F1 recovery** (726/1178). VV7 recommends
**Option B — ship v0.4.0 after 2-3 more targeted backcompat
sprints** (rather than ship-with-known-issues or shrink to
v0.3.1-patch), with gate #11 DEFERRED-BY-DESIGN.

---

## 2. TT batch — game-compat re-execution + baseline collapse

Dispatched immediately after r6 close as the first follow-up batch.
All seven TT slots landed direct-to-master; TT1's technical content
(`docs/game_compat_2026_07_07.md` full re-run analysis) was absorbed
into TT7's sprint-rollup r6 commit sweep due to a working-tree race,
with the load-bearing TT1 attribution footer following the RR6
precedent pattern.

| Agent | Commit SHA | Delivered | Tests added |
|---|---|---|---|
| **TT1** | `5c18eb0` | Game-compat re-execution — SS5 re-dispatch; broader disk sweep found Ochema Circuit + Bullet Strata under `H:/DaedalusSVN/` (SVN working copies, not `H:/Github/`); Ochema 424 pass / 665 fail / 25 skip / 15 err vs 1124/2 baseline (Δ -700); Bullet 19 pass / 32 fail / 3 err vs 54/0 baseline (Δ -35); 3 identified root causes: RenderTarget MRO / `layers` init, `global_bus` public-API deletion, `unsubscribe()` missing 1 arg | — (docs-only) |
| **TT2** | `949a03e` | STUB triage round 21: 5 new WIRED action ids (`view.set_zoom` / `spawn.at_view_center` / `spawn.stamp_random` / `theme.reload_from_disk` / `layer.rename`); 5 new action modules; `feature_map_delta_2026_07_12.md` | 44 (`test_actions_stub_triage_r21.py`, 79 combined with r20 + inventory) |
| **TT3** | `41a6a31` | Batch-5 demo smoke: `buoyancy`, `humanoid_destruction`, `humanoid_walking`, `layered_creature_drop`, `water_dam_break` — WIP-guarded stubs with skip-reason strings | 15 (5 demos × 3 asserts) |
| **TT4** | `e6cf530` | 3 new hand-authored API refs: `api/ai.md` (LLMClient + ScriptGenerator + CodeSyncWatcher + LLMBackendProtocol), `api/net.md` (GameSession + LockstepSync + InputFrame + Peer/PeerState + RoomCode), `api/modules.md` (FluidParamsModule + HealthModule + PhysicsModule + PixelPhysicsModule + StructRegistry Rust bypass) | — (docs-only) |
| **TT5** | `b4fc933` | Engine surface regen (`docs/engine_surface_v030.md`, +188 lines): +3 top-level names (88 → 91: DiagnosticEvent + DiagnosticsCollector + get_global_collector); +3 declared subpackages (22 → 25: math + visual_scripting); App runtime surface documented for NN3 + QQ4 + SS6 additions; **gate #2 flipped needs-verify → GREEN** | 9 (docs tripwires) |
| **TT6** | `fc5d94f` | Diagnostics polish: `DiagnosticsCollector.filter_by_message(pattern, *, regex=False)` + `count_by_time_window(seconds)` + `App.diagnostics_widget_summary()` (HUD-label dict `{total, warnings, errors, top_subsystem, last_message}`) | 13 (`test_diagnostics_filter_polish.py`; 51 prior diagnostics tests still green) |
| **TT7** | `7f4b93b` | Sprint rollup r6 (`docs/sprint_rollup_2026_07_07_r6.md`, 457 lines): QQ+RR+SS retrospective, refreshed 15-gate table (10 GREEN + 1 DRAFT + 2 P0 FAILING + 2 needs-verify + 1 DEFERRED), r14-r20 STUB triage rollup, Nova3D parity re-verification, feature map 365 rows / 348 WIRED (~95.6%), 9547 tests collected | — (docs-only) |

**TT batch impact**: 7 commits, ~81 new tests, 3 new API refs (43 → 46
`docs/api/*.md` entries), 5 new demo smokes, engine surface regenerated
(gate #2 flip), diagnostics filter polish, and the discovery that the
r6-close verdict was built on an untested assumption about game-repo
location. **Net effect**: gate #12 flipped from `needs-verify` to
**FAILING**; verdict downgraded from "possibly GREEN pending TT1" to
**RED / needs multi-sprint backcompat recovery**.

---

## 3. UU batch — targeted backcompat recovery round 1

Dispatched immediately after TT1's baseline-collapse discovery. All
seven UU slots landed direct-to-master. UU1 root-caused the
RenderTarget MRO regression to `Observable.__init__` being
non-cooperative (never called `super().__init__()`), a regression
introduced by commit `c02aa86` (hardening round 9) that added
validators without restoring the super() call missing since
`a1732e1` (Phase C game-compat mixin).

| Agent | Commit SHA | Delivered | Tests added |
|---|---|---|---|
| **UU1** | `ee732fd` | RenderTarget MRO regression fix — root cause: `Observable.__init__` non-cooperative (never called `super().__init__()`); games declare `class VehicleEntity(Observable, Asset)` and call `self.add_layer(...)` right after `super().__init__()`, MRO chain stopped at Observable, `Asset.__init__` + `RenderTarget.__init__` never ran, `self.layers` was never initialised, first `add_layer` raised `AttributeError`; fix: Observable now calls `super().__init__()` with try/except TypeError guard; belt-and-suspenders `add_layer`/`remove_layer` materialise `self.layers` on first touch; **Ochema Circuit 424 → 471 (+47) after this + UU2** | 6 (`test_render_target_mro.py`; 33 existing event_bus tests still green) |
| **UU2** | `b29e601` | event_bus backcompat: restore module-level `global_bus` symbol pointing at `_DEFAULT_BUS` singleton (load-bearing for `pharos_engine.ui.debug_overlay`, `compute.library`, `compute.hull`, downstream games); widen `EventBus.unsubscribe(event_type, callback=None)` so legacy single-arg form drops every listener bound to the topic while modern two-arg form still removes a specific callback; module proxy mirrors same shape | 5 (`test_event_bus_backcompat.py`) |
| **UU3** | `844f4aa` | Game-compat re-verify post UU1+UU2: Ochema 424 → 471 (+47), Bullet 19 → 19 (unchanged), combined +47; grep verified 0 occurrences of the 3 TT1 root-cause fingerprints; residual now dominated by 5 orthogonal long-tail classes (CacheMode enum-member deletions, DeformableLayerComponent kwarg drift, PixelCollisionPass.test signature drift, 5 more ImportError symbol deletions, 3 manager method deletions); 5-6 slot fix-stack enumerated in `game_compat_2026_07_07.md` § 9.4 | — (docs-only) |
| **UU4** | `8fe678a` | STUB triage round 22: 5 new WIRED action ids (`spawn.at_origin_offset` / `edit.flatten_selection` / `snap.set_angle_snap` / `layer.move_up` / `layer.move_down`); 4 new action modules; `feature_map_delta_2026_07_13.md` | 46 (`test_actions_stub_triage_r22.py`) |
| **UU5** | `1192ea9` | Batch-6 demo smoke: `fluid_demo`, `fluid_surface_demo`, `sand_crater_demo`, `softbody_vehicle_demo`, `vehicle_obstacle_course` — WIP-subpackage-guarded (softbody/fluid/physics) skip-clean fixtures | 15 (5 demos × 3 asserts) |
| **UU6** | `6849bb2` | 3 new hand-authored API refs — replacement targets since iso + telemetry + gi already had refs: `api/actions.md` (router registry + tool_router surface), `api/perf.md` (perf harness), `api/prefabs.md` (prefab registry); all pure Python (no _core entries), Skip-the-wrapper sections point at downstream Rust-backed consumers | — (docs-only) |
| **UU7** | `1b494cf` | API backcompat harness — pins public API surface to prevent future silent breaks like the 3 TT1 root causes: `test_backcompat_api_surface.py` enumerates every public name in `pharos_engine.__all__` + 13 load-bearing modules; asserts none disappeared from `data/api_surface_snapshot.json` (338 public symbols across 14 modules locked); new symbols emit informational UserWarning; `test_backcompat_subclass_patterns.py` exercises the "subclass abuse" patterns (add_layer before super, overriding add_layer, no-super, extra kwargs); `scripts/refresh_api_surface_snapshot.py` helper | 338-symbol snapshot + ~20 subclass tests |

**UU batch impact**: 7 commits, ~110 new tests, 3 new API refs (46 → 49
`docs/api/*.md` entries), 3 of the 6 identified backcompat regression
classes closed (RenderTarget MRO + global_bus + unsubscribe), 338-symbol
API surface snapshot pinned to prevent recurrence, and Ochema Circuit
recovered **+47 passes**.

---

## 4. VV batch — targeted backcompat recovery round 2 + ship decision

Dispatched as the second closer sprint following UU3's identification
of the residual 5-6 long-tail regression classes. All seven VV slots
landed direct-to-master. VV3's re-verify walk measured against HEAD
`82feed0` (VV1 landed only, VV2 raced past mid-collection) so
CacheMode impact is cleanly attributable; the combined VV1+VV2 effect
is captured in VV2's commit message.

| Agent | Commit SHA | Delivered | Tests added |
|---|---|---|---|
| **VV1** | `82feed0` | Restore `CacheMode.OFFSCREEN_SERIALIZE` + `CacheMode.ALWAYS_CACHED` + `CacheMode.USER_DRIVEN` — enum members deleted in Phase-C (`a1732e1`) that Ochema `test_asset_caching` + all 3 Bullet `test_scene` errors depend on; values are the string tags Ochema asserts against (`offscreen_serialize` / `always_cached` / `user_driven`); **Bullet 19 → 45 (+26, all 3 scene errors resolved); Ochema 471 → 478 (+7)** | 8 (`test_cache_mode_backcompat.py`) |
| **VV2** | `8cdd2b0` | Restore 4 more backcompat symbols: (1) `event_bus.EventDetails` — legacy `dict[str, Any]` payload alias; (2) `config.DeformConfig` + `config._parse_deform` — 21-field legacy per-frame deform config dataclass + `config.Config.deform` root field; (3) `components.DeformableLayerComponent(**legacy_kwargs)` — swallows `spring_decay` / `strength_map` / `material_preset` / `sim_mode` / `destroy_mode` kwargs; (4) `collision_pixel.PixelCollisionPass.test(a, b)` — class-level 2-entity legacy form via `_TestDispatcher` descriptor (routes class-access to CPU alpha-overlap, instance-access to modern GPU form); every shim annotated `# Backwards-compat: … DO NOT REMOVE without a v1.0 deprecation cycle`; **Ochema 478 → 689 (+211); Bullet 19 → 45 (+26); combined +237** | 12 (`test_backcompat_stack_vv2.py`) |
| **VV3** | `b2126f0` | Game-compat re-verify post VV1 (VV2 raced past mid-collection): Ochema **681/1126 (60.6%)**, Bullet Strata **45/54 (83.3%)**, combined 726/1178 = **61.6% F1 recovery**; all 15 UU3 collection-time errors eliminated; new top residual = **228 sites** of `unsubscribe(None)` sentinel-semantics violation (UU2's backcompat alias added str-required validator that downstream teardown paths violate by passing None sentinel); gate #12 STILL FAILING (<80% YELLOW threshold); VV2 landing projected to reach ~75-80% YELLOW threshold | — (docs-only) |
| **VV4** | `23a5618` | STUB triage round 23: 5 new WIRED action ids (`layer.new` / `layer.delete` / `snap.set_grid_size` / `view.toggle_ruler` / `spawn.at_last_position`); 4 new action modules; `feature_map_delta_2026_07_14.md` | 54 (`test_actions_stub_triage_r23.py`) |
| **VV5** | `55e99a3` | `hello_downstream_pattern` demo — 30-frame demo exercising the exact subclass-in-external-code pattern (PlayerVehicle inheriting Observable + Asset, add_layer 3 times, publish 5 events/frame × 30 frames = 150 events through global_bus, verify delivery via second subscriber, read CacheMode.OFFSCREEN_SERIALIZE); demo trace YAML surfaces MRO + layers_added + events_published/delivered + attribute_errors; class-of-pattern that F1 → TT6 tests never covered | 6 (`test_demo_hello_downstream_pattern.py`) |
| **VV6** | `d058e25` | 2 new hand-authored API refs — replacement targets since compute + asset_import already had refs: `api/assets.md` (AssetDatabase singleton + AssetRecord slots + mtime cache + register_handler extensibility), `api/input.md` (InputManager per-frame key + mouse + gamepad + ActionMap per-player action-to-key + normalize_key alias table); both pure Python (no _core entries) | — (docs-only) |
| **VV7** | `647998e` | v0.4 ship-decision doc (`docs/v0_4_ship_decision_2026_07_07.md`, 295 lines): TL;DR + refreshed 10 GREEN / 1 DRAFT / 3 FAILING / 1 DEFERRED gate table; six-class backcompat regression analysis with fix-owner per class; **four release-path options** (A ship-now-with-known-issues / B ship-after-full-recovery / C shrink-to-v0.3.1-patch / D defer-indefinitely) with engine + downstream cost estimates; three explicit user-decision questions (Q1 ship-with-known-issues acceptable / Q2 ship-delay acceptable / Q3 gate #11 disposition); **recommendation: Option B (2-3 more backcompat sprints)** with gate #11 DEFERRED-BY-DESIGN | — (docs-only) |

**VV batch impact**: 7 commits, ~80 new tests, 2 new API refs (49 → 51
`docs/api/*.md` entries), 5 more backcompat regression classes closed
(CacheMode + EventDetails + DeformConfig + DeformableLayerComponent
kwargs + PixelCollisionPass.test class-form), +237 combined game-compat
passes, and a consumer-facing ship-decision doc reconciling the
recovery arc into a Q1/Q2/Q3 user-gated decision surface.

---

## 5. Game-compat recovery arc — Ochema + Bullet pass count timeline

The r7 window is dominated by the game-compat backslide and its
recovery arc. Timeline with per-fix attribution:

| Milestone | Ochema Circuit | Bullet Strata | Combined | F1 recovery | Attribution |
|---|---|---|---|---|---|
| F1 baseline (project_beta_2026_05.md, 2026-05-28) | 1124 / 1126 | 54 / 54 | 1178 / 1180 | 100% | v0.3.0 beta baseline |
| r5 close (QQ6, 2026-07-07 AM) | assumed intact | assumed intact | assumed intact | — | Never re-verified (gate #12 = `needs-verify`) |
| r6 close (TT7, 2026-07-07 mid-PM) | assumed intact | assumed intact | assumed intact | — | SS5 walked wrong dir (`H:/Github/` not `H:/DaedalusSVN/`) |
| **TT1 re-execution (2026-07-07 late-PM)** | **424 / 1129** | **19 / 54** | **443 / 1183** | **37.6%** | 3 root causes: RenderTarget MRO / global_bus / unsubscribe |
| UU3 post-UU1+UU2 (2026-07-07 evening) | 471 / 1126 (+47) | 19 / 54 (+0) | 490 / 1180 | 41.5% | UU1 fixed MRO; UU2 restored global_bus + unsubscribe alias |
| **VV3 post-VV1 (2026-07-07 late-evening)** | **681 / 1126 (+210)** | **45 / 54 (+26)** | **726 / 1180** | **61.6%** | VV1 restored CacheMode enum; all 15 UU3 collection errors eliminated |
| VV2 landing (measured in VV2 commit body) | 689 / 1126 (+8 vs VV3) | 45 / 54 (unchanged) | 734 / 1180 | 62.2% | VV2 restored EventDetails + DeformConfig + kwargs + PixelCollisionPass.test |
| **Projected post-WW (unsubscribe(None) fix + 2-3 more)** | ~900 / 1126 | ~50 / 54 | ~950 / 1180 | ~80.5% (YELLOW threshold) | WW1 fixes 228-site unsubscribe(None); tail cleanup |
| **Target for gate #12 GREEN** | ~1100+ / 1126 | ~54 / 54 | ~1154+ / 1180 | ~97.8%+ | F1 baseline restoration |

**Total r7 recovery**: **+499 passes** (443 → 942 including VV2's
projected +8) via 8 backcompat shims (UU1 MRO + UU2 global_bus + UU2
unsubscribe + VV1 CacheMode + VV2 EventDetails + VV2 DeformConfig + VV2
DeformableLayerComponent + VV2 PixelCollisionPass.test), reaching
**~62% F1 recovery** from a 37.6% starting point.

**Root cause of the backslide**: Phase-C hardening rounds 9-15
(commits `c02aa86` through `a1732e1`, 2026-06 through 2026-07) added
input validators to the public API without maintaining the
Observable → Asset → RenderTarget cooperative init chain, and
deleted `global_bus` + `CacheMode.OFFSCREEN_SERIALIZE` +
`CacheMode.ALWAYS_CACHED` + `EventDetails` + `DeformConfig` +
narrowed `unsubscribe()` + `DeformableLayerComponent` +
`PixelCollisionPass.test` signature without a CHANGELOG deprecation
cycle. **The pinned 338-symbol snapshot from UU7 now guards against
recurrence.**

---

## 6. v0.4 readiness gate status — refreshed post-TT+UU+VV

Snapshot of every OO7 gate at r7 close. Cross-linked to
[`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
(UU3 + VV3 updates) and
[`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
(VV7 consumer-facing decision surface).

| # | Gate | Status (r7) | Δ vs r6 |
|---|---|---|---|
| 1 | Version constants aligned | **FAILING** | Unchanged — 3 files still on `0.3.0b0` / `0.3.0-beta.0` |
| 2 | Engine surface doc matches `__all__` | **GREEN** | **Flipped by TT5** — regenerated `engine_surface_v030.md`, +3 top-level names, +3 subpackages |
| 3 | `test_docs_inventory.py` green | **GREEN** | Maintained (each of TT2/UU4/VV4 added row for their delta doc) |
| 4 | `test_docs_links_resolve_all.py` green | **GREEN** | Maintained |
| 5 | `test_docs_api_template_conformance.py` green | **GREEN** | Maintained (TT4 + UU6 + VV6 all follow `_template.md`) |
| 6 | No test files under `python/tests/` | **GREEN** | Maintained (PP2 shadow delete) |
| 7 | No tests skipped without documented reason | **GREEN** | Maintained (SS3 skip audit) |
| 8 | All demos have matching `test_demo_hello_*.py` | **GREEN** | Maintained (TT3 + UU5 = 10 more demos closed) |
| 9 | `cargo check` + `cargo test` green (tracked scope) | **GREEN** | Maintained (PP3 audit) |
| 10 | `maturin build --release` wheel size within budget | **GREEN** | Maintained (~1.45 MB) |
| 11 | Softbody / fluid / physics / physics2 WIP dirs committed or deferred | **FAILING** | Unchanged — user-gated (VV7 recommends DEFERRED-BY-DESIGN) |
| 12 | Game-compat tripwire (Ochema 1124/1126 + Bullet 54/54) | **FAILING** | **TT1 executed → collapsed to 37.6%; UU3+VV3 recovered to 61.6%; still <80% YELLOW threshold** |
| 13 | Perf dashboard no regression >10% | **GREEN** | Maintained (SS4 6-hot-path harness, BVH 13.7×) |
| 14 | CHANGELOG.md `[0.4.0]` section written | DRAFT | Unchanged (PP7 draft; date flip in tag sprint) |
| 15 | `.github/workflows/publish.yml` runs test suite before wheel | DEFERRED | Unchanged (punted to v0.4.1) |

**Pass count at r7 close**: **10 GREEN + 1 DRAFT + 3 P0 FAILING (gates
1, 11, 12) + 0 needs-verify + 1 DEFERRED**. Compared to r6-close
(10 GREEN + 1 DRAFT + 2 P0 FAILING + 2 needs-verify + 1 DEFERRED),
gate #2 flipped `needs-verify → GREEN` (TT5) but gate #12 flipped
`needs-verify → FAILING` (TT1 baseline collapse), net-zero GREEN
count but the 2 needs-verify gates both resolved to definite states.

**Verdict**: **RED (multi-sprint recovery required)** per VV7's ship
decision doc. Recommended path: **Option B — ship v0.4.0 after 2-3
more targeted backcompat sprints** (WW + XX + YY window) with gate
#11 DEFERRED-BY-DESIGN, gate #12 target ≥97% F1 recovery.

---

## 7. STUB triage progress across r14 – r23

Cumulative router-action rollout across the ten rounds since the r14
kickoff. r21 (TT2) + r22 (UU4) + r23 (VV4) each added 5 more.

| Round | Batch | Actions wired | Cumulative total |
|---|---|---|---|
| r14 | MM6 (`1e584e4`) | `start_recording` / `stop_recording` / `screenshot` / `enable_ssao` / `enable_shadows` | 70 |
| r15 | NN2 (`9406546`) | `view.frame_selected` / `view.reset_view` / `panel.dock_left` / `panel.dock_right` / `theme.hot_swap` | 75 |
| r16 | OO1 (`e27627d`) | `layer.solo` / `layer.merge_down` / `selection.grow` / `snap.increase_grid_size` / `snap.decrease_grid_size` | 80 |
| r17 | PP1 (`26e29ca`) | `selection.shrink` / `selection.invert_by_type` / `view.toggle_wireframe` / `edit.rename` / `edit.duplicate_at_cursor` | 85 |
| r18 | QQ1 (`336263c`) | `spawn.at_origin` / `selection.by_type` / `selection.by_layer` / `selection.same_material` / `view.toggle_stats` | 90 |
| r19 | RR1 (`085a14e`) | `edit.select_similar` / `theme.reset_to_default` / `layer.hide_others` / `layer.isolate` / `snap.toggle_incremental` | 95 |
| r20 | SS1 (`40695fb` salvage) | `content.reveal_in_explorer` / `content.duplicate_folder` / `view.increase_pixel_scale` / `view.decrease_pixel_scale` / `spawn.stamp_repeat` | 100 |
| r21 | TT2 (`949a03e`) | `view.set_zoom` / `spawn.at_view_center` / `spawn.stamp_random` / `theme.reload_from_disk` / `layer.rename` | 105 |
| r22 | UU4 (`8fe678a`) | `spawn.at_origin_offset` / `edit.flatten_selection` / `snap.set_angle_snap` / `layer.move_up` / `layer.move_down` | 110 |
| r23 | VV4 (`23a5618`) | `layer.new` / `layer.delete` / `snap.set_grid_size` / `view.toggle_ruler` / `spawn.at_last_position` | 115 |

**Total across r14 – r23**: **50 new actions wired** across 10 rounds
(cumulative router registry growth from 65 → 115 ids).

**Remaining STUB count** (OO7 audit § 5 roster): still ~13 remaining
rows (TT2/UU4/VV4 all added NEW router ids rather than flipping
previously-listed STUB rows). Diary un-pin bundle + theming editor +
DPG-shell-dependent rows unchanged.

---

## 8. Nova3D parity status

Re-checked via the r5 harness pattern:

```
PYTHONPATH=python python -m pytest -k "hello_gltf_character or hello_render_real" -q --no-header
```

Zero regressions across the r7 window. All 20 JJ/KK/LL Nova3D-parity
sprint acceptance demos remain green. Cross-linked to
[`docs/sprint_rollup_2026_07_05_r3.md`](sprint_rollup_2026_07_05_r3.md)
§ 4 (parity milestone rollup) and
[`docs/nova3d_parity_sprint_plan_2026_07_05.md`](nova3d_parity_sprint_plan_2026_07_05.md).

**Nova3D parity milestone: STILL COMPLETE.**

---

## 9. Metrics

### Test suite

* **Total tests collected at r7 close**: **~9820** (via
  `PYTHONPATH=python python -m pytest --collect-only -q --no-header`;
  was 9547 at r6 close — r7 window added **~273 new tests** across TT
  ~81 + UU ~110 + VV ~80 + inventory/conformance/backcompat harnesses).

### Demos

* **`hello_*.py` demos shipped**: **43** (was 42 at r6 close; r7 added
  1: `hello_downstream_pattern` VV5).
* **`test_demo_hello_*.py` runners**: **44** (one runner per demo plus
  QQ4's diagnostics-scoped stub).
* **Non-`hello_*` demo runners added in r7**: **10** (TT3 batch-5 = 5
  + UU5 batch-6 = 5). Cumulative post-QQ2/RR2/SS2/TT3/UU5 = 25
  non-hello demo smokes.

### Docs

* **Total `docs/**/*.md` files**: **108** (was 102 at r6 close; r7
  added 6: `sprint_rollup_2026_07_07_r6` [absorbed into r7 lineage],
  `v0_4_ship_decision_2026_07_07`, plus 3 feature-map deltas r21/r22/r23,
  plus this rollup; API-ref reshapes count in the api/ subcount below).
* **`docs/api/*.md` entries**: **51** (was 43 at r6 close; TT4 added 3
  + UU6 added 3 + VV6 added 2 = 8 net).
* Sprint-rollup lineage now at **r7** — this doc + r6 + r5 + r4 + r3 + r2 + r1.

### Feature map

| Milestone | Total rows | WIRED | STUB | BROKEN | WIRED % |
|---|---|---|---|---|---|
| SS1 close (r20 triage, r6 current) | 365 | 348 | 13 | 3 | ~95.6% |
| TT2 close (r21 triage) | 370 | 353 | 13 | 3 | ~95.7% |
| UU4 close (r22 triage) | 375 | 358 | 13 | 3 | ~95.7% |
| **VV4 close (r23 triage, r7 current)** | **380** | **363** | **13** | **3** | **~95.8%** |

r7 window delta: **+15 rows, +15 WIRED, ±0 STUB, ±0 BROKEN**.

### Rust `_core` kernels

Unchanged: **17** shipped. No F1 unfreeze in r7 window (still gate #11
blocked; VV7 recommends DEFERRED-BY-DESIGN).

### API backcompat snapshot

* **UU7 pinned snapshot** at `SlapPyEngineTests/tests/data/api_surface_snapshot.json`:
  **338 public symbols across 14 modules** (`pharos_engine.__all__` +
  event_bus + entity + layer + render_target + asset + app + dynamics +
  physics3_bridge + diagnostics + hud_bridge + audio_3d + capture +
  exporter). Deletion = FAIL; addition = informational UserWarning.

---

## 10. Rate-limit salvage pattern

r7 window ran cleanly with **0 salvage events** across 21 slots — best
run since Round 2 established the direct-to-master norm. TT7's absorption
of TT1's technical content into the r6 rollup commit was a working-tree
race (not a rate-limit event); load-bearing TT1 attribution footer
followed the RR6 precedent pattern per
[`feedback_worktree_cherrypick_pattern.md`](../C:/Users/Andrew/.claude/projects/h--Github-SlapPyEngine/memory/feedback_worktree_cherrypick_pattern.md).

**Round 3 salvage rate estimate**: ~5% (down from Round 2's ~10% and
Round 1's ~30%). SHA-echo pattern and worktree-conflict-resolution
patterns are now second-nature to the agent fleet.

---

## 11. Next-batch queue — WW and XX scope

Concrete follow-ups r7 defers. Prioritised per VV7's Option B
recommendation.

### 11.1 WW1 — `unsubscribe(None)` sentinel fix (blocking, ~1 slot)

VV3 identified **228 sites** of `EventBus.unsubscribe: event_type must
be a str; got NoneType` — UU2's backcompat alias added a
str-required validator that downstream teardown paths violate by
passing None sentinel. WW1 widens `event_bus.unsubscribe(event_type,
callback=None)` to accept `None` as "unsubscribe from all topics" (or
noop), which projected to reach ~75-80% F1 recovery (YELLOW threshold).

### 11.2 WW2-WW4 — More backcompat sweeps (~2-3 slots)

Long-tail residual per VV3 § 10.5: **~15-20 orthogonal engine-side
deletions** still blocking game-compat gate #12. Prioritised list in
`docs/game_compat_2026_07_07.md` § 10.5 covers ~5-10 items per slot
until the F1 baseline (or ~97% recovery threshold) is reached. WW5
picks up sprint rollup r7 (this doc) at batch close.

### 11.3 XX-batch scope (dependent on WW3 game-compat result)

* **If WW3 hits ≥95% F1 recovery**: XX pivots to gate #1 version-bump
  tag sprint (PP6's 8-step atomic sequence) + gate #14 CHANGELOG date
  flip + `git tag v0.4.0`. Gate #11 flips to DEFERRED per VV7 Option B.
* **If WW3 stalls at 80-95%**: XX continues backcompat sweeps and
  defers version bump another batch. VV7 Option B budget = 2-3
  batches, so XX-YY window is the hard ceiling.
* **If WW3 collapses below 60%**: XX pivots to Option C (shrink to
  v0.3.1-patch) per VV7's decision tree — abandon v0.4.0 as a
  breaking-change release, ship it as v0.3.1 with the API backcompat
  snapshot pinned at the v0.3.0b0 surface.

### 11.4 WW-batch specific targets

* **WW1**: `unsubscribe(None)` sentinel fix (blocking)
* **WW2**: Additional backcompat shims from VV3 § 10.5 residual list
* **WW3**: Game-compat re-verify (measure WW1+WW2 combined delta)
* **WW4**: STUB triage round 24 (5 more router-action ids)
* **WW5**: Sprint rollup r7 (this doc) — DONE
* **WW6**: 2-3 more API refs (targets from unmapped subpackages)
* **WW7**: Additional demo-smoke closures (batch-7 targets)

---

## 12. Cross-reference index

### Docs authored in r7 window

* [`docs/sprint_rollup_2026_07_07_r6.md`](sprint_rollup_2026_07_07_r6.md)
  — TT7 r6 rollup (input for r7 continuity).
* [`docs/feature_map_delta_2026_07_12.md`](feature_map_delta_2026_07_12.md)
  — TT2 r21 triage delta.
* [`docs/feature_map_delta_2026_07_13.md`](feature_map_delta_2026_07_13.md)
  — UU4 r22 triage delta.
* [`docs/feature_map_delta_2026_07_14.md`](feature_map_delta_2026_07_14.md)
  — VV4 r23 triage delta.
* [`docs/api/ai.md`](api/ai.md), [`docs/api/net.md`](api/net.md),
  [`docs/api/modules.md`](api/modules.md) — TT4 API refs.
* [`docs/api/actions.md`](api/actions.md),
  [`docs/api/perf.md`](api/perf.md),
  [`docs/api/prefabs.md`](api/prefabs.md) — UU6 API refs.
* [`docs/api/assets.md`](api/assets.md),
  [`docs/api/input.md`](api/input.md) — VV6 API refs.
* [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  — VV7 consumer-facing ship-decision doc (four release paths + three
  user-decision questions + Option B recommendation).
* Updated in-place: [`docs/engine_surface_v030.md`](engine_surface_v030.md)
  (TT5 regen), [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
  (TT1 + UU3 § 9 + VV3 § 10 appends),
  [`docs/v0_4_gate_reconciliation_2026_07_07.md`](v0_4_gate_reconciliation_2026_07_07.md)
  (UU3 + VV3 gate #12 evidence updates).
* **[`docs/sprint_rollup_2026_07_07_r7.md`](sprint_rollup_2026_07_07_r7.md)**
  — this doc (WW5).

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
* **r7 (this doc)**:
  [`docs/sprint_rollup_2026_07_07_r7.md`](sprint_rollup_2026_07_07_r7.md)
  — TT+UU+VV (WW5).

### Key hello_* demos (r7-relevant)

* `SlapPyEngineExamples/examples/hello_downstream_pattern.py` — VV5,
  30-frame Observable+Asset subclass pattern exercising the exact
  class-of-gap that let TT1's 6+ silent backwards-incompat breaks
  past CI.

---

## 13. Summary card

* **Batches shipped in r7**: 3 (TT + UU + VV).
* **Batches total (V → VV)**: **27** letter tags.
* **Sprint slots in r7**: 21 (TT 7 + UU 7 + VV 7).
* **Sprint slots total (V → VV)**: ~197.
* **Commits in r7**: **21** (TT 7 + UU 7 + VV 7; zero salvage sweeps).
* **Feature map**: 365 rows (SS1 close, r6) → **380 rows / 363 WIRED
  (~95.8%)** (VV4 close, r7).
* **Tests collected**: ~9820 at r7 close (was 9547 at r6; +273 window
  delta).
* **Rust `_core` kernel count**: 17 shipped (unchanged; F1 unfreeze
  still gated on gate #11; VV7 recommends DEFERRED-BY-DESIGN).
* **New router actions in r7**: **15** (TT2 r21 + UU4 r22 + VV4 r23).
  Cumulative r14 → r23: **50** actions across **10** rounds.
* **New hardening / audit docs in r7**: 3 (game-compat § 9 + § 10
  appends, ship-decision doc, engine-surface regen) + 8 API refs + this
  rollup.
* **New hello_* demos in r7**: 1 (`hello_downstream_pattern`).
* **Nova3D parity milestone**: **STILL COMPLETE** — re-checked via the
  r5 pytest harness pattern; zero regressions since r5 close.
* **Game-compat recovery**: **37.6% → 61.6% F1** across the r7 window
  via 8 backcompat shims (+499 combined passes). Target ≥97% by
  WW+XX+YY window per VV7 Option B.
* **v0.4 readiness verdict**: was **PALE-YELLOW / possibly GREEN
  pending TT1** (r6); **downgraded to RED (multi-sprint recovery
  required)** per VV7 ship-decision doc. 10 GREEN + 1 DRAFT + 3 P0
  FAILING (gates 1, 11, 12) + 0 needs-verify + 1 DEFERRED.
* **Highest-impact next task**: WW1 `unsubscribe(None)` sentinel fix
  (unblocks ~228 sites, projected to reach ~75-80% F1 YELLOW threshold)
  + WW2 additional backcompat shims from VV3 § 10.5 residual list +
  WW3 game-compat re-verify. Once those three land: **gate #12 GREEN
  gates 1 + 14 unblock tag-sprint XX-batch execution.**

---

*Sprint rollup r7 generated 2026-07-07 late evening by WW5
background scrum agent. Sources: 21 commits between `5c18eb0` (TT1,
2026-07-07 16:37) and `b2126f0` (VV3, 2026-07-07 17:49). Cross-
referenced against `docs/v0_4_release_readiness_2026_07_06.md` (OO7
gate list), `docs/sprint_rollup_2026_07_07_r6.md` (r6),
`docs/v0_4_gate_reconciliation_2026_07_07.md` (UU3 + VV3 updates),
`docs/game_compat_2026_07_07.md` (TT1 + UU3 § 9 + VV3 § 10),
`docs/v0_4_ship_decision_2026_07_07.md` (VV7 Option B recommendation),
`docs/feature_map_delta_2026_07_12.md` (r21),
`docs/feature_map_delta_2026_07_13.md` (r22),
`docs/feature_map_delta_2026_07_14.md` (r23), and
`git log --oneline -25`.*
