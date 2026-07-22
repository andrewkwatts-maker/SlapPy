"""Backcompat pinning: enforce that public collection-shaped attrs
remain iterable / assignable in the way downstream games use them.

Motivation
----------
Sibling to ``test_backcompat_downstream_shape.py`` (return-shape
tripwire).  Downstream games routinely walk engine-managed collections
via ``for x in obj.layers`` or ``for k, v in bus._listeners.items()``
and assign lists straight into set-typed attrs like ``entity.tags``.

Silently swapping any of these to a non-iterable / non-list-assignable
container would break hundreds of downstream sites while every
engine-side unit test still passes.

DO NOT delete these tests when the fix lands — they are the tripwire,
not a triage tool.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Entity.layers iteration
# ---------------------------------------------------------------------------

def test_entity_layers_iteration_works() -> None:
    """``for layer in entity.layers`` must iterate cleanly.  If
    ``layers`` ever gets swapped from ``list`` to a lazy generator /
    proxy this test trips.
    """
    from pharos_engine.layer import Layer
    from pharos_engine.render_target import RenderTarget

    rt = RenderTarget(name="iter_test", size=(32, 32))
    rt.add_layer(Layer(name="a"))
    rt.add_layer(Layer(name="b"))
    rt.add_layer(Layer(name="c"))

    names: list[str] = []
    for layer in rt.layers:
        names.append(layer.name)
    assert names == ["a", "b", "c"]

    # Iteration must be re-runnable (not consumed).
    names_second: list[str] = [layer.name for layer in rt.layers]
    assert names_second == ["a", "b", "c"]


def test_entity_layers_supports_index_access() -> None:
    """Downstream ``entity.layers[0]`` must keep working — index access
    is the second-most-common access pattern after iteration.
    """
    from pharos_engine.layer import Layer
    from pharos_engine.render_target import RenderTarget

    rt = RenderTarget(name="index_test", size=(32, 32))
    rt.add_layer(Layer(name="first"))
    rt.add_layer(Layer(name="second"))
    assert rt.layers[0].name == "first"
    assert rt.layers[1].name == "second"
    assert rt.layers[-1].name == "second"


# ---------------------------------------------------------------------------
# EventBus._listeners dict iteration
# ---------------------------------------------------------------------------

def test_event_bus_listeners_dict_items_iteration() -> None:
    """``for topic, listeners in bus._listeners.items()`` must work.
    Ochema Circuit's diagnostics dump walks the internal listener map
    (see ``docs/game_compat_2026_07_07.md``); if ``_listeners`` gets
    swapped from ``dict`` to a bespoke registry with no ``.items()``
    the game-compat harness breaks silently.
    """
    from pharos_engine.event_bus import EventBus

    bus = EventBus()

    def _listener_a(_payload):
        pass

    def _listener_b(_payload):
        pass

    bus.subscribe("topic.one", _listener_a)
    bus.subscribe("topic.two", _listener_b)

    topics: list[str] = []
    listener_counts: list[int] = []
    for topic, listeners in bus._listeners.items():
        topics.append(topic)
        listener_counts.append(len(listeners))

    assert set(topics) == {"topic.one", "topic.two"}
    assert all(count >= 1 for count in listener_counts)


def test_event_bus_listeners_dict_keys_iteration() -> None:
    """``for topic in bus._listeners`` (implicit keys iteration) must
    work.  Guards the ``.keys()`` / plain-iter contract.
    """
    from pharos_engine.event_bus import EventBus

    bus = EventBus()
    bus.subscribe("alpha", lambda _p: None)
    bus.subscribe("beta", lambda _p: None)

    seen: list[str] = []
    for topic in bus._listeners:
        seen.append(topic)
    assert set(seen) == {"alpha", "beta"}


def test_event_bus_listeners_dict_values_iteration() -> None:
    """``for listeners in bus._listeners.values()`` must work.  Guards
    the ``.values()`` contract Ochema's telemetry dashboard uses to
    count total live subscribers.
    """
    from pharos_engine.event_bus import EventBus

    bus = EventBus()
    bus.subscribe("x", lambda _p: None)
    bus.subscribe("y", lambda _p: None)
    bus.subscribe("y", lambda _p: None)  # 2nd on same topic

    total = 0
    for listeners in bus._listeners.values():
        total += len(listeners)
    assert total == 3


# ---------------------------------------------------------------------------
# Entity.tags list-assignment contract
# ---------------------------------------------------------------------------

def test_entity_tags_list_assignment() -> None:
    """``entity.tags = ["foo", "bar"]`` must work — downstream games
    (VehicleEntity, PlayerEntity) assign a plain list to ``tags`` in
    ``__init__`` before the engine coerces it to a set for its own
    lookups.  If the setter starts rejecting non-set values every
    subclass __init__ breaks.
    """
    from pharos_engine.entity import Entity

    entity = Entity(name="tag_test")

    # Assign a plain Python list (not a set).
    entity.tags = ["foo", "bar", "baz"]  # type: ignore[assignment]

    # After the assignment the value must remain iterable + membership-
    # queryable. Whether the engine coerces list -> set at that layer is
    # up to the setter's own contract; both shapes satisfy downstream.
    assert "foo" in entity.tags
    assert "bar" in entity.tags
    assert "baz" in entity.tags

    # Iteration must still work.
    seen = list(entity.tags)
    assert set(seen) == {"foo", "bar", "baz"}


def test_entity_tags_reassignment_replaces_previous() -> None:
    """``entity.tags = [...]`` must overwrite, not append. This is the
    Ochema Circuit vehicle-loadout reset contract."""
    from pharos_engine.entity import Entity

    entity = Entity(name="reassign_test")
    entity.tags = ["old_a", "old_b"]  # type: ignore[assignment]
    entity.tags = ["new_x", "new_y"]  # type: ignore[assignment]

    assert "old_a" not in entity.tags
    assert "old_b" not in entity.tags
    assert "new_x" in entity.tags
    assert "new_y" in entity.tags


def test_entity_tags_iteration_after_default_init() -> None:
    """A freshly constructed entity's ``.tags`` must be iterable even
    when empty — protects against a future refactor that lazy-inits
    ``tags`` to ``None`` and breaks ``for t in entity.tags`` sites.
    """
    from pharos_engine.entity import Entity

    entity = Entity(name="fresh")

    # Iteration on an empty tags must not raise (must not be None).
    seen: list[str] = []
    try:
        for tag in entity.tags:
            seen.append(tag)
    except TypeError as e:
        pytest.fail(
            f"entity.tags must be iterable when empty; got {type(e).__name__}: {e}"
        )
    assert seen == []


# ---------------------------------------------------------------------------
# Scene / list-shaped collections — spot-check
# ---------------------------------------------------------------------------

def test_scene_entities_iteration_if_available() -> None:
    """Guardrail: if ``Scene`` exposes an ``entities`` collection it
    must be iterable.  Skips cleanly on builds where Scene is absent.
    """
    scene_mod = pytest.importorskip("pharos_engine.scene")
    Scene = getattr(scene_mod, "Scene", None)
    if Scene is None:
        pytest.skip("Scene class not exported in this build")

    try:
        scene = Scene()
    except TypeError:
        pytest.skip("Scene requires positional args in this build")

    entities_attr = getattr(scene, "entities", None)
    if entities_attr is None:
        pytest.skip("Scene has no `entities` attr in this build")

    # Must be iterable.
    try:
        _ = list(entities_attr)
    except TypeError as e:
        pytest.fail(
            f"Scene.entities must be iterable; got {type(e).__name__}: {e}"
        )
