"""Engine tests for ui/scene_ui.py, asset.py, render_target.py, and misc stubs."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# SceneUIEntity
# ---------------------------------------------------------------------------

class TestSceneUIEntityInit:
    def test_instantiates(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(name="TestUI", size=(200, 100))
        assert ui is not None

    def test_name_stored(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(name="MyUI")
        assert ui.name == "MyUI"

    def test_size_stored(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(320, 240))
        assert ui.size == (320, 240)

    def test_html_initially_empty(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        assert ui._html_content == ""

    def test_text_lines_initially_empty(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        assert ui._text_lines == []

    def test_has_layers(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(100, 50))
        assert len(ui.layers) >= 1

    def test_canvas_shape_matches_size(self):
        import numpy as np
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(80, 60))
        assert ui._canvas.shape == (60, 80, 4)

    def test_dirty_initially_true(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        assert ui._dirty is True


class TestSceneUIEntitySetHtml:
    def test_set_html_stores_content(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_html("<p>Hello</p>")
        assert "<p>Hello</p>" in ui._html_content

    def test_set_html_strips_tags_for_text(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_html("<h1>Title</h1><p>Body</p>")
        text = " ".join(ui._text_lines)
        assert "Title" in text
        assert "Body" in text

    def test_set_html_marks_dirty(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui._dirty = False
        ui.set_html("<p>x</p>")
        assert ui._dirty is True


class TestSceneUIEntitySetText:
    def test_set_text_stores_lines(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_text("Line 1", "Line 2", "Line 3")
        assert ui._text_lines == ["Line 1", "Line 2", "Line 3"]

    def test_set_text_marks_dirty(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui._dirty = False
        ui.set_text("hello")
        assert ui._dirty is True

    def test_set_text_replaces_previous(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_text("old")
        ui.set_text("new1", "new2")
        assert ui._text_lines == ["new1", "new2"]


class TestSceneUIEntityColors:
    def test_set_background_stores_color(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_background(50, 100, 150, 200)
        assert ui._bg_color == (50, 100, 150, 200)

    def test_set_background_marks_dirty(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui._dirty = False
        ui.set_background(0, 0, 0)
        assert ui._dirty is True

    def test_set_text_color_stores_color(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        ui.set_text_color(200, 100, 50)
        assert ui._text_color == (200, 100, 50, 255)

    def test_default_background_is_dark(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        # Default background should be dark (low R, G, B)
        assert ui._bg_color[0] < 100

    def test_default_text_color_is_white(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity()
        assert ui._text_color[0] == 255


class TestSceneUIEntityRenderToCanvas:
    def test_render_to_canvas_no_exception(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(100, 50))
        ui.set_text("Hello World")
        ui._render_to_canvas()

    def test_render_clears_dirty_flag(self):
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(100, 50))
        ui.set_text("test")
        ui._render_to_canvas()
        assert ui._dirty is False

    def test_render_canvas_non_zero_after_render(self):
        import numpy as np
        from pharos_editor.ui.scene_ui import SceneUIEntity
        ui = SceneUIEntity(size=(100, 50))
        ui._render_to_canvas()
        # After render, canvas should have some non-zero pixels (background fill)
        assert np.any(ui._canvas != 0)


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class TestAssetInit:
    def test_instantiates(self):
        from pharos_engine.asset import Asset
        a = Asset(name="Car", position=(10.0, 20.0), size=(64, 64))
        assert a is not None

    def test_name_stored(self):
        from pharos_engine.asset import Asset
        a = Asset(name="Tank")
        assert a.name == "Tank"

    def test_position_stored(self):
        from pharos_engine.asset import Asset
        a = Asset(position=(5.0, 15.0))
        assert a.position == (5.0, 15.0)

    def test_size_stored(self):
        from pharos_engine.asset import Asset
        a = Asset(size=(128, 128))
        assert a.size == (128, 128)

    def test_effects_list_initially_empty(self):
        from pharos_engine.asset import Asset
        a = Asset()
        assert a.effects == []

    def test_cache_mode_default(self):
        from pharos_engine.asset import Asset
        from pharos_engine.residency.manager import CacheMode
        a = Asset()
        assert a.cache_mode == CacheMode.OFFSCREEN_SERIALIZE

    def test_has_id_attribute(self):
        from pharos_engine.asset import Asset
        a = Asset(name="MyAsset")
        assert hasattr(a, "id")
        assert a.id  # should be non-empty

    def test_layers_initially_empty(self):
        from pharos_engine.asset import Asset
        a = Asset()
        assert a.layers == []


class TestAssetLayerManagement:
    def test_add_layer_appends(self):
        from pharos_engine.asset import Asset
        from pharos_engine.layer import Layer2D
        a = Asset()
        layer = Layer2D.blank(32, 32)
        a.add_layer(layer)
        assert layer in a.layers

    def test_add_layer_returns_layer(self):
        from pharos_engine.asset import Asset
        from pharos_engine.layer import Layer2D
        a = Asset()
        layer = Layer2D.blank(32, 32)
        result = a.add_layer(layer)
        assert result is layer

    def test_bake_data_layer_creates_slap(self, tmp_path):
        from pharos_engine.asset import Asset
        from pharos_engine.layer import Layer2D
        a = Asset(name="Bakeable")
        a.add_layer(Layer2D.blank(16, 16))
        out = tmp_path / "baked.slap"
        a.bake_data_layer(str(out))
        assert out.exists()


# ---------------------------------------------------------------------------
# RenderTarget
# ---------------------------------------------------------------------------

class TestRenderTarget:
    def test_instantiates(self):
        from pharos_engine.render_target import RenderTarget
        rt = RenderTarget(name="TestRT", size=(100, 100))
        assert rt is not None

    def test_visible_by_default(self):
        from pharos_engine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.visible is True

    def test_z_order_default_zero(self):
        from pharos_engine.render_target import RenderTarget
        rt = RenderTarget()
        assert rt.z_order == pytest.approx(0.0)

    def test_add_remove_layer(self):
        from pharos_engine.render_target import RenderTarget
        from pharos_engine.layer import Layer2D
        rt = RenderTarget(size=(64, 64))
        layer = Layer2D.blank(64, 64)
        rt.add_layer(layer)
        assert layer in rt.layers
        rt.remove_layer(layer)
        assert layer not in rt.layers

    def test_tick_runs_no_error(self):
        from pharos_engine.render_target import RenderTarget
        rt = RenderTarget()
        rt.tick(0.016)  # should not raise


# ---------------------------------------------------------------------------
# wave_manager (empty module — just verify import)
# ---------------------------------------------------------------------------

class TestWaveManager:
    def test_import_does_not_raise(self):
        import pharos_engine.wave_manager  # noqa: F401


# ---------------------------------------------------------------------------
# audio_tools (import-only; soundfile not required for import check)
# ---------------------------------------------------------------------------

class TestAudioToolsImport:
    def test_import_no_exception(self):
        import pharos_engine.tools.audio_tools  # noqa: F401

    def test_functions_exist(self):
        from pharos_engine.tools.audio_tools import trim_silence, normalize, loop_seamless
        assert callable(trim_silence)
        assert callable(normalize)
        assert callable(loop_seamless)

    def test_no_soundfile_raises_importerror_on_call(self, tmp_path):
        """When soundfile is absent, calls should raise ImportError."""
        try:
            import soundfile  # noqa: F401
            pytest.skip("soundfile is installed; can't test missing-dep path")
        except ImportError:
            pass
        from pharos_engine.tools.audio_tools import trim_silence
        dummy_in = tmp_path / "in.wav"
        dummy_in.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        with pytest.raises(ImportError):
            trim_silence(str(dummy_in), str(tmp_path / "out.wav"))
