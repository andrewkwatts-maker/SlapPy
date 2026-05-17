"""
Audio system — spatial sound playback via sounddevice + soundfile.

Optional extra: pip install SlapPyEngine[audio]
Falls back gracefully if sounddevice/soundfile not installed.

Usage:
    audio = engine.audio
    if audio:
        handle = audio.load("assets/audio/shoot.wav")
        audio.play(handle)
        audio.play_spatial(handle, entity.position, listener_pos, max_dist=500)
"""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Any


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
        try:
            import sounddevice as sd
            import soundfile as sf
            self._sd = sd
            self._sf = sf
            self._available = True
        except ImportError:
            self._sd = None
            self._sf = None
            self._available = False
        self._cache: dict[str, SoundHandle] = {}
        self._master_volume: float = 1.0

    @property
    def available(self) -> bool:
        return self._available

    def load(self, path: str) -> SoundHandle | None:
        if not self._available:
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
        if handle is None or not self._available:
            return
        vol = volume * self._master_volume
        data = handle.data * vol
        sd = self._sd
        sr = handle.samplerate

        def _play():
            try:
                sd.play(data, sr)
                if loop:
                    while True:
                        sd.wait()
                        sd.play(data, sr)
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
        if handle is None or not self._available:
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
        sd = self._sd
        sr = handle.samplerate
        t = threading.Thread(target=lambda: sd.play(data, sr), daemon=True)
        t.start()

    def stop_all(self) -> None:
        if self._available:
            try:
                self._sd.stop()
            except Exception:
                pass

    @property
    def master_volume(self) -> float:
        return self._master_volume

    @master_volume.setter
    def master_volume(self, v: float) -> None:
        self._master_volume = max(0.0, min(1.0, v))
