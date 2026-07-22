"""Tests for :class:`NotebookToastManager`.

Covers:

* Construction + defaults.
* ``show`` returns a valid id + fires shown-subscribers.
* ``dismiss`` removes a toast + fires dismissed-subscribers.
* ``dismiss_all`` empties + fires per-toast.
* ``tick`` expires toasts after ``duration_ms + FADE_OUT_MS``.
* Animation progress (slide-in / hold / fade / expired phases).
* Max-visible cap.
* Stack ordering (newest first).
* Level → colour mapping.
* Level normalisation (int / str / alias / bool refused).
* Log subscriber routes ``WARNING+`` records to toasts.
* Custom sticker glyph passes through.
* ``build`` under stub DPG registers root widgets.
* Lazy registration in the editor ``__init__``.
"""
from __future__ import annotations

import logging
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub (mirrors test_notebook_message_log)
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


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window",
        "add_text", "add_button", "add_separator", "add_group",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value",
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


def _make_manager(**kwargs):
    from pharos_editor.ui.editor.notebook_toast_manager import (
        NotebookToastManager,
    )
    return NotebookToastManager(**kwargs)


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults(self):
        mgr = _make_manager()
        assert mgr.max_visible == 5
        assert mgr.default_duration_ms == 3000
        assert mgr.active_toasts() == []

    def test_custom_caps(self):
        mgr = _make_manager(max_visible=3, default_duration_ms=1500)
        assert mgr.max_visible == 3
        assert mgr.default_duration_ms == 1500

    def test_rejects_bad_max_visible(self):
        with pytest.raises((TypeError, ValueError)):
            _make_manager(max_visible=0)
        with pytest.raises((TypeError, ValueError)):
            _make_manager(max_visible=-1)

    def test_rejects_bad_duration(self):
        with pytest.raises((TypeError, ValueError)):
            _make_manager(default_duration_ms=0)


# ===========================================================================
# Level normalisation
# ===========================================================================


class TestLevelNormalisation:
    def test_toastlevel_passthrough(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            ToastLevel, normalise_toast_level,
        )
        assert normalise_toast_level(ToastLevel.WARN) is ToastLevel.WARN

    def test_string_names(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            ToastLevel, normalise_toast_level,
        )
        assert normalise_toast_level("info") is ToastLevel.INFO
        assert normalise_toast_level("SUCCESS") is ToastLevel.SUCCESS
        assert normalise_toast_level("Warn") is ToastLevel.WARN
        assert normalise_toast_level("error") is ToastLevel.ERROR

    def test_aliases(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            ToastLevel, normalise_toast_level,
        )
        assert normalise_toast_level("WARNING") is ToastLevel.WARN
        assert normalise_toast_level("FATAL") is ToastLevel.ERROR
        assert normalise_toast_level("OK") is ToastLevel.SUCCESS
        assert normalise_toast_level("done") is ToastLevel.SUCCESS

    def test_stdlib_int_levels(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            ToastLevel, normalise_toast_level,
        )
        assert normalise_toast_level(logging.ERROR) is ToastLevel.ERROR
        assert normalise_toast_level(logging.WARNING) is ToastLevel.WARN
        assert normalise_toast_level(logging.INFO) is ToastLevel.INFO

    def test_bool_refused(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            normalise_toast_level,
        )
        with pytest.raises(TypeError):
            normalise_toast_level(True)

    def test_unknown_falls_back_to_info(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            ToastLevel, normalise_toast_level,
        )
        assert normalise_toast_level("HYPE") is ToastLevel.INFO


# ===========================================================================
# Show
# ===========================================================================


