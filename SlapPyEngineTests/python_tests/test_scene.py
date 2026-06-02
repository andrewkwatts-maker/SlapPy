"""Engine tests for Scene — headless (no GPU required)."""
from __future__ import annotations
import asyncio
import pytest


# ---------------------------------------------------------------------------
# Scene — basic construction
# ---------------------------------------------------------------------------

class TestSceneDefaults:
    def test_instantiates(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s is not None

    def test_default_name(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.name == "Scene"

    def test_custom_name(self):
        from slappyengine.scene import Scene
        s = Scene("Race01")
        assert s.name == "Race01"

    def test_starts_empty(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert len(s) == 0

    def test_bus_and_events_same_object(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.bus is s.events

    def test_strata_defaults_none(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.strata is None

    def test_camera_defaults_none(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.camera is None

    def test_post_process_defaults_empty(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.post_process == []


# ---------------------------------------------------------------------------
# Scene.add / remove / get / len
# ---------------------------------------------------------------------------

class TestSceneAddRemove:
    def test_add_returns_entity(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = Entity(name="player")
        result = s.add(e)
        assert result is e

    def test_add_increments_len(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        s.add(Entity())
        assert len(s) == 1

    def test_add_two_increments_to_two(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        s.add(Entity())
        s.add(Entity())
        assert len(s) == 2

    def test_remove_decrements_len(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity())
        s.remove(e)
        assert len(s) == 0

    def test_get_by_id(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity(name="hero"))
        result = s.get(e.id)
        assert result is e

    def test_get_missing_returns_none(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.get("nonexistent-id") is None

    def test_add_sets_scene_back_reference(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity())
        assert e.scene is s

    def test_remove_clears_scene_back_reference(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity())
        s.remove(e)
        assert e.scene is None

    def test_remove_removes_from_get(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity())
        eid = e.id
        s.remove(e)
        assert s.get(eid) is None

    def test_add_fires_entity_created_event(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        fired = []
        s.bus.subscribe("entity:created", lambda evt: fired.append(evt))
        s.add(Entity(name="x"))
        assert len(fired) == 1

    def test_remove_fires_entity_destroyed_event(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        fired = []
        s.bus.subscribe("entity:destroyed", lambda evt: fired.append(evt))
        e = s.add(Entity())
        s.remove(e)
        assert len(fired) == 1


# ---------------------------------------------------------------------------
# Scene.entities / find_by_name / find_by_tag
# ---------------------------------------------------------------------------

class TestSceneQuery:
    def test_entities_returns_list(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        s.add(Entity(name="a"))
        s.add(Entity(name="b"))
        result = s.entities
        assert isinstance(result, list)
        assert len(result) == 2

    def test_entities_empty_on_new_scene(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.entities == []

    def test_find_by_name_returns_matching(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e1 = s.add(Entity(name="enemy"))
        e2 = s.add(Entity(name="player"))
        s.add(Entity(name="enemy"))
        results = s.find_by_name("enemy")
        assert len(results) == 2
        assert e1 in results

    def test_find_by_name_no_match_returns_empty(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        s.add(Entity(name="hero"))
        assert s.find_by_name("villain") == []

    def test_find_by_tag_returns_matching(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e1 = s.add(Entity())
        e1.tags.add("enemy")
        e2 = s.add(Entity())
        e2.tags.add("player")
        results = s.find_by_tag("enemy")
        assert len(results) == 1
        assert results[0] is e1

    def test_find_by_tag_no_match_returns_empty(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        e = s.add(Entity())
        e.tags.add("npc")
        assert s.find_by_tag("boss") == []


# ---------------------------------------------------------------------------
# Z-layer management
# ---------------------------------------------------------------------------

class TestSceneZLayers:
    def _make_z_layer(self, z: float, name: str = ""):
        class _ZL:
            def __init__(self, z, name):
                self.z = z
                self.name = name
        return _ZL(z, name)

    def test_z_layers_empty_initially(self):
        from slappyengine.scene import Scene
        s = Scene()
        assert s.z_layers == []

    def test_add_z_layer_appends(self):
        from slappyengine.scene import Scene
        s = Scene()
        layer = self._make_z_layer(0.0, "ground")
        s.add_z_layer(layer)
        assert len(s.z_layers) == 1

    def test_add_z_layer_sorts_by_z(self):
        from slappyengine.scene import Scene
        s = Scene()
        high = self._make_z_layer(10.0, "sky")
        low = self._make_z_layer(0.0, "ground")
        mid = self._make_z_layer(5.0, "mid")
        s.add_z_layer(high)
        s.add_z_layer(low)
        s.add_z_layer(mid)
        zs = [l.z for l in s.z_layers]
        assert zs == sorted(zs)

    def test_remove_z_layer_removes(self):
        from slappyengine.scene import Scene
        s = Scene()
        layer = self._make_z_layer(0.0)
        s.add_z_layer(layer)
        s.remove_z_layer(layer)
        assert len(s.z_layers) == 0

    def test_remove_nonexistent_z_layer_no_crash(self):
        from slappyengine.scene import Scene
        s = Scene()
        layer = self._make_z_layer(0.0)
        s.remove_z_layer(layer)  # should not raise


# ---------------------------------------------------------------------------
# Scene._tick and simulate
# ---------------------------------------------------------------------------

class TestSceneTick:
    def test_tick_calls_entity_tick(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        tick_count = []
        class TrackingEntity(Entity):
            def tick(self, dt):
                tick_count.append(dt)
        e = s.add(TrackingEntity())
        s._tick(0.016)
        assert len(tick_count) == 1
        assert tick_count[0] == pytest.approx(0.016)

    def test_tick_multiple_entities(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        count = [0]
        class CountEntity(Entity):
            def tick(self, dt):
                count[0] += 1
        s.add(CountEntity())
        s.add(CountEntity())
        s._tick(0.016)
        assert count[0] == 2

    def test_simulate_runs_steps(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        count = [0]
        class CountEntity(Entity):
            def tick(self, dt):
                count[0] += 1
        s.add(CountEntity())
        asyncio.run(s.simulate(steps=3, dt=0.016))
        assert count[0] == 3

    def test_simulate_passes_dt(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        dts = []
        class DtEntity(Entity):
            def tick(self, dt):
                dts.append(dt)
        s.add(DtEntity())
        asyncio.run(s.simulate(steps=2, dt=0.033))
        assert all(d == pytest.approx(0.033) for d in dts)

    def test_tick_publishes_collision_events(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        from slappyengine.collision import AABBShape
        s = Scene()
        collisions = []
        s.bus.subscribe("collision", lambda evt: collisions.append(evt))
        # Add two overlapping AABB entities
        e1 = Entity(name="a", position=(0.0, 0.0))
        e1.collision_shape = AABBShape(width=10, height=10)
        e2 = Entity(name="b", position=(5.0, 0.0))
        e2.collision_shape = AABBShape(width=10, height=10)
        s.add(e1)
        s.add(e2)
        s._tick(0.016)
        # Entities overlap, so collision event should have fired
        assert len(collisions) >= 1


# ---------------------------------------------------------------------------
# Scene entity lifecycle hooks
# ---------------------------------------------------------------------------

class TestSceneEntityLifecycle:
    def test_on_create_called_on_add(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        created = []
        class TrackEntity(Entity):
            def on_create(self):
                created.append(True)
        s.add(TrackEntity())
        assert created == [True]

    def test_on_destroy_called_on_remove(self):
        from slappyengine.scene import Scene
        from slappyengine.entity import Entity
        s = Scene()
        destroyed = []
        class TrackEntity(Entity):
            def on_destroy(self):
                destroyed.append(True)
        e = s.add(TrackEntity())
        s.remove(e)
        assert destroyed == [True]
