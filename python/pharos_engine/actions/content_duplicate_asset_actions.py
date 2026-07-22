"""Content-browser duplicate action — clone a file / folder in-place.

Backs the ``content.duplicate_asset``
:class:`~pharos_engine.tool_router.ToolAction` row added by the II5
STUB-triage sprint tick (round 11 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1).

Duplicates the file or directory at ``ctx["path"]`` in the same parent
directory with a ``_copy`` suffix appended before the extension:

* ``hero.png`` → ``hero_copy.png``.
* ``Sprites/`` → ``Sprites_copy/`` (directory-recursive via
  :func:`shutil.copytree`).
* Repeated duplicates auto-uniquify: ``hero.png`` → ``hero_copy.png``
  → ``hero_copy_2.png`` → ``hero_copy_3.png``.

Return contract
---------------

* ``{"status": "duplicated", "path": "<src>", "copy": "<dst>",
   "kind": "file" | "dir", "size": bytes | None}`` on success.
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent / empty.
* ``{"status": "not_found", "path": "<abs>"}`` when the source path
  doesn't exist on disk.
* ``{"status": "error", "message": "<...>"}`` on any OS error during
  the copy (permission denied, disk full, etc.).

Best-effort side effect on success:

* ``browser.refresh()`` when the browser exposes it.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_SUFFIX = "_copy"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_browser(ctx: dict[str, Any]) -> Any:
    """Resolve a content-browser handle from *ctx*."""
    browser = ctx.get("browser")
    if browser is not None:
        return browser
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_content_browser", None)


def _dir_size(path: Path) -> int | None:
    """Return the aggregate byte count of *path* (best-effort)."""
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


def _build_copy_name(src: Path, suffix: str) -> str:
    """Return the initial candidate copy name for *src*.

    For files, splices ``suffix`` *before* the extension:
    ``hero.png`` → ``hero_copy.png``. Multi-suffix paths (``.tar.gz``)
    are handled naively — only the last extension is preserved so
    ``foo.tar.gz`` → ``foo.tar_copy.gz`` (matches Explorer semantics).

    For directories, appends ``suffix`` to the folder name:
    ``Sprites`` → ``Sprites_copy``.
    """
    if src.is_dir():
        return f"{src.name}{suffix}"
    stem = src.stem
    ext = src.suffix  # includes the leading dot
    return f"{stem}{suffix}{ext}"


def _uniquify(parent: Path, base_name: str, suffix: str) -> str:
    """Return a name that doesn't already exist under *parent*.

    First attempt: *base_name* (already suffixed). On collision, injects
    ``_2`` / ``_3`` / ... before the extension:
    ``hero_copy.png`` → ``hero_copy_2.png`` → ``hero_copy_3.png``.
    """
    if not (parent / base_name).exists():
        return base_name

    p = Path(base_name)
    stem = p.stem
    ext = p.suffix
    counter = 2
    while counter < 1000:
        candidate = f"{stem}_{counter}{ext}"
        if not (parent / candidate).exists():
            return candidate
        counter += 1
    return base_name  # last resort — caller will hit FileExistsError


def duplicate_asset(ctx: dict[str, Any]) -> dict[str, Any]:
    """Duplicate the file / directory at ``ctx["path"]`` in-place.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (str / Path): source file or directory. Required.
        * ``shell`` (optional): editor shell (used to resolve the
          content browser for the refresh side effect).
        * ``browser`` (optional): direct content-browser override.
        * ``suffix`` (optional str, default ``"_copy"``): suffix
          injected before the source extension (files) or appended to
          the folder name (directories).

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("duplicate_asset", ctx)

    raw_path = ctx.get("path")
    if not raw_path:
        return {"status": "missing_path"}
    src = Path(raw_path)
    if not src.exists():
        return {"status": "not_found", "path": str(src)}

    raw_suffix = ctx.get("suffix", _DEFAULT_SUFFIX)
    if not isinstance(raw_suffix, str) or not raw_suffix:
        suffix = _DEFAULT_SUFFIX
    else:
        suffix = raw_suffix

    parent = src.parent
    initial = _build_copy_name(src, suffix)
    final_name = _uniquify(parent, initial, suffix)
    dst = parent / final_name

    is_dir = src.is_dir()
    try:
        if is_dir:
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    except FileExistsError:
        # Race: retry with fresh uniquify.
        final_name = _uniquify(parent, initial, suffix)
        dst = parent / final_name
        try:
            if is_dir:
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    if is_dir:
        size: int | None = _dir_size(dst)
        kind = "dir"
    else:
        try:
            size = dst.stat().st_size
        except OSError:
            size = None
        kind = "file"

    # Best-effort refresh so the copy shows up.
    browser = _get_browser(ctx)
    if browser is not None:
        refresher = getattr(browser, "refresh", None)
        if callable(refresher):
            try:
                refresher()
            except Exception:  # noqa: BLE001
                pass

    return {
        "status": "duplicated",
        "path": str(src),
        "copy": str(dst),
        "name": final_name,
        "kind": kind,
        "size": size,
    }


__all__ = ["duplicate_asset"]
