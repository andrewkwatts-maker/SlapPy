"""slappyengine.deform_modes — Enumerations and config objects for DeformableLayerComponent.

All modes are game-independent. Game code selects presets and overrides
specific fields; the engine owns the semantics.
"""
from __future__ import annotations
import enum
import dataclasses
from typing import Callable


class DeformSimMode(enum.Enum):
    """Controls when the deformation physics simulation runs."""
    ALWAYS_ON = "always_on"
    # Shader dispatches every frame. stress/strain always authoritative.
    # Use for: shields, organic material, constantly-active sims.

    COLLISION_TRIGGERED = "collision_triggered"
    # Activates on collision event, runs through ACTIVE→SETTLING→STATIC.
    # GPU dispatches only while active. Zero cost at rest.
    # Use for: vehicles, crates, props — anything that should be static when undisturbed.

    MANUAL = "manual"
    # Caller controls via .activate() / .deactivate().
    # Use for: cutscene-triggered destruction, scripted events.


class DecayMode(enum.Enum):
    """Controls how elastic stress decays back to zero after impact."""
    CONSTANT = "constant"
    # Fixed spring_decay multiplier every frame.

    CURVE = "curve"
    # Piecewise linear [(time_elapsed_s, decay_rate), ...] sampled by time since activation.
    # Allows: slow wobble early, fast settling late.

    NONE = "none"
    # No decay at all. Elastic stress accumulates indefinitely.
    # Only meaningful with ALWAYS_ON sim mode.


class DestroyMode(enum.Enum):
    """What happens when integrity reaches zero."""
    PERSIST = "persist"
    # Entity stays, fully deformed. Publishes Deform.Destroyed.
    # Use for: wrecked vehicles, destroyed buildings that remain as obstacles.

    FRAGMENT = "fragment"
    # Publishes Deform.Fragment with pixel positions → game spawns debris.
    # Use for: glass shattering, wood splintering, crates exploding.

    REMOVE = "remove"
    # Entity removed from scene. Publishes Deform.Destroyed then Deform.Removed.
    # Use for: consumable pickups, thin props.

    RESPAWN = "respawn"
    # Publishes Deform.Destroyed → game handles respawn logic.
    # Use for: player vehicles, respawning enemies.

    DISABLE = "disable"
    # Stops collision/physics participation but stays visible.
    # Publishes Deform.Disabled.
    # Use for: rubble, fallen trees, spent shells.


class MaterialPreset(enum.Enum):
    """Named physics presets. Each maps to a config bundle (see MATERIAL_CONFIGS)."""
    METAL = "metal"
    # High elastic_threshold, plastic dents, no crack propagation.
    # Suitable for: vehicle bodies, machinery, containers.

    GLASS = "glass"
    # Very low threshold, instant plastic, radial shatter pattern.
    # Suitable for: windows, bottles, crystals.

    RUBBER = "rubber"
    # Very high elastic, near-zero plastic, bouncy decay curve.
    # Suitable for: tires, bumpers, balls, padding.

    WOOD = "wood"
    # Medium threshold, crack propagation along grain_map if provided.
    # Suitable for: crates, fences, furniture, trees.

    STONE = "stone"
    # Low elastic, high plastic, fracture crack lines, chunk separation.
    # Suitable for: walls, floors, boulders, concrete.

    CLOTH = "cloth"
    # Tears and drapes; directional weakness along warp axis.
    # Suitable for: flags, clothing, sails, tarps.

    ICE = "ice"
    # Crack propagation + shatter below force threshold; very low spring_decay.
    # Suitable for: frozen surfaces, ice walls, cryo effects.

    ORGANIC = "organic"
    # Slow elastic recovery, accumulating plastic. Heat-sensitive.
    # Suitable for: flesh, bark, mushrooms, soft terrain.

    # --- Physics-v2 additions (hierarchical hull simulator) -----------------
    STEEL = "steel"
    # Stiffer than METAL, higher yield, structural alloy.
    # Suitable for: armor plate, beams, heavy machinery.

    IRON = "iron"
    # Softer than STEEL, more ductile (dents readily).
    # Suitable for: vehicle bodies, cast hardware.

    CLAY = "clay"
    # Low E, low Y, high remold — settles back into shape slowly.
    # Suitable for: deformable terrain, putty, pottery.

    MUD = "mud"
    # Viscous fluid with high remold — splashes but settles.
    # Suitable for: wet ground, swampy terrain.

    WATER = "water"
    # Fluid; near-zero yield → no plastic, just flow.
    # Suitable for: pools, rain puddles, splashes.

    SAND = "sand"
    # Granular — low brittle threshold so grains scatter under stress.
    # Suitable for: dunes, beach, gravel.

    LAVA_GROUND = "lava_ground"
    # Pre-heated lava terrain (PERSIST destroy mode); pre-heat above melt threshold.
    # Suitable for: lava pools, magma terrain.

    LAVA = "lava"
    # Pre-heated lava chunks/projectiles (FRAGMENT destroy mode); slightly stiffer.
    # Suitable for: lava bombs, splashes, thrown molten rock.

    # --- Extended registry (richer material palette) ----------------------
    CONCRETE = "concrete"
    # Stiff, brittle, dense — fractures into rubble under sustained stress.
    # Suitable for: walls, slabs, urban debris.

    OIL = "oil"
    # Highly viscous fluid, no surface tension, near-zero restitution.
    # Suitable for: oil slicks, fuel spills, sticky industrial pools.

    SLIME = "slime"
    # Low-stiffness ductile material that re-forms its shape via remold.
    # Suitable for: monsters, ooze, putty traps.

    DIAMOND = "diamond"
    # Extreme stiffness; effectively unfracturable under common loads.
    # Suitable for: gem props, indestructible cores, jeweled armour.

    PAPER = "paper"
    # Lightweight and tear-prone; gives under modest stress.
    # Suitable for: scrolls, leaves, posters, cardstock.

    STEAM = "steam"
    # Ultra-low density gas; cools/evaporates quickly via high emissivity.
    # Suitable for: vents, kettle puffs, geyser plumes.

    CORAL = "coral"
    # Lightweight brittle organic; shatters but doesn't sink.
    # Suitable for: reef debris, calcified growth.

    GOLD = "gold"
    # Very ductile heavy metal; dents readily, never fractures.
    # Suitable for: bullion, jewelry, coins, dent-prone trim.

    MAGMA = "magma"
    # Hotter, more radiant variant of LAVA — melts neighbours faster.
    # Suitable for: volcano cores, lava bombs, hot eruption ejecta.

    SNOW = "snow"
    # Granular, soft, easily pushed aside; near-zero restitution.
    # Suitable for: snowbanks, powdery drifts, fresh snowfall.

    CUSTOM = "custom"
    # No preset overrides; use all manually specified kwargs.


