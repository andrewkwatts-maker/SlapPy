"""Select-similar action — extend selection by *combined* similarity signature.

Backs the ``edit.select_similar``
:class:`~pharos_editor.tool_router.ToolAction` row added by the RR1
STUB-triage sprint tick (round 19 after QQ1's round-18
``spawn.at_origin`` / ``selection.by_type`` / ``selection.by_layer`` /
``selection.same_material`` / ``view.toggle_stats`` batch).

Distinct from PP1's ``selection.invert_by_type`` (kind-only, invert) and
QQ1's ``selection.by_type`` / ``selection.same_material`` (kind-only or
material-only, inclusive). Photoshop's ``Select → Similar`` grabs every
pixel matching the seed's colour + tolerance — the Pharos Engine analogue
for entity-graph selection is a signature that fuses *kind* and
*material* (either match wins), plus a fall-through to bare kind. The
"select similar" verb thus catches sibling entities of the same class
that share either the tag or the shader — the most-common user intent
Blender's ``Shift+G → Extend Type`` and Maya's ``Select → Similar``
implement.

Signature order (per entity):

1. ``(kind, material)`` — both non-empty → strict signature.
2. ``kind`` alone — when material is missing.
3. ``material`` alone — when kind is missing.
4. ``type(entity).__name__`` — bare class name (kind-only fallback).

Any signature in the seed's set qualifies a scene entity for inclusion.

Scene walk resolution
---------------------

* ``ctx["scene"]`` — explicit override (tests use this).
* ``shell._engine.scene`` — canonical shell hook.
* ``shell._scene`` — legacy attribute.

Return contract
---------------

* ``{"status": "selected", "selection": [...], "signatures": [...],
   "added": N, "previous_count": M, "total": T}`` on success.
* ``{"status": "no_scene"}`` — no scene handle reachable.
* ``{"status": "no_selection"}`` — no seed selection to derive
  signatures from.
* ``{"status": "unchanged", "selection": [...], "signatures": [...],
   "previous_count": M}`` — every similar entity was already selected.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx
from .selection_invert_by_type_actions import _entity_kind
from .selection_same_material_actions import _entity_material


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


def _signature(entity: Any) -> tuple[str, str]:
    """Return the ``(kind, material)`` signature for *entity*.

    Missing kind / material slots are represented as empty strings so
    the equality test still works. The ``_entity_kind`` fallback
    guarantees kind is never empty in practice (drops through to
    ``type(entity).__name__``); material may legitimately be empty when
    the entity carries no shader tag.
    """
    kind = _entity_kind(entity)
    material = _entity_material(entity)
    return (kind, material or "")


def _matches(candidate_sig: tuple[str, str], seed_sigs: set[tuple[str, str]]) -> bool:
    """Return True when *candidate_sig* is a similarity hit for any seed.

    A candidate matches when:

    * It shares the full ``(kind, material)`` tuple with a seed, OR
    * A seed shares the candidate's kind (kind-similarity — the primary
      "select similar" signal), OR
    * A seed shares the candidate's non-empty material (cross-kind
      material similarity — Photoshop-style "same shader").
    """
    if candidate_sig in seed_sigs:
        return True
    c_kind, c_mat = candidate_sig
    for s_kind, s_mat in seed_sigs:
        if s_kind and s_kind == c_kind:
            return True
        if c_mat and s_mat and s_mat == c_mat:
            return True
    return False


def select_similar(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extend the selection by ``(kind, material)`` similarity to the seed.

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
    ensure_ctx("select_similar", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    seed = _resolve_selection(ctx)
    if not seed:
        return {"status": "no_selection"}

    signatures: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entity in seed:
        sig = _signature(entity)
        if sig not in seen:
            seen.add(sig)
            signatures.append(sig)

    entities = _list_scene_entities(scene)
    seed_ids = {id(e) for e in seed}
    result: list[Any] = list(seed)
    result_ids = set(seed_ids)
    for candidate in entities:
        if id(candidate) in result_ids:
            continue
        if _matches(_signature(candidate), seen):
            result.append(candidate)
            result_ids.add(id(candidate))

    added = len(result) - len(seed)
    shell = _get_shell(ctx)
    _write_selection(shell, result)

    if added == 0:
        return {
            "status": "unchanged",
            "selection": result,
            "signatures": signatures,
            "previous_count": len(seed),
        }
    return {
        "status": "selected",
        "selection": result,
        "signatures": signatures,
        "added": added,
        "previous_count": len(seed),
        "total": len(result),
    }


__all__ = ["select_similar"]
