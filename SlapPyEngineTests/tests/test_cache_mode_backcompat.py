"""Regression tests for CacheMode backwards-compat aliases.

Downstream games (Ochema Circuit, Bullet Strata) depend on the
``OFFSCREEN_SERIALIZE`` / ``ALWAYS_CACHED`` / ``USER_DRIVEN`` enum
members on ``pharos_engine.residency.manager.CacheMode``.

These predate the GPU / RAM / DISK residency-tier vocabulary and were
briefly deleted in the a1732e1 Phase-C refactor. VV1 restored them
after UU3's game-compat re-run identified this as the top remaining
regression (see ``docs/game_compat_2026_07_07.md`` § 9.3 item 1 and
§ 9.4). This module locks in the restore so future refactors cannot
silently regress downstream games again.
"""
from __future__ import annotations

from pharos_engine.residency.manager import CacheMode


def test_offscreen_serialize_exists():
    """``CacheMode.OFFSCREEN_SERIALIZE`` must be a member of the enum."""
    assert CacheMode.OFFSCREEN_SERIALIZE is not None


def test_always_cached_exists():
    """``CacheMode.ALWAYS_CACHED`` must be a member of the enum."""
    assert CacheMode.ALWAYS_CACHED is not None


def test_user_driven_exists():
    """``CacheMode.USER_DRIVEN`` must be a member of the enum."""
    assert CacheMode.USER_DRIVEN is not None


def test_offscreen_serialize_string_value():
    """Downstream Ochema tests read ``.value`` — must equal the legacy
    ``"offscreen_serialize"`` string tag."""
    assert CacheMode.OFFSCREEN_SERIALIZE.value == "offscreen_serialize"


def test_always_cached_string_value():
    """Downstream Ochema tests read ``.value`` — must equal the legacy
    ``"always_cached"`` string tag."""
    assert CacheMode.ALWAYS_CACHED.value == "always_cached"


def test_user_driven_string_value():
    """Downstream Ochema tests read ``.value`` — must equal the legacy
    ``"user_driven"`` string tag."""
    assert CacheMode.USER_DRIVEN.value == "user_driven"


def test_cache_mode_reconstructible_from_value():
    """Round-trip via ``CacheMode("<value>")`` (the enum functional API
    used by asset serialization / save-load code) must return the
    correct member for each backcompat alias."""
    assert CacheMode("offscreen_serialize") is CacheMode.OFFSCREEN_SERIALIZE
    assert CacheMode("always_cached") is CacheMode.ALWAYS_CACHED
    assert CacheMode("user_driven") is CacheMode.USER_DRIVEN


def test_all_members_present():
    """Sanity: enum must contain both the tier vocabulary
    (GPU/RAM/DISK) and the backcompat aliases side-by-side."""
    names = {m.name for m in CacheMode}
    assert {"GPU", "RAM", "DISK"}.issubset(names), (
        f"tier vocabulary regressed — got {names}"
    )
    assert {"OFFSCREEN_SERIALIZE", "ALWAYS_CACHED", "USER_DRIVEN"}.issubset(names), (
        f"backcompat aliases regressed — got {names}"
    )
