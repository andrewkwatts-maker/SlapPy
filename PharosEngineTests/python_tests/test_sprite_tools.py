"""Engine tests for sprite_tools, StructModule subclasses — headless."""
from __future__ import annotations
import tempfile
from pathlib import Path
import numpy as np
import pytest


def _make_test_png(path, width=64, height=64, color=(200, 100, 50, 255)):
    """Create a simple solid-color RGBA PNG for testing."""
    from PIL import Image
    img = Image.new("RGBA", (width, height), color)
    img.save(str(path))
    return str(path)


class TestGenerateRotationStrip:
    def test_creates_output_file(self, tmp_path):
        from pharos_engine.tools.sprite_tools import generate_rotation_strip
        src = tmp_path / "src.png"
        dst = tmp_path / "strip.png"
        _make_test_png(src)
        result = generate_rotation_strip(str(src), str(dst), frames=4, size=(32, 32))
        assert Path(result).exists()

    def test_strip_width_is_frames_times_frame_width(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import generate_rotation_strip
        src = tmp_path / "src.png"
        dst = tmp_path / "strip.png"
        _make_test_png(src, 32, 32)
        generate_rotation_strip(str(src), str(dst), frames=8, size=(32, 32))
        strip = Image.open(str(dst))
        assert strip.size[0] == 8 * 32
        assert strip.size[1] == 32

    def test_strip_all_frames_distinct(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import generate_rotation_strip
        import numpy as np
        src = tmp_path / "arrow.png"
        # Create an asymmetric image so rotations produce different results
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        d.rectangle([2, 2, 10, 30], fill=(255, 0, 0, 255))  # asymmetric shape
        img.save(str(src))
        dst = tmp_path / "strip.png"
        generate_rotation_strip(str(src), str(dst), frames=4, size=(32, 32))
        strip = Image.open(str(dst))
        arr = np.array(strip)
        # Extract first and third frame (0° and 180°) — they should differ
        f0 = arr[:, 0:32, :]
        f2 = arr[:, 64:96, :]
        assert not np.array_equal(f0, f2)

    def test_returns_absolute_path(self, tmp_path):
        from pharos_engine.tools.sprite_tools import generate_rotation_strip
        src = tmp_path / "src.png"
        dst = tmp_path / "strip.png"
        _make_test_png(src)
        result = generate_rotation_strip(str(src), str(dst), frames=2, size=(16, 16))
        assert Path(result).is_absolute()


class TestGenerateTiltSheet:
    def test_creates_correct_number_of_files(self, tmp_path):
        from pharos_engine.tools.sprite_tools import generate_tilt_sheet
        src = tmp_path / "car.png"
        _make_test_png(src)
        out_dir = tmp_path / "tilts"
        results = generate_tilt_sheet(str(src), str(out_dir), directions=4, size=(32, 32))
        assert len(results) == 4

    def test_all_output_files_exist(self, tmp_path):
        from pharos_engine.tools.sprite_tools import generate_tilt_sheet
        src = tmp_path / "car.png"
        _make_test_png(src)
        out_dir = tmp_path / "tilts"
        results = generate_tilt_sheet(str(src), str(out_dir), directions=4, size=(32, 32))
        for path in results:
            assert Path(path).exists(), f"Missing: {path}"

    def test_creates_output_dir(self, tmp_path):
        from pharos_engine.tools.sprite_tools import generate_tilt_sheet
        src = tmp_path / "car.png"
        _make_test_png(src)
        out_dir = tmp_path / "new_subdir" / "tilts"
        generate_tilt_sheet(str(src), str(out_dir), directions=2, size=(16, 16))
        assert out_dir.exists()

    def test_output_images_correct_size(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import generate_tilt_sheet
        src = tmp_path / "car.png"
        _make_test_png(src, 64, 64)
        out_dir = tmp_path / "tilts"
        results = generate_tilt_sheet(str(src), str(out_dir), directions=2, size=(48, 48))
        img = Image.open(results[0])
        assert img.size == (48, 48)


class TestRecolorSprite:
    def test_creates_output_file(self, tmp_path):
        from pharos_engine.tools.sprite_tools import recolor_sprite
        src = tmp_path / "src.png"
        dst = tmp_path / "recolored.png"
        _make_test_png(src, color=(200, 50, 50, 255))
        result = recolor_sprite(str(src), str(dst), hue_shift=120.0)
        assert Path(result).exists()

    def test_hue_shift_changes_pixels(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import recolor_sprite
        src = tmp_path / "src.png"
        dst = tmp_path / "out.png"
        # Use a saturated red so hue shift actually changes things
        _make_test_png(src, color=(255, 0, 0, 255))
        recolor_sprite(str(src), str(dst), hue_shift=120.0)
        orig = np.array(Image.open(str(src)))
        result = np.array(Image.open(str(dst)))
        # Some pixels should have changed
        assert not np.array_equal(orig[:, :, :3], result[:, :, :3])

    def test_alpha_preserved(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import recolor_sprite
        src = tmp_path / "src.png"
        dst = tmp_path / "out.png"
        _make_test_png(src, color=(200, 100, 50, 200))
        recolor_sprite(str(src), str(dst), hue_shift=90.0)
        result = np.array(Image.open(str(dst)))
        # Alpha channel should be preserved
        assert np.all(result[:, :, 3] == 200)

    def test_zero_hue_shift_minimal_change(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import recolor_sprite
        src = tmp_path / "src.png"
        dst = tmp_path / "out.png"
        _make_test_png(src, color=(200, 100, 50, 255))
        recolor_sprite(str(src), str(dst), hue_shift=0.0)
        orig = np.array(Image.open(str(src))).astype(int)
        result = np.array(Image.open(str(dst))).astype(int)
        # With 0 hue shift, difference should be very small (float rounding only)
        assert np.all(np.abs(orig - result) <= 2)

    def test_saturation_zero_produces_gray(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import recolor_sprite
        src = tmp_path / "src.png"
        dst = tmp_path / "out.png"
        _make_test_png(src, color=(200, 50, 50, 255))
        recolor_sprite(str(src), str(dst), hue_shift=0.0, saturation_scale=0.0)
        result = np.array(Image.open(str(dst)))
        # R, G, B should all be equal (grayscale)
        r, g, b = result[:, :, 0], result[:, :, 1], result[:, :, 2]
        assert np.allclose(r, g, atol=2)
        assert np.allclose(g, b, atol=2)


class TestExtractSpritesheet:
    def _make_sheet(self, path, rows, cols, cell_w=16, cell_h=16):
        """Create a grid spritesheet with each cell a different color."""
        from PIL import Image
        sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h), (0, 0, 0, 255))
        for r in range(rows):
            for c in range(cols):
                color = (r * 40 + 50, c * 40 + 50, 100, 255)
                for x in range(c * cell_w, (c + 1) * cell_w):
                    for y in range(r * cell_h, (r + 1) * cell_h):
                        sheet.putpixel((x, y), color)
        sheet.save(str(path))

    def test_correct_file_count(self, tmp_path):
        from pharos_engine.tools.sprite_tools import extract_spritesheet
        src = tmp_path / "sheet.png"
        self._make_sheet(src, rows=2, cols=3)
        results = extract_spritesheet(str(src), str(tmp_path / "out"), rows=2, cols=3)
        assert len(results) == 6

    def test_all_files_exist(self, tmp_path):
        from pharos_engine.tools.sprite_tools import extract_spritesheet
        src = tmp_path / "sheet.png"
        self._make_sheet(src, rows=2, cols=2)
        results = extract_spritesheet(str(src), str(tmp_path / "out"), rows=2, cols=2)
        for path in results:
            assert Path(path).exists()

    def test_named_outputs(self, tmp_path):
        from pharos_engine.tools.sprite_tools import extract_spritesheet
        src = tmp_path / "sheet.png"
        self._make_sheet(src, rows=1, cols=3)
        names = ["left", "center", "right"]
        results = extract_spritesheet(str(src), str(tmp_path / "out"), rows=1, cols=3, names=names)
        for result, name in zip(results, names):
            assert name in Path(result).name

    def test_default_naming(self, tmp_path):
        from pharos_engine.tools.sprite_tools import extract_spritesheet
        src = tmp_path / "sheet.png"
        self._make_sheet(src, rows=1, cols=2)
        results = extract_spritesheet(str(src), str(tmp_path / "out"), rows=1, cols=2)
        # Default names: sheet_r0_c0.png, sheet_r0_c1.png
        assert "r0_c0" in Path(results[0]).name
        assert "r0_c1" in Path(results[1]).name

    def test_cell_size_correct(self, tmp_path):
        from PIL import Image
        from pharos_engine.tools.sprite_tools import extract_spritesheet
        src = tmp_path / "sheet.png"
        self._make_sheet(src, rows=2, cols=3, cell_w=16, cell_h=16)
        results = extract_spritesheet(str(src), str(tmp_path / "out"), rows=2, cols=3)
        img = Image.open(results[0])
        assert img.size == (16, 16)


class TestStructModules:
    """Test that StructModule subclasses have correct channels."""

    def test_fluid_params_has_channels(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert len(FluidParamsModule.channels) > 0
        channel_names = [c[0] for c in FluidParamsModule.channels]
        assert "viscosity" in channel_names
        assert "pressure" in channel_names

    def test_fluid_params_has_defaults(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert "viscosity" in FluidParamsModule.default_values

    def test_physics_module_has_channels(self):
        from pharos_engine.modules.physics import PhysicsModule
        channel_names = [c[0] for c in PhysicsModule.channels]
        assert "vel_x" in channel_names
        assert "vel_y" in channel_names
        assert "density" in channel_names

    def test_physics_module_default_values(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert PhysicsModule.default_values["vel_x"] == pytest.approx(0.0)
        assert PhysicsModule.default_values["density"] == pytest.approx(1.0)

    def test_pixel_physics_module(self):
        from pharos_engine.modules.pixel_physics import PixelPhysicsModule
        assert hasattr(PixelPhysicsModule, "channels")
        assert len(PixelPhysicsModule.channels) > 0

    def test_health_module_channels(self):
        from pharos_engine.modules.health import HealthModule
        channel_names = [c[0] for c in HealthModule.channels]
        assert "health" in channel_names
        assert "max_health" in channel_names

    def test_modules_register_cleanly(self):
        from pharos_engine.struct_registry import StructRegistry
        from pharos_engine.modules.fluid_params import FluidParamsModule
        from pharos_engine.modules.physics import PhysicsModule
        reg = StructRegistry()
        reg.register(FluidParamsModule)
        reg.register(PhysicsModule)
        channel_names = [c[0] for c in reg.channels]
        assert "viscosity" in channel_names
        assert "vel_x" in channel_names

    def test_fluid_params_compute_passes(self):
        from pharos_engine.modules.fluid_params import FluidParamsModule
        assert "fluid" in FluidParamsModule.compute_passes

    def test_physics_module_compute_passes(self):
        from pharos_engine.modules.physics import PhysicsModule
        assert "rigid" in PhysicsModule.compute_passes
