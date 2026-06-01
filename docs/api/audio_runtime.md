<!-- handauthored: do not regenerate -->
# slappyengine.audio_runtime — API Reference

> Hand-written reference for the audio backend plumbing.
> `audio_runtime` is the soft-import shim that decouples
> `slappyengine.audio` from `sounddevice`. Games and the editor should
> keep using `slappyengine.audio` (`AudioManager`, `SoundHandle`); this
> module is the layer that lets that high-level API stay importable on
> machines without PortAudio installed. Landed in Phase C2 as the
> Bullet Strata unblock — see
> [`project_phase_b_repackage.md`](../sprint_5_doc_inventory.md) for the
> sprint context.

```python
from slappyengine.audio_runtime import (
    AudioBackend,         # Protocol
    get_backend,          # module accessor
)
```

Public surface is intentionally tiny: a `Protocol`, a getter, and the
two concrete backends that implement the protocol. The module is
**internal plumbing** — none of the names are re-exported at the
package root.

## Backend selection

A single, process-wide backend is selected at module import time by
`_init_backend()`:

```python
def _init_backend() -> AudioBackend:
    try:
        import sounddevice as sd
    except Exception:
        _LOG.warning(_STUB_WARNING)
        return _StubBackend()
    return _RealBackend(sd)
```

- The `try` block uses bare `except Exception`, not `except
  ImportError`, on purpose: a broken install can fail at import time
  with `OSError` when PortAudio's DLL is missing, and that path must
  also fall back to the stub.
- The warning fires exactly once per process (import-time only), with
  the canonical string:

  > `sounddevice not installed; audio playback is a no-op stub.
  > Install slappy-engine[audio] to enable sound.`

  This makes "we shipped muted" visible in CI logs without breaking
  the import.
- The selected backend is cached at module scope (`_BACKEND`). Calling
  `get_backend()` is a constant-time lookup; the backend is **not**
  re-detected if `sounddevice` later becomes available.

## AudioBackend protocol

```python
class AudioBackend(Protocol):
    def play_buffer(self, samples: np.ndarray, sample_rate: int) -> None: ...
    def stop_all(self) -> None: ...
    def is_real(self) -> bool: ...
```

The contract is deliberately narrow — sample-rate negotiation,
device selection, and channel mapping are **the backend's problem**,
not the protocol's. Callers ship a `(N,)` or `(N, channels)` float32
array and a sample rate; both backends accept what they get.

`is_real()` is the public introspection hook used by
`AudioManager.__init__` to decide whether `AudioManager.available`
should advertise itself as `True`. Stub backend ⇒ `available == False`
⇒ downstream game systems that gate on `audio.available` (e.g. spawn
calls) silently skip their audio side-effect rather than raising.

## `_RealBackend(sd)`

Thin wrapper around `sounddevice`'s module-level functions.

- `play_buffer(samples, sample_rate)` → `sd.play(samples, sample_rate)`,
  swallowing every exception. `sounddevice` raises at runtime when the
  device sample rate disagrees with the buffer's, when the default
  device disappears mid-frame (e.g. headphones unplugged), or when
  PortAudio's stream is in a bad state — none of those should crash
  the game loop.
- `stop_all()` → `sd.stop()`, same swallow.
- `is_real()` → `True`.

Device enumeration is **not** part of the protocol. If you need it
for an in-game settings menu, import `sounddevice` directly and call
`sounddevice.query_devices()` — the backend deliberately does not
expose this so the stub stays trivially implementable.

## `_StubBackend()`

Three-method no-op. Every method returns `None`; `is_real()` returns
`False`. There are no allocations, no logging on a per-call basis,
and no I/O — the stub is a zero-overhead path so it is safe to leave
audio calls in tight loops on a machine without PortAudio.

## `get_backend() -> AudioBackend`

The only public entry point. Returns the process-wide cached
backend. `AudioManager` (in `slappyengine.audio`) calls this on every
`play` / `play_spatial` / `stop_all` so test harnesses that monkey-
patch `_BACKEND` (e.g. `audio_runtime._BACKEND = MyFakeBackend()`)
take effect for the *next* manager call without rebuilding the
manager. The module-level `play_sound(handle, sample_rate=None)`
helper in `slappyengine.audio` uses the same hook for raw-buffer
playback without instantiating a manager.

## Sample-rate negotiation

There is **none**. The backend forwards whatever sample rate the
caller passes (`SoundHandle.samplerate`, which comes from
`soundfile.read()` — i.e. the file's native rate). `sounddevice` /
PortAudio handle device-side resampling when the requested rate
doesn't match the OS default; if that resampling fails at runtime,
the `try/except Exception` in `_RealBackend.play_buffer` swallows it
and the buffer is silently dropped. This is the same soft-failure
contract as `sd.play` itself — the game keeps running, the sound
doesn't.

If a caller needs exact-rate playback they should resample on the
host side before calling `play_buffer` (e.g. via `librosa.resample`
or a `scipy.signal.resample` call) — the protocol does not provide a
preferred-rate query because the stub has no preference and
exposing one would split the interface.

## Inner module surface

- `slappyengine.audio_runtime.AudioBackend` — the public protocol.
- `slappyengine.audio_runtime.get_backend` — the public accessor.
- `slappyengine.audio_runtime._RealBackend` /
  `_StubBackend` — concrete implementations; underscore-prefixed so
  the underscore communicates "use `get_backend()`, do not
  instantiate directly".
- `slappyengine.audio_runtime._BACKEND` — module-level singleton;
  test harnesses may rebind this for fake-backend injection.
- `slappyengine.audio_runtime._STUB_WARNING` — the canonical warning
  string; pinned by `tests/test_audio_stub.py`.
