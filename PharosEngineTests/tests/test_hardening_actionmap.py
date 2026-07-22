"""Negative-path tests for :class:`ActionMap` public-boundary validation
(hardening round 4).

The positive paths (``ActionMap.wasd``, ``ActionMap.arrows``,
``ActionMap.from_dict``, ``is_held`` / ``axis``) are exercised in
``examples/multiplayer_demo.py`` and the integration test suite.
This file only documents the rejection cases for ``bind`` / ``unbind``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from pharos_engine.input.action_map import ActionMap  # noqa: E402


# ---------------------------------------------------------------------------
# bind — action name
# ---------------------------------------------------------------------------

def test_bind_rejects_empty_action():
    am = ActionMap(player_id=0)
    with pytest.raises(ValueError, match="action must be non-empty"):
        am.bind("", "w")


def test_bind_rejects_int_action():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="action must be a str"):
        am.bind(123, "w")


def test_bind_rejects_bytes_action():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="action must be a str"):
        am.bind(b"move_up", "w")


def test_bind_rejects_none_action():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="action must be a str"):
        am.bind(None, "w")


# ---------------------------------------------------------------------------
# bind — key(s)
# ---------------------------------------------------------------------------

def test_bind_rejects_empty_string_key():
    am = ActionMap(player_id=0)
    with pytest.raises(ValueError, match="key must be non-empty"):
        am.bind("move_up", "")


def test_bind_rejects_empty_list_keys():
    am = ActionMap(player_id=0)
    with pytest.raises(ValueError, match="key must be non-empty"):
        am.bind("move_up", [])


def test_bind_rejects_bytes_key():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="key must be a str or iterable of str"):
        am.bind("move_up", b"w")


def test_bind_rejects_int_key():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="key must be a str or iterable of str"):
        am.bind("move_up", 119)  # ord('w') — silently accepted before


def test_bind_rejects_list_with_empty_string_entry():
    am = ActionMap(player_id=0)
    with pytest.raises(ValueError, match=r"key\[1\] must be non-empty"):
        am.bind("move_up", ["w", ""])


def test_bind_rejects_list_with_non_str_entry():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match=r"key\[0\] must be a str"):
        am.bind("move_up", [42])


# ---------------------------------------------------------------------------
# unbind — action name
# ---------------------------------------------------------------------------

def test_unbind_rejects_empty_action():
    am = ActionMap(player_id=0)
    with pytest.raises(ValueError, match="action must be non-empty"):
        am.unbind("")


def test_unbind_rejects_int_action():
    am = ActionMap(player_id=0)
    with pytest.raises(TypeError, match="action must be a str"):
        am.unbind(0)


# ---------------------------------------------------------------------------
# Positive sanity — single-string key still works
# ---------------------------------------------------------------------------

def test_bind_single_str_key_round_trip():
    am = ActionMap(player_id=0)
    am.bind("move_up", "w")
    assert am.actions_for_key("w") == ["move_up"]
    am._press("w")
    assert am.is_held("move_up")
    am._release("w")
    assert not am.is_held("move_up")


def test_bind_list_keys_uses_first_key():
    # Backwards-compatible: list form takes the first key (matches the
    # historical single-key contract).
    am = ActionMap(player_id=0)
    am.bind("move_up", ["w", "arrowup"])
    assert am.actions_for_key("w") == ["move_up"]
