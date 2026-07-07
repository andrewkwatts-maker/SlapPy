"""Regression tests for Observable kwarg-swallow shim (ZZ1, 2026-07).

Guards against `TypeError: Observable.__init__() got an unexpected keyword
argument 'name'` reported by YY3 as the top surviving game-compat failure
fingerprint (7 Ochema sites + all 4 Bullet Strata residuals).

Downstream games (Ochema Circuit, Bullet Strata) subclass Observable like:

    class VehicleEntity(Observable, Asset):
        def __init__(self, ...):
            super().__init__(name="v", position=(0, 0), size=(64, 32))

The old signature only accepted ``bus``/``topic``, so Observable rejected
every game kwarg with a TypeError. The shim widens the signature to
accept arbitrary kwargs, forwards them down the MRO, and stashes them as
attributes if the peer chain refuses.
"""
from __future__ import annotations

import pytest

from slappyengine.event_bus import EventBus, Observable


class TestObservableBackcompat:
    """Direct-construction shim tests."""

    def test_bare_observable_no_kwargs(self) -> None:
        """No-arg construction still works (existing behaviour preserved)."""
        obs = Observable()
        assert obs._observable_topic == "changed"
        assert isinstance(obs._bus, EventBus)

    def test_observable_accepts_name_kwarg(self) -> None:
        """The #1 game-compat failure: Observable(name="test") must not raise."""
        obs = Observable(name="test")
        assert obs.name == "test"

    def test_observable_accepts_id_kwarg(self) -> None:
        """Alternate game kwarg — id — should also be stashed."""
        obs = Observable(id=42)
        assert obs.id == 42

    def test_observable_accepts_multiple_arbitrary_kwargs(self) -> None:
        """Multiple game-supplied kwargs all become attributes."""
        obs = Observable(name="a", id=42, tags=["x", "y"], label="lbl")
        assert obs.name == "a"
        assert obs.id == 42
        assert obs.tags == ["x", "y"]
        assert obs.label == "lbl"

    def test_bus_and_topic_still_reserved(self) -> None:
        """bus/topic are still first-class kwargs, not stashed as attrs."""
        bus = EventBus()
        obs = Observable(bus=bus, topic="dirty")
        assert obs._bus is bus
        assert obs._observable_topic == "dirty"

    def test_bus_topic_mixed_with_game_kwargs(self) -> None:
        """Reserved kwargs coexist with arbitrary game kwargs."""
        bus = EventBus()
        obs = Observable(bus=bus, topic="dirty", name="mixed", size=(10, 20))
        assert obs._bus is bus
        assert obs._observable_topic == "dirty"
        assert obs.name == "mixed"
        assert obs.size == (10, 20)

    def test_notify_still_publishes_after_kwarg_shim(self) -> None:
        """notify() must still fire even when constructed with game kwargs."""
        received: list = []
        obs = Observable(name="pub")
        obs.subscribe(lambda evt: received.append(evt))
        obs.notify(value=7)
        assert len(received) == 1
        assert received[0]["value"] == 7


class TestObservableSubclass:
    """Verify subclass propagation still works."""

    def test_subclass_name_kwarg_propagates(self) -> None:
        """A subclass calling super().__init__(name=...) is not broken."""

        class Sub(Observable):
            pass

        s = Sub(name="s")
        assert s.name == "s"

    def test_subclass_explicit_bus_and_game_kwargs(self) -> None:
        """Subclass can mix explicit bus with game-supplied kwargs."""

        class Sub(Observable):
            def __init__(self) -> None:
                super().__init__(bus=EventBus(), name="explicit", position=(1, 2))

        s = Sub()
        assert s.name == "explicit"
        assert s.position == (1, 2)


class TestObservableMROCooperation:
    """MRO chain still cooperates so peer __init__ runs.

    The critical case per project memory: mixing Observable into an
    Asset/RenderTarget subclass must not short-circuit the MRO and skip
    ``RenderTarget.__init__`` (which sets ``self.layers``).
    """

    def test_mro_with_asset_peer_still_runs_render_target_init(self) -> None:
        """(Observable, Asset) MRO — Asset.__init__ must still run."""
        from slappyengine.asset import Asset

        class VehicleLike(Observable, Asset):
            def __init__(self) -> None:
                super().__init__(name="vehicle", position=(0.0, 0.0), size=(64, 32))

        v = VehicleLike()
        # RenderTarget.__init__ ran → self.layers exists
        assert hasattr(v, "layers")
        assert v.layers == []
        # Asset accepted the kwargs and populated its state
        assert v.size == (64, 32)
        # Observable-owned state also populated
        assert isinstance(v._bus, EventBus)

    def test_mro_object_terminus_no_error(self) -> None:
        """Standalone Observable(...) — super resolves to object — is fine."""
        obs = Observable(name="standalone")
        # object.__init__() was called on the empty chain (no TypeError)
        assert obs.name == "standalone"


class TestObservableValidationPreserved:
    """Existing validation on bus/topic kwargs must still fire."""

    def test_invalid_bus_type_still_raises(self) -> None:
        with pytest.raises(TypeError):
            Observable(bus="not-a-bus")  # type: ignore[arg-type]

    def test_empty_topic_still_raises(self) -> None:
        with pytest.raises(ValueError):
            Observable(topic="")
