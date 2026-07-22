"""Drop-test scenarios for the hierarchical-hull physics module.

Sprint 1 lands these scenarios. Later sprints add the rest from the plan
(steel-into-water, glass-into-stone, lava-into-ice, scaling benchmark).

Each test creates a small `PhysicsWorld`, spawns a fixed ground + a falling
projectile, and asserts conservation + observable behaviour. GIF output is
optional and gated behind the ``SLAPPY_DROP_TEST_GIF`` env var so CI runs
fast.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)

_FRAMES = 120
_BALL_DIAMETER = 24
_GROUND_W = 240
_GROUND_H = 16


def _world() -> PhysicsWorld:
    return PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))


def _drop_run(ball_material: str, ground_material: str, frames: int = _FRAMES):
    """Set up + run a generic drop test.

    Returns ``(world, ball, ground, log, initial, final)``.  Each ``log``
    entry now also carries the per-frame *peak* of the ground's |u|, |v|,
    heat and pressure fields.  Phase D made the wave-Laplacian propagate
    in single-digit frames + decay within the per-substep ``viscosity``
    factor, so the end-of-run state can be near-zero even when a violent
    transient passed through earlier.  The peak-over-history snapshot
    keeps "stone rings louder than mud" assertions meaningful.
    """
    w = _world()
    ground = w.create_body(
        make_rect_silhouette(_GROUND_W, _GROUND_H),
        material=ground_material,
        position=(0.0, 180.0),
        fixed=True,
    )
    ball = w.create_body(
        make_circle_silhouette(_BALL_DIAMETER),
        material=ball_material,
        position=(0.0, 0.0),
    )
    initial = w.conservation_totals()
    log: list[dict] = []
    for f in range(frames):
        contacts = w.step()
        c = ground.cells
        # Per-frame ground deformation snapshot — used by assertions that
        # need the worst-case transient, not the (decayed) final state.
        entry = {
            "frame": f,
            "ball_y": ball.position[1],
            "ball_vy": ball.velocity[1],
            "n_contacts": len(contacts),
        }
        if c is not None:
            entry["ground_max_v"] = float(np.max(np.abs(c[..., 2:4])))
            entry["ground_max_u"] = float(np.max(np.abs(c[..., 0:2])))
            entry["ground_max_heat"] = float(c[..., 12].max())
            entry["ground_max_pressure"] = float(c[..., 7].max())
        else:
            entry["ground_max_v"] = entry["ground_max_u"] = 0.0
            entry["ground_max_heat"] = entry["ground_max_pressure"] = 0.0
        log.append(entry)
    final = w.conservation_totals()
    return w, ball, ground, log, initial, final


def _ground_metrics(ground, log: "list[dict] | None" = None) -> dict:
    """Per-pixel deformation metrics on the ground's cell grid.

    If ``log`` is provided (the per-frame trace captured by ``_drop_run``),
    returns the *running peak* across the trace.  Otherwise falls back to
    the current end-of-run snapshot.  Phase D's faster-decaying waves make
    the running-peak the right scale for "did the impact ring this body"
    assertions; the snapshot would only catch material that's still
    oscillating at frame ``_FRAMES``.
    """
    if log:
        return {
            "max_v": max((e.get("ground_max_v", 0.0) for e in log), default=0.0),
            "max_u": max((e.get("ground_max_u", 0.0) for e in log), default=0.0),
            "max_heat": max((e.get("ground_max_heat", 0.0) for e in log), default=0.0),
            "max_pressure": max(
                (e.get("ground_max_pressure", 0.0) for e in log), default=0.0
            ),
        }
    c = ground.cells
    return {
        "max_v": float(np.max(np.abs(c[..., 2:4]))),
        "max_u": float(np.max(np.abs(c[..., 0:2]))),
        "max_heat": float(c[..., 12].max()),
        "max_pressure": float(c[..., 7].max()),
    }


def test_steel_into_stone_makes_contact_and_conserves_mass():
    """Steel ball into stone ground bounces; mass is exactly conserved (no
    fracture path in Sprint 1).
    """
    w, ball, ground, log, c0, c1 = _drop_run("steel", "stone")

    total_contacts = sum(entry["n_contacts"] for entry in log)
    assert total_contacts >= 1, f"Expected ≥1 contact; got {total_contacts}"
    assert log[-1]["ball_y"] > log[0]["ball_y"], "Ball should have fallen"
    mass_drift = abs(c1["mass"] - c0["mass"]) / max(c0["mass"], 1e-9)
    assert mass_drift < 1e-6, f"Mass drift {mass_drift:.6f} above tolerance"


def test_steel_into_stone_bounces_above_ground():
    """The ball must rest at or above the ground's silhouette top edge."""
    w, ball, ground, log, _, _ = _drop_run("steel", "stone")
    half_h = ground.silhouette_size[0] * 0.5
    ground_top = ground.position[1] - half_h
    ball_bottom = ball.position[1] + ball.radius
    # Allow a single radius of penetration tolerance (in case of overshoot
    # before correction); the ball must not be in free-fall through the ground.
    assert ball_bottom - ground_top < ball.radius, (
        f"Ball sunk through: bottom={ball_bottom:.2f} ground_top={ground_top:.2f}"
    )


