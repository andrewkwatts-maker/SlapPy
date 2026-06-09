"""Widget-dispatch mixin for :class:`NotebookInspector`.

Split out of ``notebook_inspector.py`` (2026-06-07 consolidation sweep) so
the inspector module stays focused on lifecycle / section rendering and
the per-type leaf renderers live in their own file. ``InspectorDispatchMixin``
implements ``_render_field`` plus one ``_render_<type>`` method per
primitive the inspector understands.

The mixin reads / writes the following attributes on ``self`` (provided by
:class:`NotebookInspector`)::

    self._panel_tag       str
    self._widget_map      dict[str, str]
    self._widgets         list[Any]
    self._nested          list  # only used by _render_reference_field
    self.call_log         list[tuple]
    self._make_callback   (name) -> Callable
    self._write_back      (name, value) -> None
    self._add_help_button (name) -> None

Every ``dpg.*`` call is wrapped in ``try/except`` so the inspector still
records its tags + call-log entries when ``dearpygui`` is missing or
stubbed out.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from slappyengine.ui.editor.property_inspector import (
    _is_float_tuple,
    _is_list_of_int,
    _is_list_of_str,
)


# Imported lazily by helpers below to avoid a circular import.
def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Slider range helpers
# ---------------------------------------------------------------------------

_SLIDER_RANGES: dict[str, tuple[float, float]] = {
    "position":  (-1000.0, 1000.0),
    "rotation":  (-360.0, 360.0),
    "scale":     (0.0, 10.0),
    "z_height":  (-100.0, 100.0),
    "z_order":   (-100.0, 100.0),
    "width":     (0.0, 4096.0),
    "height":    (0.0, 4096.0),
}

_DEFAULT_FLOAT_RANGE: tuple[float, float] = (-1000.0, 1000.0)


def _slider_range_for(name: str, value: float) -> tuple[float, float]:
    """Return a sensible ``(min, max)`` for a float field.

    Falls back to a range centred on *value* if the name isn't in the
    table, ensuring the HighlighterSlider's "min < max" invariant always
    holds even for unusual values.
    """
    rng = _SLIDER_RANGES.get(name)
    if rng is not None:
        lo, hi = rng
        if value < lo:
            lo = value - 1.0
        if value > hi:
            hi = value + 1.0
        return (float(lo), float(hi))

    span = max(abs(value) * 10.0, 100.0)
    lo = -span if value <= 0 else value - span
    hi = span if value >= 0 else value + span
    if lo >= hi:
        hi = lo + 1.0
    return (float(lo), float(hi))


def _is_path_value(value: Any) -> bool:
    return isinstance(value, Path)


# ---------------------------------------------------------------------------
# Mixin — one method per primitive type the inspector understands.
# ---------------------------------------------------------------------------


class InspectorDispatchMixin:
    """Per-type leaf renderers for :class:`NotebookInspector`.

    Each ``_render_<type>`` method builds one widget plus the trailing
    ``?`` help button, and records a ``("field", name, kind)`` entry in
    ``self.call_log``. The methods are split here so the inspector module
    stays focused on lifecycle + section dispatch.
    """

    # The mixin requires these attributes on the concrete class:
    _panel_tag: str
    _widget_map: dict[str, str]
    _widgets: list
    call_log: list

    def _make_callback(self, name: str):  # pragma: no cover - typing hint only
        ...

    def _write_back(self, name: str, value: Any) -> None:  # pragma: no cover
        ...

    def _add_help_button(self, name: str) -> None:  # pragma: no cover
        ...

    # ------------------------------------------------------------------
    # Dispatch entry point
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

    # ------------------------------------------------------------------
    # Per-type leaf renderers
    # ------------------------------------------------------------------

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


__all__ = [
    "InspectorDispatchMixin",
    "_safe_dpg",
    "_slider_range_for",
    "_is_path_value",
    "_SLIDER_RANGES",
    "_DEFAULT_FLOAT_RANGE",
]
