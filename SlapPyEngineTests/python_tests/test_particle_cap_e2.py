"""Sprint E2-E — Mobile particle cap enforcement.

Verifies that :meth:`GpuParticleSystem.set_mobile_cap` clamps ``max_particles``
to :data:`MOBILE_MAX_PARTICLES` (4096) without raising the value for systems
that are already within budget.

These tests intentionally avoid spinning up a real wgpu device: the cap logic
itself is pure Python.  We exercise it via a tiny dummy-context shim plus the
static :py:meth:`GpuParticleSystem._clamp_to_mobile_cap` helper.
"""
from __future__ import annotations

import pytest

from slappyengine.particles import (
    MOBILE_MAX_PARTICLES,
    GpuParticleSystem,
)


# ---------------------------------------------------------------------------
# Pure-Python clamp math (no GPU required)
# ---------------------------------------------------------------------------

def test_mobile_cap_constant():
    assert MOBILE_MAX_PARTICLES == 4096


def test_clamp_helper_caps_over_budget():
    assert GpuParticleSystem._clamp_to_mobile_cap(8000) == 4096
    assert GpuParticleSystem._clamp_to_mobile_cap(4097) == 4096
    assert GpuParticleSystem._clamp_to_mobile_cap(1_000_000) == 4096


def test_clamp_helper_preserves_under_budget():
    assert GpuParticleSystem._clamp_to_mobile_cap(2000) == 2000
    assert GpuParticleSystem._clamp_to_mobile_cap(4096) == 4096
    assert GpuParticleSystem._clamp_to_mobile_cap(1) == 1
    assert GpuParticleSystem._clamp_to_mobile_cap(0) == 0


# ---------------------------------------------------------------------------
# Integration via GpuParticleSystem.set_mobile_cap (with stubbed GPU ctx)
# ---------------------------------------------------------------------------

class _DummyBuffer:
    def __init__(self, size: int):
        self.size = size


class _DummyDevice:
    def create_buffer(self, *, size, usage, label=""):  # noqa: ARG002
        return _DummyBuffer(size)


class _DummyContext:
    def __init__(self):
        self.device = _DummyDevice()
        self.queue = None


def _make_system(max_particles: int) -> GpuParticleSystem:
    """Construct a GpuParticleSystem against a dummy GPU context.

    If real-wgpu construction fails in this environment, the test is skipped
    rather than failing — the pure-Python tests above already cover the math.
    """
    try:
        return GpuParticleSystem(_DummyContext(), max_particles=max_particles)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"GpuParticleSystem requires GPU init: {exc}")


def test_set_mobile_cap_clamps_over_budget():
    ps = _make_system(max_particles=8000)
    assert ps.max_particles == 8000
    ps.set_mobile_cap(True)
    assert ps.max_particles == MOBILE_MAX_PARTICLES == 4096
    assert ps.get_active_count() == 4096
    # Pipeline must be invalidated so it rebuilds against the new buffer.
    assert ps._pipeline is None
    assert ps._bind_group is None


def test_set_mobile_cap_no_op_under_budget():
    ps = _make_system(max_particles=2000)
    assert ps.max_particles == 2000
    ps.set_mobile_cap(True)
    assert ps.max_particles == 2000  # never raised
    assert ps.get_active_count() == 2000


def test_set_mobile_cap_disabled_is_no_op():
    ps = _make_system(max_particles=8000)
    ps.set_mobile_cap(False)
    assert ps.max_particles == 8000


def test_set_mobile_cap_exact_boundary():
    ps = _make_system(max_particles=MOBILE_MAX_PARTICLES)
    ps.set_mobile_cap(True)
    assert ps.max_particles == MOBILE_MAX_PARTICLES
