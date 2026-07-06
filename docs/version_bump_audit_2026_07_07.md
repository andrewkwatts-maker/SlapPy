# Version Bump Audit — v0.3.0b0 → v0.4.0 (2026-07-07)

Read-only audit produced by **PP6** during the CHANGELOG draft sprint.
The version bump itself is **deferred** — this doc enumerates every file
that carries the version string so the tag sprint can flip them in one
atomic commit.

> **Do not run any of the actions in this doc yet.** OO7's release
> readiness audit rated status **YELLOW**; the bump is gated on OO
> stabilisation + PP tag-prep sprints.

## Scope

Bump-required files (paths relative to repo root):

| File | Current | Target | Notes |
|---|---|---|---|
| `pyproject.toml` | `version = "0.3.0b0"` | `version = "0.4.0"` | Line 7; canonical PyPI version. |
| `Cargo.toml` | `version = "0.3.0-beta.0"` | `version = "0.4.0"` | Line 3; Rust workspace root version (SemVer form). |
| `python/slappyengine/__init__.py` | `__version__ = "0.3.0b0"` | `__version__ = "0.4.0"` | Line 103; canonical Python `__version__`. |

Docs referencing the old string (either as prose about "v0.3" or as
hard-coded `0.3.0` / `0.3.0b0` strings). Some are historical / correct
to leave (e.g. `wheel_size_audit_2026_06_02.md`, `master_review_2026_06_07.md`,
`v0_4_release_readiness_2026_07_06.md`), so the tag sprint should
audit each individually:

| File | Action for tag sprint |
|---|---|
| `README.md` | Update "What's new in v0.3.0" section + install snippet. |
| `docs/quickstart.md` | Update the version string in the intro. |
| `docs/getting_started.md` | Update banner + any `pip install slappy-engine==0.3.0b0` snippets. |
| `docs/CONTRIBUTING.md` | Verify the "current version" mention. |
| `docs/roadmap.md` | Roll "Near-term — v0.3.x" into "Mid-term — v0.4"; add new v0.4.x + v0.5 near-term. |
| `docs/demo_gallery.md` | Version banner. |
| `docs/engine_surface_v030.md` | Regenerate via `scripts/gen_engine_surface_doc.py` against 0.4 surface (or leave and add `engine_surface_v040.md` if we want to keep the historical snapshot). |
| `docs/master_review_2026_06_07.md` | Leave historical; adds a dated banner "written pre-v0.4 tag" if needed. |
| `docs/v0_4_release_readiness_2026_07_06.md` | Leave historical; the audit conclusion should be re-run pre-tag and rated GREEN. |
| `docs/wheel_size_audit_2026_06_02.md` | Leave historical. |
| `python/slappyengine/projects/format.py` | `version: "0.3.0b0"` at L9 — used by the `Project` YAML schema default; bump alongside the code. |
| `python/slappyengine/projects/project.py` | Verify the reference is a `slappyengine.__version__` runtime lookup, not a hard-coded string. |
| `SlapPyEngineTests/tests/test_projects.py` | Fixtures reference `0.3.0`; update alongside the bump. |
| `SlapPyEngineTests/tests/test_docs_v030.py` | Rename to `test_docs_v040.py` (or generalise) — currently pins v0.3 tripwires. |
| `SlapPyEngineExamples/examples/hello_export_cli_trace.yaml` | Regenerate against bumped `__version__`. |
| `SetVersion.bat` | Update `REM  e.g.  SetVersion.bat 0.3.0` → `0.4.0`. |
| `CHANGELOG.md` | Flip the `[0.4.0] — YYYY-MM-DD (UNRELEASED)` header to the tag date. |

## Auto-generated / regenerable

The following are produced by `scripts/`:

- `docs/engine_surface_v030.md` — regenerate via
  `scripts/gen_engine_surface_doc.py` (may be renamed to
  `engine_surface_v040.md`, keeping the v0.3 file as a historical
  snapshot for cross-version diffs).
- `docs/api/*.md` (auto-gen half) — regenerate via
  `scripts/gen_subpackage_api_docs.py` after bumping `__version__`.

## Version-consistency tripwire

`SlapPyEngineTests/tests/test_version_consistency.py` cross-checks
`pyproject.toml` ⇄ `Cargo.toml` ⇄ `python/slappyengine/__init__.py`.
The bump is one atomic commit; the tripwire will surface any missed
file.

## SetVersion helper

`SetVersion.bat` at the repo root already automates the three canonical
sites. Run:

```
SetVersion.bat 0.4.0
```

then hand-audit the doc list above.

## Suggested tag-sprint commit sequence

1. `SetVersion.bat 0.4.0` — pyproject + Cargo + `__init__.py`.
2. Docs pass — README, quickstart, getting_started, roadmap,
   demo_gallery, CONTRIBUTING (per the table above).
3. CHANGELOG date flip — `[0.4.0] — YYYY-MM-DD (UNRELEASED)` →
   `[0.4.0] — <tag date>`.
4. Regenerate auto-gen docs (`engine_surface`, `docs/api/*`).
5. Update fixtures (`test_projects.py`, `hello_export_cli_trace.yaml`,
   rename `test_docs_v030.py` → `test_docs_v040.py`).
6. Bump `format.py` project schema default.
7. `SlapPyEngineTests/tests/test_version_consistency.py` must go green.
8. `git tag v0.4.0`.
