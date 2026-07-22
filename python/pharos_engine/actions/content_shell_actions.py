"""Content-browser shell integrations — clipboard copy of asset path.

Backs the ``content.copy_asset_path`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the CC1 STUB-triage sprint tick.

The action prefers routing through
:meth:`pharos_engine.ui.editor.notebook_content_browser.NotebookContentBrowser.copy_path`
when the shell owns a content-browser handle (that method already
walks the DPG / pyperclip / tkinter fallback chain and returns the
string it placed on the clipboard). When no content browser is
reachable the helper still tries the same fallback chain directly so
headless callers (and tests) can drive the action.

Return contract
---------------

* ``{"status": "copied", "path": str, "backend": <str>}`` on success.
  ``backend`` is one of ``"browser"``, ``"pyperclip"``, ``"tkinter"``,
  ``"noop"`` — the last means "the fallback ran but no clipboard was
  available; text was still returned so tests can assert on it".
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent or
  empty. Protects against accidental dispatches from empty context
  menus.

Note: this is deliberately narrower than ``content.reveal_in_folder``
(``_fb_reveal_in_folder``) which opens the OS file explorer at the
path. ``copy_asset_path`` never spawns a subprocess — it only mutates
the OS clipboard.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_browser(ctx: dict[str, Any]) -> Any:
    """Resolve a content-browser handle from *ctx*.

    Prefers ``ctx["browser"]`` override (tests) over
    ``shell._content_browser``.
    """
    browser = ctx.get("browser")
    if browser is not None:
        return browser
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_content_browser", None)


def _fallback_copy(text: str) -> str:
    """Copy *text* to the OS clipboard via the pyperclip / tkinter chain.

    Silently degrades to a no-op when neither is importable. Returns
    the backend that succeeded (``"pyperclip"`` / ``"tkinter"`` /
    ``"noop"``).
    """
    try:
        import pyperclip  # type: ignore[import-not-found]
        pyperclip.copy(text)
        return "pyperclip"
    except Exception:  # noqa: BLE001
        pass
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return "tkinter"
    except Exception:  # noqa: BLE001
        pass
    return "noop"


def copy_asset_path(ctx: dict[str, Any]) -> dict[str, Any]:
    """Copy the asset at ``ctx["path"]`` to the OS clipboard.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (required, non-empty): the asset path to copy.
          Accepts a plain ``str`` or a ``pathlib.Path`` — the string
          coercion happens here so downstream callers don't need to
          normalize.
        * ``shell`` (optional): editor shell. When present its
          ``_content_browser.copy_path`` is preferred over the
          fallback chain.
        * ``browser`` (optional): direct content-browser override
          (tests use this).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("copy_asset_path", ctx)
    raw = ctx.get("path")
    if raw is None:
        return {"status": "missing_path"}
    text = str(raw)
    if not text:
        return {"status": "missing_path"}
    browser = _get_browser(ctx)
    if browser is not None:
        method = getattr(browser, "copy_path", None)
        if callable(method):
            try:
                returned = method(raw)
            except Exception:  # noqa: BLE001
                returned = None
            if isinstance(returned, str):
                return {
                    "status": "copied",
                    "path": returned,
                    "backend": "browser",
                }
    # No browser (or its copy_path returned nothing usable) — run
    # the fallback chain directly.
    backend = _fallback_copy(text)
    return {"status": "copied", "path": text, "backend": backend}


__all__ = ["copy_asset_path"]
