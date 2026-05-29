"""Tripwire tests for ``docs/getting_started.md``.

The getting-started doc is the first thing a new game developer sees, so a
broken snippet or stale link is a much sharper credibility hit than a stale
README somewhere deeper. These tests guard against four ways the doc can rot:

1. The file gets renamed or deleted.
2. A section heading is renamed and downstream links break.
3. A code snippet is edited into something that no longer parses as Python
   (typo, lost indentation, partial paste).
4. An internal markdown link points at a file that no longer exists.

The tests intentionally do *not* execute the snippets — execution is gated by
``ast.parse``. Running them would require a wgpu surface and a sound device,
which is exactly what the doc spends a section explaining how to opt in to.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
DOC_PATH = DOCS_DIR / "getting_started.md"

# The seven required top-level sections (matched as substrings so that
# wording-level rewording inside the heading does not flake the test —
# the section *number* is the load-bearing contract).
REQUIRED_SECTIONS = [
    "## 1. Install",
    "## 2. Hello, sprite",
    "## 3. Add physics",
    "## 4. Listen for events",
    "## 5. Render with post-processing",
    "## 6. Polish: audio, save state, performance",
    "## 7. Next steps",
]

# Cap so the doc stays scannable. 400 lines is roughly two screens of dense
# prose — past that, hand it to a deeper reference like dynamics_quickstart.
MAX_LINES = 400


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _extract_python_blocks(text: str) -> list[str]:
    """Return every triple-backtick ``python`` code block body."""
    pattern = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
    return [m.group(1) for m in pattern.finditer(text)]


def _extract_markdown_links(text: str) -> list[tuple[str, str]]:
    """Return (label, target) pairs for every ``[label](target)`` link.

    Skips bare URLs (``http(s)://`` / ``mailto:``) and pure anchors
    (``#section``) — those are not on-disk paths and so are not checked.
    """
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    out: list[tuple[str, str]] = []
    for m in pattern.finditer(text):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.append((label, target))
    return out


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------

def test_doc_exists() -> None:
    assert DOC_PATH.is_file(), f"Missing getting-started doc at {DOC_PATH}"


def test_doc_has_all_7_sections() -> None:
    text = _read_doc()
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, (
        f"Missing required sections in {DOC_PATH.name}: {missing}"
    )


def test_doc_links_resolve() -> None:
    text = _read_doc()
    links = _extract_markdown_links(text)
    assert links, "Getting-started doc has zero internal links"
    unresolved: list[tuple[str, str, Path]] = []
    for label, target in links:
        # Strip optional ``#anchor`` fragment before path resolution.
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        resolved = (DOCS_DIR / target_path).resolve()
        if not resolved.exists():
            unresolved.append((label, target, resolved))
    assert not unresolved, (
        f"Internal links in {DOC_PATH.name} resolve to missing files:\n"
        + "\n".join(
            f"  [{label}]({target}) -> {path}"
            for label, target, path in unresolved
        )
    )


def test_doc_code_blocks_parse() -> None:
    text = _read_doc()
    blocks = _extract_python_blocks(text)
    assert blocks, "Getting-started doc has zero ```python``` blocks"
    for i, src in enumerate(blocks):
        try:
            ast.parse(src)
        except SyntaxError as exc:  # pragma: no cover - failure path
            pytest.fail(
                f"Python block #{i} in {DOC_PATH.name} failed to parse:\n"
                f"{exc}\n\n--- snippet ---\n{src}\n--- end snippet ---"
            )


def test_doc_under_400_lines() -> None:
    text = _read_doc()
    line_count = len(text.splitlines())
    assert line_count <= MAX_LINES, (
        f"Getting-started doc is {line_count} lines (cap is {MAX_LINES}). "
        "Move detail into a deeper reference doc."
    )
