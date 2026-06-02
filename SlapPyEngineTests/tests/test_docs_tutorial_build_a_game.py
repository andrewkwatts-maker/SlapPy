"""Tripwire — docs/tutorial_build_a_game.md."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "tutorial_build_a_game.md"


def _read_doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_doc_exists() -> None:
    assert _DOC.exists(), f"Missing {_DOC}"


@pytest.mark.parametrize(
    "section",
    [
        "1. Project layout",
        "2. Spawning the rocket",
        "3. Adding asteroids",
        "4. Collision",
        "5. Score system",
        "6. HUD overlay",
        "7. Audio",
        "8. Save / load",
        "9. Polish: lighting and post-process",
        "10. Performance",
    ],
)
def test_doc_has_all_10_sections(section: str) -> None:
    text = _read_doc()
    assert section in text, f"Missing section header containing {section!r}"


def test_doc_links_resolve() -> None:
    text = _read_doc()
    # Markdown link pattern: [label](relative/path)
    for label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text):
        # Skip external links (http/https)
        if target.startswith(("http://", "https://", "#")):
            continue
        full = (_DOC.parent / target).resolve()
        assert full.exists(), f"Broken link {label!r} → {target} (resolved {full})"


def test_doc_code_blocks_parse() -> None:
    text = _read_doc()
    # Extract every ```python fenced block.
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    assert blocks, "No python code blocks found in tutorial doc"
    for i, block in enumerate(blocks):
        try:
            ast.parse(block)
        except SyntaxError as exc:
            raise AssertionError(
                f"Python block #{i} failed to parse:\n---\n{block}\n---\n{exc}"
            ) from exc


def test_doc_under_800_lines() -> None:
    lines = _read_doc().splitlines()
    assert len(lines) < 800, f"Tutorial is {len(lines)} lines; cap is 800"
