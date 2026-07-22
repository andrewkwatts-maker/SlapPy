"""Tripwires for the per-subpackage API reference docs under ``docs/api/``.

These tests guard the contract that:

* Every target subpackage has a ``docs/api/<name>.md`` file.
* Each doc carries the four required H2 section headers.
* Every public name actually exposed by the subpackage at runtime is
  mentioned in its doc.
* Re-running ``scripts/gen_subpackage_api_docs.py`` is byte-identical
  when no source has changed (idempotency).
* The generator does not crash on an unknown subpackage name.

If a test fails, run::

    PYTHONPATH=python python scripts/gen_subpackage_api_docs.py

to regenerate.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = REPO_ROOT / "python"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

# Load the generator module by file path so the test does not depend on
# ``scripts/`` being importable as a package.
_GEN_PATH = REPO_ROOT / "scripts" / "gen_subpackage_api_docs.py"
_spec = importlib.util.spec_from_file_location(
    "gen_subpackage_api_docs", _GEN_PATH,
)
assert _spec is not None and _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
# Register before executing so ``@dataclasses.dataclass`` decorators inside
# the generator can look the module up via ``sys.modules[cls.__module__]``.
sys.modules["gen_subpackage_api_docs"] = gen
_spec.loader.exec_module(gen)


DOC_DIR = REPO_ROOT / "docs" / "api"
TARGETS: tuple[str, ...] = gen.TARGET_SUBPACKAGES


# ---------------------------------------------------------------------------
# Per-subpackage doc presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subpackage", TARGETS)
def test_each_subpackage_doc_exists(subpackage: str) -> None:
    path = DOC_DIR / f"{subpackage}.md"
    assert path.is_file(), (
        f"missing {path.relative_to(REPO_ROOT)} — run "
        "`python scripts/gen_subpackage_api_docs.py`"
    )


# ---------------------------------------------------------------------------
# Required section headers
# ---------------------------------------------------------------------------


REQUIRED_HEADERS = ("## Classes", "## Functions", "## Constants")


@pytest.mark.parametrize("subpackage", TARGETS)
def test_each_doc_has_required_sections(subpackage: str) -> None:
    path = DOC_DIR / f"{subpackage}.md"
    # Hand-authored docs opt out of the auto-gen H2 schema. They organise
    # their content around the subpackage's own concepts (e.g. iso splits
    # "Rendering surface" vs "Combat surface"; telemetry splits "Hot path"
    # vs "Subscription primitives"). Enforce the schema only on the docs
    # the generator actually owns.
    if gen._is_handauthored(path):
        pytest.skip("hand-authored doc — schema is owned by the author")
    text = path.read_text(encoding="utf-8")
    for header in REQUIRED_HEADERS:
        assert header in text, f"{subpackage}.md missing header: {header!r}"


# ---------------------------------------------------------------------------
# Every public name mentioned
# ---------------------------------------------------------------------------


def _public_names(subpackage: str) -> list[str]:
    module = importlib.import_module(f"pharos_engine.{subpackage}")
    explicit = getattr(module, "__all__", None)
    if explicit:
        return sorted({n for n in explicit if not n.startswith("_") and n != "annotations"})
    return sorted(
        n for n in dir(module)
        if not n.startswith("_")
        and n != "annotations"
        and not inspect.ismodule(getattr(module, n, None))
    )


@pytest.mark.parametrize("subpackage", TARGETS)
def test_each_doc_lists_every_public_name(subpackage: str) -> None:
    text = (DOC_DIR / f"{subpackage}.md").read_text(encoding="utf-8")
    missing: list[str] = []
    for name in _public_names(subpackage):
        # Match the name as a backticked code span so we don't false-positive
        # on substring matches (e.g. ``Body`` inside ``SoftBodyWorld``).
        pattern = re.compile(rf"`{re.escape(name)}[`(]")
        if not pattern.search(text):
            missing.append(name)
    assert not missing, (
        f"public names missing from docs/api/{subpackage}.md: {missing}"
    )


# ---------------------------------------------------------------------------
# Idempotency: re-run is byte-identical
# ---------------------------------------------------------------------------


def test_doc_is_regenerable_idempotent(tmp_path: Path) -> None:
    """Two consecutive generator passes must produce byte-identical output."""
    # Snapshot existing docs.
    before = {
        p.name: p.read_bytes()
        for p in DOC_DIR.glob("*.md")
    }
    # Re-run.
    gen.write_all()
    after = {
        p.name: p.read_bytes()
        for p in DOC_DIR.glob("*.md")
    }
    assert before.keys() == after.keys()
    diffs = [name for name in before if before[name] != after[name]]
    assert not diffs, f"generator output drifted for: {diffs}"


# ---------------------------------------------------------------------------
# Graceful handling of an unknown subpackage
# ---------------------------------------------------------------------------


def test_generator_handles_missing_module_gracefully() -> None:
    """Rendering a non-existent subpackage should not crash."""
    body = gen._render_subpackage("definitely_not_a_real_subpackage_xyz")
    assert "Could not import" in body
    assert "pharos_engine.definitely_not_a_real_subpackage_xyz" in body


# ---------------------------------------------------------------------------
# Raises parser smoke
# ---------------------------------------------------------------------------


def test_raises_parser_handles_numpy_and_google() -> None:
    """The Raises section parser must understand both grammars."""
    numpy_doc = (
        "Do a thing.\n"
        "\n"
        "Raises\n"
        "------\n"
        "ValueError\n"
        "    when bad.\n"
        "TypeError\n"
        "    when wrong type.\n"
    )
    google_doc = (
        "Do a thing.\n"
        "\n"
        "Raises:\n"
        "    ValueError: when bad.\n"
        "    TypeError: when wrong type.\n"
    )
    numpy_parsed = gen._extract_raises(numpy_doc)
    google_parsed = gen._extract_raises(google_doc)
    assert ("ValueError", "when bad.") in numpy_parsed
    assert ("TypeError", "when wrong type.") in numpy_parsed
    assert ("ValueError", "when bad.") in google_parsed
    assert ("TypeError", "when wrong type.") in google_parsed
