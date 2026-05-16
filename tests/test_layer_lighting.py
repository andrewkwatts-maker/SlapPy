"""Tests for per-layer LightingContext independence."""


def test_layer_lighting_independent():
    from playslap.layer import Layer
    from playslap.lighting import LightingContext, DirectionalLight

    layer_a = Layer.blank(64, 64, name="A")
    layer_b = Layer.blank(64, 64, name="B")

    layer_a.lighting = LightingContext(ambient_color=(1.0, 0.5, 0.0))
    layer_b.lighting = LightingContext(ambient_color=(0.0, 0.0, 1.0))
    layer_a.lighting.add_light(DirectionalLight(direction=(1, 0)))

    assert layer_a.lighting.mode == "local"
    assert layer_b.lighting.ambient_color == (0.0, 0.0, 1.0)
    assert len(layer_a.lighting.lights) == 1
    assert len(layer_b.lighting.lights) == 0
    assert layer_a.lighting is not layer_b.lighting  # independent
    print("Layer lighting independence: OK")


def test_layer_lighting_none_inherits_scene():
    from playslap.layer import Layer

    layer = Layer.blank(64, 64, name="C")
    assert layer.lighting is None  # defaults to scene-global
