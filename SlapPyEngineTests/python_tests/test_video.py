"""Tests for :mod:`slappyengine.physics.video`.

Detection-path only - we never actually attempt to pip install during tests.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

import pytest

# Make sure the in-tree package is importable when tests are run from repo root.
_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_DIR))

from slappyengine.physics import video as video_mod  # noqa: E402
from slappyengine.physics.video import (  # noqa: E402
    FALLBACK_WARNING,
    INSTALL_HINT,
    VideoWriter,
)


def test_ffmpeg_available_detection_works() -> None:
    """``ffmpeg_available`` must return a bool and not raise."""
    result = VideoWriter.ffmpeg_available()
    assert isinstance(result, bool)


def test_ffmpeg_source_returns_known_value() -> None:
    """``ffmpeg_source`` must return one of the documented values."""
    src = VideoWriter.ffmpeg_source()
    assert src in {None, "imageio_ffmpeg", "system"}
    # Source presence must agree with the boolean detector.
    assert (src is not None) == VideoWriter.ffmpeg_available()


def test_install_hint_text() -> None:
    """Sanity: the published install hint stays the canonical pip command."""
    assert INSTALL_HINT == "pip install imageio-ffmpeg"
    assert "pip install imageio-ffmpeg" in FALLBACK_WARNING


def test_fallback_message_includes_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ffmpeg is missing and MP4 is requested, the warning must include the pip command."""
    # Force "ffmpeg unavailable" regardless of host environment.
    monkeypatch.setattr(VideoWriter, "ffmpeg_available", classmethod(lambda cls: False))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        vw = VideoWriter(tmp_path / "out.mp4")
        # Close without writing - we only care about the construction warning.
        vw.close()

    # Exactly one RuntimeWarning, and it must include the pip command.
    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime, f"expected RuntimeWarning, got {[w.category for w in caught]}"
    msg = str(runtime[0].message)
    assert "pip install imageio-ffmpeg" in msg
    assert "ffmpeg" in msg.lower()

    # Path must have been rewritten to .gif.
    assert vw.path.suffix == ".gif"


def test_no_warning_when_gif_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking for a .gif directly should never emit the fallback warning."""
    monkeypatch.setattr(VideoWriter, "ffmpeg_available", classmethod(lambda cls: False))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        vw = VideoWriter(tmp_path / "out.gif")
        vw.close()

    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not runtime, f"unexpected warnings: {[str(w.message) for w in runtime]}"
    assert vw.path.suffix == ".gif"


def test_mp4_kept_when_ffmpeg_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ffmpeg is reported available, the .mp4 extension must be preserved."""
    monkeypatch.setattr(VideoWriter, "ffmpeg_available", classmethod(lambda cls: True))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        vw = VideoWriter(tmp_path / "out.mp4")
        vw.close()

    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not runtime
    assert vw.path.suffix == ".mp4"


def test_try_install_flag_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """``try_install_ffmpeg`` must be False by default - no surprise pip calls."""
    called = {"n": 0}

    def boom() -> bool:
        called["n"] += 1
        return False

    monkeypatch.setattr(video_mod.VideoWriter, "_attempt_install", staticmethod(boom))
    monkeypatch.setattr(VideoWriter, "ffmpeg_available", classmethod(lambda cls: False))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        VideoWriter(os.devnull + ".gif")  # default flag

    assert called["n"] == 0, "VideoWriter must not attempt install by default"
