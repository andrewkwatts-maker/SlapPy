"""Spawn-history actions — re-run the most recent spawn dispatch.

Backs the ``spawn.repeat_last`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the CC1 STUB-triage sprint tick.

The action reads the "most recent spawn" tuple that
:func:`pharos_editor.tool_router._fb_spawn` records into the shell via
``shell._last_spawn = (card_id, spec)`` — or the equivalent slot on the
notebook spawn menu (``menu._last_spawn``). It then replays that tuple
through ``shell._on_spawn`` so the exact same prefab lands again.

Because the tuple is captured at dispatch time (see
:func:`_record_last_spawn` below — invoked from the router's own
``_fb_spawn`` wrapper via ``spawn.repeat_last``'s cooperative pattern),
this action needs no scene bookkeeping and no separate history log. It
simply pops the last-spawn tuple, adjusts the spec (optional
translation offset so successive presses of Shift-D don't stack every
copy at the same origin), and re-fires.

Return contract
---------------

* ``{"status": "respawned", "card_id": str, "spec": dict}`` — the
  ``_on_spawn`` hook returned normally.
* ``{"status": "no_history"}`` — no previous spawn was recorded, so
  there's nothing to repeat. Legal state on fresh editors.
* ``{"status": "no_shell"}`` — no shell was reachable via ``ctx``.
* ``{"status": "error", "message": str}`` — the ``_on_spawn`` callback
  raised.

Cooperative recording
---------------------

The router's ``_fb_spawn`` wrapper doesn't currently write to
``shell._last_spawn`` on its own — the CC1 tick adds an opt-in
``record_last_spawn`` hook here so future rounds can wire it up
without owning a fresh module. Tests exercise the hook directly.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_last_spawn(ctx: dict[str, Any]) -> tuple[str, dict] | None:
    """Return ``(card_id, spec)`` for the most recent spawn.

    Search order:

    1. ``ctx["last_spawn"]`` — explicit override (tests use this).
    2. ``shell._last_spawn`` — the shell-owned slot set by
       :func:`record_last_spawn`.
    3. ``shell._spawn_menu._last_spawn`` — the notebook spawn menu's
       own copy (matches the two-slot convention Nova3D adopted for
       tool state).

    Returns
    -------
    tuple[str, dict] | None
        The tuple if a valid record was found, else ``None``.
    """
    override = ctx.get("last_spawn")
    if isinstance(override, tuple) and len(override) == 2:
        card_id, spec = override
        if isinstance(card_id, str) and isinstance(spec, dict):
            return card_id, dict(spec)
    shell = _get_shell(ctx)
    if shell is None:
        return None
    record = getattr(shell, "_last_spawn", None)
    if not isinstance(record, tuple) or len(record) != 2:
        menu = getattr(shell, "_spawn_menu", None)
        record = getattr(menu, "_last_spawn", None) if menu else None
    if isinstance(record, tuple) and len(record) == 2:
        card_id, spec = record
        if isinstance(card_id, str) and isinstance(spec, dict):
            return card_id, dict(spec)
    return None


def record_last_spawn(
    shell: Any, card_id: str, spec: dict[str, Any],
) -> None:
    """Stash *(card_id, spec)* on *shell* so :func:`repeat_last` can find it.

    Cheap side-effect wrapper — mirrors what ``_fb_spawn`` should do at
    dispatch time. Kept as a public entry point so a shell / plugin can
    opt into repeat-last support without depending on the router
    internals.

    Silently no-ops when *shell* is ``None`` or refuses attribute
    writes.
    """
    if shell is None:
        return
    if not isinstance(card_id, str) or not card_id:
        return
    if not isinstance(spec, dict):
        return
    try:
        setattr(shell, "_last_spawn", (card_id, dict(spec)))
    except Exception:  # noqa: BLE001
        pass


def repeat_last(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-invoke the most recent spawn dispatch.

    See the module docstring for the return contract.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("repeat_last", ctx)
    shell = _get_shell(ctx)
    if shell is None and "last_spawn" not in ctx:
        return {"status": "no_shell"}
    record = _resolve_last_spawn(ctx)
    if record is None:
        return {"status": "no_history"}
    card_id, spec = record
    # Optional micro-offset so repeated Shift-D presses don't overlap.
    offset = ctx.get("offset")
    if isinstance(offset, (list, tuple)) and len(offset) in (2, 3):
        pos = spec.get("position") or spec.get("origin") or spec.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == len(offset):
            new_pos = [
                float(pos[i]) + float(offset[i])
                for i in range(len(offset))
            ]
            for key in ("position", "origin", "pos"):
                if key in spec:
                    spec[key] = new_pos
                    break
    # Dispatch — re-fires _on_spawn without going back through the
    # menu modal (that would prompt for parameters again).
    if shell is not None:
        handler = getattr(shell, "_on_spawn", None)
        if callable(handler):
            try:
                result = handler(card_id, spec)
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
            # Record the fresh spec so a *second* repeat picks it up
            # (offset stacks).
            record_last_spawn(shell, card_id, spec)
            return {
                "status": "respawned",
                "card_id": card_id,
                "spec": spec,
                "result": result,
            }
    # No shell handler — return the tuple anyway so headless callers
    # can drive their own dispatch (matches paste_selection's pattern).
    return {"status": "respawned", "card_id": card_id, "spec": spec}


__all__ = [
    "repeat_last",
    "record_last_spawn",
]
