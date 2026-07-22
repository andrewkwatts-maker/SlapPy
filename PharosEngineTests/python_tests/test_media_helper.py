"""Tests for :mod:`pharos_engine.media`.

Verifies the dispatcher chooses MP4 vs GIF based on extension and that
the MP4 path falls back to GIF cleanly when ffmpeg is unavailable.

Detection-only - we never actually invoke ffmpeg; the underlying
write_gif / write_mp4 calls are monkeypatched to record their args.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

# Ensure the in-tree package is importable when run from repo root.
_PYTHON_DIR = Path(__file__).resolve().parents[1]
if str(_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_DIR))

from pharos_engine import media as media_mod  # noqa: E402
from pharos_engine.media import (  # noqa: E402
    FALLBACK_WARNING,
    have_ffmpeg,
    save_frames,
)


class _FakeFrame:
    """Stand-in for a PIL.Image; identity is all that matters here."""


def _patch_writers(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace tools.video.write_gif / write_mp4 with recording stubs."""
    calls: dict = {"gif": [], "mp4": []}

    def fake_write_gif(frames, out_path, **kwargs):
        calls["gif"].append({"path": Path(out_path), "kwargs": dict(kwargs)})
        return Path(out_path).resolve()

    def fake_write_mp4(frames, out_path, **kwargs):
        calls["mp4"].append({"path": Path(out_path), "kwargs": dict(kwargs)})
        return Path(out_path).resolve()

    import pharos_engine.tools.video as tv
    monkeypatch.setattr(tv, "write_gif", fake_write_gif)
    monkeypatch.setattr(tv, "write_mp4", fake_write_mp4)
    return calls


def test_have_ffmpeg_returns_bool() -> None:
    assert isinstance(have_ffmpeg(), bool)


def test_gif_extension_routes_to_write_gif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    # ffmpeg presence is irrelevant for .gif - simulate "absent" to be strict.
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = save_frames([_FakeFrame()], tmp_path / "demo.gif")

    assert calls["mp4"] == []
    assert len(calls["gif"]) == 1
    assert calls["gif"][0]["path"].suffix == ".gif"
    assert out.suffix == ".gif"
    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not runtime, "GIF requests must never emit the fallback warning"


def test_mp4_extension_routes_to_write_mp4_when_ffmpeg_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = save_frames([_FakeFrame()], tmp_path / "demo.mp4")

    assert calls["gif"] == []
    assert len(calls["mp4"]) == 1
    assert calls["mp4"][0]["path"].suffix == ".mp4"
    assert out.suffix == ".mp4"
    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not runtime


def test_mp4_falls_back_to_gif_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = save_frames([_FakeFrame()], tmp_path / "demo.mp4")

    # Routed to GIF, never MP4.
    assert calls["mp4"] == []
    assert len(calls["gif"]) == 1
    assert calls["gif"][0]["path"].suffix == ".gif"
    assert out.suffix == ".gif"

    runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime, "fallback path must emit a RuntimeWarning"
    msg = str(runtime[0].message)
    assert "ffmpeg" in msg.lower()
    assert "pip install imageio-ffmpeg" in msg
    assert msg == FALLBACK_WARNING


def test_unknown_extension_coerced_to_gif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: True)

    out = save_frames([_FakeFrame()], tmp_path / "demo.wat")

    assert calls["mp4"] == []
    assert len(calls["gif"]) == 1
    assert out.suffix == ".gif"


def test_empty_frames_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_frames([], tmp_path / "demo.gif")


def test_kwargs_forwarded_to_gif_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: False)

    save_frames(
        [_FakeFrame()],
        tmp_path / "demo.gif",
        fps=60,
        loop=3,
        palette_colors=64,
    )

    kwargs = calls["gif"][0]["kwargs"]
    assert kwargs.get("fps") == 60
    assert kwargs.get("loop") == 3
    assert kwargs.get("colors") == 64


def test_kwargs_forwarded_to_mp4_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_writers(monkeypatch)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: True)

    save_frames([_FakeFrame()], tmp_path / "demo.mp4", fps=24, quality=9)

    kwargs = calls["mp4"][0]["kwargs"]
    assert kwargs.get("fps") == 24
    assert kwargs.get("quality") == 9


def test_yaml_defaults_loaded_when_no_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user passes no kwargs, defaults must come from physics.yml."""
    captured = {}

    def fake_load_defaults():
        return {
            "fps": 42,
            "quality": 3,
            "loop": 2,
            "palette_colors": 99,
            "prefer_mp4": True,
        }

    monkeypatch.setattr(media_mod, "_load_media_defaults", fake_load_defaults)

    def fake_write_gif(frames, out_path, **kwargs):
        captured.update(kwargs)
        captured["path"] = Path(out_path)
        return Path(out_path)

    import pharos_engine.tools.video as tv
    monkeypatch.setattr(tv, "write_gif", fake_write_gif)
    monkeypatch.setattr(media_mod, "have_ffmpeg", lambda: False)

    save_frames([_FakeFrame()], Path("ignored.gif"))

    assert captured.get("fps") == 42
    assert captured.get("loop") == 2
    assert captured.get("colors") == 99
