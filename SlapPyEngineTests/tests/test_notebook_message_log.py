"""Tests for :class:`NotebookMessageLog`.

Covers:

* Construction + defaults.
* ``append`` semantics, level normalisation, ring buffer trimming.
* Level filter toggles, search filter, combined filters.
* Selection round-trip + selection compensation on ring-buffer overflow.
* ``clear`` empties buffer + drops selection.
* Pause / Resume gating of ``append``.
* Save-to-file round-trip (default + explicit path).
* Log-handler integration (real ``logging.info`` → row).
* Telemetry integration (real ``telemetry.emit`` → row).
* Auto-scroll flag flip.
* ``build`` under stub DPG registers root widgets.
* Lazy registration in the editor ``__init__``.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

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

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_group(self, *a, **kw):
        self._track("add_group", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)

    def set_y_scroll(self, tag, value, *a, **kw):
        self._track("set_y_scroll", (tag, value), kw)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_input_text", "add_separator",
        "add_group",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value", "set_y_scroll",
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
def _clear_telemetry():
    from slappyengine import telemetry as t
    t.clear_history()
    # Best-effort: drop any stray subscribers from prior tests.
    for handle in list(t._subscribers.keys()):
        t.unsubscribe(handle)
    yield
    for handle in list(t._subscribers.keys()):
        t.unsubscribe(handle)
    t.clear_history()


def _make_panel(**kwargs):
    from slappyengine.ui.editor.notebook_message_log import NotebookMessageLog
    return NotebookMessageLog(**kwargs)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults(self):
        panel = _make_panel()
        assert panel.TITLE == "Messages"
        assert panel.max_rows == 500
        assert panel.messages == []
        assert panel.paused is False
        assert panel.search == ""
        assert panel.selected_index is None

    def test_custom_max_rows(self):
        panel = _make_panel(max_rows=42)
        assert panel.max_rows == 42

    def test_rejects_bad_max_rows(self):
        with pytest.raises((TypeError, ValueError)):
            _make_panel(max_rows=0)
        with pytest.raises((TypeError, ValueError)):
            _make_panel(max_rows=-5)

    def test_all_levels_visible_by_default(self):
        from slappyengine.ui.editor.notebook_message_log import LEVELS
        panel = _make_panel()
        for lv in LEVELS:
            assert panel.is_level_visible(lv)


# ===========================================================================
# Level normalisation
# ===========================================================================


class TestLevelNormalisation:
    def test_string_levels_round_trip(self):
        from slappyengine.ui.editor.notebook_message_log import normalise_level
        assert normalise_level("DEBUG") == "DEBUG"
        assert normalise_level("info") == "INFO"
        assert normalise_level("Warn") == "WARN"
        assert normalise_level("ERROR") == "ERROR"

    def test_stdlib_int_levels(self):
        from slappyengine.ui.editor.notebook_message_log import normalise_level
        assert normalise_level(logging.DEBUG) == "DEBUG"
        assert normalise_level(logging.INFO) == "INFO"
        assert normalise_level(logging.WARNING) == "WARN"
        assert normalise_level(logging.ERROR) == "ERROR"
        assert normalise_level(logging.CRITICAL) == "ERROR"

    def test_string_aliases(self):
        from slappyengine.ui.editor.notebook_message_log import normalise_level
        assert normalise_level("WARNING") == "WARN"
        assert normalise_level("FATAL") == "ERROR"
        assert normalise_level("CRITICAL") == "ERROR"
        assert normalise_level("trace") == "DEBUG"

    def test_unknown_falls_back_to_info(self):
        from slappyengine.ui.editor.notebook_message_log import normalise_level
        assert normalise_level("HYPE") == "INFO"

    def test_bool_refused(self):
        from slappyengine.ui.editor.notebook_message_log import normalise_level
        with pytest.raises(TypeError):
            normalise_level(True)


# ===========================================================================
# Append
# ===========================================================================


class TestAppend:
    def test_append_adds_row(self):
        panel = _make_panel()
        msg = panel.append("INFO", "slappyengine.dynamics", "hello")
        assert msg is not None
        assert msg.level == "INFO"
        assert msg.source == "slappyengine.dynamics"
        assert msg.message == "hello"
        assert panel.messages == [msg]

    def test_append_normalises_level(self):
        panel = _make_panel()
        msg = panel.append("warning", "src", "text")
        assert msg is not None
        assert msg.level == "WARN"

    def test_append_stamps_timestamp(self):
        panel = _make_panel()
        msg = panel.append("INFO", "src", "t")
        assert msg is not None
        assert msg.timestamp > 0.0

    def test_append_respects_explicit_timestamp(self):
        panel = _make_panel()
        msg = panel.append("INFO", "src", "t", timestamp=1234.5)
        assert msg is not None
        assert msg.timestamp == 1234.5

    def test_append_rejects_non_string_source(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.append("INFO", 123, "text")

    def test_append_rejects_non_string_message(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.append("INFO", "src", 42)


# ===========================================================================
# Ring buffer
# ===========================================================================


class TestRingBuffer:
    def test_ring_buffer_wraps(self):
        panel = _make_panel(max_rows=3)
        for i in range(5):
            panel.append("INFO", "src", f"m{i}")
        assert len(panel.messages) == 3
        # Oldest dropped; newest kept at the tail.
        assert [m.message for m in panel.messages] == ["m2", "m3", "m4"]

    def test_set_max_rows_trims_immediately(self):
        panel = _make_panel(max_rows=10)
        for i in range(6):
            panel.append("INFO", "src", f"m{i}")
        panel.set_max_rows(2)
        assert len(panel.messages) == 2
        assert [m.message for m in panel.messages] == ["m4", "m5"]

    def test_ring_buffer_selection_compensates(self):
        panel = _make_panel(max_rows=3)
        panel.append("INFO", "src", "a")
        panel.append("INFO", "src", "b")
        panel.select(1)  # selects "b"
        assert panel.selected_index == 1
        # Push one more — no overflow yet (3 max).
        panel.append("INFO", "src", "c")
        assert panel.selected_index == 1
        # Now overflow — "a" dropped, indices shift down by 1.
        panel.append("INFO", "src", "d")
        assert panel.selected_index == 0

    def test_set_max_rows_rejects_bad_values(self):
        panel = _make_panel()
        with pytest.raises((TypeError, ValueError)):
            panel.set_max_rows(0)


# ===========================================================================
# Filters
# ===========================================================================


class TestFilters:
    def test_toggle_level_hides_matching(self):
        panel = _make_panel()
        panel.append("INFO", "s", "info-1")
        panel.append("WARN", "s", "warn-1")
        panel.toggle_level("WARN")
        assert panel.is_level_visible("WARN") is False
        visible = [m.message for m in panel.visible_messages]
        assert visible == ["info-1"]

    def test_toggle_level_returns_state(self):
        panel = _make_panel()
        new = panel.toggle_level("DEBUG")
        assert new is False
        new2 = panel.toggle_level("DEBUG")
        assert new2 is True

    def test_search_filters_by_substring(self):
        panel = _make_panel()
        panel.append("INFO", "slappyengine.dyn", "physics tick")
        panel.append("INFO", "slappyengine.render", "frame drawn")
        panel.set_search("physics")
        names = [m.message for m in panel.visible_messages]
        assert names == ["physics tick"]

    def test_search_is_case_insensitive(self):
        panel = _make_panel()
        panel.append("INFO", "s", "Physics Tick")
        panel.set_search("physics")
        assert len(panel.visible_messages) == 1

    def test_search_matches_source(self):
        panel = _make_panel()
        panel.append("INFO", "slappyengine.dynamics", "unrelated")
        panel.set_search("dynamics")
        assert len(panel.visible_messages) == 1

    def test_search_matches_level(self):
        panel = _make_panel()
        panel.append("ERROR", "s", "boom")
        panel.append("INFO", "s", "hi")
        panel.set_search("error")
        assert len(panel.visible_messages) == 1

    def test_combined_level_and_search_filters(self):
        panel = _make_panel()
        panel.append("INFO", "s", "physics tick")
        panel.append("WARN", "s", "physics glitch")
        panel.set_search("physics")
        panel.toggle_level("INFO")
        assert [m.level for m in panel.visible_messages] == ["WARN"]

    def test_set_level_visible_explicit(self):
        panel = _make_panel()
        panel.set_level_visible("ERROR", False)
        panel.append("ERROR", "s", "x")
        assert panel.visible_messages == []
        panel.set_level_visible("ERROR", True)
        assert len(panel.visible_messages) == 1


# ===========================================================================
# Clear
# ===========================================================================


class TestClear:
    def test_clear_empties_buffer(self):
        panel = _make_panel()
        panel.append("INFO", "s", "a")
        panel.append("INFO", "s", "b")
        panel.clear()
        assert panel.messages == []

    def test_clear_drops_selection(self):
        panel = _make_panel()
        panel.append("INFO", "s", "a")
        panel.select(0)
        panel.clear()
        assert panel.selected_index is None


# ===========================================================================
# Selection
# ===========================================================================


class TestSelection:
    def test_select_by_visible_index(self):
        panel = _make_panel()
        panel.append("INFO", "s", "a")
        panel.append("INFO", "s", "b")
        panel.select(1)
        assert panel.selected_index == 1

    def test_select_none_clears(self):
        panel = _make_panel()
        panel.append("INFO", "s", "a")
        panel.select(0)
        panel.select(None)
        assert panel.selected_index is None

    def test_select_out_of_range_raises(self):
        panel = _make_panel()
        panel.append("INFO", "s", "a")
        with pytest.raises(IndexError):
            panel.select(5)


# ===========================================================================
# Pause / Resume
# ===========================================================================


class TestPause:
    def test_pause_blocks_appends(self):
        panel = _make_panel()
        panel.pause()
        result = panel.append("INFO", "s", "dropped")
        assert result is None
        assert panel.messages == []

    def test_resume_re_enables(self):
        panel = _make_panel()
        panel.pause()
        panel.append("INFO", "s", "dropped")
        panel.resume()
        panel.append("INFO", "s", "kept")
        msgs = [m.message for m in panel.messages]
        assert msgs == ["kept"]

    def test_toggle_pause_returns_state(self):
        panel = _make_panel()
        assert panel.toggle_pause() is True
        assert panel.paused is True
        assert panel.toggle_pause() is False
        assert panel.paused is False


# ===========================================================================
# Save-to-file
# ===========================================================================


class TestSaveToFile:
    def test_save_writes_visible_messages(self, tmp_path: Path):
        panel = _make_panel()
        panel.append("INFO", "src", "hello")
        panel.append("ERROR", "src", "boom")
        target = tmp_path / "log.txt"
        result = panel.save_to_file(target)
        assert result.exists()
        content = target.read_text(encoding="utf-8")
        assert "hello" in content
        assert "boom" in content
        assert "INFO" in content
        assert "ERROR" in content

    def test_save_respects_level_filter(self, tmp_path: Path):
        panel = _make_panel()
        panel.append("DEBUG", "src", "debug-msg")
        panel.append("INFO", "src", "info-msg")
        panel.toggle_level("DEBUG")
        target = tmp_path / "log.txt"
        panel.save_to_file(target)
        content = target.read_text(encoding="utf-8")
        assert "debug-msg" not in content
        assert "info-msg" in content

    def test_save_default_path(self, tmp_path: Path, monkeypatch):
        panel = _make_panel()
        panel.append("INFO", "src", "hello")
        monkeypatch.chdir(tmp_path)
        result = panel.save_to_file()
        assert result.parent == tmp_path.resolve()
        assert result.name.startswith("session_log_")
        assert result.name.endswith(".txt")

    def test_save_empty_buffer(self, tmp_path: Path):
        panel = _make_panel()
        target = tmp_path / "log.txt"
        panel.save_to_file(target)
        assert target.exists()


# ===========================================================================
# Logging integration
# ===========================================================================


class TestLoggingIntegration:
    def test_logging_info_appears(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_A")
        logger.setLevel(logging.DEBUG)
        panel.subscribe_to_logging(logger)
        try:
            logger.info("hello from logger")
            messages = [m.message for m in panel.messages]
            assert "hello from logger" in messages
            # Level normalisation.
            info_rows = [m for m in panel.messages if m.level == "INFO"]
            assert info_rows
        finally:
            panel.unsubscribe_from_logging()

    def test_logging_captures_level(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_B")
        logger.setLevel(logging.DEBUG)
        panel.subscribe_to_logging(logger)
        try:
            logger.error("kaboom")
            levels = [m.level for m in panel.messages]
            assert "ERROR" in levels
        finally:
            panel.unsubscribe_from_logging()

    def test_logging_captures_source_module(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_C.sub")
        logger.setLevel(logging.DEBUG)
        panel.subscribe_to_logging(logger)
        try:
            logger.info("origin check")
            sources = [m.source for m in panel.messages]
            assert "test_notebook_message_log_C.sub" in sources
        finally:
            panel.unsubscribe_from_logging()

    def test_logging_subscribe_idempotent(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_D")
        panel.subscribe_to_logging(logger)
        panel.subscribe_to_logging(logger)
        try:
            handlers = [
                h for h in logger.handlers
                if type(h).__name__ == "_DiaryLogHandler"
            ]
            assert len(handlers) == 1
        finally:
            panel.unsubscribe_from_logging()

    def test_logging_unsubscribe_detaches_handler(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_E")
        panel.subscribe_to_logging(logger)
        panel.unsubscribe_from_logging()
        handlers = [
            h for h in logger.handlers
            if type(h).__name__ == "_DiaryLogHandler"
        ]
        assert handlers == []

    def test_paused_logging_drops_records(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_F")
        logger.setLevel(logging.DEBUG)
        panel.subscribe_to_logging(logger)
        panel.pause()
        try:
            logger.info("dropped while paused")
            assert panel.messages == []
        finally:
            panel.unsubscribe_from_logging()


# ===========================================================================
# Telemetry integration
# ===========================================================================


class TestTelemetryIntegration:
    def test_telemetry_event_appears(self):
        from slappyengine import telemetry
        panel = _make_panel()
        panel.subscribe_to_telemetry()
        try:
            telemetry.emit("physics.step", frame=42)
            names = [m.source for m in panel.messages]
            assert any("physics.step" in n for n in names)
        finally:
            panel.unsubscribe_from_telemetry()

    def test_telemetry_subscribe_idempotent(self):
        panel = _make_panel()
        h1 = panel.subscribe_to_telemetry()
        h2 = panel.subscribe_to_telemetry()
        try:
            assert h1 == h2
        finally:
            panel.unsubscribe_from_telemetry()

    def test_telemetry_unsubscribe_idempotent(self):
        panel = _make_panel()
        panel.subscribe_to_telemetry()
        panel.unsubscribe_from_telemetry()
        panel.unsubscribe_from_telemetry()  # no raise

    def test_telemetry_payload_preview(self):
        from slappyengine import telemetry
        panel = _make_panel()
        panel.subscribe_to_telemetry()
        try:
            telemetry.emit("render.frame", n=5, ms=16.7)
            rows = panel.messages
            assert rows
            assert "n=" in rows[-1].message


        finally:
            panel.unsubscribe_from_telemetry()

    def test_telemetry_pattern_filter(self):
        from slappyengine import telemetry
        panel = _make_panel()
        panel.subscribe_to_telemetry("physics.*")
        try:
            telemetry.emit("physics.step")
            telemetry.emit("render.frame")
            sources = [m.source for m in panel.messages]
            assert any("physics.step" in s for s in sources)
            assert not any("render.frame" in s for s in sources)
        finally:
            panel.unsubscribe_from_telemetry()


# ===========================================================================
# Auto-scroll
# ===========================================================================


class TestAutoScroll:
    def test_default_autoscroll_on(self):
        panel = _make_panel()
        assert panel.is_autoscroll_active() is True

    def test_user_scroll_up_disables_autoscroll(self):
        panel = _make_panel()
        panel.set_user_scrolled(True)
        assert panel.is_autoscroll_active() is False

    def test_user_scroll_bottom_re_enables(self):
        panel = _make_panel()
        panel.set_user_scrolled(True)
        panel.set_user_scrolled(False)
        assert panel.is_autoscroll_active() is True

    def test_set_user_scrolled_rejects_non_bool(self):
        panel = _make_panel()
        with pytest.raises(TypeError):
            panel.set_user_scrolled("yes")


# ===========================================================================
# Build under stub DPG
# ===========================================================================


class TestBuild:
    def test_build_creates_root_widgets(self, stub_dpg):
        panel = _make_panel()
        panel.append("INFO", "src", "hello")
        panel.build(parent_tag="root")
        assert "group" in stub_dpg.calls
        # A number of add_text or add_button calls should have happened.
        assert "add_text" in stub_dpg.calls or "add_button" in stub_dpg.calls

    def test_build_renders_no_messages_placeholder(self, stub_dpg):
        panel = _make_panel()
        panel.build(parent_tag="root")
        text_calls = stub_dpg.calls.get("add_text", [])
        found = any(
            call[0] and isinstance(call[0][0], str) and "no messages" in call[0][0]
            for call in text_calls
        )
        assert found

    def test_build_registers_filter_buttons(self, stub_dpg):
        panel = _make_panel()
        panel.build(parent_tag="root")
        button_labels = [
            call[1].get("label")
            for call in stub_dpg.calls.get("add_button", [])
        ]
        for lv in ("DEBUG", "INFO", "WARN", "ERROR"):
            assert lv in button_labels
        assert "Clear" in button_labels
        assert "Save" in button_labels
        # Pause/Resume flip depending on state.
        assert "Pause" in button_labels or "Resume" in button_labels

    def test_headless_build_flips_flag(self):
        # No DPG stub — real headless.
        panel = _make_panel()
        panel.build(parent_tag="root")
        assert panel._built is True

    def test_destroy_cleans_up(self):
        panel = _make_panel()
        logger = logging.getLogger("test_notebook_message_log_destroy")
        panel.subscribe_to_logging(logger)
        panel.subscribe_to_telemetry()
        panel.destroy()
        assert panel._log_handler is None
        assert panel._telemetry_handle is None


# ===========================================================================
# Lazy registration in editor __init__
# ===========================================================================


class TestLazyRegistration:
    def test_lazy_import_works(self):
        # Force-remove the cached module so we hit the __getattr__ path.
        import slappyengine.ui.editor as editor_pkg
        assert "NotebookMessageLog" in editor_pkg.__all__
        cls = editor_pkg.NotebookMessageLog
        assert cls.__name__ == "NotebookMessageLog"

    def test_all_alphabetically_ordered_neighbors(self):
        import slappyengine.ui.editor as editor_pkg
        idx = editor_pkg.__all__.index("NotebookMessageLog")
        # Neighbours are the alphabetically-adjacent entries.
        # Verify at least the immediate ordering.
        prev_entry = editor_pkg.__all__[idx - 1]
        next_entry = editor_pkg.__all__[idx + 1]
        assert prev_entry <= "NotebookMessageLog" <= next_entry
