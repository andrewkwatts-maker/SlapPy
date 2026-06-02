"""Tests for SceneOutliner spawn-menu wiring (no DPG required)."""
from __future__ import annotations

import warnings

import pytest

from slappyengine.fluid import FluidWorld
from slappyengine.softbody import SoftBodyWorld
from slappyengine.ui.editor.scene_outliner import SceneOutliner


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


def test_outliner_has_lazy_spawn_menu():
    o = SceneOutliner()
    # Lazy: first call constructs, subsequent calls return the same instance.
    m1 = o.spawn_menu()
    m2 = o.spawn_menu()
    assert m1 is m2
    assert len(m1.actions()) >= 8


def test_set_spawn_worlds_attaches_targets():
    o = SceneOutliner()
    sb = SoftBodyWorld()
    fl = FluidWorld()
    o.set_spawn_worlds(softbody_world=sb, fluid_world=fl)
    # Programmatic invoke routes to the correct world.
    meta = o.invoke_spawn("Add SoftBody Lattice",
                          width_cells=2, height_cells=2)
    assert sb.nodes.count > 0
    assert hasattr(meta, "node_slice")
    n_before = fl.particles.count
    o.invoke_spawn("Add Fluid Pool", nx=3, ny=3)
    assert fl.particles.count > n_before


def test_invoke_spawn_unknown_label_raises():
    o = SceneOutliner()
    o.set_spawn_worlds(softbody_world=SoftBodyWorld())
    with pytest.raises(KeyError):
        o.invoke_spawn("nope")


def test_invoke_spawn_without_target_world_raises():
    o = SceneOutliner()
    # No softbody world attached, but we try a softbody-targeted action.
    o.set_spawn_worlds(softbody_world=None, fluid_world=FluidWorld())
    with pytest.raises(RuntimeError):
        o.invoke_spawn("Add SoftBody Lattice")


def test_on_spawn_callback_fires_with_obj_and_label():
    o = SceneOutliner()
    sb = SoftBodyWorld()
    o.set_spawn_worlds(softbody_world=sb)
    events: list = []
    o.set_on_spawn(lambda obj, lbl: events.append((obj, lbl)))
    o.invoke_spawn("Add SoftBody Lattice", width_cells=2, height_cells=2)
    assert len(events) == 1
    obj, lbl = events[0]
    assert lbl == "Add SoftBody Lattice"
    assert hasattr(obj, "node_slice")


def test_spawn_routes_to_fluid_world_correctly():
    """Even with a softbody world attached, fluid-targeted actions route to
    the fluid world (and vice versa)."""
    o = SceneOutliner()
    sb = SoftBodyWorld()
    fl = FluidWorld()
    o.set_spawn_worlds(softbody_world=sb, fluid_world=fl)

    sb_nodes_before = sb.nodes.count
    o.invoke_spawn("Add Fluid Pool", nx=3, ny=3)
    # Softbody world should be untouched
    assert sb.nodes.count == sb_nodes_before
    # Fluid world should have new particles
    assert fl.particles.count == 9


def test_on_add_entity_is_safe_to_call_without_dpg():
    """The default `_on_add_entity` is a no-op that doesn't open DPG modals.
    The editor shell overrides it with a real popup."""
    o = SceneOutliner()
    # Must not raise even without spawn worlds attached.
    o._on_add_entity()


def test_invoke_spawn_does_not_touch_dpg_in_headless_test():
    """`invoke_spawn` is callable from non-DPG contexts (tests, batch
    tooling). The caller is responsible for refreshing the UI when they
    have an active DPG context."""
    o = SceneOutliner()
    sb = SoftBodyWorld()
    o.set_spawn_worlds(softbody_world=sb)
    # No DPG context at all here.
    o.invoke_spawn("Add SoftBody Lattice", width_cells=2, height_cells=2)
    assert sb.nodes.count > 0
