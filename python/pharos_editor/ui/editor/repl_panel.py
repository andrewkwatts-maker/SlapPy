"""``REPLPanel`` — Python REPL surface embedded in the editor.

The user's directive (CCC2 sprint):

    "coding them in the editor via python bindings / having exposed
    functions / helper functions"

This panel lets a developer sitting in the editor drive the running
:class:`pharos_engine.App` from a live Python prompt: type a snippet,
hit Enter, and see the result rendered above the input.

Design goals
------------

* **Zero side effects on the App at build time.** The panel merely
  captures a reference to the app; it never mutates state until the
  user actually submits a command.
* **Headless-safe.** Every ``dearpygui`` call is guarded so tests can
  build the panel under a stub DPG module.
* **Discoverable.** The default namespace pre-imports
  :mod:`pharos_engine`, the helpers module, and pins the current
  :class:`App` as ``app`` — so a bare ``help()`` or ``spawn_cube()``
  works without any set-up.
* **Tab completion.** A basic attribute completer walks the namespace
  when the user hits Tab on ``app.``, ``scene.``, ``helpers.``, etc.
* **History.** Up/Down cycles through past submissions, ChromeDevTools-style.

Protocol
--------

Follows the ``build(parent_tag)`` protocol used by the rest of
``pharos_editor.ui.editor``. The shell instantiates the panel, hands it a
parent tag, and treats the returned window/child as the tab body.
"""
from __future__ import annotations

import io
import sys
import traceback
from typing import Any, Callable

from pharos_editor.editor import helpers as _helpers


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TITLE = "REPL"

_PROMPT = ">>> "
_ERROR_COLOR = (220, 90, 90)     # red for tracebacks
_RESULT_COLOR = (200, 210, 220)  # neutral for stdout / repr
_PROMPT_COLOR = (140, 180, 240)  # blue for the echoed command
_INFO_COLOR = (120, 200, 140)    # green for /help + banner

_BANNER = (
    "Pharos Engine REPL — `app`, `scene`, `helpers`, and every top-level "
    "export are pre-imported.\n"
    "Type `help()` for the helper cheat sheet, or `/help` for panel commands."
)

_PANEL_HELP = (
    "Panel commands:\n"
    "  /help    Show this message\n"
    "  /clear   Clear the output area\n"
    "  /history List the last commands\n"
    "  Tab      Complete attribute on `app.`, `scene.`, `helpers.`\n"
    "  Up/Down  Cycle through history"
)


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


# ---------------------------------------------------------------------------
# REPLPanel
# ---------------------------------------------------------------------------


