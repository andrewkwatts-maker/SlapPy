"""Panel-dock actions — dock a named panel to the left or right edge.

Backs the ``panel.dock_left`` / ``panel.dock_right``
:class:`~pharos_editor.tool_router.ToolAction` rows added by the NN2
STUB-triage sprint tick (round 15).

Every DCC editor exposes a "snap this panel to the left / right edge"
gesture (Unity Layout menu, Blender N-panel toggle, Unreal Docking).
This helper writes the panel rect into the shell's persisted layout
state so a subsequent ``file.save_layout_as`` (BB1) captures the new
dock; the shipping DPG shell re-reads that state through
``_panel_layout_state`` on the next redraw.

Shell contract
--------------

The panel id resolves through ``ctx["panel_id"]`` (required). Viewport
dims come from ``ctx["viewport_size"]`` (a ``(width, height)`` pair) or
``shell.get_viewport_size()`` / ``shell._viewport_size``. When neither
is available a headless fallback of ``(1280, 720)`` is used — matches
:mod:`panel_layout_actions`.

Dock width defaults to ``0.25`` of the viewport width (matches Unity's
default docked-panel width). Override via ``ctx["width_ratio"]``
(fractional) or ``ctx["width_px"]`` (absolute pixels).

Write path (attempted in order until one succeeds):

* ``shell.set_panel_rect(panel_id, x, y, w, h)`` — canonical method call.
* ``shell._panel_windows[panel_id]`` — MovablePanel wrapper attribute
  writes (``x`` / ``y`` / ``width`` / ``height``).
* ``shell._panel_layout_state[panel_id]`` — persisted layout entry
  attribute writes.

The chosen path is echoed back in the result dict so status-bar toasts
can hint at whether the write hit the live panel or the persisted state.

Return contract
---------------

* ``{"status": "docked", "side": "left"|"right", "panel_id": str,
   "rect": (x, y, w, h), "viewport": (vw, vh), "path": ...}`` — success.
* ``{"status": "no_shell"}`` — no shell reachable via ctx.
* ``{"status": "no_panel_id"}`` — ``ctx["panel_id"]`` missing / empty.
* ``{"status": "unknown_panel"}`` — the panel id doesn't exist in the
  shell's registered panel set.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_VIEWPORT: tuple[int, int] = (1280, 720)
_DEFAULT_WIDTH_RATIO: float = 0.25
_MIN_DOCK_WIDTH_PX: int = 120
_MAX_DOCK_WIDTH_RATIO: float = 0.75


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _viewport_size(shell: Any, ctx: dict[str, Any]) -> tuple[int, int]:
    override = ctx.get("viewport_size")
    if override is not None:
        try:
            return int(override[0]), int(override[1])
        except Exception:  # noqa: BLE001
            pass
    if shell is not None:
        getter = getattr(shell, "get_viewport_size", None)
        if callable(getter):
            try:
                got = getter()
                return int(got[0]), int(got[1])
            except Exception:  # noqa: BLE001
                pass
        raw = getattr(shell, "_viewport_size", None)
        if raw is not None:
            try:
                return int(raw[0]), int(raw[1])
            except Exception:  # noqa: BLE001
                pass
    return _DEFAULT_VIEWPORT


def _resolve_width(
    ctx: dict[str, Any], viewport_w: int,
) -> int:
    absolute = ctx.get("width_px")
    if absolute is not None:
        try:
            px = int(absolute)
        except (TypeError, ValueError):
            px = 0
        if px >= _MIN_DOCK_WIDTH_PX:
            cap = int(viewport_w * _MAX_DOCK_WIDTH_RATIO)
            return max(_MIN_DOCK_WIDTH_PX, min(cap, px))
    ratio = ctx.get("width_ratio")
    if ratio is not None:
        try:
            frac = float(ratio)
        except (TypeError, ValueError):
            frac = _DEFAULT_WIDTH_RATIO
    else:
        frac = _DEFAULT_WIDTH_RATIO
    if frac <= 0.0:
        frac = _DEFAULT_WIDTH_RATIO
    if frac > _MAX_DOCK_WIDTH_RATIO:
        frac = _MAX_DOCK_WIDTH_RATIO
    return max(_MIN_DOCK_WIDTH_PX, int(viewport_w * frac))


def _panel_exists(shell: Any, panel_id: str) -> bool:
    """Return ``True`` iff *shell* knows about *panel_id* through any surface.

    A generous check — we don't want ``panel.dock_left`` to hard-fail
    against a bespoke shell that only exposes ``_panel_layout_state``.
    """
    windows = getattr(shell, "_panel_windows", None)
    if isinstance(windows, dict) and panel_id in windows:
        return True
    state = getattr(shell, "_panel_layout_state", None)
    if isinstance(state, dict) and panel_id in state:
        return True
    ids_getter = getattr(shell, "get_panel_ids", None)
    if callable(ids_getter):
        try:
            ids = ids_getter()
            if panel_id in ids:
                return True
        except Exception:  # noqa: BLE001
            pass
    ids_attr = getattr(shell, "_panel_ids", None)
    if isinstance(ids_attr, (list, tuple, set)) and panel_id in ids_attr:
        return True
    return False


def _write_rect(
    shell: Any,
    panel_id: str,
    x: int,
    y: int,
    w: int,
    h: int,
) -> str:
    """Attempt every known write surface. Returns the path label used."""
    method = getattr(shell, "set_panel_rect", None)
    if callable(method):
        try:
            method(panel_id, x, y, w, h)
            return "method"
        except Exception:  # noqa: BLE001
            pass
    windows = getattr(shell, "_panel_windows", None)
    if isinstance(windows, dict):
        wrapper = windows.get(panel_id)
        if wrapper is not None:
            try:
                setattr(wrapper, "x", x)
                setattr(wrapper, "y", y)
                setattr(wrapper, "width", w)
                setattr(wrapper, "height", h)
                path = "window"
                # Also mirror onto layout_state when available.
                state = getattr(shell, "_panel_layout_state", None)
                if isinstance(state, dict):
                    entry = state.get(panel_id)
                    if entry is not None:
                        try:
                            setattr(entry, "x", x)
                            setattr(entry, "y", y)
                            setattr(entry, "width", w)
                            setattr(entry, "height", h)
                        except Exception:  # noqa: BLE001
                            pass
                return path
            except Exception:  # noqa: BLE001
                pass
    state = getattr(shell, "_panel_layout_state", None)
    if isinstance(state, dict):
        entry = state.get(panel_id)
        if entry is not None:
            try:
                setattr(entry, "x", x)
                setattr(entry, "y", y)
                setattr(entry, "width", w)
                setattr(entry, "height", h)
                return "state"
            except Exception:  # noqa: BLE001
                pass
    return "fallback"


def _dock(ctx: dict[str, Any], side: str) -> dict[str, Any]:
    """Shared implementation — ``side`` is ``"left"`` or ``"right"``."""
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}
    raw_id = ctx.get("panel_id")
    if raw_id is None or not isinstance(raw_id, str) or not raw_id.strip():
        return {"status": "no_panel_id"}
    panel_id = raw_id.strip()
    if not _panel_exists(shell, panel_id):
        return {"status": "unknown_panel", "panel_id": panel_id}

    viewport_w, viewport_h = _viewport_size(shell, ctx)
    dock_w = _resolve_width(ctx, viewport_w)
    x = 0 if side == "left" else max(0, viewport_w - dock_w)
    y = 0
    path = _write_rect(shell, panel_id, x, y, dock_w, viewport_h)

    # Remember the last dock side so restore_last_dock could reverse it.
    try:
        setattr(shell, "_last_dock_side", side)
        setattr(shell, "_last_docked_panel", panel_id)
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "docked",
        "side": side,
        "panel_id": panel_id,
        "rect": (x, y, dock_w, viewport_h),
        "viewport": (viewport_w, viewport_h),
        "path": path,
    }


def dock_left(ctx: dict[str, Any]) -> dict[str, Any]:
    """Dock ``ctx["panel_id"]`` to the left edge of the viewport.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` — required.
        * ``panel_id`` (required str) — id of the panel to dock.
        * ``viewport_size`` (optional 2-tuple): override the shell's
          reported viewport size.
        * ``width_ratio`` (optional float, default ``0.25``): dock
          width as a fraction of the viewport width.
        * ``width_px`` (optional int): dock width in absolute pixels.
          Wins over ``width_ratio`` when both are supplied.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("dock_left", ctx)
    return _dock(ctx, "left")


def dock_right(ctx: dict[str, Any]) -> dict[str, Any]:
    """Dock ``ctx["panel_id"]`` to the right edge of the viewport.

    Same argument surface as :func:`dock_left`. See its docstring.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("dock_right", ctx)
    return _dock(ctx, "right")


__all__ = [
    "dock_left",
    "dock_right",
]
