"""
Spawn menu — `+ Add` actions that drop softbody / fluid bodies into a world.

Each entry in :data:`SPAWN_ACTIONS` describes:

- ``label`` — text shown on the menu / button.
- ``factory`` — dotted import path of the callable that actually mutates
  the world (e.g. ``"softbody.body_builders.make_lattice"``).  Imported
  **lazily** on click so the editor stays useful even when the matching
  subsystem (softbody/fluid) isn't installed yet.
- ``spec`` — dataclass type describing the factory's input parameters.
  The modal renders one widget per dataclass field via the existing
  :class:`~slappyengine.ui.editor.property_inspector.PropertyInspector`
  reflection (its ``_iter_fields`` + ``_render_field`` two-pass renderer).

Public surface
--------------

- :data:`SPAWN_ACTIONS` — read by ``scene_outliner.py`` to populate
  the ``+ Add`` popup.
- :func:`open_spawn_modal` — opens a modal dialog for one action; on
  *Spawn* it resolves the factory, calls it with the spec instance
  fields, and closes the modal.  No-op if dearpygui isn't installed.

Spec dataclasses (``LatticeSpec`` etc.) are defined here so the menu is
importable even before the softbody / fluid packages exist in this
checkout.  Once those packages ship, builders are free to accept the
same field names — the modal just hands their values forward.
"""
from __future__ import annotations

import dataclasses
import importlib
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Spec dataclasses — one per spawn action.
# ---------------------------------------------------------------------------

@dataclass
class LatticeSpec:
    """Parameters for ``softbody.body_builders.make_lattice``."""
    name: str = "lattice"
    position: tuple[float, float] = (0.0, 0.0)
    width: int = 8
    height: int = 8
    spacing: float = 8.0
    mass: float = 1.0
    material: str = "rubber"


@dataclass
class CreatureSpec:
    """Parameters for ``softbody.body_builders.make_layered_creature``."""
    name: str = "creature"
    position: tuple[float, float] = (0.0, 0.0)
    layers: int = 3
    width: int = 6
    height: int = 10
    spacing: float = 6.0
    cross_layer_break_force: float = 50.0


@dataclass
class VehicleSpec:
    """Parameters for ``softbody.vehicle.build_vehicle``."""
    name: str = "vehicle"
    position: tuple[float, float] = (0.0, 0.0)
    chassis_w: int = 6
    chassis_h: int = 3
    wheel_count: int = 4
    wheel_radius: float = 6.0
    drivetrain: str = "RWD"


@dataclass
class PoolSpec:
    """Parameters for ``fluid.world.spawn_pool``."""
    name: str = "pool"
    position: tuple[float, float] = (0.0, 0.0)
    width: float = 64.0
    height: float = 24.0
    particle_radius: float = 1.5
    material: str = "water"


@dataclass
class SandSpec:
    """Parameters for ``fluid.world.spawn_sand_pile``."""
    name: str = "sand"
    position: tuple[float, float] = (0.0, 0.0)
    radius: float = 16.0
    particle_radius: float = 1.5
    material: str = "sand"


# ---------------------------------------------------------------------------
# Action table.
#
# `factory` is a dotted path resolved at click time so a missing softbody/
# fluid backend doesn't break editor import.
# ---------------------------------------------------------------------------

SPAWN_ACTIONS: list[dict] = [
    {
        "label":   "Add SoftBody Lattice",
        "factory": "slappyengine.softbody.body_builders.make_lattice",
        "spec":    LatticeSpec,
    },
    {
        "label":   "Add Layered Creature",
        "factory": "slappyengine.softbody.body_builders.make_layered_creature",
        "spec":    CreatureSpec,
    },
    {
        "label":   "Add Vehicle",
        "factory": "slappyengine.softbody.vehicle.build_vehicle",
        "spec":    VehicleSpec,
    },
    {
        "label":   "Add Fluid Pool",
        "factory": "slappyengine.fluid.world.spawn_pool",
        "spec":    PoolSpec,
    },
    {
        "label":   "Add Sand Pile",
        "factory": "slappyengine.fluid.world.spawn_sand_pile",
        "spec":    SandSpec,
    },
]


# ---------------------------------------------------------------------------
# Factory resolution
# ---------------------------------------------------------------------------

