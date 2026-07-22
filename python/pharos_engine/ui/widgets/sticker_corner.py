"""``add_sticker_corner`` — drop a decorative sticker on a panel corner.

Stickers are addressed by a string identifier resolved through the active
theme.  The function returns a handle (a string DPG tag) which can be
passed to :func:`remove_sticker_corner` to take the sticker back off.

The function is intentionally a *function*, not a class — sticker corners
are not "widgets" in the interactive sense; they're decorations bound to
an existing parent.  Returning a tag keeps the call ergonomic for the
common "spawn + later remove" pattern (e.g. for an animation pass).
"""
from __future__ import annotations

from pharos_engine._validation import (
    validate_non_empty_str,
)
from pharos_engine.ui.widgets.notebook_theme import (
    normalise_corner,
    resolve_theme,
)


# In-process registry so callers can ``remove_sticker_corner(handle)``
# even when the DPG context is a no-op stub (the tag is still recorded).
_active_stickers: dict[str, dict[str, str]] = {}


def add_sticker_corner(
    parent: str | int,
    sticker_id: str,
    corner: str = "TR",
) -> str:
    """Spawn a sticker decoration in *corner* of *parent*.

    Parameters
    ----------
    parent:
        DPG tag of the parent container.  Must be a non-empty string or an
        existing integer item tag.
    sticker_id:
        Theme-resolved sticker identifier (``"heart"``, ``"star"``, …).
    corner:
        One of ``"TL"``, ``"TR"``, ``"BL"``, ``"BR"`` (case-insensitive).

    Returns
    -------
    str
        The DPG tag of the spawned sticker.  Pass it to
        :func:`remove_sticker_corner` to take the sticker back off.
    """
    # ``parent`` may legitimately be an int (a real DPG item id) so we
    # only validate the string-form when the caller hands us a string.
    if isinstance(parent, str):
        validate_non_empty_str("parent", "add_sticker_corner", parent)
    elif not isinstance(parent, int) or isinstance(parent, bool):
        raise TypeError(
            "add_sticker_corner: parent must be str or int; "
            f"got {type(parent).__name__}"
        )
    sticker_id = validate_non_empty_str(
        "sticker_id", "add_sticker_corner", sticker_id,
    )
    corner = normalise_corner(corner)

    theme = resolve_theme()
    glyph = theme.icon_for(sticker_id, default="*")
    sticker_path = theme.sticker_path(sticker_id)
    color = list(theme.color("accent", (220, 120, 160, 255)))

    # The DPG tag includes the parent identifier so two stickers on
    # different parents never collide, plus the corner so the same
    # sticker can be repeated in all four corners without conflict.
    tag = f"sticker_corner_{parent}_{sticker_id}_{corner}_{id(theme)}"

    # Track the sticker even when DPG is unavailable so tests can assert
    # add/remove parity without a real GUI context.
    _active_stickers[tag] = {
        "parent": str(parent),
        "sticker_id": sticker_id,
        "corner": corner,
        "glyph": glyph,
        "sticker_path": sticker_path,
    }

    try:
        import dearpygui.dearpygui as dpg

        # Only push to DPG when we can verify a live context is present.
        # ``does_item_exist`` is a cheap probe that returns ``False`` in
        # the stub fixtures and raises in headless real-DPG (no context).
        has_context = False
        try:
            has_context = bool(dpg.does_item_exist(parent))
        except Exception:
            has_context = False
        if has_context:
            try:
                dpg.add_text(glyph, color=color, parent=parent, tag=tag)
            except Exception:
                try:
                    dpg.add_text(glyph, parent=parent)
                except Exception:
                    pass
    except Exception:
        pass

    return tag


def remove_sticker_corner(handle: str) -> bool:
    """Remove a sticker previously created by :func:`add_sticker_corner`.

    Returns ``True`` if a matching handle was removed from the registry,
    ``False`` if the handle was unknown (idempotent / safe to call twice).
    """
    if not isinstance(handle, str) or not handle:
        raise TypeError(
            "remove_sticker_corner: handle must be a non-empty str; "
            f"got {type(handle).__name__}"
        )
    if handle not in _active_stickers:
        return False
    del _active_stickers[handle]

    try:
        import dearpygui.dearpygui as dpg

        try:
            exists = dpg.does_item_exist(handle)
        except Exception:
            exists = False
        if exists:
            try:
                dpg.delete_item(handle)
            except Exception:
                pass
    except Exception:
        pass
    return True


def list_sticker_corners(parent: str | int | None = None) -> list[str]:
    """List active sticker handles, optionally filtered by *parent*.

    Returns the list of currently-active handles.  When *parent* is
    supplied, only stickers attached to that parent tag are returned.
    """
    if parent is None:
        return list(_active_stickers.keys())
    pkey = str(parent)
    return [
        tag for tag, meta in _active_stickers.items()
        if meta.get("parent") == pkey
    ]


__all__ = [
    "add_sticker_corner",
    "list_sticker_corners",
    "remove_sticker_corner",
]
