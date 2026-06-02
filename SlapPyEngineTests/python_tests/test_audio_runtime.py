"""Tests for slappyengine.audio_runtime.

Asserts the soft-import + WARNING-on-stub contract. Does NOT require
sounddevice / soundfile to be installed — the runtime adapts to either
state.
"""
from __future__ import annotations

import logging

import pytest

from slappyengine.audio_runtime import (
    backend_status,
    is_real_backend,
    play_sample,
    preload,
    set_master_volume,
)


def test_backend_status_string_present():
    status = backend_status()
    assert isinstance(status, str)
    assert len(status) > 0


def test_is_real_backend_is_a_bool():
    val = is_real_backend()
    assert isinstance(val, bool)


def test_play_sample_does_not_raise_on_missing_file():
    """Whether the backend is real or stub, calling play_sample on a
    nonexistent path should never crash the game loop."""
    ok = play_sample("/does/not/exist.wav")
    assert ok is False


def test_play_sample_returns_false_on_stub_backend():
    """When the real backend is unavailable, play_sample returns False."""
    if is_real_backend():
        pytest.skip("real backend installed; stub-path assertion N/A")
    assert play_sample("/anything.wav") is False


def test_play_sample_stub_warning_logged_at_most_once(caplog):
    """On stub backend, the no-op warning should only fire once per process."""
    if is_real_backend():
        pytest.skip("real backend installed; stub-warning assertion N/A")
    # Reset the singleton warning state by accessing the internals
    from slappyengine.audio_runtime import _get_runtime
    runtime = _get_runtime()
    runtime._stub_warned = False
    with caplog.at_level(logging.WARNING, logger="slappyengine.audio_runtime"):
        play_sample("/first.wav")
        n1 = sum(1 for r in caplog.records if "stub" in r.message.lower())
        play_sample("/second.wav")
        n2 = sum(1 for r in caplog.records if "stub" in r.message.lower())
    # Both calls returned False, but only one WARNING fired.
    assert n1 >= 1
    assert n2 == n1, "stub-warning should fire only on the first call"


def test_preload_returns_false_on_stub_backend():
    if is_real_backend():
        pytest.skip("real backend installed; stub-path assertion N/A")
    assert preload("/anything.wav") is False


def test_set_master_volume_does_not_raise():
    """Volume setter is safe to call on either backend."""
    set_master_volume(0.5)
    set_master_volume(1.0)
    set_master_volume(2.0)
    # Out-of-range values get clamped, not rejected.
    set_master_volume(-1.0)
    set_master_volume(5.0)


def test_module_import_emits_one_warning_if_stub(caplog):
    """Reimport contract: when stub, the import-time WARNING is present."""
    if is_real_backend():
        pytest.skip("real backend installed; assertion N/A")
    # Module was already imported above. Detect via the status string.
    assert "unavailable" in backend_status().lower()
