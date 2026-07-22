"""PhysicsWorld — top-level frame loop for the hierarchical-hull simulator.

Sprint 1 scope (this file):
  - Body authoring (``create_body``) producing a root hull + optional T2 grid.
  - Per-frame loop: integrate transforms → apply gravity → AABB broadphase →
    rigid contact resolution → optional CPU per-pixel substep on T2 hulls →
    drop bookkeeping (settling / dirty flags).
  - CPU-numpy per-pixel solver shim (``_cpu_substep``) that mirrors the WGSL
    kernel's elasticity + plastic + tear paths so Sprint 1 drop-tests can
    assert visible per-pixel behaviour without GPU plumbing. Sprint 2 swaps
    this for indirect-dispatched WGSL.

Notation:
  - All vectors are float32 ``np.ndarray``s of shape ``(2,)`` or ``(N, 2)``.
  - World y is *down-positive* (gravity points to +y); positions are in
    pixels at the engine's reference scale.
"""
from __future__ import annotations

import struct
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml

from pharos_engine._compat import (
    CellMaterial,
    cell_material_for,
)
from pharos_engine.physics.body import (
    PhysicsBody,
    silhouette_to_cells,
)
from pharos_engine.physics.boundary_exchange import BoundaryExchange
from pharos_engine.physics.broadphase import SpatialHashBroadphase
from pharos_engine.physics.cell import (
    CELL_GRID_SIZE,
    CellGridPool,
)
from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver
from pharos_engine.physics.hull import (
    HullTree,
    NO_CELL_GRID,
    TIER_T2,
)


# -- Config loading ---------------------------------------------------------

@dataclass
class WorldConfig:
    default_dt: float = 1.0 / 60.0
    substeps: int = 4
    gravity: tuple[float, float] = (0.0, 196.0)
    # Debug-only post-step NaN/inf assertion.  When True, ``PhysicsWorld.step``
    # scans every active cell grid after the substep loop and raises if any
    # channel contains a non-finite value — surfaces future kernel regressions
    # at the exact frame the corruption enters the state.  Default False keeps
    # the per-frame cost at zero for release builds; tests / debug runs opt in.
    debug_assert_finite: bool = False


@dataclass
class HullConfig:
    initial_hull_capacity: int = 256
    initial_cell_grid_capacity: int = 64
    settle_frames: int = 30


@dataclass
class CellConfig:
    grid_size: int = 32
    damping_when_torn: float = 0.999
    bond_intact_threshold: float = 0.7
    bond_intact_slope: float = 3.0
    brittle_damage_rate: float = 18.0
    brittle_tear_rate: float = 15.0
    brittle_bond_loss_rate: float = 12.0
    brittle_stretch_amplification: float = 3.0
    # Catastrophic brittle fracture: when the von-Mises excess crosses
    # ``brittle_eff * brittle_catastrophic_excess_ratio`` the cell's bond on
    # the dominant-stress axis AND its sibling on the perpendicular axis are
    # severed in a single substep (set to 0).  Models real brittle materials
    # (glass, ceramic, ice): once the critical-stress envelope is exceeded
    # the bond simply shatters — there is no gradual accumulation of damage
    # at that cell.  Without this gate the per-substep ``bond_loss = excess *
    # dt * rate * (1 + stretch * amp)`` only drives bonds at the impact
    # site from 1.0 → ~0.65 over the contact duration, which leaves the
    # post-impact bond field with diffuse weakening but no severed-bond
    # line — ``cc_label`` then reports a single connected cluster and
    # fragmentation never fires (the ``test_demo_destructible_wall`` /
    # ``test_glass_shatters`` regression that motivated WP-V).
    brittle_catastrophic_excess_ratio: float = 3.0
    # When the gate fires, set the severed bond to this floor (0 = fully
    # disconnected, slightly positive lets cc_label preserve a thin remnant
    # if desired for art-direction).  Default 0.
    brittle_catastrophic_bond_floor: float = 0.0
    # Catastrophic severance only fires once the per-substep accumulation
    # path has driven ``damage`` past this gate.  Prevents the first impulse
    # from flash-fragmenting an intact body; gives the cumulative path a
    # chance to localise damage to the impact zone first.
    brittle_catastrophic_damage_gate: float = 0.4
    ductile_plastic_strain_rate: float = 0.4
    ductile_poisson_ratio: float = 0.5
    ductile_damage_rate: float = 3.0
    tear_growth_rate: float = 8.0
    thermal_softening_rate: float = 0.08
    damage_weakening_rate: float = 0.6
    melt_heat: float = 9.0
    melt_anneal_rate: float = 0.98
    melt_viscous_damping: float = 0.85
    heat_diffusion_rate: float = 4.0
    heat_damping_to_heat_factor: float = 0.5
    heat_radiation_decay: float = 0.998
    heat_strain_energy_factor: float = 2.0
    fluid_pressure_coupling: float = 0.5
    fluid_pressure_smoothing: float = 0.20
    fluid_pressure_decay: float = 0.99
    silhouette_mask_threshold: float = 0.05


@dataclass
class CollisionConfig:
    contact_pair_max: int = 2048
    # Resting-contact threshold (Box2D/Bullet convention).  When the
    # relative normal velocity at a contact is below this magnitude (in
    # world units / second), restitution is treated as zero.  Without
    # this, a stack of bodies under constant gravity will rebound a small
    # ``rest * v_gravity`` upward every frame and that buzz accumulates
    # as spurious KE — see ``test_demo_sand_pile`` which catches the
    # symptom.  Physically: a bouncing ball only bounces above a finite
    # closing speed; gentler taps are absorbed plastically.
    restitution_velocity_threshold: float = 8.0


@dataclass
class GpuConfig:
    """GPU dispatch toggle for the per-pixel kernel.

    ``indirect_dispatch`` switches the per-pixel kernel from one-dispatch-
    per-hull (legacy) to a single indirect-dispatched mega-kernel that
    serves all active T2 hulls at once.  See ``per_pixel_sim.wgsl`` for
    the workgroup_id.z indexing scheme.

    ``persistent_residency`` (default True) keeps the cell-pool buffer
    on the device between dispatches and only re-uploads slots the CPU
    has dirtied since the last GPU substep.  The A/B numbers that
    justify the default live in ``docs/persistent_residency_decision.md``.
    """
    enabled: bool = True
    # Historical guard for a GPU substep that silently zeroed cell state in
    # real scenes (parity test passed because it explicitly injected + marked
    # active; real scenes route through the impulse-driven inject inside the
    # contact resolver).  The full-world-step drop reproducer in
    # ``python/tests/test_gpu_silent_zero_regression.py`` now confirms the
    # GPU and CPU paths produce identical per-cell state, so the default
    # has been flipped back to False.  Leave the flag wired so individual
    # tests / debug sessions can still force the CPU canonical reference.
    debug_force_cpu: bool = False
    # Flipped to True after benchmarks/indirect_vs_per_hull.py showed
    # indirect dispatch is 30-32% faster on dispatch-heavy scenarios
    # (fluid_pool, fracture) and within μs-noise on all others.  See
    # docs/indirect_dispatch_decision.md for the per-scenario table.
    indirect_dispatch: bool = True
    # Phase B — only upload cells the CPU has dirtied since the last
    # dispatch.  Default flipped to True after A/B benchmarks showed
    # persistent residency is 6.2× faster on ``fracture`` and 7.6×
    # faster on ``fluid_pool`` (driven by skipping the per-substep
    # full-pool blast), within noise on the dispatch-free scenarios
    # (``multi_body_*``, ``idle_settled``), and never slower.  Parity
    # against the legacy full-upload path is locked in by
    # ``python/tests/test_persistent_residency_default.py`` across all
    # six baseline scenarios plus the glass-shatter fracture event.
    # Flip to ``False`` (or set ``gpu.persistent_residency: false`` in
    # ``config/physics.yml``) to revert to legacy full-pool uploads
    # when debugging a stale-slot suspect.  See
    # ``docs/persistent_residency_decision.md`` for the per-scenario
    # numbers and ``docs/next_phase_plan.md`` §3.2.B for the design.
    persistent_residency: bool = True


@dataclass
class BoundaryExchangeConfig:
    """Per-frame heat-conduction pass across contact seams."""
    enabled: bool = True
    strip_depth: int = 3  # cells deep per side of the seam


@dataclass
class FrontierYamlConfig:
    """Phase A frontier-solver wiring: enables auto-tick from ``step()``.

    The actual disagreement thresholds live on
    :class:`pharos_engine.physics.frontier.FrontierConfig`. This wrapper
    only carries the world-level enable flag plus the solver tunables we
    forward into ``FrontierConfig`` when the world lazy-constructs its
    solver.
    """
    enabled: bool = True
    velocity_std_threshold_high: float = 0.5
    velocity_std_threshold_low: float = 0.1
    damage_std_threshold_high: float = 0.05
    damage_std_threshold_low: float = 0.01
    coalesce_hysteresis_frames: int = 4
    max_depth: int = 3
    enable_subdivide: bool = True
    enable_coalesce: bool = True


@dataclass
class EventsConfig:
    """Tunables for the auto-publish bridge wired by PhysicsEngineBridge."""
    impact_impulse_threshold: float = 1.0


@dataclass
class PhysicsYaml:
    world: WorldConfig = field(default_factory=WorldConfig)
    hull: HullConfig = field(default_factory=HullConfig)
    cell: CellConfig = field(default_factory=CellConfig)
    collision: CollisionConfig = field(default_factory=CollisionConfig)
    gpu: GpuConfig = field(default_factory=GpuConfig)
    boundary_exchange: BoundaryExchangeConfig = field(default_factory=BoundaryExchangeConfig)
    frontier: FrontierYamlConfig = field(default_factory=FrontierYamlConfig)
    events: EventsConfig = field(default_factory=EventsConfig)


