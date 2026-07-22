"""Theme reset-to-default action — snap the active theme back to baseline.

Backs the ``theme.reset_to_default``
:class:`~pharos_engine.tool_router.ToolAction` row added by the RR1
STUB-triage sprint tick (round 19).

Distinct from FF1's ``theme.reload_all`` (which flushes the whole theme
registry then re-scans disk) — this helper is the *reset* verb every DCC
ships next to reload: pick the canonical shipped default theme and
re-apply it. Photoshop's ``Reset Workspace``, Blender's ``Load Factory
Settings → Theme``, Nova3D's ``Theme → Restore Default`` — each collapses
the current theme back to the first-registered baseline without touching
user-authored themes on disk.

Default-theme resolution
------------------------

1. ``ctx["default"]`` — explicit override (tests use this to pin the
   default without depending on registry order).
2. ``shell._default_theme`` — shell-owned pointer.
3. ``ctx["ui_settings"].default_theme`` / ``shell._ui_settings.default_theme``
   — reads the same slot :mod:`~pharos_engine.ui.editor.shell` writes on
   startup.
4. ``list_registered_themes()[0]`` — first-registered theme fallback.

Return contract
---------------

* ``{"status": "reset", "theme": "<name>", "previous": "<name>|None",
   "path": "shell" | "fallback"}`` — success (theme applied and cursor
   parked at *theme*).
* ``{"status": "unchanged", "theme": "<name>"}`` — the current active
  theme already matched the default.
* ``{"status": "no_themes"}`` — the registry is empty.
* ``{"status": "error", "message": "<...>"}`` — the ``ui.theme`` module
  could not be imported (headless environment without DPG).
"""
from __future__ import annotations

from typing import Any

from . import theme_actions as _theme_actions
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_default_name(
    ctx: dict[str, Any],
    themes: list[str],
) -> str | None:
    """Return the canonical default theme name to reset to.

    Consults the ordered fallback chain documented in the module
    docstring.
    """
    explicit = ctx.get("default")
    if isinstance(explicit, str) and explicit:
        return explicit
    shell = _get_shell(ctx)
    if shell is not None:
        raw = getattr(shell, "_default_theme", None)
        if isinstance(raw, str) and raw:
            return raw
    for holder in (ctx.get("ui_settings"),
                   getattr(shell, "_ui_settings", None) if shell else None):
        if holder is None:
            continue
        raw = getattr(holder, "default_theme", None)
        if isinstance(raw, str) and raw:
            return raw
    if themes:
        return themes[0]
    return None


def _get_active_name() -> str | None:
    """Best-effort read of the currently-active theme name."""
    try:
        from pharos_engine.ui.theme import get_active_theme
    except Exception:  # noqa: BLE001
        return None
    try:
        active = get_active_theme()
    except Exception:  # noqa: BLE001 (LookupError etc.)
        return None
    name = getattr(active, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def reset_to_default(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-apply the shipped default theme.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell. Reads ``_default_theme`` /
          ``_ui_settings.default_theme`` and receives the reset via
          ``shell.apply_theme(name)`` when that method exists (matches
          the DCC-side hotkey path).
        * ``default`` (optional str): explicit default-theme override
          (tests use this).
        * ``ui_settings`` (optional): headless override for the
          ``default_theme`` slot.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reset_to_default", ctx)
    try:
        from pharos_engine.ui.theme import (
            apply_theme,
            list_registered_themes,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    themes = list_registered_themes()
    override_themes = ctx.get("themes")
    if isinstance(override_themes, (list, tuple)) and override_themes:
        themes = list(override_themes)
    if not themes:
        return {"status": "no_themes"}

    target = _resolve_default_name(ctx, themes)
    if not target:
        return {"status": "no_themes"}
    previous = _get_active_name()

    if previous == target:
        # Still park the module cursor so a follow-up ``theme.cycle``
        # walks forward from the reset point rather than from wherever
        # the user last landed.
        _theme_actions._THEME_CURSOR = target
        return {"status": "unchanged", "theme": target}

    # Prefer the shell hook when available (matches the DCC hotkey path
    # and keeps ``shell._ui_settings.default_theme`` in sync for saves).
    shell = _get_shell(ctx)
    path = "fallback"
    if shell is not None:
        setter = getattr(shell, "apply_theme", None)
        if callable(setter):
            try:
                setter(target)
                path = "shell"
            except Exception:  # noqa: BLE001
                # Fall through to the direct apply path.
                pass
    if path == "fallback":
        try:
            apply_theme(target)
        except Exception:  # noqa: BLE001
            # DPG missing / theme registration raced — still park the
            # cursor so downstream ``theme.cycle`` behaves.
            pass

    _theme_actions._THEME_CURSOR = target
    return {
        "status": "reset",
        "theme": target,
        "previous": previous,
        "path": path,
    }


__all__ = ["reset_to_default"]
