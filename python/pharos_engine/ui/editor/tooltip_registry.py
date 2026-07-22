"""``TooltipRegistry`` — centralized hover-tooltip registry for the notebook editor.

The notebook editor peppered its buttons / toggles / sliders with helpful
labels but never surfaced the explanatory copy. The
Nova3D-nesting-audit sprint plan calls out hover tooltips as a top
usability polish item; this module owns the copy in one place so
translators, docs generators, and the DPG hover-hooks all read from a
single source of truth.

Design goals
------------

* Zero-import DPG — the registry is a plain dict wrapper and can be
  constructed, filled, and introspected in headless tests.
* ``install_dpg_hover`` walks the registry and adds a ``dpg.add_tooltip``
  child for every registered widget tag; missing widgets are silently
  skipped so the caller can register speculatively.
* Tooltips render in the handwritten font (the theme's ``handwritten``
  face when available) after a 500ms hover delay — matching the
  Windows accessibility default.

Handwritten font selection is best-effort: if the notebook theme exposes
``handwritten_font`` we bind it, else the DPG default is used and the
tooltip is still visible.

Provenance: ``docs/ui_pattern_audit_2026_06_03.md`` §7.1 (tooltip audit)
and ``docs/sprint_plan_2026_06_03.md`` §"usability polish".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from pharos_engine._validation import (
    validate_int,
    validate_non_empty_str,
    validate_str,
)


DEFAULT_DELAY_MS: int = 500


@dataclass(frozen=True)
class TooltipEntry:
    """One registered tooltip — the widget tag, the copy, the delay."""

    widget_tag: str
    text: str
    delay_ms: int = DEFAULT_DELAY_MS


class TooltipRegistry:
    """Centralized tooltip-copy registry keyed by DPG widget tag.

    The registry stores every hover-tooltip the notebook editor wants to
    show. It exposes a single :meth:`register` mutator plus an
    :meth:`install_dpg_hover` sink that walks the table and attaches
    ``dpg.add_tooltip`` children to each tag.

    The registry deliberately does not import ``dearpygui`` at module
    level so headless tests can construct + introspect it without a GUI.
    """

    #: Font-tag the tooltip prefers when the notebook theme's handwritten
    #: font is registered under this name. Falls back to the DPG default.
    HANDWRITTEN_FONT_TAG: str = "notebook_handwritten_font"

    def __init__(self) -> None:
        self._entries: dict[str, TooltipEntry] = {}
        self._installed_tooltip_tags: list[str] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(
        self,
        widget_tag: str,
        text: str,
        delay_ms: int = DEFAULT_DELAY_MS,
    ) -> None:
        """Register hover-text *text* for the widget with tag *widget_tag*.

        Later ``register`` calls with the same widget_tag overwrite the
        previous entry so callers can adjust copy without unregistering
        first.

        Parameters
        ----------
        widget_tag:
            The DPG tag string of the widget the tooltip attaches to.
            Non-empty.
        text:
            The hover-tooltip body. Non-empty.
        delay_ms:
            Milliseconds the pointer must dwell before the tooltip fires.
            Defaults to :data:`DEFAULT_DELAY_MS` (500ms).
        """
        validate_non_empty_str("widget_tag", "TooltipRegistry.register", widget_tag)
        validate_non_empty_str("text", "TooltipRegistry.register", text)
        validate_int("delay_ms", "TooltipRegistry.register", delay_ms)
        if delay_ms < 0:
            raise ValueError(
                "TooltipRegistry.register: delay_ms must be >= 0; "
                f"got {delay_ms}"
            )
        self._entries[widget_tag] = TooltipEntry(
            widget_tag=widget_tag,
            text=text,
            delay_ms=int(delay_ms),
        )

    def unregister(self, widget_tag: str) -> bool:
        """Drop the tooltip registered for *widget_tag* (returns True if removed)."""
        validate_str(
            "widget_tag", "TooltipRegistry.unregister", widget_tag, allow_empty=False,
        )
        return self._entries.pop(widget_tag, None) is not None

    def register_many(self, entries: Iterable[tuple[str, str]]) -> None:
        """Bulk register — each entry is a ``(widget_tag, text)`` tuple."""
        for widget_tag, text in entries:
            self.register(widget_tag, text)

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, widget_tag: object) -> bool:
        return isinstance(widget_tag, str) and widget_tag in self._entries

    def get(self, widget_tag: str) -> TooltipEntry | None:
        """Return the :class:`TooltipEntry` for *widget_tag* (or ``None``)."""
        return self._entries.get(widget_tag)

    def text_for(self, widget_tag: str) -> str | None:
        """Return the tooltip body for *widget_tag* (or ``None``)."""
        entry = self._entries.get(widget_tag)
        return entry.text if entry is not None else None

    def entries(self) -> list[TooltipEntry]:
        """Return a snapshot of every registered :class:`TooltipEntry`."""
        return list(self._entries.values())

    def widget_tags(self) -> list[str]:
        """Return the tag list — order matches insertion (Py 3.7+ dict)."""
        return list(self._entries.keys())

    # ------------------------------------------------------------------
    # DPG installation
    # ------------------------------------------------------------------

    def install_dpg_hover(self, dpg: Any) -> int:
        """Walk the registry and attach a hover-tooltip to every widget.

        Uses ``dpg.add_tooltip(parent=widget_tag, delay=delay_seconds)``
        when the widget exists in DPG's registry (checked via
        ``does_item_exist``). Widgets missing from DPG are skipped so the
        registry can be populated speculatively.

        The installed tooltip carries a child ``add_text`` with the
        registered copy; the handwritten font is bound when available.

        Returns
        -------
        int
            Number of tooltips actually installed. Zero when DPG is
            missing or none of the widget_tags exist yet.
        """
        if dpg is None:
            return 0
        installed = 0
        for entry in self._entries.values():
            widget_tag = entry.widget_tag
            # Skip widgets that haven't been built yet — callers can
            # rerun ``install_dpg_hover`` after the missing panels build.
            try:
                exists = bool(dpg.does_item_exist(widget_tag))
            except Exception:
                exists = False
            if not exists:
                continue

            tooltip_tag = f"tooltip_{widget_tag}"
            try:
                if dpg.does_item_exist(tooltip_tag):
                    dpg.delete_item(tooltip_tag)
            except Exception:
                pass

            # Convert delay_ms → seconds float; DPG's tooltip API uses
            # a fractional-second ``delay`` argument.
            delay_seconds = entry.delay_ms / 1000.0
            try:
                with dpg.tooltip(
                    parent=widget_tag,
                    tag=tooltip_tag,
                    delay=delay_seconds,
                ):
                    try:
                        # Prefer the handwritten font when the notebook
                        # theme has published one under the well-known
                        # tag; else fall back to the default face.
                        if dpg.does_item_exist(self.HANDWRITTEN_FONT_TAG):
                            dpg.add_text(entry.text)
                            try:
                                dpg.bind_item_font(
                                    dpg.last_item(), self.HANDWRITTEN_FONT_TAG,
                                )
                            except Exception:
                                pass
                        else:
                            dpg.add_text(entry.text)
                    except Exception:
                        # Stub DPG without context-manager support —
                        # attempt the flat add_tooltip variant below.
                        raise
                installed += 1
                self._installed_tooltip_tags.append(tooltip_tag)
            except Exception:
                # Flat-call fallback for stub-DPG implementations.
                try:
                    dpg.add_tooltip(parent=widget_tag, tag=tooltip_tag)
                    dpg.add_text(entry.text, parent=tooltip_tag)
                    installed += 1
                    self._installed_tooltip_tags.append(tooltip_tag)
                except Exception:
                    pass
        return installed

    def installed_tooltip_tags(self) -> list[str]:
        """Return every tooltip-child tag :meth:`install_dpg_hover` created."""
        return list(self._installed_tooltip_tags)


# ---------------------------------------------------------------------------
# Canonical tooltip copy — one place for every notebook editor tooltip.
# ---------------------------------------------------------------------------


#: Canonical copy — (widget_tag, tooltip_text) pairs covering every button /
#: toggle / slider across the notebook editor's panels. Kept module-level so
#: ``build_default_registry`` can materialise a filled registry in one call.
DEFAULT_TOOLTIPS: tuple[tuple[str, str], ...] = (
    # ── Toolbar ────────────────────────────────────────────────────────
    ("notebook_toolbar_new",       "Start a fresh notebook page (Ctrl+N)"),
    ("notebook_toolbar_open",      "Open a scene from disk (Ctrl+O)"),
    ("notebook_toolbar_save",      "Save the current scene (Ctrl+S)"),
    ("notebook_toolbar_run",       "Preview the scene in play mode (F5)"),
    ("notebook_toolbar_undo",      "Undo the last change (Ctrl+Z)"),
    ("notebook_toolbar_redo",      "Redo the last undone change (Ctrl+Y)"),
    ("notebook_toolbar_move",      "Move-tool: drag entities around (T)"),
    ("notebook_toolbar_rotate",    "Rotate-tool: spin the selection (R)"),
    ("notebook_toolbar_scale",     "Scale-tool: resize the selection (C)"),
    ("notebook_toolbar_select",    "Select-tool: pick entities (S)"),
    ("notebook_toolbar_help",      "Open the field-guide help window (F1)"),
    # ── Outliner ───────────────────────────────────────────────────────
    ("notebook_outliner_search",   "Filter entries by name or type"),
    ("notebook_outliner_visibility",
        "Toggle whether this entity draws"),
    ("notebook_outliner_lock",     "Lock this entity so it can't be moved"),
    # ── Content browser ────────────────────────────────────────────────
    ("notebook_cb_search",         "Find a page in the notebook"),
    ("notebook_cb_breadcrumb",     "Navigate up to a parent folder"),
    # ── Spawn menu ─────────────────────────────────────────────────────
    ("notebook_spawn_summon",      "Summon this creature into the scene"),
    ("notebook_spawn_recent",      "Recently used spawn cards"),
    # ── Inspector ──────────────────────────────────────────────────────
    ("notebook_inspector_reset",   "Reset this field to its default value"),
    ("notebook_inspector_delete",  "Delete the selected entity (Del)"),
    # ── Diary / code panel ─────────────────────────────────────────────
    ("notebook_code_run",          "Run the current script (F5)"),
    ("notebook_code_format",       "Format the code with the notebook's style"),
    # ── Telemetry / post-process / animation ───────────────────────────
    ("notebook_telemetry_pause",   "Pause the telemetry stream"),
    ("notebook_telemetry_clear",   "Clear the recorded telemetry"),
    ("notebook_post_process_apply", "Apply the current post-process chain"),
    ("notebook_animation_play",    "Play the animation timeline"),
    ("notebook_animation_loop",    "Loop the animation on play"),
)


def build_default_registry() -> TooltipRegistry:
    """Return a :class:`TooltipRegistry` pre-filled with :data:`DEFAULT_TOOLTIPS`.

    Callers that need every notebook-editor tooltip in one call get a
    ready-to-``install_dpg_hover`` registry back. Additional
    per-panel tooltips can then be layered on via :meth:`register`.
    """
    registry = TooltipRegistry()
    for widget_tag, text in DEFAULT_TOOLTIPS:
        registry.register(widget_tag, text)
    return registry


def register_widget_tooltip(
    registry: TooltipRegistry,
    widget_tag: str,
    text: str,
    delay_ms: int = DEFAULT_DELAY_MS,
) -> None:
    """Convenience wrapper — validate + register a single tooltip."""
    registry.register(widget_tag, text, delay_ms=delay_ms)


#: Public alias used by :mod:`pharos_engine.ui.editor` re-exports.
build_default_tooltip_registry = build_default_registry


__all__ = [
    "DEFAULT_DELAY_MS",
    "DEFAULT_TOOLTIPS",
    "TooltipEntry",
    "TooltipRegistry",
    "build_default_registry",
    "build_default_tooltip_registry",
    "register_widget_tooltip",
]