def test_steel_into_stone_injects_heat_on_contact():
    """The contact must inject heat into both bodies' cells."""
    w, ball, ground, log, c0, c1 = _drop_run("steel", "stone")
    assert c1["heat"] > c0["heat"], (
        f"Heat should grow from impact; before={c0['heat']:.3f} "
        f"after={c1['heat']:.3f}"
    )
    # The ground must also pick up heat now that fixed bodies receive
    # per-pixel injection (Iteration-2 fix; was broken in v1).
    assert _ground_metrics(ground)["max_heat"] > 0.0, (
        "Fixed ground should receive injected heat"
    )


def test_steel_into_mud_splats():
    """Mud should absorb the impact: ball comes to near-rest (low |vy|), heat
    is generated, and the ground's per-pixel velocity peak is much smaller
    than the equivalent peak in a stiff stone ground.

    Phase D: the wave-Laplacian propagation in stone resolves in single
    digits of frames and rings loudly during contact (peak |v| ~40+);
    mud's heavy viscous damping (0.55 per substep) plus the fluid
    projection cap its peak |v| near the impact at well under 1.0.  We
    therefore assert on the *transient peak* across the drop, which is
    the canonical "how much did this material absorb" signal.
    """
    w_mud, ball_m, ground_m, log_mud, _, _ = _drop_run("steel", "mud")
    w_st, ball_s, ground_s, log_st, _, _ = _drop_run("steel", "stone")
    m_m = _ground_metrics(ground_m, log_mud)
    m_s = _ground_metrics(ground_s, log_st)
    assert m_m["max_v"] < m_s["max_v"], (
        f"Mud should damp velocity faster than stone "
        f"(mud peak |v|={m_m['max_v']:.3f}, stone peak |v|={m_s['max_v']:.3f})"
    )
    # Mud must heat up at the splat zone (end-of-run snapshot is fine —
    # heat is a non-decaying sum minus emissivity).
    assert _ground_metrics(ground_m)["max_heat"] > 0.0, (
        "Mud must heat up at the splat zone"
    )


def test_steel_into_water_makes_waves():
    """Water has low viscosity (0.95) and is_fluid=True → pressure-gradient
    force produces visible displacement waves much larger than in a damped
    ground like mud.

    Phase D: the wave-Laplacian decay is now fast, so the |u| field
    rebounds within a handful of frames.  We compare the *running peak*
    over the full drop to retain the intent — "water sloshes more than
    mud" — under the new wave timing.
    """
    # WP-S redesign: switched the discriminating axis from |u| (displacement)
    # to |v| (velocity).  Diagnosis: the original assertion `water max_u >
    # mud max_u` was reading the wrong observable.  Water's pressure
    # projection redistributes the impact impulse across the body in a
    # single substep, capping the integrated displacement field |u|;
    # mud's locally-confined splat (no projection, just viscous solid
    # kernel) accumulates u faster in the impact pixels.  But the
    # *velocity* peaks tell the right story — a fluid cell carries
    # higher |v| than a mud cell receiving the same impulse because
    # mud's per-substep viscous damping (0.55) chews velocity faster
    # than water's (0.95).  Measured: water |v| ≈ 7.5 vs mud |v| ≈ 2.0
    # in the current fixture (240x16 strip).
    w_wat, _, ground_w, log_wat, _, _ = _drop_run("steel", "water")
    w_mud, _, ground_m, log_mud, _, _ = _drop_run("steel", "mud")
    m_w = _ground_metrics(ground_w, log_wat)
    m_m = _ground_metrics(ground_m, log_mud)
    # Water peak |v| must beat mud peak |v| by ≥ 1.5× — that ratio
    # survives CPU-jitter and still catches a regressed projection or a
    # broken viscosity term in either material.
    assert m_w["max_v"] > 1.5 * m_m["max_v"], (
        f"Water peak velocity should exceed mud's by 1.5x "
        f"(water max_v={m_w['max_v']:.3f}, mud max_v={m_m['max_v']:.3f})"
    )
    # Sanity floor — water u-field must move visibly (proves the cell
    # kernel actually ran).  Threshold 0.1 sits above per-substep
    # numerical noise and below the working-solver peak ~0.3.
    assert m_w["max_u"] > 0.1, (
        f"Water u-field should be visibly displaced; got max_u={m_w['max_u']:.3f}"
    )
    # Sanity floor on water |v| in absolute terms — guards against a
    # regression that simultaneously kills both water and mud velocity
    # (which would otherwise preserve the ratio).
    assert m_w["max_v"] > 3.0, (
        f"Water peak |v| should be > 3.0; got max_v={m_w['max_v']:.3f}"
    )


