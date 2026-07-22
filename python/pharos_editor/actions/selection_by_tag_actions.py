"""Selection-by-tag action — grab every scene entity carrying a given tag.

Backs the ``edit.select_by_tag``
:class:`~pharos_editor.tool_router.ToolAction` row added by the WW4
STUB-triage sprint tick (round 24 after VV4).

Distinct from the sibling selection verbs:

* QQ1's ``selection.by_type`` matches on ``entity.kind`` /
  ``prefab_kind`` / ``type(entity).__name__``. This verb matches on
  the free-form ``tags`` / ``_tags`` set — the tag-painter panel's
  primary output.
* QQ1's ``selection.by_layer`` matches on Z-layer membership.
* QQ1's ``selection.same_material`` matches on material handle.

Tag resolution
--------------

* ``ctx["tag"]`` (required) — the string tag to match.
* Every scene entity is probed for ``.tags`` (set / list / tuple)
  or ``._tags`` (private fallback). The compare is case-sensitive
  and a *contains* check — matches Unity's ``GameObject.CompareTag``
  and Godot's ``Node.is_in_group``.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "tag": str,
   "matched": N, "total": T}`` on success (at least one match).
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "missing_tag"}`` — ``ctx["tag"]`` absent or empty
  / non-string.
* ``{"status": "no_match", "tag": str}`` — scene walk found zero
  entities carrying the tag (selection cleared).
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


def _entity_tags(entity: Any) -> set[str]:
    """Return the set of tag strings on *entity* (empty on failure)."""
    for attr in ("tags", "_tags"):
        raw = getattr(entity, attr, None)
        if raw is None:
            continue
        try:
            return {str(t) for t in raw if t is not None}
        except TypeError:
            continue
    return set()


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


def _coerce_tag(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    tag = raw.strip()
    if not tag:
        return None
    return tag


def select_by_tag(ctx: dict[str, Any]) -> dict[str, Any]:
    """Replace the selection with every entity carrying ``ctx["tag"]``.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``tag`` (required str): the tag to match on.
        * ``shell`` (optional): editor shell — receives the updated
          selection.
        * ``scene`` (optional): scene handle.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_by_tag", ctx)
    tag = _coerce_tag(ctx.get("tag"))
    if tag is None:
        return {"status": "missing_tag"}
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _list_scene_entities(scene)
    matches: list[Any] = []
    for entity in entities:
        if tag in _entity_tags(entity):
            matches.append(entity)

    shell = _get_shell(ctx)
    _write_selection(shell, matches)

    if not matches:
        return {"status": "no_match", "tag": tag}
    return {
        "status": "selected",
        "selection": matches,
        "tag": tag,
        "matched": len(matches),
        "total": len(entities),
    }


__all__ = ["select_by_tag"]
