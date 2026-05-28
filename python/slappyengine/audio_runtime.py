"""
audio_runtime — internal plumbing around the `sounddevice` backend.

This is a thin wrapper that lets `slappyengine.audio` import cleanly whether
or not `sounddevice` is installed. When `sounddevice` is missing, a silent
no-op stub backend is used and a single import-time WARNING is emitted so
that games never silently ship muted.

This module is internal plumbing — games and the editor should keep using
`slappyengine.audio` (AudioManager / SoundHandle). The `get_backend()`
accessor is only used by `audio.py` itself.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import numpy as np

_LOG = logging.getLogger("slappyengine.audio")

# Exact warning string surfaced once when the stub backend is selected.
_STUB_WARNING = (
    "sounddevice not installed; audio playback is a no-op stub. "
    "Install slappy-engine[audio] to enable sound."
)


class AudioBackend(Protocol):
    """Protocol for audio backends — real (sounddevice) or stub (no-op)."""

    def play_buffer(self, samples: np.ndarray, sample_rate: int) -> None:
        """Submit a buffer of samples for playback at the given sample rate."""
        ...

    def stop_all(self) -> None:
        """Stop any in-flight playback."""
        ...

    def is_real(self) -> bool:
        """True if this backend actually emits audio, False for the stub."""
        ...


class _RealBackend:
    """Delegates to `sounddevice` for real audio output."""

    def __init__(self, sd: Any) -> None:
        self._sd = sd

    def play_buffer(self, samples: np.ndarray, sample_rate: int) -> None:
        try:
            self._sd.play(samples, sample_rate)
        except Exception:
            # sounddevice raises on device-config errors at runtime;
            # behave like a soft fallback rather than crashing the game.
            pass

    def stop_all(self) -> None:
        try:
            self._sd.stop()
        except Exception:
            pass

    def is_real(self) -> bool:
        return True


class _StubBackend:
    """No-op backend used when `sounddevice` is unavailable."""

    def play_buffer(self, samples: np.ndarray, sample_rate: int) -> None:
        return None

    def stop_all(self) -> None:
        return None

    def is_real(self) -> bool:
        return False


def _init_backend() -> AudioBackend:
    """Pick the real backend if `sounddevice` is importable, else stub+warn."""
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except Exception:
        # ImportError is the common case; a broken install (OSError on the
        # PortAudio DLL) is also possible — both should fall back to stub.
        _LOG.warning(_STUB_WARNING)
        return _StubBackend()
    return _RealBackend(sd)


# Single import-time backend selection. Warning (if any) fires exactly once.
_BACKEND: AudioBackend = _init_backend()


def get_backend() -> AudioBackend:
    """Return the process-wide audio backend (real or stub)."""
    return _BACKEND
