"""``SaveOnQuitPrompt`` — modal that fires when a dirty window closes.

The notebook editor's shell exposes an ``is_dirty()`` bit. When the OS
window-close event arrives (or the user hits Alt+F4 / Cmd+Q) and the
scene is dirty, the shell asks this helper to prompt the user before
the app actually quits.

Three outcomes:

* ``Save`` — run the shell's save-scene callback, then quit.
* ``Discard`` — skip the save + quit anyway.
* ``Cancel`` — abort the quit; the window stays open.

The helper is DPG-optional. In headless tests the prompt is driven
programmatically via :meth:`resolve` so we can assert the save-then-quit
sequence without a GUI.

Design provenance: ``docs/sprint_plan_2026_06_03.md`` §7 (save-on-quit).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from pharos_engine._validation import (
    validate_bool,
    validate_callable,
)


class SavePromptChoice(str, Enum):
    """User's answer to the save-on-quit prompt."""

    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


class SaveOnQuitPrompt:
    """Modal helper for the "save before quit?" prompt.

    Parameters
    ----------
    is_dirty:
        Zero-arg callable returning ``True`` iff the current scene has
        unsaved changes. Typically bound to ``EditorShell.is_dirty``.
    save_scene:
        Zero-arg callable that persists the current scene to disk.
    quit_app:
        Zero-arg callable that actually tears the editor down.
    """

    MODAL_TAG = "notebook_save_on_quit_modal"
    PROMPT_TEXT = "You have unsaved changes. Save now?"

    def __init__(
        self,
        is_dirty: Callable[[], bool],
        save_scene: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        validate_callable("is_dirty", "SaveOnQuitPrompt", is_dirty)
        validate_callable("save_scene", "SaveOnQuitPrompt", save_scene)
        validate_callable("quit_app", "SaveOnQuitPrompt", quit_app)
        self._is_dirty = is_dirty
        self._save_scene = save_scene
        self._quit_app = quit_app
        self._open: bool = False
        self._last_choice: SavePromptChoice | None = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def last_choice(self) -> SavePromptChoice | None:
        return self._last_choice

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def request_close(self) -> bool:
        """Handle a window-close request.

        Returns ``True`` when the app should actually quit (either the
        scene wasn't dirty, or the user picked Save / Discard). Returns
        ``False`` when the modal is now open — the caller keeps the
        window alive and waits for :meth:`resolve` to fire.
        """
        try:
            dirty = bool(self._is_dirty())
        except Exception:
            dirty = False
        if not dirty:
            # Clean scene → straight to quit.
            self._quit_app()
            return True
        self._open_modal()
        return False

    def _open_modal(self) -> None:
        """Open the modal in DPG when available (else record state only)."""
        self._open = True
        self._last_choice = None
        dpg = _safe_dpg()
        if dpg is None:
            return
        # Tear down any lingering modal from a previous close attempt.
        try:
            if dpg.does_item_exist(self.MODAL_TAG):
                dpg.delete_item(self.MODAL_TAG)
        except Exception:
            pass
        try:
            with dpg.window(
                label="Unsaved changes",
                modal=True,
                tag=self.MODAL_TAG,
                width=380,
                height=140,
                no_close=True,
            ):
                try:
                    dpg.add_text(self.PROMPT_TEXT)
                except Exception:
                    pass
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="Save",
                            width=110,
                            callback=lambda *_: self.resolve(
                                SavePromptChoice.SAVE,
                            ),
                        )
                        dpg.add_button(
                            label="Discard",
                            width=110,
                            callback=lambda *_: self.resolve(
                                SavePromptChoice.DISCARD,
                            ),
                        )
                        dpg.add_button(
                            label="Cancel",
                            width=110,
                            callback=lambda *_: self.resolve(
                                SavePromptChoice.CANCEL,
                            ),
                        )
                except Exception:
                    pass
        except Exception:
            pass

    def resolve(self, choice: SavePromptChoice) -> bool:
        """Apply the user's answer.

        Returns ``True`` when the app should now quit.
        """
        if not isinstance(choice, SavePromptChoice):
            raise TypeError(
                f"SaveOnQuitPrompt.resolve: choice must be a SavePromptChoice; "
                f"got {type(choice).__name__}"
            )
        self._last_choice = choice
        self._open = False
        # Close the DPG modal (best-effort).
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                if dpg.does_item_exist(self.MODAL_TAG):
                    dpg.delete_item(self.MODAL_TAG)
            except Exception:
                pass

        if choice is SavePromptChoice.CANCEL:
            return False
        if choice is SavePromptChoice.SAVE:
            try:
                self._save_scene()
            except Exception:
                # A failed save shouldn't strand the user — still quit so
                # the process can exit; the caller has already shown an
                # error toast in the save handler.
                pass
        # SAVE + DISCARD both proceed to quit.
        try:
            self._quit_app()
        except Exception:
            pass
        return True


def _safe_dpg() -> Any | None:
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


__all__ = ["SaveOnQuitPrompt", "SavePromptChoice"]
