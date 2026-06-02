"""Tests for TriggerSystem and TriggerVolume."""
import pytest


def test_trigger_enter_exit():
    from slappyengine.trigger import TriggerSystem, TriggerVolume

    entered, exited = [], []
    vol = TriggerVolume(
        position=(100, 100),
        size=(50, 50),
        on_enter=lambda e: entered.append(e),
        on_exit=lambda e: exited.append(e),
    )
    sys = TriggerSystem()
    sys.add(vol)

    class FakeEntity:
        position = (110, 110)
        size = (10, 10)

    e = FakeEntity()
    sys.update([e])
    assert len(entered) == 1, "Entity should have entered the trigger"

    sys.update([e])
    assert len(entered) == 1, "on_enter should not fire again on second frame"

    e.position = (500, 500)
    sys.update([e])
    assert len(exited) == 1, "Entity should have exited the trigger"


def test_trigger_stay():
    """on_stay is called each frame while entity remains inside."""
    from slappyengine.trigger import TriggerSystem, TriggerVolume

    stayed = []
    vol = TriggerVolume(
        position=(0, 0),
        size=(200, 200),
        on_stay=lambda e: stayed.append(e),
    )
    sys = TriggerSystem()
    sys.add(vol)

    class FakeEntity:
        position = (0, 0)
        size = (10, 10)

    e = FakeEntity()

    # First frame → enter (no stay yet)
    sys.update([e])
    assert len(stayed) == 0, "on_stay should not fire on the first (enter) frame"

    # Second frame → stay
    sys.update([e])
    assert len(stayed) == 1

    # Third frame → stay again
    sys.update([e])
    assert len(stayed) == 2


def test_trigger_no_double_enter_exit():
    """Enter and exit fire exactly once per crossing."""
    from slappyengine.trigger import TriggerSystem, TriggerVolume

    enters, exits = [], []
    vol = TriggerVolume(
        position=(0, 0),
        size=(50, 50),
        on_enter=lambda e: enters.append(1),
        on_exit=lambda e: exits.append(1),
    )
    sys = TriggerSystem()
    sys.add(vol)

    class Ent:
        position = (0, 0)
        size = (4, 4)

    e = Ent()
    sys.update([e])          # enter
    sys.update([e])          # stay
    e.position = (1000, 0)
    sys.update([e])          # exit
    e.position = (0, 0)
    sys.update([e])          # enter again
    sys.update([e])          # stay
    e.position = (1000, 0)
    sys.update([e])          # exit again

    assert len(enters) == 2
    assert len(exits) == 2


def test_trigger_add_remove():
    """Removing a volume stops its callbacks from firing."""
    from slappyengine.trigger import TriggerSystem, TriggerVolume

    fired = []
    vol = TriggerVolume(
        position=(0, 0),
        size=(100, 100),
        on_enter=lambda e: fired.append(1),
    )
    sys = TriggerSystem()
    sys.add(vol)

    class Ent:
        position = (0, 0)
        size = (4, 4)

    e = Ent()
    sys.update([e])
    assert len(fired) == 1

    sys.remove(vol)
    e.position = (1000, 0)   # leave
    e.position = (0, 0)      # re-enter (but vol is removed)
    sys.update([e])
    assert len(fired) == 1, "No new enter event after volume removed"


def test_trigger_aabb_boundary():
    """Entity exactly at the boundary edge should overlap (half-extent check)."""
    from slappyengine.trigger import TriggerSystem, TriggerVolume

    fired = []
    # Vol centred at (100,100), size 50×50 → extends from 75 to 125
    vol = TriggerVolume(
        position=(100, 100),
        size=(50, 50),
        on_enter=lambda e: fired.append(1),
    )
    sys = TriggerSystem()
    sys.add(vol)

    class Ent:
        size = (2, 2)   # half-extent = 1

    # Entity at 124 → distance from centre = 24, vhw+ehw = 25+1 = 26 → overlap
    e = Ent()
    e.position = (124, 100)
    sys.update([e])
    assert len(fired) == 1

    # Entity at 126 → distance = 26 ≥ 26 → no overlap
    fired.clear()
    e2 = Ent()
    e2.position = (126, 100)
    sys.update([e2])
    assert len(fired) == 0
