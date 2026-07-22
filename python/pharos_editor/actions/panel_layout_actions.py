"""Panel layout actions — auto-tile grid + cascade.

Backs two :class:`~pharos_editor.tool_router.ToolAction` rows added by
the GG1 STUB-triage sprint tick (round 10 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1):

* ``panel.tile_grid`` — auto-tile every currently-visible panel into
  a near-square grid that fills the viewport. Companion to the
  layout-preset flow but works on the *current* set of visible panels
  instead of a persisted preset.
* ``panel.cascade`` — cascade every visible panel into an offset
  staircase (classic Windows MDI behaviour). Useful for "give me a
  quick glance at every open panel without one occluding another".

Both actions honour the viewport dimensions supplied via
``ctx["viewport_size"]`` (a ``(width, height)`` pair) or, when absent,
walk ``shell.get_viewport_size()`` / ``shell._viewport_size``. When no
viewport size is reachable a headless fallback of ``(1280, 720)`` is
used so unit tests never need a DPG context.

Panel positioning writes through ``shell.set_panel_rect(panel_id, x, y,
w, h)`` when exposed. Falls back to setting ``x`` / ``y`` / ``width`` /
``height`` on ``shell._panel_windows[panel_id]`` — the shape most of the
shipping shells already carry. The written positions are also mirrored
on ``shell._panel_layout_state[panel_id]`` (``x`` / ``y`` / ``width`` /
``height`` attributes) so a subsequent ``file.save_layout_as`` (BB1)
picks them up.

Return contract
---------------

* ``{"status": "tiled", "panels": [...], "count": N, "rows": R,
   "cols": C}`` — grid tiling succeeded.
* ``{"status": "cascaded", "panels": [...], "count": N,
   "offset": (dx, dy)}`` — cascade succeeded.
* ``{"status": "no_shell"}`` — no shell reachable via ctx.
* ``{"status": "no_visible_panels"}`` — every panel is currently hidden.
"""
from __future__ import annotations

import math
from typing import Any

from . import panel_visibility_actions as _pv
from ._ctx import ensure_ctx


_DEFAULT_VIEWPORT = (1280, 720)
_DEFAULT_CASCADE_OFFSET = (32, 32)
_DEFAULT_CASCADE_SIZE = (640, 480)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _viewport_size(ctx: dict[str, Any]) -> tuple[int, int]:
    """Return the viewport dimensions to fit tiles into.

    Resolution order:

    1. ``ctx["viewport_size"]`` — explicit ``(w, h)`` override.
    2. ``shell.get_viewport_size()`` — canonical shell hook.
    3. ``shell._viewport_size`` — persisted attribute.
    4. Default ``(1280, 720)`` — headless fallback.
    """
    raw = ctx.get("viewport_size")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        w, h = raw
        return int(w), int(h)
    shell = _get_shell(ctx)
    if shell is not None:
        getter = getattr(shell, "get_viewport_size", None)
        if callable(getter):
            try:
                out = getter()
            except Exception:  # noqa: BLE001
                out = None
            if isinstance(out, (list, tuple)) and len(out) == 2:
                return int(out[0]), int(out[1])
        stored = getattr(shell, "_viewport_size", None)
        if isinstance(stored, (list, tuple)) and len(stored) == 2:
            return int(stored[0]), int(stored[1])
    return _DEFAULT_VIEWPORT


def _visible_panels(ctx: dict[str, Any]) -> list[str]:
    """Return every currently-visible panel id from the canonical roster.

    Uses ``_pv._panel_ids`` for the roster + ``_pv._is_visible`` for
    the per-panel visibility check — same protocol DD1's close-all uses
    so the two actions agree on "what's visible" without an extra API.
    Skips the viewport panel (always-visible, has no movable frame).
    """
    shell = _get_shell(ctx)
    if shell is None:
        return []
    out: list[str] = []
    for pid in _pv._panel_ids(ctx):
        if pid in _pv._SKIP_IDS:
            continue
        if _pv._is_visible(shell, pid):
            out.append(pid)
    return out


