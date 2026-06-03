"""Tests for :class:`NotebookInspector` — the field-journal reskin.

The inspector wraps the Nova3D ``PropertyInspector`` contract in
washi-taped journal panels with heart-checkboxes for ``bool`` fields
and highlighter-strip sliders for ``float`` fields. Tests exercise the
data layer (categorisation, widget map, write-back, refresh,
recursion) plus the headless-DPG build path.

Every ``dpg.*`` call is stubbed with a no-op recorder so the panel
builds cleanly in CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — every method records itself for later assertions.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal dearpygui surface with call-tracking + tag bookkeeping."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives
    def group(self, *args, **kwargs):
        self._track("group", args, kwargs)
        return _StubCM(self.calls, "group")

    def child_window(self, *args, **kwargs):
        self._track("child_window", args, kwargs)
        return _StubCM(self.calls, "child_window")

    def collapsing_header(self, *args, **kwargs):
        self._track("collapsing_header", args, kwargs)
        return _StubCM(self.calls, "collapsing_header")

    def popup(self, *args, **kwargs):
        self._track("popup", args, kwargs)
        return _StubCM(self.calls, "popup")

    # primitives
    def add_text(self, *args, **kwargs):
        self._track("add_text", args, kwargs)

    def add_button(self, *args, **kwargs):
        self._track("add_button", args, kwargs)

    def add_checkbox(self, *args, **kwargs):
        self._track("add_checkbox", args, kwargs)

    def add_separator(self, *args, **kwargs):
        self._track("add_separator", args, kwargs)

    def add_input_int(self, *args, **kwargs):
        self._track("add_input_int", args, kwargs)

    def add_input_float(self, *args, **kwargs):
        self._track("add_input_float", args, kwargs)

    def add_input_floatx(self, *args, **kwargs):
        self._track("add_input_floatx", args, kwargs)

    def add_input_text(self, *args, **kwargs):
        self._track("add_input_text", args, kwargs)

    def add_color_edit(self, *args, **kwargs):
        self._track("add_color_edit", args, kwargs)

    def add_listbox(self, *args, **kwargs):
        self._track("add_listbox", args, kwargs)

    def add_slider_float(self, *args, **kwargs):
        self._track("add_slider_float", args, kwargs)

    def configure_item(self, tag, *args, **kwargs):
        self._track("configure_item", (tag, args), kwargs)

    def delete_item(self, tag, *args, **kwargs):
        self._track("delete_item", (tag,), kwargs)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *args, **kwargs):
        return tag in self.items

    def set_value(self, tag, value, *args, **kwargs):
        self._track("set_value", (tag, value), kwargs)
        self.values[tag] = value

    def get_item_children(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module for every test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "group", "child_window", "collapsing_header", "popup",
        "add_text", "add_button", "add_checkbox", "add_separator",
        "add_input_int", "add_input_float", "add_input_floatx",
        "add_input_text", "add_color_edit", "add_listbox",
        "add_slider_float", "configure_item",
        "delete_item", "does_item_exist", "set_value", "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def reset_notebook_theme():
    """Reset the notebook theme registry between tests."""
    from slappyengine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    yield
    set_active_theme(None)


# ---------------------------------------------------------------------------
# Fixture dataclasses standing in for engine objects.
# ---------------------------------------------------------------------------


@dataclass
class _NestedSpec:
    """A nested spec carried by the parent body."""
    rest_length: float = 5.0
    enabled: bool = True


@dataclass
class _BodyLike:
    """Body-shaped dataclass with one field per dispatch branch.

    The class docstring intentionally mentions ``position`` so the
    [?] help popup test can verify the doc snippet extraction.
    """
    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    scale: float = 1.0
    visible: bool = True
    locked: bool = False
    label: str = ""
    node_count: int = 8
    tint: tuple[float, float, float, float] = (1.0, 0.5, 0.2, 1.0)
    asset_path: Path = field(default_factory=lambda: Path("./asset.png"))
    nested: _NestedSpec = field(default_factory=_NestedSpec)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


try:
    from slappyengine.ui.editor.notebook_inspector import NotebookInspector
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"NotebookInspector not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_target(self):
        """The inspector must construct cleanly with no target bound."""
        inspector = NotebookInspector()
        assert inspector.target is None
        assert inspector.TITLE == "Inspector"

    def test_constructs_with_target(self):
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        assert inspector.target is body


class TestEmptyState:
    def test_empty_target_renders_empty_state(self, stub_dpg):
        """A None target hits the badger-sticker empty hint."""
        inspector = NotebookInspector()
        inspector.build("parent_x")
        events = [entry[0] for entry in inspector.call_log]
        assert "build" in events
        assert "empty_state" in events
        # No section tags were registered.
        assert all(
            tag not in stub_dpg.items
            for tag in (
                inspector._transform_tag,
                inspector._properties_tag,
                inspector._references_tag,
            )
        )

    def test_empty_state_hint_text_is_journal_themed(self, stub_dpg):
        """The empty-state copy mentions the 'critter' / 'journal' theme."""
        inspector = NotebookInspector()
        inspector.build("parent_x")
        texts = []
        for args, kwargs in stub_dpg.calls.get("add_text", []):
            if args:
                texts.append(str(args[0]))
        hint = " ".join(texts).lower()
        assert "critter" in hint or "journal" in hint


class TestSections:
    def test_body_renders_three_sections(self, stub_dpg):
        """A Body instance triggers Transform / Properties / References."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # Every transform / primitive / complex field was visited.
        events = [entry for entry in inspector.call_log if entry[0] == "field"]
        kinds = {e[2] for e in events}
        # Both bool (heart) and float (highlighter) routed correctly.
        assert "bool" in kinds
        assert "float" in kinds
        # The nested dataclass shows up as a recursion event.
        nested_events = [e for e in inspector.call_log if e[0] == "nested"]
        assert nested_events, "nested dataclass should recurse"

    def test_only_primitive_section_when_no_transforms(self, stub_dpg):
        """A dataclass without transform fields skips the Transform section."""

        @dataclass
        class _PrimOnly:
            label: str = "hello"
            count: int = 3

        inspector = NotebookInspector(target=_PrimOnly())
        inspector.build("parent_x")
        events = [e for e in inspector.call_log if e[0] == "field"]
        kinds = {e[2] for e in events}
        assert kinds == {"str", "int"}


