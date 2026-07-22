"""Engine tests for StrataWorld + StrataLayer — headless."""
from __future__ import annotations
import pytest


def _make_world(inactive_dim=0.35):
    from pharos_engine.strata import StrataWorld, StrataLayer
    layers = [
        StrataLayer("Physical",  0, (1.0, 1.0, 1.0, 1.0), parallax=1.0),
        StrataLayer("Cyber",     1, (0.4, 0.6, 1.0, 0.9), parallax=1.1),
        StrataLayer("Ruined",    2, (1.0, 0.35, 0.2, 0.9), parallax=0.9),
    ]
    return StrataWorld(layers, inactive_dim=inactive_dim)


class _Entity:
    def __init__(self, strata_layer=0):
        self.strata_layer = strata_layer


class TestStrataLayer:
    def test_init_stores_fields(self):
        from pharos_engine.strata import StrataLayer
        layer = StrataLayer("Test", 0, (1.0, 0.5, 0.0, 1.0), parallax=1.2)
        assert layer.name == "Test"
        assert layer.index == 0
        assert layer.tint == (1.0, 0.5, 0.0, 1.0)
        assert layer.parallax == pytest.approx(1.2)


class TestStrataWorldInit:
    def test_active_index_zero_initially(self):
        world = _make_world()
        assert world.active_index == 0

    def test_three_layers_stored(self):
        world = _make_world()
        assert len(world.layers) == 3

    def test_active_layer_returns_first(self):
        world = _make_world()
        assert world.active_layer.name == "Physical"


class TestSetActive:
    def test_set_active_changes_layer(self):
        world = _make_world()
        world.set_active(1)
        assert world.active_index == 1
        assert world.active_layer.name == "Cyber"

    def test_set_active_wraps_around(self):
        world = _make_world()
        world.set_active(3)  # 3 % 3 = 0
        assert world.active_index == 0


class TestGetLayer:
    def test_get_layer_valid(self):
        world = _make_world()
        layer = world.get_layer(1)
        assert layer is not None
        assert layer.name == "Cyber"

    def test_get_layer_out_of_bounds_none(self):
        world = _make_world()
        assert world.get_layer(99) is None
        assert world.get_layer(-1) is None


class TestEntityVisibilityAlpha:
    def test_active_layer_entity_full_alpha(self):
        world = _make_world()
        entity = _Entity(strata_layer=0)  # active layer
        assert world.entity_visibility_alpha(entity) == pytest.approx(1.0)

    def test_inactive_layer_entity_dimmed(self):
        world = _make_world(inactive_dim=0.35)
        entity = _Entity(strata_layer=1)  # inactive layer
        assert world.entity_visibility_alpha(entity) == pytest.approx(0.35)

    def test_default_strata_layer_when_missing(self):
        world = _make_world()
        class _E: pass
        e = _E()  # no strata_layer attr → defaults to 0
        assert world.entity_visibility_alpha(e) == pytest.approx(1.0)


class TestEntityTint:
    def test_tint_matches_layer(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        tint = world.entity_tint(entity)
        assert tint == world.layers[1].tint

    def test_tint_out_of_bounds_white(self):
        world = _make_world()
        entity = _Entity(strata_layer=99)
        assert world.entity_tint(entity) == (1.0, 1.0, 1.0, 1.0)


class TestPhaseTransitions:
    def test_begin_phase_marks_transition(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        world.begin_phase(entity)
        assert id(entity) in world._phase_transitions

    def test_begin_phase_alpha_midpoint(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        world.begin_phase(entity)
        alpha = world.entity_visibility_alpha(entity)
        assert alpha == pytest.approx(0.5)

    def test_end_phase_removes_transition(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        world.begin_phase(entity)
        world.end_phase(entity)
        assert id(entity) not in world._phase_transitions

    def test_end_phase_non_transitioning_no_crash(self):
        world = _make_world()
        entity = _Entity()
        world.end_phase(entity)  # should not raise

    def test_tick_advances_phase(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        world.begin_phase(entity)
        world.tick(0.1)
        alpha = world._phase_transitions.get(id(entity), None)
        if alpha is not None:
            assert alpha > 0.5

    def test_tick_completes_transition(self):
        world = _make_world()
        entity = _Entity(strata_layer=1)
        world.begin_phase(entity)
        world.tick(2.0)  # long enough to complete
        assert id(entity) not in world._phase_transitions

    def test_multiple_entities_tick_no_crash(self):
        world = _make_world()
        entities = [_Entity(strata_layer=1) for _ in range(5)]
        for e in entities:
            world.begin_phase(e)
        world.tick(0.05)
        world.tick(0.05)
        world.tick(1.0)  # complete all
        assert len(world._phase_transitions) == 0
