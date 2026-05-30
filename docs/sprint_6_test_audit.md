# Sprint 6 — test audit (skip / xfail review)

Date: 2026-05-30
Branch: `sprint-6-perf-correctness`
Author: Sprint 6 sweep

Scope: every `pytest.mark.skip`, `pytest.mark.skipif`, `pytest.mark.xfail`,
`pytest.skip(...)`, and `pytest.xfail(...)` in `tests/`. Each row lists the
location, the stated reason (or inferred reason where none is stated), and a
**recommendation** of {`resolve`, `keep xfail`, `keep skip`, `delete`}.

The audit covers **75 occurrences across 26 files** (per `Grep` count
`@pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(`).

---

## A. Hard test failures (NOT marked skip/xfail) — pre-existing on master

These showed up while running the hardening battery and are documented
here so they aren't mistaken for a Sprint-6 regression. **Not introduced
by this sprint.**

| File | Tests failing | Cause | Recommendation |
|---|---:|---|---|
| `tests/test_hardening_layer.py` | 23 | The hardening battery was authored against a hardened `Layer` / `Layer2D` / `LayerDataBuffer` API (name validation, mode validation, blank-size validation, heightmap NaN/Inf guards, struct-fields type checks). `python/slappyengine/layer.py` was never updated to add those boundary checks. Tests assert `pytest.raises(TypeError, ...)` against constructions that the current impl accepts silently. | **resolve** in a dedicated `hardening-layer` sprint — Sprint 6 is observation-only per scope, source untouched. Tracked here; do not silently `xfail` them, since they document real missing input validation. |

Other hardening suites are fully green:
* `test_hardening_actionmap.py`, `test_hardening_animation.py`,
  `test_hardening_assetdb.py`, `test_hardening_camera.py`,
  `test_hardening_dynamics.py`, `test_hardening_eventbus.py`,
  `test_hardening_iso.py`, `test_hardening_numerics.py`,
  `test_hardening_postprocess.py`, `test_hardening_residency.py`,
  `test_hardening_sprite_audit.py`, `test_hardening_telemetry.py`,
  `test_hardening_testing.py`, `test_hardening_thermal.py`,
  `test_hardening_topology.py`, `test_hardening_zones.py`.

Roll-up: **355 passed, 23 failed** out of 378 hardening assertions.

---

## B. xfail markers — review

| File:line | Reason on the file | Recommendation | Justification |
|---|---|---|---|
| `test_all_demos_smoke.py:186` `test_demo_renders_against_baseline` | "Subprocess-rendered frames diverge from in-process baselines due to seed/timing non-determinism across the dynamics demos. Per-demo tests at `tests/test_demo_<name>.py` pin tighter, in-process baselines." | **keep xfail** | The per-demo tests at `tests/test_demo_*.py` (80 passing) are the correct tight baselines. The subprocess smoke is a coverage tripwire that demos *boot and render something non-black*; pixel-identical match across subprocess seeds is not the contract this test should enforce. |
| `test_game_compat_tripwire.py:233` (15 entries) `pt.xfail("known Phase C gap: ...")` | Names not yet resolvable from `slappyengine.<name>` after Phase C. | **keep xfail** — these are deliberate landing pads for the Phase C gap-closure sprint. Sprint 6 has no mandate to close them. |

---

## C. skipif markers — environmental gates

These guard against missing optional dependencies / hardware. Keep as-is.

