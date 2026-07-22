"""Engine tests for ParticleEmitter (CPU-simulated, no GPU required) — headless."""
from __future__ import annotations
import numpy as np
import pytest


class TestParticleEmitterInit:
    def test_texture_data_shape(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32, texture_size=64)
        td = pe.texture_data
        assert td.shape == (64, 64, 4)

    def test_texture_data_dtype(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=16, texture_size=32)
        assert pe.texture_data.dtype == np.uint8

    def test_texture_data_initially_black(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=10, texture_size=16)
        assert np.all(pe.texture_data == 0)

    def test_default_texture_size(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=8)
        td = pe.texture_data
        assert td.shape[0] == td.shape[1]  # square

    def test_zero_live_particles_initially(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=100)
        # All life values should be 0 (dead)
        assert np.all(pe._life <= 0.0)

    def test_max_particles_sets_array_size(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=50)
        assert len(pe._life) == 50
        assert len(pe._pos_x) == 50
        assert len(pe._pos_y) == 50


class TestParticleEmitterEmit:
    def test_emit_creates_live_particles(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=5, position=(0.0, 0.0), color=(255, 128, 0), lifetime=1.0)
        alive = np.sum(pe._life > 0.0)
        assert alive == 5

    def test_emit_respects_position(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=1, position=(100.0, 200.0), color=(255, 255, 255), lifetime=1.0, speed_range=(0.0, 0.0))
        alive_idx = np.where(pe._life > 0.0)[0]
        assert len(alive_idx) == 1
        assert pe._pos_x[alive_idx[0]] == pytest.approx(100.0, abs=1.0)
        assert pe._pos_y[alive_idx[0]] == pytest.approx(200.0, abs=1.0)

    def test_emit_sets_lifetime(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=3, position=(0.0, 0.0), color=(255, 0, 0), lifetime=2.0, speed_range=(0.0, 0.0))
        alive_idx = np.where(pe._life > 0.0)[0]
        for idx in alive_idx:
            assert pe._life[idx] == pytest.approx(2.0, abs=0.01)

    def test_emit_stores_color(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=1, position=(0.0, 0.0), color=(200, 100, 50), lifetime=1.0, speed_range=(0.0, 0.0))
        idx = np.where(pe._life > 0.0)[0][0]
        assert pe._r[idx] == pytest.approx(200, abs=1)
        assert pe._g[idx] == pytest.approx(100, abs=1)
        assert pe._b[idx] == pytest.approx(50, abs=1)

    def test_emit_zero_count_no_crash(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=0, position=(0.0, 0.0), color=(0, 0, 0), lifetime=1.0)
        assert np.all(pe._life <= 0.0)

    def test_emit_does_not_exceed_max_particles(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=5)
        pe.emit(count=100, position=(0.0, 0.0), color=(255, 255, 255), lifetime=1.0)
        alive = np.sum(pe._life > 0.0)
        assert alive <= 5

    def test_emit_fills_dead_slots_only(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=10)
        pe.emit(count=5, position=(0.0, 0.0), color=(255, 0, 0), lifetime=1.0, speed_range=(0.0, 0.0))
        # Second emit should fill remaining 5 slots
        pe.emit(count=5, position=(10.0, 10.0), color=(0, 0, 255), lifetime=1.0, speed_range=(0.0, 0.0))
        alive = np.sum(pe._life > 0.0)
        assert alive == 10

    def test_emit_with_speed_range_sets_velocity(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=10, position=(0.0, 0.0), color=(255, 255, 255), lifetime=1.0, speed_range=(50.0, 100.0))
        alive_idx = np.where(pe._life > 0.0)[0]
        speeds = np.hypot(pe._vel_x[alive_idx], pe._vel_y[alive_idx])
        for speed in speeds:
            assert 50.0 <= speed <= 100.0 + 1.0  # small tolerance for float ops