class CrackMode(enum.Enum):
    """How cracks propagate from an impact point."""
    NONE = "none"
    # Radial alpha falloff only (fastest, current default).

    RADIAL = "radial"
    # Spider-web cracks radiating from impact center.
    # GPU shader traces N crack rays, attenuated by distance and alpha.

    GRAIN = "grain"
    # Cracks follow a grain_map texture (dark = weak grain lines).
    # Suitable for: wood grain, sheet metal stamping lines, concrete rebar gaps.

    STRUCTURAL = "structural"
    # Finds minimum-resistance paths through already-weakened pixels.
    # Most realistic; highest GPU cost. Suitable for: load-bearing walls, bridges.


class PhysicsCoupling(enum.Enum):
    """How deformation feeds back into the entity's physics state."""
    ISOLATED = "isolated"
    # Deformation is purely visual. No physics feedback (current default).

    MASS = "mass"
    # Lost pixels reduce entity mass → lighter = faster acceleration.
    # Publishes Deform.MassChanged with new_mass.

    DRAG = "drag"
    # Asymmetric damage changes aerodynamic drag profile.
    # Publishes Deform.DragChanged with drag_vector.

    COM = "com"
    # Off-center damage shifts center of mass → yaw bias in vehicle.
    # Publishes Deform.COMShifted with offset_x, offset_y.

    FULL = "full"
    # All of the above applied simultaneously.


class RepairMode(enum.Enum):
    """How and when the deformation restores toward original state."""
    NONE = "none"
    # Permanent damage. repair() calls are no-ops.

    AUTO = "auto"
    # Constant repair_rate applied every frame automatically.
    # Use for: shields, regenerating materials, healing terrain.

    AUTO_CURVE = "auto_curve"
    # Fast initial repair that slows as integrity approaches 1.0.
    # Feels organic. Same repair_curve format as decay_curve.

    EVENT_ONLY = "event_only"
    # Only on "Garage.RepairStart" or "Deform.RepairStart" event.
    # Current default for vehicles.

    BUDGET = "budget"
    # Shares a system-wide repair budget. Highest-priority entities repaired first.


class SimFrequency(enum.Enum):
    """How often the deformation simulation dispatches per second."""
    EVERY_FRAME = "every_frame"
    # Full simulation cost every frame (60Hz).

    EVERY_N_FRAMES = "every_n_frames"
    # Skip frames. n_frames configurable. Good for distant/unimportant objects.

    LOD_DISTANCE = "lod_distance"
    # Reduce simulation frequency based on camera distance.
    # Past streaming_radius_gpu: every 4 frames. Past streaming_radius_ram: every 8.

    BUDGET_DRIVEN = "budget_driven"
    # Engine allocates a per-frame ms budget across all active deformable entities.
    # Lowest-priority entities skip frames when budget is exhausted.


@dataclasses.dataclass
class ZoneConfig:
    """Config for a named pixel zone within a deformable layer.

    A zone is a rectangular or masked region of pixels with its own
    integrity threshold and destruction behavior.

    Attributes
    ----------
    name:
        Zone identifier used in event names, e.g. "front_bumper".
    integrity_threshold:
        Integrity fraction [0..1] below which this zone fires its destroy event.
    material:
        Material preset override for this zone only. None = inherit from parent.
    on_destroy_event:
        Event name published when zone integrity hits threshold.
        Payload includes: zone=name, entity=publisher, integrity=value.
    strength_scale:
        Multiplier on elastic_threshold for this zone (< 1 = weaker, > 1 = stronger).
    """
    name: str
    integrity_threshold: float = 0.0
    material: "MaterialPreset | None" = None
    on_destroy_event: str = "Deform.ZoneDestroyed"
    strength_scale: float = 1.0


