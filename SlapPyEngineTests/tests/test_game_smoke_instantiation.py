"""Game-compat smoke instantiation — one step past the surface tripwire.

The sibling :mod:`tests.test_game_compat_tripwire` locks down *importability* —
each ``(game, name)`` pair in the engine-surface contract must resolve off the
``slappyengine`` package. That catches the "deleted a public name" class of
regression, but it doesn't catch the "name imports but blows up on first
construction" class — which is exactly the failure mode that ships to a game
team in the next ``pip install`` and turns into a same-day rollback.

This file goes the extra step: for each game-required class with a defaulted
or trivially-constructable initialiser, we instantiate it and run one minimal
behaviour tick where applicable (e.g. ``EventBus.publish`` / ``DataComponent.set``
/ ``WaveSchedule.tick``). The Stone Keep iso-combat path is exercised end-to-end
across 100 frames as a NaN tripwire so regressions in the wave scheduler /
attacker-defender math surface here rather than in a downstream game.

Symbols that the engine surface declares but whose *underlying module* is not
yet present on master (the residual Phase C / phase-rollback gap) are tracked
in :data:`_MISSING_MODULES`. Each pair is marked ``xfail(strict=False)`` so
this file stays green while the gap is visible. Removing an entry here without
landing the underlying module is a regression — the strict-once tripwire test
will fire as soon as the symbol is re-added without the module behind it.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Phase C residual gaps — symbol exported in __init__._LAZY_MAP but the
# underlying module is not yet on master. Marked xfail so this test file
# stays green; the sibling tripwire test still reports the gap.
# ---------------------------------------------------------------------------

_MISSING_MODULES: dict[str, str] = {
    "TriggerSystem":           "slappyengine.trigger",
    "TriggerVolume":           "slappyengine.trigger",
    "ZoneMap":                 "slappyengine.deform_zones",
    "CrackMode":               "slappyengine.deform_modes",
    "MaterialPreset":          "slappyengine.deform_modes",
    "PixelMaterialMap":        "slappyengine.pixel_material",
    "SimFrequencyBudget":      "slappyengine.deform_controller",
    "SimState":                "slappyengine.deform_controller",
    "DeformController":        "slappyengine.deform_controller",
    "build_vehicle":           "slappyengine.softbody.vehicle",
    "VehicleSpec":             "slappyengine.softbody.vehicle",
    "WheelSpec":               "slappyengine.softbody.vehicle",
    "apply_drivetrain_torque": "slappyengine.softbody.vehicle",
    "CatmullRomSpline":        "slappyengine.spline",
    "SplineTrack":             "slappyengine.track",
    "PlayerInputProvider":     "slappyengine.input_provider",
    "PixelCollisionPass":      "slappyengine.collision_pixel",
    "MotionBlurPass":          "slappyengine.post_process.motion_blur",
}


# ---------------------------------------------------------------------------
# Phase C closure surface — these classes / modules MUST resolve and behave.
# Each test below isolates one game-required name so the failure message
# pins the regression to a specific export.
# ---------------------------------------------------------------------------


# ── EventBus + module-level publish/subscribe ───────────────────────────────

def test_event_bus_publish_subscribe_class() -> None:
    """``EventBus`` instance pub/sub round-trip — Bullet Strata reactive HUD.

    The engine's EventBus uses kwargs payloads (``bus.publish(topic, **payload)``)
    so subscribers receive a dict on dispatch. This pins that contract — the
    HUD pattern relies on it.
    """
    from slappyengine import EventBus

    bus = EventBus()
    received: list[Any] = []
    bus.subscribe("Pickup.Acquired", lambda payload: received.append(payload))
    bus.publish("Pickup.Acquired", item="shotgun")
    assert received == [{"item": "shotgun"}]


def test_event_bus_module_level_publish_subscribe() -> None:
    """``event_bus.publish``/``subscribe`` module-level helpers — Phase C item."""
    from slappyengine import event_bus

    received: list[Any] = []
    event_bus.subscribe("Test.Topic", lambda payload: received.append(payload))
    event_bus.publish("Test.Topic", value=42)
    assert received == [{"value": 42}], (
        "module-level event_bus.publish/subscribe lost — would break game-side "
        "wiring that depends on the global bus surface added in Phase C."
    )


# ── DataComponent — Bullet Strata reactive HUD watcher ───────────────────────

def test_data_component_set_get_watch() -> None:
    """DataComponent set/get + .watch — Bullet Strata HUD dirty flag wiring.

    The engine's DataComponent uses kwargs-style set (``dc.set(ammo=30)``)
    + per-key get. Pin both the kwarg-set contract and the .watch attribute
    that the HUD's reactive dirty-flag pattern relies on.
    """
    from slappyengine import DataComponent

    dc = DataComponent()
    dc.set(ammo=30)
    assert dc.get("ammo") == 30

    # .watch must exist — the dirty-flag HUD pattern subscribes here.
    assert hasattr(dc, "watch"), (
        "DataComponent.watch missing — would break Bullet Strata HUD reactive "
        "dirty-flag pattern (per project_bullet_strata.md)."
    )


# ── Observable — Phase C auto-publish base class ─────────────────────────────

def test_observable_construct_and_publish() -> None:
    """``Observable`` default ctor + auto-publish via .set on subscribed bus."""
    from slappyengine import EventBus, Observable

    bus = EventBus()
    obs = Observable(bus=bus, topic="player.state")
    captured: list[Any] = []
    bus.subscribe("player.state", lambda payload: captured.append(payload))

    # Observable uses kwargs-style notify (matches EventBus.publish signature).
    if hasattr(obs, "notify"):
        obs.notify(strata_layer=0)
    elif hasattr(obs, "publish"):
        obs.publish(strata_layer=0)
    elif hasattr(obs, "set"):
        obs.set(strata_layer=0)
    else:
        pytest.fail(
            "Observable has no publish/notify/set method — game-side auto-"
            "publish pattern would break."
        )

    assert captured == [{"strata_layer": 0}]


# ── CacheMode — Phase C enum on ResidencyManager ─────────────────────────────

def test_cache_mode_enum_values() -> None:
    """``CacheMode`` is an Enum with GPU / RAM / DISK members."""
    from slappyengine import CacheMode

    names = {m.name for m in CacheMode}
    assert {"GPU", "RAM", "DISK"}.issubset(names), (
        f"CacheMode missing one of GPU/RAM/DISK; got {names}"
    )


# ── StrataWorld / StrataLayer — Bullet Strata core primitive ────────────────

def test_strata_world_construct_with_layers() -> None:
    """``StrataWorld(layers=[StrataLayer(...)])`` — Bullet Strata world ctor."""
    from slappyengine import StrataLayer, StrataWorld

    layers = [
        StrataLayer(name="bg",    index=0, tint=(0.5, 0.5, 0.6, 1.0), parallax=0.5),
        StrataLayer(name="play",  index=1, tint=(1.0, 1.0, 1.0, 1.0), parallax=1.0),
        StrataLayer(name="fg",    index=2, tint=(0.9, 0.9, 1.0, 1.0), parallax=1.4),
    ]
    world = StrataWorld(layers=layers)
    # The world must expose its layers in index order — game code iterates
    # them for the strata-shift transition tint.
    assert len(world.layers) == 3
    assert world.layers[1].name == "play"


# ── ParticleEmitter (CPU) — defaults to no GPU ──────────────────────────────

def test_particle_emitter_default_construct_and_tick() -> None:
    """``ParticleEmitter()`` default ctor + emit + tick — no GPU needed."""
    from slappyengine import ParticleEmitter

    em = ParticleEmitter()
    em.emit(count=8, position=(32.0, 32.0), color=(255, 64, 64), lifetime=0.5)
    em.tick(1.0 / 60.0)
    # tick must produce a texture; shape (H, W, 4) uint8.
    assert em.texture_data.shape == (64, 64, 4)


# ── GpuParticleSystem — needs a wgpu ctx, mock it ───────────────────────────

def test_gpu_particle_system_construct_with_mock_ctx() -> None:
    """``GpuParticleSystem(ctx, max_particles=...)`` — Bullet Strata muzzle FX."""
    from slappyengine import GpuParticleSystem

    ctx = MagicMock()
    ctx.device.create_buffer.return_value = MagicMock()
    ctx.device.create_shader_module.return_value = MagicMock()
    ctx.device.create_bind_group_layout.return_value = MagicMock()
    ctx.device.create_bind_group.return_value = MagicMock()
    ctx.device.create_pipeline_layout.return_value = MagicMock()
    ctx.device.create_compute_pipeline.return_value = MagicMock()

    gps = GpuParticleSystem(ctx=ctx, max_particles=8)
    assert gps.max_particles == 8


# ── audio_runtime — Phase C module ──────────────────────────────────────────

def test_audio_runtime_module_get_backend() -> None:
    """``audio_runtime.get_backend()`` returns an :class:`AudioBackend`."""
    from slappyengine import audio_runtime

    backend = audio_runtime.get_backend()
    assert backend is not None
    # AudioBackend protocol — at minimum the stub must accept ``stop_all``.
    assert hasattr(backend, "stop_all") or hasattr(backend, "play")


# ── Script base class — Bullet Strata systems subclass this ─────────────────

def test_script_default_construct() -> None:
    """``Script()`` default ctor — must allow zero-arg subclass init."""
    from slappyengine import Script

    s = Script()
    assert s is not None


# ── zones surface — Stone Keep + Bullet Strata damage zones ─────────────────

def test_zones_rect_zone_construct() -> None:
    """``zones.RectZone`` + ``ZoneManager`` enter/exit round-trip."""
    from slappyengine.zones import RectZone, ZoneManager

    mgr = ZoneManager()
    entered: list[Any] = []
    zone = RectZone(
        name="pad", x=0.0, y=0.0, w=10.0, h=10.0,
        on_enter=lambda eid: entered.append(eid),
    )
    mgr.add(zone)
    mgr.update({"player": (5.0, 5.0)})
    assert entered == ["player"]


def test_zones_threshold_zone_construct() -> None:
    """``zones.ThresholdZone`` fires at threshold + re-arms on recovery."""
    from slappyengine.zones import ThresholdZone, ZoneManager

    mgr = ZoneManager()
    fired: list[float] = []
    z = ThresholdZone(
        name="hull", x=0.0, y=0.0, w=10.0, h=10.0,
        threshold=0.5, hysteresis=0.1,
        on_threshold=lambda v: fired.append(v),
    )
    mgr.add(z)
    mgr.update_threshold("hull", 0.4)  # below threshold → fire
    assert fired == [0.4]
    mgr.update_threshold("hull", 0.7)  # re-arm
    mgr.update_threshold("hull", 0.3)  # below → fire again
    assert fired == [0.4, 0.3]


# ── Stone Keep — iso.combat WaveSchedule + iso primitives ───────────────────

def test_stone_keep_wave_schedule_100_frames_no_nan() -> None:
    """100-frame ``WaveSchedule`` sim + iso primitives — Stone Keep tripwire.

    Constructs a 2-wave schedule (5 spawns total), runs 100 ticks at 30 fps,
    and asserts every spawned Defender has finite hp + finite world position
    (NaN tripwire), the schedule completes within the budget, and a Defender
    in :func:`resolve_attack` range gets killed off across repeated attacks.
    """
    import math

    from slappyengine.iso import IsoEntity, IsoGrid, IsoScene, IsoTileDef
    from slappyengine.iso.combat import (
        Attacker,
        Defender,
        WaveSchedule,
        WaveSpec,
        resolve_attack,
    )

    # iso primitives: build a small grid + scene + entity
    scene = IsoScene(grid_w=10, grid_h=10, grid_d=2)
    assert isinstance(scene.grid, IsoGrid)
    floor = IsoTileDef("floor", "mock.png")
    scene.grid.set_tile(0, 0, 0, floor)
    hero = IsoEntity(grid_x=3.0, grid_y=3.0)
    scene.add_iso_entity(hero)

    # 2-wave schedule: 3 spawns then 2 spawns.
    waves = [
        WaveSpec(
            count=3,
            spawn_points=[(0.0, 0.0), (1.0, 1.0)],
            hp_each=10.0,
            interval=0.5,
            delay=0.1,
        ),
        WaveSpec(
            count=2,
            spawn_points=[(2.0, 2.0)],
            hp_each=5.0,
            interval=0.25,
        ),
    ]
    sched = WaveSchedule(waves)

    dt = 1.0 / 30.0
    all_spawned: list[Defender] = []
    for _ in range(100):
        all_spawned.extend(sched.tick(dt))

    assert sched.finished, "schedule did not complete within 100 frames"
    assert len(all_spawned) == 5, (
        f"expected 5 total spawns across both waves, got {len(all_spawned)}"
    )

    # NaN tripwire on every spawned Defender's hp + position.
    for d in all_spawned:
        assert math.isfinite(d.hp), f"NaN hp on defender {d}"
        assert math.isfinite(d.pos[0]) and math.isfinite(d.pos[1]), (
            f"NaN position on defender {d}"
        )

    # resolve_attack: an attacker at (0, 0) with reach 5 + damage 4 should
    # kill every spawned defender within 3 swings (all of them are within
    # reach; max hp is 10 so 3 * 4 = 12 dmg suffices).
    atk = Attacker(pos=(0.0, 0.0), damage=4.0, reach=5.0)
    alive: list[Defender] = list(all_spawned)
    for _ in range(3):
        survivors: list[Defender] = []
        for d in alive:
            _dmg, still_alive = resolve_attack(atk, d)
            if still_alive:
                survivors.append(d)
        alive = survivors
    assert alive == [], (
        f"resolve_attack failed to kill all defenders in range; "
        f"{len(alive)} survivors remain"
    )


# ---------------------------------------------------------------------------
# Phase C closed-gap surface — every symbol previously tracked in
# :data:`_MISSING_MODULES` now resolves off the master ``slappyengine``
# package. The parametrised test below enforces that as a forward-looking
# regression tripwire: if a symbol disappears from the export surface, this
# test fails outright (no longer xfail-cushioned) and the sibling tripwire
# test pinpoints which game-team surface broke.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "symbol,module",
    sorted(_MISSING_MODULES.items()),
    ids=sorted(_MISSING_MODULES),
)
def test_missing_module_residual_gap(symbol: str, module: str) -> None:
    """One assertion per previously-missing Phase C symbol — must resolve now."""
    import slappyengine
    assert hasattr(slappyengine, symbol), (
        f"{symbol} regressed off the public surface — module {module} "
        f"was previously a Phase C residual gap that has been closed; "
        f"removing it again would re-break game-team installs."
    )
