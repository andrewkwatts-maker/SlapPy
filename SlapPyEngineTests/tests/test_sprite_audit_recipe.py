"""Anchor test: ensures the sprite-audit recipe doc is present and covers the
key phases. Future ticks can repeat the procedure with confidence the
checklist hasn't drifted.
"""
from __future__ import annotations

from pathlib import Path


_DOC = (
    Path(__file__).resolve().parent.parent.parent / "docs" / "sprite_audit_recipe.md"
)


def test_sprite_audit_recipe_exists():
    assert _DOC.is_file(), f"expected sprite audit recipe at {_DOC}"


def test_sprite_audit_recipe_covers_required_phases():
    text = _DOC.read_text(encoding="utf-8").lower()
    # Phase keywords called out by the upstream brief
    for keyword in ("regenerate", "verify", "scorched-wasteland"):
        assert keyword in text, (
            f"sprite_audit_recipe.md missing required keyword: {keyword!r}"
        )
    # Sanity: also mentions the headless PIL constraint
    assert "pil" in text or "pillow" in text
