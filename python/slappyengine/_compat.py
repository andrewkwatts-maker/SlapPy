"""slappyengine._compat — Phase D back-compat surface.

Hosts the small set of public-surface symbols that the legacy
``deform_modes`` / ``deform_controller`` / ``deform_zones`` modules used
to expose. Owning them here means the top-level ``slappyengine``
package's ``_LAZY_MAP`` no longer has to import the doomed modules just
to satisfy a ``hasattr(slappyengine, "MaterialPreset")`` style probe
from the multi-game compat tripwire tests.

This file is **read-only stable**: each symbol is a self-contained
back-compat surface; none of them pull in any other slappyengine
module. Deleting ``deform_modes.py`` / ``deform_controller.py`` /
``deform_zones.py`` in the next Phase D commit must NOT change the
behaviour of any symbol exported here.

Scope (per ``docs/phase_d_strip_plan_2026_05_31.md`` §(b)):

* ``MaterialPreset`` — enum, copied from ``deform_modes`` so the
  multi-game tripwire test (`test_game_compat_tripwire`) keeps
  resolving the name. Production code in ``deform_panel.py`` and
  similar legacy editor surfaces still imports from
  ``slappyengine.deform_modes`` directly — those imports keep working
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
* ``ZoneMap`` — alias for :class:`slappyengine.zones.ZoneManager`.
  This is the *one* symbol with a real replacement; the rest of the
  rebuild already canonicalises on ``ZoneManager``. The alias keeps
  game code (Bullet Strata's drone head/torso/legs zones) importing
  ``slappyengine.ZoneMap`` without changes.
"""
from __future__ import annotations

import enum


__all__ = [
    "MaterialPreset",
    "CrackMode",
    "SimFrequencyBudget",
    "SimState",
    "DeformController",
    "ZoneMap",
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
# ZoneMap — alias for the canonical ZoneManager
# ---------------------------------------------------------------------------


def _zone_map():
    """Lazy import the canonical ZoneManager.

    Kept lazy so that *importing* ``slappyengine._compat`` doesn't pull
    in the zones subpackage. The alias is resolved on first attribute
    access via the module-level ``__getattr__`` below.
    """
    from slappyengine.zones import ZoneManager
    return ZoneManager


def __getattr__(name: str):
    if name == "ZoneMap":
        cls = _zone_map()
        globals()["ZoneMap"] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
