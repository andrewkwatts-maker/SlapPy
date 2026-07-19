"""Notebook Inspector — property inspector reskinned as a field-journal entry.

The :class:`NotebookInspector` is a presentation sibling of
:class:`slappyengine.ui.editor.property_inspector.PropertyInspector`. It
reflects any Python object (dataclass or plain ``__dict__``) into the
same three Nova3D sections — **Transform / Properties / References** —
but wraps each section in a :class:`~slappyengine.ui.widgets.WashiPanel`
"field journal" page, swaps drag-floats for
:class:`~slappyengine.ui.widgets.HighlighterSlider` strips, swaps bool
checkboxes for :class:`~slappyengine.ui.widgets.HeartCheckbox` hearts,
and inserts a :class:`~slappyengine.ui.widgets.DoodleSeparator` between
sections.

Field-to-widget dispatch table::

    float     -> HighlighterSlider (theme-driven highlight colour)
    bool      -> HeartCheckbox
    str       -> input_text with washi-tape underline
    int       -> input_int with handwritten font
    tuple[4]  -> color_picker with sticker preview
    Path      -> input_text + paperclip file-picker button
    dataclass -> nested NotebookInspector inside a sub-panel
    other     -> falls through to ``[?]`` reference row

This module is **presentation only** — it never modifies
``property_inspector.py`` and re-uses its primitive-categorisation
helpers (``TRANSFORM_FIELDS`` / ``_is_engine_object`` / ``_is_primitive``)
so the dispatch contract stays in lock-step.

The widgets contract is the headless-safe Nova3D
``build(parent_tag) -> None`` protocol; every ``dpg.*`` call is wrapped
in ``try/except`` so the inspector still registers its tags and
call-log entries when ``dearpygui`` is missing or stubbed out.
"""
from __future__ import annotations

import dataclasses
import enum
import typing
from pathlib import Path
from typing import Any, Callable

from slappyengine._validation import validate_non_empty_str

# Re-use the existing categorisation contract so the two inspectors
# can never drift apart on which field goes to which section.
from slappyengine.ui.editor.property_inspector import (
    TRANSFORM_FIELDS,
    _is_engine_object,
    _is_float_tuple,
    _is_list_of_int,
    _is_list_of_str,
    _is_primitive,
)
from slappyengine.ui.editor.notebook_inspector_dispatch import (
    InspectorDispatchMixin,
    _DEFAULT_FLOAT_RANGE,
    _SLIDER_RANGES,
    _is_path_value,
    _safe_dpg,
    _slider_range_for,
)


# ---------------------------------------------------------------------------
# Constants — empty-state copy. Slider ranges + dispatch helpers live in
# notebook_inspector_dispatch.py (split 2026-06-07).
# ---------------------------------------------------------------------------

# Empty-state copy.
_EMPTY_HINT = "Select an entity to inspect its properties"
_EMPTY_STICKER = ""

# Notebook ink palette — matches ``notebook_theme.NotebookTheme.PALETTE['ink']``
# so the empty state stays on-theme without importing the theme module at
# top-level (would trigger a soft-import cycle in headless tests).
_INK_COLOR: tuple[int, int, int, int] = (40, 40, 60, 255)
_STICKER_COLOR: tuple[int, int, int, int] = (120, 80, 40, 255)
_MUTED_INK: tuple[int, int, int, int] = (90, 90, 110, 255)

# Empty-state banner labels — polished BBB7 version now shows engine +
# project info instead of only the "pick a critter" placeholder.
_ENGINE_BANNER_LABEL = "SlapPyEngine"
_PROJECT_BANNER_LABEL = "Project"
_RECENT_ACTIVITY_LABEL = "Recent activity"
_RECENT_ACTIVITY_EMPTY = "(no events yet — start the sim!)"
_RECENT_ACTIVITY_MAX = 5


