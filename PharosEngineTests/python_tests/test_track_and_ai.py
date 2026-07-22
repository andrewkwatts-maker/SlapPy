"""Engine tests for track.py (SplineTrack) and ai/ modules (LLMClient, OllamaManager).
All headless — no GPU, no network, no server required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_spline():
    from pharos_engine.spline import CatmullRomSpline
    pts = [(200, 400), (400, 150), (600, 400), (400, 600)]
    return CatmullRomSpline(pts, closed=True)


# ---------------------------------------------------------------------------
# SplineTrack — init and config
# ---------------------------------------------------------------------------

class TestSplineTrackInit:
    def test_instantiates(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track is not None

    def test_road_width_stored(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), width=80.0, canvas_size=(320, 240))
        assert track.road_width == pytest.approx(80.0)

    def test_canvas_size_stored(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(640, 480))
        assert track.canvas_size == (640, 480)

    def test_segments_stored(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), segments=120, canvas_size=(320, 240))
        assert track.segments == 120

    def test_road_color_stored(self):
        from pharos_engine.track import SplineTrack
        color = (64, 64, 64, 255)
        track = SplineTrack(_simple_spline(), road_color=color, canvas_size=(320, 240))
        assert track.road_color == color

    def test_z_height_zero(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track.z_height == pytest.approx(0.0)

    def test_layer_created(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track._layer is not None

    def test_layer_image_shape(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track._layer._image_data.shape == (240, 320, 4)

    def test_default_road_color(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        # Default asphalt color
        assert len(track.road_color) == 4

    def test_default_segments(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track.segments == 240

    def test_name_is_splinetrack(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        assert track.name == "SplineTrack"


class TestSplineTrackRebuild:
    def test_rebuild_no_crash(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        track.rebuild()   # should not raise

    def test_rebuild_produces_nonzero_pixels(self):
        from pharos_engine.track import SplineTrack
        import numpy as np
        track = SplineTrack(_simple_spline(), canvas_size=(320, 240))
        # Road pixels should have non-zero alpha
        assert np.any(track._layer._image_data[:, :, 3] > 0)

    def test_road_color_appears_in_layer(self):
        from pharos_engine.track import SplineTrack
        import numpy as np
        color = (200, 50, 50, 255)
        track = SplineTrack(_simple_spline(), road_color=color, canvas_size=(320, 240))
        rgb = track._layer._image_data[:, :, :3]
        # At least some pixels should match the road color
        mask = (rgb[:, :, 0] == 200) & (rgb[:, :, 1] == 50) & (rgb[:, :, 2] == 50)
        assert np.any(mask)

    def test_no_texture_path_no_crash(self):
        from pharos_engine.track import SplineTrack
        track = SplineTrack(_simple_spline(), texture_path=None, canvas_size=(320, 240))
        assert track._road_tex is None


# ---------------------------------------------------------------------------
# LLMClient — import-level and module constants
# ---------------------------------------------------------------------------

class TestLLMClientImport:
    def test_importable(self):
        from pharos_engine.ai.llm_client import LLMClient
        assert LLMClient is not None

    def test_default_host_constant(self):
        from pharos_engine.ai import llm_client
        assert llm_client._DEFAULT_HOST == "http://localhost:11434"

    def test_default_model_constant(self):
        from pharos_engine.ai import llm_client
        assert "coder" in llm_client._DEFAULT_MODEL or "llama" in llm_client._DEFAULT_MODEL or llm_client._DEFAULT_MODEL != ""

    def test_require_httpx_raises_import_error_hint(self, monkeypatch):
        """When httpx unavailable, _require_httpx raises ImportError with helpful hint."""
        import sys
        # Temporarily hide httpx
        original = sys.modules.get("httpx", None)
        sys.modules["httpx"] = None   # type: ignore
        try:
            from pharos_engine.ai.llm_client import _require_httpx
            with pytest.raises((ImportError, TypeError)):
                _require_httpx()
        finally:
            if original is not None:
                sys.modules["httpx"] = original
            elif "httpx" in sys.modules:
                del sys.modules["httpx"]


# ---------------------------------------------------------------------------
# OllamaManager — import-level and pure-Python methods
# ---------------------------------------------------------------------------

class TestOllamaManagerImport:
    def test_importable(self):
        from pharos_engine.ai.ollama_manager import OllamaManager
        assert OllamaManager is not None

    def test_default_model_constant(self):
        from pharos_engine.ai.ollama_manager import OllamaManager
        assert isinstance(OllamaManager.DEFAULT_MODEL, str)
        assert len(OllamaManager.DEFAULT_MODEL) > 0

    def test_instantiates(self):
        from pharos_engine.ai.ollama_manager import OllamaManager
        mgr = OllamaManager()
        assert mgr is not None

    def test_is_ollama_installed_returns_bool(self):
        from pharos_engine.ai.ollama_manager import OllamaManager
        mgr = OllamaManager()
        result = mgr.is_ollama_installed()
        assert isinstance(result, bool)

    def test_is_server_running_returns_bool(self):
        from pharos_engine.ai.ollama_manager import OllamaManager
        mgr = OllamaManager()
        result = mgr.is_server_running()
        assert isinstance(result, bool)

    def test_settings_constants(self):
        from pharos_engine.ai.ollama_manager import _SETTINGS_DIR, _SETTINGS_FILE
        assert "Pharos Engine" in str(_SETTINGS_DIR)
        assert "ai_settings" in str(_SETTINGS_FILE)

    def test_load_ai_settings_returns_dict(self):
        from pharos_engine.ai.ollama_manager import load_ai_settings
        result = load_ai_settings()
        assert isinstance(result, dict)

    def test_save_and_load_ai_settings(self, tmp_path, monkeypatch):
        import pharos_engine.ai.ollama_manager as om
        monkeypatch.setattr(om, "_SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(om, "_SETTINGS_FILE", tmp_path / "ai_settings.json")
        om.save_ai_settings({"model": "test-model", "enabled": True})
        result = om.load_ai_settings()
        assert result.get("model") == "test-model"
        assert result.get("enabled") is True
