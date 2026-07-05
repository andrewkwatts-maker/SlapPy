"""
Tests for :mod:`slappyengine.telemetry.sink`.

Covers:

* ``incr``, ``gauge``, ``histogram`` payload shape (matches DD4 sniff).
* ``perf_start`` + ``.stop()`` emits ``duration_ms``.
* ``perf_timed`` context manager.
* ``LayerSink.sublayer`` prefixes the ``source``.
* :func:`null_sink` — no-op.
* :meth:`TelemetrySink.batch` — collects + flushes on exit.
* :meth:`TelemetrySink.instrument_module` — wraps public functions.
* Payload keys align with :mod:`notebook_telemetry_dashboard` sniff.
"""
from __future__ import annotations

import time
from types import ModuleType, SimpleNamespace
from typing import List

import pytest

from slappyengine import telemetry
from slappyengine.telemetry import sink as sink_mod
from slappyengine.telemetry.sink import (
    SKIP_INSTRUMENT_MARKER,
    LayerSink,
    TelemetrySink,
    null_sink,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    """Reset module state between tests so order does not matter."""
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()
    yield
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()


@pytest.fixture()
def events() -> List[telemetry.TelemetryEvent]:
    """Subscribe a collecting callback and return its list."""
    received: List[telemetry.TelemetryEvent] = []
    telemetry.subscribe("*", received.append)
    return received


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_source_property_reflects_ctor_argument():
    s = TelemetrySink("editor")
    assert s.source == "editor"


def test_empty_source_raises_value_error():
    with pytest.raises(ValueError):
        TelemetrySink("")


def test_non_str_source_raises_type_error():
    with pytest.raises(TypeError):
        TelemetrySink(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# incr / gauge / histogram payload shapes
# ---------------------------------------------------------------------------


def test_incr_emits_count_and_delta(events):
    TelemetrySink("panel").incr("clicks", delta=3)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["count"] == 3.0
    assert payload["delta"] == 3.0
    assert payload["source"] == "panel"
    assert events[0].name == "clicks"


def test_incr_defaults_delta_to_one(events):
    TelemetrySink("panel").incr("bumps")
    assert events[0].payload["count"] == 1.0
    assert events[0].payload["delta"] == 1.0


def test_incr_rejects_non_numeric_delta():
    with pytest.raises(TypeError):
        TelemetrySink("panel").incr("bad", delta="lots")  # type: ignore[arg-type]


def test_gauge_emits_gauge_and_value(events):
    TelemetrySink("panel").gauge("cpu", 42.5)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["gauge"] == 42.5
    assert payload["value"] == 42.5
    assert payload["source"] == "panel"


def test_gauge_rejects_bool_value():
    with pytest.raises(TypeError):
        TelemetrySink("panel").gauge("bad", True)  # type: ignore[arg-type]


def test_histogram_with_explicit_bucket(events):
    TelemetrySink("panel").histogram("latency", 12.0, bucket_key="fast")
    payload = events[0].payload
    assert payload["bucket"] == "fast"
    assert payload["histogram"] == {"fast": 1}
    assert payload["value"] == 12.0


def test_histogram_auto_bucketing(events):
    TelemetrySink("panel").histogram("latency", 15.0)
    payload = events[0].payload
    # 15 is >= 10 and < 100 -> label "<100"
    assert payload["bucket"] == "<100"
    assert "histogram" in payload


def test_histogram_auto_bucket_negative(events):
    TelemetrySink("panel").histogram("stat", -1.0)
    assert events[0].payload["bucket"] == "<0"


def test_histogram_rejects_non_str_bucket_key():
    with pytest.raises(TypeError):
        TelemetrySink("panel").histogram("x", 1.0, bucket_key=7)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tags merging
# ---------------------------------------------------------------------------


def test_incr_merges_tags(events):
    TelemetrySink("panel").incr("clicks", tags={"button": "ok"})
    assert events[0].payload["button"] == "ok"
    assert events[0].payload["count"] == 1.0


def test_gauge_merges_tags(events):
    TelemetrySink("panel").gauge("mem", 512.0, tags={"region": "gpu"})
    assert events[0].payload["region"] == "gpu"


# ---------------------------------------------------------------------------
# perf_start + perf_timed
# ---------------------------------------------------------------------------


def test_perf_start_stop_emits_duration_ms(events):
    sink = TelemetrySink("panel")
    handle = sink.perf_start("rebuild")
    time.sleep(0.002)
    elapsed = handle.stop()
    assert elapsed > 0.0
    assert len(events) == 1
    payload = events[0].payload
    assert "duration_ms" in payload
    assert payload["duration_ms"] > 0.0
    assert events[0].name == "rebuild"


def test_perf_stop_is_idempotent(events):
    sink = TelemetrySink("panel")
    handle = sink.perf_start("rebuild")
    handle.stop()
    handle.stop()
    # Only one event should have been emitted.
    assert len(events) == 1


def test_perf_stop_merges_tags(events):
    sink = TelemetrySink("panel")
    handle = sink.perf_start("rebuild")
    handle.stop(tags={"pass": "geom"})
    assert events[0].payload["pass"] == "geom"
    assert "duration_ms" in events[0].payload


def test_perf_timed_context_manager_emits(events):
    sink = TelemetrySink("panel")
    with sink.perf_timed("outliner.rebuild") as handle:
        assert isinstance(handle, sink_mod._PerfHandle)
        time.sleep(0.001)
    assert len(events) == 1
    assert "duration_ms" in events[0].payload
    assert events[0].name == "outliner.rebuild"


def test_perf_timed_emits_even_when_body_raises(events):
    sink = TelemetrySink("panel")
    with pytest.raises(RuntimeError):
        with sink.perf_timed("bad.step"):
            raise RuntimeError("boom")
    assert len(events) == 1
    assert "duration_ms" in events[0].payload


# ---------------------------------------------------------------------------
# Sublayer / LayerSink
# ---------------------------------------------------------------------------


def test_sublayer_composes_source(events):
    parent = TelemetrySink("editor")
    child = parent.sublayer("outliner")
    assert isinstance(child, LayerSink)
    assert child.source == "editor.outliner"
    child.incr("nodes_shown")
    assert events[0].payload["source"] == "editor.outliner"


def test_sublayer_nesting(events):
    a = TelemetrySink("a")
    b = a.sublayer("b")
    c = b.sublayer("c")
    assert c.source == "a.b.c"
    c.gauge("x", 1.0)
    assert events[0].payload["source"] == "a.b.c"


def test_sublayer_rejects_empty_name():
    with pytest.raises(ValueError):
        TelemetrySink("editor").sublayer("")


# ---------------------------------------------------------------------------
# null_sink
# ---------------------------------------------------------------------------


def test_null_sink_is_no_op(events):
    n = null_sink()
    n.incr("a")
    n.gauge("b", 1.0)
    n.histogram("c", 1.0)
    with n.perf_timed("d"):
        pass
    assert events == []


def test_null_sink_sublayer_is_also_no_op(events):
    n = null_sink("root")
    child = n.sublayer("child")
    child.incr("nothing")
    assert events == []


def test_null_sink_source_default():
    n = null_sink()
    assert n.source == "null"


# ---------------------------------------------------------------------------
# Batch API
# ---------------------------------------------------------------------------


def test_batch_defers_emits_until_exit(events):
    sink = TelemetrySink("panel")
    with sink.batch() as b:
        b.incr("a")
        b.incr("b")
        b.gauge("c", 1.0)
        # Nothing should have hit the bus yet.
        assert events == []
    # All three should have been flushed.
    assert len(events) == 3
    assert [e.name for e in events] == ["a", "b", "c"]


def test_batch_nested_flushes_once(events):
    sink = TelemetrySink("panel")
    with sink.batch():
        sink.incr("outer_before")
        with sink.batch():
            sink.incr("inner")
        sink.incr("outer_after")
        assert events == []
    assert len(events) == 3
    assert [e.name for e in events] == ["outer_before", "inner", "outer_after"]


def test_batch_flushes_on_exception(events):
    sink = TelemetrySink("panel")
    with pytest.raises(RuntimeError):
        with sink.batch():
            sink.incr("before")
            raise RuntimeError("boom")
    # Emits captured before the exception should still be flushed.
    assert len(events) == 1
    assert events[0].name == "before"


# ---------------------------------------------------------------------------
# instrument_module
# ---------------------------------------------------------------------------


def _make_fake_module() -> ModuleType:
    mod = ModuleType("fake_mod_under_test")

    def public_a(x):
        return x + 1

    public_a.__module__ = "fake_mod_under_test"

    def public_b(x):
        return x * 2

    public_b.__module__ = "fake_mod_under_test"

    def _private_c(x):
        return -x

    _private_c.__module__ = "fake_mod_under_test"

    def opted_out(x):
        return x
    opted_out.__module__ = "fake_mod_under_test"
    setattr(opted_out, SKIP_INSTRUMENT_MARKER, True)

    # Imported helper (different module) — should be ignored.
    def imported_helper(x):
        return x
    imported_helper.__module__ = "some_other_module"

    mod.public_a = public_a
    mod.public_b = public_b
    mod._private_c = _private_c
    mod.opted_out = opted_out
    mod.imported_helper = imported_helper
    return mod


def test_instrument_module_wraps_public_functions(events):
    mod = _make_fake_module()
    sink = TelemetrySink("panel")
    wrapped_count = sink.instrument_module(mod)
    # public_a + public_b should be wrapped.  opted_out and imported_helper
    # should be skipped, so should the private one.
    assert wrapped_count == 2
    assert mod.public_a(3) == 4
    assert mod.public_b(3) == 6
    # Each wrapped call emits one duration_ms event.
    assert len(events) == 2
    for e in events:
        assert "duration_ms" in e.payload


def test_instrument_module_skips_opted_out(events):
    mod = _make_fake_module()
    sink = TelemetrySink("panel")
    sink.instrument_module(mod)
    # Calling opted_out should NOT emit.
    mod.opted_out(1)
    assert events == []


def test_instrument_module_preserves_return_value(events):
    mod = _make_fake_module()
    sink = TelemetrySink("panel")
    sink.instrument_module(mod)
    assert mod.public_a(10) == 11


def test_instrument_module_uses_custom_prefix(events):
    mod = _make_fake_module()
    sink = TelemetrySink("panel")
    sink.instrument_module(mod, prefix="editor.tools")
    mod.public_a(1)
    assert events[0].name == "editor.tools.public_a"


def test_instrument_module_rejects_non_module():
    sink = TelemetrySink("panel")
    with pytest.raises(TypeError):
        sink.instrument_module(SimpleNamespace())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DD4 dashboard sniff contract — hard alignment check.
# ---------------------------------------------------------------------------


def test_payload_keys_match_dashboard_sniff():
    """Assert every emitted payload carries a key DD4 sniffs for."""
    from slappyengine.ui.editor.notebook_telemetry_dashboard import (
        _classify_event,
    )
    sink = TelemetrySink("panel")

    # incr -> counter classification
    seen: List[telemetry.TelemetryEvent] = []
    handle = telemetry.subscribe("*", seen.append)
    sink.incr("a")
    sink.gauge("b", 1.0)
    sink.histogram("c", 1.0)
    with sink.perf_timed("d"):
        pass
    telemetry.unsubscribe(handle)

    kinds = [_classify_event(e) for e in seen]
    assert kinds == ["counter", "gauge", "histogram", "perf"]

    # Direct payload-key spot check.
    assert "count" in seen[0].payload
    assert "gauge" in seen[1].payload
    assert "histogram" in seen[2].payload
    assert "duration_ms" in seen[3].payload


def test_source_attaches_to_telemetry_event_field(events):
    """``source`` in payload should also populate ``TelemetryEvent.source``."""
    TelemetrySink("editor.outliner").incr("nodes")
    assert events[0].source == "editor.outliner"


def test_auto_bucket_label_small_values():
    assert sink_mod._auto_bucket_label(0.1) == "<1"
    assert sink_mod._auto_bucket_label(5.0) == "<10"
    assert sink_mod._auto_bucket_label(50.0) == "<100"
    assert sink_mod._auto_bucket_label(500.0) == "<1000"


def test_layer_sink_batch_composes_with_parent(events):
    """A batch opened on the parent buffers emits from a child layer too."""
    parent = TelemetrySink("editor")
    child = parent.sublayer("outliner")
    with parent.batch():
        child.incr("nodes")
        assert events == []
    assert len(events) == 1
    assert events[0].payload["source"] == "editor.outliner"


def test_perf_handle_duration_ms_attribute():
    """``_PerfHandle.duration_ms`` should be updated after stop()."""
    sink = null_sink()  # avoid emitting during the test
    handle = sink.perf_start("x")
    assert handle.duration_ms == 0.0
    time.sleep(0.001)
    handle.stop()
    assert handle.duration_ms > 0.0
