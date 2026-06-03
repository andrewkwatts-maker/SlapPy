"""Editor Theme Switcher panel — live diary-theme hot-swap UI.

A Nova3D-pattern editor panel that lets the user swap between any
registered diary-family :class:`ThemeSpec` at runtime without restarting
the editor.

The panel is composed of six top-to-bottom sections:

1. Header — "Theme" label + active theme name.
2. Theme cards grid (2 cols × N rows) — each card shows a 3-stripe
   palette preview (``primary`` / ``accent`` / ``surface``), the theme
   name, and a sticker icon hint. Click to apply.
3. Doodle separator.
4. Creature roster — one :class:`HeartCheckbox` per creature listed in
   the active theme's ``metadata["creature_roster"]``.
5. Doodle separator.
6. Global toggles — Animations master switch, Reduced motion, Easter
   eggs.
7. Footer — "Refresh editor" :class:`StickerButton`.

The panel reads its state from
:func:`slappyengine.ui.theme.get_active_theme` and writes via
:func:`slappyengine.ui.theme.apply_theme`. Creature toggles route
through a duck-typed ``CreatureScheduler.set_enabled(creature_id,
enabled)`` call when a scheduler has been bound via
:meth:`ThemeSwitcherPanel.set_scheduler`.

Integration
-----------
Register with :class:`slappyengine.ui.editor.shell.EditorShell` from
the caller (we deliberately do not modify ``shell.py`` here)::

    from slappyengine.ui.editor.theme_switcher_panel import (
        ThemeSwitcherPanel,
    )
    shell.register_panel(ThemeSwitcherPanel())

Place the registration alongside the other Details-tab panels so the
switcher lands on the right sidebar.
"""
from __future__ import annotations

from typing import Any, Callable

from slappyengine._validation import (
    validate_bool,
    validate_non_empty_str,
)


# ---------------------------------------------------------------------------
# Public constants — also surfaced through ``__all__`` so tests and the
# editor shell can reference them by name.
# ---------------------------------------------------------------------------

