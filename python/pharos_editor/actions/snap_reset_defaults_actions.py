"""Snap reset-defaults action — reset every snap knob to factory defaults.

Backs the ``snap.reset_defaults``
:class:`~pharos_editor.tool_router.ToolAction` row added by the YY4
STUB-triage sprint tick (round 25 after WW4).

Complements the sibling snap verbs — those verbs *set* the individual
knobs; this verb wipes them back to canonical defaults in one shot:

* OO1's ``snap.increase_grid_size`` / ``snap.decrease_grid_size`` walk
  a ladder — reset returns to rung ``1.0``.
* VV4's ``snap.set_grid_size`` writes an absolute grid size — reset
  writes ``1.0``.
* UU4's ``snap.set_angle_snap`` writes an absolute angle step in
  degrees — reset writes ``15.0`` (Blender / Unity default).
* RR1's ``snap.toggle_incremental`` flips the boolean gate — reset
  turns it OFF (matches Blender factory-fresh).
* ``tools.snap_to_grid`` is the master on/off toggle — reset does
  NOT touch this (matches Photoshop's "Reset Snapping" which
  preserves the master enable).

Every DCC that ships a snap panel ships a "Reset to Defaults" button
next to it: Blender's Preferences → Snap → Reset, Unity's ProGrids
"Restore Defaults", Nova3D's Snap-panel gear menu → Reset.

Defaults
--------

Match the canonical DCC defaults used across the engine:

* ``_snap_grid_size`` — ``1.0``  (one scene unit; matches
  ``spawn_at_grid_actions._DEFAULT_GRID``)
* ``_snap_angle_deg`` — ``15.0`` (matches Blender's default rotation
  snap; canonical rung in ``snap_angle_snap_actions._CANONICAL``)
* ``_snap_incremental`` — ``False`` (matches Blender factory-fresh)

The write walks the same mirror aliases the setters do so the read
paths of ``spawn.at_grid`` etc. all see the reset value.

Return contract
---------------

* ``{"status": "reset", "previous": {...}, "new": {...},
   "changed": bool}`` — success. ``changed=False`` when every knob
   was already at its default (idempotent no-op).
* ``{"status": "no_shell"}`` — no shell reachable to write against.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULTS: dict[str, Any] = {
    "grid_size": 1.0,
    "angle_deg": 15.0,
    "incremental": False,
}

# Mirror-attribute chains — write every alias to keep read paths in sync.
_GRID_ATTRS: tuple[str, ...] = ("_snap_grid_size", "_grid_size", "grid_size")
_ANGLE_ATTRS: tuple[str, ...] = ("_snap_angle_deg", "_snap_angle")
_INCREMENTAL_ATTRS: tuple[str, ...] = (
    "_snap_incremental",
    "_incremental_snap",
    "snap_incremental",
)

_TOL: float = 1e-6


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _read_float(shell: Any, attrs: tuple[str, ...], default: float) -> float:
    for attr in attrs:
        raw = getattr(shell, attr, None)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return default


def _read_bool(shell: Any, attrs: tuple[str, ...], default: bool) -> bool:
    for attr in attrs:
        raw = getattr(shell, attr, None)
        if raw is None:
            continue
        try:
            return bool(raw)
        except Exception:  # noqa: BLE001
            continue
    return default


def _write_all(shell: Any, attrs: tuple[str, ...], value: Any) -> None:
    for attr in attrs:
        try:
            setattr(shell, attr, value)
        except Exception:  # noqa: BLE001
            continue


def reset_snap_defaults(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reset every snap knob on *shell* to its factory default.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required-when-no-seed): editor shell — receives
          the reset writes.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reset_snap_defaults", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}

    previous = {
        "grid_size": _read_float(
            shell, _GRID_ATTRS, _DEFAULTS["grid_size"],
        ),
        "angle_deg": _read_float(
            shell, _ANGLE_ATTRS, _DEFAULTS["angle_deg"],
        ),
        "incremental": _read_bool(
            shell, _INCREMENTAL_ATTRS, _DEFAULTS["incremental"],
        ),
    }

    _write_all(shell, _GRID_ATTRS, _DEFAULTS["grid_size"])
    _write_all(shell, _ANGLE_ATTRS, _DEFAULTS["angle_deg"])
    _write_all(shell, _INCREMENTAL_ATTRS, _DEFAULTS["incremental"])

    changed = (
        abs(previous["grid_size"] - _DEFAULTS["grid_size"]) > _TOL
        or abs(previous["angle_deg"] - _DEFAULTS["angle_deg"]) > _TOL
        or previous["incremental"] != _DEFAULTS["incremental"]
    )

    return {
        "status": "reset",
        "previous": previous,
        "new": dict(_DEFAULTS),
        "changed": changed,
    }


__all__ = ["reset_snap_defaults", "_DEFAULTS"]
