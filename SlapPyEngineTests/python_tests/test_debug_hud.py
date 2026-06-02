"""Tests for slappyengine.physics.debug_hud.DebugHUD."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from slappyengine.physics.debug_hud import DebugHUD


# ---------------------------------------------------------------------------
# Minimal stand-ins for PhysicsWorld / PhysicsBody so the HUD tests stay
# decoupled from the (large, concurrently-edited) world.py module.
# ---------------------------------------------------------------------------


@dataclass
class _StubBody:
    mass: float = 1.0
    velocity: tuple[float, float] = (0.0, 0.0)
    cells: np.ndarray | None = None


@dataclass
class _StubWorld:
    bodies: list[Any] = field(default_factory=list)
    _last_substeps: int = 0


def _blank_frame(h: int = 90, w: int = 240) -> np.ndarray:
    """Pure-black RGBA frame for HUD readback assertions."""
    return np.zeros((h, w, 4), dtype=np.uint8)


def test_hud_renders_visible_text():
    """The HUD writes non-zero pixels into the upper-left region."""
    hud = DebugHUD()
    world = _StubWorld(bodies=[_StubBody(mass=2.0, velocity=(1.0, 0.0))])
    frame = _blank_frame()

    out = hud.render(frame, world, frame_idx=0, contact_count=0)

    assert out.shape == frame.shape
    px, py = hud.position
    # Read a 200x60 window starting at the HUD anchor (clamped to frame).
    region = out[py : py + 60, px : px + 200, :3]
    assert region.size > 0
    assert int(region.sum()) > 0, "expected HUD to draw visible pixels"


def test_hud_includes_frame_number():
    """Changing frame_idx changes the rendered pixels (digits differ)."""
    hud = DebugHUD()
    world = _StubWorld(bodies=[])
    frame_a = hud.render(_blank_frame(), world, frame_idx=0, contact_count=0)
    frame_b = hud.render(_blank_frame(), world, frame_idx=42, contact_count=0)

    # Restrict to the HUD region to avoid being misled by global noise.
    px, py = hud.position
    region_a = frame_a[py : py + 60, px : px + 200, :3]
    region_b = frame_b[py : py + 60, px : px + 200, :3]
    assert not np.array_equal(region_a, region_b), (
        "frame_idx change should produce a different HUD readout"
    )


def test_hud_with_no_world_doesnt_crash():
    """An empty world (no bodies) renders without raising."""
    hud = DebugHUD()
    empty_world = _StubWorld(bodies=[])
    out = hud.render(_blank_frame(), empty_world, frame_idx=7, contact_count=0)
    assert out.shape == (90, 240, 4)
    # And the HUD region still has *some* drawn pixels (the panel + text).
    px, py = hud.position
    region = out[py : py + 60, px : px + 200, :3]
    assert int(region.sum()) > 0


def test_hud_toggles_work():
    """With every metric toggled off, only the background panel is drawn."""
    hud = DebugHUD(
        show_frame_number=False,
        show_body_count=False,
        show_contact_count=False,
        show_mass=False,
        show_energy=False,
        show_heat=False,
        show_substeps=False,
    )
    # Bright white text on a fully-opaque black panel, to make the
    # "text vs panel" comparison trivial.
    hud.background_color = (0, 0, 0, 255)
    hud.text_color = (255, 255, 255)

    world = _StubWorld(bodies=[_StubBody()])
    out = hud.render(_blank_frame(), world, frame_idx=99, contact_count=12)

    px, py = hud.position
    # Only the small panel area should have been drawn; pick the interior
    # of the panel and assert there are no bright-white text pixels.
    panel = out[py : py + 20, px : px + 80, :3]
    # Background is opaque black, so panel pixels must equal (0, 0, 0).
    assert int(panel.max()) == 0, "no text should be drawn when all toggles are off"
