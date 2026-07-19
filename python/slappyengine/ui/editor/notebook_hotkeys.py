"""``NotebookHotkeys`` — global hotkey table for the notebook editor.

A self-contained registry of editor-wide keyboard shortcuts. Each entry
maps a canonical key string (e.g. ``"ctrl+shift+f"``) to an editor
command id (e.g. ``"editor.easter_feed_fox"``). A dispatcher callable
supplied at construction time is invoked with the command id whenever a
key press resolves to a known binding.

Two playful "easter-egg" entries (Ctrl+Shift+F / Ctrl+Shift+B) only fire
when ``settings.ui.easter_eggs`` is ``True`` and the host has supplied a
:class:`CreatureScheduler` via :meth:`set_creature_scheduler`. When the
gates aren't met the dispatcher still receives the command id so the
binding remains visible to UI hint surfaces, but the underlying
``scheduler.trigger`` call is suppressed.

Headless safety
---------------
The class never imports ``dearpygui`` at module load. :meth:`install`
attempts to register a DPG handler registry but degrades to a no-op on
the headless / CI codepath; tests drive :meth:`handle_key_event`
directly so coverage is independent of DPG.

Design provenance
-----------------

* ``docs/ui_pattern_audit_2026_06_03.md`` §4.3 (gap: documented keyboard
  shortcuts that were never bound in Nova3D).
* ``docs/theme_teengirl_notebook_2026_06_03.md`` §7 (easter-egg roster
  + gating contract).
"""
from __future__ import annotations

from typing import Any, Callable

from slappyengine._validation import (
    validate_bool,
    validate_callable,
    validate_non_empty_str,
    validate_str,
)


# ---------------------------------------------------------------------------
# Canonical bindings — frozen for the public API surface
# ---------------------------------------------------------------------------


# Easter-egg command ids — collected here so the gating check can refer
# to a single source of truth instead of string-matching.
_EASTER_EGG_COMMANDS: frozenset[str] = frozenset({
    "editor.easter_feed_fox",
    "editor.easter_baby_porcupine_roll",
})


# Easter-egg command -> (creature_id, trigger_anim_name). The hotkey
# handler routes through CreatureScheduler.trigger when these fire.
_EASTER_EGG_TRIGGERS: dict[str, tuple[str, str]] = {
    "editor.easter_feed_fox":             ("fox_01",       "feed"),
    "editor.easter_baby_porcupine_roll":  ("porcupine_01", "ball_up"),
}


_BINDINGS_FROZEN: dict[str, str] = {
    "ctrl+s":         "editor.save",
    "ctrl+z":         "editor.undo",
    "ctrl+y":         "editor.redo",
    "ctrl+n":         "editor.new",
    "ctrl+o":         "editor.open",
    "f1":             "editor.help",
    "f3":             "editor.profiler_toggle",
    "f5":             "editor.run",
    "f11":            "editor.toggle_fullscreen",
    "s":              "editor.tool_select",
    "t":              "editor.tool_move",
    "r":              "editor.tool_rotate",
    "c":              "editor.tool_scale",
    "h":              "editor.toggle_hud",
    "ctrl+shift+f":   "editor.easter_feed_fox",
    "ctrl+shift+b":   "editor.easter_baby_porcupine_roll",
    # ── Layout presets ────────────────────────────────────────────────
    "ctrl+1":         "editor.layout_preset_default",
    "ctrl+2":         "editor.layout_preset_wide_code",
    "ctrl+3":         "editor.layout_preset_focus",
    "ctrl+4":         "editor.layout_preset_triple_pane",
    "ctrl+5":         "editor.layout_preset_compact",
    "ctrl+0":         "editor.reset_layout",
    # ── Theme switcher ───────────────────────────────────────────────
    "ctrl+t":         "editor.toggle_theme_switcher",
    "ctrl+shift+t":   "editor.cycle_theme",
    # ── Panel toggles ────────────────────────────────────────────────
    "ctrl+\\":        "editor.toggle_panel_outliner",
    "ctrl+shift+\\":  "editor.toggle_panel_inspector",
    "ctrl+/":         "editor.toggle_panel_content_browser",
    "ctrl+shift+/":   "editor.toggle_panel_code",
}


# Ordered list of modifier tokens — used by :func:`_normalize_key` to
# emit a canonical "ctrl+shift+alt+<key>" form regardless of caller order.
_MODIFIER_ORDER: tuple[str, ...] = ("ctrl", "shift", "alt")


