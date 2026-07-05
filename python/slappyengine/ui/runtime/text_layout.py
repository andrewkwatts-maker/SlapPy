"""Text metrics + wrapping — PIL when available, cheap fallback otherwise.

The runtime UI needs to answer two questions at layout time:

1. How wide is this string in pixels? (:func:`measure_text`)
2. How do I break it across lines to fit into ``max_width``? (:func:`wrap_text`)

Both functions try PIL's ``ImageFont.load_default()`` first for accurate
metrics; if PIL is missing (or the load fails on a stripped wheel) we
fall back to a fast heuristic that assumes every glyph is
``font_size * 0.6`` wide. That's off by a couple of pixels on a real
proportional font but stays stable enough for HUD layouts.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# PIL soft-import — cached so we don't pay the try/except on every call.
# ---------------------------------------------------------------------------


_PIL_CACHE: dict[str, Any] = {"tried": False, "module": None}


def _pil_font_module():
    """Return the PIL ``ImageFont`` module, or ``None`` when unavailable."""
    if _PIL_CACHE["tried"]:
        return _PIL_CACHE["module"]
    _PIL_CACHE["tried"] = True
    try:
        from PIL import ImageFont  # type: ignore[import-not-found]
        _PIL_CACHE["module"] = ImageFont
    except Exception:  # pragma: no cover - defensive
        _PIL_CACHE["module"] = None
    return _PIL_CACHE["module"]


_FONT_CACHE: dict[int, Any] = {}


def _load_font(size: int) -> Any | None:
    """Return a ``PIL.ImageFont`` instance for *size*, or ``None`` on failure."""
    module = _pil_font_module()
    if module is None:
        return None
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        # PIL 10.x: load_default accepts a size kwarg. Older PIL ignores
        # it and returns the 8-pixel bitmap font — still usable, just
        # slightly less accurate.
        try:
            font = module.load_default(size=size)
        except TypeError:  # pragma: no cover - old PIL
            font = module.load_default()
    except Exception:  # pragma: no cover - defensive
        return None
    _FONT_CACHE[size] = font
    return font


# ---------------------------------------------------------------------------
# Fallback constants
# ---------------------------------------------------------------------------

_FALLBACK_WIDTH_RATIO: float = 0.6


def measure_text(text: str, font_size: int) -> tuple[float, float]:
    """Return the pixel ``(width, height)`` of *text* at *font_size*.

    Uses PIL when available (accurate glyph advance widths); falls back
    to ``len(text) * font_size * 0.6`` and ``font_size`` for height when
    PIL is missing.

    Both fields are always > 0 for non-empty text; empty text returns
    ``(0.0, font_size)`` so callers can vertically-align an empty line
    the same as a non-empty one.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"measure_text: text must be str; got {type(text).__name__}"
        )
    if not isinstance(font_size, int) or font_size <= 0:
        raise ValueError(
            f"measure_text: font_size must be a positive int; got {font_size!r}"
        )
    if text == "":
        return (0.0, float(font_size))

    font = _load_font(font_size)
    if font is not None:
        # PIL 10.x: getbbox returns (left, top, right, bottom).
        try:
            bbox = font.getbbox(text)
            width = float(bbox[2] - bbox[0])
            height = float(bbox[3] - bbox[1])
            if width > 0 and height > 0:
                return (width, height)
        except Exception:  # pragma: no cover - defensive
            pass
        # Older PIL fall-through: getsize.
        try:
            w, h = font.getsize(text)  # type: ignore[attr-defined]
            if w > 0 and h > 0:
                return (float(w), float(h))
        except Exception:  # pragma: no cover - defensive
            pass

    width = float(len(text)) * float(font_size) * _FALLBACK_WIDTH_RATIO
    height = float(font_size)
    return (width, height)


def wrap_text(text: str, max_width: float, font_size: int) -> list[str]:
    """Split *text* into lines whose measured width is <= *max_width*.

    Words that individually exceed ``max_width`` are placed on their own
    line (no mid-word breaking — keeps the wrapper cheap and predictable).
    Existing ``\\n`` sequences in *text* are treated as hard breaks and
    always start a new line.

    Returns an empty list for empty *text* so callers can iterate the
    result without a special case.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"wrap_text: text must be str; got {type(text).__name__}"
        )
    if not isinstance(font_size, int) or font_size <= 0:
        raise ValueError(
            f"wrap_text: font_size must be a positive int; got {font_size!r}"
        )
    if max_width <= 0:
        raise ValueError(
            f"wrap_text: max_width must be > 0; got {max_width!r}"
        )
    if text == "":
        return []

    lines: list[str] = []
    for hard_line in text.split("\n"):
        if hard_line == "":
            lines.append("")
            continue
        current: list[str] = []
        current_w: float = 0.0
        space_w, _ = measure_text(" ", font_size)
        for word in hard_line.split(" "):
            word_w, _ = measure_text(word, font_size)
            if not current:
                # First word of the line — always accepted, even if it
                # overflows max_width (better than losing it entirely).
                current.append(word)
                current_w = word_w
                continue
            projected = current_w + space_w + word_w
            if projected <= max_width:
                current.append(word)
                current_w = projected
            else:
                lines.append(" ".join(current))
                current = [word]
                current_w = word_w
        if current:
            lines.append(" ".join(current))
    return lines


__all__ = ["measure_text", "wrap_text"]