@dataclasses.dataclass
class CellMaterial:
    """Per-material physical parameters driving the hierarchical-hull solver.

    Architectural invariant: **material drives system evolution, not the
    reverse**.  Every coefficient that the per-pixel kernel multiplies into
    its stress/strain/heat/fracture equations lives here, on the material
    — not in a global config block.  ``CellConfig`` retains only system
    parameters (grid resolution, numerical tolerances).

    Mechanical
    ----------
    E:
        Young's modulus — stress per unit elastic strain.  Used for the
        yield-surface / stress-tensor channels of the kernel.  For the
        elastic-wave Laplacian path the kernel reads ``E_effective``
        (derived from ``wave_crossing_frames``) instead, so the visible
        wave speed is decoupled from the yield arithmetic.  See Phase D
        wave-speed renormalisation (docs/next_phase_plan.md §3.2).
    wave_crossing_frames:
        Target number of 60 Hz frames for an elastic wave to traverse a
        single body's 32-cell grid.  Lower = stiffer / faster-propagating.
        Drives ``E_effective`` (Phase D).
    Y:
        von-Mises yield strength (ductile threshold).
    brittle_modulus:
        von-Mises stress above which bonds sever and cracks initiate.
        Use ``999`` to flag "not brittle".
    viscosity:
        Per-substep velocity-damping factor while bonds are intact.
    torn_damping:
        Damping factor when bonds have severed.  Near 1.0 keeps free
        fragments coasting; lower values drag them faster.  The kernel
        interpolates ``viscosity`` ↔ ``torn_damping`` by ``bond_intact``.
    density_rho:
        Material density (mass per unit world area).  Mass and inertia of
        a body are integrated from ``ρ × density_field`` over its cells.
    restitution:
        Rigid contact bounce coefficient.  Soft materials (mud, water) use
        ~0.05; stiff steel ~0.55.

    Bonding / fracture
    ------------------
    bond_intact_threshold, bond_intact_slope:
        Map ``tear`` field to the ``bond_intact`` fraction used in damping
        interpolation.  ``bond_intact = clamp(1 - max(0, tear - thr) * slope, 0, 1)``.
    brittle_damage_rate, brittle_tear_rate, brittle_bond_loss_rate,
    brittle_stretch_amplification:
        Per-second growth rates and amplifications applied when
        ``vm > brittle_modulus``.  Glass severs bonds fast (high values);
        wood resists (lower).
    ductile_plastic_strain_rate, ductile_poisson_ratio, ductile_damage_rate:
        Plastic-flow tuning along principal stress axes.
    tear_strength, tear_growth_rate:
        Stretch threshold + growth rate for gradient-driven tearing
        (separate from yield-driven brittle fracture).
    remold_rate:
        Plastic-strain decay back toward zero (clay anneals between hits).

    Thermal
    -------
    melt_point:
        Heat threshold above which the cell behaves liquid (anneal +
        viscous damping).
    melt_anneal_rate, melt_viscous_damping:
        How fast plastic strain relaxes and velocity damps in the liquid
        phase.
    thermal_k:
        Heat-diffusion coefficient (4-neighbour Laplacian rate).
    emissivity:
        Per-substep radiation loss; ``heat *= 1 - emissivity``.
    thermal_softening_coefficient:
        Yield weakening with heat: ``soft = 1 / (1 + heat * coeff)``.
    damage_weakening_coefficient:
        Yield weakening with damage: ``damage_factor = 1 - clamp(dmg * coeff, 0, coeff)``.
    heat_strain_energy_factor:
        How much plastic-work energy converts to heat.
    initial_heat:
        Starting heat for fresh cells (lava starts at ~12).

    Fluid
    -----
    is_fluid:
        Pressure-gradient force replaces the solid stress path.
    fluid_pressure_coupling, fluid_pressure_smoothing, fluid_pressure_decay:
        Per-material fluid tuning.

    Rendering
    ---------
    radiance:
        Self-emission for visualisation/lighting passes.
    noise_overlay_amplitude:
        Opt-in per-cell noise modulation in the renderer.  ``0.0`` (default)
        is bit-identical to no overlay — entire noise path is skipped.
        Non-zero values multiply each cell's painted RGB by
        ``(1 + amplitude * noise)`` where ``noise`` is a deterministic
        value-noise hash in ``[-1, 1]`` keyed on the cell's WORLD position
        and the current frame index.  Tuned values:

          mud   = 0.15 (brown grain)
          sand  = 0.25 (yellow grit)
          water = 0.10 (blue foam)
          snow  = 0.20 (white sparkle)
          lava  = 0.30 (orange flicker)
    noise_overlay_color:
        Optional tint applied to the noise term (so e.g. mud reads
        slightly brown rather than neutral).  Defaults to white, which
        produces a brightness-only modulation.
    """
    # Mechanical -----------------------------------------------------------
    E: float = 80.0
    # Phase D: per-material wave-crossing target (frames at 60 Hz for an
    # elastic wave to traverse a 32-cell body grid).  Drives ``E_effective``.
    # Stiff (steel/iron/diamond) → 3-4; concrete/glass/stone → 5-7;
    # wood/clay/sand → 7-10; mud/water/slime/oil → 10-20;
    # snow/paper → 15-25; gas (steam) → very large (no elastic waves).
    wave_crossing_frames: float = 8.0
    Y: float = 0.20
    brittle_modulus: float = 999.0
    viscosity: float = 0.95
    torn_damping: float = 0.999
    density_rho: float = 1.0
    restitution: float = 0.30
    # Per-material closing-speed threshold below which the rigid contact
    # restitution kick is forced to zero (plastic).  Granular materials
    # (sand, snow) opt in to a high threshold (~8.0) so settled stacks
    # don't buzz on the gravity half-kick — see ``test_demo_sand_pile``
    # and the WP-P resting-contact gate in ``physics/world.py``.  Every
    # other material defaults to ``0.0`` (gate disabled) so genuine
    # fracture / fluid-impact contacts still imprint their full elastic
    # kick on the cell field — that kick IS the cell-side velocity
    # inject that drives the von-Mises stress and brittle yield (see
    # WP-R fracture regression).  At a contact the solver uses
    # ``min(mat_a.thr, mat_b.thr, global_config.thr)``, so the high
    # sand threshold only fires when both sides opt in.  The original
    # WP-P global ceiling lives on as
    # ``CollisionConfig.restitution_velocity_threshold`` for callers
    # that want to force the gate on for every contact.
    restitution_velocity_threshold: float = 0.0
    # Friction (Coulomb stiction model) ----------------------------------
    # ``static_friction_coefficient`` (μ_s) is the threshold below which
    # surfaces "stick" — no tangential slip.  When the desired sticking
    # impulse exceeds μ_s·|jn|, the contact transitions to slip and the
    # tangential impulse is clamped by the smaller kinetic coefficient
    # (μ_k).  Physical materials always have μ_s ≥ μ_k.
    static_friction_coefficient: float = 0.4
    kinetic_friction_coefficient: float = 0.3
    # Bonding / fracture --------------------------------------------------
    bond_intact_threshold: float = 0.7
    bond_intact_slope: float = 3.0
    brittle_damage_rate: float = 18.0
    brittle_tear_rate: float = 15.0
    brittle_bond_loss_rate: float = 12.0
    brittle_stretch_amplification: float = 3.0
    ductile_plastic_strain_rate: float = 0.4
    ductile_poisson_ratio: float = 0.5
    ductile_damage_rate: float = 3.0
    tear_strength: float = 999.0
    tear_growth_rate: float = 8.0
    remold_rate: float = 0.0
    # Thermal -------------------------------------------------------------
    melt_point: float = 9.0
    melt_anneal_rate: float = 0.98
    melt_viscous_damping: float = 0.85
    thermal_k: float = 4.0
    emissivity: float = 0.002
    thermal_softening_coefficient: float = 0.08
    damage_weakening_coefficient: float = 0.6
    heat_strain_energy_factor: float = 2.0
    initial_heat: float = 0.0
    # Fluid ---------------------------------------------------------------
    is_fluid: bool = False
    fluid_pressure_coupling: float = 0.5
    fluid_pressure_smoothing: float = 0.20
    fluid_pressure_decay: float = 0.99
    # Phase C: Red-Black SOR sweeps for pressure projection enforcing
    # ∇·v=0.  0 disables the projection (legacy damped-pressure behaviour).
    #
    # Convergence on the 32×32 hull grid with omega=1.5 (measured on the
    # canonical Gaussian-divergence test field):
    #     iters=4  → 45% peak |div(v)| reduction
    #     iters=6  → 60% reduction
    #     iters=8  → 70% reduction
    #     iters=10 → 75% reduction
    #     iters=12 → 78% reduction
    # The default sits at 10: that gives water enough effective
    # incompressibility to push impactors against container walls (the
    # ``water_container`` demo's ball-wall bounce depends on having
    # ≥10 sweeps; the perf saving from going below that does not justify
    # losing the demo behaviour).  Materials that need higher fidelity
    # can opt up to 12; viscous fluids (mud, oil, lava) safely opt down
    # to 4 — their damping kills divergence between sweeps anyway.
    fluid_projection_iters: int = 10
    # Opt-in multi-grid V-cycle for the pressure projection.  Default
    # ``False`` keeps the single-grid Red-Black SOR path (above) bit-
    # identical to before; setting ``True`` routes ``_pressure_project_arrays``
    # through :func:`slappyengine.physics.pressure_multigrid.vcycle_project_v`,
    # which restricts the residual to a 16×16 coarse grid, solves there with
    # ``coarse_iters`` SOR sweeps, then prolongs the correction back.  Two
    # V-cycles beat 30+ single-grid sweeps on long-wavelength modes (large
    # water bodies, slow-sloshing pools).  Enabled on the WATER preset
    # because the canonical water_container demo's slosh is a textbook
    # long-wavelength mode.
    use_multigrid: bool = False
    # Rendering -----------------------------------------------------------
    radiance: float = 0.0
    # Opt-in renderer-only noise overlay.  Default 0.0 → fully skipped, no
    # perf or pixel-level cost.  Renderer reads these in the forward-splat
    # path (see ``slappyengine.physics.render``).
    noise_overlay_amplitude: float = 0.0
    noise_overlay_color: tuple[int, int, int] = (255, 255, 255)
    # --- Fluid surface shading (opt-in) ------------------------------------
    # ``foam_amplitude`` controls how strongly high-divergence regions of
    # the displacement field (turbulent zones, wave crests) are whitened in
    # the renderer.  0.0 disables foam entirely (no extra cost).  Typical
    # values: water 0.5, mud 0.3, oil 0.2, lava 0.4, ice 0.1.
    #
    # ``ripple_amplitude`` controls a sinusoidal highlight modulated by
    # |u_y| — visually suggests specular reflection on moving fluid
    # surfaces.  0.0 disables ripple shading.  Typical values: water 0.7,
    # mud 0.2, oil 0.5, lava 0.3, ice 0.4.
    #
    # Both effects only apply when ``is_fluid`` is also True; the renderer
    # gates on (is_fluid AND amplitude > 0) so non-fluid materials pay
    # zero cost.
    foam_amplitude: float = 0.0
    ripple_amplitude: float = 0.0

    # --- Phase D: derived effective elastic modulus -------------------------
    # The per-pixel kernel solves   v += (E * lap_u) * dt / mass
    # where ``lap_u`` is the 4-neighbour Laplacian in *grid index units*
    # (Δx = 1 cell).  The discrete wave speed is therefore
    #     c_grid = sqrt(E / rho)                  [cells / sec]
    # For a wave to cross ``CELL_GRID_SIZE = 32`` cells in
    # ``wave_crossing_frames`` frames at 60 Hz we need
    #     c_grid = CELL_GRID_SIZE * 60 / wave_crossing_frames
    # so the kernel must see an *effective* modulus of
    #     E_effective = rho * (CELL_GRID_SIZE * 60 / wave_crossing_frames)²
    # This decouples the wave-speed tuning from the raw ``E`` value that
    # other code (yield surface, plastic flow) still reads.  The kernel and
    # CFL planner read ``E_effective``; everything else keeps reading ``E``.
    @property
    def E_effective(self) -> float:
        # CELL_GRID_SIZE is the per-body cell-grid resolution.  Inlined as a
        # literal here to avoid importing the physics package from
        # deform_modes (which would create a circular dependency).
        from slappyengine.physics.cell import CELL_GRID_SIZE  # local import
        target = max(float(self.wave_crossing_frames), 1e-3)
        c_grid = (float(CELL_GRID_SIZE) * 60.0) / target
        return max(float(self.density_rho), 1e-6) * c_grid * c_grid

    # --- backward-compat aliases --------------------------------------------
    # Old name was ``bond_strength`` for the restitution coefficient.  Tests
    # and a few callers still read it; keep as a read-only proxy.
    @property
    def bond_strength(self) -> float:
        return self.restitution


