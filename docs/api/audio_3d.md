<!-- handauthored: do not regenerate -->
# slappyengine.audio_3d — API Reference

> Hand-written reference for the LL4 3D positional-audio surface.
> Adds attenuation, doppler pitch shift, and equal-power stereo
> panning on top of the 2D :mod:`slappyengine.audio` one-shot layer.
> Sibling references: [`audio_runtime.md`](audio_runtime.md) documents
> the sounddevice soft-import shim this module ultimately plays through;
> [`telemetry.md`](telemetry.md) is the recommended emitter for
> voice-start / voice-stop events.

## Overview

`slappyengine.audio_3d` is the Nova3D parity Sprint 17 landing (task
LL4). It gives games the vocabulary and DSP a 3D scene needs:

* :class:`AudioListener` — pose (`position`, `forward`, `up`) plus
  `velocity` used for doppler.
* :class:`Audio3DSource` — an emitter config carrying `sound_id`,
  `position`, `velocity`, `volume`, `pitch`, and a
  `min_distance` / `max_distance` band with an attenuation curve tag.
* :class:`SoundBank` — registry of loaded sound handles keyed by short
  string ids, wrapping `audio.AudioManager` for the load and
  registering stub handles when no soundfile backend is present.
* :class:`Audio3DEngine` — manages the listener, the bank, and a pool
  of live voices; runs DSP even when no backend is attached so
  headless tests can verify gain / pitch / pan trajectories.

Pure DSP helpers (:func:`attenuation`, :func:`doppler_shift`,
:func:`stereo_pan`) are exposed as stateless free functions so games,
tests, and offline mixers can call them directly. Sound speed defaults
to 343 m/s (dry air, ~20 °C, sea level) and can be overridden on the
engine (e.g. ~1480 m/s for underwater scenes).

## Public surface

```python
from slappyengine.audio_3d import (
    AudioListener, Audio3DSource,
    SoundBank, Audio3DEngine,
    attenuation, doppler_shift, stereo_pan,
    SPEED_OF_SOUND, ATTENUATION_CURVES,
)
```

## Classes

### `AudioListener`

_dataclass — defined in `slappyengine.audio_3d`_

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `position` | `tuple[float, float, float]` | `(0, 0, 0)` | World space. |
| `forward` | `tuple[float, float, float]` | `(0, 0, 1)` | Unit vector. |
| `up` | `tuple[float, float, float]` | `(0, 1, 0)` | Unit vector. |
| `velocity` | `tuple[float, float, float]` | `(0, 0, 0)` | For doppler. |

### `Audio3DSource`

_dataclass — defined in `slappyengine.audio_3d`_

Emitter *config*; does not track voice state (many voices can share
one source). Fields include `sound_id: str`, `position`, `velocity`,
`volume: float = 1.0`, `pitch: float = 1.0`, `min_distance: float = 1.0`,
`max_distance: float = 20.0`,
`attenuation_curve: str = "inverse"`, `is_looping: bool = False`.

### `SoundBank`

_class — defined in `slappyengine.audio_3d`_

```python
SoundBank(manager: audio.AudioManager | None = None)
```

- `load(name, path) -> object` — load a file and register under
  `name`. Falls back to a stub `{"_stub": True, "path": path}` handle
  and logs a warning when the underlying manager returns `None`.
- `register(name, handle) -> None` — direct-inject a pre-built handle.
- `get(name) -> object | None`
- `list_all() -> list[str]` — sorted registered names.
- Supports `name in bank` and `len(bank)`.

Raises `ValueError` when `name` or `path` is empty / non-str.

### `Audio3DEngine`

_class — defined in `slappyengine.audio_3d`_

```python
Audio3DEngine(
    listener: AudioListener,
    sound_bank: SoundBank,
    sample_rate: int = 44100,
)
```

Manages the listener, the bank, and a pool of live voices. Methods:

