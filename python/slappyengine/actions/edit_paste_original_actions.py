"""Paste-at-original-position action — paste without cursor offset.

Backs the ``edit.paste_at_original_position``
:class:`~slappyengine.tool_router.ToolAction` row added by the II5
STUB-triage sprint tick (round 11 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1).

Sibling to :func:`slappyengine.actions.selection_actions.paste_selection`.
Where the plain ``editor.paste_selection`` applies a ``" (paste)"``
name suffix (and, in some shells, an offset so the copy appears next to
the cursor), this variant preserves the **exact** position from the
snapshot — i.e. copy → paste-in-place produces a clone sitting at the
original coordinate. Illustrator ``Cmd+Shift+V`` / Photoshop
``Shift+Ctrl+V`` / Blender ``Alt+V`` semantics.

Behavioural notes
-----------------

* **Name suffix** — defaults to ``" (copy)"`` so the outliner can still
  tell the paste-site from the source. Pass ``ctx["name_suffix"] = ""``
  to preserve the original name unchanged.
* **Position preservation** — each snapshot's ``position`` / ``origin`` /
  ``pos`` field is left untouched. The default paste path *never* mutates
  positions, so this variant is really about the *name* + a distinct
  status string so callers can render "pasted at original position"
  toasts instead of the generic "pasted".
* **Scene add** — same best-effort ``scene.add_entity`` /
  ``scene.add`` walk as ``paste_selection``. Silently no-ops when no
  scene is reachable so headless callers can drive the clipboard alone.

Return contract
---------------

* ``{"status": "pasted_at_original", "count": N, "clones": [...],
   "added": M}`` on success.
* ``{"status": "empty_clipboard"}`` when the clipboard has no snapshots
  yet.
* ``{"status": "error", "message": "<...>"}`` when clipboard access
  raises or the paste itself blows up.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .selection_actions import _get_clipboard, _get_scene


def paste_at_original_position(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return deep-copies of the clipboard snapshots preserving their
    original positions.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell. Used only to resolve a
          scene for the best-effort add step.
        * ``scene`` (optional): explicit scene override.
        * ``clipboard`` (optional): explicit
          :class:`~slappyengine.ui.editor.entity_clipboard.EntityClipboard`
          override — bypasses the process-wide singleton.
        * ``name_suffix`` (optional str, default ``" (copy)"``): suffix
          appended to the ``"name"`` field of each clone. Pass ``""`` to
          preserve the original name.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("paste_at_original_position", ctx)
    clipboard = _get_clipboard(ctx)
    if clipboard is None:
        return {"status": "error", "message": "clipboard unavailable"}
    if clipboard.is_empty():
        return {"status": "empty_clipboard"}

    suffix = ctx.get("name_suffix", " (copy)")
    if not isinstance(suffix, str):
        suffix = " (copy)"

    try:
        clones = clipboard.paste(name_suffix=suffix)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    # Positions on the snapshots are already the source coordinates —
    # no mutation needed. This helper's contract is: *do not offset*.

    added = 0
    scene = _get_scene(ctx)
    if scene is not None:
        adder = (
            getattr(scene, "add_entity", None)
            or getattr(scene, "add", None)
        )
        if callable(adder):
            for clone in clones:
                try:
                    adder(clone)
                    added += 1
                except Exception:  # noqa: BLE001
                    pass

    return {
        "status": "pasted_at_original",
        "count": len(clones),
        "clones": clones,
        "added": added,
    }


__all__ = ["paste_at_original_position"]
