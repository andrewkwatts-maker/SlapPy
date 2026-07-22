"""Engine tests for ui/debug_overlay.py and ui/hud_widgets.py — headless."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# DebugOverlay tests
# ---------------------------------------------------------------------------

class TestDebugOverlayInit:
    def test_instantiation_no_error(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        assert overlay is not None

    def test_initially_not_visible(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        assert overlay.visible is False

    def test_show_events_initially_false(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        assert overlay._show_events is False

    def test_show_passes_initially_false(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        assert overlay._show_passes is False

    def test_show_heatmap_initially_false(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        assert overlay._show_heatmap is False


class TestDebugOverlayToggles:
    def test_toggle_events_turns_on(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        result = overlay.toggle_events()
        assert result is True
        assert overlay._show_events is True

    def test_toggle_events_turns_off(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_events()
        result = overlay.toggle_events()
        assert result is False

    def test_toggle_passes_turns_on(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        result = overlay.toggle_passes()
        assert result is True

    def test_toggle_heatmap_turns_on(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        result = overlay.toggle_heatmap()
        assert result is True

    def test_visible_when_any_panel_on(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        assert overlay.visible is True

    def test_not_visible_when_all_off(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        overlay.toggle_passes()  # off again
        assert overlay.visible is False


class TestDebugOverlayReporting:
    def test_report_pass_stored(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.report_pass("PixelCollisionPass", skipping=True)
        assert "PixelCollisionPass" in overlay._pass_status
        assert overlay._pass_status["PixelCollisionPass"] is True

    def test_report_pass_running(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.report_pass("FluidPass", skipping=False)
        assert overlay._pass_status["FluidPass"] is False

    def test_record_attr_publish_when_heatmap_on(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_heatmap()
        overlay.record_attr_publish("speed")
        overlay.record_attr_publish("speed")
        assert overlay._heatmap.get("speed", 0) == 2

    def test_record_attr_publish_ignored_when_heatmap_off(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.record_attr_publish("speed")
        assert overlay._heatmap.get("speed", 0) == 0

    def test_begin_frame_clears_heatmap(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_heatmap()
        overlay.record_attr_publish("x")
        overlay.begin_frame()
        assert overlay._heatmap.get("x", 0) == 0


class TestDebugOverlayRenderText:
    def test_render_text_empty_when_all_off(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        text = overlay.render_text()
        assert text == ""

    def test_render_text_shows_pass_section(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        overlay.report_pass("FogPass", skipping=True)
        text = overlay.render_text()
        assert "ComputePass" in text
        assert "FogPass" in text

    def test_render_text_shows_heatmap_section(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_heatmap()
        overlay.record_attr_publish("velocity")
        text = overlay.render_text()
        assert "Heatmap" in text
        assert "velocity" in text

    def test_render_text_skipping_labeled(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        overlay.report_pass("TestPass", skipping=True)
        text = overlay.render_text()
        assert "SKIP" in text

    def test_render_text_running_labeled(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        overlay.report_pass("ActivePass", skipping=False)
        text = overlay.render_text()
        assert "RUN" in text


class TestDebugOverlayRender:
    def test_render_returns_none_when_invisible(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        result = overlay.render(width=400)
        assert result is None

    def test_render_returns_image_when_passes_visible(self):
        from slappyengine.ui.debug_overlay import DebugOverlay
        overlay = DebugOverlay()
        overlay.toggle_passes()
        overlay.report_pass("TestPass", skipping=False)
        result = overlay.render(width=400)
        # Either PIL image or None (if PIL unavailable)
        if result is not None:
            assert hasattr(result, "size")


# ---------------------------------------------------------------------------
# hud_widgets tests
# ---------------------------------------------------------------------------

class TestDrawStatBar:
    def _make_draw(self, size=(300, 50)):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        return ImageDraw.Draw(img), img

    def test_no_exception(self):
        from slappyengine.ui.hud_widgets import draw_stat_bar
        draw, _ = self._make_draw()
        draw_stat_bar(draw, x=10, y=10, w=100, h=16,
                      value=50, max_value=100)

    def test_full_bar_fills_completely(self):
        from PIL import Image, ImageDraw
        import numpy as np
        from slappyengine.ui.hud_widgets import draw_stat_bar
        img = Image.new("RGBA", (120, 30), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        fill = (220, 60, 60, 255)
        draw_stat_bar(draw, x=0, y=0, w=100, h=20,
                      value=100, max_value=100, fill_color=fill[:3])
        arr = np.array(img)
        # Most of the first row of the bar should be fill color
        fill_pixels = np.sum(arr[5, :100, 0] == 220)
        assert fill_pixels > 80

    def test_empty_bar_no_fill(self):
        from PIL import Image, ImageDraw
        import numpy as np
        from slappyengine.ui.hud_widgets import draw_stat_bar
        img = Image.new("RGBA", (120, 30), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        draw_stat_bar(draw, x=0, y=0, w=100, h=20,
                      value=0, max_value=100,
                      fill_color=(220, 60, 60),
                      bg_color=(40, 40, 40))
        arr = np.array(img)
        # No red fill expected
        fill_pixels = np.sum(arr[5, 5:95, 0] == 220)
        assert fill_pixels == 0

    def test_zero_max_no_crash(self):
        from slappyengine.ui.hud_widgets import draw_stat_bar
        draw, _ = self._make_draw()
        draw_stat_bar(draw, x=0, y=0, w=100, h=16, value=50, max_value=0)

    def test_over_max_clamped(self):
        from PIL import Image, ImageDraw
        import numpy as np
        from slappyengine.ui.hud_widgets import draw_stat_bar
        img = Image.new("RGBA", (120, 30), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Should not raise or overflow — value > max_value is clamped to 1.0
        draw_stat_bar(draw, x=0, y=0, w=100, h=16,
                      value=200, max_value=100, fill_color=(0, 255, 0))

    def test_with_label_no_exception(self):
        from slappyengine.ui.hud_widgets import draw_stat_bar
        draw, _ = self._make_draw()
        draw_stat_bar(draw, x=10, y=5, w=120, h=18,
                      value=75, max_value=100, label="HP")

    def test_custom_colors_applied(self):
        from PIL import Image, ImageDraw
        import numpy as np
        from slappyengine.ui.hud_widgets import draw_stat_bar
        img = Image.new("RGBA", (120, 30), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Use bright green fill on black background
        draw_stat_bar(draw, x=0, y=0, w=100, h=20,
                      value=100, max_value=100,
                      fill_color=(0, 255, 0),
                      bg_color=(0, 0, 0))
        arr = np.array(img)
        green_pixels = np.sum(arr[5, 5:95, 1] == 255)
        assert green_pixels > 50