# Sticker icon hint per theme (used to drive the small icon shown on each
# card). Themes outside this map fall back to ``"sparkle"`` so every card
# always has *some* glyph.
_THEME_STICKER_HINT: dict[str, str] = {
    "teengirl_notebook": "sparkle",
    "cozy_diary": "leaf",
    "bullet_journal": "star",
    "scrapbook_summer": "sun",
    "cottagecore_garden": "flower",
    "kawaii_planner": "heart",
}


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _color_tuple(color: Any, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Return an ``(r, g, b, a)`` tuple for any palette / token value.

    Accepts :class:`slappyengine.ui.theme.Color`, plain 4-tuples / lists,
    and falls back to *default* otherwise. ``a`` is normalised to ``0..255``.
    """
    # ThemeSpec palette values are Color instances.
    if hasattr(color, "as_rgba_tuple"):
        try:
            r, g, b, a = color.as_rgba_tuple()
            return (int(r), int(g), int(b), int(a))
        except Exception:
            return default
    if isinstance(color, (tuple, list)) and len(color) == 4:
        try:
            r, g, b, a = color
            a_int = int(a * 255) if isinstance(a, float) and a <= 1.0 else int(a)
            return (int(r), int(g), int(b), a_int)
        except Exception:
            return default
    return default


def _theme_palette_color(
    theme: Any, role: str, default: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Read ``theme.palette[role]`` (preferring ``theme.semantic.role`` if present).

    Diary themes encode semantic tokens as additional palette keys
    (``surface`` / ``primary`` / ``accent`` …) so widgets can stay
    palette-agnostic without depending on the U1 ``SemanticTokens``
    extension landing.
    """
    semantic = getattr(theme, "semantic", None)
    if semantic is not None:
        tok = getattr(semantic, role, None)
        if tok is not None:
            return _color_tuple(tok, default)
    palette = getattr(theme, "palette", None)
    if isinstance(palette, dict):
        return _color_tuple(palette.get(role), default)
    return default


def _parse_roster(theme: Any) -> list[str]:
    """Return the active theme's default creature roster as a list of IDs.

    Reads the comma-separated ``metadata["creature_roster"]`` string
    that every diary theme ships. Missing / malformed metadata yields
    an empty list — the roster section then simply renders no rows.
    """
    metadata = getattr(theme, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("creature_roster", "")
    if not isinstance(raw, str) or not raw:
        return []
    return [piece.strip() for piece in raw.split(",") if piece.strip()]


def _creature_display_name(creature_id: str) -> str:
    """Return a human-friendly label for *creature_id*.

    ``"red_panda_01"`` → ``"Red Panda"``. Falls back to a title-cased
    underscore-stripped form so the panel never shows a bare ID.
    """
    if not creature_id:
        return ""
    stem = creature_id.rsplit("_", 1)[0] if creature_id[-1].isdigit() else creature_id
    return stem.replace("_", " ").title()


# ---------------------------------------------------------------------------
# ThemeSwitcherPanel
# ---------------------------------------------------------------------------


class ThemeSwitcherPanel:
    """Editor panel for live diary-theme switching.

    Follows the Nova3D ``build(parent_tag)`` protocol — register with
    :class:`~slappyengine.ui.editor.shell.EditorShell.register_panel` and
    the shell calls :meth:`build` with the right parent container tag.

    Parameters
    ----------
    scheduler:
        Optional creature scheduler. Any object exposing
        ``set_enabled(creature_id: str, enabled: bool) -> None`` works;
        :class:`slappyengine.ui.theme.creatures.CreatureScheduler`
        ships the canonical implementation in the U3 sprint.
    on_refresh:
        Optional callback fired by the "Refresh editor" footer button.
        Falls back to a no-op when ``None`` so the button still works
        in isolation.
    """

    TITLE = "Theme"
    DEFAULT_SIZE = (280, 360)

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 280
    MIN_HEIGHT: int = 360

    def __init__(
        self,
        scheduler: Any | None = None,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        self._scheduler: Any | None = scheduler
        self._on_refresh: Callable[[], None] | None = on_refresh
        self._panel_tag: str = f"theme_switcher_panel_{id(self)}"
        self._cards_group_tag: str = f"{self._panel_tag}_cards"
        self._roster_group_tag: str = f"{self._panel_tag}_roster"
        self._header_text_tag: str = f"{self._panel_tag}_header_text"

        # Cached creature-toggle state — survives rebuilds. Keys are
        # creature IDs; values are the user's last-toggled enabled flag.
        self._creature_state: dict[str, bool] = {}

        # Global toggles — same survives-rebuild rule.
        self._animations_enabled: bool = True
        self._reduced_motion: bool = False
        self._easter_eggs: bool = True

        # Built flag + parent stash so refresh() can no-op pre-build.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Call history for headless test assertions. Each entry is a
        # ``(event, *args)`` tuple — light-weight so we don't pull a
        # full event bus into the panel.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_scheduler(self, scheduler: Any | None) -> None:
        """Attach a creature scheduler (or detach with ``None``)."""
        self._scheduler = scheduler

    def set_on_refresh(self, callback: Callable[[], None] | None) -> None:
        """Register the footer "Refresh editor" callback."""
        if callback is not None and not callable(callback):
            raise TypeError(
                "ThemeSwitcherPanel.set_on_refresh: callback must be "
                f"callable or None; got {type(callback).__name__}"
            )
        self._on_refresh = callback

    @property
    def creature_state(self) -> dict[str, bool]:
        """Return a snapshot of the current creature toggle state."""
        return dict(self._creature_state)

    @property
    def animations_enabled(self) -> bool:
        return self._animations_enabled

    @property
    def reduced_motion(self) -> bool:
        return self._reduced_motion

    @property
    def easter_eggs(self) -> bool:
        return self._easter_eggs

    def active_theme_name(self) -> str:
        """Return the active theme's name, or an empty string when none active."""
        try:
            from slappyengine.ui.theme import get_active_theme

            return getattr(get_active_theme(), "name", "")
        except Exception:
            return ""

    def list_registered_themes(self) -> list[str]:
        """Return the sorted list of registered diary themes."""
        try:
            from slappyengine.ui.theme import list_registered_themes

            return list(list_registered_themes())
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Theme card preview — pure data; tests bind against this directly
    # ------------------------------------------------------------------

    def card_preview(self, theme_id: str) -> dict[str, Any]:
        """Return the 3-stripe preview data for *theme_id*.

        Returns a dict with keys ``primary``, ``accent``, ``surface``
        (all ``(r, g, b, a)`` tuples), ``name``, ``sticker``, and
        ``active`` (bool — True when this is the active theme).
        """
        validate_non_empty_str("theme_id", "ThemeSwitcherPanel.card_preview", theme_id)
        try:
            from slappyengine.ui.theme import _REGISTRY

            theme = _REGISTRY.get(theme_id)
        except Exception:
            theme = None

        primary = _theme_palette_color(theme, "primary", (200, 120, 160, 255)) if theme else (200, 120, 160, 255)
        accent = _theme_palette_color(theme, "accent", (255, 224, 102, 255)) if theme else (255, 224, 102, 255)
        surface = _theme_palette_color(theme, "surface", (250, 246, 235, 255)) if theme else (250, 246, 235, 255)

        return {
            "name": theme_id,
            "primary": primary,
            "accent": accent,
            "surface": surface,
            "sticker": _THEME_STICKER_HINT.get(theme_id, "sparkle"),
            "active": theme_id == self.active_theme_name(),
        }

    # ------------------------------------------------------------------
    # Nova3D panel protocol
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the panel under *parent_tag*.

        Safe to call when ``dearpygui`` is missing — every DPG call is
        guarded so the panel still registers its tags for tests.
        """
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return

        # Hydrate creature_state from the active theme's default roster
        # so freshly-built panels show every creature as enabled.
        self._sync_creature_state_from_theme()

        try:
            with dpg.collapsing_header(
                label=self.TITLE,
                default_open=True,
                parent=parent_tag,
                tag=self._panel_tag,
            ):
                self._build_header(dpg)
                self._build_cards(dpg)
                self._build_separator(dpg, "wavy")
                self._build_roster(dpg)
                self._build_separator(dpg, "dotted")
                self._build_global_toggles(dpg)
                self._build_footer(dpg)
        except Exception:
            # Fall back to a flat build for stub-DPGs that don't expose
            # ``collapsing_header`` as a context manager.
            self._build_header(dpg)
            self._build_cards(dpg)
            self._build_separator(dpg, "wavy")
            self._build_roster(dpg)
            self._build_separator(dpg, "dotted")
            self._build_global_toggles(dpg)
            self._build_footer(dpg)

    def refresh(self) -> None:
        """Rebuild the cards grid + roster from the current theme state.

        Safe to call any time after :meth:`build`. No-op before build.
        """
        self.call_log.append(("refresh",))
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            self._sync_creature_state_from_theme()
            return

        # Push the active theme name into the header.
        try:
            if dpg.does_item_exist(self._header_text_tag):
                dpg.set_value(self._header_text_tag, self.active_theme_name() or "(none)")
        except Exception:
            pass

        # Rebuild the cards grid in place.
        try:
            if dpg.does_item_exist(self._cards_group_tag):
                for child in dpg.get_item_children(self._cards_group_tag, slot=1) or []:
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._cards_group_tag):
                    self._render_cards(dpg)
        except Exception:
            pass

        # Rebuild the roster.
        self._sync_creature_state_from_theme()
        try:
            if dpg.does_item_exist(self._roster_group_tag):
                for child in dpg.get_item_children(self._roster_group_tag, slot=1) or []:
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._roster_group_tag):
                    self._render_roster(dpg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_header(self, dpg: Any) -> None:
        try:
            with dpg.group(horizontal=True, parent=self._panel_tag):
                dpg.add_text("Theme", color=[180, 180, 200, 255])
                dpg.add_text(
                    self.active_theme_name() or "(none)",
                    tag=self._header_text_tag,
                    color=[220, 120, 160, 255],
                )
        except Exception:
            try:
                dpg.add_text(
                    self.active_theme_name() or "(none)",
                    tag=self._header_text_tag,
                    parent=self._panel_tag,
                )
            except Exception:
                pass

    def _build_cards(self, dpg: Any) -> None:
        try:
            with dpg.group(tag=self._cards_group_tag, parent=self._panel_tag):
                self._render_cards(dpg)
        except Exception:
            try:
                dpg.add_text(
                    "(theme cards)",
                    tag=self._cards_group_tag,
                    parent=self._panel_tag,
                )
            except Exception:
                pass

    def _render_cards(self, dpg: Any) -> None:
        theme_ids = self.list_registered_themes()
        if not theme_ids:
            try:
                dpg.add_text("(no themes registered)", color=[150, 150, 150, 255])
            except Exception:
                pass
            return

        active = self.active_theme_name()
        # Two columns per row — group horizontally, two cards per group.
        i = 0
        while i < len(theme_ids):
            pair = theme_ids[i : i + 2]
            try:
                with dpg.group(horizontal=True):
                    for theme_id in pair:
                        self._render_card(dpg, theme_id, theme_id == active)
            except Exception:
                for theme_id in pair:
                    self._render_card(dpg, theme_id, theme_id == active)
            i += 2

    def _render_card(self, dpg: Any, theme_id: str, is_active: bool) -> None:
        preview = self.card_preview(theme_id)
        card_tag = f"{self._panel_tag}_card_{theme_id}"
        try:
            with dpg.child_window(
                width=120,
                height=78,
                border=True,
                tag=card_tag,
            ):
                # Three stripes — primary, accent, surface.
                dpg.add_text("    ", color=list(preview["primary"]))
                dpg.add_text("    ", color=list(preview["accent"]))
                dpg.add_text("    ", color=list(preview["surface"]))
                # Card body — sticker hint + theme name button.
                accent_tone = [220, 120, 160, 255] if is_active else [180, 180, 200, 255]
                dpg.add_text(
                    f"[{preview['sticker']}] {theme_id}",
                    color=accent_tone,
                )
                dpg.add_button(
                    label="Apply" + (" *" if is_active else ""),
                    callback=lambda s, a, u=theme_id: self._on_theme_card_clicked(u),
                    width=-1,
                    height=18,
                )
        except Exception:
            try:
                dpg.add_button(
                    label=f"Apply {theme_id}" + (" *" if is_active else ""),
                    callback=lambda s, a, u=theme_id: self._on_theme_card_clicked(u),
                    tag=card_tag,
                )
            except Exception:
                pass

    def _build_separator(self, dpg: Any, style: str) -> None:
        try:
            from slappyengine.ui.widgets import DoodleSeparator

            sep = DoodleSeparator(style=style)
            sep.build(self._panel_tag)
        except Exception:
            try:
                dpg.add_separator(parent=self._panel_tag)
            except Exception:
                pass

    def _build_roster(self, dpg: Any) -> None:
        try:
            with dpg.group(tag=self._roster_group_tag, parent=self._panel_tag):
                dpg.add_text("Creatures", color=[180, 180, 200, 255])
                self._render_roster(dpg)
        except Exception:
            try:
                dpg.add_text(
                    "(creature roster)",
                    tag=self._roster_group_tag,
                    parent=self._panel_tag,
                )
            except Exception:
                pass

    def _render_roster(self, dpg: Any) -> None:
        roster = self._active_roster()
        if not roster:
            try:
                dpg.add_text("(no creatures)", color=[150, 150, 150, 255])
            except Exception:
                pass
            return

        from slappyengine.ui.widgets import HeartCheckbox

        for creature_id in roster:
            display = _creature_display_name(creature_id)
            enabled = self._creature_state.get(creature_id, True)

            def _make_cb(cid: str) -> Callable[[bool], None]:
                def _cb(value: bool) -> None:
                    self._on_creature_toggle(cid, bool(value))

                return _cb

            try:
                heart = HeartCheckbox(
                    label=display,
                    value=enabled,
                    callback=_make_cb(creature_id),
                )
                heart.build(self._roster_group_tag)
            except Exception:
                # Fall back to a vanilla checkbox so the slot still
                # exists for tests.
                try:
                    dpg.add_checkbox(
                        label=display,
                        default_value=enabled,
                        callback=lambda s, a, u=creature_id: (
                            self._on_creature_toggle(u, bool(a))
                        ),
                        parent=self._roster_group_tag,
                    )
                except Exception:
                    pass

    def _build_global_toggles(self, dpg: Any) -> None:
        try:
            from slappyengine.ui.widgets import HeartCheckbox

            master = HeartCheckbox(
                label="Animations",
                value=self._animations_enabled,
                callback=lambda v: self._on_animations_toggle(bool(v)),
            )
            master.build(self._panel_tag)
        except Exception:
            try:
                dpg.add_checkbox(
                    label="Animations",
                    default_value=self._animations_enabled,
                    parent=self._panel_tag,
                    callback=lambda s, a, u: self._on_animations_toggle(bool(a)),
                )
            except Exception:
                pass

        try:
            dpg.add_checkbox(
                label="Reduced motion",
                default_value=self._reduced_motion,
                parent=self._panel_tag,
                callback=lambda s, a, u: self._on_reduced_motion_toggle(bool(a)),
            )
        except Exception:
            pass

        try:
            dpg.add_checkbox(
                label="Easter eggs",
                default_value=self._easter_eggs,
                parent=self._panel_tag,
                callback=lambda s, a, u: self._on_easter_eggs_toggle(bool(a)),
            )
        except Exception:
            pass

    def _build_footer(self, dpg: Any) -> None:
        try:
            from slappyengine.ui.widgets import StickerButton

            btn = StickerButton(
                label="Refresh editor",
                sticker_icon="sparkle",
                callback=lambda *_: self._on_refresh_clicked(),
                width=-1,
                height=24,
            )
            btn.build(self._panel_tag)
        except Exception:
            try:
                dpg.add_button(
                    label="Refresh editor",
                    parent=self._panel_tag,
                    callback=lambda *_: self._on_refresh_clicked(),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _active_roster(self) -> list[str]:
        """Return the roster IDs from the active theme's metadata."""
        try:
            from slappyengine.ui.theme import get_active_theme

            return _parse_roster(get_active_theme())
        except Exception:
            return []

    def _sync_creature_state_from_theme(self) -> None:
        """Initialise toggle state from the active theme's default roster.

        Existing user-toggled creatures keep their state; new roster
        entries default to ``True`` (enabled).
        """
        for creature_id in self._active_roster():
            self._creature_state.setdefault(creature_id, True)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_theme_card_clicked(self, theme_id: str) -> None:
        """Apply the clicked theme and refresh the panel in place."""
        self.call_log.append(("theme_card_clicked", theme_id))
        try:
            from slappyengine.ui.theme import apply_theme

            apply_theme(theme_id)
        except Exception:
            return
        # Refresh the roster so it shows the new theme's defaults.
        self._sync_creature_state_from_theme()
        self.refresh()

    def _on_creature_toggle(self, creature_id: str, enabled: bool) -> None:
        """Persist the new creature state and forward to the scheduler."""
        validate_non_empty_str(
            "creature_id", "ThemeSwitcherPanel._on_creature_toggle", creature_id,
        )
        flag = validate_bool(
            "enabled", "ThemeSwitcherPanel._on_creature_toggle", enabled,
        )
        self._creature_state[creature_id] = flag
        self.call_log.append(("creature_toggle", creature_id, flag))
        if self._scheduler is not None:
            setter = getattr(self._scheduler, "set_enabled", None)
            if callable(setter):
                try:
                    setter(creature_id, flag)
                except Exception:
                    pass

    def _on_animations_toggle(self, enabled: bool) -> None:
        self._animations_enabled = bool(enabled)
        self.call_log.append(("animations_toggle", self._animations_enabled))
        if self._scheduler is not None:
            setter = getattr(self._scheduler, "set_animations_enabled", None)
            if callable(setter):
                try:
                    setter(self._animations_enabled)
                except Exception:
                    pass

    def _on_reduced_motion_toggle(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self.call_log.append(("reduced_motion_toggle", self._reduced_motion))
        if self._scheduler is not None:
            setter = getattr(self._scheduler, "set_reduced_motion", None)
            if callable(setter):
                try:
                    setter(self._reduced_motion)
                except Exception:
                    pass

    def _on_easter_eggs_toggle(self, enabled: bool) -> None:
        self._easter_eggs = bool(enabled)
        self.call_log.append(("easter_eggs_toggle", self._easter_eggs))
        if self._scheduler is not None:
            setter = getattr(self._scheduler, "set_easter_eggs", None)
            if callable(setter):
                try:
                    setter(self._easter_eggs)
                except Exception:
                    pass

    def _on_refresh_clicked(self) -> None:
        self.call_log.append(("refresh_clicked",))
        if self._on_refresh is not None:
            try:
                self._on_refresh()
            except Exception:
                pass
        self.refresh()


__all__ = ["ThemeSwitcherPanel"]
