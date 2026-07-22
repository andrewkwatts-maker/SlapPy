"""CodeModePanel — split Prompt / Code editor panel with AI synchronisation.

The AI reconciles the two panes in the direction of whichever was last edited:

  - Prompt edited last  → AI rewrites code to implement the description
  - Code edited last    → AI generates a new description from the code

For .py asset scripts a background :class:`~Pharos Engine.ai.code_sync.CodeSyncWatcher`
does this automatically whenever a local Ollama instance is available.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pharos_engine.engine import Engine


class CodeModePanel:
    """Split editor panel: left = plain-English prompt, right = Python code.

    Panel protocol — implements ``build(parent_tag)`` so it can be passed to
    :meth:`~Pharos Engine.ui.editor.shell.EditorShell.register_panel`.
    """

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._prompt_text: str = ""
        self._code_text: str = ""
        self._prompt_mtime: float = 0.0
        self._code_mtime: float = 0.0
        self._status: str = "Ready"
        self._ai_busy: bool = False
        self._script_path: Path | None = None
        self._llm = None
        self._watcher = None
        self._auto_sync_id = None
        self._pending_setup: bool = False
        self._setup_running: bool = False
        self._init_llm()

    # ── LLM initialisation ────────────────────────────────────────────────────

    def _init_llm(self) -> None:
        """Check saved AI settings then do a quick Ollama pre-flight.

        Decision tree
        -------------
        1. Load ~/.Pharos Engine/ai_settings.json.
        2. If no settings file → show the opt-in dialog on first DPG frame.
        3. If settings say disabled (model=None) → skip AI, mark disabled.
        4. If settings say enabled → check server/model; if ready go live,
           else show pull-progress modal.
        """
        try:
            from pharos_engine.ai.ollama_manager import load_ai_settings, OllamaManager
            settings = load_ai_settings()

            if not settings:
                # First run — defer opt-in dialog to the DPG thread
                self._pending_setup = True
                self._status = "Click 'Code Mode' tab to set up AI support"
                return

            model = settings.get("model")
            if not settings.get("enabled", False) or model is None:
                self._llm = None
                self._status = "AI sync disabled (None selected)"
                return

            # Settings exist and a model is chosen — check if it's ready
            mgr = OllamaManager()
            if mgr.is_server_running() and mgr.is_model_installed(model):
                from pharos_engine.ai import LLMClient
                self._llm = LLMClient()
                self._status = f"AI ready  ({model})"
            else:
                self._pending_setup = True
                self._status = f"Will download {model} on first use"
        except Exception as exc:
            self._llm = None
            self._status = f"AI unavailable: {exc}"

    def _trigger_setup(self) -> None:
        """Show the appropriate setup UI on the DPG render thread.

        Called from :meth:`update` the first time ``_pending_setup`` is True.
        Runs inline (not in a thread) because the modals drive the DPG render
        loop themselves.
        """
        if self._setup_running:
            return
        self._setup_running = True
        self._pending_setup = False

        from pharos_engine.ai.ollama_manager import load_ai_settings, OllamaManager

        settings = load_ai_settings()

        # ── Step 1: opt-in dialog (first run only) ────────────────────────
        if not settings:
            from pharos_editor.ui.editor.ollama_setup_modal import AiOptInDialog
            model = AiOptInDialog().show()
            if model is None:
                # User picked None or skipped — AI disabled
                self._llm = None
                self._set_status("AI sync disabled")
                self._setup_running = False
                return
        else:
            model = settings.get("model")
            if not settings.get("enabled", False) or model is None:
                self._llm = None
                self._set_status("AI sync disabled")
                self._setup_running = False
                return

        # ── Step 2: pull progress modal if needed ─────────────────────────
        mgr = OllamaManager()
        needs_pull = (not mgr.is_server_running()
                      or not mgr.is_model_installed(model))

        if needs_pull:
            from pharos_editor.ui.editor.ollama_setup_modal import OllamaSetupModal
            ready = OllamaSetupModal().show(model)
        else:
            ready = True

        # ── Step 3: create LLM client ────────────────────────────────────
        if ready:
            try:
                from pharos_engine.ai import LLMClient
                self._llm = LLMClient()
                self._set_status(f"AI ready  ({model})")
            except Exception as exc:
                self._llm = None
                self._set_status(f"AI unavailable: {exc}")
        else:
            self._llm = None
            try:
                import dearpygui.dearpygui as dpg
                if self._auto_sync_id is not None:
                    dpg.set_value(self._auto_sync_id, False)
            except Exception:
                pass
            self._set_status("AI sync disabled — setup cancelled or failed")

        self._setup_running = False

    # ── DPG layout ────────────────────────────────────────────────────────────

    def build(self, parent_tag) -> None:
        """Build the panel UI inside *parent_tag*.

        Called by :class:`~Pharos Engine.ui.editor.shell.EditorShell` during
        ``setup()``.
        """
        import dearpygui.dearpygui as dpg

        with dpg.group(parent=parent_tag):
            # ── Toolbar ───────────────────────────────────────────────────
            with dpg.group(horizontal=True):
                dpg.add_text("Code Mode")
                dpg.add_spacer(width=12)
                dpg.add_button(
                    label="Prompt -> Code",
                    callback=self._sync_prompt_to_code,
                    tag="cm_btn_p2c",
                )
                dpg.add_button(
                    label="Code -> Prompt",
                    callback=self._sync_code_to_prompt,
                    tag="cm_btn_c2p",
                )
                dpg.add_spacer(width=8)
                dpg.add_button(label="Open File...", callback=self._open_file_dialog)
                dpg.add_spacer(width=8)
                self._auto_sync_id = dpg.add_checkbox(
                    label="Auto-sync",
                    default_value=True,
                    callback=self._toggle_auto_sync,
                    tag="cm_auto_sync",
                )

            # Status bar
            dpg.add_text(self._status, tag="cm_status", color=(180, 180, 100))
            dpg.add_separator()

            # ── Split panes ───────────────────────────────────────────────
            # Use a fixed approximate width; DPG does not expose parent width
            # easily at build time.  Each pane takes roughly half of 1100 px.
            pane_w = 530
            pane_h = 460

            with dpg.group(horizontal=True):
                # Left: Prompt
                with dpg.child_window(
                    width=pane_w, height=pane_h, border=True, tag="cm_prompt_pane"
                ):
                    dpg.add_text("Prompt  (plain English)", color=(120, 200, 120))
                    dpg.add_text("", tag="cm_prompt_mtime", color=(100, 100, 100))
                    dpg.add_input_text(
                        tag="cm_prompt_input",
                        multiline=True,
                        width=pane_w - 16,
                        height=pane_h - 64,
                        callback=self._on_prompt_edited,
                        default_value=self._prompt_text,
                    )

                dpg.add_spacer(width=4)

                # Right: Code
                with dpg.child_window(
                    width=pane_w, height=pane_h, border=True, tag="cm_code_pane"
                ):
                    dpg.add_text("Code  (Python)", color=(120, 160, 255))
                    dpg.add_text("", tag="cm_code_mtime", color=(100, 100, 100))
                    dpg.add_input_text(
                        tag="cm_code_input",
                        multiline=True,
                        width=pane_w - 16,
                        height=pane_h - 64,
                        callback=self._on_code_edited,
                        default_value=self._code_text,
                        tab_input=True,
                    )

            # ── Diff summary line ─────────────────────────────────────────
            dpg.add_separator()
            dpg.add_text("", tag="cm_diff_summary", wrap=pane_w * 2 + 4)

    # ── Input callbacks ───────────────────────────────────────────────────────

    def _on_prompt_edited(self, sender, data) -> None:
        self._prompt_text = data
        self._prompt_mtime = time.monotonic()
        self._refresh_mtimes()

    def _on_code_edited(self, sender, data) -> None:
        self._code_text = data
        self._code_mtime = time.monotonic()
        self._refresh_mtimes()

    def _refresh_mtimes(self) -> None:
        import dearpygui.dearpygui as dpg
        try:
            p_newer = "  <- last edited" if self._prompt_mtime > self._code_mtime else ""
            c_newer = "  <- last edited" if self._code_mtime > self._prompt_mtime else ""
            dpg.set_value("cm_prompt_mtime", f"Last edited: {_fmt_age(self._prompt_mtime)}{p_newer}")
            dpg.set_value("cm_code_mtime",   f"Last edited: {_fmt_age(self._code_mtime)}{c_newer}")
        except Exception:
            pass

    # ── Status helper ─────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status = msg
        try:
            import dearpygui.dearpygui as dpg
            dpg.set_value("cm_status", msg)
        except Exception:
            pass

    # ── Manual sync buttons ───────────────────────────────────────────────────

    def _sync_prompt_to_code(self, *_) -> None:
        if self._ai_busy or not self._llm:
            return
        import threading
        threading.Thread(target=self._run_p2c, daemon=True).start()

    def _run_p2c(self) -> None:
        import asyncio
        import dearpygui.dearpygui as dpg

        self._ai_busy = True
        self._set_status("AI: rewriting code from prompt...")
        try:
            from pharos_engine.ai.code_sync import prompt_to_code
            loop = asyncio.new_event_loop()
            new_code = loop.run_until_complete(
                prompt_to_code(self._prompt_text, self._code_text, self._llm)
            )
            loop.close()
            self._code_text = new_code
            self._code_mtime = time.monotonic()
            dpg.set_value("cm_code_input", new_code)
            if self._script_path:
                self._script_path.write_text(new_code, encoding="utf-8")
            self._set_status("AI: code updated from prompt")
            dpg.set_value("cm_diff_summary", f"Code rewritten from prompt at {_now_str()}")
        except Exception as exc:
            self._set_status(f"AI error: {exc}")
        finally:
            self._ai_busy = False

    def _sync_code_to_prompt(self, *_) -> None:
        if self._ai_busy or not self._llm:
            return
        import threading
        threading.Thread(target=self._run_c2p, daemon=True).start()

    def _run_c2p(self) -> None:
        import asyncio
        import dearpygui.dearpygui as dpg

        self._ai_busy = True
        self._set_status("AI: generating description from code...")
        try:
            from pharos_engine.ai.code_sync import code_to_prompt
            loop = asyncio.new_event_loop()
            new_prompt = loop.run_until_complete(
                code_to_prompt(self._code_text, self._llm)
            )
            loop.close()
            self._prompt_text = new_prompt
            self._prompt_mtime = time.monotonic()
            dpg.set_value("cm_prompt_input", new_prompt)
            if self._script_path:
                from pharos_engine.ai.code_sync import prompt_path_for
                prompt_path_for(self._script_path).write_text(new_prompt, encoding="utf-8")
            self._set_status("AI: prompt updated from code")
            dpg.set_value("cm_diff_summary", f"Prompt generated from code at {_now_str()}")
        except Exception as exc:
            self._set_status(f"AI error: {exc}")
        finally:
            self._ai_busy = False

    # ── File picker ───────────────────────────────────────────────────────────

    def _open_file_dialog(self, *_) -> None:
        import dearpygui.dearpygui as dpg
        # Guard against opening a second dialog while one is already open
        if dpg.does_item_exist("cm_file_dialog"):
            return
        dpg.add_file_dialog(
            label="Select script",
            default_path=str(Path.home()),
            file_count=1,
            callback=self._on_file_selected,
            cancel_callback=lambda s, d: None,
            tag="cm_file_dialog",
            width=640,
            height=420,
        )
        dpg.add_file_extension(".py", color=(0, 255, 0, 255), parent="cm_file_dialog")

    def _on_file_selected(self, sender, selection) -> None:
        if not selection or "file_path_name" not in selection:
            return
        path = Path(selection["file_path_name"])
        self.load_script(path)

    # ── Auto-sync toggle ──────────────────────────────────────────────────────

    def _toggle_auto_sync(self, sender, value) -> None:
        if self._watcher:
            self._watcher._enabled = value

    # ── Script loading ────────────────────────────────────────────────────────

    def load_script(self, script_path: Path) -> None:
        """Load *script_path* and its .prompt sidecar into the panel."""
        import dearpygui.dearpygui as dpg
        from pharos_engine.ai.code_sync import prompt_path_for, CodeSyncWatcher

        self._script_path = script_path
        code = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
        pp = prompt_path_for(script_path)
        prompt = pp.read_text(encoding="utf-8") if pp.exists() else ""

        self._code_text = code
        self._prompt_text = prompt
        self._code_mtime = script_path.stat().st_mtime if script_path.exists() else 0.0
        self._prompt_mtime = pp.stat().st_mtime if pp.exists() else 0.0

        try:
            dpg.set_value("cm_code_input", code)
            dpg.set_value("cm_prompt_input", prompt)
        except Exception:
            pass

        # (Re)start background watcher for this file
        if self._watcher:
            self._watcher.stop()
        if self._llm:
            self._watcher = CodeSyncWatcher(self._llm)
            self._watcher.watch(
                script_path,
                on_code_updated=self._on_bg_code_update,
                on_prompt_updated=self._on_bg_prompt_update,
            )
            self._watcher.start()
            self._set_status(f"Watching: {script_path.name}")
        else:
            self._set_status(f"Loaded: {script_path.name} (AI sync disabled)")

    # ── Background-watcher callbacks ──────────────────────────────────────────

    def _on_bg_code_update(self, new_code: str) -> None:
        import dearpygui.dearpygui as dpg
        self._code_text = new_code
        self._code_mtime = time.monotonic()
        try:
            dpg.set_value("cm_code_input", new_code)
            dpg.set_value("cm_diff_summary", f"Code auto-synced from prompt at {_now_str()}")
        except Exception:
            pass
        self._set_status("AI: code auto-synced from prompt")

    def _on_bg_prompt_update(self, new_prompt: str) -> None:
        import dearpygui.dearpygui as dpg
        self._prompt_text = new_prompt
        self._prompt_mtime = time.monotonic()
        try:
            dpg.set_value("cm_prompt_input", new_prompt)
            dpg.set_value("cm_diff_summary", f"Prompt auto-synced from code at {_now_str()}")
        except Exception:
            pass
        self._set_status("AI: prompt auto-synced from code")

    # ── Per-frame update ──────────────────────────────────────────────────────

    def update(self) -> None:
        """Call each editor frame to keep the last-edited timestamps fresh.

        Also triggers the Ollama setup modal the first time this panel is
        updated after ``_pending_setup`` is set — at which point a valid DPG
        context is guaranteed to exist.
        """
        if self._pending_setup and not self._setup_running:
            self._trigger_setup()
        self._refresh_mtimes()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_age(ts: float) -> str:
    """Return a human-readable age string for a monotonic timestamp."""
    if ts == 0.0:
        return "never"
    age = time.monotonic() - ts
    if age < 60:
        return f"{int(age)}s ago"
    return f"{int(age / 60)}m ago"


def _now_str() -> str:
    import datetime
    return datetime.datetime.now().strftime("%H:%M:%S")
