"""Q2 Sprint — Physics Component Validation Tests.

Tests for RigidBodyComponent, DeformableLayerComponent, and InputDrivenComponent
from pharos_engine.components.  All tests run headless (CPU only, no wgpu).
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(pos=(0.0, 0.0)):
    """Minimal entity stub with position and get_component support."""
    entity = MagicMock()
    entity.position = list(pos)
    entity._components = {}

    def _get_component(cls):
        return entity._components.get(cls)

    entity.get_component = _get_component
    return entity


def _attach_rb(rb, entity):
    """Attach a RigidBodyComponent to a stub entity and register it."""
    rb.on_attach(entity)
    entity._components[type(rb)] = rb
    return rb


# ---------------------------------------------------------------------------
# 1. RigidBodyComponent — apply_force increases velocity
# ---------------------------------------------------------------------------

def test_rigidbody_apply_force_increases_velocity_x():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0)  # damping=1 = no damping
    rb.apply_force(100.0, 0.0)
    rb.update(1.0)
    assert rb.velocity_x > 0.0


def test_rigidbody_apply_force_no_y_component():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    rb.apply_force(100.0, 0.0)
    rb.update(1.0)
    assert rb.velocity_y == pytest.approx(0.0, abs=1e-9)


def test_rigidbody_apply_force_magnitude_proportional_to_mass():
    """Heavier body accelerates less under same force."""
    from pharos_engine.components import RigidBodyComponent
    rb_light = RigidBodyComponent(mass=1.0, damping=1.0)
    rb_heavy = RigidBodyComponent(mass=10.0, damping=1.0)
    rb_light.apply_force(100.0, 0.0)
    rb_heavy.apply_force(100.0, 0.0)
    rb_light.update(1.0)
    rb_heavy.update(1.0)
    assert rb_light.velocity_x > rb_heavy.velocity_x


# ---------------------------------------------------------------------------
# 2. RigidBodyComponent — damping reduces speed
# ---------------------------------------------------------------------------

def test_rigidbody_damping_reduces_speed():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=0.5)
    rb.apply_force(100.0, 0.0)
    rb.update(1.0)
    speed_after_first = rb.speed

    rb.update(1.0)   # no new force — damping should reduce speed
    assert rb.speed < speed_after_first


def test_rigidbody_zero_damping_stops_immediately():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=0.0)
    rb.apply_force(500.0, 0.0)
    rb.update(1.0)
    # damping=0 means velocity × 0 → fully stopped next update
    rb.update(1.0)
    assert rb.velocity_x == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. RigidBodyComponent — apply_impulse
# ---------------------------------------------------------------------------

def test_rigidbody_apply_impulse_immediate_velocity_change():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=2.0, damping=1.0)
    rb.apply_impulse(100.0, 0.0)   # delta_vx = 100 / 2 = 50
    assert rb.velocity_x == pytest.approx(50.0)


def test_rigidbody_apply_impulse_publishes_event():
    from pharos_engine.components import RigidBodyComponent
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    handle = subscribe("RigidBody.Impulse", lambda evt: received.append(evt))
    try:
        rb = RigidBodyComponent(mass=1.0)
        rb.apply_impulse(10.0, 0.0)
        assert len(received) == 1
        assert getattr(received[0], "magnitude", None) == pytest.approx(10.0)
    finally:
        unsubscribe(handle)


def test_rigidbody_apply_impulse_2d():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    rb.apply_impulse(3.0, 4.0)
    # apply_impulse syncs velocity_x/velocity_y immediately; speed is synced in update()
    expected_speed = math.hypot(rb.velocity_x, rb.velocity_y)  # 5.0
    assert expected_speed == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 4. RigidBodyComponent — zero mass guard
# ---------------------------------------------------------------------------

def test_rigidbody_zero_mass_no_division_error():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=0.0, damping=0.98)
    rb.apply_force(1000.0, 0.0)
    rb.update(1.0)   # must not raise ZeroDivisionError
    # With mass=0 forces are ignored — velocity stays zero
    assert rb.velocity_x == pytest.approx(0.0, abs=1e-9)


def test_rigidbody_zero_mass_impulse_no_crash():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=0.0)
    rb.apply_impulse(999.0, 0.0)   # guarded by `if self.mass > 0`
    assert rb.velocity_x == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5. RigidBodyComponent — max_speed cap
# ---------------------------------------------------------------------------

def test_rigidbody_max_speed_cap():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0, max_speed=10.0)
    rb.apply_force(10000.0, 0.0)
    rb.update(1.0)
    assert rb.speed <= 10.0 + 1e-6


# ---------------------------------------------------------------------------
# 6. RigidBodyComponent — Observable scalar events
# ---------------------------------------------------------------------------

def test_rigidbody_velocity_x_publishes_event():
    from pharos_engine.components import RigidBodyComponent
    from pharos_engine.event_bus import subscribe, unsubscribe

    received = []
    # Subscribe to the specific attribute path; Observable only publishes when
    # there is an active listener on "RigidBodyComponent.velocity_x".
    handle = subscribe("RigidBodyComponent.velocity_x", lambda evt: received.append(evt))
    try:
        rb = RigidBodyComponent(mass=1.0, damping=1.0)
        rb.apply_force(10.0, 0.0)
        rb.update(1.0)
        assert len(received) >= 1
    finally:
        unsubscribe(handle)


def test_rigidbody_speed_updated_after_update():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    rb.apply_force(3.0, 4.0)
    rb.update(1.0)
    # speed should equal hypot(vx, vy)
    expected = math.hypot(rb.velocity_x, rb.velocity_y)
    assert rb.speed == pytest.approx(expected, abs=1e-6)


# ---------------------------------------------------------------------------
# 7. RigidBodyComponent — entity position integration
# ---------------------------------------------------------------------------

def test_rigidbody_updates_entity_position():
    from pharos_engine.components import RigidBodyComponent
    entity = _make_entity(pos=(0.0, 0.0))
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    _attach_rb(rb, entity)
    rb.apply_force(100.0, 0.0)
    rb.update(1.0)
    # position should have changed in X
    assert entity.position[0] > 0.0


def test_rigidbody_dt_zero_no_change():
    from pharos_engine.components import RigidBodyComponent
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    rb.apply_force(100.0, 0.0)
    rb.update(0.0)   # dt=0 → no change
    assert rb.velocity_x == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 8. DeformableLayerComponent — init
# ---------------------------------------------------------------------------

def _make_layer(w: int = 32, h: int = 32, alpha: int = 255):
    """Make a simple Layer2D-like stub with _image_data."""
    layer = MagicMock()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    layer._image_data[:, :, 3] = alpha   # set alpha channel
    return layer


def test_deformable_init_no_crash():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer()
    dc = DeformableLayerComponent(layer)
    assert dc.integrity == pytest.approx(1.0)
    dc.teardown()


def test_deformable_init_integrity_is_one():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer()
    dc = DeformableLayerComponent(layer)
    assert dc._integrity == pytest.approx(1.0)
    dc.teardown()


# ---------------------------------------------------------------------------
# 9. DeformableLayerComponent — apply_impact reduces integrity
# ---------------------------------------------------------------------------

def test_deformable_apply_plastic_impact_reduces_integrity():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=10.0)
    dc.apply_impact((16.0, 16.0), force=500.0, radius=20.0, mode="plastic")
    dc.update(1.0 / 60.0)
    assert dc.integrity < 1.0
    dc.teardown()


def test_deformable_apply_impact_auto_mode_selects_plastic_above_threshold():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=50.0)
    dc.apply_impact((16.0, 16.0), force=200.0, mode="auto")
    pending = dc._pending_impacts
    assert pending[0]["mode"] == "plastic"
    dc.teardown()


def test_deformable_apply_impact_auto_mode_selects_elastic_below_threshold():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=100.0)
    dc.apply_impact((16.0, 16.0), force=30.0, mode="auto")
    pending = dc._pending_impacts
    assert pending[0]["mode"] == "elastic"
    dc.teardown()


# ---------------------------------------------------------------------------
# 10. DeformableLayerComponent — repair restores integrity
# ---------------------------------------------------------------------------

def test_deformable_repair_increases_integrity():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=10.0)
    # Apply a heavy plastic impact
    dc.apply_impact((16.0, 16.0), force=1000.0, radius=30.0, mode="plastic")
    dc.update(1.0 / 60.0)
    integrity_after_hit = dc.integrity

    # Now repair
    dc.repair(rate=50.0)
    dc.update(1.0 / 60.0)
    assert dc.integrity > integrity_after_hit
    dc.teardown()


def test_deformable_repair_does_not_exceed_original():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=10.0)
    dc.apply_impact((16.0, 16.0), force=100.0, radius=20.0, mode="plastic")
    dc.update(1.0 / 60.0)
    dc.repair(rate=999.0)
    dc.update(1.0 / 60.0)
    assert dc.integrity <= 1.0 + 1e-4
    dc.teardown()


# ---------------------------------------------------------------------------
# 11. DeformableLayerComponent — max_impacts_per_frame queuing
# ---------------------------------------------------------------------------

def test_deformable_max_impacts_per_frame_queued():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, max_impacts_per_frame=3)

    # Queue 5 impacts
    for i in range(5):
        dc.apply_impact((16.0, 16.0), force=100.0, radius=10.0, mode="plastic")

    assert len(dc._pending_impacts) == 5
    dc.update(1.0 / 60.0)
    # After one update: 3 processed, 2 remain
    assert len(dc._pending_impacts) == 2
    dc.teardown()


def test_deformable_remaining_impacts_processed_next_frame():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, max_impacts_per_frame=2)

    for _ in range(4):
        dc.apply_impact((16.0, 16.0), force=100.0, radius=10.0, mode="plastic")

    dc.update(0.016)   # processes 2
    assert len(dc._pending_impacts) == 2
    dc.update(0.016)   # processes remaining 2
    assert len(dc._pending_impacts) == 0
    dc.teardown()


# ---------------------------------------------------------------------------
# 12. DeformableLayerComponent — integrity bounds [0, 1]
# ---------------------------------------------------------------------------

def test_deformable_integrity_never_below_zero():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer, elastic_threshold=0.0)
    for _ in range(50):
        dc.apply_impact((16.0, 16.0), force=9999.0, radius=20.0, mode="plastic")
        dc.update(0.016)
    assert dc.integrity >= 0.0
    dc.teardown()


def test_deformable_integrity_never_above_one():
    from pharos_engine.components import DeformableLayerComponent
    layer = _make_layer(32, 32, alpha=255)
    dc = DeformableLayerComponent(layer)
    dc.repair(rate=9999.0)
    dc.update(0.016)
    assert dc.integrity <= 1.0 + 1e-6
    dc.teardown()


# ---------------------------------------------------------------------------
# 13. InputDrivenComponent — axis_to_force mapping
# ---------------------------------------------------------------------------

def _make_input(axes: dict):
    provider = MagicMock()
    provider.get_axes.return_value = axes
    return provider


def test_inputdriven_axis_maps_to_force():
    from pharos_engine.components import InputDrivenComponent, RigidBodyComponent

    entity = _make_entity()
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    _attach_rb(rb, entity)
    entity._components[RigidBodyComponent] = rb

    provider = _make_input({"throttle": 1.0})
    idc = InputDrivenComponent(
        input_provider=provider,
        axis_to_force={"throttle": (0.0, -500.0)},
    )
    idc.on_attach(entity)
    idc.update(1.0)

    # Force (0, -500) × axis 1.0 → force_acc_y = -500
    # After update, velocity_y should be non-zero negative
    rb.update(1.0)
    assert rb.velocity_y < 0.0


def test_inputdriven_zero_axis_applies_no_force():
    from pharos_engine.components import InputDrivenComponent, RigidBodyComponent

    entity = _make_entity()
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    _attach_rb(rb, entity)
    entity._components[RigidBodyComponent] = rb

    provider = _make_input({"throttle": 0.0})
    idc = InputDrivenComponent(
        input_provider=provider,
        axis_to_force={"throttle": (1000.0, 0.0)},
    )
    idc.on_attach(entity)
    idc.update(1.0)
    rb.update(1.0)
    assert rb.velocity_x == pytest.approx(0.0, abs=1e-9)


def test_inputdriven_torque_axis():
    from pharos_engine.components import InputDrivenComponent, RigidBodyComponent

    entity = _make_entity()
    entity.rotation = 0.0
    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    _attach_rb(rb, entity)
    entity._components[RigidBodyComponent] = rb

    provider = _make_input({"steer": 1.0})
    idc = InputDrivenComponent(
        input_provider=provider,
        axis_to_torque={"steer": 10.0},
    )
    idc.on_attach(entity)
    idc.update(1.0)
    rb.update(1.0)
    assert rb.angular_velocity != pytest.approx(0.0)


def test_inputdriven_no_rigidbody_no_crash():
    from pharos_engine.components import InputDrivenComponent

    entity = _make_entity()
    # Entity has no RigidBodyComponent registered
    provider = _make_input({"throttle": 1.0})
    idc = InputDrivenComponent(
        input_provider=provider,
        axis_to_force={"throttle": (100.0, 0.0)},
    )
    idc.on_attach(entity)
    idc.update(1.0)   # must not raise


# ---------------------------------------------------------------------------
# 14. Component composition — RigidBody + Deformable + Input all update
# ---------------------------------------------------------------------------

def test_component_composition_no_conflict():
    from pharos_engine.components import (
        RigidBodyComponent, DeformableLayerComponent, InputDrivenComponent
    )

    entity = _make_entity()
    entity.rotation = 0.0

    layer = _make_layer()
    rb = RigidBodyComponent(mass=1.0, damping=0.98)
    _attach_rb(rb, entity)
    entity._components[RigidBodyComponent] = rb

    dc = DeformableLayerComponent(layer)
    dc.on_attach(entity)

    provider = _make_input({"throttle": 0.5})
    idc = InputDrivenComponent(
        input_provider=provider,
        axis_to_force={"throttle": (100.0, 0.0)},
    )
    idc.on_attach(entity)

    for _ in range(10):
        idc.update(0.016)
        rb.update(0.016)
        dc.update(0.016)

    # All components processed 10 frames — position should have moved
    assert entity.position[0] > 0.0
    dc.teardown()


# ---------------------------------------------------------------------------
# 15. ComponentBase protocol compliance
# ---------------------------------------------------------------------------

def test_rigidbody_satisfies_component_protocol():
    from pharos_engine.components import RigidBodyComponent, Component
    rb = RigidBodyComponent()
    assert isinstance(rb, Component)


def test_deformable_satisfies_component_protocol():
    from pharos_engine.components import DeformableLayerComponent, Component
    layer = _make_layer()
    dc = DeformableLayerComponent(layer)
    assert isinstance(dc, Component)
    dc.teardown()


def test_inputdriven_satisfies_component_protocol():
    from pharos_engine.components import InputDrivenComponent, Component
    provider = _make_input({})
    idc = InputDrivenComponent(input_provider=provider)
    assert isinstance(idc, Component)
