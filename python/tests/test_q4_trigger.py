"""Q4 Sprint — Audio ramp/fade-out and ReverbZone tests.

Feature 1: AudioManager.set_loop_volume() smooth ramp + stop_loop() fade-out
Feature 2: ReverbZone publishes Reverb.Enter / Reverb.Exit events via TriggerSystem
"""
from __future__ import annotations

import threading
import pytest

from slappyengine.audio import AudioManager, LoopHandle
from slappyengine.trigger import ReverbZone, TriggerSystem
from slappyengine.event_bus import (
    subscribe as bus_subscribe,
    unsubscribe as bus_unsubscribe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr_with_loop(volume: float = 1.0) -> tuple[AudioManager, int]:
    """Return an AudioManager that has a LoopHandle pre-registered (no real audio)."""
    mgr = AudioManager()
    lh = LoopHandle(loop_id=1, volume=volume, _target_volume=volume)
    mgr._loops[1] = lh
    return mgr, 1


def _make_entity(pos: tuple[float, float], size: tuple[float, float] = (8.0, 8.0)):
    """Minimal entity stub with position and size."""

    class _Entity:
        def __init__(self, position, size):
            self.position = position
            self.size = size

    return _Entity(list(pos), list(size))


# ---------------------------------------------------------------------------
# 1. set_loop_volume — instant (no ramp_time)
# ---------------------------------------------------------------------------

def test_set_loop_volume_instant():
    """set_loop_volume with default ramp_time=0.0 updates volume immediately."""
    mgr, loop_id = _make_mgr_with_loop(volume=1.0)

    mgr.set_loop_volume(loop_id, 0.5)

    lh = mgr._loops[loop_id]
    assert lh.volume == pytest.approx(0.5)
    assert lh._ramp_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 2. set_loop_volume — with ramp_time
# ---------------------------------------------------------------------------

def test_set_loop_volume_ramp():
    """set_loop_volume with ramp_time>0 sets _target_volume and a positive _ramp_rate."""
    mgr, loop_id = _make_mgr_with_loop(volume=1.0)

    mgr.set_loop_volume(loop_id, 0.5, ramp_time=2.0)

    lh = mgr._loops[loop_id]
    assert lh._target_volume == pytest.approx(0.5)
    assert lh._ramp_rate > 0.0


# ---------------------------------------------------------------------------
# 3. stop_loop — with fade_out (deferred stop)
# ---------------------------------------------------------------------------

def test_stop_loop_fade_out():
    """stop_loop with fade_out>0 sets _fade_out_secs and does NOT set the stop event."""
    mgr, loop_id = _make_mgr_with_loop(volume=1.0)
    # Keep a reference to lh before stop_loop removes it from _loops
    lh = mgr._loops[loop_id]

    mgr.stop_loop(loop_id, fade_out=1.0)

    assert lh._fade_out_secs > 0.0
    assert not lh._stop.is_set()


# ---------------------------------------------------------------------------
# 4. stop_loop — instant (no fade)
# ---------------------------------------------------------------------------

def test_stop_loop_instant():
    """stop_loop with fade_out=0.0 (default) immediately sets the stop event."""
    mgr, loop_id = _make_mgr_with_loop(volume=1.0)
    lh = mgr._loops[loop_id]

    mgr.stop_loop(loop_id, fade_out=0.0)

    assert lh._stop.is_set()


# ---------------------------------------------------------------------------
# 5. ReverbZone — publishes Reverb.Enter.<tag>
# ---------------------------------------------------------------------------

def test_reverb_zone_publishes_enter():
    """TriggerSystem.update() fires Reverb.Enter.<tag> when entity enters the zone."""
    zone = ReverbZone(
        position=(100.0, 100.0),
        size=(50.0, 50.0),
        tag="cave",
        reverb_amount=0.7,
        reverb_decay=1.2,
    )
    sys = TriggerSystem()
    sys.add(zone)

    received = []
    h = bus_subscribe("Reverb.Enter.cave", lambda evt: received.append(evt))

    try:
        # Entity positioned at the centre of the zone → inside
        entity = _make_entity(pos=(100.0, 100.0))
        sys.update([entity])

        assert len(received) == 1, "Expected exactly one Reverb.Enter.cave event"
        evt = received[0]
        assert evt.amount == pytest.approx(0.7)
        assert evt.decay == pytest.approx(1.2)
    finally:
        bus_unsubscribe(h)


# ---------------------------------------------------------------------------
# 6. ReverbZone — publishes Reverb.Exit.<tag>
# ---------------------------------------------------------------------------

def test_reverb_zone_publishes_exit():
    """TriggerSystem.update() fires Reverb.Exit.<tag> when entity leaves the zone."""
    zone = ReverbZone(
        position=(100.0, 100.0),
        size=(50.0, 50.0),
        tag="cave_exit",
        reverb_amount=0.5,
        reverb_decay=0.9,
    )
    sys = TriggerSystem()
    sys.add(zone)

    enter_calls = []
    exit_calls = []
    h_enter = bus_subscribe("Reverb.Enter.cave_exit", lambda evt: enter_calls.append(evt))
    h_exit  = bus_subscribe("Reverb.Exit.cave_exit",  lambda evt: exit_calls.append(evt))

    try:
        # Frame 1: entity inside the zone → enter fires
        entity = _make_entity(pos=(100.0, 100.0))
        sys.update([entity])
        assert len(enter_calls) == 1

        # Frame 2: entity moved far outside the zone → exit fires
        entity.position = [9999.0, 9999.0]
        sys.update([entity])
        assert len(exit_calls) == 1, "Expected exactly one Reverb.Exit.cave_exit event"
    finally:
        bus_unsubscribe(h_enter)
        bus_unsubscribe(h_exit)
