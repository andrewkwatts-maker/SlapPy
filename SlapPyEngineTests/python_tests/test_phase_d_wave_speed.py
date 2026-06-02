"""Phase D — wave-speed renormalisation tests.

The per-pixel kernel evaluates its elastic Laplacian in *grid-index units*
(``Δx = 1`` cell).  Phase D introduces ``CellMaterial.E_effective``,
derived from a per-material ``wave_crossing_frames`` target, so that an
elastic wave traverses the 32-cell body grid in a visible number of
frames at 60 Hz.  The kernel reads ``E_effective`` for the wave-Laplacian
path while the raw ``E`` continues to drive the stress / yield arithmetic.

These tests verify:

1.  Steel waves cross a 32-cell body within the targeted single-digit
    frame window (2-8 frames).
2.  Material stiffness ordering is preserved (steel propagates faster
    than wood, which is faster than mud).
3.  CFL planner keeps the kernel stable even with the larger renormalised
    ``E_effective`` values (no NaN / explosion after a long run).
4.  Mass conservation through a representative drop still holds.

These tests intentionally drive the CPU path (``debug_force_cpu=True``)
so the assertions don't depend on a wgpu adapter being present in the
test environment.  The GPU path is exercised by ``test_gpu_kernel.py``
which already verifies CPU/GPU parity.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.deform_modes import MATERIAL_CONFIGS, MaterialPreset
from slappyengine.physics import (
    PhysicsWorld,
    make_rect_silhouette,
)
from slappyengine.physics.cell import CELL_GRID_SIZE
from slappyengine.physics.world import (
    CellConfig,
    CollisionConfig,
    GpuConfig,
    HullConfig,
    PhysicsYaml,
    WorldConfig,
    _IDX_DENSITY,
    _IDX_V_X,
    _IDX_V_Y,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_world(*, gravity_zero: bool = True) -> PhysicsWorld:
    """A CPU-only world with zero gravity so the only state change in the
    cell field is the elastic-wave Laplacian itself."""
    g = (0.0, 0.0) if gravity_zero else (0.0, 196.0)
    cfg = PhysicsYaml(
        world=WorldConfig(default_dt=1.0 / 60.0, substeps=4, gravity=g),
        hull=HullConfig(),
        cell=CellConfig(),
        collision=CollisionConfig(),
        gpu=GpuConfig(enabled=False, debug_force_cpu=True),
    )
    return PhysicsWorld(config=cfg)


def _spawn_block(world: PhysicsWorld, material: str):
    """Spawn a free 32-cell-wide block centred at the origin.

    A square silhouette guarantees an isotropic 32×32 cell grid, so the
    wave path from corner to corner travels the full ``CELL_GRID_SIZE``
    in each axis.
    """
    body = world.create_body(
        make_rect_silhouette(CELL_GRID_SIZE, CELL_GRID_SIZE),
        material=material,
        position=(0.0, 0.0),
        velocity=(0.0, 0.0),
    )
    # Force the body active for the kernel — auto-activation is triggered
    # by contacts, and we're driving the field directly without one.
    # Stamp a far-future deadline directly so every step in the test
    # sweeps the cell field.
    world.hulls.active_until_frame[body.root_hull_id] = 10_000
    world.hulls.activation_level[body.root_hull_id] = 2
    return body


def _inject_corner_impulse(body, *, value: float = 50.0) -> None:
    """Set a single corner cell's v_x to a non-zero value.

    Using a *velocity* impulse (rather than an initial displacement) is
    the cleanest way to seed a wave: the kernel's Laplacian then
    propagates the resulting strain across the grid each substep.  We
    zero the entire field first so the wave-front trace below is
    unambiguous.
    """
    c = body.cells
    c[..., _IDX_V_X] = 0.0
    c[..., _IDX_V_Y] = 0.0
    # Channel index 0 / 1 hold ``u`` (displacement) — also zero.
    c[..., 0] = 0.0
    c[..., 1] = 0.0
    # Drop the impulse in the (0, 0) corner cell.
    c[0, 0, _IDX_V_X] = value


def _crossing_frame(body, *, threshold: float = 0.1, max_frames: int = 60,
                    world: PhysicsWorld) -> int:
    """Step the world and return the first frame in which the cell at
    the opposite corner (n-1, n-1) sees |v| > ``threshold``.

    Returns ``max_frames`` if the wave never arrives — caller asserts.
    """
    n = CELL_GRID_SIZE
    for f in range(1, max_frames + 1):
        world.step()
        c = body.cells
        if c is None:
            # Body got removed (e.g. via fragmentation).  Treat as
            # "never arrived" — caller will see the cap.
            return max_frames
        vx = float(c[n - 1, n - 1, _IDX_V_X])
        vy = float(c[n - 1, n - 1, _IDX_V_Y])
        if (vx * vx + vy * vy) ** 0.5 > threshold:
            return f
    return max_frames


# ---------------------------------------------------------------------------
# 1. Steel wave crosses a body in target single-digit frames.
# ---------------------------------------------------------------------------

def test_steel_wave_crosses_body_in_target_frames():
    """An impulse in the (0,0) corner of a steel block must produce a
    detectable |v| at the (n-1, n-1) corner within the steel material's
    target wave-crossing window (3-4 frames per material spec, allow 2-8
    for substep-discretisation slack)."""
    w = _build_world()
    body = _spawn_block(w, "steel")
    _inject_corner_impulse(body, value=50.0)
    f = _crossing_frame(body, threshold=0.1, max_frames=60, world=w)
    assert 2 <= f <= 8, (
        f"Steel wave crossing took {f} frames; expected [2, 8] for the "
        f"renormalised E_effective.  steel.E_effective = "
        f"{MATERIAL_CONFIGS[MaterialPreset.STEEL].cell.E_effective:.1f}"
    )


# ---------------------------------------------------------------------------
# 2. Stiffness ordering: steel < wood < mud (crossing time grows with softness).
# ---------------------------------------------------------------------------

def test_per_material_relative_speeds():
    """The wave-front *arrival time* (first non-zero displacement at the
    opposite corner) must increase monotonically as the material softens.
    Steel propagates fastest, wood next, then snow.

    We pick three *solid* materials with strictly different
    ``wave_crossing_frames`` targets.  Fluids are deliberately excluded
    because the divergence-free pressure projection (Phase C) couples
    every cell globally and breaks the "wave-front travelling at finite
    speed" abstraction.

    We compare arrival times rather than "first frame above amplitude X"
    because each material's viscous damping (``CellMaterial.viscosity``)
    attenuates the wave to wildly different peak amplitudes; the *speed*
    of the leading edge is the meaningful per-material wave property,
    the peak amplitude is a separate axis governed by damping.
    """
    # Very small detection threshold so we measure leading-edge arrival,
    # not the late-stage peak.  Numerical noise at the far corner stays
    # well below ~1e-12 prior to the front arriving (FP roll/roll noise).
    arrival_threshold = 1e-6
    materials = ("steel", "wood", "snow")
    times: dict[str, int] = {}
    for m in materials:
        w = _build_world()
        body = _spawn_block(w, m)
        _inject_corner_impulse(body, value=50.0)
        times[m] = _crossing_frame(
            body, threshold=arrival_threshold, max_frames=80, world=w,
        )
    assert times["steel"] < times["wood"] < times["snow"], (
        f"Wave-speed ordering violated: {times}"
    )


# ---------------------------------------------------------------------------
# 3. CFL clamp keeps the kernel stable with the renormalised E_effective.
# ---------------------------------------------------------------------------

def test_cfl_clamp_still_holds():
    """With E_effective bumped by Phase D, the CFL planner must request
    enough substeps that the kernel stays stable.  A 60-step run on the
    stiffest material in the registry (diamond) must finish without any
    NaN / Inf in the cell field."""
    w = _build_world()
    body = _spawn_block(w, "diamond")
    _inject_corner_impulse(body, value=80.0)
    for _ in range(60):
        w.step()
        c = body.cells
        assert c is not None, "Diamond block should not be removed"
        assert np.all(np.isfinite(c)), (
            "Diamond cells contain NaN / Inf — CFL clamp insufficient "
            f"for E_effective = "
            f"{MATERIAL_CONFIGS[MaterialPreset.DIAMOND].cell.E_effective:.1f}"
        )


def test_cfl_planner_requests_more_substeps_for_stiffer_materials():
    """``_cfl_required_substeps`` is the gate the substep loop uses to
    decide how many integrator steps to take.  Stiffer materials (larger
    ``E_effective``) must require strictly more substeps than soft ones."""
    w_steel = _build_world()
    _spawn_block(w_steel, "steel")
    w_mud = _build_world()
    _spawn_block(w_mud, "mud")

    dt = w_steel.config.world.default_dt
    sub_steel = w_steel._cfl_required_substeps(dt)
    sub_mud = w_mud._cfl_required_substeps(dt)
    assert sub_steel > sub_mud, (
        f"Stiff material should require more substeps than soft: "
        f"steel={sub_steel} mud={sub_mud}"
    )


# ---------------------------------------------------------------------------
# 4. Conservation regression — mass through a drop still holds exactly.
# ---------------------------------------------------------------------------

def test_existing_conservation_still_holds():
    """Phase D only retunes the wave-Laplacian path; mass conservation
    through a representative drop must remain at single-ULP-grade drift."""
    from slappyengine.physics import make_circle_silhouette
    w = PhysicsWorld(world_bounds=(-200.0, -100.0, 200.0, 250.0))
    w.create_body(
        make_rect_silhouette(240, 16), material="stone",
        position=(0.0, 180.0), fixed=True,
    )
    w.create_body(
        make_circle_silhouette(24), material="steel", position=(0.0, 0.0),
    )

    def _cell_mass(world: PhysicsWorld) -> float:
        total = 0.0
        for body in world.bodies:
            c = body.cells
            if c is None:
                continue
            total += float(
                body.material.density_rho * c[..., _IDX_DENSITY].astype(np.float64).sum()
            )
        return total

    m0 = _cell_mass(w)
    for _ in range(120):
        w.step()
    m1 = _cell_mass(w)
    drift = abs(m1 - m0) / max(m0, 1e-9)
    assert drift < 1e-9, (
        f"Cell-mass drift {drift:.2e} above tolerance after 120 steps."
    )


# ---------------------------------------------------------------------------
# 5. E_effective is consistent with wave_crossing_frames target.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "preset",
    [
        MaterialPreset.STEEL,
        MaterialPreset.IRON,
        MaterialPreset.DIAMOND,
        MaterialPreset.STONE,
        MaterialPreset.WOOD,
        MaterialPreset.MUD,
        MaterialPreset.WATER,
        MaterialPreset.SNOW,
    ],
)
def test_e_effective_matches_wave_crossing_formula(preset: MaterialPreset):
    """For every registered material, ``E_effective`` must satisfy the
    derivation ``rho * (CELL_GRID_SIZE * 60 / wave_crossing_frames)²``.
    This locks the algebra so future edits to ``E_effective`` are caught
    by CI rather than diagnosed via mysterious wave-speed regressions."""
    cell = MATERIAL_CONFIGS[preset].cell
    assert cell is not None, f"{preset.value} should have a CellMaterial"
    target = float(cell.wave_crossing_frames)
    expected_c = float(CELL_GRID_SIZE) * 60.0 / target
    expected = float(cell.density_rho) * expected_c * expected_c
    assert abs(cell.E_effective - expected) < 1e-3, (
        f"{preset.value}.E_effective ({cell.E_effective:.3f}) does not "
        f"match the wave_crossing_frames derivation ({expected:.3f})"
    )
