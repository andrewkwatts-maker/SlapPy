"""Tests for the outliner spawn menu (pure-logic, no DPG needed).

Two surfaces are exercised:

* The label-registry API — :class:`SpawnAction`, :class:`SpawnMenu`,
  :func:`default_spawn_menu` — used by the outliner's '+ Add' popup.
* The high-level method API — :meth:`SpawnMenu.add_lattice_body` etc.
  plus :func:`create_spawn_menu` — used by code-mode / scripted spawns.
"""
from __future__ import annotations

import warnings

import pytest

from pharos_engine.fluid import FluidWorld
from pharos_engine.softbody import SoftBodyWorld
from pharos_engine.ui.editor.spawn_menu import (
    SpawnAction,
    SpawnMenu,
    create_spawn_menu,
    default_spawn_menu,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── SpawnMenu basics ────────────────────────────────────────────────────────


def test_empty_menu_has_no_actions():
    m = SpawnMenu()
    assert m.actions() == []


def test_register_preserves_insertion_order():
    m = SpawnMenu()
    m.register(SpawnAction("Z", target="softbody", factory=lambda w: None))
    m.register(SpawnAction("A", target="softbody", factory=lambda w: None))
    m.register(SpawnAction("M", target="softbody", factory=lambda w: None))
    labels = [a.label for a in m.actions()]
    assert labels == ["Z", "A", "M"]


def test_register_same_label_overwrites_factory():
    m = SpawnMenu()
    m.register(SpawnAction("A", target="softbody", factory=lambda w: "v1"))
    m.register(SpawnAction("A", target="softbody", factory=lambda w: "v2"))
    assert m.invoke("A", None) == "v2"
    assert len(m.actions()) == 1


def test_unregister_removes_action():
    m = SpawnMenu()
    m.register(SpawnAction("A", target="softbody", factory=lambda w: None))
    assert m.unregister("A") is True
    assert m.unregister("A") is False
    assert m.actions() == []


def test_invoke_unknown_label_raises_keyerror():
    m = SpawnMenu()
    with pytest.raises(KeyError):
        m.invoke("missing", None)


def test_invoke_passes_kwargs_to_factory():
    m = SpawnMenu()
    captured: dict = {}
    m.register(SpawnAction(
        "X", target="softbody",
        factory=lambda w, **kw: captured.update(kw),
    ))
    m.invoke("X", None, foo=42, bar="baz")
    assert captured == {"foo": 42, "bar": "baz"}


# ── Default menu — exercises real factories ────────────────────────────────


def test_default_menu_has_all_default_actions():
    m = default_spawn_menu()
    labels = {a.label for a in m.actions()}
    expected = {
        "Add SoftBody Lattice",
        "Add Layered Creature",
        "Add Humanoid",
        "Add Vehicle",
        "Add Rope",
        "Add Ragdoll",
        "Add Fluid Pool",
        "Add Sand Pile",
        "Add Lava Blob",
    }
    assert expected.issubset(labels)


def test_default_menu_spawn_lattice_into_softbody_world():
    m = default_spawn_menu()
    w = SoftBodyWorld()
    n_before = w.nodes.count
    meta = m.invoke("Add SoftBody Lattice", w, width_cells=2, height_cells=2)
    assert w.nodes.count > n_before
    assert hasattr(meta, "node_slice")


def test_default_menu_spawn_vehicle_into_softbody_world():
    m = default_spawn_menu()
    w = SoftBodyWorld()
    handle = m.invoke("Add Vehicle", w, drivetrain_mode="awd")
    assert hasattr(handle, "wheel_hubs")
    assert len(handle.wheel_hubs) == 2


def test_default_menu_spawn_rope_returns_slice_and_beams():
    m = default_spawn_menu()
    w = SoftBodyWorld()
    n_s, n_e, beams = m.invoke("Add Rope", w, segment_count=8)
    assert n_e - n_s == 9
    assert len(beams) == 8


def test_default_menu_spawn_ragdoll_creates_bone_nodes():
    m = default_spawn_menu()
    w = SoftBodyWorld()
    n_s, n_e, beams = m.invoke("Add Ragdoll", w)
    # 4 bones × 2 nodes = 8 nodes
    assert n_e - n_s == 8


def test_default_menu_spawn_fluid_pool_into_fluid_world():
    m = default_spawn_menu()
    w = FluidWorld()
    n_before = w.particles.count
    m.invoke("Add Fluid Pool", w, nx=4, ny=4)
    assert w.particles.count == n_before + 16


def test_default_menu_spawn_lava_blob_uses_high_temperature():
    m = default_spawn_menu()
    w = FluidWorld()
    m.invoke("Add Lava Blob", w, nx=2, ny=2, temperature=1500.0)
    # All spawned particles inherit the requested temperature.
    assert (w.particles.temperature == 1500.0).all()


def test_action_target_groups_routes_correctly():
    """The 'target' field declares which world an action belongs to."""
    m = default_spawn_menu()
    sb_actions = [a for a in m.actions() if a.target == "softbody"]
    fl_actions = [a for a in m.actions() if a.target == "fluid"]
    # softbody: lattice, creature, humanoid, vehicle, rope, ragdoll
    assert len(sb_actions) == 6
    # fluid: pool, sand, lava
    assert len(fl_actions) == 3


# ── High-level method API — the Sprint 4 deliverables ─────────────────────


def test_add_lattice_body_creates_body_in_world():
    """add_lattice_body writes a new body's worth of nodes + beams into the
    SoftBodyWorld the caller passes in and returns the BodyMeta."""
    menu = create_spawn_menu()
    world = SoftBodyWorld()
    nodes_before = world.nodes.count
    beams_before = world.beams.count
    bodies_before = len(world.bodies)

    meta = menu.add_lattice_body(world, material="wood",
                                 width_cells=4, height_cells=4,
                                 cell_size=0.10,
                                 position=(0.0, 0.0))

    assert hasattr(meta, "body_id")
    assert hasattr(meta, "node_slice")
    # 5×5 grid of nodes for a 4×4 cell lattice.
    n_s, n_e = meta.node_slice
    assert n_e - n_s == 25
    assert world.nodes.count == nodes_before + 25
    assert world.beams.count > beams_before
    assert len(world.bodies) == bodies_before + 1


def test_add_humanoid_returns_skeleton_handle_and_18_nodes():
    """add_humanoid returns a HumanoidSkeleton with all 18 named joints
    populated and 18 fresh bone nodes in the softbody world."""
    menu = create_spawn_menu()
    world = SoftBodyWorld()
    nodes_before = world.nodes.count

    skeleton = menu.add_humanoid(world, root_position=(0.0, 1.0))

    # Returned object exposes the named-joint API.
    for name in ("head", "neck", "chest", "pelvis",
                 "shoulder_l", "shoulder_r",
                 "elbow_l", "elbow_r",
                 "wrist_l", "wrist_r",
                 "hip_l", "hip_r",
                 "knee_l", "knee_r",
                 "ankle_l", "ankle_r",
                 "toe_l", "toe_r"):
        assert getattr(skeleton, name) >= 0, f"{name!r} not assigned"
    # Exactly 18 fresh nodes were added by the skeleton.
    n_s, n_e = skeleton.node_slice
    assert n_e - n_s == 18
    assert world.nodes.count == nodes_before + 18
    assert len(skeleton.all_bone_nodes()) == 18


def test_add_vehicle_default_awd_drivetrain():
    """add_vehicle defaults to AWD — every wheel is a drive wheel."""
    menu = create_spawn_menu()
    world = SoftBodyWorld()

    handle = menu.add_vehicle(world)  # default drivetrain="awd"

    assert len(handle.wheel_hubs) == 2
    # AWD ⇒ all wheels drive.
    assert sorted(handle.drive_wheel_indices) == [0, 1]


def test_add_fluid_pool_adds_particles():
    """add_fluid_pool appends nx*ny particles to the given FluidWorld."""
    menu = create_spawn_menu()
    fworld = FluidWorld()
    p_before = fworld.particles.count

    first_idx = menu.add_fluid_pool(
        fworld, material="water",
        nx=14, ny=10, spacing=0.06,
        origin=(0.0, 2.0),
    )

    assert first_idx == p_before
    assert fworld.particles.count == p_before + 14 * 10


def test_add_sand_pile_uses_sand_material():
    """add_sand_pile is a convenience wrapper that pins material to 'sand'."""
    from pharos_engine.fluid import SAND

    menu = create_spawn_menu()
    fworld = FluidWorld()

    first_idx = menu.add_sand_pile(fworld, nx=6, ny=4)

    # The sand material should now be registered on the world.
    assert SAND in fworld.materials
    sand_id = fworld.materials.index(SAND)
    # And all particles spawned by this call must reference it.
    spawned = fworld.particles.material_id[first_idx:fworld.particles.count]
    assert spawned.size == 6 * 4
    assert (spawned == sand_id).all()


def test_spawn_menu_with_explicit_world_does_not_create_new_world():
    """When the caller passes a world in, the menu must mutate THAT world —
    not silently construct a fresh one (which would orphan the spawn)."""
    menu = create_spawn_menu()

    # SoftBody variant.
    sb = SoftBodyWorld()
    sb_id_before = id(sb)
    meta = menu.add_lattice_body(sb, width_cells=2, height_cells=2)
    # The body was registered against the caller's world, not a fresh one.
    assert sb.nodes.count > 0
    assert meta.body_id in {b.body_id for b in sb.bodies}
    # The caller's reference must still point at the same world object.
    assert id(sb) == sb_id_before

    # Fluid variant.
    fw = FluidWorld()
    fw_id_before = id(fw)
    n_before = fw.particles.count
    menu.add_fluid_pool(fw, nx=3, ny=3)
    assert fw.particles.count == n_before + 9
    assert id(fw) == fw_id_before
