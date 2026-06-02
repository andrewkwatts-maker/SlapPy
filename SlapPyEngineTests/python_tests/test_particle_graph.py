"""Tests for :mod:`slappyengine.physics.particle_graph`.

The graph builds on top of the existing :class:`ParticleSystem` -- these
tests therefore exercise *only* the new node-graph behaviour
(material filtering, impulse thresholds, direction modes, color ramps,
preset shape) and trust the underlying physics already covered by
``test_particles.py``.
"""
from __future__ import annotations

import math
import random

import pytest

from slappyengine.physics.particle_graph import (
    EmitterNode,
    ParticleGraph,
    interpolate_color_ramp,
)
from slappyengine.physics.particles import ParticleSystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBody:
    """Tiny stand-in for a ``PhysicsBody``-ish object.

    ``ParticleSystem.emit_from_contacts`` (and our ``ParticleGraph``)
    consult ``body_lookup[hull_id].material_name`` to resolve a contact's
    material -- so this is all we need to pretend.
    """
    def __init__(self, material_name: str) -> None:
        self.material_name = material_name


def _make_contact(
    a_id: int = 1,
    b_id: int = 2,
    normal: tuple[float, float] = (1.0, 0.0),
    depth: float = 5.0,
    point: tuple[float, float] = (0.0, 0.0),
) -> dict:
    """Build a dict-form contact (accepted by ``_unpack_contact``)."""
    return {
        "a": a_id,
        "b": b_id,
        "normal": normal,
        "depth": depth,
        "point": point,
    }


def _make_psys() -> ParticleSystem:
    """Deterministic ParticleSystem: no gravity/drag, seeded RNG."""
    return ParticleSystem(
        gravity=(0.0, 0.0),
        air_drag=1.0,
        max_particles=4096,
        rng=random.Random(1234),
    )


def _make_graph(*nodes: EmitterNode) -> ParticleGraph:
    g = ParticleGraph(rng=random.Random(1234))
    for n in nodes:
        g.add(n)
    return g


# ---------------------------------------------------------------------------
# Basic graph behaviour
# ---------------------------------------------------------------------------

def test_empty_graph_emits_nothing() -> None:
    psys = _make_psys()
    graph = ParticleGraph()
    spawned = graph.emit_for_contact(
        psys,
        [_make_contact()],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert spawned == 0
    assert psys.count == 0


def test_emitter_fires_for_matching_material() -> None:
    psys = _make_psys()
    iron_only = EmitterNode(
        name="t",
        material_filter={"iron"},
        count_range=(5, 5),
    )
    graph = _make_graph(iron_only)

    # Iron contact → emitter fires.
    n_iron = graph.emit_for_contact(
        psys,
        [_make_contact(a_id=1, b_id=2)],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("wood")},
    )
    assert n_iron == 5
    assert psys.count == 5

    # Glass contact → emitter does NOT fire.
    psys2 = _make_psys()
    n_glass = graph.emit_for_contact(
        psys2,
        [_make_contact(a_id=1, b_id=2)],
        body_lookup={1: _FakeBody("glass"), 2: _FakeBody("wood")},
    )
    assert n_glass == 0
    assert psys2.count == 0


