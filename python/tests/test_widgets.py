"""Engine tests for ui/widgets/__init__.py — headless (PIL optional)."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draw(size=(400, 300)):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    return ImageDraw.Draw(img), img


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

class TestThemeDark:
    def test_dark_returns_theme(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.dark()
        assert isinstance(t, Theme)

    def test_dark_surface_is_dark(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.dark()
        # on_surface should be light (for readability on dark bg)
        assert t.on_surface[0] > 180

    def test_dark_primary_is_4tuple(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.dark()
        assert len(t.primary) == 4

    def test_font_size_body_positive(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.dark()
        assert t.font_size_body > 0

    def test_corner_radius_positive(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.dark()
        assert t.corner_radius > 0


class TestThemeLight:
    def test_light_returns_theme(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.light()
        assert isinstance(t, Theme)

    def test_light_surface_is_light(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.light()
        # surface should be lighter than dark theme
        assert t.surface[0] > 200

    def test_light_on_surface_is_dark(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.light()
        assert t.on_surface[0] < 50


class TestThemeFromDict:
    def test_from_dict_applies_known_keys(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.from_dict({"font_size_body": 18, "corner_radius": 8.0})
        assert t.font_size_body == 18
        assert t.corner_radius == 8.0

    def test_from_dict_ignores_unknown_keys(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.from_dict({"unknown_key": "value", "font_size_body": 12})
        assert t.font_size_body == 12

    def test_from_dict_empty_uses_defaults(self):
        from pharos_engine.ui.widgets import Theme
        t = Theme.from_dict({})
        t2 = Theme()
        assert t.font_size_body == t2.font_size_body


# ---------------------------------------------------------------------------
# Widget base
# ---------------------------------------------------------------------------

class TestWidgetInit:
    def test_defaults(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        assert w.x == 0
        assert w.y == 0
        assert w.w == 100
        assert w.h == 30
        assert w.tag == ""
        assert w.visible is True
        assert w.dirty is True

    def test_custom_geometry(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=10, y=20, w=80, h=40, tag="test")
        assert w.x == 10
        assert w.y == 20
        assert w.w == 80
        assert w.h == 40
        assert w.tag == "test"

    def test_event_value_initially_none(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        assert w._event_value is None

    def test_no_callbacks_initially(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        assert w._on_click is None
        assert w._on_change is None
        assert w._on_hover is None


class TestWidgetBind:
    def test_bind_adds_to_bindings(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()

        class _Obj:
            speed = 42.0

        obj = _Obj()
        result = w.bind(obj, "speed")
        assert result is w  # chaining
        assert len(w._bindings) == 1

    def test_update_polls_bound_value(self):
        from pharos_engine.ui.widgets import Widget

        class _Obj:
            speed = 99.0

        w = Widget()
        w.bind(_Obj(), "speed")
        w.dirty = False
        w.update()
        assert w.dirty is True

    def test_update_returns_dirty_flag(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        w.dirty = True
        assert w.update() is True
        w.dirty = False
        assert w.update() is False


class TestWidgetBindEvent:
    def test_bind_event_returns_self(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        result = w.bind_event("Test.Event")
        assert result is w

    def test_bind_event_adds_handle(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        w.bind_event("Test.EventHandle")
        assert len(w._event_handles) == 1

    def test_unbind_all_clears_handles(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        w.bind_event("Test.EventA")
        w.bind_event("Test.EventB")
        w.unbind_all()
        assert len(w._event_handles) == 0

    def test_unbind_all_clears_legacy_bindings(self):
        from pharos_engine.ui.widgets import Widget

        class _Obj:
            x = 1

        w = Widget()
        w.bind(_Obj(), "x")
        w.unbind_all()
        assert len(w._bindings) == 0

    def test_event_arrival_marks_dirty(self):
        from pharos_engine.ui.widgets import Widget
        from pharos_engine.event_bus import publish
        w = Widget()
        w.dirty = False
        w.bind_event("Widget.DirtyTest")
        publish("Widget.DirtyTest", value=7)
        assert w.dirty is True
        w.unbind_all()

    def test_event_arrival_sets_event_value(self):
        from pharos_engine.ui.widgets import Widget
        from pharos_engine.event_bus import publish
        w = Widget()
        w.bind_event("Widget.ValueTest")
        publish("Widget.ValueTest", value=123)
        assert w._event_value == 123
        w.unbind_all()

    def test_transform_applied_to_event_value(self):
        from pharos_engine.ui.widgets import Widget
        from pharos_engine.event_bus import publish
        w = Widget()
        w.bind_event("Widget.TransformTest", transform=lambda evt: getattr(evt, "value", 0) * 2)
        publish("Widget.TransformTest", value=5)
        assert w._event_value == 10
        w.unbind_all()


class TestWidgetCallbacks:
    def test_on_click_stored(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        cb = lambda _: None
        result = w.on_click(cb)
        assert result is w
        assert w._on_click is cb

    def test_on_change_stored(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        cb = lambda _: None
        w.on_change(cb)
        assert w._on_change is cb

    def test_on_hover_stored(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget()
        cb = lambda _: None
        w.on_hover(cb)
        assert w._on_hover is cb


class TestWidgetHandleEvent:
    def test_click_fires_callback(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=0, y=0, w=100, h=30)
        clicked = []
        w.on_click(lambda _: clicked.append(1))
        w.handle_event({"type": "mouse_down", "x": 50, "y": 10})
        assert len(clicked) == 1

    def test_click_outside_no_callback(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=0, y=0, w=100, h=30)
        clicked = []
        w.on_click(lambda _: clicked.append(1))
        w.handle_event({"type": "mouse_down", "x": 200, "y": 10})
        assert len(clicked) == 0

    def test_click_consumed(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=0, y=0, w=100, h=30)
        w.on_click(lambda _: None)
        result = w.handle_event({"type": "mouse_down", "x": 50, "y": 10})
        assert result is True

    def test_hover_marks_dirty(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=0, y=0, w=100, h=30)
        w.dirty = False
        w.handle_event({"type": "mouse_move", "x": 50, "y": 10})
        # Moving into widget → _hovered True → dirty
        assert w.dirty is True

    def test_hover_fires_callback(self):
        from pharos_engine.ui.widgets import Widget
        w = Widget(x=0, y=0, w=100, h=30)
        hovered = []
        w.on_hover(lambda _: hovered.append(1))
        w.handle_event({"type": "mouse_move", "x": 50, "y": 10})
        assert len(hovered) == 1


class TestWidgetApplyTheme:
    def test_apply_theme_updates_theme(self):
        from pharos_engine.ui.widgets import Widget, Theme
        w = Widget()
        new_theme = Theme.light()
        w.apply_theme(new_theme)
        assert w._theme is new_theme

    def test_apply_theme_marks_dirty(self):
        from pharos_engine.ui.widgets import Widget, Theme
        w = Widget()
        w.dirty = False
        w.apply_theme(Theme())
        assert w.dirty is True


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

class TestLabel:
    def test_init_text(self):
        from pharos_engine.ui.widgets import Label
        lb = Label(text="hello")
        assert lb.text == "hello"

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Label
        lb = Label(text="test", x=5, y=5, w=100, h=20)
        draw, _ = _make_draw()
        lb.draw(draw)

    def test_bind_format_adds_event_handle(self):
        from pharos_engine.ui.widgets import Label
        lb = Label()
        lb.bind_format("Test.LabelFormat", "{value:.1f} km/h")
        assert len(lb._event_handles) == 1
        lb.unbind_all()

    def test_bind_format_updates_event_value(self):
        from pharos_engine.ui.widgets import Label
        from pharos_engine.event_bus import publish
        lb = Label()
        lb.bind_format("Test.LabelFmtValue", "{value:.0f} km/h")
        publish("Test.LabelFmtValue", value=87.6)
        assert lb._event_value == "88 km/h"
        lb.unbind_all()

    def test_bind_format_returns_self(self):
        from pharos_engine.ui.widgets import Label
        lb = Label()
        result = lb.bind_format("Test.LabelChain", "{value}")
        assert result is lb
        lb.unbind_all()

    def test_pulse_end_updated_on_value(self):
        from pharos_engine.ui.widgets import Label
        from pharos_engine.event_bus import publish
        import time
        lb = Label()
        lb.bind_event("Test.LabelPulse")
        before = lb._pulse_end
        publish("Test.LabelPulse", value="x")
        assert lb._pulse_end > before
        lb.unbind_all()

    def test_event_value_used_in_draw(self):
        from pharos_engine.ui.widgets import Label
        from pharos_engine.event_bus import publish
        lb = Label(text="default", x=0, y=0, w=200, h=20)
        lb.bind_event("Test.LabelDraw")
        publish("Test.LabelDraw", value="updated_text")
        draw, _ = _make_draw()
        lb.draw(draw)  # should not raise
        lb.unbind_all()


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

class TestButton:
    def test_init_label(self):
        from pharos_engine.ui.widgets import Button
        b = Button(label="OK")
        assert b.label == "OK"

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Button
        b = Button(label="Click", x=10, y=10, w=80, h=28)
        draw, _ = _make_draw()
        b.draw(draw)

    def test_click_fires_callback(self):
        from pharos_engine.ui.widgets import Button
        hits = []
        b = Button(x=0, y=0, w=100, h=30)
        b.on_click(lambda _: hits.append(1))
        b.handle_event({"type": "mouse_down", "x": 50, "y": 10})
        assert len(hits) == 1

    def test_mouse_up_not_pressed(self):
        from pharos_engine.ui.widgets import Button
        b = Button(x=0, y=0, w=100, h=30)
        b.handle_event({"type": "mouse_down", "x": 50, "y": 10})
        b.handle_event({"type": "mouse_up", "x": 50, "y": 10})
        assert b._pressed is False


# ---------------------------------------------------------------------------
# ProgressBar
# ---------------------------------------------------------------------------

class TestProgressBar:
    def test_init_value(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar(value=0.7)
        assert pb.value == pytest.approx(0.7)

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar(value=0.5, x=0, y=0, w=100, h=16)
        draw, _ = _make_draw()
        pb.draw(draw)

    def test_lerp_color_returns_4tuple(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar()
        color = pb._lerp_color(0.5)
        assert len(color) == 4

    def test_lerp_color_at_zero(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar()
        color = pb._lerp_color(0.0)
        assert len(color) == 4

    def test_lerp_color_at_one(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar()
        color = pb._lerp_color(1.0)
        assert len(color) == 4

    def test_lerp_color_midpoint_is_interpolated(self):
        from pharos_engine.ui.widgets import ProgressBar
        # Use two-stop gradient for predictable result
        pb = ProgressBar(color_gradient=[(0.0, (0, 0, 0, 255)), (1.0, (100, 100, 100, 255))])
        mid = pb._lerp_color(0.5)
        assert 40 <= mid[0] <= 60  # approx 50

    def test_custom_gradient(self):
        from pharos_engine.ui.widgets import ProgressBar
        g = [(0.0, (255, 0, 0, 255)), (1.0, (0, 255, 0, 255))]
        pb = ProgressBar(color_gradient=g)
        assert pb._gradient == g

    def test_value_clamped_in_display(self):
        from pharos_engine.ui.widgets import ProgressBar
        pb = ProgressBar(value=2.0, transition_ms=0)
        draw, _ = _make_draw()
        pb.draw(draw)  # should not raise; value clamped internally


# ---------------------------------------------------------------------------
# StatBar
# ---------------------------------------------------------------------------

class TestStatBar:
    def test_init_label(self):
        from pharos_engine.ui.widgets import StatBar
        sb = StatBar(label="HP", value=0.8)
        assert sb.label == "HP"

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import StatBar
        sb = StatBar(label="HP", value=0.8, x=0, y=0, w=120, h=20)
        draw, _ = _make_draw()
        sb.draw(draw)

    def test_is_progress_bar(self):
        from pharos_engine.ui.widgets import StatBar, ProgressBar
        assert issubclass(StatBar, ProgressBar)


# ---------------------------------------------------------------------------
# Slider
# ---------------------------------------------------------------------------

class TestSlider:
    def test_init_range(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=5.0, min_val=0.0, max_val=10.0)
        assert s.min_val == 0.0
        assert s.max_val == 10.0
        assert s.value == 5.0

    def test_normalised_midpoint(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=5.0, min_val=0.0, max_val=10.0)
        assert s.normalised == pytest.approx(0.5)

    def test_normalised_at_min(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=0.0, min_val=0.0, max_val=10.0)
        assert s.normalised == pytest.approx(0.0)

    def test_normalised_at_max(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=10.0, min_val=0.0, max_val=10.0)
        assert s.normalised == pytest.approx(1.0)

    def test_normalised_zero_range(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=5.0, min_val=5.0, max_val=5.0)
        assert s.normalised == pytest.approx(0.0)

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Slider
        s = Slider(value=0.5, x=0, y=0, w=120, h=20)
        draw, _ = _make_draw()
        s.draw(draw)


# ---------------------------------------------------------------------------
# Dial
# ---------------------------------------------------------------------------

class TestDial:
    def test_init_value(self):
        from pharos_engine.ui.widgets import Dial
        d = Dial(value=0.3)
        assert d.value == pytest.approx(0.3)

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Dial
        d = Dial(value=0.5, x=10, y=10, w=80, h=80)
        draw, _ = _make_draw()
        d.draw(draw)

    def test_event_value_updates_displayed(self):
        from pharos_engine.ui.widgets import Dial
        from pharos_engine.event_bus import publish
        d = Dial(transition_ms=0, x=0, y=0, w=60, h=60)
        d.bind_event("Test.DialEvent")
        publish("Test.DialEvent", value=0.9)
        assert d._event_value == pytest.approx(0.9)
        d.unbind_all()


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class TestPanel:
    def test_add_child(self):
        from pharos_engine.ui.widgets import Panel, Label
        p = Panel(x=0, y=0, w=200, h=100)
        lb = Label(text="hi")
        result = p.add(lb)
        assert result is p
        assert lb in p.children

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Panel, Label
        p = Panel(x=0, y=0, w=200, h=100)
        p.add(Label(text="hi", x=5, y=5, w=80, h=20))
        draw, _ = _make_draw()
        p.draw(draw)

    def test_apply_theme_cascades(self):
        from pharos_engine.ui.widgets import Panel, Label, Theme
        p = Panel()
        lb = Label()
        p.add(lb)
        new_theme = Theme.light()
        p.apply_theme(new_theme)
        assert lb._theme is new_theme

    def test_handle_event_dispatches_to_children(self):
        from pharos_engine.ui.widgets import Panel, Button
        p = Panel(x=0, y=0, w=300, h=200)
        hits = []
        b = Button(label="X", x=10, y=10, w=80, h=30)
        b.on_click(lambda _: hits.append(1))
        p.add(b)
        p.handle_event({"type": "mouse_down", "x": 50, "y": 20})
        assert len(hits) == 1

    def test_invisible_panel_no_draw(self):
        from pharos_engine.ui.widgets import Panel
        p = Panel(x=0, y=0, w=200, h=100)
        p.visible = False
        draw, img = _make_draw()
        p.draw(draw)
        # Should not crash


# ---------------------------------------------------------------------------
# Checkbox
# ---------------------------------------------------------------------------

class TestCheckbox:
    def test_init_unchecked(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox()
        assert cb.checked is False

    def test_init_checked(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox(checked=True)
        assert cb.checked is True

    def test_toggle_on_click(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox(x=0, y=0, w=20, h=20)
        cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
        assert cb.checked is True

    def test_double_toggle(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox(x=0, y=0, w=20, h=20)
        cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
        cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
        assert cb.checked is False

    def test_on_change_fires(self):
        from pharos_engine.ui.widgets import Checkbox
        changes = []
        cb = Checkbox(x=0, y=0, w=20, h=20)
        cb.on_change(lambda v: changes.append(v))
        cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
        assert changes == [True]

    def test_click_outside_no_toggle(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox(x=0, y=0, w=20, h=20)
        cb.handle_event({"type": "mouse_down", "x": 100, "y": 100})
        assert cb.checked is False

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Checkbox
        cb = Checkbox(checked=True, label="Enable", x=5, y=5, w=20, h=20)
        draw, _ = _make_draw()
        cb.draw(draw)


# ---------------------------------------------------------------------------
# Dropdown
# ---------------------------------------------------------------------------

class TestDropdown:
    def test_init_options(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["A", "B", "C"])
        assert dd.options == ["A", "B", "C"]

    def test_value_property(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["X", "Y", "Z"], selected=1)
        assert dd.value == "Y"

    def test_value_empty_on_no_options(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown()
        assert dd.value == ""

    def test_click_opens(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["A", "B"], x=0, y=0, w=100, h=24)
        dd.handle_event({"type": "mouse_down", "x": 50, "y": 12})
        assert dd._open is True

    def test_click_again_closes(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["A", "B"], x=0, y=0, w=100, h=24)
        dd.handle_event({"type": "mouse_down", "x": 50, "y": 12})
        dd.handle_event({"type": "mouse_down", "x": 50, "y": 12})
        assert dd._open is False

    def test_select_option_changes_selected(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["Alpha", "Beta", "Gamma"],
                      selected=0, x=0, y=0, w=100, h=24)
        # Open it
        dd._open = True
        # "Beta" (index 1) is at row=0 among unselected options → y=0+24*1=24
        dd.handle_event({"type": "mouse_down", "x": 50, "y": 24 + 12})
        assert dd.selected == 1
        assert dd.value == "Beta"

    def test_on_change_fires_on_select(self):
        from pharos_engine.ui.widgets import Dropdown
        changes = []
        dd = Dropdown(options=["A", "B", "C"], selected=0,
                      x=0, y=0, w=100, h=24)
        dd.on_change(lambda v: changes.append(v))
        dd._open = True
        dd.handle_event({"type": "mouse_down", "x": 50, "y": 24 + 12})
        assert changes == ["B"]

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["One", "Two", "Three"],
                      selected=0, x=5, y=5, w=100, h=24)
        draw, _ = _make_draw()
        dd.draw(draw)

    def test_unselected_options_excludes_selected(self):
        from pharos_engine.ui.widgets import Dropdown
        dd = Dropdown(options=["A", "B", "C"], selected=1)
        unselected = dd._unselected_options()
        indices = [i for i, _ in unselected]
        assert 1 not in indices
        assert 0 in indices
        assert 2 in indices


# ---------------------------------------------------------------------------
# ScrollView
# ---------------------------------------------------------------------------

class TestScrollView:
    def test_init_scroll_offset(self):
        from pharos_engine.ui.widgets import ScrollView
        sv = ScrollView(x=0, y=0, w=200, h=100)
        assert sv.scroll_offset == pytest.approx(0.0)

    def test_scroll_by_positive(self):
        from pharos_engine.ui.widgets import ScrollView, Label
        sv = ScrollView(x=0, y=0, w=200, h=100)
        sv.add(Label(y=0, h=20))
        sv.add(Label(y=20, h=20))
        sv.add(Label(y=200, h=20))  # content taller than view
        sv.scroll_by(30)
        assert sv.scroll_offset > 0

    def test_scroll_by_clamped_at_zero(self):
        from pharos_engine.ui.widgets import ScrollView
        sv = ScrollView(x=0, y=0, w=200, h=100)
        sv.scroll_by(-50)
        assert sv.scroll_offset == pytest.approx(0.0)

    def test_scroll_to_sets_offset(self):
        from pharos_engine.ui.widgets import ScrollView, Label
        sv = ScrollView(x=0, y=0, w=200, h=100)
        sv.add(Label(y=0, h=20))
        sv.add(Label(y=200, h=20))  # content > view
        sv.scroll_to(50)
        assert sv.scroll_offset == pytest.approx(50.0)

    def test_at_bottom_initially_true_when_short(self):
        from pharos_engine.ui.widgets import ScrollView
        sv = ScrollView(x=0, y=0, w=200, h=100)
        assert sv.at_bottom is True

    def test_at_bottom_false_when_scrolled_up(self):
        from pharos_engine.ui.widgets import ScrollView, Label
        sv = ScrollView(x=0, y=0, w=200, h=50, scroll_speed=20)
        for i in range(10):
            sv.add(Label(y=i * 30, h=30))
        # Don't scroll — should not be at bottom (content > view, offset=0)
        assert sv.at_bottom is False

    def test_scroll_event_handled(self):
        from pharos_engine.ui.widgets import ScrollView, Label
        sv = ScrollView(x=0, y=0, w=200, h=100, scroll_speed=20)
        for i in range(10):
            sv.add(Label(y=i * 30, h=30))
        result = sv.handle_event({"type": "scroll", "x": 100, "y": 50, "dy": -1})
        assert result is True
        assert sv.scroll_offset > 0

    def test_draw_no_exception(self):
        from pharos_engine.ui.widgets import ScrollView, Label
        sv = ScrollView(x=0, y=0, w=200, h=100)
        for i in range(5):
            sv.add(Label(text=f"item {i}", y=i*20, h=20))
        draw, _ = _make_draw()
        sv.draw(draw)


# ---------------------------------------------------------------------------
# ImageWidget
# ---------------------------------------------------------------------------

class TestImageWidget:
    def test_init_no_image(self):
        from pharos_engine.ui.widgets import ImageWidget
        iw = ImageWidget(x=0, y=0, w=100, h=100)
        assert iw._image is None

    def test_set_image(self):
        from PIL import Image
        from pharos_engine.ui.widgets import ImageWidget
        iw = ImageWidget(x=0, y=0, w=80, h=80)
        img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
        iw.set_image(img)
        assert iw._image is img
        assert iw.dirty is True
        assert iw._cached_pil is None

    def test_resolve_pil_from_pil_image(self):
        from PIL import Image
        from pharos_engine.ui.widgets import ImageWidget
        img = Image.new("RGBA", (32, 32), (0, 255, 0, 255))
        iw = ImageWidget(image=img, x=0, y=0, w=64, h=64)
        resolved = iw._resolve_pil()
        assert resolved is img

    def test_resolve_pil_returns_none_when_no_image(self):
        from pharos_engine.ui.widgets import ImageWidget
        iw = ImageWidget()
        assert iw._resolve_pil() is None

    def test_draw_no_exception_with_image(self):
        from PIL import Image
        from pharos_engine.ui.widgets import ImageWidget
        img = Image.new("RGBA", (32, 32), (128, 128, 128, 255))
        iw = ImageWidget(image=img, fit="contain", x=0, y=0, w=80, h=80)
        draw, _ = _make_draw()
        iw.draw(draw)

    def test_draw_no_exception_no_image(self):
        from pharos_engine.ui.widgets import ImageWidget
        iw = ImageWidget(x=0, y=0, w=80, h=80)
        draw, _ = _make_draw()
        iw.draw(draw)

    def test_fit_modes_no_exception(self):
        from PIL import Image
        from pharos_engine.ui.widgets import ImageWidget
        img = Image.new("RGBA", (50, 50), (200, 100, 50, 255))
        for fit in ("contain", "cover", "stretch", "none"):
            iw = ImageWidget(image=img, fit=fit, x=0, y=0, w=80, h=60)
            draw, _ = _make_draw()
            iw.draw(draw)


# ---------------------------------------------------------------------------
# LayoutBox
# ---------------------------------------------------------------------------

class TestLayoutBoxInit:
    def test_defaults(self):
        from pharos_engine.ui.widgets import LayoutBox
        lb = LayoutBox()
        assert lb.direction == "column"
        assert lb.align == "start"
        assert lb.gap > 0
        assert lb.padding >= 0

    def test_custom_params(self):
        from pharos_engine.ui.widgets import LayoutBox
        lb = LayoutBox(direction="row", align="center", gap=8, padding=12,
                       x=10, y=20, w=300, h=200)
        assert lb.direction == "row"
        assert lb.align == "center"
        assert lb.gap == 8
        assert lb.padding == 12

    def test_add_child(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox()
        lbl = Label(text="test")
        result = lb.add(lbl)
        assert result is lb
        assert lbl in lb._children

    def test_add_nested_layoutbox(self):
        from pharos_engine.ui.widgets import LayoutBox
        parent = LayoutBox()
        child = LayoutBox()
        parent.add(child)
        assert child in parent._children


class TestLayoutBoxLayout:
    def test_column_sets_y_positions(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox(direction="column", gap=4, padding=0,
                       x=0, y=0, w=200, h=200)
        w1 = Label(h=20)
        w2 = Label(h=20)
        lb.add(w1).add(w2)
        lb.layout()
        assert w1.y < w2.y

    def test_row_sets_x_positions(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox(direction="row", gap=4, padding=0,
                       x=0, y=0, w=400, h=100)
        w1 = Label(w=60)
        w2 = Label(w=60)
        lb.add(w1).add(w2)
        lb.layout()
        assert w1.x < w2.x

    def test_stretch_sets_width_in_column(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox(direction="column", align="stretch",
                       padding=10, x=0, y=0, w=200, h=200)
        w = Label()
        lb.add(w)
        lb.layout()
        assert w.w == pytest.approx(200 - 2 * 10)

    def test_stretch_sets_height_in_row(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox(direction="row", align="stretch",
                       padding=10, x=0, y=0, w=400, h=100)
        w = Label()
        lb.add(w)
        lb.layout()
        assert w.h == pytest.approx(100 - 2 * 10)

    def test_layout_with_bounds(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox()
        lb.add(Label(h=30))
        lb.layout((0, 0, 300, 400))
        assert lb.w == pytest.approx(300)
        assert lb.h == pytest.approx(400)


class TestLayoutBoxApplyTheme:
    def test_theme_cascades_to_children(self):
        from pharos_engine.ui.widgets import LayoutBox, Label, Theme
        lb = LayoutBox()
        lbl = Label()
        lb.add(lbl)
        new_theme = Theme.light()
        lb.apply_theme(new_theme)
        assert lbl._theme is new_theme


class TestLayoutBoxHandleEvent:
    def test_dispatches_to_child(self):
        from pharos_engine.ui.widgets import LayoutBox, Button
        lb = LayoutBox(x=0, y=0, w=300, h=200)
        hits = []
        b = Button(label="X", x=10, y=10, w=80, h=30)
        b.on_click(lambda _: hits.append(1))
        lb.add(b)
        lb.handle_event({"type": "mouse_down", "x": 50, "y": 20})
        assert len(hits) == 1


class TestLayoutBoxRenderToLayer:
    def test_render_to_layer_returns_layer(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        lb = LayoutBox(x=0, y=0, w=200, h=100)
        lb.add(Label(text="hi", x=10, y=10, w=80, h=20))
        lb.layout()
        result = lb.render_to_layer()
        if result is not None:
            assert hasattr(result, "_image_data")

    def test_render_to_layer_with_size(self):
        from pharos_engine.ui.widgets import LayoutBox
        lb = LayoutBox(x=0, y=0, w=100, h=50)
        result = lb.render_to_layer(size=(200, 150))
        if result is not None:
            assert result._image_data.shape[0] == 150
            assert result._image_data.shape[1] == 200


class TestLayoutBoxFromDict:
    def test_from_dict_empty_children(self):
        from pharos_engine.ui.widgets import LayoutBox
        lb = LayoutBox._from_dict({"direction": "row"})
        assert lb.direction == "row"
        assert lb._children == []

    def test_from_dict_with_label_child(self):
        from pharos_engine.ui.widgets import LayoutBox, Label
        data = {
            "direction": "column",
            "children": [
                {"type": "Label", "text": "Hello", "w": 100, "h": 20}
            ]
        }
        lb = LayoutBox._from_dict(data)
        assert len(lb._children) == 1
        assert isinstance(lb._children[0], Label)
        assert lb._children[0].text == "Hello"

    def test_from_dict_unknown_widget_type_skipped(self):
        from pharos_engine.ui.widgets import LayoutBox
        data = {
            "children": [{"type": "UnknownWidget"}]
        }
        lb = LayoutBox._from_dict(data)
        assert lb._children == []

    def test_from_dict_nested_layoutbox(self):
        from pharos_engine.ui.widgets import LayoutBox
        data = {
            "children": [
                {"type": "LayoutBox", "direction": "row", "children": []}
            ]
        }
        lb = LayoutBox._from_dict(data)
        assert len(lb._children) == 1
        assert isinstance(lb._children[0], LayoutBox)

    def test_from_dict_all_widget_types(self):
        from pharos_engine.ui.widgets import LayoutBox
        types = ["Label", "Button", "ProgressBar", "StatBar",
                 "Slider", "Dial", "Panel", "Checkbox", "Dropdown"]
        data = {"children": [{"type": t, "w": 100, "h": 24} for t in types]}
        lb = LayoutBox._from_dict(data)
        assert len(lb._children) == len(types)


class TestLayoutBoxLoadYml:
    def test_load_nonexistent_returns_empty(self):
        from pharos_engine.ui.widgets import LayoutBox
        lb = LayoutBox.load_yml("nonexistent_path_xyz.yml")
        assert isinstance(lb, LayoutBox)

    def test_load_valid_yml(self, tmp_path):
        pytest.importorskip("yaml")
        from pharos_engine.ui.widgets import LayoutBox, Label
        yml_file = tmp_path / "test_layout.yml"
        yml_file.write_text(
            "direction: column\n"
            "children:\n"
            "  - type: Label\n"
            "    text: Hello\n"
            "    w: 100\n"
            "    h: 20\n",
            encoding="utf-8"
        )
        lb = LayoutBox.load_yml(str(yml_file))
        assert len(lb._children) == 1
        assert isinstance(lb._children[0], Label)

    def test_load_bad_yml_returns_empty(self, tmp_path):
        pytest.importorskip("yaml")
        from pharos_engine.ui.widgets import LayoutBox
        bad = tmp_path / "bad.yml"
        bad.write_text("this: is: invalid: yaml: {{{", encoding="utf-8")
        lb = LayoutBox.load_yml(str(bad))
        assert isinstance(lb, LayoutBox)