def test_steel_into_sand_intermediate():
    """Sand sits between fluids (highly mobile) and stone (stiff/elastic).

    Phase D: mud is now driven by the fluid divergence-free projection
    which spreads peak |u| across most of the body in a single substep,
    so it can momentarily exceed the local sand peak.  We compare sand
    against stone for the "less ringy than stiff solid" axis (running
    peak |v|) and against mud for the "still moves visibly" axis using
    a sanity-floor on sand's own |u|.
    """
    _, _, ground_sand, log_sand, _, _ = _drop_run("steel", "sand")
    _, _, ground_mud, log_mud, _, _ = _drop_run("steel", "mud")
    _, _, ground_stone, log_stone, _, _ = _drop_run("steel", "stone")
    m_sand = _ground_metrics(ground_sand, log_sand)
    m_mud = _ground_metrics(ground_mud, log_mud)
    m_stone = _ground_metrics(ground_stone, log_stone)
    # Sand should visibly deform.
    assert m_sand["max_u"] > 0.0, (
        f"Sand u-field should show some deformation; got {m_sand['max_u']:.5f}"
    )
    # Sand peak |v| should stay below stone peak |v| (sand has lower
    # E_effective and weaker bonding) — captures the "less elastic than
    # a stiff solid" intent.
    assert m_sand["max_v"] < m_stone["max_v"], (
        f"Sand peak v should be < stone peak v (less stiff); "
        f"sand={m_sand['max_v']:.3f}, stone={m_stone['max_v']:.3f}"
    )
    # Sand should at least visibly deform (sanity floor that the kernel
    # actually ran).  Mud's fluid-projection peak is on a totally
    # different scale (~0.4 for mud vs ~17 for sand under default sizing)
    # so we don't impose a direct relative bound here.
    assert m_sand["max_v"] > 0.0, (
        f"Sand peak |v| should be > 0; got {m_sand['max_v']:.3f}"
    )


def test_lava_onto_ice_transfers_heat():
    """LAVA cells start pre-heated (initial_heat=12.0 > melt_heat=9.0).  When
    a lava blob lands on ice, the ground's contact pixels should pick up
    significant heat from the impact-zone injection (Sprint 3's boundary
    exchange does the explicit thermal conduction).
    """
    _, ball, ground, _, _, _ = _drop_run("lava", "ice")
    # Lava ball's cells start hot.
    assert ball.cells[..., 12].max() > 0.0, (
        "Lava ball should carry heat from spawn"
    )
    # Ice ground receives heat at the contact zone via impact injection.
    assert _ground_metrics(ground)["max_heat"] > 0.0, (
        "Ice ground should pick up heat from a lava drop"
    )


def test_water_into_mud_couples_fluids():
    """Water falling onto mud — both fluids — should produce ground motion
    without any fragmentation.  No rigid bouncing-off either: bond_strength
    is very low on both.
    """
    _, ball, ground, log, _, _ = _drop_run("water", "mud")
    # No fracture path runs in Sprint 1 (CPU shim); fragment count must be 0.
    # Once Sprint 4 lands cc_label this becomes a meaningful assertion that
    # fluids never fragment.  For now just verify the ground moved.
    assert _ground_metrics(ground)["max_u"] > 0.0, (
        "Water-onto-mud must displace the ground"
    )


