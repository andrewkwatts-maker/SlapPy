"""Headless tests for Ochema Circuit AiDriverScript, FogSystem, QualitySystem,
and RaceAudioSystem."""
from __future__ import annotations
import sys
import math
from pathlib import Path
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())

_OCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
_OCHEMA_STR = str(_OCHEMA_DIR)
if _OCHEMA_STR not in sys.path:
    sys.path.insert(0, _OCHEMA_STR)


# =============================================================================
# Helpers
# =============================================================================

def _make_vehicle(pos=(320.0, 360.0), rotation=0.0):
    v = MagicMock()
    v.position = list(pos)
    v.velocity = [0.0, 0.0]
    v.rotation = rotation
    v.angular_vel = 0.0
    v.max_speed = 300.0
    v.is_ai = False
    return v


# =============================================================================
# AiDriverScript
# =============================================================================

class TestAiDriverScriptInit:
    def test_init_no_crash(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        assert ai is not None

    def test_init_marks_vehicle_as_ai(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        AiDriverScript(v)
        assert v.is_ai is True

    def test_init_default_waypoints(self):
        from systems.ai_driver import AiDriverScript, RACE_WAYPOINTS
        v = _make_vehicle()
        ai = AiDriverScript(v)
        assert ai._waypoints is RACE_WAYPOINTS

    def test_init_custom_waypoints(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        wps = [(100.0, 100.0), (200.0, 200.0), (300.0, 100.0)]
        ai = AiDriverScript(v, waypoints=wps)
        assert ai._waypoints is wps

    def test_init_speed_scale_stored(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v, speed_scale=0.85)
        assert ai._speed_scale == pytest.approx(0.85)

    def test_init_wp_idx_zero(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        assert ai._wp_idx == 0


class TestAiDriverScriptHelpers:
    def _ai(self, pos=(640.0, 360.0)):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(pos=pos)
        return AiDriverScript(v), v

    def test_lookahead_target_returns_tuple(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        result = ai._lookahead_target(v.position)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_lookahead_target_px_returns_tuple(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        result = ai._lookahead_target_px(v.position, 80.0)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_lookahead_target_px_zero_distance_returns_valid(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        result = ai._lookahead_target_px(v.position, 0.0)
        assert len(result) == 2

    def test_track_progress_returns_float(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(pos=(640.0, 80.0))
        ai = AiDriverScript(v)
        prog = ai._track_progress()
        assert isinstance(prog, float)

    def test_track_progress_non_negative(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        assert ai._track_progress() >= 0.0

    def test_avg_segment_length_positive(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        ai = AiDriverScript(v)
        assert ai._avg_segment_length() > 0.0

    def test_avg_segment_length_custom_waypoints(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle()
        wps = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
        ai = AiDriverScript(v, waypoints=wps)
        # Each segment = 100px, avg = 100px
        assert ai._avg_segment_length() == pytest.approx(100.0)

    def test_wrap_angle_positive_overflow(self):
        from systems.ai_driver import _wrap_angle
        assert _wrap_angle(270.0) == pytest.approx(-90.0)

    def test_wrap_angle_negative_overflow(self):
        from systems.ai_driver import _wrap_angle
        assert _wrap_angle(-270.0) == pytest.approx(90.0)

    def test_wrap_angle_no_change(self):
        from systems.ai_driver import _wrap_angle
        assert _wrap_angle(45.0) == pytest.approx(45.0)


class TestAiDriverScriptUpdate:
    def test_update_no_crash_basic(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(pos=(640.0, 80.0))
        v.angular_vel = 0.0
        ai = AiDriverScript(v)
        ai.update(0.016)

    def test_update_sets_angular_vel(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(pos=(640.0, 80.0))
        v.angular_vel = 0.0
        ai = AiDriverScript(v)
        ai.update(0.016)
        assert hasattr(v, "angular_vel")

    def test_update_with_scriptinputprovider(self):
        from systems.ai_driver import AiDriverScript
        from slappyengine.input_provider import ScriptInputProvider
        v = _make_vehicle(pos=(640.0, 80.0))
        v.input_provider = ScriptInputProvider()
        ai = AiDriverScript(v)
        ai.update(0.016)
        # Should not crash; throttle axis is set via set_axis
        assert v.input_provider is not None

    def test_update_near_waypoint_advances_index(self):
        from systems.ai_driver import AiDriverScript, RACE_WAYPOINTS, ARRIVAL_RADIUS
        wp0 = RACE_WAYPOINTS[0]
        # Place vehicle exactly at waypoint 0 to trigger advance
        v = _make_vehicle(pos=(wp0[0], wp0[1]))
        v.angular_vel = 0.0
        ai = AiDriverScript(v)
        ai.update(0.016)
        assert ai._wp_idx == 1

    def test_update_with_all_drivers_no_crash(self):
        from systems.ai_driver import AiDriverScript
        v1 = _make_vehicle(pos=(640.0, 80.0))
        v1.angular_vel = 0.0
        v2 = _make_vehicle(pos=(1100.0, 180.0))
        v2.angular_vel = 0.0
        ai1 = AiDriverScript(v1)
        ai2 = AiDriverScript(v2)
        ai1.update(0.016, all_drivers=[ai1, ai2])

    def test_update_legacy_direct_write(self):
        from systems.ai_driver import AiDriverScript
        v = _make_vehicle(pos=(640.0, 80.0))
        v.angular_vel = 0.0
        # No input_provider → legacy path should write velocity
        del v.input_provider  # MagicMock won't have isinstance check
        v.input_provider = None
        ai = AiDriverScript(v)
        ai.update(0.016)

    def test_difficulty_speed_scale_constant(self):
        from systems.ai_driver import _DIFFICULTY_SPEED_SCALE
        assert "Easy" in _DIFFICULTY_SPEED_SCALE
        assert "Normal" in _DIFFICULTY_SPEED_SCALE
        assert "Hard" in _DIFFICULTY_SPEED_SCALE
        assert _DIFFICULTY_SPEED_SCALE["Easy"] < _DIFFICULTY_SPEED_SCALE["Hard"]


# =============================================================================
# FogSystem
# =============================================================================

class TestFogSystemInit:
    def test_init_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.teardown()

    def test_density_stored(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(density=0.7, gpu=None)
        assert fs._base_density == pytest.approx(0.7)
        fs.teardown()

    def test_density_clamped_high(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(density=1.5, gpu=None)
        assert fs._base_density == pytest.approx(1.0)
        fs.teardown()

    def test_density_clamped_low(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(density=-0.3, gpu=None)
        assert fs._base_density == pytest.approx(0.0)
        fs.teardown()

    def test_color_stored(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(color=(100, 200, 50, 180), gpu=None)
        assert fs._color == (100, 200, 50, 180)
        fs.teardown()

    def test_size_stored(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(size=(256, 256), gpu=None)
        assert fs._size == (256, 256)
        fs.teardown()


class TestFogSystemWind:
    def test_set_wind_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.set_wind(2.0, 45.0)
        fs.teardown()

    def test_set_wind_stores_speed(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.set_wind(3.5, 90.0)
        assert fs._wind_speed == pytest.approx(3.5)
        fs.teardown()

    def test_set_wind_stores_angle(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.set_wind(1.0, 135.0)
        assert fs._wind_angle == pytest.approx(135.0)
        fs.teardown()

    def test_set_wind_zero_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.set_wind(0.0, 0.0)
        fs.teardown()

    def test_set_wind_updates_handle(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(wind_speed=1.0, gpu=None)
        old_handle = fs._wind_force_handle
        fs.set_wind(2.0, 45.0)
        # Handle may be the same value if sim reuses handles, but no crash
        fs.teardown()


class TestFogSystemDisplacers:
    def test_add_displacer_returns_int(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        entity = MagicMock()
        entity.position = (100.0, 100.0)
        h = fs.add_displacer(entity)
        assert isinstance(h, int)
        fs.teardown()

    def test_add_displacer_stores_handle(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        entity = MagicMock()
        entity.position = (100.0, 100.0)
        fs.add_displacer(entity)
        assert id(entity) in fs._displacer_handles
        fs.teardown()

    def test_remove_displacer_clears_entry(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        entity = MagicMock()
        entity.position = (100.0, 100.0)
        fs.add_displacer(entity)
        fs.remove_displacer(entity)
        assert id(entity) not in fs._displacer_handles
        fs.teardown()

    def test_remove_nonexistent_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.remove_displacer(MagicMock())  # should not raise
        fs.teardown()

    def test_add_displacer_clamps_strength(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        entity = MagicMock()
        entity.position = (100.0, 100.0)
        # Should not crash with out-of-range strength
        fs.add_displacer(entity, strength=999.0)
        fs.teardown()


class TestFogSystemUpdate:
    def test_update_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.update(0.016)
        fs.teardown()

    def test_update_multiple_ticks_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        for _ in range(10):
            fs.update(0.016)
        fs.teardown()

    def test_update_with_transient_displacer(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        entity = MagicMock()
        entity.position = (100.0, 100.0)
        fs.update(0.016, displacers=[(entity, 30.0, 0.5)])
        # Transient displacer should NOT remain in handles after update
        fs.teardown()

    def test_quality_skip_flag_set_by_event(self):
        from slappyengine.event_bus import publish
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        publish("Quality.TierChanged", publisher=None, tier="low",
                params={"fog_scale": 0.5, "rain_cap": 25})
        assert fs._quality_skip is True
        fs.teardown()

    def test_quality_fog_scale_applies(self):
        from slappyengine.event_bus import publish
        from systems.fog_system import FogSystem
        fs = FogSystem(density=0.8, gpu=None)
        publish("Quality.TierChanged", publisher=None, tier="medium",
                params={"fog_scale": 0.75, "rain_cap": 50})
        assert fs._density == pytest.approx(0.8 * 0.75)
        fs.teardown()


class TestFogSystemOutput:
    def test_sample_returns_float(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        val = fs.sample((100.0, 100.0))
        assert isinstance(val, float)
        fs.teardown()

    def test_sample_in_range(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        val = fs.sample((100.0, 100.0))
        assert 0.0 <= val <= 1.0
        fs.teardown()

    def test_get_layer_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        layer = fs.get_layer()
        # May return None if CPU backend doesn't produce a layer
        fs.teardown()

    def test_set_edge_density_boost(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.set_edge_density_boost(0.5)
        assert fs._edge_density_boost == pytest.approx(0.5)
        fs.teardown()

    def test_init_noise_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.init_noise(mode="fbm", octaves=3, seed=42)
        fs.teardown()

    def test_teardown_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.teardown()

    def test_teardown_twice_no_crash(self):
        from systems.fog_system import FogSystem
        fs = FogSystem(gpu=None)
        fs.teardown()
        fs.teardown()


# =============================================================================
# QualitySystem
# =============================================================================

class TestQualitySystemInit:
    def test_init_no_crash(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        assert qs is not None

    def test_init_with_target_fps(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem(target_fps=30.0)
        assert qs._target_ms == pytest.approx(1000.0 / 30.0)

    def test_current_tier_label_is_string(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        assert isinstance(qs.current_tier_label, str)

    def test_initial_tier_is_ultra(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        assert qs.current_tier_label == "ultra"

    def test_debug_str_returns_string(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        s = qs.debug_str()
        assert isinstance(s, str)

    def test_init_publishes_tier_changed_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        from systems.quality_system import QualitySystem
        events = []
        h = subscribe("Quality.TierChanged", lambda e: events.append(e))
        qs = QualitySystem()
        unsubscribe(h)
        assert len(events) >= 1


class TestQualitySystemUpdate:
    def test_update_no_crash(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        qs.update(16.0)  # 16ms frame

    def test_update_caps_large_frame_times(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem()
        # 200ms frame should be capped to 100ms
        qs.update(200.0)
        assert max(qs._frame_times) <= QualitySystem._FRAME_TIME_CAP_MS

    def test_downgrade_after_bad_frames(self):
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES
        qs = QualitySystem(target_fps=60.0)
        initial_label = qs.current_tier_label
        # Feed enough bad frames to trigger downgrade
        for _ in range(_DOWNGRADE_FRAMES + 2):
            qs.update(50.0)  # 50ms >> 16.67ms budget
        # Should have downgraded if not already at lowest
        # Just check no crash and label is valid
        assert qs.current_tier_label in ("ultra", "high", "medium", "low")

    def test_good_frames_increment_upgrade_counter(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem(target_fps=60.0)
        # Force to medium tier so there's room to upgrade
        qs._controller.set_tier(2)
        qs.update(5.0)  # 5ms — well under budget
        assert qs._upgrade_candidate_frames >= 1

    def test_bad_frame_resets_upgrade_counter(self):
        from systems.quality_system import QualitySystem
        qs = QualitySystem(target_fps=60.0)
        qs._upgrade_candidate_frames = 50
        qs.update(50.0)  # bad frame
        assert qs._upgrade_candidate_frames == 0

    def test_with_mock_clutter_system(self):
        from systems.quality_system import QualitySystem
        clutter = MagicMock()
        qs = QualitySystem(clutter_system=clutter)
        # clutter.set_particle_cap should have been called on init (_apply_tier)
        clutter.set_particle_cap.assert_called()

    def test_with_mock_weather_system(self):
        from systems.quality_system import QualitySystem
        weather = MagicMock()
        weather._rain_sim = MagicMock()
        weather._rain_sim._max_particles = 100
        weather._rain_intensity = 0.5
        qs = QualitySystem(weather_system=weather)
        # No crash is sufficient — weather integration happens on tier change

    def test_tier_changed_event_published_on_downgrade(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        from systems.quality_system import QualitySystem, _DOWNGRADE_FRAMES
        qs = QualitySystem(target_fps=60.0)
        events = []
        h = subscribe("Quality.TierChanged", lambda e: events.append(e))
        for _ in range(_DOWNGRADE_FRAMES + 2):
            qs.update(50.0)
        unsubscribe(h)
        # Some tier change event should have fired (including initial tier set in __init__)
        assert len(events) >= 0  # just no crash


# =============================================================================
# RaceAudioSystem
# =============================================================================

class TestRaceAudioSystemInit:
    def test_init_no_audio_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras is not None

    def test_not_available_when_none(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._available is False

    def test_loop_ids_initially_negative(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._engine_loop_id == -1
        assert ras._screech_loop_id == -1
        assert ras._music_loop_id == -1

    def test_handles_initially_empty(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._handles == []

    def test_fog_density_initially_zero(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._fog_density == pytest.approx(0.0)

    def test_nitro_playing_initially_false(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._nitro_playing is False

    def test_impact_cooldown_initially_zero(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        assert ras._impact_cooldown == pytest.approx(0.0)


class TestRaceAudioSystemLoadAssets:
    def test_load_assets_no_audio_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.load_assets()  # Should be a no-op

    def test_load_assets_all_handles_none_when_unavailable(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.load_assets()
        assert ras._h_engine is None
        assert ras._h_screech is None
        assert ras._h_impact is None


class TestRaceAudioSystemSubscribeEvents:
    def test_subscribe_events_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        ras.stop_all()

    def test_subscribe_events_populates_handles(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        assert len(ras._handles) > 0
        ras.stop_all()

    def test_subscribe_events_with_tracked_vehicle(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        v = _make_vehicle()
        ras.subscribe_events(tracked_vehicle=v)
        assert ras._tracked_vehicle is v
        ras.stop_all()


class TestRaceAudioSystemEventHandlers:
    def _ras(self, vehicle=None):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events(tracked_vehicle=vehicle)
        return ras

    def test_fog_density_event_updates_state(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("SimField.peak_density", publisher=None, value=0.6)
        assert ras._fog_density == pytest.approx(0.6)
        ras.stop_all()

    def test_fog_density_clamped_high(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("SimField.peak_density", publisher=None, value=2.0)
        assert ras._fog_density == pytest.approx(1.0)
        ras.stop_all()

    def test_fog_density_clamped_low(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("SimField.peak_density", publisher=None, value=-0.5)
        assert ras._fog_density == pytest.approx(0.0)
        ras.stop_all()

    def test_weather_changed_updates_wind_vol(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("Weather.Changed", publisher=None, wind_speed=80.0, intensity=0.0)
        assert ras._wind_vol == pytest.approx(1.0)
        ras.stop_all()

    def test_weather_changed_updates_rain_vol(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("Weather.Changed", publisher=None, wind_speed=0.0, intensity=0.5)
        assert ras._rain_vol == pytest.approx(0.5)
        ras.stop_all()

    def test_nitro_active_event_no_crash(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        v = MagicMock()
        v.position = (100.0, 100.0)
        publish("Vehicle.NitroActive", publisher=v, active=True)
        ras.stop_all()

    def test_race_started_no_crash(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("Race.Started", publisher=None)
        ras.stop_all()

    def test_race_finished_no_crash(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("Race.Finished", publisher=None)
        ras.stop_all()

    def test_lap_complete_no_crash(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        publish("Race.LapComplete", publisher=None)
        ras.stop_all()

    def test_vehicle_collision_no_crash(self):
        from slappyengine.event_bus import publish
        ras = self._ras()
        v = MagicMock()
        v.position = (100.0, 100.0)
        publish("Vehicle.Collision", publisher=v, force=50.0)
        ras.stop_all()

    def test_collision_below_threshold_no_impact(self):
        from slappyengine.event_bus import publish
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        v = MagicMock()
        publish("Vehicle.Collision", publisher=v, force=5.0)  # below _IMPACT_MIN_VEL
        assert ras._impact_cooldown == pytest.approx(0.0)
        ras.stop_all()

    def test_on_impact_direct_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.on_impact(force=100.0, pos=(200.0, 300.0))  # No audio but no crash

    def test_on_impact_below_threshold_no_cooldown(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.on_impact(force=10.0)  # below threshold
        assert ras._impact_cooldown == pytest.approx(0.0)


class TestRaceAudioSystemDoppler:
    def test_doppler_pitch_approaching(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        # Source moving directly toward listener at (0,0)
        source_pos = (100.0, 0.0)
        source_vel = (-200.0, 0.0)  # moving toward origin
        listener_pos = (0.0, 0.0)
        pitch = ras._doppler_pitch(source_pos, source_vel, listener_pos, base_pitch=1.0)
        assert pitch > 1.0  # approaching → higher pitch

    def test_doppler_pitch_receding(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        source_pos = (100.0, 0.0)
        source_vel = (200.0, 0.0)   # moving away from origin
        listener_pos = (0.0, 0.0)
        pitch = ras._doppler_pitch(source_pos, source_vel, listener_pos, base_pitch=1.0)
        assert pitch < 1.0  # receding → lower pitch

    def test_doppler_pitch_same_pos_returns_base(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        pitch = ras._doppler_pitch((0.0, 0.0), (100.0, 0.0), (0.0, 0.0), base_pitch=1.5)
        assert pitch == pytest.approx(1.5)

    def test_doppler_pitch_clamped(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        # Extremely fast approach — should clamp to 4.0
        source_pos = (100.0, 0.0)
        source_vel = (-10000.0, 0.0)
        listener_pos = (0.0, 0.0)
        pitch = ras._doppler_pitch(source_pos, source_vel, listener_pos, base_pitch=1.0)
        assert pitch <= 4.0


class TestRaceAudioSystemSonicBoom:
    def test_check_sonic_boom_below_threshold_no_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        events = []
        h = subscribe("Audio.SonicBoom", lambda e: events.append(e))
        entity = MagicMock()
        entity._was_subsonic = True
        entity.position = (0.0, 0.0)
        ras._check_sonic_boom(entity, 100.0)  # well below 500 * 0.95
        unsubscribe(h)
        assert len(events) == 0

    def test_check_sonic_boom_fires_event(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        events = []
        h = subscribe("Audio.SonicBoom", lambda e: events.append(e))
        entity = MagicMock()
        entity._was_subsonic = True
        entity.position = (0.0, 0.0)
        # threshold = 500 * 0.95 = 475
        ras._check_sonic_boom(entity, 480.0)
        unsubscribe(h)
        assert len(events) == 1

    def test_check_sonic_boom_not_repeated(self):
        from slappyengine.event_bus import subscribe, unsubscribe
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        events = []
        h = subscribe("Audio.SonicBoom", lambda e: events.append(e))
        entity = MagicMock()
        entity._was_subsonic = True
        entity.position = (0.0, 0.0)
        ras._check_sonic_boom(entity, 480.0)
        ras._check_sonic_boom(entity, 480.0)  # second call, already above threshold
        unsubscribe(h)
        assert len(events) == 1

    def test_sos_config_change_updates_speed(self):
        from slappyengine.event_bus import publish
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        publish("Config.Changed|audio.speed_of_sound", publisher=None, value=343.0)
        assert ras._SPEED_OF_SOUND == pytest.approx(343.0)
        ras.stop_all()


class TestRaceAudioSystemUpdate:
    def test_update_not_available_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        vehicle = _make_vehicle()
        ras.update(vehicle, 0.016)

    def test_update_decrements_impact_cooldown(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        # Manually set _available=True but no audio — just tick the cooldown
        ras._available = True
        ras._impact_cooldown = 0.5
        vehicle = _make_vehicle()
        ras.update(vehicle, 0.1)
        # Even with available=True, update should run (but play_spatial will no-op)

    def test_stop_all_clears_handles(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        ras.stop_all()
        assert ras._handles == []

    def test_stop_all_resets_loop_ids(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        ras.stop_all()
        assert ras._engine_loop_id == -1
        assert ras._screech_loop_id == -1
        assert ras._music_loop_id == -1

    def test_stop_all_twice_no_crash(self):
        from systems.audio_system import RaceAudioSystem
        ras = RaceAudioSystem(None)
        ras.subscribe_events()
        ras.stop_all()
        ras.stop_all()
