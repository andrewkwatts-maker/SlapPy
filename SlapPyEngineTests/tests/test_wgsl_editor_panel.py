"""Tests for EEE3 — WGSL live shader editor panel + hot-reloader.

Covers:

* Panel builds under a headless DPG stub.
* Compile button dispatches the current source through the reloader —
  both success and failure paths land in the ``output`` buffer.
* Save writes to disk; Revert restores from :attr:`disk_source`; the
  Reload button re-reads the file.
* Syntax highlight keyword count matches expectations for a small
  fixture shader.
* Hot-reload picks up on-disk changes via mtime polling.
* ``shader.reloaded`` fires on the event bus.
* ``reload_shader()`` helper works from a REPL-style call.
* Bracket auto-complete + dropdown discovery both behave.
"""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# DPG stub — modelled on the REPL panel test.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: dict[str, Any] = {}
        self.values: dict[str, Any] = {}
        # Widget → callback mapping so tests can dispatch buttons.
        self.callbacks: dict[str, Any] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = kwargs
            if "callback" in kwargs:
                self.callbacks[tag] = kwargs["callback"]
            if "default_value" in kwargs:
                self.values[tag] = kwargs["default_value"]

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def add_child_window(self, *a, **kw):
        self._track("add_child_window", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)

    def get_value(self, tag):
        if tag in self.values:
            return self.values[tag]
        return self.items.get(tag, {}).get("default_value", "")

    def set_value(self, tag, value):
        self.values[tag] = value


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "add_child_window", "add_button",
        "add_combo", "add_input_text", "add_text", "add_separator",
        "does_item_exist", "delete_item", "get_value", "set_value",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
            return _StubCM()
        return _noop

    mod.__getattr__ = _fallback  # type: ignore[attr-defined]

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Fixture: a tiny WGSL fixture on disk + isolated shader root.
# ---------------------------------------------------------------------------


_SAMPLE_SHADER = """// sample.wgsl — 3 keywords + 2 annotations
struct Uniforms {
    color: vec4<f32>,
};

@vertex
fn vs_main() -> @builtin(position) vec4<f32> {
    var pos = vec4<f32>(0.0, 0.0, 0.0, 1.0);
    return pos;
}

@fragment
fn fs_main() -> @location(0) vec4<f32> {
    let c = vec4<f32>(1.0, 0.5, 0.0, 1.0);
    if (c.x > 0.5) {
        return c;
    } else {
        return c;
    }
}
"""


@pytest.fixture
def shader_root(tmp_path):
    root = tmp_path / "shaders"
    root.mkdir()
    (root / "sample.wgsl").write_text(_SAMPLE_SHADER, encoding="utf-8")
    sub = root / "deferred"
    sub.mkdir()
    (sub / "extra.wgsl").write_text(
        "fn helper() -> f32 { return 1.0; }\n", encoding="utf-8",
    )
    return str(root)


@pytest.fixture
def reset_reloader():
    from slappyengine.render import shader_hot_reload as hr

    hr.reset_default_reloader()
    yield
    hr.reset_default_reloader()


# ---------------------------------------------------------------------------
# Highlight + tokeniser
# ---------------------------------------------------------------------------


class TestHighlighter:
    def test_tokenize_keyword_and_annotation(self):
        from slappyengine.ui.editor.wgsl_editor_panel import tokenize_line

        tokens = tokenize_line("@vertex fn vs_main() -> f32 {")
        kinds = [k for k, _ in tokens]
        assert "annotation" in kinds
        assert "keyword" in kinds
        assert any(t == "@vertex" for _, t in tokens)
        assert any(t == "fn" for _, t in tokens)

    def test_count_keywords_matches_expected(self):
        from slappyengine.ui.editor.wgsl_editor_panel import count_keywords

        # In _SAMPLE_SHADER:
        #   annotations: @vertex, @fragment, @builtin, @location (×2) → recognised: @vertex, @fragment
        #   keywords: struct, fn, var, return, fn, let, if, return, else, return
        # The annotation set only counts @vertex/@fragment/@compute; the rest
        # tokenise as text. Keyword set: 10.
        count = count_keywords(_SAMPLE_SHADER)
        # 2 recognised annotations + 10 recognised keywords = 12.
        assert count == 12, count

    def test_highlight_source_line_count_matches(self):
        from slappyengine.ui.editor.wgsl_editor_panel import highlight_source

        highlighted = highlight_source(_SAMPLE_SHADER)
        expected_lines = _SAMPLE_SHADER.splitlines()
        assert len(highlighted) == len(expected_lines)