class REPLPanel:
    """DearPyGui panel that evaluates Python against the running editor.

    Constructed with the current :class:`App` (or ``None`` — the panel
    will lazily grab :attr:`App._implicit` on first submit). The scene
    reference is optional; when absent, ``scene`` is bound to ``None``
    inside the namespace.

    Attributes
    ----------
    app
        The bound :class:`pharos_engine.App` — populated at construction
        or on first submit.
    scene
        Optional scene reference. Bound to ``scene`` in the namespace.
    history
        List of every submitted command in submission order.
    output
        List of ``(kind, text)`` tuples where ``kind`` is one of
        ``"prompt"`` / ``"result"`` / ``"error"`` / ``"info"``. Used by
        tests + the render loop.
    """

    TITLE = TITLE

    def __init__(
        self,
        app: Any = None,
        scene: Any = None,
        *,
        extra_namespace: dict[str, Any] | None = None,
    ) -> None:
        self.app = app
        self.scene = scene

        # Rolling history + cursor. Cursor is one past the end when the
        # user is at the "live" input line; Up decrements, Down brings
        # it back to (len(history)) i.e. the empty live line.
        self.history: list[str] = []
        self._history_cursor: int = 0

        # Structured output — tests read this directly; the DPG render
        # loop paints it into the output child window.
        self.output: list[tuple[str, str]] = []

        # Persistent namespace so `x = 1` in one command survives to the
        # next. Populated lazily on first submit so we don't force an
        # ``App`` construction at build time.
        self._namespace: dict[str, Any] | None = None
        self._extra_namespace = dict(extra_namespace or {})

        # DPG tag bookkeeping — unique per instance so multiple REPLs
        # can co-exist in a docked layout.
        _uid = id(self)
        self._panel_tag = f"repl_panel_{_uid}"
        self._output_tag = f"repl_output_{_uid}"
        self._input_tag = f"repl_input_{_uid}"
        self._built = False

        # Emit the banner as the first output line so a freshly built
        # panel is discoverable without a submit.
        self.output.append(("info", _BANNER))

    # ------------------------------------------------------------------
    # Namespace management
    # ------------------------------------------------------------------

    def _build_namespace(self) -> dict[str, Any]:
        """Assemble the exec namespace on first use.

        Includes:

        * The full :mod:`pharos_engine` module + every symbol in its
          ``__all__`` (so `App` / `launch` / etc. resolve bare).
        * The helpers module under both ``helpers`` and its individual
          function names.
        * ``app`` → the resolved :class:`App` (lazy — implicit-global
          fallback).
        * ``scene`` → the bound scene, or ``None``.
        * Anything the caller passed via ``extra_namespace=``.
        """
        import pharos_engine

        if self.app is None:
            try:
                self.app = pharos_engine.App._get_implicit()
            except Exception:
                self.app = None

        ns: dict[str, Any] = {
            "__builtins__": __builtins__,
            "pharos_engine": pharos_engine,
            "helpers": _helpers,
            "app": self.app,
            "scene": self.scene,
        }
        # Pull every top-level export into the namespace so bare
        # ``App()`` / ``load_model(...)`` works.
        for name in getattr(pharos_engine, "__all__", []):
            if name in ns:
                continue
            try:
                ns[name] = getattr(pharos_engine, name)
            except AttributeError:  # pragma: no cover
                continue
        # Same for the helpers.
        for name in getattr(_helpers, "__all__", []):
            ns.setdefault(name, getattr(_helpers, name))
        ns.update(self._extra_namespace)
        return ns

    def _get_namespace(self) -> dict[str, Any]:
        if self._namespace is None:
            self._namespace = self._build_namespace()
        return self._namespace

    # ------------------------------------------------------------------
    # Core: evaluate a single submission
    # ------------------------------------------------------------------

    def submit(self, command: str) -> str:
        """Execute *command* against the namespace and return the output text.

        Handles both statement (``x = 1``) and expression (``1 + 1``)
        forms transparently: expressions get an ``eval`` pass so their
        return value renders inline, statements get ``exec``.

        Captures stdout + stderr into the output buffer, tags them as
        ``"result"`` / ``"error"``, and returns the rendered text so
        tests can assert on it without walking the buffer.
        """
        cmd = command.rstrip("\r\n")
        if not cmd.strip():
            return ""

        # Panel-scoped slash commands — never enter the exec path.
        if cmd.startswith("/"):
            return self._run_slash_command(cmd)

        self.history.append(cmd)
        self._history_cursor = len(self.history)
        self.output.append(("prompt", _PROMPT + cmd))

        ns = self._get_namespace()

        old_stdout, old_stderr = sys.stdout, sys.stderr
        buf = io.StringIO()
        sys.stdout = buf
        sys.stderr = buf
        rendered = ""
        try:
            # Try expression first — cheap, and preserves the value.
            try:
                value = eval(cmd, ns)
            except SyntaxError:
                exec(cmd, ns)
                value = None
            printed = buf.getvalue()
            parts: list[str] = []
            if printed:
                parts.append(printed.rstrip("\n"))
            if value is not None:
                parts.append(repr(value))
            rendered = "\n".join(parts)
            if rendered:
                self.output.append(("result", rendered))
        except Exception:
            tb = traceback.format_exc()
            printed = buf.getvalue()
            rendered = (printed + tb).rstrip("\n")
            self.output.append(("error", rendered))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self._flush_to_dpg()
        return rendered

    # ------------------------------------------------------------------
    # Slash commands — /help /clear /history
    # ------------------------------------------------------------------

    def _run_slash_command(self, cmd: str) -> str:
        name = cmd[1:].strip().lower()
        if name in ("help", "?"):
            self.output.append(("info", _PANEL_HELP))
            text = _PANEL_HELP
        elif name == "clear":
            self.output.clear()
            self.output.append(("info", _BANNER))
            text = ""
        elif name == "history":
            body = "\n".join(f"{i:3d}: {c}" for i, c in enumerate(self.history))
            self.output.append(("info", body or "(no history)"))
            text = body
        else:
            msg = f"Unknown panel command: {cmd}"
            self.output.append(("error", msg))
            text = msg
        self._flush_to_dpg()
        return text

    # ------------------------------------------------------------------
    # History nav — Up / Down
    # ------------------------------------------------------------------

    def previous(self) -> str:
        """Return the previous history entry (called on Up-arrow)."""
        if not self.history:
            return ""
        self._history_cursor = max(0, self._history_cursor - 1)
        return self.history[self._history_cursor]

    def next(self) -> str:  # noqa: A003 — intentional REPL vocabulary
        """Return the next history entry, or empty at the live line."""
        if not self.history:
            return ""
        if self._history_cursor >= len(self.history) - 1:
            self._history_cursor = len(self.history)
            return ""
        self._history_cursor += 1
        return self.history[self._history_cursor]

    # ------------------------------------------------------------------
    # Tab completion — basic attribute completer.
    # ------------------------------------------------------------------

    def complete(self, text: str) -> list[str]:
        """Return candidate completions for the current input text.

        Only the trailing token is inspected. Two shapes are handled:

        * ``prefix`` → filters the top-level namespace for names starting
          with ``prefix``.
        * ``obj.attr`` → walks the namespace to resolve ``obj`` and lists
          its attributes starting with ``attr``.

        Underscore-prefixed names are hidden unless the query itself
        starts with an underscore.
        """
        ns = self._get_namespace()
        # Take the trailing identifier chain — everything after the last
        # whitespace / open paren / comma.
        tail = text.rstrip()
        for sep in (" ", "\t", "(", ",", "="):
            idx = tail.rfind(sep)
            if idx >= 0:
                tail = tail[idx + 1 :]
        if not tail:
            return sorted(k for k in ns.keys() if not k.startswith("_"))
        if "." not in tail:
            hide_priv = not tail.startswith("_")
            return sorted(
                k for k in ns.keys()
                if k.startswith(tail) and (not hide_priv or not k.startswith("_"))
            )
        # Attribute chain — resolve everything left of the final dot.
        head, _, attr = tail.rpartition(".")
        try:
            obj: Any = eval(head, ns)
        except Exception:
            return []
        candidates = dir(obj)
        hide_priv = not attr.startswith("_")
        return sorted(
            f"{head}.{c}" for c in candidates
            if c.startswith(attr) and (not hide_priv or not c.startswith("_"))
        )

    # ------------------------------------------------------------------
    # Rendering — DPG surface
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the panel under *parent_tag* (DPG protocol)."""
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                dpg.add_text("Python REPL", color=_INFO_COLOR)
                dpg.add_separator()
                # Output — scrolling, read-only, monospace.
                try:
                    dpg.add_child_window(
                        tag=self._output_tag,
                        width=-1,
                        height=-40,   # leave room for the input row
                        border=True,
                    )
                except Exception:
                    dpg.add_child_window(tag=self._output_tag)
                # Input row — single-line, submits on Enter.
                try:
                    dpg.add_input_text(
                        tag=self._input_tag,
                        hint=_PROMPT,
                        width=-1,
                        on_enter=True,
                        callback=self._on_enter_callback,
                    )
                except Exception:
                    dpg.add_input_text(
                        tag=self._input_tag,
                        callback=self._on_enter_callback,
                    )
                # Key handler — Up/Down/Tab drive history + completion.
                self._install_key_handler(dpg)
        except Exception:
            # Stub DPG that doesn't support context managers — fall back
            # to bare add_text so the tag still lands.
            try:
                dpg.add_text("Python REPL", parent=parent_tag)
            except Exception:
                pass

        self._flush_to_dpg()

    # ------------------------------------------------------------------
    def _install_key_handler(self, dpg: Any) -> None:
        """Wire Up/Down/Tab handlers into the input widget."""
        try:
            with dpg.handler_registry(tag=f"{self._panel_tag}_keys"):
                # Up arrow → history previous
                dpg.add_key_press_handler(
                    key=getattr(dpg, "mvKey_Up", 265),
                    callback=self._on_up_arrow,
                )
                dpg.add_key_press_handler(
                    key=getattr(dpg, "mvKey_Down", 264),
                    callback=self._on_down_arrow,
                )
                dpg.add_key_press_handler(
                    key=getattr(dpg, "mvKey_Tab", 258),
                    callback=self._on_tab_key,
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # DPG callbacks
    # ------------------------------------------------------------------

    def _on_enter_callback(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            text = dpg.get_value(self._input_tag) or ""
        except Exception:
            return
        self.submit(text)
        try:
            dpg.set_value(self._input_tag, "")
        except Exception:
            pass

    def _on_up_arrow(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            dpg.set_value(self._input_tag, self.previous())
        except Exception:
            pass

    def _on_down_arrow(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            dpg.set_value(self._input_tag, self.next())
        except Exception:
            pass

    def _on_tab_key(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            current = dpg.get_value(self._input_tag) or ""
        except Exception:
            return
        candidates = self.complete(current)
        if len(candidates) == 1:
            # Replace the trailing token with the completion.
            head, sep, _ = current.rpartition(" ")
            replacement = (head + sep + candidates[0]) if sep else candidates[0]
            try:
                dpg.set_value(self._input_tag, replacement)
            except Exception:
                pass
        elif candidates:
            self.output.append(("info", "  ".join(candidates)))
            self._flush_to_dpg()

    # ------------------------------------------------------------------
    # Output painter — pushes the structured buffer into DPG.
    # ------------------------------------------------------------------

    def _flush_to_dpg(self) -> None:
        """Repaint the output child window from :attr:`output`.

        Best-effort — silently no-ops when the panel hasn't been built
        or when the DPG stub doesn't support ``delete_item``.
        """
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._output_tag):
                try:
                    dpg.delete_item(self._output_tag, children_only=True)
                except Exception:
                    pass
                for kind, text in self.output:
                    color = _RESULT_COLOR
                    if kind == "error":
                        color = _ERROR_COLOR
                    elif kind == "prompt":
                        color = _PROMPT_COLOR
                    elif kind == "info":
                        color = _INFO_COLOR
                    for line in text.splitlines() or [""]:
                        try:
                            dpg.add_text(
                                line, parent=self._output_tag, color=color,
                            )
                        except Exception:
                            pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory used by the editor shell — kept as a free function so the shell
# can wire the panel without importing the class name into its module
# namespace.
# ---------------------------------------------------------------------------


def make_repl_panel(app: Any = None, scene: Any = None) -> REPLPanel:
    """Return a fresh :class:`REPLPanel` bound to *app* / *scene*.

    Used by :class:`pharos_editor.ui.editor.shell.EditorShell` so the
    shell doesn't need to know about the panel's constructor signature.
    """
    return REPLPanel(app=app, scene=scene)


__all__ = ["REPLPanel", "TITLE", "make_repl_panel"]