class TestShow:
    def test_show_returns_valid_id(self):
        mgr = _make_manager()
        tid = mgr.show("hello")
        assert isinstance(tid, str)
        assert tid
        assert tid.startswith("toast-")

    def test_show_appears_in_active(self):
        mgr = _make_manager()
        tid = mgr.show("hello")
        toasts = mgr.active_toasts()
        assert len(toasts) == 1
        assert toasts[0].id == tid
        assert toasts[0].message == "hello"

    def test_show_default_level_is_info(self):
        from pharos_editor.ui.editor.notebook_toast_manager import ToastLevel
        mgr = _make_manager()
        mgr.show("hi")
        assert mgr.active_toasts()[0].level is ToastLevel.INFO

    def test_show_accepts_level_string(self):
        from pharos_editor.ui.editor.notebook_toast_manager import ToastLevel
        mgr = _make_manager()
        mgr.show("nice", level="SUCCESS")
        assert mgr.active_toasts()[0].level is ToastLevel.SUCCESS

    def test_show_accepts_level_enum(self):
        from pharos_editor.ui.editor.notebook_toast_manager import ToastLevel
        mgr = _make_manager()
        mgr.show("boom", level=ToastLevel.ERROR)
        assert mgr.active_toasts()[0].level is ToastLevel.ERROR

    def test_show_custom_duration(self):
        mgr = _make_manager()
        mgr.show("brief", duration_ms=100)
        assert mgr.active_toasts()[0].duration_ms == 100

    def test_show_default_duration_used(self):
        mgr = _make_manager(default_duration_ms=1234)
        mgr.show("msg")
        assert mgr.active_toasts()[0].duration_ms == 1234

    def test_show_sticker_pass_through(self):
        mgr = _make_manager()
        mgr.show("with-sticker", sticker="*")
        assert mgr.active_toasts()[0].sticker_glyph == "*"

    def test_show_no_sticker_by_default(self):
        mgr = _make_manager()
        mgr.show("no-sticker")
        assert mgr.active_toasts()[0].sticker_glyph is None

    def test_show_rejects_bad_duration(self):
        mgr = _make_manager()
        with pytest.raises((TypeError, ValueError)):
            mgr.show("x", duration_ms=0)

    def test_show_ids_are_unique(self):
        mgr = _make_manager()
        ids = {mgr.show(f"msg-{i}") for i in range(20)}
        assert len(ids) == 20

    def test_show_fires_subscribers(self):
        mgr = _make_manager()
        seen: list = []
        mgr.on_toast_shown(seen.append)
        mgr.show("hello")
        assert len(seen) == 1
        assert seen[0].message == "hello"


# ===========================================================================
# Dismiss
# ===========================================================================


class TestDismiss:
    def test_dismiss_removes_toast(self):
        mgr = _make_manager()
        tid = mgr.show("hello")
        assert mgr.dismiss(tid) is True
        assert mgr.active_toasts() == []

    def test_dismiss_unknown_id_returns_false(self):
        mgr = _make_manager()
        mgr.show("a")
        assert mgr.dismiss("toast-missing") is False
        # Live toast still there.
        assert len(mgr.active_toasts()) == 1

    def test_dismiss_fires_subscriber(self):
        mgr = _make_manager()
        seen: list = []
        mgr.on_toast_dismissed(seen.append)
        tid = mgr.show("hello")
        mgr.dismiss(tid)
        assert len(seen) == 1
        assert seen[0].id == tid

    def test_dismiss_rejects_empty_id(self):
        mgr = _make_manager()
        with pytest.raises((TypeError, ValueError)):
            mgr.dismiss("")


class TestDismissAll:
    def test_dismiss_all_empties(self):
        mgr = _make_manager()
        for i in range(3):
            mgr.show(f"m{i}")
        dropped = mgr.dismiss_all()
        assert dropped == 3
        assert mgr.active_toasts() == []

    def test_dismiss_all_on_empty_state_is_zero(self):
        mgr = _make_manager()
        assert mgr.dismiss_all() == 0

    def test_dismiss_all_fires_subscribers_per_toast(self):
        mgr = _make_manager()
        seen: list = []
        mgr.on_toast_dismissed(seen.append)
        mgr.show("a")
        mgr.show("b")
        mgr.dismiss_all()
        assert len(seen) == 2

    def test_empty_state_after_dismiss_all(self):
        mgr = _make_manager()
        for i in range(4):
            mgr.show(f"m{i}")
        mgr.dismiss_all()
        assert mgr.active_toasts() == []
        assert mgr.visible_toasts() == []
        assert mgr.offscreen_toasts() == []


