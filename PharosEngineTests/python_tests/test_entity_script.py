"""Engine tests for entity.py and script.py — Entity lifecycle, component system,
Script base class, ScriptComponent. All headless — no GPU required.
"""
from __future__ import annotations
import pytest


class TestEntityDefaults:
    def test_instantiates(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e is not None

    def test_id_is_string(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert isinstance(e.id, str)

    def test_ids_are_unique(self):
        from pharos_engine.entity import Entity
        a = Entity()
        b = Entity()
        assert a.id != b.id

    def test_name_stored(self):
        from pharos_engine.entity import Entity
        e = Entity(name="Player")
        assert e.name == "Player"

    def test_position_stored(self):
        from pharos_engine.entity import Entity
        e = Entity(position=(100.0, 200.0))
        assert e.position == (100.0, 200.0)

    def test_default_name_empty(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.name == ""

    def test_default_position_origin(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.position == (0.0, 0.0)

    def test_default_rotation_zero(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.rotation == pytest.approx(0.0)

    def test_default_scale_one(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.scale == pytest.approx(1.0)

    def test_default_tags_empty(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.tags == set()

    def test_default_collision_shape_none(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.collision_shape is None

    def test_default_strata_layer_zero(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.strata_layer == 0

    def test_default_z_height_zero(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.z_height == pytest.approx(0.0)

    def test_default_z_layer_none(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.z_layer is None

    def test_default_data_none(self):
        from pharos_engine.entity import Entity
        e = Entity()
        assert e.data is None


class TestEntityMutability:
    def test_position_mutable(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.position = (50.0, 75.0)
        assert e.position == (50.0, 75.0)

    def test_rotation_mutable(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.rotation = 45.0
        assert e.rotation == pytest.approx(45.0)

    def test_scale_mutable(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.scale = 2.0
        assert e.scale == pytest.approx(2.0)

    def test_tags_mutable(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.tags.add("enemy")
        assert "enemy" in e.tags

    def test_strata_layer_mutable(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.strata_layer = 3
        assert e.strata_layer == 3


class TestEntityScriptAttachment:
    def test_attach_script_no_crash(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import Script
        class Dummy(Script): pass
        e = Entity()
        e.attach_script(Dummy())

    def test_tick_calls_on_tick(self):
        from pharos_engine.entity import Entity

        class CountScript:
            def __init__(self): self.count = 0
            def on_tick(self, entity, dt): self.count += 1

        e = Entity()
        s = CountScript()
        e.attach_script(s)
        e.tick(0.016)
        assert s.count == 1

    def test_multiple_scripts_all_ticked(self):
        from pharos_engine.entity import Entity

        class CountScript:
            def __init__(self): self.count = 0
            def on_tick(self, entity, dt): self.count += 1

        e = Entity()
        s1, s2 = CountScript(), CountScript()
        e.attach_script(s1)
        e.attach_script(s2)
        e.tick(0.016)
        assert s1.count == 1 and s2.count == 1

    def test_tick_with_no_scripts_no_crash(self):
        from pharos_engine.entity import Entity
        e = Entity()
        e.tick(0.016)

    def test_on_create_calls_on_spawn(self):
        from pharos_engine.entity import Entity
        spawned = []

        class SpawnScript:
            def on_spawn(self, e): spawned.append(True)

        e = Entity()
        e.attach_script(SpawnScript())
        e.on_create()
        assert spawned == [True]

    def test_on_destroy_calls_on_despawn(self):
        from pharos_engine.entity import Entity
        despawned = []

        class DespawnScript:
            def on_despawn(self, e): despawned.append(True)

        e = Entity()
        e.attach_script(DespawnScript())
        e.on_destroy()
        assert despawned == [True]

    def test_on_spawn_delegates_to_on_create(self):
        from pharos_engine.entity import Entity
        spawned = []

        class SpawnScript:
            def on_spawn(self, e): spawned.append(True)

        e = Entity()
        e.attach_script(SpawnScript())
        e.on_spawn()
        assert spawned == [True]


class TestEntityComponents:
    def _make_component(self):
        class FakeComp:
            def __init__(self): self.attached = False
            def on_attach(self, e): self.attached = True
            def on_detach(self, e): self.attached = False
            def update(self, dt): pass
        return FakeComp()

    def test_add_component_returns_component(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        result = e.add_component(c)
        assert result is c

    def test_get_component_returns_attached(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        e.add_component(c)
        assert e.get_component(type(c)) is c

    def test_get_missing_component_returns_none(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        assert e.get_component(type(c)) is None

    def test_on_attach_called(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        e.add_component(c)
        assert c.attached is True

    def test_remove_component_calls_on_detach(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        e.add_component(c)
        e.remove_component(type(c))
        assert c.attached is False

    def test_remove_missing_component_no_crash(self):
        from pharos_engine.entity import Entity
        e = Entity()
        c = self._make_component()
        e.remove_component(type(c))

    def test_component_update_called_from_tick(self):
        from pharos_engine.entity import Entity

        class TickComp:
            def __init__(self): self.count = 0
            def on_attach(self, e): pass
            def on_detach(self, e): pass
            def update(self, dt): self.count += 1

        e = Entity()
        c = TickComp()
        e.add_component(c)
        e.tick(0.016)
        assert c.count == 1

    def test_replace_component_detaches_old(self):
        from pharos_engine.entity import Entity

        class MyComp:
            def __init__(self, n): self.n = n; self.attached = False
            def on_attach(self, e): self.attached = True
            def on_detach(self, e): self.attached = False
            def update(self, dt): pass

        e = Entity()
        c1 = MyComp(1)
        c2 = MyComp(2)
        e.add_component(c1)
        e.add_component(c2)
        assert c1.attached is False
        assert e.get_component(MyComp) is c2


class TestScript:
    def test_instantiates(self):
        from pharos_engine.script import Script
        s = Script()
        assert s is not None

    def test_lifecycle_methods_no_crash(self):
        from pharos_engine.script import Script
        s = Script()
        e = object()
        s.on_start(e)
        s.on_update(e, 0.016)
        s.on_event(e, object())
        s.on_destroy(e)
        s.on_collision(e, object())

    def test_subclass_on_update_moves_entity(self):
        from pharos_engine.script import Script
        from pharos_engine.entity import Entity

        class Mover(Script):
            def on_tick(self, entity, dt):
                x, y = entity.position
                entity.position = (x + dt * 100, y)

        e = Entity(position=(0.0, 0.0))
        e.attach_script(Mover())
        e.tick(1.0)
        assert e.position[0] == pytest.approx(100.0)


class TestScriptComponent:
    def test_instantiates(self):
        from pharos_engine.script import ScriptComponent
        class MySC(ScriptComponent): pass
        sc = MySC()
        assert sc is not None

    def test_on_attach_calls_on_start(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import ScriptComponent
        started = []

        class MySC(ScriptComponent):
            def on_start(self, entity): started.append(entity)

        e = Entity()
        sc = MySC()
        e.add_component(sc)
        assert started == [e]

    def test_entity_stored_on_attach(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import ScriptComponent

        class MySC(ScriptComponent): pass

        e = Entity()
        sc = MySC()
        e.add_component(sc)
        assert sc.entity is e

    def test_entity_cleared_on_detach(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import ScriptComponent

        class MySC(ScriptComponent): pass

        e = Entity()
        sc = MySC()
        e.add_component(sc)
        e.remove_component(MySC)
        assert sc.entity is None

    def test_update_calls_on_update(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import ScriptComponent
        updates = []

        class MySC(ScriptComponent):
            def on_update(self, entity, dt): updates.append(dt)

        e = Entity()
        sc = MySC()
        e.add_component(sc)
        sc.update(0.016)
        assert updates == [pytest.approx(0.016)]

    def test_on_detach_calls_on_destroy(self):
        from pharos_engine.entity import Entity
        from pharos_engine.script import ScriptComponent
        destroyed = []

        class MySC(ScriptComponent):
            def on_destroy(self, entity): destroyed.append(True)

        e = Entity()
        sc = MySC()
        e.add_component(sc)
        e.remove_component(MySC)
        assert destroyed == [True]
