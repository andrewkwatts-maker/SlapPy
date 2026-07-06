<!-- handauthored: do not regenerate -->
# slappyengine.capture — API Reference

> Hand-written reference for the LL2 capture subpackage.
> Records renderer output to MP4, GIF, or a per-frame PNG sequence with
> a single unified lifecycle. Sibling references:
> [`studio.md`](studio.md) uses this subpackage as the eventual home for
> its GIF writer; [`testing.md`](testing.md) points its visual
> regression harness at :class:`FrameDump` for baseline generation;
> [`gpu.md`](gpu.md) documents the renderer's `read_pixels` surface
> capture consumes.

## Overview

`slappyengine.capture` was promoted to the public engine surface for
Nova3D parity Sprint 15 so games, tutorials, and CI produce reproducible
video artefacts from any renderer exposing an HxWx4 `uint8`
`read_pixels()` return.

Every backend shares the same `begin() / write_frame(pixels) / close()`
lifecycle so tests and higher-level tools treat them uniformly. The
:class:`CaptureManager` is the ergonomic entry point — it auto-detects
the backend from the output filename extension.

FFmpeg is **soft-imported**. Missing binary raises a distinctive
:class:`FFmpegNotFoundError` so tests can `pytest.skip(...)` cleanly.
Cross-platform: on Windows, the subprocess is spawned with
`CREATE_NO_WINDOW` so batch pipelines never flash a console window.

## Public surface

```python
from slappyengine.capture import (
    CaptureManager, CaptureResult,
    VideoCapture, GIFCapture, FrameDump,
    FFmpegNotFoundError, FFMPEG_AVAILABLE, get_ffmpeg_executable,
)
```

## Classes

### `CaptureManager`

_class — defined in `slappyengine.capture.capture_manager`_

High-level `record(renderer, path, frames=180, fps=30, progress=None)`
API. Auto-selects the backend from the output extension:

| Extension | Backend | Dep |
|-----------|---------|-----|
| `.mp4` / `.mov` | :class:`VideoCapture` | FFmpeg |
| `.gif` | :class:`GIFCapture` | PIL |
| `.png` (directory) | :class:`FrameDump` | PIL |

Returns a :class:`CaptureResult` describing what was written.

### `CaptureResult`

_dataclass — defined in `slappyengine.capture.capture_manager`_

| Field | Type | Notes |
|-------|------|-------|
| `path` | `Path` | Written file or directory. |
| `frames_written` | `int` | May be `< frames` on early abort. |
| `duration_seconds` | `float` | `frames_written / fps`. |
| `backend` | `str` | `"video"` / `"gif"` / `"frame_dump"`. |
| `warnings` | `list[str]` | Non-fatal issues (e.g. dropped frames). |

### `VideoCapture`

_class — defined in `slappyengine.capture.video_capture`_

FFmpeg-backed MP4 / MOV writer.

```python
VideoCapture(
    path: str | Path,
    *,
    fps: int = 30,
    codec: str = "libx264",
    crf: int = 23,
    pix_fmt: str = "yuv420p",
)
```

Lifecycle: `begin(width, height)` -> `write_frame(pixels)` per frame ->
`close()`. Raises :class:`FFmpegNotFoundError` on `begin()` when no
FFmpeg binary is found.

### `GIFCapture`

_class — defined in `slappyengine.capture.gif_capture`_

Pure-PIL animated-GIF writer. Zero FFmpeg dependency.

```python
GIFCapture(
    path: str | Path,
    *,
    fps: int = 15,
    loop: int = 0,       # 0 = infinite
    optimize: bool = True,
)
```

### `FrameDump`

_class — defined in `slappyengine.capture.frame_dump`_

Per-frame PNG dump to a directory. Filenames are
`frame_{index:05d}.png`.

```python
FrameDump(
    directory: str | Path,
    *,
    prefix: str = "frame_",
    zero_pad: int = 5,
)
```

Used by the visual regression harness (`slappyengine.testing`) to
generate baseline frames.

### `FFmpegNotFoundError`

_exception — defined in `slappyengine.capture.video_capture`_

Raised by :class:`VideoCapture` when no FFmpeg binary is discoverable.
The message names both probe paths (`imageio-ffmpeg` and the system
`PATH`) so the failure is actionable.

## Functions

### `get_ffmpeg_executable() -> str | None`

_defined in `slappyengine.capture.video_capture`_

Resolve the FFmpeg binary path, checking `imageio-ffmpeg` first, then
the system `PATH`. Returns `None` when both fail — pair with
:data:`FFMPEG_AVAILABLE` for boolean checks.

## Constants

### `FFMPEG_AVAILABLE`

_bool — defined in `slappyengine.capture.video_capture`_

Value: `True` when :func:`get_ffmpeg_executable` resolves at import
time. Callers can gate feature detection on this without needing a
try/except.

## Usage

```python
from slappyengine.capture import CaptureManager
from slappyengine.render import NullRenderer

renderer = NullRenderer(width=320, height=240)
manager = CaptureManager()

# GIF — no FFmpeg required.
result = manager.record(renderer, "out/spin.gif", frames=60, fps=30)
assert result.frames_written == 60

# MP4 — soft-imports FFmpeg; skips cleanly when unavailable.
from slappyengine.capture import FFMPEG_AVAILABLE
if FFMPEG_AVAILABLE:
    manager.record(renderer, "out/spin.mp4", frames=60, fps=30)
```

## Skip the wrapper

`slappyengine.capture` is Python-only. There is **no** Rust equivalent
under `slappyengine._core`; the writers are thin lifecycle wrappers
around FFmpeg subprocess pipes and PIL's `Image.save`. Bypassing the
wrapper is only useful when you already own an FFmpeg / GStreamer /
NVENC pipeline and want to feed it your renderer's `read_pixels()`
output directly.

For MP4 specifically, callers can call `get_ffmpeg_executable()` and
build the subprocess pipe by hand — that path is exactly what
:class:`VideoCapture` does, minus the lifecycle guarantees.

## See also

- [`studio.md`](studio.md) — the demo-authoring sugar layer whose
  `record()` GIF writer will migrate to this subpackage.
- [`testing.md`](testing.md) — visual regression harness that generates
  baselines via :class:`FrameDump`.
- [`gpu.md`](gpu.md) — HH4 renderer whose `read_pixels()` output feeds
  every backend here.
- [`../video_output.md`](../video_output.md) — MP4 vs GIF trade-offs.
