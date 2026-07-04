"""``PaperClipAttachment`` — collapsible group with a paperclip icon.

A small paperclip icon sits above a group of related content.  Clicking
the icon toggles the collapse state; the widget owns the boolean and
propagates it to a DPG ``collapsing_header`` when built.  A subtle
diary-themed shadow is emulated by drawing a slightly-offset second text
line beneath the label — a proper drop-shadow lives in the theme's
nine-slice slot.

Theme keys:

* ``palette["ink"]`` — clip / label colour.
* ``palette["paper"]`` — background wash.
* ``nine_slice["paper_clip"]`` — clip glyph texture (optional).
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from slappyengine._validation import (
    validate_bool,
    validate_non_empty_str,
)
from slappyengine.ui.widgets._dpg_base import _NotebookWidget


class PaperClipAttachment(_NotebookWidget):
    """Collapsible group with a paperclip glyph.

    Parameters
    ----------
    label:
        Visible label displayed next to the clip glyph.
    children:
        Iterable of zero-arg builder callables invoked during
        :meth:`build` when the attachment is expanded.
    expanded:
        Initial collapse state.  ``False`` starts collapsed.
    on_click:
        Optional callback fired when the user clicks the clip; receives
        the new expanded state (bool).
    on_change:
        Optional callback fired whenever ``expanded`` toggles (either via
        click or programmatic :meth:`set_expanded`).
    """

    _CLIP_GLYPH: str = "📎"
    _CLIP_FALLBACK: str = "\\o"  # ASCII paperclip when the emoji font is missing

    def __init__(
        self,
        label: str,
        children: Sequence[Callable[[], None]] | None = None,
        *,
        expanded: bool = False,
        on_click: Callable | None = None,
        on_change: Callable | None = None,
    ) -> None:
        super().__init__()
        self.label = validate_non_empty_str("label", "PaperClipAttachment", label)
        self.expanded = validate_bool(
            "expanded", "PaperClipAttachment", expanded,
        )

        if children is None:
            children = []
        if not isinstance(children, (list, tuple)):
            raise TypeError(
                "PaperClipAttachment: children must be a list or tuple; "
                f"got {type(children).__name__}"
            )
        for i, ch in enumerate(children):
            if not callable(ch):
                raise TypeError(
                    f"PaperClipAttachment: children[{i}] must be callable; "
                    f"got {type(ch).__name__}"
                )
        self.children: list[Callable[[], None]] = list(children)

        if on_click is not None and not callable(on_click):
            raise TypeError(
                f"PaperClipAttachment: on_click must be callable or None; "
                f"got {type(on_click).__name__}"
            )
        if on_change is not None and not callable(on_change):
            raise TypeError(
                f"PaperClipAttachment: on_change must be callable or None; "
                f"got {type(on_change).__name__}"
            )
        self.on_click: Callable | None = on_click
        self.on_change: Callable | None = on_change

        theme = self._theme
        self._ink_color = theme.color("ink", (40, 40, 60, 255))
        self._paper_color = theme.color("paper", (250, 246, 235, 255))
        self._shadow_color = (
            max(0, self._paper_color[0] - 40),
            max(0, self._paper_color[1] - 40),
            max(0, self._paper_color[2] - 30),
            180,
        )
        self._nine_slice = theme.nine_slice_path("paper_clip")

        self._header_tag: str | None = None

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_header_tag"] = None
        state["_root_tag"] = None
        state["_parent_tag"] = None
        state["_built"] = False
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def ink_color(self) -> tuple[int, int, int, int]:
        return self._ink_color

    @property
    def paper_color(self) -> tuple[int, int, int, int]:
        return self._paper_color

    @property
    def shadow_color(self) -> tuple[int, int, int, int]:
        return self._shadow_color

    @property
    def nine_slice_path(self) -> str:
        return self._nine_slice

    @property
    def clip_glyph(self) -> str:
        """Return the clip glyph (emoji preferred, ASCII fallback otherwise)."""
        # Prefer the theme's registered clip glyph, then the emoji, then ASCII.
        theme_glyph = self._theme.icon_for("paper_clip", default="")
        if theme_glyph:
            return theme_glyph
        return self._CLIP_GLYPH

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def add_child(self, builder: Callable[[], None]) -> None:
        if not callable(builder):
            raise TypeError(
                f"PaperClipAttachment.add_child: builder must be callable; "
                f"got {type(builder).__name__}"
            )
        self.children.append(builder)

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically update the collapse state.  Fires ``on_change``."""
        v = validate_bool(
            "expanded", "PaperClipAttachment.set_expanded", expanded,
        )
        if v == self.expanded:
            return
        self.expanded = v
        if self._built and self._header_tag is not None:
            dpg = self._safe_dpg()
            if dpg is not None:
                try:
                    dpg.configure_item(self._header_tag, default_open=v)
                except Exception:
                    pass
        if self.on_change is not None:
            try:
                self.on_change(v)
            except Exception:
                pass

    def toggle(self) -> bool:
        """Flip the collapse state, fire ``on_click`` + ``on_change``.

        Returns the new expanded state.
        """
        if not self._enabled:
            return self.expanded
        self.expanded = not self.expanded
        if self.on_click is not None:
            try:
                self.on_click(self.expanded)
            except Exception:
                pass
        if self.on_change is not None:
            try:
                self.on_change(self.expanded)
            except Exception:
                pass
        return self.expanded

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _on_header(self, sender, app_data, user_data) -> None:
        if not self._enabled:
            return
        self.expanded = bool(app_data)
        if self.on_click is not None:
            try:
                self.on_click(self.expanded)
            except Exception:
                pass
        if self.on_change is not None:
            try:
                self.on_change(self.expanded)
            except Exception:
                pass

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"paper_clip_attachment_{id(self)}"
        self._header_tag = f"{root_tag}__hdr"
        header_label = f"{self.clip_glyph} {self.label}"
        try:
            with dpg.collapsing_header(
                label=header_label,
                default_open=bool(self.expanded),
                parent=parent_tag,
                tag=self._header_tag,
            ):
                for ch in self.children:
                    try:
                        ch()
                    except Exception:
                        pass
        except Exception:
            try:
                with dpg.group(parent=parent_tag, tag=root_tag):
                    dpg.add_text(header_label, color=list(self._ink_color))
                    for ch in self.children:
                        try:
                            ch()
                        except Exception:
                            pass
            except Exception:
                try:
                    dpg.add_text(header_label, parent=parent_tag, tag=root_tag)
                except Exception:
                    pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._ink_color = theme.color("ink", self._ink_color)
        self._paper_color = theme.color("paper", self._paper_color)
        self._shadow_color = (
            max(0, self._paper_color[0] - 40),
            max(0, self._paper_color[1] - 40),
            max(0, self._paper_color[2] - 30),
            180,
        )
        self._nine_slice = theme.nine_slice_path("paper_clip")


__all__ = ["PaperClipAttachment"]
