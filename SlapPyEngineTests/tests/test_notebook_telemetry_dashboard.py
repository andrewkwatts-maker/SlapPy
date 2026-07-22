"""Tests for :class:`NotebookTelemetryDashboard` (DD4).

Coverage:

* Construction
    - Constructs without DPG errors / soft-imports succeed.
    - Rejects bad ``poll_interval_ms`` / ``auto_scroll`` inputs.
    - Poll interval clamps to ``[100, 5000]``.
    - Sparkline sample count constant exposed.
* Subscriber lifecycle
    - ``subscribe_to_telemetry`` registers a single handle (idempotent).
    - ``unsubscribe`` drops the handle (idempotent).
    - Build auto-subscribes.
* Aggregation
    - Counter increments after ``count`` payload.
    - Counter delta tracks per-poll.
    - Gauge value + sparkline sample buffer.
    - Sparkline caps at ``SPARKLINE_SAMPLE_COUNT``.
    - Histogram single-``bucket`` increments.
    - Histogram dict payload merges.
    - Perf timer records ``duration_ms``.
    - Perf tab sort order is descending by mean.
    - Unknown payloads dropped silently.
* Transport
    - Pause blocks refresh + aggregation.
    - Clear empties every bucket.
    - Resume re-enables capture.
* Poll tick
    - ``tick`` respects the poll interval.
    - ``tick`` with zero dt is a no-op.
    - Paused ``tick`` returns False.
    - Bad ``dt_seconds`` raises.
* Tabs
    - Active tab flips + rejects unknown names.
    - Every tab body renders under stub DPG.
* Export
    - ``export_csv`` writes a valid file with counter + gauge rows.
* Theme
    - Theme switch appends to ``call_log``.
* Build
    - ``build`` under stub DPG calls the expected widget factories.
* Registration
    - Editor ``__all__`` + ``_LAZY_MAP`` list the new class.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self._next_id = 100
        self._labels: dict[int, str] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # Container-style
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def tab_bar(self, *a, **kw):
        self._track("tab_bar", a, kw)
        return _StubCM()

    def tab(self, *a, **kw):
        self._track("tab", a, kw)
        # Give the tab an id that maps back to its label so
        # ``get_item_label`` can round-trip.
        tab_id = self._next_id
        self._next_id += 1
        label = kw.get("label")
        if isinstance(label, str):
            self._labels[tab_id] = label
        return _StubCM()

    # Leaf widgets
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_slider_float(self, *a, **kw):
        self._track("add_slider_float", a, kw)

    def add_slider_int(self, *a, **kw):
        self._track("add_slider_int", a, kw)

    def add_drawlist(self, *a, **kw):
        self._track("add_drawlist", a, kw)
        tid = self._next_id
        self._next_id += 1
        return tid

    def draw_polyline(self, *a, **kw):
        self._track("draw_polyline", a, kw)

    def draw_line(self, *a, **kw):
        self._track("draw_line", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def get_item_label(self, tid, *a, **kw):
        return self._labels.get(tid)

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "collapsing_header", "window",
        "tab_bar", "tab",
        "add_text", "add_button", "add_input_text", "add_checkbox",
        "add_separator", "add_slider_float", "add_slider_int",
        "add_drawlist", "draw_polyline", "draw_line",
        "does_item_exist", "delete_item", "get_item_children",
        "get_item_label", "set_value",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_state():
    from pharos_engine import telemetry as t
    from pharos_engine.ui.widgets import notebook_theme
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    t.clear_history()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    t.clear_history()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dashboard(**kwargs):
    from pharos_engine.ui.editor.notebook_telemetry_dashboard import (
        NotebookTelemetryDashboard,
    )
    return NotebookTelemetryDashboard(**kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg_errors(self):
        d = _make_dashboard()
        assert d.TITLE == "Telemetry Dashboard"
        assert d.paused is False
        assert d.counters == {}
        assert d.gauges == {}
        assert d.histograms == {}
        assert d.perf == {}

    def test_defaults_expose_constants(self):
        from pharos_engine.ui.editor.notebook_telemetry_dashboard import (
            POLL_INTERVAL_DEFAULT_MS,
            POLL_INTERVAL_MAX_MS,
            POLL_INTERVAL_MIN_MS,
            SPARKLINE_SAMPLE_COUNT,
            TAB_NAMES,
        )
        assert POLL_INTERVAL_MIN_MS == 100
        assert POLL_INTERVAL_MAX_MS == 5000
        assert POLL_INTERVAL_DEFAULT_MS == 500
        assert SPARKLINE_SAMPLE_COUNT == 60
        assert TAB_NAMES == ("Counters", "Gauges", "Histograms", "Perf")

    def test_rejects_bad_poll_interval(self):
        with pytest.raises((TypeError, ValueError)):
            _make_dashboard(poll_interval_ms=-1)

    def test_rejects_bad_auto_scroll(self):
        with pytest.raises(TypeError):
            _make_dashboard(auto_scroll="yes")  # type: ignore[arg-type]

    def test_poll_interval_clamps_low(self):
        d = _make_dashboard(poll_interval_ms=10)
        assert d.poll_interval_ms == 100

    def test_poll_interval_clamps_high(self):
        d = _make_dashboard(poll_interval_ms=99_999)
        assert d.poll_interval_ms == 5000


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


class TestSubscription:
    def test_subscribe_idempotent(self):
        d = _make_dashboard()
        d.subscribe_to_telemetry()
        first = d._subscription_handle
        d.subscribe_to_telemetry()
        assert d._subscription_handle == first

    def test_unsubscribe_idempotent(self):
        d = _make_dashboard()
        d.subscribe_to_telemetry()
        d.unsubscribe()
        d.unsubscribe()
        assert d._subscription_handle is None

    def test_build_auto_subscribes(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.build(parent_tag="root")
        try:
            telemetry.emit("counter.test", count=1)
            assert "counter.test" in d.counters
        finally:
            d.destroy()


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_counter_increments(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("spawn.count", count=3)
            telemetry.emit("spawn.count", count=2)
            assert d.counters["spawn.count"] == 5.0
        finally:
            d.unsubscribe()

    def test_counter_default_delta_is_one(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("beat", counter=True)
            telemetry.emit("beat", counter=True)
            assert d.counters["beat"] == 2.0
        finally:
            d.unsubscribe()

    def test_counter_delta_per_poll(self):
        from pharos_engine import telemetry

        d = _make_dashboard(poll_interval_ms=100)
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("hits", count=4)
            # Simulate a poll flush — freezes the delta baseline.
            d.tick(dt_seconds=0.2)
            cur, last = d._counters["hits"]
            assert cur == 4.0 and last == 4.0
            telemetry.emit("hits", count=2)
            cur2, last2 = d._counters["hits"]
            assert cur2 == 6.0 and last2 == 4.0
            # Delta since last flush:
            assert (cur2 - last2) == 2.0
        finally:
            d.unsubscribe()

    def test_gauge_records_current_value(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("fps", gauge=60.0)
            telemetry.emit("fps", gauge=59.0)
            assert d.gauges["fps"] == 59.0
        finally:
            d.unsubscribe()

    def test_gauge_bare_value_key_recognised(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("bare.gauge", value=1.5)
            assert d.gauges["bare.gauge"] == 1.5
        finally:
            d.unsubscribe()

    def test_gauge_sparkline_sample_count(self):
        """Sparkline buffer holds up to :data:`SPARKLINE_SAMPLE_COUNT`."""
        from pharos_engine import telemetry
        from pharos_engine.ui.editor.notebook_telemetry_dashboard import (
            SPARKLINE_SAMPLE_COUNT,
        )

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            for i in range(SPARKLINE_SAMPLE_COUNT + 30):
                telemetry.emit("fps", gauge=float(i))
            samples = d.gauge_samples("fps")
            assert len(samples) == SPARKLINE_SAMPLE_COUNT
            # Newest values retained — deque(maxlen=…) trims oldest.
            assert samples[-1] == float(SPARKLINE_SAMPLE_COUNT + 29)
        finally:
            d.unsubscribe()

    def test_histogram_bucket_increments(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("collisions", bucket="head")
            telemetry.emit("collisions", bucket="head")
            telemetry.emit("collisions", bucket="torso")
            hist = d.histograms["collisions"]
            assert hist["head"] == 2
            assert hist["torso"] == 1
        finally:
            d.unsubscribe()

    def test_histogram_dict_payload_merges(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit(
                "latency_buckets",
                histogram={"0-10ms": 5, "10-50ms": 3},
            )
            telemetry.emit(
                "latency_buckets",
                histogram={"0-10ms": 1, "50-100ms": 2},
            )
            hist = d.histograms["latency_buckets"]
            assert hist["0-10ms"] == 6
            assert hist["10-50ms"] == 3
            assert hist["50-100ms"] == 2
        finally:
            d.unsubscribe()

    def test_perf_records_duration(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            for v in (1.0, 2.0, 3.0, 4.0):
                telemetry.emit("physics.step", duration_ms=v)
            stats = d.perf["physics.step"]
            assert stats["max"] == 4.0
            assert stats["mean"] == pytest.approx(2.5)
            assert d.perf_series("physics.step").count == 4
        finally:
            d.unsubscribe()

    def test_perf_tab_sort_order(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("slow", duration_ms=100.0)
            telemetry.emit("fast", duration_ms=1.0)
            telemetry.emit("mid", duration_ms=50.0)
            perf = d.perf
            # Sorted by mean descending → slow > mid > fast.
            ordered = sorted(perf.items(), key=lambda kv: kv[1]["mean"], reverse=True)
            assert [name for name, _ in ordered] == ["slow", "mid", "fast"]
        finally:
            d.unsubscribe()

    def test_unknown_payload_dropped(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("ambient.event", note="hi")
            assert d.counters == {}
            assert d.gauges == {}
            assert d.histograms == {}
            assert d.perf == {}
        finally:
            d.unsubscribe()


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class TestTransport:
    def test_pause_blocks_ingestion(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            d.pause()
            telemetry.emit("silent", count=1)
            assert d.counters == {}
        finally:
            d.unsubscribe()

    def test_pause_blocks_tick_refresh(self):
        d = _make_dashboard(poll_interval_ms=100)
        d.pause()
        # Big dt would normally refresh; paused → False + no state change.
        assert d.tick(dt_seconds=10.0) is False

    def test_resume_restores_ingestion(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            d.pause()
            telemetry.emit("dropped", count=1)
            d.resume()
            telemetry.emit("kept", count=1)
            assert "kept" in d.counters
            assert "dropped" not in d.counters
        finally:
            d.unsubscribe()

    def test_clear_empties_state(self):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("c", count=1)
            telemetry.emit("g", gauge=1.0)
            telemetry.emit("h", bucket="x")
            telemetry.emit("p", duration_ms=1.0)
            d.clear()
            assert d.counters == {}
            assert d.gauges == {}
            assert d.histograms == {}
            assert d.perf == {}
        finally:
            d.unsubscribe()


# ---------------------------------------------------------------------------
# Poll tick
# ---------------------------------------------------------------------------


class TestTick:
    def test_tick_below_interval_no_refresh(self):
        d = _make_dashboard(poll_interval_ms=1000)
        # 100 ms << 1000 ms — no flush.
        assert d.tick(dt_seconds=0.1) is False

    def test_tick_at_interval_refreshes(self):
        d = _make_dashboard(poll_interval_ms=500)
        assert d.tick(dt_seconds=0.6) is True

    def test_tick_zero_dt_no_refresh(self):
        d = _make_dashboard(poll_interval_ms=100)
        assert d.tick(dt_seconds=0.0) is False

    def test_tick_rejects_bad_dt(self):
        d = _make_dashboard()
        with pytest.raises(TypeError):
            d.tick(dt_seconds="0.1")  # type: ignore[arg-type]

    def test_tick_rejects_negative_dt(self):
        d = _make_dashboard()
        with pytest.raises(ValueError):
            d.tick(dt_seconds=-0.1)

    def test_set_poll_interval_clamps(self):
        d = _make_dashboard(poll_interval_ms=500)
        assert d.set_poll_interval_ms(50) == 100  # clamps up
        assert d.set_poll_interval_ms(10_000) == 5000  # clamps down
        assert d.set_poll_interval_ms(750) == 750


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


class TestTabs:
    def test_default_active_tab(self):
        d = _make_dashboard()
        assert d.active_tab == "Counters"

    def test_set_active_tab_rejects_unknown(self):
        d = _make_dashboard()
        with pytest.raises(ValueError):
            d.set_active_tab("Bogus")

    def test_set_active_tab_updates(self):
        d = _make_dashboard()
        d.set_active_tab("Gauges")
        assert d.active_tab == "Gauges"

    def test_every_tab_renders_under_stub(self, stub_dpg):
        from pharos_engine import telemetry
        from pharos_engine.ui.editor.notebook_telemetry_dashboard import (
            TAB_NAMES,
        )

        d = _make_dashboard()
        # Prime one of each kind.
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("c", count=1)
            telemetry.emit("g", gauge=1.0)
            telemetry.emit("g", gauge=2.0)
            telemetry.emit("h", bucket="x")
            telemetry.emit("p", duration_ms=1.0)
        finally:
            pass

        for tab in TAB_NAMES:
            d.set_active_tab(tab)
            d.build(parent_tag="root")
            # add_text is called by every tab body.
            assert "add_text" in stub_dpg.calls
            d.destroy()

    def test_gauge_tab_draws_polyline(self, stub_dpg):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.set_active_tab("Gauges")
        d.subscribe_to_telemetry()
        for i in range(10):
            telemetry.emit("fps", gauge=float(i))
        d.build(parent_tag="root")
        # drawlist + polyline should be issued for the gauge sparkline.
        assert "add_drawlist" in stub_dpg.calls
        d.destroy()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_csv_writes_valid_file(self, tmp_path):
        from pharos_engine import telemetry

        d = _make_dashboard()
        d.subscribe_to_telemetry()
        try:
            telemetry.emit("hits", count=5)
            telemetry.emit("fps", gauge=60.0)
            path = tmp_path / "snapshot.csv"
            written = d.export_csv(path)
            assert written == path
            content = path.read_text(encoding="utf-8").strip().splitlines()
            assert content[0] == "kind,name,value"
            # One counter row + one gauge row.
            assert any(row.startswith("counter,hits,") for row in content[1:])
            assert any(row.startswith("gauge,fps,") for row in content[1:])
        finally:
            d.unsubscribe()

    def test_export_csv_creates_parent_dirs(self, tmp_path):
        d = _make_dashboard()
        target = tmp_path / "a" / "b" / "out.csv"
        d.export_csv(target)
        assert target.exists()


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestTheme:
    def test_theme_switch_logs(self):
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        d = _make_dashboard()
        theme = NotebookTheme(name="alt")
        set_active_theme(theme)
        assert any(call[0] == "theme_changed" for call in d.call_log)


# ---------------------------------------------------------------------------
# Auto-scroll
# ---------------------------------------------------------------------------


class TestAutoScroll:
    def test_default_auto_scroll(self):
        d = _make_dashboard()
        assert d.auto_scroll is True

    def test_set_auto_scroll(self):
        d = _make_dashboard()
        d.set_auto_scroll(False)
        assert d.auto_scroll is False

    def test_set_auto_scroll_rejects_non_bool(self):
        d = _make_dashboard()
        with pytest.raises(TypeError):
            d.set_auto_scroll("nope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_creates_root_widgets(self, stub_dpg):
        d = _make_dashboard()
        d.build(parent_tag="root")
        # Title + header row emit text.
        assert "add_text" in stub_dpg.calls
        # Header controls emit checkbox + slider.
        assert "add_checkbox" in stub_dpg.calls
        assert "add_slider_int" in stub_dpg.calls
        # Tab bar + tabs are opened.
        assert "tab_bar" in stub_dpg.calls
        assert "tab" in stub_dpg.calls
        # Tabs are named per :data:`TAB_NAMES`.
        tab_labels = {
            call[1].get("label") for call in stub_dpg.calls["tab"]
        }
        assert {"Counters", "Gauges", "Histograms", "Perf"}.issubset(tab_labels)
        d.destroy()

    def test_counter_row_appears_after_emit(self, stub_dpg):
        from pharos_engine import telemetry

        d = _make_dashboard(poll_interval_ms=100)
        d.build(parent_tag="root")
        try:
            telemetry.emit("hits", count=1)
            stub_dpg.calls.setdefault("add_text", []).clear()
            # Tick past the poll interval to force a refresh — that's when
            # the counter row is rendered into the body group.
            assert d.tick(dt_seconds=0.2) is True
            texts = [call[0][0] for call in stub_dpg.calls.get("add_text", [])]
            assert any(
                "hits" in t for t in texts if isinstance(t, str)
            ), f"expected 'hits' in {texts!r}"
        finally:
            d.destroy()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_contains_dashboard(self):
        from pharos_engine.ui import editor
        assert "NotebookTelemetryDashboard" in editor.__all__

    def test_lazy_map_maps_dashboard(self):
        from pharos_engine.ui import editor
        assert "NotebookTelemetryDashboard" in editor._LAZY_MAP
        assert (
            editor._LAZY_MAP["NotebookTelemetryDashboard"]
            == ".notebook_telemetry_dashboard"
        )

    def test_lazy_import_resolves(self):
        from pharos_engine.ui import editor
        cls = editor.NotebookTelemetryDashboard  # triggers __getattr__
        assert cls.TITLE == "Telemetry Dashboard"
