"""Legacy Nova3D reference. The shipping editor uses notebook_* siblings — see docs/ui_pattern_audit_2026_06_03.md."""
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


def _is_list_of_int(value: Any) -> bool:
    """Return True if *value* is a non-empty list of plain ints (not bool).

    Used to render ``IKChainSpec.node_indices`` and similar index lists with
    a single comma-separated text widget rather than a popup-only ref row.
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    )


def _is_primitive(value: Any) -> bool:
    """Return True for values that map to a simple DPG input widget."""
    if isinstance(value, (bool, int, float, str)):
        return True
    if _is_float_tuple(value):
        return True
    if _is_list_of_str(value):
        return True
    if _is_list_of_int(value):
        return True
    return False


def _is_simple_value_dict(value: Any) -> bool:
    """Return True for a dict whose values are all primitive-ish.

    Used to inline-render the ``JointSpec.params`` / ``MotorSpec.params`` /
    similar "kind-specific extras" bags as key/value rows instead of an
    opaque ``[?]`` popup.  Empty dicts also qualify so the inspector renders
    a "(empty)" placeholder under the field name.
    """
    if not isinstance(value, dict):
        return False
    return all(_is_primitive(v) for v in value.values())


def _is_engine_object(value: Any) -> bool:
    """Return True for complex engine objects that should not be shown inline.

    An engine object is anything whose type lives in a ``SlapPyEngine.*``
    module and is *not* a dataclass (dataclasses are considered plain data).
    A list containing at least one non-primitive item is also treated as complex.

    Dataclasses from :mod:`pharos_engine.dynamics` (``Body``, ``Material``,
    ``JointSpec``, ``MotorSpec``, ``SpringSpec``, ``RopeSpec``,
    ``IKChainSpec``, ``RagdollSpec``, ``BoneSpec``) all hit the
    ``is_dataclass`` short-circuit and are therefore reflected through the
    standard primitive-widget path rather than treated as opaque refs.
    """
    if isinstance(value, list):
        return any(not _is_primitive(item) for item in value)

    t = type(value)
    mod = getattr(t, "__module__", "") or ""
    if mod.startswith("pharos_engine") and not dataclasses.is_dataclass(value):
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

        elif _is_list_of_int(value):
            # Edit as comma-separated text — writeback parses back to list[int]
            # so dynamics.IKChainSpec.node_indices round-trips.
            text = ", ".join(str(int(v)) for v in value)

            def _list_int_cb(_sender, app_data, _user_data, _attr=name):
                if self._obj is None:
                    return
                try:
                    parsed = [
                        int(part)
                        for part in str(app_data).replace(";", ",").split(",")
                        if part.strip() != ""
                    ]
                except ValueError:
                    return
                try:
                    setattr(self._obj, _attr, parsed)
                except (AttributeError, TypeError):
                    pass

            dpg.add_input_text(
                label=name,
                default_value=text,
                callback=_list_int_cb,
                parent=parent,
                tag=tag,
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

        Special case: ``dict`` fields (e.g. the ``params`` bag on
        :class:`pharos_engine.dynamics.JointSpec` / ``MotorSpec`` /
        ``SpringSpec`` / ``RopeSpec`` / ``IKChainSpec``) render as an
        inline key/value table so authors can tweak primitive entries
        without losing the dict.
        """
        import dearpygui.dearpygui as dpg

        if isinstance(value, dict):
            self._render_dict_field(parent, name, value)
            return

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

    def _render_dict_field(self, parent, name: str, value: dict) -> None:
        """Inline-render a dict-of-primitives bag as labelled key/value rows.

        Used for the kind-specific ``params`` dict shared by the dynamics
        spec dataclasses (``JointSpec.params``, ``MotorSpec.params``,
        ``SpringSpec.params``, ``RopeSpec.params``, ``IKChainSpec.params``).
        Empty dicts render a "(params bag, empty)" placeholder so the field
        still appears in the inspector.

        Each primitive entry gets its own DPG widget; mutations write back
        through ``self._obj.<name>[<key>] = app_data``.  Non-primitive values
        inside the dict fall through to a read-only ``key: repr`` row.
        """
        import dearpygui.dearpygui as dpg

        header_tag = self._unique_tag(f"{name}_header")
        section_tag = self._unique_tag(f"{name}_section")
        self._widget_map[name] = section_tag

        with dpg.group(parent=parent, tag=section_tag):
            entries = list(value.items())
            label = f"{name} (dict, {len(entries)} keys)"
            dpg.add_text(label, tag=header_tag)
            if not entries:
                dpg.add_text(
                    "  (params bag, empty)",
                    parent=section_tag,
                    tag=self._unique_tag(f"{name}_empty"),
                )
                return
            for key, val in entries:
                row_tag = self._unique_tag(f"{name}__{key}")
                if isinstance(val, bool):
                    dpg.add_checkbox(
                        label=f"{name}.{key}",
                        default_value=val,
                        callback=self._make_dict_callback(name, key),
                        parent=section_tag,
                        tag=row_tag,
                    )
                elif isinstance(val, int):
                    dpg.add_input_int(
                        label=f"{name}.{key}",
                        default_value=val,
                        callback=self._make_dict_callback(name, key),
                        parent=section_tag,
                        tag=row_tag,
                    )
                elif isinstance(val, float):
                    dpg.add_input_float(
                        label=f"{name}.{key}",
                        default_value=val,
                        callback=self._make_dict_callback(name, key),
                        parent=section_tag,
                        tag=row_tag,
                    )
                elif isinstance(val, str):
                    dpg.add_input_text(
                        label=f"{name}.{key}",
                        default_value=val,
                        callback=self._make_dict_callback(name, key),
                        parent=section_tag,
                        tag=row_tag,
                    )
                elif _is_float_tuple(val) and len(val) == self._FLOAT2_LEN:
                    dpg.add_input_floatx(
                        label=f"{name}.{key}",
                        default_value=list(val),
                        size=self._FLOAT2_LEN,
                        callback=self._make_dict_callback(name, key, as_tuple=True),
                        parent=section_tag,
                        tag=row_tag,
                    )
                elif _is_float_tuple(val) and len(val) == self._FLOAT3_LEN:
                    dpg.add_input_floatx(
                        label=f"{name}.{key}",
                        default_value=list(val),
                        size=self._FLOAT3_LEN,
                        callback=self._make_dict_callback(name, key, as_tuple=True),
                        parent=section_tag,
                        tag=row_tag,
                    )
                else:
                    # Unknown value type — read-only repr row.
                    dpg.add_text(
                        f"  {key}: {val!r}",
                        parent=section_tag,
                        tag=row_tag,
                    )

    def _make_dict_callback(self, attr_name: str, key: Any, as_tuple: bool = False):
        """Return a DPG callback that writes back into ``self._obj.<attr>[key]``.

        ``as_tuple=True`` coerces list-valued widget output (e.g. floatx)
        into a tuple before storing so the dict round-trips byte-for-byte.
        """
        def _cb(_sender, app_data, _user_data):  # noqa: ANN001
            if self._obj is None:
                return
            bag = getattr(self._obj, attr_name, None)
            if not isinstance(bag, dict):
                return
            try:
                if as_tuple and isinstance(app_data, (list, tuple)):
                    bag[key] = tuple(app_data)
                else:
                    bag[key] = app_data
            except (TypeError, AttributeError):
                pass

        return _cb

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
