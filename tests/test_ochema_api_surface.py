"""Tripwire: lock the engine top-level names Ochema Circuit's RACE scene needs.

The RACE button on Ochema's main menu loads `scenes.race.RaceScene`, which
chain-imports through entities.track_background / track_city / track_mountain.
That chain reaches for `slappyengine.CatmullRomSpline`, `SplineTrack`,
`PlayerInputProvider`, `CacheMode`, `PixelCollisionPass`. Plus the rendering
passes the race scene composes (DofPass, GTAOPass, MotionBlurPass, etc.).

Adding new entries below is fine — removing one means a real game breaks.
"""
from __future__ import annotations

import importlib

import pytest


_CONTRACT = [
    # vehicle scene (softbody.vehicle re-exports)
    "build_vehicle", "VehicleSpec", "WheelSpec", "apply_drivetrain_torque",
    # track + spline
    "CatmullRomSpline", "SplineTrack",
    # input
    "PlayerInputProvider",
    # residency / collision
    "CacheMode", "PixelCollisionPass",
    # rendering passes Ochema uses
    "DofPass", "GTAOPass", "MotionBlurPass",
    "RenderPass", "NightVisionPass",
    # GI
    "RadianceCascadeConfig", "LightingContext",
    # sim
    "SimFrequencyBudget", "SimState", "DeformController",
]


@pytest.mark.parametrize("name", _CONTRACT)
def test_engine_exposes(name: str) -> None:
    """slappyengine.<name> must resolve. Lazy-load is fine."""
    mod = importlib.import_module("slappyengine")
    assert hasattr(mod, name), (
        f"slappyengine.{name} is missing — Ochema's RACE scene will fail "
        f"to chain-import. Add {name!r} to _LAZY_MAP in "
        "python/slappyengine/__init__.py."
    )
    # touching the attribute triggers the lazy resolve; must not raise
    getattr(mod, name)
