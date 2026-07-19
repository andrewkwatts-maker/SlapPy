"""``ShaderHotReloader`` — live WGSL reload for the editor (EEE3).

The user's directive:

    "coding them in the editor via python bindings / having exposed
    functions"

This module is the runtime half of the WGSL live-editor loop. The editor
panel (:mod:`slappyengine.ui.editor.wgsl_editor_panel`) drives it via
``.recompile(path, new_source)`` when the user hits the Compile button;
the shell drives it via ``.watch()`` from the per-frame tick so on-disk
edits (external editors, VCS resets) are picked up without the user
having to click anything.

Design goals
------------

* **Zero required deps.** wgpu is a soft-import — when it isn't
  installed, :meth:`recompile` still returns a :class:`CompileResult`
  (marked ``ok=False`` with a "wgpu unavailable" message) so the panel
  can render a coherent status line.
* **Every reload emits a bus event.** ``shader.reloaded`` on
  :mod:`slappyengine.event_bus` — subscribers (a running renderer, a
  demo, a test) rebuild their pipelines without polling.
* **Compiler errors are structured.** Whenever wgpu surfaces a
  compilation error we parse it for line + column so the panel's error
  gutter can highlight the offending token.
* **Callback-per-shader.** Each registered path carries its own
  ``on_reload(new_source: str)`` callback so the same reloader can
  service multiple pipelines with different rebuild logic (viewport
  cube, deferred g-buffer, tonemap pass, …).

Public surface
--------------

* :class:`ShaderHotReloader`
* :func:`get_default_reloader` — process-wide singleton the editor
  panel + REPL helper share.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine import event_bus as _event_bus


# ---------------------------------------------------------------------------
# wgpu soft-import — every wgpu reference goes through the module-level
# alias so tests can force the "wgpu unavailable" branch by monkeypatching
# ``_wgpu`` to ``None``.
# ---------------------------------------------------------------------------
try:  # pragma: no cover — optional dep
    import wgpu as _wgpu  # type: ignore[import-not-found]
    import wgpu.utils as _wgpu_utils  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    _wgpu = None  # type: ignore[assignment]
    _wgpu_utils = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Result + registry types
# ---------------------------------------------------------------------------


@dataclass
class CompileError:
    """A single WGSL compile diagnostic — line, column, and message."""

    line: int
    column: int
    message: str

    def format(self) -> str:
        return f"line {self.line}, col {self.column}: {self.message}"


@dataclass
class CompileResult:
    """Outcome of a WGSL compile attempt.

    Attributes
    ----------
    ok
        ``True`` when validation passed. When wgpu isn't installed, ``ok``
        is ``False`` and :attr:`message` carries the "wgpu unavailable"
        notice — callers that only care about the on-disk save don't have
        to distinguish these cases.
    message
        Human-readable summary (empty on success unless the wgpu backend
        surfaced warnings).
    errors
        Structured error list — one entry per diagnostic. Empty on
        success or when the failure lacked line info.
    validated
        ``True`` when a real wgpu device was available to validate the
        module; ``False`` when the soft-import failed and we only saved
        text to disk.
    """

    ok: bool
    message: str = ""
    errors: list[CompileError] = field(default_factory=list)
    validated: bool = False


@dataclass
class _Entry:
    """Bookkeeping per registered shader path."""

    path: str
    on_reload: Callable[[str], None]
    last_mtime: float = 0.0


# ---------------------------------------------------------------------------
# Error message parsing — best-effort regex over wgpu's stringified errors.
# ---------------------------------------------------------------------------

# wgpu-rs surfaces errors like:
#   "Shader validation error: ... at line 12, column 4"
#   "error: Parser error: ... at 12:4"
#   "Naga error: ... [line 3]"
# We accept every common shape and default to (1, 1) when nothing matches.
_LINE_COL_PATTERNS = [
    re.compile(r"line\s+(\d+)[,:\s]+col(?:umn)?\s+(\d+)", re.IGNORECASE),
    re.compile(r"(?:^|\D)(\d+):(\d+)"),
    re.compile(r"\[line\s+(\d+)\]", re.IGNORECASE),
]


def _parse_compile_error(msg: str) -> list[CompileError]:
    """Extract ``[CompileError]`` from a stringified wgpu compile error."""
    errors: list[CompileError] = []
    for line in msg.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        line_no, col_no = 0, 0
        for pat in _LINE_COL_PATTERNS:
            m = pat.search(stripped)
            if m:
                try:
                    line_no = int(m.group(1))
                    col_no = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 1
                except (ValueError, IndexError):
                    continue
                break
        if line_no > 0:
            errors.append(CompileError(line_no, col_no or 1, stripped))
    if not errors and msg.strip():
        errors.append(CompileError(1, 1, msg.strip().splitlines()[0]))
    return errors


# ---------------------------------------------------------------------------
# ShaderHotReloader
# ---------------------------------------------------------------------------


class ShaderHotReloader:
    """Track shader paths + recompile them on demand.

    Two entry points:

    * :meth:`recompile` — user-driven (the Compile button). Takes the
      new source, optionally validates it against a wgpu device, calls
      the registered on-reload callback with the new text, and emits
      a ``shader.reloaded`` bus event.
    * :meth:`watch` — polled from the editor's per-frame tick. Walks
      every registered path and re-fires the reload pipeline when the
      on-disk ``mtime`` changed since we last saw it.

    The reloader is intentionally callback-based rather than owning
    pipelines directly — the same instance can service the 3D viewport,
    the deferred renderer, and a demo scene without any of them knowing
    about each other.
    """

    _EVENT_NAME = "shader.reloaded"

    def __init__(self, device: Any | None = None) -> None:
        self._entries: dict[str, _Entry] = {}
        # Compile-validation device. Soft-imported — when wgpu isn't up,
        # :meth:`recompile` still fires the callback so the panel's Save
        # + Reload paths remain useful.
        self._device: Any = device
        # Last observed reload result per path — the panel reads this to
        # paint its output panel green/red.
        self.last_result: dict[str, CompileResult] = {}
        # Latency in seconds of the most recent reload (recompile + fire
        # callback + emit event) — measured by :meth:`recompile` so the
        # editor can surface a "reloaded in 3ms" hint.
        self.last_latency_s: float = 0.0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        path: str,
        on_reload: Callable[[str], None],
    ) -> None:
        """Track *path* and call *on_reload(new_source)* on every reload.

        Idempotent — re-registering the same path replaces the callback
        so panels rebuilt after a hot-reload don't stack listeners.
        The initial ``mtime`` is captured so :meth:`watch` doesn't fire
        an unnecessary reload on the very first poll.
        """
        abs_path = os.path.abspath(path)
        mtime = 0.0
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            pass
        self._entries[abs_path] = _Entry(
            path=abs_path, on_reload=on_reload, last_mtime=mtime,
        )

    def unregister(self, path: str) -> None:
        """Stop tracking *path*. No-op if unknown."""
        self._entries.pop(os.path.abspath(path), None)

    def registered_paths(self) -> list[str]:
        """Return every currently-tracked absolute path."""
        return list(self._entries.keys())

    # ------------------------------------------------------------------
    # Poll-based watching
    # ------------------------------------------------------------------

    def watch(self) -> list[str]:
        """Poll every registered shader's mtime. Reload changed ones.

        Returns the list of paths that were reloaded on this tick. Safe
        to call at any rate; the editor calls it at ~1 Hz from the shell
        tick to keep the poll cost negligible.
        """
        reloaded: list[str] = []
        for entry in list(self._entries.values()):
            try:
                mtime = os.path.getmtime(entry.path)
            except OSError:
                continue
            if mtime <= entry.last_mtime:
                continue
            entry.last_mtime = mtime
            try:
                with open(entry.path, "r", encoding="utf-8") as fh:
                    new_source = fh.read()
            except OSError:
                continue
            self.recompile(entry.path, new_source)
            reloaded.append(entry.path)
        return reloaded

    # ------------------------------------------------------------------
    # Recompile pipeline
    # ------------------------------------------------------------------

    def recompile(self, path: str, new_source: str) -> CompileResult:
        """Validate + dispatch a new WGSL source for *path*.

        Steps:

        1. Validate the source via :meth:`_validate` (wgpu.create_shader_module).
        2. Fire the registered on-reload callback with the new text —
           unconditionally, so the panel can preview an in-progress edit
           even before validation lands.
        3. Emit ``shader.reloaded`` on the default event bus with
           ``path`` + ``ok`` + ``latency_s`` in the payload.

        Records the outcome in :attr:`last_result` + measures wall-clock
        latency into :attr:`last_latency_s`.
        """
        t0 = time.perf_counter()
        abs_path = os.path.abspath(path)
        result = self._validate(new_source)
        # Fire the on-reload callback even when validation failed — many
        # callbacks (e.g. the viewport panel) can hold onto the previous
        # module until the next successful compile; letting them see the
        # new text also gives them a chance to log a diff.
        entry = self._entries.get(abs_path)
        if entry is not None:
            try:
                entry.on_reload(new_source)
            except Exception as e:  # pragma: no cover — user callback
                # A bad callback must NOT propagate — this is a live-edit
                # loop and killing it on an unrelated exception would be
                # a poor UX.
                result = CompileResult(
                    ok=False,
                    message=f"reload callback raised: {e!r}",
                    errors=result.errors,
                    validated=result.validated,
                )
        latency = time.perf_counter() - t0
        self.last_latency_s = latency
        self.last_result[abs_path] = result
        try:
            _event_bus.publish(
                self._EVENT_NAME,
                path=abs_path,
                ok=result.ok,
                validated=result.validated,
                message=result.message,
                latency_s=latency,
            )
        except Exception:  # pragma: no cover — bus should never raise
            pass
        return result

    def recompile_all(self) -> dict[str, CompileResult]:
        """Reload every tracked path from disk and return per-path results."""
        results: dict[str, CompileResult] = {}
        for path in list(self._entries.keys()):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    new_source = fh.read()
            except OSError as e:
                results[path] = CompileResult(
                    ok=False,
                    message=f"read failed: {e!r}",
                    errors=[],
                    validated=False,
                )
                continue
            results[path] = self.recompile(path, new_source)
        return results

    # ------------------------------------------------------------------
    # Validation (wgpu-backed when available)
    # ------------------------------------------------------------------

    def _validate(self, source: str) -> CompileResult:
        """Compile *source* through wgpu's shader-module validator.

        Falls through to a text-only "wgpu unavailable" result when the
        soft-import failed — the Save path is still useful in that mode.
        """
        if _wgpu is None or _wgpu_utils is None:
            return CompileResult(
                ok=False,
                message="wgpu unavailable — cannot validate WGSL syntax",
                errors=[],
                validated=False,
            )
        device = self._device
        if device is None:
            try:
                device = _wgpu_utils.get_default_device()
                self._device = device
            except Exception as e:  # pragma: no cover — GPU-dependent
                return CompileResult(
                    ok=False,
                    message=f"wgpu adapter unavailable: {e!r}",
                    errors=[],
                    validated=False,
                )
        try:
            # ``create_shader_module`` raises on parse / validation errors
            # in most wgpu-py versions; some versions surface errors via
            # ``device.on_uncaptured_error`` — we don't try to plumb that
            # through here because the panel's compile button also gives
            # us an in-band success indicator.
            device.create_shader_module(code=source)
        except Exception as e:  # pragma: no cover — GPU-dependent
            msg = str(e)
            return CompileResult(
                ok=False,
                message=msg,
                errors=_parse_compile_error(msg),
                validated=True,
            )
        return CompileResult(ok=True, message="OK", errors=[], validated=True)


# ---------------------------------------------------------------------------
# Process-wide singleton — the editor panel + the REPL helper both use it.
# ---------------------------------------------------------------------------

_DEFAULT_RELOADER: ShaderHotReloader | None = None


def get_default_reloader() -> ShaderHotReloader:
    """Return the process-wide :class:`ShaderHotReloader` singleton.

    Lazily constructed on first access so plain ``import
    slappyengine.render.shader_hot_reload`` doesn't force a wgpu device
    request. Tests can reset the singleton via :func:`reset_default_reloader`.
    """
    global _DEFAULT_RELOADER
    if _DEFAULT_RELOADER is None:
        _DEFAULT_RELOADER = ShaderHotReloader()
    return _DEFAULT_RELOADER


def reset_default_reloader() -> None:
    """Clear the singleton. Used by tests between cases."""
    global _DEFAULT_RELOADER
    _DEFAULT_RELOADER = None


__all__ = [
    "CompileError",
    "CompileResult",
    "ShaderHotReloader",
    "get_default_reloader",
    "reset_default_reloader",
]
