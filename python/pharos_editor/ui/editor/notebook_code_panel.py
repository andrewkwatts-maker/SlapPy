"""``NotebookCodePanel`` — diary-themed reskin of the Nova3D Code Mode panel.

The :class:`CodeModePanel` (see ``code_mode_panel.py``) drives a split
prompt-↔-code editor with AI synchronisation against a local Ollama
model. This sibling reskins the same logical contract as a "personal
diary entry":

* A bookmark ribbon at the top lists the open files — click to switch.
* Two pages side-by-side: the left page is the prompt ("Dear diary…")
  written in the theme's body font; the right page is the generated
  Python in a monospace face.
* A footer ribbon of action buttons: Regenerate / Explain / Pin / Saved.
* Sticker corners for gentle onboarding (a doodled arrow points at the
  Regenerate button on first launch).

Design provenance
-----------------

* ``docs/ui_pattern_audit_2026_06_03.md`` §1.7 — Nova3D code panel contract
  + woodland/notebook translation ("diary page with bookmark ribbon").

Headless / soft-import contract
-------------------------------

The panel never blocks the editor on Ollama:

* The AI plumbing (``pharos_engine.ai.ollama_manager`` /
  ``pharos_engine.ai.code_sync``) is imported lazily inside the action
  callbacks. If the import or backend probe fails, the panel falls
  back to a soft message ("Install Ollama to ask the journal to write
  code") and the Regenerate / Explain buttons become no-ops.
* Every ``dpg.*`` call is wrapped in ``try/except`` so the panel still
  registers its tags + call log entries when ``dearpygui`` is missing
  or stubbed.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import validate_non_empty_str


# ---------------------------------------------------------------------------
# Constants — placeholder copy, button labels, status messages
# ---------------------------------------------------------------------------

_PROMPT_PLACEHOLDER = "Dear diary..."
_DEFAULT_PROMPT_HINT = (
    "Dear diary... tell the journal what you want your game to do "
    "(plain English, no code)."
)
_OLLAMA_MISSING_HINT = (
    "Install Ollama to ask the journal to write code. "
    "Visit https://ollama.com to set it up."
)
_DEFAULT_TITLE = "Today's page"

# Footer button glyphs — soft hearts/flowers to keep the diary mood.
_BTN_REGENERATE = "Regenerate"
_BTN_EXPLAIN = "Explain"
_BTN_PIN = "Pin"
_BTN_SAVED = "Saved"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _try_import_code_sync() -> tuple[Any, Any, Any] | None:
    """Return ``(prompt_to_code, code_to_prompt, prompt_path_for)`` or ``None``.

    Imported lazily so the editor still loads when ``pharos_engine[ai]``
    isn't installed.
    """
    try:
        from pharos_engine.ai.code_sync import (
            code_to_prompt,
            prompt_path_for,
            prompt_to_code,
        )
        return prompt_to_code, code_to_prompt, prompt_path_for
    except Exception:
        return None


def _try_make_llm_client() -> Any | None:
    """Construct and return an LLM client, or ``None`` on failure.

    Probes the local Ollama via :class:`OllamaManager` first so we never
    construct an LLM client that's guaranteed to fail on first call.
    """
    try:
        from pharos_engine.ai.ollama_manager import (
            OllamaManager,
            load_ai_settings,
        )
    except Exception:
        return None

    try:
        settings = load_ai_settings()
        model = settings.get("model") if settings else None
        if not settings.get("enabled", False) or model is None:
            return None
        mgr = OllamaManager()
        if not mgr.is_server_running():
            return None
        if not mgr.is_model_installed(model):
            return None
        from pharos_engine.ai import LLMClient
        return LLMClient()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# NotebookCodePanel
# ---------------------------------------------------------------------------


class NotebookCodePanel:
    """Code Mode tab themed as a personal-diary entry.

    Two-pane layout: AI prompt on the left (handwritten font, lined paper
    background), generated Python on the right (monospace, dot-grid
    background). Bookmark ribbon at the top for chapter/file navigation.

    Per Nova3D's ``build(parent_tag)`` protocol.

    Parameters
    ----------
    code_sync_watcher:
        Optional preconstructed :class:`CodeSyncWatcher` used for
        background prompt/code reconciliation. When ``None`` (the
        default), the panel constructs one lazily once an LLM client
        becomes available. Pass an instance from tests to assert
        watcher routing without a real Ollama server.
    """

    TITLE = "Code"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 320

    def __init__(
        self,
        code_sync_watcher: Any | None = None,
        engine: Any | None = None,
    ) -> None:
        self._engine = engine
        self._watcher = code_sync_watcher

        # Two-pane buffers.
        self._prompt_text: str = ""
        self._code_text: str = ""
        self._prompt_mtime: float = 0.0
        self._code_mtime: float = 0.0

        # Lifecycle / status flags.
        self._status: str = "Ready"
        self._ai_busy: bool = False
        self._code_pinned: bool = False
        self._saved_indicator: bool = False

        # File bookkeeping — bookmark ribbon entries.
        self._files: list[Path] = []
        self._active_file: Path | None = None

        # AI plumbing — lazily resolved.
        self._llm: Any | None = None
        self._ai_available: bool = False
        self._ollama_missing: bool = False

        # DPG tag names — stable across rebuilds so refresh() can target them.
        oid = id(self)
        self._panel_tag = f"notebook_code_{oid}"
        self._ribbon_tag = f"{self._panel_tag}_ribbon"
        self._prompt_pane_tag = f"{self._panel_tag}_prompt_pane"
        self._code_pane_tag = f"{self._panel_tag}_code_pane"
        self._prompt_input_tag = f"{self._panel_tag}_prompt_input"
        self._code_input_tag = f"{self._panel_tag}_code_input"
        self._status_tag = f"{self._panel_tag}_status"
        self._hint_tag = f"{self._panel_tag}_hint"
        self._footer_tag = f"{self._panel_tag}_footer"
        self._sticker_tag: str | None = None

        # Build lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Tags per ribbon entry so click-to-switch works.
        self._ribbon_tags: dict[Path, str] = {}

        # Call log for headless test assertions.
        self.call_log: list[tuple[Any, ...]] = []

        # Probe AI availability — non-blocking, soft fallback only.
        self._probe_ai()

    # ------------------------------------------------------------------
    # AI plumbing
    # ------------------------------------------------------------------

    def _probe_ai(self) -> None:
        """Try to construct an LLM client. Sets ``_ai_available`` accordingly.

        Soft-fails to ``False`` when Ollama is missing or disabled. Never
        raises; the panel must remain usable without AI.
        """
        client = _try_make_llm_client()
        if client is None:
            self._llm = None
            self._ai_available = False
            self._ollama_missing = True
            self._status = "AI offline — Ollama not detected"
            return
        self._llm = client
        self._ai_available = True
        self._ollama_missing = False
        self._status = "AI ready"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prompt_text(self) -> str:
        """Return the current prompt buffer."""
        return self._prompt_text

    def get_code_text(self) -> str:
        """Return the current code buffer."""
        return self._code_text

    @property
    def ai_available(self) -> bool:
        """Return True when the AI backend probed cleanly at construction."""
        return self._ai_available

    @property
    def ollama_missing(self) -> bool:
        """Return True when the soft-fallback hint should display."""
        return self._ollama_missing

    @property
    def code_pinned(self) -> bool:
        """Return True when the code pane is editable (pinned by the user)."""
        return self._code_pinned

    @property
    def files(self) -> list[Path]:
        """Return the list of open files (bookmark ribbon entries)."""
        return list(self._files)

    @property
    def active_file(self) -> Path | None:
        """Return the path of the currently active file (or ``None``)."""
        return self._active_file

    @property
    def status(self) -> str:
        """Return the current status message."""
        return self._status

    def register_file(self, path: str | Path) -> Path:
        """Add *path* to the bookmark ribbon (idempotent). Returns the Path."""
        p = Path(path)
        for existing in self._files:
            if existing == p:
                return existing
        self._files.append(p)
        self.call_log.append(("register_file", str(p)))
        # If this is the first file, make it active.
        if self._active_file is None:
            self.set_file(p)
        else:
            # Otherwise just re-render the ribbon so the new tab appears.
            self._rebuild_ribbon()
        return p

    # Legacy CodeModePanel compat — Engine.run_editor() + content browser
    # both call .load_script(path). Alias to set_file so the existing
    # bookmark ribbon + buffer loader handle it.
    def load_script(self, script_path: str | Path) -> None:
        """Alias for :meth:`set_file`. Compat with the legacy
        ``CodeModePanel.load_script`` contract that the editor shell + the
        content browser call when the user double-clicks a ``.py`` file.
        """
        self.set_file(script_path)

    def update(self) -> None:
        """Per-frame tick from Engine.run_editor()'s main loop.

        Compat shim for the legacy ``CodeModePanel.update`` contract.
        The notebook code panel doesn't need per-frame work today
        (file watchers will hook into CodeSyncWatcher later), so this
        is currently a no-op that returns immediately.
        """
        return None

    def set_file(self, path: str | Path) -> None:
        """Switch the active file and load its .py + .prompt contents.

        Adds the path to the bookmark ribbon if not already present.
        Safe to call before :meth:`build`; the buffers are updated
        regardless and the UI catches up on the next build.
        """
        p = Path(path)
        if p not in self._files:
            self._files.append(p)
        self._active_file = p
        self.call_log.append(("set_file", str(p)))

        # Load the .py file if it exists on disk.
        try:
            self._code_text = p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception:
            self._code_text = ""

        # Load the .prompt sidecar if available.
        prompt_text = ""
        helpers = _try_import_code_sync()
        if helpers is not None:
            _, _, prompt_path_for = helpers
            try:
                pp = prompt_path_for(p)
                if pp.exists():
                    prompt_text = pp.read_text(encoding="utf-8")
            except Exception:
                pass
        self._prompt_text = prompt_text
        self._prompt_mtime = time.monotonic() if prompt_text else 0.0
        self._code_mtime = time.monotonic() if self._code_text else 0.0

        # Push the new buffers into DPG and rebuild the ribbon highlight.
        self._sync_inputs_to_dpg()
        self._rebuild_ribbon()
        self._set_status(f"Loaded: {p.name}")

    def new_file(self) -> None:
        """Ribbon ``+ New`` button — open an unsaved scratch buffer.

        Adds a new ``untitled_<n>.py`` entry to the ribbon, clears the
        prompt/code buffers, and switches focus to it. The file is
        not written to disk until the user saves through the engine.
        """
        self.call_log.append(("new_file_clicked",))
        n = 1
        existing = {p.name for p in self._files}
        while f"untitled_{n}.py" in existing:
            n += 1
        scratch = Path(f"untitled_{n}.py")
        self._files.append(scratch)
        self._active_file = scratch
        self._prompt_text = ""
        self._code_text = ""
        self._prompt_mtime = 0.0
        self._code_mtime = 0.0
        self._sync_inputs_to_dpg()
        self._rebuild_ribbon()
        self._set_status(f"New scratch buffer: {scratch.name}")

    def regenerate(self) -> None:
        """AI prompt → code. Blocks briefly while the AI runs.

        Soft no-op when Ollama isn't available. Status updates reflect
        outcome so the user always knows what happened.
        """
        self.call_log.append(("regenerate",))
        if self._ai_busy:
            return
        if not self._ai_available or self._llm is None:
            self._set_status(_OLLAMA_MISSING_HINT)
            return
        helpers = _try_import_code_sync()
        if helpers is None:
            self._set_status(_OLLAMA_MISSING_HINT)
            return
        prompt_to_code, _, _ = helpers
        self._ai_busy = True
        self._set_status("AI: rewriting code from prompt...")
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                new_code = loop.run_until_complete(
                    prompt_to_code(self._prompt_text, self._code_text, self._llm)
                )
            finally:
                loop.close()
            if new_code:
                self._code_text = new_code
                self._code_mtime = time.monotonic()
                if self._active_file is not None:
                    try:
                        self._active_file.write_text(new_code, encoding="utf-8")
                    except Exception:
                        pass
                self._sync_inputs_to_dpg()
                self._set_status("AI: code regenerated from prompt")
        except Exception as exc:
            self._set_status(f"AI error: {exc}")
        finally:
            self._ai_busy = False

    def reverse_sync(self) -> None:
        """Code → prompt explanation. Soft no-op without Ollama."""
        self.call_log.append(("reverse_sync",))
        if self._ai_busy:
            return
        if not self._ai_available or self._llm is None:
            self._set_status(_OLLAMA_MISSING_HINT)
            return
        helpers = _try_import_code_sync()
        if helpers is None:
            self._set_status(_OLLAMA_MISSING_HINT)
            return
        _, code_to_prompt, prompt_path_for = helpers
        self._ai_busy = True
        self._set_status("AI: generating description from code...")
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                new_prompt = loop.run_until_complete(
                    code_to_prompt(self._code_text, self._llm)
                )
            finally:
                loop.close()
            if new_prompt:
                self._prompt_text = new_prompt
                self._prompt_mtime = time.monotonic()
                if self._active_file is not None:
                    try:
                        prompt_path_for(self._active_file).write_text(
                            new_prompt, encoding="utf-8",
                        )
                    except Exception:
                        pass
                self._sync_inputs_to_dpg()
                self._set_status("AI: prompt regenerated from code")
        except Exception as exc:
            self._set_status(f"AI error: {exc}")
        finally:
            self._ai_busy = False

    def toggle_pin(self) -> None:
        """Toggle the code pane between read-only and editable."""
        self._code_pinned = not self._code_pinned
        self.call_log.append(("toggle_pin", self._code_pinned))
        # The pin state is read on the next sync; nudge it.
        self._sync_inputs_to_dpg()

    def toggle_saved(self) -> None:
        """Flip the Saved indicator (used by the on-save butterfly hook)."""
        self._saved_indicator = not self._saved_indicator
        self.call_log.append(("toggle_saved", self._saved_indicator))

    def refresh_theme(self) -> None:
        """Re-resolve theme colours; reserved for the on-theme-switch hook.

        The notebook theme exposes paper / ink / washi semantics; this
        method exists so future theme overhauls can re-pull palette
        values without reconstructing the panel.
        """
        self.call_log.append(("refresh_theme",))
        # No cached colour state today — the build path queries the theme
        # directly per render. Just re-emit the status so listeners observe.
        self._set_status(self._status)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the panel under *parent_tag* (DPG protocol).

        Layout:

        1. Bookmark ribbon — horizontal strip of file tabs + "+ New".
        2. Two-pane group — prompt on the left, code on the right.
        3. Footer ribbon — Regenerate / Explain / Pin / Saved.
        4. Status line at the bottom.
        5. Sticker corner pointing at Regenerate (gentle onboarding).
        """
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                self._build_ribbon(dpg)
                self._build_two_pane(dpg)
                self._build_footer(dpg)
                self._build_status(dpg)
        except Exception:
            # Stub DPG / no context-manager support — flat fallback path.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag, tag=self._panel_tag)
            except Exception:
                pass
            self._build_ribbon(dpg)
            self._build_two_pane(dpg)
            self._build_footer(dpg)
            self._build_status(dpg)

        # Optional sticker corner — gentle onboarding hint. Soft-fails.
        self._add_sticker_corner()

    # ------------------------------------------------------------------
    # Build helpers
    # ------------------------------------------------------------------

    def _build_ribbon(self, dpg: Any) -> None:
        """Bookmark ribbon — one NotebookTab-style button per open file."""
        try:
            with dpg.group(
                horizontal=True, parent=self._panel_tag, tag=self._ribbon_tag,
            ):
                self._render_ribbon_entries(dpg)
        except Exception:
            try:
                dpg.add_text(
                    "Ribbon", parent=self._panel_tag, tag=self._ribbon_tag,
                )
            except Exception:
                pass
            self._render_ribbon_entries(dpg)
        self.call_log.append(("ribbon_built", len(self._files)))

    def _render_ribbon_entries(self, dpg: Any) -> None:
        """Render one tab per open file plus a [+ New] button."""
        self._ribbon_tags = {}
        for path in self._files:
            tag = f"{self._ribbon_tag}__{abs(hash(str(path)))}"
            self._ribbon_tags[path] = tag
            label = f"o {path.name}" if path == self._active_file else path.name
            try:
                dpg.add_button(
                    label=label,
                    parent=self._ribbon_tag,
                    tag=tag,
                    callback=self._make_ribbon_callback(path),
                )
            except Exception:
                pass
        try:
            dpg.add_button(
                label="+ New",
                parent=self._ribbon_tag,
                tag=f"{self._ribbon_tag}_new_btn",
                callback=lambda *_: self.new_file(),
            )
        except Exception:
            pass

    def _make_ribbon_callback(self, path: Path) -> Callable[..., None]:
        """Return a DPG callback that switches the active file to *path*."""
        def _cb(*_args: Any, **_kwargs: Any) -> None:
            self.call_log.append(("ribbon_click", str(path)))
            self.set_file(path)
        return _cb

    def _rebuild_ribbon(self) -> None:
        """Wipe + re-render the ribbon to reflect the current file list."""
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._ribbon_tag):
                # Delete the children only — keep the ribbon container.
                try:
                    children = dpg.get_item_children(self._ribbon_tag, 1)
                except Exception:
                    children = []
                if isinstance(children, dict):
                    children = list(children.values())
                for child in children or []:
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
        except Exception:
            pass
        self._render_ribbon_entries(dpg)

    def _build_two_pane(self, dpg: Any) -> None:
        """Side-by-side prompt + code pane group."""
        pane_w = 530
        pane_h = 460
        try:
            with dpg.group(horizontal=True, parent=self._panel_tag):
                self._build_prompt_pane(dpg, pane_w, pane_h)
                self._build_code_pane(dpg, pane_w, pane_h)
        except Exception:
            self._build_prompt_pane(dpg, pane_w, pane_h)
            self._build_code_pane(dpg, pane_w, pane_h)

    def _build_prompt_pane(self, dpg: Any, pane_w: int, pane_h: int) -> None:
        """Left page: AI prompt with washi-tape underline + diary placeholder."""
        try:
            with dpg.child_window(
                width=pane_w, height=pane_h, border=True,
                parent=self._panel_tag, tag=self._prompt_pane_tag,
            ):
                # Page title — handwritten font slot when the theme provides one.
                try:
                    dpg.add_text(
                        "Dear diary...",
                        color=(120, 90, 70, 255),
                    )
                except Exception:
                    pass
                # The hint shows when Ollama is missing.
                try:
                    hint = (
                        _OLLAMA_MISSING_HINT
                        if self._ollama_missing
                        else _DEFAULT_PROMPT_HINT
                    )
                    dpg.add_text(
                        hint,
                        wrap=pane_w - 16,
                        color=(150, 130, 100, 255),
                        tag=self._hint_tag,
                    )
                except Exception:
                    pass
                # Multiline prompt input — body font (legibility wins).
                try:
                    dpg.add_input_text(
                        multiline=True,
                        width=pane_w - 16,
                        height=pane_h - 96,
                        default_value=self._prompt_text,
                        hint=_PROMPT_PLACEHOLDER,
                        tag=self._prompt_input_tag,
                        callback=self._on_prompt_edited,
                    )
                except Exception:
                    try:
                        dpg.add_input_text(
                            multiline=True,
                            parent=self._prompt_pane_tag,
                            tag=self._prompt_input_tag,
                            default_value=self._prompt_text,
                        )
                    except Exception:
                        pass
                # Washi-tape underline — decorative coloured strip.
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=(255, 175, 200, 200),
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG flat path: just register the prompt input tag.
            try:
                dpg.add_input_text(
                    multiline=True,
                    parent=self._panel_tag,
                    tag=self._prompt_input_tag,
                    default_value=self._prompt_text,
                )
            except Exception:
                pass

    def _build_code_pane(self, dpg: Any, pane_w: int, pane_h: int) -> None:
        """Right page: generated Python with dot-grid background."""
        try:
            with dpg.child_window(
                width=pane_w, height=pane_h, border=True,
                parent=self._panel_tag, tag=self._code_pane_tag,
            ):
                try:
                    dpg.add_text(
                        "# Today's code",
                        color=(80, 100, 140, 255),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_text(
                        multiline=True,
                        width=pane_w - 16,
                        height=pane_h - 64,
                        default_value=self._code_text,
                        tab_input=True,
                        readonly=not self._code_pinned,
                        tag=self._code_input_tag,
                        callback=self._on_code_edited,
                    )
                except Exception:
                    try:
                        dpg.add_input_text(
                            multiline=True,
                            parent=self._code_pane_tag,
                            tag=self._code_input_tag,
                            default_value=self._code_text,
                        )
                    except Exception:
                        pass
        except Exception:
            try:
                dpg.add_input_text(
                    multiline=True,
                    parent=self._panel_tag,
                    tag=self._code_input_tag,
                    default_value=self._code_text,
                )
            except Exception:
                pass

    def _build_footer(self, dpg: Any) -> None:
        """Footer ribbon of action buttons: Regenerate / Explain / Pin / Saved."""
        try:
            with dpg.group(
                horizontal=True, parent=self._panel_tag, tag=self._footer_tag,
            ):
                self._render_footer_buttons(dpg)
        except Exception:
            self._render_footer_buttons(dpg)

    def _render_footer_buttons(self, dpg: Any) -> None:
        try:
            dpg.add_button(
                label=_BTN_REGENERATE,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_regen",
                callback=lambda *_: self.regenerate(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_EXPLAIN,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_explain",
                callback=lambda *_: self.reverse_sync(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_PIN,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_pin",
                callback=lambda *_: self.toggle_pin(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_SAVED,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_saved",
                callback=lambda *_: self.toggle_saved(),
            )
        except Exception:
            pass

    def _build_status(self, dpg: Any) -> None:
        """Status line at the very bottom — margin annotation."""
        try:
            dpg.add_text(
                self._status,
                parent=self._panel_tag,
                tag=self._status_tag,
                color=(150, 130, 100, 255),
            )
        except Exception:
            pass

    def _add_sticker_corner(self) -> None:
        """Drop a doodled-arrow sticker pointing at the Regenerate button."""
        try:
            from pharos_editor.ui.widgets.sticker_corner import add_sticker_corner
            self._sticker_tag = add_sticker_corner(
                self._panel_tag, "doodle_arrow", corner="TR",
            )
            self.call_log.append(("sticker_added", self._sticker_tag))
        except Exception:
            self._sticker_tag = None

    # ------------------------------------------------------------------
    # Input callbacks
    # ------------------------------------------------------------------

    def _on_prompt_edited(self, sender: Any, data: Any) -> None:
        """Cache the prompt buffer and timestamp on every keystroke."""
        try:
            self._prompt_text = str(data)
        except Exception:
            return
        self._prompt_mtime = time.monotonic()
        self.call_log.append(("prompt_edited", len(self._prompt_text)))

    def _on_code_edited(self, sender: Any, data: Any) -> None:
        """Cache the code buffer and timestamp on every keystroke."""
        if not self._code_pinned:
            # Read-only — ignore late writes from a stale callback.
            return
        try:
            self._code_text = str(data)
        except Exception:
            return
        self._code_mtime = time.monotonic()
        self.call_log.append(("code_edited", len(self._code_text)))

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        msg = validate_non_empty_str("msg", "NotebookCodePanel._set_status", msg)
        self._status = msg
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._status_tag):
                dpg.set_value(self._status_tag, msg)
        except Exception:
            pass

    def _sync_inputs_to_dpg(self) -> None:
        """Push the prompt / code buffers into the DPG input widgets."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._prompt_input_tag):
                dpg.set_value(self._prompt_input_tag, self._prompt_text)
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._code_input_tag):
                dpg.set_value(self._code_input_tag, self._code_text)
        except Exception:
            pass
        # Code pane read-only flag tracks the pin state.
        try:
            if dpg.does_item_exist(self._code_input_tag):
                dpg.configure_item(
                    self._code_input_tag, readonly=not self._code_pinned,
                )
        except Exception:
            pass


__all__ = ["NotebookCodePanel"]
