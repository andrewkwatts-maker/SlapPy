from __future__ import annotations

import dataclasses
from typing import Any

# Fields treated as transform-group members
TRANSFORM_FIELDS: frozenset[str] = frozenset(
    ("position", "rotation", "scale", "z_height", "z_order")
)

# Float field names that benefit from drag widgets instead of input widgets
DRAG_FLOAT_NAMES: frozenset[str] = frozenset(
    ("position", "rotation", "scale", "z_height", "z_order", "width", "height")
)


def _is_float_tuple(value: Any) -> bool:
    """Return True if *value* is a tuple whose every element is a float or int."""
    return (
        isinstance(value, tuple)
        and len(value) > 0
        and all(isinstance(v, (float, int)) for v in value)
    )


def _is_list_of_str(value: Any) -> bool:
    """Return True if *value* is a list whose every element is a str."""
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_primitive(value: Any) -> bool:
    """Return True for values that map to a simple DPG input widget."""
    if isinstance(value, (bool, int, float, str)):
        return True
    if _is_float_tuple(value):
        return True
    if _is_list_of_str(value):
        return True
    return False


def _is_engine_object(value: Any) -> bool:
    """Return True for complex engine objects that should not be shown inline.

    An engine object is anything whose type lives in a ``SlapPyEngine.*``
    module and is *not* a dataclass (dataclasses are considered plain data).
    A list containing at least one non-primitive item is also treated as complex.
    """
    if isinstance(value, list):
        return any(not _is_primitive(item) for item in value)

    t = type(value)
    mod = getattr(t, "__module__", "") or ""
    if mod.startswith("slappyengine") and not dataclasses.is_dataclass(value):
        return True

    return False