# ===========================================================================
# Tick / expiry / animation
# ===========================================================================


class TestTick:
    def test_tick_before_duration_keeps_toast(self):
        mgr = _make_manager()
        mgr.show("hi", duration_ms=1000)
        prog = mgr.tick(500)
        assert len(mgr.active_toasts()) == 1
        assert len(prog) == 1
        assert prog[0]["phase"] in ("slide", "hold")

    def test_tick_after_full_lifetime_expires(self):
        mgr = _make_manager()
        mgr.show("hi", duration_ms=1000)
        # duration + FADE_OUT_MS (500) = 1500 ms total lifetime.
        mgr.tick(1600)
        assert mgr.active_toasts() == []

    def test_tick_slide_in_progress(self):
        mgr = _make_manager()
        mgr.show("hi", duration_ms=2000)
        # SLIDE_IN_MS = 300; at 150ms we're half-way.
        prog = mgr.tick(150)
        assert prog[0]["phase"] == "slide"
        assert 0.4 <= prog[0]["slide_in"] <= 0.6

    def test_tick_hold_phase(self):
        mgr = _make_manager()
        mgr.show("hi", duration_ms=1000)
        prog = mgr.tick(600)
        assert prog[0]["phase"] == "hold"
        assert prog[0]["alpha"] == pytest.approx(1.0)

    def test_tick_fade_phase(self):
        mgr = _make_manager()
        mgr.show("hi", duration_ms=1000)
        # Between duration (1000) and total (1500).
        prog = mgr.tick(1250)
        assert prog[0]["phase"] == "fade"
        # Alpha halfway through fade.
        assert 0.4 <= prog[0]["alpha"] <= 0.6

    def test_tick_returns_progress_ids(self):
        mgr = _make_manager()
        t1 = mgr.show("a", duration_ms=1000)
        t2 = mgr.show("b", duration_ms=1000)
        prog = mgr.tick(400)
        ids = {p["id"] for p in prog}
        assert ids == {t1, t2}

    def test_tick_fires_dismissed_on_expiry(self):
        mgr = _make_manager()
        seen: list = []
        mgr.on_toast_dismissed(seen.append)
        mgr.show("hi", duration_ms=100)
        mgr.tick(1000)
        assert len(seen) == 1

    def test_tick_rejects_non_number(self):
        mgr = _make_manager()
        with pytest.raises(TypeError):
            mgr.tick("nope")

    def test_tick_rejects_bool(self):
        mgr = _make_manager()
        with pytest.raises(TypeError):
            mgr.tick(True)


# ===========================================================================
# Max visible + stacking
# ===========================================================================


class TestMaxVisible:
    def test_max_visible_enforced(self):
        mgr = _make_manager(max_visible=3)
        for i in range(6):
            mgr.show(f"m{i}")
        assert len(mgr.active_toasts()) == 6
        assert len(mgr.visible_toasts()) == 3
        assert len(mgr.offscreen_toasts()) == 3

    def test_stack_ordering_newest_first(self):
        mgr = _make_manager()
        t1 = mgr.show("first")
        t2 = mgr.show("second")
        t3 = mgr.show("third")
        active = mgr.active_toasts()
        assert active[0].id == t3
        assert active[1].id == t2
        assert active[2].id == t1

    def test_offscreen_are_oldest(self):
        mgr = _make_manager(max_visible=2)
        oldest = mgr.show("oldest")
        mgr.show("middle")
        mgr.show("newest")
        offscreen_ids = [t.id for t in mgr.offscreen_toasts()]
        assert offscreen_ids == [oldest]


# ===========================================================================
# Level colour mapping
# ===========================================================================


