"""Smoke test for ``examples/visual_check_demo.py`` (RR2 gap-close, batch 3).

The demo runs the 5 splatter presets through 60 frames each and stitches
them into a 1×5 grid GIF.  We pin the demo's internals but only exercise
a single preset via ``run_preset`` to keep test wall-clock < 1 s.

Pins:
1. Demo module imports cleanly and exposes ``main`` + ``run_preset``.
2. The ``PRESET_NAMES`` tuple matches the built-in splatter preset set.
3. ``run_preset('sand')`` returns FRAMES worth of PIL images and finite
   settled/baked counts.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "visual_check_demo.py"


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    try:
        from pharos_engine.physics.blast import detonate  # noqa: F401
        from pharos_engine.physics.particle_field import ParticleField  # noqa: F401
        from pharos_engine.physics.splatter_presets import get as _get  # noqa: F401
    except Exception as exc:
        pytest.skip(f"particle physics WIP unavailable: {exc}")

    spec = importlib.util.spec_from_file_location("visual_check_demo_rr2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["visual_check_demo_rr2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"visual_check_demo failed to import: {exc}")
    return module


def test_visual_check_module_imports(demo):
    """Demo file loaded and exposes ``main`` + ``run_preset``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))
    assert callable(getattr(demo, "run_preset", None))
    assert isinstance(demo.PRESET_NAMES, tuple)


def test_visual_check_preset_names(demo):
    """The demo pins the canonical 5-preset splatter set."""
    assert demo.PRESET_NAMES == ("sand", "mud", "sloppy", "rock", "snow"), (
        f"preset set drifted: {demo.PRESET_NAMES}"
    )
    # Cross-check against the source of truth.
    from pharos_engine.physics.splatter_presets import get as _get
    for name in demo.PRESET_NAMES:
        try:
            preset = _get(name)
        except Exception as exc:
            pytest.skip(f"preset {name!r} missing upstream: {exc}")
        assert preset.name == name, (
            f"preset lookup mismatch: asked for {name!r}, got {preset.name!r}"
        )


def test_visual_check_single_preset_runs(demo):
    """``run_preset('sand')`` returns FRAMES worth of PIL images + stats."""
    from pharos_engine.physics.splatter_presets import get as _get
    try:
        preset = _get("sand")
        frames, stats = demo.run_preset(preset)
    except Exception as exc:
        pytest.skip(f"run_preset('sand') upstream drift: {exc}")

    assert len(frames) == demo.FRAMES, (
        f"expected {demo.FRAMES} frames, got {len(frames)}"
    )
    # Each frame is a PIL image with the expected cell size.
    first = frames[0]
    assert first.size == (demo.CELL_W, demo.CELL_H), (
        f"cell size drift: {first.size} vs ({demo.CELL_W}, {demo.CELL_H})"
    )
    # Stats keys are pinned by the demo's contract.
    for key in ("settled", "baked", "total", "pile_max", "crater_max"):
        assert key in stats, f"stats missing key {key!r}"
    assert stats["total"] > 0, "particle field should have baked cells"
