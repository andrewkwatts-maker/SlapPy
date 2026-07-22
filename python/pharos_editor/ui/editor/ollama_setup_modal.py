"""Ollama setup UI — opt-in dialog + pull-progress modal.

Flow
----
1. :class:`AiOptInDialog` — shown on first launch; asks whether the user
   wants local AI support and which model to use.  Saves the choice to
   ``~/.SlapPyEngine/ai_settings.json`` so it is never asked again.
2. :class:`OllamaSetupModal` — shown when the chosen model still needs to
   be pulled.  Shows a live progress bar fed by ``ollama pull`` output.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Tag constants — all prefixed to avoid DPG collisions ──────────────────────
_OPT_MODAL   = "ai_optin_modal"
_OPT_COMBO   = "ai_optin_combo"
_OPT_CUSTOM  = "ai_optin_custom"
_OPT_DESC    = "ai_optin_desc"

_PULL_MODAL  = "ollama_setup_modal"
_PULL_STATUS = "ollama_setup_status"
_PULL_BAR    = "ollama_setup_progress"
_PULL_PCT    = "ollama_setup_pct"
_PULL_CANCEL = "ollama_setup_cancel"

# ── Available models shown in the dropdown ────────────────────────────────────
AVAILABLE_MODELS = [
    "None (disable AI sync)",
    "qwen2.5-coder:7b  (Recommended — 4.7 GB)",
    "codellama:7b  (Meta CodeLlama — 3.8 GB)",
    "deepseek-coder:6.7b  (DeepSeek — 3.8 GB)",
    "phi3:mini  (Small & fast — 2.3 GB)",
    "Other (type below)…",
]

_MODEL_TAGS = {
    "None (disable AI sync)":             None,
    "qwen2.5-coder:7b  (Recommended — 4.7 GB)": "qwen2.5-coder:7b",
    "codellama:7b  (Meta CodeLlama — 3.8 GB)":  "codellama:7b",
    "deepseek-coder:6.7b  (DeepSeek — 3.8 GB)": "deepseek-coder:6.7b",
    "phi3:mini  (Small & fast — 2.3 GB)":        "phi3:mini",
    "Other (type below)…":                None,  # resolved from custom input
}


# ─────────────────────────────────────────────────────────────────────────────
# Opt-in dialog
# ─────────────────────────────────────────────────────────────────────────────

class AiOptInDialog:
    """First-run dialog asking whether to enable local AI support.

    Shows a model picker and saves the choice to
    ``~/.SlapPyEngine/ai_settings.json``.  Returns the chosen model tag
    (``str``) or ``None`` (disabled / skipped).

    Usage::

        choice = AiOptInDialog().show()  # blocks via DPG frame loop
        # choice is a model tag like "qwen2.5-coder:7b" or None
    """

    def __init__(self) -> None:
        self._choice: str | None | bool = ...  # Ellipsis = pending
        self._selected_label: str = AVAILABLE_MODELS[1]  # default: recommended
        self._custom_text: str = ""

    def show(self) -> str | None:
        """Display the opt-in modal and block until the user chooses."""
        import dearpygui.dearpygui as dpg

        self._choice = ...
        self._build(dpg)

        while self._choice is ...:
            dpg.render_dearpygui_frame()

        try:
            dpg.delete_item(_OPT_MODAL)
        except Exception:
            pass

        return self._choice  # type: ignore[return-value]

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self, dpg) -> None:
        if dpg.does_item_exist(_OPT_MODAL):
            dpg.delete_item(_OPT_MODAL)

        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()
        w, h = 480, 280

        with dpg.window(
            label="Local AI Support",
            tag=_OPT_MODAL,
            modal=True,
            no_close=True,
            width=w,
            height=h,
            pos=(max(0, (vw - w) // 2), max(0, (vh - h) // 2)),
        ):
            dpg.add_text(
                "SlapPyEngine can use a local Ollama model to automatically\n"
                "sync your prompt descriptions with code as you edit.",
                wrap=w - 24,
                color=(200, 200, 220),
            )
            dpg.add_spacer(height=6)
            dpg.add_separator()
            dpg.add_spacer(height=6)

            dpg.add_text("Select a model:", color=(180, 180, 180))
            dpg.add_combo(
                items=AVAILABLE_MODELS,
                default_value=self._selected_label,
                width=w - 24,
                tag=_OPT_COMBO,
                callback=self._on_combo_change,
            )
            dpg.add_spacer(height=4)
            dpg.add_input_text(
                tag=_OPT_CUSTOM,
                hint="Custom model tag, e.g. llama3:8b",
                width=w - 24,
                default_value="",
                show=False,
                callback=self._on_custom_change,
            )
            dpg.add_text(
                "Models are downloaded once (~2-5 GB) and run locally.\n"
                "Choose None to skip — you can enable AI later in Code Mode.",
                tag=_OPT_DESC,
                wrap=w - 24,
                color=(140, 140, 150),
            )
            dpg.add_spacer(height=10)

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Enable AI",
                    width=120,
                    callback=self._on_enable,
                )
                dpg.add_spacer(width=8)
                dpg.add_button(
                    label="Skip (no AI)",
                    width=120,
                    callback=self._on_skip,
                )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_combo_change(self, sender, app_data) -> None:
        import dearpygui.dearpygui as dpg
        self._selected_label = app_data
        is_custom = app_data == "Other (type below)…"
        dpg.configure_item(_OPT_CUSTOM, show=is_custom)

    def _on_custom_change(self, sender, app_data) -> None:
        self._custom_text = app_data.strip()

    def _on_enable(self, *_) -> None:
        label = self._selected_label
        if label == "Other (type below)…":
            tag = self._custom_text or None
        else:
            tag = _MODEL_TAGS.get(label)

        from pharos_engine.ai.ollama_manager import save_ai_settings
        save_ai_settings({"model": tag, "enabled": tag is not None})
        self._choice = tag  # may be None (user picked "None (disable)")

    def _on_skip(self, *_) -> None:
        # Skip without saving → will ask again next session
        self._choice = None


# ─────────────────────────────────────────────────────────────────────────────
# Pull-progress modal
# ─────────────────────────────────────────────────────────────────────────────

class OllamaSetupModal:
    """DPG modal that runs :meth:`OllamaManager.ensure_ready` in a thread.

    Shows a live progress bar updated by the ollama pull output stream.

    Usage::

        ready = OllamaSetupModal().show("qwen2.5-coder:7b")
    """

    def __init__(self) -> None:
        self._ready: bool | None = None
        self._cancel = threading.Event()
        self._not_installed = False

    def show(self, model: str | None = None) -> bool:
        import dearpygui.dearpygui as dpg
        from pharos_engine.ai.ollama_manager import OllamaManager

        if model is None:
            model = OllamaManager.DEFAULT_MODEL

        self._ready = None
        self._cancel.clear()
        self._not_installed = False

        self._build(dpg, model)

        worker = threading.Thread(
            target=self._worker, args=(model,), daemon=True, name="ollama-pull"
        )
        worker.start()

        while self._ready is None and not self._cancel.is_set():
            dpg.render_dearpygui_frame()

        try:
            dpg.delete_item(_PULL_MODAL)
        except Exception:
            pass

        worker.join(timeout=0)
        return bool(self._ready)

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self, dpg, model: str) -> None:
        if dpg.does_item_exist(_PULL_MODAL):
            dpg.delete_item(_PULL_MODAL)

        vw = dpg.get_viewport_width()
        vh = dpg.get_viewport_height()
        w, h = 460, 200

        with dpg.window(
            label="Downloading AI Model",
            tag=_PULL_MODAL,
            modal=True,
            no_close=True,
            width=w,
            height=h,
            pos=(max(0, (vw - w) // 2), max(0, (vh - h) // 2)),
        ):
            dpg.add_text(
                f"Setting up  {model}",
                color=(180, 200, 255),
            )
            dpg.add_separator()
            dpg.add_spacer(height=8)

            dpg.add_text(
                "Initialising...",
                tag=_PULL_STATUS,
                wrap=w - 24,
                color=(220, 220, 180),
            )
            dpg.add_spacer(height=6)

            # Progress bar — starts at a tiny non-zero value so it's visible
            dpg.add_progress_bar(
                tag=_PULL_BAR,
                default_value=0.01,
                width=-1,
                height=22,
                overlay="0%",
            )
            dpg.add_spacer(height=10)
            dpg.add_button(
                label="Cancel",
                tag=_PULL_CANCEL,
                callback=self._on_cancel,
            )

    # ── Background worker ─────────────────────────────────────────────────────

    def _worker(self, model: str) -> None:
        from pharos_engine.ai.ollama_manager import OllamaManager
        mgr = OllamaManager()
        result = mgr.ensure_ready(
            model=model,
            on_progress=self._on_progress,
            cancel_event=self._cancel,
        )
        if not result and self._not_installed:
            self._show_not_installed()
        else:
            self._ready = result

    # ── Progress callback (any thread) ────────────────────────────────────────

    def _on_progress(self, status: str, fraction: float) -> None:
        import dearpygui.dearpygui as dpg

        if "ollama.com" in status.lower():
            self._not_installed = True

        # Clamp to [0.01, 1.0] so the bar always shows at least a sliver
        clamped = max(0.01, min(1.0, fraction))
        pct_str = f"{int(fraction * 100)}%"

        try:
            dpg.set_value(_PULL_STATUS, status[:80])
            dpg.set_value(_PULL_BAR, clamped)
            dpg.configure_item(_PULL_BAR, overlay=pct_str)
        except Exception:
            pass

    # ── Cancel ────────────────────────────────────────────────────────────────

    def _on_cancel(self, *_) -> None:
        self._cancel.set()
        self._ready = False

    # ── Not-installed fallback ────────────────────────────────────────────────

    def _show_not_installed(self) -> None:
        import dearpygui.dearpygui as dpg
        try:
            dpg.set_value(
                _PULL_STATUS,
                "Ollama is not installed on this machine.\n"
                "Install it from  https://ollama.com  then restart the editor.",
            )
            dpg.set_value(_PULL_BAR, 0.01)
            dpg.configure_item(_PULL_BAR, overlay="")
            dpg.configure_item(_PULL_CANCEL, label="Close")
        except Exception:
            pass
        self._ready = False
