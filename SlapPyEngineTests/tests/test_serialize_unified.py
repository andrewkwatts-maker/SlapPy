"""Cross-subsystem serialize tests — JSON + YAML round-trip for thermal,
zones, iso.combat, telemetry history, and the SaveGame envelope.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.serialize import SaveGame, from_dict, load, save, to_dict


# ── HeatField ──────────────────────────────────────────────────────────────

def test_heatfield_dict_round_trip() -> None:
    from pharos_engine.thermal import HeatField
    grid = np.linspace(0.0, 100.0, 64, dtype=np.float64).reshape(8, 8)
    hf = HeatField(grid.copy(), conductivity=0.5, diffusivity=0.2)
    d = to_dict(hf)
    hf2 = from_dict(d)
    assert hf2.conductivity == pytest.approx(0.5)
    assert hf2.diffusivity == pytest.approx(0.2)
    np.testing.assert_array_equal(hf2.temperature, grid)


def test_heatfield_yaml_save_load(tmp_path: Path) -> None:
    from pharos_engine.thermal import HeatField
    grid = np.eye(4, dtype=np.float64) * 50.0
    hf = HeatField(grid.copy())
    p = tmp_path / "hf.yml"
    save(hf, p)
    hf2 = load(p)
    np.testing.assert_array_equal(hf2.temperature, grid)


# ── Zones ──────────────────────────────────────────────────────────────────

def test_rectzone_round_trip() -> None:
    from pharos_engine.zones import RectZone
    z = RectZone(name="safe", x=1.0, y=2.0, w=3.0, h=4.0, material="steel")
    d = to_dict(z)
    z2 = from_dict(d)
    assert z2.name == "safe"
    assert (z2.x, z2.y, z2.w, z2.h) == (1.0, 2.0, 3.0, 4.0)
    assert z2.material == "steel"


def test_thresholdzone_round_trip() -> None:
    from pharos_engine.zones import ThresholdZone
    z = ThresholdZone(
        name="trigger", x=0, y=0, w=2, h=2,
        threshold=0.5, hysteresis=0.1, strength_scale=2.0,
    )
    d = to_dict(z)
    z2 = from_dict(d)
    assert z2.threshold == pytest.approx(0.5)
    assert z2.hysteresis == pytest.approx(0.1)
    assert z2.strength_scale == pytest.approx(2.0)


def test_zonemanager_round_trip(tmp_path: Path) -> None:
    from pharos_engine.zones import RectZone, ZoneManager
    zm = ZoneManager()
    zm.add(RectZone(name="a", x=0, y=0, w=1, h=1))
    zm.add(RectZone(name="b", x=5, y=5, w=2, h=2))
    p = tmp_path / "zones.json"
    save(zm, p)
    zm2 = load(p)
    assert sorted(zm2.names()) == ["a", "b"]


# ── iso.combat ─────────────────────────────────────────────────────────────

def test_wavespec_round_trip() -> None:
    from pharos_engine.iso.combat import WaveSpec
    ws = WaveSpec(
        count=4, spawn_points=[(0, 5), (10, 5)],
        hp_each=40, interval=1.0, delay=0.5,
    )
    d = to_dict(ws)
    ws2 = from_dict(d)
    assert ws2.count == 4
    assert ws2.spawn_points == [(0.0, 5.0), (10.0, 5.0)]
    assert ws2.delay == pytest.approx(0.5)


def test_attacker_defender_round_trip() -> None:
    from pharos_engine.iso.combat import Attacker, Defender
    a = Attacker(pos=(3.0, 4.0), damage=5.0, reach=2.0, team="red")
    d_a = to_dict(a)
    a2 = from_dict(d_a)
    assert a2.pos == (3.0, 4.0)
    assert a2.damage == 5.0
    assert a2.team == "red"

    d = Defender(pos=(7.0, 8.0), hp=80.0, team="blue")
    d_d = to_dict(d)
    d2 = from_dict(d_d)
    assert d2.pos == (7.0, 8.0)
    assert d2.hp == 80.0


def test_waveschedule_round_trip(tmp_path: Path) -> None:
    from pharos_engine.iso.combat import WaveSchedule, WaveSpec
    ws = WaveSpec(count=2, spawn_points=[(0, 0)], hp_each=10, interval=1.0)
    sched = WaveSchedule([ws])
    p = tmp_path / "sched.yml"
    save(sched, p)
    sched2 = load(p)
    # Re-loaded schedule's internal _waves list mirrors the input specs.
    assert len(sched2._waves) == 1
    assert sched2._waves[0].spec.count == 2


# ── Telemetry ──────────────────────────────────────────────────────────────

def test_telemetry_history_round_trip(tmp_path: Path) -> None:
    from pharos_engine import telemetry
    telemetry.clear_history()
    telemetry.emit("physics.step", frame=1, dt=0.016)
    telemetry.emit("combat.hit", damage=5.0)
    hist = telemetry.get_event_history("*")
    assert len(hist) == 2
    p = tmp_path / "hist.json"
    save(hist, p)
    hist2 = load(p)
    assert len(hist2) == 2
    assert hist2[0].name == "physics.step"
    assert hist2[1].payload.get("damage") == 5.0


# ── SaveGame envelope ──────────────────────────────────────────────────────

def test_savegame_round_trip_yml(tmp_path: Path) -> None:
    from pharos_engine.dynamics import World, RopeSpec, build_rope
    from pharos_engine.thermal import HeatField
    from pharos_engine.zones import RectZone, ZoneManager

    world = World(gravity=(0.0, -9.81))
    build_rope(
        RopeSpec(node_count=8, total_length=2.0, mass_per_node=0.1,
                 stiffness=1e6, damping=0.01),
        world, anchor_a=(0.0, 0.0), anchor_b=(2.0, 0.0),
    )
    for _ in range(5):
        world.step(1.0 / 60.0)

    hf = HeatField(np.full((8, 8), 20.0, dtype=np.float64))
    zm = ZoneManager()
    zm.add(RectZone(name="goal", x=1, y=1, w=2, h=2))

    sg = SaveGame(world=world, thermal=hf, zones=zm, meta={"level": "tutorial"})
    p = tmp_path / "savegame.yml"
    save(sg, p)
    assert p.exists()
    sg2 = load(p)

    assert sg2.meta == {"level": "tutorial"}
    assert sg2.world is not None
    assert sg2.thermal is not None
    assert sg2.zones is not None
    # Dynamics determinism preserved.
    np.testing.assert_allclose(sg2.world.positions, world.positions, atol=1e-9)


def test_savegame_round_trip_json(tmp_path: Path) -> None:
    sg = SaveGame(meta={"score": 1234})
    p = tmp_path / "save.json"
    save(sg, p)
    sg2 = load(p)
    assert sg2.meta == {"score": 1234}


# ── Error paths ────────────────────────────────────────────────────────────

def test_save_rejects_unknown_suffix(tmp_path: Path) -> None:
    sg = SaveGame()
    with pytest.raises(ValueError, match=".json, .yml, or .yaml"):
        save(sg, tmp_path / "save.pickle")


def test_load_rejects_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load("/nonexistent/path/save.json")


def test_to_dict_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError, match="unsupported type"):
        to_dict(42)


def test_from_dict_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        from_dict({"_kind": "Mystery"})