@dataclasses.dataclass
class MaterialConfig:
    """Full config bundle for a material preset.

    This is what MaterialPreset maps to. Game code can instantiate
    MaterialConfig directly for fully custom materials.
    """
    elastic_threshold: float = 80.0
    spring_decay: float = 0.94
    decay_mode: DecayMode = DecayMode.CONSTANT
    decay_curve: "list[tuple[float, float]] | None" = None
    crack_mode: CrackMode = CrackMode.NONE
    crack_count: int = 6          # rays for RADIAL/GRAIN modes
    crack_length_px: float = 40.0
    destroy_mode: DestroyMode = DestroyMode.PERSIST
    repair_mode: RepairMode = RepairMode.EVENT_ONLY
    repair_rate: float = 1.0
    physics_coupling: PhysicsCoupling = PhysicsCoupling.ISOLATED
    sim_mode: DeformSimMode = DeformSimMode.COLLISION_TRIGGERED
    sim_frequency: SimFrequency = SimFrequency.EVERY_FRAME
    settle_threshold: float = 0.5
    settling_ramp_rate: float = 4.0
    # Per-cell physical params for the hierarchical-hull simulator. ``None``
    # for legacy presets that have not been wired to the v2 simulator yet.
    cell: "CellMaterial | None" = None


# ---------------------------------------------------------------------------
# Material preset → default config bundles
# ---------------------------------------------------------------------------