# ---------------------------------------------------------------------------
# Bracket auto-complete
# ---------------------------------------------------------------------------


class TestAutocomplete:
    def test_open_brace_closes(self):
        from slappyengine.ui.editor.wgsl_editor_panel import autocomplete_brackets

        assert autocomplete_brackets("struct Foo {") == "struct Foo {}"

    def test_open_paren_closes(self):
        from slappyengine.ui.editor.wgsl_editor_panel import autocomplete_brackets

        assert autocomplete_brackets("fn f(") == "fn f()"

    def test_no_change_for_regular_text(self):
        from slappyengine.ui.editor.wgsl_editor_panel import autocomplete_brackets

        assert autocomplete_brackets("let x = 1;") == "let x = 1;"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_discover_wgsl_shaders(self, shader_root):
        from slappyengine.ui.editor.wgsl_editor_panel import discover_wgsl_shaders

        paths = discover_wgsl_shaders(shader_root)
        assert len(paths) == 2
        assert all(p.endswith(".wgsl") for p in paths)

    def test_discover_missing_root(self, tmp_path):
        from slappyengine.ui.editor.wgsl_editor_panel import discover_wgsl_shaders

        assert discover_wgsl_shaders(str(tmp_path / "nope")) == []


# ---------------------------------------------------------------------------
# Panel build + button dispatch
# ---------------------------------------------------------------------------


