"""Panel-visibility "close others" action — keep the current panel only.

Backs the ``panel.close_others`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the FF1 STUB-triage sprint tick (round 9 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1).

Companion to the DD1 ``panel.close_all`` / ``panel.restore_last_hidden``
pair (:mod:`panel_visibility_actions`). Where ``close_all`` hides every
panel, ``close_others`` hides every panel *except* the one the user is
currently focused on. Perfect for "solo this panel" workflows.

The kept panel is resolved in this order:

1. ``ctx["keep"]`` — explicit override (right-click "Close Others").
2. ``shell._active_panel_id`` — the shell's remembered focus.
3. ``shell._last_focused_panel_id`` — legacy fallback.

When no keep-target can be resolved the helper returns
``{"status": "no_target"}`` so the caller can surface a "click a panel
first" toast.

The batch of closed panels is pushed onto ``shell._hidden_panel_stack``
using the same protocol as :mod:`panel_visibility_actions`, so a
subsequent ``panel.restore_last_hidden`` (DD1) undoes the operation.

Return contract
---------------

* ``{"status": "closed", "kept": "<id>", "panels": [id, ...],
   "count": N}`` on success.
* ``{"status": "no_shell"}`` when no shell is reachable via ctx.
* ``{"status": "no_target"}`` when the keep-target can't be resolved.
"""
from __future__ import annotations

from typing import Any

from . import panel_visibility_actions as _pv
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_keep(ctx: dict[str, Any]) -> str | None:
    """Return the panel id the caller wants to keep visible."""
    raw = ctx.get("keep")
    if isinstance(raw, str) and raw:
        return raw
    shell = _get_shell(ctx)
    if shell is None:
        return None
    for attr in ("_active_panel_id", "_last_focused_panel_id"):
        candidate = getattr(shell, attr, None)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def close_other_panels(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hide every visible panel except ``ctx["keep"]`` (or the active one).

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): editor shell owning the panels.
        * ``keep`` (optional str): panel id to keep visible. Falls back
          to ``shell._active_panel_id`` / ``shell._last_focused_panel_id``.
        * ``panels`` (optional list[str]): override the panel roster —
          same semantics as :func:`panel_visibility_actions.close_all_panels`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("close_other_panels", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}
    keep = _resolve_keep(ctx)
    if keep is None:
        return {"status": "no_target"}

    closed: list[str] = []
    for pid in _pv._panel_ids(ctx):
        if pid == keep:
            continue
        if pid in _pv._SKIP_IDS:
            continue
        if not _pv._is_visible(shell, pid):
            continue
        ok = _pv._set_panel_visibility(shell, pid, False)
        if ok:
            closed.append(pid)

    if closed:
        _pv._push_stack(shell, closed)

    return {
        "status": "closed",
        "kept": keep,
        "panels": closed,
        "count": len(closed),
    }


__all__ = ["close_other_panels"]
