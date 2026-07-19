"""Tests for :class:`MovablePanelWindow` and the EditorShell movable layout.

Exercises the wrapper's construction, accessor / mutator surface,
visibility flags, ``MIN_WIDTH`` / ``MIN_HEIGHT`` enforcement, theme
integration via ``theme.frames.for_panel``, and the default layout
the editor shell composes when wiring its notebook panels.

Every Dear PyGui call inside the wrapper is guarded so these tests
can run headless without spinning up a viewport.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — wrapper tests must run without a real DPG context.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str, kwargs: dict) -> None:
        self._recorder = recorder
        self._name = name
        self._kwargs = kwargs

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(
            (self._name, dict(self._kwargs)),
        )
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Recording stand-in for ``dearpygui.dearpygui``."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def window(self, *args, **kwargs):
        self._track("window", args, kwargs)
        return _StubCM(self.calls, "window", kwargs)

    def configure_item(self, tag, *args, **kwargs):
        self._track("configure_item", (tag,) + args, kwargs)

    def does_item_exist(self, tag, *args, **kwargs):
        return tag in self.items

    def bind_item_theme(self, tag, handle):
        self._track("bind_item_theme", (tag, handle), {})


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a fresh stub ``dearpygui.dearpygui`` for the test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in ("window", "configure_item", "does_item_exist",
                 "bind_item_theme"):
        setattr(mod, name, getattr(stub, name))
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    return stub


# ---------------------------------------------------------------------------
# Panel fixtures — drive the wrapper with synthetic panels so we don't
# depend on a fully-wired notebook stack.
# ---------------------------------------------------------------------------


class _SimplePanel:
    """Bare-bones panel — implements ``build`` and nothing else."""

    def __init__(self) -> None:
        self.builds: list[Any] = []

    def build(self, parent_tag: Any) -> None:
        self.builds.append(parent_tag)


class _PanelWithMin(_SimplePanel):
    """Panel that declares ``MIN_WIDTH`` / ``MIN_HEIGHT``."""

    MIN_WIDTH = 400
    MIN_HEIGHT = 320


class _PanelWithTitle:
    TITLE = "Reticulated Splines"

    def build(self, parent_tag: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Construction + introspection
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_construct_with_simple_panel(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        panel = _SimplePanel()
        win = MovablePanelWindow(panel, title="Hello", kind="sidebar")
        assert win.panel is panel
        assert win.title == "Hello"
        assert win.kind == "sidebar"
        assert win.is_built is False

    def test_title_falls_back_to_panel_TITLE(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_PanelWithTitle())
        assert win.title == "Reticulated Splines"

    def test_title_falls_back_to_class_name_when_unset(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        assert win.title == "_SimplePanel"

    def test_rejects_panel_without_build(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        class _NoBuild:
            pass

        with pytest.raises(TypeError):
            MovablePanelWindow(_NoBuild())

    def test_rejects_none_panel(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        with pytest.raises(TypeError):
            MovablePanelWindow(None)

    def test_rejects_empty_kind(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        with pytest.raises(ValueError):
            MovablePanelWindow(_SimplePanel(), kind="")

    def test_unique_window_tags(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        a = MovablePanelWindow(_SimplePanel())
        b = MovablePanelWindow(_SimplePanel())
        assert a.get_window_tag() != b.get_window_tag()

    def test_explicit_window_tag_honored(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), window_tag="my_panel")
        assert win.get_window_tag() == "my_panel"


# ---------------------------------------------------------------------------
# Position + size accessors
# ---------------------------------------------------------------------------


class TestPositionAndSize:
    def test_default_position(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), default_pos=(40, 80))
        assert win.get_position() == (40, 80)

    def test_set_position_roundtrip(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        win.set_position(120, 240)
        assert win.get_position() == (120, 240)

    def test_set_position_rejects_non_int(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        with pytest.raises(TypeError):
            win.set_position(1.5, 2)  # type: ignore[arg-type]

    def test_default_size(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), default_size=(640, 480))
        assert win.get_size() == (640, 480)

    def test_set_size_roundtrip(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        win.set_size(500, 360)
        assert win.get_size() == (500, 360)

    def test_set_size_respects_min(self):
        """``set_size`` clamps to ``min_size``."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(
            _SimplePanel(),
            default_size=(400, 400),
            min_size=(300, 250),
        )
        win.set_size(100, 100)
        # Clamped up to the minimum.
        assert win.get_size() == (300, 250)

    def test_panel_MIN_WIDTH_overrides_constructor_min(self):
        """A panel declaring ``MIN_WIDTH`` raises the effective minimum."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(
            _PanelWithMin(),
            default_size=(500, 500),
            min_size=(200, 200),
        )
        # _PanelWithMin: MIN_WIDTH=400, MIN_HEIGHT=320
        assert win.min_size == (400, 320)

    def test_default_size_clamped_to_min(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(
            _SimplePanel(),
            default_size=(100, 80),
            min_size=(200, 150),
        )
        assert win.get_size() == (200, 150)

    def test_set_size_rejects_zero(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        with pytest.raises(ValueError):
            win.set_size(0, 100)


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


class TestVisibility:
    def test_visible_by_default(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        assert win.is_visible() is True

    def test_hide_then_show(self):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        win.hide()
        assert win.is_visible() is False
        win.show()
        assert win.is_visible() is True


# ---------------------------------------------------------------------------
# Build — with the headless DPG stub.
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_marks_built(self, stub_dpg):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        panel = _SimplePanel()
        win = MovablePanelWindow(panel)
        win.build()
        assert win.is_built is True

    def test_build_invokes_panel_build(self, stub_dpg):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        panel = _SimplePanel()
        win = MovablePanelWindow(panel)
        win.build()
        assert len(panel.builds) == 1
        # The panel's build receives the wrapper's window tag.
        assert panel.builds[0] == win.get_window_tag()

    def test_build_window_kwargs(self, stub_dpg):
        """``dpg.window`` is called with the expected movable-window flags."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(
            _SimplePanel(),
            title="Movable",
            default_pos=(10, 20),
            default_size=(640, 480),
            min_size=(200, 150),
            closable=True,
            kind="sidebar",
        )
        win.build()
        contexts = stub_dpg.calls["window"]
        assert len(contexts) == 1
        _, kwargs = contexts[0]
        # Movable + resizable + titled — the default sidebar shape.
        assert kwargs["no_move"] is False
        assert kwargs["no_resize"] is False
        assert kwargs["no_title_bar"] is False
        # closable=True means no_close should be False.
        assert kwargs["no_close"] is False
        assert kwargs["label"] == "Movable"
        assert kwargs["width"] == 640
        assert kwargs["height"] == 480
        assert kwargs["pos"] == [10, 20]
        assert kwargs["min_size"] == [200, 150]

    def test_build_with_no_resize_flag(self, stub_dpg):
        """``no_resize=True`` propagates to ``dpg.window``."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(
            _SimplePanel(),
            kind="toolbar",
            no_resize=True,
        )
        win.build()
        _, kwargs = stub_dpg.calls["window"][0]
        assert kwargs["no_resize"] is True
        # Still movable.
        assert kwargs["no_move"] is False

    def test_closable_false_marks_no_close_true(self, stub_dpg):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), closable=False)
        win.build()
        _, kwargs = stub_dpg.calls["window"][0]
        assert kwargs["no_close"] is True

    def test_modal_propagates(self, stub_dpg):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), modal=True)
        win.build()
        _, kwargs = stub_dpg.calls["window"][0]
        assert kwargs["modal"] is True

    def test_set_position_propagates_after_build(self, stub_dpg):
        """``set_position`` after build issues ``configure_item``."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel())
        win.build()
        win.set_position(150, 250)
        cfg_calls = stub_dpg.calls.get("configure_item", [])
        # At least one configure_item with pos=...
        pos_call = next(
            (c for c in cfg_calls if "pos" in c[1]),
            None,
        )
        assert pos_call is not None
        assert pos_call[1]["pos"] == [150, 250]

    def test_build_headless_without_dpg(self, monkeypatch):
        """When DPG is absent, build still flips ``is_built``."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        # Force the import to fail by removing the module from sys.modules
        # and shadowing it with an unimportable placeholder.
        monkeypatch.setitem(sys.modules, "dearpygui", None)
        monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", None)

        panel = _SimplePanel()
        win = MovablePanelWindow(panel)
        win.build()
        assert win.is_built is True
        # The panel build is still invoked — the wrapper drives the
        # panel even in headless mode so tests of the wrapped panel
        # can run uniformly.
        assert len(panel.builds) == 1


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_theme_registry():
    """Drop the registry + active theme between tests."""
    from slappyengine.ui.theme import _reset_registry_for_tests

    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _make_test_theme(name: str = "frame_test"):
    """Build a minimal :class:`ThemeSpec` with a recognisable sidebar frame."""
    from slappyengine.ui.theme import (
        Color,
        FrameStyle,
        Gradient,
        PanelFrameSet,
        SemanticTokens,
        ThemeSpec,
    )

    accent = Color(255, 100, 50)
    base = Color(20, 20, 20)
    ink = Color(240, 240, 240)
    semantic = SemanticTokens(
        primary=accent,
        primary_gradient=Gradient(start=accent, end=Color(255, 200, 150)),
        secondary=accent,
        accent=accent,
        background=base,
        surface=base,
        surface_hover=base,
        border=accent,
        text_primary=ink,
        text_secondary=ink,
        text_disabled=ink,
        success=accent,
        warning=accent,
        error=accent,
        info=accent,
        focus_ring=accent,
        glass_bg=base,
        glass_blur_px=4.0,
    )
    # Sidebar gets a fat 5 px border + 12 px rounding so we can fingerprint
    # it back out of ``theme.frames.for_panel("sidebar")``.
    sidebar_frame = FrameStyle(
        border_size=5.0,
        rounding=12.0,
        padding_x=10,
        padding_y=8,
    )
    return ThemeSpec(
        name=name,
        semantic=semantic,
        frames=PanelFrameSet(sidebar=sidebar_frame),
    )


class TestThemeIntegration:
    def test_get_frame_style_pulls_from_theme(self, reset_theme_registry):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow
        from slappyengine.ui.theme import apply_theme, register_theme

        register_theme(_make_test_theme("sidebar_test"))
        apply_theme("sidebar_test")

        win = MovablePanelWindow(_SimplePanel(), kind="sidebar")
        frame = win.get_frame_style()
        assert frame is not None
        # Our test theme set sidebar border_size to 5.0; the default is 1.0.
        assert frame.border_size == 5.0
        assert frame.rounding == 12.0

    def test_unknown_kind_falls_back_to_default(self, reset_theme_registry):
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow
        from slappyengine.ui.theme import apply_theme, register_theme

        register_theme(_make_test_theme("default_test"))
        apply_theme("default_test")

        win = MovablePanelWindow(_SimplePanel(), kind="viewport")
        frame = win.get_frame_style()
        assert frame is not None
        # Default FrameStyle: border_size=1.0.
        assert frame.border_size == 1.0

    def test_get_frame_style_none_when_no_theme(self, reset_theme_registry):
        """Without an active theme, ``get_frame_style`` returns ``None``."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow

        win = MovablePanelWindow(_SimplePanel(), kind="sidebar")
        # No apply_theme call — registry empty.
        assert win.get_frame_style() is None


