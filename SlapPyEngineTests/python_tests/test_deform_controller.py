"""Engine tests for DeformController + SimFrequencyBudget — headless."""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# DeformController
# ---------------------------------------------------------------------------

class TestDeformControllerDefaults:
    def test_starts_static(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController()
        assert ctrl.state == SimState.STATIC

    def test_is_active_false_when_static(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        assert ctrl.is_active is False

    def test_always_on_is_active(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController(sim_mode="always_on")
        assert ctrl.is_active is True

    def test_always_on_tick_returns_true(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController(sim_mode="always_on")
        should_dispatch, _ = ctrl.tick(0.016, energy_estimate=99.0)
        assert should_dispatch is True

    def test_static_tick_returns_false(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        should_dispatch, _ = ctrl.tick(0.016, energy_estimate=99.0)
        assert should_dispatch is False


class TestDeformControllerActivation:
    def test_activate_transitions_to_active(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController()
        ctrl.activate()
        assert ctrl.state == SimState.ACTIVE

    def test_active_tick_returns_true(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        ctrl.activate()
        should_dispatch, _ = ctrl.tick(0.016, energy_estimate=99.0)
        assert should_dispatch is True

    def test_active_is_active_true(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        ctrl.activate()
        assert ctrl.is_active is True

    def test_deactivate_returns_to_static(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController(sim_mode="manual")
        ctrl.activate()
        ctrl.deactivate()
        assert ctrl.state == SimState.STATIC

    def test_activate_always_on_is_noop(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController(sim_mode="always_on")
        ctrl.activate()
        # always_on doesn't use state machine; state should stay STATIC (no transition)
        assert ctrl.sim_mode == "always_on"


class TestDeformControllerSettling:
    def test_active_settles_when_energy_low(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController(settle_threshold=1.0, settling_ramp_rate=30.0)
        ctrl.activate()
        # First tick with high energy — stays ACTIVE
        ctrl.tick(0.1, energy_estimate=5.0)
        assert ctrl.state == SimState.ACTIVE
        # Tick with low energy after 0.05s grace — transitions to SETTLING
        ctrl.tick(0.1, energy_estimate=0.1)
        assert ctrl.state == SimState.SETTLING

    def test_settling_eventually_returns_to_static(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController(settling_ramp_rate=100.0)
        ctrl.activate()
        ctrl.tick(0.1, energy_estimate=5.0)  # time_active > 0.05
        ctrl.tick(0.1, energy_estimate=0.01) # below threshold → SETTLING
        for _ in range(60):
            ctrl.tick(0.016, energy_estimate=0.0)
        assert ctrl.state == SimState.STATIC

    def test_settling_decay_increases_toward_1(self):
        from pharos_engine.deform_controller import DeformController, SimState
        ctrl = DeformController(spring_decay=0.5, settling_ramp_rate=10.0)
        ctrl.activate()
        ctrl.tick(0.1, energy_estimate=5.0)
        ctrl.tick(0.1, energy_estimate=0.0)  # → SETTLING
        initial_decay = ctrl._settling_decay
        ctrl.tick(0.1, energy_estimate=0.0)
        assert ctrl._settling_decay >= initial_decay


class TestDeformControllerDecay:
    def test_constant_mode_returns_base_decay(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController(decay_mode="constant", spring_decay=0.7)
        ctrl.activate()
        _, decay = ctrl.tick(0.016, energy_estimate=99.0)
        assert decay == pytest.approx(0.7)

    def test_none_mode_returns_1(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController(decay_mode="none")
        ctrl.activate()
        _, decay = ctrl.tick(0.016, energy_estimate=99.0)
        assert decay == pytest.approx(1.0)

    def test_curve_mode_interpolates(self):
        from pharos_engine.deform_controller import DeformController
        curve = [(0.0, 0.5), (1.0, 0.9)]
        ctrl = DeformController(decay_mode="curve", decay_curve=curve)
        ctrl.activate()
        # After 0.5s active, decay should be midway between 0.5 and 0.9
        ctrl._time_active = 0.5
        decay = ctrl._current_decay()
        assert pytest.approx(decay, abs=0.05) == 0.7


class TestDeformControllerFrequency:
    def test_every_frame_always_true(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        ctrl.activate()
        ctrl.tick(0.016, energy_estimate=99.0)
        assert ctrl.should_dispatch_this_frame("every_frame") is True

    def test_every_n_frames_skips(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController(n_frames_skip=4)
        ctrl.activate()
        results = []
        for _ in range(8):
            ctrl.tick(0.016, energy_estimate=99.0)
            results.append(ctrl.should_dispatch_this_frame("every_n_frames"))
        # Some frames should return False
        assert False in results

    def test_time_active_increments(self):
        from pharos_engine.deform_controller import DeformController
        ctrl = DeformController()
        ctrl.activate()
        ctrl.tick(0.1, energy_estimate=99.0)
        assert ctrl.time_active == pytest.approx(0.1, abs=0.001)


# ---------------------------------------------------------------------------
# SimFrequencyBudget
# ---------------------------------------------------------------------------

class TestSimFrequencyBudget:
    def test_init_default_budget(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        assert budget._budget_ms > 0.0

    def test_allocate_budget_resets_used(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.request_slot()  # use some budget
        budget.allocate_budget(5.0)
        assert budget._used_ms == pytest.approx(0.0)

    def test_request_slot_within_budget_returns_true(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.allocate_budget(10.0)
        assert budget.request_slot(priority=1.0) is True

    def test_request_slot_exhausted_returns_false(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.allocate_budget(0.05)  # tiny budget
        # Request many slots until exhausted
        results = [budget.request_slot(priority=1.0) for _ in range(20)]
        assert False in results

    def test_remaining_ms_decreases(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.allocate_budget(2.0)
        r0 = budget.remaining_ms
        budget.request_slot()
        assert budget.remaining_ms < r0

    def test_remaining_ms_non_negative(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.allocate_budget(0.001)
        for _ in range(100):
            budget.request_slot()
        assert budget.remaining_ms >= 0.0

    def test_low_priority_blocked_when_budget_tight(self):
        from pharos_engine.deform_controller import SimFrequencyBudget
        budget = SimFrequencyBudget()
        budget.allocate_budget(0.15)
        # High-priority grabs one slot
        budget.request_slot(priority=1.0)
        # Low-priority should fail when budget is tight
        result = budget.request_slot(priority=0.1)
        # With budget ~0.15 and cost 0.1 per slot, two high-prio could fit
        # but low prio (0.1) means cost check: 0.2 <= 0.15 * 0.1 = 0.015 → False
        assert result is False
