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


# ---------------------------------------------------------------------------
# Constants — section ranges and theme tokens
# ---------------------------------------------------------------------------

# Fallback slider ranges keyed by transform/property name.  The
# HighlighterSlider widget validates ``min < max``, so we keep the table
# generous enough that any reasonable starting value will clamp inside
# the range rather than crash construction.
_SLIDER_RANGES: dict[str, tuple[float, float]] = {
    "position":  (-1000.0, 1000.0),
    "rotation":  (-360.0, 360.0),
    "scale":     (0.0, 10.0),
    "z_height":  (-100.0, 100.0),
    "z_order":   (-100.0, 100.0),
    "width":     (0.0, 4096.0),
    "height":    (0.0, 4096.0),
}

# Default range for any other float field — large enough to cover the
# normal physics-domain values (mass, stiffness < 1e9 won't break the
# clamp but the slider becomes unusable for those; tests that need real
# ranges should bind a custom range later).
_DEFAULT_FLOAT_RANGE: tuple[float, float] = (-1000.0, 1000.0)

# Empty-state copy.
_EMPTY_HINT = "Pick a critter to view its journal entry"
_EMPTY_STICKER = "[badger]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _slider_range_for(name: str, value: float) -> tuple[float, float]:
    """Return a sensible ``(min, max)`` for a float field.

    Falls back to a range centred on *value* if the name isn't in the
    table, ensuring the HighlighterSlider's "min < max" invariant always
    holds even for unusual values.
    """
    rng = _SLIDER_RANGES.get(name)
    if rng is not None:
        lo, hi = rng
        # Stretch the range if value is outside it so clamp-on-construct
        # doesn't silently swallow the current value.
        if value < lo:
            lo = value - 1.0
        if value > hi:
            hi = value + 1.0
        return (float(lo), float(hi))

    # Generic range — symmetric around the current value, never zero-width.
    span = max(abs(value) * 10.0, 100.0)
    lo = -span if value <= 0 else value - span
    hi = span if value >= 0 else value + span
    if lo >= hi:
        hi = lo + 1.0
    return (float(lo), float(hi))


def _is_dataclass_value(value: Any) -> bool:
    """Return True for *instances* (not classes) of dataclasses."""
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def _is_path_value(value: Any) -> bool:
    return isinstance(value, Path)


# ---------------------------------------------------------------------------
# NotebookInspector
# ---------------------------------------------------------------------------