def _resolve_engine_version() -> str:
    """Return the running engine ``__version__`` (best-effort).

    Isolated so tests can monkeypatch a stable value instead of coupling
    the empty-state text to the actual release string.
    """
    try:
        from slappyengine import __version__ as _v
        return str(_v)
    except Exception:
        return "?"


# Module-level override slot so the editor shell can register the
# currently-open project without the inspector needing a two-way import.
_project_context_override: tuple[str, str] | None = None


def set_project_context(name: str | None, version: str = "") -> None:
    """Register (or clear) the project banner shown in the empty state.

    Passing ``name=None`` clears the override so the banner disappears
    on the next empty-state render.  The editor shell should call this
    on project-open/close; the inspector re-reads the value each time
    it rebuilds the empty state (no listener needed).
    """
    global _project_context_override
    if name is None:
        _project_context_override = None
    else:
        _project_context_override = (str(name), str(version or ""))


def _resolve_project_banner() -> tuple[str, str] | None:
    """Return ``(name, version)`` for the currently-active project, if any.

    Uses the module-level override first (set via
    :func:`set_project_context`); falls back to a best-effort lookup on
    :mod:`slappyengine.projects` and finally returns ``None`` so the
    banner is suppressed rather than showing "Unknown Project".
    """
    if _project_context_override is not None:
        return _project_context_override
    try:
        from slappyengine.projects import get_active_project  # type: ignore[attr-defined]
        proj = get_active_project()
        if proj is None:
            return None
        name = getattr(getattr(proj, "metadata", proj), "name", None)
        version = getattr(getattr(proj, "metadata", proj), "version", None)
        if not name:
            return None
        return str(name), str(version) if version else ""
    except Exception:
        return None


def _resolve_recent_activity(limit: int = _RECENT_ACTIVITY_MAX) -> list[str]:
    """Return up to *limit* recent event labels from ``event_bus.global_bus``.

    The event bus doesn't store history by default, so the inspector
    lazily attaches a bounded ring-buffer subscriber on first read. This
    keeps the empty state useful without leaking listeners across
    inspector instances (the buffer is a module-level singleton).
    """
    buf = _ensure_recent_activity_buffer()
    return list(buf)[-limit:]


# Module-level ring buffer + one-shot subscriber flag so we don't stack
# listeners every time the inspector rebuilds.
_recent_activity_buffer: list[str] = []
_recent_activity_installed: bool = False


def _ensure_recent_activity_buffer() -> list[str]:
    """Install a bounded activity buffer on the global bus, once."""
    global _recent_activity_installed
    if _recent_activity_installed:
        return _recent_activity_buffer
    try:
        from slappyengine.event_bus import global_bus  # type: ignore[attr-defined]

        def _record(evt: Any) -> None:
            try:
                label = getattr(evt, "name", None) or getattr(evt, "label", None) or "event"
            except Exception:
                label = "event"
            _recent_activity_buffer.append(str(label))
            if len(_recent_activity_buffer) > 32:
                # Trim aggressively so long editor sessions don't grow.
                del _recent_activity_buffer[: len(_recent_activity_buffer) - 32]

        # Tap the bus's publish path so every event is recorded.  We
        # wrap the existing ``publish`` rather than subscribing per-topic
        # because we don't know the topic vocabulary in advance.
        _orig_publish = global_bus.publish

        def _tap_publish(event_type: str, **payload: Any):
            evt = _orig_publish(event_type, **payload)
            _record(evt)
            return evt

        # Only install once — the flag guards against re-wrap.
        global_bus.publish = _tap_publish  # type: ignore[assignment]
        _recent_activity_installed = True
    except Exception:
        # Bus missing / unpatchable — silent fallback keeps the empty
        # state working with an empty list.
        pass
    return _recent_activity_buffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_dataclass_value(value: Any) -> bool:
    """Return True for *instances* (not classes) of dataclasses."""
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


# ---------------------------------------------------------------------------
# NotebookInspector
# ---------------------------------------------------------------------------


