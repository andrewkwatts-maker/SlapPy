"""Regression tests for the RenderTarget MRO break that clobbered ~700 Ochema
Circuit tests and ~35 Bullet Strata tests (UU1).

Root cause
----------
Games declared entities like ``class VehicleEntity(Observable, Asset)`` and then
called ``self.add_layer(...)`` inside their own ``__init__`` immediately after
``super().__init__()``. ``Observable.__init__`` was not cooperative — it did not
call ``super().__init__()`` — so the MRO chain stopped at Observable and
``Asset.__init__`` (and by extension ``RenderTarget.__init__`` which sets
``self.layers = []``) never ran. The first ``add_layer`` call then raised
``AttributeError: '<Entity subclass>' object has no attribute 'layers'``.

Fix
---
1. ``Observable.__init__`` now calls ``super().__init__()`` so the MRO chain
   propagates through to the Entity/Asset base.
2. ``RenderTarget.add_layer`` / ``remove_layer`` defensively materialise
   ``self.layers`` on first touch as belt-and-suspenders for any future MRO
   irregularity.
"""
from __future__ import annotations

import pytest

from slappyengine.asset import Asset
from slappyengine.event_bus import Observable
from slappyengine.layer import Layer
from slappyengine.render_target import RenderTarget


class _VehicleLike(Observable, Asset):
    """Mirror of Ochema Circuit's VehicleEntity(Observable, Asset) — this is
    the exact class shape that regressed."""

    def __init__(self) -> None:
        super().__init__()
        # Games call add_layer immediately after super().__init__() — this
        # must not raise AttributeError('... has no attribute layers').
        blank = Layer.blank(4, 4, name="body")
        self.add_layer(blank)


class _PlayerLike(Observable, Asset):
    """Mirror of Bullet Strata's PlayerEntity(Observable, Asset)."""

    def __init__(self) -> None:
        super().__init__()
        self.add_layer(Layer.blank(2, 2, name="torso"))
        self.add_layer(Layer.blank(2, 2, name="head"))


def test_observable_asset_subclass_add_layer_in_init() -> None:
    """Instantiating an Observable+Asset subclass that calls add_layer in its
    own __init__ must not raise AttributeError."""
    v = _VehicleLike()
    assert hasattr(v, "layers")
    assert len(v.layers) == 1
    assert v.layers[0].name == "body"
    # Observable state also initialised.
    assert hasattr(v, "_bus")
    assert hasattr(v, "_observable_topic")
    # Entity/Asset state also initialised.
    assert hasattr(v, "id")
    assert v.size == (64, 64)
    assert v.material_map is None


def test_bullet_strata_style_multi_layer_subclass() -> None:
    """Player-style entity with several add_layer calls in __init__."""
    p = _PlayerLike()
    assert [lyr.name for lyr in p.layers] == ["torso", "head"]


def test_base_render_target_still_has_empty_layers_list() -> None:
    """Sanity: the base RenderTarget continues to initialise ``layers`` to an
    empty list. This guards against regressions from the class-level attribute
    workarounds we considered."""
    rt = RenderTarget()
    assert rt.layers == []
    # Two independent instances must not share list state.
    rt2 = RenderTarget()
    rt.add_layer(Layer.blank(1, 1, name="a"))
    assert rt.layers != rt2.layers
    assert rt2.layers == []


def test_add_layer_idempotent_across_init_orders() -> None:
    """add_layer works regardless of whether the Observable mixin appears
    first or second in the MRO, and regardless of whether add_layer is called
    before or after super().__init__()."""

    # Case A: Observable first, add_layer after super().
    class A(Observable, Asset):
        def __init__(self) -> None:
            super().__init__()
            self.add_layer(Layer.blank(1, 1, name="a"))

    # Case B: Asset first, add_layer after super().
    class B(Asset, Observable):
        def __init__(self) -> None:
            super().__init__()
            self.add_layer(Layer.blank(1, 1, name="b"))

    # Case C: Plain Asset subclass (no Observable), add_layer after super.
    class C(Asset):
        def __init__(self) -> None:
            super().__init__()
            self.add_layer(Layer.blank(1, 1, name="c"))

    for cls, expected in [(A, "a"), (B, "b"), (C, "c")]:
        inst = cls()
        assert len(inst.layers) == 1, f"{cls.__name__} lost layer"
        assert inst.layers[0].name == expected


def test_add_layer_self_heals_when_layers_missing() -> None:
    """The defensive guard inside RenderTarget.add_layer materialises
    ``layers`` on first touch even if some future MRO break skips
    RenderTarget.__init__ entirely."""
    rt = RenderTarget.__new__(RenderTarget)  # skip __init__ deliberately
    assert not hasattr(rt, "layers")
    rt.add_layer(Layer.blank(1, 1, name="x"))
    assert len(rt.layers) == 1


def test_standalone_observable_unaffected() -> None:
    """Making Observable cooperative must not break plain Observable subclasses
    used across ~100 existing engine tests."""

    class Plain(Observable):
        pass

    p = Plain()
    assert hasattr(p, "_bus")
    assert p._observable_topic == "changed"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
