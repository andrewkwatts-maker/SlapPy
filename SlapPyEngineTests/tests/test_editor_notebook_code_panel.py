"""Tests for :class:`NotebookCodePanel` — the diary-themed Code Mode reskin.

The panel mirrors the Nova3D ``CodeModePanel`` contract (prompt / code
two-pane editor with AI prompt-↔-code sync) but presents the layout
as a personal diary entry with a bookmark ribbon for open files.

Coverage:

* The panel constructs without DPG errors, both with and without
  ``dearpygui`` available.
* The two-pane layout produces prompt + code text inputs.
* The bookmark ribbon shows one tab per registered file.
* :meth:`set_file` switches the active file and loads its .py + .prompt.
* :meth:`regenerate` calls the AI prompt→code backend (mocked when
  Ollama is missing).
* When Ollama is missing the soft-fallback message surfaces.
* :meth:`reverse_sync` triggers the code→prompt explanation path.
* Theme switch routes through :meth:`refresh_theme`.

Every ``dpg.*`` call is stubbed with a no-op recorder so the panel
builds cleanly in CI without a real GUI context.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal dearpygui surface with call tracking + tag bookkeeping."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}
        self.configs: dict[str, dict] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context-manager primitives
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM(self.calls, "group")

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM(self.calls, "child_window")

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM(self.calls, "popup")

    # primitives
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str) and a:
            self.values[tag] = a[0]

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)
        tag = kw.get("tag")
        if isinstance(tag, str):
            self.values[tag] = kw.get("default_value", "")

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,) + a, kw)
        if isinstance(tag, str):
            self.configs.setdefault(tag, {}).update(kw)

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        if isinstance(tag, str):
            self.values[tag] = value

    def get_item_children(self, *a, **kw):
        return []


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name: str):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "group", "child_window", "popup",
        "add_text", "add_button", "add_input_text", "add_separator",
        "configure_item", "delete_item", "does_item_exist", "set_value",
        "get_item_children",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture
def force_ai_missing(monkeypatch):
    """Force the AI plumbing to soft-fail.

    Patches :func:`_try_make_llm_client` to return ``None`` so the
    panel reports Ollama as missing regardless of the host environment.
    """
    import slappyengine.ui.editor.notebook_code_panel as ncp
    monkeypatch.setattr(ncp, "_try_make_llm_client", lambda: None)
    yield


@pytest.fixture
def mock_ai(monkeypatch):
    """Install a mock LLM client + prompt_to_code / code_to_prompt pair.

    The mock client just records the calls; the helper functions return
    canned strings so we can assert the panel routes data correctly.
    """
    import slappyengine.ui.editor.notebook_code_panel as ncp

    calls: dict[str, list] = {"prompt_to_code": [], "code_to_prompt": []}

    class _MockLLM:
        def generate(self, *a, **kw) -> str:
            return ""

    async def _fake_prompt_to_code(prompt, code, llm):
        calls["prompt_to_code"].append((prompt, code))
        return "# regenerated\nprint('hello world')\n"

    async def _fake_code_to_prompt(code, llm):
        calls["code_to_prompt"].append((code,))
        return "This program prints a greeting to the console."

    def _prompt_path_for(path):
        return Path(str(path) + ".prompt")

    def _fake_helpers():
        return _fake_prompt_to_code, _fake_code_to_prompt, _prompt_path_for

    monkeypatch.setattr(ncp, "_try_make_llm_client", lambda: _MockLLM())
    monkeypatch.setattr(ncp, "_try_import_code_sync", _fake_helpers)
    yield calls


# ---------------------------------------------------------------------------
# Import guard.
# ---------------------------------------------------------------------------


try:
    from slappyengine.ui.editor.notebook_code_panel import NotebookCodePanel
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"NotebookCodePanel not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg(self, force_ai_missing):
        """The panel must construct cleanly without a DPG module."""
        panel = NotebookCodePanel()
        assert panel.TITLE == "Code"
        assert panel.get_prompt_text() == ""
        assert panel.get_code_text() == ""

    def test_constructs_with_watcher_arg(self, force_ai_missing):
        """The constructor accepts an optional CodeSyncWatcher handle."""
        sentinel = object()
        panel = NotebookCodePanel(code_sync_watcher=sentinel)
        assert panel._watcher is sentinel

    def test_status_initial(self, force_ai_missing):
        """Initial status reflects the AI probe outcome."""
        panel = NotebookCodePanel()
        # Without Ollama the status should hint at offline mode.
        assert "Ollama" in panel.status or "offline" in panel.status.lower()


# ---------------------------------------------------------------------------
# Build / layout
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_runs_without_dpg_errors(self, stub_dpg, force_ai_missing):
        """``build()`` materialises tags under the parent without raising."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        # The root container is registered.
        assert panel._panel_tag in stub_dpg.items

    def test_two_pane_layout_has_prompt_and_code_inputs(
        self, stub_dpg, force_ai_missing,
    ):
        """The two-pane layout produces both prompt + code input widgets."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        input_calls = stub_dpg.calls.get("add_input_text", [])
        # At least two multiline inputs — prompt + code.
        multilines = [
            (a, kw) for a, kw in input_calls if kw.get("multiline", False)
        ]
        assert len(multilines) >= 2, "expected prompt + code multiline inputs"
        # The prompt + code input tags are registered.
        assert panel._prompt_input_tag in stub_dpg.items
        assert panel._code_input_tag in stub_dpg.items

    def test_ribbon_built_with_no_files(self, stub_dpg, force_ai_missing):
        """The ribbon container is built even when no files are registered."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        assert panel._ribbon_tag in stub_dpg.items
        events = [e[0] for e in panel.call_log]
        assert "ribbon_built" in events

    def test_footer_has_four_action_buttons(self, stub_dpg, force_ai_missing):
        """Footer ribbon contains Regenerate / Explain / Pin / Saved."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        buttons = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label") or (a[0] if a else "") for a, kw in buttons]
        for expected in ("Regenerate", "Explain", "Pin", "Saved"):
            assert expected in labels, f"missing footer button: {expected}"


# ---------------------------------------------------------------------------
# Bookmark ribbon
# ---------------------------------------------------------------------------


class TestBookmarkRibbon:
    def test_register_file_adds_to_ribbon(self, stub_dpg, force_ai_missing, tmp_path):
        """register_file() appends a path to the files list."""
        panel = NotebookCodePanel()
        f = tmp_path / "player.py"
        f.write_text("class Player: pass", encoding="utf-8")
        panel.register_file(f)
        assert f in panel.files
        # The first registered file becomes active automatically.
        assert panel.active_file == f

    def test_register_file_is_idempotent(
        self, stub_dpg, force_ai_missing, tmp_path,
    ):
        """Registering the same path twice keeps the file list deduped."""
        panel = NotebookCodePanel()
        f = tmp_path / "enemy.py"
        f.write_text("", encoding="utf-8")
        panel.register_file(f)
        panel.register_file(f)
        assert panel.files.count(f) == 1

    def test_ribbon_renders_one_tab_per_file(
        self, stub_dpg, force_ai_missing, tmp_path,
    ):
        """After registering 3 files + build, the ribbon shows 3 tab buttons."""
        panel = NotebookCodePanel()
        for name in ("player.py", "enemy.py", "scene.py"):
            f = tmp_path / name
            f.write_text("", encoding="utf-8")
            panel.register_file(f)
        panel.build("parent_x")
        # Each file produced an add_button call with a tag inside the ribbon.
        buttons = stub_dpg.calls.get("add_button", [])
        # Ribbon button tags share the ribbon tag prefix.
        ribbon_btn_tags = [
            kw.get("tag")
            for _, kw in buttons
            if isinstance(kw.get("tag"), str)
            and kw["tag"].startswith(panel._ribbon_tag + "__")
        ]
        assert len(ribbon_btn_tags) == 3

    def test_set_file_switches_active(
        self, stub_dpg, force_ai_missing, tmp_path,
    ):
        """set_file() makes a different registered file active."""
        panel = NotebookCodePanel()
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("# a", encoding="utf-8")
        b.write_text("# b", encoding="utf-8")
        panel.register_file(a)
        panel.register_file(b)
        panel.set_file(b)
        assert panel.active_file == b

    def test_set_file_loads_code_from_disk(
        self, stub_dpg, force_ai_missing, tmp_path,
    ):
        """set_file() reads the .py contents into the code buffer."""
        panel = NotebookCodePanel()
        f = tmp_path / "script.py"
        f.write_text("class Player: pass\n", encoding="utf-8")
        panel.set_file(f)
        assert "class Player" in panel.get_code_text()

    def test_set_file_loads_prompt_sidecar(
        self, mock_ai, stub_dpg, tmp_path,
    ):
        """set_file() also reads the matching .prompt sidecar."""
        panel = NotebookCodePanel()
        f = tmp_path / "with_sidecar.py"
        f.write_text("x = 1\n", encoding="utf-8")
        sidecar = tmp_path / "with_sidecar.py.prompt"
        sidecar.write_text("Initialise x to 1.", encoding="utf-8")
        panel.set_file(f)
        assert "Initialise x" in panel.get_prompt_text()


# ---------------------------------------------------------------------------
# AI integration / soft fallback
# ---------------------------------------------------------------------------


class TestAIIntegration:
    def test_regenerate_calls_ai_backend(self, mock_ai, stub_dpg, tmp_path):
        """regenerate() routes through prompt_to_code with the buffers."""
        panel = NotebookCodePanel()
        f = tmp_path / "task.py"
        f.write_text("pass\n", encoding="utf-8")
        panel.set_file(f)
        panel._prompt_text = "Make the player jump higher with a star."
        panel.build("parent_x")
        panel.regenerate()
        assert len(mock_ai["prompt_to_code"]) == 1
        prompt, code = mock_ai["prompt_to_code"][0]
        assert "jump higher" in prompt
        # Generated code is captured in the buffer.
        assert "regenerated" in panel.get_code_text()

    def test_reverse_sync_calls_code_to_prompt(self, mock_ai, stub_dpg, tmp_path):
        """reverse_sync() routes through code_to_prompt with the code buffer."""
        panel = NotebookCodePanel()
        f = tmp_path / "doc.py"
        f.write_text("def f(): return 1\n", encoding="utf-8")
        panel.set_file(f)
        panel.build("parent_x")
        panel.reverse_sync()
        assert len(mock_ai["code_to_prompt"]) == 1
        # Explanation is captured into the prompt buffer.
        assert "greeting" in panel.get_prompt_text()

    def test_soft_fallback_when_ollama_missing(self, stub_dpg, force_ai_missing):
        """Regenerate is a no-op + status update when Ollama isn't installed."""
        panel = NotebookCodePanel()
        # Probe must have reported Ollama as missing.
        assert panel.ollama_missing is True
        assert panel.ai_available is False
        panel.build("parent_x")
        panel.regenerate()
        # The soft hint surfaced in the status line.
        assert "Ollama" in panel.status

    def test_soft_fallback_hint_visible_in_prompt_pane(
        self, stub_dpg, force_ai_missing,
    ):
        """The 'Install Ollama' soft hint is rendered in the prompt pane."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        texts: list[str] = []
        for args, kwargs in stub_dpg.calls.get("add_text", []):
            if args:
                texts.append(str(args[0]))
        joined = " ".join(texts)
        assert "Ollama" in joined

    def test_regenerate_writes_back_to_disk(self, mock_ai, stub_dpg, tmp_path):
        """When a file is bound, regenerate() persists the new code."""
        panel = NotebookCodePanel()
        f = tmp_path / "persisted.py"
        f.write_text("# starter\n", encoding="utf-8")
        panel.set_file(f)
        panel._prompt_text = "Make this say hello."
        panel.regenerate()
        # The file on disk now reflects the regenerated code.
        assert "regenerated" in f.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pin toggle + read-only code pane
# ---------------------------------------------------------------------------


class TestPinToggle:
    def test_code_pane_starts_read_only(self, stub_dpg, force_ai_missing):
        """The code pane is read-only by default — AI-generated content."""
        panel = NotebookCodePanel()
        assert panel.code_pinned is False
        panel.build("parent_x")
        # The add_input_text call for the code pane carries readonly=True.
        code_input_calls = [
            (a, kw) for a, kw in stub_dpg.calls.get("add_input_text", [])
            if kw.get("tag") == panel._code_input_tag
        ]
        assert code_input_calls, "code input was never built"
        _, kwargs = code_input_calls[0]
        assert kwargs.get("readonly") is True

    def test_toggle_pin_flips_state(self, stub_dpg, force_ai_missing):
        """toggle_pin() flips the code-editable flag."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        assert panel.code_pinned is False
        panel.toggle_pin()
        assert panel.code_pinned is True
        panel.toggle_pin()
        assert panel.code_pinned is False


# ---------------------------------------------------------------------------
# Theme switch
# ---------------------------------------------------------------------------


class TestThemeSwitch:
    def test_refresh_theme_updates_status(self, stub_dpg, force_ai_missing):
        """refresh_theme() re-emits the status so listeners observe the flip."""
        panel = NotebookCodePanel()
        panel.build("parent_x")
        panel.refresh_theme()
        events = [e[0] for e in panel.call_log]
        assert "refresh_theme" in events
