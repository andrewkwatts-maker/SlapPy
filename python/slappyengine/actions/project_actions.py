"""Project-lifecycle actions — save, new, open-recent.

These callbacks back the ``editor.save_project``, ``editor.new_project``,
and ``editor.open_recent`` :class:`~slappyengine.tool_router.ToolAction`
rows in :data:`slappyengine.tool_router.REGISTRY`. They exist as free
functions so headless tests can drive them without instantiating the DPG
editor shell — every dependency (shell, project registry, target path)
is pulled from the ``ctx`` dict the router hands the fallback.

Return contract
---------------

Each helper returns a dict describing what happened:

* ``save_project`` — ``{"status": "saved", "path": "..."}`` on success,
  ``{"status": "no_project"}`` when no project is loaded.
* ``new_project`` — ``{"status": "created", "path": "..."}`` on success,
  ``{"status": "missing_path"}`` / ``{"status": "missing_name"}`` when
  the ``ctx`` dict is under-specified.
* ``open_recent`` — ``{"status": "opened", "path": "..."}`` when the
  recents list was consulted successfully; ``{"status": "empty"}`` when
  the registry is empty.

All three swallow filesystem exceptions and surface them as
``{"status": "error", "message": "..."}`` so a failed save never crashes
the editor's status-bar hookup.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_project_from_ctx(ctx: dict[str, Any]) -> Any:
    """Extract a live :class:`~slappyengine.projects.Project` handle.

    Search order:

    1. ``ctx["project"]`` — direct override (tests pass this).
    2. ``ctx["shell"]._project`` — the shell's active project.
    3. ``ctx["shell"]._engine._project_manager._project`` — legacy hook.
    """
    proj = ctx.get("project")
    if proj is not None:
        return proj
    shell = _get_shell(ctx)
    if shell is None:
        return None
    proj = getattr(shell, "_project", None)
    if proj is not None:
        return proj
    engine = getattr(shell, "_engine", None)
    if engine is None:
        return None
    manager = getattr(engine, "_project_manager", None)
    if manager is None:
        return None
    return getattr(manager, "_project", None)


def save_project(ctx: dict[str, Any]) -> dict[str, Any]:
    """Save the active project's ``project.slap_proj`` manifest.

    Called by the ``editor.save_project`` router action. Writes the
    manifest YAML to :attr:`Project.slap_proj_path` via
    :meth:`Project.save`. When the shell / project handle is missing,
    returns ``{"status": "no_project"}`` so the caller can surface a
    "No project loaded" toast rather than crash.
    """
    project = _get_project_from_ctx(ctx)
    if project is None:
        return {"status": "no_project"}
    try:
        project.save()
    except Exception as exc:  # noqa: BLE001 — surface any I/O failure
        return {"status": "error", "message": str(exc)}
    try:
        path = str(project.slap_proj_path)
    except Exception:  # noqa: BLE001 — fall back gracefully
        path = str(getattr(project, "path", ""))
    return {"status": "saved", "path": path}


def new_project(ctx: dict[str, Any]) -> dict[str, Any]:
    """Scaffold a new project directory + manifest.

    Called by the ``editor.new_project`` router action. Requires
    ``ctx["path"]`` (the target root directory) and ``ctx["name"]``
    (the project name). Optional ``ctx["description"]`` /
    ``ctx["scaffold"]`` follow the :meth:`Project.new` defaults.

    When a shell is present and exposes a ``_project_registry`` attr,
    the new project is registered so it appears in the recents list.
    """
    path = ctx.get("path")
    name = ctx.get("name")
    if not path:
        return {"status": "missing_path"}
    if not name:
        return {"status": "missing_name"}
    try:
        from slappyengine.projects import Project
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"projects import failed: {exc}"}
    description = ctx.get("description", "") or ""
    scaffold = ctx.get("scaffold", True)
    try:
        project = Project.new(
            root=Path(path),
            name=str(name),
            description=str(description),
            scaffold=bool(scaffold),
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    # Best-effort: hand the fresh project to the shell + register it.
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_project", project)
        except Exception:  # noqa: BLE001
            pass
    registry = ctx.get("registry")
    if registry is None:
        try:
            from slappyengine.projects import get_default_registry
            registry = get_default_registry()
        except Exception:  # noqa: BLE001
            registry = None
    if registry is not None:
        try:
            registry.register(project)
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "created",
        "path": str(project.path),
        "name": project.metadata.name,
    }


def open_recent(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pop the recent-projects picker (or open a specific recent entry).

    Called by the ``editor.open_recent`` router action. Two modes:

    * ``ctx["path"]`` provided — open that specific project.
    * ``ctx["index"]`` provided (int, default 0) — open the ``index``-th
      most-recent entry from the registry.

    Returns ``{"status": "opened", "path": "..."}`` on success,
    ``{"status": "empty"}`` when the registry has no entries,
    ``{"status": "not_found", "index": N}`` when the requested index is
    out of range.
    """
    registry = ctx.get("registry")
    if registry is None:
        try:
            from slappyengine.projects import get_default_registry
            registry = get_default_registry()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    # Explicit path — open it directly.
    target = ctx.get("path")
    if target:
        try:
            project = registry.open(Path(str(target)))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
        shell = _get_shell(ctx)
        if shell is not None:
            try:
                setattr(shell, "_project", project)
            except Exception:  # noqa: BLE001
                pass
        return {"status": "opened", "path": str(project.path)}
    # Index-based lookup.
    try:
        entries = registry.list_recent(limit=10)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    if not entries:
        return {"status": "empty"}
    index = ctx.get("index", 0)
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(entries):
        return {"status": "not_found", "index": index}
    entry = entries[index]
    try:
        project = registry.open(Path(entry.path))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_project", project)
        except Exception:  # noqa: BLE001
            pass
    return {"status": "opened", "path": str(project.path), "index": index}


__all__ = [
    "save_project",
    "new_project",
    "open_recent",
]
