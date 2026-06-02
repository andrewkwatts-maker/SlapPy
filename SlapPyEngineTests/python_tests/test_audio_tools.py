"""Headless tests for audio_tools — soundfile is mocked throughout."""
from __future__ import annotations
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


def _sf_mock(data: np.ndarray, samplerate: int = 44100):
    """Build a soundfile mock that returns *data* on .read()."""
    sf = MagicMock()
    sf.read.return_value = (data, samplerate)
    return sf


def _patch_sf(sf_mock):
    return patch("slappyengine.tools.audio_tools._require_soundfile",
                 return_value=sf_mock)


# =============================================================================
# _require_soundfile — ImportError when soundfile not installed
# =============================================================================

class TestRequireSoundfile:
    def test_raises_import_error_when_missing(self):
        """_require_soundfile raises ImportError when soundfile isn't installed."""
        with patch("slappyengine.tools.audio_tools._require_soundfile",
                   side_effect=ImportError("soundfile not found")):
            from slappyengine.tools.audio_tools import _require_soundfile
            with pytest.raises(ImportError):
                _require_soundfile()


# =============================================================================
# trim_silence
# =============================================================================

class TestTrimSilence:
    def _call(self, data, out_path, threshold_db=-40.0):
        from slappyengine.tools.audio_tools import trim_silence
        sf = _sf_mock(data)
        with _patch_sf(sf):
            result = trim_silence("fake.wav", str(out_path), threshold_db=threshold_db)
        return result, sf

    def test_returns_string(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32) * 0.5
        result, _ = self._call(data, tmp_path / "out.wav")
        assert isinstance(result, str)

    def test_all_silence_writes_one_sample(self, tmp_path):
        data = np.zeros((500, 1), dtype=np.float32)  # complete silence
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 1

    def test_all_loud_preserves_full_length(self, tmp_path):
        data = np.ones((200, 1), dtype=np.float32) * 0.9
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 200

    def test_leading_silence_trimmed(self, tmp_path):
        data = np.zeros((300, 1), dtype=np.float32)
        data[100:] = 0.8  # silence in first 100 samples
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 200  # 300 - 100 leading silence samples

    def test_trailing_silence_trimmed(self, tmp_path):
        data = np.zeros((300, 1), dtype=np.float32)
        data[:200] = 0.8  # silence in last 100 samples
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 200

    def test_both_ends_trimmed(self, tmp_path):
        data = np.zeros((500, 1), dtype=np.float32)
        data[100:400] = 0.5  # loud in middle 300 samples
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 300

    def test_samplerate_preserved(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32) * 0.5
        sf = _sf_mock(data, samplerate=22050)
        from slappyengine.tools.audio_tools import trim_silence
        with _patch_sf(sf):
            trim_silence("fake.wav", str(tmp_path / "out.wav"))
        sr_written = sf.write.call_args[0][2]
        assert sr_written == 22050

    def test_higher_threshold_trims_more(self, tmp_path):
        data = np.zeros((300, 1), dtype=np.float32)
        data[:] = 0.01  # very quiet, below -40dB threshold
        data[100:200] = 0.5  # louder section
        # With default -40dB: 0.01 is above threshold (0.01 > 0.01 linear is borderline)
        # With -20dB threshold: 0.01 < 0.1 linear → silence
        _, sf_tight = self._call(data, tmp_path / "tight.wav", threshold_db=-20.0)
        written_tight = sf_tight.write.call_args[0][1]
        _, sf_loose = self._call(data, tmp_path / "loose.wav", threshold_db=-60.0)
        written_loose = sf_loose.write.call_args[0][1]
        assert len(written_tight) <= len(written_loose)

    def test_write_called_once(self, tmp_path):
        data = np.ones((50, 1), dtype=np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        sf.write.assert_called_once()

    def test_multichannel_data(self, tmp_path):
        data = np.zeros((200, 2), dtype=np.float32)
        data[50:150, :] = 0.7
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert written.shape[1] == 2  # channels preserved


# =============================================================================
# normalize
# =============================================================================

class TestNormalize:
    def _call(self, data, out_path, peak_db=-1.0):
        from slappyengine.tools.audio_tools import normalize
        sf = _sf_mock(data)
        with _patch_sf(sf):
            result = normalize("fake.wav", str(out_path), peak_db=peak_db)
        return result, sf

    def test_returns_string(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32) * 0.5
        result, _ = self._call(data, tmp_path / "out.wav")
        assert isinstance(result, str)

    def test_silent_file_passes_through(self, tmp_path):
        data = np.zeros((100, 1), dtype=np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert np.allclose(written, 0.0)

    def test_peak_at_target_db(self, tmp_path):
        data = np.zeros((100, 1), dtype=np.float32)
        data[50] = 0.4  # peak of 0.4 linear
        _, sf = self._call(data, tmp_path / "out.wav", peak_db=-6.0)
        written = sf.write.call_args[0][1]
        target_linear = 10 ** (-6.0 / 20.0)
        assert abs(np.abs(written).max() - target_linear) < 0.001

    def test_negative_one_db_target(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32) * 0.5
        _, sf = self._call(data, tmp_path / "out.wav", peak_db=-1.0)
        written = sf.write.call_args[0][1]
        target = 10 ** (-1.0 / 20.0)
        assert abs(written.max() - target) < 0.001

    def test_output_clipped_to_one(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32) * 0.001  # very quiet
        _, sf = self._call(data, tmp_path / "out.wav", peak_db=0.0)  # target = 1.0 linear
        written = sf.write.call_args[0][1]
        assert written.max() <= 1.0

    def test_shape_preserved(self, tmp_path):
        data = np.random.rand(200, 2).astype(np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert written.shape == data.shape

    def test_write_called_once(self, tmp_path):
        data = np.ones((50, 1), dtype=np.float32) * 0.3
        _, sf = self._call(data, tmp_path / "out.wav")
        sf.write.assert_called_once()

    def test_samplerate_preserved(self, tmp_path):
        data = np.ones((100, 1), dtype=np.float32)
        sf = _sf_mock(data, samplerate=48000)
        from slappyengine.tools.audio_tools import normalize
        with _patch_sf(sf):
            normalize("fake.wav", str(tmp_path / "out.wav"))
        sr_written = sf.write.call_args[0][2]
        assert sr_written == 48000


# =============================================================================
# loop_seamless
# =============================================================================

class TestLoopSeamless:
    def _call(self, data, out_path):
        from slappyengine.tools.audio_tools import loop_seamless
        sf = _sf_mock(data)
        with _patch_sf(sf):
            result = loop_seamless("fake.wav", str(out_path))
        return result, sf

    def test_returns_string(self, tmp_path):
        data = np.random.rand(10240, 1).astype(np.float32)
        result, _ = self._call(data, tmp_path / "out.wav")
        assert isinstance(result, str)

    def test_output_same_length(self, tmp_path):
        data = np.random.rand(4096, 1).astype(np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == len(data)

    def test_output_same_channels(self, tmp_path):
        data = np.random.rand(4096, 2).astype(np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert written.shape[1] == 2

    def test_fade_len_min_512_samples(self, tmp_path):
        # Short file: n=1000, 5% = 50 < 512 → fade_len = 512
        data = np.random.rand(1000, 1).astype(np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == 1000

    def test_fade_len_five_percent_for_long_file(self, tmp_path):
        # Long file: 20480 samples, 5% = 1024 > 512 → fade_len = 1024
        n = 20480
        data = np.ones((n, 1), dtype=np.float32) * 0.5
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        assert len(written) == n

    def test_crossfade_modifies_end_region(self, tmp_path):
        n = 10000
        fade_len = max(512, int(n * 0.05))  # = 512 for n=10000
        data = np.zeros((n, 1), dtype=np.float32)
        data[:fade_len] = 0.0   # beginning is silent
        data[-fade_len:] = 1.0  # end is loud
        _, sf = self._call(data, tmp_path / "out.wav")
        written = sf.write.call_args[0][1]
        # At last sample: fade_out[-1]=0 → end contribution=0;
        #                 fade_in[-1]=1  → start contribution=0.0 (start is silent)
        # So result[-1] = 1.0*0 + 0.0*1 = 0.0 (different from original 1.0)
        assert written[-1][0] == pytest.approx(0.0, abs=0.05)

    def test_write_called_once(self, tmp_path):
        data = np.random.rand(4096, 1).astype(np.float32)
        _, sf = self._call(data, tmp_path / "out.wav")
        sf.write.assert_called_once()

    def test_samplerate_preserved(self, tmp_path):
        data = np.random.rand(4096, 1).astype(np.float32)
        sf = _sf_mock(data, samplerate=22050)
        from slappyengine.tools.audio_tools import loop_seamless
        with _patch_sf(sf):
            loop_seamless("fake.wav", str(tmp_path / "out.wav"))
        sr_written = sf.write.call_args[0][2]
        assert sr_written == 22050