class PropertyInspector:
    """
    Auto-generates DPG input widgets from Python object attributes.

    Rendering is split into three collapsing sections:

    Transform
        Drag widgets for ``position``, ``rotation``, ``scale``, ``z_height``,
        ``z_order``.
    Properties
        Primitive fields not in the transform group (bool, int, float, str,
        simple tuples, list[str]).
    References (collapsed by default)
        Complex / engine-object fields shown as ``<name>: TypeName [?]`` with
        a popup button for the full repr.

    Panel protocol: ``build(parent_tag) -> None``

    Usage::

        inspector = PropertyInspector()
        inspector.build("sidebar")          # call once after dpg context exists
        inspector.set_object(my_entity)     # call whenever selection changes
    """

    _RGBA_TUPLE_LEN = 4
    _FLOAT2_LEN = 2
    _FLOAT3_LEN = 3

    def __init__(self) -> None:
        self._obj: Any = None
        self._panel_tag: str = "property_inspector"
        self._widget_map: dict[str, str | int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_object(self, obj: Any) -> None:
        """Bind a new object to the inspector and refresh all widgets."""
        self._obj = obj
        self._refresh()

    def build(self, parent_tag) -> None:
        """
        Create the inspector container inside *parent_tag*.

        Must be called after ``dpg.create_context()`` and before the first
        render loop iteration.  Subsequent calls to :meth:`set_object` will
        repopulate the container without recreating it.
        """
        import dearpygui.dearpygui as dpg

        with dpg.child_window(
            tag=self._panel_tag,
            parent=parent_tag,
            border=False,
            autosize_x=True,
            height=-1,
        ):
            dpg.add_text("Properties", tag=f"{self._panel_tag}_header")
            dpg.add_separator(tag=f"{self._panel_tag}_sep")

        if self._obj is not None:
            self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iter_fields(self) -> list[tuple[str, Any]]:
        """Return (name, value) pairs for every inspectable field on *self._obj*."""
        obj = self._obj
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

    def _unique_tag(self, attr_name: str) -> str:
        """Return a stable, unique DPG tag for a given attribute widget."""
        obj_id = id(self._obj)
        return f"{self._panel_tag}__{obj_id}__{attr_name}"

    # ------------------------------------------------------------------
    # Widget rendering — one field at a time
    # ------------------------------------------------------------------

    def _render_field(self, parent, name: str, value: Any) -> None:
        """Add one DPG widget for the field *name* with current *value*.

        This is called by the two-pass renderer in ``_refresh`` for both the
        Transform section and the Properties section.  Complex objects are
        handled separately in ``_render_complex_field``.

        Dispatch table
        --------------
        bool                        → checkbox
        int                         → input_int
        float (drag name)           → drag_float
        float (other)               → input_float
        str                         → input_text
        tuple[float|int] len 2
          (drag name)               → drag_floatx size=2
          (other)                   → input_floatx size=2
        tuple[float|int] len 3      → input_floatx size=3
        tuple[float|int] len 4      → color_edit (RGBA)
        list[str]                   → listbox
        """
        import dearpygui.dearpygui as dpg

        tag = self._unique_tag(name)
        self._widget_map[name] = tag
        callback = self._make_callback(name)
        use_drag = name in DRAG_FLOAT_NAMES

        if isinstance(value, bool):
            dpg.add_checkbox(
                label=name,
                default_value=value,
                callback=callback,
                parent=parent,
                tag=tag,
            )

        elif isinstance(value, int):
            dpg.add_input_int(
                label=name,
                default_value=value,
                callback=callback,
                parent=parent,
                tag=tag,
            )

        elif isinstance(value, float):
            if use_drag:
                dpg.add_drag_float(
                    label=name,
                    default_value=value,
                    speed=0.5,
                    callback=callback,
                    parent=parent,
                    tag=tag,
                )
            else:
                dpg.add_input_float(
                    label=name,
                    default_value=value,
                    callback=callback,
                    parent=parent,
                    tag=tag,
                )

        elif isinstance(value, str):
            dpg.add_input_text(
                label=name,
                default_value=value,
                callback=callback,
                parent=parent,
                tag=tag,
            )

        elif _is_float_tuple(value) and len(value) == self._RGBA_TUPLE_LEN:
            dpg.add_color_edit(
                label=name,
                default_value=list(value),
                callback=callback,
                parent=parent,
                tag=tag,
            )

        elif _is_float_tuple(value) and len(value) == self._FLOAT3_LEN:
            dpg.add_input_floatx(
                label=name,
                default_value=list(value),
                size=self._FLOAT3_LEN,
                callback=callback,
                parent=parent,
                tag=tag,
            )

        elif _is_float_tuple(value) and len(value) == self._FLOAT2_LEN:
            if use_drag:
                dpg.add_drag_floatx(
                    label=name,
                    default_value=list(value),
                    size=self._FLOAT2_LEN,
                    speed=0.5,
                    callback=callback,
                    parent=parent,
                    tag=tag,
                )
            else:
                dpg.add_input_floatx(
                    label=name,
                    default_value=list(value),
                    size=self._FLOAT2_LEN,
                    callback=callback,
                    parent=parent,
                    tag=tag,
                )

        elif _is_list_of_str(value):
            dpg.add_listbox(
                items=value,
                label=name,
                parent=parent,
                tag=tag,
                num_items=min(len(value), 4),
            )

        else:
            # Primitive-looking value with unexpected type → read-only text
            dpg.add_text(
                f"{name}: {value!r}",
                parent=parent,
                tag=tag,
            )

    def _render_complex_field(self, parent, name: str, value: Any) -> None:
        """Render a non-primitive field as ``<name>: TypeName [?]``.

        The ``[?]`` button opens a modal popup with the full repr string.
        This keeps the inspector uncluttered while still providing access to
        the raw value for debugging.
        """
        import dearpygui.dearpygui as dpg

        type_name = type(value).__name__
        row_tag = self._unique_tag(f"{name}_row")
        popup_tag = self._unique_tag(f"{name}_popup")
        btn_tag = self._unique_tag(f"{name}_btn")

        with dpg.group(horizontal=True, parent=parent, tag=row_tag):
            dpg.add_text(f"{name}: {type_name}")

            # Capture repr eagerly; repr() of live engine objects can change
            repr_str = repr(value)

            def _show_popup(sender, app_data, user_data, _repr=repr_str, _popup=popup_tag):  # noqa: ANN001
                if dpg.does_item_exist(_popup):
                    dpg.configure_item(_popup, show=True)

            dpg.add_button(label="?", small=True, callback=_show_popup, tag=btn_tag)

        # Build the popup once; toggle visibility on button click.
        with dpg.popup(parent=btn_tag, tag=popup_tag, mousebutton=-1):
            dpg.add_text(repr_str, wrap=400)

    # ------------------------------------------------------------------
    # Callback factory
    # ------------------------------------------------------------------

    def _make_callback(self, attr_name: str):
        """Return a DPG callback that writes ``self._obj.<attr_name> = app_data``."""
        def _cb(sender, app_data, user_data):  # noqa: ANN001
            if self._obj is not None:
                try:
                    setattr(self._obj, attr_name, app_data)
                except (AttributeError, TypeError):
                    pass

        return _cb

    # ------------------------------------------------------------------
    # Refresh (two-pass layout)
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """
        Wipe all existing child widgets from the inspector panel and rebuild
        them for the currently bound object using the three-section layout:

        1. Transform   — collapsing header, drag widgets
        2. Properties  — collapsing header, all other primitive fields
        3. References  — collapsing header (collapsed), complex objects

        Safe to call before :meth:`build` has been invoked (no-op in that case).
        """
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._panel_tag):
            return

        self._widget_map.clear()
        dpg.delete_item(self._panel_tag, children_only=True)

        # Re-add static header items deleted above.
        dpg.add_text("Properties", tag=f"{self._panel_tag}_header", parent=self._panel_tag)
        dpg.add_separator(tag=f"{self._panel_tag}_sep", parent=self._panel_tag)

        if self._obj is None:
            dpg.add_text(
                "(no object selected)",
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_empty",
            )
            return

        type_name = type(self._obj).__name__
        dpg.add_text(
            f"Type: {type_name}",
            parent=self._panel_tag,
            tag=f"{self._panel_tag}_typename",
        )
        dpg.add_separator(parent=self._panel_tag, tag=f"{self._panel_tag}_sep2")

        # ---- Pass 1: categorise all fields --------------------------------
        transform_fields: list[tuple[str, Any]] = []
        primitive_fields: list[tuple[str, Any]] = []
        complex_fields: list[tuple[str, Any]] = []

        for name, value in self._iter_fields():
            if name in TRANSFORM_FIELDS:
                transform_fields.append((name, value))
            elif _is_engine_object(value):
                complex_fields.append((name, value))
            elif _is_primitive(value):
                primitive_fields.append((name, value))
            else:
                # Non-engine non-primitive (e.g. dict, set, unknown object)
                complex_fields.append((name, value))

        # ---- Pass 2: render sections --------------------------------------

        # Transform section
        if transform_fields:
            with dpg.collapsing_header(
                label="Transform",
                default_open=True,
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_sec_transform",
            ):
                for name, value in transform_fields:
                    self._render_field(f"{self._panel_tag}_sec_transform", name, value)

        # Properties section
        if primitive_fields:
            with dpg.collapsing_header(
                label="Properties",
                default_open=True,
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_sec_props",
            ):
                for name, value in primitive_fields:
                    self._render_field(f"{self._panel_tag}_sec_props", name, value)

        # References section (collapsed by default to reduce noise)
        if complex_fields:
            with dpg.collapsing_header(
                label="References",
                default_open=False,
                parent=self._panel_tag,
                tag=f"{self._panel_tag}_sec_refs",
            ):
                for name, value in complex_fields:
                    self._render_complex_field(
                        f"{self._panel_tag}_sec_refs", name, value
                    )
