"""Backcompat pinning: exercise the "subclass abuse" patterns downstream
games actually use, so we catch MRO / init-order regressions.

Motivation
----------
TT1's game-compat re-run (2026-07-07) uncovered a silent breaking
change to ``RenderTarget.__init__`` lifecycle: downstream games
(Ochema Circuit's ``VehicleEntity``, Bullet Strata's ``PlayerEntity``)
call ``add_layer`` inside their own ``__init__`` BEFORE
``super().__init__()`` has established the ``layers`` field. When the
engine reorders where ``self.layers = []`` gets created, every
downstream subclass crashes.

Engine-side tests don't exercise this pattern (nothing engine-side
subclasses ``RenderTarget`` this way), which is why the F1 → TT6 delta
went silent for ~5 weeks.

This module tests the exact "subclass abuse" patterns downstream games
use so future regressions trip immediately.

DO NOT delete these tests when the fix lands — they are the tripwire,
not a triage tool.
"""
from __future__ import annotations

import pytest

from slappyengine.asset import Asset
from slappyengine.entity import Entity
from slappyengine.layer import Layer
from slappyengine.render_target import RenderTarget


# ---------------------------------------------------------------------------
# RenderTarget subclass abuse
# ---------------------------------------------------------------------------

def test_render_target_subclass_add_layer_after_super_init() -> None:
    """Baseline: the well-behaved pattern must work."""

    class WellBehaved(RenderTarget):
        def __init__(self) -> None:
            super().__init__(name="wb", size=(32, 32))
            self.add_layer(Layer(name="wb_layer"))

    inst = WellBehaved()
    assert len(inst.layers) == 1
    assert inst.layers[0].name == "wb_layer"


def test_render_target_subclass_add_layer_before_super_init() -> None:
    """The failing pattern TT1 caught: ``add_layer`` called BEFORE
    ``super().__init__()``. Downstream ``VehicleEntity`` /
    ``PlayerEntity`` do this. Must not crash with
    ``AttributeError: 'Foo' object has no attribute 'layers'``.

    Strategy: if the engine-side fix is present the call succeeds; if
    the engine still has the F1 → TT6 regression the call raises
    ``AttributeError``. We ``xfail`` on the exact regression signal so
    the test suite reports the state honestly without being permanently
    red on a known-open UU1/UU2 sprint.
    """

    class MisbehavedRT(RenderTarget):
        def __init__(self) -> None:
            try:
                self.add_layer(Layer(name="early"))
            except AttributeError as e:
                pytest.xfail(
                    f"Known regression (TT1 game-compat): {e}. Owner "
                    "sprints UU1/UU2. Once fixed this xfail flips to "
                    "xpass — remove the xfail wrapper here."
                )
            super().__init__(name="mis", size=(32, 32))

    inst = MisbehavedRT()
    # If we make it here the engine now tolerates the pattern.
    assert hasattr(inst, "layers"), "layers must exist post-super()"
    assert isinstance(inst.layers, list)


def test_render_target_subclass_no_super_call() -> None:
    """Extreme case: a subclass that never calls ``super().__init__()``
    at all. ``RenderTarget.add_layer`` currently defends against this by
    materialising ``self.layers`` on first touch (see the "Defensive"
    comment in ``render_target.py``). Locking that behaviour prevents a
    future "clean-up" pass from removing the defensive branch and
    re-introducing the TT1-class regression.
    """

    class NoSuperRT(RenderTarget):
        def __init__(self) -> None:
            # deliberately no super().__init__()
            pass

    inst = NoSuperRT()
    # Defensive path: add_layer must not crash even when __init__ was
    # skipped entirely. If this test starts failing, the defensive
    # ``if not hasattr(self, 'layers')`` branch in
    # ``render_target.py::RenderTarget.add_layer`` was probably removed.
    inst.add_layer(Layer(name="lazy_init"))
    assert hasattr(inst, "layers")
    assert len(inst.layers) == 1


# ---------------------------------------------------------------------------
# Asset subclass abuse
# ---------------------------------------------------------------------------

