"""Tests for ``slappyengine.iso.combat`` — Phase C3 (Stone Keep).

Pure-logic only: no GPU, no rendering, no Stone Keep imports.
"""
from __future__ import annotations

import pytest

from slappyengine.iso.combat import (
    Attacker,
    Defender,
    WaveSchedule,
    WaveSpec,
    resolve_attack,
)


# ---------------------------------------------------------------------------
# resolve_attack
# ---------------------------------------------------------------------------

def test_resolve_attack_in_reach_reduces_hp():
    attacker = Attacker(pos=(0.0, 0.0), damage=25.0, reach=5.0)
    defender = Defender(pos=(3.0, 0.0), hp=100.0)

    dealt, alive = resolve_attack(attacker, defender)

    assert dealt == pytest.approx(25.0)
    assert alive is True
    assert defender.hp == pytest.approx(75.0)


def test_resolve_attack_out_of_reach_zero_damage():
    attacker = Attacker(pos=(0.0, 0.0), damage=25.0, reach=2.0)
    defender = Defender(pos=(10.0, 0.0), hp=100.0)

    dealt, alive = resolve_attack(attacker, defender)

    assert dealt == 0.0
    # Defender wasn't touched but is still alive.
    assert alive is True
    assert defender.hp == pytest.approx(100.0)


def test_resolve_attack_kill_returns_alive_false():
    attacker = Attacker(pos=(0.0, 0.0), damage=100.0, reach=5.0)
    defender = Defender(pos=(1.0, 1.0), hp=50.0)

    dealt, alive = resolve_attack(attacker, defender)

    assert dealt == pytest.approx(100.0)
    assert alive is False
    assert defender.hp <= 0


# ---------------------------------------------------------------------------
# WaveSchedule
# ---------------------------------------------------------------------------

def test_wave_schedule_zero_delay_spawns_immediately():
    spec = WaveSpec(
        count=1,
        spawn_points=[(0.0, 0.0)],
        hp_each=10.0,
        interval=1.0,
        delay=0.0,
    )
    sched = WaveSchedule([spec])

    # Even an infinitesimal tick should fire the zero-delay first spawn.
    out = sched.tick(0.0001)

    assert len(out) == 1
    assert out[0].hp == pytest.approx(10.0)
    assert out[0].pos == (0.0, 0.0)
    assert sched.finished is True


def test_wave_schedule_respects_interval():
    spec = WaveSpec(
        count=3,
        spawn_points=[(0.0, 0.0)],
        hp_each=10.0,
        interval=1.0,
        delay=0.0,
    )
    sched = WaveSchedule([spec])

    # First tick fires the zero-delay spawn.
    first = sched.tick(0.0)
    assert len(first) == 1

    # Half the interval — nothing new.
    none = sched.tick(0.5)
    assert none == []

    # Cross the interval boundary — exactly one more spawn.
    next_spawn = sched.tick(0.5)
    assert len(next_spawn) == 1

    # Another half-interval — still nothing.
    assert sched.tick(0.5) == []


def test_wave_schedule_finished_when_all_spawned():
    spec = WaveSpec(
        count=2,
        spawn_points=[(0.0, 0.0)],
        hp_each=10.0,
        interval=1.0,
        delay=0.0,
    )
    sched = WaveSchedule([spec])

    assert sched.finished is False
    # Big tick: enough to cover delay (0) + interval (1) and emit both.
    out = sched.tick(5.0)
    assert len(out) == 2
    assert sched.finished is True


def test_wave_schedule_determinism():
    waves = [
        WaveSpec(
            count=3,
            spawn_points=[(0.0, 0.0), (1.0, 1.0)],
            hp_each=10.0,
            interval=0.5,
            delay=0.25,
        ),
        WaveSpec(
            count=2,
            spawn_points=[(5.0, 5.0)],
            hp_each=20.0,
            interval=1.0,
            delay=0.0,
        ),
    ]
    dt_sequence = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    def run(waves_arg):
        sched = WaveSchedule(waves_arg)
        collected = []
        for dt in dt_sequence:
            collected.extend(sched.tick(dt))
        return collected, sched.finished

    out_a, fin_a = run([WaveSpec(**w.__dict__) for w in waves])
    out_b, fin_b = run([WaveSpec(**w.__dict__) for w in waves])

    assert len(out_a) == len(out_b)
    assert fin_a == fin_b
    for a, b in zip(out_a, out_b):
        assert a.pos == b.pos
        assert a.hp == pytest.approx(b.hp)
        assert a.team == b.team


def test_wave_schedule_round_robin_spawn_points():
    points = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    spec = WaveSpec(
        count=7,                  # > len(spawn_points)
        spawn_points=points,
        hp_each=5.0,
        interval=0.1,
        delay=0.0,
    )
    sched = WaveSchedule([spec])

    # Run long enough that every spawn fires.
    out = sched.tick(100.0)

    assert len(out) == 7
    # Spawn `i` must land on points[i % len(points)].
    for i, defender in enumerate(out):
        assert defender.pos == points[i % len(points)]
    assert sched.finished is True
