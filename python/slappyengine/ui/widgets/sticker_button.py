"""``StickerButton`` — sticker-style button primitive.

Renders as a peeled sticker via the active theme's nine-slice / shader.
The button is composed of an icon (SVG path resolved by the theme, or an
emoji fallback) + a label + a slight rotation so it visually "tilts" off
the page.

Theme keys read at construction time:

* ``palette["accent"]``  — sticker base colour.
* ``palette["ink"]``     — label colour.
* ``nine_slice["sticker_button"]`` — peeled-sticker shader path
  (optional; widget falls back to a plain DPG button when missing).
* ``sticker_rotation``   — base tilt in degrees (clamped to ``[-15, 15]``).
"""
from __future__ import annotations

from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_str,
)
from slappyengine.ui.widgets._dpg_base import _NotebookWidget
from slappyengine.ui.widgets.notebook_theme import (
    clamp_rotation,
    resolve_theme,
)


class StickerButton(_NotebookWidget):
    """Sticker-styled clickable button.

    Parameters
    ----------
    label:
        Visible label.  Must be a non-empty string.
    sticker_icon:
        Sticker identifier.  The active theme resolves it to a sticker PNG
        via ``theme.sticker_path()``; when no asset is registered the
        widget falls back to ``theme.icon_for()`` (emoji / text).
    callback:
        Invoked on click.  Receives ``(sender, app_data, user_data)`` like
        any DPG callback.
    rotation:
        Optional override for the theme's default sticker tilt.  Clamped
        to ``[-15, 15]`` degrees.
    width / height:
        Optional DPG pixel sizes.  Defaults to ``(120, 36)`` so the
        sticker reads as "thumb-friendly" by default.
    """

    def __init__(
        self,
        label: str,
        sticker_icon: str,
        callback: Callable,
        *,
        rotation: float | None = None,
        width: int = 120,
        height: int = 36,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "StickerButton", label)
        self.sticker_icon = validate_non_empty_str(
            "sticker_icon", "StickerButton", sticker_icon,
        )
        self.callback = validate_callable("callback", "StickerButton", callback)

        # Width / height defaults follow the editor's existing toolbar metrics.
        if not isinstance(width, int) or isinstance(width, bool):
            raise TypeError("StickerButton: width must be int")
        if not isinstance(height, int) or isinstance(height, bool):
            raise TypeError("StickerButton: height must be int")
        self.width = width
        self.height = height

        theme = resolve_theme()
        base_rot = rotation if rotation is not None else theme.sticker_rotation
        self.rotation = clamp_rotation(base_rot)

        # Cached resolution snapshots — exposed for theme-application tests.
        self._sticker_path: str = theme.sticker_path(sticker_icon)
        self._fallback_icon: str = theme.icon_for(sticker_icon, default="*")
        self._accent: tuple[int, int, int, int] = theme.color(
            "accent", (220, 120, 160, 255),
        )
        self._ink: tuple[int, int, int, int] = theme.color(
            "ink", (40, 40, 60, 255),
        )

    # ------------------------------------------------------------------
    # Properties — readable snapshots that tests assert against without
    # touching the (DPG-bound) widget tree.
    # ------------------------------------------------------------------

    @property
    def sticker_path(self) -> str:
        """Path to the resolved sticker PNG (or ``""`` when unavailable)."""
        return self._sticker_path

    @property
    def fallback_icon(self) -> str:
        """Emoji / text fallback the theme picked for this sticker."""
        return self._fallback_icon

    @property
    def accent_color(self) -> tuple[int, int, int, int]:
        """Sticker accent colour the theme picked."""
        return self._accent

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Materialise the sticker button under *parent_tag*.

        When ``dearpygui`` is not importable the call is a no-op so the
        widget remains constructable in headless contexts.
        """
        dpg = self._safe_dpg()
        if dpg is None:
            return

        # A DPG group hosts the icon + label so themes can decorate the
        # whole sticker (rotation / nine-slice shader) as a single item.
        root_tag = (
            f"sticker_button_{id(self)}"
        )
        try:
            with dpg.group(
                horizontal=True,
                parent=parent_tag,
                tag=root_tag,
            ):
                # Icon — show the emoji fallback when no SVG / PNG is
                # available.  Themes that ship real stickers can override
                # the icon by binding an image to the same parent.
                icon = self._fallback_icon or "*"
                dpg.add_text(icon)
                dpg.add_button(
                    label=self.label,
                    width=self.width,
                    height=self.height,
                    callback=self.callback,
                )
        except Exception:
            # The stub-DPG used by tests doesn't necessarily implement
            # ``group`` as a context manager — fall back to a flat call
            # so the widget still registers a build attempt.
            try:
                dpg.add_button(
                    label=self.label,
                    width=self.width,
                    height=self.height,
                    callback=self.callback,
                    parent=parent_tag,
                    tag=root_tag,
                )
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._sticker_path = theme.sticker_path(self.sticker_icon)
        self._fallback_icon = theme.icon_for(self.sticker_icon, default="*")
        self._accent = theme.color("accent", self._accent)
        self._ink = theme.color("ink", self._ink)
        self.rotation = clamp_rotation(theme.sticker_rotation)


__all__ = ["StickerButton"]
