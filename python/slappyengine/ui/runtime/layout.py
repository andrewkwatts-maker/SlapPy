"""Layout helpers — stack / grid / anchors.

Layouts here operate on **items**: any object with a ``.position``
attribute (2-tuple) and a ``.size`` attribute (2-tuple) that the helper
is allowed to mutate. The runtime UI widgets don't return item objects
directly — they take positions inline — so callers typically use these
helpers on ad-hoc dataclasses that they hand to widgets afterwards::

    from dataclasses import dataclass, field

    @dataclass
    class Item:
        position: tuple[float, float] = (0.0, 0.0)
        size: tuple[float, float] = (100.0, 24.0)

    items = [Item() for _ in range(3)]
    stack_vertical(items, spacing=6.0)
    for i, item in enumerate(items):
        ui.button(f"btn_{i}", "Click", item.position, item.size)

The anchor helpers are frame-of-reference constructors — they return a
callable that maps ``(screen_w, screen_h) → (x, y)`` so a HUD can be
built once and stay pinned to a corner as the window resizes.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence


AnchorFn = Callable[[float, float], tuple[float, float]]


def _has_pos_size(item: Any) -> bool:
    return hasattr(item, "position") and hasattr(item, "size")


def stack_vertical(items: Sequence[Any], spacing: float = 4.0) -> None:
    """Stack *items* vertically, mutating each ``.position`` in place.

    The first item keeps its incoming ``.position``; each subsequent item
    is placed directly below the previous one at the same x-coordinate,
    with *spacing* pixels of gap.
    """
    if spacing < 0:
        raise ValueError(f"stack_vertical: spacing must be >= 0; got {spacing!r}")
    if not items:
        return
    first = items[0]
    if not _has_pos_size(first):
        raise TypeError(
            "stack_vertical: items must expose .position and .size; "
            f"first item {type(first).__name__} does not"
        )
    x, y = float(first.position[0]), float(first.position[1])
    cursor_y = y
    for i, item in enumerate(items):
        if not _has_pos_size(item):
            raise TypeError(
                f"stack_vertical: items[{i}] must expose .position and .size"
            )
        item.position = (x, cursor_y)
        cursor_y += float(item.size[1]) + float(spacing)


def stack_horizontal(items: Sequence[Any], spacing: float = 4.0) -> None:
    """Stack *items* horizontally, mutating each ``.position`` in place."""
    if spacing < 0:
        raise ValueError(f"stack_horizontal: spacing must be >= 0; got {spacing!r}")
    if not items:
        return
    first = items[0]
    if not _has_pos_size(first):
        raise TypeError(
            "stack_horizontal: items must expose .position and .size; "
            f"first item {type(first).__name__} does not"
        )
    x, y = float(first.position[0]), float(first.position[1])
    cursor_x = x
    for i, item in enumerate(items):
        if not _has_pos_size(item):
            raise TypeError(
                f"stack_horizontal: items[{i}] must expose .position and .size"
            )
        item.position = (cursor_x, y)
        cursor_x += float(item.size[0]) + float(spacing)


def grid(
    cols: int,
    items: Sequence[Any],
    spacing_x: float = 4.0,
    spacing_y: float = 4.0,
) -> None:
    """Arrange *items* into a ``cols``-wide grid; mutates ``.position``.

    The grid origin is taken from ``items[0].position``. Row height is
    computed per-row as the max ``size[1]`` in that row, so mixed-height
    items stay aligned without overlap.
    """
    if not isinstance(cols, int) or cols <= 0:
        raise ValueError(f"grid: cols must be a positive int; got {cols!r}")
    if spacing_x < 0 or spacing_y < 0:
        raise ValueError(
            "grid: spacing_x/spacing_y must be >= 0; "
            f"got spacing_x={spacing_x!r} spacing_y={spacing_y!r}"
        )
    if not items:
        return
    first = items[0]
    if not _has_pos_size(first):
        raise TypeError(
            "grid: items must expose .position and .size; "
            f"first item {type(first).__name__} does not"
        )
    origin_x, origin_y = float(first.position[0]), float(first.position[1])
    row_start = 0
    y_cursor = origin_y
    while row_start < len(items):
        row_end = min(row_start + cols, len(items))
        row = items[row_start:row_end]
        x_cursor = origin_x
        row_h = 0.0
        for item in row:
            if not _has_pos_size(item):
                raise TypeError(
                    "grid: every item must expose .position and .size"
                )
            item.position = (x_cursor, y_cursor)
            x_cursor += float(item.size[0]) + float(spacing_x)
            row_h = max(row_h, float(item.size[1]))
        y_cursor += row_h + float(spacing_y)
        row_start = row_end


# ---------------------------------------------------------------------------
# Anchor factories
# ---------------------------------------------------------------------------


def anchor_topleft(x: float, y: float) -> AnchorFn:
    """Return a resolver that pins *(x, y)* relative to the top-left corner.

    The resolver is ``(screen_w, screen_h) → (x_screen, y_screen)`` — the
    ``screen_*`` args are ignored for top-left anchors but kept in the
    signature so all three factories share the same call convention.
    """

    x_f = float(x)
    y_f = float(y)

    def _resolve(screen_w: float, screen_h: float) -> tuple[float, float]:
        return (x_f, y_f)

    return _resolve


def anchor_center() -> AnchorFn:
    """Return a resolver that pins the origin to the screen centre."""

    def _resolve(screen_w: float, screen_h: float) -> tuple[float, float]:
        return (float(screen_w) * 0.5, float(screen_h) * 0.5)

    return _resolve


def anchor_bottomright(x: float, y: float) -> AnchorFn:
    """Return a resolver that pins the origin to ``(-x, -y)`` from the bottom-right.

    The returned position is ``(screen_w - x, screen_h - y)`` — useful
    for pinning HUD chunks like ammo counters or minimaps.
    """

    x_f = float(x)
    y_f = float(y)

    def _resolve(screen_w: float, screen_h: float) -> tuple[float, float]:
        return (float(screen_w) - x_f, float(screen_h) - y_f)

    return _resolve


__all__ = [
    "AnchorFn",
    "anchor_bottomright",
    "anchor_center",
    "anchor_topleft",
    "grid",
    "stack_horizontal",
    "stack_vertical",
]
