"""Sprint 9: notebook theme picker panel.

A tiny panel that lists every theme discovered by :class:`ThemeCatalog`
(shipped + `~/.pharos/themes/` user themes) with a live swatch preview
and an Apply button. Data-model only — the DPG rendering integration
is a thin add-on the shell mounts when it has a live context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pharos_editor.themes import Theme, ThemeCatalog


@dataclass
class ThemeSwatch:
    """Small preview payload for the picker row."""

    name: str
    display_name: str
    palette_swatches: list[tuple[str, tuple[int, int, int, int]]]
    tags: list[str]


class NotebookThemePicker:
    """Panel state for the theme picker.

    The shell wires callbacks: ``on_apply(name)`` is invoked when the
    user clicks Apply on a theme row, allowing the shell to hot-swap
    the theme via its existing theming stack.
    """

    #: Minimum window size — a theme card needs ~280 px wide for the
    #: swatch strip, and ~400 px tall to fit at least three cards.
    #: MovablePanelWindow's clamp respects these over its default 200x150.
    TITLE: str = "Themes"
    MIN_WIDTH: int = 300
    MIN_HEIGHT: int = 400

    def __init__(
        self,
        catalog: ThemeCatalog | None = None,
        on_apply: Callable[[str], None] | None = None,
    ) -> None:
        self._catalog = catalog or ThemeCatalog()
        self._on_apply = on_apply
        self._current: str | None = None

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Re-scan the catalog. Called after user drops a new YAML into
        ``~/.pharos/themes/``."""
        self._catalog.reload()

    def names(self) -> list[str]:
        return self._catalog.names()

    def swatch_for(self, name: str) -> ThemeSwatch:
        theme: Theme = self._catalog.get(name)
        keys = [
            "bg", "panel_bg", "accent_pink", "accent_teal",
            "accent_yellow", "text",
        ]
        swatches: list[tuple[str, tuple[int, int, int, int]]] = []
        for k in keys:
            v = theme.palette.get(k)
            if v is not None and len(v) >= 3:
                a = v[3] if len(v) >= 4 else 255
                swatches.append((k, (int(v[0]), int(v[1]), int(v[2]), int(a))))
        return ThemeSwatch(
            name=theme.name,
            display_name=theme.display_name,
            palette_swatches=swatches,
            tags=list(theme.tags),
        )

    def apply(self, name: str) -> str:
        """Apply the named theme, invoking the on_apply hook when set.
        Returns the applied name so callers can echo it into the status
        bar or telemetry.
        """
        if name not in self._catalog.names():
            raise KeyError(f"unknown theme {name!r}")
        self._current = name
        if self._on_apply is not None:
            try:
                self._on_apply(name)
            except Exception as exc:
                from pharos_editor.errors import route
                route(exc, "notebook_theme_picker.on_apply")
        return name

    def current(self) -> str | None:
        return self._current


# ---------------------------------------------------------------------------
# Panel style hints — Sprint 9 pattern
# ---------------------------------------------------------------------------

PANEL_STYLE_HINTS: dict[str, str] = {
    "background": "bg",
    "row_background": "panel_bg",
    "row_border": "panel_border",
    "title_text": "text",
    "swatch_border": "text_secondary",
    "apply_button_accent": "accent_pink",
}


__all__ = ["NotebookThemePicker", "ThemeSwatch", "PANEL_STYLE_HINTS"]
