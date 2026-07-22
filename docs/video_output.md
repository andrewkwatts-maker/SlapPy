# Video Output (MP4 vs GIF)

Pharos Engine's showcase and capture tools emit MP4 by default and fall back to
GIF when an ffmpeg backend cannot be located. MP4 is strongly preferred:
files are roughly an order of magnitude smaller for the same length, playback
is smoother, and you get true 24-bit colour instead of GIF's 8-bit (256-entry)
palette - which means no dithering artefacts on gradients, fog, or lighting.

## Install

The recommended path is the vendored ffmpeg binary that ships with
`imageio-ffmpeg` (no PATH setup, no system package manager):

```
pip install imageio-ffmpeg
```

This is a single ~25 MB wheel that bundles a static ffmpeg build for your
platform. After install, MP4 emission "just works" - no further configuration.

### Alternative: system ffmpeg

If you already have ffmpeg installed system-wide and it's on `PATH`,
`VideoWriter` will detect and use it without needing the Python wheel:

- macOS: `brew install ffmpeg`
- Debian/Ubuntu: `sudo apt install ffmpeg`
- Windows: download a static build from <https://www.gyan.dev/ffmpeg/builds/>
  and add the `bin\` directory to your `PATH`.

Verify it's on PATH with `ffmpeg -version`.

## Verify

```
python -c "from pharos_engine.physics.video import VideoWriter; print(VideoWriter.ffmpeg_available())"
```

Prints `True` if MP4 emission is available, `False` if `VideoWriter` will
fall back to GIF. For more detail:

```
python -c "from pharos_engine.physics.video import VideoWriter; print(VideoWriter.ffmpeg_source())"
```

Prints `imageio_ffmpeg`, `system`, or `None`.

## Usage

```python
from pharos_engine.physics.video import VideoWriter

with VideoWriter("out/showcase.mp4", fps=60) as vw:
    for frame in render_frames():
        vw.append(frame)  # frame is an HxWx3 (or HxWx4) ndarray
```

If ffmpeg is unavailable the writer rewrites the extension to `.gif` and
emits a `RuntimeWarning` that includes the install hint.

## Buffered API: `pharos_engine.media.save_frames`

For visual demos that build a Python list of `PIL.Image` frames and then
flush them in one shot, prefer the buffered helper:

```python
from pharos_engine.media import save_frames

# Pick MP4 vs GIF purely from the extension.  Falls back to .gif (with
# a RuntimeWarning) when ffmpeg is missing.
save_frames(pil_frames, "out/demo.mp4", fps=30)   # MP4 if available
save_frames(pil_frames, "out/demo.gif", fps=30)   # always GIF, never warns
```

`save_frames` is a thin dispatcher over `pharos_engine.tools.video.write_gif`
and `write_mp4`.  Numeric defaults (`fps`, `quality`, GIF `loop`,
`palette_colors`) come from the `media:` section of `config/physics.yml`:

```yaml
media:
  fps: 30
  quality: 7
  loop: 0
  palette_colors: 128
  prefer_mp4: true
```

### Installing ffmpeg

The recommended path is the vendored binary:

```
pip install imageio-ffmpeg
```

Alternatives if you prefer a system install:

- Windows: `winget install Gyan.FFmpeg`
  (or download a static build from <https://www.gyan.dev/ffmpeg/builds/>
  and add `bin\` to `PATH`)
- macOS: `brew install ffmpeg`
- Debian / Ubuntu: `sudo apt-get install ffmpeg`

Verify availability:

```python
from pharos_engine.media import have_ffmpeg
print(have_ffmpeg())   # True iff MP4 emission will work
```

## Troubleshooting

**The output is still a GIF after I installed `imageio-ffmpeg`.**
You're probably using a different Python interpreter than the one you
installed into. Check with:

```
python -c "import sys; print(sys.executable)"
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.__file__)"
```

Both should point to the same environment.

**MP4 plays in VLC but not in browsers.**
The default codec is `libx264`, which is universally supported.  If you
overrode the codec via `VideoWriter(codec=...)`, switch back to `libx264`
and use a `.mp4` extension.

**Frame rate is wrong / playback too fast or slow.**
The `fps` argument to `VideoWriter` must match the rate at which you
`append()` frames. The writer does no resampling.

**Output format / codec params.**
`VideoWriter` exposes `codec` (default `libx264`) and `quality` (0-10, default
8 - higher is better quality but larger files).  For more advanced ffmpeg
parameters, drop down to `imageio.get_writer` directly.

**Auto-install during a script.**
For one-off scripts you can pass `try_install_ffmpeg=True` to attempt
`pip install imageio-ffmpeg` on first use. This is off by default to avoid
surprise installs in shared / CI environments.
