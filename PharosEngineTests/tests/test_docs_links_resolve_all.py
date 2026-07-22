"""Walk every Markdown file under ``docs/`` and assert every link resolves.

The check is intentionally simple-minded:

* Parse every ``[label](target)`` link out of every ``docs/**/*.md`` file
  (also matches image links ``![alt](target)``).
* Skip ``http://`` / ``https://`` / ``mailto:`` targets — those are not
  on-disk references and verifying them requires the network.
* Skip pure fragment targets like ``#section`` — we only check link
  targets that point at on-disk files / directories.
* For every remaining target, strip any trailing ``#anchor`` or ``?query``
  and resolve relative to the **containing doc's directory**. Assert the
  resulting path exists on disk.

If this test fails the report lists every broken link so the fix is
mechanical — either update the link, move the target, or convert the
reference to a URL. No engine imports needed; this runs in any minimal
test environment.

Locked here so the docs stay self-consistent across sprint boundaries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"


# Matches both ``[label](target)`` and ``![alt](target)`` markdown links.
# The lookbehind for ``!`` lets us match either form without duplicating
# the regex. Targets stop at the first unescaped closing paren.
_LINK_RE = re.compile(
    r"!?\[(?P<label>[^\]\n]*)\]\((?P<target>[^)\n]+)\)"
)

# Schemes we never try to resolve on disk.
_SKIP_SCHEMES: tuple[str, ...] = (
    "http://",
    "https://",
    "mailto:",
    "ftp://",
    "ftps://",
)


def _iter_doc_files() -> Iterable[Path]:
    """Yield every ``.md`` file under ``docs/`` in sorted, stable order."""
    return sorted(DOCS_ROOT.rglob("*.md"))


def _strip_anchor(target: str) -> str:
    """Drop ``#anchor`` / ``?query`` suffix from a link target."""
    for sep in ("#", "?"):
        idx = target.find(sep)
        if idx != -1:
            target = target[:idx]
    return target


def _is_external(target: str) -> bool:
    """Return ``True`` if the target is a URL / mail link we should skip."""
    lower = target.lower()
    return any(lower.startswith(scheme) for scheme in _SKIP_SCHEMES)


def _extract_links(doc: Path) -> list[tuple[str, str, int]]:
    """Return ``[(label, target, line_number), ...]`` for the doc.

    Reads with ``utf-8-sig`` so a stray BOM at the top of a hand-written
    doc never causes a false positive.
    """
    text = doc.read_text(encoding="utf-8-sig")
    out: list[tuple[str, str, int]] = []
    for match in _LINK_RE.finditer(text):
        target = match.group("target").strip()
        if not target:
            continue
        label = match.group("label")
        line_no = text.count("\n", 0, match.start()) + 1
        out.append((label, target, line_no))
    return out


def test_docs_directory_exists() -> None:
    """Sanity-check that there is a ``docs/`` directory to walk."""
    assert DOCS_ROOT.is_dir(), f"missing docs directory at {DOCS_ROOT}"


def test_at_least_one_doc_file() -> None:
    """If the docs tree has nothing in it we want the test suite to scream."""
    docs = list(_iter_doc_files())
    assert docs, f"no *.md files found under {DOCS_ROOT}"


def test_all_doc_links_resolve_on_disk() -> None:
    """Every relative link in every ``docs/**/*.md`` must point at an existing path.

    Builds a list of every broken link before failing so contributors see
    every offender in one pytest run, not one per fix-cycle.
    """
    broken: list[str] = []
    checked = 0
    for doc in _iter_doc_files():
        rel_doc = doc.relative_to(REPO_ROOT)
        for label, target, line_no in _extract_links(doc):
            if _is_external(target):
                continue
            stripped = _strip_anchor(target).strip()
            if not stripped:
                # Pure fragment / query — nothing to resolve on disk.
                continue
            # Resolve relative to the doc's directory.
            resolved = (doc.parent / stripped).resolve()
            checked += 1
            if not resolved.exists():
                broken.append(
                    f"{rel_doc}:{line_no} -> [{label}]({target}) "
                    f"=> {resolved} (does not exist)"
                )

    assert checked > 0, "found zero on-disk links to verify — regex broken?"
    assert not broken, (
        f"{len(broken)} broken link(s) found across docs/:\n"
        + "\n".join("  " + entry for entry in broken)
    )


@pytest.mark.parametrize(
    "doc_path",
    [pytest.param(p, id=str(p.relative_to(REPO_ROOT))) for p in _iter_doc_files()],
)
def test_per_doc_links_resolve(doc_path: Path) -> None:
    """Per-doc variant of the bulk check — pinpoints which file is broken."""
    broken: list[str] = []
    for label, target, line_no in _extract_links(doc_path):
        if _is_external(target):
            continue
        stripped = _strip_anchor(target).strip()
        if not stripped:
            continue
        resolved = (doc_path.parent / stripped).resolve()
        if not resolved.exists():
            broken.append(
                f"line {line_no}: [{label}]({target}) => {resolved}"
            )
    assert not broken, (
        f"broken link(s) in {doc_path.relative_to(REPO_ROOT)}:\n"
        + "\n".join("  " + entry for entry in broken)
    )