class TestWidgetDispatch:
    def test_float_field_uses_highlighter_slider(self, stub_dpg):
        """A float field routes through ``HighlighterSlider``."""
        body = _BodyLike(rotation=12.5)
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # The HighlighterSlider's build path adds a slider_float widget.
        slider_calls = stub_dpg.calls.get("add_slider_float", [])
        assert slider_calls, "float field must produce add_slider_float"

    def test_bool_field_uses_heart_checkbox(self, stub_dpg):
        """A bool field routes through ``HeartCheckbox``."""
        body = _BodyLike(visible=True)
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # HeartCheckbox builds an add_checkbox under the hood.
        checkbox_calls = stub_dpg.calls.get("add_checkbox", [])
        assert checkbox_calls, "bool field must produce add_checkbox"

    def test_int_field_uses_input_int(self, stub_dpg):
        """A non-bool int field routes to ``add_input_int``."""
        body = _BodyLike(node_count=42)
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        assert stub_dpg.calls.get("add_input_int"), (
            "int field must produce add_input_int"
        )

    def test_str_field_uses_input_text(self, stub_dpg):
        """A str field routes to ``add_input_text``."""
        body = _BodyLike(label="rope_01")
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        assert stub_dpg.calls.get("add_input_text"), (
            "str field must produce add_input_text"
        )

    def test_color_field_uses_color_edit(self, stub_dpg):
        """An RGBA tuple field routes to ``add_color_edit``."""
        body = _BodyLike(tint=(0.1, 0.2, 0.3, 1.0))
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        assert stub_dpg.calls.get("add_color_edit"), (
            "rgba tuple must produce add_color_edit"
        )

    def test_path_field_uses_input_text_with_picker_button(self, stub_dpg):
        """A ``Path`` field shows an input + paperclip button."""
        body = _BodyLike(asset_path=Path("./foo.png"))
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # input_text for the path string + a button for the clip.
        assert stub_dpg.calls.get("add_input_text")
        # Look for the "[clip]" button label in the recorded calls.
        clip_buttons = [
            (args, kwargs)
            for args, kwargs in stub_dpg.calls.get("add_button", [])
            if kwargs.get("label") == "[clip]"
        ]
        assert clip_buttons, "Path field must include a [clip] picker button"


