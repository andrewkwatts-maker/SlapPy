def test_lighting_mode_default():
    from slappyengine.layer import Layer3D
    layer = Layer3D("test")
    assert layer.lighting_mode == "unlit"

def test_lighting_mode_set():
    from slappyengine.layer import Layer3D
    layer = Layer3D("test")
    layer.lighting_mode = "self_3d"
    assert layer.lighting_mode == "self_3d"
    layer.lighting_mode = "defer_2d"
    assert layer.lighting_mode == "defer_2d"

def test_gbuffer_target_sets_mode():
    from slappyengine.layer import Layer2D, Layer3D
    layer3d = Layer3D("test")
    lighting_layer = Layer2D.blank(64, 64, "lighting")
    layer3d.gbuffer_target = lighting_layer
    assert layer3d.lighting_mode == "defer_2d"
    assert layer3d.gbuffer_target is lighting_layer

def test_gbuffer_target_none_keeps_mode():
    from slappyengine.layer import Layer3D
    layer = Layer3D("test")
    layer.lighting_mode = "self_3d"
    layer.gbuffer_target = None
    assert layer.lighting_mode == "self_3d"  # not changed