def test_asset_subclass_standard() -> None:
    """Standard pattern: subclass Asset, call super, add a layer."""

    class MyAsset(Asset):
        def __init__(self) -> None:
            super().__init__(name="ma", size=(64, 64))
            self.custom = True
            self.add_layer(Layer(name="ma_layer"))

    inst = MyAsset()
    assert inst.custom is True
    assert len(inst.layers) == 1


def test_asset_subclass_overrides_add_layer() -> None:
    """Games commonly override ``add_layer`` to intercept every layer
    add (e.g. to auto-tag layers by material). Must still route through
    ``super().add_layer`` cleanly."""

    class TaggingAsset(Asset):
        def __init__(self) -> None:
            super().__init__(name="ta", size=(64, 64))
            self.tagged_layers: list[str] = []

        def add_layer(self, layer):  # type: ignore[override]
            self.tagged_layers.append(layer.name or "unnamed")
            return super().add_layer(layer)

    inst = TaggingAsset()
    inst.add_layer(Layer(name="alpha"))
    inst.add_layer(Layer(name="beta"))
    assert inst.tagged_layers == ["alpha", "beta"]
    assert len(inst.layers) == 2


def test_asset_subclass_lazy_super_init() -> None:
    """Deferred ``super().__init__()`` — a subclass sets attributes first,
    then calls super. This is the exact anti-pattern from the TT1 report.
    Documented via ``xfail`` if the underlying regression is still live."""

    class LazySuperAsset(Asset):
        def __init__(self) -> None:
            self.custom_pre = "set-before-super"
            try:
                # Some games try to reach add_layer early.
                self.add_layer(Layer(name="early_asset_layer"))
            except AttributeError as e:
                pytest.xfail(
                    f"Known regression (TT1 game-compat): {e}. Owner "
                    "sprints UU1/UU2."
                )
            super().__init__(name="lazy", size=(64, 64))

    inst = LazySuperAsset()
    assert inst.custom_pre == "set-before-super"


# ---------------------------------------------------------------------------
# Entity subclass abuse
# ---------------------------------------------------------------------------

def test_entity_subclass_override_init_calls_super_first() -> None:
    """Standard subclass ordering: super().__init__() first."""

    class Actor(Entity):
        def __init__(self, hp: int = 100) -> None:
            super().__init__(name="actor")
            self.hp = hp

    a = Actor(hp=50)
    assert a.name == "actor"
    assert a.hp == 50
    assert isinstance(a.tags, set)


def test_entity_subclass_override_init_calls_super_last() -> None:
    """Some games set their own state before delegating to Entity's
    ``__init__``. Must not raise.
    """

    class LateSuperActor(Entity):
        def __init__(self) -> None:
            self.pre_super = "ok"
            super().__init__(name="late")
            self.post_super = "ok"

    a = LateSuperActor()
    assert a.pre_super == "ok"
    assert a.post_super == "ok"
    assert a.name == "late"


def test_entity_subclass_extra_positional_kwargs() -> None:
    """Ochema-style pattern: subclass takes extra kwargs and forwards
    ``name`` / ``position`` to super. Signature must remain compatible.
    """

    class Weapon(Entity):
        def __init__(
            self,
            damage: int,
            name: str = "weapon",
            position: tuple[float, float] = (0.0, 0.0),
        ) -> None:
            super().__init__(name=name, position=position)
            self.damage = damage

    w = Weapon(damage=25, name="rifle", position=(3.0, 4.0))
    assert w.damage == 25
    assert w.name == "rifle"
    assert w.position == (3.0, 4.0)


def test_entity_subclass_ticks_scripts_after_reinit() -> None:
    """A subclass that adds its own scripts must have them fire under
    ``tick(dt)`` — same contract as the base class."""

    class ScriptedActor(Entity):
        def __init__(self) -> None:
            super().__init__(name="scripted")
            self.tick_count = 0

            class _Script:
                def on_tick(inner_self, ent, dt):  # noqa: N805
                    ent.tick_count += 1

            self.attach_script(_Script())

    a = ScriptedActor()
    a.tick(0.016)
    a.tick(0.016)
    assert a.tick_count == 2
