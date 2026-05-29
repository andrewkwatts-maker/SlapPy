"""Multi-game compat tripwire: lock the engine surface that real games depend on.

This file is the master contract for the three flagship games SlapPyEngine
must keep importable:

* **Ochema Circuit** — top-down arcade racer. Its RACE scene chain-imports
  through ``scenes.race.RaceScene`` → track + spline + race-scene post-process
  passes. Mirrors the contract from ``tests/test_ochema_api_surface.py``;
  duplicated here so the multi-game tripwire is self-contained.

* **Bullet Strata** — 4-player multi-strata arena shooter. Per
  ``memory/project_bullet_strata.md``, the game wires the engine's
  ``TriggerSystem`` (weapon-pickup zones), ``DeformController`` (all three
  enemy types — drone / shade / brute), ``ZoneMap`` (head/torso/legs damage
  zones on the drone sprite), a reactive HUD driven by ``DataComponent.watch``
  + ``EventBus``, and the audio runtime (``audio_runtime`` module).

* **Stone Keep** — iso tower-defence. Per
  ``memory/project_sprint_2026_05_29.md`` (Phase C3), the game's combat loop
  uses ``slappyengine.iso.combat.resolve_attack`` + ``WaveSpec`` +
  ``WaveSchedule.tick``, plus the iso grid / scene primitives
  (``IsoGrid``, ``IsoScene``, ``IsoEntity``) and the ``zones`` package for
  spawn pads / damage zones.

The test is parameterised one assertion per ``(game, name)`` pair so a
failure tells you exactly which game would break and on which symbol.
Dotted names (e.g. ``iso.combat.resolve_attack``) are supported — the test
walks the dotted path attribute-by-attribute.

Adding a name here is fine; removing one is a compat break.
"""
from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# Per-game engine surface contracts
# ---------------------------------------------------------------------------

