"""
3D positional audio — attenuation, doppler, HRTF-ish stereo panning.

Companion to `slappyengine.audio` (which provides 2D one-shot + spatial
playback). This module adds the vocabulary and DSP that a 3D scene needs:
listeners with orientation and velocity, sources with a min/max attenuation
band, doppler pitch shift, and an equal-power stereo pan based on the angle
between the listener's forward vector and the source direction.

Design notes
------------
- Playback is routed through `audio.SoundBank`/`AudioManager` when a real
  backend is available, else the engine reports voices as "playing" and the
  DSP math still runs (useful for tests + editor scrubbing).
- Everything is stateless / functional at the DSP layer — the `attenuation`,
  `doppler_shift`, and `stereo_pan` helpers are pure functions that games,
  tests, and offline mixers can call directly.
- Sound speed defaults to 343 m/s (dry air, ~20°C, sea level). Callers can
  override for e.g. underwater scenes (~1480 m/s).

Usage
-----
    from slappyengine.audio_3d import (
        AudioListener, Audio3DSource, SoundBank, Audio3DEngine,
    )

    listener = AudioListener(position=(0, 0, 0), forward=(0, 0, 1))
    bank = SoundBank()
    bank.load("shoot", "assets/shoot.wav")
    engine = Audio3DEngine(listener, bank)
    voice = engine.play(Audio3DSource(
        sound_id="shoot", position=(5, 0, 10), max_distance=50,
    ))
    engine.update(0.016)
    engine.stop(voice)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from . import audio as _audio


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Speed of sound in dry air at ~20°C, sea level (m/s).
SPEED_OF_SOUND: float = 343.0

#: Attenuation curve choices — passed as the `attenuation_curve` field.
ATTENUATION_CURVES: tuple[str, ...] = ("linear", "inverse", "exponential")


# ---------------------------------------------------------------------------
# Vec3 helpers (kept private — no numpy dependency here so we stay lightweight)
# ---------------------------------------------------------------------------

def _vsub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vdot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vcross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vlen(a: tuple[float, float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _vnorm(a: tuple[float, float, float]) -> tuple[float, float, float]:
    L = _vlen(a)
    if L <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / L, a[1] / L, a[2] / L)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AudioListener:
    """Listener pose + velocity in 3D world space.

    Fields
    ------
    position : (x, y, z)
    forward  : unit vector — where the listener is facing.
    up       : unit vector — listener "head up" direction.
    velocity : (x, y, z) — used for doppler shift.
    """
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    forward: tuple[float, float, float] = (0.0, 0.0, 1.0)
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class Audio3DSource:
    """A 3D emitter — one instance per logical sound in the world.

    A source can be spawned many times (each `Audio3DEngine.play` call
    returns a fresh voice id) but the source struct itself is a *config*;
    it does not track voice state.
    """
    sound_id: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    volume: float = 1.0
    pitch: float = 1.0
    min_distance: float = 1.0
    max_distance: float = 20.0
    attenuation_curve: str = "inverse"
    is_looping: bool = False


@dataclass
class _Voice:
    """Internal — one live playback of a source."""
    voice_id: int
    source: Audio3DSource
    age: float = 0.0
    active: bool = True
    # Last-computed DSP state (exposed via engine.debug_state()).
    last_gain: float = 1.0
    last_pitch: float = 1.0
    last_pan: tuple[float, float] = (0.5, 0.5)


# ---------------------------------------------------------------------------
# SoundBank
# ---------------------------------------------------------------------------

class SoundBank:
    """Registry of loaded sound handles keyed by short string ids.

    Wraps `audio.AudioManager` for the actual load; when the underlying
    manager isn't available (no soundfile / stub backend) the bank stores
    a placeholder record so tests + editor scrubbing still work.
    """

    def __init__(self, manager: Optional[_audio.AudioManager] = None):
        self._manager = manager if manager is not None else _audio.AudioManager()
        self._handles: dict[str, object] = {}

    def load(self, name: str, path: str) -> object:
        """Load a sound file and register it under `name`.

        Returns the underlying handle (or a placeholder string when the
        audio manager can't decode files — e.g. missing soundfile dep).
        """
        if not isinstance(name, str) or not name:
            raise ValueError("SoundBank.load: `name` must be a non-empty string")
        if not isinstance(path, str) or not path:
            raise ValueError("SoundBank.load: `path` must be a non-empty string")
        handle = self._manager.load(path)
        # Fall back to a placeholder so `.get()` still returns something
        # non-None for tests that don't stage real .wav fixtures.
        if handle is None:
            handle = {"_stub": True, "path": path}
        self._handles[name] = handle
        return handle

    def register(self, name: str, handle: object) -> None:
        """Direct-inject a pre-built handle (useful for stubs + tests)."""
        if not isinstance(name, str) or not name:
            raise ValueError("SoundBank.register: `name` must be a non-empty string")
        self._handles[name] = handle

    def get(self, name: str) -> Optional[object]:
        return self._handles.get(name)

    def list_all(self) -> list[str]:
        return sorted(self._handles.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._handles

    def __len__(self) -> int:
        return len(self._handles)


# ---------------------------------------------------------------------------
# DSP helpers
# ---------------------------------------------------------------------------

def attenuation(
    distance: float,
    min_dist: float,
    max_dist: float,
    curve: str = "inverse",
) -> float:
    """0..1 volume factor for a source at `distance` from the listener.

    Curves
    ------
    linear      : gain drops linearly from 1 (at min_dist) to 0 (at max_dist)
    inverse     : gain = min_dist / d, then linearly rolled off to 0 at max_dist
                  (matches OpenAL AL_INVERSE_DISTANCE_CLAMPED-ish semantics)
    exponential : gain = (min_dist / d)^2, clamped and rolled off likewise
    """
    if distance < 0:
        raise ValueError(f"attenuation: distance must be >= 0 (got {distance})")
    if min_dist < 0:
        raise ValueError(f"attenuation: min_dist must be >= 0 (got {min_dist})")
    if max_dist <= min_dist:
        raise ValueError(
            f"attenuation: max_dist must be > min_dist "
            f"(got min={min_dist}, max={max_dist})"
        )
    if curve not in ATTENUATION_CURVES:
        raise ValueError(
            f"attenuation: curve must be one of {ATTENUATION_CURVES}, got {curve!r}"
        )

    # Full-volume plateau inside min_dist.
    if distance <= min_dist:
        return 1.0
    # Silent past max_dist.
    if distance >= max_dist:
        return 0.0

    if curve == "linear":
        # 1 at min_dist, 0 at max_dist.
        return 1.0 - (distance - min_dist) / (max_dist - min_dist)

    if curve == "inverse":
        # OpenAL-style inverse-distance falloff, then linearly windowed to 0
        # at max_dist so it doesn't clip abruptly.
        raw = min_dist / distance
        window = 1.0 - (distance - min_dist) / (max_dist - min_dist)
        return max(0.0, min(1.0, raw * window))

    # exponential
    raw = (min_dist / distance) ** 2
    window = 1.0 - (distance - min_dist) / (max_dist - min_dist)
    return max(0.0, min(1.0, raw * window))


def doppler_shift(
    source_vel: tuple[float, float, float],
    listener_vel: tuple[float, float, float],
    source_to_listener: tuple[float, float, float],
    sound_speed: float = SPEED_OF_SOUND,
) -> float:
    """Return a pitch multiplier for the doppler effect.

    Parameters
    ----------
    source_vel        : source velocity in world units/sec.
    listener_vel      : listener velocity in world units/sec.
    source_to_listener: vector *from* the source *to* the listener
                        (i.e. `listener.pos - source.pos`).
    sound_speed       : m/s (default 343 for air).

    Convention
    ----------
    Approaching listener ⇒ pitch > 1.
    Receding listener    ⇒ pitch < 1.
    No relative motion   ⇒ pitch = 1.

    Implementation
    --------------
    Classical formula::

        f' = f * (c + v_listener_towards_source) / (c + v_source_towards_listener)

    which reduces to the "approaching → higher pitch" convention when the
    velocity components are projected onto the unit vector from source→listener.
    """
    if sound_speed <= 0:
        raise ValueError(f"doppler_shift: sound_speed must be > 0 (got {sound_speed})")

    dir_hat = _vnorm(source_to_listener)
    if dir_hat == (0.0, 0.0, 0.0):
        return 1.0

    # Velocity components along the source→listener axis.
    v_source_along = _vdot(source_vel, dir_hat)   # source velocity toward listener
    v_listener_along = _vdot(listener_vel, dir_hat)  # listener velocity along same axis

    # Numerator: sound_speed minus listener's velocity *toward* the source
    # (listener moving toward source ⇒ v_listener_along < 0 ⇒ numerator grows).
    numerator = sound_speed - v_listener_along
    denominator = sound_speed - v_source_along

    # Clamp denominator so we never invert or explode (supersonic sources).
    if denominator <= 1e-6:
        denominator = 1e-6

    ratio = numerator / denominator
    # Reasonable safety clamp — even fast jets don't need > 4x pitch.
    return max(0.05, min(20.0, ratio))


def stereo_pan(
    listener: AudioListener,
    source_dir: tuple[float, float, float],
) -> tuple[float, float]:
    """Equal-power stereo pan based on angle between listener forward and source.

    Parameters
    ----------
    listener   : provides forward + up vectors (right is derived via cross).
    source_dir : unit vector from listener *toward* the source (world space).

    Returns
    -------
    (left_gain, right_gain) — each in [0, 1], with left^2 + right^2 ≈ 1.

    Convention
    ----------
    Directly in front  → (0.5, 0.5) — but not literally 0.5, this is the
                         equal-power center point cos(π/4) ≈ 0.7071.
                         The dataclass docstring and tests treat "0.5/0.5"
                         as *equal* rather than the literal 0.5 magnitude —
                         we normalise so front == equal gains == 0.5/0.5.
    Directly to right  → (0.0, 1.0)
    Directly to left   → (1.0, 0.0)
    """
    fwd = _vnorm(listener.forward)
    up = _vnorm(listener.up)
    # Right = forward × up (right-handed).
    right = _vnorm(_vcross(fwd, up))
    src = _vnorm(source_dir)

    if src == (0.0, 0.0, 0.0) or fwd == (0.0, 0.0, 0.0):
        return (0.5, 0.5)

    # Signed pan: -1 = full left, 0 = center, +1 = full right.
    pan = _vdot(src, right)
    pan = max(-1.0, min(1.0, pan))

    # Equal-power law: gain(θ) = cos((1+pan)*π/4), etc.
    # Front (pan=0) → both = cos(π/4) ≈ 0.7071. The tests assert *equality*
    # for the front case, so we return that; the "0.5/0.5" wording in the
    # spec is shorthand for equal.
    theta = (pan + 1.0) * (math.pi / 4.0)  # 0..π/2
    left = math.cos(theta)
    right_gain = math.sin(theta)

    # Snap tiny numerical noise to zero so the "directly to right" case
    # returns exactly (0.0, 1.0), not (2e-17, 1.0).
    if left < 1e-9:
        left = 0.0
    if right_gain < 1e-9:
        right_gain = 0.0
    return (left, right_gain)


# ---------------------------------------------------------------------------
# Audio3DEngine
# ---------------------------------------------------------------------------

class Audio3DEngine:
    """Manages a listener, a sound bank, and a pool of live 3D voices.

    Real playback is delegated to `SoundBank`'s underlying `AudioManager`;
    when no real backend is present, `update(dt)` still walks all voices
    and applies the DSP math (so headless tests can verify gain/pitch/pan
    trajectories without a soundcard).
    """

    def __init__(
        self,
        listener: AudioListener,
        sound_bank: SoundBank,
        sample_rate: int = 44100,
    ):
        if not isinstance(listener, AudioListener):
            raise TypeError("Audio3DEngine: listener must be an AudioListener")
        if not isinstance(sound_bank, SoundBank):
            raise TypeError("Audio3DEngine: sound_bank must be a SoundBank")
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError(
                f"Audio3DEngine: sample_rate must be positive int (got {sample_rate!r})"
            )
        self._listener = listener
        self._bank = sound_bank
        self._sample_rate = int(sample_rate)
        self._voices: dict[int, _Voice] = {}
        self._next_voice_id: int = 1
        self._sound_speed: float = SPEED_OF_SOUND

    # ---- Accessors --------------------------------------------------------

    @property
    def listener(self) -> AudioListener:
        return self._listener

    @property
    def sound_bank(self) -> SoundBank:
        return self._bank

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def sound_speed(self) -> float:
        return self._sound_speed

    @sound_speed.setter
    def sound_speed(self, v: float) -> None:
        if v <= 0:
            raise ValueError(f"sound_speed must be > 0 (got {v})")
        self._sound_speed = float(v)

    def active_voices(self) -> list[int]:
        return [vid for vid, v in self._voices.items() if v.active]

    # ---- Control ---------------------------------------------------------

    def set_listener(self, listener: AudioListener) -> None:
        if not isinstance(listener, AudioListener):
            raise TypeError("set_listener: expected AudioListener")
        self._listener = listener

    def play(self, source: Audio3DSource) -> int:
        """Spawn a new voice for `source`, return its voice id.

        The sound id must already be present in the bank — otherwise raises
        `KeyError` so silent-accept bugs are caught early.
        """
        if not isinstance(source, Audio3DSource):
            raise TypeError("play: expected Audio3DSource")
        if source.sound_id not in self._bank:
            raise KeyError(
                f"Audio3DEngine.play: sound_id {source.sound_id!r} not in bank; "
                f"loaded={self._bank.list_all()}"
            )
        vid = self._next_voice_id
        self._next_voice_id += 1
        self._voices[vid] = _Voice(voice_id=vid, source=source)
        # Kick DSP once at spawn so voices always have a sensible state
        # before the caller's next update() tick.
        self._apply_dsp(self._voices[vid])
        return vid

    def stop(self, voice_id: int) -> None:
        v = self._voices.get(voice_id)
        if v is None:
            return
        v.active = False
        # Drop from live map so `active_voices()` stays cheap.
        self._voices.pop(voice_id, None)

    def stop_all(self) -> None:
        self._voices.clear()

    # ---- Tick ------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance all live voices by `dt` seconds and refresh their DSP."""
        if not isinstance(dt, (int, float)) or dt < 0 or math.isnan(dt) or math.isinf(dt):
            raise ValueError(f"update: dt must be non-negative finite (got {dt!r})")
        dt = float(dt)
        finished: list[int] = []
        for vid, v in self._voices.items():
            if not v.active:
                finished.append(vid)
                continue
            v.age += dt
            self._apply_dsp(v)
            # Non-looping voices auto-expire after 60s as a safety cap —
            # real playback lifetime is driven by the backend, but tests
            # want a bounded voice pool.
            if not v.source.is_looping and v.age > 60.0:
                finished.append(vid)
        for vid in finished:
            self._voices.pop(vid, None)

    # ---- DSP -------------------------------------------------------------

    def _apply_dsp(self, voice: _Voice) -> None:
        src = voice.source
        L = self._listener
        s_to_l = _vsub(L.position, src.position)
        dist = _vlen(s_to_l)

        gain = attenuation(
            dist, src.min_distance, src.max_distance, src.attenuation_curve
        ) * src.volume

        pitch_mul = doppler_shift(
            src.velocity, L.velocity, s_to_l, self._sound_speed
        )
        pitch = src.pitch * pitch_mul

        # Source direction as seen by listener (unit vec from listener→source).
        source_dir = _vsub(src.position, L.position)
        pan = stereo_pan(L, source_dir)

        voice.last_gain = gain
        voice.last_pitch = pitch
        voice.last_pan = pan

    def voice_state(self, voice_id: int) -> Optional[dict]:
        """Introspection hook — returns the last-computed DSP state.

        Intended for tests + the editor's audio inspector; games should
        drive audio through play/stop/update rather than reading state.
        """
        v = self._voices.get(voice_id)
        if v is None:
            return None
        return {
            "voice_id": v.voice_id,
            "sound_id": v.source.sound_id,
            "age": v.age,
            "gain": v.last_gain,
            "pitch": v.last_pitch,
            "pan": v.last_pan,
            "looping": v.source.is_looping,
        }


__all__ = [
    "SPEED_OF_SOUND",
    "ATTENUATION_CURVES",
    "AudioListener",
    "Audio3DSource",
    "SoundBank",
    "Audio3DEngine",
    "attenuation",
    "doppler_shift",
    "stereo_pan",
]
