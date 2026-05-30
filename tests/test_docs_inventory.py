"""Tripwire for ``docs/sprint_5_doc_inventory.md``.

The inventory is meant to be a one-page index of every Markdown file
under ``docs/``. This test enforces two invariants:

1. Every ``docs/**/*.md`` file appears as a link in the inventory. If
   you add a doc and forget to index it, this test fails.
2. Every link in the inventory points at an on-disk file. (The general
   doc-link check in ``test_docs_links_resolve_all.py`` already covers
   this, but we duplicate the assertion here so a stale entry in the
   inventory is reported with the inventory-specific failure message.)
3. Every indexed entry has a non-empty one-line description (the table
   body cell must not be empty / just whitespace).

Pure text assertions — no engine imports — so this file runs in any
minimal environment.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
INVENTORY = DOCS_ROOT / "sprint_5_doc_inventory.md"

# Inventory link form: ``[`api/foo.md`](api/foo.md)`` or
# ``[api/foo.md](api/foo.md)`` etc. We only care about the target side.
_LINK_RE = re.compile(r"\[(?P<label>[^\]\n]*)\]\((?P<target>[^)\n]+)\)")

# Table-row form (skipping the table header / separator rows):
#   | [label](target) | description |
_ROW_RE = re.compile(
    r"^\|\s*(?P<linkcell>\[[^\]]*\]\([^)]+\))\s*\|\s*(?P<desc>.+?)\s*\|\s*$",
    re.MULTILINE,
)


def _inventory_text() -> str:
    assert INVENTORY.exists(), f"missing inventory doc at {INVENTORY}"
    return INVENTORY.read_text(encoding="utf-8-sig")


def _all_doc_paths() -> list[Path]:
    return sorted(DOCS_ROOT.rglob("*.md"))


def _indexed_targets(text: str) -> set[str]:
    """Return the set of inventory-link targets (normalised to forward-slash)."""
    targets: set[str] = set()
    for match in _LINK_RE.finditer(text):
        target = match.group("target").strip()
        # Strip any fragment / query suffix.
        for sep in ("#", "?"):
            idx = target.find(sep)
            if idx != -1:
                target = target[:idx]
        # Normalise so windows backslashes never sneak in.
        targets.add(target.replace("\\", "/"))
    return targets


def test_inventory_doc_exists() -> None:
    assert INVENTORY.is_file(), f"inventory doc missing at {INVENTORY}"


def test_every_doc_is_indexed() -> None:
    """Every doc under ``docs/**/*.md`` must appear in the inventory."""
    text = _inventory_text()
    indexed = _indexed_targets(text)

    missing: list[str] = []
    for doc in _all_doc_paths():
        rel = doc.relative_to(DOCS_ROOT).as_posix()
        if rel not in indexed:
            missing.append(rel)

    assert not missing, (
        f"{len(missing)} doc(s) missing from "
        f"{INVENTORY.relative_to(REPO_ROOT)}:\n"
        + "\n".join("  - " + m for m in missing)
    )


def test_inventory_targets_all_exist() -> None:
    """Every inventory link target must resolve to an on-disk file."""
    text = _inventory_text()
    broken: list[str] = []
    for match in _LINK_RE.finditer(text):
        target = match.group("target").strip()
        # Strip fragment / query.
        for sep in ("#", "?"):
            idx = target.find(sep)
            if idx != -1:
                target = target[:idx]
        resolved = (INVENTORY.parent / target).resolve()
        if not resolved.exists():
            broken.append(f"[{match.group('label')}]({match.group('target')})")
    assert not broken, (
        f"{len(broken)} inventory entry/entries point at non-existent paths:\n"
        + "\n".join("  - " + b for b in broken)
    )


def test_every_indexed_entry_has_description() -> None:
    """Each inventory table row must include a non-empty description cell."""
    text = _inventory_text()
    empty: list[str] = []
    for match in _ROW_RE.finditer(text):
        link = match.group("linkcell")
        desc = (match.group("desc") or "").strip()
        if not desc or desc.lower() in {"todo", "tbd", "-"}:
            empty.append(link)
    assert not empty, (
        f"{len(empty)} inventory row(s) missing a description:\n"
        + "\n".join("  - " + e for e in empty)
    )
