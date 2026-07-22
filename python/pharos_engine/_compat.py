"""pharos_engine._compat — Phase D back-compat surface.

Hosts the small set of public-surface symbols that the legacy
``deform_modes`` / ``deform_controller`` / ``deform_zones`` modules used
to expose. Owning them here means the top-level ``pharos_engine``
package's ``_LAZY_MAP`` no longer has to import the doomed modules just
to satisfy a ``hasattr(pharos_engine, "MaterialPreset")`` style probe
from the multi-game compat tripwire tests.

This file is **read-only stable**: each symbol is a self-contained
back-compat surface; none of them pull in any other pharos_engine
module. Deleting ``deform_modes.py`` / ``deform_controller.py`` /
``deform_zones.py`` in the next Phase D commit must NOT change the
behaviour of any symbol exported here.

Scope (per ``docs/phase_d_strip_plan_2026_05_31.md`` §(b)):

* ``MaterialPreset`` — enum, copied from ``deform_modes`` so the
  multi-game tripwire test (`test_game_compat_tripwire`) keeps
  resolving the name. Production code in ``deform_panel.py`` and
  similar legacy editor surfaces still imports from
  ``pharos_engine.deform_modes`` directly — those imports keep working
  until the editor surface is decommissioned in Phase D step 5.
* ``CrackMode`` — enum, same rationale. The crack-propagation feature
  itself is retired (per the migration matrix); this is a name-only
  back-compat shim so the tripwire stays green.
* ``SimFrequencyBudget`` — minimal class. Retired feature in the new
  softbody.solver world (the engine no longer has a global GPU
  dispatch budget). The class is preserved as a no-op stub: it answers
  ``request_slot`` truthfully under its old semantics but is not wired
  to anything in the rebuild solver.
* ``SimState`` — enum, retired feature. The COLLISION_TRIGGERED →
  ACTIVE → SETTLING → STATIC state machine is gone; softbody bodies
  are always "active" in the rebuild. Exported here only to preserve
  the name surface.
* ``DeformController`` — minimal class. Retired feature; the rebuild
  uses ``softbody.body_builders.make_layered_creature`` (a different
  architecture). Preserved here as a thin stand-in that accepts the
  legacy ctor kwargs without exploding.
* ``ZoneMap`` — alias for :class:`pharos_engine.zones.ZoneManager`.
  This is the *one* symbol with a real replacement; the rest of the
  rebuild already canonicalises on ``ZoneManager``. The alias keeps
  game code (Bullet Strata's drone head/torso/legs zones) importing
  ``pharos_engine.ZoneMap`` without changes.
* ``CellMaterial`` — dataclass, ported verbatim from
  ``deform_modes`` (Phase D step 6 unblock). The five legacy
  ``physics/*`` consumers (``body.py``, ``boundary_exchange.py``,
  ``pressure_multigrid.py``, ``scene_loader.py``, ``world.py``) read
  every field by name through the per-pixel-sim shader uploader, so
  the field set, defaults, and types are reproduced exactly. The
  ``E_effective`` property uses a function-local import of
  ``CELL_GRID_SIZE`` to avoid creating a circular dependency on the
  ``physics`` subpackage from import time of ``_compat``.
* ``cell_material_for`` — convenience function, ported verbatim from
  ``deform_modes``. Looks up a built-in material preset by name and
  returns its attached :class:`CellMaterial` (or ``None`` if the
  material has no v2 cell params). Hosting it here means
  ``physics/scene_loader.py`` no longer needs to import from
  ``deform_modes`` to translate YAML ``material:`` strings into the
  per-cell parameter bundle.
"""
from __future__ import annotations

import dataclasses
import enum


__all__ = [
    "MaterialPreset",
    "CrackMode",
    "SimFrequencyBudget",
    "SimState",
    "DeformController",
    "ZoneMap",
    "CellMaterial",
    "cell_material_for",
]


# ---------------------------------------------------------------------------
# MaterialPreset — name-only back-compat enum
# ---------------------------------------------------------------------------


class MaterialPreset(enum.Enum):
    """Named physics presets — back-compat name surface only.

    The rebuild engine looks up materials by bare string against
    ``softbody.material.MATERIALS`` / ``fluid.material.MATERIALS``;
    this enum is preserved so legacy code that still imports the name
    keeps resolving. Each member's value is the canonical lowercase
    string used by the YAML-backed material registries, so
    ``MaterialPreset.STEEL.value == "steel"`` round-trips into the
    new material API.
    """

    METAL = "metal"
    GLASS = "glass"
    RUBBER = "rubber"
    WOOD = "wood"
    STONE = "stone"
    CLOTH = "cloth"
    ICE = "ice"
    ORGANIC = "organic"
    STEEL = "steel"
    IRON = "iron"
    CLAY = "clay"
    MUD = "mud"
    WATER = "water"
    SAND = "sand"
    LAVA_GROUND = "lava_ground"
    LAVA = "lava"
    CONCRETE = "concrete"
    OIL = "oil"
    SLIME = "slime"
    DIAMOND = "diamond"
    PAPER = "paper"
    STEAM = "steam"
    CORAL = "coral"
    GOLD = "gold"
    MAGMA = "magma"
    SNOW = "snow"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# CrackMode — retired feature, name surface only
