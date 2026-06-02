"""Tests for slappyengine.deform_controller."""
from __future__ import annotations
import sys
import os
import pytest

# Ensure the package root is on the path for direct test runs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from slappyengine.deform_controller import DeformController, SimFrequencyBudget, SimState


# ---------------------------------------------------------------------------
# SimState / activation tests
# ---------------------------------------------------------------------------

def test_collision_triggered_starts_static():
    """Fresh controller with collision_triggered mode begins in STATIC state."""
    ctrl = DeformController(sim_mode="collision_triggered")
    assert ctrl.state == SimState.STATIC


def test_activate_transitions_to_active():
    """After activate(), state should be ACTIVE."""
    ctrl = DeformController(sim_mode="collision_triggered")
    ctrl.activate()
    assert ctrl.state == SimState.ACTIVE


def test_always_on_always_dispatches():
    """always_on mode: tick() always returns should_dispatch=True regardless of energy."""
    ctrl = DeformController(sim_mode="always_on")
    for energy in (0.0, 0.1, 1.0, 100.0):
        should_dispatch, _ = ctrl.tick(dt=0.016, energy_estimate=energy)
        assert should_dispatch, f"Expected dispatch with energy={energy}"


def test_static_never_dispatches():
    """STATIC state: tick() always returns should_dispatch=False."""
    ctrl = DeformController(sim_mode="collision_triggered")
    assert ctrl.state == SimState.STATIC
    should_dispatch, _ = ctrl.tick(dt=0.016, energy_estimate=99.0)
    assert not should_dispatch


# ---------------------------------------------------------------------------
# Settling / decay ramp tests
# ---------------------------------------------------------------------------

def test_settling_ramps_decay():
    """In SETTLING state, effective_spring_decay increases each successive tick."""
    ctrl = DeformController(
        sim_mode="collision_triggered",
        decay_mode="constant",
        spring_decay=0.80,
        settling_ramp_rate=4.0,
    )
    ctrl.activate()
    # Force into SETTLING by ticking with low energy past the 0.05s guard
    ctrl.tick(dt=0.06, energy_estimate=0.0)
    assert ctrl.state == SimState.SETTLING, "Expected SETTLING after low-energy tick past guard"

    prev_decay = ctrl._settling_decay
    for _ in range(5):
        _, decay = ctrl.tick(dt=0.016, energy_estimate=0.0)
        if ctrl.state == SimState.STATIC:
            break
        assert decay >= prev_decay, "Decay should be non-decreasing during SETTLING"
        prev_decay = decay


def test_settles_to_static():
    """After enough SETTLING ticks, state eventually returns to STATIC."""
    ctrl = DeformController(
        sim_mode="collision_triggered",
        decay_mode="constant",
        spring_decay=0.80,
        settling_ramp_rate=30.0,  # fast ramp for test speed
    )
    ctrl.activate()
    # Burn past the 0.05s guard with zero energy to enter SETTLING immediately
    ctrl.tick(dt=0.06, energy_estimate=0.0)
    assert ctrl.state == SimState.SETTLING

    # Run up to 200 ticks — with ramp_rate=30, settling should complete quickly
    max_ticks = 200
    for _ in range(max_ticks):
        ctrl.tick(dt=0.016, energy_estimate=0.0)
        if ctrl.state == SimState.STATIC:
            break
    assert ctrl.state == SimState.STATIC, "Controller never returned to STATIC"


# ---------------------------------------------------------------------------
# Decay mode tests
# ---------------------------------------------------------------------------

def test_curve_mode_interpolates():
    """CURVE mode: at t=0.125s between [(0.0, 0.94), (0.25, 0.97)] → 0.955."""
    curve = [(0.0, 0.94), (0.25, 0.97)]
    ctrl = DeformController(
        sim_mode="collision_triggered",
        decay_mode="curve",
        decay_curve=curve,
        settle_threshold=0.0,   # never auto-settle during this test
    )
    ctrl.activate()

    # We need _time_active = 0.125 exactly.
    # tick() increments _time_active before sampling, so tick with dt=0.125
    # but keep energy_estimate high enough to stay ACTIVE (above settle_threshold=0)
    # Actually settle_threshold=0.0 means energy<0 never fires; any energy>=0 won't trigger.
    # Use a negative settle_threshold workaround — instead set threshold very low negative
    # Re-create with a threshold that won't fire at our energy level.
    ctrl2 = DeformController(
        sim_mode="collision_triggered",
        decay_mode="curve",
        decay_curve=curve,
        settle_threshold=-1.0,  # impossible to meet → stays ACTIVE
    )
    ctrl2.activate()
    # dt=0.125 → _time_active becomes 0.125 after tick
    _, decay = ctrl2.tick(dt=0.125, energy_estimate=1.0)
    expected = 0.955
    assert abs(decay - expected) < 1e-9, f"Expected {expected}, got {decay}"


def test_none_decay_returns_1():
    """decay_mode='none' always returns spring_decay=1.0 regardless of state."""
    ctrl = DeformController(
        sim_mode="always_on",
        decay_mode="none",
        spring_decay=0.94,
    )
    for _ in range(5):
        _, decay = ctrl.tick(dt=0.016, energy_estimate=1.0)
        assert decay == 1.0, f"Expected 1.0 for none decay, got {decay}"


# ---------------------------------------------------------------------------
# Energy threshold tests
# ---------------------------------------------------------------------------

def test_energy_above_threshold_stays_active():
    """High energy_estimate keeps the controller in ACTIVE state past the time guard."""
    ctrl = DeformController(
        sim_mode="collision_triggered",
        settle_threshold=0.5,
    )
    ctrl.activate()
    # Tick past the 0.05s guard with energy well above threshold
    for _ in range(10):
        ctrl.tick(dt=0.016, energy_estimate=5.0)
    assert ctrl.state == SimState.ACTIVE, "Should remain ACTIVE while energy > threshold"


def test_energy_below_threshold_transitions_settling():
    """Low energy_estimate + time > 0.05s triggers ACTIVE → SETTLING transition."""
    ctrl = DeformController(
        sim_mode="collision_triggered",
        settle_threshold=0.5,
    )
    ctrl.activate()
    # One large tick past the 0.05s guard with energy below threshold
    ctrl.tick(dt=0.06, energy_estimate=0.1)
    assert ctrl.state == SimState.SETTLING, (
        f"Expected SETTLING after low-energy tick past guard, got {ctrl.state}"
    )


# ---------------------------------------------------------------------------
# SimFrequencyBudget tests
# ---------------------------------------------------------------------------

def test_budget_allocator():
    """request_slot() returns False once the frame budget is exhausted."""
    budget = SimFrequencyBudget()
    # Use 0.35ms budget: cleanly fits 3 slots at 0.1ms each (0.3 <= 0.35)
    # and rejects a 4th (0.4 > 0.35).
    budget.allocate_budget(budget_ms=0.35)

    results = [budget.request_slot(priority=1.0) for _ in range(5)]

    # First 3 should succeed, remainder should fail
    assert results[:3] == [True, True, True], f"Expected 3 grants, got {results}"
    assert all(not r for r in results[3:]), f"Expected remaining False, got {results[3:]}"

    # Remaining budget should reflect 3 slots used
    assert budget.remaining_ms == pytest.approx(0.35 - 3 * 0.1, abs=1e-9)

    # After re-allocating, budget resets and new slots are granted
    budget.allocate_budget(budget_ms=0.35)
    assert budget.remaining_ms == pytest.approx(0.35)
    assert budget.request_slot(priority=1.0) is True
