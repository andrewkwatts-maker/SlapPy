"""Tests for :mod:`pharos_engine.physics.particles`.

These cover the public surface promised by the visual particle system:
emission, motion integration (gravity + drag), life-decay culling, the
hard cap at ``max_particles``, material → style mapping, and the
render path.
"""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from pharos_engine.physics.particles import (
    Particle,
    ParticleSystem,
    style_for_material,
)


def _make_sys(**kw) -> ParticleSystem:
    """Helper: a deterministic system (seeded RNG, no gravity unless asked)."""
    kw.setdefault("gravity", (0.0, 0.0))
    kw.setdefault("air_drag", 1.0)
    kw.setdefault("max_particles", 1024)
    kw.setdefault("rng", random.Random(1234))
    return ParticleSystem(**kw)


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

def test_emit_increases_particle_count() -> None:
    ps = _make_sys()
    # Use "spark" style (count_mul=1.2) → request 10 should give >= 10.
    # Use "shatter" instead (count_mul=1.0) for an exact match.
    spawned = ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=10)
    assert spawned == 10
    assert ps.count == 10


def test_emit_default_style_is_dust() -> None:
    # Unknown material → dust (count_mul=0.9 → 9 of 10).
    ps = _make_sys()
    spawned = ps.emit((0.0, 0.0), (0.0, 0.0), "unobtanium", count=10)
    assert spawned == 9
    assert ps.count == 9


# ---------------------------------------------------------------------------
# Step / integration
# ---------------------------------------------------------------------------

def test_step_advances_position() -> None:
    ps = _make_sys()
    # Manually seed a single particle going right at 50 px/s.
    spawned = ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=1)
    assert spawned == 1
    # Override velocity to a known value.
    ps._vel[0] = (50.0, 0.0)
    ps._pos[0] = (0.0, 0.0)
    ps._life[0] = 10.0
    ps._mlife[0] = 10.0

    ps.step(0.1)
    # Position should be ~(5, 0).
    p = next(iter(ps.iter_particles()))
    assert p.position[0] == pytest.approx(5.0, abs=1e-4)
    assert p.position[1] == pytest.approx(0.0, abs=1e-4)


def test_dead_particles_are_culled() -> None:
    ps = _make_sys()
    ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=10)
    # Force everyone to short life.
    ps._life[: ps.count] = 0.1
    ps._mlife[: ps.count] = 0.1
    before = ps.count
    ps.step(0.2)
    assert ps.count < before
    assert ps.count == 0


def test_max_particles_clamps() -> None:
    ps = _make_sys(max_particles=20)
    # Try to spawn way more than the cap (account for count_mul=1.0 on shatter).
    spawned = ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=500)
    assert ps.count == 20
    assert spawned == 20
    # A second emit can't grow past the cap either.
    again = ps.emit((0.0, 0.0), (0.0, 1.0), "stone", count=50)
    assert again == 0
    assert ps.count == 20


def test_air_drag_decays_velocity() -> None:
    # drag=0.5 retention per second → after 1.0s velocity halves.
    ps = ParticleSystem(
        gravity=(0.0, 0.0),
        air_drag=0.5,
        max_particles=8,
        rng=random.Random(7),
    )
    ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=1)
    ps._vel[0] = (100.0, 0.0)
    ps._life[0] = 100.0
    ps._mlife[0] = 100.0
    ps.step(1.0)
    p = next(iter(ps.iter_particles()))
    # After 1.0s of dt with air_drag=0.5 and no gravity, vx should be ~50.
    assert p.velocity[0] == pytest.approx(50.0, rel=1e-3)


def test_gravity_pulls_down() -> None:
    ps = ParticleSystem(
        gravity=(0.0, 100.0),
        air_drag=1.0,
        max_particles=8,
        rng=random.Random(7),
    )
    ps.emit((0.0, 0.0), (0.0, -1.0), "stone", count=1)
    ps._vel[0] = (0.0, 0.0)
    ps._pos[0] = (0.0, 0.0)
    ps._life[0] = 10.0
    ps._mlife[0] = 10.0
    ps.step(0.5)
    p = next(iter(ps.iter_particles()))
    # vy should be ~50 after 0.5s under g=100.
    assert p.velocity[1] == pytest.approx(50.0, abs=1e-3)


# ---------------------------------------------------------------------------
# Material → style colour mapping
# ---------------------------------------------------------------------------

def _avg_color(ps: ParticleSystem) -> tuple[float, float, float]:
    cols = ps._col[: ps.count].astype(np.float32)
    return tuple(cols.mean(axis=0).tolist())  # type: ignore[return-value]


