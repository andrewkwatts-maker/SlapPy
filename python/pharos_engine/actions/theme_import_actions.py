"""Theme-import actions — load ``*.theme.yaml`` / ``*.theme.css`` from disk.

Backs the ``theme.import_from_file`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the BB1 STUB-triage sprint tick. Companion to
``theme.export_current`` (Z7) — the pair is a symmetric YAML round-trip
that lets users copy themes between machines / share them via chat.

The action loads a theme spec from a caller-supplied file, registers it
with the process-wide theme registry, and optionally activates it. When
no path is supplied but a ``ctx["shell"]`` is present with a
``prompt_open_path`` callable (mirror of the ``prompt_save_path`` hook
that Z7 uses), that callable is invoked so the user gets the familiar
Tk chooser. Otherwise the action returns ``{"status": "no_path"}`` and
the caller can flash a "which file?" toast.

Supported formats
-----------------

* ``.theme.yaml`` — the canonical shape produced by
  :meth:`pharos_engine.ui.theme.ThemeSpec.to_yaml`. Fed through
  :meth:`ThemeSpec.from_yaml`.
* ``.yaml`` / ``.yml`` — same shape, alternate extension.
* ``.theme.css`` — reserved for a future declarative-CSS loader. For
  now the action returns ``{"status": "unsupported", "format": "css"}``
  so the caller can surface a "CSS import coming soon" toast rather
  than silently mis-parse.

Return contract
---------------

* ``{"status": "imported", "theme": "<name>", "path": str,
  "activated": bool}`` on success.
* ``{"status": "no_path"}`` when neither ``ctx["path"]`` nor a shell
  prompt hook was reachable.
* ``{"status": "missing", "path": str}`` when the path resolves but the
  file doesn't exist.
* ``{"status": "unsupported", "format": str}`` for unknown extensions.
* ``{"status": "error", "message": str}`` when parsing / registration
  raised.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


_YAML_SUFFIXES: tuple[str, ...] = (".theme.yaml", ".yaml", ".yml")
_CSS_SUFFIXES: tuple[str, ...] = (".theme.css", ".css")


def _resolve_path(ctx: dict[str, Any]) -> Path | None:
    """Return the source Path or ``None`` when nothing resolves.

    Search order:

    1. ``ctx["path"]`` — direct override (tests + programmatic callers).
    2. ``ctx["shell"].prompt_open_path(default_ext)`` — shell hook that
       opens the native Tk open-file dialog. When the user cancels this
       returns ``None`` and the import bails cleanly.
    """
    override = ctx.get("path")
    if override is not None:
        return Path(override)
    shell = ctx.get("shell")
    if shell is None:
        return None
    prompter = getattr(shell, "prompt_open_path", None)
    if not callable(prompter):
        return None
    try:
        picked = prompter(".theme.yaml")
    except Exception:  # noqa: BLE001
        return None
    if not picked:
        return None
    return Path(picked)


def _classify_suffix(path: Path) -> str:
    """Return ``"yaml"`` / ``"css"`` / ``""`` based on *path*'s extension.

    We check the compound suffixes (``.theme.yaml`` / ``.theme.css``)
    first so a themey-named file wins over the generic single suffix.
    """
    name = path.name.lower()
    for suffix in _YAML_SUFFIXES:
        if name.endswith(suffix):
            return "yaml"
    for suffix in _CSS_SUFFIXES:
        if name.endswith(suffix):
            return "css"
    return ""


def import_from_file(ctx: dict[str, Any]) -> dict[str, Any]:
    """Load a theme file from disk and register it.

    Parameters (via ``ctx``)
    ------------------------
    * ``path`` — the source file. When absent the shell's
      ``prompt_open_path`` hook is invoked.
    * ``activate`` — when truthy (default: ``True``), the newly-loaded
      theme becomes the process-wide active theme. Set to ``False`` to
      just add it to the registry without swapping.
    * ``shell`` — optional shell handle (only read for the
      ``prompt_open_path`` fallback).

    Returns
    -------
    dict
        See the module docstring for the full contract.
    """
    path = _resolve_path(ctx)
    if path is None:
        return {"status": "no_path"}
    if not path.is_file():
        return {"status": "missing", "path": str(path)}

    kind = _classify_suffix(path)
    if kind == "css":
        return {"status": "unsupported", "format": "css"}
    if kind != "yaml":
        return {"status": "unsupported", "format": path.suffix or "unknown"}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"status": "error", "message": str(exc)}

    try:
        from pharos_engine.ui.theme import (
            ThemeSpec,
            apply_theme,
            register_theme,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    try:
        theme = ThemeSpec.from_yaml(text)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    try:
        register_theme(theme)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    activate = bool(ctx.get("activate", True))
    if activate:
        try:
            apply_theme(theme.name)
        except Exception:  # noqa: BLE001
            # Registration succeeded but activation failed (unlikely) —
            # still surface the imported theme so the caller can retry.
            activate = False

    return {
        "status": "imported",
        "theme": theme.name,
        "path": str(path),
        "activated": activate,
    }


__all__ = [
    "import_from_file",
]
