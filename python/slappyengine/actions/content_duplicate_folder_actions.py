"""Content-browser duplicate-folder action — clone a directory.

Backs the ``content.duplicate_folder``
:class:`~slappyengine.tool_router.ToolAction` row added by the SS1
STUB-triage sprint tick (round 20).

Distinct from II5's ``content.duplicate_asset`` (which handles files
*and* directories transparently). The folder-only verb is exposed as a
separate action id because:

1. Explorer / Finder / Unity all bind a *dedicated* "Duplicate Folder"
   right-click item (visually distinct from "Duplicate" on files) —
   projects assume the two verbs are addressable separately.
2. Refusing to duplicate a file surfaces a clear ``not_a_folder``
   result the caller can toast (rather than silently deep-copying a
   large scene binary the user meant to leave alone).
3. Directory duplication has stricter uniquify semantics (folder names
   don't have extensions) — keeping the code path separate avoids the
   file-side stem/ext splicing.

Return contract
---------------

* ``{"status": "duplicated", "path": "<src>", "copy": "<dst>",
   "name": "<final>", "size": bytes | None, "file_count": N}`` on
  success.
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent /
  empty.
* ``{"status": "not_found", "path": "<abs>"}`` when the source path
  doesn't exist.
* ``{"status": "not_a_folder", "path": "<abs>"}`` when the source
  exists but is a file (caller should route to
  ``content.duplicate_asset`` instead).
* ``{"status": "error", "message": "<...>"}`` on any OS error during
  the copy.
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
    browser = ctx.get("browser")
    if browser is not None:
        return browser
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_content_browser", None)


def _dir_size_and_count(path: Path) -> tuple[int | None, int]:
    """Return ``(byte_total, file_count)`` for *path* (best-effort)."""
    total = 0
    count = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                count += 1
                try:
                    total += child.stat().st_size
                except OSError:
                    return (None, count)
    except OSError:
        return (None, count)
    return (total, count)


def _uniquify(parent: Path, base_name: str) -> str:
    """Return a folder name that doesn't already exist under *parent*.

    ``Sprites_copy`` → ``Sprites_copy`` when free; on collision walks
    ``Sprites_copy_2`` / ``Sprites_copy_3`` / ... capped at 999.
    """
    if not (parent / base_name).exists():
        return base_name
    counter = 2
    while counter < 1000:
        candidate = f"{base_name}_{counter}"
        if not (parent / candidate).exists():
            return candidate
        counter += 1
    return base_name


def duplicate_folder(ctx: dict[str, Any]) -> dict[str, Any]:
    """Duplicate the directory at ``ctx["path"]`` in-place.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (str / Path, required): source directory.
        * ``shell`` (optional): editor shell (used to resolve the
          content browser for the refresh side effect).
        * ``browser`` (optional): direct content-browser override.
        * ``suffix`` (optional str, default ``"_copy"``): appended to
          the source folder name to build the target name.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("duplicate_folder", ctx)

    raw_path = ctx.get("path")
    if not raw_path:
        return {"status": "missing_path"}
    src = Path(raw_path)
    if not src.exists():
        return {"status": "not_found", "path": str(src)}
    if not src.is_dir():
        return {"status": "not_a_folder", "path": str(src)}

    raw_suffix = ctx.get("suffix", _DEFAULT_SUFFIX)
    if not isinstance(raw_suffix, str) or not raw_suffix:
        suffix = _DEFAULT_SUFFIX
    else:
        suffix = raw_suffix

    parent = src.parent
    base_name = f"{src.name}{suffix}"
    final_name = _uniquify(parent, base_name)
    dst = parent / final_name
    try:
        shutil.copytree(src, dst)
    except FileExistsError:
        # Race: retry with fresh uniquify.
        final_name = _uniquify(parent, base_name)
        dst = parent / final_name
        try:
            shutil.copytree(src, dst)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    size, file_count = _dir_size_and_count(dst)

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
        "size": size,
        "file_count": file_count,
    }


__all__ = ["duplicate_folder"]
