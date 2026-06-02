"""Tests for slappyengine.physics.memory_budget."""
from __future__ import annotations

import warnings

import pytest

from slappyengine.physics import (
    PhysicsWorld,
    MemoryBudget,
    MemoryBudgetConfig,
    MemoryBudgetExceeded,
    load_physics_config,
    make_circle_silhouette,
)
from slappyengine.physics.hull import TIER_T0


# -- Helpers -----------------------------------------------------------------

def _spawn_bodies(world: PhysicsWorld, n: int) -> None:
    """Spawn ``n`` lightweight T0 bodies (no cell-pool slots) for cap tests."""
    sil = make_circle_silhouette(8)
    for i in range(n):
        # TIER_T0 = no cell-grid slot allocation -> we can spawn many cheaply
        # without exhausting the cell pool, which is the variable we're
        # exercising in body-count tests.
        world.create_body(
            sil, material="sand",
            position=(float(i), 0.0),
            tier=TIER_T0,
        )


def _bare_world() -> PhysicsWorld:
    """A PhysicsWorld with no world bounds, so spawning is cheap."""
    return PhysicsWorld()


# -- Tests -------------------------------------------------------------------

def test_budget_passes_when_under_caps():
    world = _bare_world()
    _spawn_bodies(world, 3)
    budget = MemoryBudget(MemoryBudgetConfig())
    snap = budget.check(world, particles_count=10, frame=0)
    for key in ("n_bodies", "n_cell_pool_slots", "particles"):
        assert snap[key]["over_cap"] is False, snap


def test_budget_warns_at_80_percent():
    world = _bare_world()
    _spawn_bodies(world, 8)  # 8 / 10 = 80%
    cfg = MemoryBudgetConfig(max_bodies=10, max_cell_pool_slots=10_000,
                             max_particle_count=10_000, warn_at_fraction=0.80)
    budget = MemoryBudget(cfg)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        snap = budget.check(world, particles_count=0, frame=0)
    assert snap["n_bodies"]["over_cap"] is False
    matching = [
        w for w in caught
        if "approaching" in str(w.message).lower() and "n_bodies" in str(w.message)
    ]
    assert matching, f"expected an 'approaching cap' warning, got {caught}"


def test_budget_raises_at_100_percent():
    world = _bare_world()
    cfg = MemoryBudgetConfig(max_bodies=5, max_cell_pool_slots=10_000,
                             max_particle_count=10_000, warn_at_fraction=0.80)
    _spawn_bodies(world, 8)  # > 5
    budget = MemoryBudget(cfg)
    with pytest.raises(MemoryBudgetExceeded):
        budget.check(world, particles_count=0, frame=0)


def test_budget_includes_cell_pool_usage():
    world = _bare_world()
    # Default create_body uses TIER_T2, which acquires a cell-pool slot.
    sil = make_circle_silhouette(8)
    world.create_body(sil, material="sand", position=(0.0, 0.0))
    world.create_body(sil, material="sand", position=(20.0, 0.0))
    budget = MemoryBudget(MemoryBudgetConfig())
    usage = budget.current_usage(world, particles_count=0)
    assert usage["n_cell_pool_slots"]["current"] == world.cell_pool.in_use_count
    assert usage["n_cell_pool_slots"]["current"] == 2


def test_budget_includes_particle_count():
    world = _bare_world()
    budget = MemoryBudget(MemoryBudgetConfig())
    usage = budget.current_usage(world, particles_count=1234)
    assert usage["particles"]["current"] == 1234
    # And the snapshot returned by check() also surfaces it.
    snap = budget.check(world, particles_count=1234, frame=0)
    assert snap["particles"]["current"] == 1234


def test_budget_warnings_rate_limited():
    world = _bare_world()
    _spawn_bodies(world, 9)  # 9 / 10 = 90% -> warn band
    cfg = MemoryBudgetConfig(max_bodies=10, max_cell_pool_slots=10_000,
                             max_particle_count=10_000, warn_at_fraction=0.80)
    budget = MemoryBudget(cfg)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # Two consecutive frames within the rate-limit window.
        budget.check(world, particles_count=0, frame=0)
        budget.check(world, particles_count=0, frame=1)
    body_warns = [
        w for w in caught
        if "n_bodies" in str(w.message) and "approaching" in str(w.message).lower()
    ]
    assert len(body_warns) == 1, (
        f"expected exactly one rate-limited warning, got {len(body_warns)}: {caught}"
    )


def test_memory_yaml_section_parses():
    cfg = load_physics_config()
    # The one-line import in physics/__init__ installs a ``memory`` attribute.
    assert hasattr(cfg, "memory"), "PhysicsYaml should expose a .memory section"
    mem = cfg.memory
    assert mem.max_bodies == 4096
    assert mem.max_cell_pool_slots == 1024
    assert mem.max_particle_count == 65536
    assert mem.warn_at_fraction == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Sprint 7 — API-boundary enforcement tests.
#
# These exercise the enforcement that's wired into ``PhysicsWorld.create_body``,
# ``CellGridPool.acquire``, and ``ParticleSystem.emit``: the
# ``MemoryBudget.check_*_alloc`` helpers warn at ``warn_at_fraction`` and
# raise ``MemoryBudgetExceeded`` past the cap.
# ---------------------------------------------------------------------------

