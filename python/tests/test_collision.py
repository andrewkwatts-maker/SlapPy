"""Engine tests for collision.py — headless, no GPU."""
from __future__ import annotations
import math
import pytest


class _FakeEntity:
    def __init__(self, x=0.0, y=0.0, shape=None, z=None):
        self.position = (x, y)
        self.collision_shape = shape
        if z is not None:
            self.z = z
        self._scripts = []


class TestCollisionShapes:
    def test_aabb_shape_stores_fields(self):
        from slappyengine.collision import AABBShape
        s = AABBShape(width=32, height=16, offset_x=4, offset_y=2)
        assert s.width == 32
        assert s.height == 16
        assert s.offset_x == 4
        assert s.offset_y == 2

    def test_aabb_shape_default_offsets(self):
        from slappyengine.collision import AABBShape
        s = AABBShape(width=10, height=10)
        assert s.offset_x == pytest.approx(0.0)
        assert s.offset_y == pytest.approx(0.0)

    def test_circle_shape_stores_fields(self):
        from slappyengine.collision import CircleShape
        s = CircleShape(radius=20, offset_x=2, offset_y=3)
        assert s.radius == 20
        assert s.offset_x == 2
        assert s.offset_y == 3

    def test_circle_shape_default_offsets(self):
        from slappyengine.collision import CircleShape
        s = CircleShape(radius=15)
        assert s.offset_x == pytest.approx(0.0)
        assert s.offset_y == pytest.approx(0.0)


class TestCheckAABB:
    def test_no_overlap_returns_false(self):
        from slappyengine.collision import AABBShape, check_aabb
        a = _FakeEntity(0, 0)
        b = _FakeEntity(100, 0)
        sa, sb = AABBShape(10, 10), AABBShape(10, 10)
        hit, ov = check_aabb(a, sa, b, sb)
        assert hit is False
        assert ov == (0.0, 0.0)

    def test_overlapping_returns_true(self):
        from slappyengine.collision import AABBShape, check_aabb
        a = _FakeEntity(0, 0)
        b = _FakeEntity(5, 0)
        sa, sb = AABBShape(10, 10), AABBShape(10, 10)
        hit, ov = check_aabb(a, sa, b, sb)
        assert hit is True

    def test_overlap_vector_x_direction(self):
        from slappyengine.collision import AABBShape, check_aabb
        a = _FakeEntity(0, 0)
        b = _FakeEntity(8, 0)
        sa, sb = AABBShape(10, 10), AABBShape(10, 10)
        hit, (ox, oy) = check_aabb(a, sa, b, sb)
        assert hit is True
        assert ox > 0  # pushed rightward
        assert oy == pytest.approx(0.0)

    def test_touching_edges_no_overlap(self):
        from slappyengine.collision import AABBShape, check_aabb
        a = _FakeEntity(0, 0)
        b = _FakeEntity(10, 0)  # exactly touching
        sa, sb = AABBShape(10, 10), AABBShape(10, 10)
        hit, _ = check_aabb(a, sa, b, sb)
        assert hit is False

    def test_offsets_applied(self):
        from slappyengine.collision import AABBShape, check_aabb
        # Without offsets they don't touch; with offsets they do
        a = _FakeEntity(0, 0)
        b = _FakeEntity(12, 0)
        sa = AABBShape(10, 10, offset_x=3)  # a extends from x=3 to x=13
        sb = AABBShape(10, 10)              # b is at x=12 to x=22
        hit, _ = check_aabb(a, sa, b, sb)
        assert hit is True


class TestCheckCircle:
    def test_distant_circles_no_collision(self):
        from slappyengine.collision import CircleShape, check_circle
        a = _FakeEntity(0, 0)
        b = _FakeEntity(50, 0)
        sa, sb = CircleShape(radius=10), CircleShape(radius=10)
        hit, _ = check_circle(a, sa, b, sb)
        assert hit is False

    def test_overlapping_circles_collision(self):
        from slappyengine.collision import CircleShape, check_circle
        a = _FakeEntity(0, 0)
        b = _FakeEntity(15, 0)
        sa, sb = CircleShape(radius=10), CircleShape(radius=10)
        hit, (ox, oy) = check_circle(a, sa, b, sb)
        assert hit is True
        assert ox > 0  # overlap pushes right

    def test_overlap_magnitude(self):
        from slappyengine.collision import CircleShape, check_circle
        a = _FakeEntity(0, 0)
        b = _FakeEntity(16, 0)   # 4px overlap (r1+r2=20, dist=16)
        sa, sb = CircleShape(radius=10), CircleShape(radius=10)
        hit, (ox, oy) = check_circle(a, sa, b, sb)
        assert hit is True
        assert abs(ox) == pytest.approx(4.0, abs=0.01)

    def test_coincident_circles(self):
        from slappyengine.collision import CircleShape, check_circle
        a = _FakeEntity(0, 0)
        b = _FakeEntity(0, 0)
        sa, sb = CircleShape(radius=10), CircleShape(radius=10)
        hit, _ = check_circle(a, sa, b, sb)
        assert hit is True


