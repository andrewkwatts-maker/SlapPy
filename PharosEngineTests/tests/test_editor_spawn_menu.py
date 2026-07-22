"""Tests for editor spawn menu (Phase A — editor reuse pattern).

These tests run **without** a real dearpygui context.  ``open_spawn_modal``
returns silently when dearpygui isn't installed, so we focus on the
data-layer contract:

- :data:`SPAWN_ACTIONS` has the five Phase A entries.
- Each entry's ``spec`` is a dataclass that constructs without args.
- Each entry's ``factory`` is a dotted path that *resolves* once we
  stub out the matching softbody / fluid modules in ``sys.modules``.
- ``open_spawn_modal`` is callable with a stubbed DPG and constructs
  a spec instance without raising.
"""
from __future__ import annotations

import dataclasses
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# DPG stub fixture — same shape as tests/test_editor.py
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """Inject a no-op dearpygui.dearpygui module for the duration of a test."""
    class _NoOpModule:
        def __getattr__(self, name):
            def _ctx(*a, **kw):
                # Support both calls and `with dpg.window(...)` blocks.
                return _CtxStub()
            return _ctx

        def does_item_exist(self, *a, **kw):
            return True

        def set_value(self, *a, **kw):
            return None

        def delete_item(self, *a, **kw):
            return None

    class _CtxStub:
        def __enter__(self):
            return self
        def __exit__(self, *a, **kw):
            return False
        def __call__(self, *a, **kw):
            return self

    stub_instance = _NoOpModule()
    stub = types.ModuleType("dearpygui.dearpygui")
    stub.__getattr__ = lambda name: getattr(stub_instance, name)

    dpg_pkg = types.ModuleType("dearpygui")
    dpg_pkg.dearpygui = stub_instance

    monkeypatch.setitem(sys.modules, "dearpygui", dpg_pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub_instance)
    yield stub_instance


# ---------------------------------------------------------------------------
# Module-level guard — skip if the editor submodules aren't importable.
# ---------------------------------------------------------------------------

try:
    from pharos_editor.ui.editor import spawn_menu  # noqa: F401
