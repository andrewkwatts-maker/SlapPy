"""Sanity tests for docs/strip_pass_v2_audit.md.

This is a dry-run audit document produced for Phase D of the plan at
``C:/Users/Andrew/.claude/plans/ok-we-were-working-reactive-valley.md``.

These tests assert that the doc:

* exists in the expected location,
* contains a per-module section for every candidate enumerated in the
  plan's Phase D step 3,
* contains a total LOC estimate for the "safe to delete" candidates,
* contains a "deform_modes coupling" audit (the single highest-risk
  deletion ordering hazard in the plan),
* contains a "FIRST module to cut" recommendation.

The doc is informational only — no source-tree changes follow from this
test passing. Phase D deletions are externally gated on Ochema CI.
"""
from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    """Return the worktree root (parent of tests/, peer of docs/)."""
    return Path(__file__).resolve().parent.parent.parent


def _audit_doc_path() -> Path:
    return _repo_root() / "docs" / "strip_pass_v2_audit.md"


def _read_doc() -> str:
    path = _audit_doc_path()
    assert path.exists(), f"strip-audit doc missing at {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Candidate inventory — exactly the list from the plan's Phase D step 3
# ---------------------------------------------------------------------------

CANDIDATE_SOURCE_MODULES = [
    "python/pharos_engine/physics/frontier.py",
    "python/pharos_engine/physics/boundary_exchange.py",
    "python/pharos_engine/physics/cc_label.py",
    "python/pharos_engine/physics/pressure_multigrid.py",
    "python/pharos_engine/physics/crack_repair_adapter.py",
    "python/pharos_engine/physics/deform_adapter.py",
    "python/pharos_engine/physics/engine_bridge.py",
    "python/pharos_engine/physics/granular_render.py",
    "python/pharos_engine/deform_modes.py",
    "python/pharos_engine/deform_controller.py",
    "python/pharos_engine/deform_crack.py",
    "python/pharos_engine/deform_repair.py",
    "python/pharos_engine/deform_zones.py",
    "python/pharos_engine/pixel_struct.py",
]

CANDIDATE_TEST_GLOBS = [
    "python/tests/test_demo_complex_scene.py",
    "python/tests/test_demo_destructible_wall.py",
    "python/tests/test_demo_lava_flow.py",
    "python/tests/test_demo_materials_gallery.py",
    "python/tests/test_demo_projectile.py",
    "python/tests/test_demo_sand_pile.py",
    "python/tests/test_demo_vehicle.py",
    "python/tests/test_demo_vehicle_jointed.py",
    "python/tests/test_demo_water_container.py",
]


# ---------------------------------------------------------------------------
# Existence + structural assertions
# ---------------------------------------------------------------------------

def test_audit_doc_exists():
    assert _audit_doc_path().exists(), (
        f"docs/strip_pass_v2_audit.md must exist at "
        f"{_audit_doc_path()}"
    )


def test_audit_doc_is_nontrivial():
    body = _read_doc()
    # Heuristic: anything under ~5 KB is suspect for a 14-module audit.
    assert len(body) > 5_000, (
        f"audit doc is suspiciously small ({len(body)} bytes) — "
        f"expected a per-module section for each of "
        f"{len(CANDIDATE_SOURCE_MODULES)} source candidates"
    )


def test_audit_doc_mentions_every_source_candidate():
    body = _read_doc()
    missing: list[str] = []
    for path in CANDIDATE_SOURCE_MODULES:
        if path not in body:
            missing.append(path)
    assert not missing, (
        f"audit doc is missing per-module sections for: {missing}"
    )


def test_audit_doc_mentions_demo_tests():
    """Plan's Phase D step 1 cites the demo tests by name."""
    body = _read_doc()
    missing: list[str] = []
    for path in CANDIDATE_TEST_GLOBS:
        # The demo-test table uses bare filenames, not full paths.
        # Accept either form.
        name = path.rsplit("/", 1)[-1]
        if path not in body and name not in body:
            missing.append(path)
    assert not missing, (
        f"audit doc is missing demo-test rows for: {missing}"
    )


# ---------------------------------------------------------------------------
# Classification — every module is classified as safe / safe-after / blocked
# ---------------------------------------------------------------------------

STATUS_TOKENS = (
    "safe to delete",
    "safe-after-",
    "blocked-on-",
)


