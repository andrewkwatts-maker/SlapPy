"""Tool-settings actions — snap-to-grid toggle.

Backs the ``tool.snap_to_grid`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the Z7 STUB-triage sprint tick.

The action toggles :attr:`SnapConfig.enable_grid` on the editor shell's
:class:`~pharos_editor.ui.editor.snap_manager.SnapManager`. When no shell
is present (headless tests, notebook-mode callers) the toggle falls back
to a module-level flag so the router still round-trips a boolean.

The ctx may also supply ``force=True|False`` to lock the toggle to a
specific state — matches the "grid snap ON" / "grid snap OFF" menu items
some editors expose alongside the default toggle button.

Return contract
---------------

* ``{"status": "toggled", "enabled": bool, "path": "shell"}`` when the
  shell's SnapManager was mutated.
* ``{"status": "toggled", "enabled": bool, "path": "fallback"}`` when the
  headless module-level flag was flipped.
* ``{"status": "error", "message": str}`` when the shell exposes a
  SnapManager but ``enable_grid`` could not be written to.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


# Module-level fallback flag used when no shell is reachable. Tests can
# reset via :func:`_reset_snap_grid_for_tests`.
_HEADLESS_SNAP_GRID_ENABLED: bool = False


def _reset_snap_grid_for_tests() -> None:
    """Drop the module-level fallback flag. Test-only escape hatch."""
    global _HEADLESS_SNAP_GRID_ENABLED
    _HEADLESS_SNAP_GRID_ENABLED = False


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_force(ctx: dict[str, Any]) -> bool | None:
    """Return the ``force`` override (or ``None`` for "toggle current")."""
    force = ctx.get("force")
    if force is None:
        return None
    return bool(force)


def toggle_snap_to_grid(ctx: dict[str, Any]) -> dict[str, Any]:
    """Toggle (or set) the grid-snap flag on the active SnapManager.

    Resolution order:

    1. ``ctx["shell"]._snap_manager.config.enable_grid`` — the canonical
       runtime flag consumed by the drag handler.
    2. Module-level ``_HEADLESS_SNAP_GRID_ENABLED`` — used when no shell
       or SnapManager is reachable so tests can still exercise the flip.

    When ``ctx["force"]`` is ``True`` / ``False`` the flag is set to that
    value instead of toggled. This lets menu items like "Snap: ON" /
    "Snap: OFF" reuse the same action id.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_snap_to_grid", ctx)
    global _HEADLESS_SNAP_GRID_ENABLED

    force = _resolve_force(ctx)
    shell = _get_shell(ctx)

    if shell is not None:
        manager = getattr(shell, "_snap_manager", None)
        if manager is not None:
            config = getattr(manager, "config", None)
            if config is not None:
                try:
                    current = bool(getattr(config, "enable_grid", False))
                    new_val = force if force is not None else (not current)
                    setattr(config, "enable_grid", new_val)
                except Exception as exc:  # noqa: BLE001
                    return {"status": "error", "message": str(exc)}
                # Mirror the state on the shell so status-bar hooks that
                # read ``shell._snap_grid_enabled`` stay in sync.
                try:
                    setattr(shell, "_snap_grid_enabled", new_val)
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "status": "toggled",
                    "enabled": new_val,
                    "path": "shell",
                }

    # Headless fallback.
    new_val = (
        force if force is not None else (not _HEADLESS_SNAP_GRID_ENABLED)
    )
    _HEADLESS_SNAP_GRID_ENABLED = new_val
    if shell is not None:
        try:
            setattr(shell, "_snap_grid_enabled", new_val)
        except Exception:  # noqa: BLE001
            pass
    return {"status": "toggled", "enabled": new_val, "path": "fallback"}


__all__ = [
    "toggle_snap_to_grid",
    "_reset_snap_grid_for_tests",
]
