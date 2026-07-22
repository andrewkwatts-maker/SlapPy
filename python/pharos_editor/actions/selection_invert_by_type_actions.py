"""Selection invert-by-type action — select every entity of the same type.

Backs the ``selection.invert_by_type``
:class:`~pharos_editor.tool_router.ToolAction` row added by the PP1
STUB-triage sprint tick (round 17).

Blender's ``Select → All by Type``, Unity's ``Select → All in Hierarchy
of Type`` — every scene-graph tool exposes a "grab everything that
matches the current selection's kind" gesture. This helper reads the
kind of every currently-selected entity (from ``entity.kind`` /
``entity.prefab_kind`` / ``entity.type`` / ``type(entity).__name__``),
walks the scene, and replaces the selection with every entity in the
scene whose kind matches — *excluding* the seed entities so the result
is genuinely an "invert" (Photoshop ``Select → Similar``-style, but
scoped by kind rather than pixel value).

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Kind resolution order (per entity):

1. ``entity.kind``
2. ``entity.prefab_kind``
3. ``entity.type``
4. ``type(entity).__name__``

Return contract
---------------

* ``{"status": "inverted", "selection": [...], "kinds": [...],
   "added": N, "previous_count": M}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to derive kinds
  from.
* ``{"status": "no_matches", "kinds": [...]}`` — no non-selected entity
  in the scene matched any seed kind.
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
    engine = getattr(shell, "_engine", None)
    if engine is not None:
        cand = getattr(engine, "scene", None) or getattr(engine, "_scene", None)
        if cand is not None:
            return cand
    return getattr(shell, "_scene", None)


def _list_scene_entities(scene: Any) -> list[Any]:
    entities_attr = getattr(scene, "entities", None)
    if entities_attr is not None:
        try:
            return [e for e in list(entities_attr) if e is not None]
        except TypeError:
            pass
    getter = getattr(scene, "get_entities", None)
    if callable(getter):
        try:
            return [e for e in list(getter()) if e is not None]
        except Exception:  # noqa: BLE001
            return []
    return []


def _resolve_selection(ctx: dict[str, Any]) -> list[Any]:
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
            return [x for x in override if x is not None]
        return [override]
    shell = _get_shell(ctx)
    if shell is None:
        return []
    for attr in ("_selected_entities", "selection", "_selection"):
        val = getattr(shell, attr, None)
        if val is None:
            continue
        if isinstance(val, (list, tuple, set)):
            return [x for x in val if x is not None]
    single = getattr(shell, "_selected_entity", None)
    if single is not None:
        return [single]
    return []


def _entity_kind(entity: Any) -> str:
    """Return the entity's kind string.

    Search order matches the module docstring — the first non-empty
    string on ``kind`` / ``prefab_kind`` / ``type`` wins, falling
    through to ``type(entity).__name__`` so untagged entities still
    group by their concrete class.
    """
    if isinstance(entity, dict):
        for key in ("kind", "prefab_kind", "type"):
            val = entity.get(key)
            if val:
                return str(val)
        return "dict"
    for attr in ("kind", "prefab_kind", "type"):
        val = getattr(entity, attr, None)
        if val:
            return str(val)
    return type(entity).__name__


def _write_selection(shell: Any, selection: list[Any]) -> None:
    if shell is None:
        return
    for attr in ("_selected_entities", "selection", "_selection"):
        if hasattr(shell, attr):
            try:
                setattr(shell, attr, list(selection))
                break
            except Exception:  # noqa: BLE001
                continue
    else:
        try:
            setattr(shell, "_selected_entities", list(selection))
        except Exception:  # noqa: BLE001
            pass


def invert_by_type(ctx: dict[str, Any]) -> dict[str, Any]:
    """Replace the selection with every same-kind entity in the scene.

    The seed selection defines which "kinds" to pull in. Every scene
    entity whose kind matches a seed kind and which is *not itself* in
    the seed selection is added to the result. The seed entities are
    excluded — this is an invert-by-type, not a "select all matching
    including current".

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``selection`` (optional): explicit seed selection.
        * ``shell`` (optional): editor shell — provides selection
          fallback + receives the updated selection.
        * ``scene`` (optional): scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("invert_by_type", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    kinds: list[str] = []
    seen_kinds: set[str] = set()
    for entity in seed:
        k = _entity_kind(entity)
        if k not in seen_kinds:
            seen_kinds.add(k)
            kinds.append(k)

    entities = _list_scene_entities(scene)
    seed_ids = {id(e) for e in seed}

    matches: list[Any] = []
    for candidate in entities:
        if id(candidate) in seed_ids:
            continue
        if _entity_kind(candidate) in seen_kinds:
            matches.append(candidate)

    shell = _get_shell(ctx)

    if not matches:
        # Leave the current selection untouched — matches Blender's
        # "no matching entities" no-op behaviour.
        return {
            "status": "no_matches",
            "kinds": kinds,
            "previous_count": len(seed),
        }

    _write_selection(shell, matches)
    return {
        "status": "inverted",
        "selection": matches,
        "kinds": kinds,
        "added": len(matches),
        "previous_count": len(seed),
    }


__all__ = ["invert_by_type"]