def _resolve_factory(dotted: str) -> Callable[..., Any]:
    """Import and return the callable at the dotted import path *dotted*.

    Looks up first as ``slappyengine.<dotted>``-style absolute path; if
    that fails (legacy entries omit the package prefix), falls back to
    ``slappyengine.<dotted>``.  Raises ``ImportError`` if neither
    resolves.
    """
    candidates = [dotted]
    if not dotted.startswith("slappyengine."):
        candidates.append(f"slappyengine.{dotted}")

    last_err: Exception | None = None
    for path in candidates:
        try:
            mod_path, _, attr = path.rpartition(".")
            if not mod_path:
                raise ImportError(f"dotted path has no module: {path!r}")
            module = importlib.import_module(mod_path)
            return getattr(module, attr)
        except (ImportError, AttributeError) as err:
            last_err = err
            continue
    raise ImportError(
        f"Could not resolve factory {dotted!r}: {last_err}"
    ) from last_err


def _spec_to_kwargs(spec: Any) -> dict[str, Any]:
    """Return a dict mapping ``spec`` dataclass fields → current values."""
    return {f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)}


# ---------------------------------------------------------------------------
# Modal — uses the existing PropertyInspector for field reflection.
# ---------------------------------------------------------------------------

def open_spawn_modal(action: dict, world: Any) -> None:
    """Open a dearpygui modal for *action* and call its factory on confirm.

    Parameters
    ----------
    action:
        One of the entries in :data:`SPAWN_ACTIONS`.
    world:
        The target world / scene the spawned body will be added to.
        Passed as the **first** positional argument to the factory; the
        spec fields are unpacked as keyword arguments.

    Behaviour
    ---------
    The modal is rendered with two regions:

    1. A DPG child window populated by
       :meth:`PropertyInspector.build` + :meth:`set_object`, so every
       primitive field on the spec dataclass automatically gets a widget
       (drag/input/checkbox/color-edit).  This is the *same* reflection
       used by the regular Details panel; we do not duplicate widget code.
    2. A footer with ``Spawn`` and ``Cancel`` buttons.

    On ``Spawn`` the factory is resolved (``importlib.import_module`` →
    ``getattr``) and called as ``factory(world, **spec_fields)``.  Errors
    are caught and surfaced via DPG; nothing raises out of the callback.

    No-op (and returns silently) if dearpygui isn't installed.
    """
    try:
        import dearpygui.dearpygui as dpg
    except ImportError:
        return

    spec_cls = action["spec"]
    spec_instance = spec_cls()

    # Build a fresh PropertyInspector bound to this spec; rendered into a
    # child window inside the modal.
    from slappyengine.ui.editor.property_inspector import PropertyInspector

    inspector = PropertyInspector()
    # Distinct panel tag per modal so multiple modals don't collide.
    panel_tag = f"spawn_modal_inspector_{id(spec_instance)}"
    inspector._panel_tag = panel_tag

    modal_tag = f"spawn_modal_{id(spec_instance)}"
    body_tag  = f"{modal_tag}_body"

    def _on_spawn(*_a, **_kw) -> None:
        """Resolve factory, call factory(world, **kwargs), close modal."""
        try:
            factory = _resolve_factory(action["factory"])
            kwargs = _spec_to_kwargs(spec_instance)
            factory(world, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive UI path
            # Surface the error in the status bar if it exists; otherwise
            # swallow rather than crashing the render loop.
            if dpg.does_item_exist("status_bar"):
                dpg.set_value("status_bar", f"Spawn failed: {exc}")
        finally:
            if dpg.does_item_exist(modal_tag):
                dpg.delete_item(modal_tag)

    def _on_cancel(*_a, **_kw) -> None:
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

    with dpg.window(
        label=action["label"],
        modal=True,
        no_close=False,
        tag=modal_tag,
        width=360,
        height=420,
    ):
        # Inspector child window — auto-reflects every spec field.
        with dpg.child_window(tag=body_tag, width=-1, height=-50, border=False):
            pass
        inspector.build(body_tag)
        inspector.set_object(spec_instance)

        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Spawn",  callback=_on_spawn,  width=120)
            dpg.add_button(label="Cancel", callback=_on_cancel, width=120)