def _write_panel_rect(
    shell: Any, panel_id: str, x: int, y: int, w: int, h: int,
) -> bool:
    """Write panel *panel_id*'s rect. Returns True on best-effort success.

    Route order:

    1. ``shell.set_panel_rect(id, x, y, w, h)`` — canonical setter.
    2. ``shell._panel_windows[id]`` — attribute assignment on the
       wrapper (``x`` / ``y`` / ``width`` / ``height``).
    3. ``shell._panel_layout_state[id]`` — attribute assignment on the
       persisted state entry.
    """
    setter = getattr(shell, "set_panel_rect", None)
    if callable(setter):
        try:
            setter(panel_id, x, y, w, h)
            _mirror_to_state(shell, panel_id, x, y, w, h)
            return True
        except Exception:  # noqa: BLE001
            pass
    ok = False
    windows = getattr(shell, "_panel_windows", None)
    if isinstance(windows, dict):
        wrapper = windows.get(panel_id)
        if wrapper is not None:
            try:
                wrapper.x = x
                wrapper.y = y
                wrapper.width = w
                wrapper.height = h
                ok = True
            except Exception:  # noqa: BLE001
                pass
    _mirror_to_state(shell, panel_id, x, y, w, h)
    return ok or _mirror_to_state(shell, panel_id, x, y, w, h)


def _mirror_to_state(
    shell: Any, panel_id: str, x: int, y: int, w: int, h: int,
) -> bool:
    """Mirror the rect onto ``shell._panel_layout_state``.

    Returns ``True`` when the state entry existed and was updated
    (so a stateless shell still counts a successful write on
    ``_panel_windows``).
    """
    state = getattr(shell, "_panel_layout_state", None)
    if not isinstance(state, dict):
        return False
    entry = state.get(panel_id)
    if entry is None:
        return False
    try:
        entry.x = x
        entry.y = y
        entry.width = w
        entry.height = h
        return True
    except Exception:  # noqa: BLE001
        return False


def tile_grid(ctx: dict[str, Any]) -> dict[str, Any]:
    """Auto-tile every visible panel into a near-square grid.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): editor shell.
        * ``viewport_size`` (optional): ``(w, h)`` override.
        * ``panels`` (optional list[str]): panel-roster override —
          same key as :mod:`panel_visibility_actions`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("tile_grid", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}
    panels = _visible_panels(ctx)
    if not panels:
        return {"status": "no_visible_panels"}

    vw, vh = _viewport_size(ctx)
    n = len(panels)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = max(1, int(math.ceil(n / cols)))
    cell_w = max(1, vw // cols)
    cell_h = max(1, vh // rows)

    tiled: list[str] = []
    for idx, pid in enumerate(panels):
        col = idx % cols
        row = idx // cols
        x = col * cell_w
        y = row * cell_h
        _write_panel_rect(shell, pid, x, y, cell_w, cell_h)
        tiled.append(pid)

    return {
        "status": "tiled",
        "panels": tiled,
        "count": len(tiled),
        "rows": rows,
        "cols": cols,
    }


def cascade(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cascade every visible panel into an offset staircase.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): editor shell.
        * ``offset`` (optional ``(dx, dy)``): per-step offset.
          Defaults to ``(32, 32)``.
        * ``panel_size`` (optional ``(w, h)``): per-panel dimensions.
          Defaults to ``(640, 480)``.
        * ``viewport_size`` (optional): clamps the cascade so panels
          don't march off the viewport edge.
        * ``panels`` (optional list[str]): panel-roster override.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("cascade", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}
    panels = _visible_panels(ctx)
    if not panels:
        return {"status": "no_visible_panels"}

    raw_off = ctx.get("offset")
    if isinstance(raw_off, (list, tuple)) and len(raw_off) == 2:
        dx, dy = int(raw_off[0]), int(raw_off[1])
    else:
        dx, dy = _DEFAULT_CASCADE_OFFSET

    raw_size = ctx.get("panel_size")
    if isinstance(raw_size, (list, tuple)) and len(raw_size) == 2:
        pw, ph = int(raw_size[0]), int(raw_size[1])
    else:
        pw, ph = _DEFAULT_CASCADE_SIZE

    vw, vh = _viewport_size(ctx)

    cascaded: list[str] = []
    for idx, pid in enumerate(panels):
        x = idx * dx
        y = idx * dy
        # Clamp so we never walk fully off the viewport edge.
        if x + pw > vw:
            x = max(0, vw - pw)
        if y + ph > vh:
            y = max(0, vh - ph)
        _write_panel_rect(shell, pid, x, y, pw, ph)
        cascaded.append(pid)

    return {
        "status": "cascaded",
        "panels": cascaded,
        "count": len(cascaded),
        "offset": (dx, dy),
    }


__all__ = ["tile_grid", "cascade"]
