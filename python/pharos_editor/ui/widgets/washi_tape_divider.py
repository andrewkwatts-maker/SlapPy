"""``WashiTapeDivider`` — horizontal washi-tape strip used as a divider.

Uses the T2 tape shader library (``pharos_editor.ui.theme.washi_tape``)
to resolve the tape style by id.  The import is soft — when the library
is missing the widget falls back to a coloured ``dpg.add_text`` strip
using the theme's ``washi`` palette entry.

Parameterises:

* ``tape_style_id`` — one of the ids in :data:`WASHI_TAPES` (e.g.
  ``"tape_pink_dots"``).  Must be a non-empty string.
* ``length_px`` — strip length in pixels.  Positive int.
* ``rotation_deg`` — visual rotation in degrees.  Clamped to
  ``[-45, 45]`` so the tape stays roughly horizontal.
"""
from __future__ import annotations

from typing import Any, Callable

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_positive_int,
)
from pharos_editor.ui.widgets._dpg_base import _NotebookWidget


def _soft_import_tape_library() -> tuple[list[str], Callable | None]:
    """Return (known-tape-ids, get_tape_fn) — empty + None when soft-import fails."""
    try:
        from pharos_editor.ui.theme.washi_tape import (
            WASHI_TAPES, get_tape,
        )
        return sorted(getattr(WASHI_TAPES, "keys", lambda: [])()), get_tape
    except Exception:
        try:
            # Handle the case where WASHI_TAPES is a list-of-dataclasses.
            from pharos_editor.ui.theme.washi_tape import (
                WASHI_TAPES, get_tape,
            )
            ids = []
            for item in WASHI_TAPES:
                tid = getattr(item, "id", None)
                if isinstance(tid, str):
                    ids.append(tid)
            return sorted(ids), get_tape
        except Exception:
            return [], None


class WashiTapeDivider(_NotebookWidget):
    """Horizontal divider styled as washi tape.

    Parameters
    ----------
    tape_style_id:
        Id of the tape style in the T2 library.  When the library is
        missing or the id is unknown the widget still constructs and
        falls back to a plain coloured strip.
    length_px:
        Strip length in pixels.  Default 200 px.
    rotation_deg:
        Visual rotation in degrees, clamped to ``[-45, 45]``.
    """

    def __init__(
        self,
        tape_style_id: str = "tape_pink_dots",
        *,
        length_px: int = 200,
        rotation_deg: float = 0.0,
    ) -> None:
        super().__init__()
        self.tape_style_id = validate_non_empty_str(
            "tape_style_id", "WashiTapeDivider", tape_style_id,
        )
        self.length_px = validate_positive_int(
            "length_px", "WashiTapeDivider", length_px,
        )
        rot = validate_finite_float(
            "rotation_deg", "WashiTapeDivider", rotation_deg,
        )
        # Clamp so the tape reads as horizontal-ish rather than "fell off".
        if rot < -45.0:
            rot = -45.0
        elif rot > 45.0:
            rot = 45.0
        self.rotation_deg = rot

        # Resolve tape style through the T2 library (soft import).
        known_ids, get_tape = _soft_import_tape_library()
        self._known_ids: list[str] = list(known_ids)
        self._tape_resolved: bool = False
        self._tape_display_name: str = self.tape_style_id
        if get_tape is not None:
            try:
                style = get_tape(self.tape_style_id)
                if style is not None:
                    self._tape_resolved = True
                    self._tape_display_name = getattr(
                        style, "display_name", self.tape_style_id,
                    )
            except Exception:
                pass

        theme = self._theme
        self._washi_color = theme.color("washi", (180, 200, 230, 255))
        self._paper_color = theme.color("paper", (250, 246, 235, 255))

        self._strip_tag: str | None = None

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_strip_tag"] = None
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
    def washi_color(self) -> tuple[int, int, int, int]:
        return self._washi_color

    @property
    def tape_resolved(self) -> bool:
        """``True`` when the T2 library returned a matching tape style."""
        return self._tape_resolved

    @property
    def tape_display_name(self) -> str:
        """Human-readable name resolved from the T2 library (or the id)."""
        return self._tape_display_name

    @property
    def known_tape_ids(self) -> list[str]:
        """Cached list of known tape style ids (empty when the library soft-imports fail)."""
        return list(self._known_ids)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set_tape_style(self, tape_style_id: str) -> None:
        """Swap the tape style at runtime.  Resolves through the T2 library."""
        s = validate_non_empty_str(
            "tape_style_id", "WashiTapeDivider.set_tape_style", tape_style_id,
        )
        self.tape_style_id = s
        _, get_tape = _soft_import_tape_library()
        self._tape_resolved = False
        self._tape_display_name = s
        if get_tape is not None:
            try:
                style = get_tape(s)
                if style is not None:
                    self._tape_resolved = True
                    self._tape_display_name = getattr(
                        style, "display_name", s,
                    )
            except Exception:
                pass

    def set_rotation(self, rotation_deg: float) -> None:
        """Update the rotation.  Clamped to ``[-45, 45]``."""
        rot = validate_finite_float(
            "rotation_deg", "WashiTapeDivider.set_rotation", rotation_deg,
        )
        if rot < -45.0:
            rot = -45.0
        elif rot > 45.0:
            rot = 45.0
        self.rotation_deg = rot

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"washi_tape_divider_{id(self)}"
        self._strip_tag = f"{root_tag}__strip"
        strip_char = "▬"
        strip_len = max(1, int(self.length_px / 8))
        try:
            with dpg.group(parent=parent_tag, tag=root_tag):
                dpg.add_text(
                    strip_char * strip_len,
                    color=list(self._washi_color),
                    tag=self._strip_tag,
                )
        except Exception:
            try:
                dpg.add_text(
                    strip_char * strip_len,
                    color=list(self._washi_color),
                    parent=parent_tag,
                    tag=self._strip_tag,
                )
            except Exception:
                try:
                    dpg.add_separator(parent=parent_tag, tag=root_tag)
                except Exception:
                    pass

        self._mark_built(parent_tag, root_tag)

    def refresh_theme(self) -> None:
        super().refresh_theme()
        theme = self._theme
        self._washi_color = theme.color("washi", self._washi_color)
        self._paper_color = theme.color("paper", self._paper_color)


__all__ = ["WashiTapeDivider"]
