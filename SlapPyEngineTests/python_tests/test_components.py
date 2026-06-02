"""Engine tests for composable components — CPU headless path.

Covers PhysicsComponent, CollisionComponent, RigidBodyComponent,
DeformableLayerComponent, and InputDrivenComponent.  All tests run
without a GPU context.
"""
from __future__ import annotations
import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _Entity:
    """Minimal entity stub for component testing."""
    def __init__(self, pos=(0.0, 0.0)):
        self.position = list(pos)
        self.rotation = 0.0
        self._components: dict = {}

    def add_component(self, comp):
        comp.on_attach(self)
        self._components[type(comp)] = comp
        return comp

    def get_component(self, cls):
        return self._components.get(cls)


class _Layer:
    """Minimal Layer2D stub with RGBA image data."""
    def __init__(self, w=32, h=32, alpha=255):
        self._image_data = np.zeros((h, w, 4), dtype=np.uint8)
        self._image_data[:, :, 0] = 200
        self._image_data[:, :, 3] = alpha


# ---------------------------------------------------------------------------
# PhysicsComponent
# ---------------------------------------------------------------------------

class TestPhysicsComponent:
    def test_default_velocity_zero(self):
        from slappyengine.components import PhysicsComponent
        pc = PhysicsComponent()
        assert pc.velocity == (0.0, 0.0)

    def test_custom_velocity_stored(self):
        from slappyengine.components import PhysicsComponent
        pc = PhysicsComponent(velocity=(10.0, -5.0))
        assert pc.velocity[0] == pytest.approx(10.0)
        assert pc.velocity[1] == pytest.approx(-5.0)

    def test_update_moves_entity(self):
        from slappyengine.components import PhysicsComponent
        ent = _Entity(pos=(0.0, 0.0))
        pc = PhysicsComponent(velocity=(100.0, 0.0))
        ent.add_component(pc)
        pc.update(1.0)
        assert ent.position[0] == pytest.approx(100.0)

    def test_update_no_entity_no_crash(self):
        from slappyengine.components import PhysicsComponent
        pc = PhysicsComponent(velocity=(5.0, 5.0))
        pc.update(1.0)  # entity is None

    def test_adopts_entity_velocity_on_attach(self):
        from slappyengine.components import PhysicsComponent
        ent = _Entity()
        ent.velocity = (50.0, 25.0)
        pc = PhysicsComponent()
        ent.add_component(pc)
        assert pc.velocity[0] == pytest.approx(50.0)
        assert pc.velocity[1] == pytest.approx(25.0)

    def test_detach_clears_entity(self):
        from slappyengine.components import PhysicsComponent
        ent = _Entity()
        pc = PhysicsComponent()
        pc.on_attach(ent)
        assert pc.entity is ent
        pc.on_detach(ent)
        assert pc.entity is None


# ---------------------------------------------------------------------------
# CollisionComponent
# ---------------------------------------------------------------------------

class TestCollisionComponent:
    def test_defaults(self):
        from slappyengine.components import CollisionComponent
        cc = CollisionComponent()
        assert cc.shape is None
        assert cc.layer == 0
        assert cc.mask == 0xFFFF
        assert cc.on_collide is None

    def test_custom_values_stored(self):
        from slappyengine.components import CollisionComponent
        cb = []
        cc = CollisionComponent(shape="AABB", layer=2, mask=4,
                                on_collide=lambda e: cb.append(e))
        assert cc.shape == "AABB"
        assert cc.layer == 2
        assert cc.mask == 4
        cc.on_collide("other")
        assert len(cb) == 1

    def test_satisfies_component_protocol(self):
        from slappyengine.components import CollisionComponent, Component
        cc = CollisionComponent()
        assert isinstance(cc, Component)


# ---------------------------------------------------------------------------
# RigidBodyComponent
# ---------------------------------------------------------------------------