def test_emitter_skips_below_impulse_threshold() -> None:
    psys = _make_psys()
    node = EmitterNode(
        name="t",
        impulse_threshold=10.0,
        count_range=(4, 4),
    )
    graph = _make_graph(node)
    # Depth 1.0 < threshold 10.0 → suppressed.
    spawned = graph.emit_for_contact(
        psys,
        [_make_contact(depth=1.0)],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert spawned == 0
    assert psys.count == 0
    # Depth 50.0 > threshold → fires.
    spawned2 = graph.emit_for_contact(
        psys,
        [_make_contact(depth=50.0)],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert spawned2 == 4
    assert psys.count == 4


def test_count_range_respected() -> None:
    """An emitter with count_range=(5, 5) spawns exactly 5 each call."""
    psys = _make_psys()
    node = EmitterNode(name="t", count_range=(5, 5))
    graph = _make_graph(node)
    n = graph.emit_for_contact(
        psys,
        [_make_contact()],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert n == 5
    assert psys.count == 5
    # And again.
    graph.emit_for_contact(
        psys,
        [_make_contact()],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert psys.count == 10


# ---------------------------------------------------------------------------
# Color ramp
# ---------------------------------------------------------------------------

def test_color_ramp_interpolates() -> None:
    """At t=0.5 between (0, white) and (1, black), colour ≈ midpoint."""
    ramp = [(0.0, (255, 255, 255)), (1.0, (0, 0, 0))]
    c = interpolate_color_ramp(ramp, 0.5)
    # 127 or 128 depending on rounding -- be lenient by a single unit.
    for chan in c:
        assert 126 <= chan <= 129
    # Endpoints clamp.
    assert interpolate_color_ramp(ramp, -1.0) == (255, 255, 255)
    assert interpolate_color_ramp(ramp,  2.0) == (0, 0, 0)
    # Multi-stop ramp midpoint between waypoints.
    rmp = [(0.0, (0, 0, 0)), (0.5, (100, 100, 100)), (1.0, (200, 200, 200))]
    midmid = interpolate_color_ramp(rmp, 0.25)
    for chan in midmid:
        assert 49 <= chan <= 51  # halfway between 0 and 100


# ---------------------------------------------------------------------------
# Direction modes
# ---------------------------------------------------------------------------

def _emit_one(psys: ParticleSystem, node: EmitterNode,
              normal: tuple[float, float]) -> tuple[float, float]:
    """Emit a single particle and return its velocity vector."""
    contact = _make_contact(normal=normal, depth=5.0)
    graph = _make_graph(node)
    graph.emit_for_contact(
        psys,
        [contact],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert psys.count >= 1
    p = next(iter(psys.iter_particles()))
    return p.velocity


def test_direction_modes() -> None:
    # Use a wide range so randomness doesn't accidentally pass; we just
    # check the average direction over many samples.
    def _avg_dir(node: EmitterNode, normal: tuple[float, float],
                 n_samples: int = 200) -> tuple[float, float]:
        psys = ParticleSystem(
            gravity=(0.0, 0.0), air_drag=1.0,
            max_particles=4096, rng=random.Random(42),
        )
        graph = ParticleGraph(rng=random.Random(42))
        graph.add(node)
        contacts = [
            _make_contact(normal=normal, depth=5.0) for _ in range(n_samples)
        ]
        graph.emit_for_contact(
            psys, contacts,
            body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
        )
        xs = []
        ys = []
        for p in psys.iter_particles():
            mag = math.hypot(*p.velocity)
            if mag > 0:
                xs.append(p.velocity[0] / mag)
                ys.append(p.velocity[1] / mag)
        return sum(xs) / len(xs), sum(ys) / len(ys)

    # "normal": cone aligned with +x normal → mean dir near (+1, 0).
    n_node = EmitterNode(
        name="n", direction_mode="normal", count_range=(1, 1),
        cone_half_angle_rad=0.3, speed_range=(100.0, 100.0),
    )
    avx, avy = _avg_dir(n_node, (1.0, 0.0))
    assert avx > 0.85, f"normal mode mean x={avx}"
    assert abs(avy) < 0.25, f"normal mode mean y={avy}"

    # "radial": uniform full circle → mean ~ (0, 0).
    r_node = EmitterNode(
        name="r", direction_mode="radial", count_range=(1, 1),
        speed_range=(100.0, 100.0),
    )
    rvx, rvy = _avg_dir(r_node, (1.0, 0.0))
    assert abs(rvx) < 0.2, f"radial mode mean x={rvx}"
    assert abs(rvy) < 0.2, f"radial mode mean y={rvy}"

    # "fixed": fixed_direction=(0, -1) → mean direction near (0, -1).
    f_node = EmitterNode(
        name="f", direction_mode="fixed", count_range=(1, 1),
        fixed_direction=(0.0, -1.0),
        cone_half_angle_rad=0.2, speed_range=(100.0, 100.0),
    )
    fvx, fvy = _avg_dir(f_node, (1.0, 0.0))
    assert fvy < -0.85, f"fixed mode mean y={fvy}"
    assert abs(fvx) < 0.25, f"fixed mode mean x={fvx}"

    # "tangent": perpendicular to normal (1, 0) → direction along ±y.
    # The implementation picks the +y-rotation of the normal.
    t_node = EmitterNode(
        name="t", direction_mode="tangent", count_range=(1, 1),
        cone_half_angle_rad=0.1, speed_range=(100.0, 100.0),
    )
    tvx, tvy = _avg_dir(t_node, (1.0, 0.0))
    # tangent to (1, 0) is (0, ±1).  Just assert |x| is small and |y|
    # is large -- sign depends on the rotation convention.
    assert abs(tvx) < 0.25, f"tangent mode mean x={tvx}"
    assert abs(tvy) > 0.85, f"tangent mode mean y={tvy}"


# ---------------------------------------------------------------------------
# Layered emitters
# ---------------------------------------------------------------------------

def test_two_emitters_layer() -> None:
    """Sparks (5 fast) + smoke (3 slow) on the same iron contact both fire."""
    psys = _make_psys()
    sparks = EmitterNode(
        name="sparks",
        count_range=(5, 5),
        speed_range=(400.0, 400.0),
        material_filter={"iron"},
        drag_per_sec=1.0,  # don't attenuate so the velocity check is clean
    )
    smoke = EmitterNode(
        name="smoke",
        count_range=(3, 3),
        speed_range=(20.0, 20.0),
        material_filter={"iron"},
        drag_per_sec=1.0,
    )
    graph = _make_graph(sparks, smoke)
    total = graph.emit_for_contact(
        psys,
        [_make_contact(normal=(1.0, 0.0))],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert total == 8
    assert psys.count == 8
    # Verify we got a mix of fast and slow particles.
    speeds = sorted(math.hypot(*p.velocity) for p in psys.iter_particles())
    assert any(s > 300.0 for s in speeds), f"expected fast particles, got {speeds}"
    assert any(s < 50.0  for s in speeds), f"expected slow particles, got {speeds}"


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def test_iron_impact_preset_emits_sparks() -> None:
    """Iron impact preset spawns bright (R>200) fast (>200px/s) sparks."""
    psys = _make_psys()
    graph = ParticleGraph.preset_iron_impact()
    # Replace the graph's RNG with one we control so the test is
    # reproducible across machines.
    graph._rng = random.Random(0xC0FFEE)
    n = graph.emit_for_contact(
        psys,
        [_make_contact(normal=(1.0, 0.0), depth=5.0)],
        body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
    )
    assert n > 0

    # At least one particle should be a bright fast spark and at least
    # one should be a slow dark smoke puff.
    bright_fast = 0
    slow_dark = 0
    for p in psys.iter_particles():
        speed = math.hypot(*p.velocity)
        if p.color[0] > 200 and speed > 200.0:
            bright_fast += 1
        if p.color[0] < 120 and speed < 80.0:
            slow_dark += 1
    assert bright_fast >= 1, "iron impact should emit bright fast sparks"
    assert slow_dark   >= 1, "iron impact should emit slow dark smoke"


def test_all_presets_construct_and_have_emitters() -> None:
    """Every preset returns a non-empty ParticleGraph."""
    for ctor in (
        ParticleGraph.preset_iron_impact,
        ParticleGraph.preset_glass_shatter,
        ParticleGraph.preset_lava_drip,
        ParticleGraph.preset_water_splash,
        ParticleGraph.preset_explosion,
    ):
        g = ctor()
        assert isinstance(g, ParticleGraph)
        assert len(g) >= 2, f"{ctor.__name__} should have at least 2 layers"
        for em in g:
            assert isinstance(em, EmitterNode)
            assert em.count_range[0] >= 0
            assert em.count_range[1] >= em.count_range[0]
            assert em.life_range[0] > 0


def test_explosion_preset_fires_without_material_filter() -> None:
    """preset_explosion has no material filter → fires on any contact."""
    psys = _make_psys()
    graph = ParticleGraph.preset_explosion()
    graph._rng = random.Random(7)
    n = graph.emit_for_contact(
        psys,
        [_make_contact(depth=5.0)],
        body_lookup={1: _FakeBody("unobtanium"), 2: _FakeBody("nothing")},
    )
    assert n > 0
    assert psys.count == n


def test_spawn_chance_zero_suppresses_emission() -> None:
    psys = _make_psys()
    node = EmitterNode(
        name="never", count_range=(5, 5), spawn_chance=0.0,
    )
    graph = _make_graph(node)
    # Try many times so RNG can't get lucky.
    for _ in range(20):
        graph.emit_for_contact(
            psys,
            [_make_contact()],
            body_lookup={1: _FakeBody("iron"), 2: _FakeBody("iron")},
        )
    assert psys.count == 0