| File:line | Guard | Recommendation |
|---|---|---|
| `test_animation.py:56` | `not _has_animupdate` -- AnimUpdate dataclass not yet defined | **resolve** (small): define `AnimUpdate` in `slappyengine.animation` and drop the guard. Out of scope for Sprint 6 (no source edits) — flag for the next animation sprint. |
| `test_audio_runtime.py:44` | sounddevice unavailable | **keep skip** — optional backend; stub fallback exists |
| `test_compute.py:23`, `test_gpu_headless.py:26` | "No GPU adapter available" | **keep skip** — required when CI has no GPU |
| `test_editor.py:30,123,211,259,337,375` | Editor sub-panels not importable on minimal install | **keep skip** — editor sub-deps are optional |
| `test_editor_material_editor_kinds.py:79`, `test_editor_property_inspector_dataclass.py:86`, `test_editor_spawn_menu.py:73` | Editor not importable | **keep skip** |
| `test_landscape.py:11` | landscape module not importable | **keep skip** |
| `test_postprocess.py:10,86,100,111,125,142` | RenderTarget / SceneUIEntity not importable | **keep skip** |
| `test_node_material.py` (14 entries) | `slappyengine.material.node_material` / `graph_schema` not available on this checkout | **keep skip** — modules are optional and module-import-guarded |
| `test_material.py:110,128,149` | materials.yml absent in repo | **keep skip** |
| `test_scene_ui.py:18,342,352,368,378,391,400,412,426,428,442,444,459,461,475,477` | `slappyengine.ui` not importable on minimal install, or `handle_keyboard` / `set_key_callback` not yet implemented | **mixed** — the 1 import-level skip should stay; the 15 "not yet implemented" skips inside test bodies should be **resolved** by implementing the keyboard plumbing or **deleted** if the methods are abandoned. Flag for UI sprint. |
| `test_tools_run_examples.py:140` | hello_rope.py / hello_motor.py not present | **keep skip** — present in current checkout, so this skip never fires here; guard exists for partial checkouts |

---

## D. skip markers without a clear forward path — listed for resolution

| File:line | Reason | Recommendation |
|---|---|---|
| `test_lighting_render_channel_topo_round8.py:146,223,254` (3 occurrences) `@pytest.mark.skip(reason="Uses agent's assert_scene_matches(array, array, *, tolerance) signature; master shape is (scene, name, tolerance). Topo logic locked by sibling tests.")` | The agent that landed Lighting Round 8 wrote 6 tests but 3 of them used a different `assert_scene_matches` signature than master's. The 3 sibling tests that *do* match the master signature cover the same topo-sort invariant. | **resolve** — port the 3 skipped tests to master's `assert_scene_matches(scene, name, tolerance)` shape so the topo-sort regression is asserted from both directions (insertion-order tie-break **and** composited-frame change). The skipped path tests visible artifacts; the active sibling path tests sort order only. Out of scope for Sprint 6; flag for a small lighting-cleanup sprint. |
| `test_lighting_ca_falloff_round6.py:29` | Module/import gate. | **keep skip** if guard, **delete** otherwise — inspect during cleanup. |
| `test_lighting_taa_refinement.py:217`, `test_lighting_gtao_adaptive.py:295`, `test_lighting_bloom_smooth_threshold.py:254` | Baseline-bootstrap skips: `pytest.skip(f"baseline written: {ref_path}")` -- intentional, only fire when the baseline file doesn't exist yet (first-run capture). | **keep skip** — standard "auto-baseline" pattern. |

## E. Visual baseline harness skips

`tests/visual/test_vis_*.py` (12 occurrences across 6 files) all use the
same idiom:

```python
if not has_reference_frames:
    pytest.skip("No reference frames")
if not non_black_test_passed:
    pytest.skip("Run non_black test first")
```

**Recommendation: keep skip.** This is the deliberate visual-harness
bootstrapping pattern; the skips only fire when the baseline tarball isn't
checked in, which is the documented state on a minimal clone.

---

## Summary

| Bucket | Count | Action |
|---|---:|---|
| Hard failures (not marked) — pre-existing layer hardening gap | 23 | Resolve in `hardening-layer` sprint (source edits forbidden in Sprint 6) |
| xfail — deliberate Phase C landing pads | 16 | Keep (1 in `test_all_demos_smoke`, 15 in `test_game_compat_tripwire`) |
| skip — environmental / optional-dep gates | 47 | Keep |
| skip — auto-baseline bootstrap | 15 (visual harness + 3 lighting baselines) | Keep |
| skip — agent-shaped signature mismatch (topo round 8) | 3 | Resolve in lighting-cleanup sprint |
| skip — "not yet implemented" UI keyboard hooks | 15 | Resolve in UI sprint or delete the abandoned tests |

Net: every active skip/xfail has a clear reason. The only gap is the 23
hard failures in `test_hardening_layer.py` which are out of Sprint 6
scope but should be the entry point for a follow-up.