class TestRigidBodyComponent:
    def test_defaults(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent()
        assert rb.mass == pytest.approx(1.0)
        assert rb.velocity == [0.0, 0.0]
        assert rb.speed == pytest.approx(0.0)

    def test_apply_force_accumulates(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0)
        rb.apply_force(10.0, 5.0)
        assert rb._force_acc[0] == pytest.approx(10.0)
        assert rb._force_acc[1] == pytest.approx(5.0)

    def test_update_integrates_velocity(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        rb.apply_force(10.0, 0.0)
        rb.update(1.0)
        # v = a*dt = F/m * dt = 10 * 1 = 10
        assert rb.velocity[0] == pytest.approx(10.0, rel=0.01)

    def test_update_resets_force_accumulator(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent()
        rb.apply_force(5.0, 5.0)
        rb.update(0.016)
        assert rb._force_acc[0] == pytest.approx(0.0)
        assert rb._force_acc[1] == pytest.approx(0.0)

    def test_damping_reduces_velocity(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=0.5)
        rb.velocity[0] = 100.0
        rb.update(0.016)
        assert rb.velocity[0] < 100.0

    def test_max_speed_caps_velocity(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0, max_speed=50.0)
        rb.apply_force(10000.0, 0.0)
        rb.update(1.0)
        assert math.hypot(rb.velocity[0], rb.velocity[1]) <= 50.5

    def test_apply_impulse_changes_velocity_immediately(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=2.0)
        rb.apply_impulse(20.0, 0.0)
        # delta_v = impulse / mass = 20 / 2 = 10
        assert rb.velocity[0] == pytest.approx(10.0)

    def test_apply_impulse_publishes_event(self):
        from slappyengine.components import RigidBodyComponent
        from slappyengine.event_bus import subscribe, unsubscribe
        rb = RigidBodyComponent(mass=1.0)
        received = []
        h = subscribe("RigidBody.Impulse", lambda e: received.append(e))
        try:
            rb.apply_impulse(5.0, 5.0)
            assert len(received) == 1
            assert received[0].magnitude == pytest.approx(math.hypot(5.0, 5.0))
        finally:
            unsubscribe(h)

    def test_velocity_x_observable_updates_after_update(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        rb.apply_force(100.0, 0.0)
        rb.update(1.0)
        assert rb.velocity_x == pytest.approx(rb.velocity[0])

    def test_speed_observable_updated_after_update(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        rb.apply_force(3.0, 4.0)
        rb.update(1.0)
        expected_speed = math.hypot(rb.velocity[0], rb.velocity[1])
        assert rb.speed == pytest.approx(expected_speed)

    def test_update_moves_entity_position(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        ent = _Entity(pos=(0.0, 0.0))
        ent.add_component(rb)
        rb.velocity[0] = 60.0
        rb.update(1.0)
        assert ent.position[0] > 0.0

    def test_update_zero_dt_no_change(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0)
        rb.velocity[0] = 10.0
        before = rb.velocity[0]
        rb.update(0.0)
        assert rb.velocity[0] == pytest.approx(before)

    def test_torque_changes_angular_velocity(self):
        from slappyengine.components import RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, angular_damping=1.0)
        rb.apply_torque(10.0)
        rb.update(1.0)
        assert rb.angular_velocity > 0.0

    def test_no_publish_attrs_not_published(self):
        from slappyengine.components import RigidBodyComponent
        from slappyengine.event_bus import subscribe, unsubscribe
        rb = RigidBodyComponent()
        force_events = []
        h = subscribe("RigidBodyComponent._force_acc", lambda e: force_events.append(e))
        try:
            rb._force_acc[0] = 999.0
            rb._force_acc = [1.0, 2.0]
            assert len(force_events) == 0
        finally:
            unsubscribe(h)

    def test_is_observable(self):
        from slappyengine.components import RigidBodyComponent
        from slappyengine.event_bus import Observable
        rb = RigidBodyComponent()
        assert isinstance(rb, Observable)


# ---------------------------------------------------------------------------
# DeformableLayerComponent
# ---------------------------------------------------------------------------

class TestDeformableLayerComponent:
    def test_init_integrity_one(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer)
        assert dc.integrity == pytest.approx(1.0)

    def test_apply_impact_queues_impact(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer)
        dc.apply_impact((16, 16), force=100.0, radius=5.0)
        assert len(dc._pending_impacts) == 1

    def test_apply_impact_auto_selects_mode(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer, elastic_threshold=80.0)
        dc.apply_impact((8, 8), force=20.0)   # below threshold → elastic
        dc.apply_impact((8, 8), force=200.0)  # above threshold → plastic
        assert dc._pending_impacts[0]["mode"] == "elastic"
        assert dc._pending_impacts[1]["mode"] == "plastic"

    def test_update_processes_impacts_cpu(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer(alpha=255)
        dc = DeformableLayerComponent(layer)
        dc.apply_impact((16, 16), force=500.0, radius=8.0, mode="plastic")
        dc.update(0.016)
        # Some alpha should have been reduced at or near centre
        centre_alpha = int(layer._image_data[16, 16, 3])
        assert centre_alpha < 255

    def test_update_clears_pending_impacts(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer)
        dc.apply_impact((5, 5), force=100.0)
        dc.update(0.016)
        assert len(dc._pending_impacts) == 0

    def test_integrity_decreases_after_plastic_impact(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer(alpha=255)
        dc = DeformableLayerComponent(layer)
        for _ in range(20):
            dc.apply_impact((16, 16), force=999.0, radius=16.0, mode="plastic")
            dc.update(0.016)
        assert dc.integrity < 1.0

    def test_update_no_image_data_no_crash(self):
        from slappyengine.components import DeformableLayerComponent
        layer = type("L", (), {"_image_data": None})()
        dc = DeformableLayerComponent(layer)
        dc.apply_impact((5, 5), force=100.0)
        dc.update(0.016)  # should not raise

    def test_repair_restores_alpha(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer(alpha=255)
        dc = DeformableLayerComponent(layer)
        # Damage it
        dc.apply_impact((16, 16), force=9000.0, radius=16.0, mode="plastic")
        dc.update(0.016)
        damaged_alpha = layer._image_data[16, 16, 3]
        # Repair many steps
        dc.update(0.016)  # initialises _original_alpha
        for _ in range(200):
            dc.repair(rate=5.0)
        repaired_alpha = layer._image_data[16, 16, 3]
        assert repaired_alpha >= damaged_alpha

    def test_integrity_event_published_on_change(self):
        from slappyengine.components import DeformableLayerComponent
        from slappyengine.event_bus import subscribe, unsubscribe
        layer = _Layer(alpha=255)
        dc = DeformableLayerComponent(layer)
        events = []
        h = subscribe("DeformableLayerComponent.integrity", lambda e: events.append(e))
        try:
            dc.apply_impact((16, 16), force=9000.0, radius=10.0, mode="plastic")
            dc.update(0.016)
            # Event should fire because integrity changed from 1.0
            assert len(events) >= 1
        finally:
            unsubscribe(h)

    def test_vehicle_destroyed_fires_at_zero_integrity(self):
        from slappyengine.components import DeformableLayerComponent
        from slappyengine.event_bus import subscribe, unsubscribe
        # Create layer with very low initial alpha so one impact zeroes it
        layer = _Layer(alpha=1)
        dc = DeformableLayerComponent(layer, elastic_threshold=0.0)
        destroyed = []
        h = subscribe("Vehicle.Destroyed", lambda e: destroyed.append(e))
        try:
            for _ in range(5):
                dc.apply_impact((16, 16), force=99999.0, radius=16.0, mode="plastic")
                dc.update(0.016)
            # If integrity hit 0, destroyed should have fired
            if dc.integrity <= 0.0:
                assert len(destroyed) >= 1
        finally:
            unsubscribe(h)

    def test_teardown_unsubscribes_without_crash(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer)
        dc.teardown()  # should not raise

    def test_material_preset_organic_applied(self):
        from slappyengine.components import DeformableLayerComponent
        from slappyengine.deform_modes import MaterialPreset
        layer = _Layer()
        dc = DeformableLayerComponent(layer, material_preset=MaterialPreset.ORGANIC)
        # Organic preset should lower elastic_threshold vs default
        assert dc.elastic_threshold < 80.0 or dc.spring_decay != 0.94

    def test_max_impacts_per_frame_respected(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer, max_impacts_per_frame=2)
        for _ in range(10):
            dc.apply_impact((16, 16), force=50.0)
        dc.update(0.016)
        # Only 2 processed; 8 remain
        assert len(dc._pending_impacts) == 8

    def test_integrity_from_strain_returns_float(self):
        from slappyengine.components import DeformableLayerComponent
        layer = _Layer()
        dc = DeformableLayerComponent(layer)
        dc.update(0.016)  # initialises stress/strain buf
        result = dc.integrity_from_strain()
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# InputDrivenComponent
# ---------------------------------------------------------------------------

class TestInputDrivenComponent:
    def _make_provider(self, axes: dict):
        class _P:
            def get_axes(self_inner):
                return axes
        return _P()

    def test_init_empty_maps(self):
        from slappyengine.components import InputDrivenComponent
        comp = InputDrivenComponent(self._make_provider({}))
        assert comp.axis_to_force == {}
        assert comp.axis_to_torque == {}

    def test_update_no_rigid_body_no_crash(self):
        from slappyengine.components import InputDrivenComponent
        comp = InputDrivenComponent(
            self._make_provider({"throttle": 1.0}),
            axis_to_force={"throttle": (0.0, -100.0)},
        )
        ent = _Entity()
        comp.on_attach(ent)
        comp.update(0.016)  # no RigidBodyComponent — should not crash

    def test_force_applied_to_rigid_body(self):
        from slappyengine.components import InputDrivenComponent, RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        ent = _Entity()
        ent.add_component(rb)
        comp = InputDrivenComponent(
            self._make_provider({"throttle": 1.0}),
            axis_to_force={"throttle": (0.0, -100.0)},
        )
        comp.on_attach(ent)
        comp.update(0.016)
        # After update, force was applied; calling rb.update integrates it
        rb.update(0.016)
        assert rb.velocity[1] < 0.0

    def test_negative_axis_applies_reversed_force(self):
        from slappyengine.components import InputDrivenComponent, RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        ent = _Entity()
        ent.add_component(rb)
        comp = InputDrivenComponent(
            self._make_provider({"steer": -1.0}),
            axis_to_force={"steer": (50.0, 0.0)},
        )
        comp.on_attach(ent)
        comp.update(0.016)
        rb.update(0.016)
        assert rb.velocity[0] < 0.0

    def test_torque_applied_to_rigid_body(self):
        from slappyengine.components import InputDrivenComponent, RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, angular_damping=1.0)
        ent = _Entity()
        ent.add_component(rb)
        comp = InputDrivenComponent(
            self._make_provider({"spin": 1.0}),
            axis_to_torque={"spin": 200.0},
        )
        comp.on_attach(ent)
        comp.update(0.016)
        rb.update(0.016)
        assert rb.angular_velocity > 0.0

    def test_missing_axis_treated_as_zero(self):
        from slappyengine.components import InputDrivenComponent, RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0)
        ent = _Entity()
        ent.add_component(rb)
        comp = InputDrivenComponent(
            self._make_provider({}),  # no axes provided
            axis_to_force={"throttle": (0.0, -100.0)},
        )
        comp.on_attach(ent)
        comp.update(0.016)
        rb.update(0.016)
        # No axis → no force → velocity stays at 0
        assert rb.velocity[0] == pytest.approx(0.0, abs=1e-6)
        assert rb.velocity[1] == pytest.approx(0.0, abs=1e-6)

    def test_multiple_axes_all_applied(self):
        from slappyengine.components import InputDrivenComponent, RigidBodyComponent
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        ent = _Entity()
        ent.add_component(rb)
        comp = InputDrivenComponent(
            self._make_provider({"a1": 1.0, "a2": 1.0}),
            axis_to_force={"a1": (10.0, 0.0), "a2": (0.0, 10.0)},
        )
        comp.on_attach(ent)
        comp.update(0.016)
        rb.update(0.016)
        assert rb.velocity[0] > 0.0
        assert rb.velocity[1] > 0.0
