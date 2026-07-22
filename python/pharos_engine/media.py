"""Unified frame-list capture helper.

This module exposes a single entry point, :func:`save_frames`, that picks
between MP4 and GIF based on the destination extension and falls back to
GIF transparently when no ffmpeg backend is available.

It is a thin dispatcher over the existing primitives:

* :func:`pharos_engine.tools.video.write_gif` for ``.gif``,
* :func:`pharos_engine.tools.video.write_mp4` for ``.mp4``,
* :func:`pharos_engine.tools.video.have_mp4_support` for detection.

For *streaming* (frame-by-frame) capture use
:class:`pharos_engine.physics.video.VideoWriter` directly. ``save_frames``
is for the buffered list-of-PIL-Images case which is what almost every
visual demo uses today.

Defaults (``fps``, ``quality``, ``loop``, ``palette_colors``) come from
``config/physics.yml`` under the ``media:`` section. The YAML lookup is
best-effort; if the file or the section is missing, sane built-in
defaults are used.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Sequence, Union

PathLike = Union[str, Path]

# Built-in defaults used when config/physics.yml is unavailable or has no
# ``media:`` section. Keep these in sync with the YAML values below.
_BUILTIN_DEFAULTS = {
    "fps": 30,
    "quality": 7,
    "loop": 0,
    "palette_colors": 128,
    "prefer_mp4": True,
}

_MP4_SUFFIXES = {".mp4", ".m4v", ".mov"}
_GIF_SUFFIXES = {".gif"}

FALLBACK_WARNING = (
    "ffmpeg not available - falling back to GIF. "
    "Install with: pip install imageio-ffmpeg "
    "(or system ffmpeg: winget install Gyan.FFmpeg / apt-get install ffmpeg)"
)


def _load_media_defaults() -> dict:
    """Best-effort load of ``media:`` section from config/physics.yml.

    Never raises. Returns the builtin defaults overlaid with whatever the
    YAML provides.
    """
    defaults = dict(_BUILTIN_DEFAULTS)
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:
        return defaults
    # Walk up from this file: python/pharos_engine/media.py -> repo root -> config/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "physics.yml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception:
                return defaults
            media_section = data.get("media") if isinstance(data, dict) else None
            if isinstance(media_section, dict):
                for key in defaults:
                    if key in media_section:
                        defaults[key] = media_section[key]
            return defaults
    return defaults


def have_ffmpeg() -> bool:
    """True iff an MP4 backend is currently importable.

    Mirrors :func:`pharos_engine.tools.video.have_mp4_support` but is the
    canonical entry point for ``media``-level callers.
    """
    from pharos_engine.tools.video import have_mp4_support
    return have_mp4_support()


def save_frames(
    frames: Sequence[object],
    path: PathLike,
    fps: float | None = None,
    *,
    quality: int | None = None,
    loop: int | None = None,
    palette_colors: int | None = None,
) -> Path:
    """Save ``frames`` to ``path``; pick MP4 vs GIF by file extension.

    Parameters
    ----------
    frames:
        A sequence of ``PIL.Image.Image`` instances. Must be non-empty.
    path:
        Destination file. Extension decides the backend:

        * ``.mp4`` / ``.m4v`` / ``.mov`` -> MP4 via imageio-ffmpeg.
          Falls back to GIF (with the extension rewritten to ``.gif``)
          and emits a :class:`RuntimeWarning` if ffmpeg is unavailable.
        * ``.gif`` -> animated GIF via PIL.
        * anything else -> treated as GIF (suffix coerced to ``.gif``).
    fps, quality, loop, palette_colors:
        Override the YAML defaults loaded from ``config/physics.yml``
        under ``media:``. ``quality`` applies only to MP4; ``loop`` and
        ``palette_colors`` apply only to GIF.

    Returns
    -------
    Path
        Absolute path of the written file (the final, possibly
        fallback-rewritten extension).
    """
    if not frames:
        raise ValueError("save_frames() requires at least one frame")

    cfg = _load_media_defaults()
    if fps is None:
        fps = float(cfg["fps"])
    if quality is None:
        quality = int(cfg["quality"])
    if loop is None:
        loop = int(cfg["loop"])
    if palette_colors is None:
        palette_colors = int(cfg["palette_colors"])

    dest = Path(path)
    suffix = dest.suffix.lower()

    wants_mp4 = suffix in _MP4_SUFFIXES
    if not wants_mp4 and suffix not in _GIF_SUFFIXES:
        # Unknown extension -> normalise to GIF, since that's the universal
        # fallback. We do *not* warn here; the user explicitly chose the
        # extension and we just clarify it.
        dest = dest.with_suffix(".gif")
        suffix = ".gif"

    if wants_mp4 and not have_ffmpeg():
        warnings.warn(FALLBACK_WARNING, RuntimeWarning, stacklevel=2)
        dest = dest.with_suffix(".gif")
        wants_mp4 = False

    if wants_mp4:
        from pharos_engine.tools.video import write_mp4
        return write_mp4(frames, dest, fps=fps, quality=quality)

    from pharos_engine.tools.video import write_gif
    return write_gif(
        frames,
        dest,
        fps=fps,
        loop=loop,
        colors=palette_colors,
    )


__all__ = ["save_frames", "have_ffmpeg", "FALLBACK_WARNING"]