class TestParticleEmitterTick:
    def test_tick_reduces_life(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=5, position=(0.0, 0.0), color=(255, 255, 255), lifetime=2.0, speed_range=(0.0, 0.0))
        pe.tick(dt=0.5)
        alive_idx = np.where(pe._life > 0.0)[0]
        for idx in alive_idx:
            assert pe._life[idx] == pytest.approx(1.5, abs=0.01)

    def test_tick_kills_expired_particles(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=5, position=(0.0, 0.0), color=(255, 255, 255), lifetime=0.5, speed_range=(0.0, 0.0))
        pe.tick(dt=1.0)  # longer than lifetime
        alive = np.sum(pe._life > 0.0)
        assert alive == 0

    def test_tick_advances_position(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=1, position=(0.0, 0.0), color=(255, 255, 255), lifetime=5.0, speed_range=(0.0, 0.0))
        alive_idx = np.where(pe._life > 0.0)[0]
        pe._vel_x[alive_idx[0]] = 100.0
        pe._vel_y[alive_idx[0]] = 0.0
        pe.tick(dt=0.1)
        alive_idx2 = np.where(pe._life > 0.0)[0]
        assert pe._pos_x[alive_idx2[0]] == pytest.approx(10.0, abs=0.5)

    def test_tick_with_gravity_increases_y_velocity(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.emit(count=1, position=(0.0, 0.0), color=(255, 255, 255), lifetime=5.0, speed_range=(0.0, 0.0))
        idx = np.where(pe._life > 0.0)[0][0]
        initial_vy = pe._vel_y[idx]
        pe.tick(dt=0.1, gravity=200.0)
        assert pe._vel_y[idx] != initial_vy  # gravity changed velocity

    def test_tick_empty_emitter_no_crash(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32)
        pe.tick(dt=1.0)  # no particles — should not raise

    def test_tick_rebuilds_texture(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32, texture_size=64)
        pe.emit(count=10, position=(32.0, 32.0), color=(255, 128, 64), lifetime=5.0, speed_range=(0.0, 0.0))
        pe.tick(dt=0.016)
        # After tick with particles near center, some pixels should be non-zero
        td = pe.texture_data
        assert np.any(td[:, :, 3] > 0), "expected at least one non-transparent pixel after tick"


class TestParticleEmitterTextureData:
    def test_texture_data_is_uint8(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=16, texture_size=32)
        pe.emit(count=1, position=(16.0, 16.0), color=(255, 255, 255), lifetime=1.0, speed_range=(0.0, 0.0))
        pe.tick(dt=0.0)
        assert pe.texture_data.dtype == np.uint8

    def test_texture_data_correct_shape(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=10, texture_size=48)
        assert pe.texture_data.shape == (48, 48, 4)

    def test_alpha_proportional_to_remaining_life(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32, texture_size=64)
        # At half-life, alpha should be ~127
        pe.emit(count=1, position=(32.0, 32.0), color=(255, 255, 255), lifetime=2.0, speed_range=(0.0, 0.0))
        pe.tick(dt=1.0)  # consume half of lifetime
        td = pe.texture_data
        # Find non-zero alpha pixels and check they're roughly half
        alpha_pixels = td[:, :, 3]
        nonzero = alpha_pixels[alpha_pixels > 0]
        if len(nonzero) > 0:
            # At half life, alpha should be roughly 127 (±40 tolerance)
            assert np.any(np.abs(nonzero.astype(int) - 127) < 40)

    def test_texture_cleared_when_no_particles(self):
        from pharos_engine.particles import ParticleEmitter
        pe = ParticleEmitter(max_particles=32, texture_size=32)
        pe.emit(count=5, position=(16.0, 16.0), color=(255, 0, 0), lifetime=0.01, speed_range=(0.0, 0.0))
        pe.tick(dt=1.0)  # kill all particles
        td = pe.texture_data
        assert np.all(td == 0), "texture should be fully black when no live particles"


class TestEmitterConfig:
    def test_to_bytes_length(self):
        from pharos_engine.particles import EmitterConfig
        cfg = EmitterConfig()
        data = cfg.to_bytes()
        assert len(data) == 64  # 16 floats × 4 bytes

    def test_to_bytes_returns_bytes(self):
        from pharos_engine.particles import EmitterConfig
        cfg = EmitterConfig(position=(1.0, 2.0, 3.0))
        assert isinstance(cfg.to_bytes(), bytes)

    def test_default_shape_point(self):
        from pharos_engine.particles import EmitterConfig, EmitterShape
        cfg = EmitterConfig()
        assert cfg.shape == EmitterShape.POINT

    def test_custom_speed_range(self):
        from pharos_engine.particles import EmitterConfig
        cfg = EmitterConfig(speed_min=10.0, speed_max=50.0)
        assert cfg.speed_min == pytest.approx(10.0)
        assert cfg.speed_max == pytest.approx(50.0)


class TestTurbulenceConfig:
    def test_to_bytes_length(self):
        from pharos_engine.particles import TurbulenceConfig
        tc = TurbulenceConfig(strength=0.5, speed=2.0, scale=0.01)
        assert len(tc.to_bytes()) == 16  # 4 floats × 4 bytes

    def test_default_strength_zero(self):
        from pharos_engine.particles import TurbulenceConfig
        tc = TurbulenceConfig()
        assert tc.strength == pytest.approx(0.0)