class NotebookInspector(InspectorDispatchMixin):
    """Property inspector themed as a field-journal entry.

    Three sections: **Transform / Properties / References** — same
    Nova3D contract, just dressed up. Reuses the dispatch helpers from
    :mod:`slappyengine.ui.editor.property_inspector` so dataclass fields
    work for free.

    Parameters
    ----------
    target:
        Optional object to bind at construction time. May be ``None``;
        the empty state then renders the "(no critter selected)" hint.

    Attributes
    ----------
    TITLE:
        Editor shell title — same string the legacy inspector uses so
        the shell's panel dock keeps a single "Inspector" label.
    """

    TITLE = "Inspector"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 280
    MIN_HEIGHT: int = 400

    def __init__(
        self,
        target: Any | None = None,
        *,
        on_field_changed: Callable[[str, Any, Any], None] | None = None,
    ) -> None:
        self._target: Any = target
        self._on_field_changed: Callable[[str, Any, Any], None] | None = on_field_changed
        self._panel_tag: str = f"notebook_inspector_{id(self)}"
        self._transform_tag = f"{self._panel_tag}_transform"
        self._properties_tag = f"{self._panel_tag}_properties"
        self._references_tag = f"{self._panel_tag}_references"
        self._empty_tag = f"{self._panel_tag}_empty"
        self._reflection_tag = f"{self._panel_tag}_reflection"

        # Map of attr-name -> widget root tag.  Tests and the refresh
        # path use it; one entry per built widget.
        self._widget_map: dict[str, str] = {}

        # Held strong-refs to live widget primitives (HeartCheckbox,
        # HighlighterSlider, nested NotebookInspector …) so theme
        # listeners stay registered.
        self._widgets: list[Any] = []
        self._nested: list[NotebookInspector] = []

        # Builder lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Call history for headless test assertions; one tuple per event.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def target(self) -> Any:
        """Return the currently bound target (or ``None``)."""
        return self._target

    def set_target(self, target: Any) -> None:
        """Bind a new target object and refresh the inspector body."""
        self._target = target
        self.call_log.append(("set_target", type(target).__name__ if target is not None else None))
        self.refresh()

    # Legacy PropertyInspector compat — Engine.run_editor() calls set_object.
    def set_object(self, target: Any) -> None:
        """Compat alias for :meth:`set_target`. Mirrors the legacy
        `PropertyInspector.set_object` contract that the engine driver
        calls during boot."""
        self.set_target(target)

    def build(self, parent_tag: int | str) -> None:
        """Materialise the inspector container under *parent_tag*.

        Safe to call when ``dearpygui`` is missing — every DPG call is
        guarded so the inspector still registers its tags for tests.
        """
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                border=False,
                autosize_x=True,
                height=-1,
            ):
                # Hand-written title row — the theme picks the font.
                try:
                    dpg.add_text("Properties", color=[40, 40, 60, 255])
                except Exception:
                    pass
        except Exception:
            # Stub-DPG without context-manager support — flat path.
            try:
                dpg.add_text(
                    "Properties",
                    parent=parent_tag,
                    tag=self._panel_tag,
                )
            except Exception:
                pass

        # Render the body — empty state OR three sections.
        self._render_body(dpg)

    def refresh(self) -> None:
        """Tear down and rebuild the journal body.

        Safe to call before :meth:`build` — becomes a no-op in that case.
        """
        self.call_log.append(("refresh",))
        if not self._built:
            return

        dpg = _safe_dpg()
        if dpg is None:
            # Without DPG there's nothing to wipe; just record the call.
            return

        # Wipe the existing body so we can re-render.
        try:
            if dpg.does_item_exist(self._panel_tag):
                # Note: dearpygui's children_only kwarg avoids deleting
                # our root window — only the contents below the title.
                for tag in (
                    self._transform_tag,
                    self._properties_tag,
                    self._references_tag,
                    self._empty_tag,
                    self._reflection_tag,
                ):
                    try:
                        if dpg.does_item_exist(tag):
                            dpg.delete_item(tag)
                    except Exception:
                        pass
        except Exception:
            pass

        # Drop strong-refs to old widgets so theme listeners can detach.
        for w in self._widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._widgets.clear()
        self._nested.clear()
        self._widget_map.clear()

        self._render_body(dpg)

    # ------------------------------------------------------------------
    # Body renderer — empty state + three section pipelines
    # ------------------------------------------------------------------

    def _render_body(self, dpg: Any) -> None:
        """Build either the empty state, or the three section panels."""
        if self._target is None:
            self._render_empty_state(dpg)
            return

        # Categorise fields — same rules as PropertyInspector._refresh.
        transform_fields: list[tuple[str, Any]] = []
        primitive_fields: list[tuple[str, Any]] = []
        complex_fields: list[tuple[str, Any]] = []

        for name, value in self._iter_fields():
            if name in TRANSFORM_FIELDS:
                transform_fields.append((name, value))
            elif _is_dataclass_value(value):
                # Nested dataclass — render in the References section as
                # a recursive NotebookInspector sub-panel.
                complex_fields.append((name, value))
            elif _is_engine_object(value):
                complex_fields.append((name, value))
            elif _is_primitive(value) or _is_path_value(value):
                primitive_fields.append((name, value))
            else:
                complex_fields.append((name, value))

        # Type header — useful for debugging.
        try:
            dpg.add_text(
                f"Type: {type(self._target).__name__}",
                parent=self._panel_tag,
            )
        except Exception:
            pass

        self._render_section(
            dpg,
            tag=self._transform_tag,
            title="Transform",
            fields=transform_fields,
            separator_style="wavy",
        )
        self._render_section(
            dpg,
            tag=self._properties_tag,
            title="Properties",
            fields=primitive_fields,
            separator_style="dotted",
        )
        self._render_reference_section(
            dpg,
            tag=self._references_tag,
            title="References",
            fields=complex_fields,
        )

    def _render_empty_state(self, dpg: Any) -> None:
        """Render the polished empty state.

        Instead of the bare "pick a critter" placeholder, we now show:

        1. Engine version banner (``SlapPyEngine v0.3.0b0``).
        2. Project banner (``Project: MyGame v0.3.0b0``) — suppressed
           when no project is active.
        3. Recent-activity mini-log (last 5 events from ``global_bus``).
        4. The classic badger sticker hint at the bottom so the
           whimsical theme stays intact.

        All copy uses the notebook ink palette (not gray) so the empty
        state reads as intentional design rather than a stub.
        """
        engine_version = _resolve_engine_version()
        project_banner = _resolve_project_banner()
        recent = _resolve_recent_activity()

        try:
            with dpg.group(parent=self._panel_tag, tag=self._empty_tag):
                # 1. Engine banner.
                dpg.add_text(
                    f"{_ENGINE_BANNER_LABEL} v{engine_version}",
                    color=list(_INK_COLOR),
                )
                # 2. Project banner (best-effort — suppressed if no proj).
                if project_banner is not None:
                    name, version = project_banner
                    label = f"{_PROJECT_BANNER_LABEL}: {name}"
                    if version:
                        label = f"{label} v{version}"
                    dpg.add_text(label, color=list(_MUTED_INK))
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                # 3. Recent-activity mini-log.
                dpg.add_text(
                    _RECENT_ACTIVITY_LABEL, color=list(_INK_COLOR),
                )
                if recent:
                    for item in recent:
                        dpg.add_text(f"  - {item}", color=list(_MUTED_INK))
                else:
                    dpg.add_text(
                        _RECENT_ACTIVITY_EMPTY, color=list(_MUTED_INK),
                    )
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                # 4. Whimsy tail — kept so the field-journal vibe stays.
                dpg.add_text(_EMPTY_STICKER, color=list(_STICKER_COLOR))
                dpg.add_text(_EMPTY_HINT, color=list(_INK_COLOR))
        except Exception:
            try:
                dpg.add_text(
                    f"{_ENGINE_BANNER_LABEL} v{engine_version}",
                    parent=self._panel_tag,
                    tag=self._empty_tag,
                )
                if project_banner is not None:
                    name, version = project_banner
                    dpg.add_text(
                        f"{_PROJECT_BANNER_LABEL}: {name} v{version}".rstrip(),
                        parent=self._panel_tag,
                    )
                dpg.add_text(
                    _RECENT_ACTIVITY_LABEL, parent=self._panel_tag,
                )
                for item in (recent or [_RECENT_ACTIVITY_EMPTY]):
                    dpg.add_text(f"  - {item}", parent=self._panel_tag)
                dpg.add_text(
                    f"{_EMPTY_STICKER} {_EMPTY_HINT}",
                    parent=self._panel_tag,
                )
            except Exception:
                pass
        self.call_log.append(("empty_state",))

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_section(
        self,
        dpg: Any,
        *,
        tag: str,
        title: str,
        fields: list[tuple[str, Any]],
        separator_style: str,
    ) -> None:
        """Wrap *fields* in a washi-taped journal panel followed by a doodle."""
        if not fields:
            return

        # Washi-tape framed panel — theme colours come from active theme.
        from slappyengine.ui.widgets import WashiPanel

        builders: list[Callable[[], None]] = [
            self._make_field_builder(name, value) for name, value in fields
        ]

        try:
            panel = WashiPanel(title=title, children=builders)
            # The WashiPanel builds its own child_window so we just hand
            # it the inspector parent tag.
            panel.build(self._panel_tag)
            # Stash so tests can assert the panel built + theme listeners
            # stay alive.
            self._widgets.append(panel)
            # WashiPanel doesn't accept a custom root_tag, so we record
            # its assigned root under our section tag so refresh can wipe.
            self._widget_map[tag] = panel.root_tag or tag
        except Exception:
            # Headless fallback — just render the section header so
            # tests still see the title text.
            try:
                dpg.add_text(
                    f"-- {title} --",
                    parent=self._panel_tag,
                    tag=tag,
                )
            except Exception:
                pass
            # And run the children directly so their widgets still build.
            for b in builders:
                try:
                    b()
                except Exception:
                    pass

        # Doodle separator after the section.
        self._add_doodle_separator(dpg, separator_style)

    def _render_reference_section(
        self,
        dpg: Any,
        *,
        tag: str,
        title: str,
        fields: list[tuple[str, Any]],
    ) -> None:
        """Render References — includes recursive NotebookInspector sub-panels.

        Each ``dataclass`` field gets a nested NotebookInspector so the
        sub-fields read as their own mini-page within the parent journal.
        Non-dataclass complex fields fall back to the ``[?]`` row pattern.
        """
        if not fields:
            return

        from slappyengine.ui.widgets import WashiPanel

        builders: list[Callable[[], None]] = []
        for name, value in fields:
            builders.append(self._make_reference_builder(name, value))

        try:
            panel = WashiPanel(title=title, children=builders)
            panel.build(self._panel_tag)
            self._widgets.append(panel)
            self._widget_map[tag] = panel.root_tag or tag
        except Exception:
            try:
                dpg.add_text(
                    f"-- {title} --",
                    parent=self._panel_tag,
                    tag=tag,
                )
            except Exception:
                pass
            for b in builders:
                try:
                    b()
                except Exception:
                    pass

    def _add_doodle_separator(self, dpg: Any, style: str) -> None:
        try:
            from slappyengine.ui.widgets import DoodleSeparator

            sep = DoodleSeparator(style=style)
            sep.build(self._panel_tag)
            self._widgets.append(sep)
        except Exception:
            try:
                dpg.add_separator(parent=self._panel_tag)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Field builders — one closure per attribute, run by WashiPanel
    # ------------------------------------------------------------------

    def _make_field_builder(self, name: str, value: Any) -> Callable[[], None]:
        """Return a zero-arg closure that builds one field's widget."""
        def _build() -> None:
            self._render_field(name, value)

        return _build

    def _make_reference_builder(self, name: str, value: Any) -> Callable[[], None]:
        """Return a zero-arg closure that builds one reference row."""
        def _build() -> None:
            self._render_reference_field(name, value)

        return _build

    # ------------------------------------------------------------------
    # Per-type widget renderers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Reference (complex / dataclass) renderer
    # ------------------------------------------------------------------

    def _render_reference_field(self, name: str, value: Any) -> None:
        """Render a complex value — nested dataclasses recurse."""
        dpg = _safe_dpg()
        # Nested dataclass → collapsing_header + recursive NotebookInspector.
        if _is_dataclass_value(value):
            nested_parent = self._panel_tag
            header_tag = f"{self._panel_tag}__{name}_header"
            # Wrap the nested inspector in a collapsing_header so V3
            # nested-dataclass rows fold like the task contract asks.
            if dpg is not None:
                try:
                    header_cm = dpg.collapsing_header(
                        label=f"{name}: {type(value).__name__}",
                        parent=self._panel_tag,
                        tag=header_tag,
                        default_open=True,
                    )
                    header_cm.__enter__()
                    nested_parent = header_tag
                    self.call_log.append(("collapsing_header", name))
                except Exception:
                    header_cm = None
            else:
                header_cm = None

            try:
                # Forward the ``on_field_changed`` hook so edits inside a
                # nested inspector still surface at the parent's callback.
                nested = NotebookInspector(
                    target=value, on_field_changed=self._on_field_changed
                )
                nested.build(nested_parent)
                self._nested.append(nested)
                self._widget_map[name] = nested._panel_tag
                self.call_log.append(("nested", name, type(value).__name__))
            except Exception:
                pass
            finally:
                if header_cm is not None:
                    try:
                        header_cm.__exit__(None, None, None)
                    except Exception:
                        pass
            return

        # Non-dataclass complex value — `name: TypeName [?]` row.
        if dpg is None:
            return

        row_tag = f"{self._panel_tag}__{name}_row"
        btn_tag = f"{self._panel_tag}__{name}_btn"
        popup_tag = f"{self._panel_tag}__{name}_popup"
        type_name = type(value).__name__
        repr_str = repr(value)

        def _show_popup(_sender, _app, _user, _popup=popup_tag):
            try:
                if dpg.does_item_exist(_popup):
                    dpg.configure_item(_popup, show=True)
            except Exception:
                pass
            self.call_log.append(("popup_open", name))

        try:
            with dpg.group(horizontal=True, parent=self._panel_tag, tag=row_tag):
                dpg.add_text(f"{name}: {type_name}")
                dpg.add_button(
                    label="?",
                    small=True,
                    callback=_show_popup,
                    tag=btn_tag,
                )
            with dpg.popup(parent=btn_tag, tag=popup_tag, mousebutton=-1):
                dpg.add_text(repr_str, wrap=400)
            self._widget_map[name] = row_tag
        except Exception:
            # Stub-DPG flat path — at least record the button tag.
            try:
                dpg.add_button(
                    label=f"{name}: {type_name} ?",
                    parent=self._panel_tag,
                    tag=btn_tag,
                    callback=_show_popup,
                )
                self._widget_map[name] = btn_tag
            except Exception:
                pass

        self.call_log.append(("reference", name, type_name))

    # ------------------------------------------------------------------
    # [?] help popup — shared with PropertyInspector's `[?]` pattern
    # ------------------------------------------------------------------

    def _add_help_button(self, name: str) -> None:
        """Add a small `?` button next to the last-built field.

        Clicking it would open a tooltip with the field's docstring.
        Doc lookup goes through the target's class annotations / docstring
        when available; otherwise falls back to the attribute name.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        btn_tag = f"{self._panel_tag}__{name}_help_btn"
        tip_tag = f"{self._panel_tag}__{name}_help_tip"
        doc = self._field_doc(name)

        def _on_help(_sender, _app, _user, _name=name):
            self.call_log.append(("help_popup", _name))
            try:
                if dpg.does_item_exist(tip_tag):
                    dpg.configure_item(tip_tag, show=True)
            except Exception:
                pass

        try:
            dpg.add_button(
                label="?",
                small=True,
                parent=self._panel_tag,
                tag=btn_tag,
                callback=_on_help,
            )
            with dpg.popup(parent=btn_tag, tag=tip_tag, mousebutton=-1):
                dpg.add_text(doc, wrap=320)
        except Exception:
            try:
                dpg.add_button(
                    label="?",
                    parent=self._panel_tag,
                    tag=btn_tag,
                    callback=_on_help,
                )
            except Exception:
                pass

    def _field_doc(self, name: str) -> str:
        """Return a short doc snippet for *name* (or a friendly fallback)."""
        if self._target is None:
            return name
        cls = type(self._target)
        # Dataclass-aware: the class docstring describes every field.
        doc = (cls.__doc__ or "").strip()
        if not doc:
            return name
        # Naive lookup: if the docstring mentions the field name, return
        # a small snippet around it; otherwise return the first line.
        idx = doc.find(name)
        if idx == -1:
            return doc.splitlines()[0]
        return doc[idx : idx + 200]

    # ------------------------------------------------------------------
    # Field iteration + write-back
    # ------------------------------------------------------------------

    def _iter_fields(self) -> list[tuple[str, Any]]:
        """Return ``(name, value)`` pairs for every inspectable field."""
        obj = self._target
        if obj is None:
            return []
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return [
                (f.name, getattr(obj, f.name))
                for f in dataclasses.fields(obj)
            ]
        return [
            (k, v)
            for k, v in vars(obj).items()
            if not k.startswith("_")
        ]

    # ------------------------------------------------------------------
    # V3 — dataclass reflection helpers
    # ------------------------------------------------------------------

    def _dataclass_fields_by_name(self) -> dict[str, dataclasses.Field]:
        """Return a ``{name: Field}`` map for the current target, or ``{}``.

        Used by the V3 reflection path so per-row helpers (metadata
        lookup, reset-to-default, ``object.__setattr__`` write-back)
        can pull the source-of-truth Field descriptor without re-walking
        ``dataclasses.fields(target)`` on every access.
        """
        obj = self._target
        if obj is None or not dataclasses.is_dataclass(obj) or isinstance(obj, type):
            return {}
        try:
            return {f.name: f for f in dataclasses.fields(obj)}
        except Exception:
            return {}

    def field_metadata(self, name: str) -> dict[str, Any]:
        """Return ``field.metadata`` (as a plain dict) or ``{}``.

        Exposed so tests + callers can round-trip the same source of
        truth that the widget-builder consults for ``doc`` / ``range`` /
        ``read_only`` decoration.
        """
        f = self._dataclass_fields_by_name().get(name)
        if f is None:
            return {}
        try:
            return dict(f.metadata) if f.metadata else {}
        except Exception:
            return {}

    def field_range(self, name: str) -> tuple[float, float] | None:
        """Return the ``metadata['range']`` tuple for *name*, or ``None``.

        Accepts either a 2-tuple ``(min, max)`` or a 2-list; anything
        else returns ``None`` so the caller falls back to the automatic
        slider range table.
        """
        rng = self.field_metadata(name).get("range")
        if rng is None:
            return None
        try:
            lo, hi = rng
            return (float(lo), float(hi))
        except Exception:
            return None

    def field_is_read_only(self, name: str) -> bool:
        """Return True when the field's metadata carries ``read_only=True``."""
        return bool(self.field_metadata(name).get("read_only", False))

    def field_doc(self, name: str) -> str | None:
        """Return ``metadata['doc']`` for *name* (or ``None`` when absent)."""
        doc = self.field_metadata(name).get("doc")
        if doc is None:
            return None
        return str(doc)

    def field_default(self, name: str) -> Any:
        """Return the dataclass default for *name*.

        Prefers ``field.default``; falls back to
        ``field.default_factory()`` when the field uses one.  Returns
        the sentinel :data:`dataclasses.MISSING` when the field has
        neither so callers can detect the "no default" case.
        """
        f = self._dataclass_fields_by_name().get(name)
        if f is None:
            return dataclasses.MISSING
        if f.default is not dataclasses.MISSING:
            return f.default
        if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            try:
                return f.default_factory()  # type: ignore[misc]
            except Exception:
                return dataclasses.MISSING
        return dataclasses.MISSING

    def reset_field(self, name: str) -> Any:
        """Restore *name* to its dataclass default and fire the change hook.

        Returns the value written back, or :data:`dataclasses.MISSING`
        when the field has no default (in which case no write happens).
        This is the target of the per-row 🔄 "Reset to default" button.
        """
        default = self.field_default(name)
        if default is dataclasses.MISSING:
            self.call_log.append(("reset_missing", name))
            return dataclasses.MISSING
        self._write_back(name, default)
        self.call_log.append(("reset", name, default))
        return default

    def _enum_type_for_field(self, name: str) -> type[enum.Enum] | None:
        """Return the ``Enum`` subclass for *name*, if any.

        Uses ``typing.get_type_hints`` (evaluated) with a
        ``getattr`` fallback for classes whose annotations aren't
        forward-resolvable (e.g. ``from __future__ import annotations``
        combined with local type names).  We check the current value's
        runtime class first — it's the fastest and always accurate for
        already-populated fields.
        """
        obj = self._target
        if obj is None:
            return None
        current = getattr(obj, name, None)
        if isinstance(current, enum.Enum):
            return type(current)
        # Fallback — resolve the annotation.
        try:
            hints = typing.get_type_hints(type(obj))
        except Exception:
            return None
        hint = hints.get(name)
        if isinstance(hint, type) and issubclass(hint, enum.Enum):
            return hint
        return None

    def _make_callback(self, name: str) -> Callable[[Any], None]:
        """Return a 1-arg callback that writes ``target.<name> = value``."""
        def _cb(value: Any) -> None:
            self._write_back(name, value)

        return _cb

    def _write_back(self, name: str, value: Any) -> None:
        """Write *value* into ``self._target.<name>`` and log the edit.

        Uses :func:`object.__setattr__` so frozen dataclasses can still
        be edited from the inspector (the V3 write-back contract) and
        publishes the ``on_field_changed(name, old, new)`` callback when
        one was supplied to the constructor.
        """
        validate_non_empty_str("name", "NotebookInspector._write_back", name)
        if self._target is None:
            return
        # Snapshot the old value BEFORE the write so ``on_field_changed``
        # sees the pre-edit state.  ``getattr`` with a sentinel keeps
        # unknown-attr edits silent (backwards-compat with the earlier
        # contract that swallowed AttributeError).
        _sentinel = object()
        old = getattr(self._target, name, _sentinel)
        try:
            # ``object.__setattr__`` bypasses frozen dataclasses AND any
            # ``__setattr__`` override on the target's class — the
            # inspector should always land the edit.
            object.__setattr__(self._target, name, value)
        except (AttributeError, TypeError):
            # Some __slots__ classes still reject unknown names via
            # object.__setattr__; keep the historic silent-swallow.
            self.call_log.append(("edit_dropped", name))
            return
        self.call_log.append(("edit", name, value))
        if self._on_field_changed is not None and old is not _sentinel:
            try:
                self._on_field_changed(name, old, value)
            except Exception:
                # Never let a caller's listener take down the inspector.
                self.call_log.append(("on_field_changed_error", name))


__all__ = ["NotebookInspector", "set_project_context"]
