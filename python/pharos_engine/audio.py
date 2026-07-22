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


# Backwards-compat: legacy loop registry record used by
# `AudioManager.play_loop` / `stop_loop` / `set_loop_volume` /
# `set_loop_pitch`. Ochema Circuit's Sprint P3 tests introspect
# `am._loops[loop_id].volume` / `.pitch` directly, so the fields must
# be plain attributes not properties.
# DO NOT REMOVE without a v1.0 deprecation cycle.
class _AudioLoopHandle:
    """Bookkeeping record for a tracked looping playback."""

    __slots__ = ("loop_id", "handle", "volume", "pitch", "stopped")

    def __init__(
        self,
        loop_id: int,
        handle: "SoundHandle | None",
        volume: float = 1.0,
        pitch: float = 1.0,
    ) -> None:
        self.loop_id: int = int(loop_id)
        self.handle: "SoundHandle | None" = handle
        self.volume: float = float(volume)
        self.pitch: float = float(pitch)
        self.stopped: bool = False


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
        # Backwards-compat: legacy loop-management state used by
        # `AudioManager.play_loop` / `stop_loop` / `set_loop_volume` /
        # `set_loop_pitch`. Ochema Circuit's Sprint P3 audio system
        # (systems/audio_system.py + tests/test_p3_audio.py) tracks
        # long-running loops by integer id. Kept alongside the modern
        # fire-and-forget `play(loop=True)` path so both APIs coexist.
        # DO NOT REMOVE without a v1.0 deprecation cycle.
        self._loops: dict[int, _AudioLoopHandle] = {}
        self._loop_id_counter: int = 0
        self._loop_lock: threading.Lock = threading.Lock()

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
        # Backwards-compat: also mark every registered loop as stopped so
        # loop-tracking tests observe the `_loops` dict empty after this
        # call. Real playback shutdown is handled by the backend.
        with self._loop_lock:
            for loop in list(self._loops.values()):
                loop.stopped = True
            self._loops.clear()
        audio_runtime.get_backend().stop_all()

    # ------------------------------------------------------------------ loop mgmt

    # Backwards-compat: Ochema Circuit's Sprint P3 audio system tracks
    # long-running engine / screech / music loops by integer id. Modern
    # `play(loop=True)` is fire-and-forget; the legacy API wants a
    # returned int handle plus per-loop volume + pitch mutation. Kept as
    # a thin registry over an inner thread; no-op-safe when the backend
    # is missing (still hands back a valid int id so caller `.stop_loop`
    # patterns don't crash).
    # DO NOT REMOVE without a v1.0 deprecation cycle.
    def play_loop(
        self,
        handle: "SoundHandle | None",
        volume: float = 1.0,
        pitch: float = 1.0,
    ) -> int:
        """Start a tracked looping playback. Returns an integer loop id."""
        with self._loop_lock:
            self._loop_id_counter += 1
            loop_id = self._loop_id_counter
            loop = _AudioLoopHandle(
                loop_id=loop_id,
                handle=handle,
                volume=max(0.0, min(1.0, float(volume))),
                pitch=max(0.1, min(4.0, float(pitch))),
            )
            self._loops[loop_id] = loop

        if handle is None:
            return loop_id

        # Prefer a caller-injected `_sd` (mocked sounddevice) — Ochema
        # Circuit's tests substitute a MagicMock there so tracked-loop
        # tests remain headless. Fall back to `audio_runtime` only when
        # `_sd` is absent AND `_available` is truthy so we never spawn a
        # thread that hits a live audio backend from a test harness.
        sd = getattr(self, "_sd", None)
        if sd is None and not self._available:
            return loop_id

        def _run() -> None:
            data = handle.data
            sr = handle.samplerate
            interval = max(len(data) / float(sr), 0.01)
            import time
            while not loop.stopped:
                try:
                    scaled = data * (loop.volume * self._master_volume)
                    if sd is not None and hasattr(sd, "play"):
                        sd.play(scaled, sr)
                    else:
                        audio_runtime.get_backend().play_buffer(scaled, sr)
                except Exception:
                    break
                time.sleep(interval)
            with self._loop_lock:
                self._loops.pop(loop_id, None)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return loop_id

    def stop_loop(self, loop_id: int) -> None:
        """Mark a tracked loop stopped and drop it from the registry."""
        with self._loop_lock:
            loop = self._loops.pop(loop_id, None)
        if loop is not None:
            loop.stopped = True

    def set_loop_volume(self, loop_id: int, volume: float) -> None:
        """Clamp and update a tracked loop's per-loop volume in [0.0, 1.0]."""
        clamped = max(0.0, min(1.0, float(volume)))
        with self._loop_lock:
            loop = self._loops.get(loop_id)
        if loop is not None:
            loop.volume = clamped

    def set_loop_pitch(self, loop_id: int, pitch: float) -> None:
        """Clamp and update a tracked loop's playback pitch to [0.1, 4.0]."""
        clamped = max(0.1, min(4.0, float(pitch)))
        with self._loop_lock:
            loop = self._loops.get(loop_id)
        if loop is not None:
            loop.pitch = clamped

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
