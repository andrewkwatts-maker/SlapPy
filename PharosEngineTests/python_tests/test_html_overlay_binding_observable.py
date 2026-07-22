"""Headless tests for HtmlOverlay, Binding (filter/debounce/bidirectional),
Observable (__no_publish__, inheritance, event payload), and EventBus fan-out.

webview is mocked so no GUI context is needed.
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock

# Mock webview before any import
sys.modules.setdefault("webview", MagicMock())
sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("pharos_engine.compute.asset_compute", MagicMock())


# ===========================================================================
# HtmlOverlay
# ===========================================================================

class TestHtmlOverlayInit:
    def _overlay(self, w=800, h=600, title=""):
        from pharos_editor.ui.html_overlay import HtmlOverlay
        return HtmlOverlay(w, h, title)

    def test_instantiates(self):
        assert self._overlay() is not None

    def test_width_stored(self):
        assert self._overlay(w=1280)._width == 1280

    def test_height_stored(self):
        assert self._overlay(h=720)._height == 720

    def test_title_stored(self):
        assert self._overlay(title="Game HUD")._title == "Game HUD"

    def test_window_none_initially(self):
        assert self._overlay()._window is None

    def test_not_running_initially(self):
        assert self._overlay().is_running is False

    def test_default_html_non_empty(self):
        h = self._overlay()
        assert len(h._html) > 0

    def test_webview_missing_raises(self):
        import pytest
        import importlib
        # Temporarily remove webview mock
        orig = sys.modules.get("webview")
        sys.modules["webview"] = None
        # Need to reload the module to trigger the ImportError path
        if "pharos_editor.ui.html_overlay" in sys.modules:
            del sys.modules["pharos_editor.ui.html_overlay"]
        try:
            with pytest.raises(ImportError, match="pywebview"):
                from pharos_editor.ui.html_overlay import HtmlOverlay
                HtmlOverlay(800, 600)
        finally:
            sys.modules["webview"] = orig
            if "pharos_editor.ui.html_overlay" in sys.modules:
                del sys.modules["pharos_editor.ui.html_overlay"]


class TestHtmlOverlaySetHtml:
    def _overlay(self):
        from pharos_editor.ui.html_overlay import HtmlOverlay
        return HtmlOverlay(800, 600)

    def test_set_html_updates_field(self):
        h = self._overlay()
        h.set_html("<b>hello</b>")
        assert h._html == "<b>hello</b>"

    def test_set_html_overwrites(self):
        h = self._overlay()
        h.set_html("<p>first</p>")
        h.set_html("<p>second</p>")
        assert "<p>second</p>" in h._html

    def test_set_html_with_window_calls_load(self):
        h = self._overlay()
        mock_win = MagicMock()
        h._window = mock_win
        h.set_html("<p>reload</p>")
        mock_win.load_html.assert_called_once_with("<p>reload</p>")

    def test_set_html_load_exception_no_crash(self):
        h = self._overlay()
        mock_win = MagicMock()
        mock_win.load_html.side_effect = Exception("error")
        h._window = mock_win
        h.set_html("<p>test</p>")  # should not raise


class TestHtmlOverlaySetHud:
    def _overlay(self):
        from pharos_editor.ui.html_overlay import HtmlOverlay
        return HtmlOverlay(800, 600)

    def test_set_hud_includes_keys(self):
        h = self._overlay()
        h.set_hud({"HP": "100", "Speed": "80"})
        assert "HP" in h._html
        assert "Speed" in h._html

    def test_set_hud_includes_values(self):
        h = self._overlay()
        h.set_hud({"Score": "9999"})
        assert "9999" in h._html

    def test_set_hud_empty_dict(self):
        h = self._overlay()
        h.set_hud({})
        assert len(h._html) > 0  # still valid HTML

    def test_set_hud_produces_html_element(self):
        h = self._overlay()
        h.set_hud({"Key": "Val"})
        assert "<html>" in h._html.lower() or "html" in h._html.lower()


class TestHtmlOverlayLifecycle:
    def _overlay(self):
        from pharos_editor.ui.html_overlay import HtmlOverlay
        return HtmlOverlay(800, 600)

    def test_hide_no_crash_without_window(self):
        self._overlay().hide()  # should not raise

    def test_destroy_no_crash_without_window(self):
        self._overlay().destroy()  # should not raise

    def test_destroy_clears_window(self):
        h = self._overlay()
        mock_win = MagicMock()
        h._window = mock_win
        h.destroy()
        assert h._window is None

    def test_destroy_sets_running_false(self):
        h = self._overlay()
        h._running = True
        h.destroy()
        assert h.is_running is False

    def test_hide_calls_window_hide(self):
        h = self._overlay()
        mock_win = MagicMock()
        h._window = mock_win
        h.hide()
        mock_win.hide.assert_called_once()

    def test_destroy_calls_window_destroy(self):
        h = self._overlay()
        mock_win = MagicMock()
        h._window = mock_win
        h.destroy()
        mock_win.destroy.assert_called_once()


# ===========================================================================
# Binding — filter, debounce, bidirectional, formatter
# ===========================================================================

class TestBindingFilter:
    def _setup(self):
        from pharos_engine.event_bus import Observable, Binding

        class Src(Observable):
            pass

        class Tgt:
            value = None

        src, tgt = Src(), Tgt()
        return Binding, src, tgt

    def test_filter_passes_when_predicate_true(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "speed", tgt, "value")
        b.filter(lambda v: v > 5.0)
        src.speed = 10.0
        assert tgt.value == 10.0

    def test_filter_blocks_when_predicate_false(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "speed", tgt, "value")
        b.filter(lambda v: v > 5.0)
        src.speed = 3.0
        assert tgt.value is None  # not updated

    def test_filter_returns_self_for_chaining(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "x", tgt, "value")
        assert b.filter(lambda v: True) is b

    def test_filter_always_true(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "val", tgt, "value")
        b.filter(lambda v: True)
        src.val = 42
        assert tgt.value == 42

    def test_filter_updates_on_second_change_when_predicate_passes(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "level", tgt, "value")
        b.filter(lambda v: v >= 0)
        src.level = -1  # blocked
        assert tgt.value is None
        src.level = 5  # allowed
        assert tgt.value == 5


class TestBindingDebounce:
    def _setup(self):
        from pharos_engine.event_bus import Observable, Binding

        class Src(Observable):
            pass

        class Tgt:
            value = None

        src, tgt = Src(), Tgt()
        return Binding, src, tgt

    def test_debounce_returns_self(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "x", tgt, "value")
        assert b.debounce(0.1) is b

    def test_debounce_does_not_crash(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "x", tgt, "value")
        b.debounce(0.5)
        src.x = 10  # should not raise

    def test_debounce_eventually_updates(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "x", tgt, "value")
        b.debounce(0.0)  # zero debounce — immediate
        src.x = 7
        assert tgt.value == 7


class TestBindingBidirectional:
    def _setup(self):
        from pharos_engine.event_bus import Observable, Binding

        class Src(Observable):
            pass

        class ObsTgt(Observable):
            pass

        src, tgt = Src(), ObsTgt()
        return Binding, src, tgt

    def test_forward_binding(self):
        Binding, src, tgt = self._setup()
        Binding(src, "score", tgt, "score", bidirectional=True)
        src.score = 100
        assert tgt.score == 100

    def test_backward_binding(self):
        Binding, src, tgt = self._setup()
        Binding(src, "score", tgt, "score", bidirectional=True)
        tgt.score = 200
        assert src.score == 200

    def test_formatter_applied_forward(self):
        Binding, src, tgt = self._setup()
        Binding(src, "speed", tgt, "speed", formatter=lambda x: x * 2, bidirectional=False)
        src.speed = 5.0
        assert abs(tgt.speed - 10.0) < 1e-9

    def test_non_bidirectional_default(self):
        Binding, src, tgt = self._setup()
        b = Binding(src, "x", tgt, "x")
        assert b._bidirectional is False


class TestBindingFormatter:
    def _setup(self):
        from pharos_engine.event_bus import Observable, Binding

        class Src(Observable):
            pass

        class Tgt:
            value = None

        return Binding, Src(), Tgt()

    def test_formatter_doubles_value(self):
        Binding, src, tgt = self._setup()
        Binding(src, "x", tgt, "value", formatter=lambda v: v * 2)
        src.x = 3
        assert tgt.value == 6

    def test_formatter_string_conversion(self):
        Binding, src, tgt = self._setup()
        Binding(src, "score", tgt, "value", formatter=lambda v: f"{v:.0f} pts")
        src.score = 42
        assert tgt.value == "42 pts"

    def test_no_formatter_passes_raw(self):
        Binding, src, tgt = self._setup()
        Binding(src, "hp", tgt, "value")
        src.hp = 99
        assert tgt.value == 99


# ===========================================================================
# Observable — __no_publish__, inheritance, payload structure
# ===========================================================================

class TestObservableNoPublish:
    def _bus(self):
        from pharos_engine.event_bus import global_bus
        return global_bus

    def test_private_attr_not_published(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Obj(Observable):
            pass

        h = global_bus.subscribe("Obj._internal", lambda e: events.append(e))
        obj = Obj()
        obj._internal = 42
        global_bus.unsubscribe(h)
        assert events == []

    def test_no_publish_attr_skipped(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Obj(Observable):
            __no_publish__ = frozenset({"temp"})

        h = global_bus.subscribe("Obj.temp", lambda e: events.append(e))
        obj = Obj()
        obj.temp = 99
        global_bus.unsubscribe(h)
        assert events == []

    def test_public_attr_is_published(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Obj(Observable):
            __no_publish__ = frozenset({"excluded"})

        h = global_bus.subscribe("Obj.public_attr", lambda e: events.append(e))
        obj = Obj()
        obj.public_attr = 1
        global_bus.unsubscribe(h)
        assert len(events) == 1

    def test_multiple_no_publish_attrs(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Obj(Observable):
            __no_publish__ = frozenset({"a", "b", "c"})

        for attr in ("Obj.a", "Obj.b", "Obj.c"):
            global_bus.subscribe(attr, lambda e: events.append(e))

        obj = Obj()
        obj.a = 1
        obj.b = 2
        obj.c = 3
        assert events == []


class TestObservableInheritance:
    def test_child_publishes_with_own_name(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Parent(Observable):
            pass

        class Child(Parent):
            pass

        h = global_bus.subscribe("Child.x", lambda e: events.append(e))
        c = Child()
        c.x = 5
        global_bus.unsubscribe(h)
        assert len(events) == 1

    def test_parent_subscribe_does_not_catch_child_event(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Parent(Observable):
            pass

        class Child(Parent):
            pass

        h = global_bus.subscribe("Parent.x", lambda e: events.append(e))
        c = Child()
        c.x = 5  # publishes "Child.x", not "Parent.x"
        global_bus.unsubscribe(h)
        assert events == []


class TestObservableEventPayload:
    def test_payload_has_value(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Src(Observable):
            pass

        h = global_bus.subscribe("Src.count", lambda e: events.append(e))
        obj = Src()
        obj.count = 7
        global_bus.unsubscribe(h)

        inner = events[0]["_event"]
        assert inner.payload["value"] == 7

    def test_payload_has_attr_name(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Src(Observable):
            pass

        h = global_bus.subscribe("Src.score", lambda e: events.append(e))
        obj = Src()
        obj.score = 0
        global_bus.unsubscribe(h)

        inner = events[0]["_event"]
        assert inner.payload["attr"] == "score"

    def test_publisher_is_the_object(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Src(Observable):
            pass

        h = global_bus.subscribe("Src.hp", lambda e: events.append(e))
        obj = Src()
        obj.hp = 1
        global_bus.unsubscribe(h)

        inner = events[0]["_event"]
        assert inner.publisher is obj

    def test_event_name_contains_value(self):
        from pharos_engine.event_bus import Observable, global_bus
        events = []

        class Src(Observable):
            pass

        h = global_bus.subscribe("Src.level", lambda e: events.append(e))
        obj = Src()
        obj.level = 3
        global_bus.unsubscribe(h)

        inner = events[0]["_event"]
        assert "3" in inner.name or inner.payload["value"] == 3


# ===========================================================================
# EventBus — hierarchical fan-out
# ===========================================================================

class TestEventBusFanOut:
    def test_child_event_reaches_parent_subscriber(self):
        from pharos_engine.event_bus import global_bus, publish
        events = []
        h = global_bus.subscribe("Race", lambda e: events.append("Race"))
        publish("Race.PositionsUpdated", data={})
        global_bus.unsubscribe(h)
        assert "Race" in events

    def test_child_event_also_reaches_child_subscriber(self):
        from pharos_engine.event_bus import global_bus, publish
        events = []
        h = global_bus.subscribe("Race.PositionsUpdated", lambda e: events.append("child"))
        publish("Race.PositionsUpdated", data={})
        global_bus.unsubscribe(h)
        assert "child" in events

    def test_parent_event_does_not_reach_sibling(self):
        from pharos_engine.event_bus import global_bus, publish
        events = []
        h = global_bus.subscribe("Race.OtherEvent", lambda e: events.append("sibling"))
        publish("Race.PositionsUpdated", data={})
        global_bus.unsubscribe(h)
        assert events == []

    def test_listener_count_zero_for_unknown(self):
        from pharos_engine.event_bus import global_bus
        assert global_bus.listener_count("Completely.Unknown.Event.XYZ") == 0

    def test_listener_count_increases_on_subscribe(self):
        from pharos_engine.event_bus import global_bus
        evt = "__test_lc__"
        before = global_bus.listener_count(evt)
        h = global_bus.subscribe(evt, lambda e: None)
        assert global_bus.listener_count(evt) > before
        global_bus.unsubscribe(h)

    def test_listener_count_decreases_on_unsubscribe(self):
        from pharos_engine.event_bus import global_bus
        evt = "__test_lc2__"
        h = global_bus.subscribe(evt, lambda e: None)
        count_with = global_bus.listener_count(evt)
        global_bus.unsubscribe(h)  # pass the int handle, not the event name
        assert global_bus.listener_count(evt) < count_with

    def test_publish_returns_without_subscribers(self):
        from pharos_engine.event_bus import publish
        publish("Orphan.Event.NobodyListens", x=1)  # should not raise

    def test_multiple_subscribers_all_receive(self):
        from pharos_engine.event_bus import global_bus, publish
        results = []
        h1 = global_bus.subscribe("Multi.Test", lambda e: results.append(1))
        h2 = global_bus.subscribe("Multi.Test", lambda e: results.append(2))
        publish("Multi.Test")
        global_bus.unsubscribe(h1)
        global_bus.unsubscribe(h2)
        assert 1 in results and 2 in results
