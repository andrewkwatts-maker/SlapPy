"""Negative-path tests for :mod:`slappyengine.audio` public-boundary
validation (hardening round 7).

The positive paths (loading WAVs through :meth:`AudioManager.load`,
fire-and-forget playback, spatial attenuation) are covered by
``test_audio_runtime.py`` and ``test_demo_hello_audio.py``. This file only
exercises the rejection cases on the new ``_audio_validation`` boundary.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from slappyengine.audio import AudioManager, SoundHandle, play_sound  # noqa: E402


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _stub_handle() -> SoundHandle:
    """Build a trivial in-memory SoundHandle for play()/play_spatial() tests.

    A 1-frame stereo buffer is enough — playback is fire-and-forget and the
    real backend is a no-op stub under pytest (sounddevice not installed).
    """
    data = np.zeros((1, 2), dtype=np.float32)
    return SoundHandle(path="<stub>", data=data, samplerate=44100)


# ---------------------------------------------------------------------------
# AudioManager.load — path
# ---------------------------------------------------------------------------


def test_load_rejects_non_str_path():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="path must be a str or Path"):
        mgr.load(123)


def test_load_rejects_bytes_path():
    # soundfile.read accepts bytes as raw audio data — silently succeeds with
    # garbage samples. Refuse loudly at the boundary.
    mgr = AudioManager()
    with pytest.raises(TypeError, match="path must be a str or Path"):
        mgr.load(b"/some/path.wav")


def test_load_rejects_none_path():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="path must be a str or Path"):
        mgr.load(None)


def test_load_rejects_empty_path():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="path must be a non-empty path"):
        mgr.load("")


def test_load_rejects_whitespace_only_path():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="path must be a non-empty path"):
        mgr.load("   ")


def test_load_rejects_list_path():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="path must be a str or Path"):
        mgr.load(["assets", "audio", "shot.wav"])


# ---------------------------------------------------------------------------
# AudioManager.play — handle / volume / loop
# ---------------------------------------------------------------------------


def test_play_rejects_string_as_handle():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        mgr.play("path/to/sound.wav")


def test_play_rejects_int_as_handle():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        mgr.play(0)


def test_play_rejects_dict_as_handle():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        mgr.play({"data": np.zeros(10), "samplerate": 44100})


def test_play_rejects_negative_volume():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="volume must be >= 0"):
        mgr.play(_stub_handle(), volume=-0.5)


def test_play_rejects_nan_volume():
    # NaN volume → buffer multiplied to NaN → silent (or worse, crackle).
    mgr = AudioManager()
    with pytest.raises(ValueError, match="volume must be finite"):
        mgr.play(_stub_handle(), volume=float("nan"))


def test_play_rejects_inf_volume():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="volume must be finite"):
        mgr.play(_stub_handle(), volume=float("inf"))


def test_play_rejects_oversize_volume():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="volume must be <= 10"):
        mgr.play(_stub_handle(), volume=1000.0)


def test_play_rejects_string_volume():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="volume must be a real number"):
        mgr.play(_stub_handle(), volume="loud")


def test_play_rejects_bool_volume():
    # True/False would silently mean volume=1.0/0.0. Refuse — almost
    # certainly a typo at the call site.
    mgr = AudioManager()
    with pytest.raises(TypeError, match="volume must be a real number"):
        mgr.play(_stub_handle(), volume=True)


def test_play_rejects_int_loop():
    # loop=1 would silently "loop forever" via `if loop:`. Refuse.
    mgr = AudioManager()
    with pytest.raises(TypeError, match="loop must be a bool"):
        mgr.play(_stub_handle(), loop=1)


def test_play_rejects_str_loop():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="loop must be a bool"):
        mgr.play(_stub_handle(), loop="yes")


def test_play_rejects_none_loop():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="loop must be a bool"):
        mgr.play(_stub_handle(), loop=None)


# ---------------------------------------------------------------------------
# AudioManager.play_spatial — handle / positions / max_dist / loop
# ---------------------------------------------------------------------------


def test_play_spatial_rejects_position_wrong_length():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="source_pos must have length 2"):
        mgr.play_spatial(_stub_handle(), (1.0, 2.0, 3.0), (0.0, 0.0))


def test_play_spatial_rejects_listener_pos_wrong_length():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="listener_pos must have length 2"):
        mgr.play_spatial(_stub_handle(), (1.0, 2.0), (0.0,))


def test_play_spatial_rejects_string_source_pos():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="source_pos must be a 2-tuple"):
        mgr.play_spatial(_stub_handle(), "origin", (0.0, 0.0))


def test_play_spatial_rejects_nan_source_pos():
    mgr = AudioManager()
    with pytest.raises(ValueError, match=r"source_pos\[0\] must be finite"):
        mgr.play_spatial(_stub_handle(), (float("nan"), 0.0), (0.0, 0.0))


def test_play_spatial_rejects_inf_listener_pos():
    mgr = AudioManager()
    with pytest.raises(ValueError, match=r"listener_pos\[1\] must be finite"):
        mgr.play_spatial(_stub_handle(), (0.0, 0.0), (0.0, float("inf")))


def test_play_spatial_rejects_bool_in_position():
    mgr = AudioManager()
    with pytest.raises(TypeError, match=r"source_pos\[0\] must be a real number"):
        mgr.play_spatial(_stub_handle(), (True, 0.0), (0.0, 0.0))


def test_play_spatial_rejects_zero_max_dist():
    # max_dist=0 → division by zero in the attenuation calc.
    mgr = AudioManager()
    with pytest.raises(ValueError, match="max_dist must be > 0"):
        mgr.play_spatial(_stub_handle(), (1.0, 2.0), (0.0, 0.0), max_dist=0.0)


def test_play_spatial_rejects_negative_max_dist():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="max_dist must be > 0"):
        mgr.play_spatial(_stub_handle(), (1.0, 2.0), (0.0, 0.0), max_dist=-1.0)


def test_play_spatial_rejects_nan_max_dist():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="max_dist must be finite"):
        mgr.play_spatial(
            _stub_handle(), (1.0, 2.0), (0.0, 0.0), max_dist=float("nan")
        )


def test_play_spatial_rejects_inf_max_dist():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="max_dist must be finite"):
        mgr.play_spatial(
            _stub_handle(), (1.0, 2.0), (0.0, 0.0), max_dist=float("inf")
        )


def test_play_spatial_rejects_string_max_dist():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="max_dist must be a real number"):
        mgr.play_spatial(
            _stub_handle(), (1.0, 2.0), (0.0, 0.0), max_dist="far"
        )


def test_play_spatial_rejects_str_handle():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        mgr.play_spatial("oops", (0.0, 0.0), (0.0, 0.0))


def test_play_spatial_rejects_int_loop():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="loop must be a bool"):
        mgr.play_spatial(_stub_handle(), (1.0, 2.0), (0.0, 0.0), loop=1)


# ---------------------------------------------------------------------------
# AudioManager.master_volume setter
# ---------------------------------------------------------------------------


def test_master_volume_rejects_nan():
    # NaN → setter clamps via max/min → silently becomes NaN-poisoned.
    mgr = AudioManager()
    with pytest.raises(ValueError, match="master_volume must be finite"):
        mgr.master_volume = float("nan")


def test_master_volume_rejects_inf():
    mgr = AudioManager()
    with pytest.raises(ValueError, match="master_volume must be finite"):
        mgr.master_volume = float("inf")


def test_master_volume_rejects_string():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="master_volume must be a real number"):
        mgr.master_volume = "max"


def test_master_volume_rejects_bool():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="master_volume must be a real number"):
        mgr.master_volume = True


def test_master_volume_rejects_none():
    mgr = AudioManager()
    with pytest.raises(TypeError, match="master_volume must be a real number"):
        mgr.master_volume = None


def test_master_volume_clamps_after_validation():
    # Sanity: a legit out-of-band value still clamps to [0, 1] — the
    # validator only refuses non-finite / non-numeric, not out-of-range.
    mgr = AudioManager()
    mgr.master_volume = 5.0
    assert mgr.master_volume == 1.0
    mgr.master_volume = -1.0
    assert mgr.master_volume == 0.0
    mgr.master_volume = 0.7
    assert math.isclose(mgr.master_volume, 0.7)


# ---------------------------------------------------------------------------
# Module-level play_sound — handle / sample_rate
# ---------------------------------------------------------------------------


def test_play_sound_rejects_string_handle():
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        play_sound("not a handle")


def test_play_sound_rejects_dict_handle():
    with pytest.raises(TypeError, match="handle must be a SoundHandle or None"):
        play_sound({"data": np.zeros(10)})


def test_play_sound_rejects_zero_sample_rate():
    with pytest.raises(ValueError, match="sample_rate must be >= 1"):
        play_sound(_stub_handle(), sample_rate=0)


def test_play_sound_rejects_negative_sample_rate():
    with pytest.raises(ValueError, match="sample_rate must be >= 1"):
        play_sound(_stub_handle(), sample_rate=-44100)


def test_play_sound_rejects_float_sample_rate():
    # sounddevice silently truncates floats — refuse loudly.
    with pytest.raises(TypeError, match="sample_rate must be an int"):
        play_sound(_stub_handle(), sample_rate=44100.0)


def test_play_sound_rejects_bool_sample_rate():
    # True == 1Hz audio — almost certainly a typo.
    with pytest.raises(TypeError, match="sample_rate must be an int"):
        play_sound(_stub_handle(), sample_rate=True)


def test_play_sound_rejects_string_sample_rate():
    with pytest.raises(TypeError, match="sample_rate must be an int"):
        play_sound(_stub_handle(), sample_rate="44100")


def test_play_sound_accepts_none_handle():
    # Public contract: None → no-op, never raises.
    play_sound(None)
    play_sound(None, sample_rate=None)


def test_play_sound_accepts_explicit_sample_rate():
    # Positive sanity: real handle + valid SR should not raise (backend is
    # a no-op stub when sounddevice isn't installed).
    play_sound(_stub_handle(), sample_rate=48000)