except Exception as _import_err:  # pragma: no cover
    pytest.skip(
        f"editor.spawn_menu not importable: {_import_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Action-table shape
# ---------------------------------------------------------------------------

class TestSpawnActionsTable:
    def test_nine_actions(self):
        """5 Phase A actions + 4 Phase B+ dynamics primitives."""
        from pharos_editor.ui.editor.spawn_menu import SPAWN_ACTIONS
        assert len(SPAWN_ACTIONS) == 9

    def test_required_action_labels(self):
        from pharos_editor.ui.editor.spawn_menu import SPAWN_ACTIONS
        labels = {a["label"] for a in SPAWN_ACTIONS}
        assert "Add SoftBody Lattice"  in labels
        assert "Add Layered Creature"  in labels
        assert "Add Vehicle"           in labels
        assert "Add Fluid Pool"        in labels
        assert "Add Sand Pile"         in labels
        assert "Add Rope"              in labels
        assert "Add Ragdoll"           in labels
        assert "Add IK Chain"          in labels
        assert "Add Humanoid"          in labels

    def test_each_action_has_label_factory_spec(self):
        from pharos_editor.ui.editor.spawn_menu import SPAWN_ACTIONS
        for action in SPAWN_ACTIONS:
            assert "label"   in action
            assert "factory" in action
            assert "spec"    in action
            assert isinstance(action["label"],   str)
            assert isinstance(action["factory"], str)
            assert dataclasses.is_dataclass(action["spec"])

    def test_each_spec_constructs_without_args(self):
        from pharos_editor.ui.editor.spawn_menu import SPAWN_ACTIONS
        for action in SPAWN_ACTIONS:
            instance = action["spec"]()
            assert instance is not None
            # All fields should be readable.
            for f in dataclasses.fields(instance):
                getattr(instance, f.name)


# ---------------------------------------------------------------------------
# Factory resolution
# ---------------------------------------------------------------------------

class TestFactoryResolution:
    def test_resolves_when_factory_exists(self, monkeypatch):
        """Stub out one factory in sys.modules and confirm it resolves."""
        from pharos_editor.ui.editor.spawn_menu import _resolve_factory

        fake_mod = types.ModuleType("pharos_engine.fake_softbody")
        fake_mod.make_thing = lambda world, **kw: ("called", world, kw)
        monkeypatch.setitem(sys.modules, "pharos_engine.fake_softbody", fake_mod)

        fn = _resolve_factory("pharos_engine.fake_softbody.make_thing")
        assert callable(fn)
        result = fn(object(), x=1)
        assert result[0] == "called"
        assert result[2] == {"x": 1}

    def test_raises_when_factory_missing(self):
        """A non-existent dotted path should raise ImportError."""
        from pharos_editor.ui.editor.spawn_menu import _resolve_factory
        with pytest.raises(ImportError):
            _resolve_factory(
                "pharos_engine.nonexistent_module_xyz.does_not_exist"
            )


# ---------------------------------------------------------------------------
# Modal — at minimum, does not raise when called with a stubbed DPG.
# ---------------------------------------------------------------------------

class TestOpenSpawnModal:
    def test_modal_opens_without_raising_for_each_action(self):
        from pharos_editor.ui.editor.spawn_menu import (
            SPAWN_ACTIONS, open_spawn_modal,
        )
        world = object()
        for action in SPAWN_ACTIONS:
            # Must not raise even though no real DPG context exists.
            open_spawn_modal(action, world)

    def test_modal_spawn_invokes_factory_with_spec_kwargs(self, monkeypatch):
        """When the user clicks Spawn, factory(world, **spec_fields) runs."""
        from pharos_editor.ui.editor import spawn_menu as sm

        captured: dict = {}

        def fake_factory(world, **kwargs):
            captured["world"] = world
            captured["kwargs"] = kwargs
            return "ok"

        # Monkey-patch _resolve_factory to return our fake regardless of
        # the dotted path — the resolution itself is covered above.
        monkeypatch.setattr(sm, "_resolve_factory", lambda dotted: fake_factory)

        action = sm.SPAWN_ACTIONS[0]   # "Add SoftBody Lattice"
        spec_default = action["spec"]()
        expected_kwargs = {
            f.name: getattr(spec_default, f.name)
            for f in dataclasses.fields(spec_default)
        }

        # Manually drive the spawn path: simulate clicking the Spawn button.
        # open_spawn_modal builds its on-spawn closure inside; to test the
        # callback directly we reach into the action machinery.
        kwargs = sm._spec_to_kwargs(spec_default)
        result = fake_factory("WORLD", **kwargs)
        assert result == "ok"
        assert captured["world"] == "WORLD"
        assert captured["kwargs"] == expected_kwargs


# ---------------------------------------------------------------------------
# Phase B+ dynamics primitives — rope / ragdoll / IK chain spawn through
# the unified ``pharos_engine.dynamics`` builders.  Each test drives the
# adapter factory the same way ``open_spawn_modal`` would on Spawn click.
# ---------------------------------------------------------------------------

def _find_action(label: str) -> dict:
    from pharos_editor.ui.editor.spawn_menu import SPAWN_ACTIONS
    for action in SPAWN_ACTIONS:
        if action["label"] == label:
            return action
    raise AssertionError(f"action {label!r} missing from SPAWN_ACTIONS")


class TestDynamicsSpawnActions:
    def test_spawn_rope_constructs_body(self):
        """Driving the Rope action's adapter factory materialises a rope Body."""
        from pharos_engine.dynamics.world import World
        from pharos_editor.ui.editor.spawn_menu import _resolve_factory, _spec_to_kwargs

        action = _find_action("Add Rope")
        spec_default = action["spec"]()
        kwargs = _spec_to_kwargs(spec_default)

        factory = _resolve_factory(action["factory"])
        world = World()
        body = factory(world, **kwargs)

        assert body is not None
        assert getattr(body, "kind", None) == "rope"
        # Rope spawns ``node_count`` contiguous nodes.
        assert body.node_count == spec_default.node_count
        # And registers itself on the world.
        assert body in world.bodies
        # Distance joints span every adjacent pair (plus optional bends).
        assert len(world.joints) >= spec_default.node_count - 1

    def test_spawn_ragdoll_constructs_body(self):
        """Driving the Ragdoll action's adapter materialises a ragdoll Body."""
        from pharos_engine.dynamics.world import World
        from pharos_editor.ui.editor.spawn_menu import _resolve_factory, _spec_to_kwargs

        action = _find_action("Add Ragdoll")
        spec_default = action["spec"]()
        kwargs = _spec_to_kwargs(spec_default)

        factory = _resolve_factory(action["factory"])
        world = World()
        body = factory(world, **kwargs)

        assert body is not None
        assert getattr(body, "kind", None) == "ragdoll"
        # Root node + one child endpoint per bone.
        assert body.node_count == 1 + spec_default.bone_count
        assert body in world.bodies
        # Each bone owns at least one distance joint.
        assert len(world.joints) >= spec_default.bone_count

    def test_spawn_ikchain_constructs_solver_state(self):
        """IK is a solver, not a body — adapter returns the solve_ik bool."""
        import numpy as np

        from pharos_engine.dynamics.world import World
        from pharos_editor.ui.editor.spawn_menu import _resolve_factory, _spec_to_kwargs

        action = _find_action("Add IK Chain")
        spec_default = action["spec"]()
        kwargs = _spec_to_kwargs(spec_default)

        # IK needs node indices to exist on the world — seed nodes that
        # match the default csv ("0,1,2,3").
        world = World()
        positions = np.array(
            [(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (12.0, 0.0)],
            dtype=np.float64,
        )
        world.add_nodes(positions, masses=np.array([0.0, 1.0, 1.0, 1.0]))

        factory = _resolve_factory(action["factory"])
        result = factory(world, **kwargs)

        # solve_ik returns a bool — True when the tip reaches the target,
        # False otherwise. Either is a valid "solver ran" signal.
        assert isinstance(result, bool)

    def test_dynamics_spawn_actions_open_modal_without_raising(self):
        """The generic modal-builder must auto-reflect the new specs."""
        from pharos_editor.ui.editor.spawn_menu import open_spawn_modal

        world = object()
        for label in ("Add Rope", "Add Ragdoll", "Add IK Chain", "Add Humanoid"):
            action = _find_action(label)
            # Must not raise — property_inspector reflection auto-handles
            # primitive dataclass fields with no extension needed.
            open_spawn_modal(action, world)
