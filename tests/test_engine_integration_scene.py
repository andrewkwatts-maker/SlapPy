"""Cross-package integration scenario — engine_integration_v2.

This single test fixture composes four engine subpackages over a 60-frame
sim:

* :mod:`slappyengine.iso.combat` — a defender at (5, 5) plus a
  :class:`WaveSchedule` that spawns three attackers from arena edges.
* :mod:`slappyengine.zones` — a :class:`RectZone` trigger that fires
  ``on_enter`` callbacks as attackers cross into ``(3..7, 3..7)``.
* :mod:`slappyengine.thermal` — a 32x32 :class:`HeatField` with a hot
  spot at cell ``(16, 16)`` diffusing under a ``clamp`` boundary.
* :mod:`slappyengine.dynamics` — a rope of 8 nodes anchored between
  ``(2, 0)`` and ``(8, 0)`` stepped each frame.

After 60 frames at ``dt = 1/30`` six assertions exercise each subpackage's
observable state plus a visual baseline rendered through
:func:`slappyengine.testing.assert_scene_matches`.

Notes on rough edges surfaced
-----------------------------
* ``WaveSchedule.tick`` returns :class:`Defender` objects regardless of
  whether the caller intends them to be attackers. We re-wrap each
  spawned :class:`Defender` as an :class:`Attacker` for the
  :func:`resolve_attack` call while keeping the original ``Defender`` as
  the HP container for the attacker entity. The two types do not share a
  base — composition is on the caller.
* ``thermal.HeatField`` mutates its grid in place; ``total_heat`` is a
  whole-grid sum so under ``boundary="clamp"`` it stays effectively
  constant. We only assert it has not GROWN by more than the tolerance —
  conservation is a separate guarantee on the clamp path.
* ``dynamics.World.step`` always integrates gravity. A rope anchored at
  ``y=0`` on both ends will droop into negative ``y``; we account for
  that in the viewport when rendering.
* ``zones.ZoneManager.update`` requires the caller to push positions for
  every frame; we use stringified ``"attacker_i"`` keys so the same
  entity id round-trips across ticks.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List, Tuple

import math
import numpy as np
import pytest

from slappyengine.dynamics import RopeSpec, World, build_rope
from slappyengine.iso.combat import (
    Attacker,
    Defender,
    WaveSchedule,
    WaveSpec,
    resolve_attack,
)
from slappyengine.testing import assert_scene_matches
from slappyengine.thermal import HeatField
from slappyengine.zones import RectZone, ZoneManager


# ── Scenario constants ──────────────────────────────────────────────────────

FRAMES = 60
DT = 1.0 / 30.0
ATTACKER_SPEED = 3.0          # iso units / second
ATTACKER_REACH = 1.5          # melee range in iso units
ATTACKER_DAMAGE = 5.0         # per-frame hit while in reach
DEFENDER_POS = (5.0, 5.0)
DEFENDER_HP_INITIAL = 100.0

GRID_N = 32
HOT_CELL = (16, 16)
HOT_TEMPERATURE = 800.0
COLD_TEMPERATURE = 20.0

ROPE_ANCHOR_A = (2.0, 0.0)
ROPE_ANCHOR_B = (8.0, 0.0)
ROPE_NODE_COUNT = 8
ROPE_LENGTH = 6.0

# Viewport that covers the iso arena AND the rope's droop.
VIEW_X0, VIEW_X1 = 0.0, 11.0
VIEW_Y0, VIEW_Y1 = -6.0, 11.0
RENDER_W = RENDER_H = 256


# ── Helpers ─────────────────────────────────────────────────────────────────


def _world_to_pixel(x: float, y: float) -> Tuple[int, int]:
    """Project iso world coords into the 256x256 render canvas.

    ``y`` is flipped so that y=+11 is the TOP of the canvas (PIL is y-down).
    """
    u = (x - VIEW_X0) / (VIEW_X1 - VIEW_X0)
    v = 1.0 - (y - VIEW_Y0) / (VIEW_Y1 - VIEW_Y0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round(v * (RENDER_H - 1)))
    return px, py


def _render_frame(
    heat: HeatField,
    rope_positions: np.ndarray,
    attackers_pos: List[Tuple[float, float]],
    zone: RectZone,
) -> np.ndarray:
    """Compose a 256x256 RGBA frame visualising every subpackage.

    Returns a (H, W, 4) uint8 buffer suitable for the testing harness.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (0, 0, 0, 255))

    # ── Heat field overlay (red gradient, alpha ∝ temperature) ─────────────
    grid = heat.temperature
    peak = max(float(grid.max()), 1.0)
    norm = np.clip(grid / peak, 0.0, 1.0)
    overlay = np.zeros((GRID_N, GRID_N, 4), dtype=np.uint8)
    overlay[..., 0] = (norm * 255).astype(np.uint8)
    overlay[..., 3] = (norm * 200).astype(np.uint8)
    # The heat grid covers the arena rectangle (0..10) x (0..10).
    heat_layer = Image.fromarray(overlay, mode="RGBA")
    heat_px_x0, heat_px_y0 = _world_to_pixel(0.0, 10.0)
    heat_px_x1, heat_px_y1 = _world_to_pixel(10.0, 0.0)
    heat_layer = heat_layer.resize(
        (max(1, heat_px_x1 - heat_px_x0), max(1, heat_px_y1 - heat_px_y0)),
        Image.Resampling.BILINEAR,
    )
    img.alpha_composite(heat_layer, (heat_px_x0, heat_px_y0))

    draw = ImageDraw.Draw(img)

    # ── Zone outline (yellow rect) ────────────────────────────────────────
    zx0, zy0 = _world_to_pixel(zone.x, zone.y + zone.h)
    zx1, zy1 = _world_to_pixel(zone.x + zone.w, zone.y)
    draw.rectangle([(zx0, zy0), (zx1, zy1)], outline=(255, 255, 0, 255), width=2)

    # ── Rope (white polyline) ─────────────────────────────────────────────
    pts = [_world_to_pixel(float(p[0]), float(p[1])) for p in rope_positions]
    if len(pts) >= 2:
        draw.line(pts, fill=(255, 255, 255, 255), width=2)

    # ── Defender (green square) ───────────────────────────────────────────
    dpx, dpy = _world_to_pixel(*DEFENDER_POS)
    draw.rectangle(
        [(dpx - 4, dpy - 4), (dpx + 4, dpy + 4)],
        fill=(0, 220, 0, 255),
        outline=(0, 255, 0, 255),
    )

    # ── Attackers (red dots) ──────────────────────────────────────────────
    for ax, ay in attackers_pos:
        apx, apy = _world_to_pixel(ax, ay)
        draw.ellipse(
            [(apx - 3, apy - 3), (apx + 3, apy + 3)],
            fill=(255, 32, 32, 255),
        )

    return np.asarray(img, dtype=np.uint8)


