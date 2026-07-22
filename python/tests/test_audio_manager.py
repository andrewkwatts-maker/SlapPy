"""Engine tests for AudioManager — headless (graceful degradation without sounddevice)."""
from __future__ import annotations
import pytest


class TestLoopHandle:
    def test_init_fields(self):
        from slappyengine.audio import LoopHandle
        lh = LoopHandle(loop_id=7, volume=0.8)
        assert lh.loop_id == 7
        assert lh.volume == pytest.approx(0.8)
        assert lh.pitch == pytest.approx(1.0)

    def test_stop_event_initially_clear(self):
        from slappyengine.audio import LoopHandle
        lh = LoopHandle(loop_id=1)
        assert not lh._stop.is_set()

    def test_thread_initially_none(self):
        from slappyengine.audio import LoopHandle
        lh = LoopHandle(loop_id=2)
        assert lh._thread is None


class TestAudioManagerInit:
    def test_available_attribute_exists(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        assert hasattr(am, "available")
        assert isinstance(am.available, bool)

    def test_available_false_without_sounddevice(self):
        """sounddevice is not installed in CI — expect available=False."""
        from slappyengine.audio import AudioManager
        am = AudioManager()
        # In CI without sounddevice installed
        try:
            import sounddevice  # noqa: F401
            # sounddevice is installed — available may be True
        except ImportError:
            assert am.available is False

    def test_master_volume_default(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        assert am.master_volume == pytest.approx(1.0)

    def test_cache_initially_empty(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        assert am._cache == {}

    def test_loops_initially_empty(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        assert am._loops == {}


class TestAudioManagerMasterVolume:
    def test_set_master_volume(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.master_volume = 0.5
        assert am.master_volume == pytest.approx(0.5)

    def test_master_volume_clamped_above_one(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.master_volume = 2.0
        assert am.master_volume == pytest.approx(1.0)

    def test_master_volume_clamped_below_zero(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.master_volume = -0.5
        assert am.master_volume == pytest.approx(0.0)


class TestAudioManagerLoadNoSounddevice:
    def test_load_returns_none_when_unavailable(self, tmp_path):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        if am.available:
            pytest.skip("sounddevice installed — skip unavailable path")
        result = am.load(str(tmp_path / "nonexistent.wav"))
        assert result is None

    def test_play_does_not_raise_when_unavailable(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        if am.available:
            pytest.skip("sounddevice installed")
        am.play(None)  # must not raise

    def test_play_loop_returns_int_when_unavailable(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None, volume=0.5)
        assert isinstance(loop_id, int)

    def test_play_loop_increments_id(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        id1 = am.play_loop(None)
        id2 = am.play_loop(None)
        assert id2 > id1

    def test_stop_loop_nonexistent_no_raise(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.stop_loop(9999)  # must not raise

    def test_set_loop_volume_nonexistent_no_raise(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.set_loop_volume(9999, 0.5)  # must not raise

    def test_set_loop_pitch_nonexistent_no_raise(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.set_loop_pitch(9999, 1.5)  # must not raise

    def test_stop_all_no_raise(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.stop_all()  # must not raise

    def test_play_spatial_none_no_raise(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.play_spatial(None, (0, 0), (100, 100))  # must not raise


class TestAudioManagerLoopLifecycle:
    def test_loop_stored_in_loops_dict(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None)
        assert loop_id in am._loops

    def test_stop_loop_removes_from_dict(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None)
        am.stop_loop(loop_id)
        assert loop_id not in am._loops

    def test_set_loop_volume_updates_target(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None, volume=1.0)
        am.set_loop_volume(loop_id, 0.3)
        lh = am._loops.get(loop_id)
        assert lh is not None
        assert lh._target_volume == pytest.approx(0.3)

    def test_set_loop_pitch_clamped(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None)
        am.set_loop_pitch(loop_id, 10.0)  # beyond max=4.0
        lh = am._loops.get(loop_id)
        assert lh.pitch == pytest.approx(4.0)

    def test_set_loop_pitch_clamped_below(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        loop_id = am.play_loop(None)
        am.set_loop_pitch(loop_id, 0.0)  # below min=0.1
        lh = am._loops.get(loop_id)
        assert lh.pitch == pytest.approx(0.1)

    def test_stop_all_clears_loops(self):
        from slappyengine.audio import AudioManager
        am = AudioManager()
        am.play_loop(None)
        am.play_loop(None)
        am.stop_all()
        assert len(am._loops) == 0
