"""
BehaviorPanel — AI-assisted entity script editor.

Two modes toggled by radio buttons:
  Prompt mode: Natural language → "Generate Script" button → calls Ollama
  Python mode: Generated/hand-written code → "Apply" button → attaches script to entity

The DPG panel protocol: build(parent_tag) -> None
"""
from __future__ import annotations
import threading


class BehaviorPanel:
    """
    Editor panel for AI-assisted entity scripting.
    Prompt ↔ Python toggle, Ollama-backed generation, live apply to entity.
    """

    def __init__(self):
        self._entity = None
        self._prompt_text: str = ""
        self._python_text: str = ""
        self._mode: str = "prompt"   # "prompt" or "python"
        self._generating: bool = False
        self._status: str = "Ready"
        self._llm = None
        self._generator = None
        self._panel_tag = "behavior_panel"

    def set_entity(self, entity) -> None:
        """Set the entity that scripts will be attached to when Apply is clicked."""
        self._entity = entity

    def build(self, parent_tag) -> None:
        """Build the DPG widget tree inside *parent_tag*."""
        try:
            import dearpygui.dearpygui as dpg
        except ImportError:
            return

        dpg.add_text("Behavior Script", color=(200, 200, 100), parent=parent_tag)
        dpg.add_separator(parent=parent_tag)

        # Mode toggle
        dpg.add_radio_button(
            items=["Prompt", "Python"],
            default_value="Prompt",
            callback=self._on_mode_change,
            horizontal=True,
            parent=parent_tag,
            tag="behavior_mode_radio",
        )
        dpg.add_separator(parent=parent_tag)

        # Prompt area (visible in prompt mode)
        dpg.add_input_text(
            tag="behavior_prompt",
            multiline=True,
            width=320,
            height=120,
            hint="Describe what this entity should do...",
            parent=parent_tag,
            callback=lambda s, a, u: setattr(self, "_prompt_text", a),
        )
        dpg.add_button(
            label="Generate Script",
            tag="behavior_generate_btn",
            callback=self._on_generate,
            parent=parent_tag,
        )

        # Python area (visible in python mode, hidden initially)
        dpg.add_input_text(
            tag="behavior_python",
            multiline=True,
            width=320,
            height=180,
            hint="# EntityScript class will appear here",
            parent=parent_tag,
            show=False,
            callback=lambda s, a, u: setattr(self, "_python_text", a),
        )
        with dpg.group(
            horizontal=True,
            parent=parent_tag,
            tag="behavior_python_btns",
            show=False,
        ):
            dpg.add_button(label="Apply", callback=self._on_apply)
            dpg.add_button(label="Copy", callback=self._on_copy)

        dpg.add_separator(parent=parent_tag)
        dpg.add_text(
            self._status,
            tag="behavior_status",
            color=(150, 200, 150),
            parent=parent_tag,
        )

    # ------------------------------------------------------------------
    # Mode toggle
    # ------------------------------------------------------------------

    def _on_mode_change(self, sender, app_data, user_data):
        try:
            import dearpygui.dearpygui as dpg
        except ImportError:
            return
        self._mode = "prompt" if app_data == "Prompt" else "python"
        show_prompt = self._mode == "prompt"
        dpg.configure_item("behavior_prompt", show=show_prompt)
        dpg.configure_item("behavior_generate_btn", show=show_prompt)
        dpg.configure_item("behavior_python", show=not show_prompt)
        dpg.configure_item("behavior_python_btns", show=not show_prompt)

    # ------------------------------------------------------------------
    # Script generation (background thread)
    # ------------------------------------------------------------------

    def _on_generate(self, sender=None, app_data=None, user_data=None):
        if self._generating:
            return
        self._set_status("Generating...", (200, 200, 100))
        self._generating = True
        prompt = self._prompt_text

        def _run():
            try:
                if self._generator is None:
                    from playslap.ai.script_gen import ScriptGenerator
                    self._generator = ScriptGenerator()
                code = self._generator.from_prompt(prompt)
                self._python_text = code
                self._set_status(f"Done ({len(code.splitlines())} lines)", (100, 220, 100))
                try:
                    import dearpygui.dearpygui as dpg
                    if dpg.does_item_exist("behavior_python"):
                        dpg.set_value("behavior_python", code)
                except Exception:
                    pass
            except Exception as e:
                self._set_status(f"Error: {e}", (220, 80, 80))
            finally:
                self._generating = False

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Apply script to entity
    # ------------------------------------------------------------------

    def _on_apply(self, sender=None, app_data=None, user_data=None):
        if not self._python_text or self._entity is None:
            self._set_status("No entity selected or no script to apply", (200, 100, 100))
            return
        try:
            ns: dict = {}
            exec(compile(self._python_text, "<behavior_panel>", "exec"), ns)
            script_cls = ns.get("EntityScript")
            if script_cls is None:
                self._set_status("Script must define class EntityScript", (200, 100, 100))
                return
            # Remove any previously applied BehaviorPanel scripts
            self._entity._scripts = [
                s for s in self._entity._scripts
                if type(s).__name__ != "EntityScript"
            ]
            self._entity.attach_script(script_cls())
            self._set_status("Script applied!", (100, 220, 100))
        except Exception as e:
            self._set_status(f"Compile error: {e}", (220, 80, 80))

    # ------------------------------------------------------------------
    # Copy to clipboard
    # ------------------------------------------------------------------

    def _on_copy(self, sender=None, app_data=None, user_data=None):
        try:
            import dearpygui.dearpygui as dpg
            dpg.set_clipboard_text(self._python_text)
            self._set_status("Copied to clipboard", (150, 200, 150))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, color=(150, 200, 150)):
        self._status = msg
        try:
            import dearpygui.dearpygui as dpg
            if dpg.does_item_exist("behavior_status"):
                dpg.configure_item("behavior_status", default_value=msg, color=color)
        except Exception:
            pass