def _normalize_key(key: str, mods: list[str] | None = None) -> str:
    """Return the canonical ``ctrl+shift+alt+<key>`` form for a key event.

    Lower-cases every token, drops duplicates, and reorders modifiers so
    callers can pass ``["Shift", "Ctrl"]`` and still hit the
    ``"ctrl+shift+..."`` keys in :data:`_BINDINGS_FROZEN`.
    """
    tokens: list[str] = []
    if mods:
        seen: set[str] = set()
        for m in mods:
            if not isinstance(m, str):
                continue
            ml = m.strip().lower()
            if not ml or ml in seen:
                continue
            seen.add(ml)
        # Emit modifiers in canonical order.
        for m in _MODIFIER_ORDER:
            if m in seen:
                tokens.append(m)
    base = key.strip().lower()
    if not base:
        return "+".join(tokens) if tokens else ""
    # Accept either "ctrl+s" or "s" with mods=["ctrl"].
    if "+" in base and not tokens:
        # The caller already passed a composite key; re-normalise it via
        # split + recurse so the same canonical form is produced.
        parts = [p.strip().lower() for p in base.split("+") if p.strip()]
        mods_only = [p for p in parts if p in _MODIFIER_ORDER]
        non_mods = [p for p in parts if p not in _MODIFIER_ORDER]
        if non_mods:
            # Last non-mod is the "real" key; rest get folded into mods.
            return _normalize_key(non_mods[-1], mods_only + non_mods[:-1])
        return "+".join(mods_only)
    tokens.append(base)
    return "+".join(tokens)


# ---------------------------------------------------------------------------
# NotebookHotkeys
# ---------------------------------------------------------------------------


class NotebookHotkeys:
    """Global hotkey table for the notebook editor.

    Registers with DPG's input handlers; each key dispatches an editor
    command. Some keys have playful "easter egg" overrides gated by
    ``settings.ui.easter_eggs``.

    Parameters
    ----------
    command_dispatcher:
        Callable invoked with the resolved command id on every key
        match. The host (typically :class:`EditorShell`) maps the id to
        a concrete editor action — save / undo / open theme switcher /
        etc.
    easter_eggs:
        Initial value of the easter-egg gate. Defaults to ``True``;
        :class:`EditorShell` overrides this from ``settings.ui``.
    """

    # Class-level mapping — frozen public surface; instances should
    # never mutate it. Tests pin its membership.
    BINDINGS: dict[str, str] = dict(_BINDINGS_FROZEN)

    # Re-export the easter-egg set so tests + UI hints can refer to
    # named members rather than literal strings.
    EASTER_EGG_COMMANDS: frozenset[str] = _EASTER_EGG_COMMANDS

    def __init__(
        self,
        command_dispatcher: Callable[[str], None],
        *,
        easter_eggs: bool = True,
    ) -> None:
        validate_callable(
            "command_dispatcher", "NotebookHotkeys", command_dispatcher,
        )
        self._dispatcher: Callable[[str], None] = command_dispatcher
        self._easter_eggs: bool = validate_bool(
            "easter_eggs", "NotebookHotkeys", easter_eggs,
        )
        # The creature scheduler is bound lazily — the editor shell wires
        # it after ``setup_theme_subsystem`` runs. Easter-egg keys early-
        # exit when no scheduler is bound.
        self._creature_scheduler: Any | None = None
        # Counts for diagnostics + tests.
        self._dispatched_count: int = 0
        self._suppressed_easter_eggs: int = 0
        # DPG handler-registry tag (set by :meth:`install` when DPG
        # exists, ``None`` otherwise).
        self._handler_registry: int | str | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_easter_eggs(self, enabled: bool) -> None:
        """Toggle the easter-egg gate at runtime."""
        self._easter_eggs = validate_bool(
            "enabled", "NotebookHotkeys.set_easter_eggs", enabled,
        )

    def set_creature_scheduler(self, scheduler: Any) -> None:
        """Bind the :class:`CreatureScheduler` easter-egg triggers route through."""
        if scheduler is None:
            raise TypeError(
                "NotebookHotkeys.set_creature_scheduler: scheduler must "
                "not be None"
            )
        self._creature_scheduler = scheduler

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def easter_eggs_enabled(self) -> bool:
        return self._easter_eggs

    @property
    def dispatched_count(self) -> int:
        return self._dispatched_count

    @property
    def suppressed_easter_egg_count(self) -> int:
        return self._suppressed_easter_eggs

    @property
    def handler_registry_tag(self) -> int | str | None:
        return self._handler_registry

    def bindings(self) -> dict[str, str]:
        """Return a shallow copy of the binding table."""
        return dict(self.BINDINGS)

    def command_for(self, key: str, mods: list[str] | None = None) -> str | None:
        """Look up the command id a (key, mods) tuple resolves to."""
        validate_str(
            "key", "NotebookHotkeys.command_for", key, allow_empty=False,
        )
        canon = _normalize_key(key, mods)
        return self.BINDINGS.get(canon)

    # ------------------------------------------------------------------
    # Install / dispatch
    # ------------------------------------------------------------------

    def install(self) -> None:
        """Register the hotkey table with DPG's global handler registry.

        Headless-safe: no-ops when ``dearpygui`` is not installed.
        Production calls this once from :meth:`EditorShell.setup`; tests
        drive :meth:`handle_key_event` directly.
        """
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except Exception:
            self._handler_registry = None
            return
        try:
            with dpg.handler_registry() as reg:
                # DPG fires the same callback for every key; the callback
                # converts the integer key code to a canonical string and
                # routes through :meth:`handle_key_event`.
                dpg.add_key_press_handler(
                    callback=lambda s, app_data, *_:
                        self._on_dpg_key_press(app_data),
                )
            self._handler_registry = reg
        except Exception:
            self._handler_registry = None

    def _on_dpg_key_press(self, key_code: Any) -> None:
        """Translate a DPG key-press event into a :meth:`handle_key_event` call."""
        try:
            import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
        except Exception:
            return
        try:
            # DPG 2.x renamed mvKey_Control/Shift/Alt → mvKey_Mod{Ctrl,Shift,Alt}
            _ctrl = getattr(dpg, "mvKey_ModCtrl", None) or getattr(dpg, "mvKey_Control", None)
            _shift = getattr(dpg, "mvKey_ModShift", None) or getattr(dpg, "mvKey_Shift", None)
            _alt = getattr(dpg, "mvKey_ModAlt", None) or getattr(dpg, "mvKey_Alt", None)
            mods: list[str] = []
            if _ctrl is not None and dpg.is_key_down(_ctrl):
                mods.append("ctrl")
            if _shift is not None and dpg.is_key_down(_shift):
                mods.append("shift")
            if _alt is not None and dpg.is_key_down(_alt):
                mods.append("alt")
            # Translate the integer key code via the dpg constants by
            # consulting the lower-case binding table — anything we can't
            # name falls back to chr() for the letter keys.
            name = _key_code_to_name(key_code)
            if name:
                self.handle_key_event(name, mods)
        except Exception:
            pass

    def handle_key_event(self, key: str, mods: list[str]) -> bool:
        """Resolve and dispatch a single key event.

        Returns ``True`` iff the event matched a binding *and* either
        the dispatcher fired without raising or the easter-egg gate
        suppressed the call gracefully. ``False`` means the event did
        not match any binding (the caller can chain to other handlers).
        """
        validate_str(
            "key", "NotebookHotkeys.handle_key_event", key, allow_empty=False,
        )
        if mods is None:
            mods = []
        if not isinstance(mods, list):
            raise TypeError(
                "NotebookHotkeys.handle_key_event: mods must be a list of "
                f"str; got {type(mods).__name__}"
            )
        canon = _normalize_key(key, mods)
        if not canon:
            return False
        command = self.BINDINGS.get(canon)
        if command is None:
            return False
        # Easter-egg gating: the dispatcher is *not* invoked when the
        # gate is closed so the editor can't accidentally execute the
        # mascot trigger via a bound text widget.
        if command in self.EASTER_EGG_COMMANDS:
            if not self._easter_eggs:
                self._suppressed_easter_eggs += 1
                return True  # event "handled" — just not acted on
            # Route through the CreatureScheduler.trigger entry point.
            self._fire_easter_egg(command)
        # Always notify the dispatcher (even for easter eggs that just
        # fired) so the host can update UI hints / status bar.
        try:
            self._dispatcher(command)
        except Exception:
            return True
        self._dispatched_count += 1
        return True

    def _fire_easter_egg(self, command: str) -> None:
        """Route an easter-egg command to ``CreatureScheduler.trigger``.

        Silently no-ops when no scheduler is bound or the underlying
        trigger raises (e.g. the host's creature roster does not declare
        the named animation).
        """
        if self._creature_scheduler is None:
            return
        try:
            creature_id, anim_name = _EASTER_EGG_TRIGGERS[command]
        except KeyError:
            return
        trigger = getattr(self._creature_scheduler, "trigger", None)
        if trigger is None:
            return
        try:
            trigger(creature_id, anim_name)
        except Exception:
            # Missing animation -> swallow; the dispatcher still fires.
            pass