# ---------------------------------------------------------------------------
# Default layout — :meth:`EditorShell.compose_default_panel_layout`.
# ---------------------------------------------------------------------------


@pytest.fixture
def shell_with_panels(reset_theme_registry):
    """Build a notebook-panel-wired :class:`EditorShell`."""
    from slappyengine.ui.editor.shell import EditorShell

    class _StubEngine:
        def __init__(self):
            self.scene = None

    shell = EditorShell(_StubEngine())
    shell.setup_theme_subsystem()
    shell.setup_notebook_panels()
    # Content browser is built lazily by setup() — wire one manually
    # so the default layout has something to position there.
    from slappyengine.ui.editor.notebook_content_browser import (
        NotebookContentBrowser,
    )
    shell._content_browser = NotebookContentBrowser(
        on_open_scene=lambda *_: None,
        on_open_script=lambda *_: None,
        on_open_asset=lambda *_: None,
    )
    return shell


class TestDefaultLayout:
    def test_compose_produces_dict(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        assert isinstance(windows, dict)
        assert "toolbar" in windows
        assert "outliner" in windows
        assert "inspector" in windows
        assert "content_browser" in windows
        assert "status_bar" in windows

    def test_toolbar_position_pinned_to_top(self, shell_with_panels):
        # Post-BBB1: the toolbar sits over the CENTRE column only —
        # its x is ``LEFT_W`` and Scene / Inspector span the full
        # sidebar height either side of it.  Keep the y-anchor check
        # so a regression that dropped the toolbar into the workspace
        # would still catch here.
        from slappyengine.ui.editor.shell import LEFT_W

        windows = shell_with_panels.compose_default_panel_layout()
        tb = windows["toolbar"]
        x, y = tb.get_position()
        assert x == LEFT_W
        assert y < 100

    def test_outliner_position_is_left_dock(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        out = windows["outliner"]
        x, _ = out.get_position()
        assert x == 0  # Left edge.

    def test_inspector_position_is_right_dock(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        insp = windows["inspector"]
        x, _ = insp.get_position()
        # Right dock — well into the right half of the viewport.
        assert x > shell_with_panels._width // 2

    def test_status_bar_no_resize(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        sb = windows["status_bar"]
        assert sb.no_resize is True

    def test_toolbar_no_resize(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        tb = windows["toolbar"]
        assert tb.no_resize is True

    def test_sidebar_panels_are_resizable(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        out = windows["outliner"]
        insp = windows["inspector"]
        assert out.no_resize is False
        assert insp.no_resize is False

    def test_default_layout_persists_on_shell(self, shell_with_panels):
        windows = shell_with_panels.compose_default_panel_layout()
        assert shell_with_panels._panel_windows is windows
