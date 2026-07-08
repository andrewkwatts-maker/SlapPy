# v0.4 Tag-Readiness Green-Light Checklist — 2026-07-07 (YY7)

Atomic tag-day checklist for `v0.4.0`. This is the operational
sibling to VV7's ship-decision doc
([`v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md))
and PP6's version-bump audit
([`version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)):
once the user answers VV7's Q1/Q2/Q3 and the P0 gates flip GREEN,
the tag-day operator executes the three steps below in order.

Written by **YY7** background scrum agent (re-dispatch of XX7),
2026-07-07 late-evening batch. **Docs-only.** No version strings
or Python source touched.

---

## 1. TL;DR

Tag-day is a **three-step, all-or-nothing** mechanical sequence:
version-string bump, CHANGELOG date flip, `git tag` + `git push`.
Do not start until the four pre-tag verification checks in § 3 are
GREEN and every VV7 user-decision question in § 7 has an answer.
If the post-tag wheel smoke fails (§ 4), execute the rollback in
§ 5 and re-tag as `v0.4.0.post1` — do not amend a pushed tag.

---

## 2. The 3-item tag checklist

Atomic. Execute strictly in order. Each step's success gate is
listed inline; **stop and report** if any gate fails.

### Step 1 — Update version strings

Bump the three canonical version-string sites in one atomic commit.
The `SetVersion.bat` helper at the repo root wraps all three:

```
SetVersion.bat 0.4.0
```

