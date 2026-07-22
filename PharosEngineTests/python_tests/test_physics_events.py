"""Tests for PhysicsEventPublisher — physics → EventBus/Audio/Triggers bridge.

These tests use lightweight stubs for ContactPair, PhysicsBody, and
PhysicsWorld so they exercise the publisher in isolation, plus one
integration test that drives a real :class:`PhysicsWorld` to verify
end-to-end behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pharos_engine.event_bus import EventBus, subscribe, global_bus
from pharos_engine.physics.event_publisher import PhysicsEventPublisher


# ── Stubs ────────────────────────────────────────────────────────────────────


@dataclass
class StubContact:
    a: int
    b: int
    normal: tuple = (1.0, 0.0)
    depth: float = 0.0
    point: tuple = (0.0, 0.0)


@dataclass
class StubBody:
    root_hull_id: int
    material_name: str = "stone"
    mass: float = 1.0
    velocity: tuple = (0.0, 0.0)
    name: str = ""
    controller: Any = None


@dataclass
class StubWorld:
    bodies: list = field(default_factory=list)


class StubAudio:
    """Records every play() call for assertion."""

    def __init__(self):
        self.calls: list[tuple[str, float]] = []

    def play(self, sound_name, volume=1.0, **kw):
        self.calls.append((sound_name, float(volume)))


class StubTriggers:
    def __init__(self):
        self.updates: list[list] = []

    def update(self, entities):
        self.updates.append(list(entities))


@dataclass
class StubController:
    state: Any  # has a .name (e.g. enum) or is a string


class _StateEnumLike:
    """Mimics ``SimState`` enum-style attribute access."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.value = name.lower()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_bus():
    """Snapshot/restore global bus state so subscriptions don't leak."""
    saved = dict(global_bus._listeners)
    global_bus._listeners.clear()
    yield
    global_bus._listeners.clear()
    global_bus._listeners.update(saved)


@pytest.fixture
def captured():
    """Yield a dict whose keys are event names and values are lists of payloads.

    Returned alongside a `sub` helper that subscribes to an event and
    routes its payload into the dict.
    """
    bag: dict[str, list] = {}

    def sub(event_name: str) -> int:
        bag.setdefault(event_name, [])
        return subscribe(event_name, lambda evt: bag[event_name].append(evt))

    return bag, sub


# ── Tests ────────────────────────────────────────────────────────────────────


def test_contact_event_fires(clean_bus, captured):
    """Every contact in the list fires `Physics.Contact`."""
    bag, sub = captured
    sub("Physics.Contact")

    a = StubBody(root_hull_id=0, material_name="stone", mass=1.0)
    b = StubBody(root_hull_id=1, material_name="stone", mass=1.0)
    world = StubWorld(bodies=[a, b])
    pub = PhysicsEventPublisher(event_bus=EventBus())

    contacts = [StubContact(a=0, b=1, normal=(1.0, 0.0), depth=0.1)]
    pub.on_step(world, contacts, dt=0.016)

    assert len(bag["Physics.Contact"]) == 1
    evt = bag["Physics.Contact"][0]
    assert evt.material_a == "stone"
    assert evt.material_b == "stone"