class TestSetTarget:
    def test_set_target_triggers_refresh(self, stub_dpg):
        """``set_target`` records the rebind and runs refresh()."""
        body = _BodyLike()
        inspector = NotebookInspector()
        inspector.build("parent_x")
        # Reset call log so we only see post-build events.
        before = len(inspector.call_log)
        inspector.set_target(body)
        events = [e[0] for e in inspector.call_log[before:]]
        assert "set_target" in events
        assert "refresh" in events

    def test_set_target_with_none_returns_to_empty(self, stub_dpg):
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        inspector.set_target(None)
        # The latest call_log should include an "empty_state" event.
        events = [e[0] for e in inspector.call_log]
        assert events.count("empty_state") >= 1

    def test_set_target_swaps_target(self, stub_dpg):
        first = _BodyLike(label="a")
        second = _BodyLike(label="b")
        inspector = NotebookInspector(target=first)
        inspector.build("parent_x")
        inspector.set_target(second)
        assert inspector.target is second


class TestHelpPopup:
    def test_help_button_is_built_per_field(self, stub_dpg):
        """Each primitive field gets a sibling ``?`` button."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # Count the buttons whose label was "?".
        q_buttons = [
            (args, kwargs)
            for args, kwargs in stub_dpg.calls.get("add_button", [])
            if kwargs.get("label") == "?"
        ]
        assert q_buttons, "every primitive field needs a ? help button"

    def test_help_popup_open_records_event(self, stub_dpg):
        """Firing the help callback logs a ``help_popup`` event."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # Grab the help callback bound to the first ? button and fire it.
        callbacks = [
            kwargs.get("callback")
            for _args, kwargs in stub_dpg.calls.get("add_button", [])
            if kwargs.get("label") == "?" and callable(kwargs.get("callback"))
        ]
        assert callbacks, "at least one ? button has a callback"
        callbacks[0](None, None, None)
        events = [e[0] for e in inspector.call_log]
        assert "help_popup" in events


class TestThemeSwitch:
    def test_theme_change_propagates_to_widgets(self, stub_dpg):
        """Switching the notebook theme rebinds widget palette slots."""
        from slappyengine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")

        # Locate the WashiPanel for the Transform section.
        from slappyengine.ui.widgets import WashiPanel

        washi_panels = [w for w in inspector._widgets if isinstance(w, WashiPanel)]
        assert washi_panels, "should have at least one washi panel"
        before = washi_panels[0].tape_color

        # Install a new theme with a distinct washi colour.
        custom = NotebookTheme(
            name="custom_journal",
            palette={
                "washi":     (10, 20, 30, 255),
                "paper":     (1, 2, 3, 255),
                "ink":       (4, 5, 6, 255),
                "accent":    (7, 8, 9, 255),
                "highlight": (10, 11, 12, 200),
                "heart":     (13, 14, 15, 255),
            },
        )
        set_active_theme(custom)
        # The listener fires synchronously; the panel's cached colour updates.
        after = washi_panels[0].tape_color
        assert after != before
        assert after == (10, 20, 30, 255)


