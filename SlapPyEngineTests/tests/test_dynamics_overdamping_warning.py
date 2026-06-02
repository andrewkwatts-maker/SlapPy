"""Runtime warning for the XPBD per-iteration damping × iteration-count footgun.

XPBD position damping is applied per inner solver iteration; the effective
per-step attenuation is ``1 - (1 - damping)^iters``. The default
``World.solver_iterations = 8`` combined with even modest ``damping`` values
quickly drives that effective damping near 1, silently turning oscillating
springs into stiff welds. The ``hello_spring`` demo (commit 0a799a6) hit this
with ``damping=0.01, iters=8`` (effective ~7.7 %) being subtle enough to miss
but ``iters=12`` would already exceed the threshold for many spring kits.

These tests pin the diagnostic behaviour:

* :func:`estimate_effective_damping` returns the algebraic critical value.
* :meth:`World.step` emits a ``RuntimeWarning`` on first invocation when any
  spring / distance joint exceeds the threshold.
* The warning fires *once* per ``(joint id, iters, damping)`` tuple even when
  ``step`` is called repeatedly.
* Authors can opt out by setting ``World.warn_overdamping = False``.
* Safe combinations stay silent.
"""
from __future__ import annotations

import warnings

import pytest

from slappyengine.dynamics import (
    OVERDAMPING_THRESHOLD,
    World,
    estimate_effective_damping,
    make_spring,
)
from slappyengine.dynamics.world import _reset_warning_cache


@pytest.fixture(autouse=True)
def _clear_overdamp_warning_cache():
    """Reset the process-wide throttle so each test observes the warning.

    ``World._check_overdamping`` deduplicates by
    ``(kind, damping, iters)`` across the entire interpreter to keep
    demo smoke tests quiet — without this fixture a later test sharing
    the same configuration as an earlier one would silently observe
    zero warnings.
    """
    _reset_warning_cache()
    yield
    _reset_warning_cache()


# ---------------------------------------------------------------------------
# estimate_effective_damping pure-math contract
# ---------------------------------------------------------------------------


def test_effective_damping_critical_threshold():
    """``damping=0.5, iters=4`` is well past critical: effective >= 0.93."""
    eff = estimate_effective_damping(0.5, 4)
    # 1 - 0.5^4 = 1 - 0.0625 = 0.9375
    assert eff >= 0.93, f"expected >= 0.93, got {eff:.4f}"
    assert eff <= 1.0


def test_effective_damping_zero_is_zero():
    assert estimate_effective_damping(0.0, 8) == 0.0


def test_effective_damping_iters_one_is_identity():
    assert estimate_effective_damping(0.37, 1) == pytest.approx(0.37)


def test_effective_damping_clamps_negative_damping():
    assert estimate_effective_damping(-0.1, 8) == 0.0


def test_effective_damping_clamps_iters_below_one():
    # Solver itself uses max(1, iters); diagnostics should mirror that.
    assert estimate_effective_damping(0.3, 0) == pytest.approx(0.3)
    assert estimate_effective_damping(0.3, -5) == pytest.approx(0.3)


def test_effective_damping_hello_spring_safe_case():
    """Documents the hello_spring workaround: damping=0.01 + iters=1 is safe."""
    # Default solver_iterations=8 path -- subtle but well below the warn line.
    eff_default = estimate_effective_damping(0.01, 8)
    assert eff_default == pytest.approx(1.0 - 0.99**8)
    assert eff_default < OVERDAMPING_THRESHOLD
    # The hello_spring iters=1 workaround.
    eff_workaround = estimate_effective_damping(0.01, 1)
    assert eff_workaround == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# World.step warning behaviour
# ---------------------------------------------------------------------------


def _build_world(damping: float, iters: int) -> World:
    """Build a 2-node world with a single spring between them."""
    w = World(gravity=(0.0, 0.0))
    w.solver_iterations = iters
    w.add_node((0.0, 0.0), mass=0.0)
    w.add_node((1.2, 0.0), mass=1.0)
    w.add_joint(make_spring(0, 1, rest_length=1.0, stiffness=400.0, damping=damping))
    return w


