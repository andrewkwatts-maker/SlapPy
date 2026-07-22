"""``WGSLEditorPanel`` — live WGSL shader editor in the editor (EEE3).

The user's directive:

    "coding them in the editor via python bindings / having exposed
    functions"

This panel is the UI half of the shader hot-reload loop. It surfaces
every ``*.wgsl`` file under :mod:`pharos_engine.render.shaders` in a
dropdown, loads the source into a monospace multiline editor, and gives
the user a toolbar with **Compile**, **Save**, **Revert**, and
**Reload from disk** buttons. Compile errors surface in a coloured
output panel with line + column references parsed out of the wgpu
diagnostic string.

Design goals
------------

* **Headless-safe.** Every DPG call is guarded so pytest under a stub
  DPG module can build the panel and drive the buttons without a real
  GUI context.
* **Zero required deps.** wgpu is soft-imported through
  :mod:`pharos_engine.render.shader_hot_reload`; when it's missing the
  panel still renders and Save / Revert still work — the compile
  output just reads "wgpu unavailable".
* **Discoverable syntax highlight.** A tiny WGSL keyword highlighter
  paints ``@vertex`` / ``@fragment`` / ``@compute`` / ``fn`` / ``var`` /
  ``let`` / ``struct`` / ``if`` / ``else`` / ``return`` / ``for`` /
  ``while`` / ``switch`` / ``case`` / ``default`` in an accent colour
  by rendering a coloured preview line-by-line below the editor.
* **Bracket auto-complete.** Typing ``{`` or ``(`` inserts the matching
  closing bracket so the user can iterate on a struct without hunting
  for the paired brace.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from pharos_engine.render.shader_hot_reload import (
    CompileResult,
    ShaderHotReloader,
    get_default_reloader,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TITLE = "WGSL"

# Highlight palette — pulled from the notebook theme so the WGSL panel
# blends into the surrounding editor chrome.
_TOOLBAR_COLOR = (140, 180, 240)
_SUCCESS_COLOR = (120, 200, 140)
_ERROR_COLOR = (220, 90, 90)
_INFO_COLOR = (200, 210, 220)
_KEYWORD_COLOR = (200, 160, 240)
_ANNOT_COLOR = (240, 180, 120)

# The 15 WGSL tokens the highlighter recognises. Kept flat + explicit so
# the test suite can spot-check the recognised list without importing the
# entire highlighter state machine.
_WGSL_KEYWORDS = {
    "fn", "var", "let", "struct", "if", "else",
    "return", "for", "while", "switch", "case", "default",
}
_WGSL_ANNOTATIONS = {"@vertex", "@fragment", "@compute"}

# Editor sizing — 30 lines of monospace at DPG's default font is ~510 px.
_EDITOR_HEIGHT_PX = 510
_OUTPUT_HEIGHT_PX = 140


# ---------------------------------------------------------------------------
# DPG soft-access helper — every panel guards its DPG calls the same way.
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` if the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shader discovery — scans the bundled shader tree so the dropdown stays
# in sync with whatever a plugin might have dropped into the folder.
# ---------------------------------------------------------------------------


def _shaders_root() -> str:
    """Return the absolute path of the bundled WGSL shader directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(
        os.path.join(here, "..", "..", "render", "shaders"),
    )


def discover_wgsl_shaders(root: str | None = None) -> list[str]:
    """Return every ``*.wgsl`` path under *root* (default: bundled).

    Sorted alphabetically so the dropdown order is deterministic across
    OSes. Missing root → empty list (the panel renders the placeholder).
    """
    base = root or _shaders_root()
    if not os.path.isdir(base):
        return []
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            if name.lower().endswith(".wgsl"):
                out.append(os.path.abspath(os.path.join(dirpath, name)))
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Syntax highlight tokeniser — plain-Python, no regex over the whole file.
# ---------------------------------------------------------------------------


