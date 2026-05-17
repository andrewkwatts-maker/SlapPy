"""HUD widget drawing helpers — PIL-based, engine-side utilities.

These functions operate on a :class:`PIL.ImageDraw.ImageDraw` context so they
can be called from any :class:`~SlapPyEngine.ui.scene_ui.SceneUIEntity`
``_render`` method without duplicating bar-drawing arithmetic across games.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import ImageDraw as _ImageDrawModule

    ImageDraw = _ImageDrawModule.ImageDraw


def draw_stat_bar(
    draw: "ImageDraw",
    x: int,
    y: int,
    w: int,
    h: int,
    value: float,
    max_value: float,
    fill_color: tuple = (220, 60, 60),
    bg_color: tuple = (40, 40, 40),
    label: str = "",
    label_color: tuple = (255, 255, 255),
) -> None:
    """Draw a filled stat bar (HP, energy, armour, etc.) onto a PIL ImageDraw.

    The bar is drawn left-to-right; ``value / max_value`` determines fill width.
    An optional short ``label`` (e.g. ``"HP"``, ``"EN"``) is rendered left-aligned
    inside the bar.

    Args:
        draw: Active :class:`PIL.ImageDraw.ImageDraw` surface.
        x: Left edge of the bar in image-local pixels.
        y: Top edge of the bar in image-local pixels.
        w: Total width of the bar in pixels.
        h: Height of the bar in pixels.
        value: Current value (may be float).
        max_value: Maximum value; if 0 the fill ratio is treated as 0.
        fill_color: RGB or RGBA tuple for the filled portion.
        bg_color: RGB or RGBA tuple for the empty background.
        label: Short text drawn inside the bar (empty → no text).
        label_color: RGB or RGBA tuple for the label text.

    Example::

        from slappyengine.ui.hud_widgets import draw_stat_bar
        draw_stat_bar(draw, x=20, y=10, w=200, h=16,
                      value=player.hp, max_value=100,
                      fill_color=(220, 60, 60), label="HP")
    """
    ratio: float = max(0.0, min(1.0, value / max_value)) if max_value > 0 else 0.0

    # Background
    draw.rectangle([x, y, x + w, y + h], fill=bg_color)

    # Filled portion
    if ratio > 0:
        draw.rectangle([x, y, x + int(w * ratio), y + h], fill=fill_color)

    # Label
    if label:
        text_y = y + max(0, (h - 12) // 2)
        draw.text((x + 4, text_y), label, fill=label_color)
