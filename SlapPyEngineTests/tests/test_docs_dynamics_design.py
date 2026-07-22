"""Documentation tripwire for docs/dynamics_design.md.

These tests prevent the canonical dynamics reference from rotting silently
when new joint kinds or composite primitives are added to
``pharos_engine.dynamics``.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "dynamics_design.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_exists():
    """The dynamics design reference is present at the canonical path."""
    assert DOC_PATH.is_file(), f"Missing {DOC_PATH}"
    assert DOC_PATH.stat().st_size > 0


def test_doc_mentions_all_joint_kinds():
    """Every JointSpec kind exported by pharos_engine.dynamics is documented."""
    from pharos_engine.dynamics import KIND_PARAM_KEYS

    text = _read_doc()
    missing = [kind for kind in KIND_PARAM_KEYS if kind not in text]
    assert not missing, (
        f"Joint kinds missing from docs/dynamics_design.md: {missing}"
    )


def test_doc_mentions_all_primitives():
    """All higher-level composite primitives and builders are referenced."""
    text = _read_doc()
    required = [
        "RopeSpec",
        "RagdollSpec",
        "IKChainSpec",
        "MotorSpec",
        "SpringSpec",
    ]
    missing = [name for name in required if name not in text]
    assert not missing, (
        f"Composite primitives missing from docs/dynamics_design.md: {missing}"
    )


def test_doc_has_solver_internals_section():
    """The Solver internals section header is present."""
    text = _read_doc()
    assert "## Solver internals" in text, (
        "docs/dynamics_design.md must include a '## Solver internals' section"
    )


def test_doc_has_xpbd_foundation_section():
    """The XPBD foundation explanation is present (structural anchor)."""
    text = _read_doc()
    assert "## Foundation: XPBD" in text


def test_doc_has_compatibility_notes_section():
    """The legacy-to-unified compatibility bridge is documented."""
    text = _read_doc()
    assert "## Compatibility notes" in text
    # Sanity: the bridge must call out the three legacy authoring types.
    for name in ("BodyMeta", "VehicleSpec", "WheelSpec"):
        assert name in text, (
            f"docs/dynamics_design.md compatibility section must mention {name}"
        )


def test_doc_references_macklin_xpbd_paper():
    """Citation to the substrate paper is present (Macklin 2016 XPBD)."""
    text = _read_doc()
    assert "Macklin" in text and "XPBD" in text


def test_doc_keys_match_module_schema():
    """Every kind-specific params key documented in KIND_PARAM_KEYS appears in the doc."""
    from pharos_engine.dynamics import KIND_PARAM_KEYS

    text = _read_doc()
    interesting_keys: set[str] = set()
    for keys in KIND_PARAM_KEYS.values():
        interesting_keys.update(keys)
    # Filter trivial single-letter keys (none today, but defensive).
    interesting_keys = {k for k in interesting_keys if len(k) >= 3}
    missing = [k for k in sorted(interesting_keys) if k not in text]
    assert not missing, (
        f"Param keys missing from docs/dynamics_design.md: {missing}"
    )
