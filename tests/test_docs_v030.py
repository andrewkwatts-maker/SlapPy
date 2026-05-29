"""Tripwire tests for v0.3 release docs.

Locks the README and CHANGELOG entries that downstream games and the
docs-generator scripts depend on. Pure text assertions — no engine
imports — so this file runs in any minimal environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


@pytest.fixture(scope="module")
def readme_text() -> str:
    assert README.exists(), f"README not found at {README}"
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def changelog_text() -> str:
    assert CHANGELOG.exists(), f"CHANGELOG not found at {CHANGELOG}"
    return CHANGELOG.read_text(encoding="utf-8")


def test_readme_mentions_v030(readme_text: str) -> None:
    """README must call out the v0.3 release with a dedicated heading."""
    assert (
        "What's new in v0.3" in readme_text
        or "What's new in v0.3.0" in readme_text
    ), "README missing 'What's new in v0.3' (or v0.3.0) heading"


def test_readme_links_to_engine_surface_doc(readme_text: str) -> None:
    """README must link to the auto-generated engine-surface reference."""
    assert "docs/engine_surface_v030.md" in readme_text, (
        "README must contain a markdown link to docs/engine_surface_v030.md"
    )


def test_changelog_has_030_section(changelog_text: str) -> None:
    """CHANGELOG must contain a top-level [0.3.0] release header."""
    assert "## [0.3.0]" in changelog_text, (
        "CHANGELOG missing '## [0.3.0]' release section"
    )


def test_changelog_030_mentions_new_subpackages(changelog_text: str) -> None:
    """The 0.3.0 section must enumerate every new top-level subpackage."""
    section = _extract_030_section(changelog_text)
    required = (
        "dynamics",
        "zones",
        "topology",
        "numerics",
        "thermal",
        "iso",
        "telemetry",
        "testing",
    )
    missing = [name for name in required if name not in section]
    assert not missing, (
        f"0.3.0 section missing references to subpackages: {missing}"
    )


def test_changelog_030_mentions_hardening(changelog_text: str) -> None:
    """The 0.3.0 section must mention hardening / input validation."""
    section = _extract_030_section(changelog_text).lower()
    assert "hardening" in section or "input validation" in section, (
        "0.3.0 section must mention 'hardening' or 'input validation'"
    )


def _extract_030_section(text: str) -> str:
    """Return everything in the 0.3.0 section up to the next ## heading."""
    marker = "## [0.3.0]"
    start = text.find(marker)
    assert start != -1, "expected [0.3.0] section header in CHANGELOG"
    # Find next top-level heading after the 0.3.0 marker.
    next_section = text.find("\n## ", start + len(marker))
    if next_section == -1:
        return text[start:]
    return text[start:next_section]
