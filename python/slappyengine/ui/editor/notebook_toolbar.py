"""``NotebookToolbar`` — stationery-tray reskin of the Nova3D toolbar.

A notebook-themed variant of
:class:`slappyengine.ui.editor.toolbar.EditorToolbar`. Tool buttons are
rendered as "rubber stamps in a stationery tray": each button uses a
:class:`StickerButton` widget and the active tool is underlined with a
washi-tape strip baked through
:meth:`slappyengine.ui.theme.nine_slice.NineSlice.render_procedural`.

The existing Nova3D ``EditorToolbar`` is preserved verbatim — this module
is an opt-in sibling, never a replacement. The editor shell chooses
which to mount.

Public surface
--------------

.. code-block:: python

    from slappyengine.ui.editor.notebook_toolbar import NotebookToolbar

    bar = NotebookToolbar(on_tool_changed=lambda t: print("tool:", t))
    bar.build("toolbar_window")
    bar.set_active("rotate")          # programmatic switch
    bar.handle_shortcut("R")          # keyboard route

Design provenance
-----------------

* ``docs/ui_pattern_audit_2026_06_03.md`` §1.2 (Nova3D toolbar contract)
  + §4 (the S/T/R/E keyboard-shortcut gap this module closes).
* ``docs/theme_teengirl_notebook_2026_06_03.md`` §4.1 (toolbar tool SVG
  icons) + §3.1 (washi-tape colour roles).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
)
from slappyengine.ui.theme.creatures.slot_policy import SlotRegion
from slappyengine.ui.theme.nine_slice import NineSlice
from slappyengine.ui.theme.svg_icon import SVGIcon
from slappyengine.ui.widgets.notebook_theme import (
    NotebookTheme,
    register_theme_listener,
    resolve_theme,
)
from slappyengine.ui.widgets.sticker_button import StickerButton


# ---------------------------------------------------------------------------
# Inline SVG icons — each ≤ 500 bytes per the sprint constraint.
# Tool glyphs cribbed from ``docs/theme_teengirl_notebook_2026_06_03.md`` §4.1
# with light edits so the parser (which understands M/L/Z + H/V) renders
# without bezier curves.
# ---------------------------------------------------------------------------

_SVG_HEART_ARROW = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 21 L4 13 L4 10 L8 6 L12 10 L16 6 L20 10 L20 13 Z"'
    ' fill="currentColor"/>'
    '<path d="M14 11 L21 4 L21 8 L17 8 L21 4 Z"'
    ' fill="currentColor"/></svg>'
)

_SVG_FOUR_ARROW_FLOWER = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="12,2 14,6 12,8 10,6"'
    ' fill="currentColor"/>'
    '<polygon points="12,22 14,18 12,16 10,18"'
    ' fill="currentColor"/>'
    '<polygon points="2,12 6,10 8,12 6,14"'
    ' fill="currentColor"/>'
    '<polygon points="22,12 18,10 16,12 18,14"'
    ' fill="currentColor"/></svg>'
)

_SVG_SPIRAL = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 4 L20 4 L20 20 L4 20 L4 8 L16 8 L16 16 L8 16 L8 12 L12 12"'
    ' fill="none" stroke="currentColor" stroke-width="2"/></svg>'
)

_SVG_BOW_TIE = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="4,6 4,18 11,12" fill="currentColor"/>'
    '<polygon points="20,6 20,18 13,12" fill="currentColor"/>'
    '<polygon points="10,10 14,10 14,14 10,14" fill="currentColor"/></svg>'
)


# Static-byte guard so a future copy-paste edit can't quietly bust the budget.
for _name, _svg in (
    ("heart_arrow", _SVG_HEART_ARROW),
    ("four_arrow_flower", _SVG_FOUR_ARROW_FLOWER),
    ("spiral", _SVG_SPIRAL),
    ("bow_tie", _SVG_BOW_TIE),
):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"NotebookToolbar: SVG {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolSpec:
    """Static description of one toolbar tool."""

    tool_id: str
    label: str
    svg: str
    shortcut: str


_TOOLS: tuple[_ToolSpec, ...] = (
    _ToolSpec("select",  "Select", _SVG_HEART_ARROW,       "S"),
    _ToolSpec("move",    "Move",   _SVG_FOUR_ARROW_FLOWER, "T"),
    _ToolSpec("rotate",  "Rotate", _SVG_SPIRAL,            "R"),
    _ToolSpec("scale",   "Scale",  _SVG_BOW_TIE,           "C"),
)


# ---------------------------------------------------------------------------
# Default semantic / palette fallbacks. These mirror the
# ``teengirl_notebook`` theme so a headless build that has not registered
# a theme still produces a coherent washi colour.
# ---------------------------------------------------------------------------


_FALLBACK_ACCENT: tuple[int, int, int, int] = (255, 224, 102, 255)
_FALLBACK_WASHI: tuple[int, int, int, int] = (255, 111, 181, 255)
_FALLBACK_INK: tuple[int, int, int, int] = (31, 47, 102, 255)


# ---------------------------------------------------------------------------
# NotebookToolbar
# ---------------------------------------------------------------------------


class NotebookToolbar:
    """Stationery-tray toolbar — Select / Move / Rotate / Scale.

    The toolbar exposes the same logical contract as the Nova3D
    :class:`EditorToolbar` (one active tool at a time, callback on
    change) but reskins the chrome:

    * Tool buttons are :class:`StickerButton` instances themed as
      "rubber stamps in a tray".
    * The active tool gets a 2-px washi-tape strip baked underneath via
      :meth:`NineSlice.render_procedural`.
    * Tooltips pull from the active theme's typography + ``text_primary``
      semantic token.
    * Keyboard shortcuts ``S`` / ``T`` / ``R`` / ``C`` switch tools — the
      audit doc (§4) flagged these were documented but unbound.
    * An optional 32×32 creature slot is reserved at the right margin; the
      module-level creature scheduler renders any creature with
      ``prefers_slot="toolbar_idle"`` there.

    Parameters
    ----------
    on_tool_changed:
        Callback invoked every time :meth:`set_active` mutates the active
        tool. Receives the new tool id (``"select"`` / ``"move"`` /
        ``"rotate"`` / ``"scale"``).
    """

    TOOLS: tuple[tuple[str, str, str, str], ...] = tuple(
        (t.tool_id, t.label, t.svg, t.shortcut) for t in _TOOLS
    )

    _BTN_W: int = 96
    _BTN_H: int = 36
    _TAPE_H: int = 2

    # 32×32 region reserved at the right margin for the napping creature.
    _CREATURE_SLOT_W: int = 32
    _CREATURE_SLOT_H: int = 32

    def __init__(
        self,
        on_tool_changed: Callable[[str], None] | None = None,
    ) -> None:
        if on_tool_changed is not None:
            validate_callable(
                "on_tool_changed", "NotebookToolbar", on_tool_changed,
            )
        self._on_tool_changed = on_tool_changed
        self._active_tool: str = _TOOLS[0].tool_id

        # Theme snapshot — re-resolved on every set_active call so the
        # washi-tape colour tracks runtime theme switches.
        self._theme_spec = self._resolve_theme_spec()

        # SVG icons live on the instance so tests can introspect bytes /
        # rasterisation without going through DPG.
        self._icons: dict[str, SVGIcon] = {}
        for spec in _TOOLS:
            self._icons[spec.tool_id] = SVGIcon(
                svg_xml=spec.svg,
                size=24,
                default_fill=self._resolve_accent(),
            )

        # Sticker buttons — constructed eagerly so theme listeners attach
        # before any build call. Kept on the instance for refresh.
        self._buttons: dict[str, StickerButton] = {}
        for spec in _TOOLS:
            self._buttons[spec.tool_id] = StickerButton(
                label=spec.label,
                sticker_icon=spec.tool_id,
                callback=lambda s, a, u, tid=spec.tool_id: self.set_active(tid),
                width=self._BTN_W,
                height=self._BTN_H,
            )

        # Cached washi-tape strip texture per (tool_id) — regenerated on
        # theme change. Tests assert dtype/shape/colour against these.
        self._tape_textures: dict[str, np.ndarray] = {}
        self._rebuild_tape_textures()

        # Creature slot region — pinned to the right margin of the toolbar.
        # The scheduler reads region.x/y/w/h to anchor the render fn.
        self._creature_slot: SlotRegion = SlotRegion(
            x=len(_TOOLS) * (self._BTN_W + 6) + 8,
            y=2,
            w=self._CREATURE_SLOT_W,
            h=self._CREATURE_SLOT_H,
            parent_panel="notebook_toolbar",
        )

        # Track which creature claimed the slot (theme defaults to fox_01).
        self._creature_id: str | None = "fox_01"

        # Re-run icon + tape colour binding when the theme registry flips.
        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Theme resolution helpers
    # ------------------------------------------------------------------

    def _resolve_theme_spec(self) -> NotebookTheme:
        """Return the active :class:`NotebookTheme` (or the fallback)."""
        return resolve_theme()

    def _resolve_accent(self) -> tuple[int, int, int, int]:
        """Active theme's ``semantic.accent`` colour (RGBA 0-255).

        Reads from the *ThemeSpec* registry when available; falls back to
        the notebook widget theme's ``palette["accent"]`` and finally to
        a hard-coded highlighter-yellow.
        """
        spec = self._lookup_themespec()
        if spec is not None:
            try:
                return spec.semantic.accent.as_rgba_tuple()
            except Exception:  # pragma: no cover - defensive
                pass
        theme = self._resolve_theme_spec()
        return theme.color("accent", _FALLBACK_ACCENT)

    def _resolve_washi(self) -> tuple[int, int, int, int]:
        """Active theme's washi-tape colour, with semantic.accent fallback.

        Mirrors the spec brief: prefer ``palette["washi_tape"]``; if
        absent, drop back to ``semantic.accent``.
        """
        spec = self._lookup_themespec()
        if spec is not None:
            washi = spec.palette.get("washi_tape") or spec.palette.get("washi")
            if washi is not None:
                try:
                    return washi.as_rgba_tuple()
                except Exception:  # pragma: no cover - defensive
                    pass
            try:
                return spec.semantic.accent.as_rgba_tuple()
            except Exception:  # pragma: no cover - defensive
                pass
        theme = self._resolve_theme_spec()
        return theme.color("washi", theme.color("accent", _FALLBACK_WASHI))

    def _resolve_text_primary(self) -> tuple[int, int, int, int]:
        """Active theme's ``semantic.text_primary`` colour."""
        spec = self._lookup_themespec()
        if spec is not None:
            try:
                return spec.semantic.text_primary.as_rgba_tuple()
            except Exception:  # pragma: no cover - defensive
                pass
        theme = self._resolve_theme_spec()
        return theme.color("ink", _FALLBACK_INK)

    @staticmethod
    def _lookup_themespec():
        """Return the active :class:`ThemeSpec` or ``None`` (lazy import).

        Importing ``slappyengine.ui.theme`` at module load would pull the
        full registry into every editor entry; we lazy-load here so the
        notebook toolbar stays importable in headless contexts.
        """
        try:
            from slappyengine.ui import theme as theme_pkg

            return theme_pkg.get_active_theme()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API — matches the brief signature exactly
    # ------------------------------------------------------------------

    def set_active(self, tool_id: str) -> None:
        """Switch the active tool and notify the callback.

        Raises
        ------
        ValueError
            If *tool_id* is not one of the four registered tools.
        """
        tool_id = validate_non_empty_str(
            "tool_id", "NotebookToolbar.set_active", tool_id,
        )
        valid = {spec.tool_id for spec in _TOOLS}
        if tool_id not in valid:
            raise ValueError(
                f"NotebookToolbar.set_active: tool_id must be one of "
                f"{sorted(valid)}; got {tool_id!r}"
            )
        changed = tool_id != self._active_tool
        self._active_tool = tool_id
        if changed and self._on_tool_changed is not None:
            try:
                self._on_tool_changed(tool_id)
            except Exception:
                # Callbacks that crash should not poison the toolbar.
                pass

    def get_active(self) -> str:
        """Return the currently active tool id."""
        return self._active_tool

    def handle_shortcut(self, key: str) -> bool:
        """Dispatch a keypress to the matching tool. Returns ``True`` on hit.

        Comparison is case-insensitive — both ``"S"`` and ``"s"`` route to
        the Select tool. Keys that don't match any tool return ``False``
        without mutating state so callers can chain to other handlers.
        """
        if not isinstance(key, str) or not key:
            return False
        up = key.upper()
        for spec in _TOOLS:
            if spec.shortcut.upper() == up:
                self.set_active(spec.tool_id)
                return True
        return False

    @property
    def shortcuts(self) -> dict[str, str]:
        """Return the keyboard-shortcut → tool-id mapping."""
        return {spec.shortcut: spec.tool_id for spec in _TOOLS}

    @property
    def tools(self) -> tuple[tuple[str, str, str, str], ...]:
        """Return the static tools table — used by tests + tooltip code."""
        return self.TOOLS

    @property
    def icons(self) -> dict[str, SVGIcon]:
        """Return the per-tool :class:`SVGIcon` instances."""
        return dict(self._icons)

    @property
    def buttons(self) -> dict[str, StickerButton]:
        """Return the per-tool :class:`StickerButton` instances."""
        return dict(self._buttons)

    @property
    def creature_slot(self) -> SlotRegion:
        """Return the reserved 32×32 creature region."""
        return self._creature_slot

    @property
    def creature_id(self) -> str | None:
        """Return the id of the creature occupying the slot (or ``None``)."""
        return self._creature_id

    @property
    def active_tape_color(self) -> tuple[int, int, int, int]:
        """Washi-tape colour for the active tool indicator."""
        return self._resolve_washi()

    @property
    def active_indicator_color(self) -> tuple[int, int, int, int]:
        """Semantic-accent colour the indicator falls back to.

        Tests assert that the rendered tape texture's centre pixel
        matches this colour after a theme switch.
        """
        return self._resolve_accent()

    def tooltip(self, tool_id: str) -> dict[str, object]:
        """Return a tooltip descriptor — label, font family, text colour.

        Returns
        -------
        dict
            ``{"text": str, "color": (r,g,b,a), "font": str, "size": int}``.
            ``font`` is the theme's body font family when available, else
            ``"sans-serif"``.
        """
        valid = {spec.tool_id for spec in _TOOLS}
        if tool_id not in valid:
            raise ValueError(
                "NotebookToolbar.tooltip: tool_id must be one of "
                f"{sorted(valid)}; got {tool_id!r}"
            )
        label = next(t.label for t in _TOOLS if t.tool_id == tool_id)
        font_family = "sans-serif"
        font_size = 14
        spec = self._lookup_themespec()
        if spec is not None:
            body = spec.fonts.get("body") or spec.fonts.get("caption")
            if body is not None:
                font_family = body.family
                font_size = int(body.size)
        return {
            "text": label,
            "color": self._resolve_text_primary(),
            "font": font_family,
            "size": font_size,
        }

    def tape_texture(self, tool_id: str) -> np.ndarray:
        """Return the baked washi-tape strip for *tool_id*.

        Used by the renderer to paint the active-tool indicator and by
        tests to assert the strip dimensions + colour.
        """
        valid = {spec.tool_id for spec in _TOOLS}
        if tool_id not in valid:
            raise ValueError(
                "NotebookToolbar.tape_texture: tool_id must be one of "
                f"{sorted(valid)}; got {tool_id!r}"
            )
        tex = self._tape_textures.get(tool_id)
        if tex is None:
            self._rebuild_tape_textures()
            tex = self._tape_textures[tool_id]
        return tex

    def refresh_theme(self) -> None:
        """Re-resolve colours + icons against the live theme.

        Called automatically when ``set_active_theme`` fires; the API is
        public so editor hosts that rebuild the toolbar in place can force
        a refresh without reconstructing the panel.
        """
        self._theme_spec = self._resolve_theme_spec()
        accent = self._resolve_accent()
        for tool_id, icon in self._icons.items():
            icon.default_fill = accent
            # Drop the cached raster so the next consumer re-rasterises.
            icon._texture = None
            icon._dpg_texture_id = None
        for btn in self._buttons.values():
            btn.refresh_theme()
        self._rebuild_tape_textures()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the toolbar inside *parent_tag*.

        Uses ``dearpygui`` when available; falls back to a no-op + per-
        button build so the API remains callable in headless / stub-DPG
        environments. The caller is responsible for having entered a DPG
        context (``dpg.create_context()``) when DPG is installed — this
        is the same contract the existing :class:`EditorToolbar` carries.
        """
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except Exception:
            dpg = None  # type: ignore[assignment]

        if dpg is None:
            # Headless — drive child build paths anyway so listeners attach.
            for btn in self._buttons.values():
                try:
                    btn.build(parent_tag)
                except Exception:
                    pass
            return

        try:
            with dpg.group(horizontal=True, parent=parent_tag):
                for spec in _TOOLS:
                    btn = self._buttons[spec.tool_id]
                    btn.build(parent_tag)
        except Exception:
            # Stub DPG / context-manager unsupported — flat fallback.
            for spec in _TOOLS:
                try:
                    self._buttons[spec.tool_id].build(parent_tag)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme) -> None:
        """``NotebookTheme`` listener — refresh on every active-theme flip."""
        try:
            self.refresh_theme()
        except Exception:
            pass

    def _rebuild_tape_textures(self) -> None:
        """Bake the 2-px washi-tape strip for every tool button.

        We use :meth:`NineSlice.render_procedural` with zero insets and a
        plain solid-fill pattern so the resulting array is a flat colour
        band the renderer can blit under the active button. Even though
        we only show the strip under one button at a time we bake one
        per tool — the tests assert that every button has a matching
        texture available so switching tools is allocation-free.
        """
        color = self._resolve_washi()
        # render_procedural draws a 1-pixel border at the insets; pass
        # zero insets so the whole strip is the requested colour.
        strip = NineSlice(source=None, insets=(0, 0, 0, 0))
        tex = strip.render_procedural(
            size=(self._BTN_W, self._TAPE_H),
            color=color,
        )
        # Same strip for every tool today; key by tool_id so the renderer
        # can swap textures per-button without reaching into private state.
        self._tape_textures = {spec.tool_id: tex for spec in _TOOLS}


__all__ = ["NotebookToolbar"]
