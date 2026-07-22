"""Reverse theme cycle — walk the theme registry backwards.

Backs the ``theme.cycle_reverse`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the DD1 STUB-triage sprint tick (round 7 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1).

Symmetric to
:func:`pharos_editor.actions.theme_actions.cycle_theme`: same shell-hook
preference, same headless fallback over
:func:`pharos_editor.ui.theme.list_registered_themes`, but the cursor
advances in the *opposite* direction. The two actions share
:data:`pharos_editor.actions.theme_actions._THEME_CURSOR` so a forward
tick followed by a reverse tick returns to the starting theme.

Return contract
---------------

* ``{"status": "cycled", "theme": "<name>", "path": "shell",
   "direction": "reverse"}`` when a shell hook was invoked.
* ``{"status": "cycled", "theme": "<name>", "path": "fallback",
   "direction": "reverse"}`` when the headless cursor was rewound.
* ``{"status": "no_themes"}`` when no themes have been registered.
"""
from __future__ import annotations

from typing import Any

from . import theme_actions as _theme_actions
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def cycle_theme_reverse(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rotate to the *previous* registered theme.

    Resolution order mirrors :func:`cycle_theme`:

    1. ``ctx["shell"].cycle_theme_reverse()`` — preferred shell hook.
    2. ``ctx["shell"].cycle_theme(direction="reverse")`` — same method,
       optional kwarg (some shells share the plumbing).
    3. Headless fallback — rewind the shared cursor and call
       :func:`~pharos_editor.ui.theme.apply_theme` on the previous entry.

    When the theme registry is empty the fallback returns
    ``{"status": "no_themes"}``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("cycle_theme_reverse", ctx)
    shell = _get_shell(ctx)
    if shell is not None:
        # 1) Dedicated reverse hook
        method = getattr(shell, "cycle_theme_reverse", None)
        if callable(method):
            try:
                result = method()
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            if isinstance(result, str):
                _theme_actions._THEME_CURSOR = result
                return {
                    "status": "cycled",
                    "theme": result,
                    "path": "shell",
                    "direction": "reverse",
                }
            settings = getattr(shell, "_ui_settings", None)
            theme = getattr(settings, "default_theme", None) if settings else None
            if isinstance(theme, str):
                _theme_actions._THEME_CURSOR = theme
                return {
                    "status": "cycled",
                    "theme": theme,
                    "path": "shell",
                    "direction": "reverse",
                }
            return {
                "status": "cycled",
                "theme": "",
                "path": "shell",
                "direction": "reverse",
            }
        # 2) Shared cycle_theme with direction kwarg
        method = getattr(shell, "cycle_theme", None)
        if callable(method):
            try:
                result = method(direction="reverse")
            except TypeError:
                # Shell's cycle_theme takes no kwargs — skip and fall
                # through to the headless path so the reverse ordering
                # still holds.
                result = None
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            if isinstance(result, str):
                _theme_actions._THEME_CURSOR = result
                return {
                    "status": "cycled",
                    "theme": result,
                    "path": "shell",
                    "direction": "reverse",
                }

    # ── Headless fallback ─────────────────────────────────────────
    try:
        from pharos_editor.ui.theme import (
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

    cursor = _theme_actions._THEME_CURSOR
    if cursor in themes:
        idx = themes.index(cursor)
        prev = themes[(idx - 1) % len(themes)]
    else:
        # No cursor set — start from the last entry so a single reverse
        # click lands on the tail (matches the forward wrap semantic).
        prev = themes[-1]
    _theme_actions._THEME_CURSOR = prev

    try:
        apply_theme(prev)
    except Exception:  # noqa: BLE001
        pass
    return {
        "status": "cycled",
        "theme": prev,
        "path": "fallback",
        "direction": "reverse",
    }


__all__ = ["cycle_theme_reverse"]
