"""Memory budget enforcement for :class:`PhysicsWorld`.

This module is imported by :mod:`pharos_engine.physics.__init__` and, as a
side effect of that import, wraps
:func:`pharos_engine.physics.world.load_physics_config` so the returned
:class:`PhysicsYaml` instance carries an extra ``memory`` attribute
populated from the YAML ``memory:`` section.  We do this here (rather
than editing ``world.py``) so the memory budget can ship as a fully
self-contained add-on.


A scene that runs unattended can quietly allocate gigabytes of cell-grid
storage (each :class:`~pharos_engine.physics.cell.CellGridPool` slot is 64 KB,
each rigid body carries ~96 B of state, and particle systems can scale into
the hundreds of thousands).  :class:`MemoryBudget` wraps those three knobs
in a single per-frame ``check()`` call that warns at a configurable
fraction of capacity and raises :class:`MemoryBudgetExceeded` when a hard
cap is breached.

The memory totals reported here are *approximations* — they are derived
from the documented per-slot/per-body footprint of the simulator, not from
:func:`sys.getsizeof`.  See :data:`BYTES_PER_BODY`, :data:`BYTES_PER_CELL_SLOT`,
and :data:`BYTES_PER_PARTICLE` for the constants in use.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

# -- Approximate per-resource memory cost ------------------------------------
#
# These are documented constants, not measurements from ``sys.getsizeof``.
# Update them if the underlying struct layouts change materially.

# PhysicsBody carries roughly: 2x float64 position (16), 2x float64 velocity
# (16), float64 angle + angular_velocity (16), mass + inertia (16), plus
# per-body Python object overhead and a handful of small fields.  ~96 bytes
# is a deliberately rough estimate of the *dense numeric* footprint, which
# is what the budget exists to bound.
BYTES_PER_BODY: int = 96

# One CellGridPool slot = 32 * 32 cells * 16 float32 channels * 4 bytes = 64 KB.
# See ``pharos_engine.physics.cell.CellGridPool`` for the canonical layout.
BYTES_PER_CELL_SLOT: int = 64 * 1024

# Per-particle footprint: position (8B), velocity (8B), color (16B), lifetime,
# size, etc.  ~64 bytes is a documented estimate of the dense buffer cost.
BYTES_PER_PARTICLE: int = 64


# -- Configuration -----------------------------------------------------------

@dataclass
class MemoryBudgetConfig:
    """Per-resource caps that :class:`MemoryBudget` enforces.

    The defaults below cap a single scene at roughly:
        4096 bodies      * 96 B   = ~384 KB
        1024 cell slots  * 64 KB  = 64 MB
        65536 particles  * 64 B   = ~4 MB
        ─────────────────────────────────
        Total            ≈ 68 MB hard ceiling.

    ``warn_at_fraction`` is the threshold at which :meth:`MemoryBudget.check`
    emits a (rate-limited) :class:`UserWarning` for any resource whose
    usage has crossed ``cap * warn_at_fraction`` but not yet exceeded the cap.
    """

    max_bodies: int = 4096
    max_cell_pool_slots: int = 1024  # each is 64 KB -> 64 MB max
    max_particle_count: int = 65536
    warn_at_fraction: float = 0.80   # warn when reaching 80% of any cap


# -- Exception ---------------------------------------------------------------

class MemoryBudgetExceeded(MemoryError):
    """Raised by :meth:`MemoryBudget.check` when a hard cap is exceeded.

    Subclasses :class:`MemoryError` so callers that already catch the
    standard out-of-memory hierarchy will see budget breaches as well.
    """


# -- Tracked resource names --------------------------------------------------

_RESOURCE_BODIES = "n_bodies"
_RESOURCE_CELLS = "n_cell_pool_slots"
_RESOURCE_PARTICLES = "particles"

# How many frames to suppress repeat warnings for the same resource.
# Without this, an 80%-full pool would emit one warning per frame for the
# rest of the run.
_WARNING_RATE_LIMIT_FRAMES = 120  # ~2 seconds at 60 Hz


# -- Helpers -----------------------------------------------------------------

def _resource_caps(config: MemoryBudgetConfig) -> dict[str, int]:
    """Return the hard cap for each tracked resource."""
    return {
        _RESOURCE_BODIES: int(config.max_bodies),
        _RESOURCE_CELLS: int(config.max_cell_pool_slots),
        _RESOURCE_PARTICLES: int(config.max_particle_count),
    }


def _bytes_per_unit() -> dict[str, int]:
    """Return the approximate per-unit byte cost for each tracked resource."""
    return {
        _RESOURCE_BODIES: BYTES_PER_BODY,
        _RESOURCE_CELLS: BYTES_PER_CELL_SLOT,
        _RESOURCE_PARTICLES: BYTES_PER_PARTICLE,
    }


# -- Budget tracker ----------------------------------------------------------

class MemoryBudget:
    """Tracks current physics memory usage against configured caps.

    Hooks/usage pattern: a game loop calls

        budget.check(world, particles_count=..., frame=world.frame)

    each frame.  When a cap is approached or exceeded it raises
    :class:`MemoryBudgetExceeded` (subclass of :class:`MemoryError`) or
    emits a warning via :func:`warnings.warn`.

    Approximation: the ``approx_bytes`` fields are derived from the
    documented per-unit costs in :data:`BYTES_PER_BODY`,
    :data:`BYTES_PER_CELL_SLOT`, and :data:`BYTES_PER_PARTICLE` — they are
    not measured with :func:`sys.getsizeof`.
    """

    def __init__(self, config: MemoryBudgetConfig) -> None:
        self.config = config
        # Frame at which we last warned about a given resource, used to
        # rate-limit "approaching cap" warnings so they don't spam the log
        # once a scene settles near the threshold.
        self._last_warning_frame: dict[str, int] = {}

    # -- Snapshot construction ----------------------------------------------

    def current_usage(self, world: Any, particles_count: int = 0) -> dict:
        """Return current usage without checking the cap.

        Includes an ``approx_bytes`` field on each resource (computed from
        the documented per-unit cost — not from :func:`sys.getsizeof`) and
        a top-level ``approx_bytes_total``.
        """
        bodies_n = len(getattr(world, "bodies", []))
        cell_pool = getattr(world, "cell_pool", None)
        cells_n = int(getattr(cell_pool, "in_use_count", 0)) if cell_pool is not None else 0
        parts_n = int(particles_count)

        per_unit = _bytes_per_unit()
        caps = _resource_caps(self.config)

        usage: dict[str, Any] = {
            _RESOURCE_BODIES: {
                "current": bodies_n,
                "cap": caps[_RESOURCE_BODIES],
                "approx_bytes": bodies_n * per_unit[_RESOURCE_BODIES],
            },
            _RESOURCE_CELLS: {
                "current": cells_n,
                "cap": caps[_RESOURCE_CELLS],
                "approx_bytes": cells_n * per_unit[_RESOURCE_CELLS],
            },
            _RESOURCE_PARTICLES: {
                "current": parts_n,
                "cap": caps[_RESOURCE_PARTICLES],
                "approx_bytes": parts_n * per_unit[_RESOURCE_PARTICLES],
            },
        }
        usage["approx_bytes_total"] = (
            usage[_RESOURCE_BODIES]["approx_bytes"]
            + usage[_RESOURCE_CELLS]["approx_bytes"]
            + usage[_RESOURCE_PARTICLES]["approx_bytes"]
        )
        return usage

    # -- Per-frame check ----------------------------------------------------

    def check(self, world: Any, particles_count: int = 0, frame: int = 0) -> dict:
        """Compare current usage to caps and warn/raise as needed.

        Returns a snapshot dict (same shape as :meth:`current_usage`) with
        an additional ``over_cap`` flag on each resource.  Raises
        :class:`MemoryBudgetExceeded` if any resource is at or above its
        hard cap.  Emits a (rate-limited) :class:`UserWarning` for each
        resource that has reached
        ``cap * config.warn_at_fraction`` but not yet exceeded the cap.
        """
        usage = self.current_usage(world, particles_count=particles_count)

        warn_fraction = float(self.config.warn_at_fraction)
        over_resources: list[tuple[str, int, int]] = []  # (name, current, cap)

        for name in (_RESOURCE_BODIES, _RESOURCE_CELLS, _RESOURCE_PARTICLES):
            entry = usage[name]
            current = int(entry["current"])
            cap = int(entry["cap"])
            entry["over_cap"] = current > cap

            if current > cap:
                over_resources.append((name, current, cap))
                continue

            # Warn band: current >= cap * warn_fraction (but not over cap).
            if cap > 0 and current >= cap * warn_fraction:
                self._maybe_warn(name, current, cap, frame)

        if over_resources:
            parts = ", ".join(
                f"{name}={current}/{cap}" for name, current, cap in over_resources
            )
            raise MemoryBudgetExceeded(
                f"PhysicsWorld memory budget exceeded: {parts}. "
                f"Approx total {usage['approx_bytes_total']} bytes."
            )

        return usage

    # -- Internal -----------------------------------------------------------

    def _maybe_warn(self, name: str, current: int, cap: int, frame: int) -> None:
        """Emit an 'approaching cap' warning, rate-limited per resource."""
        last = self._last_warning_frame.get(name)
        if last is not None and (frame - last) < _WARNING_RATE_LIMIT_FRAMES:
            return
        self._last_warning_frame[name] = frame
        pct = (current / cap) * 100.0 if cap > 0 else 0.0
        warnings.warn(
            f"PhysicsWorld memory budget approaching cap for {name}: "
            f"{current}/{cap} ({pct:.0f}%).",
            UserWarning,
            stacklevel=2,
        )

    # -- API-boundary enforcement ------------------------------------------
    #
    # These helpers are invoked by ``PhysicsWorld.create_body``,
    # ``CellGridPool.acquire``, and ``ParticleSystem.emit`` so memory caps
    # are enforced at allocation time (not just on a per-frame audit).
    #
    # Each ``_check_alloc`` call accepts the prospective post-allocation
    # count (``next_count = current + delta``) and either:
    #   - returns silently if under ``cap * warn_at_fraction`` (no warn band),
    #   - emits a (rate-limited) ``UserWarning`` once usage enters the warn
    #     band [warn_at_fraction*cap, cap], or
    #   - raises ``MemoryBudgetExceeded`` if the prospective count would
    #     strictly exceed the cap.
    #
    # The ``yaml_key`` argument is the dotted ``memory.<field>`` path
    # surfaced to users in the error message so they know exactly which
    # YAML knob to raise.

    def _check_alloc(
        self,
        resource: str,
        next_count: int,
        cap: int,
        yaml_key: str,
    ) -> None:
        if cap <= 0:
            return
        if next_count > cap:
            raise MemoryBudgetExceeded(
                f"{resource} reached cap: {next_count}/{cap}; "
                f"raise in config/physics.yml {yaml_key}."
            )
        warn_fraction = float(self.config.warn_at_fraction)
        if next_count >= cap * warn_fraction:
            # Reuse the per-resource rate-limited warning, but key off the
            # resource alone so repeat allocations in the same scene burst
            # don't spam.  Use a synthetic "frame" of the count so multiple
            # bursts > rate-limit window apart still re-warn.
            last = self._last_warning_frame.get(resource)
            # If we've already warned for this resource, only re-warn once
            # the count has grown by at least 1; this keeps a tight loop
            # from emitting a warning per allocation while still surfacing
            # the issue exactly once when the threshold is first crossed.
            if last is not None and last >= next_count:
                return
            self._last_warning_frame[resource] = next_count
            pct = (next_count / cap) * 100.0
            warnings.warn(
                f"PhysicsWorld memory budget approaching cap for {resource}: "
                f"{next_count}/{cap} ({pct:.0f}%); "
                f"raise in config/physics.yml {yaml_key}.",
                UserWarning,
                stacklevel=3,
            )

    def check_body_alloc(self, next_count: int) -> None:
        """Enforce ``max_bodies`` against ``next_count`` (the proposed total)."""
        self._check_alloc(
            _RESOURCE_BODIES,
            int(next_count),
            int(self.config.max_bodies),
            "memory.max_bodies",
        )

    def check_cell_slot_alloc(self, next_count: int) -> None:
        """Enforce ``max_cell_pool_slots`` against ``next_count``."""
        self._check_alloc(
            _RESOURCE_CELLS,
            int(next_count),
            int(self.config.max_cell_pool_slots),
            "memory.max_cell_pool_slots",
        )

    def check_particle_alloc(self, next_count: int) -> None:
        """Enforce ``max_particle_count`` against ``next_count``."""
        self._check_alloc(
            _RESOURCE_PARTICLES,
            int(next_count),
            int(self.config.max_particle_count),
            "memory.max_particle_count",
        )


# -- YAML loader ------------------------------------------------------------

def load_memory_budget_config(raw: dict | None) -> MemoryBudgetConfig:
    """Build a :class:`MemoryBudgetConfig` from a raw ``memory:`` dict.

    Missing keys fall back to the dataclass defaults; ``raw=None`` returns
    a pure-defaults config.
    """
    defaults = MemoryBudgetConfig()
    if not isinstance(raw, dict):
        return defaults
    return MemoryBudgetConfig(
        max_bodies=int(raw.get("max_bodies", defaults.max_bodies)),
        max_cell_pool_slots=int(raw.get("max_cell_pool_slots", defaults.max_cell_pool_slots)),
        max_particle_count=int(raw.get("max_particle_count", defaults.max_particle_count)),
        warn_at_fraction=float(raw.get("warn_at_fraction", defaults.warn_at_fraction)),
    )


def _install_memory_section_on_physics_yaml() -> None:
    """Wrap ``load_physics_config`` so its result carries a ``memory`` field.

    Idempotent — calling it twice is a no-op (the wrapper checks an attribute
    on the function object).  We do this at import time from
    :mod:`pharos_engine.physics.__init__`.
    """
    # Local import to avoid a circular import at module load.
    from pharos_engine.physics import world as _world_mod
    import yaml as _yaml
    from pathlib import Path as _Path

    if getattr(_world_mod.load_physics_config, "_memory_section_installed", False):
        return

    _original_load = _world_mod.load_physics_config

    # Attach a sensible default to the dataclass class so even pure-default
    # PhysicsYaml() instances have ``.memory``.
    if not hasattr(_world_mod.PhysicsYaml, "memory"):
        _world_mod.PhysicsYaml.memory = MemoryBudgetConfig()  # type: ignore[attr-defined]

    def _wrapped_load(path=None):
        result = _original_load(path)
        mem_raw: dict | None = None
        try:
            if path is None:
                path = _world_mod._find_physics_yml()
            if path is not None and _Path(path).exists():
                with open(path, encoding="utf-8") as fh:
                    raw = _yaml.safe_load(fh) or {}
                if isinstance(raw, dict):
                    sub = raw.get("memory", None)
                    if isinstance(sub, dict):
                        mem_raw = sub
        except Exception:
            mem_raw = None
        result.memory = load_memory_budget_config(mem_raw)
        return result

    _wrapped_load._memory_section_installed = True  # type: ignore[attr-defined]
    _world_mod.load_physics_config = _wrapped_load


__all__ = [
    "BYTES_PER_BODY",
    "BYTES_PER_CELL_SLOT",
    "BYTES_PER_PARTICLE",
    "MemoryBudget",
    "MemoryBudgetConfig",
    "MemoryBudgetExceeded",
    "load_memory_budget_config",
]
