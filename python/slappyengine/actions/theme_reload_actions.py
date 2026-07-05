"""Theme registry reload action — force a rescan of builtin + user themes.

Backs the ``theme.reload_all`` :class:`~slappyengine.tool_router.ToolAction`
row added by the FF1 STUB-triage sprint tick (round 9 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1).

Motivated by the theming-editor workflow: after editing a theme's
underlying JSON / .toml on disk, the shell needs a way to reload the
registry without restarting the editor. This action wraps that flush.

Steps performed
---------------

1. Snapshot the current active theme name (so it can be re-applied).
2. Reset the shared theme cursor
   (:mod:`slappyengine.actions.theme_actions._THEME_CURSOR`) so the
   next ``theme.cycle`` starts from a clean slate.
3. Clear the process-wide ``_REGISTRY`` via
   :func:`slappyengine.ui.theme._reset_registry_for_tests` (an
   internal-but-reused escape hatch — the shipping name is misleading,
   the function is our stable reset point).
4. Re-run :func:`slappyengine.ui.theme.bake_default_themes` to re-seed
   the builtin roster.
5. Re-scan any :class:`UserThemeStore` reachable via
   ``ctx["store"]`` / ``shell._user_theme_store`` and re-register every
   user theme.
6. Re-apply the previously-active theme (best-effort).

Return contract
---------------

* ``{"status": "reloaded", "themes": [...], "count": N,
   "active": "<name>|None", "reactivated": bool}`` on success.
* ``{"status": "error", "message": "<...>"}`` when the ui.theme
  subpackage can't be imported (extremely unlikely in headless tests
  since the tests import :mod:`slappyengine.tool_router` which in turn
  transitively imports the theme package via other action modules).

The helper also fires ``shell.on_themes_reloaded(themes)`` when the
shell exposes such a hook so the theme-switcher panel can rebuild its
row list.
"""
from __future__ import annotations

from typing import Any

from . import theme_actions as _theme_actions
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_store(ctx: dict[str, Any]) -> Any:
    """Resolve a :class:`UserThemeStore` handle from *ctx*.

    Prefers ``ctx["store"]`` over ``shell._user_theme_store``.
    """
    store = ctx.get("store")
    if store is not None:
        return store
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_user_theme_store", None)


def reload_all_themes(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flush and re-scan the theme registry.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell. Used to (a) locate the
          :class:`UserThemeStore` and (b) fire the
          ``on_themes_reloaded`` broadcast.
        * ``store`` (optional): direct :class:`UserThemeStore` override.
        * ``skip_bake`` (optional bool): when truthy, skip the
          ``bake_default_themes`` step (headless tests use this so we
          don't hit disk for every reload assertion).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reload_all_themes", ctx)
    try:
        from slappyengine.ui.theme import (
            _reset_registry_for_tests,
            apply_theme,
            bake_default_themes,
            get_active_theme,
            list_registered_themes,
            register_theme,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Snapshot the current active theme (name, not the object) so we
    # can re-apply after the reset. `get_active_theme()` raises when no
    # theme is active — treat that as "no snapshot needed".
    try:
        active_before = get_active_theme()
    except LookupError:
        active_before = None
    except Exception:  # noqa: BLE001
        active_before = None
    active_name = getattr(active_before, "name", None)

    # Step 1: reset the cursor so post-reload `theme.cycle` starts fresh.
    _theme_actions._THEME_CURSOR = None

    # Step 2: clear the registry.
    _reset_registry_for_tests()

    # Step 3: re-bake builtins.
    if not ctx.get("skip_bake"):
        try:
            bake_default_themes()
        except Exception:  # noqa: BLE001
            # Baking failures are non-fatal — the user_themes store
            # rescan below can still populate the registry.
            pass

    # Step 4: re-register user themes.
    store = _get_store(ctx)
    if store is not None:
        # UserThemeStore exposes an iterable of user themes; different
        # revisions have named the accessor differently, so probe each
        # in order.
        iterables = []
        for name in ("themes", "list_themes", "all_themes", "iter_themes"):
            candidate = getattr(store, name, None)
            if callable(candidate):
                try:
                    iterables.append(candidate())
                except Exception:  # noqa: BLE001
                    pass
            elif candidate is not None:
                iterables.append(candidate)
        for iterable in iterables:
            try:
                for theme in iterable:
                    try:
                        register_theme(theme)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

    # Step 5: re-apply previously-active theme.
    themes = list_registered_themes()
    reactivated = False
    if active_name and active_name in themes:
        try:
            apply_theme(active_name)
            reactivated = True
        except Exception:  # noqa: BLE001
            pass

    # Step 6: broadcast to the shell so the switcher panel rebuilds.
    shell = _get_shell(ctx)
    if shell is not None:
        hook = getattr(shell, "on_themes_reloaded", None)
        if callable(hook):
            try:
                hook(list(themes))
            except Exception:  # noqa: BLE001
                pass

    return {
        "status": "reloaded",
        "themes": list(themes),
        "count": len(themes),
        "active": active_name,
        "reactivated": reactivated,
    }


__all__ = ["reload_all_themes"]