class TestLevelColors:
    def test_all_levels_have_border_color(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            LEVEL_BORDER_COLORS, ToastLevel,
        )
        for level in ToastLevel:
            assert level in LEVEL_BORDER_COLORS
            rgba = LEVEL_BORDER_COLORS[level]
            assert len(rgba) == 4
            for c in rgba:
                assert 0 <= c <= 255

    def test_success_is_green(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            LEVEL_BORDER_COLORS, ToastLevel,
        )
        r, g, b, _a = LEVEL_BORDER_COLORS[ToastLevel.SUCCESS]
        # Green channel is dominant.
        assert g > r and g > b

    def test_warn_is_amber(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            LEVEL_BORDER_COLORS, ToastLevel,
        )
        r, g, b, _a = LEVEL_BORDER_COLORS[ToastLevel.WARN]
        # Red + green high, blue low.
        assert r > b and g > b

    def test_error_is_red(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            LEVEL_BORDER_COLORS, ToastLevel,
        )
        r, g, b, _a = LEVEL_BORDER_COLORS[ToastLevel.ERROR]
        assert r > g and r > b


# ===========================================================================
# Logging integration
# ===========================================================================


class TestLoggingIntegration:
    def test_warning_becomes_toast(self):
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_A")
        logger.setLevel(logging.DEBUG)
        mgr.subscribe_to_logging(logging.WARNING, logger)
        try:
            logger.warning("watch out")
            messages = [t.message for t in mgr.active_toasts()]
            assert "watch out" in messages
        finally:
            mgr.unsubscribe_from_logging()

    def test_info_below_threshold_no_toast(self):
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_B")
        logger.setLevel(logging.DEBUG)
        mgr.subscribe_to_logging(logging.WARNING, logger)
        try:
            logger.info("just info")
            assert mgr.active_toasts() == []
        finally:
            mgr.unsubscribe_from_logging()

    def test_error_becomes_error_level_toast(self):
        from pharos_editor.ui.editor.notebook_toast_manager import ToastLevel
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_C")
        logger.setLevel(logging.DEBUG)
        mgr.subscribe_to_logging(logging.WARNING, logger)
        try:
            logger.error("kaboom")
            levels = [t.level for t in mgr.active_toasts()]
            assert ToastLevel.ERROR in levels
        finally:
            mgr.unsubscribe_from_logging()

    def test_subscribe_replaces_previous(self):
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_D")
        mgr.subscribe_to_logging(logging.WARNING, logger)
        mgr.subscribe_to_logging(logging.ERROR, logger)
        try:
            handlers = [
                h for h in logger.handlers
                if type(h).__name__ == "_ToastLogHandler"
            ]
            assert len(handlers) == 1
            assert handlers[0].level == logging.ERROR
        finally:
            mgr.unsubscribe_from_logging()

    def test_unsubscribe_detaches(self):
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_E")
        mgr.subscribe_to_logging(logging.WARNING, logger)
        mgr.unsubscribe_from_logging()
        handlers = [
            h for h in logger.handlers
            if type(h).__name__ == "_ToastLogHandler"
        ]
        assert handlers == []

    def test_subscribe_rejects_bad_threshold(self):
        mgr = _make_manager()
        with pytest.raises(TypeError):
            mgr.subscribe_to_logging(threshold="warn")  # type: ignore[arg-type]


# ===========================================================================
# Subscribers
# ===========================================================================


class TestSubscribers:
    def test_shown_subscriber_can_be_removed(self):
        mgr = _make_manager()
        cb = lambda t: None  # noqa: E731
        mgr.on_toast_shown(cb)
        assert mgr.remove_shown_subscriber(cb) is True
        assert mgr.remove_shown_subscriber(cb) is False

    def test_dismissed_subscriber_can_be_removed(self):
        mgr = _make_manager()
        cb = lambda t: None  # noqa: E731
        mgr.on_toast_dismissed(cb)
        assert mgr.remove_dismissed_subscriber(cb) is True

    def test_subscriber_must_be_callable(self):
        mgr = _make_manager()
        with pytest.raises(TypeError):
            mgr.on_toast_shown("nope")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            mgr.on_toast_dismissed(123)  # type: ignore[arg-type]

    def test_subscriber_exception_swallowed(self):
        mgr = _make_manager()
        def bad(_t): raise RuntimeError("boom")
        mgr.on_toast_shown(bad)
        # Must not raise.
        tid = mgr.show("hi")
        assert tid


