"""E1-H: ComputeLibrary and RunRule verification tests.

Covers:
  - ComputeLibrary.list_registered() and the underlying _registry dict
  - RunRule.ON_SUBSCRIBED listener-count guard in ComputePass.should_run()
  - RunRule.ALWAYS unconditional dispatch

All tests are headless — no GPU context required.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_library():
    """Return ComputeLibrary with a clean _registry (avoids cross-test bleed)."""
    from slappyengine.compute.library import ComputeLibrary
    ComputeLibrary._registry = {}
    return ComputeLibrary


def _make_pass(run_rule, event_name: str = "Test.Event"):
    """Build a ComputePass without importing wgpu at module level."""
    from slappyengine.compute.pipeline import ComputePass
    return ComputePass(
        source="@compute @workgroup_size(64) fn main() {}",
        run_rule=run_rule,
        event_name=event_name,
    )


# ---------------------------------------------------------------------------
# TestComputeLibraryListRegistered
# ---------------------------------------------------------------------------

class TestComputeLibraryListRegistered:
    def setup_method(self):
        # Isolate registry state for every test
        from slappyengine.compute.library import ComputeLibrary
        ComputeLibrary._registry = {}

    def test_list_registered_returns_list(self):
        """list_registered() must return a plain list (not dict_keys, etc.)."""
        lib = _fresh_library()
        result = lib.list_registered()
        assert isinstance(result, list)

    def test_list_registered_empty_when_nothing_registered(self):
        lib = _fresh_library()
        assert lib.list_registered() == []

    def test_list_registered_includes_registered_name(self):
        """A shader registered via register() must appear in list_registered()."""
        lib = _fresh_library()
        lib.register("my_shader", "@compute @workgroup_size(1) fn main() {}")
        names = lib.list_registered()
        assert "my_shader" in names

    def test_list_registered_multiple_shaders(self):
        lib = _fresh_library()
        lib.register("shader_a", "// a")
        lib.register("shader_b", "// b")
        lib.register("shader_c", "// c")
        names = lib.list_registered()
        assert set(names) == {"shader_a", "shader_b", "shader_c"}

    def test_list_registered_returns_copy(self):
        """Mutating the returned list must not corrupt the registry."""
        lib = _fresh_library()
        lib.register("stable", "// src")
        names = lib.list_registered()
        names.append("injected")
        # Registry should be unaffected
        assert "injected" not in lib.list_registered()


# ---------------------------------------------------------------------------
# TestRunRuleOnSubscribed
# ---------------------------------------------------------------------------

class TestRunRuleOnSubscribed:
    def setup_method(self):
        # Clear all event-bus listeners between tests
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_zero_listeners_skips_dispatch(self):
        """ON_SUBSCRIBED with no listeners → should_run() returns False."""
        from slappyengine.compute.pipeline import RunRule
        # Patch global_bus.listener_count to return 0
        with patch("slappyengine.event_bus.global_bus") as mock_bus:
            mock_bus.listener_count.return_value = 0
            pass_ = _make_pass(RunRule.ON_SUBSCRIBED, "Test.Event")
            assert pass_.should_run() is False
            mock_bus.listener_count.assert_called_once_with("Test.Event")

    def test_one_listener_triggers_dispatch(self):
        """ON_SUBSCRIBED with one listener → should_run() returns True."""
        from slappyengine.compute.pipeline import RunRule
        with patch("slappyengine.event_bus.global_bus") as mock_bus:
            mock_bus.listener_count.return_value = 1
            pass_ = _make_pass(RunRule.ON_SUBSCRIBED, "Test.Event")
            assert pass_.should_run() is True

    def test_on_subscribed_empty_event_name_returns_false(self):
        """ON_SUBSCRIBED with no event_name must return False (nothing to check)."""
        from slappyengine.compute.pipeline import RunRule
        pass_ = _make_pass(RunRule.ON_SUBSCRIBED, event_name="")
        assert pass_.should_run() is False

    def test_always_always_dispatches(self):
        """ALWAYS run rule → should_run() returns True regardless of listeners."""
        from slappyengine.compute.pipeline import RunRule
        with patch("slappyengine.event_bus.global_bus") as mock_bus:
            mock_bus.listener_count.return_value = 0
            pass_ = _make_pass(RunRule.ALWAYS, "Test.Event")
            assert pass_.should_run() is True
            # ALWAYS must NOT consult the event bus
            mock_bus.listener_count.assert_not_called()

    def test_on_subscribed_live_bus_zero(self):
        """Integration: ON_SUBSCRIBED against real global_bus with no subscribers."""
        from slappyengine.compute.pipeline import RunRule
        pass_ = _make_pass(RunRule.ON_SUBSCRIBED, "Live.Test.Event")
        # No subscribe() call → listener_count == 0
        assert pass_.should_run() is False

    def test_on_subscribed_live_bus_one(self):
        """Integration: ON_SUBSCRIBED against real global_bus with one subscriber."""
        from slappyengine.compute.pipeline import RunRule
        from slappyengine.event_bus import subscribe, unsubscribe
        handle = subscribe("Live.Test.Event", lambda e: None)
        try:
            pass_ = _make_pass(RunRule.ON_SUBSCRIBED, "Live.Test.Event")
            assert pass_.should_run() is True
        finally:
            unsubscribe(handle)