MATERIAL_CONFIGS: dict[MaterialPreset, MaterialConfig] = {
    MaterialPreset.METAL: MaterialConfig(
        elastic_threshold=80.0,
        spring_decay=0.94,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.00, 0.94), (0.15, 0.94), (0.20, 0.97), (0.28, 0.995)],
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.EVENT_ONLY,
        physics_coupling=PhysicsCoupling.COM,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Generic "metal" — mirrors the demo "iron" entry.
        cell=CellMaterial(
            E=300.0, Y=0.45, viscosity=0.985, density_rho=2.0,
            tear_strength=0.20, brittle_modulus=999.0, remold_rate=0.0,
            restitution=0.50, is_fluid=False,
            wave_crossing_frames=4.0,
        ),
    ),
    MaterialPreset.GLASS: MaterialConfig(
        elastic_threshold=5.0,
        spring_decay=0.60,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.RADIAL,
        crack_count=8,
        crack_length_px=60.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        settle_threshold=0.01,
        settling_ramp_rate=20.0,
        cell=CellMaterial(
            E=220.0, Y=0.08, viscosity=0.94, density_rho=1.0,
            tear_strength=0.03, brittle_modulus=0.3, remold_rate=0.0,
            restitution=0.40, is_fluid=False,
            wave_crossing_frames=6.0,
        ),
    ),
    MaterialPreset.RUBBER: MaterialConfig(
        elastic_threshold=200.0,
        spring_decay=0.88,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.00, 0.88), (0.30, 0.92), (0.50, 0.96)],
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.AUTO,
        repair_rate=2.0,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        cell=CellMaterial(
            E=80.0, Y=999.0, viscosity=0.92, density_rho=1.1,
            tear_strength=999.0, brittle_modulus=999.0, remold_rate=0.0,
            restitution=0.85, is_fluid=False,
            static_friction_coefficient=0.85, kinetic_friction_coefficient=0.75,
            wave_crossing_frames=10.0,
        ),
    ),
    MaterialPreset.WOOD: MaterialConfig(
        elastic_threshold=30.0,
        spring_decay=0.96,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.GRAIN,
        crack_count=4,
        crack_length_px=50.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_N_FRAMES,
        cell=CellMaterial(
            E=100.0, Y=0.10, viscosity=0.92, density_rho=0.7,
            tear_strength=0.10, brittle_modulus=0.4, remold_rate=0.0,
            restitution=0.25, is_fluid=False,
            wave_crossing_frames=8.0,
        ),
    ),
    MaterialPreset.STONE: MaterialConfig(
        elastic_threshold=10.0,
        spring_decay=0.98,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.STRUCTURAL,
        crack_count=5,
        crack_length_px=80.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_N_FRAMES,
        settle_threshold=0.05,
        cell=CellMaterial(
            E=180.0, Y=0.20, viscosity=0.97, density_rho=1.6,
            tear_strength=0.06, brittle_modulus=0.6, remold_rate=0.0,
            restitution=0.30, is_fluid=False,
            wave_crossing_frames=6.0,
        ),
    ),
    MaterialPreset.CLOTH: MaterialConfig(
        elastic_threshold=15.0,
        spring_decay=0.90,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.0, 0.90), (0.5, 0.95)],
        crack_mode=CrackMode.GRAIN,
        crack_count=2,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.DRAG,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # No direct demo entry — cloth is not wired to v2 yet.
        cell=None,
    ),
    MaterialPreset.ICE: MaterialConfig(
        elastic_threshold=8.0,
        spring_decay=0.50,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.RADIAL,
        crack_count=12,
        crack_length_px=90.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        settle_threshold=0.02,
        settling_ramp_rate=30.0,
        cell=CellMaterial(
            E=160.0, Y=0.05, viscosity=0.96, density_rho=0.9,
            tear_strength=0.04, brittle_modulus=0.25, remold_rate=0.0,
            restitution=0.20, is_fluid=False,
            static_friction_coefficient=0.05, kinetic_friction_coefficient=0.03,
            wave_crossing_frames=6.0,
            # Ice is solid (is_fluid=False) so the renderer's foam/ripple
            # gate will skip these — kept for completeness/parity with the
            # spec table.
            foam_amplitude=0.1,
            ripple_amplitude=0.4,
        ),
    ),
    MaterialPreset.ORGANIC: MaterialConfig(
        elastic_threshold=25.0,
        spring_decay=0.97,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.0, 0.97), (0.5, 0.975), (2.0, 0.99)],
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.AUTO_CURVE,
        repair_rate=0.5,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.LOD_DISTANCE,
        # No direct demo entry — modelled after soft ductile clay.
        cell=CellMaterial(
            E=40.0, Y=0.05, viscosity=0.88, density_rho=1.4,
            tear_strength=0.40, brittle_modulus=999.0, remold_rate=0.05,
            restitution=0.10, is_fluid=False,
            wave_crossing_frames=12.0,
        ),
    ),
    # --- Physics-v2 presets -------------------------------------------------
    MaterialPreset.STEEL: MaterialConfig(
        elastic_threshold=100.0,
        spring_decay=0.95,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.00, 0.95), (0.15, 0.96), (0.30, 0.99)],
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.EVENT_ONLY,
        physics_coupling=PhysicsCoupling.COM,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        cell=CellMaterial(
            E=300.0, Y=0.30, brittle_modulus=2.5, density_rho=2.4,
            tear_strength=2.0, remold_rate=0.0, is_fluid=False,
            viscosity=0.985, restitution=0.55,
            wave_crossing_frames=3.0,
        ),
    ),
    MaterialPreset.IRON: MaterialConfig(
        elastic_threshold=80.0,
        spring_decay=0.94,
        decay_mode=DecayMode.CURVE,
        decay_curve=[(0.00, 0.94), (0.15, 0.94), (0.20, 0.97), (0.28, 0.995)],
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.EVENT_ONLY,
        physics_coupling=PhysicsCoupling.COM,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        cell=CellMaterial(
            E=200.0, Y=0.18, brittle_modulus=2.0, density_rho=2.0,
            tear_strength=1.2, remold_rate=0.0, is_fluid=False,
            viscosity=0.985, restitution=0.50,
            wave_crossing_frames=4.0,
        ),
    ),
    MaterialPreset.CLAY: MaterialConfig(
        elastic_threshold=15.0,
        spring_decay=0.88,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        cell=CellMaterial(
            E=40.0, Y=0.04, brittle_modulus=999.0, density_rho=1.3,
            tear_strength=999.0, remold_rate=0.01, is_fluid=False,
            viscosity=0.88, restitution=0.10,
            wave_crossing_frames=10.0,
        ),
    ),
    MaterialPreset.MUD: MaterialConfig(
        elastic_threshold=8.0,
        spring_decay=0.55,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # High-viscosity fluid behaviour — splashes but settles.
        # Viscous fluids spread their divergence quickly through the
        # damping term, so the projection has less low-frequency content
        # to relax; 4 sweeps is plenty for the visible mud splash.
        cell=CellMaterial(
            E=15.0, Y=0.02, brittle_modulus=999.0, density_rho=1.2,
            tear_strength=999.0, remold_rate=0.02, is_fluid=True,
            viscosity=0.55, restitution=0.05,
            static_friction_coefficient=0.7, kinetic_friction_coefficient=0.5,
            wave_crossing_frames=14.0,
            fluid_projection_iters=4,
            # Brown grainy mud surface.
            noise_overlay_amplitude=0.15,
            noise_overlay_color=(110, 80, 50),
            foam_amplitude=0.3,
            ripple_amplitude=0.2,
        ),
    ),
    MaterialPreset.WATER: MaterialConfig(
        elastic_threshold=2.0,
        spring_decay=0.50,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        cell=CellMaterial(
            E=10.0, Y=999.0, brittle_modulus=999.0, density_rho=1.0,
            tear_strength=999.0, remold_rate=0.0, is_fluid=True,
            viscosity=0.95, restitution=0.05,
            static_friction_coefficient=0.0, kinetic_friction_coefficient=0.0,
            wave_crossing_frames=12.0,
            # Multi-grid V-cycle handles the long-wavelength slosh modes
            # that single-grid SOR struggles with on a 32-cell water pool.
            use_multigrid=True,
            # Subtle blue foam/sparkle on water.
            noise_overlay_amplitude=0.10,
            noise_overlay_color=(180, 210, 255),
            foam_amplitude=0.5,
            ripple_amplitude=0.7,
        ),
    ),
    MaterialPreset.SAND: MaterialConfig(
        elastic_threshold=10.0,
        spring_decay=0.85,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Granular — low brittle threshold so grains scatter under stress.
        cell=CellMaterial(
            E=25.0, Y=0.06, brittle_modulus=0.8, density_rho=1.5,
            tear_strength=0.5, remold_rate=0.01, is_fluid=False,
            viscosity=0.90, restitution=0.10,
            wave_crossing_frames=8.0,
            # WP-P / WP-R: granular piles need an 8.0 closing-speed gate
            # so the gravity half-kick on settled stacks doesn't re-inject
            # ``rest * v_gravity`` per frame as spurious KE.  This is the
            # opt-in granular case for the WP-R per-material gate; every
            # other material defaults to 0.0 (no gate).
            restitution_velocity_threshold=8.0,
            # Yellow grit on sand — strongest grain of the four.
            noise_overlay_amplitude=0.25,
            noise_overlay_color=(230, 200, 130),
        ),
    ),
    MaterialPreset.LAVA_GROUND: MaterialConfig(
        elastic_threshold=8.0,
        spring_decay=0.65,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Pre-heated above melt threshold (cell.melt_point default = 9.0).
        # Viscous molten material → 4 sweeps suffice.
        cell=CellMaterial(
            E=30.0, Y=0.05, brittle_modulus=999.0, density_rho=1.6,
            tear_strength=999.0, remold_rate=0.005, is_fluid=True,
            viscosity=0.65, restitution=0.10,
            initial_heat=12.0, radiance=8.0,
            wave_crossing_frames=14.0,
            fluid_projection_iters=4,
            foam_amplitude=0.4,
            ripple_amplitude=0.3,
        ),
    ),
    MaterialPreset.LAVA: MaterialConfig(
        elastic_threshold=10.0,
        spring_decay=0.65,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Same physical params as LAVA_GROUND but stiffer (E=50) and Fragment.
        # Viscous molten material → 4 sweeps suffice.
        cell=CellMaterial(
            E=50.0, Y=0.05, brittle_modulus=999.0, density_rho=1.6,
            tear_strength=999.0, remold_rate=0.005, is_fluid=True,
            viscosity=0.65, restitution=0.10,
            initial_heat=12.0, radiance=8.0,
            wave_crossing_frames=12.0,
            fluid_projection_iters=4,
            # Orange flickering surface — strongest amplitude to read as "lava".
            noise_overlay_amplitude=0.30,
            noise_overlay_color=(255, 140, 40),
            foam_amplitude=0.4,
            ripple_amplitude=0.3,
        ),
    ),
    # --- Extended registry --------------------------------------------------
    MaterialPreset.CONCRETE: MaterialConfig(
        elastic_threshold=12.0,
        spring_decay=0.97,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.STRUCTURAL,
        crack_count=6,
        crack_length_px=80.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_N_FRAMES,
        settle_threshold=0.05,
        # Stiff (E=250) and very brittle (low brittle_modulus, fast damage/tear).
        cell=CellMaterial(
            E=250.0, Y=0.25, brittle_modulus=0.5, density_rho=2.4,
            tear_strength=0.05, remold_rate=0.0, is_fluid=False,
            viscosity=0.97, restitution=0.10,
            brittle_damage_rate=22.0, brittle_tear_rate=18.0,
            wave_crossing_frames=5.0,
        ),
    ),
    MaterialPreset.OIL: MaterialConfig(
        elastic_threshold=2.0,
        spring_decay=0.45,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Highly viscous fluid: low E, no yield, near-zero restitution.
        # Very viscous → divergence is killed by damping; 4 sweeps suffice.
        cell=CellMaterial(
            E=8.0, Y=999.0, brittle_modulus=999.0, density_rho=0.92,
            tear_strength=999.0, remold_rate=0.0, is_fluid=True,
            viscosity=0.45, restitution=0.02,
            wave_crossing_frames=18.0,
            fluid_projection_iters=4,
            foam_amplitude=0.2,
            ripple_amplitude=0.5,
        ),
    ),
    MaterialPreset.SLIME: MaterialConfig(
        elastic_threshold=10.0,
        spring_decay=0.80,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.AUTO,
        repair_rate=1.0,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Low-stiffness ductile with high remold rate — re-forms its shape.
        cell=CellMaterial(
            E=20.0, Y=0.03, brittle_modulus=999.0, density_rho=1.1,
            tear_strength=999.0, remold_rate=0.05, is_fluid=False,
            viscosity=0.85, restitution=0.20,
            wave_crossing_frames=12.0,
        ),
    ),
    MaterialPreset.DIAMOND: MaterialConfig(
        elastic_threshold=300.0,
        spring_decay=0.99,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Extreme E, very high yield, brittle_modulus high enough that common
        # contact stresses never reach it — effectively unfracturable.
        cell=CellMaterial(
            E=600.0, Y=2.0, brittle_modulus=12.0, density_rho=3.5,
            tear_strength=999.0, remold_rate=0.0, is_fluid=False,
            viscosity=0.99, restitution=0.85,
            wave_crossing_frames=3.0,
        ),
    ),
    MaterialPreset.PAPER: MaterialConfig(
        elastic_threshold=6.0,
        spring_decay=0.85,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.GRAIN,
        crack_count=3,
        crack_length_px=40.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Very tear-prone: low tear_strength + high tear_growth_rate.
        cell=CellMaterial(
            E=20.0, Y=0.05, brittle_modulus=999.0, density_rho=0.4,
            tear_strength=0.3, tear_growth_rate=20.0, remold_rate=0.0,
            is_fluid=False, viscosity=0.90, restitution=0.10,
            wave_crossing_frames=18.0,
        ),
    ),
    MaterialPreset.STEAM: MaterialConfig(
        elastic_threshold=1.0,
        spring_decay=0.40,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.REMOVE,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Ultra-low density gas; high emissivity → quick radiative cooling.
        cell=CellMaterial(
            E=2.0, Y=999.0, brittle_modulus=999.0, density_rho=0.05,
            tear_strength=999.0, remold_rate=0.0, is_fluid=True,
            viscosity=0.50, restitution=0.02,
            emissivity=0.05,
            wave_crossing_frames=30.0,
        ),
    ),
    MaterialPreset.CORAL: MaterialConfig(
        elastic_threshold=20.0,
        spring_decay=0.95,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.RADIAL,
        crack_count=6,
        crack_length_px=45.0,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Brittle but lightweight organic — between glass and wood.
        cell=CellMaterial(
            E=120.0, Y=0.10, brittle_modulus=0.4, density_rho=1.5,
            tear_strength=0.08, remold_rate=0.0, is_fluid=False,
            viscosity=0.94, restitution=0.20,
            wave_crossing_frames=7.0,
        ),
    ),
    MaterialPreset.GOLD: MaterialConfig(
        elastic_threshold=70.0,
        spring_decay=0.93,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.EVENT_ONLY,
        physics_coupling=PhysicsCoupling.COM,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Very ductile heavy metal — low yield, high plastic-strain rate,
        # brittle_modulus parked at 999 so it never fractures.
        cell=CellMaterial(
            E=180.0, Y=0.10, brittle_modulus=999.0, density_rho=4.0,
            tear_strength=999.0, remold_rate=0.0, is_fluid=False,
            viscosity=0.98, restitution=0.35,
            ductile_plastic_strain_rate=0.5,
            wave_crossing_frames=5.0,
        ),
    ),
    MaterialPreset.MAGMA: MaterialConfig(
        elastic_threshold=10.0,
        spring_decay=0.65,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.FRAGMENT,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.ISOLATED,
        sim_mode=DeformSimMode.ALWAYS_ON,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Hotter than LAVA (initial_heat 18 > melt_point 9) and more radiant.
        # Viscous molten material → 4 sweeps suffice.
        cell=CellMaterial(
            E=50.0, Y=0.05, brittle_modulus=999.0, density_rho=1.6,
            tear_strength=999.0, remold_rate=0.005, is_fluid=True,
            viscosity=0.65, restitution=0.10,
            initial_heat=18.0, radiance=12.0,
            wave_crossing_frames=10.0,
            fluid_projection_iters=4,
        ),
    ),
    MaterialPreset.SNOW: MaterialConfig(
        elastic_threshold=4.0,
        spring_decay=0.80,
        decay_mode=DecayMode.CONSTANT,
        crack_mode=CrackMode.NONE,
        destroy_mode=DestroyMode.PERSIST,
        repair_mode=RepairMode.NONE,
        physics_coupling=PhysicsCoupling.MASS,
        sim_mode=DeformSimMode.COLLISION_TRIGGERED,
        sim_frequency=SimFrequency.EVERY_FRAME,
        # Granular powder: low E, low Y, low brittle threshold, very low restitution.
        cell=CellMaterial(
            E=8.0, Y=0.03, brittle_modulus=0.2, density_rho=0.3,
            tear_strength=0.6, remold_rate=0.005, is_fluid=False,
            viscosity=0.85, restitution=0.05,
            wave_crossing_frames=20.0,
            # Granular: opt in to the WP-R closing-speed gate (matches sand).
            restitution_velocity_threshold=8.0,
            # White sparkle on snow.
            noise_overlay_amplitude=0.20,
            noise_overlay_color=(255, 255, 255),
        ),
    ),
    MaterialPreset.CUSTOM: MaterialConfig(),  # all defaults, user overrides everything
}


