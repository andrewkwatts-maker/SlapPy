"""
Audio system — spatial sound playback via sounddevice + soundfile.

Optional extra: pip install SlapPyEngine[audio]
Falls back gracefully if sounddevice/soundfile not installed. When
sounddevice is missing, the engine logs a single WARNING at import time
(see `audio_runtime`) and playback becomes a no-op stub rather than
raising — games stay importable but ship muted, loudly.

Usage:
    audio = engine.audio
    if audio:
        handle = audio.load("assets/audio/shoot.wav")
        audio.play(handle)
        audio.play_spatial(handle, entity.position, listener_pos, max_dist=500)
"""
from __future__ import annotations
import threading
from typing import Any

from . import audio_runtime
from ._audio_validation import (
    validate_bool,
    validate_finite_2tuple,
    validate_master_volume,
    validate_path,
    validate_positive_finite_float,
    validate_positive_int,
    validate_sound_handle_or_none,
    validate_volume,
)


class SoundHandle:
    """Opaque handle returned by AudioManager.load()."""

    def __init__(self, path: str, data: Any, samplerate: int):
        self.path = path
        self.data = data          # numpy float32 array (samples, channels)
        self.samplerate = samplerate


class AudioManager:
    """
    Thin wrapper around sounddevice for one-shot and spatial audio.
    All playback is fire-and-forget (daemon threads).
    """

    def __init__(self):
        # Playback is routed through `audio_runtime` so we degrade gracefully
        # when sounddevice is missing. `soundfile` is still a soft import
        # because it owns `load()`; without it, the manager reports
        # unavailable and returns None from `load()`.
        try:
            import soundfile as sf
            self._sf = sf
        except ImportError:
            self._sf = None
        backend = audio_runtime.get_backend()
        # Available iff we can both decode files and route them to a real
        # backend. Stub backend ⇒ no audible playback ⇒ available == False
        # (preserves prior contract: `audio.available` gates spawn calls).
        self._available = (self._sf is not None) and backend.is_real()
        self._cache: dict[str, SoundHandle] = {}
        self._master_volume: float = 1.0

    @property
    def available(self) -> bool:
        return self._available

    def load(self, path: str) -> SoundHandle | None:
        path = validate_path("path", "AudioManager.load", path)
        if self._sf is None:
            return None
        if path in self._cache:
            return self._cache[path]
        try:
            data, sr = self._sf.read(path, dtype="float32")
            handle = SoundHandle(path, data, sr)
            self._cache[path] = handle
            return handle
        except Exception as e:
            print(f"[AudioManager] Failed to load {path}: {e}")
            return None

    def play(
        self,
        handle: SoundHandle | None,
        volume: float = 1.0,
        loop: bool = False,
    ) -> None:
        handle = validate_sound_handle_or_none("handle", "AudioManager.play", handle)
        volume = validate_volume("volume", "AudioManager.play", volume)
        loop = validate_bool("loop", "AudioManager.play", loop)
        if handle is None:
            return
        vol = volume * self._master_volume
        data = handle.data * vol
        sr = handle.samplerate
        backend = audio_runtime.get_backend()

        def _play():
            try:
                backend.play_buffer(data, sr)
                if loop:
                    # Best-effort loop: re-submit on a fixed cadence based
                    # on buffer length. Real backend's sd.wait() isn't on the
                    # AudioBackend protocol, so we sleep instead.
                    import time
                    interval = max(len(data) / float(sr), 0.01)
                    while True:
                        time.sleep(interval)
                        backend.play_buffer(data, sr)
            except Exception:
                pass

        t = threading.Thread(target=_play, daemon=True)
        t.start()

    def play_spatial(
        self,
        handle: SoundHandle | None,
        source_pos: tuple[float, float],
        listener_pos: tuple[float, float],
        max_dist: float = 500.0,
        loop: bool = False,
    ) -> None:
        handle = validate_sound_handle_or_none(
            "handle", "AudioManager.play_spatial", handle
        )
        source_pos = validate_finite_2tuple(
            "source_pos", "AudioManager.play_spatial", source_pos
        )
        listener_pos = validate_finite_2tuple(
            "listener_pos", "AudioManager.play_spatial", listener_pos
        )
        max_dist = validate_positive_finite_float(
            "max_dist", "AudioManager.play_spatial", max_dist
        )
        loop = validate_bool("loop", "AudioManager.play_spatial", loop)
        if handle is None:
            return
        dx = source_pos[0] - listener_pos[0]
        dy = source_pos[1] - listener_pos[1]
        dist = (dx**2 + dy**2) ** 0.5
        volume = max(0.0, 1.0 - dist / max_dist)
        # Simple panning: negative dx = left channel louder
        pan = max(-1.0, min(1.0, dx / max_dist))
        data = handle.data.copy()
        if data.ndim == 1:
            data = data[:, None]  # mono → (N, 1)
        if data.shape[1] == 1:
            # duplicate mono to stereo
            import numpy as np
            data = np.hstack([data, data])
        left_vol = volume * (1.0 - max(0.0, pan))
        right_vol = volume * (1.0 + min(0.0, pan))
        data[:, 0] *= left_vol * self._master_volume
        data[:, 1] *= right_vol * self._master_volume
        sr = handle.samplerate
        backend = audio_runtime.get_backend()
        t = threading.Thread(
            target=lambda: backend.play_buffer(data, sr), daemon=True
        )
        t.start()

    def stop_all(self) -> None:
        audio_runtime.get_backend().stop_all()

    @property
    def master_volume(self) -> float:
        return self._master_volume

    @master_volume.setter
    def master_volume(self, v: float) -> None:
        v = validate_master_volume("master_volume", "AudioManager", v)
        self._master_volume = max(0.0, min(1.0, v))


def play_sound(handle: SoundHandle | None, sample_rate: int | None = None) -> None:
    """Module-level convenience playback hook.

    Routes through `audio_runtime.get_backend().play_buffer(...)` so tests
    (and downstream callers) can submit a raw buffer without instantiating
    an `AudioManager`. Returns silently when `handle` is None.
    """
    handle = validate_sound_handle_or_none("handle", "play_sound", handle)
    if sample_rate is not None:
        sample_rate = validate_positive_int(
            "sample_rate", "play_sound", sample_rate
        )
    if handle is None:
        return
    sr = sample_rate if sample_rate is not None else getattr(handle, "samplerate", 44100)
    audio_runtime.get_backend().play_buffer(handle.data, sr)
