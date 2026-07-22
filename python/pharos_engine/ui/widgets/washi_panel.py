"""``WashiPanel`` — bordered panel with a washi-tape top edge.

The theme picks the tape colour / pattern via ``palette["washi"]`` and
``nine_slice["washi_panel"]``; the widget owns only the structural
layout (title row, tape strip, content child window).
"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)
from pharos_engine.ui.widgets._dpg_base import _NotebookWidget


class WashiPanel(_NotebookWidget):
    """Bordered container with a washi-tape decoration above the title.

    Parameters
    ----------
    title:
        Panel title.  Must be a non-empty string.
    children:
        Iterable of zero-arg builder callables (each receives no args and
        builds its own DPG content into the *current* container).  The
        empty list is allowed so the panel can be populated lazily.
    width / height:
        Optional DPG pixel sizes.  Defaults to ``(-1, -1)`` so the panel
        fills its parent.
    """

    def __init__(
        self,
        title: str,
        children: Sequence[Callable[[], None]] | None = None,
        *,
        width: int = -1,
        height: int = -1,
    ) -> None:
        super().__init__()
        self.title = validate_non_empty_str("title", "WashiPanel", title)

        if children is None:
            children = []
        if not isinstance(children, (list, tuple)):
            raise TypeError(
                "WashiPanel: children must be a list or tuple of callables; "
                f"got {type(children).__name__}"
            )
        for i, ch in enumerate(children):
            if not callable(ch):
                raise TypeError(
                    f"WashiPanel: children[{i}] must be callable; "
                    f"got {type(ch).__name__}"
                )
        self.children: list[Callable[[], None]] = list(children)

        # Width / height are stored verbatim — DPG accepts -1 for "fill".
        if not isinstance(width, int) or isinstance(width, bool):
            raise TypeError("WashiPanel: width must be int")
        if not isinstance(height, int) or isinstance(height, bool):
            raise TypeError("WashiPanel: height must be int")
        self.width = width
        self.height = height

        theme = self._theme
        self._tape_color = theme.color("washi", (180, 200, 230, 255))
        self._paper_color = theme.color("paper", (250, 246, 235, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._nine_slice = theme.nine_slice_path("washi_panel")

    # ------------------------------------------------------------------
    # Public mutation
    # ------------------------------------------------------------------

    def add_child(self, builder: Callable[[], None]) -> None:
        """Append a child builder.  Must be called before :meth:`build`."""
        if not callable(builder):
            raise TypeError(
                f"WashiPanel.add_child: builder must be callable; "
                f"got {type(builder).__name__}"
            )
        self.children.append(builder)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tape_color(self) -> tuple[int, int, int, int]:
        return self._tape_color

    @property
    def paper_color(self) -> tuple[int, int, int, int]:
        return self._paper_color

    @property
    def nine_slice_path(self) -> str:
        return self._nine_slice

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"washi_panel_{id(self)}"
        try:
            with dpg.child_window(
                parent=parent_tag,
                width=self.width,
                height=self.height,
                tag=root_tag,
            ):
                # Washi-tape strip — a coloured text row stands in for the
                # textured tape; the theme can decorate the same row with
                # a drawlist later without breaking the widget contract.
                tape_color = list(self._tape_color)
                dpg.add_text("================", color=tape_color)
                dpg.add_text(self.title, color=list(self._ink_color))
                dpg.add_separator()
                # Render each child inside the panel.
                for ch in self.children:
                    try:
                        ch()
                    except Exception:
                        # A misbehaving child shouldn't break sibling children.
                        pass
        except Exception:
            # Stub-DPG without context-manager support — flat call path.
            try:
                dpg.add_text(self.title, parent=parent_tag)
            except Exception:
                pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._tape_color = theme.color("washi", self._tape_color)
        self._paper_color = theme.color("paper", self._paper_color)
        self._ink_color = theme.color("ink", self._ink_color)
        self._nine_slice = theme.nine_slice_path("washi_panel")


__all__ = ["WashiPanel"]