Files touched (per PP6's audit —
[`version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
§ Scope):

| File | Line | Old | New |
|---|---|---|---|
| `pyproject.toml` | 7 | `version = "0.3.0b0"` | `version = "0.4.0"` |
| `Cargo.toml` | 3 | `version = "0.3.0-beta.0"` | `version = "0.4.0"` |
| `python/slappyengine/__init__.py` | 103 | `__version__ = "0.3.0b0"` | `__version__ = "0.4.0"` |

**Success gate.**
`SlapPyEngineTests/tests/test_version_consistency.py` green
(cross-checks the three files agree).

### Step 2 — Update CHANGELOG.md

Flip the draft header on line 8 of `CHANGELOG.md` from unreleased
draft form to the tag date:

* **Before:** `## [0.4.0] — YYYY-MM-DD (UNRELEASED)`
* **After:**  `## [0.4.0] — 2026-07-XX`

Replace `XX` with the actual tag-day date-of-month. Do not touch
the body content of the `[0.4.0]` section — PP7 already drafted it
per gate #14.

**Success gate.** `grep '(UNRELEASED)' CHANGELOG.md` returns
nothing under the `[0.4.0]` heading.

### Step 3 — Tag and push

Commit steps 1 + 2 as one commit (`v0.4.0 release`), then:

```
git tag -a v0.4.0 -m "SlapPyEngine v0.4.0"
git push origin master
git push origin v0.4.0
```

**Success gate.** `git ls-remote --tags origin` shows
`refs/tags/v0.4.0` pointing at the release commit.

---

## 3. Pre-tag verification

**All four checks must be GREEN before Step 1.** Run in the order
below on a clean checkout of `master`.

| # | Check | Command | Pass criterion |
|---|---|---|---|
| 3.1 | Engine tests all-green | `pytest SlapPyEngineTests/tests` | 0 failed, 0 error; skips must already be documented per SS3 skip audit. |
| 3.2 | Game-compat ≥80% of F1 (1178 combined) — **PASSING** (2026-07-08 +2 AAA3 reaffirm) | Re-run YY3/ZZ3/AAA3 harness against `H:/DaedalusSVN/Ochema Circuit/` + `H:/DaedalusSVN/Bullet Strata/` (**note**: repo dirs contain spaces — YY7 briefing path `OchemaCircuit/BulletStrata` was wrong; ZZ3 verified correct spaced paths) | Combined ≥ **942** passes (0.80 × 1178). **PASSING at 93.3% F1** (AAA3 reaffirm): AAA3 walk against HEAD `c758122` (ZZ2 backcompat) measured Ochema **1045/68/13** (93.0% of F1) + Bullet Strata **54/0/0** (**100.0% of F1 — FULLY RECOVERED**); combined **1099/1178 = 93.3%** (well above 80% YELLOW threshold, ~1.7 pp below 95% GREEN). YELLOW plateau sustained across 3 consecutive re-verify ticks: YY3 91.8% → ZZ3 92.4% → **AAA3 93.3%** (upward drift). Bullet Strata half of gate #12 is unambiguously CLOSED. Analysis: `docs/game_compat_2026_07_07.md` § 12 (YY3) + § 13 (ZZ3) + § 14 (**AAA3**). Pre-tag operators may proceed to Step 1 with gate #12 status YELLOW / SHIP-AT-YELLOW-NOW per ship-decision doc § 9 Option F, or wait one more tick for BB batch attempting GREEN threshold cross per § 10 Option B tail. |
| 3.3 | `cargo check --release` zero errors | `cargo check --release --workspace` | Exit 0, no `error:` lines. Warnings tolerated. |
| 3.4 | `maturin build --release` wheel ≤50MB | `maturin build --release` then `ls -lh target/wheels/*.whl` | Wheel size ≤ **50 MB** (PyPI upload budget). WW7 baseline is ~1.45 MB per gate #10 evidence. |

If **any** check fails, do not proceed. Route failures back to the
appropriate batch (compat regressions → VV/WW backcompat; Rust
errors → LL/JJ Rust batches; wheel bloat → wheel_size_audit).

---

## 4. Post-tag verification

Execute in order after Step 3's push confirms.

| # | Check | Command | Pass criterion |
|---|---|---|---|
| 4.1 | Publish wheel to PyPI | `maturin publish --release` | PyPI upload returns 200; wheel appears at `https://pypi.org/project/slappyengine/0.4.0/`. |
| 4.2 | PyPI mirror pull test | `pip install --no-cache-dir slappyengine==0.4.0` in a fresh venv | Install succeeds, `python -c "import slappyengine; print(slappyengine.__version__)"` prints `0.4.0`. Smoke-run one demo (`python -m slappyengine.demo.hello_studio`). |
| 4.3 | GitHub release notes | `gh release create v0.4.0 --notes-file <(sed -n '/^## \[0.4.0\]/,/^## \[/p' CHANGELOG.md \| head -n -1)` | GitHub release page renders with body pulled from the `[0.4.0]` section of `CHANGELOG.md`. |

---

## 5. Rollback plan

If **4.1** (PyPI publish) fails: fix locally, no rollback needed —
the tag lives locally only until push in 3.

If **4.2** (mirror pull test) or **4.3** (release notes) fail
after Step 3 already pushed the tag:

1. Delete the remote tag:
   ```
   git push origin :refs/tags/v0.4.0
   ```
2. Delete the local tag:
   ```
   git tag -d v0.4.0
   ```
3. Investigate and fix the root cause. Do **not** amend the
   release commit; add a follow-up commit.
4. Re-tag as `v0.4.0.post1` per PEP 440 post-release semantics:
   ```
   git tag -a v0.4.0.post1 -m "SlapPyEngine v0.4.0.post1 — <root cause>"
   git push origin master
   git push origin v0.4.0.post1
   ```
5. Add a `[0.4.0.post1]` entry to `CHANGELOG.md` documenting the
   post-release fix.

**Never** force-push over a live `v0.4.0` tag. Downstream mirrors
(PyPI, GitHub) treat tags as immutable; a re-tagged SHA at the
same version string will break `pip install` reproducibility.

---

## 6. Cross-links

* [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  — **VV7** ship-decision doc + **YY3** § 8 Option E addendum + **ZZ3**
  § 9 Option F formalisation (recommended: **Option F — SHIP-AT-YELLOW-NOW**;
  91.8% F1 recovery sustained across YY3 + ZZ3 re-verifies). This
  checklist presumes Option F is accepted and the residual v0.4.1
  followup pack (AA1/AA2/AA3 targeting ~14-18 residual sites) is
  scheduled post-tag.
* [`docs/version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
  — **PP6** version-string audit (three canonical bump sites +
  historical vs must-update docs list). Step 1 is a direct
  execution of PP6's audit.
* [`docs/sprint_rollup_2026_07_07_r7.md`](sprint_rollup_2026_07_07_r7.md)
  — **WW7** additional demo-smoke closures (batch-7 targets)
  per r7 rollup § next-tick. WW7's demo-smoke coverage feeds
  pre-tag verification 3.1.
* [`docs/api_stability_2026_07_07.md`](api_stability_2026_07_07.md)
  — **UU7** API backcompat harness (338 pinned symbols across 14
  load-bearing modules + 10 subclass-abuse patterns). UU7's
  snapshot guards against regression during pre-tag verification
  3.2 and post-tag 4.2.

---

## 7. User questions still open

Copied verbatim from VV7's ship-decision doc § 6. Tag-day cannot
proceed until each has an answer.

1. **Ship-with-known-issues acceptable?** Are Ochema Circuit and
   Bullet Strata owners (both user) OK with a v0.4.0 that ships
   with partial game-compat (Ochema ~42% pass, Bullet ~35% pass)
   and a v0.4.1 followup within 1-2 weeks?
   * If YES → Option A (tag now, accept 3.2 miss).
   * If NO → Option B or Option C.
2. **Ship delay acceptable?** If NO to Q1, do you want to delay
   v0.4.0 for the 2-3 sprints needed to fully recover game-compat
   via the VV / WW / XX backcompat batches?
   * If YES → Option B (tag after 3.2 flips GREEN).
   * If NO → Option C (retag as v0.3.1 patch — this checklist
     changes: rewrite `[0.4.0]` header as `[0.3.1]` and re-run 3.1).
3. **Gate #11 disposition — WIP unfreeze?** For the four
   uncommitted subpackage trees (`softbody/`, `fluid/`, `physics/`,
   `physics2/`) plus four untracked Rust source files
   (`src/raster.rs`, `src/pbf_solver.rs`, `src/softbody_solver.rs`,
   `src/fluid_shader.rs`): land them as-is under an
   `[experimental]` pip extra so early adopters can opt in, or
   keep them frozen and defer formally to v0.4.1?
   * Land as `[experimental]` → gate 11 flips to GREEN; add an
     `[experimental]` extras row to `pyproject.toml` before Step 1.
   * Keep frozen with docs deferral note → gate 11 flips to
     DEFERRED; add a `Deferred to v0.4.1` bullet under
     `[0.4.0]` § Known Issues in `CHANGELOG.md`.

---

*Tag-readiness checklist generated 2026-07-07 late-evening by YY7
background scrum agent (re-dispatch of XX7). Sources: VV7
ship-decision doc (`docs/v0_4_ship_decision_2026_07_07.md`), PP6
version-bump audit (`docs/version_bump_audit_2026_07_07.md`), WW7
demo-smoke plan (`docs/sprint_rollup_2026_07_07_r7.md` § next-tick),
UU7 API backcompat contract (`docs/api_stability_2026_07_07.md`),
live `CHANGELOG.md:8` header, `pyproject.toml:7` +
`Cargo.toml:3` + `python/slappyengine/__init__.py:103` version
cross-check. Docs-only — no version strings or Python source touched.*
