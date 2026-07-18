"""Layer sort-by-z action — reorder layers by ascending z-value.

Backs the ``layer.sort_by_z``
:class:`~slappyengine.tool_router.ToolAction` row added by the AAA4
STUB-triage sprint tick (round 27 after ZZ4).

Distinct from the sibling layer verbs:

* UU4's ``layer.move_up`` / ``layer.move_down`` shift a *single*
  layer one position within the layer list.
* VV4's ``layer.new`` / ``layer.delete`` add / remove entries.
* TT2's ``layer.rename`` retitles a layer.
* NN1's ``layer.solo`` / RR1's ``layer.hide_others`` /
  ``layer.isolate`` / YY4's ``layer.lock`` toggle per-layer visibility
  / lock flags.
* OO1's ``layer.merge_down`` collapses adjacent layers.
* WW4's ``layer.clear`` wipes contents.
* ZZ4's ``layer.unlock_all`` clears every lock in one sweep.

This verb is the *bulk-reorder* action — sorts every layer in the
scene by its ``.z`` value in ascending order, matching the
z-back-to-front convention used by every layered DCC. Photoshop's
Layer → Arrange → Reverse (bulk-sort) / Krita's Layer → Sort
Layers by Depth / Affinity Photo's Layer → Sort by Z / Nova3D's
Layer-panel gear → Sort by Z.

Sort semantics
--------------

* ``direction="ascending"`` (default) — sort by ``.z`` low → high.
  Convention: lower z = further back in a right-handed system.
* ``direction="descending"`` — sort ``.z`` high → low. Convention:
  higher z = further back in a left-handed / screen-space system.
* Layers with identical z values keep their relative order (stable
  sort).
* Layers missing a ``.z`` attribute are treated as ``0.0`` for
  sorting.

``ctx["dry_run"]=True`` reports the intended new ordering without
writing.

Return contract
---------------

* ``{"status": "sorted", "order": [name, name, ...],
   "count": N, "direction": "ascending" | "descending",
   "moved": bool}`` — success. ``moved`` is ``True`` iff any layer
   changed index.
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layers"}`` — scene has no z_layers.
* ``{"status": "already_sorted", "order": [...], "count": N,
   "direction": ...}`` — layers already in the requested order
   (idempotent no-op).
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


def _list_layers(scene: Any) -> list[Any]:
    layers_attr = getattr(scene, "z_layers", None)
    if layers_attr is None:
        return []
    try:
        return [l for l in list(layers_attr) if l is not None]
    except TypeError:
        return []


def _layer_z(layer: Any) -> float:
    raw = getattr(layer, "z", None)
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _layer_name(layer: Any) -> str:
    return str(getattr(layer, "name", "") or "")


def _write_layers(scene: Any, ordered: list[Any]) -> None:
    # Write through the same public attribute the reader used.
    try:
        setattr(scene, "z_layers", list(ordered))
    except Exception:  # noqa: BLE001
        pass
    # Also refresh the private slot when present.
    if hasattr(scene, "_z_layers"):
        try:
            setattr(scene, "_z_layers", list(ordered))
        except Exception:  # noqa: BLE001
            pass


def _refresh_hook(shell: Any) -> None:
    if shell is None:
        return
    hook = getattr(shell, "_on_layer_order_changed", None)
    if callable(hook):
        try:
            hook()
        except Exception:  # noqa: BLE001
            return
        return
    hook = getattr(shell, "_refresh_layer_panel", None)
    if callable(hook):
        try:
            hook()
        except Exception:  # noqa: BLE001
            pass


def sort_by_z(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reorder every layer by its ``.z`` value.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — falls back to
          ``_engine.scene`` / ``_scene``.
        * ``direction`` (optional str): ``"ascending"`` (default) or
          ``"descending"``.
        * ``dry_run`` (optional bool): report the intended ordering
          without writing.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("sort_by_z", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}

    direction = ctx.get("direction", "ascending")
    if direction not in ("ascending", "descending"):
        direction = "ascending"
    reverse = direction == "descending"

    # Stable sort — Python's list.sort is stable.
    ordered = sorted(layers, key=_layer_z, reverse=reverse)
    order_names = [_layer_name(l) for l in ordered]
    original_names = [_layer_name(l) for l in layers]

    moved = order_names != original_names
    if not moved:
        return {
            "status": "already_sorted",
            "order": order_names,
            "count": len(order_names),
            "direction": direction,
        }

    dry = bool(ctx.get("dry_run", False))
    if not dry:
        _write_layers(scene, ordered)
        _refresh_hook(_get_shell(ctx))

    return {
        "status": "sorted",
        "order": order_names,
        "count": len(order_names),
        "direction": direction,
        "moved": True,
    }


__all__ = ["sort_by_z"]
