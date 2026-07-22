"""Engine tests for tools/track_tools.py and tools/texture_tools.py — headless."""
from __future__ import annotations
import numpy as np
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockSpline:
    """Minimal spline-like object providing sample_points()."""

    def __init__(self, pts=None):
        self._pts = pts or [
            (0.0, 0.0), (100.0, 0.0), (200.0, 100.0), (100.0, 200.0), (0.0, 100.0)
        ]

    def sample_points(self, n=256):
        # Return evenly-spaced subset
        step = max(1, len(self._pts) // n)
        result = self._pts[::step][:n]
        return result


class _EvaluateSpline:
    """Spline that uses evaluate(t) interface."""

    def evaluate(self, t):
        return (t * 400.0, t * 300.0)


class _ControlPointSpline:
    """Spline that uses control_points attribute."""

    control_points = [(0, 0), (100, 0), (200, 100)]


# ---------------------------------------------------------------------------
# track_tools tests
# ---------------------------------------------------------------------------

class TestBakeTrackThumbnail:
    def test_returns_pil_image(self):
        from PIL import Image
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        spline = _MockSpline()
        img = bake_track_thumbnail(spline, size=(100, 100))
        assert isinstance(img, Image.Image)

    def test_correct_size(self):
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        spline = _MockSpline()
        img = bake_track_thumbnail(spline, size=(80, 60))
        assert img.size == (80, 60)

    def test_non_black_output_with_track(self):
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        import numpy as np
        spline = _MockSpline()
        img = bake_track_thumbnail(spline, size=(128, 128))
        arr = np.array(img)
        # Should have some non-background pixels (the road line)
        assert arr.max() > 30

    def test_empty_spline_returns_image(self):
        from PIL import Image
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        spline = _MockSpline(pts=[])
        img = bake_track_thumbnail(spline, size=(50, 50))
        assert isinstance(img, Image.Image)
        assert img.size == (50, 50)

    def test_evaluate_interface(self):
        from PIL import Image
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        spline = _EvaluateSpline()
        img = bake_track_thumbnail(spline, size=(64, 64))
        assert isinstance(img, Image.Image)

    def test_control_points_interface(self):
        from PIL import Image
        from pharos_engine.tools.track_tools import bake_track_thumbnail
        spline = _ControlPointSpline()
        img = bake_track_thumbnail(spline, size=(64, 64))
        assert isinstance(img, Image.Image)


class TestExportTrackBoundary:
    def test_creates_file(self, tmp_path):
        from pharos_engine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        result = export_track_boundary(spline, width=50, out_png=out, canvas_size=(256, 256))
        assert Path(result).exists()

    def test_returns_absolute_path(self, tmp_path):
        from pharos_engine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        result = export_track_boundary(spline, width=50, out_png=out, canvas_size=(128, 128))
        assert Path(result).is_absolute()

    def test_output_size_matches_canvas(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=40, out_png=out, canvas_size=(320, 240))
        img = Image.open(out)
        assert img.size == (320, 240)

    def test_output_is_rgba(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=40, out_png=out, canvas_size=(128, 128))
        img = Image.open(out)
        assert img.mode == "RGBA"

    def test_creates_parent_dir(self, tmp_path):
        from pharos_engine.tools.track_tools import export_track_boundary
        spline = _MockSpline()
        out = str(tmp_path / "subdir" / "boundary.png")
        export_track_boundary(spline, width=40, out_png=out, canvas_size=(64, 64))
        assert Path(out).exists()

    def test_has_varying_alpha_values(self, tmp_path):
        from PIL import Image
        import numpy as np
        from pharos_engine.tools.track_tools import export_track_boundary
        # Use full mock spline to ensure a large enough track fits the canvas
        spline = _MockSpline()
        out = str(tmp_path / "boundary.png")
        export_track_boundary(spline, width=30, out_png=out, canvas_size=(512, 512))
        arr = np.array(Image.open(out))
        # Alpha channel should have at least two distinct values (road vs off-road)
        unique_alpha = np.unique(arr[:, :, 3])
        assert len(unique_alpha) >= 2, "Expected road and off-road alpha values"


class TestGenerateTrackDecalMask:
    def test_returns_ndarray(self):
        from pharos_engine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=50)
        assert isinstance(mask, np.ndarray)

    def test_mask_is_boolean(self):
        from pharos_engine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=50)
        assert mask.dtype == bool

    def test_mask_has_two_dims(self):
        from pharos_engine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=50)
        assert mask.ndim == 2

    def test_some_true_pixels(self):
        from pharos_engine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline()
        mask = generate_track_decal_mask(spline, width=60)
        assert mask.any(), "Expected some True pixels (road area)"

    def test_empty_spline_fallback(self):
        from pharos_engine.tools.track_tools import generate_track_decal_mask
        spline = _MockSpline(pts=[])
        mask = generate_track_decal_mask(spline, width=50)
        assert isinstance(mask, np.ndarray)


# ---------------------------------------------------------------------------
# texture_tools tests
# ---------------------------------------------------------------------------