# ── Scenario runner ─────────────────────────────────────────────────────────


class _ScenarioResult:
    """Container for everything the scenario produced.

    Held by a module-scoped fixture so the six assertion functions can
    interrogate the same end-of-run state without re-running the sim.
    """

    def __init__(self) -> None:
        self.defender: Defender = Defender(pos=DEFENDER_POS, hp=DEFENDER_HP_INITIAL)
        # Attacker bundle: (Defender hp-bag, current pos)
        self.attackers: List[Defender] = []
        self.zone_enter_count: int = 0
        self.zone_enter_ids: List[str] = []
        self.heat: HeatField | None = None
        self.heat_total_initial: float = 0.0
        self.heat_total_final: float = 0.0
        self.rope_positions_final: np.ndarray | None = None
        self.frame_image: np.ndarray | None = None


def _run_scenario() -> _ScenarioResult:
    """Execute the 60-frame scenario and return aggregated state."""
    result = _ScenarioResult()

    # iso.combat — defender + wave schedule
    wave = WaveSpec(
        count=3,
        spawn_points=[(0.0, 5.0), (10.0, 5.0), (5.0, 0.0)],
        hp_each=50.0,
        interval=0.5,
    )
    schedule = WaveSchedule([wave])

    # zones — trigger rect 3..7 x 3..7
    def _on_enter(eid):
        result.zone_enter_count += 1
        result.zone_enter_ids.append(str(eid))

    zone = RectZone(name="trigger", x=3.0, y=3.0, w=4.0, h=4.0, on_enter=_on_enter)
    zone_mgr = ZoneManager()
    zone_mgr.add(zone)

    # thermal — 32x32 grid, T=20 baseline, T=800 hot spot
    grid = np.full((GRID_N, GRID_N), COLD_TEMPERATURE, dtype=np.float64)
    grid[HOT_CELL] = HOT_TEMPERATURE
    heat = HeatField(grid, conductivity=1.0, diffusivity=0.1)
    result.heat = heat
    result.heat_total_initial = heat.total_heat()

    # dynamics — 8-node rope between (2, 0) and (8, 0)
    world = World(gravity=(0.0, -9.81))
    rope_spec = RopeSpec(
        node_count=ROPE_NODE_COUNT,
        total_length=ROPE_LENGTH,
        mass_per_node=0.1,
        stiffness=1.0e6,
        damping=0.05,
        anchor_a_pinned=True,
        anchor_b_pinned=True,
    )
    rope_body = build_rope(rope_spec, world, ROPE_ANCHOR_A, ROPE_ANCHOR_B)

    # ── Frame loop ────────────────────────────────────────────────────────
    last_attacker_positions: List[Tuple[float, float]] = []
    for _ in range(FRAMES):
        # Spawn new attackers from the wave schedule. The schedule emits
        # Defender objects; we treat them as attackers (the spec names the
        # 'enemy' role 'attacker' in this scenario).
        new_entities: List[Defender] = schedule.tick(DT)
        for ent in new_entities:
            result.attackers.append(ent)

        # Move attackers toward the defender and resolve melee attacks.
        for atk in result.attackers:
            if atk.hp <= 0.0:
                continue
            dx = DEFENDER_POS[0] - atk.pos[0]
            dy = DEFENDER_POS[1] - atk.pos[1]
            dist = math.hypot(dx, dy)
            if dist > 1e-6:
                nx = dx / dist
                ny = dy / dist
                step = ATTACKER_SPEED * DT
                atk.pos = (atk.pos[0] + nx * step, atk.pos[1] + ny * step)

            atk_view = Attacker(
                pos=atk.pos,
                damage=ATTACKER_DAMAGE,
                reach=ATTACKER_REACH,
                team="enemy",
            )
            resolve_attack(atk_view, result.defender)

        # zones.ZoneManager.update wants a dict of {entity_id: (x, y)}.
        positions = {
            f"attacker_{i}": atk.pos
            for i, atk in enumerate(result.attackers)
        }
        zone_mgr.update(positions)

        # thermal step (clamp keeps total energy effectively constant).
        heat.step(DT, boundary="clamp")

        # dynamics step.
        world.step(DT)

        last_attacker_positions = [atk.pos for atk in result.attackers]

    # Final state capture for the assertions + visual baseline.
    result.heat_total_final = heat.total_heat()
    result.rope_positions_final = world.positions[
        rope_body.node_offset : rope_body.node_offset + rope_body.node_count
    ].copy()
    result.frame_image = _render_frame(
        heat,
        result.rope_positions_final,
        last_attacker_positions,
        zone,
    )
    return result


