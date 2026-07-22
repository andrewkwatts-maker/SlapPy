"""Theme I/O actions — export the current theme to a user-picked path.

Backs the ``theme.export_current`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the Z7 STUB-triage sprint tick. Companion to the existing
``theme.cycle`` action from Y1.

The action writes the currently-active :class:`ThemeSpec` to a YAML
file whose path the caller provides via ``ctx["path"]``. When no path is
supplied but a ``ctx["shell"]`` is present with a ``prompt_save_path``
callable (matches the shell's Tk save-dialog hook), that callable is
invoked so the user gets the familiar native chooser. Otherwise the
action returns ``{"status": "no_path"}`` and the caller can flash a
"where should I save this?" toast.

Design goals
------------

* **Round-trippable** — the payload is produced by
  :meth:`ThemeSpec.to_yaml` so a subsequent load through
  :class:`UserThemeStore` re-inflates the exact theme.
* **Atomic write** — the write path reuses
  :meth:`UserThemeStore._atomic_write_text` so a crash mid-flush never
  leaves a partial file for the next launch to stumble on.
* **Headless-safe** — callers may pass ``ctx["theme"]`` (a
  :class:`ThemeSpec` instance) instead of an active theme registry. This
  keeps the tests fully headless.

Return contract
---------------

* ``{"status": "exported", "path": str, "theme": str, "size_bytes": int}``
  on success.
* ``{"status": "no_path"}`` when no path override was supplied and no
  shell prompt hook is reachable.
* ``{"status": "no_theme"}`` when no theme is active and none was passed
  in ``ctx["theme"]``.
* ``{"status": "error", "message": str}`` when the write raised.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


def _resolve_theme(ctx: dict[str, Any]) -> Any:
    """Return the :class:`ThemeSpec` to export.

    Search order:

    1. ``ctx["theme"]`` — direct override (tests pass this).
    2. :func:`pharos_editor.ui.theme.get_active_theme` — the current
       process-wide active theme registered via ``apply_theme(name)``.
    """
    override = ctx.get("theme")
    if override is not None:
        return override
    try:
        from pharos_editor.ui.theme import get_active_theme
    except Exception:  # noqa: BLE001
        return None
    try:
        return get_active_theme()
    except Exception:  # noqa: BLE001
        # No active theme yet.
        return None


def _resolve_path(ctx: dict[str, Any], theme_name: str) -> Path | None:
    """Return the destination Path or ``None`` when nothing resolves.

    Search order:

    1. ``ctx["path"]`` — direct override (tests pass this).
    2. ``ctx["shell"].prompt_save_path(default_name)`` — shell hook that
       opens the native Tk save dialog. When the user cancels this
       returns ``None`` and the export bails cleanly.
    """
    override = ctx.get("path")
    if override is not None:
        return Path(override)
    shell = ctx.get("shell")
    if shell is None:
        return None
    prompter = getattr(shell, "prompt_save_path", None)
    if not callable(prompter):
        return None
    try:
        default_name = f"{theme_name}.theme.yaml"
        picked = prompter(default_name)
    except Exception:  # noqa: BLE001
        return None
    if not picked:
        return None
    return Path(picked)


def _serialize(theme: Any) -> str | None:
    """Emit the YAML payload for *theme* or ``None`` when to_yaml fails."""
    to_yaml = getattr(theme, "to_yaml", None)
    if not callable(to_yaml):
        return None
    try:
        return to_yaml()
    except Exception:  # noqa: BLE001
        return None


def _atomic_write(path: Path, text: str) -> None:
    """Atomically write *text* to *path* (temp + rename)."""
    # Reuse UserThemeStore's atomic write so the two paths stay in sync.
    try:
        from pharos_editor.ui.theme.user_themes import UserThemeStore
    except Exception:
        # Last-resort fallback: plain write. Rare (only when the theme
        # module can't import — headless tests still hit this path).
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    UserThemeStore._atomic_write_text(path, text)


def export_current_theme(ctx: dict[str, Any]) -> dict[str, Any]:
    """Write the active :class:`ThemeSpec` to a YAML file.

    Parameters (via ``ctx``)
    ------------------------
    * ``path`` — destination file. When absent the shell's
      ``prompt_save_path`` hook is invoked so the user picks one.
    * ``theme`` — optional :class:`ThemeSpec` override; skips the
      ``get_active_theme()`` lookup.
    * ``shell`` — shell handle (only read for the ``prompt_save_path``
      fallback).

    Returns
    -------
    dict
        See the module docstring for the full contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("export_current_theme", ctx)
    theme = _resolve_theme(ctx)
    if theme is None:
        return {"status": "no_theme"}
    theme_name = getattr(theme, "name", "theme")
    path = _resolve_path(ctx, theme_name)
    if path is None:
        return {"status": "no_path"}
    payload = _serialize(theme)
    if payload is None:
        return {
            "status": "error",
            "message": "theme.to_yaml() failed or missing",
        }
    try:
        _atomic_write(path, payload)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    return {
        "status": "exported",
        "path": str(path),
        "theme": theme_name,
        "size_bytes": len(payload.encode("utf-8")),
    }


__all__ = [
    "export_current_theme",
]
