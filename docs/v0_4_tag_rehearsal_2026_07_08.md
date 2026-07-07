# v0.4 Tag Ceremony Rehearsal — 2026-07-08 (ZZ7)

Dry-run script for the `v0.4.0` tag ceremony. Every step below is
what the tag-day operator will execute **once the user answers
YES to VV7's Q1 (ship-with-known-issues acceptable) and Q2
(ship-delay acceptable, Option B)**. Until then, nothing here runs.

Written by **ZZ7** background scrum agent, 2026-07-08 batch.
**Docs-only.** No version strings, `pyproject.toml`, `Cargo.toml`,
`CHANGELOG.md`, `python/slappyengine/__init__.py`, or Python source
touched. This doc is a rehearsal — the operator copy-pastes the
commands below in order once the ship-decision gate clears.

Prerequisite reading, in order:

1. VV7 ship-decision doc —
   [`v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
   (recommends Option B; opens Q1 / Q2 / Q3).
2. YY7 tag-readiness green-light checklist —
   [`v0_4_tag_readiness_2026_07_07.md`](v0_4_tag_readiness_2026_07_07.md)
   (three-step atomic tag checklist; source-of-truth for gates).
3. PP6 version-bump audit —
   [`version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
   (three canonical bump sites + 11 doc audit rows + 5 fixture
   rows).
4. WW7 CHANGELOG expansion —
   `CHANGELOG.md` line 8 currently reads
   `## [0.4.0] — YYYY-MM-DD (UNRELEASED)`, waiting on date flip.

---

## 1. Assumptions

* Tag date is `2026-07-XX` where `XX` is the day of month the
  operator executes this script. Replace `XX` verbatim in Step 3.
* Working tree is clean on `master` (WIP dirs `softbody/`,
  `fluid/`, `physics/`, `physics2/` and untracked `src/*.rs`
  ignored per gate #11 — VV7's Q3 says land as `[experimental]`
  extra OR keep frozen; either path is compatible with the
  ceremony below since the WIP paths are not staged).
* Fresh venv exists for post-tag verification with
  `PYTHONPATH=python`.
* `maturin`, `cargo`, `git`, `gh`, `sed`, `grep`, `pytest`
  available on `PATH`. Windows operators run under Git Bash or
  WSL — the `sed -i` syntax is POSIX; PowerShell operators
  substitute `SetVersion.bat 0.4.0` for the three `sed`
  invocations in Step 1 (see § 3).

---

## 2. PRE-FLIGHT CHECKS

Rehearsal — run these three checks on a clean `master`. All three
must be GREEN before touching version strings. Expected outputs
below assume live commit around `c5b00e1` (YY3-verified 91.8% F1).

```
$ PYTHONPATH=python python -m pytest SlapPyEngineTests/tests/ -q --no-header --tb=line
(expect: N passed, no failures — SS3 skip audit + WW6 tripwires green)
```

```
$ PYTHONPATH=h:/Github/SlapPyEngine/python python -m pytest H:/DaedalusSVN/OchemaCircuit/tests -q --no-header --tb=line
(expect: >= 1067 passes — YY3 baseline was Ochema 1032 + Bullet 50 = 1082 combined at 91.8% F1;
1067 sets the ≥95% F1 threshold agreed for Option B ship-gate)
```

```
$ cargo check --release
(expect: zero errors; warnings tolerated per YY7 § 3.3)
```

```
$ maturin build --release && ls -lh target/wheels/*.whl
(expect: wheel size ≤ 50 MB; WW7 baseline ~1.45 MB per gate #10)
```

If any pre-flight fails → **STOP.** Route the failure through the
appropriate batch (VV/WW backcompat for game-compat regressions;
LL/JJ Rust batches for Rust errors; wheel_size_audit for bloat).

---

## 3. STEP 1 — Version bump

Three canonical sites per PP6 audit. Rehearsal — do not run.

```
$ sed -i 's/0.3.0b0/0.4.0/' pyproject.toml
$ grep 'version =' pyproject.toml
version = "0.4.0"
```

```
$ sed -i 's/0.3.0-beta.0/0.4.0/' Cargo.toml
$ grep '^version' Cargo.toml
version = "0.4.0"
```

```
$ sed -i 's/__version__ = "0.3.0b0"/__version__ = "0.4.0"/' python/slappyengine/__init__.py
$ grep '__version__' python/slappyengine/__init__.py
__version__ = "0.4.0"
```

**Windows-native alternative** (single call, wraps all three):

```
> SetVersion.bat 0.4.0
```

**Success gate.** Run the version-consistency tripwire:

```
$ PYTHONPATH=python python -m pytest SlapPyEngineTests/tests/test_version_consistency.py -q --no-header
(expect: 1 passed)
```

**Do NOT stage yet.** Step 2 lands next in the same commit.

---

## 4. STEP 2 — CHANGELOG date flip

Flip line 8 header from `UNRELEASED` draft form to the tag date.
Replace `07` and `XX` with the actual month/day of tag execution.

```
$ sed -i 's/## \[0.4.0\] — YYYY-MM-DD (UNRELEASED)/## [0.4.0] — 2026-07-XX/' CHANGELOG.md
$ grep -n '^## \[0.4.0\]' CHANGELOG.md
8:## [0.4.0] — 2026-07-XX
```

**Success gate.** No `(UNRELEASED)` marker remains under the
`[0.4.0]` heading:

```
$ grep -c '(UNRELEASED)' CHANGELOG.md
0
```

The body content of the `[0.4.0]` section is already drafted by
WW7 — do not touch it.

---

## 5. STEP 3 — Commit + tag

Single atomic commit for Step 1 + Step 2, then annotated tag,
then push both branch and tag.

```
$ git add pyproject.toml Cargo.toml python/slappyengine/__init__.py CHANGELOG.md
$ git status --short
M CHANGELOG.md
M Cargo.toml
M pyproject.toml
M python/slappyengine/__init__.py
$ git commit -m "Release v0.4.0"
$ git tag -a v0.4.0 -m "SlapPyEngine v0.4.0"
$ git push origin master
$ git push origin v0.4.0
```

**Success gate.** Remote lists the tag:

```
$ git ls-remote --tags origin | grep v0.4.0
<sha>	refs/tags/v0.4.0
```

---

## 6. STEP 4 — Build wheel + publish

Build the release wheel and publish to PyPI.

```
$ maturin build --release
$ ls -lh target/wheels/
(expect: slappyengine-0.4.0-<py>-<abi>-<plat>.whl, ≤ 50 MB)
$ maturin publish --release
(expect: PyPI upload returns 200; wheel appears at
 https://pypi.org/project/slappyengine/0.4.0/)
```

`maturin publish` prompts for PyPI credentials (or reads
`~/.pypirc`); the operator supplies these interactively.

---

## 7. STEP 5 — Post-release verification

Fresh venv smoke, one demo run, GitHub release notes.

```
$ python -m venv /tmp/slap-verify && source /tmp/slap-verify/bin/activate
$ pip install --upgrade slappy-engine==0.4.0
$ python -c "import slappyengine; print(slappyengine.__version__)"
0.4.0
$ python -m slappyengine.demo.hello_studio
(expect: window opens, demo runs to completion)
```

Then create the GitHub release from the CHANGELOG body:

```
$ gh release create v0.4.0 --title "SlapPyEngine v0.4.0" \
    --notes-file <(sed -n '/^## \[0.4.0\]/,/^## \[/p' CHANGELOG.md | head -n -1)
(expect: GitHub release page renders with body from CHANGELOG [0.4.0] section)
```

---

## 8. ROLLBACK PLAN

Four rollback branches keyed by how far the ceremony has
progressed when the failure hits. Never force-push over a
published `v0.4.0` tag — PyPI and GitHub treat tags as immutable.

### 8.1 Failure BEFORE Step 3 (commit not yet created)

Discard version bump + CHANGELOG edit:

```
$ git checkout -- pyproject.toml Cargo.toml python/slappyengine/__init__.py CHANGELOG.md
$ git status --short
(expect: empty)
```

### 8.2 Failure AFTER Step 3 commit, BEFORE push

Rewind the local commit and delete the local tag:

```
$ git reset --hard HEAD~1
$ git tag -d v0.4.0
$ git status --short
(expect: empty)
$ git tag -l v0.4.0
(expect: empty)
```

### 8.3 Failure AFTER push, BEFORE PyPI publish

The tag is on the remote but no wheel is live yet. Delete the
remote tag, then revert the local commit and force-push branch:

```
$ git push origin :refs/tags/v0.4.0
$ git tag -d v0.4.0
$ git revert HEAD --no-edit
$ git push origin master
```

Alternatively — if the commit itself is fine and only the tag was
premature — leave the commit, delete the tag, fix, re-tag:

```
$ git push origin :refs/tags/v0.4.0
$ git tag -d v0.4.0
(fix root cause, add follow-up commit)
$ git tag -a v0.4.0 -m "SlapPyEngine v0.4.0"
$ git push origin master
$ git push origin v0.4.0
```

### 8.4 Failure AFTER PyPI publish (post-release)

Do **not** rewrite `v0.4.0`. Follow YY7 § 5 rollback and PEP 440
post-release semantics:

```
$ git push origin :refs/tags/v0.4.0     # only if not yet consumed downstream
$ git tag -d v0.4.0
(fix root cause, add follow-up commit)
$ git tag -a v0.4.0.post1 -m "SlapPyEngine v0.4.0.post1 — <root cause>"
$ git push origin master
$ git push origin v0.4.0.post1
```

Then add a `[0.4.0.post1]` entry to `CHANGELOG.md` documenting
the post-release fix. Never re-use the `v0.4.0` tag name at a new
SHA once PyPI has served the wheel — `pip install
slappy-engine==0.4.0` reproducibility depends on immutability.

---

## 9. Cross-links

* [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  — **VV7** ship-decision doc (four release paths + Q1 / Q2 / Q3
  open). This rehearsal presumes YES/YES answers to Q1 + Q2.
* [`docs/v0_4_tag_readiness_2026_07_07.md`](v0_4_tag_readiness_2026_07_07.md)
  — **YY7** three-step tag checklist. This rehearsal is the
  operator-script sibling.
* [`docs/version_bump_audit_2026_07_07.md`](version_bump_audit_2026_07_07.md)
  — **PP6** version-bump audit (3 canonical sites + 11 doc-audit
  rows + 5 fixture rows). Steps 1 + 3 execute PP6's audit.
* [`CHANGELOG.md`](../CHANGELOG.md) line 8 — **WW7** UNRELEASED
  draft header. Step 2 flips it.
* [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md)
  — **YY3** F1 recovery arc (37.6% → 91.8% across 6 backcompat
  slots). Feeds pre-flight § 2 second check.

---

## 10. User questions still blocking

Copied verbatim from VV7 § 6 (also mirrored in YY7 § 7). Tag-day
cannot proceed until each has an answer.

1. **Ship-with-known-issues acceptable?** — Ochema Circuit +
   Bullet Strata at 91.8% F1 (YY3 verified) rather than the 95%
   originally proposed. YES → proceed with Option A / B; NO →
   two more backcompat slots to close remaining 7-site
   `Observable(name=...)` kwarg + 7-site DeformableLayerComponent
   surface residuals.
2. **Ship delay acceptable?** — If Q1 = NO, do you accept the
   1-2 sprint delay for Option B? YES → this rehearsal runs after
   the closer sprints; NO → Option C (retag as v0.3.1 patch;
   rewrite Steps 1–2 with `0.3.1` and re-run pre-flight § 2).
3. **Gate #11 disposition — WIP unfreeze?** — For the four
   uncommitted subpackage trees (`softbody/`, `fluid/`,
   `physics/`, `physics2/`) plus four untracked Rust source files
   (`src/raster.rs`, `src/pbf_solver.rs`, `src/softbody_solver.rs`,
   `src/fluid_shader.rs`): land as `[experimental]` pip extra or
   keep frozen with docs deferral note? Either answer is
   compatible with this rehearsal — WIP paths are not staged in
   Step 3's `git add` list.

---

*Tag-ceremony rehearsal generated 2026-07-08 by ZZ7 background
scrum agent. Sources: YY7 tag-readiness checklist
(`docs/v0_4_tag_readiness_2026_07_07.md`), VV7 ship-decision
doc (`docs/v0_4_ship_decision_2026_07_07.md`), PP6 version-bump
audit (`docs/version_bump_audit_2026_07_07.md`), WW7 CHANGELOG
draft (`CHANGELOG.md:8`), YY3 F1 recovery arc
(`docs/game_compat_2026_07_07.md` § 12), live `pyproject.toml:7`
+ `Cargo.toml:3` + `python/slappyengine/__init__.py:103` version
cross-check. Docs-only — no version strings or Python source
touched.*