def _find_physics_yml() -> Path | None:
    """Walk up from this file looking for ``config/physics.yml``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "config" / "physics.yml"
        if cand.exists():
            return cand
    return None


def load_physics_config(path: str | Path | None = None) -> PhysicsYaml:
    """Load ``config/physics.yml`` (or return defaults if absent)."""
    if path is None:
        path = _find_physics_yml()
    if path is None or not Path(path).exists():
        return PhysicsYaml()
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    def _sub(d: dict, key: str) -> dict:
        v = d.get(key, {})
        return v if isinstance(v, dict) else {}

    w_raw = _sub(raw, "world")
    g = w_raw.get("gravity", [0.0, 196.0])
    world = WorldConfig(
        default_dt=float(w_raw.get("default_dt", 1.0 / 60.0)),
        substeps=int(w_raw.get("substeps", 4)),
        gravity=(float(g[0]), float(g[1])),
    )

    h_raw = _sub(raw, "hull")
    hull_cfg = HullConfig(
        initial_hull_capacity=int(h_raw.get("initial_hull_capacity", 256)),
        initial_cell_grid_capacity=int(h_raw.get("initial_cell_grid_capacity", 64)),
        settle_frames=int(h_raw.get("settle_frames", 30)),
    )

    c_raw = _sub(raw, "cell")
    defaults = CellConfig()
    cell_cfg = CellConfig(
        grid_size=int(c_raw.get("grid_size", defaults.grid_size)),
        damping_when_torn=float(c_raw.get("damping_when_torn", defaults.damping_when_torn)),
        bond_intact_threshold=float(c_raw.get("bond_intact_threshold", defaults.bond_intact_threshold)),
        bond_intact_slope=float(c_raw.get("bond_intact_slope", defaults.bond_intact_slope)),
        brittle_damage_rate=float(c_raw.get("brittle_damage_rate", defaults.brittle_damage_rate)),
        brittle_tear_rate=float(c_raw.get("brittle_tear_rate", defaults.brittle_tear_rate)),
        brittle_bond_loss_rate=float(c_raw.get("brittle_bond_loss_rate", defaults.brittle_bond_loss_rate)),
        brittle_stretch_amplification=float(c_raw.get("brittle_stretch_amplification", defaults.brittle_stretch_amplification)),
        brittle_catastrophic_excess_ratio=float(c_raw.get("brittle_catastrophic_excess_ratio", defaults.brittle_catastrophic_excess_ratio)),
        brittle_catastrophic_bond_floor=float(c_raw.get("brittle_catastrophic_bond_floor", defaults.brittle_catastrophic_bond_floor)),
        brittle_catastrophic_damage_gate=float(c_raw.get("brittle_catastrophic_damage_gate", defaults.brittle_catastrophic_damage_gate)),
        ductile_plastic_strain_rate=float(c_raw.get("ductile_plastic_strain_rate", defaults.ductile_plastic_strain_rate)),
        ductile_poisson_ratio=float(c_raw.get("ductile_poisson_ratio", defaults.ductile_poisson_ratio)),
        ductile_damage_rate=float(c_raw.get("ductile_damage_rate", defaults.ductile_damage_rate)),
        tear_growth_rate=float(c_raw.get("tear_growth_rate", defaults.tear_growth_rate)),
        thermal_softening_rate=float(c_raw.get("thermal_softening_rate", defaults.thermal_softening_rate)),
        damage_weakening_rate=float(c_raw.get("damage_weakening_rate", defaults.damage_weakening_rate)),
        melt_heat=float(c_raw.get("melt_heat", defaults.melt_heat)),
        melt_anneal_rate=float(c_raw.get("melt_anneal_rate", defaults.melt_anneal_rate)),
        melt_viscous_damping=float(c_raw.get("melt_viscous_damping", defaults.melt_viscous_damping)),
        heat_diffusion_rate=float(c_raw.get("heat_diffusion_rate", defaults.heat_diffusion_rate)),
        heat_damping_to_heat_factor=float(c_raw.get("heat_damping_to_heat_factor", defaults.heat_damping_to_heat_factor)),
        heat_radiation_decay=float(c_raw.get("heat_radiation_decay", defaults.heat_radiation_decay)),
        heat_strain_energy_factor=float(c_raw.get("heat_strain_energy_factor", defaults.heat_strain_energy_factor)),
        fluid_pressure_coupling=float(c_raw.get("fluid_pressure_coupling", defaults.fluid_pressure_coupling)),
        fluid_pressure_smoothing=float(c_raw.get("fluid_pressure_smoothing", defaults.fluid_pressure_smoothing)),
        fluid_pressure_decay=float(c_raw.get("fluid_pressure_decay", defaults.fluid_pressure_decay)),
        silhouette_mask_threshold=float(c_raw.get("silhouette_mask_threshold", defaults.silhouette_mask_threshold)),
    )

    col_raw = _sub(raw, "collision")
    collision = CollisionConfig(
        contact_pair_max=int(col_raw.get("contact_pair_max", 2048)),
        restitution_velocity_threshold=float(
            col_raw.get("restitution_velocity_threshold",
                        CollisionConfig.restitution_velocity_threshold)
        ),
    )

    gpu_raw = _sub(raw, "gpu")
    gpu_cfg = GpuConfig(
        enabled=bool(gpu_raw.get("enabled", True)),
        debug_force_cpu=bool(gpu_raw.get("debug_force_cpu", False)),
        indirect_dispatch=bool(gpu_raw.get("indirect_dispatch", False)),
        persistent_residency=bool(gpu_raw.get("persistent_residency", True)),
    )

    be_raw = _sub(raw, "boundary_exchange")
    be_defaults = BoundaryExchangeConfig()
    boundary_exchange_cfg = BoundaryExchangeConfig(
        enabled=bool(be_raw.get("enabled", be_defaults.enabled)),
        strip_depth=int(be_raw.get("strip_depth", be_defaults.strip_depth)),
    )

    fr_raw = _sub(raw, "frontier")
    fr_defaults = FrontierYamlConfig()
    # The yml's existing ``frontier:`` block is the A* priority tuning;
    # Phase A extends it with the activation-driven auto-tick flag plus the
    # FrontierSolver thresholds.  Keys absent from the file fall through to
    # the dataclass defaults so older configs keep working.
    # Also accept the legacy hull.* threshold names from the same yml so
    # tuning stays centralised.
    h_raw_for_frontier = _sub(raw, "hull")
    frontier_cfg = FrontierYamlConfig(
        enabled=bool(fr_raw.get("enabled", fr_defaults.enabled)),
        velocity_std_threshold_high=float(fr_raw.get(
            "velocity_std_threshold_high",
            h_raw_for_frontier.get("promote_velocity_std", fr_defaults.velocity_std_threshold_high),
        )),
        velocity_std_threshold_low=float(fr_raw.get(
            "velocity_std_threshold_low",
            h_raw_for_frontier.get("demote_velocity_std", fr_defaults.velocity_std_threshold_low),
        )),
        damage_std_threshold_high=float(fr_raw.get(
            "damage_std_threshold_high",
            h_raw_for_frontier.get("promote_damage_std", fr_defaults.damage_std_threshold_high),
        )),
        damage_std_threshold_low=float(fr_raw.get(
            "damage_std_threshold_low",
            h_raw_for_frontier.get("demote_damage_std", fr_defaults.damage_std_threshold_low),
        )),
        coalesce_hysteresis_frames=int(fr_raw.get(
            "coalesce_hysteresis_frames",
            h_raw_for_frontier.get("demote_hysteresis_frames", fr_defaults.coalesce_hysteresis_frames),
        )),
        max_depth=int(fr_raw.get("max_depth", fr_defaults.max_depth)),
        enable_subdivide=bool(fr_raw.get("enable_subdivide", fr_defaults.enable_subdivide)),
        enable_coalesce=bool(fr_raw.get("enable_coalesce", fr_defaults.enable_coalesce)),
    )

    ev_raw = _sub(raw, "events")
    ev_defaults = EventsConfig()
    events_cfg = EventsConfig(
        impact_impulse_threshold=float(
            ev_raw.get("impact_impulse_threshold", ev_defaults.impact_impulse_threshold)
        ),
    )

    return PhysicsYaml(
        world=world, hull=hull_cfg, cell=cell_cfg, collision=collision, gpu=gpu_cfg,
        boundary_exchange=boundary_exchange_cfg,
        frontier=frontier_cfg,
        events=events_cfg,
    )


# -- PixelState channel indices (must match cell.CELL_PIXEL_STRUCT order) ----
_IDX_U_X, _IDX_U_Y = 0, 1
_IDX_V_X, _IDX_V_Y = 2, 3
_IDX_PERM_XX, _IDX_PERM_YY, _IDX_PERM_XY = 4, 5, 6
_IDX_PRESSURE = 7
_IDX_DAMAGE = 8
_IDX_DENSITY = 9
_IDX_STRETCH = 10
_IDX_TEAR = 11
_IDX_HEAT = 12
_IDX_BOND_N, _IDX_BOND_E, _IDX_BOND_S = 13, 14, 15


class _ActiveUntilFrameView:
    """Read/write shim mimicking the legacy ``dict[hid, int]`` API.

    Phase A promoted the storage to a numpy column on
    :class:`HullTree`.  External callers (tests, debug code) that wrote
    ``world.active_until_frame[hid] = N`` or did
    ``world.active_until_frame.get(hid, -1)`` still work through this
    view; new code should hit ``world.hulls.active_until_frame`` directly.
    """
    __slots__ = ("_hulls",)

    def __init__(self, hulls: HullTree) -> None:
        self._hulls = hulls

    def __getitem__(self, hid: int) -> int:
        return int(self._hulls.active_until_frame[int(hid)])

    def __setitem__(self, hid: int, value: int) -> None:
        self._hulls.active_until_frame[int(hid)] = int(value)

    def __contains__(self, hid: int) -> bool:
        # A hull is "in" the active set iff its deadline is non-sentinel.
        return int(self._hulls.active_until_frame[int(hid)]) >= 0

    def get(self, hid: int, default: int = -1) -> int:
        v = int(self._hulls.active_until_frame[int(hid)])
        return v if v >= 0 else default

    def __iter__(self):
        col = self._hulls.active_until_frame
        for hid in range(col.shape[0]):
            if int(col[hid]) >= 0:
                yield hid

    def __len__(self) -> int:
        return int((self._hulls.active_until_frame >= 0).sum())


@dataclass
class ContactPair:
    a: int       # hull id
    b: int       # hull id
    normal: tuple[float, float]   # from a -> b
    depth: float                  # penetration depth
    point: tuple[float, float]    # world contact point


class PhysicsWorld:
    """Top-level container + frame loop.

    Sprint 1 capabilities:
      - Author bodies from silhouette + material name.
      - Apply gravity to non-fixed bodies.
      - Detect circle-circle and circle-AABB contacts.
      - Resolve contacts with normal restitution (no friction yet).
      - Run a CPU-numpy per-pixel substep on bodies with T2 cell grids.
    """

    def __init__(
        self,
        config: PhysicsYaml | None = None,
        world_bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Create an empty world.

        Parameters
        ----------
        config:
            Pre-loaded :class:`PhysicsYaml`. ``None`` reads ``config/physics.yml``.
        world_bounds:
            Optional ``(x0, y0, x1, y1)`` rectangle. Bodies that cross a
            boundary collide with that wall; useful for closed test arenas.
        """
        self.config: PhysicsYaml = config if config is not None else load_physics_config()
        # Memory-budget enforcement (Sprint 7).  The ``memory`` attribute is
        # installed on ``PhysicsYaml`` by
        # ``pharos_engine.physics.memory_budget._install_memory_section_on_physics_yaml``
        # at import time, so it's always present here.  Import lazily to
        # avoid a circular import at module load.
        from pharos_engine.physics.memory_budget import (
            MemoryBudget as _MemoryBudget,
            MemoryBudgetConfig as _MemoryBudgetConfig,
        )
        _mem_cfg = getattr(self.config, "memory", None) or _MemoryBudgetConfig()
        self.memory_budget: _MemoryBudget = _MemoryBudget(_mem_cfg)
        self.hulls: HullTree = HullTree(
            capacity=self.config.hull.initial_hull_capacity,
        )
        self.cell_pool: CellGridPool = CellGridPool(
            capacity=self.config.hull.initial_cell_grid_capacity,
            memory_budget=self.memory_budget,
        )
        self.world_bounds: tuple[float, float, float, float] | None = world_bounds
        self.bodies: list[PhysicsBody] = []
        self.frame: int = 0
        # Phase A: ``active_until_frame`` is now an SoA column on ``self.hulls``
        # (parallel to position/velocity).  We keep a property shim below so
        # external readers see a dict-like view of {hid -> deadline}.
        # Lazy-constructed FrontierSolver instance auto-ticked from step().
        self._frontier: FrontierSolver | None = None
        # Per-hull material lookup, parallel to hulls.material_id but mapping
        # to actual CellMaterial objects (richer than the uint16 id).
        self._materials: dict[int, CellMaterial] = {}
        # Material-name -> stable id (uint16).
        self._material_ids: dict[str, int] = {}
        self._next_material_id: int = 0
        # Hull id -> owning body, for narrowphase/inject extents.
        self._body_for_hull: dict[int, PhysicsBody] = {}

        # Lazy-constructed uniform-grid broadphase.  Built on first
        # ``_broadphase`` call so we can size cells against the actual
        # configured hull capacity.  Cell-size of 64 px tracks the
        # engine's reference 32 px ball (typical hull diagonal); see
        # ``pharos_engine.physics.broadphase`` for the reasoning.
        self._broadphase_hash: SpatialHashBroadphase | None = None

        # Per-frame cross-seam heat exchange.  Borrows references to the
        # cell pool, hull tree, body lookup, and material lookup so it
        # always sees the current state without re-wiring.
        self._boundary_exchange: BoundaryExchange = BoundaryExchange(
            cell_pool=self.cell_pool,
            hulls=self.hulls,
            body_lookup=self._body_for_hull,
            material_lookup=self._materials,
        )

        # GPU dispatch state — initialised lazily on first _gpu_substep call.
        self._gpu_initialised: bool = False
        self._gpu_available: bool = False
        self._gpu_device = None              # type: ignore[assignment]
        self._gpu_queue = None               # type: ignore[assignment]
        self._gpu_pipeline = None            # type: ignore[assignment]
        self._gpu_bind_layout = None         # type: ignore[assignment]
        self._gpu_src_buf = None             # type: ignore[assignment]
        self._gpu_dst_buf = None             # type: ignore[assignment]
        self._gpu_mask_buf = None            # type: ignore[assignment]
        self._gpu_uniform_buf = None         # type: ignore[assignment]
        self._gpu_readback_buf = None        # type: ignore[assignment]
        self._gpu_buf_capacity: int = 0      # slots currently sized in src/dst
        # Indirect-dispatch buffers (Sprint 3).  Sized lazily on first use.
        self._gpu_per_hull_params_buf = None       # type: ignore[assignment]
        self._gpu_active_hulls_buf = None          # type: ignore[assignment]
        self._gpu_indirect_args_buf = None         # type: ignore[assignment]
        self._gpu_multi_readback_buf = None        # type: ignore[assignment]
        self._gpu_indirect_capacity: int = 0       # max active hulls currently sized
        # Phase C — pressure-projection pipeline + dedicated buffers.
        self._gpu_proj_pipeline = None             # type: ignore[assignment]
        self._gpu_proj_bind_layout = None          # type: ignore[assignment]
        self._gpu_proj_cfg_buf = None              # type: ignore[assignment]
        self._gpu_proj_per_hull_params_buf = None  # type: ignore[assignment]
        self._gpu_proj_active_hulls_buf = None     # type: ignore[assignment]

    # -- material registration ----------------------------------------------

    def _intern_material(self, name: str, material: CellMaterial) -> int:
        if name in self._material_ids:
            return self._material_ids[name]
        mid = self._next_material_id
        self._next_material_id += 1
        self._material_ids[name] = mid
        return mid

    # -- body authoring ------------------------------------------------------

    def create_body(
        self,
        silhouette: np.ndarray,
        material: str,
        position: tuple[float, float] = (0.0, 0.0),
        velocity: tuple[float, float] = (0.0, 0.0),
        fixed: bool = False,
        tier: int = TIER_T2,
    ) -> PhysicsBody:
        """Author a body from a silhouette mask + material name.

        Architecture invariant: the cell density field is the **single
        source of truth** for body shape, mass, and inertia.  All derived
        quantities — bounding circle, AABB, rigid mass, inertia tensor —
        are integrals over the cell field weighted by the material's
        ``density_rho``.

        ``fixed=True`` flags this body as ground/wall: rigid integration
        and gravity are skipped, but cells still simulate (so water still
        ripples and mud still splats).
        """
        # Memory-budget gate (Sprint 7): refuse / warn before allocating a
        # new body so runaway scenes don't quietly consume gigabytes.  The
        # check compares the prospective post-allocation total against the
        # ``memory.max_bodies`` cap from ``config/physics.yml``.
        budget = getattr(self, "memory_budget", None)
        if budget is not None:
            budget.check_body_alloc(len(self.bodies) + 1)

        mat = cell_material_for(material)
        if mat is None:
            raise ValueError(f"Unknown material '{material}'. "
                             f"Registered: {sorted(self._material_ids.keys())}")
        material_id = self._intern_material(material, mat)
        self._materials[material_id] = mat

        h, w = silhouette.shape[:2]
        # World units per cell (per axis). Cells are always 32×32 in body-
        # local frame; cell_size sets the body's world footprint.
        cell_size_x = float(w) / CELL_GRID_SIZE
        cell_size_y = float(h) / CELL_GRID_SIZE
        cell_area = cell_size_x * cell_size_y

        # Spawn cells first (so we can integrate from the actual field).
        cell_grid_id = NO_CELL_GRID
        if tier == TIER_T2:
            cell_grid_id = self.cell_pool.acquire()
            cells = self.cell_pool.slot_view(cell_grid_id)
            seeded = silhouette_to_cells(silhouette, mat)
            cells[..., _IDX_DENSITY] = seeded[..., _IDX_DENSITY]
            cells[..., _IDX_HEAT] = seeded[..., _IDX_HEAT]
            # Phase B — body creation just authored the slot from CPU.
            self.cell_pool.mark_dirty(cell_grid_id)
            # Mass + inertia integrated from cells (material drives the body).
            density = cells[..., _IDX_DENSITY]
            mass = float((mat.density_rho * density * cell_area).sum())
            # Inertia about geometric centroid: I = Σ ρ * d * area * |r|².
            cx_idx = (CELL_GRID_SIZE - 1) * 0.5
            cy_idx = (CELL_GRID_SIZE - 1) * 0.5
            yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
            dx = (xx - cx_idx) * cell_size_x
            dy = (yy - cy_idx) * cell_size_y
            r2 = dx * dx + dy * dy
            inertia = float((mat.density_rho * density * cell_area * r2).sum())
        else:
            # T0 fallback: estimate from silhouette directly (no cell grid).
            mass = float((silhouette > 0.5).sum()) * mat.density_rho * cell_area
            inertia = mass * (cell_size_x ** 2 + cell_size_y ** 2) * (CELL_GRID_SIZE ** 2) / 12.0

        if mass <= 0.0:
            mass = 1.0
            inertia = 1.0

        hull_id = self.hulls.spawn_root(
            x=float(position[0]),
            y=float(position[1]),
            cell_size_x=cell_size_x,
            cell_size_y=cell_size_y,
            mass=mass,
            inertia=inertia,
            material_id=material_id,
            tier=tier,
            fixed=fixed,
        )
        self.hulls.cell_grid_id[hull_id] = cell_grid_id
        self.hulls.velocity[hull_id, 0] = float(velocity[0])
        self.hulls.velocity[hull_id, 1] = float(velocity[1])

        body = PhysicsBody(
            world=self,
            root_hull_id=hull_id,
            material_name=material,
            material=mat,
            silhouette_size=(int(h), int(w)),
            fixed=fixed,
        )
        self.bodies.append(body)
        self._body_for_hull[hull_id] = body
        return body

    # -- frame step ----------------------------------------------------------

    def step(self, dt: float | None = None) -> list[ContactPair]:
        """Advance the world by one frame.  Velocity-Verlet integrator.

        Returns the contact pairs resolved this frame (for diagnostics/tests).
        """
        if dt is None:
            dt = self.config.world.default_dt

        # Velocity-Verlet for constant gravity: half-kick, drift, half-kick.
        # This is symplectic AND second-order accurate for constant
        # acceleration — total energy in free-fall stays bounded.
        self._half_kick_gravity(dt)
        self.hulls.integrate_transforms(dt)
        self._half_kick_gravity(dt)

        # Broadphase + contacts.
        contacts = self._broadphase()
        wall_contacts = self._resolve_walls()
        contacts.extend(wall_contacts)
        for pair in contacts:
            if pair.b >= 0:
                self._resolve_contact(pair)

        # Cross-seam heat conduction.  Runs after contacts are known but
        # before the per-pixel substep so internal diffusion can spread
        # any heat that just flowed across the seam within the same frame.
        # Wall contacts (b < 0) are skipped inside BoundaryExchange.exchange.
        if self.config.boundary_exchange.enabled:
            self._boundary_exchange.exchange(contacts, dt)
            # Phase B — heat flowed across contact seams; the affected
            # slots are exactly the pair-members of each non-wall
            # contact.  Mark them dirty so the GPU substep picks up the
            # post-exchange heat before its kernel reads it.
            for pair in contacts:
                if pair.b < 0:
                    continue
                ga = int(self.hulls.cell_grid_id[pair.a])
                gb = int(self.hulls.cell_grid_id[pair.b])
                if ga >= 0:
                    self.cell_pool.mark_dirty(ga)
                if gb >= 0:
                    self.cell_pool.mark_dirty(gb)

        # Phase A: auto-tick the FrontierSolver before the substep loop.
        # ``frontier.tick`` may subdivide/coalesce hulls based on the
        # disagreement metrics computed from the cell field that was just
        # advanced above (boundary exchange ran, contacts injected).
        # Subdivision allocates one cell-grid slot per child; pre-grow the
        # pool when capacity is tight so the auto-tick never trips on an
        # exhausted pool mid-frame.
        # Phase A: auto-tick the FrontierSolver. ``tick`` walks every alive
        # hull computing 32×32 cell-field statistics; on a fully-quiescent
        # scene that work is dead weight (the disagreement scores are zero
        # and no subdivide/coalesce will fire).  Short-circuit when there
        # are no hot hulls AND no subdivided parents pending coalesce so
        # the quiescent-scene budget is bounded by broadphase + gravity
        # alone, per the Phase A design target in
        # ``docs/next_phase_plan.md`` section 3.2.
        # When we DO tick, pre-grow the cell pool to cover the worst case
        # (every alive T2 leaf subdividing into 7 children) so the tick
        # never aborts mid-loop on an exhausted pool.
        if self.config.frontier.enabled:
            hulls = self.hulls
            has_hot = bool((hulls._alive & (hulls.active_until_frame >= int(self.frame))).any())
            has_children = bool((hulls._alive & (hulls.child_count > 0)).any())
            if has_hot or has_children:
                n_alive_t2 = int((hulls._alive & (hulls.cell_grid_id >= 0)).sum())
                headroom = n_alive_t2 * 7 + 8
                if self.cell_pool.in_use_count + headroom > self.cell_pool.capacity:
                    new_cap = max(
                        self.cell_pool.capacity * 2,
                        self.cell_pool.in_use_count + headroom,
                    )
                    self.cell_pool.grow(new_cap)
                self._ensure_frontier_solver().tick(self)

        # Per-pixel substep on T2 hulls.  Substep count is the MAX of the
        # user-configured baseline and the CFL-required count: the elastic
        # wave speed c = √(E/ρ) must satisfy c·dt_sub ≤ min(cell_size_x,
        # cell_size_y) for stability, so a stiff material on a small grid
        # forces more substeps automatically.  We compute the planned
        # cadence regardless of activation so diagnostic readers see the
        # CFL safety net even when the substep loop is skipped.
        substeps = max(self.config.world.substeps, self._cfl_required_substeps(dt))
        self._last_substeps = substeps
        # Eagerly resolve the GPU/CPU decision once per frame so the
        # lazy ``_init_gpu`` runs even on frames where no hull is active
        # (otherwise ``_gpu_available`` would stay False forever on a
        # settled scene, which makes diagnostic HUDs lie about whether
        # the GPU is in use).  The result is reused below.
        use_gpu = self._should_use_gpu()
        # Phase A: if no hull is active this frame the per-pixel substep
        # has nothing to do.  Skipping the whole loop is what makes
        # settled-body-heavy scenes 5-10× cheaper.
        active_slots = self._gather_active_slots()
        if active_slots:
            substep_dt = dt / substeps
            for _ in range(substeps):
                if use_gpu:
                    self._gpu_substep(substep_dt)
                else:
                    self._cpu_substep(substep_dt)

        # Automatic fragmentation: when a body's bond field has visibly
        # severed (min bond < threshold), run cc_label on it; if the cells
        # split into disjoint components, spawn each extra component as a
        # new root body. This is what makes glass actually break into
        # pieces instead of just becoming a damaged-looking single body.
        # Cheap rate-limit: only check once every N frames per body.
        if (self.frame & 3) == 0:  # every 4 frames
            self._try_spawn_fragments()

        # Phase A hysteresis decay: any hull whose deadline has slipped
        # past the current frame falls one notch toward quiescent.  This
        # is purely cosmetic for gating (the deadline check is the source
        # of truth) but keeps ``activation_level`` honest for debug HUDs.
        hulls = self.hulls
        expired = hulls._alive & (hulls.active_until_frame < int(self.frame)) & (hulls.activation_level > 0)
        if expired.any():
            # 2 (hot) -> 1 (warm) -> 0 (quiescent) on each step past deadline.
            hulls.activation_level[expired] -= 1

        # Debug-only NaN/inf surface.  Disabled by default; tests/debug
        # runs flip ``config.world.debug_assert_finite`` to catch a kernel
        # regression at the exact frame it lands, rather than letting the
        # corruption silently propagate for hundreds of frames before
        # surfacing in a downstream warning (the WP-O lava-demo failure
        # mode: inf at frame 229 ⇒ ``invalid value in cast`` at the
        # renderer's forward-splat several frames later).
        if self.config.world.debug_assert_finite:
            self._debug_assert_state_finite()

        self.frame += 1
        return contacts

    def _debug_assert_state_finite(self) -> None:
        """Scan every active cell grid for non-finite values.

        Cheap-but-not-free: ~one ``np.isfinite`` pass per active hull's
        32x32xC grid.  Only invoked when ``WorldConfig.debug_assert_finite``
        is True so release builds pay zero.  On a hit, raises
        :class:`RuntimeError` carrying the offending hull id, channel,
        and a small sample of bad values — enough to localise the kernel
        that produced the NaN without re-running the whole simulation
        under a debugger.
        """
        hulls = self.hulls
        alive = hulls._alive
        has_grid = hulls.cell_grid_id >= 0
        for hid_arr in np.nonzero(alive & has_grid)[0]:
            hid = int(hid_arr)
            gid = int(hulls.cell_grid_id[hid])
            if gid < 0:
                continue
            cells = self.cell_pool.slot_view(gid)
            if not np.all(np.isfinite(cells)):
                bad = ~np.isfinite(cells)
                # Surface the first offending channel for quick triage.
                for c in range(cells.shape[-1]):
                    ch_bad = bad[..., c]
                    if ch_bad.any():
                        sample = cells[..., c][ch_bad].ravel()[:3]
                        raise RuntimeError(
                            f"Non-finite physics state at frame={self.frame} "
                            f"hull={hid} grid_slot={gid} channel={c} "
                            f"count={int(ch_bad.sum())} sample={sample}"
                        )

    def _ensure_frontier_solver(self) -> FrontierSolver:
        """Lazy-construct ``self._frontier`` from the YAML-loaded config.

        Phase A wires the frontier solver into ``world.step``; the solver
        instance is created the first time we tick it so a world that
        disables ``frontier.enabled`` never pays the construction cost.
        """
        if self._frontier is None:
            fy = self.config.frontier
            self._frontier = FrontierSolver(FrontierConfig(
                velocity_std_threshold_high=fy.velocity_std_threshold_high,
                velocity_std_threshold_low=fy.velocity_std_threshold_low,
                damage_std_threshold_high=fy.damage_std_threshold_high,
                damage_std_threshold_low=fy.damage_std_threshold_low,
                coalesce_hysteresis_frames=fy.coalesce_hysteresis_frames,
                max_depth=fy.max_depth,
                enable_subdivide=fy.enable_subdivide,
                enable_coalesce=fy.enable_coalesce,
            ))
        return self._frontier

    def _try_spawn_fragments(self) -> None:
        """For each active root body with severed bonds, look for disjoint
        connected components and spawn them as new bodies.

        Hard caps per-frame to avoid runaway pool growth: at most
        ``_MAX_FRAGMENTS_PER_FRAME`` new bodies, and only attempt fragmentation
        on bodies whose min-bond has dropped meaningfully.
        """
        _MAX_FRAGMENTS_PER_FRAME = 8
        spawned_this_frame = 0
        from pharos_engine.physics.body import PhysicsBody as _PB
        alive_roots = np.nonzero(
            self.hulls._alive
            & (self.hulls.parent_id < 0)
            & (self.hulls.cell_grid_id >= 0)
            & (~self.hulls.fixed)
        )[0]
        for hid_arr in alive_roots:
            if spawned_this_frame >= _MAX_FRAGMENTS_PER_FRAME:
                break
            hid = int(hid_arr)
            gid = int(self.hulls.cell_grid_id[hid])
            if gid < 0:
                continue
            cells = self.cell_pool.slot_view(gid)
            # Cheap pre-check: if no bond has been severed, skip the full CC pass.
            if float(min(cells[..., 14].min(), cells[..., 15].min())) > 0.5:
                continue
            # Grow the pool if we're close to exhaustion before attempting
            # to spawn fragments (one cell-grid slot needed per new fragment).
            if self.cell_pool.in_use_count > self.cell_pool.capacity - 8:
                self.cell_pool.grow(self.cell_pool.capacity * 2)
            try:
                new_ids = self.hulls.spawn_fragment(
                    parent_id=hid,
                    cell_pool=self.cell_pool,
                    material_lookup=self._materials,
                )
            except RuntimeError as e:
                # Pool exhausted on a single body with many shards — log and
                # bail this frame; the bond field stays severed so the
                # visual fracture is still there.
                import warnings
                warnings.warn(f"spawn_fragment aborted: {e}")
                break
            if not new_ids:
                continue
            # Phase B — fragmentation rewrote the parent slot (severed
            # bonds zero'd, possibly density set to 0 in disconnected
            # components) and acquired new slots for each child fragment.
            # ``cell_pool.acquire`` already marked the new slots dirty,
            # but we still need to flag the parent so its next upload
            # carries the post-spawn bond state.
            self.cell_pool.mark_dirty(gid)
            for new_hid in new_ids:
                new_gid = int(self.hulls.cell_grid_id[new_hid])
                if new_gid >= 0:
                    self.cell_pool.mark_dirty(new_gid)
            # Wrap each new hull as a PhysicsBody so external code can find it.
            parent = self._body_for_hull.get(hid)
            material_name = parent.material_name if parent is not None else "stone"
            material = parent.material if parent is not None else None
            for new_hid in new_ids:
                cs_x = float(self.hulls.cell_size_x[new_hid])
                cs_y = float(self.hulls.cell_size_y[new_hid])
                h = int(cs_y * CELL_GRID_SIZE)
                w = int(cs_x * CELL_GRID_SIZE)
                body = _PB(
                    world=self,
                    root_hull_id=new_hid,
                    material_name=material_name,
                    material=material if material is not None else (
                        cell_material_for(material_name)
                    ),
                    silhouette_size=(h, w),
                    fixed=False,
                )
                self.bodies.append(body)
                self._body_for_hull[new_hid] = body
                self._mark_active(new_hid)
                spawned_this_frame += 1
                if spawned_this_frame >= _MAX_FRAGMENTS_PER_FRAME:
                    break

    def _cfl_required_substeps(self, dt: float) -> int:
        """Compute the minimum substep count needed to satisfy CFL across
        all active T2 hulls.  Material drives this — stiff materials
        (high ``E_effective``) need more substeps.

        Phase D: the per-pixel kernel evaluates its Laplacian in *grid
        index units* (Δx = 1 cell), so the relevant wave speed for CFL is
        ``c_grid = sqrt(E_effective / rho)`` in cells/sec.  We require
        ``c_grid * dt < 0.5`` for explicit-Laplacian stability.  Earlier
        revisions used ``dx = cell_size`` in physical units; that was
        inconsistent with what the kernel actually computes and let the
        stiff materials race past CFL when E was bumped.
        """
        alive = np.nonzero(self.hulls._alive & (self.hulls.cell_grid_id >= 0))[0]
        if alive.size == 0:
            return 1
        required = 1
        for hid in alive:
            mat = self._materials.get(int(self.hulls.material_id[hid]))
            if mat is None or mat.density_rho <= 0.0:
                continue
            E_wave = mat.E_effective
            c_grid = float(np.sqrt(E_wave / mat.density_rho))
            # CFL number ≤ 0.5 for the explicit elastic Laplacian on the
            # Δx = 1 grid.
            required_for_this = int(np.ceil(c_grid * dt / 0.5))
            if required_for_this > required:
                required = required_for_this
        return min(required, 64)  # safety cap

    def _half_kick_gravity(self, dt: float) -> None:
        """Apply gravity for half the timestep — half of velocity-Verlet."""
        gx, gy = self.config.world.gravity
        movable = self.hulls._alive & ~self.hulls.fixed
        if not movable.any():
            return
        self.hulls.velocity[movable, 0] += gx * dt * 0.5
        self.hulls.velocity[movable, 1] += gy * dt * 0.5

    # -- broadphase + contact ------------------------------------------------

    def _broadphase(self) -> list[ContactPair]:
        """Spatial-hash broadphase over live root hulls.

        Replaces the prior ``O(N^2)`` pair sweep.  Each frame we rebuild
        a uniform-grid hash of every live root AABB, query the
        de-duplicated candidate-pair list, then run the existing
        ``_aabb_overlap`` + ``_narrowphase`` chain on those candidates.
        The contact-pair set produced is identical to the naive
        broadphase (verified by ``test_spatial_hash_finds_same_contacts_
        as_naive``); only the pruning factor changes.
        """
        if self._broadphase_hash is None:
            self._broadphase_hash = SpatialHashBroadphase(
                cell_size=64.0,
                expected_bodies=int(self.config.hull.initial_hull_capacity),
            )
        bp = self._broadphase_hash
        bp.rebuild(self.hulls)
        fixed = self.hulls.fixed
        contacts: list[ContactPair] = []
        cap = self.config.collision.contact_pair_max
        for a, b in bp.candidate_pairs():
            if fixed[a] and fixed[b]:
                continue
            if not self._aabb_overlap(a, b):
                continue
            pair = self._narrowphase(a, b)
            if pair is not None:
                contacts.append(pair)
                if len(contacts) >= cap:
                    return contacts
        return contacts

    def _aabb_overlap(self, a: int, b: int) -> bool:
        a0x, a0y, a1x, a1y = self.hulls.aabb[a]
        b0x, b0y, b1x, b1y = self.hulls.aabb[b]
        return not (a1x < b0x or b1x < a0x or a1y < b0y or b1y < a0y)

    def _narrowphase(self, a: int, b: int) -> ContactPair | None:
        """Unified AABB-vs-AABB narrowphase.

        Each body has a single canonical extent: its 32×32 cell grid
        scaled by ``cell_size_x/y``.  Contact normal is the axis with the
        smaller penetration depth, signed away from body ``a``.
        """
        ax0, ay0, ax1, ay1 = self.hulls.aabb[a]
        bx0, by0, bx1, by1 = self.hulls.aabb[b]
        # Per-axis overlap.
        ox = min(ax1, bx1) - max(ax0, bx0)
        oy = min(ay1, by1) - max(ay0, by0)
        if ox <= 0.0 or oy <= 0.0:
            return None
        # Pick the minimum-penetration axis as the contact normal.
        if ox < oy:
            sign = 1.0 if (self.hulls.position[b, 0] > self.hulls.position[a, 0]) else -1.0
            n = (float(sign), 0.0)
            depth = float(ox)
            cy = 0.5 * (max(ay0, by0) + min(ay1, by1))
            cx = (max(ax0, bx0) if sign > 0 else min(ax1, bx1))
        else:
            sign = 1.0 if (self.hulls.position[b, 1] > self.hulls.position[a, 1]) else -1.0
            n = (0.0, float(sign))
            depth = float(oy)
            cx = 0.5 * (max(ax0, bx0) + min(ax1, bx1))
            cy = (max(ay0, by0) if sign > 0 else min(ay1, by1))
        return ContactPair(a=a, b=b, normal=n, depth=depth, point=(cx, cy))

    def _restitution_threshold(
        self,
        mat_a: "CellMaterial | None",
        mat_b: "CellMaterial | None",
    ) -> float:
        """Combined resting-contact velocity threshold for this contact.

        WP-R: per-material thresholds combined as ``min(mat_a, mat_b)`` so
        any brittle participant lowers the bar.  The global
        ``CollisionConfig.restitution_velocity_threshold`` is the fallback
        for materials that haven't been wired (``None``) and a hard ceiling
        — explicit YAML lowering of the global still wins over per-material
        defaults, preserving the WP-P behaviour for callers that opt out of
        per-material gating by tightening the global.

        See the WP-R fracture-regression analysis: the rigid impulse magnitude
        drives the cell-side velocity inject, which drives the von-Mises
        stress that the brittle yield surface reads.  Suppressing
        restitution at low closing speeds also suppresses the stress that
        starts a glass shatter — so brittle materials need a much lower
        threshold than sand/dense ones to keep fracture impacts intact.
        """
        global_thr = float(self.config.collision.restitution_velocity_threshold)
        thr_a = float(mat_a.restitution_velocity_threshold) if mat_a is not None else global_thr
        thr_b = float(mat_b.restitution_velocity_threshold) if mat_b is not None else global_thr
        mat_thr = min(thr_a, thr_b)
        # When the global is explicitly tightened down (YAML override), it
        # acts as a ceiling that overrides per-material opt-out — that keeps
        # the WP-P sand-pile fix testable from config alone.  When the
        # global is zero (gate disabled), the per-material value is the
        # whole story.
        if global_thr <= 0.0:
            return mat_thr
        return min(mat_thr, global_thr)

    def _resolve_contact(self, pair: ContactPair) -> None:
        """Resolve a contact: separate, apply normal+tangential impulse with
        restitution and friction (now with rotational dynamics), then
        transfer the inelastic Δv into the contact-zone cells as a
        zero-mean (linear + angular) body-local velocity field.

        Rotational dynamics use the Baraff/Witkin impulse formulation:

            v_point = v + ω × r,   r = p_contact - p_body
            inv_sum = 1/m_a + 1/m_b + (r_a × n)² / I_a + (r_b × n)² / I_b
            j = -(1 + rest) * v_n_rel / inv_sum
            Δv = j * n / m,   Δω = (r × (j*n)) / I

        Momentum and energy are conserved by construction:
          * Rigid Σp change = -Σp gained by cells (action/reaction).
          * Rigid angular impulse on a body = r × J; balances across pair.
          * Rigid ΔKE_lost = ΔKE_cells + ΔHeat (split by ``cell_kinetic_share``).
        """
        a, b = pair.a, pair.b
        nx, ny = pair.normal
        ma = float(self.hulls.mass[a]) if not self.hulls.fixed[a] else float("inf")
        mb = float(self.hulls.mass[b]) if not self.hulls.fixed[b] else float("inf")
        inv_ma = 0.0 if ma == float("inf") else 1.0 / ma
        inv_mb = 0.0 if mb == float("inf") else 1.0 / mb
        ia = float(self.hulls.inertia[a]) if not self.hulls.fixed[a] else float("inf")
        ib = float(self.hulls.inertia[b]) if not self.hulls.fixed[b] else float("inf")
        inv_ia = 0.0 if ia == float("inf") or ia <= 0.0 else 1.0 / ia
        inv_ib = 0.0 if ib == float("inf") or ib <= 0.0 else 1.0 / ib
        inv_sum_lin = inv_ma + inv_mb
        if inv_sum_lin <= 0.0:
            return

        # Snapshot pre-impulse state (linear + angular) so we can derive Δ
        # per body for the cell-side inject.
        va_pre = self.hulls.velocity[a].copy()
        vb_pre = self.hulls.velocity[b].copy()
        oma_pre = float(self.hulls.omega[a])
        omb_pre = float(self.hulls.omega[b])

        # Position correction (push apart so they don't overlap).
        correction = pair.depth / inv_sum_lin
        if not self.hulls.fixed[a]:
            self.hulls.position[a, 0] -= nx * correction * inv_ma
            self.hulls.position[a, 1] -= ny * correction * inv_ma
        if not self.hulls.fixed[b]:
            self.hulls.position[b, 0] += nx * correction * inv_mb
            self.hulls.position[b, 1] += ny * correction * inv_mb

        # Lever arms from each body's centre to the contact point.  Use the
        # post-correction position so the impulse arm matches the geometry
        # we just established.
        ra_x = float(pair.point[0]) - float(self.hulls.position[a, 0])
        ra_y = float(pair.point[1]) - float(self.hulls.position[a, 1])
        rb_x = float(pair.point[0]) - float(self.hulls.position[b, 0])
        rb_y = float(pair.point[1]) - float(self.hulls.position[b, 1])

        # Point velocities (rigid translation + ω × r) at the contact.
        va_pt_x = float(va_pre[0]) - oma_pre * ra_y
        va_pt_y = float(va_pre[1]) + oma_pre * ra_x
        vb_pt_x = float(vb_pre[0]) - omb_pre * rb_y
        vb_pt_y = float(vb_pre[1]) + omb_pre * rb_x
        rvx = vb_pt_x - va_pt_x
        rvy = vb_pt_y - va_pt_y
        vn = rvx * nx + rvy * ny
        if vn > 0.0:  # already separating
            self._mark_active(a)
            self._mark_active(b)
            return

        # Restitution: soft-body min — a ball into mud uses mud's low rest.
        mat_a = self._materials.get(int(self.hulls.material_id[a]))
        mat_b = self._materials.get(int(self.hulls.material_id[b]))
        rest_a = mat_a.bond_strength if mat_a is not None else 0.3
        rest_b = mat_b.bond_strength if mat_b is not None else 0.3
        rest = min(rest_a, rest_b)
        # Resting-contact gate: below the contact's closing-speed
        # threshold, treat the bounce as fully plastic.  This is what
        # keeps a settled pile from buzzing — the gravity half-kick
        # would otherwise re-inject ``rest * v_gravity`` per frame on
        # every stacked pair, accumulating into spurious KE growth.
        #
        # WP-R: per-material threshold combined as ``min(mat_a, mat_b)``.
        # Sand/dense materials keep the high default (~8.0) so resting
        # stacks stay quiet; brittle materials (glass, stone, concrete,
        # ice, coral, paper, snow) override down to ~0.5 so genuine
        # fracture impacts still imprint their full elastic kick on the
        # cell field — the stress / damage chain reads the impulse-driven
        # cell velocity inject, so a suppressed restitution coefficient
        # also suppresses the von-Mises stress that drives brittle yield.
        thr = self._restitution_threshold(mat_a, mat_b)
        if abs(vn) < thr:
            rest = 0.0

        # 2D cross products: scalar (rx*jy - ry*jx) for r×j, and the
        # rotational-inertia contribution (r×n)² / I for the denominator.
        ra_cross_n = ra_x * ny - ra_y * nx
        rb_cross_n = rb_x * ny - rb_y * nx
        inv_sum_n = inv_sum_lin + (ra_cross_n * ra_cross_n) * inv_ia + (rb_cross_n * rb_cross_n) * inv_ib
        if inv_sum_n <= 0.0:
            return

        j = -(1.0 + rest) * vn / inv_sum_n
        jx, jy = j * nx, j * ny
        if not self.hulls.fixed[a]:
            self.hulls.velocity[a, 0] -= jx * inv_ma
            self.hulls.velocity[a, 1] -= jy * inv_ma
            # ω_a -= (r_a × J) / I_a;   J = j*n
            self.hulls.omega[a] -= (ra_x * jy - ra_y * jx) * inv_ia
        if not self.hulls.fixed[b]:
            self.hulls.velocity[b, 0] += jx * inv_mb
            self.hulls.velocity[b, 1] += jy * inv_mb
            self.hulls.omega[b] += (rb_x * jy - rb_y * jx) * inv_ib

        # Coulomb friction with proper static-vs-kinetic (stiction) model.
        # Each material exposes ``static_friction_coefficient`` (μ_s) and
        # ``kinetic_friction_coefficient`` (μ_k), combined across the pair
        # via geometric mean: μ = √(μ_a · μ_b).  Standard Baraff trick:
        #
        #   * Compute the tangential impulse jt_target that would zero
        #     the relative tangential velocity (perfect sticking).
        #   * If |jt_target| ≤ μ_s · |jn| the contact sticks — apply
        #     jt_target in full (no slip).
        #   * Otherwise the contact slips — clamp to the kinetic cone
        #     |jt| = μ_k · |jn|, signed opposite the tangential velocity.
        mu_s_a = mat_a.static_friction_coefficient if mat_a is not None else 0.4
        mu_s_b = mat_b.static_friction_coefficient if mat_b is not None else 0.4
        mu_k_a = mat_a.kinetic_friction_coefficient if mat_a is not None else 0.3
        mu_k_b = mat_b.kinetic_friction_coefficient if mat_b is not None else 0.3
        mu_s = float(np.sqrt(max(0.0, mu_s_a) * max(0.0, mu_s_b)))
        mu_k = float(np.sqrt(max(0.0, mu_k_a) * max(0.0, mu_k_b)))
        # Tangent direction (perpendicular to normal).
        tx, ty = -ny, nx
        vt = rvx * tx + rvy * ty
        if mu_s > 0.0 or mu_k > 0.0:
            ra_cross_t = ra_x * ty - ra_y * tx
            rb_cross_t = rb_x * ty - rb_y * tx
            inv_sum_t = inv_sum_lin + (ra_cross_t * ra_cross_t) * inv_ia + (rb_cross_t * rb_cross_t) * inv_ib
            if inv_sum_t > 0.0:
                # Impulse that would exactly zero the tangential velocity.
                jt_target = -vt / inv_sum_t
                jn_abs = abs(j)
                if abs(jt_target) <= mu_s * jn_abs:
                    # Stiction case: contact sticks, apply the full target.
                    jt = jt_target
                else:
                    # Kinetic case: slip with kinetic friction, opposing vt.
                    jt = -mu_k * jn_abs if vt > 0.0 else mu_k * jn_abs
                jtx, jty = jt * tx, jt * ty
                if not self.hulls.fixed[a]:
                    self.hulls.velocity[a, 0] -= jtx * inv_ma
                    self.hulls.velocity[a, 1] -= jty * inv_ma
                    self.hulls.omega[a] -= (ra_x * jty - ra_y * jtx) * inv_ia
                if not self.hulls.fixed[b]:
                    self.hulls.velocity[b, 0] += jtx * inv_mb
                    self.hulls.velocity[b, 1] += jty * inv_mb
                    self.hulls.omega[b] += (rb_x * jty - rb_y * jtx) * inv_ib

        # Per-body rigid Δ (post-impulse minus pre-impulse) — linear AND
        # angular.  Fixed bodies see Δ = 0 in their rigid state but we
        # still transfer the impulse into their cells (ground splat / wave).
        dvax = float(self.hulls.velocity[a, 0] - va_pre[0])
        dvay = float(self.hulls.velocity[a, 1] - va_pre[1])
        dvbx = float(self.hulls.velocity[b, 0] - vb_pre[0])
        dvby = float(self.hulls.velocity[b, 1] - vb_pre[1])
        doma = float(self.hulls.omega[a]) - oma_pre
        domb = float(self.hulls.omega[b]) - omb_pre

        # If a body is fixed, the impulse it would have absorbed is
        # equivalent to the other body's Δ (action/reaction with infinite
        # inertia).  Synthesise that for the cell-side inject.
        if self.hulls.fixed[a]:
            dvax, dvay = -dvbx, -dvby
            doma = -domb
        if self.hulls.fixed[b]:
            dvbx, dvby = -dvax, -dvay
            domb = -doma

        # Cells in the contact zone gain the body-local velocity needed for
        # their world velocity to remain unchanged across the rigid bounce.
        # That's `-Δv_rigid - Δω × r_cell` weighted by the falloff kernel.
        # By construction the integral of cell momentum gain equals the rigid
        # momentum loss for that body, so Σp is conserved across the contact.
        # The angular-mean subtraction inside the inject keeps the cell field
        # zero-mean in the angular sense too.
        self._inject_local_velocity_field(
            hull_id=a,
            world_point=pair.point,
            local_dv=(-dvax, -dvay),
            local_d_omega=-doma,
            impact_speed_for_heat=abs(vn),
            rest=rest,
        )
        self._inject_local_velocity_field(
            hull_id=b,
            world_point=pair.point,
            local_dv=(-dvbx, -dvby),
            local_d_omega=-domb,
            impact_speed_for_heat=abs(vn),
            rest=rest,
        )
        self._mark_active(a)
        self._mark_active(b)

    def _resolve_walls(self) -> list[ContactPair]:
        """Resolve wall contacts with full rotational + frictional dynamics.

        Walls are treated as a fixed body with infinite mass and inertia.
        Each hit produces a real contact point — the body's surface point
        closest to the wall — and the Baraff/Witkin impulse formulation
        gives off-centre hits a torque (a ball scraping a wall picks up
        spin) and Coulomb friction brakes tangential motion.  We also
        inject ``local_dv`` + ``local_d_omega`` into the body's cell field
        (with the wall as a no-cells partner) so the contact-zone cells
        lag the rigid bounce, and a fraction of the inelastic energy is
        deposited as heat at the contact.

        Limitation: walls are still axis-aligned planes.  A body
        simultaneously crossing two boundaries (a corner) generates two
        independent contacts resolved in sequence; we do not project the
        contact normal into the diagonal.
        """
        if self.world_bounds is None:
            return []
        x0, y0, x1, y1 = self.world_bounds
        contacts: list[ContactPair] = []
        movable = np.nonzero(
            self.hulls._alive & ~self.hulls.fixed & (self.hulls.parent_id < 0)
        )[0]
        for idx in movable:
            i = int(idx)
            r = float(self.hulls.radius[i])
            # Half-extent of the body along each axis — the cell grid is
            # always 32 cells per axis at ``cell_size_xy`` per cell, so the
            # half-extent is half the world footprint.  ``radius`` is the
            # half-diagonal (bounding circle) and is used for the "is
            # touching the wall" test to match the broadphase circle
            # assumption, but the contact point itself must land on the
            # body's axis-aligned surface (``half_extent`` from the centre
            # along the wall normal).  If we used ``radius`` for the
            # contact point on a 32×32 grid it would fall OUTSIDE the cell
            # field (the bounding-circle radius exceeds the half-extent by
            # √2) and the inject would silently miss every cell.
            hx = 0.5 * float(self.hulls.cell_size_x[i]) * CELL_GRID_SIZE
            hy = 0.5 * float(self.hulls.cell_size_y[i]) * CELL_GRID_SIZE

            # Each axis is independent — we may produce up to two contacts
            # per body per frame (a corner is two separate impulses).
            # Re-read position between axes because the X impulse may have
            # nudged the centre.
            px = float(self.hulls.position[i, 0])
            if px - r < x0:
                self.hulls.position[i, 0] = x0 + r
                cp = (float(self.hulls.position[i, 0]) - hx,
                      float(self.hulls.position[i, 1]))
                self._apply_wall_impulse(i, normal=(1.0, 0.0), contact_point=cp)
                contacts.append(ContactPair(a=i, b=-1, normal=(1.0, 0.0),
                                            depth=0.0, point=cp))
            elif px + r > x1:
                self.hulls.position[i, 0] = x1 - r
                cp = (float(self.hulls.position[i, 0]) + hx,
                      float(self.hulls.position[i, 1]))
                self._apply_wall_impulse(i, normal=(-1.0, 0.0), contact_point=cp)
                contacts.append(ContactPair(a=i, b=-1, normal=(-1.0, 0.0),
                                            depth=0.0, point=cp))

            py = float(self.hulls.position[i, 1])
            if py - r < y0:
                self.hulls.position[i, 1] = y0 + r
                cp = (float(self.hulls.position[i, 0]),
                      float(self.hulls.position[i, 1]) - hy)
                self._apply_wall_impulse(i, normal=(0.0, 1.0), contact_point=cp)
                contacts.append(ContactPair(a=i, b=-1, normal=(0.0, 1.0),
                                            depth=0.0, point=cp))
            elif py + r > y1:
                self.hulls.position[i, 1] = y1 - r
                cp = (float(self.hulls.position[i, 0]),
                      float(self.hulls.position[i, 1]) + hy)
                self._apply_wall_impulse(i, normal=(0.0, -1.0), contact_point=cp)
                contacts.append(ContactPair(a=i, b=-1, normal=(0.0, -1.0),
                                            depth=0.0, point=cp))
        return contacts

    def _apply_wall_impulse(
        self,
        hull_id: int,
        normal: tuple[float, float],
        contact_point: tuple[float, float],
    ) -> None:
        """Baraff/Witkin impulse + friction against an immovable wall.

        The wall has infinite mass and inertia, so all of its terms in the
        denominator drop to zero:

            inv_sum_n = 1/m + (r × n)² / I
            j         = -(1 + rest) * v_n / inv_sum_n
            Δv        =  j * n / m
            Δω        =  (r × J) / I,   J = j * n

        ``v_n`` uses the body's contact-point velocity ``v + ω × r``, so an
        off-centre hit on a spinning body sees its true relative-to-wall
        velocity.  Friction follows the same denominator with the tangent
        substituted for the normal, clamped by the Coulomb cone ``|jt| ≤
        μ |jn|``.  The same ``local_dv`` + ``local_d_omega`` that lag the
        rigid bounce are injected into the contact-zone cells.
        """
        if self.hulls.fixed[hull_id]:
            return
        nx, ny = float(normal[0]), float(normal[1])
        m = float(self.hulls.mass[hull_id])
        I_b = float(self.hulls.inertia[hull_id])
        if m <= 0.0:
            return
        inv_m = 1.0 / m
        inv_I = 0.0 if I_b <= 0.0 else 1.0 / I_b

        v_pre = self.hulls.velocity[hull_id].copy()
        om_pre = float(self.hulls.omega[hull_id])

        # Lever arm from body centre to contact point.
        px = float(self.hulls.position[hull_id, 0])
        py = float(self.hulls.position[hull_id, 1])
        rx = float(contact_point[0]) - px
        ry = float(contact_point[1]) - py

        # Point velocity at the contact (rigid translation + ω × r).
        v_pt_x = float(v_pre[0]) - om_pre * ry
        v_pt_y = float(v_pre[1]) + om_pre * rx
        # Relative velocity of the body's contact point vs. the (stationary)
        # wall, along the contact normal (which points INTO the world, away
        # from the wall surface).  A negative ``vn`` means the body is
        # closing on the wall.
        vn = v_pt_x * nx + v_pt_y * ny
        if vn >= 0.0:
            # Already separating from the wall — no impulse needed.
            self._mark_active(hull_id)
            return

        mat = self._materials.get(int(self.hulls.material_id[hull_id]))
        rest = mat.bond_strength if mat is not None else 0.3
        # Resting-contact gate — same convention as ``_resolve_contact``;
        # a body kissing a wall with sub-threshold closing speed should
        # not pump KE through repeated tiny rebounds.  WP-R: the wall has
        # no material, so the body's own per-material threshold governs.
        thr = self._restitution_threshold(mat, None)
        if abs(vn) < thr:
            rest = 0.0

        # Normal impulse — wall side of the denominator is zero.
        r_cross_n = rx * ny - ry * nx
        inv_sum_n = inv_m + (r_cross_n * r_cross_n) * inv_I
        if inv_sum_n <= 0.0:
            return
        j = -(1.0 + rest) * vn / inv_sum_n
        jx, jy = j * nx, j * ny
        self.hulls.velocity[hull_id, 0] += jx * inv_m
        self.hulls.velocity[hull_id, 1] += jy * inv_m
        self.hulls.omega[hull_id] += (rx * jy - ry * jx) * inv_I

        # Coulomb friction along the contact tangent.  Same material-driven
        # μ as body-body: μ = (1 - rest²)(1 - viscosity).
        mu = 0.3
        if mat is not None:
            mu = float((1.0 - rest * rest) * (1.0 - mat.viscosity))
            mu = max(0.0, mu)
        tx, ty = -ny, nx
        # Tangent component of the body's contact-point velocity.
        vt = v_pt_x * tx + v_pt_y * ty
        if abs(vt) > 1e-6 and mu > 0.0:
            r_cross_t = rx * ty - ry * tx
            inv_sum_t = inv_m + (r_cross_t * r_cross_t) * inv_I
            if inv_sum_t > 0.0:
                jt = -vt / inv_sum_t
                jt = max(-mu * abs(j), min(mu * abs(j), jt))
                jtx, jty = jt * tx, jt * ty
                self.hulls.velocity[hull_id, 0] += jtx * inv_m
                self.hulls.velocity[hull_id, 1] += jty * inv_m
                self.hulls.omega[hull_id] += (rx * jty - ry * jtx) * inv_I

        # Rigid Δ (post − pre): the cells must lag this change so the
        # contact-zone gains the body-local velocity field needed for the
        # contact-point KE loss to live in cells + heat rather than
        # vanishing.  Wall is treated as a body with no cells — only this
        # body's cells receive the inject.
        dvx = float(self.hulls.velocity[hull_id, 0] - v_pre[0])
        dvy = float(self.hulls.velocity[hull_id, 1] - v_pre[1])
        d_om = float(self.hulls.omega[hull_id]) - om_pre

        self._inject_local_velocity_field(
            hull_id=hull_id,
            world_point=contact_point,
            local_dv=(-dvx, -dvy),
            local_d_omega=-d_om,
            impact_speed_for_heat=abs(vn),
            rest=rest,
        )
        self._mark_active(hull_id)

    def _mark_active(self, hull_id: int) -> None:
        """Stamp ``hull_id`` hot for ``settle_frames`` more frames.

        Writes the SoA column on ``self.hulls`` directly so the per-frame
        gating in ``_gather_active_slots`` is a vectorised numpy mask.
        ``activation_level=2`` marks the hull as recently contacted; the
        end-of-step hysteresis decay drops it back down once the deadline
        passes.
        """
        deadline = int(self.frame) + int(self.config.hull.settle_frames)
        current = int(self.hulls.active_until_frame[hull_id])
        if deadline > current:
            self.hulls.active_until_frame[hull_id] = deadline
        self.hulls.activation_level[hull_id] = 2

    def _is_active(self, hull_id: int) -> bool:
        """Hull is active iff its deadline is still in the future."""
        return int(self.hulls.active_until_frame[hull_id]) >= int(self.frame)

    @property
    def active_until_frame(self) -> "_ActiveUntilFrameView":
        """Backwards-compatible dict-like view over the SoA column.

        Phase A migrated the storage from a Python dict to a numpy column
        on :class:`HullTree`.  Code that previously did
        ``world.active_until_frame[hid]`` or ``.get(hid, -1)`` keeps
        working through this shim, but new call sites should read the
        column directly for speed.
        """
        return _ActiveUntilFrameView(self.hulls)

    # -- impact injection (momentum-balanced cell deformation) --------------

    def _inject_local_velocity_field(
        self,
        hull_id: int,
        world_point: tuple[float, float],
        local_dv: tuple[float, float],
        impact_speed_for_heat: float,
        rest: float,
        local_d_omega: float = 0.0,
    ) -> None:
        """Inject a *zero-mean* body-local velocity perturbation at the
        contact zone (linear + angular).

        Architecture invariant: ``v_rigid`` and ``ω_rigid`` already
        represent the body's bulk translation and spin.  The per-cell
        ``v_local`` field must therefore have a mass-weighted mean of zero
        AND a mass-weighted ``r × v`` integral of zero in body-local frame
        — otherwise it shifts the body's CoM or its angular momentum and
        double-counts what the rigid state already tracks.

        How we enforce that:
          1. Compute a smoothstep falloff around the contact point.
          2. Add ``local_dv * falloff`` (linear) and
             ``(d_omega × r_cell_local) * falloff`` (angular) to each
             cell's local velocity.
          3. Subtract the resulting mass-weighted linear mean from every
             (inside) cell.
          4. Subtract the resulting mass-weighted angular mean — i.e.,
             subtract ``ω_mean × r_cell_local`` so Σ m_cell (r × v) = 0
             in body-local frame.

        Steps 3 and 4 make the inject a pure deformation (waves, ringing,
        splat) without ever creating net body momentum or angular
        momentum.  Energy comes from the rigid solver's restitution loss;
        cells gain only the inelastic portion via the heat path below.
        """
        gid = int(self.hulls.cell_grid_id[hull_id])
        if gid < 0:
            return
        cells = self.cell_pool.slot_view(gid)

        # Single source of truth for body extent: the hull's cell_size_xy.
        cs_x = float(self.hulls.cell_size_x[hull_id])
        cs_y = float(self.hulls.cell_size_y[hull_id])
        w = cs_x * CELL_GRID_SIZE
        h = cs_y * CELL_GRID_SIZE
        px = float(self.hulls.position[hull_id, 0])
        py = float(self.hulls.position[hull_id, 1])
        local_x = (world_point[0] - (px - w / 2.0)) / cs_x
        local_y = (world_point[1] - (py - h / 2.0)) / cs_y
        radius_cells = max(2.0, CELL_GRID_SIZE * 0.18)

        yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
        dx = xx - float(local_x)
        dy = yy - float(local_y)
        dist = np.sqrt(dx * dx + dy * dy)
        t = np.clip(1.0 - dist / radius_cells, 0.0, 1.0)
        falloff = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
        density_mask = (cells[..., _IDX_DENSITY] > 0.05).astype(np.float32)
        weight = falloff * density_mask

        # Body-local cell offsets (in world units).  We compute these
        # about the centre-of-mass (the mass-weighted centroid of the
        # density field) rather than the geometric centre — that way the
        # linear-mean and angular-mean subtraction steps decouple
        # cleanly (constant velocity carries zero angular momentum about
        # the CoM by definition; pure rotation about the CoM carries
        # zero linear momentum by definition).
        cx_idx = (CELL_GRID_SIZE - 1) * 0.5
        cy_idx = (CELL_GRID_SIZE - 1) * 0.5
        material = self._materials.get(int(self.hulls.material_id[hull_id]))
        rho_mat = material.density_rho if material is not None else 1.0
        m_per_cell = rho_mat * cells[..., _IDX_DENSITY]
        body_mass = float(m_per_cell.sum())
        if body_mass > 1e-9:
            com_x = float((m_per_cell * (xx - cx_idx)).sum()) / body_mass
            com_y = float((m_per_cell * (yy - cy_idx)).sum()) / body_mass
        else:
            com_x = com_y = 0.0
        rx_cell = (xx - cx_idx - com_x) * cs_x
        ry_cell = (yy - cy_idx - com_y) * cs_y

        # Linear inject.
        cells[..., _IDX_V_X] += float(local_dv[0]) * weight
        cells[..., _IDX_V_Y] += float(local_dv[1]) * weight

        # Angular inject: each contact-zone cell also lags the body by
        # d_omega × r_cell_local = (-d_omega * ry, +d_omega * rx).
        if local_d_omega != 0.0:
            cells[..., _IDX_V_X] += (-float(local_d_omega) * ry_cell) * weight
            cells[..., _IDX_V_Y] += (float(local_d_omega) * rx_cell) * weight

        # Enforce the zero-mean invariants: subtract the mass-weighted
        # mean of v_local (linear) AND the mass-weighted ω of v_local
        # (angular) so the body-local linear+angular momentum integrals
        # stay zero.  Because ``r_cell`` is in the CoM frame, the two
        # subtractions decouple — pure-translation has zero L about CoM,
        # pure-rotation about CoM has zero linear p.
        inside = density_mask > 0.0
        if body_mass > 1e-9:
            # Angular zero-mean FIRST: compute the mass-weighted mean
            # angular velocity of the local field,
            # ω_mean = Σ m (r × v) / Σ m r², then subtract ω_mean × r_cell
            # from each cell so the body-local angular momentum integral
            # is zero.  We do this before the linear-mean subtraction
            # because subtracting ω×r leaves a residual linear-mean of
            # ω_mean × r_com (zero only if the CoM is exactly at the
            # geometric centre — true only up to discretisation noise),
            # and the linear pass cleans up that residual cleanly.
            r2 = rx_cell * rx_cell + ry_cell * ry_cell
            I_cells = float((m_per_cell * r2).sum())
            if I_cells > 1e-9:
                L_cells = float(
                    (m_per_cell * (
                        rx_cell * cells[..., _IDX_V_Y]
                        - ry_cell * cells[..., _IDX_V_X]
                    )).sum()
                )
                mean_omega = L_cells / I_cells
                if abs(mean_omega) > 0.0:
                    # v -= ω_mean × r  =>  vx += ω_mean * ry, vy -= ω_mean * rx
                    cells[..., _IDX_V_X][inside] += (mean_omega * ry_cell)[inside]
                    cells[..., _IDX_V_Y][inside] -= (mean_omega * rx_cell)[inside]

            # Linear zero-mean: subtract the mass-weighted mean of v_local
            # so the body-local momentum integral stays zero.  Cells
            # *inside the silhouette only* — outside cells are masked.
            mean_vx = float((m_per_cell * cells[..., _IDX_V_X]).sum()) / body_mass
            mean_vy = float((m_per_cell * cells[..., _IDX_V_Y]).sum()) / body_mass
            cells[..., _IDX_V_X][inside] -= mean_vx
            cells[..., _IDX_V_Y][inside] -= mean_vy

        # Heat: a fraction of the inelastic energy loss becomes heat at the
        # contact site.  Total ΔKE_inel = 0.5 * µ * (1 - rest²) * vn²; half
        # of that lands here, the other body absorbs the rest.
        v2 = impact_speed_for_heat * impact_speed_for_heat
        heat_share = 0.5 * (1.0 - rest * rest) * v2
        cells[..., _IDX_HEAT] += heat_share * weight * 0.05

        # Phase B — CPU just wrote to this slot's v/heat channels; the
        # GPU substep must re-upload before its next dispatch.  We do
        # this unconditionally (cheap set.add) so the residency path is
        # safe to toggle on at any frame boundary.
        self.cell_pool.mark_dirty(gid)

    # -- CPU per-pixel solver shim (numpy port of per_pixel_sim.wgsl) -------

    def _cpu_substep(self, dt: float) -> None:
        """Run a numpy per-pixel solver step on every active T2 hull.

        Mirrors the logic of ``physics/shaders/per_pixel_sim.wgsl``. Not
        production-fast, but correct enough that Sprint 1's drop-tests can
        assert visible deformation in mud/water/sand grounds.

        Phase A: gating goes through the vectorised SoA column rather than
        the legacy per-hull ``_is_active`` dict lookup.
        """
        cell = self.config.cell
        hulls = self.hulls
        alive = hulls._alive
        has_grid = hulls.cell_grid_id >= 0
        hot = hulls.active_until_frame >= int(self.frame)
        active_hids = np.nonzero(alive & has_grid & hot)[0]
        for hid_arr in active_hids:
            hid = int(hid_arr)
            gid = int(hulls.cell_grid_id[hid])
            mat = self._materials.get(int(hulls.material_id[hid]))
            if mat is None:
                continue
            src = self.cell_pool.slot_view(gid).copy()
            dst = self.cell_pool.slot_view(gid)
            self._cpu_kernel(src, dst, mat, dt, cell)
            # Phase B — CPU is the source of truth after this kernel pass.
            # If the next substep ends up routing through the GPU (e.g.
            # because the user toggled gpu.enabled mid-run), persistent
            # residency must re-upload from this fresh CPU state.
            self.cell_pool.mark_dirty(gid)

    @staticmethod
    def _cpu_kernel(
        src: np.ndarray,
        dst: np.ndarray,
        mat: CellMaterial,
        dt: float,
        cell: CellConfig,
    ) -> None:
        """Numpy port of the WGSL elasticity / yield / heat kernel.

        Material drives the system: every scalar in the equations below is
        a ``mat.*`` field.  ``cell`` carries only numerical infrastructure
        (mask threshold, grid size).

        Paths covered:
          * Linear elasticity (4-neighbour Laplacian)
          * Viscous damping → heat (intact ↔ torn interpolation)
          * Heat diffusion (Laplacian, rate ``mat.thermal_k``)
          * Radiation cooling (rate ``mat.emissivity``)
          * Thermal + damage yield weakening
          * Brittle fracture (severs bonds, preserves mass)
          * Ductile plasticity (anisotropic perm-strain on principal axes)
          * Stretch-driven tearing
          * Bond-loss damping coupling (free fragments keep momentum)
          * Fluid pressure-gradient force
          * Melt-phase annealing
        """
        # NaN/inf guard rails at kernel entry.  Field values are taken as
        # float32 and clamped into safe physical ranges.  Without this, a
        # single rogue NaN/inf cell (from a prior substep that drove
        # ``v_mag2 = vx*vx + vy*vy`` past float32 overflow ~3.4e38, or from
        # an external mutation) would propagate through every roll/sqrt/divide
        # below and contaminate the entire grid.  Capping
        # ``u``/``v``/``heat``/``pressure`` well below float32 overflow is
        # the root-cause fix for the downstream
        # ``RuntimeWarning: invalid value encountered in cast`` raised by
        # render.py when ``world_cx = local_x + px`` is then ``astype(np.int32)``.
        _U_LIMIT = 1.0e8     # displacement (world units)
        _V_LIMIT = 1.0e6     # velocity (world units / s)
        _HEAT_LIMIT = 1.0e6
        _PRESSURE_LIMIT = 1.0e8

        # Input load.  The cell pool is sanitised on write-back at the end of
        # every kernel call (and by ``_pressure_project_arrays``), so the only
        # way a non-finite value can enter is via an external mutation outside
        # the substep loop.  We rely on the single ``nan_to_num`` safety net at
        # the bottom of the kernel and skip the per-channel cleaning here —
        # ``np.clip`` with ``out=`` keeps inputs in physical range without
        # allocating an intermediate.  This trades one front-loaded
        # ``nan_to_num`` pass for ~12 in-place clips, which cuts the
        # input-prep time by ~3-4× on the fluid_pool benchmark.
        u = src[..., _IDX_U_X:_IDX_U_Y + 1].astype(np.float32, copy=True)
        np.clip(u, -_U_LIMIT, _U_LIMIT, out=u)
        v = src[..., _IDX_V_X:_IDX_V_Y + 1].astype(np.float32, copy=True)
        np.clip(v, -_V_LIMIT, _V_LIMIT, out=v)

        def _load_clip(channel: int, lo: float, hi: float) -> np.ndarray:
            arr = src[..., channel].astype(np.float32, copy=True)
            np.clip(arr, lo, hi, out=arr)
            return arr

        perm_xx = _load_clip(_IDX_PERM_XX, -1.0, 1.0)
        perm_yy = _load_clip(_IDX_PERM_YY, -1.0, 1.0)
        perm_xy = _load_clip(_IDX_PERM_XY, -1.0, 1.0)
        pressure = _load_clip(_IDX_PRESSURE, -_PRESSURE_LIMIT, _PRESSURE_LIMIT)
        damage = _load_clip(_IDX_DAMAGE, 0.0, 1.0)
        density = _load_clip(_IDX_DENSITY, 0.0, 1.0)
        tear = _load_clip(_IDX_TEAR, 0.0, 1.5)
        heat = _load_clip(_IDX_HEAT, 0.0, _HEAT_LIMIT)
        bond_e = _load_clip(_IDX_BOND_E, 0.0, 1.0)
        bond_s = _load_clip(_IDX_BOND_S, 0.0, 1.0)
        bond_n_owned = _load_clip(_IDX_BOND_N, 0.0, 1.0)

        # Hoist material constants used in the hot path so attribute lookups
        # are not repeated inside the substep.  (Each ``mat.E`` lookup walks
        # the dataclass ``__getattr__``; doing it once per substep instead of
        # per expression shaves a small but real overhead on the 22-substep
        # fluid_pool run.)
        E_mat = float(mat.E)
        E_wave = float(mat.E_effective)
        density_rho = float(mat.density_rho)
        viscosity = float(mat.viscosity)
        torn_damping = float(mat.torn_damping)
        bond_intact_thresh = float(mat.bond_intact_threshold)
        bond_intact_slope = float(mat.bond_intact_slope)
        thermal_k = float(mat.thermal_k)
        emissivity = float(mat.emissivity)
        thermal_soft_coef = float(mat.thermal_softening_coefficient)
        damage_weaken_coef = float(mat.damage_weakening_coefficient)
        Y_mat = float(mat.Y)
        brittle_mod = float(mat.brittle_modulus)
        # KE→heat injection factor lives in CellConfig (engine-wide knob in
        # ``config/physics.yml``); plastic-strain→heat factor is per-material.
        heat_damp_factor = float(cell.heat_damping_to_heat_factor)
        heat_strain_factor = float(mat.heat_strain_energy_factor)

        # West bond at (y,x) = east bond at (y,x-1); north = south of (y-1,x).
        # Slice-shift (zero-padded) instead of np.roll: avoids per-call allocator
        # pressure inside the substep, matching the pattern proven out in
        # ``_pressure_project_arrays``.  Wrap semantics are irrelevant because
        # the outside-grid edges are zero-padded by construction.
        bond_w = np.zeros_like(bond_e)
        bond_w[:, 1:] = bond_e[:, :-1]
        bond_n = np.zeros_like(bond_s)
        bond_n[1:, :] = bond_s[:-1, :]

        # Neighbour density × bond coupling weights — slice-shifted, zero-padded.
        d_l = np.zeros_like(density)
        d_l[:, 1:] = density[:, :-1]
        d_l *= bond_w
        d_r = np.zeros_like(density)
        d_r[:, :-1] = density[:, 1:]
        d_r *= bond_e
        d_t = np.zeros_like(density)
        d_t[1:, :] = density[:-1, :]
        d_t *= bond_n
        d_b = np.zeros_like(density)
        d_b[:-1, :] = density[1:, :]
        d_b *= bond_s

        # Shifted displacement neighbours (zero-padded), scaled by d_*.
        u_l = np.zeros_like(u)
        u_l[:, 1:, :] = u[:, :-1, :]
        u_l *= d_l[..., None]
        u_r = np.zeros_like(u)
        u_r[:, :-1, :] = u[:, 1:, :]
        u_r *= d_r[..., None]
        u_t = np.zeros_like(u)
        u_t[1:, :, :] = u[:-1, :, :]
        u_t *= d_t[..., None]
        u_b = np.zeros_like(u)
        u_b[:-1, :, :] = u[1:, :, :]
        u_b *= d_b[..., None]

        # Strain tensor (central differences).
        eps_xx = (u_r[..., 0] - u_l[..., 0]) * 0.5
        eps_yy = (u_b[..., 1] - u_t[..., 1]) * 0.5
        eps_xy = ((u_r[..., 1] - u_l[..., 1]) + (u_b[..., 0] - u_t[..., 0])) * 0.25

        # Stretch metric — magnitude of neighbour-displacement gradient.
        dux_dx = u_r[..., 0] - u_l[..., 0]
        duy_dy = u_b[..., 1] - u_t[..., 1]
        dux_dy = u_t[..., 0] - u_b[..., 0]
        duy_dx = u_r[..., 1] - u_l[..., 1]
        stretch_now = np.sqrt(
            dux_dx * dux_dx + duy_dy * duy_dy + dux_dy * dux_dy + duy_dx * duy_dx
        )

        # Elastic stress from Hooke (subtract permanent strain).
        eps_el_xx = eps_xx - perm_xx
        eps_el_yy = eps_yy - perm_yy
        eps_el_xy = eps_xy - perm_xy
        sigma_xx = E_mat * eps_el_xx
        sigma_yy = E_mat * eps_el_yy
        sigma_xy = E_mat * eps_el_xy
        s_mean = (sigma_xx + sigma_yy) * 0.5
        s_dev_xx = sigma_xx - s_mean
        s_dev_yy = sigma_yy - s_mean
        vm = np.sqrt(
            s_dev_xx * s_dev_xx + s_dev_yy * s_dev_yy + 3.0 * sigma_xy * sigma_xy
        )

        # Laplacian force.  Phase D: use renormalised modulus ``E_effective``
        # for the wave-Laplacian path so the discrete kernel propagates the
        # wave-front at a visible rate (32 cells in ``wave_crossing_frames``
        # frames at 60 Hz).  The raw ``mat.E`` continues to drive the stress
        # tensor / yield arithmetic above, so this is purely a wave-speed
        # renormalisation — no change to fracture / plasticity scaling.
        lap_x = u_l[..., 0] + u_r[..., 0] + u_t[..., 0] + u_b[..., 0] - 4.0 * u[..., 0] * density
        lap_y = u_l[..., 1] + u_r[..., 1] + u_t[..., 1] + u_b[..., 1] - 4.0 * u[..., 1] * density
        f_x = E_wave * lap_x
        f_y = E_wave * lap_y

        if mat.is_fluid:
            # Slice-shift pressure neighbours (zero-padded) instead of np.roll.
            p_l = np.zeros_like(pressure)
            p_l[:, 1:] = pressure[:, :-1]
            p_l *= d_l
            p_r = np.zeros_like(pressure)
            p_r[:, :-1] = pressure[:, 1:]
            p_r *= d_r
            p_t = np.zeros_like(pressure)
            p_t[1:, :] = pressure[:-1, :]
            p_t *= d_t
            p_b = np.zeros_like(pressure)
            p_b[:-1, :] = pressure[1:, :]
            p_b *= d_b
            f_x = f_x - (p_r - p_l)
            f_y = f_y - (p_b - p_t)

        # Integrate velocity → apply mass-modulated forcing.
        # ``mass_eff`` is floored at 0.001 to guarantee a finite divisor even
        # when ``density`` is 0 (vacuum cells outside the silhouette).
        mass_eff = density_rho * density
        np.maximum(mass_eff, 0.001, out=mass_eff)
        inv_mass_dt = (dt / mass_eff)[..., None]
        v[..., 0] += f_x * inv_mass_dt[..., 0]
        v[..., 1] += f_y * inv_mass_dt[..., 0]
        # Cap velocity below the float32 sqrt-overflow threshold so
        # ``v_mag2 = vx*vx + vy*vy`` further down cannot saturate to inf.
        # This is the root-cause guard that stops the NaN cascade reported
        # in the showcase run: without it, a fast-moving steel ball impact
        # could push f_x/dt/mass_eff past ~1e19, then v*v past float32 max,
        # then heat += inf, then heat_lap = inf - inf = NaN.
        np.clip(v, -_V_LIMIT, _V_LIMIT, out=v)

        # Bond-intact damping: material drives the viscosity interpolation.
        # Intact regions damp at mat.viscosity; torn regions at mat.torn_damping.
        tear_excess = tear - bond_intact_thresh
        np.maximum(tear_excess, 0.0, out=tear_excess)
        bond_intact = 1.0 - tear_excess * bond_intact_slope
        np.clip(bond_intact, 0.0, 1.0, out=bond_intact)
        effective_D = torn_damping * (1.0 - bond_intact) + viscosity * bond_intact
        v *= effective_D[..., None]

        # Heat: damping → heat → diffusion → radiation.  All rates per-material.
        v_mag2 = v[..., 0] * v[..., 0] + v[..., 1] * v[..., 1]
        ke = 0.5 * mass_eff * v_mag2
        damped_ke = ke * (1.0 - effective_D * effective_D)
        # Heat-Laplacian: slice-shifted neighbour contributions (zero-padded).
        h_l = np.zeros_like(heat)
        h_l[:, 1:] = heat[:, :-1]
        h_r = np.zeros_like(heat)
        h_r[:, :-1] = heat[:, 1:]
        h_t = np.zeros_like(heat)
        h_t[1:, :] = heat[:-1, :]
        h_b = np.zeros_like(heat)
        h_b[:-1, :] = heat[1:, :]
        # Symmetric, conservation-preserving heat-diffusion stencil
        # (WP-O legacy).  ``c_ij = d_* = density[j] * bond_ij``.
        heat_lap = (
            h_l * d_l + h_r * d_r + h_t * d_t + h_b * d_b
            - heat * (d_l + d_r + d_t + d_b)
        )
        heat += heat_lap * (dt * thermal_k)
        # Density-weighted KE → heat injection (WP-T).
        #
        # Two corrections vs the legacy ``heat += damped_ke * 0.5`` form:
        #   1. Multiply by ``density``.  At partial-fill edge cells the
        #      cell volume is mostly void; only the ``density`` fraction is
        #      real material that actually dissipates KE into heat.
        #   2. Skip the injection entirely for fluids.  In the continuous
        #      Navier–Stokes picture viscous dissipation does heat the
        #      fluid, but the discrete cell-local form ``(1 - D²) * 0.5 * m * v²``
        #      double-counts: at LAVA's ``viscosity = 0.65`` the kernel
        #      claims 57.8 % of every cell's KE is converted to heat each
        #      substep, which combined with thermal-softening (``Y_eff /=
        #      (1 + heat * thermal_soft_coef)``) forms a positive feedback
        #      loop that saturates the 1e6 heat clamp by frame ~60 of the
        #      lava-flow demo.  Heat in a fluid is supposed to come from
        #      external work (contact, radiation) and external boundary
        #      exchange — not from the per-cell velocity field that the
        #      pressure-projection has not yet had a chance to
        #      divergence-zero.  Fluids therefore skip the KE-heat dump
        #      entirely; viscous damping still removes ``(1 - D)`` of v
        #      per substep, but that energy is dissipated to the
        #      environment rather than recirculated into the same cell's
        #      temperature.
        if not mat.is_fluid:
            heat += damped_ke * heat_damp_factor * density
        heat *= (1.0 - emissivity)
        # Final heat clamp: keeps ``1 / (1 + heat * coef)`` below well-defined
        # and stops a single high-energy substep from pushing the field to inf.
        # NaN guard kept here because heat_lap can blow up if input bond/density
        # fields are pathological; the final write-back is then the second net.
        np.nan_to_num(heat, copy=False, nan=0.0, posinf=_HEAT_LIMIT, neginf=0.0)
        np.clip(heat, 0.0, _HEAT_LIMIT, out=heat)

        # Thermal + damage weakening of yield (material-driven coefficients).
        soft_factor = 1.0 / (1.0 + heat * thermal_soft_coef)
        damage_weak = damage * damage_weaken_coef
        np.clip(damage_weak, 0.0, damage_weaken_coef, out=damage_weak)
        damage_factor = 1.0 - damage_weak
        weakness = soft_factor * damage_factor
        Y_eff = Y_mat * weakness
        brittle_eff = brittle_mod * weakness

        # Melt branch — anneals plastic strain, applies viscous damping.
        is_melted = heat > mat.melt_point
        if np.any(is_melted):
            perm_xx[is_melted] *= mat.melt_anneal_rate
            perm_yy[is_melted] *= mat.melt_anneal_rate
            perm_xy[is_melted] *= mat.melt_anneal_rate
            v[is_melted] *= mat.melt_viscous_damping

        # Brittle path — sever the dominant-axis bond, accumulate damage+tear.
        brittle = (~is_melted) & (vm > brittle_eff) & (brittle_mod < 800.0)
        if np.any(brittle):
            excess_b = vm[brittle] - brittle_eff[brittle]
            damage[brittle] = np.clip(
                damage[brittle] + excess_b * dt * mat.brittle_damage_rate,
                0.0, 1.0,
            )
            tear[brittle] = np.clip(
                tear[brittle] + excess_b * dt * mat.brittle_tear_rate,
                0.0, 1.5,
            )
            bond_loss = (
                excess_b * dt * mat.brittle_bond_loss_rate
                * (1.0 + stretch_now[brittle] * mat.brittle_stretch_amplification)
            )
            sever_h = np.abs(sigma_xx[brittle]) > np.abs(sigma_yy[brittle])
            bond_e_b = bond_e[brittle].copy()
            bond_s_b = bond_s[brittle].copy()
            bond_e_b[sever_h] = np.maximum(0.0, bond_e_b[sever_h] - bond_loss[sever_h])
            bond_s_b[~sever_h] = np.maximum(0.0, bond_s_b[~sever_h] - bond_loss[~sever_h])
            # Catastrophic severance — vm well past the brittle envelope
            # AND the cell already accumulated meaningful damage from
            # the per-substep accumulation path.  Severs the dominant
            # bond on this cell completely so a single substep produces
            # a step-function break instead of multiplicative decay; the
            # accumulation gate (damage > threshold) prevents the very
            # first impulse from flash-fragmenting an entire body in one
            # frame.  See WP-V (config knobs
            # ``brittle_catastrophic_excess_ratio`` /
            # ``brittle_catastrophic_bond_floor``).
            cat_ratio = float(cell.brittle_catastrophic_excess_ratio)
            cat_floor = float(cell.brittle_catastrophic_bond_floor)
            cat_dmg_gate = float(cell.brittle_catastrophic_damage_gate)
            cat_mask = (
                (excess_b > brittle_eff[brittle] * (cat_ratio - 1.0))
                & (damage[brittle] > cat_dmg_gate)
            )
            if np.any(cat_mask):
                # Only sever the dominant-axis bond catastrophically.
                # This still leaves the perpendicular axis to accumulate
                # damage at its own rate.
                cat_h = cat_mask & sever_h
                cat_v = cat_mask & (~sever_h)
                bond_e_b[cat_h] = np.minimum(bond_e_b[cat_h], cat_floor)
                bond_s_b[cat_v] = np.minimum(bond_s_b[cat_v], cat_floor)
            bond_e[brittle] = bond_e_b
            bond_s[brittle] = bond_s_b

        # Ductile path — anisotropic plastic strain along principal stress axes.
        ductile = (~is_melted) & (~brittle) & (vm > Y_eff)
        if np.any(ductile):
            s_diff = (sigma_xx[ductile] - sigma_yy[ductile]) * 0.5
            R_stress = np.sqrt(s_diff * s_diff + sigma_xy[ductile] * sigma_xy[ductile])
            theta = 0.5 * np.arctan2(sigma_xy[ductile], s_diff)
            ct = np.cos(theta)
            st_ = np.sin(theta)
            ct2 = ct * ct
            st2 = st_ * st_
            excess_d = (vm[ductile] - Y_eff[ductile]) / np.maximum(vm[ductile], 1e-4)
            d_eps_1 = excess_d * mat.ductile_plastic_strain_rate * R_stress / max(mat.E, 1.0)
            d_eps_2 = -d_eps_1 * mat.ductile_poisson_ratio
            d_eps_xx = d_eps_1 * ct2 + d_eps_2 * st2
            d_eps_yy = d_eps_1 * st2 + d_eps_2 * ct2
            d_eps_xy = (d_eps_1 - d_eps_2) * st_ * ct
            perm_xx[ductile] += d_eps_xx
            perm_yy[ductile] += d_eps_yy
            perm_xy[ductile] += d_eps_xy
            damage[ductile] = np.clip(
                damage[ductile] + (vm[ductile] - Y_eff[ductile]) * dt * mat.ductile_damage_rate,
                0.0, 1.0,
            )
            strain_energy = 0.5 * mat.E * (
                eps_el_xx[ductile] ** 2 + eps_el_yy[ductile] ** 2
                + 2.0 * eps_el_xy[ductile] ** 2
            ) * excess_d
            # Density-weighted plastic-work → heat injection (WP-T).
            #
            # Two corrections vs the legacy path:
            #   1. Multiply by ``density`` — at a partial-fill cell only the
            #      ``density`` fraction is real material, so only that
            #      fraction thermalises into the cell-averaged ``heat``
            #      field.  Mirrors the KE → heat fix above.
            #   2. Gate by ``~is_fluid`` — fluid materials have no plastic
            #      yield surface in the continuum sense; their irreversible
            #      energy dissipation already lives in the viscous-damping
            #      term ``(1 - effective_D**2) * ke`` further up.  Running
            #      the ductile branch for LAVA injects a runaway
            #      ``0.5 * E * eps_el² * heat_strain_factor`` every substep
            #      once the lava cools just past ``melt_point`` (the
            #      ``is_melted`` gate releases, the projection-residual
            #      ``eps_el`` is tiny but non-zero, and the elastic-energy
            #      formula ``0.5 * E * eps²`` compounds exponentially once
            #      ``heat > melt_point`` thermal-softens ``Y_eff`` again
            #      — root cause of the WP-T lava-saturation cascade at
            #      frame 30 onward).
            if not mat.is_fluid:
                heat[ductile] += (
                    strain_energy * heat_strain_factor * density[ductile]
                )

        # Remold (clay/mud anneal plastic strain over time).
        remold_decay = 1.0 - mat.remold_rate * dt * 60.0
        perm_xx *= remold_decay
        perm_yy *= remold_decay
        perm_xy *= remold_decay

        # Stretch-driven tearing.
        if mat.tear_strength < 800.0:
            torn = stretch_now > mat.tear_strength
            if np.any(torn):
                excess_t = stretch_now[torn] - mat.tear_strength
                tear[torn] = np.clip(
                    tear[torn] + excess_t * dt * mat.tear_growth_rate,
                    0.0, 1.5,
                )

        # Fluid pressure update (per-material coupling).  The damped-pressure
        # smoothing stays as a cheap relaxation signal; Phase C then runs a
        # real divergence-free projection on top that actually enforces
        # nabla.v approx 0 by subtracting grad p from the velocity field.
        if mat.is_fluid:
            # Slice-shifted v[...,0] / v[...,1] neighbours, zero-padded.
            vx = v[..., 0]
            vy = v[..., 1]
            vx_r = np.zeros_like(vx)
            vx_r[:, :-1] = vx[:, 1:]
            vx_l = np.zeros_like(vx)
            vx_l[:, 1:] = vx[:, :-1]
            vy_b = np.zeros_like(vy)
            vy_b[:-1, :] = vy[1:, :]
            vy_t = np.zeros_like(vy)
            vy_t[1:, :] = vy[:-1, :]
            div_v_smooth = (
                vx_r * d_r - vx_l * d_l + vy_b * d_b - vy_t * d_t
            ) * 0.5
            pressure = pressure - div_v_smooth * mat.E * dt * mat.fluid_pressure_coupling

            # Slice-shifted pressure neighbours for the smoothing pass.
            p_l_s = np.zeros_like(pressure)
            p_l_s[:, 1:] = pressure[:, :-1]
            p_r_s = np.zeros_like(pressure)
            p_r_s[:, :-1] = pressure[:, 1:]
            p_t_s = np.zeros_like(pressure)
            p_t_s[1:, :] = pressure[:-1, :]
            p_b_s = np.zeros_like(pressure)
            p_b_s[:-1, :] = pressure[1:, :]
            p_avg = (
                p_l_s * d_l + p_r_s * d_r + p_t_s * d_t + p_b_s * d_b
            ) * 0.25
            pressure = pressure * (1.0 - mat.fluid_pressure_smoothing) + p_avg * mat.fluid_pressure_smoothing
            pressure = pressure * mat.fluid_pressure_decay

            # Phase C: Jacobi-iterated divergence-free projection.
            # Solves laplacian(p) = div(v) / dt, then v -= grad(p) * dt.
            # Without this, divergence accumulates and the smoothing path
            # diffuses it away as energy.
            if mat.fluid_projection_iters > 0:
                v, pressure = PhysicsWorld._pressure_project_arrays(
                    v, pressure, density, mat, dt,
                    cell.silhouette_mask_threshold,
                )

        # Update displacement (after projection so the divergence-free v
        # is what actually advects the cells this substep).
        u_new = u + v * dt

        # Final write-back NaN/inf guard.  Even though we clean inputs and
        # clamp v after integration, the fluid pressure-projection branch and
        # the Jacobi sweeps can in pathological configurations produce
        # non-finite values (e.g. an isolated fluid cell with no neighbours
        # and high divergence).  Sanitising once more here means the cell
        # grid is *never* persisted with NaN/inf, which removes the upstream
        # source of the renderer's ``invalid value encountered in cast``.
        # ``nan_to_num(copy=False, ...)`` writes in place — avoids an extra
        # allocation per channel.
        np.nan_to_num(u_new, copy=False, nan=0.0, posinf=_U_LIMIT, neginf=-_U_LIMIT)
        np.clip(u_new, -_U_LIMIT, _U_LIMIT, out=u_new)
        np.nan_to_num(v, copy=False, nan=0.0, posinf=_V_LIMIT, neginf=-_V_LIMIT)
        np.clip(v, -_V_LIMIT, _V_LIMIT, out=v)
        np.nan_to_num(
            pressure, copy=False, nan=0.0,
            posinf=_PRESSURE_LIMIT, neginf=-_PRESSURE_LIMIT,
        )
        np.clip(pressure, -_PRESSURE_LIMIT, _PRESSURE_LIMIT, out=pressure)
        np.nan_to_num(heat, copy=False, nan=0.0, posinf=_HEAT_LIMIT, neginf=0.0)
        np.clip(heat, 0.0, _HEAT_LIMIT, out=heat)
        np.nan_to_num(stretch_now, copy=False, nan=0.0, posinf=_U_LIMIT, neginf=0.0)

        # Mask: zero out displacement+velocity+heat outside the silhouette.
        # Heat is masked alongside u/v because vacuum cells have no thermal
        # mass — any residue from the asymmetric legacy heat-Laplacian (or
        # neighbour-side boundary effects) must not persist between substeps,
        # otherwise it re-injects into the active region next frame.
        outside = density < cell.silhouette_mask_threshold
        u_new[outside] = 0.0
        v[outside] = 0.0
        heat[outside] = 0.0

        # Write back the full state vector.
        dst[..., _IDX_U_X:_IDX_U_Y + 1] = u_new
        dst[..., _IDX_V_X:_IDX_V_Y + 1] = v
        dst[..., _IDX_PERM_XX] = perm_xx
        dst[..., _IDX_PERM_YY] = perm_yy
        dst[..., _IDX_PERM_XY] = perm_xy
        dst[..., _IDX_PRESSURE] = pressure
        dst[..., _IDX_DAMAGE] = damage
        dst[..., _IDX_DENSITY] = density  # mass conservation: density preserved
        dst[..., _IDX_STRETCH] = stretch_now
        dst[..., _IDX_TEAR] = tear
        dst[..., _IDX_HEAT] = heat
        dst[..., _IDX_BOND_N] = bond_n_owned   # owned bonds (N = north neighbour's S)
        dst[..., _IDX_BOND_E] = bond_e
        dst[..., _IDX_BOND_S] = bond_s

    # -- Phase C: divergence-free pressure projection (CPU prototype) -------

    def _pressure_project(
        self,
        cells: np.ndarray,
        mat: "CellMaterial",
        dt: float,
    ) -> None:
        """Jacobi-iterated pressure projection that enforces div(v) = 0
        inside a fluid body's cell grid.

        Solves laplacian(p) = div(v) / dt, then v -= grad(p) * dt.

        Boundary: Neumann-zero (dp/dn = 0) at silhouette edges (cells with
        density < threshold). Implemented by zeroing the pressure read at
        boundary neighbours during the Jacobi sweep (free-surface).

        Operates in-place on the cells array's velocity (channels 2,3) and
        pressure (channel 7).  Density is read from channel 9.
        """
        threshold = float(self.config.cell.silhouette_mask_threshold)
        v = cells[..., _IDX_V_X:_IDX_V_Y + 1].astype(np.float32, copy=True)
        pressure = cells[..., _IDX_PRESSURE].astype(np.float32, copy=True)
        density = cells[..., _IDX_DENSITY].astype(np.float32, copy=True)
        v_new, p_new = PhysicsWorld._pressure_project_arrays(
            v, pressure, density, mat, dt, threshold,
        )
        cells[..., _IDX_V_X:_IDX_V_Y + 1] = v_new
        cells[..., _IDX_PRESSURE] = p_new

    # Module-level scratch pool for ``_pressure_project_arrays``.  Keyed
    # on grid ``(H, W)`` — in practice every fluid hull shares the same
    # dims (``cell.grid_size`` from ``config/physics.yml``), so this
    # collapses to a single allocation that gets reused for every body
    # for the lifetime of the process.  Empty by default; populated
    # lazily on the first projection call at each shape.
    _PROJ_SCRATCH: dict[tuple[int, int], dict[str, np.ndarray]] = {}

    @staticmethod
    def _get_proj_scratch(H: int, W: int) -> dict[str, np.ndarray]:
        """Return the pooled SOR scratch buffers for an ``(H, W)`` grid.

        Allocates lazily on first access; subsequent calls return the
        same dict so the caller can ``fill(0.0)`` and overwrite in
        place.  The dict holds:

        * ``m_l, m_r, m_t, m_b`` — neighbour-exists shifted-mask buffers
        * ``shifted`` — slice-shift scratch used for div / gradient
        * ``div`` — divergence (RHS for the SOR sweep)
        * ``p``     — pressure being solved
        * ``nb_sum`` — accumulator for the 4-neighbour pressure gather
        * ``red_w, black_w`` — omega-masked red/black weight buffers
        * ``red_pat, black_pat`` — the constant checkerboard patterns
          (only depend on shape — built once, never mutated)
        """
        cache = PhysicsWorld._PROJ_SCRATCH.get((H, W))
        if cache is not None:
            return cache
        zeros = lambda: np.zeros((H, W), dtype=np.float32)
        yy, xx = np.indices((H, W))
        red_pat = ((yy + xx) % 2 == 0).astype(np.float32)
        black_pat = ((yy + xx) % 2 == 1).astype(np.float32)
        cache = {
            "m_l": zeros(), "m_r": zeros(), "m_t": zeros(), "m_b": zeros(),
            "shifted": zeros(),
            "div": zeros(),
            "p": zeros(),
            "nb_sum": zeros(),
            "red_w": zeros(),
            "black_w": zeros(),
            "red_pat": red_pat,
            "black_pat": black_pat,
        }
        PhysicsWorld._PROJ_SCRATCH[(H, W)] = cache
        return cache

    @staticmethod
    def _pressure_project_arrays(
        v: np.ndarray,
        pressure: np.ndarray,
        density: np.ndarray,
        mat: "CellMaterial",
        dt: float,
        mask_threshold: float,
    ) -> "tuple[np.ndarray, np.ndarray]":
        """Functional core of :py:meth:`_pressure_project`.

        Takes (H, W, 2) velocity, (H, W) pressure, (H, W) density and
        returns the projected (v, pressure) with the body mask reapplied.

        Implementation uses a *consistent* operator pair on a collocated
        grid: backward-difference divergence + forward-difference gradient,
        which compose to the standard 5-point Laplacian.  This keeps the
        Jacobi solver from stalling on the checkerboard null space that a
        pure central-difference scheme suffers from.

            div(v)[i,j] = (vx[i,j] - vx[i-1,j]) + (vy[i,j] - vy[i,j-1])
            for k in iters:
                # Red-Black SOR sweeps over a 5-point Laplacian.
                p[i,j] = (1 - w) * p_old +
                         w * (p_l + p_r + p_t + p_b - div) / 4
            v_x[i,j] -= (p[i+1,j] - p[i,j])
            v_y[i,j] -= (p[i,j+1] - p[i,j])

        The factor of 1/dt usually attached to the RHS is folded into the
        pressure (so ``p`` here is the pseudo-pressure P = p_phys * dt /
        rho); this keeps the solver stable across dt without retuning.

        Why Red-Black SOR instead of plain Jacobi?
        ------------------------------------------
        Plain Jacobi converges at rate cos(pi/N) per sweep — on a 32-cell
        grid that is ~0.995, so a residual takes ~500 sweeps to drop 70%.
        Red-Black Gauss-Seidel halves that, and adding a successive
        over-relaxation factor omega in [1, 2) drops the effective rate
        to about (1 - sin(pi/N)) — under 10 sweeps to remove most of a
        low-frequency mode.  Same per-sweep cost in numpy.

        Boundary handling
        -----------------
        * Cells outside the silhouette (density < mask_threshold) are
          treated as vacuum: their pressure is zero (Dirichlet free
          surface) and they do not contribute to neighbour updates.
        * The residual is restricted to fluid cells each sweep so cells
          outside the body stay at zero pressure / velocity.
        """
        iters = int(getattr(mat, 'fluid_projection_iters', 0))
        if iters <= 0:
            return v, pressure

        # Opt-in multi-grid V-cycle path.  Gated on
        # ``CellMaterial.use_multigrid`` (default False), so legacy
        # callers and existing tests see bit-identical behaviour.  The
        # V-cycle module handles its own early-out, mask handling, NaN
        # guard, and shares the same operator pair as the loop below.
        if bool(getattr(mat, "use_multigrid", False)):
            from pharos_engine.physics.pressure_multigrid import vcycle_project_v
            return vcycle_project_v(
                v, pressure, density, mat, dt, mask_threshold,
                smooth_pre=2, smooth_post=2, coarse_iters=8,
            )

        H, W = density.shape
        # Red-Black SOR relaxation factor.  omega ~= 2 / (1 + sin(pi/N))
        # is the theoretical optimum for the 5-point Laplacian on an N-cell
        # square; in practice the fluid mask + boundary handling on the
        # kernel grid makes that overshoot, so use a milder, fixed omega
        # that converges reliably without destabilising splashes.
        omega = np.float32(1.5)

        # Fluid mask + neighbour-interior flags.
        #
        # Performance note: WP-A removed ``np.roll`` for the neighbour
        # shifts (slice-based copies on preallocated scratch buffers).
        # WP-F goes further: the SOR sweep was the residual hot-spot
        # after WP-A.  Two changes pull another ~30-40% out of the
        # kernel:
        #
        #   1. Scratch buffers (``nb_sum``, the omega-mask weights, the
        #      neighbour exists masks) are pooled in a module-level
        #      cache keyed on ``(H, W)``.  The function is a
        #      ``@staticmethod`` so we cannot stash them on ``self``;
        #      the module cache amortises allocation across every body
        #      sharing the same hull grid (all of them on a fixed
        #      ``cell.grid_size = 32`` setup).
        #   2. The inner Red-Black update is reordered to be entirely
        #      in-place on the ``nb_sum`` scratch — the previous version
        #      allocated four temporaries per sweep
        #      (``p_jacobi``, ``p_jacobi - p``, ``red_w * (...)``,
        #      and the ``nb_sum - rhs`` intermediate).  The new form
        #      uses ``np.subtract(..., out=nb_sum)`` style ops so the
        #      hot loop performs *zero* heap allocations per sweep.
        #
        # The neighbour-mask multiplies in the gather (``* m_l[:, 1:]``)
        # are kept defensively: vacuum cells of ``p`` are provably zero
        # under the omega weighting (red_w/black_w are zero outside the
        # mask, so ``p += red_w * delta`` never touches them), so in
        # principle the multiplies are no-ops.  We retain them so any
        # caller that hands in a non-zero seed pressure on vacuum cells
        # still converges correctly — the cost is one MAC per cell, well
        # below the in-place arithmetic savings.
        mask = (density >= mask_threshold).astype(np.float32, copy=False)

        cache = PhysicsWorld._get_proj_scratch(H, W)
        m_l, m_r, m_t, m_b = cache["m_l"], cache["m_r"], cache["m_t"], cache["m_b"]
        # Refresh the neighbour masks from the current body mask — these
        # buffers are owned by the cache so the writes are in-place.
        m_l.fill(0.0); m_l[:, 1:] = mask[:, :-1]
        m_r.fill(0.0); m_r[:, :-1] = mask[:, 1:]
        m_t.fill(0.0); m_t[1:, :] = mask[:-1, :]
        m_b.fill(0.0); m_b[:-1, :] = mask[1:, :]

        v_x = v[..., 0].astype(np.float32, copy=True)
        v_y = v[..., 1].astype(np.float32, copy=True)

        # Backward-difference divergence on the collocated grid.  Reuse
        # the cache ``shifted`` scratch to avoid the per-call allocation.
        shifted = cache["shifted"]
        shifted.fill(0.0)
        shifted[:, 1:] = v_x[:, :-1]
        np.multiply(shifted, m_l, out=shifted)  # shifted == v_x_l now
        div = cache["div"]
        np.subtract(v_x, shifted, out=div)      # div = v_x - v_x_l
        shifted.fill(0.0)
        shifted[1:, :] = v_y[:-1, :]
        np.multiply(shifted, m_t, out=shifted)  # shifted == v_y_t now
        # div += (v_y - v_y_t)
        np.add(div, v_y, out=div)
        np.subtract(div, shifted, out=div)

        # Early-out: if the velocity field is already essentially
        # divergence-free (settled water sitting in a container, or a body
        # the upstream kernel just finished projecting and nothing has
        # disturbed) the SOR sweeps have no meaningful work to do — the
        # gradient subtraction below would just be subtracting numerical
        # noise from v.  Bail out and return the inputs untouched.  The
        # threshold is tight enough that any visible splash still
        # triggers the full solver (peak |div(v)| during the steel-into-
        # water impact is ~0.4); the value 1e-3 is one tenth of the
        # ``test_projection_reduces_divergence`` fixture's residual.
        if float(np.abs(div).max()) < 1e-3:
            return v, pressure

        # Start the SOR solve from zero pressure rather than warm-starting
        # off the damped-pressure field — the damped field is on a
        # different scale, so using it as a warm start makes the solver
        # overshoot.  A fresh start converges fast enough at the default
        # sweep count and the lost information is not missed.
        p = cache["p"]
        p.fill(0.0)

        # Red-black checkerboard pattern: cells with (y + x) % 2 == 0 are
        # "red", the others are "black".  Updating reds first using
        # neighbour blacks, then blacks using neighbour reds, is
        # equivalent to one Gauss-Seidel sweep with half the spectral
        # radius of Jacobi.  Pre-multiply each by omega*mask so the hot
        # loop reduces to a single MAC per cell.
        red_w = cache["red_w"]
        black_w = cache["black_w"]
        # Recompute the omega-mask weights from the current mask (the
        # checkerboard pattern itself is cached, mask varies per body).
        np.multiply(cache["red_pat"], mask, out=red_w)
        red_w *= omega
        np.multiply(cache["black_pat"], mask, out=black_w)
        black_w *= omega

        nb_sum = cache["nb_sum"]

        for _ in range(iters):
            # Red sweep — accumulate four shifted neighbour pressures.
            nb_sum.fill(0.0)
            nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]    # left neighbour
            nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]   # right neighbour
            nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]    # top neighbour
            nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]   # bottom neighbour
            # In-place SOR step on nb_sum:
            #   nb_sum := ((nb_sum - div) * 0.25 - p) * red_w
            #   p     += nb_sum
            np.subtract(nb_sum, div, out=nb_sum)
            nb_sum *= 0.25
            np.subtract(nb_sum, p, out=nb_sum)
            nb_sum *= red_w
            p += nb_sum

            # Black sweep — re-gather neighbours (reds just changed).
            nb_sum.fill(0.0)
            nb_sum[:, 1:] += p[:, :-1] * m_l[:, 1:]
            nb_sum[:, :-1] += p[:, 1:] * m_r[:, :-1]
            nb_sum[1:, :] += p[:-1, :] * m_t[1:, :]
            nb_sum[:-1, :] += p[1:, :] * m_b[:-1, :]
            np.subtract(nb_sum, div, out=nb_sum)
            nb_sum *= 0.25
            np.subtract(nb_sum, p, out=nb_sum)
            nb_sum *= black_w
            p += nb_sum

            # Restrict to fluid cells (kills any vacuum-cell drift from
            # finite-precision arithmetic in the omega step).
            p *= mask

        # Forward-difference gradient — paired with the backward-diff div
        # above to give the consistent 5-point Laplacian.  Reuse the
        # cache shifted scratch one more time for the gradient.
        shifted.fill(0.0)
        shifted[:, :-1] = p[:, 1:]
        np.multiply(shifted, m_r, out=shifted)  # shifted == p_r_arr
        v_x_new = v_x - (shifted - p)
        shifted.fill(0.0)
        shifted[:-1, :] = p[1:, :]
        np.multiply(shifted, m_b, out=shifted)  # shifted == p_b_arr
        v_y_new = v_y - (shifted - p)

        v_out = v.astype(np.float32, copy=True)
        v_out[..., 0] = v_x_new
        v_out[..., 1] = v_y_new

        # Re-mask so cells outside the body do not drift.  ``p`` aliases
        # the cache buffer, so we must return a *copy* — the next call
        # would otherwise stomp the caller's pressure array.
        outside = mask < 0.5
        v_out[outside] = 0.0
        p_out = p.copy()
        p_out[outside] = 0.0
        return v_out, p_out

    # -- GPU per-pixel solver (WGSL dispatch) -------------------------------

    def _should_use_gpu(self) -> bool:
        """Decide between GPU and CPU paths for this frame's substeps."""
        gpu_cfg = self.config.gpu
        if gpu_cfg.debug_force_cpu:
            return False
        if not gpu_cfg.enabled:
            return False
        if not self._gpu_initialised:
            self._init_gpu()
        return self._gpu_available

    def _init_gpu(self) -> None:
        """Acquire a wgpu adapter/device + build the persistent kernel
        resources.  Falls back gracefully if no adapter is available.
        """
        self._gpu_initialised = True
        try:
            import wgpu  # type: ignore
        except Exception:
            warnings.warn(
                "wgpu module not importable; falling back to CPU per-pixel kernel.",
                RuntimeWarning,
                stacklevel=2,
            )
            self._gpu_available = False
            return

        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        except Exception:
            adapter = None
        if adapter is None:
            warnings.warn(
                "No wgpu adapter available; falling back to CPU per-pixel kernel.",
                RuntimeWarning,
                stacklevel=2,
            )
            self._gpu_available = False
            return

        try:
            device = adapter.request_device_sync(required_features=[], required_limits={})
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"wgpu device request failed ({exc!r}); falling back to CPU kernel.",
                RuntimeWarning,
                stacklevel=2,
            )
            self._gpu_available = False
            return

        # Cache the wgpu module + device.
        self._wgpu = wgpu
        self._gpu_device = device
        self._gpu_queue = device.queue
        try:
            self._gpu_adapter_name = adapter.summary
        except Exception:
            self._gpu_adapter_name = "unknown"

        # Compile the kernel once.
        shader_path = Path(__file__).with_name("shaders") / "per_pixel_sim.wgsl"
        src = shader_path.read_text(encoding="utf-8")
        module = device.create_shader_module(code=src, label="per_pixel_sim")
        self._gpu_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
            label="per_pixel_sim_pipeline",
        )
        self._gpu_bind_layout = self._gpu_pipeline.get_bind_group_layout(0)

        # Phase C: separate compute pipeline for the Red-Black SOR
        # pressure projection.  Dispatches *after* the per-pixel kernel
        # only for hulls whose material is a fluid with iters > 0.
        proj_shader_path = (
            Path(__file__).with_name("shaders") / "pressure_project.wgsl"
        )
        proj_src = proj_shader_path.read_text(encoding="utf-8")
        proj_module = device.create_shader_module(
            code=proj_src, label="pressure_project",
        )
        self._gpu_proj_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": proj_module, "entry_point": "main"},
            label="pressure_project_pipeline",
        )
        self._gpu_proj_bind_layout = (
            self._gpu_proj_pipeline.get_bind_group_layout(0)
        )
        # Tiny uniform buffer carrying the iteration count (one u32 + pad
        # to 16 B for uniform alignment).
        self._gpu_proj_cfg_buf = device.create_buffer(
            size=16,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="pressure_project_cfg",
        )

        # Per-hull params lives in a STORAGE buffer (the shader uses an
        # ``array<HullParams>`` so it can index per workgroup_id.z).  Size
        # grows lazily; start at 1 hull's worth.
        self._gpu_params_size = self._params_struct_size()
        self._gpu_resize_indirect_buffers(max_active=1)

        # Allocate cell + mask buffers sized to current pool capacity.
        self._gpu_resize_buffers(self.cell_pool.capacity)

        self._gpu_available = True

    # Number of float32s per cell slot.
    _SLOT_FLOATS = CELL_GRID_SIZE * CELL_GRID_SIZE * 16
    _SLOT_BYTES = _SLOT_FLOATS * 4
    _SLOT_MASK_BYTES = CELL_GRID_SIZE * CELL_GRID_SIZE * 4  # one u32 per pixel

    @staticmethod
    def _params_struct_size() -> int:
        """Size of one HullParams record in bytes.

        The WGSL struct is 40 × 4-byte scalars (u32/f32) = 160 B with no
        internal padding (all fields share 4-byte alignment).  WGSL stride
        for ``array<HullParams>`` is therefore 160 B — we do NOT round up
        to 16 here because that would mismatch the GPU stride.
        WP-V added three brittle-catastrophic scalars.
        """
        return 40 * 4

    def _gpu_resize_buffers(self, capacity: int) -> None:
        """(Re)allocate src/dst/mask GPU buffers sized to ``capacity`` slots.

        Called on first init and whenever ``cell_pool.grow()`` enlarges the
        host-side backing array.
        """
        wgpu = self._wgpu
        device = self._gpu_device
        total_cells_bytes = capacity * self._SLOT_BYTES
        total_mask_bytes = capacity * self._SLOT_MASK_BYTES
        usage_storage = (
            wgpu.BufferUsage.STORAGE
            | wgpu.BufferUsage.COPY_DST
            | wgpu.BufferUsage.COPY_SRC
        )
        # Destroy old buffers if any.
        for attr in ("_gpu_src_buf", "_gpu_dst_buf", "_gpu_mask_buf", "_gpu_readback_buf"):
            old = getattr(self, attr, None)
            if old is not None:
                try:
                    old.destroy()
                except Exception:
                    pass
        self._gpu_src_buf = device.create_buffer(
            size=total_cells_bytes, usage=usage_storage, label="per_pixel_src",
        )
        self._gpu_dst_buf = device.create_buffer(
            size=total_cells_bytes, usage=usage_storage, label="per_pixel_dst",
        )
        self._gpu_mask_buf = device.create_buffer(
            size=total_mask_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="per_pixel_mask",
        )
        # Per-slot readback buffer (legacy per-hull path).
        self._gpu_readback_buf = device.create_buffer(
            size=self._SLOT_BYTES,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
            label="per_pixel_readback",
        )
        # Stamp the mask as all-on (silhouette gating happens via density).
        mask_all_on = np.full(
            (capacity * CELL_GRID_SIZE * CELL_GRID_SIZE,), 0xFF, dtype=np.uint32
        )
        self._gpu_queue.write_buffer(self._gpu_mask_buf, 0, mask_all_on.tobytes())
        self._gpu_buf_capacity = capacity

    def _maybe_resize_gpu_for_pool(self) -> None:
        """Resize GPU buffers to match the cell pool's current capacity."""
        if self.cell_pool.capacity != self._gpu_buf_capacity:
            self._gpu_resize_buffers(self.cell_pool.capacity)

    def _gpu_resize_indirect_buffers(self, max_active: int) -> None:
        """(Re)allocate indirect-dispatch buffers sized for ``max_active``
        hulls in flight at once.

        Three storage buffers + one indirect-args buffer + one wider readback
        buffer.  Grown lazily as scenes spawn more simultaneously-active T2
        hulls.
        """
        wgpu = self._wgpu
        device = self._gpu_device
        # Round up to at least 1 to avoid zero-sized buffers.
        max_active = max(1, max_active)
        params_total_bytes = max_active * self._gpu_params_size
        # Active-hull indices: one u32 each, but pad to >= 4 bytes for safety.
        active_total_bytes = max(4, max_active * 4)
        # Multi-slot readback (active_count slots × per-slot bytes).
        multi_readback_bytes = max_active * self._SLOT_BYTES

        # Destroy old buffers if any.
        for attr in (
            "_gpu_per_hull_params_buf",
            "_gpu_active_hulls_buf",
            "_gpu_indirect_args_buf",
            "_gpu_multi_readback_buf",
            "_gpu_proj_per_hull_params_buf",
            "_gpu_proj_active_hulls_buf",
        ):
            old = getattr(self, attr, None)
            if old is not None:
                try:
                    old.destroy()
                except Exception:
                    pass

        self._gpu_per_hull_params_buf = device.create_buffer(
            size=params_total_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="per_hull_params",
        )
        self._gpu_active_hulls_buf = device.create_buffer(
            size=active_total_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="active_hulls",
        )
        self._gpu_indirect_args_buf = device.create_buffer(
            size=16,  # 3 × u32 + pad
            usage=(
                wgpu.BufferUsage.INDIRECT
                | wgpu.BufferUsage.STORAGE
                | wgpu.BufferUsage.COPY_DST
            ),
            label="indirect_args",
        )
        self._gpu_multi_readback_buf = device.create_buffer(
            size=multi_readback_bytes,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
            label="per_pixel_multi_readback",
        )
        # Phase C — dedicated buffers for the pressure-projection pass.
        # Carry the subset of active hulls that are fluid bodies with
        # ``fluid_projection_iters > 0`` so the projection workgroup count
        # equals the fluid-only count.
        self._gpu_proj_per_hull_params_buf = device.create_buffer(
            size=params_total_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="proj_per_hull_params",
        )
        self._gpu_proj_active_hulls_buf = device.create_buffer(
            size=active_total_bytes,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            label="proj_active_hulls",
        )
        self._gpu_indirect_capacity = max_active

    def _maybe_resize_indirect_for_active(self, n_active: int) -> None:
        """Grow indirect-dispatch buffers if more hulls are active than fit."""
        if n_active > self._gpu_indirect_capacity:
            # Grow with headroom (×2) to amortise future growth.
            self._gpu_resize_indirect_buffers(max_active=max(n_active, self._gpu_indirect_capacity * 2))

    def _pack_params(self, mat: "CellMaterial", dt: float) -> bytes:
        """Pack the WGSL Params uniform struct as little-endian bytes.

        Field layout must match per_pixel_sim.wgsl exactly.
        """
        cell = self.config.cell
        # Use the material's tear_strength as-is; CPU kernel does the same.
        return struct.pack(
            "<4I 36f",
            CELL_GRID_SIZE,                          # width
            CELL_GRID_SIZE,                          # height
            1 if mat.is_fluid else 0,                # is_fluid
            0,                                       # _pad0
            float(dt),                               # dt
            float(mat.E),                            # E
            float(mat.Y),                            # Y
            float(mat.brittle_modulus),              # brittle_modulus
            float(mat.density_rho),                  # rho
            float(mat.viscosity),                    # viscosity
            float(mat.torn_damping),                 # torn_damping
            float(mat.tear_strength),                # tear_strength
            float(mat.remold_rate),                  # remold_rate
            float(mat.bond_intact_threshold),        # bond_intact_threshold
            float(mat.bond_intact_slope),            # bond_intact_slope
            float(mat.brittle_damage_rate),          # brittle_damage_rate
            float(mat.brittle_tear_rate),            # brittle_tear_rate
            float(mat.brittle_bond_loss_rate),       # brittle_bond_loss_rate
            float(mat.brittle_stretch_amplification),# brittle_stretch_amplification
            float(cell.brittle_catastrophic_excess_ratio),  # WP-V
            float(cell.brittle_catastrophic_bond_floor),    # WP-V
            float(cell.brittle_catastrophic_damage_gate),   # WP-V
            float(mat.ductile_plastic_strain_rate),  # ductile_plastic_strain_rate
            float(mat.ductile_poisson_ratio),        # ductile_poisson_ratio
            float(mat.ductile_damage_rate),          # ductile_damage_rate
            float(mat.tear_growth_rate),             # tear_growth_rate
            float(mat.melt_point),                   # melt_point
            float(mat.melt_anneal_rate),             # melt_anneal_rate
            float(mat.melt_viscous_damping),         # melt_viscous_damping
            float(mat.thermal_k),                    # thermal_k
            float(mat.emissivity),                   # emissivity
            float(mat.thermal_softening_coefficient),# thermal_softening_coefficient
            float(mat.damage_weakening_coefficient), # damage_weakening_coefficient
            float(mat.heat_strain_energy_factor),    # heat_strain_energy_factor
            float(mat.fluid_pressure_coupling),      # fluid_pressure_coupling
            float(mat.fluid_pressure_smoothing),     # fluid_pressure_smoothing
            float(mat.fluid_pressure_decay),         # fluid_pressure_decay
            float(cell.silhouette_mask_threshold),   # silhouette_mask_threshold
            float(mat.E_effective),                  # E_wave (Phase D)
            float(cell.heat_damping_to_heat_factor), # heat_damping_to_heat_factor (WP-T)
        )

    def _pack_per_hull_params(
        self,
        active_slots: list[tuple[int, int, "CellMaterial"]],
        dt: float,
    ) -> bytes:
        """Pack N hulls' worth of HullParams records back-to-back.

        The on-GPU stride is ``self._gpu_params_size`` (padded to 16 B).  We
        emit one struct per active hull in the same order ``active_slots``
        is iterated; ``active_hulls[i]`` then picks the cell-pool slot for
        index ``i``.
        """
        pieces: list[bytes] = []
        for (_hid, _gid, mat) in active_slots:
            piece = self._pack_params(mat, dt)
            # ``_pack_params`` already emits exactly ``_gpu_params_size`` (148 B)
            # to match the WGSL stride; pad only if we ever bump record size.
            if len(piece) < self._gpu_params_size:
                piece = piece + b"\x00" * (self._gpu_params_size - len(piece))
            pieces.append(piece)
        return b"".join(pieces)

    def _gather_active_slots(self) -> list[tuple[int, int, "CellMaterial"]]:
        """Find all active T2 hulls (alive + cell grid + currently active).

        Phase A: this is now a single vectorised numpy mask.  The hot test
        is ``active_until_frame >= self.frame`` read directly from the
        SoA column on :class:`HullTree`, so quiescent scenes pay only a
        broadphase + boolean-AND of size ``hull_capacity`` here — no
        per-hull Python attribute access.
        """
        hulls = self.hulls
        alive = hulls._alive
        has_grid = hulls.cell_grid_id >= 0
        hot = hulls.active_until_frame >= int(self.frame)
        active_hids = np.nonzero(alive & has_grid & hot)[0]
        out: list[tuple[int, int, "CellMaterial"]] = []
        for hid_arr in active_hids:
            hid = int(hid_arr)
            mat = self._materials.get(int(hulls.material_id[hid]))
            if mat is None:
                continue
            out.append((hid, int(hulls.cell_grid_id[hid]), mat))
        return out

    def _gpu_substep(self, dt: float) -> None:
        """Run the per-pixel kernel on the GPU.

        Two paths:

        * ``indirect_dispatch=True`` (default): a single
          ``dispatch_workgroups_indirect`` call covers every active T2 hull.
          One bind group, one params upload, one dispatch, one readback.
        * ``indirect_dispatch=False``: legacy per-hull loop, one dispatch
          per hull.  Kept as a parity reference.
        """
        if not self._gpu_available:
            self._cpu_substep(dt)
            return

        self._maybe_resize_gpu_for_pool()

        active_slots = self._gather_active_slots()
        if not active_slots:
            return

        if self.config.gpu.indirect_dispatch:
            self._gpu_substep_indirect(dt, active_slots)
        else:
            self._gpu_substep_per_hull(dt, active_slots)

    # -- Phase C — GPU pressure projection ---------------------------------

    def _gpu_projection_pass(
        self,
        encoder,
        active_slots: list[tuple[int, int, "CellMaterial"]],
        dt: float,
    ) -> None:
        """Encode the divergence-free pressure-projection compute pass.

        Iterates ``active_slots`` for the subset whose material is a fluid
        with ``fluid_projection_iters > 0`` and dispatches the
        ``pressure_project.wgsl`` kernel on ``_gpu_dst_buf`` in place.

        Mirrors the CPU ``_pressure_project_arrays`` Red-Black SOR sweep
        to within 1e-3 (parity contract with the per-pixel kernel).

        No-op if no fluid hull is present, so non-fluid scenes (steel,
        stone, ...) pay zero GPU cost beyond the gather here.
        """
        # Subset of active hulls eligible for projection.
        fluid_slots: list[tuple[int, int, "CellMaterial"]] = [
            (hid, gid, mat) for (hid, gid, mat) in active_slots
            if mat.is_fluid and int(getattr(mat, "fluid_projection_iters", 0)) > 0
        ]
        if not fluid_slots:
            return  # gate: no dispatch when no fluid bodies need projection

        wgpu = self._wgpu
        device = self._gpu_device
        queue = self._gpu_queue
        n_fluid = len(fluid_slots)
        # Ensure dedicated buffers are sized for at least n_fluid; reuse the
        # per-pixel-sim capacity since both grow together.
        self._maybe_resize_indirect_for_active(n_fluid)

        # All fluid hulls in a dispatch group must share the same
        # ``fluid_projection_iters`` AND the same ``use_multigrid`` flag
        # so the K loop / V-cycle path inside the shader is uniform.
        # In practice every fluid in a scene shares the default (water:
        # iters=12, use_multigrid=True), so this typically collapses to
        # one dispatch.
        iters_groups: dict[
            tuple[int, int], list[tuple[int, int, "CellMaterial"]]
        ] = {}
        for slot in fluid_slots:
            iters = int(slot[2].fluid_projection_iters)
            use_mg = 1 if bool(getattr(slot[2], "use_multigrid", False)) else 0
            iters_groups.setdefault((iters, use_mg), []).append(slot)

        for (iters, use_mg), group in iters_groups.items():
            n_group = len(group)
            # Pack params + active-hull indices for this group.
            params_blob = self._pack_per_hull_params(group, dt)
            queue.write_buffer(
                self._gpu_proj_per_hull_params_buf, 0, params_blob,
            )
            active_indices = np.array(
                [gid for (_hid, gid, _mat) in group], dtype=np.uint32,
            )
            if active_indices.size < self._gpu_indirect_capacity:
                pad = np.zeros(
                    self._gpu_indirect_capacity - active_indices.size,
                    dtype=np.uint32,
                )
                active_indices = np.concatenate([active_indices, pad])
            queue.write_buffer(
                self._gpu_proj_active_hulls_buf, 0, active_indices.tobytes(),
            )

            # Write the projection-config uniform.
            #   iters         — single-grid SOR iter count (also used as
            #                   the source of n_cycles for V-cycle).
            #   use_multigrid — 1 ⇒ shader takes the V-cycle path.
            #   n_cycles      — number of V-cycles to run; matches CPU
            #                   ``max(1, iters // 4)`` in pressure_multigrid.
            n_cycles = max(1, iters // 4) if use_mg else 0
            cfg_blob = struct.pack(
                "<4I", int(iters), int(use_mg), int(n_cycles), 0,
            )
            queue.write_buffer(self._gpu_proj_cfg_buf, 0, cfg_blob)

            bind_group = device.create_bind_group(
                layout=self._gpu_proj_bind_layout,
                entries=[
                    {"binding": 0, "resource": {
                        "buffer": self._gpu_proj_per_hull_params_buf,
                        "offset": 0,
                        "size": self._gpu_indirect_capacity * self._gpu_params_size,
                    }},
                    {"binding": 1, "resource": {"buffer": self._gpu_dst_buf}},
                    {"binding": 2, "resource": {
                        "buffer": self._gpu_proj_active_hulls_buf,
                        "offset": 0,
                        "size": max(4, self._gpu_indirect_capacity * 4),
                    }},
                    {"binding": 3, "resource": {
                        "buffer": self._gpu_proj_cfg_buf,
                        "offset": 0,
                        "size": 16,
                    }},
                ],
            )
            cp = encoder.begin_compute_pass(label="pressure_project_pass")
            cp.set_pipeline(self._gpu_proj_pipeline)
            cp.set_bind_group(0, bind_group)
            # One workgroup per fluid hull; each workgroup covers a 32×32 grid.
            cp.dispatch_workgroups(1, 1, n_group)
            cp.end()

    # -- Phase B — persistent residency upload helper -----------------------

    def _gpu_upload_dirty_slots(self, cells_host: np.ndarray) -> int:
        """Upload only the slots flagged as dirty on the cell pool.

        Coalesces contiguous dirty slot indices into a single
        ``write_buffer`` call (one device-side memcpy per run) so the
        bytes-per-substep on a settled scene drops from ``capacity *
        64 KB`` to ``len(dirty) * 64 KB``.

        Returns the number of bytes uploaded — handy for tests and
        diagnostics.  Clears the dirty set on the pool by promoting
        each uploaded slot to ``gpu_resident``.
        """
        pool = self.cell_pool
        queue = self._gpu_queue
        dirty = pool.dirty_slots()
        if not dirty:
            return 0
        # Sort once so we can detect contiguous runs.
        sorted_slots = sorted(dirty)
        slot_bytes = self._SLOT_BYTES
        # Sanity: cap each upload at the actual GPU buffer capacity in
        # case the pool grew but the GPU buffers haven't been resized
        # yet (callers should have resized first; this is belt-and-
        # braces).
        cap = self._gpu_buf_capacity
        total_bytes = 0
        run_start = sorted_slots[0]
        run_end = run_start  # inclusive
        def _flush(start: int, end: int) -> int:
            if start >= cap:
                return 0
            end_clipped = min(end, cap - 1)
            n = end_clipped - start + 1
            blob = cells_host[start : start + n].tobytes()
            queue.write_buffer(self._gpu_src_buf, start * slot_bytes, blob)
            return n * slot_bytes
        for slot in sorted_slots[1:]:
            if slot == run_end + 1:
                run_end = slot
            else:
                total_bytes += _flush(run_start, run_end)
                run_start = run_end = slot
        total_bytes += _flush(run_start, run_end)
        for slot in sorted_slots:
            pool.mark_gpu_resident(slot)
        return total_bytes

    def _gpu_substep_indirect(
        self,
        dt: float,
        active_slots: list[tuple[int, int, "CellMaterial"]],
    ) -> None:
        """Single indirect dispatch over every active hull."""
        wgpu = self._wgpu
        device = self._gpu_device
        queue = self._gpu_queue

        n_active = len(active_slots)
        self._maybe_resize_indirect_for_active(n_active)

        # Phase B — persistent GPU residency.  When enabled, only re-
        # upload slots the CPU has dirtied since the last dispatch; the
        # rest are already correct on the device from a previous step.
        # When disabled, fall back to the legacy full-pool blast so any
        # CPU writer that forgets to call ``mark_dirty`` can't desync the
        # GPU state.  See ``docs/next_phase_plan.md`` §3.2.B.
        cells_host = self.cell_pool._cells
        if not cells_host.flags["C_CONTIGUOUS"]:
            cells_host = np.ascontiguousarray(cells_host)
        if self.config.gpu.persistent_residency:
            self._gpu_upload_dirty_slots(cells_host)
        else:
            queue.write_buffer(self._gpu_src_buf, 0, cells_host.tobytes())

        # Pack + upload per-hull params, active-hull indices, indirect args.
        params_blob = self._pack_per_hull_params(active_slots, dt)
        queue.write_buffer(self._gpu_per_hull_params_buf, 0, params_blob)

        active_indices = np.array(
            [gid for (_hid, gid, _mat) in active_slots], dtype=np.uint32
        )
        # Pad to capacity so write_buffer size matches the buffer's binding
        # size (wgpu requires the storage binding to be fully addressable).
        if active_indices.size < self._gpu_indirect_capacity:
            pad = np.zeros(self._gpu_indirect_capacity - active_indices.size, dtype=np.uint32)
            active_indices = np.concatenate([active_indices, pad])
        queue.write_buffer(self._gpu_active_hulls_buf, 0, active_indices.tobytes())

        wg = max(1, CELL_GRID_SIZE // 8)
        indirect_args = np.array(
            [wg, wg, n_active, 0], dtype=np.uint32
        ).tobytes()
        queue.write_buffer(self._gpu_indirect_args_buf, 0, indirect_args)

        bind_group = device.create_bind_group(
            layout=self._gpu_bind_layout,
            entries=[
                {"binding": 0, "resource": {
                    "buffer": self._gpu_per_hull_params_buf,
                    "offset": 0,
                    "size": self._gpu_indirect_capacity * self._gpu_params_size,
                }},
                {"binding": 1, "resource": {"buffer": self._gpu_src_buf}},
                {"binding": 2, "resource": {"buffer": self._gpu_dst_buf}},
                {"binding": 3, "resource": {
                    "buffer": self._gpu_active_hulls_buf,
                    "offset": 0,
                    "size": max(4, self._gpu_indirect_capacity * 4),
                }},
            ],
        )

        encoder = device.create_command_encoder(label="per_pixel_substep_indirect")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(self._gpu_pipeline)
        cp.set_bind_group(0, bind_group)
        cp.dispatch_workgroups_indirect(self._gpu_indirect_args_buf, 0)
        cp.end()

        # Phase C — divergence-free pressure projection over fluid hulls
        # only.  Reads/writes ``_gpu_dst_buf`` in place between the
        # per-pixel kernel and the readback copies, so the values pulled
        # back to host are already projection-corrected.
        self._gpu_projection_pass(encoder, active_slots, dt)

        # Copy each active slot's dst into a contiguous region of the
        # multi-readback buffer so we can map ONCE and demultiplex on CPU.
        for i, (_hid, gid, _mat) in enumerate(active_slots):
            encoder.copy_buffer_to_buffer(
                self._gpu_dst_buf, gid * self._SLOT_BYTES,
                self._gpu_multi_readback_buf, i * self._SLOT_BYTES,
                self._SLOT_BYTES,
            )
        queue.submit([encoder.finish()])

        # One map_sync for the whole batch.
        readback_bytes = n_active * self._SLOT_BYTES
        self._gpu_multi_readback_buf.map_sync(wgpu.MapMode.READ)
        try:
            raw = self._gpu_multi_readback_buf.read_mapped(0, readback_bytes)
            arr = np.frombuffer(bytes(raw), dtype=np.float32).reshape(
                n_active, CELL_GRID_SIZE, CELL_GRID_SIZE, 16
            )
            for i, (_hid, gid, _mat) in enumerate(active_slots):
                self.cell_pool._cells[gid] = arr[i]
                # Phase B — host slot just got rewritten from the GPU
                # dst buffer.  Next substep's src buffer needs that data
                # so re-flag as dirty for the next dispatch.  (We don't
                # try to short-circuit "copy dst → src" on the GPU side
                # in v1: the device-local memcpy would save host
                # bandwidth, but conservation tests / readback consumers
                # also rely on the host view being canonical.)
                if self.config.gpu.persistent_residency:
                    self.cell_pool.mark_dirty(gid)
        finally:
            self._gpu_multi_readback_buf.unmap()

    def _gpu_substep_per_hull(
        self,
        dt: float,
        active_slots: list[tuple[int, int, "CellMaterial"]],
    ) -> None:
        """Legacy: one dispatch per hull.  Kept for parity / fallback.

        Uses the SAME WGSL shader as the indirect path, but with a 1-element
        params + active-hulls window so ``workgroup_id.z == 0`` picks the
        right slot.
        """
        wgpu = self._wgpu
        device = self._gpu_device
        queue = self._gpu_queue

        # Reuse the indirect-buffer slot with max_active=1 (resize down to
        # exactly 1 hull if currently larger to keep bind-group bindings
        # consistent — but we don't actually need to: a 1-element write is
        # fine, the shader only reads index 0).
        self._maybe_resize_indirect_for_active(1)

        # Phase B — same persistent-residency gate as the indirect path.
        cells_host = self.cell_pool._cells
        if not cells_host.flags["C_CONTIGUOUS"]:
            cells_host = np.ascontiguousarray(cells_host)
        if self.config.gpu.persistent_residency:
            self._gpu_upload_dirty_slots(cells_host)
        else:
            queue.write_buffer(self._gpu_src_buf, 0, cells_host.tobytes())

        wg = max(1, CELL_GRID_SIZE // 8)

        for (_hid, gid, mat) in active_slots:
            # 1-hull window.
            params_blob = self._pack_params(mat, dt)
            pad = self._gpu_params_size - len(params_blob)
            if pad > 0:
                params_blob = params_blob + b"\x00" * pad
            queue.write_buffer(self._gpu_per_hull_params_buf, 0, params_blob)
            active_indices = np.array([gid], dtype=np.uint32)
            if active_indices.size < self._gpu_indirect_capacity:
                pad_n = self._gpu_indirect_capacity - active_indices.size
                active_indices = np.concatenate([active_indices, np.zeros(pad_n, dtype=np.uint32)])
            queue.write_buffer(self._gpu_active_hulls_buf, 0, active_indices.tobytes())

            bind_group = device.create_bind_group(
                layout=self._gpu_bind_layout,
                entries=[
                    {"binding": 0, "resource": {
                        "buffer": self._gpu_per_hull_params_buf,
                        "offset": 0,
                        "size": self._gpu_indirect_capacity * self._gpu_params_size,
                    }},
                    {"binding": 1, "resource": {"buffer": self._gpu_src_buf}},
                    {"binding": 2, "resource": {"buffer": self._gpu_dst_buf}},
                    {"binding": 3, "resource": {
                        "buffer": self._gpu_active_hulls_buf,
                        "offset": 0,
                        "size": max(4, self._gpu_indirect_capacity * 4),
                    }},
                ],
            )

            encoder = device.create_command_encoder(label="per_pixel_substep_per_hull")
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(self._gpu_pipeline)
            cp.set_bind_group(0, bind_group)
            cp.dispatch_workgroups(wg, wg, 1)
            cp.end()

            # Phase C — pressure projection on this single hull (if it is
            # a fluid with iters > 0).
            self._gpu_projection_pass(encoder, [(_hid, gid, mat)], dt)

            encoder.copy_buffer_to_buffer(
                self._gpu_dst_buf, gid * self._SLOT_BYTES,
                self._gpu_readback_buf, 0, self._SLOT_BYTES,
            )
            queue.submit([encoder.finish()])

            self._gpu_readback_buf.map_sync(wgpu.MapMode.READ)
            try:
                raw = self._gpu_readback_buf.read_mapped(0, self._SLOT_BYTES)
                arr = np.frombuffer(bytes(raw), dtype=np.float32).reshape(
                    CELL_GRID_SIZE, CELL_GRID_SIZE, 16
                )
                self.cell_pool._cells[gid] = arr
                # Phase B — host slot rewritten from GPU; src needs the
                # new bytes on next dispatch.  See ``_gpu_substep_indirect``.
                if self.config.gpu.persistent_residency:
                    self.cell_pool.mark_dirty(gid)
            finally:
                self._gpu_readback_buf.unmap()

    # -- conservation totals (for tests) ------------------------------------

    def conservation_totals(self) -> dict[str, float]:
        """Snapshot every conserved quantity in the system.

        Tracks the *full energy budget*:

            E_total = Σ KE_rigid + Σ KE_cells_local + Σ heat + Σ U_strain + Σ PE_grav

        Mass and momentum are computed from the rigid bus only — the cell
        velocity field is by architectural invariant zero-mean in body-local
        frame, so it doesn't contribute to system Σp.  Strain energy is
        ``½ E (ε_xx² + ε_yy² + 2 ε_xy²)`` integrated over each body's cells.
        """
        total_mass_cells = 0.0
        total_heat = 0.0
        total_ke_cells = 0.0
        total_strain = 0.0
        total_ke_rigid = 0.0
        total_pe_grav = 0.0
        total_px_rigid = 0.0
        total_py_rigid = 0.0
        g_y = self.config.world.gravity[1]
        for body in self.bodies:
            hid = body.root_hull_id
            cs_x = float(self.hulls.cell_size_x[hid])
            cs_y = float(self.hulls.cell_size_y[hid])
            cell_area = cs_x * cs_y
            m = body.mass
            vx, vy = body.velocity
            if not body.fixed:
                total_ke_rigid += 0.5 * m * (vx * vx + vy * vy)
                total_pe_grav += -m * g_y * body.position[1]
                total_px_rigid += m * vx
                total_py_rigid += m * vy
            c = body.cells
            if c is None:
                continue
            rho = body.material.density_rho
            d = c[..., _IDX_DENSITY].astype(np.float64)
            cell_mass = rho * d * cell_area
            total_mass_cells += float(cell_mass.sum())
            cvx = c[..., _IDX_V_X].astype(np.float64)
            cvy = c[..., _IDX_V_Y].astype(np.float64)
            total_ke_cells += float((0.5 * cell_mass * (cvx * cvx + cvy * cvy)).sum())
            total_heat += float(c[..., _IDX_HEAT].sum())
            # Strain energy from displacement field.  ε from central
            # differences of u, then U = ½ E (ε² with perm-strain subtracted).
            ux = c[..., _IDX_U_X].astype(np.float64)
            uy = c[..., _IDX_U_Y].astype(np.float64)
            eps_xx = (np.roll(ux, -1, axis=1) - np.roll(ux, 1, axis=1)) * 0.5
            eps_yy = (np.roll(uy, -1, axis=0) - np.roll(uy, 1, axis=0)) * 0.5
            eps_xy = (
                (np.roll(uy, -1, axis=1) - np.roll(uy, 1, axis=1))
                + (np.roll(ux, -1, axis=0) - np.roll(ux, 1, axis=0))
            ) * 0.25
            eps_el_xx = eps_xx - c[..., _IDX_PERM_XX].astype(np.float64)
            eps_el_yy = eps_yy - c[..., _IDX_PERM_YY].astype(np.float64)
            eps_el_xy = eps_xy - c[..., _IDX_PERM_XY].astype(np.float64)
            U = 0.5 * body.material.E * (
                eps_el_xx * eps_el_xx + eps_el_yy * eps_el_yy
                + 2.0 * eps_el_xy * eps_el_xy
            ) * d * cell_area
            total_strain += float(U.sum())

        return {
            "mass_cells": total_mass_cells,
            "p_rigid_x": total_px_rigid,
            "p_rigid_y": total_py_rigid,
            "ke_rigid": total_ke_rigid,
            "ke_cells": total_ke_cells,
            "heat": total_heat,
            "strain": total_strain,
            "pe_grav": total_pe_grav,
            "energy_total": total_ke_rigid + total_ke_cells
                + total_heat + total_strain + total_pe_grav,
            # Backward-compat alias kept by tests.
            "mass": total_mass_cells,
            "momentum_x": total_px_rigid,
            "momentum_y": total_py_rigid,
        }

    def iter_bodies(self) -> Iterable[PhysicsBody]:
        return iter(self.bodies)
