"""Tripwire: ``scripts/gen_subpackage_api_docs.py`` must not clobber
hand-authored docs under ``docs/api/``.

A doc opts out of regeneration by carrying the
``<!-- handauthored: do not regenerate -->`` marker in its first
~10 lines (see ``HANDAUTHORED_MARKER`` in the generator). When the
marker is present, ``write_all()`` must leave the file's bytes
untouched.

We protect this contract with a regression test rather than a code
review note because the failure mode is silent — the generator simply
overwrites the doc, and the loss is only noticed once someone diffs
their hand-authored prose against the auto-gen stub.

The test:

1. Snapshots the SHA-256 of every ``docs/api/*.md`` file that carries
   the marker.
2. Runs ``write_all()``.
3. Re-hashes the marked files and asserts byte equality.

If this test fails, the generator has regressed the opt-out path —
do NOT regenerate the marked files; fix the generator instead.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = REPO_ROOT / "python"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

# Load the generator the same way ``test_docs_api_ref.py`` does so we
# don't depend on ``scripts/`` being importable as a package.
_GEN_PATH = REPO_ROOT / "scripts" / "gen_subpackage_api_docs.py"
_spec = importlib.util.spec_from_file_location("gen_subpackage_api_docs", _GEN_PATH)
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
sys.modules["gen_subpackage_api_docs"] = gen
_spec.loader.exec_module(gen)


DOC_DIR = REPO_ROOT / "docs" / "api"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _handauthored_docs() -> list[Path]:
    """Return every ``docs/api/*.md`` that carries the opt-out marker."""
    out: list[Path] = []
    for path in sorted(DOC_DIR.glob("*.md")):
        if gen._is_handauthored(path):
            out.append(path)
    return out


def test_handauthored_marker_constant_present() -> None:
    """The generator must expose the marker as a module-level constant."""
    assert hasattr(gen, "HANDAUTHORED_MARKER")
    assert isinstance(gen.HANDAUTHORED_MARKER, str)
    assert "handauthored" in gen.HANDAUTHORED_MARKER


def test_at_least_one_handauthored_doc_exists() -> None:
    """Sanity-check that the opt-out is in active use.

    Without this assertion the regression test below could silently
    pass on an empty set if every marker was deleted by mistake.
    """
    marked = _handauthored_docs()
    assert marked, (
        "Expected at least one docs/api/*.md to carry the "
        f"{gen.HANDAUTHORED_MARKER!r} marker — none found. Did the "
        "marker get stripped during a regeneration?"
    )


def test_write_all_preserves_handauthored_docs(tmp_path: Path) -> None:
    """Running the generator must not modify any marker-carrying doc."""
    marked = _handauthored_docs()
    if not marked:
        pytest.skip("no hand-authored docs to protect")

    before = {p: _sha256(p) for p in marked}
    gen.write_all()
    after = {p: _sha256(p) for p in marked}

    modified = [
        str(p.relative_to(REPO_ROOT))
        for p in marked
        if before[p] != after[p]
    ]
    assert not modified, (
        f"{len(modified)} hand-authored doc(s) were modified by "
        "write_all(); the marker opt-out is broken:\n  - "
        + "\n  - ".join(modified)
    )


def test_is_handauthored_detects_marker_in_head(tmp_path: Path) -> None:
    """``_is_handauthored`` finds the marker only in the head of the file."""
    head_doc = tmp_path / "head.md"
    head_doc.write_text(
        gen.HANDAUTHORED_MARKER + "\n# heading\nbody\n",
        encoding="utf-8",
    )
    assert gen._is_handauthored(head_doc) is True

    plain_doc = tmp_path / "plain.md"
    plain_doc.write_text("# heading\nbody\n", encoding="utf-8")
    assert gen._is_handauthored(plain_doc) is False

    # Marker buried past the head window must NOT count.
    buried = tmp_path / "buried.md"
    buried.write_text(
        "\n".join(["x"] * (gen.HANDAUTHORED_HEAD_LINES + 5))
        + "\n"
        + gen.HANDAUTHORED_MARKER
        + "\n",
        encoding="utf-8",
    )
    assert gen._is_handauthored(buried) is False


def test_missing_file_is_not_handauthored(tmp_path: Path) -> None:
    """``_is_handauthored`` must return False for a non-existent path."""
    assert gen._is_handauthored(tmp_path / "does_not_exist.md") is False
