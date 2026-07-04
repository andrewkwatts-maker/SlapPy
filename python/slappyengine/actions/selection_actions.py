"""Selection-lifecycle actions — select-all / deselect-all / copy / paste.

Backs four action ids added by the Y1 STUB-triage sprint tick:

* ``tool.select_all`` — flag every entity in the active scene as selected.
* ``tool.deselect_all`` — clear whatever selection the shell is tracking.
* ``editor.copy_selection`` — snapshot the current selection into the
  process-wide :class:`~slappyengine.ui.editor.entity_clipboard.EntityClipboard`.
* ``editor.paste_selection`` — pull the last-copied snapshots from the
  clipboard and hand them back so the caller can spawn fresh entities
  (best-effort ``scene.add`` when a live scene is reachable).

Every helper takes a single ``ctx: dict`` argument matching the router's
Python-fallback signature. They intentionally sidestep the DPG editor
shell and instead reach through ``ctx["shell"]`` / ``ctx["scene"]`` /
``ctx["clipboard"]`` handles so headless tests can drive the flow.

Return contract
---------------

* ``select_all`` — ``{"status": "selected", "count": N}``. When there is
  no reachable scene the helper returns
  ``{"status": "no_scene"}`` so the shell can flash a "no scene loaded"
  toast rather than crash.
* ``deselect_all`` — ``{"status": "deselected"}`` on success (including
  the "there was nothing to deselect" case, which is the intended UX for
  Ctrl+Shift+A).
* ``copy_selection`` — ``{"status": "copied", "count": N}`` on success,
  ``{"status": "no_selection"}`` when the shell is empty.
* ``paste_selection`` — ``{"status": "pasted", "count": N, "clones": [...]}``
  when at least one snapshot survives the paste;
  ``{"status": "empty_clipboard"}`` when nothing has been copied yet.
"""
from __future__ import annotations

from typing import Any


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a Scene handle from *ctx*.

    Search order:

    1. ``ctx["scene"]`` — direct override.
    2. ``ctx["shell"]._engine.scene`` — the shell's engine handle.
    3. ``ctx["shell"]._scene`` — legacy shell-owned scene attribute.
    """
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = getattr(engine, "scene", None) or getattr(engine, "_scene", None)
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _get_clipboard(ctx: dict[str, Any]) -> Any:
    """Resolve an :class:`EntityClipboard` from *ctx* (lazy import)."""
    clipboard = ctx.get("clipboard")
    if clipboard is not None:
        return clipboard
    try:
        from slappyengine.ui.editor.entity_clipboard import (
            get_active_clipboard,
        )
    except Exception:  # noqa: BLE001
        return None
    return get_active_clipboard()


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    """Return the entities backing the current selection as a list.

    Matches the search order used by
    :mod:`slappyengine.actions.edit_actions` so the two duplicate paths
    stay consistent.
    """
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _list_scene_entities(scene: Any) -> list[Any]:
    """Return every entity in *scene* as a list.

    Handles three surfaces:

    * :attr:`Scene.entities` — the canonical property on
      :class:`slappyengine.scene.Scene`.
    * ``scene._entities`` mapping — dict of id → entity.
    * ``scene.entities()`` callable — some tests / fakes expose a fn.
    """
    if scene is None:
        return []
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is None:
        raw = getattr(scene, "_entities", None)
        if isinstance(raw, dict):
            return list(raw.values())
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return []
    if callable(entities_attr):
        try:
            got = entities_attr()
        except Exception:  # noqa: BLE001
            return []
        return list(got) if got is not None else []
    # Property / list / tuple.
    try:
        return list(entities_attr)
    except TypeError:
        return []


def select_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """Flag every entity in the active scene as selected.

    Writes the full entity list onto ``shell._selected_entities`` (when a
    shell is present) so downstream panels (Outliner, Inspector) can pick
    it up. When only a single entity is present the singular
    ``shell._selected_entity`` slot is also populated so the legacy
    inspector hook still fires.

    Returns
    -------
    dict
        ``{"status": "selected", "count": N}`` on success. When no scene
        is reachable returns ``{"status": "no_scene"}``.
    """
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    entities = _list_scene_entities(scene)
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(entities))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(
                shell,
                "_selected_entity",
                entities[0] if entities else None,
            )
        except Exception:  # noqa: BLE001
            pass
    return {"status": "selected", "count": len(entities)}


def deselect_all(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drop whatever selection the shell is tracking.

    Clears both the singular ``_selected_entity`` slot and the plural
    ``_selected_entities`` list so the two views agree.
    """
    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entity", None)
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entities", [])
        except Exception:  # noqa: BLE001
            pass
    return {"status": "deselected"}


def copy_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the current selection into the shared :class:`EntityClipboard`.

    Unlike ``edit.duplicate_selection`` this does NOT auto-paste — it
    only stashes the copies so a subsequent ``editor.paste_selection`` /
    ``Ctrl+V`` can consume them.
    """
    entities = _resolve_selection(ctx)
    if not entities:
        return {"status": "no_selection"}
    clipboard = _get_clipboard(ctx)
    if clipboard is None:
        return {"status": "error", "message": "clipboard unavailable"}
    try:
        n = clipboard.copy(entities)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    return {"status": "copied", "count": n}


def paste_selection(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return deep-copies of the last-copied snapshots + spawn them.

    Pulls from the process-wide clipboard (or ``ctx["clipboard"]`` when
    overridden). When a live scene is reachable via ``ctx["scene"]`` or
    the shell handle, each clone dict is best-effort-added via
    ``scene.add(...)`` — but a missing scene is silently allowed so
    headless tests can still exercise the fallback.

    Returns
    -------
    dict
        ``{"status": "pasted", "count": N, "clones": [...]}`` on success,
        ``{"status": "empty_clipboard"}`` when the clipboard has no
        snapshots yet.
    """
    clipboard = _get_clipboard(ctx)
    if clipboard is None:
        return {"status": "error", "message": "clipboard unavailable"}
    if clipboard.is_empty():
        return {"status": "empty_clipboard"}
    suffix = ctx.get("name_suffix", " (paste)")
    try:
        clones = clipboard.paste(name_suffix=suffix)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    added = 0
    scene = _get_scene(ctx)
    if scene is not None:
        # Try the two common scene-add entry points.
        adder = getattr(scene, "add_entity", None) or getattr(scene, "add", None)
        if callable(adder):
            for clone in clones:
                try:
                    adder(clone)
                    added += 1
                except Exception:  # noqa: BLE001
                    # Scenes that reject dict-shaped entities are fine —
                    # the clone still round-trips through the clipboard.
                    pass
    return {
        "status": "pasted",
        "count": len(clones),
        "clones": clones,
        "added": added,
    }


__all__ = [
    "select_all",
    "deselect_all",
    "copy_selection",
    "paste_selection",
]
