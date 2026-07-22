"""Layer lifecycle actions — create + delete a Z-layer.

Backs two :class:`~pharos_engine.tool_router.ToolAction` rows added by
the VV4 STUB-triage sprint tick (round 23 after UU4's round-22
``spawn.at_origin_offset`` / ``edit.flatten_selection`` /
``snap.set_angle_snap`` / ``layer.move_up`` / ``layer.move_down``
batch):

* ``layer.new``    — insert a fresh Z-layer above the currently
  active layer (Photoshop ``Ctrl+Shift+N`` / Krita ``Ins`` /
  Nova3D Layer-panel ``+`` button).
* ``layer.delete`` — remove the active Z-layer (Photoshop trash-can
  icon / Krita ``Del`` on the layer panel).

Distinct from the neighbouring layer verbs:

* DD1's ``edit.duplicate_layer`` clones an existing layer — this pair
  creates a blank one or removes it entirely.
* OO1's ``layer.merge_down`` collapses two layers into one; delete
  discards the layer content.
* TT2's ``layer.rename`` touches the name only.
* UU4's ``layer.move_up`` / ``layer.move_down`` reorders — never
  changes layer count.
* RR1's ``layer.hide_others`` / ``layer.isolate`` toggle visibility.

Every layered DCC ships this create/delete pair as a companion to the
reorder/duplicate/rename verbs: Photoshop's Layers-panel top-right
menu, Krita's Layer menu, Affinity Photo's Layer → New Layer / Delete
Layer, Nova3D's Layer-panel ``+`` / ``-`` buttons.

Naming policy
-------------

* ``layer.new`` picks the first unused ``"Layer N"`` name (matches
  Photoshop's default). Callers can override with ``ctx["name"]``.
* When the requested name collides, the helper appends ``_2``, ``_3``…
  (mirrors ``layer_rename_actions._uniquify``).

Delete safety
-------------

* Refuses to remove the last remaining layer — scenes must have at
  least one layer to remain valid. Returns
  ``{"status": "last_layer"}`` in that case.
* Deletes the layer **entry** from ``scene.z_layers`` but does not
  touch entities — matches Photoshop's "delete empty layer" flow.
  Callers wanting a merge-then-delete should invoke
  ``layer.merge_down`` first.
* Repoints ``shell._active_layer`` to the layer immediately below
  (or the topmost when the deleted one was the bottom).

Return contract (``layer.new``)
-------------------------------

* ``{"status": "created", "name": str, "z": float, "collided": bool}``
  — success. ``collided=True`` when a numeric suffix was appended to
  disambiguate the requested name.
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "error", "message": str}`` — scene refused the add.

Return contract (``layer.delete``)
----------------------------------

* ``{"status": "deleted", "target": str, "z": float,
   "next_active": str | None}`` — success.
* ``{"status": "no_scene"}`` — no scene reachable.
* ``{"status": "no_layers"}`` — the scene has zero registered layers.
* ``{"status": "no_layer"}`` — no target layer resolvable.
* ``{"status": "last_layer", "target": str}`` — refused (would leave
  scene layer-less).
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_DEFAULT_BASE = "Layer"


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


def _layer_name(layer: Any) -> str:
    return str(getattr(layer, "name", "") or "")


def _layer_z(layer: Any) -> float:
    try:
        return float(getattr(layer, "z", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _find_by_name(layers: list[Any], name: str) -> Any:
    for layer in layers:
        if _layer_name(layer) == name:
            return layer
    return None


def _uniquify(base: str, taken: set[str]) -> tuple[str, bool]:
    if base not in taken:
        return (base, False)
    counter = 2
    while True:
        candidate = f"{base}_{counter}"
        if candidate not in taken:
            return (candidate, True)
        counter += 1


def _next_default_name(taken: set[str]) -> str:
    """Return the first unused ``"Layer N"`` name (N ≥ 1)."""
    n = 1
    while True:
        candidate = f"{_DEFAULT_BASE} {n}"
        if candidate not in taken:
            return candidate
        n += 1


def _refresh_hook(shell: Any) -> None:
    if shell is None:
        return
    for hook_name in (
        "_on_layer_added",
        "_on_layer_removed",
        "_on_layer_reordered",
        "_refresh_layer_panel",
    ):
        hook = getattr(shell, hook_name, None)
        if callable(hook):
            try:
                hook()
            except Exception:  # noqa: BLE001
                pass
            break


def _make_layer_stub(name: str, z: float) -> Any:
    """Fabricate a minimal layer object when the scene has no factory.

    Uses :class:`types.SimpleNamespace` so tests / headless callers can
    still observe ``.name`` and ``.z`` attributes on the returned
    layer. Real scenes should implement ``scene.new_z_layer(name)`` or
    ``scene.add_z_layer(layer)`` to get their own layer types.
    """
    from types import SimpleNamespace
    return SimpleNamespace(name=name, z=z)


def create_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Insert a new Z-layer into the scene.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``name`` (optional str): requested layer name. Defaults to
          ``"Layer N"`` picking the smallest unused ``N``.
        * ``z`` (optional float): explicit z coordinate. Defaults to
          ``max(existing z) + 1.0`` (or ``0.0`` when scene is empty).
        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — receives
          ``_active_layer`` retarget + refresh hook.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("create_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    taken: set[str] = {_layer_name(l) for l in layers}

    raw_name = ctx.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        base = raw_name.strip()
        final, collided = _uniquify(base, taken)
    else:
        final = _next_default_name(taken)
        collided = False

    raw_z = ctx.get("z")
    if raw_z is not None:
        try:
            z = float(raw_z)
        except (TypeError, ValueError):
            z = 0.0
    else:
        if layers:
            z = max(_layer_z(l) for l in layers) + 1.0
        else:
            z = 0.0

    # Try scene-side factory before falling back to SimpleNamespace stub.
    factory = getattr(scene, "new_z_layer", None)
    layer: Any = None
    if callable(factory):
        try:
            layer = factory(final)
            if layer is not None:
                try:
                    setattr(layer, "z", z)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    if layer is None:
        layer = _make_layer_stub(final, z)
        adder = getattr(scene, "add_z_layer", None)
        if callable(adder):
            try:
                adder(layer)
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}
        else:
            raw = getattr(scene, "_z_layers", None)
            if isinstance(raw, list):
                raw.append(layer)
            else:
                # Scene refused the add — surface it.
                return {
                    "status": "error",
                    "message": "scene has no add_z_layer / _z_layers",
                }

    shell = _get_shell(ctx)
    if shell is not None:
        try:
            setattr(shell, "_active_layer", layer)
        except Exception:  # noqa: BLE001
            pass
        _refresh_hook(shell)

    return {
        "status": "created",
        "name": final,
        "z": z,
        "collided": collided,
    }


def _resolve_target(ctx: dict[str, Any], layers: list[Any]) -> Any:
    override = ctx.get("layer")
    if override is not None:
        return override
    name = ctx.get("layer_name")
    if isinstance(name, str) and name:
        got = _find_by_name(layers, name)
        if got is not None:
            return got
    shell = _get_shell(ctx)
    if shell is not None:
        active = getattr(shell, "_active_layer", None)
        if active is not None:
            return active
    return None


def delete_layer(ctx: dict[str, Any]) -> dict[str, Any]:
    """Remove a Z-layer from the scene.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``layer`` (optional): explicit target.
        * ``layer_name`` (optional str): name lookup.
        * ``scene`` (optional): explicit scene handle.
        * ``shell`` (optional): editor shell — provides
          ``_active_layer`` fallback + receives retarget.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("delete_layer", ctx)
    scene = _get_scene(ctx)
    if scene is None:
        return {"status": "no_scene"}
    layers = _list_layers(scene)
    if not layers:
        return {"status": "no_layers"}
    target = _resolve_target(ctx, layers)
    if target is None:
        return {"status": "no_layer"}
    if len(layers) < 2:
        return {"status": "last_layer", "target": _layer_name(target)}

    target_name = _layer_name(target)
    target_z = _layer_z(target)

    # Try scene-side remover first.
    remover = getattr(scene, "remove_z_layer", None)
    removed = False
    if callable(remover):
        try:
            remover(target)
            removed = True
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
    if not removed:
        raw = getattr(scene, "_z_layers", None)
        if isinstance(raw, list):
            try:
                raw.remove(target)
                removed = True
            except ValueError:
                pass
        if not removed:
            # Try mutating z_layers directly if it's a list.
            z_raw = getattr(scene, "z_layers", None)
            if isinstance(z_raw, list):
                try:
                    z_raw.remove(target)
                    removed = True
                except ValueError:
                    pass
    if not removed:
        return {
            "status": "error",
            "message": "scene refused the layer remove",
        }

    # Pick the next active layer — prefer the one immediately below
    # (lower z) so the visual focus stays close to the deleted layer.
    remaining = [l for l in _list_layers(scene) if l is not target]
    next_active: Any = None
    if remaining:
        below = [l for l in remaining if _layer_z(l) < target_z]
        if below:
            next_active = max(below, key=_layer_z)
        else:
            next_active = min(remaining, key=_layer_z)

    shell = _get_shell(ctx)
    if shell is not None and next_active is not None:
        try:
            setattr(shell, "_active_layer", next_active)
        except Exception:  # noqa: BLE001
            pass
    if shell is not None:
        _refresh_hook(shell)

    return {
        "status": "deleted",
        "target": target_name,
        "z": target_z,
        "next_active": (
            _layer_name(next_active) if next_active is not None else None
        ),
    }


__all__ = ["create_layer", "delete_layer"]