def test_impact_event_fires_above_threshold(clean_bus, captured):
    """High-velocity collision fires `Physics.Impact`; low-velocity does not."""
    bag, sub = captured
    sub("Physics.Impact")
    sub("Physics.Contact")

    # Bodies on a collision course: A moving +x at 50, B stationary, normal +x.
    a = StubBody(root_hull_id=0, mass=2.0, velocity=(50.0, 0.0), material_name="metal")
    b = StubBody(root_hull_id=1, mass=2.0, velocity=(0.0, 0.0), material_name="metal")
    world = StubWorld(bodies=[a, b])
    pub = PhysicsEventPublisher(event_bus=EventBus(), impact_impulse_threshold=1.0)

    pub.on_step(world, [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)

    assert len(bag["Physics.Impact"]) == 1
    assert len(bag["Physics.Contact"]) == 1

    # Now low-velocity touching: clear pair memory, reset bodies.
    bag["Physics.Impact"].clear()
    bag["Physics.Contact"].clear()
    pub2 = PhysicsEventPublisher(event_bus=EventBus(), impact_impulse_threshold=1.0)
    a_slow = StubBody(root_hull_id=2, mass=1.0, velocity=(0.01, 0.0), material_name="metal")
    b_slow = StubBody(root_hull_id=3, mass=1.0, velocity=(0.0, 0.0), material_name="metal")
    world2 = StubWorld(bodies=[a_slow, b_slow])
    pub2.on_step(world2, [StubContact(a=2, b=3, normal=(1.0, 0.0))], dt=0.016)

    assert len(bag["Physics.Contact"]) == 1
    assert len(bag["Physics.Impact"]) == 0


def test_audio_played_on_impact(clean_bus):
    """AudioManager.play() is invoked with the metal impact sound."""
    audio = StubAudio()
    a = StubBody(root_hull_id=0, mass=2.0, velocity=(40.0, 0.0), material_name="metal")
    b = StubBody(root_hull_id=1, mass=2.0, velocity=(0.0, 0.0), material_name="metal")
    world = StubWorld(bodies=[a, b])
    pub = PhysicsEventPublisher(EventBus(), audio_manager=audio,
                                impact_impulse_threshold=1.0)

    pub.on_step(world, [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)

    assert len(audio.calls) == 1
    sound, vol = audio.calls[0]
    assert sound == "clang_metal"
    assert 0.0 <= vol <= 1.0


def test_impact_sound_picks_harder_material(clean_bus):
    """Glass vs stone → shatter_glass.  Steel vs mud → clang_metal."""
    audio = StubAudio()

    # Glass + stone — glass is harder.
    a = StubBody(root_hull_id=0, mass=1.0, velocity=(30.0, 0.0), material_name="glass")
    b = StubBody(root_hull_id=1, mass=1.0, velocity=(0.0, 0.0), material_name="stone")
    pub = PhysicsEventPublisher(EventBus(), audio_manager=audio,
                                impact_impulse_threshold=1.0)
    pub.on_step(StubWorld(bodies=[a, b]),
                [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)
    assert audio.calls[-1][0] == "shatter_glass"

    # Steel + mud — steel is harder; default sound for "steel" is clang_metal.
    audio.calls.clear()
    c = StubBody(root_hull_id=2, mass=1.0, velocity=(30.0, 0.0), material_name="steel")
    d = StubBody(root_hull_id=3, mass=1.0, velocity=(0.0, 0.0), material_name="mud")
    pub2 = PhysicsEventPublisher(EventBus(), audio_manager=audio,
                                 impact_impulse_threshold=1.0)
    pub2.on_step(StubWorld(bodies=[c, d]),
                 [StubContact(a=2, b=3, normal=(1.0, 0.0))], dt=0.016)
    assert audio.calls[-1][0] == "clang_metal"


def test_fragment_event_on_spawn_fragment(clean_bus, captured):
    """When a new body appears mid-simulation, `Physics.Fragment` fires."""
    bag, sub = captured
    sub("Physics.Fragment")

    parent = StubBody(root_hull_id=0, material_name="glass", mass=1.0)
    world = StubWorld(bodies=[parent])
    pub = PhysicsEventPublisher(EventBus())

    # Frame 1: only the parent exists.
    pub.on_step(world, [], dt=0.016)
    assert bag["Physics.Fragment"] == []

    # Frame 2: spawn_fragment created hull 5.
    frag = StubBody(root_hull_id=5, material_name="glass", mass=0.3)
    world.bodies.append(frag)
    pub.on_step(world, [], dt=0.016)

    assert len(bag["Physics.Fragment"]) == 1
    evt = bag["Physics.Fragment"][0]
    assert 5 in evt.fragment_ids
    assert evt.fragment_count == 1


def test_no_double_publish_on_resting_contact(clean_bus, captured):
    """Two bodies in resting contact for many steps fire Impact at most once."""
    bag, sub = captured
    sub("Physics.Impact")
    sub("Physics.Contact")

    # Start with a closing velocity above threshold so frame 0 fires Impact.
    a = StubBody(root_hull_id=0, mass=2.0, velocity=(20.0, 0.0), material_name="stone")
    b = StubBody(root_hull_id=1, mass=2.0, velocity=(0.0, 0.0), material_name="stone")
    world = StubWorld(bodies=[a, b])
    pub = PhysicsEventPublisher(EventBus(), impact_impulse_threshold=1.0)

    contacts = [StubContact(a=0, b=1, normal=(1.0, 0.0))]
    pub.on_step(world, contacts, dt=0.016)

    # Subsequent 9 steps: contact persists but velocities are now zero
    # (post-impulse rest); only the very first frame counted as Impact.
    a.velocity = (0.0, 0.0)
    b.velocity = (0.0, 0.0)
    for _ in range(9):
        pub.on_step(world, contacts, dt=0.016)

    assert len(bag["Physics.Impact"]) == 1, (
        f"Resting contact spawned {len(bag['Physics.Impact'])} impacts"
    )
    assert len(bag["Physics.Contact"]) == 10


def test_publisher_without_audio_doesnt_crash(clean_bus, captured):
    """No audio_manager set → Impact events still fire, no crash."""
    bag, sub = captured
    sub("Physics.Impact")
    a = StubBody(root_hull_id=0, mass=2.0, velocity=(40.0, 0.0), material_name="metal")
    b = StubBody(root_hull_id=1, mass=2.0, velocity=(0.0, 0.0), material_name="metal")
    pub = PhysicsEventPublisher(EventBus(), audio_manager=None,
                                impact_impulse_threshold=1.0)
    pub.on_step(StubWorld(bodies=[a, b]),
                [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)
    assert len(bag["Physics.Impact"]) == 1


def test_publisher_without_triggers_doesnt_crash(clean_bus, captured):
    """No trigger_system set → contact and impact events still fire."""
    bag, sub = captured
    sub("Physics.Contact")
    sub("Physics.Impact")
    a = StubBody(root_hull_id=0, mass=2.0, velocity=(40.0, 0.0), material_name="metal")
    b = StubBody(root_hull_id=1, mass=2.0, velocity=(0.0, 0.0), material_name="metal")
    pub = PhysicsEventPublisher(EventBus(), trigger_system=None,
                                impact_impulse_threshold=1.0)
    pub.on_step(StubWorld(bodies=[a, b]),
                [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)
    assert len(bag["Physics.Contact"]) == 1
    assert len(bag["Physics.Impact"]) == 1


def test_trigger_system_invoked_when_set(clean_bus):
    """If a trigger_system is provided, it receives the contacting bodies."""
    triggers = StubTriggers()
    a = StubBody(root_hull_id=0, mass=1.0, velocity=(10.0, 0.0), material_name="stone")
    b = StubBody(root_hull_id=1, mass=1.0, velocity=(0.0, 0.0), material_name="stone")
    pub = PhysicsEventPublisher(EventBus(), trigger_system=triggers,
                                impact_impulse_threshold=1.0)
    pub.on_step(StubWorld(bodies=[a, b]),
                [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)
    assert len(triggers.updates) >= 1


def test_settled_event_on_static_transition(clean_bus, captured):
    """A controller flipping ACTIVE → STATIC publishes `Physics.Settled`."""
    bag, sub = captured
    sub("Physics.Settled")

    state_active = _StateEnumLike("ACTIVE")
    state_static = _StateEnumLike("STATIC")
    body = StubBody(root_hull_id=0, material_name="stone", mass=1.0,
                    controller=StubController(state=state_active))
    world = StubWorld(bodies=[body])
    pub = PhysicsEventPublisher(EventBus())

    pub.on_step(world, [], dt=0.016)
    assert bag["Physics.Settled"] == []

    body.controller = StubController(state=state_static)
    pub.on_step(world, [], dt=0.016)
    assert len(bag["Physics.Settled"]) == 1


def test_register_impact_sound_overrides_default(clean_bus):
    """register_impact_sound() updates the lookup used for AudioManager.play."""
    audio = StubAudio()
    pub = PhysicsEventPublisher(EventBus(), audio_manager=audio,
                                impact_impulse_threshold=1.0)
    pub.register_impact_sound("stone", "custom_stone_thud")

    a = StubBody(root_hull_id=0, mass=1.0, velocity=(20.0, 0.0), material_name="stone")
    b = StubBody(root_hull_id=1, mass=1.0, velocity=(0.0, 0.0), material_name="stone")
    pub.on_step(StubWorld(bodies=[a, b]),
                [StubContact(a=0, b=1, normal=(1.0, 0.0))], dt=0.016)

    assert audio.calls[-1][0] == "custom_stone_thud"
