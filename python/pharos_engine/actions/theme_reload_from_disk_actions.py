"""Theme reload-from-disk action — hot-reload a single theme's YAML file.

Backs the ``theme.reload_from_disk``
:class:`~pharos_engine.tool_router.ToolAction` row added by the TT2
STUB-triage sprint tick (round 21).

Distinct from the two adjacent theme-lifecycle verbs:

* FF1's ``theme.reload_all`` — flushes the *entire* registry and rebakes
  every builtin + user theme from scratch. Heavy-hammer verb — throws
  away every in-memory tweak.
* RR1's ``theme.reset_to_default`` — snaps the active theme cursor back
  to the shipped baseline; never touches disk.
* BB1's ``theme.import_from_file`` — loads an arbitrary user-picked
  file into the registry.

``theme.reload_from_disk`` is the *targeted* hot-reload — the "I just
edited the theme's YAML in another editor, please pick up my changes
without dropping every other in-memory theme" verb. Blender's
"Reload Scripts" for a single addon, Godot's Editor → Theme →
Reload From Disk, Substance Painter's Refresh Shelf.

Source resolution
-----------------

1. ``ctx["path"]`` — explicit file to reload (tests use this).
2. ``ctx["theme_name"]`` + resolver → walk
   ``shell._user_theme_store`` / ``shell._theme_paths`` for a matching
   entry.
3. Active theme's ``source_path`` attribute when the ThemeSpec carries
   one.

Return contract
---------------

* ``{"status": "reloaded", "theme": "<name>", "path": str,
   "reactivated": bool}`` on success. ``reactivated`` is ``True`` when
   the reloaded theme was the active one (so we re-applied it in
   place — an in-place hot-reload).
* ``{"status": "no_path"}`` — no source path resolvable.
* ``{"status": "missing", "path": str}`` — the resolved path is absent
   on disk.
* ``{"status": "error", "message": str}`` — parse / registry failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_active_name() -> str | None:
    try:
        from pharos_engine.ui.theme import get_active_theme
    except Exception:  # noqa: BLE001
        return None
    try:
        active = get_active_theme()
    except Exception:  # noqa: BLE001
        return None
    name = getattr(active, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _get_active_source_path() -> Path | None:
    try:
        from pharos_engine.ui.theme import get_active_theme
    except Exception:  # noqa: BLE001
        return None
    try:
        active = get_active_theme()
    except Exception:  # noqa: BLE001
        return None
    raw = getattr(active, "source_path", None)
    if raw is None:
        return None
    try:
        return Path(str(raw))
    except Exception:  # noqa: BLE001
        return None


def _resolve_path(ctx: dict[str, Any]) -> Path | None:
    """Return the source Path or ``None`` when nothing resolves.

    Search order:

    1. ``ctx["path"]`` — explicit override.
    2. ``ctx["theme_name"]`` looked up against ``shell._theme_paths`` or
       ``shell._user_theme_store``.
    3. Active theme's ``source_path``.
    """
    override = ctx.get("path")
    if override is not None:
        return Path(override)
    shell = _get_shell(ctx)
    theme_name = ctx.get("theme_name")
    if shell is not None and isinstance(theme_name, str) and theme_name:
        paths = getattr(shell, "_theme_paths", None)
        if isinstance(paths, dict):
            raw = paths.get(theme_name)
            if raw is not None:
                return Path(raw)
        store = getattr(shell, "_user_theme_store", None)
        if store is not None:
            path_of = getattr(store, "path_of", None)
            if callable(path_of):
                try:
                    got = path_of(theme_name)
                except Exception:  # noqa: BLE001
                    got = None
                if got is not None:
                    return Path(got)
    return _get_active_source_path()


def reload_from_disk(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-parse the active (or named) theme's on-disk YAML file.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (optional): explicit ``*.theme.yaml`` file.
        * ``theme_name`` (optional): resolve the path via the shell's
          registered path table.
        * ``shell`` (optional): editor shell (path lookup + apply hook).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reload_from_disk", ctx)
    path = _resolve_path(ctx)
    if path is None:
        return {"status": "no_path"}
    if not path.is_file():
        return {"status": "missing", "path": str(path)}

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

    active = _get_active_name()
    reactivated = False
    if isinstance(active, str) and active == theme.name:
        shell = _get_shell(ctx)
        setter = getattr(shell, "apply_theme", None) if shell else None
        if callable(setter):
            try:
                setter(theme.name)
                reactivated = True
            except Exception:  # noqa: BLE001
                pass
        if not reactivated:
            try:
                apply_theme(theme.name)
                reactivated = True
            except Exception:  # noqa: BLE001
                pass

    return {
        "status": "reloaded",
        "theme": theme.name,
        "path": str(path),
        "reactivated": reactivated,
    }


__all__ = ["reload_from_disk"]
