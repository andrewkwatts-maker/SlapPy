"""Selection-by-type action — grab every scene entity matching the seed kinds.

Backs the ``selection.by_type``
:class:`~pharos_engine.tool_router.ToolAction` row added by the QQ1
STUB-triage sprint tick (round 18).

Companion to PP1's :mod:`selection_invert_by_type_actions` — that helper
*replaces* the selection with only the non-seed matches (a true
"invert"), while this helper is the *inclusive* variant Blender ships
under ``Shift+G → Type`` and Unity ships under ``Select → All of Type``:
grab everything that matches, seeds included.

Kind resolution matches
:mod:`selection_invert_by_type_actions._entity_kind` — first non-empty
string on ``kind`` / ``prefab_kind`` / ``type``, falling through to
``type(entity).__name__``.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "kinds": [...],
   "added": N, "previous_count": M, "total": T}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to derive kinds
  from.
* ``{"status": "unchanged", "selection": [...], "kinds": [...]}`` —
  every same-kind entity was already selected.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .selection_invert_by_type_actions import _entity_kind


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


def select_by_type(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extend the selection to every scene entity matching the seed kinds.

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
    ensure_ctx("select_by_type", ctx)
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
    # Result starts with the seed selection preserved.
    result: list[Any] = list(seed)
    result_ids = set(seed_ids)
    for candidate in entities:
        if id(candidate) in result_ids:
            continue
        if _entity_kind(candidate) in seen_kinds:
            result.append(candidate)
            result_ids.add(id(candidate))

    added = len(result) - len(seed)
    shell = _get_shell(ctx)
    _write_selection(shell, result)

    if added == 0:
        return {
            "status": "unchanged",
            "selection": result,
            "kinds": kinds,
            "previous_count": len(seed),
        }
    return {
        "status": "selected",
        "selection": result,
        "kinds": kinds,
        "added": added,
        "previous_count": len(seed),
        "total": len(result),
    }


__all__ = ["select_by_type"]