def tokenize_line(line: str) -> list[tuple[str, str]]:
    """Split *line* into ``(kind, text)`` tuples for coloured rendering.

    ``kind`` is one of ``"keyword"`` / ``"annotation"`` / ``"text"``.
    Whitespace is preserved so re-joining ``text`` reproduces *line*.
    Punctuation stays inside the ``"text"`` bucket — the panel only
    tints identifiers.
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        # Annotation runs — start with '@' and consume identifier chars.
        if ch == "@":
            j = i + 1
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            token = line[i:j]
            kind = "annotation" if token in _WGSL_ANNOTATIONS else "text"
            tokens.append((kind, token))
            i = j
            continue
        # Identifier runs — consume [A-Za-z_][A-Za-z0-9_]*.
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (line[j].isalnum() or line[j] == "_"):
                j += 1
            token = line[i:j]
            kind = "keyword" if token in _WGSL_KEYWORDS else "text"
            tokens.append((kind, token))
            i = j
            continue
        # Everything else — group by "not identifier / not @" runs.
        j = i + 1
        while j < n and not (
            line[j].isalpha() or line[j] == "_" or line[j] == "@"
        ):
            j += 1
        tokens.append(("text", line[i:j]))
        i = j
    return tokens


def highlight_source(source: str) -> list[list[tuple[str, str]]]:
    """Return one ``[tokens]`` list per line of *source*.

    Empty lines round-trip as ``[("text", "")]`` so the panel can still
    render the blank as a keep-place row.
    """
    lines = source.splitlines() or [""]
    return [tokenize_line(line) or [("text", "")] for line in lines]


def count_keywords(source: str) -> int:
    """Return the number of recognised WGSL keywords in *source*.

    Used by tests to spot-check the highlighter's coverage without
    walking the token list. Annotations (``@vertex`` etc.) count as
    keywords for this metric because they're both painted.
    """
    total = 0
    for line in highlight_source(source):
        for kind, _tok in line:
            if kind in ("keyword", "annotation"):
                total += 1
    return total


# ---------------------------------------------------------------------------
# Bracket auto-complete — inserts the matching close-bracket in-string.
# ---------------------------------------------------------------------------

_BRACKET_PAIRS = {"{": "}", "(": ")", "[": "]"}


def autocomplete_brackets(source: str) -> str:
    """Append the matching close-bracket for any unbalanced open at the tail.

    Used when the user types ``struct Foo {`` — hitting the auto-complete
    action closes the block on their behalf. Only inspects the trailing
    open bracket; a full brace-balancer would be overkill for the live
    edit use case.
    """
    if not source:
        return source
    tail = source[-1]
    if tail in _BRACKET_PAIRS:
        return source + _BRACKET_PAIRS[tail]
    return source


# ---------------------------------------------------------------------------
# WGSLEditorPanel
# ---------------------------------------------------------------------------


class WGSLEditorPanel:
    """DPG panel for editing WGSL live inside the editor.

    Attributes
    ----------
    reloader
        The :class:`ShaderHotReloader` this panel drives. Defaults to
        the process-wide singleton via :func:`get_default_reloader`.
    shader_paths
        Every discovered ``*.wgsl`` path — the dropdown source.
    current_path
        The path currently open in the editor. ``None`` before the
        first shader is picked.
    current_source
        The live buffer of the multiline editor.
    disk_source
        The version last read from disk — used by Revert.
    last_result
        The most recent :class:`CompileResult` — drives the output panel.
    output
        List of ``(kind, text)`` output rows: ``"success"`` / ``"error"``
        / ``"info"``. Tests read this directly.
    """

    TITLE = TITLE

    def __init__(
        self,
        reloader: ShaderHotReloader | None = None,
        *,
        shader_root: str | None = None,
        on_reload: Callable[[str, str], None] | None = None,
    ) -> None:
        self.reloader = reloader if reloader is not None else get_default_reloader()
        self._shader_root = shader_root or _shaders_root()
        self.shader_paths: list[str] = discover_wgsl_shaders(self._shader_root)

        self.current_path: str | None = None
        self.current_source: str = ""
        self.disk_source: str = ""
        self.last_result: CompileResult | None = None
        # Structured output rows — tests + the render loop both walk this.
        self.output: list[tuple[str, str]] = [
            ("info", "WGSL editor ready — pick a shader to begin."),
        ]

        # External per-path reload callback — the editor wires this to a
        # renderer's rebuild hook. Optional.
        self._external_on_reload = on_reload

        # DPG tag bookkeeping — unique per instance so multiple panels
        # can co-exist in a split layout.
        _uid = id(self)
        self._panel_tag = f"wgsl_panel_{_uid}"
        self._dropdown_tag = f"wgsl_dropdown_{_uid}"
        self._editor_tag = f"wgsl_editor_{_uid}"
        self._output_tag = f"wgsl_output_{_uid}"
        self._preview_tag = f"wgsl_preview_{_uid}"
        self._status_tag = f"wgsl_status_{_uid}"
        self._built = False

        # Auto-pick the first discovered shader so a freshly built panel
        # shows real content instead of the placeholder.
        if self.shader_paths:
            try:
                self._load_from_disk(self.shader_paths[0])
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Toolbar action count — the shell status bar surfaces this.
    # ------------------------------------------------------------------

    BUTTON_COUNT = 4  # Compile, Save, Revert, Reload from disk

    # ------------------------------------------------------------------
    # Panel protocol — build(parent_tag) matches every sibling panel.
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the WGSL editor under *parent_tag* (DPG protocol)."""
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                # ── Toolbar row ------------------------------------------------
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="Compile",
                            callback=self._on_compile_clicked,
                            tag=f"{self._panel_tag}_btn_compile",
                        )
                        dpg.add_button(
                            label="Save",
                            callback=self._on_save_clicked,
                            tag=f"{self._panel_tag}_btn_save",
                        )
                        dpg.add_button(
                            label="Revert",
                            callback=self._on_revert_clicked,
                            tag=f"{self._panel_tag}_btn_revert",
                        )
                        dpg.add_button(
                            label="Reload from disk",
                            callback=self._on_reload_clicked,
                            tag=f"{self._panel_tag}_btn_reload",
                        )
                        dpg.add_text(
                            self._status_text(),
                            tag=self._status_tag,
                            color=_INFO_COLOR,
                        )
                except Exception:
                    pass

                # ── Shader picker dropdown ------------------------------------
                labels = [self._short_label(p) for p in self.shader_paths]
                default_label = (
                    self._short_label(self.current_path)
                    if self.current_path else (labels[0] if labels else "")
                )
                try:
                    dpg.add_combo(
                        items=labels,
                        default_value=default_label,
                        label="Shader",
                        callback=self._on_dropdown_change,
                        tag=self._dropdown_tag,
                    )
                except Exception:
                    pass

                # ── Multiline WGSL editor -------------------------------------
                try:
                    dpg.add_input_text(
                        multiline=True,
                        default_value=self.current_source,
                        width=-1,
                        height=_EDITOR_HEIGHT_PX,
                        callback=self._on_editor_change,
                        tag=self._editor_tag,
                    )
                except Exception:
                    pass

                # ── Highlight preview (coloured line-by-line) -----------------
                try:
                    dpg.add_child_window(
                        tag=self._preview_tag,
                        width=-1,
                        height=180,
                        border=True,
                    )
                except Exception:
                    pass

                # ── Compile output panel --------------------------------------
                try:
                    dpg.add_child_window(
                        tag=self._output_tag,
                        width=-1,
                        height=_OUTPUT_HEIGHT_PX,
                        border=True,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        self._flush_preview_to_dpg()
        self._flush_output_to_dpg()

    # ------------------------------------------------------------------
    # Toolbar / dropdown callbacks
    # ------------------------------------------------------------------

    def _on_compile_clicked(self, *_a: Any, **_kw: Any) -> None:
        """Compile the live buffer and dispatch to the hot-reloader."""
        self._sync_editor_from_dpg()
        self.compile()

    def _on_save_clicked(self, *_a: Any, **_kw: Any) -> None:
        """Persist the live buffer to disk without recompiling."""
        self._sync_editor_from_dpg()
        self.save()

    def _on_revert_clicked(self, *_a: Any, **_kw: Any) -> None:
        """Reset the editor buffer back to the last on-disk snapshot."""
        self.revert()

    def _on_reload_clicked(self, *_a: Any, **_kw: Any) -> None:
        """Re-read the current shader from disk (in case an external editor wrote)."""
        if self.current_path is None:
            return
        self._load_from_disk(self.current_path)
        self._push_editor_to_dpg()
        self.output.append(
            ("info", f"reloaded {os.path.basename(self.current_path)} from disk"),
        )
        self._flush_output_to_dpg()

    def _on_dropdown_change(self, _sender: Any = None, value: Any = None) -> None:
        """Dropdown selection changed — load that shader into the editor."""
        if value is None:
            return
        # ``value`` is the short label; map it back to the absolute path.
        for path in self.shader_paths:
            if self._short_label(path) == value:
                self._load_from_disk(path)
                self._push_editor_to_dpg()
                return

    def _on_editor_change(self, _sender: Any = None, value: Any = None) -> None:
        """Editor text changed — mirror to :attr:`current_source` + refresh preview.

        Also runs bracket auto-complete when the user just typed an open
        brace so the closing brace appears without a second keystroke.
        """
        if value is None:
            return
        completed = autocomplete_brackets(str(value))
        if completed != value:
            # Push the auto-completed source back into the editor so the
            # user sees the pair land immediately.
            self.current_source = completed
            self._push_editor_to_dpg()
        else:
            self.current_source = str(value)
        self._flush_preview_to_dpg()

    # ------------------------------------------------------------------
    # Public actions — callable from the REPL too.
    # ------------------------------------------------------------------

    def compile(self) -> CompileResult:
        """Validate + hot-reload the current buffer. Returns the result.

        Also emits the outcome into :attr:`output` so the DPG output
        panel repaints. Callable from the REPL for scripted testing.
        """
        if self.current_path is None:
            result = CompileResult(
                ok=False,
                message="no shader selected",
                errors=[],
                validated=False,
            )
            self.last_result = result
            self.output.append(("error", result.message))
            self._flush_output_to_dpg()
            self._push_status_to_dpg()
            return result
        # Auto-register the current shader so the callback fires even if
        # the caller never called :meth:`bind`.
        if self.current_path not in self.reloader.registered_paths():
            self.reloader.register(self.current_path, self._on_reload_source)
        result = self.reloader.recompile(self.current_path, self.current_source)
        self.last_result = result
        latency_ms = self.reloader.last_latency_s * 1000.0
        if result.ok:
            self.output.append(
                ("success", f"compiled OK in {latency_ms:.2f} ms"),
            )
        else:
            head = result.message.splitlines()[0] if result.message else "compile failed"
            self.output.append(("error", head))
            for err in result.errors[:16]:
                self.output.append(("error", "  " + err.format()))
        self._flush_output_to_dpg()
        self._push_status_to_dpg()
        return result

    def save(self) -> str | None:
        """Write the live buffer to :attr:`current_path`. Returns the path."""
        if self.current_path is None:
            self.output.append(("error", "no shader selected — nothing to save"))
            self._flush_output_to_dpg()
            return None
        try:
            with open(self.current_path, "w", encoding="utf-8") as fh:
                fh.write(self.current_source)
            self.disk_source = self.current_source
            self.output.append(
                ("info", f"saved {os.path.basename(self.current_path)}"),
            )
            self._flush_output_to_dpg()
            return self.current_path
        except OSError as e:
            self.output.append(("error", f"save failed: {e!r}"))
            self._flush_output_to_dpg()
            return None

    def revert(self) -> None:
        """Drop the live buffer back to :attr:`disk_source`."""
        self.current_source = self.disk_source
        self._push_editor_to_dpg()
        self.output.append(("info", "reverted to disk"))
        self._flush_output_to_dpg()

    def bind_reload_callback(self, callback: Callable[[str, str], None]) -> None:
        """Wire an external ``on_reload(path, source)`` callback.

        Used by the editor shell to hand the panel a renderer-side hook
        so a recompiled shader rebuilds the running pipeline. Optional.
        """
        self._external_on_reload = callback

    # ------------------------------------------------------------------
    # Tick — called from the shell tick to drive mtime polling.
    # ------------------------------------------------------------------

    def tick(self, dt: float = 1.0 / 60.0) -> None:
        """Advance the mtime poll clock; run :meth:`reloader.watch` at ~1 Hz."""
        self._tick_accum = getattr(self, "_tick_accum", 0.0) + float(dt)
        if self._tick_accum < 1.0:
            return
        self._tick_accum = 0.0
        try:
            reloaded = self.reloader.watch()
        except Exception:
            return
        if reloaded:
            for path in reloaded:
                self.output.append(
                    ("info", f"hot-reloaded {os.path.basename(path)} from disk"),
                )
            self._flush_output_to_dpg()

    # ------------------------------------------------------------------
    # Internal — disk IO + DPG plumbing.
    # ------------------------------------------------------------------

    def _load_from_disk(self, path: str) -> None:
        """Read *path* off disk into :attr:`current_source` + :attr:`disk_source`."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            source = ""
        self.current_path = os.path.abspath(path)
        self.current_source = source
        self.disk_source = source

    def _on_reload_source(self, new_source: str) -> None:
        """Reloader callback — keep the local buffer in sync + notify external hook."""
        self.current_source = new_source
        if self._external_on_reload is not None and self.current_path is not None:
            try:
                self._external_on_reload(self.current_path, new_source)
            except Exception:
                pass

    def _short_label(self, path: str | None) -> str:
        if path is None:
            return ""
        root = self._shader_root
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            rel = os.path.basename(path)
        return rel.replace("\\", "/")

    def _status_text(self) -> str:
        name = (
            os.path.basename(self.current_path)
            if self.current_path else "(no shader)"
        )
        if self.last_result is None:
            return f"{name}"
        if self.last_result.ok:
            return f"{name} — OK"
        return f"{name} — errors"

    def _sync_editor_from_dpg(self) -> None:
        """Pull the live text out of DPG's input widget."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            value = dpg.get_value(self._editor_tag)
            if value is not None:
                self.current_source = str(value)
        except Exception:
            pass

    def _push_editor_to_dpg(self) -> None:
        """Write :attr:`current_source` back into the DPG input widget."""
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._editor_tag):
                dpg.set_value(self._editor_tag, self.current_source)
        except Exception:
            pass
        self._flush_preview_to_dpg()

    def _push_status_to_dpg(self) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._status_tag):
                dpg.set_value(self._status_tag, self._status_text())
        except Exception:
            pass

    def _flush_preview_to_dpg(self) -> None:
        """Rebuild the coloured preview child window from :attr:`current_source`."""
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if not dpg.does_item_exist(self._preview_tag):
                return
            try:
                dpg.delete_item(self._preview_tag, children_only=True)
            except Exception:
                pass
            # Cap preview at the first 60 lines to keep the redraw cheap.
            highlighted = highlight_source(self.current_source)[:60]
            for tokens in highlighted:
                try:
                    with dpg.group(horizontal=True, parent=self._preview_tag):
                        for kind, text in tokens:
                            if not text:
                                continue
                            color = _INFO_COLOR
                            if kind == "keyword":
                                color = _KEYWORD_COLOR
                            elif kind == "annotation":
                                color = _ANNOT_COLOR
                            try:
                                dpg.add_text(text, color=color)
                            except Exception:
                                pass
                except Exception:
                    # Stub DPG that lacks group context managers → append
                    # a flat line instead.
                    text = "".join(t for _k, t in tokens)
                    try:
                        dpg.add_text(text, parent=self._preview_tag)
                    except Exception:
                        pass
        except Exception:
            pass

    def _flush_output_to_dpg(self) -> None:
        """Repaint the compile output panel from :attr:`output`."""
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if not dpg.does_item_exist(self._output_tag):
                return
            try:
                dpg.delete_item(self._output_tag, children_only=True)
            except Exception:
                pass
            for kind, text in self.output[-40:]:
                color = _INFO_COLOR
                if kind == "success":
                    color = _SUCCESS_COLOR
                elif kind == "error":
                    color = _ERROR_COLOR
                for line in (text.splitlines() or [""]):
                    try:
                        dpg.add_text(line, parent=self._output_tag, color=color)
                    except Exception:
                        pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory used by the editor shell — kept as a free function so the shell
# doesn't need to import the class name into its module namespace.
# ---------------------------------------------------------------------------


def make_wgsl_panel(
    reloader: ShaderHotReloader | None = None,
    *,
    shader_root: str | None = None,
) -> WGSLEditorPanel:
    """Return a fresh :class:`WGSLEditorPanel` bound to *reloader*."""
    return WGSLEditorPanel(reloader=reloader, shader_root=shader_root)


__all__ = [
    "WGSLEditorPanel",
    "TITLE",
    "make_wgsl_panel",
    "discover_wgsl_shaders",
    "tokenize_line",
    "highlight_source",
    "count_keywords",
    "autocomplete_brackets",
]