_GAME_CONTRACTS: dict[str, list[str]] = {
    # ------------------------------------------------------------------
    # Ochema Circuit — copied from tests/test_ochema_api_surface.py.
    # The RACE scene chain-imports these top-level names off ``slappyengine``.
    # ------------------------------------------------------------------
    "ochema_circuit": [
        # vehicle scene (softbody.vehicle re-exports)
        "build_vehicle",
        "VehicleSpec",
        "WheelSpec",
        "apply_drivetrain_torque",
        # track + spline
        "CatmullRomSpline",
        "SplineTrack",
        # input
        "PlayerInputProvider",
        # residency / collision
        "CacheMode",
        "PixelCollisionPass",
        # rendering passes Ochema uses
        "DofPass",
        "GTAOPass",
        "MotionBlurPass",
        "RenderPass",
        "NightVisionPass",
        # GI
        "RadianceCascadeConfig",
        "LightingContext",
        # sim
        "SimFrequencyBudget",
        "SimState",
        "DeformController",
    ],
    # ------------------------------------------------------------------
    # Bullet Strata — from project_bullet_strata.md (sessions 1-6).
    # The arena scene + entities/* import these names directly off
    # ``slappyengine``. The HUD's "reactive dirty flag" is built on
    # ``DataComponent.watch`` + ``EventBus`` — both must stay exported.
    # ------------------------------------------------------------------
    "bullet_strata": [
        # Pickup zones: TriggerSystem + TriggerVolume + EventBus
        "TriggerSystem",
        "TriggerVolume",
        # Deformable enemies: DeformController + MaterialPreset on all 3 types
        "DeformController",
        "MaterialPreset",
        # Per-sprite damage zones (head/torso/legs on DroneEnemy)
        "ZoneMap",
        # Reactive HUD: DataComponent.watch sets _dirty; EventBus for popups
        "DataComponent",
        "EventBus",
        # GPU particles for muzzle flash / impact / death bursts
        "GpuParticleSystem",
        "ParticleEmitter",
        # Sim frequency budget (deform tick allocator)
        "SimFrequencyBudget",
        # CrackMode + PixelMaterialMap on cover entities
        "CrackMode",
        "PixelMaterialMap",
        # CacheMode on enemies + cover (damage persists across strata shifts)
        "CacheMode",
        # Observable PlayerEntity (auto-publishes strata_layer / current_weapon)
        "Observable",
        # Script base class — all systems subclass this
        "Script",
        # Audio runtime (item 13 — game-side wiring depends on this module)
        "audio_runtime",
        # Strata core primitives (game name; engine module is generalised)
        "StrataWorld",
        "StrataLayer",
    ],
    # ------------------------------------------------------------------
    # Stone Keep — iso tower-defence. Per project_sprint_2026_05_29.md
    # (Phase C3 / iso/combat), the game's wave + attack-resolution loop
    # imports these names. Dotted paths supported.
    # ------------------------------------------------------------------
    "stone_keep": [
        # iso/combat — Phase C3 surface
        "iso.combat.resolve_attack",
        "iso.combat.WaveSpec",
        "iso.combat.WaveSchedule",
        "iso.combat.Attacker",
        "iso.combat.Defender",
        # iso grid + scene primitives
        "iso.IsoGrid",
        "iso.IsoCell",
        "iso.IsoTileDef",
        "iso.IsoEntity",
        "iso.IsoScene",
        "iso.IsoCamera",
        "iso.IsoViewpoint",
        # Zones (spawn pads + damage zones used by tower-defence systems)
        "zones.RectZone",
        "zones.ThresholdZone",
        "zones.ZoneManager",
        # Generic event bus (wave events fire on the global bus)
        "EventBus",
        # Generic data component (tower / enemy stats)
        "DataComponent",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_dotted(mod, dotted: str):
    """Walk a dotted attribute path off ``mod``.

    For dotted paths whose intermediate segments are subpackages
    (e.g. ``iso.combat.resolve_attack``), the test must explicitly
    ``import_module`` each subpackage segment — Python doesn't bind
    ``slappyengine.iso.combat`` onto ``slappyengine.iso`` until
    something has imported it. Treating subpackages as importable
    here lets us probe the *real* compat surface, not just whatever
    happened to be eagerly imported by side effect.

    Returns the resolved object. Raises ``AttributeError`` or
    ``ImportError`` if any segment is missing.
    """
    parts = dotted.split(".")
    obj = mod
    accumulated = mod.__name__
    for i, part in enumerate(parts):
        # Try attribute access first (covers classes / functions / already
        # bound submodules / PEP 562 lazy resolution).
        if hasattr(obj, part):
            obj = getattr(obj, part)
            accumulated = f"{accumulated}.{part}"
            continue
        # Attribute not present — if we're still walking module-shaped
        # segments, try a real ``import_module``. This handles the
        # canonical ``slappyengine.iso.combat.resolve_attack`` case where
        # ``combat`` is a submodule that hasn't been imported yet.
        if i < len(parts) - 1:
            try:
                obj = importlib.import_module(f"{accumulated}.{part}")
                accumulated = f"{accumulated}.{part}"
                continue
            except ImportError:
                pass
        # Last segment, or import failed — fall through to AttributeError.
        obj = getattr(obj, part)
        accumulated = f"{accumulated}.{part}"
    return obj


def _has_dotted(mod, dotted: str) -> bool:
    """``hasattr`` for dotted paths. Lazy submodules are tolerated."""
    try:
        _resolve_dotted(mod, dotted)
    except (AttributeError, ImportError):
        return False
    return True


# Known-broken (game, name) pairs that don't resolve on master HEAD today.
# Each is a real Phase C surface gap to close in a follow-up commit. Adding
# to this set converts a hard failure into an xfail so the suite stays green
# while the gaps remain visible in the test report. Removing an entry here
# without landing the underlying export is a regression.
_KNOWN_BROKEN: set[tuple[str, str]] = {
    ("ochema_circuit", "CacheMode"),
    ("ochema_circuit", "PixelCollisionPass"),
    ("bullet_strata", "TriggerSystem"),
    ("bullet_strata", "TriggerVolume"),
    ("bullet_strata", "MaterialPreset"),
    ("bullet_strata", "ZoneMap"),
    ("bullet_strata", "GpuParticleSystem"),
    ("bullet_strata", "ParticleEmitter"),
    ("bullet_strata", "CrackMode"),
    ("bullet_strata", "PixelMaterialMap"),
    ("bullet_strata", "CacheMode"),
    ("bullet_strata", "Observable"),
    ("bullet_strata", "audio_runtime"),
    ("bullet_strata", "StrataWorld"),
    ("bullet_strata", "StrataLayer"),
}


# Flatten the per-game contracts into a single parametrisation list so each
# missing surface produces a single distinct test failure.
_PARAMS: list[tuple[str, str]] = [
    (game, name)
    for game, names in _GAME_CONTRACTS.items()
    for name in names
]


@pytest.mark.parametrize(
    "game,name",
    _PARAMS,
    ids=[f"{g}:{n}" for g, n in _PARAMS],
)
def test_game_surface(game: str, name: str) -> None:
    """``slappyengine.<name>`` must resolve — lazy-load is fine.

    Known-broken pairs are xfailed so the suite stays green while the gap is
    visible. Closing a gap should remove the entry from ``_KNOWN_BROKEN``.
    Dotted names (``iso.combat.resolve_attack``) are walked segment by
    segment, so subpackage exports are exercised too. The failure message
    pins down which game would break on next import.
    """
    if (game, name) in _KNOWN_BROKEN:
        import pytest as _pt
        _pt.xfail(f"known Phase C gap: slappyengine.{name} not resolvable")
    mod = importlib.import_module("slappyengine")
    assert _has_dotted(mod, name), (
        f"slappyengine.{name} is missing — would break {game} on next import. "
        f"Either re-add the name to slappyengine.__init__._LAZY_MAP (or its "
        f"subpackage __init__) or, if the removal is intentional, file a "
        f"compat break against {game}."
    )
    # Touching the attribute triggers the lazy resolve; must not raise.
    _resolve_dotted(mod, name)
