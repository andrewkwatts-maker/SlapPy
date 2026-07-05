"""Select-by-prefab-kind action — "select every rope" flow.

Backs the ``edit.select_by_prefab_kind``
:class:`~slappyengine.tool_router.ToolAction` row added by the JJ6
STUB-triage sprint tick (round 12 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1 / EE1 / FF1 / GG1 / II5).

Mirrors the DCC "select similar" flow (Blender's ``Shift+G``, Maya's
``Select > Select Similar``, After Effects' right-click "select same
type"). Given a target kind string (``"rope"``, ``"softbody"``,
``"fluid"``, ...), sweeps the scene and swaps the current selection for
every entity whose ``kind`` / ``prefab_kind`` / ``type`` / ``category``
attribute matches.

Kind resolution
---------------

1. ``ctx["kind"]`` — explicit override; always wins.
2. Otherwise the helper pulls the kind of the currently-selected entity
   (Blender's Shift+G semantics: "select entities like the one I've
   already got selected"). When no single entity is selected we return
   ``{"status": "no_selection"}`` so the caller can hint "select one
   entity first".

Kind attribute walk (per-entity, first match wins): ``kind``,
``prefab_kind``, ``type``, ``category``. Numeric / enum values are
coerced via ``str(value)`` so a ``PrefabKind.ROPE`` enum matches
``"PrefabKind.ROPE"``.

Match modes
-----------

* ``mode = "replace"`` (default) — swap the selection for the matches.
* ``mode = "add"`` — extend the existing selection with the matches.

Filter hooks
------------

* ``include_locked`` (default ``False``) — locked entries are skipped.
* ``include_hidden`` (default ``False``) — hidden entries are skipped.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "count": N, "kind": k,
   "previous_count": M}`` on success.
* ``{"status": "no_scene"}`` when no scene handle resolves.
* ``{"status": "empty_scene"}`` when the scene has zero entities.
* ``{"status": "no_selection"}`` when ``kind`` is unset and there's
  nothing selected to derive it from.
* ``{"status": "no_kind_on_reference"}`` when the reference entity has
  none of ``kind`` / ``prefab_kind`` / ``type`` / ``category``.
* ``{"status": "no_matches", "kind": k}`` when the scene has entities but
  none match the requested kind.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .edit_invert_selection_actions import (
    _get_scene,
    _get_shell,
    _is_hidden,
    _is_locked,
    _resolve_selection,
    _walk_scene_entities,
)


_KIND_ATTRS = ("kind", "prefab_kind", "type", "category")


def _entity_kind(entity: Any) -> str | None:
    """Return the first non-None kind-like attribute of *entity*."""
    for attr in _KIND_ATTRS:
        value = getattr(entity, attr, None)
        if value is None:
            continue
        # Coerce enums / classes to their string form so users can pass
        # ``"PrefabKind.ROPE"`` and match reliably.
        return str(value)
    return None


def _resolve_reference_kind(ctx: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(kind, error_status)``.

    Exactly one is non-None: the kind on success, or an error status when
    resolution fails.
    """
    override = ctx.get("kind")
    if override is not None:
        return str(override), None

    selection = _resolve_selection(ctx)
    if not selection:
        return None, "no_selection"

    # If there's a single-entity current selection, use it as the
    # reference. If multiple entities are selected, take the first (Blender's
    # Shift+G uses "the active entity" which we approximate as the head).
    reference = selection[0]
    kind = _entity_kind(reference)
    if kind is None:
        return None, "no_kind_on_reference"
    return kind, None


def select_by_prefab_kind(ctx: dict[str, Any]) -> dict[str, Any]:
    """Select every scene entity whose kind matches the reference kind.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``shell`` (optional): editor shell — selection is retargeted on
          success.
        * ``scene`` (optional): scene override.
        * ``kind`` (optional str): explicit target kind. When absent the
          kind is pulled from the current selection's first entity.
        * ``mode`` (optional ``"replace"`` / ``"add"``, default
          ``"replace"``).
        * ``include_locked`` (optional bool, default ``False``).
        * ``include_hidden`` (optional bool, default ``False``).
        * ``selection`` (optional): explicit selection override.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("select_by_prefab_kind", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}

    entities = _walk_scene_entities(scene)
    if not entities:
        return {"status": "empty_scene"}

    kind, err = _resolve_reference_kind(ctx)
    if err is not None:
        return {"status": err}
    assert kind is not None

    include_locked = bool(ctx.get("include_locked", False))
    include_hidden = bool(ctx.get("include_hidden", False))

    matches: list[Any] = []
    for entity in entities:
        if not include_locked and _is_locked(entity):
            continue
        if not include_hidden and _is_hidden(entity):
            continue
        if _entity_kind(entity) == kind:
            matches.append(entity)

    if not matches:
        return {"status": "no_matches", "kind": kind}

    mode = ctx.get("mode", "replace")
    previous_selection = _resolve_selection(ctx)
    previous_count = len(previous_selection)

    if mode == "add":
        # De-duplicate on id().
        seen: set[int] = {id(e) for e in previous_selection}
        merged = list(previous_selection)
        for entity in matches:
            if id(entity) not in seen:
                merged.append(entity)
                seen.add(id(entity))
        selection = merged
    else:  # replace (default)
        selection = list(matches)

    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_selected_entities", list(selection))
        except Exception:  # noqa: BLE001
            pass
        try:
            setattr(shell, "_selected_entity", selection[0])
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "selected",
        "selection": selection,
        "count": len(selection),
        "kind": kind,
        "previous_count": previous_count,
        "matches": matches,
        "match_count": len(matches),
    }


__all__ = ["select_by_prefab_kind"]
