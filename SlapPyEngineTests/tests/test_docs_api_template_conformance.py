"""Tripwire: every hand-authored ``docs/api/*.md`` follows the meta-template.

The canonical structure is documented in ``docs/api/_template.md``; this
test guards the three load-bearing pieces every hand-authored doc must
carry so the per-subpackage references stay structurally consistent
across sprints. New hand-authored API docs should be written from
``_template.md``; existing docs were swept in the same sprint that
landed the template.

Specifically, every file under ``docs/api/`` that carries the
``<!-- handauthored: do not regenerate -->`` marker must:

1. Start with the marker on line 1 (exact bytes).
2. Have an H1 line of the form ``# slappyengine.<X> — API Reference``
   where ``<X>`` is a dotted subpackage path (``post_process``,
   ``ui.editor``, …).
3. Have at least one of the canonical landing-section H2s:
   ``## Overview``, ``## Public surface``, or ``## Usage``.

The meta-template itself (``_template.md``) is exempt — it is a
documentation artefact, not a per-subpackage reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = REPO_ROOT / "docs" / "api"

HANDAUTHORED_MARKER = "<!-- handauthored: do not regenerate -->"
H1_RE = re.compile(r"^#\s+slappyengine\.[A-Za-z0-9_.]+\s+—\s+API Reference\s*$")
LANDING_H2S = ("## Overview", "## Public surface", "## Usage")

# The meta-template is not a per-subpackage reference; skip it.
EXCLUDED_STEMS = frozenset({"_template"})


def _handauthored_docs() -> list[Path]:
    """Return every ``docs/api/*.md`` that carries the opt-out marker."""
    out: list[Path] = []
    for path in sorted(DOC_DIR.glob("*.md")):
        if path.stem in EXCLUDED_STEMS:
            continue
        # Mirror the generator's head-window scan: only the first ~10
        # lines count as the marker zone.
        try:
            head = "\n".join(
                path.read_text(encoding="utf-8").splitlines()[:10]
            )
        except OSError:
            continue
        if HANDAUTHORED_MARKER in head:
            out.append(path)
    return out


def test_at_least_one_handauthored_doc_exists() -> None:
    """Sanity-check that the test set is non-empty.

    Without this assertion the per-doc parametrisations below could
    silently pass on an empty set if every marker was deleted.
    """
    marked = _handauthored_docs()
    assert marked, (
        "Expected at least one docs/api/*.md to carry the "
        f"{HANDAUTHORED_MARKER!r} marker — none found."
    )


@pytest.mark.parametrize(
    "doc_path",
    _handauthored_docs(),
    ids=lambda p: p.name,
)
def test_handauthored_doc_starts_with_marker(doc_path: Path) -> None:
    """The marker must be the literal first line of the file."""
    text = doc_path.read_text(encoding="utf-8")
    first_line = text.splitlines()[0] if text else ""
    assert first_line == HANDAUTHORED_MARKER, (
        f"{doc_path.relative_to(REPO_ROOT)} must start with "
        f"{HANDAUTHORED_MARKER!r} on line 1; saw {first_line!r}."
    )


@pytest.mark.parametrize(
    "doc_path",
    _handauthored_docs(),
    ids=lambda p: p.name,
)
def test_handauthored_doc_has_canonical_h1(doc_path: Path) -> None:
    """The H1 must match ``# slappyengine.<X> — API Reference``."""
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    h1_lines = [ln for ln in lines if ln.startswith("# ")]
    assert h1_lines, (
        f"{doc_path.relative_to(REPO_ROOT)} has no H1 line."
    )
    first_h1 = h1_lines[0]
    assert H1_RE.match(first_h1), (
        f"{doc_path.relative_to(REPO_ROOT)} H1 must match "
        f"'# slappyengine.<X> — API Reference'; saw {first_h1!r}."
    )


@pytest.mark.parametrize(
    "doc_path",
    _handauthored_docs(),
    ids=lambda p: p.name,
)
def test_handauthored_doc_has_landing_section(doc_path: Path) -> None:
    """Each doc must have at least one of the canonical landing H2s."""
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Match the H2 prefix so a parenthetical qualifier such as
    # ``## Public surface (`__all__`)`` still counts as the canonical
    # landing section.
    found = [
        h2 for h2 in LANDING_H2S
        if any(ln == h2 or ln.startswith(h2 + " ") for ln in lines)
    ]
    assert found, (
        f"{doc_path.relative_to(REPO_ROOT)} must have at least one of "
        f"{LANDING_H2S}; none found. See docs/api/_template.md."
    )
