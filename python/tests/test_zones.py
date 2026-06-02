"""Tests for slappyengine.zones — generic rectangular zones with integrity probes."""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from slappyengine.event_bus import global_bus, subscribe, unsubscribe
from slappyengine.zones import (
    Zone,
    ZoneManager,
    alpha_image_probe,
    fluid_density_probe,
    softbody_beam_probe,
)


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


@pytest.fixture(autouse=True)
def _clear_bus():
    global_bus.clear()
    yield
    global_bus.clear()


def _make_image(h: int = 32, w: int = 32, alpha: int = 255) -> np.ndarray:
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[..., 3] = alpha
    return img


# ── Basic manager behaviour ─────────────────────────────────────────────────


def test_add_and_query_rect_zone():
    mgr = ZoneManager()
    mgr.add_rect("bumper", x=0, y=0, w=8, h=8, threshold=0.3)
    assert "bumper" in mgr.names()
    assert mgr.integrity("bumper") == 1.0
    assert mgr.is_destroyed("bumper") is False


def test_remove_zone():
    mgr = ZoneManager()
    mgr.add_rect("a", 0, 0, 4, 4)
    mgr.add_rect("b", 4, 0, 4, 4)
    assert mgr.remove("a") is True
    assert mgr.names() == ["b"]
    assert mgr.remove("nope") is False


# ── Alpha-image probe ───────────────────────────────────────────────────────


def test_alpha_image_probe_full_alpha_is_full_integrity():
    img = _make_image(alpha=255)
    mgr = ZoneManager()
    z = mgr.add_rect("z", x=0, y=0, w=10, h=10, threshold=0.5)
    mgr.update(alpha_image_probe(img))
    assert mgr.integrity("z") == pytest.approx(1.0)
    assert not mgr.is_destroyed("z")


def test_alpha_image_probe_zero_alpha_destroys():
    img = _make_image(alpha=0)
    mgr = ZoneManager()
    mgr.add_rect("z", x=0, y=0, w=10, h=10, threshold=0.5,
                 on_destroy="Test.Destroyed")
    events: list = []
    handle = subscribe("Test.Destroyed", lambda evt: events.append(evt))
    try:
        mgr.update(alpha_image_probe(img))
    finally:
        unsubscribe(handle)
    assert mgr.integrity("z") == pytest.approx(0.0)
    assert mgr.is_destroyed("z")
    assert len(events) == 1
    assert events[0].zone == "z"


def test_destroy_event_fires_only_once_until_recovery():
    img = _make_image(alpha=0)
    mgr = ZoneManager()
    mgr.add_rect("z", 0, 0, 10, 10, threshold=0.5, on_destroy="Test.Once")
    events: list = []
    handle = subscribe("Test.Once", lambda evt: events.append(evt))
    try:
        # Same destroyed-state across multiple frames → one event.
        for _ in range(3):
            mgr.update(alpha_image_probe(img))
        assert len(events) == 1

        # Repair to integrity 1.0 (re-arms)
        img.fill(255)
        img[..., 3] = 255
        mgr.update(alpha_image_probe(img))
        assert not mgr.is_destroyed("z")

        # Damage again → second event.
        img[..., 3] = 0
        mgr.update(alpha_image_probe(img))
        assert len(events) == 2
    finally:
        unsubscribe(handle)


def test_alpha_probe_with_mask():
    """Mask restricts which pixels of the rect contribute to the probe."""
    img = _make_image(alpha=255)
    img[2:4, 2:4, 3] = 0  # punch a 2×2 hole
    mgr = ZoneManager()
    # Mask: only cover the 2×2 hole region. Integrity should be 0.
    mask = np.ones((6, 6), dtype=np.uint8)
    mask[:2, :2] = 0
    mask[4:, 4:] = 0
    mgr.add_rect("z", x=2, y=2, w=2, h=2, threshold=0.5,
                 mask=np.ones((2, 2), dtype=np.uint8))
    mgr.update(alpha_image_probe(img))
    assert mgr.integrity("z") == pytest.approx(0.0)


# ── Softbody beam probe ─────────────────────────────────────────────────────


def test_softbody_beam_probe_intact_body_is_full_integrity():
    from slappyengine.softbody import SoftBodyWorld, make_lattice_body
    w = SoftBodyWorld()
    meta = make_lattice_body(w, "steel", width_cells=4, height_cells=4,
                             cell_size=0.1, position=(0.0, 0.0))
    mgr = ZoneManager()
    # Zone covers the whole lattice
    mgr.add_rect("body", x=-1, y=-1, w=3, h=3, threshold=0.5)
    mgr.update(softbody_beam_probe(w, meta))
    assert mgr.integrity("body") == pytest.approx(1.0)


def test_softbody_beam_probe_breaks_drop_integrity():
    from slappyengine.softbody import SoftBodyWorld, make_lattice_body
    w = SoftBodyWorld()
    meta = make_lattice_body(w, "steel", width_cells=4, height_cells=4,
                             cell_size=0.1, position=(0.0, 0.0))
    # Break half the beams in this body
    bs, be = meta.beam_slice
    n_body_beams = be - bs
    w.beams.broken[bs : bs + n_body_beams // 2] = True

    mgr = ZoneManager()
    mgr.add_rect("body", x=-1, y=-1, w=3, h=3, threshold=0.6)
    mgr.update(softbody_beam_probe(w, meta))
    integ = mgr.integrity("body")
    assert 0.3 < integ < 0.7, f"expected ~0.5 integrity, got {integ:.3f}"


# ── Fluid density probe ─────────────────────────────────────────────────────


def test_fluid_density_probe_empty_zone_is_dry():
    from slappyengine.fluid import FluidWorld
    fw = FluidWorld()
    mgr = ZoneManager()
    mgr.add_rect("dry", x=0, y=0, w=2, h=2, threshold=0.5)
    mgr.update(fluid_density_probe(fw))
    assert mgr.integrity("dry") == pytest.approx(1.0)


def test_fluid_density_probe_wet_zone_drops_integrity():
    from slappyengine.fluid import FluidWorld
    fw = FluidWorld()
    fw.add_block_of_particles(
        "water", nx=8, ny=8, spacing=0.05,
        origin=(0.0, 0.0), jitter=0.0,
    )
    mgr = ZoneManager()
    # Zone over the particle block: many particles → integrity drops.
    mgr.add_rect("wet", x=0, y=0, w=1, h=1, threshold=0.5)
    mgr.update(fluid_density_probe(fw))
    assert mgr.integrity("wet") < 1.0


# ── Reset ───────────────────────────────────────────────────────────────────


def test_reset_clears_destroyed_flag_and_restores_integrity():
    img = _make_image(alpha=0)
    mgr = ZoneManager()
    mgr.add_rect("z", 0, 0, 10, 10, threshold=0.5)
    mgr.update(alpha_image_probe(img))
    assert mgr.is_destroyed("z")
    mgr.reset()
    assert not mgr.is_destroyed("z")
    assert mgr.integrity("z") == 1.0
