"""
Basic tests for core Python types — no GPU or Rust extension required.
"""
import math
import pytest

from pharos_engine.entity import Entity
from pharos_engine.render_target import RenderTarget
from pharos_engine.cube_array import CubeArray
from pharos_engine.layer import Layer
from pharos_engine.asset import Asset
from pharos_engine.scene import Scene
from pharos_engine.camera import Camera
from pharos_engine.tags import TagRegistry
from pharos_engine.material import ColorRange


# ---------------------------------------------------------------------------
# test_entity_creation
# ---------------------------------------------------------------------------

def test_entity_creation():
    e = Entity(name="hero")
    # id must be a non-empty uuid string
    assert isinstance(e.id, str)
    assert len(e.id) == 36   # standard uuid4 hyphenated length
    # default position
    assert e.position == (0.0, 0.0)
    assert e.name == "hero"


# ---------------------------------------------------------------------------
# test_render_target_layers
# ---------------------------------------------------------------------------

def test_render_target_layers():
    rt = RenderTarget(name="rt", size=(128, 128))
    assert rt.layers == []

    layer_a = Layer.blank(128, 128, name="A")
    layer_b = Layer.blank(128, 128, name="B")

    rt.add_layer(layer_a)
    rt.add_layer(layer_b)
    assert len(rt.layers) == 2
    assert layer_a in rt.layers
    assert layer_b in rt.layers

    rt.remove_layer(layer_a)
    assert len(rt.layers) == 1
    assert layer_a not in rt.layers
    assert layer_b in rt.layers


# ---------------------------------------------------------------------------
# test_cube_array_frame_advance
# ---------------------------------------------------------------------------

def test_cube_array_frame_advance():
    ca = CubeArray(name="anim")
    ca.frame_count = 8
    ca.fps = 8.0          # 1 frame per second
    ca.playing = True

    assert ca.current_frame == 0

    # Tick by 1 second → should advance 8 * 1.0 = 8 frames, wrapped to 0
    # (loop=True by default)  Actually that's 8 % 8 = 0, so tick 0.5 s instead
    ca.tick(0.5)          # 0.5 s × 8 fps = 4 frames
    assert ca.current_frame == 4

    ca.tick(0.5)          # another 0.5 s → frame 8 % 8 = 0 (looped)
    assert ca.current_frame == 0


# ---------------------------------------------------------------------------
# test_layer_from_blank
# ---------------------------------------------------------------------------

def test_layer_from_blank():
    layer = Layer.blank(64, 64, name="blank_layer")
    assert layer.name == "blank_layer"
    assert layer.size == (64, 64)
    # image data shape: (height, width, 4)
    assert layer._image_data is not None
    assert layer._image_data.shape == (64, 64, 4)
    # all pixels must be zero (transparent black)
    assert (layer._image_data == 0).all()


# ---------------------------------------------------------------------------
# test_asset_from_layers
# ---------------------------------------------------------------------------

def test_asset_from_layers():
    # Loading from a non-existent file should raise FileNotFoundError
    with pytest.raises(FileNotFoundError):
        Asset.from_image("/nonexistent/path/image.png")


# ---------------------------------------------------------------------------
# test_scene_add_remove
# ---------------------------------------------------------------------------

def test_scene_add_remove():
    scene = Scene(name="TestScene")
    entity = Entity(name="player")

    scene.add(entity)
    found = scene.find_by_name("player")
    assert len(found) == 1
    assert found[0] is entity

    # entity must be accessible via get()
    assert scene.get(entity.id) is entity

    scene.remove(entity)
    assert scene.find_by_name("player") == []
    assert scene.get(entity.id) is None


# ---------------------------------------------------------------------------
# test_camera_transforms
# ---------------------------------------------------------------------------

def test_camera_transforms():
    cam = Camera(position=(100.0, 50.0), zoom=2.0)
    cam._viewport_size = (800, 600)

    world_point = (150.0, 80.0)
    screen_point = cam.world_to_screen(world_point)

    # Round-trip: screen → world must recover the original world coords
    recovered = cam.screen_to_world(screen_point)
    assert math.isclose(recovered[0], world_point[0], abs_tol=1e-6)
    assert math.isclose(recovered[1], world_point[1], abs_tol=1e-6)

    # Camera centre must map to screen centre
    cx, cy = cam.position
    sx, sy = cam.world_to_screen((cx, cy))
    vw, vh = cam._viewport_size
    assert math.isclose(sx, vw / 2, abs_tol=1e-6)
    assert math.isclose(sy, vh / 2, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# test_tag_registry
# ---------------------------------------------------------------------------

def test_tag_registry():
    reg = TagRegistry()
    m_water = reg.define("water")
    m_soil = reg.define("soil")
    m_fire = reg.define("fire")

    # Each tag gets a unique power-of-two mask
    assert m_water != m_soil != m_fire
    assert m_water & m_soil == 0
    assert m_water & m_fire == 0

    # mask() for a single name matches define() return value
    assert reg.mask("water") == m_water

    # Multi-mask OR
    combined = reg.mask("water", "soil")
    assert combined == (m_water | m_soil)
    assert combined & m_water
    assert combined & m_soil
    assert not (combined & m_fire)

    # Membership test
    assert "water" in reg
    assert "unknown" not in reg


# ---------------------------------------------------------------------------
# test_color_range_match
# ---------------------------------------------------------------------------

def test_color_range_match():
    # Blue water: r 0-60, g 40-100, b 180-255
    water_range = ColorRange(r=(0, 60), g=(40, 100), b=(180, 255))

    # Matching pixel
    assert water_range.matches(30, 60, 220) is True

    # Out-of-range red channel
    assert water_range.matches(61, 60, 220) is False

    # Out-of-range green channel
    assert water_range.matches(30, 101, 220) is False

    # Out-of-range blue channel
    assert water_range.matches(30, 60, 179) is False

    # Boundary values (inclusive)
    assert water_range.matches(0, 40, 180) is True
    assert water_range.matches(60, 100, 255) is True
