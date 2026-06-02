"""
Tests for `slappyengine.audio_runtime` — the sounddevice shim.

These tests cover:
  - Real backend selection when `sounddevice` is importable.
  - Stub backend fallback when `sounddevice` is missing.
  - Exactly one WARNING is logged on stub-mode import.
  - `slappyengine.audio` routes playback through `audio_runtime.get_backend()`.
"""
from __future__ import annotations

import importlib
import logging
import sys
from unittest import mock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _reload_runtime():
    """Force-reimport `audio_runtime` so module-import side-effects re-run."""
    import slappyengine.audio_runtime as ar
    importlib.reload(ar)
    return ar


def _sounddevice_available() -> bool:
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# test_real_backend_when_sounddevice_present
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _sounddevice_available(),
    reason="sounddevice not installed in this env — real-backend path can't be exercised",
)
def test_real_backend_when_sounddevice_present():
    ar = _reload_runtime()
    backend = ar.get_backend()
    assert backend.is_real() is True


# ---------------------------------------------------------------------------
# test_stub_backend_when_sounddevice_absent
# ---------------------------------------------------------------------------

def test_stub_backend_when_sounddevice_absent():
    # `patch.dict(..., {"sounddevice": None})` forces `import sounddevice` to
    # raise ImportError, simulating the missing-dep case even on machines that
    # have it installed.
    with mock.patch.dict(sys.modules, {"sounddevice": None}):
        ar = _reload_runtime()
        backend = ar.get_backend()
        assert backend.is_real() is False
        # No-op: must not raise even with garbage shapes.
        backend.play_buffer(np.zeros(1024, dtype=np.float32), 44100)
        backend.stop_all()

    # Restore real backend selection for the rest of the suite.
    _reload_runtime()


# ---------------------------------------------------------------------------
# test_warning_logged_once_for_stub
# ---------------------------------------------------------------------------

def test_warning_logged_once_for_stub(caplog):
    expected = (
        "sounddevice not installed; audio playback is a no-op stub. "
        "Install slappy-engine[audio] to enable sound."
    )
    with mock.patch.dict(sys.modules, {"sounddevice": None}):
        with caplog.at_level(logging.WARNING, logger="slappyengine.audio"):
            ar = _reload_runtime()
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and r.name == "slappyengine.audio"
                and r.getMessage() == expected
            ]
            assert len(warnings) == 1, (
                f"expected exactly 1 stub-mode WARNING, got {len(warnings)}: "
                f"{[r.getMessage() for r in caplog.records]}"
            )

            # Subsequent get_backend() calls must not re-warn — the backend is
            # cached at module-import time.
            pre_count = len(caplog.records)
            for _ in range(5):
                ar.get_backend()
            assert len(caplog.records) == pre_count, (
                "get_backend() must not emit new log records after init"
            )

    # Restore real backend selection.
    _reload_runtime()


# ---------------------------------------------------------------------------
# test_audio_module_uses_runtime
# ---------------------------------------------------------------------------

def test_audio_module_uses_runtime():
    """`audio.play_sound(...)` must route through audio_runtime.get_backend()."""
    from slappyengine import audio, audio_runtime

    mock_backend = mock.MagicMock()
    mock_backend.is_real.return_value = True

    samples = np.zeros(2048, dtype=np.float32)
    handle = audio.SoundHandle(path="virtual.wav", data=samples, samplerate=48000)

    with mock.patch.object(audio_runtime, "get_backend", return_value=mock_backend):
        audio.play_sound(handle)

    mock_backend.play_buffer.assert_called_once()
    args, _ = mock_backend.play_buffer.call_args
    # First arg is the sample buffer, second is the sample rate.
    assert args[0] is samples
    assert args[1] == 48000
