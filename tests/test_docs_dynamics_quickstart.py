"""Tripwire tests for ``docs/dynamics_quickstart.md``.

These tests guard the quick-start doc against the four most common ways it
can rot:

1. The file goes missing.
2. A section heading gets renamed or removed.
3. A code snippet is edited into something that no longer parses as
   Python (typo, lost indentation, partial paste).
4. An internal link points at a file that does not exist.

The tests deliberately do *not* execute the snippets — they only confirm
they parse with ``ast.parse``. End-to-end behaviour is exercised by the
per-demo regression tests (``tests/test_demo_hello_*.py``).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
DOC_PATH = DOCS_DIR / "dynamics_quickstart.md"


REQUIRED_SECTIONS = [
    "0. Install",
    "1. Your first rope",
    "2. Add a ragdoll",
    "3. Tracking a target with IK",
    "4. Springs and motors",
    "5. Combining primitives",
    "6. Rendering",
    "7. Common pitfalls",
    "See also",
]


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _extract_python_blocks(text: str) -> list[str]:
    """Return every triple-backtick ``python`` code block as a string."""
    # Match ```python ... ``` blocks (DOTALL across newlines).
    pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
    return [m.group(1) for m in pattern.finditer(text)]


def _extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """Return (label, target) pairs for every ``[label](target)`` link.

    Skips bare URLs (anything starting with ``http://`` / ``https://``) and
    anchor-only targets (``#section``).
    """
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    results: list[tuple[str, str]] = []
    for m in pattern.finditer(text):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        results.append((label, target))
    return results


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------

def test_doc_exists() -> None:
    assert DOC_PATH.is_file(), f"Missing quick-start doc at {DOC_PATH}"


def test_doc_has_all_sections() -> None:
    text = _read_doc()
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, (
        f"Missing required sections in {DOC_PATH.name}: {missing}"
    )


def test_doc_code_blocks_parse_as_python() -> None:
    text = _read_doc()
    blocks = _extract_python_blocks(text)
    assert blocks, "Quick-start doc has zero ```python``` blocks"
    for i, src in enumerate(blocks):
        try:
            ast.parse(src)
        except SyntaxError as exc:  # pragma: no cover - failure path
            pytest.fail(
                f"Python block #{i} in {DOC_PATH.name} failed to parse:\n"
                f"{exc}\n\n--- snippet ---\n{src}\n--- end snippet ---"
            )


def test_doc_links_resolve() -> None:
    text = _read_doc()
    links = _extract_markdown_links(text)
    assert links, "Quick-start doc has zero internal links"
    unresolved: list[tuple[str, str, Path]] = []
    for label, target in links:
        # Strip an optional `#anchor` fragment.
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        resolved = (DOCS_DIR / target_path).resolve()
        if not resolved.exists():
            unresolved.append((label, target, resolved))
    assert not unresolved, (
        "Internal links in "
        f"{DOC_PATH.name} resolve to missing files:\n"
        + "\n".join(
            f"  [{label}]({target}) -> {path}"
            for label, target, path in unresolved
        )
    )
