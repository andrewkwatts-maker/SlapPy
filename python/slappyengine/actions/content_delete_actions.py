"""Content-browser delete action — modal-confirm + on-disk delete.

Backs the ``content.delete_asset`` :class:`~slappyengine.tool_router.ToolAction`
row added by the GG1 STUB-triage sprint tick (round 10 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1).

Flips row 243 (previously STUB, "delete handler defers to host callback
which may be unbound") into a first-class action. Deletes a file or a
directory (recursively) at ``ctx["path"]``, guarded behind an explicit
``ctx["confirmed"]`` flag so a click never trashes work without the
confirm-modal round trip.

Two behavioural modes are exposed:

* ``ctx["confirmed"] is not True`` (default): the helper returns a
  ``{"status": "confirm_required", "path": ..., "kind": "file"|"dir",
  "prompt": "...", "size": bytes | None}`` payload. The shell renders
  its confirmation modal, then re-invokes the action with
  ``confirmed=True``.
* ``ctx["confirmed"] is True``: performs the on-disk delete via
  :func:`Path.unlink` (files) or :func:`shutil.rmtree` (directories).

Return contract
---------------

* ``{"status": "confirm_required", ...}`` — see above.
* ``{"status": "deleted", "path": "<abs>", "kind": "file"|"dir",
   "size": bytes | None}`` on success.
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent / empty.
* ``{"status": "not_found", "path": "<abs>"}`` when the source path
  doesn't exist on disk.
* ``{"status": "error", "message": "<...>"}`` on any OS error during
  the delete (permission denied, in-use handle, etc.).

Best-effort side effects on success:

* ``browser.refresh()`` when the browser exposes it.
* ``shell._selected_asset_path`` cleared when it referenced the deleted
  path.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_browser(ctx: dict[str, Any]) -> Any:
    """Resolve a content-browser handle from *ctx*.

    Prefers ``ctx["browser"]`` over ``shell._content_browser``.
    """
    browser = ctx.get("browser")
    if browser is not None:
        return browser
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_content_browser", None)


def _dir_size(path: Path) -> int | None:
    """Return the aggregate byte count of *path* (best-effort).

    Returns ``None`` when the walk raises (permission denied etc.) so
    the caller can render a "size unknown" hint in the confirm modal
    without the delete flow blowing up.
    """
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    return None
    except OSError:
        return None
    return total


def _probe_size(path: Path) -> int | None:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return None
    if path.is_dir():
        return _dir_size(path)
    return None


def delete_asset(ctx: dict[str, Any]) -> dict[str, Any]:
    """Delete ``ctx["path"]`` — file or recursive directory.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (required str / Path): the asset path.
        * ``confirmed`` (optional bool): opt-in flag. When absent /
          falsy the helper returns a ``confirm_required`` payload
          instead of touching disk.
        * ``shell`` / ``browser`` (optional): refresh + selection
          clear hooks.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("delete_asset", ctx)
    raw_path = ctx.get("path")
    if not raw_path:
        return {"status": "missing_path"}

    target = Path(raw_path)
    if not target.exists():
        return {"status": "not_found", "path": str(target)}

    kind = "dir" if target.is_dir() else "file"
    size = _probe_size(target)

    if not ctx.get("confirmed"):
        if kind == "dir":
            prompt = (
                f"Delete folder \"{target.name}\" and everything inside "
                "it? This cannot be undone."
            )
        else:
            prompt = (
                f"Delete file \"{target.name}\"? This cannot be undone."
            )
        return {
            "status": "confirm_required",
            "path": str(target),
            "kind": kind,
            "prompt": prompt,
            "size": size,
        }

    try:
        if kind == "dir":
            shutil.rmtree(target)
        else:
            target.unlink()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    browser = _get_browser(ctx)
    if browser is not None:
        refresher = getattr(browser, "refresh", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:  # noqa: BLE001
                pass

    shell = _get_shell(ctx)
    if shell is not None:
        current = getattr(shell, "_selected_asset_path", None)
        if isinstance(current, str) and current == str(target):
            try:
                setattr(shell, "_selected_asset_path", None)
            except Exception:  # noqa: BLE001
                pass

    return {
        "status": "deleted",
        "path": str(target),
        "kind": kind,
        "size": size,
    }


__all__ = ["delete_asset"]