class NotebookInspector:
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

    def __init__(self, target: Any | None = None) -> None:
        self._target: Any = target
        self._panel_tag: str = f"notebook_inspector_{id(self)}"
        self._transform_tag = f"{self._panel_tag}_transform"
        self._properties_tag = f"{self._panel_tag}_properties"
        self._references_tag = f"{self._panel_tag}_references"
        self._empty_tag = f"{self._panel_tag}_empty"

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
                    dpg.add_text("Field Journal", color=[40, 40, 60, 255])
                except Exception:
                    pass
        except Exception:
            # Stub-DPG without context-manager support — flat path.
            try:
                dpg.add_text(
                    "Field Journal",
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
        """Render the "(no critter selected)" hint with badger sticker."""
        try:
            with dpg.group(parent=self._panel_tag, tag=self._empty_tag):
                dpg.add_text(_EMPTY_STICKER, color=[120, 80, 40, 255])
                dpg.add_text(_EMPTY_HINT, color=[120, 120, 140, 255])
        except Exception:
            try:
                dpg.add_text(
                    f"{_EMPTY_STICKER} {_EMPTY_HINT}",
                    parent=self._panel_tag,
                    tag=self._empty_tag,
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

    def _render_field(self, name: str, value: Any) -> None:
        """Dispatch *value* to the right notebook widget."""
        # NOTE: ``bool`` is a subclass of ``int`` — keep the bool branch first.
        if isinstance(value, bool):
            self._render_bool(name, value)
        elif isinstance(value, int):
            self._render_int(name, value)
        elif isinstance(value, float):
            self._render_float(name, value)
        elif isinstance(value, str):
            self._render_str(name, value)
        elif _is_path_value(value):
            self._render_path(name, value)
        elif _is_float_tuple(value) and len(value) == 4:
            self._render_color(name, value)
        elif _is_float_tuple(value):
            self._render_float_tuple(name, value)
        elif _is_list_of_str(value):
            self._render_list_str(name, value)
        elif _is_list_of_int(value):
            self._render_list_int(name, value)
        else:
            self._render_help_row(name, value)

    def _render_bool(self, name: str, value: bool) -> None:
        from slappyengine.ui.widgets import HeartCheckbox

        try:
            heart = HeartCheckbox(
                label=name,
                value=value,
                callback=self._make_callback(name),
            )
            heart.build(self._panel_tag)
            self._widgets.append(heart)
            self._widget_map[name] = heart.root_tag or name
        except Exception:
            dpg = _safe_dpg()
            if dpg is None:
                return
            try:
                tag = f"{self._panel_tag}__{name}"
                dpg.add_checkbox(
                    label=name,
                    default_value=value,
                    parent=self._panel_tag,
                    tag=tag,
                    callback=lambda s, a, u, *_extra: self._write_back(name, bool(a)),
                )
                self._widget_map[name] = tag
            except Exception:
                pass
        self.call_log.append(("field", name, "bool"))
        self._add_help_button(name)

    def _render_int(self, name: str, value: int) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_input_int(
                label=name,
                default_value=value,
                parent=self._panel_tag,
                tag=tag,
                callback=lambda s, a, u, *_extra: self._write_back(name, int(a)),
            )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "int"))
        self._add_help_button(name)

    def _render_float(self, name: str, value: float) -> None:
        from slappyengine.ui.widgets import HighlighterSlider

        lo, hi = _slider_range_for(name, value)
        try:
            slider = HighlighterSlider(
                label=name,
                value=float(value),
                min=lo,
                max=hi,
                callback=self._make_callback(name),
            )
            slider.build(self._panel_tag)
            self._widgets.append(slider)
            self._widget_map[name] = slider.root_tag or name
        except Exception:
            dpg = _safe_dpg()
            if dpg is None:
                return
            tag = f"{self._panel_tag}__{name}"
            try:
                dpg.add_input_float(
                    label=name,
                    default_value=float(value),
                    parent=self._panel_tag,
                    tag=tag,
                    callback=lambda s, a, u, *_extra: self._write_back(name, float(a)),
                )
                self._widget_map[name] = tag
            except Exception:
                pass
        self.call_log.append(("field", name, "float"))
        self._add_help_button(name)

    def _render_str(self, name: str, value: str) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_input_text(
                label=name,
                default_value=value,
                parent=self._panel_tag,
                tag=tag,
                callback=lambda s, a, u, *_extra: self._write_back(name, str(a)),
            )
            # The washi-tape "underline" is a 1px coloured strip the
            # theme paints under the input; we add the slot but the
            # actual rendering is the theme's job.
            try:
                dpg.add_text(
                    "________",
                    parent=self._panel_tag,
                    color=[200, 180, 120, 200],
                )
            except Exception:
                pass
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "str"))
        self._add_help_button(name)

    def _render_path(self, name: str, value: Path) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            with dpg.group(horizontal=True, parent=self._panel_tag):
                dpg.add_input_text(
                    label=name,
                    default_value=str(value),
                    tag=tag,
                    callback=lambda s, a, u, *_extra: self._write_back(name, Path(a)),
                )
                # Paperclip glyph "file picker" stand-in — the real picker
                # plugs in here in a later sprint.
                dpg.add_button(
                    label="[clip]",
                    callback=lambda s, a, u, *_extra, _n=name: self.call_log.append(
                        ("path_picker", _n),
                    ),
                )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "path"))
        self._add_help_button(name)

    def _render_color(self, name: str, value: tuple) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_color_edit(
                label=name,
                default_value=list(value),
                parent=self._panel_tag,
                tag=tag,
                callback=lambda s, a, u, *_extra: self._write_back(name, tuple(a)),
            )
            # Sticker preview — small coloured square the theme styles
            # as a wax-seal sticker.
            try:
                dpg.add_text(
                    "[sticker]",
                    parent=self._panel_tag,
                    color=list(value)[:4],
                )
            except Exception:
                pass
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "color"))
        self._add_help_button(name)

    def _render_float_tuple(self, name: str, value: tuple) -> None:
        """Multi-axis float widget for ``(x, y)`` and ``(x, y, z)`` tuples."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_input_floatx(
                label=name,
                default_value=list(value),
                size=len(value),
                parent=self._panel_tag,
                tag=tag,
                callback=lambda s, a, u, *_extra: self._write_back(name, tuple(a)),
            )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, f"float{len(value)}"))
        self._add_help_button(name)

    def _render_list_str(self, name: str, value: list[str]) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_listbox(
                items=value,
                label=name,
                parent=self._panel_tag,
                tag=tag,
                num_items=min(len(value), 4),
            )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "list_str"))
        self._add_help_button(name)

    def _render_list_int(self, name: str, value: list[int]) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        text = ", ".join(str(int(v)) for v in value)

        def _cb(_sender, app_data, _user_data):
            try:
                parsed = [
                    int(part)
                    for part in str(app_data).replace(";", ",").split(",")
                    if part.strip() != ""
                ]
            except ValueError:
                return
            self._write_back(name, parsed)

        try:
            dpg.add_input_text(
                label=name,
                default_value=text,
                parent=self._panel_tag,
                tag=tag,
                callback=_cb,
            )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "list_int"))
        self._add_help_button(name)

    def _render_help_row(self, name: str, value: Any) -> None:
        """Fallback read-only row for unknown types."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        tag = f"{self._panel_tag}__{name}"
        try:
            dpg.add_text(
                f"{name}: {value!r}",
                parent=self._panel_tag,
                tag=tag,
            )
            self._widget_map[name] = tag
        except Exception:
            pass
        self.call_log.append(("field", name, "other"))

    # ------------------------------------------------------------------
    # Reference (complex / dataclass) renderer
    # ------------------------------------------------------------------

    def _render_reference_field(self, name: str, value: Any) -> None:
        """Render a complex value — nested dataclasses recurse."""
        dpg = _safe_dpg()
        # Nested dataclass → sub-NotebookInspector.
        if _is_dataclass_value(value):
            try:
                nested = NotebookInspector(target=value)
                nested.build(self._panel_tag)
                self._nested.append(nested)
                self._widget_map[name] = nested._panel_tag
                self.call_log.append(("nested", name, type(value).__name__))
                return
            except Exception:
                pass

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

    def _make_callback(self, name: str) -> Callable[[Any], None]:
        """Return a 1-arg callback that writes ``target.<name> = value``."""
        def _cb(value: Any) -> None:
            self._write_back(name, value)

        return _cb

    def _write_back(self, name: str, value: Any) -> None:
        """Write *value* into ``self._target.<name>`` and log the edit."""
        validate_non_empty_str("name", "NotebookInspector._write_back", name)
        if self._target is None:
            return
        try:
            setattr(self._target, name, value)
            self.call_log.append(("edit", name, value))
        except (AttributeError, TypeError):
            pass


__all__ = ["NotebookInspector"]