def test_emit_from_material_picks_right_style() -> None:
    # Stone → shatter: bright (mean luminance high), low colour bias.
    ps_stone = _make_sys()
    ps_stone.emit((0.0, 0.0), (1.0, 0.0), "stone", count=60)
    r, g, b = _avg_color(ps_stone)
    # Whiteish: every channel above 140, all roughly equal.
    assert r > 140 and g > 140 and b > 140
    assert max(r, g, b) - min(r, g, b) < 30

    # Water → splash: blue dominates.
    ps_water = _make_sys()
    ps_water.emit((0.0, 0.0), (1.0, 0.0), "water", count=60)
    r, g, b = _avg_color(ps_water)
    assert b > r and b > g
    assert b > 150

    # Lava → ember: red dominates and is bright (bloom-ready, R > 220).
    ps_lava = _make_sys()
    ps_lava.emit((0.0, 0.0), (1.0, 0.0), "lava", count=60)
    r, g, b = _avg_color(ps_lava)
    assert r > 220
    assert r > g and r > b


def test_style_for_material_helper() -> None:
    assert style_for_material("stone") == "shatter"
    assert style_for_material("iron") == "spark"
    assert style_for_material("mud") == "splatter"
    assert style_for_material("water") == "splash"
    assert style_for_material("lava") == "ember"
    assert style_for_material("sand") == "dust"
    assert style_for_material("nope") == "dust"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def test_render_paints_particles_in_frame() -> None:
    ps = _make_sys()
    # Emit a clump at (50, 50) in world space.  All life=1 so colour
    # is not faded to zero on the first render.
    ps.emit((50.0, 50.0), (0.0, 0.0), "stone", count=30)
    ps._life[: ps.count] = 1.0
    ps._mlife[: ps.count] = 1.0
    # Make sure they're not size-0.
    ps._size[: ps.count] = np.maximum(ps._size[: ps.count], 1.0)

    frame = np.zeros((128, 128, 4), dtype=np.uint8)
    frame[..., 3] = 255
    out = ps.render(frame, world_view=(0.0, 0.0, 128.0, 128.0))
    assert out is frame  # same buffer returned
    # There must now be lit pixels somewhere.
    rgb_sum = frame[..., :3].sum()
    assert rgb_sum > 0


def test_render_offscreen_particles_are_skipped() -> None:
    ps = _make_sys()
    # Emit far outside the view rect.
    ps.emit((10_000.0, 10_000.0), (0.0, 0.0), "stone", count=20)
    ps._life[: ps.count] = 1.0
    ps._mlife[: ps.count] = 1.0
    frame = np.zeros((64, 64, 4), dtype=np.uint8)
    frame[..., 3] = 255
    ps.render(frame, world_view=(0.0, 0.0, 64.0, 64.0))
    # Nothing painted into the RGB channels.
    assert frame[..., :3].sum() == 0


def test_render_with_no_particles_is_noop() -> None:
    ps = _make_sys()
    frame = np.zeros((16, 16, 4), dtype=np.uint8)
    out = ps.render(frame, world_view=(0.0, 0.0, 16.0, 16.0))
    assert out is frame
    assert frame.sum() == 0


# ---------------------------------------------------------------------------
# Contact-driven emission
# ---------------------------------------------------------------------------

class _FakeBody:
    def __init__(self, name: str) -> None:
        self.material_name = name


def test_emit_from_contacts_uses_body_lookup() -> None:
    ps = _make_sys()
    # Build a ContactPair-like object.
    class C:
        a = 0
        b = 1
        normal = (1.0, 0.0)
        depth = 2.0
        point = (5.0, 5.0)
    contacts = [C()]
    body_lookup = {0: _FakeBody("stone"), 1: _FakeBody("water")}
    spawned = ps.emit_from_contacts(contacts, world=None, hulls=None,
                                    body_lookup=body_lookup)
    assert spawned > 0
    assert ps.count == spawned
    # Side A=stone (shatter, whiteish), side B=water (splash, bluish):
    # combined particles should still have a non-trivial blue mean.
    r, g, b = _avg_color(ps)
    assert b > 0


def test_emit_from_contacts_accepts_dicts() -> None:
    ps = _make_sys()
    contacts = [
        {"a": 0, "b": 1, "normal": (0.0, 1.0), "depth": 1.0, "point": (0.0, 0.0)},
    ]
    body_lookup = {0: _FakeBody("iron"), 1: _FakeBody("iron")}
    n = ps.emit_from_contacts(contacts, body_lookup=body_lookup)
    assert n > 0
    assert ps.count == n


def test_emit_from_contacts_empty_is_noop() -> None:
    ps = _make_sys()
    assert ps.emit_from_contacts([], body_lookup={}) == 0
    assert ps.count == 0


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_clear_drops_all() -> None:
    ps = _make_sys()
    ps.emit((0.0, 0.0), (1.0, 0.0), "stone", count=10)
    assert ps.count == 10
    ps.clear()
    assert ps.count == 0


def test_invalid_max_particles_raises() -> None:
    with pytest.raises(ValueError):
        ParticleSystem(max_particles=0)


def test_particle_dataclass_view() -> None:
    ps = _make_sys()
    ps.emit((1.0, 2.0), (1.0, 0.0), "stone", count=1)
    p = next(iter(ps.iter_particles()))
    assert isinstance(p, Particle)
    assert p.position == pytest.approx((1.0, 2.0))
    assert 0.0 < p.life <= p.max_life
    assert p.size >= 1.0