def resolve_material(
    preset: MaterialPreset,
    **overrides,
) -> MaterialConfig:
    """Return a MaterialConfig for *preset* with any kwargs applied as overrides.

    Example
    -------
    >>> cfg = resolve_material(MaterialPreset.METAL, elastic_threshold=60.0)
    >>> cfg.elastic_threshold
    60.0
    """
    import dataclasses as dc
    base = MATERIAL_CONFIGS[preset]
    if not overrides:
        return base
    return dc.replace(base, **overrides)


# ---------------------------------------------------------------------------
# Custom material registry — runtime-editable presets
# ---------------------------------------------------------------------------

_CUSTOM_MATERIALS: dict[str, MaterialConfig] = {}


def register_material(name: str, config: MaterialConfig) -> None:
    """Register a custom material preset at runtime.

    If *name* matches an existing MaterialPreset enum value, overrides it.
    Otherwise adds a custom entry accessible via :func:`get_material`.

    Parameters
    ----------
    name:
        Identifier string.  Use a MaterialPreset value (e.g. ``"metal"``) to
        shadow a built-in preset; use any other string for a new custom preset.
    config:
        MaterialConfig to associate with *name*.
    """
    _CUSTOM_MATERIALS[name] = config


def unregister_material(name: str) -> None:
    """Remove a custom material preset registered via :func:`register_material`.

    No-op if *name* was never registered.
    """
    _CUSTOM_MATERIALS.pop(name, None)


