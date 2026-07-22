"""Snap toggle-pixel-perfect action — flip integer-pixel snap mode.

Backs the ``snap.toggle_pixel_perfect``
:class:`~pharos_editor.tool_router.ToolAction` row added by the AAA4
STUB-triage sprint tick (round 27 after ZZ4).

Distinct from the sibling snap verbs:

* OO1's ``snap.increase_grid_size`` / ``snap.decrease_grid_size``
  walk the grid rung ladder.
* VV4's ``snap.set_grid_size`` writes an absolute rung.
* ZZ4's ``snap.cycle_grid_size`` cycles rungs with wraparound.
* UU4's ``snap.set_angle_snap`` sets the rotation angle-snap.
* RR1's ``snap.toggle_incremental`` flips *increment-based* snap
  (each drag step lands on the grid, but positions between steps
  are unclamped).
* YY4's ``snap.reset_defaults`` resets every snap setting.
* Nova3D's ``edit.snap_to_pixel_grid`` performs a *one-shot* snap
  action.
* CC1's ``edit.snap_to_grid`` performs a *one-shot* grid snap.

This verb is the **mode toggle** — flips a persistent pixel-perfect
flag on the shell so that *every* subsequent position write rounds
to the nearest integer pixel. Matches Aseprite's Edit → Preferences
→ Snap to Pixel / Krita's Snap to Pixel Grid toggle / Blender's
Snap → "Pixel" absolute mode / Nova3D's snap-mode toolbar
pixel-perfect button.

Distinct from RR1's ``snap.toggle_incremental`` — that verb toggles
*incremental* snap (grid-cell stepping); this verb toggles
*absolute* pixel snap (integer round-off). The two are complementary
and independently toggleable.

Storage contract
----------------

* Shell attribute: ``_pixel_perfect_snap`` (canonical).
* Default when the attribute is absent: ``False`` — pixel-perfect
  is opt-in.

Return contract
---------------

* ``{"status": "toggled", "target": "pixel_perfect_snap",
   "enabled": bool, "previous": bool}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable and no explicit
  ``ctx["enabled"]`` seed to toggle against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_PIXEL_PERFECT_ATTR = "_pixel_perfect_snap"
_DEFAULT_ENABLED = False


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_flag(shell: Any, default: bool) -> bool:
    if shell is None:
        return default
    val = getattr(shell, _PIXEL_PERFECT_ATTR, default)
    try:
        return bool(val)
    except Exception:  # noqa: BLE001
        return default


def _write_flag(shell: Any, value: bool) -> bool:
    if shell is None:
        return value
    try:
        setattr(shell, _PIXEL_PERFECT_ATTR, value)
    except Exception:  # noqa: BLE001
        return value
    hook = getattr(shell, "_on_snap_mode_changed", None)
    if callable(hook):
        try:
            hook(_PIXEL_PERFECT_ATTR, value)
        except Exception:  # noqa: BLE001
            pass
    return value


def toggle_pixel_perfect(ctx: dict[str, Any]) -> dict[str, Any]:
    """Enable / disable integer-pixel snap mode.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — read / write for
          ``_pixel_perfect_snap``.
        * ``enabled`` (optional bool): explicit initial value; the
          toggle is applied to *this* rather than the shell attribute.
          Lets tests exercise the flip in isolation.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("toggle_pixel_perfect", ctx)
    shell = _get_shell(ctx)
    if shell is None and "enabled" not in ctx:
        return {"status": "no_shell"}
    seed = ctx.get("enabled")
    if isinstance(seed, bool):
        current = seed
    else:
        current = _read_flag(shell, default=_DEFAULT_ENABLED)
    new_val = not current
    effective = _write_flag(shell, new_val)
    return {
        "status": "toggled",
        "target": "pixel_perfect_snap",
        "enabled": bool(effective),
        "previous": current,
    }


__all__ = ["toggle_pixel_perfect", "_PIXEL_PERFECT_ATTR"]
