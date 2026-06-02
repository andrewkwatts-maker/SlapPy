"""Comprehensive per-layer lighting isolation tests.

Proves that two layers can have completely independent lighting with no
bleed-through. All tests are pure Python — no GPU, no wgpu required.
"""
import pytest


# ---------------------------------------------------------------------------
# Helper imports (re-used across tests)
# ---------------------------------------------------------------------------

def _imports():
    from slappyengine.layer import Layer
    from slappyengine.lighting import (
        LightingContext, DirectionalLight, PointLight, ConeLight,
    )
    return Layer, LightingContext, DirectionalLight, PointLight, ConeLight


# ---------------------------------------------------------------------------
# a) Warm vs cool lighting on two separate layers
# ---------------------------------------------------------------------------

def test_warm_vs_cool_lighting():
    """Background layer gets warm amber lighting; foreground gets cool blue.
    The two LightingContext objects must be fully independent.
    """
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    # Warm amber ambient + directional
    bg = Layer.blank(64, 64, name="bg")
    bg.lighting = LightingContext(
        ambient_color=(1.0, 0.6, 0.1),
        ambient_intensity=0.3,
        mode="local",
    )
    bg.lighting.add_light(
        DirectionalLight(direction=(0.707, 0.707), color=(1.0, 0.8, 0.3), intensity=1.2)
    )

    # Cool blue ambient + point
    fg = Layer.blank(64, 64, name="fg")
    fg.lighting = LightingContext(
        ambient_color=(0.1, 0.2, 1.0),
        ambient_intensity=0.5,
        mode="local",
    )
    fg.lighting.add_light(
        PointLight(position=(32.0, 32.0), color=(0.2, 0.4, 1.0), intensity=2.0)
    )

    # Ambient colours must differ
    assert bg.lighting.ambient_color != fg.lighting.ambient_color

    # Each layer owns its own lights list
    assert bg.lighting.lights is not fg.lighting.lights

    # Mutating bg lights must not affect fg lights
    extra = DirectionalLight(direction=(0.0, 1.0))
    bg.lighting.add_light(extra)
    assert extra not in fg.lighting.lights

    # Mode defaults to "local"
    assert bg.lighting.mode == "local"
    assert fg.lighting.mode == "local"

    # Contexts are distinct objects
    assert bg.lighting is not fg.lighting


# ---------------------------------------------------------------------------
# b) add_light / remove_light / clear_lights lifecycle
# ---------------------------------------------------------------------------

def test_add_remove_lights():
    """Adding, removing, and clearing lights on a single LightingContext."""
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    layer = Layer.blank(32, 32, name="lifecycle")
    layer.lighting = LightingContext()

    p1 = PointLight(position=(10.0, 10.0))
    p2 = PointLight(position=(20.0, 20.0))
    p3 = PointLight(position=(30.0, 30.0))

    layer.lighting.add_light(p1)
    layer.lighting.add_light(p2)
    layer.lighting.add_light(p3)
    assert len(layer.lighting.lights) == 3

    layer.lighting.remove_light(p2)
    assert len(layer.lighting.lights) == 2
    assert p2 not in layer.lighting.lights
    assert p1 in layer.lighting.lights
    assert p3 in layer.lighting.lights

    layer.lighting.clear_lights()
    assert len(layer.lighting.lights) == 0


# ---------------------------------------------------------------------------
# c) lighting=None means the layer defers to scene-global lighting
# ---------------------------------------------------------------------------

def test_lighting_none_means_scene_global():
    """Layer.blank() starts with lighting=None. Assigning and removing a
    LightingContext must work without error, and None is accepted back.
    """
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    layer = Layer.blank(64, 64, name="global_inherit")

    # Default: no per-layer override
    assert layer.lighting is None

    # Assign a context
    ctx = LightingContext(ambient_color=(0.5, 0.5, 0.5))
    layer.lighting = ctx
    assert layer.lighting is ctx

    # Remove it again — layer reverts to scene-global behaviour
    layer.lighting = None
    assert layer.lighting is None


# ---------------------------------------------------------------------------
# d) mode="cross" is stored correctly
# ---------------------------------------------------------------------------

def test_cross_mode_flag():
    """LightingContext created with mode='cross' must report that mode back."""
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    ctx = LightingContext(mode="cross")
    assert ctx.mode == "cross"

    # Also sanity-check the other accepted modes
    for mode in ("none", "global", "local", "cross"):
        c = LightingContext(mode=mode)
        assert c.mode == mode


# ---------------------------------------------------------------------------
# e) Multiple light types coexist in a single context
# ---------------------------------------------------------------------------

def test_light_types_in_context():
    """DirectionalLight, PointLight, and ConeLight can all live in the same
    LightingContext and be individually accessible.
    """
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    layer = Layer.blank(64, 64, name="mixed_lights")
    layer.lighting = LightingContext()

    dl = DirectionalLight(direction=(1.0, 0.0), intensity=0.8)
    pl = PointLight(position=(50.0, 50.0), radius=150.0)
    cl = ConeLight(position=(0.0, 0.0), direction=(0.0, 1.0), half_angle=0.4)

    layer.lighting.add_light(dl)
    layer.lighting.add_light(pl)
    layer.lighting.add_light(cl)

    assert len(layer.lighting.lights) == 3
    assert dl in layer.lighting.lights
    assert pl in layer.lighting.lights
    assert cl in layer.lighting.lights

    # Each light retains its type identity
    assert isinstance(layer.lighting.lights[0], DirectionalLight)
    assert isinstance(layer.lighting.lights[1], PointLight)
    assert isinstance(layer.lighting.lights[2], ConeLight)


# ---------------------------------------------------------------------------
# f) Same-position lights on two layers are truly independent objects
# ---------------------------------------------------------------------------

def test_two_layers_same_light_position():
    """Two layers each hold a PointLight at the same position but different
    colours. Mutating layer 1's light must have zero effect on layer 2's light.
    """
    Layer, LightingContext, DirectionalLight, PointLight, ConeLight = _imports()

    layer1 = Layer.blank(64, 64, name="layer1")
    layer2 = Layer.blank(64, 64, name="layer2")

    layer1.lighting = LightingContext()
    layer2.lighting = LightingContext()

    RED   = (1.0, 0.0, 0.0)
    BLUE  = (0.0, 0.0, 1.0)
    GREEN = (0.0, 1.0, 0.0)

    light1 = PointLight(position=(100.0, 200.0), color=RED)
    light2 = PointLight(position=(100.0, 200.0), color=BLUE)

    layer1.lighting.add_light(light1)
    layer2.lighting.add_light(light2)

    # Confirm initial state
    assert layer1.lighting.lights[0].color == RED
    assert layer2.lighting.lights[0].color == BLUE

    # Mutate layer 1's light colour
    light1.color = GREEN
    layer1.lighting.lights[0].color = GREEN

    # Layer 2's light must be unaffected
    assert layer2.lighting.lights[0].color == BLUE, (
        "Changing layer1's light colour bled through to layer2"
    )

    # The two lights are separate objects
    assert layer1.lighting.lights[0] is not layer2.lighting.lights[0]

    # The two LightingContexts are separate objects
    assert layer1.lighting is not layer2.lighting

    # Removing from layer1 leaves layer2 intact
    layer1.lighting.clear_lights()
    assert len(layer1.lighting.lights) == 0
    assert len(layer2.lighting.lights) == 1
