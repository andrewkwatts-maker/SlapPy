"""Select-by-name action — jump editor selection to a named entity.

Backs the ``edit.select_by_name`` :class:`~pharos_engine.tool_router.ToolAction`
row added by the CC1 STUB-triage sprint tick (round 6 after
X3 / Y1 / Z7 / AA1 / BB1).

The action is deliberately narrower than
:mod:`pharos_engine.actions.selection_actions.select_all`: it walks the
active scene, matches every entity whose ``name`` attribute equals
``ctx["name"]``, then writes the match onto the shell's selection slots
(``_selected_entity`` for the singular slot, ``_selected_entities`` for
the plural list). When multiple entities share the same name (a legal
state for Bullet Strata's cloned pickup icons) every match is captured
in the plural list and the *first* match is promoted to the singular
slot so the inspector still updates.

Return contract
---------------

* ``{"status": "selected", "count": N, "entity_ids": [..]}`` on success
  — ``count`` is always ``≥ 1``.
* ``{"status": "not_found", "name": str}`` when no entity in the scene
  has the requested name. The shell can flash a "No entity named X"
  toast without further probing.
* ``{"status": "no_scene"}`` when no scene handle can be resolved from
  ``ctx`` (mirrors the selection_actions convention).
* ``{"status": "missing_name"}`` when ``ctx["name"]`` is absent or empty
  — protects against accidental dispatches from empty-string entry
  widgets.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_scene(ctx: dict[str, Any]) -> Any:
    """Resolve a Scene handle from *ctx* — mirrors selection_actions."""
    scene = ctx.get("scene")
    if scene is not None:
        return scene
    shell = _get_shell(ctx)
    if shell is None:
        return None
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        scene = (
            getattr(engine, "scene", None)
            or getattr(engine, "_scene", None)
        )
        if scene is not None:
            return scene
    return getattr(shell, "_scene", None)


def _find_by_name(scene: Any, name: str) -> list[Any]:
    """Return every entity in *scene* whose ``.name`` equals *name*.

    Handles three surfaces:

    * :meth:`Scene.find_by_name` — the canonical entry point.
    * ``scene._entities`` dict of id -> entity — direct walk.
    * ``scene.entities`` list/tuple/property — plain walk.
    """
    finder = getattr(scene, "find_by_name", None)
    if callable(finder):
        try:
            got = finder(name)
        except Exception:  # noqa: BLE001
            got = None
        if got is not None:
            try:
                return list(got)
            except TypeError:
                return []
    # Fall back to a manual sweep.
    raw = getattr(scene, "_entities", None)
    if isinstance(raw, dict):
        pool = list(raw.values())
    else:
        entities_attr = getattr(scene, "entities", None)
        if callable(entities_attr):
            try:
                pool = list(entities_attr())
            except Exception:  # noqa: BLE001
                return []
        elif entities_attr is None:
            return []
        else:
            try:
                pool = list(entities_attr)
            except TypeError:
                return []
    return [e for e in pool if getattr(e, "name", None) == name]


def _entity_id(entity: Any) -> str:
    """Return the entity id or a fallback repr — best-effort."""
    eid = getattr(entity, "id", None)
    if eid is not None:
        return str(eid)
    return repr(entity)


def select_by_name(ctx: dict[str, Any]) -> dict[str, Any]:
    """Jump the editor selection to the entity(ies) named ``ctx["name"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``name`` (required, non-empty ``str``): the entity name to
          match.
        * ``scene`` (optional): explicit scene handle for headless
          tests. Falls back to the shell's engine scene otherwise.
        * ``shell`` (optional): editor shell for selection write-back.
          Missing shell is legal — the return dict still names the
          matches so callers can drive their own selection.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_by_name", ctx)
    name = ctx.get("name")
    if not isinstance(name, str) or not name:
        return {"status": "missing_name"}
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    matches = _find_by_name(scene, name)
    if not matches:
        return {"status": "not_found", "name": name}
    shell = _get_shell(ctx)
    if shell is not None:
        # Plural list first so tests see the full match set even when
        # the shell rejects the singular write.
        try:
            setattr(shell, "_selected_entities", list(matches))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entity", matches[0])
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "selected",
        "count": len(matches),
        "entity_ids": [_entity_id(e) for e in matches],
        "name": name,
    }


__all__ = ["select_by_name"]