def get_material(name: str) -> "MaterialConfig | None":
    """Return a MaterialConfig by name string.

    Lookup order
    ------------
    1. Custom registry (allows overriding built-ins).
    2. Built-in MaterialPreset enum by value string.

    Returns ``None`` if *name* is not found in either registry.
    """
    # Custom registry first — allows shadowing built-in presets
    if name in _CUSTOM_MATERIALS:
        return _CUSTOM_MATERIALS[name]
    # Fall back to built-in enum
    try:
        preset = MaterialPreset(name)
        return MATERIAL_CONFIGS.get(preset)
    except ValueError:
        return None


def cell_material_for(name: str) -> "CellMaterial | None":
    """Look up the per-cell physical params for a material by name.

    Convenience wrapper that resolves *name* via :func:`get_material` and
    returns the attached :class:`CellMaterial`, or ``None`` if the material
    is unknown or has no v2 cell params yet.
    """
    mc = get_material(name)
    if mc is None:
        return None
    return mc.cell


def list_materials() -> "list[str]":
    """Return all available material names (built-in enum values + custom).

    Built-in names appear first, in enum definition order.  Custom names
    follow in insertion order.
    """
    builtin = [p.value for p in MaterialPreset]
    custom = [k for k in _CUSTOM_MATERIALS if k not in builtin]
    return builtin + custom
