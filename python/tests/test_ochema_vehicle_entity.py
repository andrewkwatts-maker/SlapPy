"""Headless tests for VehicleEntity methods not covered by test_game_tracks_hazards.py.

Targets: update_sprite, _update_damage_layers, set_nitro, update_nitro_light,
         on_end, get_strength_map_layer, has_cockpit, validate, _recompute,
         apply_impact, is_destroyed, take_damage direction mapping.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock

# --------------------------------------------------------------------------- #
# GPU / wgpu stubs (must appear before any slappyengine import)
# --------------------------------------------------------------------------- #
sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

# --------------------------------------------------------------------------- #
# Ochema Circuit on sys.path
# --------------------------------------------------------------------------- #
_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vehicle(driver_id: int = 0, vehicle_class: str = "racer"):
    from entities.vehicle import VehicleEntity
    return VehicleEntity(driver_id=driver_id, vehicle_class=vehicle_class)


def _make_part(part_type_name: str, grid_x: int = 1, grid_y: int = 1):
    from entities.part import VehiclePart, PartType
    return VehiclePart(PartType[part_type_name], grid_x=grid_x, grid_y=grid_y)


# =============================================================================
# is_destroyed — all armor at zero
# =============================================================================

class TestIsDestroyed:
    def test_not_destroyed_initially(self):
        v = _make_vehicle()
        assert v.is_destroyed is False

    def test_is_destroyed_when_all_armor_zero(self):
        v = _make_vehicle()
        for key in list(v.armor_hp):
            v.armor_hp[key] = 0.0
        assert v.is_destroyed is True

    def test_is_destroyed_partial_armor_remaining(self):
        v = _make_vehicle()
        for key in list(v.armor_hp):
            v.armor_hp[key] = 0.0
        v.armor_hp["FRONT"] = 10.0
        assert v.is_destroyed is False


# =============================================================================
# take_damage — direction-to-face mapping (rotation = 0)
# =============================================================================

class TestTakeDamageDirectionMapping:
    def _v(self):
        v = _make_vehicle()
        v.rotation = 0.0
        return v

    def test_right_face_hit_by_rightward_direction(self):
        v = self._v()
        initial = v.armor_hp["RIGHT"]
        v.take_damage(5.0, direction=(1.0, 0.0))
        assert v.armor_hp["RIGHT"] < initial

    def test_left_face_hit_by_leftward_direction(self):
        v = self._v()
        initial = v.armor_hp["LEFT"]
        v.take_damage(5.0, direction=(-1.0, 0.0))
        assert v.armor_hp["LEFT"] < initial

    def test_front_face_hit_by_forward_direction(self):
        v = self._v()
        initial = v.armor_hp["FRONT"]
        v.take_damage(5.0, direction=(0.0, -1.0))
        assert v.armor_hp["FRONT"] < initial

    def test_rear_face_hit_by_rearward_direction(self):
        v = self._v()
        initial = v.armor_hp["REAR"]
        v.take_damage(5.0, direction=(0.0, 1.0))
        assert v.armor_hp["REAR"] < initial

    def test_damage_clamped_to_zero(self):
        v = self._v()
        v.take_damage(99999.0, direction=(0.0, -1.0))
        assert v.armor_hp["FRONT"] == 0.0

    def test_only_one_face_reduced_per_hit(self):
        v = self._v()
        initial_totals = dict(v.armor_hp)
        v.take_damage(10.0, direction=(1.0, 0.0))
        unchanged_count = sum(
            1 for k in ("FRONT", "REAR", "LEFT")
            if v.armor_hp[k] == initial_totals[k]
        )
        assert unchanged_count == 3


# =============================================================================
# apply_impact — delegates to deform without raising
# =============================================================================

class TestApplyImpact:
    def test_apply_impact_no_crash(self):
        v = _make_vehicle()
        v.apply_impact((32.0, 16.0), force=50.0, radius=12.0, mode="plastic")

    def test_apply_impact_elastic_no_crash(self):
        v = _make_vehicle()
        v.apply_impact((10.0, 10.0), force=20.0, mode="elastic")


# =============================================================================
# _recompute — centre of mass and yaw_bias
# =============================================================================

class TestRecompute:
    def test_empty_parts_zero_mass(self):
        v = _make_vehicle()
        v.parts.clear()
        v._recompute()
        assert v.total_mass == 0.0

    def test_empty_parts_zero_yaw(self):
        v = _make_vehicle()
        v.parts.clear()
        v._recompute()
        assert v.yaw_bias == 0.0

    def test_single_part_com(self):
        v = _make_vehicle()
        v.parts.clear()
        part = _make_part("ENGINE", grid_x=2, grid_y=3)
        v.add_part(part)
        cx, cy = v.center_of_mass
        assert abs(cx - 2.0) < 0.01
        assert abs(cy - 3.0) < 0.01

    def test_two_parts_com_midpoint(self):
        v = _make_vehicle()
        v.parts.clear()
        p1 = _make_part("ENGINE", grid_x=0, grid_y=0)
        p2 = _make_part("ARMOR", grid_x=4, grid_y=0)
        v.add_part(p1)
        v.add_part(p2)
        cx, cy = v.center_of_mass
        total_mass = p1.mass + p2.mass
        expected_cx = (0 * p1.mass + 4 * p2.mass) / total_mass
        assert abs(cx - expected_cx) < 0.1

    def test_symmetric_parts_low_yaw_bias(self):
        v = _make_vehicle()
        v.parts.clear()
        # grid_size is 8 from config; centre = 4
        from slappyengine.vehicle_parts import PartSlot
        p1 = _make_part("ARMOR", grid_x=4, grid_y=0)
        p2 = _make_part("ARMOR", grid_x=4, grid_y=7)
        v.add_part(p1)
        v.add_part(p2)
        # Both at x=4 (centre), so yaw_bias should be near zero
        assert abs(v.yaw_bias) < 0.1


# =============================================================================
# update_sprite — tilt frame selection
# =============================================================================

class TestUpdateSprite:
    def test_no_tilt_no_crash(self):
        v = _make_vehicle()
        v.pitch = 0.0
        v.roll = 0.0
        v.update_sprite()  # should not raise

    def test_small_tilt_shows_first_layer(self):
        v = _make_vehicle()
        # When angle_map is not None and tilt < 0.05, layer 0 gets opacity=1
        v.pitch = 0.0
        v.roll = 0.0
        v.update_sprite()
        if v._angle_map is not None and len(v.layers) >= 8:
            assert v.layers[0].opacity == 1.0

    def test_large_tilt_no_crash(self):
        v = _make_vehicle()
        v.pitch = 0.5
        v.roll = 0.3
        v.update_sprite()  # angle_map.apply should run without raising

    def test_no_angle_map_no_crash(self):
        v = _make_vehicle()
        v._angle_map = None
        v.update_sprite()  # should return early without error


# =============================================================================
# _update_damage_layers — internals / frame alpha control
# =============================================================================

class TestUpdateDamageLayers:
    def test_high_integrity_internals_hidden(self):
        v = _make_vehicle()
        v._update_damage_layers(0.8)
        lyr = v.layers[v._internals_layer_index]
        assert int(lyr._image_data[:, :, 3].max()) == 0

    def test_low_integrity_internals_visible(self):
        v = _make_vehicle()
        v._update_damage_layers(0.2)
        lyr = v.layers[v._internals_layer_index]
        assert int(lyr._image_data[:, :, 3].max()) > 0

    def test_critical_integrity_frame_visible(self):
        v = _make_vehicle()
        v._update_damage_layers(0.05)
        lyr = v.layers[v._frame_layer_index]
        assert int(lyr._image_data[:, :, 3].max()) > 0

    def test_repair_hides_internals(self):
        v = _make_vehicle()
        v._update_damage_layers(0.1)  # damage
        v._update_damage_layers(0.9)  # repaired
        lyr = v.layers[v._internals_layer_index]
        assert int(lyr._image_data[:, :, 3].max()) == 0

    def test_repair_hides_frame(self):
        v = _make_vehicle()
        v._update_damage_layers(0.05)  # damage
        v._update_damage_layers(0.9)   # repaired
        lyr = v.layers[v._frame_layer_index]
        assert int(lyr._image_data[:, :, 3].max()) == 0

    def test_internals_revealed_flag_set(self):
        v = _make_vehicle()
        v._update_damage_layers(0.3)  # integrity 0.45
        assert v._internals_revealed is True

    def test_frame_revealed_flag_set(self):
        v = _make_vehicle()
        v._update_damage_layers(0.1)  # integrity < 0.15
        assert v._frame_revealed is True

    def test_internals_revealed_resets_on_repair(self):
        v = _make_vehicle()
        v._update_damage_layers(0.3)
        v._update_damage_layers(0.9)
        assert v._internals_revealed is False


# =============================================================================
# set_nitro — PointLight creation and event publication
# =============================================================================

class TestSetNitro:
    def test_nitro_creates_point_light(self):
        from slappyengine.lighting import PointLight
        v = _make_vehicle()
        v.set_nitro(True, None)
        assert v._nitro_light is not None
        assert isinstance(v._nitro_light, PointLight)

    def test_nitro_sets_active_flag(self):
        v = _make_vehicle()
        v.set_nitro(True, None)
        assert v._nitro_active is True

    def test_nitro_same_state_is_noop(self):
        v = _make_vehicle()
        v.set_nitro(True, None)
        first_light = v._nitro_light
        v.set_nitro(True, None)  # no-op
        assert v._nitro_light is first_light  # same object

    def test_nitro_deactivate(self):
        v = _make_vehicle()
        v.set_nitro(True, None)
        v.set_nitro(False, None)
        assert v._nitro_active is False

    def test_nitro_publishes_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("Vehicle.NitroActive", lambda e: received.append(e))
        v.set_nitro(True, None)
        unsubscribe(h)
        assert len(received) >= 1

    def test_nitro_event_has_active_payload(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("Vehicle.NitroActive", lambda e: received.append(e))
        v.set_nitro(True, None)
        unsubscribe(h)
        assert received[0].payload.get("active") is True

    def test_nitro_observable_attr_fires(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("VehicleEntity.nitro_active", lambda e: received.append(e))
        v.set_nitro(True, None)
        unsubscribe(h)
        assert len(received) >= 1

    def test_nitro_calls_lighting_add_light(self):
        v = _make_vehicle()
        lighting = MagicMock()
        v.set_nitro(True, lighting)
        lighting.add_light.assert_called_once_with(v._nitro_light)

    def test_nitro_deactivate_calls_remove_light(self):
        v = _make_vehicle()
        lighting = MagicMock()
        v.set_nitro(True, lighting)
        v.set_nitro(False, lighting)
        lighting.remove_light.assert_called_once_with(v._nitro_light)


# =============================================================================
# update_nitro_light — position and intensity update
# =============================================================================

class TestUpdateNitroLight:
    def test_no_light_no_crash(self):
        v = _make_vehicle()
        v._nitro_light = None
        v.update_nitro_light(0.0)  # should return early

    def test_inactive_nitro_no_update(self):
        from slappyengine.lighting import PointLight
        v = _make_vehicle()
        v._nitro_light = PointLight((0.0, 0.0), z=0.0)
        v._nitro_active = False
        v.update_nitro_light(0.0)
        # Position should remain (0, 0) — no update applied
        assert v._nitro_light.position == (0.0, 0.0)

    def test_active_nitro_updates_intensity(self):
        from slappyengine.lighting import PointLight
        v = _make_vehicle()
        v.set_nitro(True, None)
        v.position = (100.0, 100.0)
        v.rotation = 0.0
        v.update_nitro_light(1.0)
        # intensity = 3.0 + sin(20.0) * 0.5 — just check it's in plausible range
        assert 2.0 <= v._nitro_light.intensity <= 4.0

    def test_active_nitro_places_light_behind_car(self):
        from slappyengine.lighting import PointLight
        v = _make_vehicle()
        v.set_nitro(True, None)
        v.position = (200.0, 300.0)
        v.rotation = 0.0  # heading = east (cos=1, sin=0)
        v.update_nitro_light(0.0)
        lx, ly = v._nitro_light.position
        # Behind car: px - fwd[0]*18 = 200 - 1*18 = 182
        assert abs(lx - 182.0) < 1.0
        assert abs(ly - 300.0) < 1.0


# =============================================================================
# get_strength_map_layer — debug layer
# =============================================================================

class TestGetStrengthMapLayer:
    def test_returns_layer_or_none(self):
        from slappyengine.layer import Layer
        v = _make_vehicle()
        result = v.get_strength_map_layer()
        assert result is None or isinstance(result, Layer)

    def test_returns_none_when_no_strength_map(self):
        v = _make_vehicle()
        v._strength_map = None
        result = v.get_strength_map_layer()
        assert result is None

    def test_layer_has_correct_shape(self):
        from slappyengine.layer import Layer
        import numpy as np
        v = _make_vehicle()
        if v._strength_map is None:
            pytest.skip("No strength map on this vehicle")
        result = v.get_strength_map_layer()
        assert result is not None
        h, w = v._strength_map.shape
        assert result._image_data.shape == (h, w, 4)

    def test_layer_alpha_is_200(self):
        v = _make_vehicle()
        if v._strength_map is None:
            pytest.skip("No strength map on this vehicle")
        result = v.get_strength_map_layer()
        assert result is not None
        assert result._image_data[:, :, 3].min() == 200


# =============================================================================
# has_cockpit — queries parts list
# =============================================================================

class TestHasCockpit:
    def test_no_parts_no_cockpit(self):
        v = _make_vehicle()
        v.parts.clear()
        assert v.has_cockpit is False

    def test_cockpit_part_detected(self):
        v = _make_vehicle()
        v.parts.clear()
        part = _make_part("COCKPIT", grid_x=3, grid_y=3)
        v.parts.append(part)
        assert v.has_cockpit is True

    def test_dead_cockpit_not_counted(self):
        v = _make_vehicle()
        v.parts.clear()
        part = _make_part("COCKPIT", grid_x=3, grid_y=3)
        part.hp = 0.0  # dead
        v.parts.append(part)
        assert v.has_cockpit is False

    def test_engine_part_does_not_count_as_cockpit(self):
        v = _make_vehicle()
        v.parts.clear()
        part = _make_part("ENGINE", grid_x=3, grid_y=3)
        v.parts.append(part)
        assert v.has_cockpit is False


# =============================================================================
# validate — requires engine + ≥2 wheels + cockpit
# =============================================================================

class TestValidate:
    def test_no_parts_fails(self):
        v = _make_vehicle()
        v.parts.clear()
        assert v.validate() is False

    def test_engine_only_fails(self):
        v = _make_vehicle()
        v.parts.clear()
        v.parts.append(_make_part("ENGINE"))
        assert v.validate() is False

    def test_engine_and_two_wheels_no_cockpit_fails(self):
        v = _make_vehicle()
        v.parts.clear()
        v.parts.append(_make_part("ENGINE"))
        v.parts.append(_make_part("WHEEL", grid_x=0))
        v.parts.append(_make_part("WHEEL", grid_x=7))
        assert v.validate() is False

    def test_cockpit_engine_one_wheel_fails(self):
        v = _make_vehicle()
        v.parts.clear()
        v.parts.append(_make_part("ENGINE"))
        v.parts.append(_make_part("COCKPIT"))
        v.parts.append(_make_part("WHEEL"))
        assert v.validate() is False

    def test_all_required_parts_passes(self):
        v = _make_vehicle()
        v.parts.clear()
        v.parts.append(_make_part("ENGINE"))
        v.parts.append(_make_part("COCKPIT"))
        v.parts.append(_make_part("WHEEL", grid_x=0))
        v.parts.append(_make_part("WHEEL", grid_x=7))
        assert v.validate() is True

    def test_dead_engine_fails(self):
        v = _make_vehicle()
        v.parts.clear()
        engine = _make_part("ENGINE")
        engine.hp = 0.0
        v.parts.append(engine)
        v.parts.append(_make_part("COCKPIT"))
        v.parts.append(_make_part("WHEEL", grid_x=0))
        v.parts.append(_make_part("WHEEL", grid_x=7))
        assert v.validate() is False

    def test_dead_wheel_not_counted(self):
        v = _make_vehicle()
        v.parts.clear()
        v.parts.append(_make_part("ENGINE"))
        v.parts.append(_make_part("COCKPIT"))
        w1 = _make_part("WHEEL", grid_x=0)
        w1.hp = 0.0  # dead — not counted
        w2 = _make_part("WHEEL", grid_x=7)
        v.parts.append(w1)
        v.parts.append(w2)
        # Only 1 alive wheel → fails
        assert v.validate() is False


# =============================================================================
# on_end — subscription cleanup
# =============================================================================

class TestOnEnd:
    def test_on_end_clears_paint_handle(self):
        v = _make_vehicle()
        v.on_end()
        assert v._paint_handle is None

    def test_on_end_clears_damage_layer_handle(self):
        v = _make_vehicle()
        v.on_end()
        assert v._damage_layer_handle is None

    def test_on_end_idempotent(self):
        v = _make_vehicle()
        v.on_end()
        v.on_end()  # second call should not raise


# =============================================================================
# update_tire_renderers — requires _tire_renderers setup
# =============================================================================

class TestUpdateTireRenderers:
    def test_no_tire_renderers_no_crash(self):
        v = _make_vehicle()
        # _tire_renderers not set up → should return early silently
        v.update_tire_renderers(0.016, steer_angle=0.0)

    def test_with_tire_renderers_no_crash(self):
        v = _make_vehicle()
        try:
            v._setup_tire_renderers()
            v.velocity = [200.0, 0.0]
            v.update_tire_renderers(0.016, steer_angle=0.1)
        except (ImportError, AttributeError):
            pytest.skip("CylinderSpriteRenderer not available headless")


# =============================================================================
# Observable tracking (additional attrs not in test_game_tracks_hazards.py)
# =============================================================================

class TestVehicleObservableExtra:
    def test_gear_is_tracked(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("VehicleEntity.gear", lambda e: received.append(e))
        v.gear = 3
        unsubscribe(h)
        assert len(received) >= 1

    def test_drift_factor_is_tracked(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("VehicleEntity.drift_factor", lambda e: received.append(e))
        v.drift_factor = 0.7
        unsubscribe(h)
        assert len(received) >= 1

    def test_steer_is_tracked(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("VehicleEntity.steer", lambda e: received.append(e))
        v.steer = 0.5
        unsubscribe(h)
        assert len(received) >= 1

    def test_brake_is_tracked(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        received = []
        h = subscribe("VehicleEntity.brake", lambda e: received.append(e))
        v.brake = 1.0
        unsubscribe(h)
        assert len(received) >= 1

    def test_nitro_active_observable_deactivate_fires(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        v = _make_vehicle()
        v.set_nitro(True, None)  # activate first
        received = []
        h = subscribe("VehicleEntity.nitro_active", lambda e: received.append(e))
        v.set_nitro(False, None)  # deactivate
        unsubscribe(h)
        assert len(received) >= 1


# =============================================================================
# _on_paint_changed — only applies if publisher is self
# =============================================================================

class TestOnPaintChanged:
    def test_paint_changes_if_publisher_is_self(self):
        v = _make_vehicle()
        original = v.paint_color

        class _FakeEvt:
            publisher = v
            payload = {"color": (255, 0, 0)}

        v._on_paint_changed(_FakeEvt())
        assert v.paint_color == (255, 0, 0)

    def test_paint_ignored_if_publisher_is_other(self):
        v = _make_vehicle()
        original = v.paint_color

        class _FakeEvt:
            publisher = object()  # different publisher
            payload = {"color": (255, 0, 0)}

        v._on_paint_changed(_FakeEvt())
        assert v.paint_color == original