def test_warning_fires_for_overdamped_spring():
    """damping=0.5, iters=4 → effective ≈ 0.94, well above 0.5: warn."""
    w = _build_world(damping=0.5, iters=4)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert len(overdamp) == 1, (
        f"expected one over-damp RuntimeWarning, got "
        f"{[str(r.message) for r in caught]}"
    )
    msg = str(overdamp[0].message)
    # Message must call out the joint id, the iteration count, and the damping.
    assert "iterations" in msg or "solver_iterations" in msg
    assert "0.5" in msg
    assert "4" in msg


def test_no_warning_for_safe_combination():
    """damping=0.01, iters=8 → effective ≈ 0.077, below 0.5: silent."""
    w = _build_world(damping=0.01, iters=8)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(5):
            w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert overdamp == [], (
        f"safe combination must not warn; got {[str(r.message) for r in overdamp]}"
    )


def test_warning_fires_once_per_combination():
    """Repeated ``step`` calls must not spam the warning."""
    w = _build_world(damping=0.5, iters=4)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(100):
            w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert len(overdamp) == 1, (
        f"expected exactly one warning across 100 steps, got {len(overdamp)}"
    )


def test_warn_overdamping_false_suppresses():
    """``world.warn_overdamping = False`` silences the diagnostic."""
    w = _build_world(damping=0.5, iters=4)
    w.warn_overdamping = False
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(10):
            w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert overdamp == [], (
        f"warn_overdamping=False must suppress all over-damp warnings; "
        f"got {[str(r.message) for r in overdamp]}"
    )


# ---------------------------------------------------------------------------
# Regression coverage: changing solver_iterations re-arms the warning
# ---------------------------------------------------------------------------


def test_warning_re_arms_when_iters_change():
    """Changing ``solver_iterations`` should retrigger the check.

    The dedup key includes the iteration count, so a configuration change
    that pushes a previously safe joint into the over-damped region is
    surfaced rather than silently masked by the cache.
    """
    w = _build_world(damping=0.1, iters=4)
    # iters=4, damping=0.1 → effective = 1 - 0.9^4 = 0.3439 — safe.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.step(1.0 / 240.0)
    assert all(
        "over-damp" not in str(r.message).lower() for r in caught
    ), "iters=4 damping=0.1 should not warn"

    # Bump iters; effective shoots up to 1 - 0.9^32 ≈ 0.966.
    w.solver_iterations = 32
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert len(overdamp) == 1, (
        f"raising iters into the over-damp band must re-warn; "
        f"got {[str(r.message) for r in caught]}"
    )


# ---------------------------------------------------------------------------
# Process-wide throttle: same (kind, damping, iters) only warns once even
# across 50 joints / multiple worlds (regression for the 71-warning floor
# seen during v0.3 sprint G demo smoke tests).
# ---------------------------------------------------------------------------


def test_warning_throttled_across_many_joints():
    """50 joints with the same (kind, damping, iters) emit at most one warning."""
    w = World(gravity=(0.0, 0.0))
    w.solver_iterations = 4
    # Anchor.
    w.add_node((0.0, 0.0), mass=0.0)
    for i in range(50):
        w.add_node((1.0 + 0.01 * i, 0.0), mass=1.0)
        w.add_joint(
            make_spring(0, i + 1, rest_length=1.0, stiffness=400.0, damping=0.5)
        )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(3):
            w.step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert len(overdamp) <= 1, (
        f"50 identical joints should yield at most one over-damp warning; "
        f"got {len(overdamp)}: {[str(r.message) for r in overdamp]}"
    )


def test_warning_throttled_across_multiple_worlds():
    """Two distinct Worlds with the same key share the throttle."""
    def build(damping: float, iters: int) -> World:
        w = World(gravity=(0.0, 0.0))
        w.solver_iterations = iters
        w.add_node((0.0, 0.0), mass=0.0)
        w.add_node((1.2, 0.0), mass=1.0)
        w.add_joint(
            make_spring(0, 1, rest_length=1.0, stiffness=400.0, damping=damping)
        )
        return w

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(5):
            build(damping=0.5, iters=4).step(1.0 / 240.0)
    overdamp = [
        rec for rec in caught
        if issubclass(rec.category, RuntimeWarning)
        and "over-damp" in str(rec.message).lower()
    ]
    assert len(overdamp) == 1, (
        f"5 worlds with identical (kind, damping, iters) must produce "
        f"exactly one warning; got {len(overdamp)}"
    )