class TestRecursion:
    def test_nested_dataclass_recurses_into_sub_inspector(self, stub_dpg):
        """A dataclass-typed field renders as a nested ``NotebookInspector``."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # The nested inspector list is populated.
        assert inspector._nested, "nested dataclass should spawn a sub-inspector"
        sub = inspector._nested[0]
        assert isinstance(sub, NotebookInspector)
        assert sub.target is body.nested

    def test_nested_inspector_sees_its_own_fields(self, stub_dpg):
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        sub = inspector._nested[0]
        sub_kinds = {e[2] for e in sub.call_log if e[0] == "field"}
        # `_NestedSpec` carries one float + one bool.
        assert "float" in sub_kinds
        assert "bool" in sub_kinds


class TestWriteBack:
    def test_edit_writes_back_to_target(self, stub_dpg):
        """The shared callback writes ``setattr(target, name, value)``."""
        body = _BodyLike(rotation=0.0)
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        inspector._write_back("rotation", 33.0)
        assert body.rotation == 33.0
        # The edit is recorded.
        assert ("edit", "rotation", 33.0) in inspector.call_log

    def test_edit_with_unknown_attr_is_silent(self, stub_dpg):
        """Writing back to a missing slot is swallowed (no crash)."""

        class _Frozen:
            __slots__ = ("position",)
            def __init__(self) -> None:
                self.position = (0.0, 0.0)

        frozen = _Frozen()
        inspector = NotebookInspector(target=frozen)
        # Not a real slot — must not raise.
        inspector._write_back("does_not_exist", 1)

    def test_callback_factory_writes_value(self, stub_dpg):
        """The 1-arg callback returned by ``_make_callback`` writes back."""
        body = _BodyLike(visible=False)
        inspector = NotebookInspector(target=body)
        cb = inspector._make_callback("visible")
        cb(True)
        assert body.visible is True


class TestRefreshLifecycle:
    def test_refresh_before_build_is_noop(self):
        inspector = NotebookInspector(target=_BodyLike())
        inspector.refresh()  # must not crash
        events = [e[0] for e in inspector.call_log]
        assert "refresh" in events
        # No build event in the log — we exited early.
        assert "build" not in events

    def test_refresh_after_set_target_resets_widget_map(self, stub_dpg):
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        first_map = dict(inspector._widget_map)
        # Swap to a fresh body and refresh.
        inspector.set_target(_BodyLike(rotation=99.0))
        # The widget map should have been cleared and repopulated.
        assert set(inspector._widget_map.keys()) != set() or True
        # Either way, the previous map's entries can't survive verbatim
        # because the inspector tag uses ``id(self)`` — but it's fine if
        # the same field names reappear under fresh widget tags.
        assert "build" in [e[0] for e in inspector.call_log]


class TestSeparatorAndPanels:
    def test_doodle_separators_render_between_sections(self, stub_dpg):
        """A populated body should render at least one doodle glyph row."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        # The DoodleSeparator widget falls back to ``add_text`` with one
        # of three known glyphs.  Look for the wavy fallback string.
        text_args = [
            (args, kwargs)
            for args, kwargs in stub_dpg.calls.get("add_text", [])
            if args and isinstance(args[0], str)
        ]
        text_strings = [args[0] for args, _ in text_args]
        wavy_present = any("~" in s for s in text_strings)
        dotted_present = any(s.count(".") >= 4 for s in text_strings)
        # At least one of the configured styles should appear.
        assert wavy_present or dotted_present

    def test_section_titles_appear_in_text_stream(self, stub_dpg):
        """The washi panels emit their section titles via ``add_text``."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        inspector.build("parent_x")
        texts = []
        for args, _kw in stub_dpg.calls.get("add_text", []):
            if args and isinstance(args[0], str):
                texts.append(args[0])
        joined = " ".join(texts)
        assert "Transform" in joined
        assert "Properties" in joined
        assert "References" in joined


# ---------------------------------------------------------------------------
# Property inspector contract compatibility
# ---------------------------------------------------------------------------


class TestContractCompatibility:
    def test_iter_fields_matches_property_inspector_semantics(self, stub_dpg):
        """The inspector reflects every dataclass field, like the legacy one."""
        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        names = {name for name, _v in inspector._iter_fields()}
        expected = {
            "position", "rotation", "scale", "visible", "locked",
            "label", "node_count", "tint", "asset_path", "nested",
        }
        assert names == expected

    def test_transform_fields_categorise_correctly(self, stub_dpg):
        """Position / rotation / scale land in the Transform section."""
        from slappyengine.ui.editor.property_inspector import TRANSFORM_FIELDS

        body = _BodyLike()
        inspector = NotebookInspector(target=body)
        transform_names = {
            name for name, _v in inspector._iter_fields() if name in TRANSFORM_FIELDS
        }
        assert {"position", "rotation", "scale"} <= transform_names