# ---------------------------------------------------------------------------
# DPG key-code -> canonical name (lazy, only consulted in the DPG path)
# ---------------------------------------------------------------------------


def _key_code_to_name(code: Any) -> str | None:
    """Return the canonical lower-case key name for *code* (best-effort).

    Handles the alphanumeric keys we bind plus the F1 / F3 / F5 / F11
    function keys and the Esc / Tab control keys. Anything else returns
    ``None`` so :meth:`NotebookHotkeys.handle_key_event` falls through.
    """
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    # Map of dpg constant -> canonical name.
    mapping: dict[int, str] = {}
    try:
        for letter in "abcdefghijklmnopqrstuvwxyz":
            const = getattr(dpg, f"mvKey_{letter.upper()}", None)
            if isinstance(const, int):
                mapping[const] = letter
        for digit in "0123456789":
            const = getattr(dpg, f"mvKey_{digit}", None)
            if isinstance(const, int):
                mapping[const] = digit
        for fk in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
                   "F9", "F10", "F11", "F12"):
            const = getattr(dpg, f"mvKey_{fk}", None)
            if isinstance(const, int):
                mapping[const] = fk.lower()
    except Exception:
        return None
    try:
        return mapping.get(int(code))
    except Exception:
        return None


__all__ = ["NotebookHotkeys"]
