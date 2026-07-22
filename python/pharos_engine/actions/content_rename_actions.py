"""Content-browser rename action — rename a file or folder on disk.

Backs the ``content.rename_asset`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the FF1 STUB-triage sprint tick (round 9 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1).

Renames ``ctx["path"]`` to a sibling ``ctx["new_name"]``. Preserves the
existing file extension unless *new_name* itself carries one (this
matches Windows Explorer / macOS Finder behaviour — typing "foo" for a
file called "bar.png" produces "foo.png"). Directories skip the
extension-preservation step so ``"Old Folder"`` → ``"New Folder"`` isn't
mangled into ``"New Folder.Folder"``.

Return contract
---------------

* ``{"status": "renamed", "old_path": "<abs>", "new_path": "<abs>",
   "old_name": "<basename>", "new_name": "<basename>"}`` on success.
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent / empty.
* ``{"status": "missing_new_name"}`` when ``ctx["new_name"]`` is absent
  / empty.
* ``{"status": "not_found", "path": "<abs>"}`` when the source path
  doesn't exist on disk.
* ``{"status": "collision", "path": "<abs>"}`` when the target already
  exists and ``ctx["overwrite"]`` is not truthy.
* ``{"status": "invalid_name", "name": str}`` when the new name contains
  a path separator (``os.sep`` / ``/``) — prevents the "rename" flow
  from silently doing a "move".
* ``{"status": "error", "message": "<...>"}`` on any other OS error.

The helper also refreshes the content browser (``browser.refresh()``
when exposed) and retargets ``shell._selected_asset_path`` at the new
path so a subsequent double-click / inspector refresh sticks.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


_INVALID_CHARS = ("/", "\\")


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


def _resolve_new_name(src: Path, requested: str) -> str:
    """Merge the requested new name with *src*'s extension policy.

    * Directories: pass ``requested`` through untouched.
    * Files where ``requested`` already carries a suffix
      (``requested.endswith(src.suffix)``, or ``Path(requested).suffix``
      is non-empty): pass through.
    * Otherwise: append ``src.suffix`` so ``"foo"`` → ``"foo.png"``
      when *src* is ``bar.png``.
    """
    if src.is_dir():
        return requested
    requested_suffix = Path(requested).suffix
    if requested_suffix:
        return requested
    if src.suffix:
        return requested + src.suffix
    return requested


def rename_asset(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rename ``ctx["path"]`` to a sibling ``ctx["new_name"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (required str / Path): the current asset path.
        * ``new_name`` (required str): the new *basename* (not a full
          path). May optionally include an extension.
        * ``overwrite`` (optional bool): allow overwriting an existing
          sibling. Defaults to ``False``.
        * ``shell`` / ``browser`` (optional): refresh + retarget hooks.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("rename_asset", ctx)
    raw_path = ctx.get("path")
    if not raw_path:
        return {"status": "missing_path"}
    raw_new = ctx.get("new_name")
    if not isinstance(raw_new, str) or not raw_new.strip():
        return {"status": "missing_new_name"}

    new_name = raw_new.strip()
    # Reject anything that looks like a path segment — "rename" should
    # never accidentally move.
    for bad in _INVALID_CHARS:
        if bad in new_name:
            return {"status": "invalid_name", "name": new_name}

    src = Path(raw_path)
    if not src.exists():
        return {"status": "not_found", "path": str(src)}

    final_name = _resolve_new_name(src, new_name)
    dst = src.parent / final_name

    if dst == src:
        # No-op rename — silently succeed so the caller doesn't have to
        # special-case "user pressed Enter without editing".
        return {
            "status": "renamed",
            "old_path": str(src),
            "new_path": str(dst),
            "old_name": src.name,
            "new_name": dst.name,
        }

    if dst.exists() and not ctx.get("overwrite"):
        return {"status": "collision", "path": str(dst)}

    try:
        os.replace(src, dst) if ctx.get("overwrite") else src.rename(dst)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Best-effort browser refresh + selection retarget.
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
        try:
            setattr(shell, "_selected_asset_path", str(dst))
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "renamed",
        "old_path": str(src),
        "new_path": str(dst),
        "old_name": src.name,
        "new_name": dst.name,
    }


__all__ = ["rename_asset"]
