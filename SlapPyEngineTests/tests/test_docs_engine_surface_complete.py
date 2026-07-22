"""Tripwire for ``docs/engine_surface_v030.md``.

Asserts the generated doc is in sync with the actual public surface:

* the doc file exists,
* every name in :data:`pharos_engine.__all__` is mentioned,
* every subpackage in the ``_subpackages`` set inside
  ``pharos_engine.__init__.__getattr__`` is mentioned,
* the four required section headers are present.

If the doc drifts, run::

    PYTHONPATH=python python scripts/gen_engine_surface_doc.py

to regenerate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import pharos_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "engine_surface_v030.md"
INIT_PATH = REPO_ROOT / "python" / "pharos_engine" / "__init__.py"


def _read_subpackages_from_init() -> set[str]:
    """Parse ``__init__.py`` for the ``_subpackages`` set literal."""
    src = INIT_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__getattr__":
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "_subpackages":
                            if isinstance(stmt.value, (ast.Set, ast.Tuple, ast.List)):
                                return {
                                    elt.value
                                    for elt in stmt.value.elts
                                    if isinstance(elt, ast.Constant)
                                    and isinstance(elt.value, str)
                                }
    raise AssertionError("could not locate _subpackages set in __init__.py")


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), (
        f"missing {DOC_PATH.relative_to(REPO_ROOT)} — run "
        "`python scripts/gen_engine_surface_doc.py`"
    )
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_exists() -> None:
    assert DOC_PATH.is_file(), DOC_PATH


def test_doc_has_required_headers(doc_text: str) -> None:
    """All four section headers from the spec must be present."""
    required = [
        "Top-level surface",
        "Subpackages",
        "Stability notes",
        "Getting started",
    ]
    for header in required:
        assert header in doc_text, f"missing header: {header!r}"


def test_doc_mentions_every_top_level_name(doc_text: str) -> None:
    """Every entry in ``__all__`` must appear in the doc."""
    missing = []
    for name in sorted(pharos_engine.__all__):
        # Match the name as a backticked code span so we don't false-positive
        # on substring matches (e.g. ``Layer`` inside ``Layer2D``).
        pattern = re.compile(rf"`{re.escape(name)}`")
        if not pattern.search(doc_text):
            missing.append(name)
    assert not missing, f"top-level names missing from doc: {missing}"


def test_doc_mentions_every_subpackage(doc_text: str) -> None:
    """Every subpackage declared in ``__init__.__getattr__`` must appear."""
    subs = _read_subpackages_from_init()
    assert subs, "no subpackages discovered — generator/test out of sync"
    missing = []
    for name in sorted(subs):
        pattern = re.compile(rf"`pharos_engine\.{re.escape(name)}`")
        if not pattern.search(doc_text):
            missing.append(name)
    assert not missing, f"subpackages missing from doc: {missing}"


def test_every_all_name_resolves() -> None:
    """Sanity: every ``__all__`` entry must resolve via ``getattr``.

    Any failure here means the generator will skip the broken name and the
    contract is silently incomplete. Flag them loudly.
    """
    failures: list[tuple[str, str]] = []
    for name in sorted(pharos_engine.__all__):
        try:
            getattr(pharos_engine, name)
        except Exception as exc:  # pragma: no cover - diagnostic
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"unresolvable __all__ names: {failures}"