# ===========================================================================
# Build under stub DPG
# ===========================================================================


class TestBuild:
    def test_build_flips_flag(self):
        mgr = _make_manager()
        mgr.build(parent_tag="root")
        assert mgr._built is True

    def test_build_renders_placeholder_when_empty(self, stub_dpg):
        mgr = _make_manager()
        mgr.build(parent_tag="root")
        text_calls = stub_dpg.calls.get("add_text", [])
        found = any(
            call[0] and isinstance(call[0][0], str) and "no toasts" in call[0][0]
            for call in text_calls
        )
        assert found

    def test_build_renders_visible_toasts(self, stub_dpg):
        mgr = _make_manager()
        mgr.show("hello", level="SUCCESS")
        mgr.build(parent_tag="root")
        assert "child_window" in stub_dpg.calls

    def test_destroy_cleans_up(self):
        mgr = _make_manager()
        logger = logging.getLogger("test_notebook_toast_manager_destroy")
        mgr.subscribe_to_logging(logging.WARNING, logger)
        mgr.on_toast_shown(lambda t: None)
        mgr.show("hi")
        mgr.destroy()
        assert mgr._log_handler is None
        assert mgr.active_toasts() == []


# ===========================================================================
# Sticker options
# ===========================================================================


class TestStickerOptions:
    def test_sticker_options_exposed(self):
        from pharos_editor.ui.editor.notebook_toast_manager import (
            STICKER_OPTIONS,
        )
        assert isinstance(STICKER_OPTIONS, tuple)
        assert len(STICKER_OPTIONS) >= 10

    def test_custom_sticker_pass_through(self):
        mgr = _make_manager()
        mgr.show("branded", sticker="~")
        assert mgr.active_toasts()[0].sticker_glyph == "~"


# ===========================================================================
# Toast dataclass
# ===========================================================================


class TestToastDataclass:
    def test_toast_progress_expired_phase(self):
        from pharos_editor.ui.editor.notebook_toast_manager import Toast
        t = Toast(message="x", duration_ms=100)
        t.created_ms = 0.0
        # Well past total_lifetime_ms.
        p = t.progress(10_000)
        assert p["phase"] == "expired"
        assert p["alpha"] == 0.0

    def test_toast_progress_slide_phase(self):
        from pharos_editor.ui.editor.notebook_toast_manager import Toast
        t = Toast(message="x", duration_ms=1000)
        t.created_ms = 0.0
        p = t.progress(0.0)
        assert p["phase"] == "slide"
        assert p["slide_in"] == 0.0

    def test_toast_progress_slide_full_at_boundary(self):
        from pharos_editor.ui.editor.notebook_toast_manager import Toast
        t = Toast(message="x", duration_ms=1000)
        t.created_ms = 0.0
        p = t.progress(Toast.SLIDE_IN_MS)
        assert p["slide_in"] == 1.0

    def test_toast_total_lifetime(self):
        from pharos_editor.ui.editor.notebook_toast_manager import Toast
        t = Toast(message="x", duration_ms=1234)
        assert t.total_lifetime_ms() == 1234 + Toast.FADE_OUT_MS

    def test_toast_default_id(self):
        from pharos_editor.ui.editor.notebook_toast_manager import Toast
        t1 = Toast(message="a")
        t2 = Toast(message="a")
        assert t1.id != t2.id


# ===========================================================================
# Lazy registration in editor __init__
# ===========================================================================


class TestLazyRegistration:
    def test_lazy_import_works(self):
        import pharos_editor.ui.editor as editor_pkg
        assert "NotebookToastManager" in editor_pkg.__all__
        cls = editor_pkg.NotebookToastManager
        assert cls.__name__ == "NotebookToastManager"

    def test_all_alphabetically_ordered_neighbors(self):
        import pharos_editor.ui.editor as editor_pkg
        idx = editor_pkg.__all__.index("NotebookToastManager")
        prev_entry = editor_pkg.__all__[idx - 1]
        next_entry = editor_pkg.__all__[idx + 1]
        assert prev_entry <= "NotebookToastManager" <= next_entry