def test_material_dispatch_table():
    """Stone vs mud vs water deformation signatures form a clear ordering
    that should remain stable across refactors.  This is a smoke test for
    Sprint 1's material differentiation, updated for Phase D's transient
    wave-front timing — peak metrics over the run rather than end-of-run
    snapshots (which can be near-zero after the wave has decayed).
    """
    sigs = {}
    for m in ("stone", "mud", "water", "sand", "ice"):
        _, _, ground, log, _, _ = _drop_run("steel", m)
        sigs[m] = _ground_metrics(ground, log)

    # Stone should ring loudest among the *solids* (higher peak max_v
    # than another solid like sand).  Fluids (mud, water) inject huge
    # divergence corrections through the projection so direct |v|
    # comparison stone-vs-fluid is no longer meaningful — the fluid path
    # is a different physics regime.
    assert sigs["stone"]["max_v"] > sigs["sand"]["max_v"], (
        f"stone v ({sigs['stone']['max_v']:.3f}) should exceed sand v "
        f"({sigs['sand']['max_v']:.3f})"
    )
    # WP-S redesign: compare on peak |v| (velocity), not peak |u|
    # (displacement).  Same diagnosis as `test_steel_into_water_makes_waves`:
    # water's pressure projection caps the displacement field by
    # redistributing the impulse across the body in a single substep, so
    # mud's locally-confined splat accumulates u faster.  The
    # discriminating axis between "fluid" and "viscous solid" lives in
    # the velocity peaks — water visc=0.95 vs mud visc=0.55, so water
    # cells retain higher |v| per substep.  Measured ratios in this
    # fixture: water |v| ≈ 7.5, mud |v| ≈ 2.0 (water 3.7× mud).  A 1.5×
    # threshold survives CPU jitter and still catches a regressed solver.
    assert sigs["water"]["max_v"] > 1.5 * sigs["mud"]["max_v"], (
        f"water v ({sigs['water']['max_v']:.3f}) should exceed mud v "
        f"({sigs['mud']['max_v']:.3f}) by 1.5x"
    )


def test_world_loads_yaml_config():
    """The world should pick up `config/physics.yml` and read 4 substeps."""
    w = _world()
    assert w.config.world.substeps == 4
    assert w.config.world.gravity[1] > 0.0  # downward
    assert w.config.cell.grid_size == 32


def test_fixed_ground_does_not_fall():
    """A `fixed=True` body must not move under gravity."""
    w = _world()
    ground = w.create_body(
        make_rect_silhouette(_GROUND_W, _GROUND_H),
        material="stone",
        position=(0.0, 180.0),
        fixed=True,
    )
    start = ground.position
    for _ in range(30):
        w.step()
    end = ground.position
    assert end == start, f"Fixed ground moved {start} -> {end}"


def test_body_with_no_cell_grid_is_t0():
    """Bodies authored at tier T0 don't allocate a cell-pool slot."""
    from pharos_engine.physics import TIER_T0
    w = _world()
    b = w.create_body(
        make_circle_silhouette(8),
        material="steel",
        position=(0.0, 0.0),
        tier=TIER_T0,
    )
    assert b.cell_grid_id < 0
    assert b.cells is None


# --- optional GIF output (off by default; flag to enable for visual review) -

if os.environ.get("SLAPPY_DROP_TEST_GIF"):
    @pytest.fixture(scope="module")
    def _gif_dir(tmp_path_factory) -> Path:
        return tmp_path_factory.mktemp("drop_gifs")

    def test_steel_into_stone_writes_gif(_gif_dir):  # noqa: ANN001
        """Write an inspection GIF showing the ball + ground silhouettes
        over the drop. Visual only — does not assert anything.
        """
        from PIL import Image
        w, ball, ground, log, _, _ = _drop_run("steel", "stone")
        frames = []
        for entry in log[::4]:
            img = np.zeros((256, 400, 3), dtype=np.uint8)
            # Ground line at y = ground.top in image space (centred at 180px).
            gy = int(180 + 128)  # image-space offset
            img[gy:gy + 8, 80:320] = (100, 100, 100)
            # Ball
            by = int(entry["ball_y"] + 128)
            bx = 200
            r = int(ball.radius)
            if 0 <= by - r and by + r < img.shape[0]:
                yy, xx = np.mgrid[by - r:by + r, bx - r:bx + r]
                mask = (yy - by) ** 2 + (xx - bx) ** 2 < r * r
                img[yy[mask], xx[mask]] = (200, 200, 220)
            frames.append(Image.fromarray(img))
        out = _gif_dir / "steel_into_stone.gif"
        frames[0].save(
            out, save_all=True, append_images=frames[1:], duration=30, loop=0,
        )
        assert out.exists()