class TestGenerateNoiseTexture:
    def test_returns_pil_image(self):
        from PIL import Image
        from pharos_engine.tools.texture_tools import generate_noise_texture
        img = generate_noise_texture(mode="fbm", width=64, height=64, octaves=2, seed=0)
        assert isinstance(img, Image.Image)

    def test_correct_size(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        img = generate_noise_texture(mode="fbm", width=32, height=48)
        assert img.size == (32, 48)

    def test_mode_is_grayscale(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        img = generate_noise_texture(mode="fbm", width=32, height=32)
        assert img.mode == "L"

    def test_fbm_has_variation(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        import numpy as np
        img = generate_noise_texture(mode="fbm", width=64, height=64, octaves=3)
        arr = np.array(img)
        assert arr.std() > 5.0, "FBM noise should have significant variation"

    def test_worley_mode(self):
        from PIL import Image
        from pharos_engine.tools.texture_tools import generate_noise_texture
        img = generate_noise_texture(mode="worley", width=64, height=64, seed=7)
        assert isinstance(img, Image.Image)
        assert img.size == (64, 64)

    def test_worley_has_variation(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        import numpy as np
        img = generate_noise_texture(mode="worley", width=64, height=64)
        arr = np.array(img)
        assert arr.std() > 5.0

    def test_seed_reproducible(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        import numpy as np
        img1 = generate_noise_texture(mode="fbm", width=32, height=32, seed=42)
        img2 = generate_noise_texture(mode="fbm", width=32, height=32, seed=42)
        assert np.array_equal(np.array(img1), np.array(img2))

    def test_different_seeds_differ(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        import numpy as np
        img1 = generate_noise_texture(mode="fbm", width=64, height=64, seed=1)
        img2 = generate_noise_texture(mode="fbm", width=64, height=64, seed=99)
        assert not np.array_equal(np.array(img1), np.array(img2))

    def test_unknown_mode_raises(self):
        from pharos_engine.tools.texture_tools import generate_noise_texture
        with pytest.raises(ValueError, match="Unknown noise mode"):
            generate_noise_texture(mode="invalid")


class TestPaintDecal:
    def _make_png(self, path, size=(64, 64), color=(200, 100, 50, 255)):
        from PIL import Image
        img = Image.new("RGBA", size, color)
        img.save(str(path))

    def test_creates_output_file(self, tmp_path):
        from pharos_engine.tools.texture_tools import paint_decal
        target = tmp_path / "target.png"
        decal = tmp_path / "decal.png"
        out = tmp_path / "out.png"
        self._make_png(target)
        self._make_png(decal, color=(255, 0, 0, 200))
        result = paint_decal(str(target), str(decal), pos=(32, 32), radius=16.0, rotation=0.0, out_png=str(out))
        assert Path(result).exists()

    def test_returns_absolute_path(self, tmp_path):
        from pharos_engine.tools.texture_tools import paint_decal
        target = tmp_path / "target.png"
        decal = tmp_path / "decal.png"
        out = tmp_path / "out.png"
        self._make_png(target)
        self._make_png(decal, color=(255, 0, 0, 200))
        result = paint_decal(str(target), str(decal), pos=(32, 32), radius=16.0, rotation=0.0, out_png=str(out))
        assert Path(result).is_absolute()

    def test_output_size_matches_target(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.texture_tools import paint_decal
        target = tmp_path / "target.png"
        decal = tmp_path / "decal.png"
        out = tmp_path / "out.png"
        self._make_png(target, size=(100, 80))
        self._make_png(decal)
        paint_decal(str(target), str(decal), pos=(50, 40), radius=20.0, rotation=0.0, out_png=str(out))
        img = Image.open(str(out))
        assert img.size == (100, 80)


class TestGenerateGradient:
    def test_returns_pil_image(self):
        from PIL import Image
        from pharos_engine.tools.texture_tools import generate_gradient
        img = generate_gradient([(0, 0, 0), (255, 255, 255)], width=64, height=32)
        assert isinstance(img, Image.Image)

    def test_correct_size(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        img = generate_gradient([(0, 0, 0), (255, 0, 0)], width=100, height=50)
        assert img.size == (100, 50)

    def test_mode_is_rgba(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        img = generate_gradient([(0, 0, 0), (255, 255, 255)], width=32, height=32)
        assert img.mode == "RGBA"

    def test_horizontal_gradient_varies_left_to_right(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        import numpy as np
        img = generate_gradient([(0, 0, 0, 255), (255, 255, 255, 255)],
                                width=128, height=4, direction="horizontal")
        arr = np.array(img)
        # Left column should be dark, right column bright
        assert int(arr[0, 0, 0]) < int(arr[0, -1, 0])

    def test_vertical_gradient_varies_top_to_bottom(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        import numpy as np
        img = generate_gradient([(0, 0, 0, 255), (255, 255, 255, 255)],
                                width=4, height=128, direction="vertical")
        arr = np.array(img)
        assert int(arr[0, 0, 0]) < int(arr[-1, 0, 0])

    def test_three_color_gradient(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        img = generate_gradient([(255, 0, 0), (0, 255, 0), (0, 0, 255)],
                                width=128, height=8)
        assert img.size == (128, 8)

    def test_too_few_colors_raises(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        with pytest.raises(ValueError):
            generate_gradient([(255, 0, 0)], width=64, height=64)

    def test_rgba_colors_accepted(self):
        from pharos_engine.tools.texture_tools import generate_gradient
        img = generate_gradient([(0, 0, 0, 128), (255, 255, 255, 200)], width=32, height=32)
        assert img is not None
