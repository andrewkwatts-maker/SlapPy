"""Engine tests for compute/pipeline.py — RunRule enum, ComputePass pure-Python
logic (should_run, trigger, chain, from_source). No GPU dispatch.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# RunRule enum
# ---------------------------------------------------------------------------

class TestRunRule:
    def test_three_values(self):
        from pharos_engine.compute.pipeline import RunRule
        assert RunRule.ALWAYS is not None
        assert RunRule.ON_SUBSCRIBED is not None
        assert RunRule.ON_DEMAND is not None

    def test_values_distinct(self):
        from pharos_engine.compute.pipeline import RunRule
        vals = {RunRule.ALWAYS, RunRule.ON_SUBSCRIBED, RunRule.ON_DEMAND}
        assert len(vals) == 3


# ---------------------------------------------------------------------------
# ComputePass — construction and metadata
# ---------------------------------------------------------------------------

class TestComputePassInit:
    def test_instantiates(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="@compute fn main() {}")
        assert cp is not None

    def test_source_stored(self):
        from pharos_engine.compute.pipeline import ComputePass
        src = "@compute fn main() {}"
        cp = ComputePass(source=src)
        assert cp.source == src

    def test_default_entry_point(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="")
        assert cp.entry_point == "main"

    def test_custom_entry_point(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="", entry_point="fluid_main")
        assert cp.entry_point == "fluid_main"

    def test_default_label_empty(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="")
        assert cp.label == ""

    def test_custom_label(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="", label="MyPass")
        assert cp.label == "MyPass"

    def test_default_run_rule_always(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="")
        assert cp.run_rule is RunRule.ALWAYS

    def test_custom_run_rule(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        assert cp.run_rule is RunRule.ON_DEMAND

    def test_default_event_name_empty(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="")
        assert cp.event_name == ""

    def test_custom_event_name(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="", event_name="Compute.Hull.Result")
        assert cp.event_name == "Compute.Hull.Result"

    def test_triggered_false_by_default(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass(source="")
        assert cp._triggered is False


# ---------------------------------------------------------------------------
# ComputePass — should_run logic
# ---------------------------------------------------------------------------

class TestComputePassShouldRun:
    def setup_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from pharos_engine.event_bus import global_bus
        global_bus.clear()

    def test_always_should_run(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ALWAYS)
        assert cp.should_run() is True

    def test_on_subscribed_false_without_listeners(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_SUBSCRIBED,
                         event_name="Orphan.Compute.Event")
        assert cp.should_run() is False

    def test_on_subscribed_true_with_listener(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        from pharos_engine.event_bus import subscribe, unsubscribe
        cp = ComputePass(source="", run_rule=RunRule.ON_SUBSCRIBED,
                         event_name="Hull.Ready")
        h = subscribe("Hull.Ready", lambda e: None)
        result = cp.should_run()
        unsubscribe(h)
        assert result is True

    def test_on_subscribed_false_when_no_event_name(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_SUBSCRIBED, event_name="")
        assert cp.should_run() is False

    def test_on_demand_false_before_trigger(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        assert cp.should_run() is False

    def test_on_demand_true_after_trigger(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        cp.trigger()
        assert cp.should_run() is True

    def test_on_demand_resets_after_run(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        cp.trigger()
        cp.should_run()         # consumes the trigger
        assert cp.should_run() is False

    def test_trigger_multiple_times_still_one_shot(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        cp.trigger()
        cp.trigger()   # calling again is idempotent
        cp.should_run()  # consume
        assert cp.should_run() is False


# ---------------------------------------------------------------------------
# ComputePass — trigger() and chain()
# ---------------------------------------------------------------------------

class TestComputePassTrigger:
    def test_trigger_sets_triggered_flag(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass(source="", run_rule=RunRule.ON_DEMAND)
        cp.trigger()
        assert cp._triggered is True

    def test_chain_returns_next_pass(self):
        from pharos_engine.compute.pipeline import ComputePass
        a = ComputePass(source="")
        b = ComputePass(source="")
        result = a.chain(b)
        assert result is b

    def test_chain_stores_chained_passes(self):
        from pharos_engine.compute.pipeline import ComputePass
        a = ComputePass(source="")
        b = ComputePass(source="")
        a.chain(b)
        assert b in a._chained_passes

    def test_chain_multiple(self):
        from pharos_engine.compute.pipeline import ComputePass
        a = ComputePass(source="")
        b = ComputePass(source="")
        c = ComputePass(source="")
        a.chain(b)
        a.chain(c)
        assert len(a._chained_passes) == 2


# ---------------------------------------------------------------------------
# ComputePass — from_source factory
# ---------------------------------------------------------------------------

class TestComputePassFromSource:
    def test_from_source_creates_pass(self):
        from pharos_engine.compute.pipeline import ComputePass, RunRule
        cp = ComputePass.from_source(
            source="@compute fn main() {}",
            label="test_pass",
            run_rule=RunRule.ON_DEMAND,
        )
        assert cp.source == "@compute fn main() {}"
        assert cp.label == "test_pass"
        assert cp.run_rule is RunRule.ON_DEMAND

    def test_from_source_default_entry_point(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass.from_source(source="// shader")
        assert cp.entry_point == "main"

    def test_from_source_custom_entry_point(self):
        from pharos_engine.compute.pipeline import ComputePass
        cp = ComputePass.from_source(source="// shader", entry_point="cs_main")
        assert cp.entry_point == "cs_main"