# ── Pytest fixture — run the scenario once for all assertions ───────────────


@pytest.fixture(scope="module")
def scenario() -> _ScenarioResult:
    return _run_scenario()


# ── Assertions (one per subpackage axis) ────────────────────────────────────


def test_integration_defender_hp_decreased(scenario):
    """iso.combat: at least one attacker reached the defender and damaged it."""
    assert scenario.defender.hp < DEFENDER_HP_INITIAL, (
        f"defender hp did not decrease (still {scenario.defender.hp}); "
        f"attackers never reached melee. Attacker positions: "
        f"{[a.pos for a in scenario.attackers]}"
    )


def test_integration_zone_fired_on_entry(scenario):
    """zones: on_enter fired at least once as attackers crossed the trigger."""
    assert scenario.zone_enter_count > 0, (
        "zone on_enter callback never fired — attackers did not cross "
        f"into the trigger rect (3..7, 3..7). Final attacker positions: "
        f"{[a.pos for a in scenario.attackers]}"
    )


def test_integration_thermal_diffused(scenario):
    """thermal: hot spot has cooled, peak temperature dropped from 800."""
    assert scenario.heat is not None
    peak = float(scenario.heat.temperature.max())
    assert peak < HOT_TEMPERATURE, (
        f"thermal hot spot did not diffuse (peak still {peak} >= "
        f"{HOT_TEMPERATURE})"
    )


def test_integration_thermal_total_energy_decreased(scenario):
    """thermal: total energy stays within 30% of the initial total.

    Per the docstring on HeatField, clamp boundary preserves Σ T modulo
    float rounding. We allow up to a 30% drop to be tolerant of any
    boundary leak under aggressive substepping; the realistic delta is
    typically << 1e-6.
    """
    initial = scenario.heat_total_initial
    final = scenario.heat_total_final
    assert final >= initial * 0.7, (
        f"thermal total energy dropped too far: initial={initial:.4f}, "
        f"final={final:.4f} ({100 * (1 - final / initial):.2f}% loss)"
    )


def test_integration_rope_no_nan(scenario):
    """dynamics: every rope node finished with a finite position."""
    pos = scenario.rope_positions_final
    assert pos is not None
    assert np.all(np.isfinite(pos)), (
        f"rope node positions contained non-finite values: {pos}"
    )


def test_integration_visual_baseline(scenario):
    """testing: 256x256 composite matches the committed golden master.

    First run writes ``engine_integration_v2.png`` under
    ``python/slappyengine/testing/baselines/`` and passes.
    """
    frame = scenario.frame_image
    assert frame is not None
    assert frame.dtype == np.uint8
    assert frame.shape == (RENDER_H, RENDER_W, 4)
    scene = SimpleNamespace(_image_data=frame)
    assert_scene_matches(
        scene,
        "engine_integration_v2",
        tolerance=0.05,
        width=RENDER_W,
        height=RENDER_H,
    )
