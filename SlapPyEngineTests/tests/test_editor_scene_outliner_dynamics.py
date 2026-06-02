"""Sprint 7G — scene outliner dynamics tree.

These tests exercise the data-layer enumeration of ``SceneOutliner.iter_dynamics_rows``
and verify the selection callback path. DPG is stubbed out (same pattern as
``test_editor_spawn_menu``) so the tests stay headless and run on CI without
a real GUI context.

Coverage matrix:

* ``test_empty_world_has_no_rows`` — a freshly-constructed ``World`` with
  zero bodies / zero joints produces an empty enumeration.
* ``test_single_rope_top_level_groups`` — spawning a rope yields the
  3-row spine: ``World``, ``Bodies (1)``, ``Joints (N)``.
* ``test_humanoid_body_surfaces_15_nodes`` — a body tagged ``humanoid``
  with ``node_count == 15`` produces a humanoid group entry whose label
  carries "15 nodes" and the body is reachable through the tree expansion.
* ``test_select_callback_fires_with_body_ref`` — clicking a body row
  invokes ``on_select`` with the underlying :class:`Body` instance.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# DPG stub fixture — identical no-op shape used by the other editor tests.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """Inject a no-op dearpygui.dearpygui module for the duration of a test."""
    class _CtxStub:
        def __enter__(self):
            return self
        def __exit__(self, *a, **kw):
            return False
        def __call__(self, *a, **kw):
            return self

    class _NoOpModule:
        def __getattr__(self, name):
            def _ctx(*a, **kw):
                return _CtxStub()
            return _ctx

        def does_item_exist(self, *a, **kw):
            return False

        def set_value(self, *a, **kw):
            return None

        def delete_item(self, *a, **kw):
            return None

        def get_item_children(self, *a, **kw):
            return []

    inst = _NoOpModule()
    stub = types.ModuleType("dearpygui.dearpygui")
    stub.__getattr__ = lambda name: getattr(inst, name)

    dpg_pkg = types.ModuleType("dearpygui")
    dpg_pkg.dearpygui = inst

    monkeypatch.setitem(sys.modules, "dearpygui", dpg_pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", inst)
    yield inst


# ---------------------------------------------------------------------------
# Import guards — skip the whole module if the editor + dynamics packages
# aren't importable in this checkout.
# ---------------------------------------------------------------------------

try:
    from slappyengine.ui.editor.scene_outliner import (  # noqa: F401
        SceneOutliner,
        _is_humanoid_body,
    )
    from slappyengine.dynamics.world import World as _DynWorld  # noqa: F401
    from slappyengine.dynamics.body import Body as _Body  # noqa: F401
except Exception as _import_err:  # pragma: no cover
    pytest.skip(
        f"scene_outliner or dynamics not importable: {_import_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spawn_rope(world):
    """Spawn the default Sprint 6 rope on *world* via the spawn-menu adapter.

    Resolves through the public spawn-menu surface so the test exercises the
    same code path the editor's ``+ Add`` button would.
    """
    from slappyengine.ui.editor.spawn_menu import (
        SPAWN_ACTIONS,
        _resolve_factory,
        _spec_to_kwargs,
    )
    action = next(a for a in SPAWN_ACTIONS if a["label"] == "Add Rope")
    spec = action["spec"]()
    kwargs = _spec_to_kwargs(spec)
    factory = _resolve_factory(action["factory"])
    return factory(world, **kwargs)


# ---------------------------------------------------------------------------
# Empty world
# ---------------------------------------------------------------------------

class TestEmptyWorld:
    def test_empty_world_has_no_rows(self):
        """Zero bodies + zero joints → empty enumeration (nothing to draw)."""
        from slappyengine.dynamics.world import World

        outliner = SceneOutliner()
        outliner.set_dynamics_world(World())
        rows = outliner.iter_dynamics_rows()
        assert rows == []

    def test_no_world_attached_returns_empty(self):
        """``iter_dynamics_rows`` is safe to call without a world."""
        outliner = SceneOutliner()
        assert outliner.iter_dynamics_rows() == []


# ---------------------------------------------------------------------------
# Single rope
# ---------------------------------------------------------------------------

class TestSingleRope:
    def test_single_rope_top_level_groups(self):
        """Spawning one rope yields the 3-row spine: World / Bodies / Joints."""
        from slappyengine.dynamics.world import World

        world = World()
        rope_body = _spawn_rope(world)
        assert rope_body in world.bodies

        outliner = SceneOutliner()
        outliner.set_dynamics_world(world)
        rows = outliner.iter_dynamics_rows()

        # Top-level structural rows (depth 0 or 1) — the 3-row spine.
        top_level = [r for r in rows if r["depth"] <= 1]
        types = [r["type"] for r in top_level]
        assert "world" in types
        assert "bodies_group" in types
        assert "joints_group" in types
        # No humanoid group for a plain rope.
        assert "humanoids_group" not in types
        assert len(top_level) == 3

        # The rope body is reachable as a body row.
        body_rows = [r for r in rows if r["type"] == "body"]
        assert len(body_rows) == 1
        assert body_rows[0]["ref"] is rope_body

        # And every solver joint shows up as a leaf with a non-None ref.
        joint_rows = [r for r in rows if r["type"] == "joint"]
        assert len(joint_rows) == len(world.joints)
        for row in joint_rows:
            assert row["ref"] is not None

    def test_joints_are_grouped_by_kind(self):
        """Joints sub-tree groups identical ``kind`` values together."""
        from slappyengine.dynamics.world import World

        world = World()
        _spawn_rope(world)

        outliner = SceneOutliner()
        outliner.set_dynamics_world(world)
        rows = outliner.iter_dynamics_rows()

        # At least one joint-kind group exists, and every joint leaf
        # appears after one (depth 3, parent depth 2).
        kind_groups = [r for r in rows if r["type"] == "joint_kind_group"]
        assert len(kind_groups) >= 1
        joint_leaves = [r for r in rows if r["type"] == "joint"]
        assert all(r["depth"] == 3 for r in joint_leaves)


# ---------------------------------------------------------------------------
# Humanoid body — tagged via parameters dict.
# ---------------------------------------------------------------------------

class TestHumanoidBody:
    def _world_with_humanoid_body(self):
        """Construct a dynamics world holding a humanoid-tagged Body."""
        import numpy as np
        from slappyengine.dynamics.world import World
        from slappyengine.dynamics.body import Body

        world = World()
        # The 15-node humanoid skeleton (pelvis + neck + head + 2 arms of 3
        # + 2 legs of 3) — only the count matters here.
        positions = np.zeros((15, 2), dtype=np.float64)
        world.add_nodes(positions, masses=1.0)
        body = Body(
            kind="ragdoll",
            parameters={"humanoid": True},
            node_offset=0,
            node_count=15,
            label="humanoid_0",
        )
        world.register_body(body)
        return world, body

    def test_humanoid_body_surfaces_15_nodes(self):
        """A humanoid-tagged body produces a Humanoids group entry."""
        world, body = self._world_with_humanoid_body()

        outliner = SceneOutliner()
        outliner.set_dynamics_world(world)
        rows = outliner.iter_dynamics_rows()

        # The new group must appear and carry the count of humanoid bodies.
        hum_groups = [r for r in rows if r["type"] == "humanoids_group"]
        assert len(hum_groups) == 1
        assert hum_groups[0]["label"] == "Humanoids (1)"

        # Drill-down row carries the 15-node count in its label and refs
        # back to the same Body object the user registered.
        humanoid_leaves = [r for r in rows if r["type"] == "humanoid"]
        assert len(humanoid_leaves) == 1
        assert "15 nodes" in humanoid_leaves[0]["label"]
        assert humanoid_leaves[0]["ref"] is body

    def test_humanoid_helper_predicate(self):
        """``_is_humanoid_body`` matches both tag and kind conventions."""
        from slappyengine.dynamics.body import Body

        tagged = Body(kind="ragdoll", parameters={"humanoid": True})
        kinded = Body(kind="humanoid", parameters={})
        plain  = Body(kind="rope", parameters={})

        assert _is_humanoid_body(tagged)
        assert _is_humanoid_body(kinded)
        assert not _is_humanoid_body(plain)


# ---------------------------------------------------------------------------
# Selection callback — clicking a body row routes the ref to the inspector.
# ---------------------------------------------------------------------------

class TestSelectionCallback:
    def test_select_callback_fires_with_body_ref(self):
        """`_on_select_dynamics` invokes the registered on-select hook."""
        from slappyengine.dynamics.world import World

        world = World()
        rope_body = _spawn_rope(world)

        outliner = SceneOutliner()
        outliner.set_dynamics_world(world)

        captured: list = []
        outliner.set_on_select(lambda ref: captured.append(ref))

        outliner._on_select_dynamics(rope_body)
        assert captured == [rope_body]
        # The selection state should track the routed reference so the
        # PropertyInspector can be wired straight off `get_selected`.
        assert outliner.get_selected() is rope_body

    def test_select_callback_fires_with_joint_ref(self):
        """Joint clicks also route through the standard hook."""
        from slappyengine.dynamics.world import World

        world = World()
        _spawn_rope(world)
        first_joint = world.joints[0]

        outliner = SceneOutliner()
        outliner.set_dynamics_world(world)

        captured: list = []
        outliner.set_on_select(lambda ref: captured.append(ref))

        outliner._on_select_dynamics(first_joint)
        assert captured == [first_joint]
        assert outliner.get_selected() is first_joint

    def test_select_callback_ignores_structural_ref_none(self):
        """Structural (group) rows have ``ref is None`` and never fire."""
        outliner = SceneOutliner()
        fired: list = []
        outliner.set_on_select(lambda ref: fired.append(ref))
        outliner._on_select_dynamics(None)
        assert fired == []
