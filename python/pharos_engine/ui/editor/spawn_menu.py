"""Legacy Nova3D reference. The shipping editor uses notebook_spawn_menu — see docs/ui_pattern_audit_2026_06_03.md.

Survivors (do NOT extend):
  * ``EditorShell`` imports ``SPAWN_ACTIONS`` here for legacy + Add wiring.
  * ``notebook_spawn_menu`` lazy-imports the Nova3D spec dataclasses
    (``RopeSpawnSpec`` / ``RagdollSpawnSpec`` / ``HumanoidSpawnSpec`` /
    ``IKChainSpawnSpec``) so the two menus stay spec-compatible.

Spawn menu — `+ Add` actions that drop softbody / fluid bodies into a world.

Each entry in :data:`SPAWN_ACTIONS` describes:

- ``label`` — text shown on the menu / button.
- ``factory`` — dotted import path of the callable that actually mutates
  the world (e.g. ``"softbody.body_builders.make_lattice"``).  Imported
  **lazily** on click so the editor stays useful even when the matching
  subsystem (softbody/fluid) isn't installed yet.
- ``spec`` — dataclass type describing the factory's input parameters.
  The modal renders one widget per dataclass field via the existing
  :class:`~pharos_engine.ui.editor.property_inspector.PropertyInspector`
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
# Phase B+ dynamics primitives (rope / ragdoll / IK).
#
# The underlying ``pharos_engine.dynamics`` builders accept the real
# ``RopeSpec`` / ``RagdollSpec`` / ``IKChainSpec`` plus extra positional
# arguments (anchor points, target points, root pin flags).  We mirror their
# primitive fields here as authoring specs so the property-inspector
# reflection picks each one up as a simple widget, and translate to the
# real spec + extra args inside small adapter factories below.
# ---------------------------------------------------------------------------

@dataclass
class RopeSpawnSpec:
    """Parameters for ``_spawn_rope`` — flattened :class:`RopeSpec` + anchors."""
    name: str = "rope"
    node_count: int = 16
    total_length: float = 32.0
    mass_per_node: float = 0.1
    stiffness: float = 1.0e6
    damping: float = 0.05
    bend_stiffness: float = 0.0
    anchor_a: tuple[float, float] = (0.0, 0.0)
    anchor_b: tuple[float, float] = (32.0, 0.0)
    anchor_a_pinned: bool = True
    anchor_b_pinned: bool = False


@dataclass
class RagdollSpawnSpec:
    """Parameters for ``_spawn_ragdoll`` — basic humanoid stick figure.

    Builds a default 4-bone skeleton (head, torso, two legs) at
    ``anchor_pos`` with the given segment ``bone_length``.  Stiffness /
    damping match :class:`RagdollSpec` defaults but expose them so authors
    can tune the rig without leaving the modal.
    """
    name: str = "ragdoll"
    anchor_pos: tuple[float, float] = (0.0, 0.0)
    bone_count: int = 4
    bone_length: float = 8.0
    bone_mass: float = 1.0
    stiffness: float = 5.0e6
    damping: float = 0.05
    pin_root: bool = True


@dataclass
class IKChainSpawnSpec:
    """Parameters for ``_spawn_ik_chain``.

    ``node_indices_csv`` is a CSV string the inspector can edit as a plain
    text field; the adapter parses it back to a list of ints before
    constructing the real :class:`IKChainSpec`.
    """
    name: str = "ik_chain"
    node_indices_csv: str = "0,1,2,3"
    target: tuple[float, float] = (16.0, 0.0)
    fixed_root: bool = True
    iterations: int = 10
    tolerance: float = 0.01


@dataclass
class HumanoidSpawnSpec:
    """Parameters for ``_spawn_humanoid``.

    Mirrors the keyword arguments of :func:`build_humanoid` as primitives
    so the property inspector can reflect each one as a plain widget. The
    resulting skeleton has 15 nodes (pelvis + neck + head + 2*(shoulder,
    elbow, wrist) + 2*(hip, knee, ankle)) — same anatomy described in
    :mod:`pharos_engine.dynamics.humanoid`.
    """
    name: str = "humanoid"
    root_position: tuple[float, float] = (0.0, 1.0)
    bone_mass: float = 1.0
    head_mass: float = 1.5
    bone_stiffness: float = 5.0e6
    bone_damping: float = 0.05
    bone_break_strain: float = 0.25


# ---------------------------------------------------------------------------
# Adapter factories for dynamics primitives.
#
# The dynamics builders take ``(spec, world, *extra)``; the spawn modal
# calls ``factory(world, **kwargs)``.  These adapters bridge the two —
# they live at module scope so :func:`_resolve_factory` can find them via
# the standard dotted-path lookup just like the softbody / fluid entries.
# ---------------------------------------------------------------------------

def _spawn_rope(world: Any, **kwargs: Any) -> Any:
    """Build a :class:`RopeSpec` from kwargs and call :func:`build_rope`."""
    from pharos_engine.dynamics.rope import RopeSpec, build_rope

    anchor_a = kwargs.pop("anchor_a", (0.0, 0.0))
    anchor_b = kwargs.pop("anchor_b", (32.0, 0.0))
    kwargs.pop("name", None)  # cosmetic only; not on RopeSpec
    spec = RopeSpec(**kwargs)
    return build_rope(spec, world, anchor_a, anchor_b)


def _spawn_ragdoll(world: Any, **kwargs: Any) -> Any:
    """Build a default ragdoll skeleton and call :func:`build_ragdoll`.

    Lays out ``bone_count`` bones in a vertical chain (root → tip), all
    with the same ``bone_length`` / ``bone_mass``.  Authors who need a
    custom topology should call :func:`build_ragdoll` directly with their
    own :class:`BoneSpec` list.
    """
    from pharos_engine.dynamics.ragdoll import (
        BoneSpec, RagdollSpec, build_ragdoll,
    )

    kwargs.pop("name", None)
    anchor_pos = kwargs.pop("anchor_pos", (0.0, 0.0))
    pin_root = kwargs.pop("pin_root", True)
    bone_count = int(kwargs.pop("bone_count", 4))
    bone_length = float(kwargs.pop("bone_length", 8.0))
    bone_mass = float(kwargs.pop("bone_mass", 1.0))

    bones: list[BoneSpec] = []
    for i in range(max(1, bone_count)):
        bones.append(
            BoneSpec(
                parent_idx=i - 1,
                length=bone_length,
                mass=bone_mass,
                direction=(0.0, -1.0),
                label=f"bone_{i}",
            )
        )
    spec = RagdollSpec(bones=bones, **kwargs)
    return build_ragdoll(spec, world, anchor_pos, pin_root=pin_root)


def _spawn_humanoid(world: Any, **kwargs: Any) -> Any:
    """Build a 15-node humanoid skeleton via :func:`build_humanoid`.

    Unlike rope / ragdoll which target the slim XPBD :class:`World`, the
    humanoid factory in :mod:`pharos_engine.dynamics.humanoid` expects a
    world that exposes the softbody ``.nodes`` / ``.beams`` SoA arrays —
    typically :class:`pharos_engine.softbody.world.SoftBodyWorld`. The
    adapter passes ``world`` through unchanged so authors can hand the
    editor either world type and get a clear ``TypeError`` if the world
    doesn't match (the build_humanoid guard fires immediately).
    """
    from pharos_engine.dynamics.humanoid import build_humanoid

    kwargs.pop("name", None)
    root_position = kwargs.pop("root_position", (0.0, 1.0))
    return build_humanoid(world, root_position=root_position, **kwargs)


def _spawn_ik_chain(world: Any, **kwargs: Any) -> bool:
    """Build an :class:`IKChainSpec` from kwargs and call :func:`solve_ik`.

    IK is a solver rather than a body — returns the bool result of
    :func:`solve_ik` (``True`` when the tip reaches the target).
    """
    from pharos_engine.dynamics.ik import IKChainSpec, solve_ik

    kwargs.pop("name", None)
    csv = kwargs.pop("node_indices_csv", "")
    node_indices = [
        int(piece.strip())
        for piece in csv.split(",")
        if piece.strip()
    ]
    target = kwargs.pop("target", (0.0, 0.0))
    fixed_root = bool(kwargs.pop("fixed_root", True))
    iterations = int(kwargs.pop("iterations", 10))
    tolerance = float(kwargs.pop("tolerance", 0.01))

    spec = IKChainSpec(
        node_indices=node_indices,
        target=target,
        fixed_root=fixed_root,
        **kwargs,
    )
    return solve_ik(spec, world, iterations=iterations, tolerance=tolerance)


# ---------------------------------------------------------------------------
# Action table.
#
# `factory` is a dotted path resolved at click time so a missing softbody/
# fluid backend doesn't break editor import.
# ---------------------------------------------------------------------------

SPAWN_ACTIONS: list[dict] = [
    {
        "label":   "Add SoftBody Lattice",
        "factory": "pharos_engine.softbody.body_builders.make_lattice",
        "spec":    LatticeSpec,
    },
    {
        "label":   "Add Layered Creature",
        "factory": "pharos_engine.softbody.body_builders.make_layered_creature",
        "spec":    CreatureSpec,
    },
    {
        "label":   "Add Vehicle",
        "factory": "pharos_engine.softbody.vehicle.build_vehicle",
        "spec":    VehicleSpec,
    },
    {
        "label":   "Add Fluid Pool",
        "factory": "pharos_engine.fluid.world.spawn_pool",
        "spec":    PoolSpec,
    },
    {
        "label":   "Add Sand Pile",
        "factory": "pharos_engine.fluid.world.spawn_sand_pile",
        "spec":    SandSpec,
    },
    {
        "label":   "Add Rope",
        "factory": "pharos_engine.ui.editor.spawn_menu._spawn_rope",
        "spec":    RopeSpawnSpec,
    },
    {
        "label":   "Add Ragdoll",
        "factory": "pharos_engine.ui.editor.spawn_menu._spawn_ragdoll",
        "spec":    RagdollSpawnSpec,
    },
    {
        "label":   "Add IK Chain",
        "factory": "pharos_engine.ui.editor.spawn_menu._spawn_ik_chain",
        "spec":    IKChainSpawnSpec,
    },
    {
        "label":   "Add Humanoid",
        "factory": "pharos_engine.ui.editor.spawn_menu._spawn_humanoid",
        "spec":    HumanoidSpawnSpec,
    },
]


# ---------------------------------------------------------------------------
# Factory resolution
# ---------------------------------------------------------------------------

def _resolve_factory(dotted: str) -> Callable[..., Any]:
    """Import and return the callable at the dotted import path *dotted*.

    Looks up first as ``pharos_engine.<dotted>``-style absolute path; if
    that fails (legacy entries omit the package prefix), falls back to
    ``pharos_engine.<dotted>``.  Raises ``ImportError`` if neither
    resolves.
    """
    candidates = [dotted]
    if not dotted.startswith("pharos_engine."):
        candidates.append(f"pharos_engine.{dotted}")

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
    from pharos_engine.ui.editor.property_inspector import PropertyInspector

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
