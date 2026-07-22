"""Notebook-themed welcome / splash screen.

The :class:`NotebookWelcome` panel is the editor's first-run "front
cover" — a centred modal styled as a hand-drawn diary cover. It
introduces Pharos Engine with three warm onboarding cues:

1. A trio of *sticker demo cards* (fox / bunny / butterfly) that open
   one-click example demos:

   * fox → ``examples/hello_ragdoll.py``
   * bunny → ``examples/hello_rope.py``
   * butterfly → ``examples/hello_studio.py``

2. A pink *"Start drawing!"* sticker button that opens a blank scene.

3. A mini *theme swatch row* (six 32×32 px swatches) that hot-swaps
   the active diary theme + closes the welcome.

A :class:`HeartCheckbox` at the bottom toggles
:attr:`UISettings.welcome_shown` so the modal only auto-appears once.
Users re-open it via ``Help → Welcome``.

The lined-paper background uses the active theme's palette; sparkle +
heart stickers decorate the top-left and bottom-right corners and a
:class:`CreatureScheduler` "sparkle" creature drifts across the
handwritten header on a 4-second loop.

Headless-safe — every DPG call is guarded so the module imports + builds
cleanly under a stub ``dearpygui`` in CI.
"""
from __future__ import annotations

from typing import Any, Callable

from pharos_engine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_str,
)
from pharos_editor.ui.widgets.heart_checkbox import HeartCheckbox
from pharos_editor.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from pharos_editor.ui.widgets.sticker_corner import (
    add_sticker_corner,
    remove_sticker_corner,
)


# ---------------------------------------------------------------------------
# Demo card catalog
# ---------------------------------------------------------------------------

# Each card binds a sticker glyph + display label + demo id. The demo id is
# what gets forwarded to the ``on_open_demo`` callback; the editor shell
# resolves it to ``examples/hello_<demo_id>.py`` when opening the file.
DEMO_CARDS: tuple[dict[str, str], ...] = (
    {"demo_id": "ragdoll", "sticker": "fox",       "glyph": "fx", "label": "ragdoll"},
    {"demo_id": "rope",    "sticker": "bunny",     "glyph": "bn", "label": "rope"},
    {"demo_id": "studio",  "sticker": "butterfly", "glyph": "bf", "label": "studio"},
)


# ---------------------------------------------------------------------------
# Theme swatch row
# ---------------------------------------------------------------------------

# (theme_id, two-letter swatch code) — order matches the design doc layout.
THEME_SWATCHES: tuple[tuple[str, str], ...] = (
    ("teengirl_notebook",  "TG"),
    ("cozy_diary",         "CD"),
    ("bullet_journal",     "BJ"),
    ("scrapbook_summer",   "SS"),
    ("cottagecore_garden", "CG"),
    ("kawaii_planner",     "KP"),
)


# Layout-preset chooser row — pair each preset id with a 2-character
# sticker label. Order matches :data:`layout_presets.PRESETS`.
LAYOUT_PRESETS: tuple[tuple[str, str], ...] = (
    ("default",     "DF"),
    ("wide_code",   "WC"),
    ("focus",       "FO"),
    ("triple_pane", "TP"),
    ("compact",     "CP"),
)


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


