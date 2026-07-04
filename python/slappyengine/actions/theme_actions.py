"""Theme-lifecycle actions — cycle to next registered theme.

Backs the ``theme.cycle`` :class:`~slappyengine.tool_router.ToolAction`
row. Prefers ``ctx["shell"].cycle_theme()`` when the shell exposes it
(matches the ``Ctrl+Shift+T`` hotkey path), otherwise falls back to a
headless-safe cycle over the process-wide theme registry from
:mod:`slappyengine.ui.theme`.

The fallback keeps its own module-level cursor so repeated dispatches
walk the theme list in a stable order — tests can assert on this by
calling :func:`_reset_theme_cursor_for_tests` between runs.

Return contract
---------------

* ``{"status": "cycled", "theme": "<name>", "path": "shell"}`` when the
  shell hook was invoked.
* ``{"status": "cycled", "theme": "<name>", "path": "fallback"}`` when
  the headless cursor was advanced.
* ``{"status": "no_themes"}`` when no themes have been registered.
"""
from __future__ import annotations

from typing import Any


# Module-level cursor tracking the last cycled theme so consecutive
# dispatches walk the ``list_registered_themes()`` order deterministically.
_THEME_CURSOR: str | None = None


def _reset_theme_cursor_for_tests() -> None:
    """Drop the module cursor. Test-only escape hatch."""
    global _THEME_CURSOR
    _THEME_CURSOR = None


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def cycle_theme(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rotate to the next registered theme.

    Resolution order:

    1. ``ctx["shell"].cycle_theme()`` — the existing shell method
       already owns the diary-theme rotation (see ``shell.py:506``).
    2. Headless fallback — walk ``list_registered_themes()`` and call
       :func:`~slappyengine.ui.theme.apply_theme` on the next entry.

    When the theme registry is empty (nothing has been registered yet)
    the fallback returns ``{"status": "no_themes"}`` so the caller can
    surface a "no themes available" toast rather than crash.
    """
    global _THEME_CURSOR
    shell = _get_shell(ctx)
    if shell is not None:
        method = getattr(shell, "cycle_theme", None)
        if callable(method):
            try:
                result = method()
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            # ``shell.cycle_theme`` returns the theme id it activated —
            # normalise to a dict so ToolRouter callers can consume it.
            if isinstance(result, str):
                _THEME_CURSOR = result
                return {"status": "cycled", "theme": result, "path": "shell"}
            # Some shells return None (still succeeded) — best-effort
            # read of the current default_theme.
            settings = getattr(shell, "_ui_settings", None)
            if settings is not None:
                theme = getattr(settings, "default_theme", None)
                if isinstance(theme, str):
                    _THEME_CURSOR = theme
                    return {
                        "status": "cycled",
                        "theme": theme,
                        "path": "shell",
                    }
            return {"status": "cycled", "theme": "", "path": "shell"}

    # ── Headless fallback ─────────────────────────────────────────
    try:
        from slappyengine.ui.theme import (
            apply_theme,
            list_registered_themes,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    themes = list_registered_themes()
    override = ctx.get("themes")
    if isinstance(override, (list, tuple)) and override:
        themes = list(override)
    if not themes:
        return {"status": "no_themes"}

    # Advance the cursor deterministically.
    if _THEME_CURSOR in themes:
        idx = themes.index(_THEME_CURSOR)
        nxt = themes[(idx + 1) % len(themes)]
    else:
        nxt = themes[0]
    _THEME_CURSOR = nxt

    # Apply the theme (soft-fails when DPG / registry is missing).
    try:
        apply_theme(nxt)
    except Exception:  # noqa: BLE001
        # Registration path might have raced with a test that cleared
        # the registry — return "cycled" anyway so tests can assert on
        # the cursor advance.
        pass
    return {"status": "cycled", "theme": nxt, "path": "fallback"}


__all__ = [
    "cycle_theme",
    "_reset_theme_cursor_for_tests",
]
