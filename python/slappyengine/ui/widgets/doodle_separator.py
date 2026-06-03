"""``DoodleSeparator`` — decorative divider with hand-drawn styles."""
from __future__ import annotations

from slappyengine._validation import validate_str
from slappyengine.ui.widgets._dpg_base import _NotebookWidget


_VALID_STYLES: frozenset[str] = frozenset({"wavy", "dotted", "star_chain"})


# ASCII fallback patterns — themes that ship real glyph fonts can override
# these via a custom font; the widget contract only guarantees that
# ``style`` round-trips and that ``build`` registers some kind of divider.
_FALLBACK_GLYPHS: dict[str, str] = {
    "wavy":       "~~~~~~~~~~~~~~~~~~~~~~~~",
    "dotted":     "................",
    "star_chain": "* * * * * * * * *",
}


class DoodleSeparator(_NotebookWidget):
    """Decorative horizontal divider.

    Parameters
    ----------
    style:
        One of ``"wavy"``, ``"dotted"``, ``"star_chain"``.  The theme
        picks the actual glyph / colour; this widget owns only the layout
        slot.
    """

    def __init__(self, style: str = "wavy") -> None:
        super().__init__()
        s = validate_str("style", "DoodleSeparator", style, allow_empty=False)
        if s not in _VALID_STYLES:
            raise ValueError(
                "DoodleSeparator: style must be one of "
                f"{sorted(_VALID_STYLES)}; got {s!r}"
            )
        self.style = s

        theme = self._theme
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._accent_color = theme.color("accent", (220, 120, 160, 255))

    @property
    def glyph(self) -> str:
        """Return the ASCII fallback glyph used when no font override exists."""
        return _FALLBACK_GLYPHS.get(self.style, "----")

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"doodle_separator_{id(self)}"
        color = (
            list(self._accent_color)
            if self.style != "dotted"
            else list(self._ink_color)
        )
        try:
            dpg.add_text(self.glyph, color=color, parent=parent_tag, tag=root_tag)
        except Exception:
            try:
                dpg.add_separator(parent=parent_tag, tag=root_tag)
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._ink_color = theme.color("ink", self._ink_color)
        self._accent_color = theme.color("accent", self._accent_color)


__all__ = ["DoodleSeparator"]
