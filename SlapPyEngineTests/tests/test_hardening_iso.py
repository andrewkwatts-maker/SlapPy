"""Input-validation tests for ``slappyengine.iso.combat`` public API."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from slappyengine.iso.combat import (
    Attacker,
    Defender,
    WaveSchedule,
    WaveSpec,
    resolve_attack,
)


# ---------------------------------------------------------------------------
# resolve_attack — duck-typing + finiteness
# ---------------------------------------------------------------------------


def test_resolve_attack_rejects_attacker_missing_pos():
    bad = SimpleNamespace(damage=1.0, reach=1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(TypeError, match="attacker missing"):
        resolve_attack(bad, d)  # type: ignore[arg-type]


def test_resolve_attack_rejects_attacker_missing_damage():
    bad = SimpleNamespace(pos=(0.0, 0.0), reach=1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(TypeError, match="attacker missing"):
        resolve_attack(bad, d)  # type: ignore[arg-type]


def test_resolve_attack_rejects_attacker_missing_reach():
    bad = SimpleNamespace(pos=(0.0, 0.0), damage=1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(TypeError, match="attacker missing"):
        resolve_attack(bad, d)  # type: ignore[arg-type]


def test_resolve_attack_rejects_defender_missing_hp():
    a = Attacker(pos=(0.0, 0.0), damage=1.0, reach=1.0)
    bad = SimpleNamespace(pos=(0.0, 0.0))
    with pytest.raises(TypeError, match="defender missing"):
        resolve_attack(a, bad)  # type: ignore[arg-type]


def test_resolve_attack_rejects_negative_damage():
    a = Attacker(pos=(0.0, 0.0), damage=-1.0, reach=1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(ValueError, match="attacker.damage"):
        resolve_attack(a, d)


def test_resolve_attack_rejects_negative_reach():
    a = Attacker(pos=(0.0, 0.0), damage=1.0, reach=-1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(ValueError, match="attacker.reach"):
        resolve_attack(a, d)


def test_resolve_attack_rejects_nan_damage():
    a = Attacker(pos=(0.0, 0.0), damage=float("nan"), reach=1.0)
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(ValueError, match="attacker.damage"):
        resolve_attack(a, d)


def test_resolve_attack_rejects_inf_reach():
    a = Attacker(pos=(0.0, 0.0), damage=1.0, reach=float("inf"))
    d = Defender(pos=(0.0, 0.0), hp=10.0)
    with pytest.raises(ValueError, match="attacker.reach"):
        resolve_attack(a, d)


def test_resolve_attack_rejects_nan_hp():
    a = Attacker(pos=(0.0, 0.0), damage=1.0, reach=1.0)
    d = Defender(pos=(0.0, 0.0), hp=float("nan"))
    with pytest.raises(ValueError, match="defender.hp"):
        resolve_attack(a, d)


# ---------------------------------------------------------------------------
# WaveSpec.__post_init__
# ---------------------------------------------------------------------------


def test_wavespec_rejects_zero_count():
    with pytest.raises(ValueError, match="count"):
        WaveSpec(count=0, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)


def test_wavespec_rejects_negative_count():
    with pytest.raises(ValueError, match="count"):
        WaveSpec(count=-1, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)


def test_wavespec_rejects_empty_spawn_points():
    with pytest.raises(ValueError, match="spawn_points"):
        WaveSpec(count=2, spawn_points=[], hp_each=1.0, interval=1.0)


def test_wavespec_rejects_negative_hp_each():
    with pytest.raises(ValueError, match="hp_each"):
        WaveSpec(
            count=2, spawn_points=[(0.0, 0.0)], hp_each=-5.0, interval=1.0,
        )


def test_wavespec_rejects_zero_hp_each():
    with pytest.raises(ValueError, match="hp_each"):
        WaveSpec(
            count=2, spawn_points=[(0.0, 0.0)], hp_each=0.0, interval=1.0,
        )


def test_wavespec_rejects_negative_interval():
    with pytest.raises(ValueError, match="interval"):
        WaveSpec(
            count=2, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=-1.0,
        )


def test_wavespec_rejects_negative_delay():
    with pytest.raises(ValueError, match="delay"):
        WaveSpec(
            count=2, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0,
            delay=-0.5,
        )


def test_wavespec_rejects_non_int_count():
    with pytest.raises(TypeError, match="count"):
        WaveSpec(
            count=2.5,  # type: ignore[arg-type]
            spawn_points=[(0.0, 0.0)],
            hp_each=1.0,
            interval=1.0,
        )


# ---------------------------------------------------------------------------
# WaveSchedule.tick
# ---------------------------------------------------------------------------


def test_wave_schedule_tick_rejects_negative_dt():
    spec = WaveSpec(count=1, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)
    sched = WaveSchedule([spec])
    with pytest.raises(ValueError, match="dt"):
        sched.tick(-0.1)


def test_wave_schedule_tick_rejects_nan_dt():
    spec = WaveSpec(count=1, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)
    sched = WaveSchedule([spec])
    with pytest.raises(ValueError, match="dt"):
        sched.tick(float("nan"))


def test_wave_schedule_tick_rejects_string_dt():
    spec = WaveSpec(count=1, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)
    sched = WaveSchedule([spec])
    with pytest.raises(TypeError, match="dt"):
        sched.tick("fast")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Positive sanity — validated builders still compose.
# ---------------------------------------------------------------------------


def test_positive_resolve_attack_runs():
    a = Attacker(pos=(0.0, 0.0), damage=5.0, reach=5.0)
    d = Defender(pos=(1.0, 1.0), hp=50.0)
    dealt, alive = resolve_attack(a, d)
    assert dealt == pytest.approx(5.0)
    assert alive is True


def test_positive_wavespec_constructs():
    spec = WaveSpec(
        count=3, spawn_points=[(0.0, 0.0), (1.0, 0.0)],
        hp_each=10.0, interval=0.5, delay=0.0,
    )
    assert spec.count == 3
    assert len(spec.spawn_points) == 2


def test_positive_waveschedule_runs():
    spec = WaveSpec(
        count=2, spawn_points=[(0.0, 0.0)],
        hp_each=10.0, interval=0.5, delay=0.0,
    )
    sched = WaveSchedule([spec])
    out = sched.tick(5.0)
    assert len(out) == 2


def test_positive_zero_dt_is_legal():
    spec = WaveSpec(count=1, spawn_points=[(0.0, 0.0)], hp_each=1.0, interval=1.0)
    sched = WaveSchedule([spec])
    out = sched.tick(0.0)
    # Zero-delay first spawn still fires on a zero-dt tick.
    assert len(out) == 1