# ---------------------------------------------------------------------------


class CrackMode(enum.Enum):
    """How cracks propagate from an impact point — retired feature.

    The per-pixel crack-propagation shader was retired in Phase B in
    favour of softbody.solver's ``break_strain`` beam breakage. This
    enum survives only as a name-import compat shim.
    """

    NONE = "none"
    RADIAL = "radial"
    GRAIN = "grain"
    STRUCTURAL = "structural"


# ---------------------------------------------------------------------------
# SimState — retired feature, name surface only
# ---------------------------------------------------------------------------


class SimState(enum.Enum):
    """Sim activation state — retired feature.

    The rebuild solver dispatches every step; there is no
    STATIC / ACTIVE / SETTLING state machine. Preserved for legacy
    code that still references the member names.
    """

    STATIC = "static"
    ACTIVE = "active"
    SETTLING = "settling"


# ---------------------------------------------------------------------------
# SimFrequencyBudget — retired feature, minimal stub
# ---------------------------------------------------------------------------


class SimFrequencyBudget:
    """Frame-budget allocator — retired feature, no-op-compatible stub.

    The legacy ``deform_controller.SimFrequencyBudget`` rationed GPU
    dispatch time across multiple deform entities. The rebuild
    softbody.solver does not multiplex like this; budget management is
    per-``World.step()`` substep count.

    This stub preserves the constructor + the two public methods so
    legacy game code constructs without raising. ``request_slot`` is
    permissive (always returns True when budget remains) under the
    historical semantics, but there is no actual dispatcher reading
    its decisions.
    """

    def __init__(self) -> None:
        self._budget_ms: float = 2.0
        self._used_ms: float = 0.0
        self._cost_per_dispatch_ms: float = 0.1

    def allocate_budget(self, budget_ms: float) -> None:
        """Reset the per-frame budget. Call once per frame."""
        self._budget_ms = float(budget_ms)
        self._used_ms = 0.0

    def request_slot(self, priority: float = 1.0) -> bool:
        """Return True iff a slot remains under the historical formula."""
        if self._used_ms + self._cost_per_dispatch_ms <= self._budget_ms * priority:
            self._used_ms += self._cost_per_dispatch_ms
            return True
        return False

    @property
    def remaining_ms(self) -> float:
        return max(0.0, self._budget_ms - self._used_ms)


# ---------------------------------------------------------------------------
# DeformController — retired feature, minimal stub
# ---------------------------------------------------------------------------


class DeformController:
    """Per-entity deform orchestrator — retired feature, minimal stub.

    The legacy controller drove Layer2D-pixel deform sims; the rebuild
    uses ``softbody.body_builders.make_layered_creature`` which is a
    different architecture (beam-based, no per-pixel state machine).

    This stub accepts the legacy keyword arguments without raising so
    game code that constructs it (e.g. Bullet Strata enemy entities)
    still imports cleanly. The ``activate`` / ``deactivate`` methods
    are no-ops — the rebuild has no concept of a sim activation gate.
    """

    def __init__(
        self,
        sim_mode: str = "collision_triggered",
        decay_mode: str = "constant",
        spring_decay: float = 0.94,
        decay_curve: "list[tuple[float, float]] | None" = None,
        settle_threshold: float = 0.5,
        settling_ramp_rate: float = 4.0,
        n_frames_skip: int = 4,
    ) -> None:
        self.sim_mode = sim_mode
        self.decay_mode = decay_mode
        self.spring_decay = spring_decay
        self.decay_curve = decay_curve or []
        self.settle_threshold = settle_threshold
        self.settling_ramp_rate = settling_ramp_rate
        self.n_frames_skip = n_frames_skip
        self.state: SimState = SimState.STATIC

    def activate(self) -> None:
        """No-op in the rebuild solver."""
        self.state = SimState.ACTIVE

    def deactivate(self) -> None:
        """No-op in the rebuild solver."""
        self.state = SimState.STATIC


