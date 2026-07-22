"""Tripwire tests for ``docs/rust_port_plan_dynamics.md``.

The doc is a decision-quality writeup for the proposed Rust port of
``pharos_engine.dynamics``. These tests guarantee its structural and
evidentiary integrity so future edits cannot silently strip the parts
the decision relies on (bench numbers, prior-port citations, the
seven required sections).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parent.parent.parent / "docs" / "rust_port_plan_dynamics.md"


def _read() -> str:
    if not DOC.exists():
        pytest.fail(f"missing rust port plan doc: {DOC}")
    return DOC.read_text(encoding="utf-8")


def test_doc_exists() -> None:
    """The plan file lives at ``docs/rust_port_plan_dynamics.md``."""
    assert DOC.is_file(), f"expected file at {DOC}, not found"
    body = DOC.read_text(encoding="utf-8")
    # Anything below ~5 KB cannot possibly contain the 7 required sections
    # plus a real Rust API sketch.
    assert len(body) > 5_000, (
        f"doc is suspiciously short ({len(body)} bytes); expected a "
        f"multi-thousand-byte plan"
    )


def test_doc_has_all_sections() -> None:
    """The doc must cover the seven mandated sections from the spec.

    The spec orders them as:
        1. Bench current Python solver
        2. Profile hot path (cProfile, top 10)
        3. Map hot functions to Rust port candidates
        4. Estimate speedup, with citations
        5. Define the Rust API surface (pyo3 signatures)
        6. Risk callouts
        7. Phased delivery plan
    """
    body = _read()
    expected_headings = [
        # Tolerant patterns: each entry is a regex matched case-insensitively
        # against the doc body. The patterns mirror the section titles in the
        # doc but allow for minor wording drift.
        ("section 1 — bench", r"^##\s*1\.\s*bench", "bench results"),
        ("section 2 — profile", r"^##\s*2\.\s*hot[- ]path profile", "cProfile section"),
        ("section 3 — classify", r"^##\s*3\.\s*hot[- ]function", "classification section"),
        ("section 4 — speedup", r"^##\s*4\.\s*speedup estimate", "speedup section"),
        ("section 5 — api", r"^##\s*5\.\s*rust api surface", "Rust API section"),
        ("section 6 — risks", r"^##\s*6\.\s*risk callouts", "risk callouts"),
        ("section 7 — phases", r"^##\s*7\.\s*phased delivery plan", "phased plan"),
    ]
    missing = []
    for label, pat, descr in expected_headings:
        if not re.search(pat, body, flags=re.IGNORECASE | re.MULTILINE):
            missing.append(f"{label} ({descr}, pattern={pat!r})")
    assert not missing, (
        "rust port plan is missing required sections:\n  - "
        + "\n  - ".join(missing)
    )


def test_doc_includes_bench_numbers() -> None:
    """At least three ``X.X ms`` style time literals must appear in prose.

    The plan stands or falls on having real measured numbers; an edit
    that strips them produces a non-decision-quality document.
    """
    body = _read()
    # Match any decimal number followed by optional whitespace then "ms"
    # (allow non-breaking space variants and bold markup).
    pat = re.compile(r"\d+(?:\.\d+)?\s*ms\b", flags=re.IGNORECASE)
    matches = pat.findall(body)
    assert len(matches) >= 3, (
        f"expected at least 3 'NN.NN ms' bench numbers; found "
        f"{len(matches)} in {DOC}: {matches!r}"
    )


def test_doc_references_existing_core_module() -> None:
    """The plan must cite the existing ``_core`` Rust extension and at
    least one already-ported function from prior engine work.

    Per ``project_rust_steps_1_4_2026_05`` / ``project_rust_migration_
    final_2026_05`` we have several landed kernels — softbody XPBD,
    PBF inner loop, IK solver (``pharos_engine._core.solve_ik``), etc.
    The doc must name at least one of them so the speedup estimate
    has provenance.
    """
    body = _read()
    assert "pharos_engine._core" in body, (
        "expected the doc to mention the existing 'pharos_engine._core' "
        "extension module (the Rust home of all current ports)"
    )
    # At least one already-ported kernel from memory must be named.
    # We accept any of the documented landings.
    candidates = [
        "softbody XPBD",
        "softbody_xpbd",
        "PBF",
        "pbf_step",
        "pbf inner",
        "solve_ik",
        "ik_solver",
        "FABRIK",
        "raster.rs",
    ]
    hits = [name for name in candidates if name.lower() in body.lower()]
    assert hits, (
        "expected the doc to name at least one already-ported kernel from "
        "the engine's _core module (e.g. softbody XPBD, PBF inner, "
        "solve_ik / FABRIK, raster.rs). Found none of: "
        f"{candidates!r}"
    )