class TestPanelBuild:
    def test_panel_builds(self, stub_dpg, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        panel.build("parent_stub")

        # The 4 required toolbar buttons all landed as add_button calls.
        button_labels = [
            kw.get("label")
            for _a, kw in stub_dpg.calls.get("add_button", [])
        ]
        for expected in ("Compile", "Save", "Revert", "Reload from disk"):
            assert expected in button_labels

    def test_button_count_constant(self):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        assert WGSLEditorPanel.BUTTON_COUNT == 4

    def test_panel_auto_loads_first_shader(self, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        assert panel.current_path is not None
        assert panel.current_source.strip() != ""


# ---------------------------------------------------------------------------
# Compile / save / revert / reload behaviours
# ---------------------------------------------------------------------------


class TestCompilePath:
    def test_compile_no_shader_reports_error(self, tmp_path, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        # Empty shader root → no auto-load.
        empty = tmp_path / "empty"
        empty.mkdir()
        panel = WGSLEditorPanel(shader_root=str(empty))
        result = panel.compile()
        assert result.ok is False

    def test_compile_wgpu_unavailable_still_reports(
        self, monkeypatch, shader_root, reset_reloader,
    ):
        from slappyengine.render import shader_hot_reload as hr
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        monkeypatch.setattr(hr, "_wgpu", None)
        monkeypatch.setattr(hr, "_wgpu_utils", None)
        panel = WGSLEditorPanel(shader_root=shader_root)
        result = panel.compile()
        assert result.ok is False
        assert "wgpu" in result.message.lower()
        # The output panel should have a matching entry.
        assert any(kind == "error" for kind, _ in panel.output)

    def test_compile_success_path_with_stub_wgpu(
        self, monkeypatch, shader_root, reset_reloader,
    ):
        """Compile succeeds when a stub wgpu device accepts everything."""
        from slappyengine.render import shader_hot_reload as hr
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        class _StubDevice:
            def create_shader_module(self, code=None, **_kw):
                self.last_code = code
                return object()

        class _StubUtils:
            @staticmethod
            def get_default_device():
                return _StubDevice()

        class _StubWgpu:
            pass

        monkeypatch.setattr(hr, "_wgpu", _StubWgpu)
        monkeypatch.setattr(hr, "_wgpu_utils", _StubUtils)
        panel = WGSLEditorPanel(shader_root=shader_root)
        result = panel.compile()
        assert result.ok is True
        assert result.validated is True

    def test_compile_failure_path_with_stub_wgpu(
        self, monkeypatch, shader_root, reset_reloader,
    ):
        """Compile flags an error when wgpu raises during shader module creation."""
        from slappyengine.render import shader_hot_reload as hr
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        class _StubDevice:
            def create_shader_module(self, code=None, **_kw):
                raise RuntimeError(
                    "Shader validation error: unexpected token at line 5, column 7"
                )

        class _StubUtils:
            @staticmethod
            def get_default_device():
                return _StubDevice()

        class _StubWgpu:
            pass

        monkeypatch.setattr(hr, "_wgpu", _StubWgpu)
        monkeypatch.setattr(hr, "_wgpu_utils", _StubUtils)
        panel = WGSLEditorPanel(shader_root=shader_root)
        result = panel.compile()
        assert result.ok is False
        assert result.validated is True
        assert result.errors
        # Structured error carries line + col.
        assert result.errors[0].line == 5
        assert result.errors[0].column == 7


class TestSaveRevertReload:
    def test_save_writes_to_disk(self, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        panel.current_source = "// edited\n"
        saved = panel.save()
        assert saved is not None
        with open(saved, "r", encoding="utf-8") as fh:
            assert fh.read() == "// edited\n"

    def test_revert_restores_disk_source(self, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        original = panel.disk_source
        panel.current_source = "// dirty edit\n"
        assert panel.current_source != original
        panel.revert()
        assert panel.current_source == original

    def test_reload_reads_from_disk(self, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        assert panel.current_path is not None
        # Simulate an external write.
        with open(panel.current_path, "w", encoding="utf-8") as fh:
            fh.write("// external edit\n")
        panel._on_reload_clicked()
        assert panel.current_source == "// external edit\n"


# ---------------------------------------------------------------------------
# Hot-reloader — mtime polling + event bus emission
# ---------------------------------------------------------------------------


class TestHotReloader:
    def test_register_and_recompile_fires_callback(
        self, shader_root, reset_reloader,
    ):
        from slappyengine.render.shader_hot_reload import ShaderHotReloader

        reloader = ShaderHotReloader()
        target = os.path.join(shader_root, "sample.wgsl")
        received: list[str] = []
        reloader.register(target, lambda src: received.append(src))
        reloader.recompile(target, "// new source\n")
        assert received == ["// new source\n"]

    def test_watch_detects_mtime_change(self, shader_root, reset_reloader):
        from slappyengine.render.shader_hot_reload import ShaderHotReloader

        reloader = ShaderHotReloader()
        target = os.path.join(shader_root, "sample.wgsl")
        received: list[str] = []
        reloader.register(target, lambda src: received.append(src))
        # Bump mtime and modify content — the poll should pick up.
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("// bumped\n")
        future = time.time() + 5.0
        os.utime(target, (future, future))
        reloaded = reloader.watch()
        assert target in [os.path.abspath(p) for p in reloaded]
        assert received == ["// bumped\n"]

    def test_shader_reloaded_event_fires(self, shader_root, reset_reloader):
        from slappyengine import event_bus
        from slappyengine.render.shader_hot_reload import ShaderHotReloader

        reloader = ShaderHotReloader()
        target = os.path.join(shader_root, "sample.wgsl")
        reloader.register(target, lambda _s: None)

        received: list[Any] = []

        def _listener(payload):
            received.append(payload)

        event_bus.subscribe("shader.reloaded", _listener)
        try:
            reloader.recompile(target, "// event trigger\n")
        finally:
            event_bus.unsubscribe("shader.reloaded", _listener)

        assert received
        # Payload carries the reload metadata.
        payload = received[0]
        # EventPayload supports dict-style access.
        assert payload["path"].endswith("sample.wgsl")
        assert "ok" in payload
        assert "latency_s" in payload

    def test_recompile_all_walks_every_path(self, shader_root, reset_reloader):
        from slappyengine.render.shader_hot_reload import ShaderHotReloader

        reloader = ShaderHotReloader()
        a = os.path.join(shader_root, "sample.wgsl")
        b = os.path.join(shader_root, "deferred", "extra.wgsl")
        seen: list[str] = []
        reloader.register(a, lambda _s: seen.append("a"))
        reloader.register(b, lambda _s: seen.append("b"))
        results = reloader.recompile_all()
        assert set(seen) == {"a", "b"}
        assert len(results) == 2

    def test_latency_recorded(self, shader_root, reset_reloader):
        from slappyengine.render.shader_hot_reload import ShaderHotReloader

        reloader = ShaderHotReloader()
        target = os.path.join(shader_root, "sample.wgsl")
        reloader.register(target, lambda _s: None)
        reloader.recompile(target, "// x\n")
        # Latency should be positive and modest (< 1 second on any dev box).
        assert 0.0 < reloader.last_latency_s < 1.0


# ---------------------------------------------------------------------------
# reload_shader() helper — REPL entrypoint
# ---------------------------------------------------------------------------


class TestReloadShaderHelper:
    def test_helper_exposed_in_editor_helpers(self):
        from slappyengine.editor import helpers

        assert hasattr(helpers, "reload_shader")
        assert "reload_shader" in helpers.__all__

    def test_helper_dispatches_through_reloader(
        self, shader_root, reset_reloader,
    ):
        from slappyengine.app import App
        from slappyengine.editor.helpers import reload_shader
        from slappyengine.render.shader_hot_reload import get_default_reloader

        App._clear_implicit()
        app = App()
        App._implicit = app
        try:
            target = os.path.join(shader_root, "sample.wgsl")
            result = reload_shader(target)
            assert result is not None
            # Whether the compile validated or not, the reloader logged it.
            assert target.endswith("sample.wgsl")
            # The path is now registered on the default reloader.
            reloader = get_default_reloader()
            assert any(
                p.endswith("sample.wgsl")
                for p in reloader.registered_paths()
            )
            # The trace on the app records the reload.
            assert any(
                entry[0] == "reload_shader" for entry in app.trace
            )
        finally:
            try:
                app.close()
            except Exception:
                pass
            App._clear_implicit()


# ---------------------------------------------------------------------------
# Panel tick — bridges the mtime poll
# ---------------------------------------------------------------------------


class TestPanelTick:
    def test_tick_fires_watch_at_1hz(self, shader_root, reset_reloader):
        from slappyengine.ui.editor.wgsl_editor_panel import WGSLEditorPanel

        panel = WGSLEditorPanel(shader_root=shader_root)
        target = panel.current_path
        assert target is not None
        # Register the panel's own on-reload callback with the reloader
        # via a real compile call so watch() has something to invoke.
        panel.compile()
        # Bump mtime on the current shader.
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("// tick-bumped\n")
        future = time.time() + 10.0
        os.utime(target, (future, future))

        # First 0.5s tick — under the 1Hz threshold, no reload yet.
        panel.tick(dt=0.5)
        assert panel.current_source != "// tick-bumped\n"
        # Second 0.6s tick pushes accumulator past 1s → watch runs.
        panel.tick(dt=0.6)
        # After tick, the on-reload callback populated current_source.
        assert panel.current_source == "// tick-bumped\n"