def _world_with_budget(**budget_kwargs) -> PhysicsWorld:
    """Build a PhysicsWorld and replace its MemoryBudget with a tight one.

    All ``budget_kwargs`` are forwarded to :class:`MemoryBudgetConfig`; any
    unspecified caps default to large values so unrelated allocations
    don't trip the limit.
    """
    defaults = dict(
        max_bodies=10_000,
        max_cell_pool_slots=10_000,
        max_particle_count=10_000,
        warn_at_fraction=0.80,
    )
    defaults.update(budget_kwargs)
    world = _bare_world()
    world.memory_budget = MemoryBudget(MemoryBudgetConfig(**defaults))
    # CellGridPool was constructed with the original budget; rebind so the
    # tight cap is what gets enforced on subsequent acquires.
    world.cell_pool.memory_budget = world.memory_budget
    return world


# -- max_bodies enforcement (create_body) -----------------------------------

def test_max_bodies_warns_at_80pct():
    """Crossing the 80% body cap during ``create_body`` must emit a warning."""
    # max_bodies=10, warn at 80% (=8).  Spawn 7 bodies (under threshold),
    # confirm no warn yet, then spawn the 8th which trips the warn band.
    world = _world_with_budget(max_bodies=10)
    sil = make_circle_silhouette(8)
    for i in range(7):
        world.create_body(sil, material="sand", position=(float(i), 0.0),
                          tier=TIER_T0)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        world.create_body(sil, material="sand", position=(7.0, 0.0),
                          tier=TIER_T0)
    matches = [
        w for w in caught
        if "n_bodies" in str(w.message)
        and "memory.max_bodies" in str(w.message)
    ]
    assert matches, (
        f"expected an 'approaching cap' warning naming memory.max_bodies, "
        f"got {[str(w.message) for w in caught]}"
    )


def test_max_bodies_raises_at_100pct():
    """Exceeding the body cap during ``create_body`` must raise cleanly."""
    world = _world_with_budget(max_bodies=3)
    sil = make_circle_silhouette(8)
    # Spawn up to the cap (3) — must succeed.
    for i in range(3):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            world.create_body(sil, material="sand", position=(float(i), 0.0),
                              tier=TIER_T0)
    # 4th body crosses the cap and must raise MemoryBudgetExceeded.
    with pytest.raises(MemoryBudgetExceeded) as excinfo:
        world.create_body(sil, material="sand", position=(4.0, 0.0),
                          tier=TIER_T0)
    msg = str(excinfo.value)
    assert "memory.max_bodies" in msg, (
        f"error message should name the YAML key to raise; got: {msg!r}"
    )


# -- max_cell_pool_slots enforcement (CellGridPool.acquire) -----------------

def test_max_cell_pool_slots_warns():
    """Crossing 80% of the cell-pool cap on ``acquire`` must warn."""
    # max_cell_pool_slots=10 -> warn band starts at 8.  Use T2 bodies so
    # each create_body consumes one cell-pool slot.
    world = _world_with_budget(max_cell_pool_slots=10)
    # Pre-grow the pool so capacity isn't the limiting factor.
    world.cell_pool.grow(16)
    sil = make_circle_silhouette(8)
    for i in range(7):
        world.create_body(sil, material="sand", position=(float(i * 40), 0.0))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        world.create_body(sil, material="sand", position=(7 * 40.0, 0.0))
    matches = [
        w for w in caught
        if "n_cell_pool_slots" in str(w.message)
        and "memory.max_cell_pool_slots" in str(w.message)
    ]
    assert matches, (
        f"expected an 'approaching cap' warning naming "
        f"memory.max_cell_pool_slots, got {[str(w.message) for w in caught]}"
    )


def test_max_cell_pool_slots_raises():
    """Acquire past the cell-pool cap must raise ``MemoryBudgetExceeded``."""
    world = _world_with_budget(max_cell_pool_slots=2)
    world.cell_pool.grow(8)  # ensure raw capacity > cap
    sil = make_circle_silhouette(8)
    # Spawn up to the cap (2).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        world.create_body(sil, material="sand", position=(0.0, 0.0))
        world.create_body(sil, material="sand", position=(40.0, 0.0))
    # Third body would need a 3rd slot -> over cap.
    with pytest.raises(MemoryBudgetExceeded) as excinfo:
        world.create_body(sil, material="sand", position=(80.0, 0.0))
    msg = str(excinfo.value)
    assert "memory.max_cell_pool_slots" in msg, (
        f"error message should name the YAML key to raise; got: {msg!r}"
    )


# -- max_particle_count enforcement (ParticleSystem.emit) -------------------

def test_max_particle_count_warns():
    """Crossing 80% of the particle cap during ``emit`` must warn."""
    from slappyengine.physics.particles import ParticleSystem
    budget = MemoryBudget(MemoryBudgetConfig(
        max_bodies=10_000,
        max_cell_pool_slots=10_000,
        max_particle_count=10,
        warn_at_fraction=0.80,
    ))
    # ParticleSystem capacity must be at least the cap so the budget is
    # the limiting factor, not max_particles.
    ps = ParticleSystem(max_particles=64, memory_budget=budget)
    # Emit 9 particles (passes 80% threshold of cap=10).  Material
    # ``water`` maps to the "splash" style which has ``count_mul=1.0`` so
    # asking for 9 yields exactly 9 spawned particles.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        spawned = ps.emit(
            world_point=(0.0, 0.0),
            impulse=(1.0, 0.0),
            material_name="water",
            count=9,
        )
    assert spawned == 9, f"expected to spawn 9 particles, got {spawned}"
    matches = [
        w for w in caught
        if "particles" in str(w.message)
        and "memory.max_particle_count" in str(w.message)
    ]
    assert matches, (
        f"expected an 'approaching cap' warning naming "
        f"memory.max_particle_count, got {[str(w.message) for w in caught]}"
    )
