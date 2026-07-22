"""``NotebookDiaryPage`` — diary-page script editor.

A two-column editor presented as a diary page laid flat: the LEFT page is
a live viewport (rendering the user's script via a small
:class:`pharos_engine.studio.Stage`) and the RIGHT page is the script
source — either Python (multiline text input) or a placeholder Visual
Nodes pane.

Layout sketch::

    ┌──── [washi tape: script_name.diary.py] ──── [♡] [✿] ────────┐
    │  ┌──────────────────────┐  ┌─────────────────────────────┐  │
    │  │                      │  │ # Dear diary…               │  │
    │  │     LIVE VIEWPORT    │  │ def update(dt):              │  │
    │  │      (script's       │  │     for body in scene.bodies:│  │
    │  │       output)        │  │         body.position[1] += │  │
    │  │                      │  │     # sketch here            │  │
    │  └──────────────────────┘  └─────────────────────────────┘  │
    │  [♡ Run]  [✿ Stop]   ◇ Python │ Nodes   [💖 Save]  [Open…]   │
    └──────────────────────────────────────────────────────────────┘

Design provenance
-----------------

* ``docs/ui_pattern_audit_2026_06_03.md`` — diary-page reskin family.
* ``docs/theme_teengirl_notebook_2026_06_03.md`` — palette + typography
  for the washi-tape title strip, ruled-paper background, sticker glyphs.
* ``python/pharos_engine/ui/editor/notebook_code_panel.py`` — sibling
  diary-styled panel; the soft-DPG / call-log / theme-listener
  contracts are mirrored here.
* ``python/pharos_engine/ui/editor/notebook_inspector.py`` — field-journal
  styling reference (washi-tape sections, sticker glyphs).

Headless / soft-import contract
-------------------------------

* :class:`pharos_engine.studio.Stage` is imported lazily inside
  :meth:`run_script`. If the import fails (missing optional extras) the
  panel reports a soft status hint and the viewport remains a blank
  placeholder.
* Every ``dpg.*`` call is wrapped in ``try/except`` so the panel still
  registers its tags and call-log entries when ``dearpygui`` is missing
  or stubbed (used by the test-suite).
* Companion ``.diary.meta.yaml`` files are read/written best-effort —
  YAML errors don't break the panel.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import validate_non_empty_str

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — placeholder copy, button labels, status messages
# ---------------------------------------------------------------------------

PYTHON_MODE = "python"
NODES_MODE = "nodes"
_VALID_MODES = (PYTHON_MODE, NODES_MODE)

_PLACEHOLDER_CODE = (
    "# Dear diary...\n"
    "# Write some code...\n"
    "#\n"
    "# def setup():\n"
    "#     pass\n"
    "#\n"
    "# def update(dt):\n"
    "#     # sketch here\n"
    "#     pass\n"
)

_PLACEHOLDER_HINT = "# Dear diary..."

_NODES_PLACEHOLDER = "Visual nodes coming soon (see P4 sprint)"
_NODES_GENERATE_LABEL = "Generate Python from nodes"

_STUDIO_MISSING_HINT = (
    "pharos_engine.studio.Stage unavailable - viewport idle."
)
_VIEWPORT_ERROR_HINT = "x your script needs care - see status bar"
_DEFAULT_STATUS = "Ready"

# Footer button labels — soft hearts/flowers to keep the diary mood.
_BTN_RUN = "Run"
_BTN_STOP = "Stop"
_BTN_SAVE = "Save"
_BTN_OPEN = "Open..."
_BTN_TOGGLE_PYTHON = "Python | Nodes"

# Default diary path used when the panel is created without a target file.
_UNTITLED_NAME = "untitled.diary.py"

# Theme tokens — the panel reads these at build time so the theme swap
# can re-render with the new colours via :meth:`refresh_theme`.
_PAPER_COLOR = (251, 247, 236, 255)        # cream
_INK_COLOR = (31, 47, 102, 255)            # ink navy
_WASHI_COLOR = (255, 111, 181, 255)        # bubblegum pink
_MUTED_COLOR = (122, 118, 137, 255)        # muted body
_ACCENT_COLOR = (255, 224, 102, 255)       # highlighter yellow


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


def _try_import_studio() -> Any | None:
    """Return ``pharos_engine.studio`` or ``None`` on import error.

    Imported lazily so the editor still loads in minimum-dependency
    environments. The panel falls back to an idle viewport when the
    studio module isn't importable.
    """
    try:
        from pharos_engine import studio  # noqa: WPS433

        return studio
    except Exception:
        return None


def _meta_path_for(diary_path: Path) -> Path:
    """Return the companion ``.diary.meta.yaml`` path next to *diary_path*.

    Strips one trailing ``.py`` so ``foo.diary.py`` -> ``foo.diary.meta.yaml``
    (keeping the ``.diary`` infix as a discriminator).
    """
    name = diary_path.name
    if name.endswith(".diary.py"):
        stem = name[: -len(".diary.py")]
        return diary_path.with_name(f"{stem}.diary.meta.yaml")
    # Generic ``.py`` (or other) - append the meta suffix.
    return diary_path.with_name(diary_path.stem + ".diary.meta.yaml")


def _load_meta(meta_path: Path) -> dict[str, Any]:
    """Best-effort YAML load — returns ``{}`` on any error.

    Uses ``yaml.safe_load`` when PyYAML is available; falls back to a
    one-key-per-line parser otherwise. Either way, malformed meta files
    never crash the panel.
    """
    if not meta_path.exists():
        return {}
    try:
        try:
            import yaml  # type: ignore[import-not-found]

            raw = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            # Naive fallback parser - "key: value" lines only.
            out: dict[str, Any] = {}
            for line in meta_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip().strip('"').strip("'")
            return out
    except Exception:
        return {}


def _write_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    """Best-effort YAML write — silent on failure."""
    try:
        try:
            import yaml  # type: ignore[import-not-found]

            text = yaml.safe_dump(meta, sort_keys=True)
        except Exception:
            text = "\n".join(f"{k}: {v}" for k, v in sorted(meta.items())) + "\n"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(text, encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# NotebookDiaryPage
# ---------------------------------------------------------------------------


class NotebookDiaryPage:
    """A diary-page script editor.

    Opens like a personal-diary page laid flat: a washi-tape title strip
    at the top, a 2-column body (LEFT = live viewport, RIGHT = Python
    text or Visual Nodes placeholder), and a footer ribbon of action
    buttons (Run / Stop / mode toggle / Save / Open).

    Per Nova3D's ``build(parent_tag)`` protocol — every ``dpg.*`` call
    is guarded so the panel constructs cleanly in headless tests.

    Parameters
    ----------
    engine:
        Optional engine handle. When the engine exposes ``run_script``
        / ``stop_script`` hooks, :meth:`run_script` / :meth:`stop_script`
        forward to them; otherwise both methods do their own light-weight
        Stage lifecycle.
    on_save:
        Optional ``(path, source) -> None`` callback fired when
        :meth:`save` persists a diary file. The editor shell wires this
        so it can refresh the content browser.
    """

    TITLE = "Diary"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 720
    MIN_HEIGHT: int = 440

    def __init__(
        self,
        engine: Any = None,
        on_save: Callable[[Path, str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._on_save = on_save

        # Per-file source buffers — keyed by path so the toggle preserves
        # both Python and Nodes content as the user flips modes.
        self._sources: dict[Path, str] = {}
        self._node_sources: dict[Path, str] = {}
        self._modes: dict[Path, str] = {}

        # Live state.
        self._active_path: Path | None = None
        self._mode: str = PYTHON_MODE
        self._status: str = _DEFAULT_STATUS
        self._last_exception: BaseException | None = None
        self._stage: Any | None = None
        self._script_running: bool = False
        self._frame: int = 0

        # DPG tag names — stable across rebuilds so refresh() can target.
        oid = id(self)
        self._panel_tag = f"notebook_diary_{oid}"
        self._title_tag = f"{self._panel_tag}_title"
        self._tape_tag = f"{self._panel_tag}_tape"
        self._heart_tag = f"{self._panel_tag}_heart"
        self._flower_tag = f"{self._panel_tag}_flower"
        self._body_tag = f"{self._panel_tag}_body"
        self._viewport_pane_tag = f"{self._panel_tag}_viewport"
        self._viewport_canvas_tag = f"{self._panel_tag}_viewport_canvas"
        self._viewport_layer_tag = f"{self._panel_tag}_viewport_layer"
        self._viewport_error_tag = f"{self._panel_tag}_viewport_error"
        self._code_pane_tag = f"{self._panel_tag}_code"
        self._code_input_tag = f"{self._panel_tag}_code_input"
        self._nodes_pane_tag = f"{self._panel_tag}_nodes"
        self._nodes_placeholder_tag = f"{self._panel_tag}_nodes_placeholder"
        self._nodes_generate_tag = f"{self._panel_tag}_nodes_generate"
        self._footer_tag = f"{self._panel_tag}_footer"
        self._toggle_tag = f"{self._panel_tag}_toggle"
        self._status_tag = f"{self._panel_tag}_status"

        # Build lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Theme cache — re-pulled on refresh_theme().
        self._paper_color = _PAPER_COLOR
        self._ink_color = _INK_COLOR
        self._washi_color = _WASHI_COLOR
        self._muted_color = _MUTED_COLOR
        self._accent_color = _ACCENT_COLOR

        # Call log for headless test assertions.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_path(self) -> Path | None:
        """Return the currently bound diary path (or ``None``)."""
        return self._active_path

    def get_source(self) -> str:
        """Return the current source for the active mode."""
        if self._active_path is None:
            return ""
        if self._mode == NODES_MODE:
            return self._node_sources.get(self._active_path, "")
        return self._sources.get(self._active_path, "")

    def set_source(self, source: str) -> bool:
        """Set the source for the current mode + active path.

        Returns
        -------
        bool
            ``True`` when the buffer was stored.

        Raises
        ------
        TypeError
            If *source* is not a ``str``.
        """
        if not isinstance(source, str):
            raise TypeError(
                f"NotebookDiaryPage.set_source: source must be str; "
                f"got {type(source).__name__}",
            )
        if self._active_path is None:
            # Promote the untitled placeholder so the buffer is captured.
            self._active_path = Path(_UNTITLED_NAME)
            self._modes.setdefault(self._active_path, self._mode)
        if self._mode == NODES_MODE:
            self._node_sources[self._active_path] = source
        else:
            self._sources[self._active_path] = source
        self.call_log.append(("set_source", len(source)))
        self._sync_inputs_to_dpg()
        return True

    def get_mode(self) -> str:
        """Return the current mode — ``"python"`` or ``"nodes"``."""
        return self._mode

    def set_mode(self, mode: str) -> bool:
        """Switch the right pane between Python and Nodes.

        Source for each mode is preserved per file so the user can
        flip back and forth without losing work.

        Returns
        -------
        bool
            ``True`` when the mode was toggled, ``False`` when the
            request matched the current mode (idempotent short-circuit).

        Raises
        ------
        ValueError
            If *mode* isn't one of the known modes.
        TypeError
            If *mode* isn't a ``str``.
        """
        if not isinstance(mode, str):
            raise TypeError(
                f"NotebookDiaryPage.set_mode: mode must be str; "
                f"got {type(mode).__name__}",
            )
        if mode not in _VALID_MODES:
            raise ValueError(
                f"NotebookDiaryPage.set_mode: mode must be one of "
                f"{_VALID_MODES}; got {mode!r}",
            )
        if mode == self._mode:
            return False
        self._mode = mode
        if self._active_path is not None:
            self._modes[self._active_path] = mode
        self.call_log.append(("set_mode", mode))
        self._refresh_mode_visibility()
        return True

    def _validate_state(self) -> bool:
        """Verify the diary page's active-path + mode + buffer maps are sane.

        Raises
        ------
        RuntimeError
            When the current mode is unknown or the active path is
            registered without a buffer entry.
        """
        if self._mode not in _VALID_MODES:
            raise RuntimeError(
                "NotebookDiaryPage._validate_state: mode "
                f"{self._mode!r} is not one of {_VALID_MODES}"
            )
        if self._active_path is not None:
            if (
                self._active_path not in self._sources
                and self._active_path not in self._node_sources
            ):
                raise RuntimeError(
                    "NotebookDiaryPage._validate_state: active_path "
                    f"{self._active_path} has no buffer entry"
                )
        return True

    @property
    def status(self) -> str:
        """Return the current status message."""
        return self._status

    @property
    def last_exception(self) -> BaseException | None:
        """Return the last exception raised by the running script (if any)."""
        return self._last_exception

    @property
    def stage(self) -> Any | None:
        """Return the underlying :class:`Stage`, if one has been spun up."""
        return self._stage

    def open_diary(self, path: Path | str) -> bool:
        """Load the .py source + companion .meta.yaml for *path*.

        The path is canonicalised but never required to exist on disk —
        a missing file simply opens a blank scaffold so "New Diary"
        works without disk writes.

        Returns
        -------
        bool
            ``True`` when the diary was opened. Read errors are logged
            and the panel still swaps to a blank scaffold.

        Raises
        ------
        TypeError
            If *path* is not a ``str`` or :class:`Path`.
        ValueError
            If *path* is an empty string.
        """
        if isinstance(path, bool) or not isinstance(path, (str, Path)):
            raise TypeError(
                "NotebookDiaryPage.open_diary: path must be str or Path; "
                f"got {type(path).__name__}"
            )
        if isinstance(path, str) and not path:
            raise ValueError(
                "NotebookDiaryPage.open_diary: path must not be empty"
            )
        p = Path(path)
        self._active_path = p
        self.call_log.append(("open_diary", str(p)))

        # Load source from disk (best-effort).
        try:
            source = p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception as exc:
            _LOG.warning(
                "NotebookDiaryPage.open_diary: read(%s) raised %s: %s",
                p, type(exc).__name__, exc,
            )
            source = ""
        if not source:
            source = _PLACEHOLDER_CODE
        self._sources[p] = source

        # Load companion meta.yaml — pick last mode + status.
        meta = _load_meta(_meta_path_for(p))
        last_mode = str(meta.get("last_mode", PYTHON_MODE))
        if last_mode not in _VALID_MODES:
            last_mode = PYTHON_MODE
        self._mode = last_mode
        self._modes[p] = last_mode

        # Pre-seed a node-source buffer so the toggle has somewhere to write.
        self._node_sources.setdefault(p, "")

        self._set_status(f"Opened: {p.name}")
        self._sync_inputs_to_dpg()
        self._refresh_mode_visibility()
        return True

    def run_script(self) -> bool:
        """Spin up (or reuse) a Stage + bind the source as ``update_fn``.

        When the engine exposes a ``run_script(panel)`` hook, this
        forwards to it. Otherwise we soft-import
        :class:`pharos_engine.studio.Stage`, wrap the diary source in a
        callable, and start ticking it from :meth:`tick`.

        Returns
        -------
        bool
            ``True`` when the script is now live-running; ``False``
            when the studio extra is missing, the source failed to
            compile, or an engine hook raised (all cases are logged
            and reflected in the status bar).
        """
        self.call_log.append(("run_script",))

        # Engine override — preferred path.
        if self._engine is not None:
            hook = getattr(self._engine, "run_script", None)
            if callable(hook):
                try:
                    hook(self)
                    self._script_running = True
                    self._set_status("Running (engine)")
                    return True
                except Exception as exc:
                    _LOG.warning(
                        "NotebookDiaryPage.run_script: engine hook raised "
                        "%s: %s",
                        type(exc).__name__, exc,
                    )
                    self._record_exception(exc)
                    return False

        studio = _try_import_studio()
        if studio is None:
            _LOG.warning(
                "NotebookDiaryPage.run_script: pharos_engine.studio missing"
            )
            self._set_status(_STUDIO_MISSING_HINT)
            return False

        # Compile + extract update_fn from the source.
        source = self.get_source()
        if self._mode == NODES_MODE:
            self._set_status("Nodes mode - run not yet wired")
            return False
        try:
            ns: dict[str, Any] = {}
            code = compile(source, str(self._active_path or "<diary>"), "exec")
            exec(code, ns)  # noqa: S102 - intentional sandbox-light
        except Exception as exc:
            self._record_exception(exc)
            return False

        # Build a Stage — softbody_stage is the lightest viable default.
        try:
            self._stage = studio.softbody_stage()
        except Exception as exc:
            self._record_exception(exc)
            return False

        setup_fn = ns.get("setup")
        if callable(setup_fn):
            try:
                setup_fn()
            except Exception as exc:
                self._record_exception(exc)
                return False

        self._update_fn = ns.get("update")
        self._script_running = True
        self._last_exception = None
        self._set_status("Running")
        return True

    def stop_script(self) -> bool:
        """Tear down the running stage + clear the live viewport.

        Forwards to ``engine.stop_script`` when available; otherwise
        drops the local Stage handle and resets the running flag.

        Returns
        -------
        bool
            ``True`` when a running script was stopped; ``False`` when
            there was nothing running to stop.
        """
        self.call_log.append(("stop_script",))
        was_running = self._script_running
        if self._engine is not None:
            hook = getattr(self._engine, "stop_script", None)
            if callable(hook):
                try:
                    hook(self)
                except Exception as exc:
                    _LOG.warning(
                        "NotebookDiaryPage.stop_script: engine hook "
                        "raised %s: %s",
                        type(exc).__name__, exc,
                    )
        self._script_running = False
        # Allow a teardown() hook to run for clean stop.
        teardown = getattr(self, "_update_fn", None)
        if teardown is None:
            teardown = None
        self._update_fn = None
        self._stage = None
        self._frame = 0
        self._set_status("Stopped")
        return was_running

    def tick(self, dt: float = 1.0 / 60.0) -> None:
        """Per-frame tick driven by the editor main loop.

        Steps the bound Stage one substep and dispatches the user's
        ``update(dt)`` function. Exceptions are caught + routed to the
        status bar.
        """
        if not self._script_running or self._stage is None:
            return
        update = getattr(self, "_update_fn", None)
        try:
            if callable(update):
                update(dt)
            # Tick the Stage's primary world the same way studio.record does.
            stage = self._stage
            if stage.softbody is not None:
                from pharos_engine.softbody import step as softbody_step
                softbody_step(stage.softbody)
        except Exception as exc:
            self._record_exception(exc)
            return
        self._frame += 1

    def save(self) -> bool:
        """Write the current source + meta.yaml back to disk.

        Triggers the optional ``on_save`` callback so the editor shell
        can refresh views (content browser, recent files, …).

        Returns
        -------
        bool
            ``True`` when the file was written; ``False`` when there's
            no active diary bound or the write raised (warning logged;
            status bar carries the error message for the user).
        """
        self.call_log.append(("save",))
        if self._active_path is None:
            _LOG.warning(
                "NotebookDiaryPage.save: no active diary bound; nothing "
                "to write"
            )
            self._set_status("Save: no active diary")
            return False
        path = self._active_path
        source = self.get_source()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        except Exception as exc:
            _LOG.warning(
                "NotebookDiaryPage.save: write(%s) raised %s: %s",
                path, type(exc).__name__, exc,
            )
            self._set_status(f"Save error: {exc}")
            return False
        # Update companion meta.
        meta = _load_meta(_meta_path_for(path))
        meta["last_mode"] = self._mode
        meta["last_run_state"] = "running" if self._script_running else "idle"
        _write_meta(_meta_path_for(path), meta)
        self._set_status(f"Saved: {path.name}")
        if self._on_save is not None:
            try:
                self._on_save(path, source)
            except Exception as exc:
                _LOG.warning(
                    "NotebookDiaryPage.save: on_save callback raised "
                    "%s: %s",
                    type(exc).__name__, exc,
                )
        return True

    def refresh_theme(self) -> bool:
        """Re-pull theme colours after a theme switch.

        The new diary palette is read from the active theme via the
        widget ``_theme`` resolver; falls back to the cream/ink/pink
        defaults when no theme is bound.

        Returns
        -------
        bool
            ``True`` when a live theme was resolved and colours were
            refreshed; ``False`` when the resolver raised (defaults
            preserved). Either way, the status bar is re-emitted so
            listeners observe the swap.
        """
        self.call_log.append(("refresh_theme",))
        ok = True
        try:
            from pharos_engine.ui.theme import resolve_theme

            theme = resolve_theme()
            self._paper_color = theme.color("surface", self._paper_color)
            self._ink_color = theme.color("on_surface", self._ink_color)
            self._washi_color = theme.color("primary", self._washi_color)
            self._muted_color = theme.color(
                "text_secondary", self._muted_color,
            )
            self._accent_color = theme.color("accent", self._accent_color)
        except Exception as exc:
            _LOG.warning(
                "NotebookDiaryPage.refresh_theme: resolve_theme raised "
                "%s: %s",
                type(exc).__name__, exc,
            )
            ok = False
        # Re-emit the status so any listener observes the swap.
        self._set_status(self._status)
        return ok

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> bool:
        """Materialise the panel under *parent_tag* (DPG protocol).

        Layout:

        1. Washi-tape title strip (file name + heart/flower stickers).
        2. Two-column body — LEFT viewport, RIGHT code/nodes pane.
        3. Footer ribbon: Run / Stop / mode toggle / Save / Open.
        4. Status row at the bottom.

        Returns
        -------
        bool
            ``True`` once the panel is marked built (headless-safe).

        Raises
        ------
        TypeError
            If *parent_tag* is not a ``str`` or ``int``.
        ValueError
            If *parent_tag* is an empty ``str``.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookDiaryPage.build", parent_tag,
            )
        elif not isinstance(parent_tag, int):
            raise TypeError(
                "NotebookDiaryPage.build: parent_tag must be str or int; "
                f"got {type(parent_tag).__name__}"
            )
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return True

        try:
            with dpg.group(parent=parent_tag, tag=self._panel_tag):
                self._build_title_strip(dpg)
                self._build_body(dpg)
                self._build_footer(dpg)
                self._build_status(dpg)
        except Exception:
            # Stub DPG / no context-manager support — flat fallback path.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag, tag=self._panel_tag)
            except Exception:
                pass
            self._build_title_strip(dpg)
            self._build_body(dpg)
            self._build_footer(dpg)
            self._build_status(dpg)

        # Sync mode visibility once at the end — both panes were just built.
        self._refresh_mode_visibility()
        return True

    # ------------------------------------------------------------------
    # Build helpers — title strip
    # ------------------------------------------------------------------

    def _build_title_strip(self, dpg: Any) -> None:
        """Washi-tape strip + filename + heart/flower sticker glyphs."""
        title = (
            self._active_path.name
            if self._active_path is not None
            else _UNTITLED_NAME
        )
        try:
            with dpg.group(
                horizontal=True,
                parent=self._panel_tag,
                tag=self._tape_tag,
            ):
                # Washi-tape strip — ASCII stand-in; theme paints over.
                try:
                    dpg.add_text(
                        "=== === ===",
                        color=list(self._washi_color),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_text(
                        title,
                        tag=self._title_tag,
                        color=list(self._ink_color),
                    )
                except Exception:
                    pass
                # Heart + flower stickers on the right.
                try:
                    dpg.add_text(
                        "[heart]",
                        tag=self._heart_tag,
                        color=list(self._washi_color),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_text(
                        "[flower]",
                        tag=self._flower_tag,
                        color=list(self._accent_color),
                    )
                except Exception:
                    pass
        except Exception:
            # Flat fallback — register the tag so tests still observe it.
            try:
                dpg.add_text(
                    f"=== {title} === [heart] [flower]",
                    parent=self._panel_tag,
                    tag=self._tape_tag,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Build helpers — body (viewport + code/nodes)
    # ------------------------------------------------------------------

    def _build_body(self, dpg: Any) -> None:
        """Two-column body: viewport on the left, source on the right."""
        pane_w = 360
        pane_h = 320
        try:
            with dpg.group(
                horizontal=True,
                parent=self._panel_tag,
                tag=self._body_tag,
            ):
                self._build_viewport_pane(dpg, pane_w, pane_h)
                self._build_code_pane(dpg, pane_w, pane_h)
                self._build_nodes_pane(dpg, pane_w, pane_h)
        except Exception:
            self._build_viewport_pane(dpg, pane_w, pane_h)
            self._build_code_pane(dpg, pane_w, pane_h)
            self._build_nodes_pane(dpg, pane_w, pane_h)

    def _build_viewport_pane(self, dpg: Any, pane_w: int, pane_h: int) -> None:
        """Left page: live viewport canvas (ruled-paper background)."""
        try:
            with dpg.child_window(
                width=pane_w,
                height=pane_h,
                border=True,
                parent=self._body_tag,
                tag=self._viewport_pane_tag,
            ):
                # Ruled-paper hint — the theme paints the actual rules.
                try:
                    dpg.add_text(
                        "ruled paper :: viewport",
                        color=list(self._muted_color),
                    )
                except Exception:
                    pass
                # Drawlist canvas — viewport texture target.
                try:
                    dpg.add_drawlist(
                        width=pane_w - 16,
                        height=pane_h - 64,
                        tag=self._viewport_canvas_tag,
                    )
                except Exception:
                    pass
                # Draw-layer group bound to the canvas (lazy — only when
                # the canvas was successfully created).
                try:
                    dpg.add_draw_layer(
                        parent=self._viewport_canvas_tag,
                        tag=self._viewport_layer_tag,
                    )
                except Exception:
                    pass
                # Soft viewport-error overlay — hidden until a script
                # raises. The status bar carries the actual exception.
                try:
                    dpg.add_text(
                        _VIEWPORT_ERROR_HINT,
                        tag=self._viewport_error_tag,
                        color=list(self._washi_color),
                        show=False,
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG flat path — register tags so tests can find them.
            try:
                dpg.add_text(
                    "viewport",
                    parent=self._panel_tag,
                    tag=self._viewport_pane_tag,
                )
            except Exception:
                pass
            try:
                dpg.add_drawlist(
                    parent=self._panel_tag,
                    tag=self._viewport_canvas_tag,
                )
            except Exception:
                pass

    def _build_code_pane(self, dpg: Any, pane_w: int, pane_h: int) -> None:
        """Right page (Python mode): monospace multiline text input."""
        default_value = (
            self._sources.get(self._active_path, _PLACEHOLDER_CODE)
            if self._active_path is not None
            else _PLACEHOLDER_CODE
        )
        try:
            with dpg.child_window(
                width=pane_w,
                height=pane_h,
                border=True,
                parent=self._body_tag,
                tag=self._code_pane_tag,
            ):
                # Dot-grid hint — the theme paints the actual grid.
                try:
                    dpg.add_text(
                        "dot grid :: code",
                        color=list(self._muted_color),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_text(
                        multiline=True,
                        width=pane_w - 16,
                        height=pane_h - 64,
                        default_value=default_value,
                        hint=_PLACEHOLDER_HINT,
                        tab_input=True,
                        tag=self._code_input_tag,
                        callback=self._on_code_edited,
                    )
                except Exception:
                    try:
                        dpg.add_input_text(
                            multiline=True,
                            parent=self._code_pane_tag,
                            tag=self._code_input_tag,
                            default_value=default_value,
                        )
                    except Exception:
                        pass
        except Exception:
            try:
                dpg.add_input_text(
                    multiline=True,
                    parent=self._panel_tag,
                    tag=self._code_input_tag,
                    default_value=default_value,
                )
            except Exception:
                pass

    def _build_nodes_pane(self, dpg: Any, pane_w: int, pane_h: int) -> None:
        """Right page (Nodes mode): placeholder + Generate Python button."""
        try:
            with dpg.child_window(
                width=pane_w,
                height=pane_h,
                border=True,
                parent=self._body_tag,
                tag=self._nodes_pane_tag,
                show=False,
            ):
                try:
                    dpg.add_text(
                        _NODES_PLACEHOLDER,
                        tag=self._nodes_placeholder_tag,
                        color=list(self._muted_color),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label=_NODES_GENERATE_LABEL,
                        tag=self._nodes_generate_tag,
                        callback=lambda *_: self._generate_python_from_nodes(),
                    )
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(
                    _NODES_PLACEHOLDER,
                    parent=self._panel_tag,
                    tag=self._nodes_placeholder_tag,
                )
            except Exception:
                pass
            try:
                dpg.add_button(
                    label=_NODES_GENERATE_LABEL,
                    parent=self._panel_tag,
                    tag=self._nodes_generate_tag,
                    callback=lambda *_: self._generate_python_from_nodes(),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Build helpers — footer + status
    # ------------------------------------------------------------------

    def _build_footer(self, dpg: Any) -> None:
        """Footer ribbon: Run / Stop / mode toggle / Save / Open."""
        try:
            with dpg.group(
                horizontal=True,
                parent=self._panel_tag,
                tag=self._footer_tag,
            ):
                self._render_footer_buttons(dpg)
        except Exception:
            self._render_footer_buttons(dpg)

    def _render_footer_buttons(self, dpg: Any) -> None:
        try:
            dpg.add_button(
                label=_BTN_RUN,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_run",
                callback=lambda *_: self.run_script(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_STOP,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_stop",
                callback=lambda *_: self.stop_script(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_TOGGLE_PYTHON,
                parent=self._footer_tag,
                tag=self._toggle_tag,
                callback=lambda *_: self._toggle_mode(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_SAVE,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_save",
                callback=lambda *_: self.save(),
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label=_BTN_OPEN,
                parent=self._footer_tag,
                tag=f"{self._footer_tag}_open",
                callback=lambda *_: self._open_clicked(),
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
                color=list(self._muted_color),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_code_edited(self, sender: Any, data: Any) -> None:
        """Cache the code buffer on every keystroke."""
        try:
            text = str(data)
        except Exception:
            return
        if self._active_path is None:
            self._active_path = Path(_UNTITLED_NAME)
        if self._mode == NODES_MODE:
            self._node_sources[self._active_path] = text
        else:
            self._sources[self._active_path] = text
        self.call_log.append(("code_edited", len(text)))

    def _toggle_mode(self) -> None:
        """Footer button — flip between Python and Nodes."""
        self.set_mode(NODES_MODE if self._mode == PYTHON_MODE else PYTHON_MODE)

    def _open_clicked(self) -> None:
        """Footer Open button — defer to the engine's open-file hook.

        When the engine handle exposes ``open_diary_picker``, that is
        invoked. Otherwise we record the request and surface a hint
        in the status bar; the editor shell intercepts the hint and
        opens its native file dialog.
        """
        self.call_log.append(("open_clicked",))
        if self._engine is not None:
            hook = getattr(self._engine, "open_diary_picker", None)
            if callable(hook):
                try:
                    hook(self)
                    return
                except Exception:
                    pass
        self._set_status("Open: file picker not bound")

    def _generate_python_from_nodes(self) -> None:
        """Stub: emit a placeholder snippet so the toggle path is testable."""
        self.call_log.append(("generate_python_from_nodes",))
        py_source = (
            "# Auto-generated from visual nodes (stub)\n"
            "def update(dt):\n"
            "    pass\n"
        )
        if self._active_path is None:
            self._active_path = Path(_UNTITLED_NAME)
        self._sources[self._active_path] = py_source
        self.set_mode(PYTHON_MODE)
        self._set_status("Generated Python from nodes (stub)")
        self._sync_inputs_to_dpg()

    # ------------------------------------------------------------------
    # Status + exception helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        msg = validate_non_empty_str("msg", "NotebookDiaryPage._set_status", msg)
        self._status = msg
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._status_tag):
                dpg.set_value(self._status_tag, msg)
        except Exception:
            pass

    def _record_exception(self, exc: BaseException) -> None:
        """Cache the exception + show the viewport overlay + status hint."""
        self._last_exception = exc
        self._script_running = False
        # Format a one-line summary for the status bar.
        kind = type(exc).__name__
        msg = str(exc).splitlines()[0] if str(exc) else ""
        summary = f"{kind}: {msg}" if msg else kind
        self._set_status(summary)
        # Toggle the viewport-error overlay on.
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._viewport_error_tag):
                dpg.configure_item(self._viewport_error_tag, show=True)
        except Exception:
            pass
        # Stash the traceback for the next status query.
        try:
            self._last_traceback = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__),
            )
        except Exception:
            self._last_traceback = ""

    # ------------------------------------------------------------------
    # DPG sync
    # ------------------------------------------------------------------

    def _sync_inputs_to_dpg(self) -> None:
        """Push the source + title buffers into the DPG input widgets."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        # Title strip — update the filename label.
        try:
            if dpg.does_item_exist(self._title_tag):
                title = (
                    self._active_path.name
                    if self._active_path is not None
                    else _UNTITLED_NAME
                )
                dpg.set_value(self._title_tag, title)
        except Exception:
            pass
        # Code input — push the Python source (the Nodes pane shares
        # the same input today since the placeholder is read-only).
        try:
            if dpg.does_item_exist(self._code_input_tag):
                dpg.set_value(self._code_input_tag, self.get_source())
        except Exception:
            pass

    def _refresh_mode_visibility(self) -> None:
        """Show the code pane when in Python mode; nodes pane otherwise."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        show_code = self._mode == PYTHON_MODE
        try:
            if dpg.does_item_exist(self._code_pane_tag):
                dpg.configure_item(self._code_pane_tag, show=show_code)
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._nodes_pane_tag):
                dpg.configure_item(self._nodes_pane_tag, show=not show_code)
        except Exception:
            pass


__all__ = [
    "NotebookDiaryPage",
    "PYTHON_MODE",
    "NODES_MODE",
]