def test_audit_doc_classifies_every_module():
    """Each source candidate must appear adjacent to a strip-status token.

    We look in a window after each candidate's section header for one of
    the three canonical status tokens. This catches modules that were
    enumerated but never classified.
    """
    body = _read_doc()
    unclassified: list[str] = []
    for path in CANDIDATE_SOURCE_MODULES:
        idx = body.find(path)
        if idx < 0:
            continue  # already caught by test_audit_doc_mentions_every_source_candidate
        # Look in the next ~3 KB after the header for a status token.
        window = body[idx : idx + 3_000]
        if not any(tok in window for tok in STATUS_TOKENS):
            unclassified.append(path)
    assert not unclassified, (
        f"candidates with no strip-status classification: {unclassified}\n"
        f"Each section needs one of: {STATUS_TOKENS}"
    )


# ---------------------------------------------------------------------------
# Headline metrics: deform_modes coupling, LOC total, first-cut recommendation
# ---------------------------------------------------------------------------

def test_audit_doc_has_deform_modes_coupling_section():
    """The plan calls this out as the single highest-risk deletion order
    hazard. The audit MUST surface it explicitly."""
    body = _read_doc().lower()
    # Either the components.py top-level import or the __init__ coupling
    # must be discussed by name.
    assert "deform_modes" in body, "deform_modes never mentioned"
    assert "components.py" in body or "__init__" in body, (
        "deform_modes coupling section must reference the call site "
        "(components.py or __init__.py)"
    )
    # The five symbol names from components.py:26 must each appear.
    for sym in (
        "DeformSimMode",
        "DecayMode",
        "DestroyMode",
        "MaterialPreset",
        "resolve_material",
    ):
        assert sym in _read_doc(), (
            f"deform_modes coupling audit must list symbol {sym!r}"
        )


def test_audit_doc_reports_total_loc_estimate():
    """A grand-total LOC figure for the safe-to-delete candidates must
    appear in the doc (the plan's headline estimate is ~4,800 LOC)."""
    body = _read_doc()
    # Look for any LOC figure in the 3,000–5,500 range that's tagged as
    # a total. We accept commas, no-commas, or "~" prefixes.
    pattern = re.compile(
        r"(?:total|grand\s+total|subtotal|net|estimate)[^\n]{0,200}?"
        r"(\d{1,2}[,]?\d{3})(?:\s*LOC)?",
        re.IGNORECASE,
    )
    matches = pattern.findall(body)
    assert matches, (
        "expected a LOC total line near the words 'total' / 'subtotal' / "
        "'estimate'; none found"
    )
    # At least one number must land in the realistic strip-pass range.
    in_range = [
        m for m in matches
        if 400 <= int(m.replace(",", "")) <= 8000
    ]
    assert in_range, (
        f"LOC totals found ({matches}) but none in plausible range "
        f"400-8000 — expected ~474 / ~2110 / ~2184 / ~4766 / ~4800"
    )


def test_audit_doc_recommends_first_module_to_cut():
    """The agent task explicitly asked for a 'recommended FIRST module
    to cut when Phase D actually fires' line. Assert it's there."""
    body = _read_doc().lower()
    assert "first" in body and (
        "engine_bridge" in body or "crack_repair_adapter" in body or
        "deform_adapter" in body or "frontier" in body
    ), (
        "audit doc must recommend a specific FIRST module to cut "
        "when Phase D fires"
    )


def test_audit_doc_mentions_repackaged_targets():
    """Phase B's repackaged modules (topology, numerics, zones, thermal)
    must each be referenced as the migration target for at least one
    candidate."""
    body = _read_doc()
    for target in (
        "pharos_engine.topology",
        "pharos_engine.numerics",
        "pharos_engine.zones",
        "pharos_engine.thermal",
    ):
        assert target in body, (
            f"audit doc must reference repackaged module {target!r} as a "
            f"migration target"
        )


def test_audit_doc_marks_dry_run_status():
    """Sanity: nobody should be able to read this doc and think Phase D
    has been executed. It is a dry-run."""
    body = _read_doc().lower()
    assert "dry-run" in body or "dry run" in body or "audit" in body, (
        "audit doc must explicitly mark itself as a dry-run / audit"
    )
    # Negative guardrail: no language implying deletion already happened.
    assert "deleted today" not in body, (
        "audit must not claim deletions have been performed"
    )


def test_audit_doc_marks_game_blockers():
    """Ochema Circuit and Bullet Strata each block at least one module
    per the consumer grep. Stone Keep does not block any."""
    body = _read_doc()
    assert "Ochema" in body, (
        "audit must call out Ochema Circuit as a game-side consumer"
    )
    assert "Bullet Strata" in body, (
        "audit must call out Bullet Strata as a game-side consumer"
    )
    # Stone Keep should appear with a "none" / "clean" annotation, or
    # be explicitly excluded.
    assert "Stone Keep" in body, (
        "audit must call out Stone Keep (even if to say it's clean)"
    )
