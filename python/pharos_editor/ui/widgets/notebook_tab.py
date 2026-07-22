"""``NotebookTab`` — tab with a torn-paper edge.

The theme chooses the paper texture via ``nine_slice["notebook_tab"]``
and the paper / accent colours via ``palette``.  The widget owns only
the structural layout (label header + content container).
"""
from __future__ import annotations

from typing import Callable, Sequence

from pharos_engine._validation import validate_non_empty_str
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


class NotebookTab(_NotebookWidget):
    """Single tab inside a tab bar (or a stand-alone "page" container).

    Parameters
    ----------
    label:
        Tab label (visible to the user).
    children:
        Iterable of zero-arg builder callables.  Each runs inside the
        tab's content container during :meth:`build`.
    """

    def __init__(
        self,
        label: str,
        children: Sequence[Callable[[], None]] | None = None,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "NotebookTab", label)

        if children is None:
            children = []
        if not isinstance(children, (list, tuple)):
            raise TypeError(
                "NotebookTab: children must be a list or tuple of callables; "
                f"got {type(children).__name__}"
            )
        for i, ch in enumerate(children):
            if not callable(ch):
                raise TypeError(
                    f"NotebookTab: children[{i}] must be callable; "
                    f"got {type(ch).__name__}"
                )
        self.children: list[Callable[[], None]] = list(children)

        theme = self._theme
        self._paper_color = theme.color("paper", (250, 246, 235, 255))
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._nine_slice = theme.nine_slice_path("notebook_tab")

    # ------------------------------------------------------------------
    # Public mutation
    # ------------------------------------------------------------------

    def add_child(self, builder: Callable[[], None]) -> None:
        if not callable(builder):
            raise TypeError(
                f"NotebookTab.add_child: builder must be callable; "
                f"got {type(builder).__name__}"
            )
        self.children.append(builder)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

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
        """Materialise the tab under *parent_tag*.

        Callers may pass either a ``tab_bar`` tag (in which case DPG
        renders the tab as a real tab) or any container tag (in which
        case the tab degrades to a labelled child window — the torn
        edge still renders via the theme's nine-slice).
        """
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"notebook_tab_{id(self)}"
        try:
            # Prefer the real ``tab`` primitive when available.
            with dpg.tab(
                label=self.label, parent=parent_tag, tag=root_tag,
            ):
                for ch in self.children:
                    try:
                        ch()
                    except Exception:
                        pass
        except Exception:
            # Fall back to a labelled child window so the widget remains
            # usable inside non-tab parents.
            try:
                with dpg.child_window(
                    label=self.label, parent=parent_tag, tag=root_tag,
                ):
                    for ch in self.children:
                        try:
                            ch()
                        except Exception:
                            pass
            except Exception:
                try:
                    dpg.add_text(self.label, parent=parent_tag)
                except Exception:
                    pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._paper_color = theme.color("paper", self._paper_color)
        self._ink_color = theme.color("ink", self._ink_color)
        self._nine_slice = theme.nine_slice_path("notebook_tab")


__all__ = ["NotebookTab"]
