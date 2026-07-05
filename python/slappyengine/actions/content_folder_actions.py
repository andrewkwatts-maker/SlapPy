"""Content-browser folder actions — create a new sub-directory.

Backs the ``content.new_folder`` :class:`~slappyengine.tool_router.ToolAction`
row added by the FF1 STUB-triage sprint tick (round 9 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1).

Creates a fresh directory beneath the resolved content-browser root
(or an explicit ``ctx["parent"]`` path). When the requested name is
missing or empty the helper synthesises ``"New Folder"`` (matching the
Explorer / Finder default). If a collision would result the name is
uniquified with a ``" (2)"`` / ``" (3)"`` suffix so back-to-back clicks
don't stomp existing directories.

The action deliberately does *not* spawn a modal — the shell / content
browser is expected to prompt for a name and pass it through
``ctx["name"]``. When ``name`` is absent the default ``"New Folder"``
lands and the shell can rely on the subsequent
``content.rename_asset`` flow (:mod:`content_rename_actions`) to make
the user's choice stick.

Return contract
---------------

* ``{"status": "created", "path": "<abs>", "name": "<final>",
   "parent": "<abs>"}`` on success.
* ``{"status": "no_parent"}`` when neither ``ctx["parent"]`` nor the
  browser's ``root_path`` is reachable.
* ``{"status": "parent_missing", "parent": "<abs>"}`` when the resolved
  parent does not exist on disk (headless test using a stale path).
* ``{"status": "error", "message": "<...>"}`` when the underlying
  ``Path.mkdir`` raises for any other reason (permission denied etc.).

The helper also refreshes the content browser (``browser.refresh()``
when exposed) so the new folder shows up without an explicit reload.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_NAME = "New Folder"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_browser(ctx: dict[str, Any]) -> Any:
    """Resolve a content-browser handle from *ctx*.

    Prefers explicit ``ctx["browser"]`` over ``shell._content_browser``.
    """
    browser = ctx.get("browser")
    if browser is not None:
        return browser
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_content_browser", None)


def _resolve_parent(ctx: dict[str, Any]) -> Path | None:
    """Return the parent directory as a :class:`Path` (or ``None``).

    Resolution order:

    1. ``ctx["parent"]`` — explicit override (tests + right-click menu).
    2. ``browser.current_path`` — the browser's current viewing directory.
    3. ``browser.root_path`` — the browser's root directory.
    4. ``shell._content_root`` — legacy attribute on some shells.
    """
    raw = ctx.get("parent")
    if raw:
        return Path(raw)
    browser = _get_browser(ctx)
    if browser is not None:
        for key in ("current_path", "root_path"):
            candidate = getattr(browser, key, None)
            if candidate:
                return Path(candidate)
    shell = _get_shell(ctx)
    if shell is not None:
        candidate = getattr(shell, "_content_root", None)
        if candidate:
            return Path(candidate)
    return None


def _uniquify(parent: Path, name: str) -> str:
    """Return a name that does not currently exist under *parent*.

    ``"foo"`` → ``"foo"`` when free; ``"foo (2)"`` on first collision;
    ``"foo (3)"`` on the second collision, etc. Bounded at 999 attempts
    so a mis-configured filesystem can never spin the helper forever.
    """
    candidate = name
    counter = 2
    while (parent / candidate).exists() and counter < 1000:
        candidate = f"{name} ({counter})"
        counter += 1
    return candidate


def new_folder(ctx: dict[str, Any]) -> dict[str, Any]:
    """Create a new sub-directory beneath the browser's current path.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell (used to resolve the
          content browser).
        * ``browser`` (optional): direct content-browser override —
          bypasses ``shell._content_browser``.
        * ``parent`` (optional str / Path): override the parent
          directory. Otherwise resolved from the browser.
        * ``name`` (optional str): folder name. Defaults to
          ``"New Folder"`` on empty / missing input.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("new_folder", ctx)
    parent = _resolve_parent(ctx)
    if parent is None:
        return {"status": "no_parent"}
    if not parent.exists():
        return {"status": "parent_missing", "parent": str(parent)}

    raw_name = ctx.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        name = _DEFAULT_NAME
    else:
        name = raw_name.strip()

    final_name = _uniquify(parent, name)
    target = parent / final_name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        # Race: another process just created it. Uniquify again.
        final_name = _uniquify(parent, name)
        target = parent / final_name
        try:
            target.mkdir(parents=False, exist_ok=False)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Best-effort browser refresh so the new folder shows up.
    browser = _get_browser(ctx)
    if browser is not None:
        refresher = getattr(browser, "refresh", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:  # noqa: BLE001
                pass

    return {
        "status": "created",
        "path": str(target),
        "name": final_name,
        "parent": str(parent),
    }


__all__ = ["new_folder"]