class NotebookWelcome:
    """First-run / splash screen styled as a diary's front cover.

    Shows once on first launch (controlled by ``settings.ui.welcome_shown``).
    User can re-open via Help → Welcome menu or
    :meth:`EditorShell.show_welcome`.

    Parameters
    ----------
    settings:
        The editor's :class:`UISettings` block. The welcome modal reads
        ``welcome_shown`` to decide whether to auto-display on launch
        and writes the field back when the user ticks the hide checkbox.
    on_start_blank:
        Zero-arg callback invoked when the user clicks the
        ``"Start drawing!"`` button. The shell typically wires this to
        ``Engine.new_scene()`` followed by :meth:`dismiss`.
    on_open_demo:
        Callback invoked with the demo id (``"ragdoll"``, ``"rope"``,
        ``"studio"``) when the user clicks one of the sticker demo
        cards. The shell resolves the id to the appropriate
        ``examples/hello_<id>.py`` script.
    on_dismiss:
        Zero-arg callback fired whenever the welcome panel closes —
        either via the hide-checkbox, a card click, or the start
        button. The shell typically uses this to delete the modal
        window tag from DPG.
    """

    TITLE = "Welcome"
    WIDTH = 600
    HEIGHT = 500
    SPARKLE_CREATURE_ID = "sparkle"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 600
    MIN_HEIGHT: int = 500

    def __init__(
        self,
        settings: Any,
        on_start_blank: Callable[[], None],
        on_open_demo: Callable[[str], None],
        on_dismiss: Callable[[], None],
        on_open_picker: Callable[[], None] | None = None,
        on_pick_layout: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._on_start_blank = validate_callable(
            "on_start_blank", "NotebookWelcome", on_start_blank,
        )
        self._on_open_demo = validate_callable(
            "on_open_demo", "NotebookWelcome", on_open_demo,
        )
        self._on_dismiss = validate_callable(
            "on_dismiss", "NotebookWelcome", on_dismiss,
        )
        # ``on_pick_layout`` lets the welcome screen surface a 5-button
        # layout-preset chooser above the theme swatches. Optional — the
        # row falls back to a no-op when no callback is supplied.
        self._on_pick_layout: Callable[[str], None] | None = (
            validate_callable(
                "on_pick_layout", "NotebookWelcome", on_pick_layout,
            )
            if on_pick_layout is not None
            else None
        )
        # ``on_open_picker`` opens the project picker modal — wired by the
        # shell so the welcome screen has a dedicated "Open a notebook"
        # button above the demo cards. Optional so existing callers that
        # don't yet have a project subsystem keep working.
        self._on_open_picker: Callable[[], None] | None = (
            validate_callable(
                "on_open_picker", "NotebookWelcome", on_open_picker,
            )
            if on_open_picker is not None
            else None
        )

        # Theme snapshot — refreshed when the user picks a swatch.
        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        # DPG state
        self._panel_tag = f"notebook_welcome_{id(self)}"
        self._sticker_handles: list[str] = []
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # The heart-checkbox is constructed up front so tests can flip it
        # without having to first call ``build``. The callback writes the
        # new value through to the bound :class:`UISettings`.
        self._hide_checkbox = HeartCheckbox(
            label="Don't show this again",
            value=bool(getattr(settings, "welcome_shown", False)),
            callback=self._on_hide_toggle,
        )

        # Scheduler hook — set via :meth:`bind_creature_scheduler`. When
        # bound the welcome panel calls ``scheduler.trigger("sparkle",
        # "twinkle")`` once per 4-second sparkle cycle so the header
        # drifts a tiny twinkle animation.
        self._scheduler: Any | None = None
        # Track the count of triggers fired during the panel's lifetime so
        # tests can assert "the sparkle creature was animated at least once
        # since build" without a wall-clock dependency.
        self._sparkle_trigger_count: int = 0

    # ------------------------------------------------------------------
    # Theme + scheduler wiring
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()

    def bind_creature_scheduler(self, scheduler: Any | None) -> None:
        """Attach a :class:`CreatureScheduler` (or detach with ``None``).

        Once bound, :meth:`tick_sparkle` will route through the
        scheduler so the header's sparkle creature drifts on cue.
        """
        self._scheduler = scheduler

    def tick_sparkle(self) -> bool:
        """Pulse the sparkle twinkle on the bound scheduler.

        The sparkle creature ships an always-on ``twinkle`` *idle*
        animation rather than a trigger animation (sparkle is a
        decoration motif, not an event creature). We therefore try the
        trigger path first — themes that ship a trigger-flavoured
        sparkle variant pick this up — and fall back to confirming the
        sparkle is registered as an idle creature.

        Returns ``True`` whenever the scheduler acknowledged the pulse
        (either a trigger fired or the sparkle is at least registered),
        ``False`` otherwise. The editor's render loop pulses this every
        4 seconds while the welcome panel is visible.
        """
        if self._scheduler is None:
            return False
        ok = False
        # Trigger path — succeeds when a trigger anim is declared.
        try:
            ok = bool(
                self._scheduler.trigger(self.SPARKLE_CREATURE_ID, "twinkle"),
            )
        except LookupError:
            # No trigger declared — fall through to the idle-presence path.
            ok = False
        except Exception:
            ok = False
        # Idle-presence path — the sparkle's ``twinkle`` is an idle anim
        # on the canonical built-in, so registration alone counts as a
        # successful pulse for the looping decoration.
        if not ok:
            try:
                ids = list(self._scheduler.registered_ids)
            except Exception:
                ids = []
            if self.SPARKLE_CREATURE_ID in ids:
                ok = True
        if ok:
            self._sparkle_trigger_count += 1
        return ok

    @property
    def sparkle_trigger_count(self) -> int:
        return self._sparkle_trigger_count

    # ------------------------------------------------------------------
    # First-run gate
    # ------------------------------------------------------------------

    def is_first_run(self) -> bool:
        """Return ``True`` if the welcome panel has never been dismissed."""
        return not bool(getattr(self._settings, "welcome_shown", False))

    def mark_seen(self) -> None:
        """Persist that the user has dismissed the welcome panel."""
        try:
            self._settings.welcome_shown = True
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Build / dismiss
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Render the welcome modal under *parent_tag*.

        Safe to call when ``dearpygui`` is missing — every DPG call is
        guarded so the panel still registers its callbacks for tests.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str("parent_tag", "NotebookWelcome.build", parent_tag)
        self._parent_tag = parent_tag
        self._built = True

        dpg = _safe_dpg()
        if dpg is None:
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        paper = list(self._theme.color("paper", (250, 246, 235, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                width=self.WIDTH,
                height=self.HEIGHT,
                border=True,
            ):
                # Sticker corners — TL sparkle + BR heart.
                try:
                    handle_tl = add_sticker_corner(
                        self._panel_tag, "sparkle", "TL",
                    )
                    self._sticker_handles.append(handle_tl)
                except Exception:
                    pass
                try:
                    handle_br = add_sticker_corner(
                        self._panel_tag, "heart", "BR",
                    )
                    self._sticker_handles.append(handle_br)
                except Exception:
                    pass

                # Header row — the big handwritten title.
                try:
                    dpg.add_text(
                        "* Pharos *", color=accent, tag=f"{self._panel_tag}_header",
                    )
                except Exception:
                    pass
                try:
                    dpg.add_text(
                        "(a teeny game-making notebook)",
                        color=ink,
                        tag=f"{self._panel_tag}_subtitle",
                    )
                except Exception:
                    pass

                # ── Open existing notebook (project picker) ───────
                # Shown ABOVE the demo cards on first run so users with
                # an existing project can jump straight to it without
                # going through a demo first.
                if self._on_open_picker is not None:
                    try:
                        dpg.add_button(
                            label="Open a notebook...",
                            width=-1,
                            height=32,
                            callback=self._on_open_picker_clicked,
                            tag=f"{self._panel_tag}_open_picker_btn",
                        )
                    except Exception:
                        pass

                # ── Demo card row ─────────────────────────────────
                try:
                    with dpg.group(
                        horizontal=True, tag=f"{self._panel_tag}_cards",
                    ):
                        for card in DEMO_CARDS:
                            self._build_demo_card(dpg, card, ink, accent)
                except Exception:
                    # Stub DPG without context-manager group support —
                    # flatten the call path.
                    for card in DEMO_CARDS:
                        self._build_demo_card(dpg, card, ink, accent)

                # Doodle separator
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=washi,
                        tag=f"{self._panel_tag}_sep1",
                    )
                except Exception:
                    pass

                # ── Start drawing button ──────────────────────────
                try:
                    dpg.add_text(
                        "Start a blank notebook:", color=ink,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="+ New Scene",
                        width=-1,
                        height=36,
                        callback=self._on_start_blank_clicked,
                        tag=f"{self._panel_tag}_start_btn",
                    )
                except Exception:
                    pass

                # Doodle separator
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=washi,
                        tag=f"{self._panel_tag}_sep2",
                    )
                except Exception:
                    pass

                # ── Layout preset row ──────────────────────────────
                # Five sticker buttons matching :data:`LAYOUT_PRESETS`.
                if self._on_pick_layout is not None:
                    try:
                        dpg.add_text("Pick a layout:", color=ink)
                    except Exception:
                        pass
                    try:
                        with dpg.group(
                            horizontal=True,
                            tag=f"{self._panel_tag}_layouts",
                        ):
                            for layout_id, label in LAYOUT_PRESETS:
                                self._build_layout_button(dpg, layout_id, label)
                    except Exception:
                        for layout_id, label in LAYOUT_PRESETS:
                            self._build_layout_button(dpg, layout_id, label)

                # ── Theme swatch row ──────────────────────────────
                try:
                    dpg.add_text("Or pick a theme:", color=ink)
                except Exception:
                    pass
                try:
                    with dpg.group(
                        horizontal=True, tag=f"{self._panel_tag}_swatches",
                    ):
                        for theme_id, swatch_code in THEME_SWATCHES:
                            self._build_theme_swatch(dpg, theme_id, swatch_code)
                except Exception:
                    for theme_id, swatch_code in THEME_SWATCHES:
                        self._build_theme_swatch(dpg, theme_id, swatch_code)

                # ── Hide checkbox ────────────────────────────────
                try:
                    self._hide_checkbox.build(self._panel_tag)
                except Exception:
                    pass
        except Exception:
            # Final fallback so the panel still registers a title.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_demo_card(
        self,
        dpg: Any,
        card: dict[str, str],
        ink: list[int],
        accent: list[int],
    ) -> None:
        """Render a single sticker-card column for the demo trio."""
        demo_id = card["demo_id"]
        glyph = card["glyph"]
        label = card["label"]
        card_tag = f"{self._panel_tag}_card_{demo_id}"
        try:
            with dpg.group(tag=card_tag):
                try:
                    dpg.add_text(glyph, color=accent)
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label=label,
                        width=120,
                        height=36,
                        callback=(
                            lambda *_a, d=demo_id: self._on_demo_card_clicked(d)
                        ),
                        tag=f"{card_tag}_btn",
                    )
                except Exception:
                    pass
        except Exception:
            # Stub DPG path — flat button only.
            try:
                dpg.add_button(
                    label=label,
                    callback=(
                        lambda *_a, d=demo_id: self._on_demo_card_clicked(d)
                    ),
                    tag=f"{card_tag}_btn",
                )
            except Exception:
                pass

    def _build_theme_swatch(self, dpg: Any, theme_id: str, swatch_code: str) -> None:
        """Render a single 32×32 swatch in the theme row."""
        swatch_tag = f"{self._panel_tag}_swatch_{theme_id}"
        try:
            dpg.add_button(
                label=f"[{swatch_code}]",
                width=32,
                height=32,
                callback=(
                    lambda *_a, t=theme_id: self._on_theme_swatch_clicked(t)
                ),
                tag=swatch_tag,
            )
        except Exception:
            pass

    def _build_layout_button(self, dpg: Any, layout_id: str, label: str) -> None:
        """Render a single 36×32 layout-preset sticker button."""
        button_tag = f"{self._panel_tag}_layout_{layout_id}"
        try:
            dpg.add_button(
                label=f"[{label}]",
                width=36,
                height=32,
                callback=(
                    lambda *_a, lid=layout_id: self._on_layout_button_clicked(lid)
                ),
                tag=button_tag,
            )
        except Exception:
            pass

    def dismiss(self) -> None:
        """Hide the welcome panel and run cleanup.

        Removes sticker corners, fires the ``on_dismiss`` callback, and
        deletes the panel's DPG window. Safe to call before / after
        :meth:`build` — the cleanup is idempotent.
        """
        for handle in list(self._sticker_handles):
            try:
                remove_sticker_corner(handle)
            except Exception:
                pass
        self._sticker_handles.clear()

        dpg = _safe_dpg()
        if dpg is not None:
            try:
                if dpg.does_item_exist(self._panel_tag):
                    dpg.delete_item(self._panel_tag)
            except Exception:
                pass

        try:
            self._on_dismiss()
        except Exception:
            pass
        self._built = False

    def destroy(self) -> None:
        """Tear down the panel — drop theme listener + sticker handles."""
        unregister_theme_listener(self._on_theme_changed)
        self.dismiss()

    # ------------------------------------------------------------------
    # Callback handlers
    # ------------------------------------------------------------------

    def _on_start_blank_clicked(self, *_: Any) -> None:
        try:
            self._on_start_blank()
        except Exception:
            pass
        self.mark_seen()
        self.dismiss()

    def _on_open_picker_clicked(self, *_: Any) -> None:
        """"Open a notebook" button — hand off to the project picker."""
        if self._on_open_picker is None:
            return
        try:
            self._on_open_picker()
        except Exception:
            pass
        # Mark seen + dismiss so the welcome screen doesn't pop on top
        # of the picker once the picker resolves a project.
        self.mark_seen()
        self.dismiss()

    def _on_demo_card_clicked(self, demo_id: str) -> None:
        validate_non_empty_str(
            "demo_id", "NotebookWelcome._on_demo_card_clicked", demo_id,
        )
        try:
            self._settings.last_opened_demo = demo_id
        except Exception:
            pass
        try:
            self._on_open_demo(demo_id)
        except Exception:
            pass
        self.mark_seen()
        self.dismiss()

    def _on_theme_swatch_clicked(self, theme_id: str) -> None:
        validate_non_empty_str(
            "theme_id", "NotebookWelcome._on_theme_swatch_clicked", theme_id,
        )
        try:
            from pharos_editor.ui.theme import apply_theme

            apply_theme(theme_id)
        except Exception:
            pass
        self.mark_seen()
        self.dismiss()

    def _on_layout_button_clicked(self, layout_id: str) -> None:
        validate_non_empty_str(
            "layout_id", "NotebookWelcome._on_layout_button_clicked", layout_id,
        )
        if self._on_pick_layout is None:
            return
        try:
            self._on_pick_layout(layout_id)
        except Exception:
            pass
        self.mark_seen()
        self.dismiss()

    def _on_hide_toggle(self, value: Any) -> None:
        """HeartCheckbox callback — pushes the new value into UISettings."""
        try:
            self._settings.welcome_shown = bool(value)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests)
    # ------------------------------------------------------------------

    @property
    def panel_tag(self) -> str:
        return self._panel_tag

    @property
    def demo_card_ids(self) -> list[str]:
        """Return the demo ids in render order."""
        return [c["demo_id"] for c in DEMO_CARDS]

    @property
    def theme_swatch_ids(self) -> list[str]:
        """Return the theme ids in render order."""
        return [tid for tid, _ in THEME_SWATCHES]

    @property
    def layout_preset_ids(self) -> list[str]:
        """Return the layout preset ids in render order."""
        return [lid for lid, _ in LAYOUT_PRESETS]

    @property
    def hide_checkbox(self) -> HeartCheckbox:
        return self._hide_checkbox


__all__ = [
    "DEMO_CARDS",
    "LAYOUT_PRESETS",
    "NotebookWelcome",
    "THEME_SWATCHES",
]
