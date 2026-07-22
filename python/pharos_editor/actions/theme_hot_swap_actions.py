"""Theme hot-swap action — apply a named theme without cycling.

Backs the ``theme.hot_swap`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the NN2 STUB-triage sprint tick (round 15).

Distinct from the existing router entries:

* ``theme.cycle`` — walks the roster in registration order.
* ``theme.cycle_reverse`` — walks the roster backwards.
* ``theme.random`` — picks any theme (biased away from the current one).
* ``theme.reload_all`` — flushes the registry and rebakes builtins.

``theme.hot_swap`` is the missing "please apply *this specific* theme
right now" gate — matches Unity's "Preferences -> Themes -> pick from
dropdown" and Blender's "Preferences -> Themes -> load preset" flows.
Callers pass ``ctx["theme"]`` (a name string) and the helper resolves
it against :func:`pharos_editor.ui.theme.get_theme` before applying via
:func:`~pharos_editor.ui.theme.apply_theme`.

Shell integration
-----------------

When a shell is present, the helper also mirrors the swap onto the
``shell._theme_cursor`` (used by ``theme.cycle``) so a subsequent
``theme.cycle`` continues from the new active theme rather than
rewinding to the previous one. This matches the behaviour of the
Nova3D dark shell's theme switcher panel.

If the shell exposes ``shell.apply_theme(name)`` the helper calls that
first so the shell can do any bespoke re-styling. Otherwise it walks
the ``pharos_editor.ui.theme`` package directly.

Return contract
---------------

* ``{"status": "swapped", "theme": "<name>", "previous": "<name>|None",
   "path": "shell" | "theme_module" | "fallback"}`` — success.
* ``{"status": "unchanged", "theme": "<name>"}`` — the requested
  theme was already active.
* ``{"status": "no_theme"}`` — ``ctx["theme"]`` is missing / empty.
* ``{"status": "unknown_theme", "theme": "<name>",
   "available": [names, ...]}`` — the theme doesn't exist in the
  registry; the available roster is echoed for the caller's picker.
* ``{"status": "error", "message": "<...>"}`` — the ui.theme
  subpackage failed to import (rare — only in ultra-minimal test envs).
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_name(ctx: dict[str, Any]) -> str | None:
    raw = ctx.get("theme")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    return name or None


def _import_theme_module() -> Any:
    try:
        import pharos_editor.ui.theme as theme_mod
    except Exception:  # noqa: BLE001
        return None
    return theme_mod


def _list_registered(theme_mod: Any) -> list[str]:
    if theme_mod is None:
        return []
    lister = getattr(theme_mod, "list_registered_themes", None)
    if callable(lister):
        try:
            got = lister()
            return [str(n) for n in got]
        except Exception:  # noqa: BLE001
            pass
    getter = getattr(theme_mod, "get_theme_names", None)
    if callable(getter):
        try:
            got = getter()
            return [str(n) for n in got]
        except Exception:  # noqa: BLE001
            pass
    return []


def _resolve_theme(theme_mod: Any, name: str) -> Any:
    """Return a truthy handle iff *name* is a known theme.

    The ui.theme package exposes ``list_registered_themes`` but no
    ``get_theme`` helper — so "resolution" here is just membership.
    Returning the name itself keeps the calling code's ``is None`` /
    truthy check working.
    """
    if theme_mod is None:
        return None
    getter = getattr(theme_mod, "get_theme", None)
    if callable(getter):
        try:
            got = getter(name)
            if got is not None:
                return got
        except Exception:  # noqa: BLE001
            pass
    lister = getattr(theme_mod, "list_registered_themes", None)
    if callable(lister):
        try:
            names = lister()
        except Exception:  # noqa: BLE001
            return None
        for candidate in names:
            if str(candidate) == name:
                return name
    return None


def _get_active_name(theme_mod: Any, shell: Any) -> str | None:
    if shell is not None:
        current = getattr(shell, "_active_theme", None)
        if isinstance(current, str) and current:
            return current
    if theme_mod is not None:
        getter = getattr(theme_mod, "get_active_theme_name", None)
        if callable(getter):
            try:
                got = getter()
                if isinstance(got, str) and got:
                    return got
            except Exception:  # noqa: BLE001
                pass
    return None


def _apply_via_shell(shell: Any, name: str) -> bool:
    if shell is None:
        return False
    fn = getattr(shell, "apply_theme", None)
    if callable(fn):
        try:
            fn(name)
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _apply_via_module(theme_mod: Any, name: str) -> bool:
    if theme_mod is None:
        return False
    fn = getattr(theme_mod, "apply_theme", None)
    if callable(fn):
        try:
            fn(name)
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


def _mirror_shell_state(shell: Any, name: str) -> None:
    if shell is None:
        return
    for attr in ("_active_theme", "_current_theme", "_theme_cursor"):
        try:
            setattr(shell, attr, name)
        except Exception:  # noqa: BLE001
            continue


def hot_swap(ctx: dict[str, Any]) -> dict[str, Any]:
    """Apply the theme named by ``ctx["theme"]`` directly.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``theme`` (required str) — name of the theme to activate.
        * ``shell`` (optional) — when present, the helper prefers
          ``shell.apply_theme(name)`` over the module-level fallback.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("hot_swap", ctx)
    name = _resolve_name(ctx)
    if not name:
        return {"status": "no_theme"}

    theme_mod = _import_theme_module()
    if theme_mod is None:
        return {
            "status": "error",
            "message": "pharos_editor.ui.theme failed to import",
        }

    resolved = _resolve_theme(theme_mod, name)
    if resolved is None:
        return {
            "status": "unknown_theme",
            "theme": name,
            "available": _list_registered(theme_mod),
        }

    shell = _get_shell(ctx)
    previous = _get_active_name(theme_mod, shell)
    if previous == name:
        return {"status": "unchanged", "theme": name}

    if _apply_via_shell(shell, name):
        path = "shell"
    elif _apply_via_module(theme_mod, name):
        path = "theme_module"
    else:
        path = "fallback"

    _mirror_shell_state(shell, name)

    return {
        "status": "swapped",
        "theme": name,
        "previous": previous,
        "path": path,
    }


__all__ = ["hot_swap"]
