"""Negative-path tests for :class:`Camera` follow / and :mod:`slappyengine.
strata` public-boundary validation (hardening round 11).

Round 4 hardened the :class:`Camera` constructor and ``position`` / ``zoom``
property setters. This round extends coverage to :meth:`Camera.follow`
(``entity``, ``lerp``, ``screen_w``, ``screen_h``) and adds the first pass
of validation to :class:`StrataLayer` / :class:`StrataWorld`.

Positive paths for :class:`Camera` are covered by ``test_hardening_camera.py``
plus ``test_basic.py``. Positive paths for strata are covered by
``test_game_smoke_instantiation.py::test_strata_world_construct_with_layers``.

Silent-acceptance bugs this round catches:

1. ``StrataWorld(layers=[])`` used to silently construct, then crash with
   ``IndexError`` on first ``active_layer`` access and ``ZeroDivisionError``
   on the first ``set_active`` modulo.
2. ``StrataWorld.set_active(True)`` used to silently mean "layer 1" because
   ``True % len(layers) == 1`` — the bool slipped through the bare
   ``index % n`` arithmetic.
3. ``StrataWorld.set_active(1.5)`` used to silently store a float
   ``active_index``, breaking later ``el == self.active_index`` equality
   checks against entity int ``strata_layer`` values.
4. ``StrataLayer(tint=(1.0, 1.0, 1.0))`` (3-tuple) used to silently
   construct an invalid layer; the renderer would index out-of-bounds on
   the missing alpha channel.
5. ``StrataLayer(tint=(float('nan'), 0, 0, 1))`` used to silently propagate
   NaN through the RGBA multiply each frame.
6. ``StrataWorld(layers=..., inactive_dim=float('nan'))`` used to silently
   become the inactive-layer alpha multiplier.
7. ``StrataWorld.tick(float('nan'))`` used to silently NaN every
   phase-transition alpha.
8. ``Camera.follow(entity, lerp=float('nan'))`` used to silently advance the
   camera ``position`` to NaN the next frame.
9. ``Camera.follow(entity, lerp=True)`` used to silently snap-follow because
   ``True >= 1.0``.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from slappyengine.camera import Camera  # noqa: E402
from slappyengine.strata import StrataLayer, StrataWorld  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Entity:
    """Minimal stand-in for a follow target / strata-tracked entity."""

    def __init__(self, position=(0.0, 0.0), strata_layer: int = 0) -> None:
        self.position = position
        self.strata_layer = strata_layer


def _ok_layers() -> list[StrataLayer]:
    return [
        StrataLayer(name="bg", index=0, tint=(1.0, 1.0, 1.0, 1.0)),
        StrataLayer(name="fg", index=1, tint=(0.4, 0.6, 1.0, 0.9)),
    ]


# ---------------------------------------------------------------------------
# Camera.follow — entity
# ---------------------------------------------------------------------------


def test_follow_rejects_none_entity():
    cam = Camera()
    with pytest.raises(TypeError, match="entity must be an object with a"):
        cam.follow(None)


def test_follow_rejects_entity_without_position():
    cam = Camera()

    class _NoPos:
        pass

    with pytest.raises(TypeError, match="entity must be an object with a"):
        cam.follow(_NoPos())


def test_follow_rejects_entity_position_too_short():
    cam = Camera()
    ent = _Entity(position=(1.0,))
    with pytest.raises(ValueError, match=r"entity\.position must have length"):
        cam.follow(ent)


def test_follow_rejects_entity_position_with_nan():
    cam = Camera()
    ent = _Entity(position=(float("nan"), 0.0))
    with pytest.raises(ValueError, match=r"entity\.position\[0\] must be finite"):
        cam.follow(ent)


def test_follow_rejects_entity_position_with_inf_y():
    cam = Camera()
    ent = _Entity(position=(0.0, float("inf")))
    with pytest.raises(ValueError, match=r"entity\.position\[1\] must be finite"):
        cam.follow(ent)


def test_follow_rejects_entity_position_bool_member():
    cam = Camera()
    ent = _Entity(position=(True, 1.0))
    with pytest.raises(TypeError, match=r"entity\.position\[0\] must be a real number"):
        cam.follow(ent)


# ---------------------------------------------------------------------------
# Camera.follow — lerp
# ---------------------------------------------------------------------------


def test_follow_rejects_nan_lerp():
    # SILENT BUG: NaN lerp would set position to NaN next frame.
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(ValueError, match="lerp must be finite"):
        cam.follow(ent, lerp=float("nan"))


def test_follow_rejects_zero_lerp():
    # lerp == 0 would freeze the camera; almost certainly a typo for 1.0.
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(ValueError, match=r"lerp must be in \(0, 1\]"):
        cam.follow(ent, lerp=0.0)


def test_follow_rejects_negative_lerp():
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(ValueError, match=r"lerp must be in \(0, 1\]"):
        cam.follow(ent, lerp=-0.1)


def test_follow_rejects_too_large_lerp():
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(ValueError, match=r"lerp must be in \(0, 1\]"):
        cam.follow(ent, lerp=1.5)


def test_follow_rejects_bool_lerp():
    # SILENT BUG: True == 1.0 ≥ 1.0 → snap-follow. Refuse to surface the typo.
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(TypeError, match="lerp must be a real number"):
        cam.follow(ent, lerp=True)


def test_follow_rejects_string_lerp():
    cam = Camera()
    ent = _Entity(position=(10.0, 20.0))
    with pytest.raises(TypeError, match="lerp must be a real number"):
        cam.follow(ent, lerp="fast")


# ---------------------------------------------------------------------------
# Camera.follow — screen_w / screen_h
# ---------------------------------------------------------------------------


def test_follow_rejects_zero_screen_w():
    cam = Camera()
    ent = _Entity(position=(0.0, 0.0))
    with pytest.raises(ValueError, match="screen_w must be > 0"):
        cam.follow(ent, screen_w=0)


def test_follow_rejects_nan_screen_h():
    cam = Camera()
    ent = _Entity(position=(0.0, 0.0))
    with pytest.raises(ValueError, match="screen_h must be finite"):
        cam.follow(ent, screen_h=float("nan"))


def test_follow_rejects_bool_screen_w():
    cam = Camera()
    ent = _Entity(position=(0.0, 0.0))
    with pytest.raises(TypeError, match="screen_w must be a real number"):
        cam.follow(ent, screen_w=True)


def test_follow_accepts_none_screen_args():
    # Positive path: None falls back to viewport size.
    cam = Camera()
    ent = _Entity(position=(40.0, 60.0))
    cam.follow(ent, screen_w=None, screen_h=None)
    assert math.isfinite(cam.position[0])
    assert math.isfinite(cam.position[1])


# ---------------------------------------------------------------------------
# StrataLayer constructor — name / index / tint / parallax
# ---------------------------------------------------------------------------


def test_strata_layer_rejects_non_str_name():
    with pytest.raises(TypeError, match="name must be a str"):
        StrataLayer(name=123, index=0, tint=(1.0, 1.0, 1.0, 1.0))


def test_strata_layer_rejects_empty_name():
    with pytest.raises(ValueError, match="name must be non-empty"):
        StrataLayer(name="", index=0, tint=(1.0, 1.0, 1.0, 1.0))


def test_strata_layer_rejects_bool_index():
    # SILENT BUG: True would store as index 1 silently.
    with pytest.raises(TypeError, match="index must be an int"):
        StrataLayer(name="bg", index=True, tint=(1.0, 1.0, 1.0, 1.0))


def test_strata_layer_rejects_negative_index():
    with pytest.raises(ValueError, match="index must be >= 0"):
        StrataLayer(name="bg", index=-1, tint=(1.0, 1.0, 1.0, 1.0))


def test_strata_layer_rejects_float_index():
    with pytest.raises(TypeError, match="index must be an int"):
        StrataLayer(name="bg", index=1.5, tint=(1.0, 1.0, 1.0, 1.0))


def test_strata_layer_rejects_3tuple_tint():
    # SILENT BUG: 3-tuple tint would later IndexError in renderer's RGBA mul.
    with pytest.raises(ValueError, match=r"tint must have length 4"):
        StrataLayer(name="bg", index=0, tint=(1.0, 1.0, 1.0))


def test_strata_layer_rejects_nan_tint_channel():
    # SILENT BUG: NaN in any tint channel propagates through render multiply.
    with pytest.raises(ValueError, match=r"tint\[0\] must be finite"):
        StrataLayer(name="bg", index=0, tint=(float("nan"), 0.0, 0.0, 1.0))


def test_strata_layer_rejects_nan_parallax():
    with pytest.raises(ValueError, match="parallax must be finite"):
        StrataLayer(name="bg", index=0, tint=(1.0, 1.0, 1.0, 1.0), parallax=float("nan"))


def test_strata_layer_rejects_string_tint():
    with pytest.raises(TypeError, match="tint must be a 4-tuple"):
        StrataLayer(name="bg", index=0, tint="white")


def test_strata_layer_rejects_bool_tint_channel():
    with pytest.raises(TypeError, match=r"tint\[3\] must be a real number"):
        StrataLayer(name="bg", index=0, tint=(1.0, 1.0, 1.0, True))


# ---------------------------------------------------------------------------
# StrataWorld constructor — layers / inactive_dim
# ---------------------------------------------------------------------------


def test_strata_world_rejects_empty_layers():
    # SILENT BUG: empty layers used to construct then ZeroDivisionError in
    # set_active and IndexError in active_layer.
    with pytest.raises(ValueError, match="layers must be non-empty"):
        StrataWorld(layers=[])


def test_strata_world_rejects_non_list_layers():
    with pytest.raises(TypeError, match="layers must be a list of StrataLayer"):
        StrataWorld(layers="not-a-list")


def test_strata_world_rejects_non_layer_element():
    with pytest.raises(TypeError, match=r"layers\[0\] must be a StrataLayer"):
        StrataWorld(layers=[{"name": "bg"}])


def test_strata_world_rejects_nan_inactive_dim():
    # SILENT BUG: NaN inactive_dim would render every inactive entity as NaN.
    with pytest.raises(ValueError, match="inactive_dim must be finite"):
        StrataWorld(layers=_ok_layers(), inactive_dim=float("nan"))


def test_strata_world_rejects_too_large_inactive_dim():
    with pytest.raises(ValueError, match=r"inactive_dim must be in \[0, 1\]"):
        StrataWorld(layers=_ok_layers(), inactive_dim=2.0)


def test_strata_world_rejects_negative_inactive_dim():
    with pytest.raises(ValueError, match=r"inactive_dim must be in \[0, 1\]"):
        StrataWorld(layers=_ok_layers(), inactive_dim=-0.5)


def test_strata_world_rejects_bool_inactive_dim():
    with pytest.raises(TypeError, match="inactive_dim must be a real number"):
        StrataWorld(layers=_ok_layers(), inactive_dim=True)


# ---------------------------------------------------------------------------
# StrataWorld.set_active / get_layer
# ---------------------------------------------------------------------------


def test_set_active_rejects_bool():
    # SILENT BUG: True % len(layers) used to silently mean "layer 1".
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="index must be an int"):
        world.set_active(True)


def test_set_active_rejects_float():
    # SILENT BUG: 1.5 used to silently store as active_index (float) and
    # break equality checks against int strata_layer values.
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="index must be an int"):
        world.set_active(1.5)


def test_set_active_rejects_negative():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(ValueError, match="index must be >= 0"):
        world.set_active(-1)


def test_set_active_accepts_int_with_modulo_wrap():
    # Positive path: wrap-around behaviour preserved.
    world = StrataWorld(layers=_ok_layers())
    world.set_active(5)  # 5 % 2 == 1
    assert world.active_index == 1


def test_get_layer_rejects_bool():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="index must be an int"):
        world.get_layer(True)


def test_get_layer_returns_none_for_out_of_range():
    # Positive path: out-of-range non-negative int still returns None.
    world = StrataWorld(layers=_ok_layers())
    assert world.get_layer(99) is None


# ---------------------------------------------------------------------------
# StrataWorld.entity_* / phase API
# ---------------------------------------------------------------------------


def test_entity_visibility_alpha_rejects_none():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="entity must not be None"):
        world.entity_visibility_alpha(None)


def test_entity_tint_rejects_none():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="entity must not be None"):
        world.entity_tint(None)


def test_begin_phase_rejects_none_entity():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="entity must not be None"):
        world.begin_phase(None)


def test_begin_phase_rejects_nan_transition_time():
    world = StrataWorld(layers=_ok_layers())
    ent = _Entity()
    with pytest.raises(ValueError, match="transition_time must be finite"):
        world.begin_phase(ent, transition_time=float("nan"))


def test_end_phase_rejects_none_entity():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="entity must not be None"):
        world.end_phase(None)


def test_tick_rejects_nan_dt():
    # SILENT BUG: NaN dt would NaN every phase-transition alpha.
    world = StrataWorld(layers=_ok_layers())
    ent = _Entity()
    world.begin_phase(ent)
    with pytest.raises(ValueError, match="dt must be finite"):
        world.tick(float("nan"))


def test_tick_rejects_bool_dt():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(TypeError, match="dt must be a real number"):
        world.tick(True)


def test_tick_rejects_inf_dt():
    world = StrataWorld(layers=_ok_layers())
    with pytest.raises(ValueError, match="dt must be finite"):
        world.tick(float("inf"))


# ---------------------------------------------------------------------------
# Positive sanity — make sure the validators don't break the happy path
# ---------------------------------------------------------------------------


def test_strata_world_happy_path_still_works():
    world = StrataWorld(layers=_ok_layers(), inactive_dim=0.25)
    assert world.active_layer.name == "bg"
    world.set_active(1)
    assert world.active_layer.name == "fg"

    ent = _Entity(strata_layer=1)
    assert world.entity_visibility_alpha(ent) == 1.0
    assert world.entity_tint(ent) == (0.4, 0.6, 1.0, 0.9)

    world.begin_phase(ent, transition_time=0.2)
    world.tick(1.0 / 60.0)
    world.end_phase(ent)


def test_camera_follow_happy_path_still_works():
    cam = Camera(position=(0.0, 0.0), zoom=1.0)
    ent = _Entity(position=(100.0, 200.0))
    cam.follow(ent, lerp=0.5, screen_w=800, screen_h=600)
    assert math.isfinite(cam.position[0])
    assert math.isfinite(cam.position[1])
