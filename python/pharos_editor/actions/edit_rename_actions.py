"""Edit-rename action — rename the currently-selected scene entity.

Backs the ``edit.rename`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the PP1 STUB-triage sprint tick (round 17).

Distinct from FF1's ``content.rename_asset`` (which renames a file /
folder on disk in the content browser). ``edit.rename`` renames an
*entity* — the ``F2`` gesture Blender / Unity / Unreal share: pick the
selected entity, assign a new name, refresh the outliner. When the
current selection contains multiple entities the helper renames all of
them by appending a numeric suffix (``foo`` → ``foo_01``, ``foo_02``…)
so the multi-select case doesn't collapse to a single duplicate name.

Selection resolution
--------------------

1. ``ctx["entity"]`` — explicit single-entity override.
2. ``ctx["selection"]`` — explicit list override.
3. ``shell._selected_entities`` — canonical multi-select shell slot.
4. ``shell._selected_entity`` — single-select shell slot.

Name validation
---------------

* Whitespace-only names are rejected as ``invalid_name``.
* Names containing path separators (``/`` / ``\\``) are rejected — this
  matches ``content.rename_asset``'s guard so a "rename" flow can't
  accidentally do a scene-graph re-parent.

Return contract
---------------

* ``{"status": "renamed", "renamed": [(old_name, new_name), ...],
   "count": N}`` on success.
* ``{"status": "no_selection"}`` — no entity resolvable.
* ``{"status": "missing_name"}`` — ``ctx["new_name"]`` is absent /
  empty.
* ``{"status": "invalid_name", "name": str}`` — new name failed
  validation.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_INVALID_CHARS = ("/", "\\")


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _resolve_targets(ctx: dict[str, Any]) -> list[Any]:
    """Return the list of entities to rename.

    Explicit ``ctx["entity"]`` and ``ctx["selection"]`` win over the
    shell's stored selection. When both are absent the resolver falls
    through to ``_selected_entities`` → ``_selected_entity``.
    """
    entity = ctx.get("entity")
    if entity is not None:
        return [entity]
    override = ctx.get("selection")
    if override is not None:
        if isinstance(override, (list, tuple, set)):
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


def _get_entity_name(entity: Any) -> str:
    if isinstance(entity, dict):
        return str(entity.get("name") or "")
    val = getattr(entity, "name", None)
    return str(val or "")


def _set_entity_name(entity: Any, value: str) -> bool:
    if isinstance(entity, dict):
        try:
            entity["name"] = value
            return True
        except Exception:  # noqa: BLE001
            return False
    try:
        setattr(entity, "name", value)
        return True
    except Exception:  # noqa: BLE001
        return False


def _validate_name(name: str) -> tuple[bool, str]:
    """Return ``(ok, cleaned_name)``.

    Trims surrounding whitespace. Rejects empty strings and any name
    containing a path separator.
    """
    cleaned = str(name).strip()
    if not cleaned:
        return (False, cleaned)
    for ch in _INVALID_CHARS:
        if ch in cleaned:
            return (False, cleaned)
    return (True, cleaned)


def rename_entity(ctx: dict[str, Any]) -> dict[str, Any]:
    """Rename the resolved entity / entities to ``ctx["new_name"]``.

    When the resolved target list has more than one entity, the helper
    appends a numeric ``"_NN"`` suffix (zero-padded to 2 digits) so the
    scene graph doesn't end up with N sibling entities all named the
    same string.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``entity`` (optional): explicit single-entity override.
        * ``selection`` (optional): explicit list override.
        * ``shell`` (optional): editor shell — provides selection
          fallback + best-effort outliner refresh.
        * ``new_name`` (required): the target name.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("rename_entity", ctx)
    raw_name = ctx.get("new_name")
    if raw_name is None or str(raw_name) == "":
        return {"status": "missing_name"}
    ok, cleaned = _validate_name(str(raw_name))
    if not ok:
        return {"status": "invalid_name", "name": cleaned}
    targets = _resolve_targets(ctx)
    if not targets:
        return {"status": "no_selection"}

    renamed: list[tuple[str, str]] = []
    if len(targets) == 1:
        old = _get_entity_name(targets[0])
        if _set_entity_name(targets[0], cleaned):
            renamed.append((old, cleaned))
    else:
        for idx, entity in enumerate(targets, start=1):
            old = _get_entity_name(entity)
            new = f"{cleaned}_{idx:02d}"
            if _set_entity_name(entity, new):
                renamed.append((old, new))

    # Best-effort: nudge the shell's outliner to redraw.
    shell = _get_shell(ctx)
    if shell is not None:
        for hook_name in ("_on_entity_renamed", "_refresh_outliner"):
            hook = getattr(shell, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception:  # noqa: BLE001
                    pass
                break

    return {
        "status": "renamed",
        "renamed": renamed,
        "count": len(renamed),
    }


__all__ = ["rename_entity"]
