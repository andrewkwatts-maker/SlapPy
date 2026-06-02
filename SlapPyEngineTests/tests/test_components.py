"""Tests for RigidBodyComponent, DeformableLayerComponent, InputDrivenComponent."""
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# RigidBodyComponent
# ---------------------------------------------------------------------------

class FakeEntity:
    def __init__(self, pos=(0.0, 0.0)):
        self.position = list(pos)
        self.rotation = 0.0
        self._components = {}

    def get_component(self, t):
        return self._components.get(t)

    def add_component(self, comp):
        self._components[type(comp)] = comp
        comp.on_attach(self)
        return comp


def test_rigid_body_force():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=1.0, damping=1.0)  # damping=1 → no damping
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_force(100.0, 0.0)
    rb.update(1.0)  # dt = 1 s

    assert rb.velocity[0] == pytest.approx(100.0, abs=0.01)
    assert rb.velocity[1] == pytest.approx(0.0,   abs=0.01)


def test_rigid_body_integrates_position():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    entity = FakeEntity(pos=[0.0, 0.0])
    rb.on_attach(entity)

    rb.apply_force(0.0, 50.0)
    rb.update(1.0)

    # After 1s: v=50, x=0+50*1=50
    assert entity.position[1] == pytest.approx(50.0, abs=0.01)


def test_rigid_body_mass_scaling():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=2.0, damping=1.0)
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_force(100.0, 0.0)
    rb.update(1.0)

    # a = F/m = 50, v = 50
    assert rb.velocity[0] == pytest.approx(50.0, abs=0.01)


def test_rigid_body_max_speed():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=1.0, damping=1.0, max_speed=10.0)
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_force(10000.0, 0.0)
    rb.update(1.0)

    import math
    speed = math.sqrt(rb.velocity[0]**2 + rb.velocity[1]**2)
    assert speed <= 10.01, "Speed should be clamped to max_speed"


def test_rigid_body_damping():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=1.0, damping=0.5)
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_force(10.0, 0.0)
    rb.update(1.0)
    v1 = rb.velocity[0]

    # Second tick with no force: velocity should damp to v1 * 0.5
    rb.update(1.0)
    assert rb.velocity[0] == pytest.approx(v1 * 0.5, abs=0.01)


def test_rigid_body_impulse():
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=2.0, damping=1.0)
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_impulse(20.0, 0.0)
    # impulse → velocity change = 20/2 = 10
    assert rb.velocity[0] == pytest.approx(10.0, abs=0.01)


def test_rigid_body_reset_accumulators():
    """Force accumulator should be reset each tick (no carry-over)."""
    from slappyengine.components import RigidBodyComponent

    rb = RigidBodyComponent(mass=1.0, damping=1.0)
    entity = FakeEntity()
    rb.on_attach(entity)

    rb.apply_force(100.0, 0.0)
    rb.update(1.0)
    v_after_first = rb.velocity[0]

    # No new force — velocity should only change due to damping (=1 here)
    rb.update(1.0)
    assert rb.velocity[0] == pytest.approx(v_after_first, abs=0.01)


# ---------------------------------------------------------------------------
# DeformableLayerComponent
# ---------------------------------------------------------------------------

class FakeLayer:
    def __init__(self, w=64, h=64):
        self._image_data = np.ones((h, w, 4), dtype=np.uint8) * 255
        self._data_array = None


def test_deformable_impact():
    from slappyengine.components import DeformableLayerComponent

    layer = FakeLayer()
    comp = DeformableLayerComponent(layer, elastic_threshold=50)
    comp.apply_impact((32, 32), force=100.0, radius=10.0, mode="plastic")
    comp.update(0.016)

    # integrity should drop below 1.0 (some alpha was reduced)
    assert comp.integrity < 1.0


def test_deformable_plastic_reduces_alpha():
    from slappyengine.components import DeformableLayerComponent

    layer = FakeLayer(w=32, h=32)
    comp = DeformableLayerComponent(layer, elastic_threshold=50)
    comp.apply_impact((16, 16), force=200.0, radius=5.0, mode="plastic")
    comp.update(0.016)

    # Alpha at centre should be less than 255
    centre_alpha = int(layer._image_data[16, 16, 3])
    assert centre_alpha < 255, f"Centre alpha was {centre_alpha}, expected < 255"


def test_deformable_integrity_property():
    from slappyengine.components import DeformableLayerComponent

    layer = FakeLayer()
    comp = DeformableLayerComponent(layer)
    assert comp.integrity == 1.0  # initial state before first update

    comp.apply_impact((32, 32), force=255.0, radius=30.0, mode="plastic")
    comp.update(0.016)
    assert 0.0 <= comp.integrity <= 1.0


def test_deformable_auto_mode():
    """mode='auto' selects elastic below threshold, plastic above."""
    from slappyengine.components import DeformableLayerComponent

    layer = FakeLayer()
    comp = DeformableLayerComponent(layer, elastic_threshold=100)
    # force=50 < threshold → elastic
    comp.apply_impact((16, 16), force=50.0, radius=5.0, mode="auto")
    assert comp._pending_impacts[0]["mode"] == "elastic"

    # force=200 > threshold → plastic
    comp.apply_impact((16, 16), force=200.0, radius=5.0, mode="auto")
    assert comp._pending_impacts[1]["mode"] == "plastic"


# ---------------------------------------------------------------------------
# InputDrivenComponent
# ---------------------------------------------------------------------------

class FakeInputProvider:
    def __init__(self, axes: dict):
        self._axes = axes

    def get_axes(self):
        return self._axes


def test_input_driven_applies_force():
    from slappyengine.components import RigidBodyComponent, InputDrivenComponent

    entity = FakeEntity()
    rb = entity.add_component(RigidBodyComponent(mass=1.0, damping=1.0))
    provider = FakeInputProvider({"throttle": 1.0})
    idc = InputDrivenComponent(
        provider,
        axis_to_force={"throttle": (0.0, -100.0)},
    )
    idc.on_attach(entity)

    idc.update(1.0)
    # Force (0, -100) with value 1.0 → fy_acc = -100
    # Now call rb.update to integrate
    rb.update(1.0)
    assert rb.velocity[1] == pytest.approx(-100.0, abs=0.01)


def test_input_driven_torque():
    from slappyengine.components import RigidBodyComponent, InputDrivenComponent

    entity = FakeEntity()
    rb = entity.add_component(RigidBodyComponent(mass=1.0, damping=1.0,
                                                  angular_damping=1.0))
    provider = FakeInputProvider({"steer": 0.5})
    idc = InputDrivenComponent(
        provider,
        axis_to_torque={"steer": 200.0},
    )
    idc.on_attach(entity)

    idc.update(1.0)
    rb.update(1.0)
    # torque = 0.5 * 200 = 100, alpha = 100/1 = 100, av = 100 * 1 = 100
    assert rb.angular_velocity == pytest.approx(100.0, abs=0.01)


def test_input_driven_no_rb():
    """InputDrivenComponent is silent when no RigidBodyComponent is attached."""
    from slappyengine.components import InputDrivenComponent

    entity = FakeEntity()
    provider = FakeInputProvider({"throttle": 1.0})
    idc = InputDrivenComponent(provider, axis_to_force={"throttle": (0.0, -1.0)})
    idc.on_attach(entity)
    idc.update(0.016)  # Should not raise
