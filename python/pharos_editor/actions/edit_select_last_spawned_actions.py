"""Selection action — pick the most recently spawned entity.

Backs the ``edit.select_last_spawned``
:class:`~pharos_editor.tool_router.ToolAction` row added by the AAA4
STUB-triage sprint tick (round 27 after ZZ4).

Distinct from the sibling selection-navigation verbs:

* YY4's ``edit.select_parent`` walks *one step* up the DAG.
* ZZ4's ``edit.select_root`` walks *all the way up* to the outermost
  ancestor.
* FF1's ``edit.select_children`` walks *down* to descendants.
* PP2's ``edit.select_next`` / ``edit.select_previous`` walk *sideways*
  through siblings.
* QQ1's ``selection.by_type`` / ``by_layer`` / ``same_material`` and
  WW4's ``edit.select_by_tag`` walk the *flat* scene by attribute.
* RR1's ``edit.select_similar`` walks by matching attributes.

This verb is the *temporal* selector — it snaps the selection onto
the entity that was most recently spawned into the scene. Matches
Blender's ``Ctrl+.`` (select last operator result) / Unity's
Ctrl+Shift+Insert (select newly-created) / Nova3D's Outliner
"Reselect Last Spawn" gesture.

Distinct from CC1's ``spawn.spawn_at_cursor`` etc. — those verbs
*create* a new entity; this verb *re-selects* whatever was created
most recently.

Last-spawned resolution
-----------------------

Search order:

1. ``ctx["entity"]`` — explicit override (tests use this).
2. ``shell._last_spawned_entity`` — canonical shell slot.
3. ``shell._spawn_history[-1]`` — legacy list fallback.
4. ``ctx["scene"]._last_spawned`` / ``shell._scene._last_spawned`` —
   scene-level fallback.

Modes
-----

* ``mode="replace"`` (default) — replace the selection. Matches
  Blender's ``Ctrl+.``.
* ``mode="add"`` — append to the existing selection. Matches Unity's
  Shift+Ctrl+Insert.

Return contract
---------------

* ``{"status": "selected", "entity": <ent>, "selection": [...]}`` —
  success.
* ``{"status": "no_spawn_history"}`` — nothing has been spawned yet
  and no override.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    return getattr(shell, "_scene", None)


def _resolve_last_spawned(ctx: dict[str, Any]) -> Any:
    """Return the last-spawned entity or ``None`` when unavailable."""
    override = ctx.get("entity")
    if override is not None:
        return override

    shell = _get_shell(ctx)
    if shell is not None:
        cand = getattr(shell, "_last_spawned_entity", None)
        if cand is not None:
            return cand
        history = getattr(shell, "_spawn_history", None)
        if isinstance(history, (list, tuple)) and history:
            return history[-1]

    scene = _get_scene(ctx)
    if scene is not None:
        cand = getattr(scene, "_last_spawned", None)
        if cand is not None:
            return cand
    return None


def _existing_selection(shell: Any) -> list[Any]:
    if shell is None:
        return []
    multi = getattr(shell, "_selected_entities", None)
    if isinstance(multi, (list, tuple)) and multi:
        return [x for x in multi if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _dedupe_by_identity(items: list[Any]) -> list[Any]:
    seen: set[int] = set()
    out: list[Any] = []
    for item in items:
        if id(item) in seen:
            continue
        seen.add(id(item))
        out.append(item)
    return out


def select_last_spawned(ctx: dict[str, Any]) -> dict[str, Any]:
    """Retarget the selection onto the most recently spawned entity.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell exposing
          ``_last_spawned_entity`` / ``_spawn_history`` and receiving
          the selection update.
        * ``scene`` (optional): scene override.
        * ``entity`` (optional): explicit last-spawned override.
        * ``mode`` (optional str): ``"replace"`` (default) or
          ``"add"``.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_last_spawned", ctx)
    entity = _resolve_last_spawned(ctx)
    if entity is None:
        return {"status": "no_spawn_history"}

    shell = _get_shell(ctx)
    mode = ctx.get("mode", "replace")
    if mode == "add":
        new_selection = _dedupe_by_identity(
            _existing_selection(shell) + [entity],
        )
    else:
        new_selection = [entity]

    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(new_selection))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entity", new_selection[0])
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "selected",
        "entity": entity,
        "selection": new_selection,
    }


__all__ = ["select_last_spawned"]
