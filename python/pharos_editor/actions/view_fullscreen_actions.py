"""Viewport-fullscreen action — hide chrome, maximise viewport.

Backs the ``view.fullscreen`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the GG1 STUB-triage sprint tick (round 10 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1).

Toggles a "focus-mode" fullscreen where every side / bottom / top panel
is hidden and the viewport panel is expanded to the full viewport
rectangle. Complementary to the existing ``F11`` OS-level fullscreen
(``editor.toggle_fullscreen`` / ``shell.toggle_fullscreen``) — where
that action toggles the OS window chrome, this one toggles the *editor
chrome*: menu bar / toolbar / status bar / every non-viewport panel.

Behavioural modes
-----------------

* ``mode="toggle"`` (default) — flip the current fullscreen state.
* ``mode="enter"`` — snapshot the current chrome state and hide it.
  No-op if already in fullscreen.
* ``mode="exit"`` — restore the snapshot and re-show every chrome
  element. No-op if not in fullscreen.

Snapshot storage
----------------

The pre-fullscreen state is stashed on
``shell._fullscreen_snapshot``: a dict shaped as::

    {
        "chrome": {"menu_bar": True, "toolbar": True, ...},
        "panels": ["outliner", "inspector", ...],  # panels that were visible
    }

On exit the snapshot is popped and every recorded chrome / panel id
is toggled back on.

Return contract
---------------

* ``{"status": "entered", "chrome_hidden": [...], "panels_hidden": [...]}``
  — entered fullscreen.
* ``{"status": "exited", "chrome_shown": [...], "panels_shown": [...]}``
  — exited fullscreen.
* ``{"status": "already_fullscreen"}`` — enter called while in FS.
* ``{"status": "not_fullscreen"}`` — exit called while not in FS.
* ``{"status": "no_shell"}`` — no shell reachable via ctx.
"""
from __future__ import annotations

from typing import Any

from . import panel_visibility_actions as _pv
from ._ctx import ensure_ctx


# Canonical chrome element ids. Each corresponds to a shell attribute
# ``_<id>_visible`` that renders code observes.
_CHROME_IDS: tuple[str, ...] = (
    "menu_bar",
    "toolbar",
    "status_bar",
    "left_sidebar",
    "right_sidebar",
)


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _is_fullscreen(shell: Any) -> bool:
    return bool(getattr(shell, "_fullscreen_snapshot", None))


def _chrome_ids(ctx: dict[str, Any]) -> list[str]:
    override = ctx.get("chrome")
    if isinstance(override, (list, tuple)) and override:
        return [str(x) for x in override if isinstance(x, str)]
    return list(_CHROME_IDS)


def _chrome_attr(chrome_id: str) -> str:
    return f"_{chrome_id}_visible"


def _get_chrome_visible(shell: Any, chrome_id: str) -> bool:
    """Return the current visibility of *chrome_id* on *shell*.

    Prefers ``shell.is_chrome_visible(chrome_id)`` when exposed; falls
    back to the ``_<id>_visible`` attribute. Defaults to ``True`` — the
    shell's post-init state.
    """
    getter = getattr(shell, "is_chrome_visible", None)
    if callable(getter):
        try:
            return bool(getter(chrome_id))
        except Exception:  # noqa: BLE001
            pass
    return bool(getattr(shell, _chrome_attr(chrome_id), True))


def _set_chrome_visible(
    shell: Any, chrome_id: str, visible: bool,
) -> bool:
    """Apply *visible* to *chrome_id* on *shell*.

    Route order:

    1. ``shell.set_chrome_visible(id, visible)`` — canonical setter.
    2. ``shell._<id>_visible`` attribute set.

    Best-effort — a shell that exposes neither returns ``False`` so
    the caller can note the chrome id in the "failed" bucket without
    the fullscreen flow blowing up.
    """
    setter = getattr(shell, "set_chrome_visible", None)
    if callable(setter):
        try:
            setter(chrome_id, visible)
            return True
        except Exception:  # noqa: BLE001
            pass
    try:
        setattr(shell, _chrome_attr(chrome_id), bool(visible))
        return True
    except Exception:  # noqa: BLE001
        return False


def _enter_fullscreen(
    shell: Any, ctx: dict[str, Any],
) -> dict[str, Any]:
    """Snapshot + hide every chrome element and non-viewport panel."""
    chrome_snapshot: dict[str, bool] = {}
    chrome_hidden: list[str] = []
    for cid in _chrome_ids(ctx):
        chrome_snapshot[cid] = _get_chrome_visible(shell, cid)
        if chrome_snapshot[cid]:
            if _set_chrome_visible(shell, cid, False):
                chrome_hidden.append(cid)

    panels_hidden: list[str] = []
    for pid in _pv._panel_ids(ctx):
        if pid in _pv._SKIP_IDS:
            continue
        if not _pv._is_visible(shell, pid):
            continue
        if _pv._set_panel_visibility(shell, pid, False):
            panels_hidden.append(pid)

    snapshot = {
        "chrome": chrome_snapshot,
        "panels": list(panels_hidden),
    }
    try:
        setattr(shell, "_fullscreen_snapshot", snapshot)
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "entered",
        "chrome_hidden": chrome_hidden,
        "panels_hidden": panels_hidden,
    }


def _exit_fullscreen(shell: Any) -> dict[str, Any]:
    """Pop the snapshot + re-show every recorded chrome / panel id."""
    snapshot = getattr(shell, "_fullscreen_snapshot", None)
    if not isinstance(snapshot, dict):
        return {"status": "not_fullscreen"}

    chrome_shown: list[str] = []
    for cid, was_visible in snapshot.get("chrome", {}).items():
        if was_visible and _set_chrome_visible(shell, cid, True):
            chrome_shown.append(cid)

    panels_shown: list[str] = []
    for pid in snapshot.get("panels", []):
        if _pv._set_panel_visibility(shell, pid, True):
            panels_shown.append(pid)

    try:
        setattr(shell, "_fullscreen_snapshot", None)
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "exited",
        "chrome_shown": chrome_shown,
        "panels_shown": panels_shown,
    }


def fullscreen(ctx: dict[str, Any]) -> dict[str, Any]:
    """Toggle / enter / exit fullscreen focus mode.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (required): editor shell.
        * ``mode`` (optional str): ``"toggle"`` (default) / ``"enter"``
          / ``"exit"``.
        * ``chrome`` (optional list[str]): chrome-id roster override.
        * ``panels`` (optional list[str]): panel-roster override —
          same key as :mod:`panel_visibility_actions`.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("fullscreen", ctx)
    shell = _get_shell(ctx)
    if shell is None:
        return {"status": "no_shell"}

    mode = ctx.get("mode", "toggle")
    in_fs = _is_fullscreen(shell)

    if mode == "enter":
        if in_fs:
            return {"status": "already_fullscreen"}
        return _enter_fullscreen(shell, ctx)
    if mode == "exit":
        if not in_fs:
            return {"status": "not_fullscreen"}
        return _exit_fullscreen(shell)

    # Toggle.
    if in_fs:
        return _exit_fullscreen(shell)
    return _enter_fullscreen(shell, ctx)


__all__ = ["fullscreen"]
