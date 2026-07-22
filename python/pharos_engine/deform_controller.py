"""pharos_engine.deform_controller — Sim state machine and decay schedule for DeformableLayerComponent."""
from __future__ import annotations
import enum
import math


class SimState(enum.Enum):
    STATIC   = "static"    # simulation not running; zero GPU cost
    ACTIVE   = "active"    # simulation running; impacts being processed
    SETTLING = "settling"  # impacts done; spring_decay ramping up to kill residual


class DeformController:
    """Manages simulation activation, decay scheduling, and settling.

    Parameters
    ----------
    sim_mode:
        One of the DeformSimMode values (passed as string to avoid circular import).
        "always_on" | "collision_triggered" | "manual"
    decay_mode:
        "constant" | "curve" | "none"
    spring_decay:
        Base spring_decay value for CONSTANT mode. Ignored in CURVE/NONE modes.
    decay_curve:
        List of (time_elapsed_s, decay_rate) tuples for CURVE mode.
        Piecewise-linear; sampled by time since last activation.
    settle_threshold:
        Total absolute stress (sum |stress_per_pixel| conceptually; in practice
        a scalar energy estimate) below which ACTIVE→SETTLING transition fires.
    settling_ramp_rate:
        How fast spring_decay ramps toward 1.0 during SETTLING phase.
        Higher = faster damp-out. Typical: 4.0–30.0.
    n_frames_skip:
        For EVERY_N_FRAMES frequency: dispatch every N frames.
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
        self._base_spring_decay = spring_decay
        self.decay_curve = decay_curve or []
        self.settle_threshold = settle_threshold
        self.settling_ramp_rate = settling_ramp_rate
        self.n_frames_skip = n_frames_skip

        self.state: SimState = SimState.STATIC
        self._time_active: float = 0.0      # seconds since last activation
        self._settling_decay: float = spring_decay  # current effective decay during settling
        self._frame_counter: int = 0

    # ------------------------------------------------------------------
    # Activation (called externally by collision system)
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Transition to ACTIVE state. Safe to call when already ACTIVE."""
        if self.sim_mode == "always_on":
            return  # always_on never uses the state machine
        self.state = SimState.ACTIVE
        self._time_active = 0.0
        self._settling_decay = self._base_spring_decay

    def deactivate(self) -> None:
        """Force immediate return to STATIC (MANUAL mode)."""
        self.state = SimState.STATIC

    # ------------------------------------------------------------------
    # Per-frame update — call before dispatching GPU shader
    # ------------------------------------------------------------------

    def tick(self, dt: float, energy_estimate: float) -> tuple[bool, float]:
        """Advance controller by dt seconds.

        Parameters
        ----------
        dt:
            Frame delta time in seconds.
        energy_estimate:
            Scalar estimate of remaining elastic energy in the simulation
            (e.g., sum of |stress| values / pixel_count, or max stress).
            Used to detect settling.

        Returns
        -------
        should_dispatch : bool
            True if the deformation shader should run this frame.
        effective_spring_decay : float
            The spring_decay value to pass to the GPU shader this frame.
        """
        self._frame_counter += 1

        # always_on: always dispatch, return configured decay
        if self.sim_mode == "always_on":
            return True, self._current_decay()

        # manual / collision_triggered: state machine
        if self.state == SimState.STATIC:
            return False, self._base_spring_decay

        self._time_active += dt

        if self.state == SimState.ACTIVE:
            # Check if energy has settled enough to start settling phase
            if energy_estimate < self.settle_threshold and self._time_active > 0.05:
                self.state = SimState.SETTLING
                self._settling_decay = self._current_decay()
            return True, self._current_decay()

        if self.state == SimState.SETTLING:
            # Ramp spring_decay toward 1.0 at settling_ramp_rate per second
            self._settling_decay = min(
                1.0,
                self._settling_decay + (1.0 - self._settling_decay) * self.settling_ramp_rate * dt
            )
            # If essentially at 1.0 (< 0.001 from it), snap to STATIC
            if self._settling_decay >= 0.999:
                self.state = SimState.STATIC
                return False, 1.0  # one last frame with full decay to zero out stress
            return True, self._settling_decay

        return False, self._base_spring_decay

    def should_dispatch_this_frame(self, frequency_mode: str) -> bool:
        """Apply frequency-mode frame skipping on top of state machine decision.

        Call this AFTER tick() returns should_dispatch=True.
        """
        if frequency_mode == "every_frame":
            return True
        if frequency_mode == "every_n_frames":
            return (self._frame_counter % max(1, self.n_frames_skip)) == 0
        if frequency_mode == "lod_distance":
            # Caller sets n_frames_skip externally based on camera distance
            return (self._frame_counter % max(1, self.n_frames_skip)) == 0
        if frequency_mode == "budget_driven":
            # Budget system sets n_frames_skip; same check
            return (self._frame_counter % max(1, self.n_frames_skip)) == 0
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_decay(self) -> float:
        """Sample the effective spring_decay for the current time_active."""
        if self.decay_mode == "none":
            return 1.0  # no decay — stress never reduces
        if self.decay_mode == "constant" or not self.decay_curve:
            return self._base_spring_decay
        # CURVE: piecewise-linear interpolation
        t = self._time_active
        curve = self.decay_curve
        if t <= curve[0][0]:
            return curve[0][1]
        if t >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            t0, v0 = curve[i]
            t1, v1 = curve[i + 1]
            if t0 <= t <= t1:
                alpha = (t - t0) / max(1e-9, t1 - t0)
                return v0 + (v1 - v0) * alpha
        return self._base_spring_decay

    @property
    def is_active(self) -> bool:
        return self.state != SimState.STATIC or self.sim_mode == "always_on"

    @property
    def time_active(self) -> float:
        return self._time_active


class SimFrequencyBudget:
    """System-wide frame budget for BUDGET_DRIVEN sim frequency.

    Each frame, the scene calls allocate_budget(budget_ms). Controllers
    with budget_driven frequency call request_slot() to check if they
    can dispatch. Higher priority entities get slots first.

    Typical usage: scene allocates 2ms per frame; 10 entities share it.
    High-priority (recently collided) entities dispatch every frame;
    background entities skip frames.
    """

    def __init__(self) -> None:
        self._budget_ms: float = 2.0
        self._used_ms: float = 0.0
        self._cost_per_dispatch_ms: float = 0.1  # estimated GPU cost per entity

    def allocate_budget(self, budget_ms: float) -> None:
        """Call once per frame before any request_slot() calls."""
        self._budget_ms = budget_ms
        self._used_ms = 0.0

    def request_slot(self, priority: float = 1.0) -> bool:
        """Return True if this entity can dispatch this frame.

        priority: 0..1, higher = more likely to get a slot.
        Low-priority entities are skipped when budget is exhausted.
        """
        if self._used_ms + self._cost_per_dispatch_ms <= self._budget_ms * priority:
            self._used_ms += self._cost_per_dispatch_ms
            return True
        return False

    @property
    def remaining_ms(self) -> float:
        return max(0.0, self._budget_ms - self._used_ms)
