import numpy as np
import pytest

def test_circle_observer():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField(size=(200, 200), blend_radius=0.0, decay_rate=0.0)

    class FakeEntity:
        position = (100, 100)

    obs = VisibilityObserver(entity=FakeEntity(), range=40.0, mode="circle")
    vf.add_observer(obs)
    vf.update()

    # Centre should be fully visible
    assert vf.sample((100, 100)) == pytest.approx(1.0, abs=0.05)
    # Far point should be invisible
    assert vf.sample((0, 0)) == pytest.approx(0.0, abs=0.05)

def test_add_remove_observer():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((100, 100))
    class FakeEntity:
        position = (50, 50)
    h = vf.add_observer(VisibilityObserver(entity=FakeEntity()))
    assert len(vf._observers) == 1
    vf.remove_observer(h)
    assert len(vf._observers) == 0

def test_decay():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((100, 100), decay_rate=0.5, blend_radius=0.0)
    class FakeEntity:
        position = (50, 50)
    h = vf.add_observer(VisibilityObserver(entity=FakeEntity(), range=30.0, mode="circle"))
    vf.update()  # entity sees centre
    vf.remove_observer(h)
    before = vf.sample((50, 50))
    vf.update()  # no observers — should decay
    after = vf.sample((50, 50))
    assert after < before  # decayed

def test_overlap_mode_max():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((200, 200), overlap_mode="max", blend_radius=0.0)
    class E1:
        position = (50, 100)
    class E2:
        position = (150, 100)
    vf.add_observer(VisibilityObserver(entity=E1(), range=60.0))
    vf.add_observer(VisibilityObserver(entity=E2(), range=60.0))
    vf.update()
    # Both zones should be visible
    assert vf.sample((50, 100)) > 0.5
    assert vf.sample((150, 100)) > 0.5

def test_blend_radius_soft_edge():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((200, 200), blend_radius=30.0, decay_rate=0.0)
    class FakeEntity:
        position = (100, 100)
    vf.add_observer(VisibilityObserver(entity=FakeEntity(), range=50.0))
    vf.update()
    # At boundary of range, value should be < 1.0 (faded)
    boundary_sample = vf.sample((100, 150))  # 50px from centre = boundary
    inner_sample = vf.sample((100, 100))
    assert inner_sample > boundary_sample

def test_get_layer():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((64, 64))
    class FakeEntity:
        position = (32, 32)
    vf.add_observer(VisibilityObserver(entity=FakeEntity(), range=20.0))
    vf.update()
    layer = vf.get_layer()
    assert layer is not None
    assert layer._image_data is not None

def test_cone_observer():
    from slappyengine.visibility import VisibilityField, VisibilityObserver
    vf = VisibilityField((200, 200), blend_radius=0.0)
    class FakeEntity:
        position = (100, 100)
        rotation = 0.0  # facing right (0 degrees)
    obs = VisibilityObserver(entity=FakeEntity(), range=60.0,
                              mode="cone", cone_angle=90.0)
    vf.add_observer(obs)
    vf.update()
    # Should see ahead (right)
    assert vf.sample((140, 100)) > 0.0
    # Should NOT see behind
    assert vf.sample((60, 100)) == pytest.approx(0.0, abs=0.1)