class TestCheckAABBCircle:
    def test_circle_far_from_box_no_collision(self):
        from slappyengine.collision import AABBShape, CircleShape, check_aabb_circle
        box_ent = _FakeEntity(0, 0)
        circ_ent = _FakeEntity(100, 0)
        box, circ = AABBShape(20, 20), CircleShape(radius=10)
        hit, _ = check_aabb_circle(box_ent, box, circ_ent, circ)
        assert hit is False

    def test_circle_overlapping_box(self):
        from slappyengine.collision import AABBShape, CircleShape, check_aabb_circle
        box_ent = _FakeEntity(0, 0)
        circ_ent = _FakeEntity(18, 10)  # center inside box (box is 0-20, 0-20)
        box, circ = AABBShape(20, 20), CircleShape(radius=10)
        hit, _ = check_aabb_circle(box_ent, box, circ_ent, circ)
        assert hit is True

    def test_circle_center_inside_box_always_hits(self):
        from slappyengine.collision import AABBShape, CircleShape, check_aabb_circle
        box_ent = _FakeEntity(0, 0)
        circ_ent = _FakeEntity(10, 10)  # dead center of 20×20 box
        box, circ = AABBShape(20, 20), CircleShape(radius=1)
        hit, _ = check_aabb_circle(box_ent, box, circ_ent, circ)
        assert hit is True


class TestCollisionWorld:
    def test_register_entity(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        e = _FakeEntity(0, 0, shape=AABBShape(10, 10))
        world.register(e)
        assert e in world._entities

    def test_register_idempotent(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        e = _FakeEntity(0, 0, shape=AABBShape(10, 10))
        world.register(e)
        world.register(e)
        assert world._entities.count(e) == 1

    def test_unregister_entity(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        e = _FakeEntity(0, 0, shape=AABBShape(10, 10))
        world.register(e)
        world.unregister(e)
        assert e not in world._entities

    def test_unregister_nonexistent_no_error(self):
        from slappyengine.collision import CollisionWorld
        world = CollisionWorld()
        e = _FakeEntity(0, 0)
        world.unregister(e)  # should not raise

    def test_tick_no_entities_returns_empty(self):
        from slappyengine.collision import CollisionWorld
        world = CollisionWorld()
        hits = world.tick()
        assert hits == []

    def test_tick_detects_overlap(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        a = _FakeEntity(0, 0, shape=AABBShape(20, 20))
        b = _FakeEntity(10, 0, shape=AABBShape(20, 20))
        world.register(a)
        world.register(b)
        hits = world.tick()
        assert len(hits) == 1
        assert (a, b) in hits

    def test_tick_no_overlap_no_hits(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        a = _FakeEntity(0, 0, shape=AABBShape(10, 10))
        b = _FakeEntity(100, 0, shape=AABBShape(10, 10))
        world.register(a)
        world.register(b)
        hits = world.tick()
        assert hits == []

    def test_tick_fires_on_collision_callback(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        calls = []

        class _Script:
            def on_collision(self, entity, other, overlap):
                calls.append((entity, other))

        a = _FakeEntity(0, 0, shape=AABBShape(20, 20))
        b = _FakeEntity(10, 0, shape=AABBShape(20, 20))
        a._scripts = [_Script()]
        world.register(a)
        world.register(b)
        world.tick()
        assert len(calls) >= 1

    def test_entity_without_collision_shape_skipped(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        world = CollisionWorld()
        a = _FakeEntity(0, 0, shape=AABBShape(20, 20))
        b = _FakeEntity(10, 0, shape=None)  # no shape
        world.register(a)
        world.register(b)
        hits = world.tick()
        assert hits == []

    def test_z_height_filters_non_overlapping(self):
        from slappyengine.collision import CollisionWorld, AABBShape
        from slappyengine.z_height import ZAABBShape
        world = CollisionWorld()
        # Entities at very different Z ranges should not collide
        a = _FakeEntity(0, 0, shape=AABBShape(20, 20))
        b = _FakeEntity(5, 0, shape=AABBShape(20, 20))
        a.z_height = 0.0
        b.z_height = 0.0
        a.z_collision_shape = ZAABBShape(width=20, height=20, z_min=0, z_max=10)
        b.z_collision_shape = ZAABBShape(width=20, height=20, z_min=500, z_max=510)
        world.register(a)
        world.register(b)
        hits = world.tick()
        # No collision due to Z separation
        assert len(hits) == 0

    def test_mixed_shape_types_detected(self):
        from slappyengine.collision import CollisionWorld, AABBShape, CircleShape
        world = CollisionWorld()
        box_ent = _FakeEntity(0, 0, shape=AABBShape(20, 20))
        circ_ent = _FakeEntity(10, 10, shape=CircleShape(radius=5))  # inside box
        world.register(box_ent)
        world.register(circ_ent)
        hits = world.tick()
        assert len(hits) == 1
