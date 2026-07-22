"""
Tests for :mod:`pharos_engine.capture`.

Covers the three backends (VideoCapture / GIFCapture / FrameDump), the
CaptureManager dispatcher (format detection, timing, progress callback),
CaptureResult population, single-frame ``capture_screenshot``, plus the
zero-frames edge case. Video-encoding tests soft-skip when neither
``imageio-ffmpeg`` nor a system ``ffmpeg`` binary is available.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import pytest

from pharos_engine import capture
from pharos_engine.capture import (
    CaptureManager,
    CaptureResult,
    FFMPEG_AVAILABLE,
    FrameDump,
    GIFCapture,
    VideoCapture,
    get_ffmpeg_executable,
)


# ---------------------------------------------------------------------------
# Fake renderer that ships an animated ramp
# ---------------------------------------------------------------------------
class _FakeRenderer:
    """Minimal stand-in for :class:`pharos_engine.render.NullRenderer`.

    Emits a solid colour that scrolls across frames so encoders have real
    inter-frame variation to work with.
    """

    def __init__(self, size: Tuple[int, int] = (16, 12)) -> None:
        self.window_size = size
        self._frame = 0
        self.begin_calls = 0
        self.end_calls = 0

    def begin_frame(self) -> None:
        self.begin_calls += 1

    def end_frame(self) -> None:
        self.end_calls += 1

    def read_pixels(self) -> np.ndarray:
        w, h = self.window_size
        img = np.zeros((h, w, 4), dtype=np.uint8)
        img[..., 0] = (self._frame * 20) % 256
        img[..., 1] = (self._frame * 13 + 40) % 256
        img[..., 2] = (self._frame * 7 + 80) % 256
        img[..., 3] = 255
        self._frame += 1
        return img


# ---------------------------------------------------------------------------
# 1. FrameDump
# ---------------------------------------------------------------------------
def test_frame_dump_writes_n_png_files(tmp_path: Path) -> None:
    r = _FakeRenderer((16, 12))
    mgr = CaptureManager()
    result = mgr.record(r, tmp_path / "dump", frames=5, fps=30)

    pngs = sorted(p.name for p in (tmp_path / "dump").glob("*.png"))
    assert len(pngs) == 5
    assert pngs[0] == "frame_00000.png"
    assert pngs[-1] == "frame_00004.png"
    assert result.frames_written == 5
    assert result.format == "frames"


def test_frame_dump_writes_valid_rgba_png(tmp_path: Path) -> None:
    from PIL import Image

    fd = FrameDump(tmp_path, resolution=(8, 6), fps=30)
    fd.begin()
    pixels = np.full((6, 8, 4), 200, dtype=np.uint8)
    fd.write_frame(pixels)
    fd.close()

    img = Image.open(tmp_path / "frame_00000.png")
    assert img.size == (8, 6)
    assert img.mode == "RGBA"


def test_frame_dump_manifest_written(tmp_path: Path) -> None:
    fd = FrameDump(tmp_path, resolution=(4, 4), fps=24)
    fd.begin()
    fd.write_frame(np.zeros((4, 4, 4), dtype=np.uint8))
    fd.close()
    manifest_text = (tmp_path / "manifest.txt").read_text(encoding="utf-8")
    assert "fps=24" in manifest_text
    assert "frames=1" in manifest_text


# ---------------------------------------------------------------------------
# 2. GIFCapture
# ---------------------------------------------------------------------------
def test_gif_capture_produces_valid_gif(tmp_path: Path) -> None:
    from PIL import Image

    out = tmp_path / "out.gif"
    gif = GIFCapture(out, resolution=(16, 12), fps=10)
    gif.begin()
    for i in range(4):
        pixels = np.zeros((12, 16, 4), dtype=np.uint8)
        pixels[..., i % 3] = 255
        pixels[..., 3] = 255
        gif.write_frame(pixels)
    gif.close()

    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "GIF"
        assert img.size == (16, 12)
        # Verify it's animated (has more than 1 frame)
        try:
            img.seek(3)
        except EOFError:
            pytest.fail("GIF was not animated (fewer than 4 frames)")


def test_gif_capture_via_manager_auto_detects(tmp_path: Path) -> None:
    r = _FakeRenderer((16, 12))
    mgr = CaptureManager()
    out = tmp_path / "clip.gif"
    result = mgr.record(r, out, frames=3, fps=15)

    assert result.format == "gif"
    assert result.frames_written == 3
    assert out.exists() and out.stat().st_size > 0


def test_gif_capture_high_fps_warns(tmp_path: Path) -> None:
    gif = GIFCapture(tmp_path / "fast.gif", resolution=(4, 4), fps=200)
    assert any("fps" in w for w in gif.warnings)


# ---------------------------------------------------------------------------
# 3. VideoCapture (soft-skip when ffmpeg is missing)
# ---------------------------------------------------------------------------
def test_video_capture_soft_skips_if_ffmpeg_missing() -> None:
    """The FFMPEG_AVAILABLE flag matches the ability to resolve a binary."""
    resolved = get_ffmpeg_executable()
    assert FFMPEG_AVAILABLE == (resolved is not None)
    # Whichever side of the split we're on, the assertion above must
    # match runtime behaviour. If ffmpeg is missing, VideoCapture.begin
    # must raise FFmpegNotFoundError.
    if not FFMPEG_AVAILABLE:
        vc = VideoCapture("nope.mp4", resolution=(4, 4), fps=30)
        with pytest.raises(capture.FFmpegNotFoundError):
            vc.begin()


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg backend unavailable")
def test_video_capture_writes_mp4(tmp_path: Path) -> None:
    out = tmp_path / "clip.mp4"
    vc = VideoCapture(out, resolution=(16, 12), fps=30, bitrate="1M")
    vc.begin()
    for _ in range(6):
        vc.write_frame(np.full((12, 16, 4), 128, dtype=np.uint8))
    vc.close()
    assert out.exists() and out.stat().st_size > 0
    assert vc.frames_written == 6


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg backend unavailable")
def test_video_capture_via_manager(tmp_path: Path) -> None:
    r = _FakeRenderer((16, 12))
    mgr = CaptureManager()
    out = tmp_path / "video.mp4"
    result = mgr.record(r, out, frames=6, fps=30, bitrate="1M")
    assert result.format == "mp4"
    assert result.frames_written == 6
    assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 4. CaptureManager auto-detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path, expected",
    [
        ("out.mp4", "video"),
        ("out.MOV", "video"),
        ("out.webm", "video"),
        ("out.gif", "gif"),
        ("dir/", "frames"),
        ("no_ext", "frames"),
        ("shot.png", "image"),
        ("shot.JPG", "image"),
    ],
)
def test_capture_manager_detect_format(path: str, expected: str) -> None:
    assert CaptureManager.detect_format(path) == expected


def test_capture_manager_detect_format_directory(tmp_path: Path) -> None:
    # An existing directory should be treated as frames regardless of
    # trailing separator.
    subdir = tmp_path / "shots"
    subdir.mkdir()
    assert CaptureManager.detect_format(subdir) == "frames"


def test_capture_manager_rejects_unknown_extension() -> None:
    with pytest.raises(ValueError):
        CaptureManager.detect_format("out.xyz")


def test_record_image_extension_rejected(tmp_path: Path) -> None:
    r = _FakeRenderer()
    mgr = CaptureManager()
    with pytest.raises(ValueError):
        mgr.record(r, tmp_path / "shot.png", frames=1)


# ---------------------------------------------------------------------------
# 5. Progress callback
# ---------------------------------------------------------------------------
def test_progress_callback_fires(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()
    log: List[Tuple[int, int]] = []
    mgr.record(
        r,
        tmp_path / "dump",
        frames=4,
        fps=15,
        on_frame_written=lambda n, total: log.append((n, total)),
    )
    assert log == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_progress_callback_exceptions_captured_as_warnings(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()

    def broken_cb(n: int, total: int) -> None:
        raise RuntimeError("boom")

    result = mgr.record(
        r,
        tmp_path / "dump",
        frames=2,
        fps=15,
        on_frame_written=broken_cb,
    )
    assert result.frames_written == 2
    assert any("boom" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 6. CaptureResult population
# ---------------------------------------------------------------------------
def test_capture_result_fields_populated(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()
    result = mgr.record(r, tmp_path / "dump", frames=3, fps=30)
    assert isinstance(result, CaptureResult)
    assert result.path == tmp_path / "dump"
    assert result.format == "frames"
    assert result.frames_written == 3
    assert result.wall_time_seconds >= 0.0
    assert result.avg_fps >= 0.0
    assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# 7. capture_screenshot
# ---------------------------------------------------------------------------
def test_capture_screenshot_writes_single_png(tmp_path: Path) -> None:
    from PIL import Image

    r = _FakeRenderer((16, 12))
    mgr = CaptureManager()
    out = tmp_path / "shot.png"
    result = mgr.capture_screenshot(r, out)

    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (16, 12)
        assert img.mode == "RGBA"
    assert result.frames_written == 1
    assert result.format == "png"


def test_capture_screenshot_writes_jpeg(tmp_path: Path) -> None:
    from PIL import Image

    r = _FakeRenderer((16, 12))
    mgr = CaptureManager()
    out = tmp_path / "shot.jpg"
    mgr.capture_screenshot(r, out)
    with Image.open(out) as img:
        # JPEG cannot carry alpha — screenshot converts to RGB.
        assert img.mode == "RGB"


def test_capture_screenshot_defaults_to_png(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()
    result = mgr.capture_screenshot(r, tmp_path / "no_ext")
    assert result.path.suffix == ".png"
    assert result.path.exists()


# ---------------------------------------------------------------------------
# 8. Zero-frames edge case
# ---------------------------------------------------------------------------
def test_zero_frames_does_not_crash(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()
    result = mgr.record(r, tmp_path / "dump", frames=0, fps=30)
    assert result.frames_written == 0
    assert result.wall_time_seconds >= 0.0
    # Directory should still exist (backend.begin() creates it).
    assert (tmp_path / "dump").exists()


def test_gif_zero_frames_writes_placeholder(tmp_path: Path) -> None:
    from PIL import Image

    out = tmp_path / "empty.gif"
    gif = GIFCapture(out, resolution=(4, 4), fps=10)
    gif.begin()
    gif.close()
    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "GIF"


# ---------------------------------------------------------------------------
# 9. Frame-shape / dtype validation
# ---------------------------------------------------------------------------
def test_write_frame_rejects_wrong_shape(tmp_path: Path) -> None:
    fd = FrameDump(tmp_path, resolution=(4, 4), fps=30)
    fd.begin()
    with pytest.raises(ValueError):
        fd.write_frame(np.zeros((3, 3), dtype=np.uint8))
    fd.close()


def test_write_frame_rejects_wrong_resolution(tmp_path: Path) -> None:
    fd = FrameDump(tmp_path, resolution=(4, 4), fps=30)
    fd.begin()
    with pytest.raises(ValueError):
        fd.write_frame(np.zeros((3, 5, 4), dtype=np.uint8))
    fd.close()


def test_write_frame_before_begin_raises(tmp_path: Path) -> None:
    fd = FrameDump(tmp_path, resolution=(4, 4), fps=30)
    with pytest.raises(RuntimeError):
        fd.write_frame(np.zeros((4, 4, 4), dtype=np.uint8))


# ---------------------------------------------------------------------------
# 10. Seconds -> frames conversion
# ---------------------------------------------------------------------------
def test_record_seconds_converts_to_frames(tmp_path: Path) -> None:
    r = _FakeRenderer((4, 4))
    mgr = CaptureManager()
    result = mgr.record(r, tmp_path / "dump", seconds=0.2, fps=30)
    # 0.2 * 30 = 6
    assert result.frames_written == 6


def test_record_rejects_missing_duration(tmp_path: Path) -> None:
    r = _FakeRenderer((4, 4))
    mgr = CaptureManager()
    with pytest.raises(ValueError):
        mgr.record(r, tmp_path / "dump")


def test_record_rejects_both_frames_and_seconds(tmp_path: Path) -> None:
    r = _FakeRenderer((4, 4))
    mgr = CaptureManager()
    with pytest.raises(ValueError):
        mgr.record(r, tmp_path / "dump", frames=3, seconds=0.1)


# ---------------------------------------------------------------------------
# 11. Renderer lifecycle plumbing
# ---------------------------------------------------------------------------
def test_record_drives_renderer_lifecycle(tmp_path: Path) -> None:
    r = _FakeRenderer((8, 6))
    mgr = CaptureManager()
    mgr.record(r, tmp_path / "dump", frames=4, fps=15)
    assert r.begin_calls == 4
    assert r.end_calls == 4


# ---------------------------------------------------------------------------
# 12. Context manager sugar
# ---------------------------------------------------------------------------
def test_context_manager_closes_backend(tmp_path: Path) -> None:
    with FrameDump(tmp_path, resolution=(4, 4), fps=30) as fd:
        assert fd.is_open
        fd.write_frame(np.zeros((4, 4, 4), dtype=np.uint8))
    assert not fd.is_open
    assert (tmp_path / "frame_00000.png").exists()


def test_gif_context_manager(tmp_path: Path) -> None:
    from PIL import Image

    out = tmp_path / "clip.gif"
    with GIFCapture(out, resolution=(4, 4), fps=10) as gif:
        gif.write_frame(np.full((4, 4, 4), 100, dtype=np.uint8))
        gif.write_frame(np.full((4, 4, 4), 200, dtype=np.uint8))
    with Image.open(out) as img:
        assert img.format == "GIF"


# ---------------------------------------------------------------------------
# 13. Public surface
# ---------------------------------------------------------------------------
def test_public_surface_matches_dunder_all() -> None:
    for name in capture.__all__:
        assert hasattr(capture, name), f"capture.{name} missing"