- `set_listener(listener)`
- `play(source) -> int` — spawn a voice, return its id. Raises
  `KeyError` when `source.sound_id` is not in the bank.
- `stop(voice_id)` / `stop_all()`
- `update(dt) -> None` — advance all voices by `dt` seconds and
  refresh their DSP; auto-expires non-looping voices after 60 s.
- `active_voices() -> list[int]`
- `voice_state(voice_id) -> dict | None` — inspection hook returning
  the last-computed `{gain, pitch, pan, age, sound_id, looping}`.
- Properties: `listener`, `sound_bank`, `sample_rate`, `sound_speed`
  (settable, must be `> 0`).

## Functions

### `attenuation(distance, min_dist, max_dist, curve="inverse") -> float`

_defined in `slappyengine.audio_3d`_

0..1 volume factor. Curves: `"linear"`, `"inverse"` (OpenAL
`AL_INVERSE_DISTANCE_CLAMPED`-ish), `"exponential"`. Full volume
inside `min_dist`; silent past `max_dist`. Raises `ValueError` on
negative distances, `max_dist <= min_dist`, or an unknown curve.

### `doppler_shift(source_vel, listener_vel, source_to_listener, sound_speed=SPEED_OF_SOUND) -> float`

_defined in `slappyengine.audio_3d`_

Classical `f' = f * (c - v_listener) / (c - v_source)` projected onto
the source→listener unit axis. Approaching → pitch > 1; receding →
pitch < 1. Clamped to `[0.05, 20.0]` for numerical safety. Raises
`ValueError` when `sound_speed <= 0`.

### `stereo_pan(listener, source_dir) -> tuple[left, right]`

_defined in `slappyengine.audio_3d`_

Equal-power stereo pan based on the angle between the listener's
forward vector and the source direction (right derived via
forward × up). Front → equal gains; hard right → `(0.0, 1.0)`;
hard left → `(1.0, 0.0)`.

## Constants

### `SPEED_OF_SOUND`

_float — defined in `slappyengine.audio_3d`_

Value: `343.0` (m/s). Default sound speed used by
:func:`doppler_shift`.

### `ATTENUATION_CURVES`

_tuple[str, ...] — defined in `slappyengine.audio_3d`_

Value: `("linear", "inverse", "exponential")`. Legal
`attenuation_curve` tags for :class:`Audio3DSource`.

## Usage

```python
from slappyengine.audio_3d import (
    AudioListener, Audio3DSource, SoundBank, Audio3DEngine,
)

listener = AudioListener(position=(0, 0, 0), forward=(0, 0, 1))
bank = SoundBank()
bank.register("shoot", handle={"_stub": True})   # or bank.load("shoot", ...)

engine = Audio3DEngine(listener, bank)
voice = engine.play(Audio3DSource(
    sound_id="shoot", position=(5, 0, 10), max_distance=50,
))
engine.update(1.0 / 60.0)

state = engine.voice_state(voice)
assert 0.0 <= state["gain"] <= 1.0
assert 0.05 <= state["pitch"] <= 20.0
```

## Skip the wrapper

`slappyengine.audio_3d` is Python-only. Grep of
`slappyengine._core_facade.RUST_MODULE_MAP` shows **no** `audio_3d`
entry — the DSP helpers are `math.sqrt` / `math.cos` scalars, and
`update()` walks at most a handful of live voices per frame. Rewriting
in Rust would not move any measurable frame-time needle.

Games that already own a lower-level audio pipeline (WWise, FMOD,
their own mixer) can bypass :class:`Audio3DEngine` entirely and call
:func:`attenuation`, :func:`doppler_shift`, :func:`stereo_pan` as
stateless DSP helpers on their own voice pool.

## See also

- [`audio_runtime.md`](audio_runtime.md) — sounddevice soft-import
  shim the underlying `AudioManager` plays through.
- [`telemetry.md`](telemetry.md) — recommended emitter for voice
  lifecycle events (`audio_3d.voice_started` etc.).
