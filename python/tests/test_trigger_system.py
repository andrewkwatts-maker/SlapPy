"""Engine tests for trigger.py — TriggerVolume, TriggerSystem, ReverbZone.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Ent:
    """Minimal entity-like object for TriggerSystem tests."""
    def __init__(self, x, y, w=8, h=8):
        self.position = (float(x), float(y))
        self.size = (float(w), float(h))


# ---------------------------------------------------------------------------
# TriggerVolume — construction
# ---------------------------------------------------------------------------

class TestTriggerVolumeInit:
    def test_instantiates(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v is not None

    def test_position_stored(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(100.0, 200.0), size=(50, 50))
        assert v.position == (100.0, 200.0)

    def test_size_stored(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(80.0, 40.0))
        assert v.size == (80.0, 40.0)

    def test_default_tag_empty(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v.tag == ""

    def test_custom_tag(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10), tag="boost")
        assert v.tag == "boost"

    def test_default_callbacks_none(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v.on_enter is None
        assert v.on_exit is None
        assert v.on_stay is None

    def test_default_pixel_precise_false(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v.pixel_precise is False

    def test_normal_default(self):
        from slappyengine.trigger import TriggerVolume
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        assert v.normal == (0.0, 1.0)


# ---------------------------------------------------------------------------
# TriggerSystem — volume management
# ---------------------------------------------------------------------------

class TestTriggerSystemManagement:
    def test_instantiates(self):
        from slappyengine.trigger import TriggerSystem
        sys = TriggerSystem()
        assert sys is not None

    def test_add_returns_volume(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        sys = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        result = sys.add(v)
        assert result is v

    def test_add_increments_count(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        sys = TriggerSystem()
        sys.add(TriggerVolume(position=(0, 0), size=(10, 10)))
        assert len(sys._volumes) == 1

    def test_remove_volume(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        sys = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        sys.add(v)
        sys.remove(v)
        assert len(sys._volumes) == 0

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        sys = TriggerSystem()
        v = TriggerVolume(position=(0, 0), size=(10, 10))
        sys.remove(v)  # should not raise

    def test_clear_removes_all(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        sys = TriggerSystem()
        sys.add(TriggerVolume(position=(0, 0), size=(10, 10)))
        sys.add(TriggerVolume(position=(100, 100), size=(10, 10)))
        sys.clear()
        assert len(sys._volumes) == 0


# ---------------------------------------------------------------------------
# TriggerSystem — on_enter / on_exit callbacks
# ---------------------------------------------------------------------------

class TestTriggerSystemCallbacks:
    def test_on_enter_fires_on_overlap(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        v = TriggerVolume(position=(50, 50), size=(40, 40),
                          on_enter=lambda e: entered.append(e))
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(50, 50, 8, 8)   # centre inside volume
        sys.update([entity])
        assert entity in entered

    def test_on_enter_fires_only_once(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        v = TriggerVolume(position=(50, 50), size=(40, 40),
                          on_enter=lambda e: entered.append(e))
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(50, 50, 8, 8)
        sys.update([entity])
        sys.update([entity])   # second frame — still inside
        assert len(entered) == 1

    def test_on_stay_fires_while_inside(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        stays = []
        v = TriggerVolume(position=(50, 50), size=(40, 40),
                          on_stay=lambda e: stays.append(e))
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(50, 50, 8, 8)
        sys.update([entity])   # frame 1: enter (no stay yet)
        sys.update([entity])   # frame 2: stay fires
        assert entity in stays

    def test_on_exit_fires_when_leaving(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        exited = []
        v = TriggerVolume(position=(50, 50), size=(40, 40),
                          on_exit=lambda e: exited.append(e))
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(50, 50, 8, 8)
        sys.update([entity])             # enter
        entity.position = (500, 500)     # move away
        sys.update([entity])             # exit
        assert entity in exited

    def test_no_fire_when_outside(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        v = TriggerVolume(position=(50, 50), size=(10, 10),
                          on_enter=lambda e: entered.append(e))
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(200, 200, 8, 8)   # far away
        sys.update([entity])
        assert entered == []

    def test_tag_fires_publish_event(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        from slappyengine.event_bus import subscribe, unsubscribe, global_bus
        global_bus.clear()
        received = []
        v = TriggerVolume(position=(50, 50), size=(40, 40), tag="cp_1")
        sys = TriggerSystem()
        sys.add(v)
        h = subscribe("Trigger.Enter.cp_1", lambda e: received.append(e))
        entity = _Ent(50, 50)
        sys.update([entity])
        unsubscribe(h)
        global_bus.clear()
        assert len(received) >= 1

    def test_entity_without_size_uses_default(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        entered = []
        v = TriggerVolume(position=(50, 50), size=(20, 20),
                          on_enter=lambda e: entered.append(e))
        sys = TriggerSystem()
        sys.add(v)

        class MinimalEnt:
            position = (50.0, 50.0)   # no size attribute

        sys.update([MinimalEnt()])
        assert len(entered) == 1

    def test_no_callbacks_no_crash(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        v = TriggerVolume(position=(50, 50), size=(40, 40))  # no callbacks
        sys = TriggerSystem()
        sys.add(v)
        entity = _Ent(50, 50)
        sys.update([entity])
        entity.position = (500, 500)
        sys.update([entity])  # exit without callback — should not raise


# ---------------------------------------------------------------------------
# TriggerSystem — multiple volumes
# ---------------------------------------------------------------------------

class TestTriggerSystemMultiVolume:
    def test_multiple_volumes_all_checked(self):
        from slappyengine.trigger import TriggerSystem, TriggerVolume
        a_entered = []
        b_entered = []
        va = TriggerVolume(position=(0, 0), size=(20, 20),
                           on_enter=lambda e: a_entered.append(e))
        vb = TriggerVolume(position=(100, 100), size=(20, 20),
                           on_enter=lambda e: b_entered.append(e))
        sys = TriggerSystem()
        sys.add(va)
        sys.add(vb)
        ea = _Ent(0, 0)
        eb = _Ent(100, 100)
        sys.update([ea, eb])
        assert ea in a_entered
        assert eb in b_entered


# ---------------------------------------------------------------------------
# ReverbZone
# ---------------------------------------------------------------------------

class TestReverbZone:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def teardown_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_instantiates(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(100, 50), tag="cave")
        assert rz is not None

    def test_reverb_amount_stored(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(100, 50), reverb_amount=0.7)
        assert rz.reverb_amount == pytest.approx(0.7)

    def test_reverb_decay_stored(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(100, 50), reverb_decay=1.5)
        assert rz.reverb_decay == pytest.approx(1.5)

    def test_is_trigger_volume_subclass(self):
        from slappyengine.trigger import ReverbZone, TriggerVolume
        assert issubclass(ReverbZone, TriggerVolume)

    def test_default_reverb_amount(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(100, 50))
        assert rz.reverb_amount == pytest.approx(0.4)

    def test_default_reverb_decay(self):
        from slappyengine.trigger import ReverbZone
        rz = ReverbZone(position=(0, 0), size=(100, 50))
        assert rz.reverb_decay == pytest.approx(0.8)