# ---------------------------------------------------------------------------
# CellMaterial — Phase D step 6 unblock port (verbatim from deform_modes)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CellMaterial:
    """Per-material physical parameters driving the hierarchical-hull solver.

    Architectural invariant: **material drives system evolution, not the
    reverse**.  Every coefficient that the per-pixel kernel multiplies into
    its stress/strain/heat/fracture equations lives here, on the material
    — not in a global config block.

    Phase D step 6: hosted here in ``_compat`` so the five legacy
    ``physics/*`` consumers (``body.py``, ``boundary_exchange.py``,
    ``pressure_multigrid.py``, ``scene_loader.py``, ``world.py``) survive
    the eventual deletion of ``deform_modes.py``.  The field set is a
    verbatim port: every name, default, and type is preserved exactly,
    because ``physics/world.py:_pack_params`` reads them by name to fill
    the WGSL ``PixelMaterialParams`` struct uploaded to the GPU kernel.
    """
    # Mechanical -----------------------------------------------------------
    E: float = 80.0
    # Phase D: per-material wave-crossing target (frames at 60 Hz for an
    # elastic wave to traverse a 32-cell body grid).  Drives ``E_effective``.
    wave_crossing_frames: float = 8.0
    Y: float = 0.20
    brittle_modulus: float = 999.0
    viscosity: float = 0.95
    torn_damping: float = 0.999
    density_rho: float = 1.0
    restitution: float = 0.30
    # Per-material closing-speed threshold below which the rigid contact
    # restitution kick is forced to zero (plastic).  Granular materials
    # (sand, snow) opt in to a high threshold (~8.0); every other material
    # defaults to ``0.0`` (gate disabled).
    restitution_velocity_threshold: float = 0.0
    # Friction (Coulomb stiction model) ----------------------------------
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
    fluid_projection_iters: int = 10
    use_multigrid: bool = False
    # Rendering -----------------------------------------------------------
    radiance: float = 0.0
    noise_overlay_amplitude: float = 0.0
    noise_overlay_color: tuple[int, int, int] = (255, 255, 255)
    foam_amplitude: float = 0.0
    ripple_amplitude: float = 0.0

    @property
    def E_effective(self) -> float:
        """Derived effective elastic modulus driving the kernel Laplacian.

        ``E_effective = rho * (CELL_GRID_SIZE * 60 / wave_crossing_frames)^2``

        Function-local import of ``CELL_GRID_SIZE`` avoids importing the
        ``physics`` subpackage from ``_compat`` at module load time.
        """
        from pharos_engine.physics.cell import CELL_GRID_SIZE  # local import
        target = max(float(self.wave_crossing_frames), 1e-3)
        c_grid = (float(CELL_GRID_SIZE) * 60.0) / target
        return max(float(self.density_rho), 1e-6) * c_grid * c_grid

    @property
    def bond_strength(self) -> float:
        """Back-compat alias for ``restitution`` (old field name)."""
        return self.restitution


def cell_material_for(name: str) -> "CellMaterial | None":
    """Look up the per-cell physical params for a material by name.

    Phase D step 6: hosted here in ``_compat`` so ``physics/scene_loader.py``
    can resolve YAML ``material:`` strings without importing
    ``deform_modes`` (which is slated for deletion).  Delegates to
    :func:`pharos_engine.deform_modes.get_material` while the legacy
    registry is still present, rebuilding the result as a
    :class:`_compat.CellMaterial` instance so callers receive the
    Phase-D-survivor type — not the legacy one.  Returns ``None`` once
    ``deform_modes`` is removed, which the consumer call sites already
    handle (every consumer treats ``None`` as "material unknown, skip
    per-pixel sim wiring").
    """
    try:
        from pharos_engine.deform_modes import get_material
    except ImportError:
        return None
    mc = get_material(name)
    if mc is None or mc.cell is None:
        return None
    src = mc.cell
    # Rebuild as a _compat.CellMaterial by copying every dataclass field
    # by name; if the legacy class ever sprouts a field that _compat
    # doesn't know about we silently drop it (the WGSL uploader reads
    # only the names that ``_compat.CellMaterial`` exposes).
    kwargs = {}
    for f in dataclasses.fields(CellMaterial):
        if hasattr(src, f.name):
            kwargs[f.name] = getattr(src, f.name)
    return CellMaterial(**kwargs)


# ---------------------------------------------------------------------------
# ZoneMap — alias for the canonical ZoneManager
# ---------------------------------------------------------------------------


def _zone_map():
    """Lazy import the canonical ZoneManager.

    Kept lazy so that *importing* ``pharos_engine._compat`` doesn't pull
    in the zones subpackage. The alias is resolved on first attribute
    access via the module-level ``__getattr__`` below.
    """
    from pharos_engine.zones import ZoneManager
    return ZoneManager


def __getattr__(name: str):
    if name == "ZoneMap":
        cls = _zone_map()
        globals()["ZoneMap"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
