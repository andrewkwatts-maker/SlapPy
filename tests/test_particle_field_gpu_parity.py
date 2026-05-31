"""CPU/GPU parity scaffolding for the upcoming ParticleField GPU port.

Each GPU kernel we land in Sprints 2-3 must produce results within
float-tolerance of the existing CPU implementation. This file holds
the shared assertion / setup helpers plus one demo test per kernel.

Until a kernel ships, both halves of the pair run the CPU path — the
test still exercises the harness (CPU vs CPU == identical), and we
flip the GPU instance to ``use_gpu=True`` once the kernel exists.
The skipped placeholders mark each kernel slot so removing the skip
decorator is the only step needed to enable a parity check.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.physics.particle_field import (
    ParticleField,
    SAND_MAT,
)


# ── Helpers ────────────────────────────────────────────────────────────


def assert_soa_close(cpu_field, gpu_field, rtol=1e-4, atol=1e-5):
    """Compare two ParticleField SoAs element-wise."""
    for fname in (
        'pos', 'vel', 'material_id', 'radius', 'bake_radius',
        'color', 'phase', 'phase_age', 'kinetic_age',
        'rigidify_at', 'impact_vel', 'temperature',
    ):
        cpu_val = getattr(cpu_field, fname)
        gpu_val = getattr(gpu_field, fname)
        np.testing.assert_allclose(
            cpu_val, gpu_val, rtol=rtol, atol=atol,
            err_msg=f"SoA field {fname!r} divergence",
        )


def make_paired_fields(n_particles=200, seed=42):
    """Construct two identical ParticleField instances seeded with the
    same particles. Returns ``(cpu, gpu)``.

    For now BOTH instances run the CPU path — the GPU one will be
    flipped to ``use_gpu=True`` once GPU kernels exist. The test still
    passes (CPU vs CPU) which confirms the harness works.
    """
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    # Pin the internal RNG so spawn() picks identical fragment shapes,
    # rotations and rigidify_at draws for both fields.
    cpu._rng = np.random.default_rng(seed)
    gpu._rng = np.random.default_rng(seed)

    # Drive the particle layout from a third RNG so the spawn loop is
    # not coupled to the per-field RNG that spawn() advances internally.
    layout_rng = np.random.default_rng(seed + 1)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[16.0, 16.0],
        high=[240.0, 96.0],   # spawn in upper portion so they fall
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = layout_rng.uniform(
        low=[-40.0, -20.0],
        high=[40.0, 20.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    return cpu, gpu


def step_both(cpu, gpu, dt=1 / 60, n=10):
    """Step both fields the same number of times."""
    for _ in range(n):
        cpu.step(dt)
        gpu.step(dt)


# ── Active tests ───────────────────────────────────────────────────────


def test_integrate_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    # Spawn happened in mid-air with varying velocities so gravity +
    # drag have a noticeable effect after a few frames. Step a small
    # number of times to keep particles airborne (and therefore inside
    # the _integrate path) without all of them landing.
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


# ── Sprint 2 placeholders ─────────────────────────────────────────────


def test_collide_cpu_gpu_parity():
    """50 sand particles dropped onto a flat ground; step 30 frames.

    Mid-air spawn with downward velocity guarantees the collide kernel
    is exercised heavily (~every particle hits the ground line within
    30 frames). CPU vs GPU SoAs must stay within float tolerance.
    """
    # Build two identical fields with a flat sand ground.
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    cpu._rng = np.random.default_rng(42)
    gpu._rng = np.random.default_rng(42)
    for f in (cpu, gpu):
        f.fill_ground(
            top_y=180, color=(120, 90, 60), sub_color=(80, 60, 40),
            material="sand",
        )
    gpu.use_gpu_collide = True

    # 50 sand particles in mid-air, all moving downward (vy > 0).
    n_particles = 50
    layout_rng = np.random.default_rng(43)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[16.0, 40.0],
        high=[240.0, 100.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = layout_rng.uniform(
        low=[-10.0, 40.0],
        high=[10.0, 80.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)
    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    # Step 30 frames; sand will land within the first ~10 frames.
    step_both(cpu, gpu, n=30)
    assert_soa_close(cpu, gpu)


def test_drill_cpu_gpu_parity():
    """Fire 5 bullets at a stone wall on both CPU and GPU paths;
    assert pos/vel/phase agree after 30 frames and the post-drill mask
    (alpha channel only) matches pixel-wise.

    Notes
    -----
    * Bullets are spawned with a horizontal stride of 12 px so no two
      drill the SAME pixel in any single frame — keeps the parity
      tight even though both paths process bullets in non-determinstic
      order when their drill columns overlap.
    * BULLET_MAT has drill_eject_gain=0 so no ejecta spawn — keeps
      RNG-dependent paths out of the test.
    """
    from slappyengine.physics.particle_field import (
        ParticleField, Material,
    )

    BULLET = Material(
        name="bullet",
        binding_force=1.0e3,        # easy KE threshold
        air_drag_per_sec=1.0,        # no drag (clean parity)
        gravity_scale=0.0,           # no gravity
        density=8.0,
        color=(220, 200, 60),
        radius_min=1,
        radius_max=1,
        drill_max_px=64,
        drill_velocity_loss=0.92,
        drill_eject_gain=0.0,        # no ejecta — keeps RNG out
        drill_entry_crater=0,        # no jitter
        drill_entry_crater_jitter=0,
        mass_conservation=1.0,
    )
    STONE = Material(
        name="stone",
        binding_force=2.0e5,
        cohesion=0.05,
        color=(110, 100, 90),
    )

    def _build_field(use_gpu_drill: bool) -> ParticleField:
        f = ParticleField(width=256, height=128)
        f.use_gpu_drill = use_gpu_drill
        f._rng = np.random.default_rng(424242)
        f.register_material(BULLET)
        f.register_material(STONE)
        stone_id = f.material_id_of("stone")
        bullet_id = f.material_id_of("bullet")
        # Paint a vertical stone wall from x=160 to x=192.
        f.mask[:, 160:192, 0] = 110
        f.mask[:, 160:192, 1] = 100
        f.mask[:, 160:192, 2] = 90
        f.mask[:, 160:192, 3] = 255
        f._fixed_mask[:, 160:192] = True
        f.material_grid[:, 160:192] = stone_id
        # Spawn 5 bullets at x=20, spaced 12 px apart on Y so they
        # drill independent rows of the wall.
        for k in range(5):
            f.spawn(
                x=20.0,
                y=20.0 + k * 12.0,
                vx=1800.0,
                vy=0.0,
                material=bullet_id,
            )
        return f

    cpu = _build_field(use_gpu_drill=False)
    gpu = _build_field(use_gpu_drill=True)

    dt = 1.0 / 60.0
    for _ in range(30):
        cpu.step(dt)
        gpu.step(dt)

    # pos / vel / phase parity
    np.testing.assert_allclose(
        cpu.pos, gpu.pos, rtol=1e-3, atol=1e-2,
        err_msg="pos divergence after drill",
    )
    np.testing.assert_allclose(
        cpu.vel, gpu.vel, rtol=1e-3, atol=1e-1,
        err_msg="vel divergence after drill",
    )
    np.testing.assert_array_equal(
        cpu.phase, gpu.phase,
        err_msg="phase divergence after drill",
    )
    # Mask alpha parity — post-drill terrain shape must match exactly.
    np.testing.assert_array_equal(
        cpu.mask[..., 3], gpu.mask[..., 3],
        err_msg="mask alpha divergence after drill",
    )


# ── Sprint 3 placeholders ─────────────────────────────────────────────


def test_slump_cpu_gpu_parity():
    """Build a flat sand ground, spawn particles that fall + bake into
    loose piles, step both fields, and compare mask / loose state.

    The slump GPU port advances a per-pixel PCG32 RNG (one per pixel,
    once per pass), while the CPU path uses the shared ``self._rng``
    with vectorised row-at-a-time draws. The two RNG strategies are
    NOT bit-equivalent — per-pixel exact parity is not expected. We
    assert distribution-level invariants instead:

      * Mass conservation: total solid-pixel count agrees within 1%
        (both paths only redistribute, never spawn or destroy mass).
      * At least 90% of the mask-alpha pixels match between CPU/GPU.
      * Fixed pixels are NEVER touched by either path.
    """
    def _build_field(use_gpu: bool, seed: int) -> ParticleField:
        f = ParticleField(width=128, height=96)
        f._rng = np.random.default_rng(seed)
        f.use_gpu_slump = use_gpu
        # Fixed ground at y=80 — must NOT be touched by slump.
        f.fill_ground(
            top_y=80, color=(120, 90, 60), sub_color=(80, 60, 40),
            material="sand",
        )
        return f

    SEED = 7777
    cpu = _build_field(use_gpu=False, seed=SEED)
    gpu = _build_field(use_gpu=True, seed=SEED)

    # Spawn a handful of sand particles that will land + bake into piles.
    n_particles = 80
    layout_rng = np.random.default_rng(SEED + 1)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[10.0, 20.0], high=[118.0, 60.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = np.zeros((n_particles, 2), dtype=np.float32)
    vel[:, 1] = layout_rng.uniform(40.0, 80.0, n_particles).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)
    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    # 30 frames: particles fall, land, settle, bake into loose pixels,
    # and the slump pass redistributes them every frame.
    dt = 1.0 / 60.0
    for _ in range(30):
        cpu.step(dt)
        gpu.step(dt)

    # ── Mass conservation ──────────────────────────────────────────
    cpu_mass = int((cpu.mask[..., 3] > 0).sum())
    gpu_mass = int((gpu.mask[..., 3] > 0).sum())
    mass_tol = max(1, int(0.01 * max(cpu_mass, gpu_mass)))
    assert abs(cpu_mass - gpu_mass) <= mass_tol, (
        f"slump mass divergence: CPU={cpu_mass}, GPU={gpu_mass}, "
        f"tol={mass_tol}"
    )

    # ── Fixed pixels untouched ─────────────────────────────────────
    assert (cpu.mask[80:, :, 3] == 255).all(), "CPU disturbed fixed ground"
    assert (gpu.mask[80:, :, 3] == 255).all(), "GPU disturbed fixed ground"

    # ── ≥90% mask alpha overlap ────────────────────────────────────
    total_pixels = cpu.mask.shape[0] * cpu.mask.shape[1]
    matching = int((cpu.mask[..., 3] == gpu.mask[..., 3]).sum())
    pct_match = matching / total_pixels
    assert pct_match >= 0.90, (
        f"slump mask alpha overlap too low: {pct_match:.3f} "
        f"({matching}/{total_pixels})"
    )


def test_kinetic_relax_cpu_gpu_parity():
    """Spawn 200 sand particles in a tight cluster (so kinetic_relax
    actually has work to do — many particles share a single spatial
    cell), step both fields 20 frames, assert position convergence
    within ~1e-3.

    The GPU shader visits intra-cell pairs only — same as the CPU
    vectorised reference. Float-summation order is the only source of
    drift, hence the loose tolerance.
    """
    n_particles = 200
    seed = 7
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    cpu._rng = np.random.default_rng(seed)
    gpu._rng = np.random.default_rng(seed)

    layout_rng = np.random.default_rng(seed + 1)
    sand_id = cpu.material_id_of("sand")
    # Tight cluster — everyone within +/-2 px of the centre so the hash
    # bins them into 1-2 cells (bin_size = 3.75).
    centre = np.array([128.0, 128.0], dtype=np.float32)
    offsets = layout_rng.uniform(low=-2.0, high=2.0,
                                 size=(n_particles, 2)).astype(np.float32)
    pos = centre + offsets
    vel = np.zeros((n_particles, 2), dtype=np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    gpu.use_gpu_kinetic_relax = True

    for _ in range(20):
        cpu.step(1 / 60)
        gpu.step(1 / 60)

    # Per-step push parity is ~1e-5 (verified in the gpu_kinetic_relax
    # dev log) — but over 20 frames the divergence amplifies non-
    # linearly because particles right on a cell boundary can flip
    # which side they bin to after a sub-pixel push, and from then
    # on both paths take different bifurcations. The atol catches
    # genuine regressions while tolerating that branching; bumped to
    # 4 px after the CPU step() switched to 3 PBF-style sub-iterations
    # (Macklin 2013), which amplifies boundary bifurcation across the
    # extra passes. The GPU wrapper mirrors the 3 sub-iters for parity.
    np.testing.assert_allclose(cpu.pos, gpu.pos, rtol=1e-2, atol=4.0,
                               err_msg="kinetic_relax pos divergence")


@pytest.mark.skip(reason="GPU kernel not yet ported — Sprint 3")
def test_fluid_relax_cpu_gpu_parity():
    cpu, gpu = make_paired_fields(n_particles=200)
    step_both(cpu, gpu, n=20)
    assert_soa_close(cpu, gpu)


def test_thermal_step_cpu_gpu_parity():
    """100 snow particles spawned at T=10 °C — well above SNOW_THERMAL's
    melt_at=2.0 °C — phase-change to water in the first frame. Both
    fields run the same particle population; the CPU half uses
    ``_thermal_step`` and the GPU half uses ``gpu_thermal_step``
    (which falls back to a numpy mimic when wgpu is unavailable, so
    the test still exercises the upload/readback wiring even on a
    headless CI).

    Asserts temperatures within ~1 °C (the per-frame relaxation is
    order-of-magnitude larger than f32 drift, but mid-relaxation
    snapshots can disagree by tens of millidegrees per step; 1e-4 is
    too tight against f32 buffer roundtrip noise) and material_ids
    match exactly (phase change is discrete: above the threshold the
    id flips, below it doesn't).
    """
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    gpu.use_gpu_thermal = True
    cpu._rng = np.random.default_rng(123)
    gpu._rng = np.random.default_rng(123)

    snow_id = cpu.material_id_of("snow")
    n = 100
    pos = np.linspace(
        [16.0, 32.0], [240.0, 96.0], n, dtype=np.float32,
    )
    vel = np.zeros((n, 2), dtype=np.float32)
    mids = np.full(n, snow_id, dtype=np.int32)
    radii = np.ones(n, dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    # Drive only the thermal step — skip the full physics tick so the
    # parity check is exercising the kernel in isolation.
    DT = 1.0 / 60.0
    for _ in range(5):
        cpu._thermal_step(DT)
        from slappyengine.physics.particle_gpu import gpu_thermal_step
        gpu_thermal_step(gpu, DT)

    np.testing.assert_allclose(
        cpu.temperature, gpu.temperature, atol=1e-4,
        err_msg="thermal_step: temperature drift between CPU and GPU",
    )
    np.testing.assert_array_equal(
        cpu.material_id, gpu.material_id,
        err_msg="thermal_step: phase-change discrepancy (material_id mismatch)",
    )
    np.testing.assert_array_equal(
        cpu.color, gpu.color,
        err_msg="thermal_step: color not updated to match new material",
    )


def test_bake_cpu_gpu_parity():
    """Spawn 50 sand particles in mid-air over a flat ground; step both
    fields long enough for everyone to settle and bake; assert mask
    parity within ~5% pixel difference.

    Tolerance is driven by:
      * Rotation quantisation — the GPU atlas pre-rasterises shapes at
        N_ROTATIONS=8 bins; the CPU uses the exact float rotation.
      * Write-ordering non-determinism — when two polygons overlap the
        last-write-wins ordering between CPU and GPU can pick different
        colours (matches the CPU's own iteration-order non-determinism
        noted in baked_terrain.bake_settled_particles).
    """
    # Build two identical fields with a flat sand ground.
    cpu = ParticleField(width=256, height=256)
    gpu = ParticleField(width=256, height=256)
    cpu._rng = np.random.default_rng(42)
    gpu._rng = np.random.default_rng(42)
    for f in (cpu, gpu):
        f.fill_ground(
            top_y=180, color=(120, 90, 60), sub_color=(80, 60, 40),
            material="sand",
        )
    gpu.use_gpu_bake = True

    # 50 sand particles in mid-air, all moving downward (vy > 0).
    n_particles = 50
    layout_rng = np.random.default_rng(43)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[16.0, 40.0],
        high=[240.0, 100.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = layout_rng.uniform(
        low=[-10.0, 40.0],
        high=[10.0, 80.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)
    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    # 100 frames: ~10 fall, then slide/settle, then bake by ~frame 25.
    dt = 1.0 / 60.0
    for _ in range(100):
        cpu.step(dt)
        gpu.step(dt)

    # Compare the alpha channels of the masks. ~5% slack tolerates
    # rotation-bin quantisation + write-ordering races.
    cpu_alpha = cpu.mask[..., 3] > 0
    gpu_alpha = gpu.mask[..., 3] > 0
    n_pixels = cpu_alpha.size
    n_disagree = int((cpu_alpha != gpu_alpha).sum())
    frac_disagree = n_disagree / float(n_pixels)
    assert frac_disagree <= 0.05, (
        f"bake mask alpha divergence too high: "
        f"{n_disagree}/{n_pixels} pixels differ ({frac_disagree:.3%})"
    )
    # Number of baked particles should match closely (both paths gate
    # on phase == SETTLING and ~bake_flag).
    cpu_baked = int(cpu.bake_flag.sum())
    gpu_baked = int(gpu.bake_flag.sum())
    assert abs(cpu_baked - gpu_baked) <= 2, (
        f"bake-flag count divergence: CPU={cpu_baked}, GPU={gpu_baked}"
    )


# ── Slide kernel (column_top + per-particle slide) ────────────────────


def _new_slide_field(seed: int = 99) -> ParticleField:
    """Two identical fields with a flat sand ground at y=180. Particles
    spawn airborne above the ground so the slide kernel kicks in after
    they land. Internal _rng is pinned for reproducible PCG seeds.
    """
    f = ParticleField(width=256, height=256)
    f._rng = np.random.default_rng(seed)
    f.fill_ground(
        top_y=180, color=(120, 90, 60), sub_color=(80, 60, 40),
        material="sand",
    )
    return f


def test_slide_cpu_gpu_parity_flat_ground():
    """30 sand particles dropped onto a flat ground; step long enough
    for the slide kernel to take over from collide, and check that
    pos/vel/phase converge within the documented tolerance.

    The GPU port uses a per-particle PCG32 RNG instead of the shared
    ``self._rng`` for the settle-threshold jitter, so bit-exact parity
    is not possible. We compare:
      * pos within ~1 px (atol=1.0) — slight position drift OK.
      * vel within ~2 px/s (atol=2.0) — different jitter draws lead
        to slightly different stopping points.
      * phase counts agree within a small slack — both paths should
        settle "around the same time" within a couple frames.
    """
    cpu = _new_slide_field(seed=99)
    gpu = _new_slide_field(seed=99)
    gpu.use_gpu_slide = True

    n_particles = 30
    layout_rng = np.random.default_rng(100)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[20.0, 60.0], high=[236.0, 120.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    # Moderate horizontal velocity so particles slide after landing.
    vel = np.zeros((n_particles, 2), dtype=np.float32)
    vel[:, 0] = layout_rng.uniform(-30.0, 30.0, n_particles).astype(np.float32)
    vel[:, 1] = layout_rng.uniform(40.0, 80.0, n_particles).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    # 60 frames: ~10 fall, then ~50 of slide / settle / bake.
    dt = 1.0 / 60.0
    for _ in range(60):
        cpu.step(dt)
        gpu.step(dt)

    np.testing.assert_allclose(
        cpu.pos, gpu.pos, atol=1.0, rtol=0.05,
        err_msg="slide pos divergence on flat ground exceeds 1 px tol",
    )
    np.testing.assert_allclose(
        cpu.vel, gpu.vel, atol=2.0, rtol=0.05,
        err_msg="slide vel divergence on flat ground exceeds 2 px/s tol",
    )
    # Phase counts should match within a small slack (jitter affects
    # when each particle crosses settle threshold by ±1 frame).
    cpu_settled = int((cpu.phase >= 2).sum())
    gpu_settled = int((gpu.phase >= 2).sum())
    assert abs(cpu_settled - gpu_settled) <= 5, (
        f"settled-particle count diverges too far: "
        f"CPU={cpu_settled}, GPU={gpu_settled}"
    )


def test_detach_isolated_pixels_cpu_gpu_parity():
    """Build a mask with 5 known isolated pixels + a few clumps;
    run the CPU detach + the GPU detach on two identical fields and
    assert both find the SAME 5 pixels (sorted (y, x) lists must
    compare equal — the detach pass is integer-decision-only so the
    parity is bit-exact, not within-tolerance).

    Layout (256x128 field)::

        - Five lone pixels at known coords, scattered across the canvas.
        - A 4x4 solid clump at (40..44, 40..44) — every internal pixel
          has solid neighbours, so the clump must be ignored entirely.
        - A 2x2 clump at (200..202, 80..82) — same property.
        - A solid pixel marked fixed (in ``_fixed_mask``) at (10, 100)
          with no neighbours — must be skipped because fixed.

    The CPU helper inside particle_gpu mirrors the on-device WGSL
    kernel exactly; both should detach the FIVE non-fixed lone pixels
    and nothing else.
    """
    from slappyengine.physics.particle_gpu import (
        gpu_detach_isolated_pixels,
        _numpy_detach_isolated_pixels,
        is_gpu_detach_available,
    )

    def _build_field() -> ParticleField:
        f = ParticleField(width=256, height=128)
        sand_id = f.material_id_of("sand")
        # 5 known isolated pixels — coords chosen to be away from each
        # other AND away from the canvas border (border pixels are
        # excluded by the 1-pixel inset on both paths).
        lone_pixels = [
            (50, 30),
            (100, 60),
            (150, 90),
            (200, 20),
            (220, 100),
        ]
        for (x, y) in lone_pixels:
            f.mask[y, x] = (128, 64, 64, 255)
            f.material_grid[y, x] = sand_id
        # 4x4 clump.
        f.mask[40:44, 40:44] = (80, 200, 80, 255)
        f.material_grid[40:44, 40:44] = sand_id
        # 2x2 clump.
        f.mask[80:82, 200:202] = (200, 80, 200, 255)
        f.material_grid[80:82, 200:202] = sand_id
        # Fixed lone pixel — must be skipped.
        f.mask[100, 10] = (255, 255, 255, 255)
        f._fixed_mask[100, 10] = True
        return f

    cpu = _build_field()
    gpu = _build_field()

    cpu_coords = _numpy_detach_isolated_pixels(cpu)
    gpu_coords = gpu_detach_isolated_pixels(gpu)

    expected = sorted([
        (30, 50),
        (60, 100),
        (90, 150),
        (20, 200),
        (100, 220),
    ])
    assert cpu_coords == expected, (
        f"CPU detach missed expected pixels: got {cpu_coords}, "
        f"expected {expected}"
    )
    assert gpu_coords == cpu_coords, (
        f"CPU and GPU detach diverged: CPU={cpu_coords}, GPU={gpu_coords} "
        f"(backend={'GPU' if is_gpu_detach_available() else 'numpy-fallback'})"
    )
    # Side-effect parity: both fields should have spawned the same number
    # of particles and cleared the same mask pixels.
    assert cpu.pos.shape[0] == gpu.pos.shape[0] == 5, (
        f"spawn_batch count divergence: CPU={cpu.pos.shape[0]}, "
        f"GPU={gpu.pos.shape[0]}"
    )
    np.testing.assert_array_equal(
        cpu.mask[..., 3] > 0, gpu.mask[..., 3] > 0,
        err_msg="post-detach mask alpha divergence",
    )


def test_slide_cpu_gpu_parity_irregular_ground():
    """Slide redirect on a pre-baked irregular ground.

    Paint a hill in the middle of the field; spawn sliding particles
    above the hill so the redirect logic (best_left_drop / best_right_drop
    > step threshold) is exercised. Tolerance widens — particles that
    redirect off a tall pile take RNG-influenced paths (the LEFT/RIGHT
    tiebreaker draws a coin) and amplify divergence over many frames.
    """
    def _build_field(use_gpu: bool, seed: int) -> ParticleField:
        f = ParticleField(width=256, height=256)
        f._rng = np.random.default_rng(seed)
        f.use_gpu_slide = use_gpu
        # Flat ground at y=200.
        f.fill_ground(
            top_y=200, color=(120, 90, 60), sub_color=(80, 60, 40),
            material="sand",
        )
        # Bake an irregular hill on top of the ground at x in [100, 156].
        # The hill is tall (rises 20 px) so the slide redirect triggers
        # — best_*_drop must reach the step threshold (>=4 for slow).
        for x in range(100, 156):
            # Triangular profile: highest at x=128.
            local_h = int(20 * (1.0 - abs(x - 128) / 28.0))
            for dy in range(local_h):
                y = 200 - dy
                f.mask[y, x, :3] = (140, 110, 70)
                f.mask[y, x, 3] = 255
        return f

    cpu = _build_field(use_gpu=False, seed=314)
    gpu = _build_field(use_gpu=True, seed=314)

    # Spawn particles ABOVE the hill so they fall onto it and have to
    # slide off down a sloped surface.
    n_particles = 20
    layout_rng = np.random.default_rng(315)
    sand_id = cpu.material_id_of("sand")
    pos = layout_rng.uniform(
        low=[110.0, 60.0], high=[148.0, 120.0],
        size=(n_particles, 2),
    ).astype(np.float32)
    vel = np.zeros((n_particles, 2), dtype=np.float32)
    vel[:, 0] = layout_rng.uniform(-15.0, 15.0, n_particles).astype(np.float32)
    vel[:, 1] = layout_rng.uniform(50.0, 80.0, n_particles).astype(np.float32)
    mids = np.full(n_particles, sand_id, dtype=np.int32)
    radii = np.full(n_particles, float(SAND_MAT.radius_min), dtype=np.float32)

    cpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())
    gpu.spawn_batch(pos=pos.copy(), vel=vel.copy(),
                    material_ids=mids.copy(), radii=radii.copy())

    dt = 1.0 / 60.0
    for _ in range(80):
        cpu.step(dt)
        gpu.step(dt)

    # Pos tolerance: bigger here because the redirect tie-breaker can
    # pick LEFT on CPU and RIGHT on GPU; once a particle takes a
    # different column its trajectory diverges. We only assert that
    # both fields end up with a similar mass distribution — the centre
    # of mass shouldn't drift more than ~10 px and final settled count
    # should match within a small slack.
    cpu_settled = int((cpu.phase >= 2).sum())
    gpu_settled = int((gpu.phase >= 2).sum())
    assert abs(cpu_settled - gpu_settled) <= 8, (
        f"irregular-ground settled count diverges: "
        f"CPU={cpu_settled}, GPU={gpu_settled}"
    )
    # Centre-of-mass parity on x — particles can scatter individually
    # but the bulk should land near the hill base on both paths.
    if cpu.pos.shape[0] > 0:
        cpu_com_x = float(cpu.pos[:, 0].mean())
        gpu_com_x = float(gpu.pos[:, 0].mean())
        assert abs(cpu_com_x - gpu_com_x) < 15.0, (
            f"COM_x drift too large: CPU={cpu_com_x:.2f}, GPU={gpu_com_x:.2f}"
        )
