"""Content-browser reveal-in-explorer action — highlight the item itself.

Backs the ``content.reveal_in_explorer``
:class:`~slappyengine.tool_router.ToolAction` row added by the SS1
STUB-triage sprint tick (round 20 after RR1's round-19
``edit.select_similar`` / ``theme.reset_to_default`` /
``layer.hide_others`` / ``layer.isolate`` / ``snap.toggle_incremental``
batch).

Distinct from the pre-existing ``content.reveal_in_folder`` fallback
(``_fb_reveal_in_folder`` in :mod:`slappyengine.tool_router`):

* ``content.reveal_in_folder`` opens the OS explorer at the given path
  (or its parent when a file is supplied) — the shell essentially calls
  ``os.startfile`` / ``xdg-open`` on whatever it gets.
* ``content.reveal_in_explorer`` **highlights the target itself**
  inside the explorer window: on Windows this is
  ``explorer /select,<path>``, on macOS ``open -R <path>``, on Linux
  the closest we can get is opening the parent directory (the free
  desktop specs do not standardise per-item selection).

Every DCC that ships a content browser exposes both verbs — Unity's
``Assets → Show in Explorer`` (selects) alongside the default
double-click (opens folder), Godot's ``Show in File Manager`` (selects
on Windows/macOS, opens folder on Linux), Substance Painter's ``Reveal
in Explorer``.

Return contract
---------------

* ``{"status": "revealed", "path": "<abs>", "platform": "<str>",
   "mode": "select" | "open_parent"}`` on success.
* ``{"status": "missing_path"}`` when ``ctx["path"]`` is absent / empty.
* ``{"status": "not_found", "path": "<abs>"}`` when the path does not
  exist on disk.
* ``{"status": "error", "message": "<...>"}`` when the underlying
  subprocess call raises.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from ._ctx import ensure_ctx


def _platform() -> str:
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _reveal_win(path: Path) -> str:
    """Open Windows Explorer with *path* selected.

    Uses ``explorer /select,<path>`` — the canonical Windows recipe.
    Explorer swallows its own exit code (returns 1 even on success)
    so we ignore the return value and rely on the caller checking
    that the process didn't raise.
    """
    subprocess.Popen(["explorer", f"/select,{path}"])
    return "select"


def _reveal_darwin(path: Path) -> str:
    """Reveal *path* selected in Finder — the ``open -R`` recipe."""
    subprocess.Popen(["open", "-R", str(path)])
    return "select"


def _reveal_linux(path: Path) -> str:
    """Open the parent directory of *path* — Linux desktops don't
    standardise a per-item select flag, so we degrade gracefully.

    The path is passed to ``xdg-open`` so whichever file manager the
    user has configured lights up. When *path* is a directory itself
    we open it; when it's a file we open its parent (matching the
    Godot / Unity Linux fallback path).
    """
    target = path if path.is_dir() else path.parent
    subprocess.Popen(["xdg-open", str(target)])
    return "open_parent"


def reveal_in_explorer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reveal ``ctx["path"]`` selected in the OS file explorer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``path`` (required, non-empty str / Path): item to reveal.
        * ``shell`` (optional): reserved for future browser-side
          highlight integration. Ignored for now.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("reveal_in_explorer", ctx)
    raw = ctx.get("path")
    if raw is None or (isinstance(raw, str) and not raw):
        return {"status": "missing_path"}
    path = Path(raw)
    if not path.exists():
        return {"status": "not_found", "path": str(path)}

    plat = _platform()
    try:
        if plat == "win32":
            mode = _reveal_win(path)
        elif plat == "darwin":
            mode = _reveal_darwin(path)
        else:
            mode = _reveal_linux(path)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    return {
        "status": "revealed",
        "path": str(path),
        "platform": plat,
        "mode": mode,
    }


__all__ = ["reveal_in_explorer"]
