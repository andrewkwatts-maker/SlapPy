"""Spatial-hash acceleration tests for :class:`slappyengine.zones.ZoneManager`.

Covers the perf-zones-spatial-hash sprint:

* Speedup at 1000 entities / 50 zones is at least 3x on this hardware.
* The spatial-hash path emits exactly the same enter/exit events as
  the linear scan on a non-trivial workload.
* Edge cases: zero entities, zones at negative coordinates, and adding
  zones after the first :meth:`update` (the index must rebuild).

The existing :mod:`tests.test_hardening_zones` and
:mod:`python.tests.test_zones_primitive` suites continue to be the
source of truth for input validation and the base zone surface — these
tests focus on the acceleration layer.
"""
from __future__ import annotations

import random
import statistics
import time

import pytest

from slappyengine.zones import RectZone, ZoneManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORLD = 100.0


def _build_zones(
    n: int, rng: random.Random, world: float = WORLD,
) -> list[RectZone]:
    """Generate *n* small zones scattered across a *world*-sided square."""
    zones: list[RectZone] = []
    for i in range(n):
        w = rng.uniform(4.0, 12.0)
        h = rng.uniform(4.0, 12.0)
        x = rng.uniform(0.0, world - w)
        y = rng.uniform(0.0, world - h)
        zones.append(RectZone(name=f"z{i}", x=x, y=y, w=w, h=h))
    return zones


def _scatter(
    n: int, rng: random.Random, world: float = WORLD,
) -> dict[int, tuple[float, float]]:
    return {
        i: (rng.uniform(0.0, world), rng.uniform(0.0, world))
        for i in range(n)
    }


def _record_events(
    mgr: ZoneManager, zones: list[RectZone],
) -> list[tuple[str, str, int]]:
    """Wire enter/exit callbacks that append to a shared event log."""
    log: list[tuple[str, str, int]] = []
    for zone in zones:
        zname = zone.name
        zone.on_enter = lambda eid, _z=zname: log.append(("enter", _z, eid))
        zone.on_exit = lambda eid, _z=zname: log.append(("exit", _z, eid))
        mgr.add(zone)
    return log


def _normalise(events: list[tuple[str, str, int]]) -> set[tuple[str, str, int]]:
    """Compare events as a set per frame to ignore set-iteration order."""
    return set(events)


# ---------------------------------------------------------------------------
# Speedup at 1000 entities / 50 zones
# ---------------------------------------------------------------------------


def test_spatial_hash_speedup_at_1000_entities():
    """Spatial hash is at least 3x faster than linear scan at 1000/50."""
    rng_zones = random.Random(0x5EED1)
    rng_pos = random.Random(0x5EED2)

    # Identical workload across both managers — same zone layout, same
    # entity positions — so the only variable is the index.
    zones_a = _build_zones(50, rng_zones)
    rng_zones = random.Random(0x5EED1)
    zones_b = _build_zones(50, rng_zones)
    positions = _scatter(1000, rng_pos)

    mgr_linear = ZoneManager()
    for z in zones_a:
        mgr_linear.add(z)
    mgr_linear.enable_spatial_hash(False)

    mgr_hash = ZoneManager()
    for z in zones_b:
        mgr_hash.add(z)

    # Warm-up one frame so first-frame enter events don't pollute the
    # timing samples.
    mgr_linear.update(positions)
    mgr_hash.update(positions)

    def _median_us(mgr: ZoneManager, frames: int = 40) -> float:
        samples = []
        for _ in range(frames):
            t0 = time.perf_counter()
            mgr.update(positions)
            t1 = time.perf_counter()
            samples.append((t1 - t0) * 1e6)
        return statistics.median(samples)

    linear_us = _median_us(mgr_linear)
    hash_us = _median_us(mgr_hash)

    speedup = linear_us / hash_us
    assert speedup >= 3.0, (
        f"spatial hash speedup {speedup:.2f}x < 3.0x required "
        f"(linear={linear_us:.1f}us, hash={hash_us:.1f}us)"
    )


# ---------------------------------------------------------------------------
# Byte-for-byte parity
# ---------------------------------------------------------------------------


def test_spatial_hash_events_match_linear_scan():
    """Spatial hash and linear scan emit identical enter/exit events.

    Drives both managers with the same zone layout + per-frame entity
    positions across 20 frames of motion, recording events on both
    sides. Per-frame event sets must be equal.
    """
    rng = random.Random(0x4EC0FA17)

    # Same zone seed → byte-identical zones on both managers.
    rng_zones_a = random.Random(0xAAAA)
    rng_zones_b = random.Random(0xAAAA)
    zones_a = _build_zones(20, rng_zones_a)
    zones_b = _build_zones(20, rng_zones_b)

    mgr_linear = ZoneManager()
    mgr_linear.enable_spatial_hash(False)
    log_linear = _record_events(mgr_linear, zones_a)

    mgr_hash = ZoneManager()
    log_hash = _record_events(mgr_hash, zones_b)

    n_entities = 200
    positions: dict[int, tuple[float, float]] = {
        i: (rng.uniform(0.0, WORLD), rng.uniform(0.0, WORLD))
        for i in range(n_entities)
    }

    for _frame in range(20):
        # Mutate ~half the entities each frame so we get a mix of
        # enter / exit / no-change events.
        for eid in list(positions):
            if rng.random() < 0.5:
                positions[eid] = (
                    rng.uniform(0.0, WORLD), rng.uniform(0.0, WORLD),
                )

        # Snapshot log lengths so we can compare per-frame deltas.
        pre_linear = len(log_linear)
        pre_hash = len(log_hash)
        mgr_linear.update(positions)
        mgr_hash.update(positions)

        frame_linear = _normalise(log_linear[pre_linear:])
        frame_hash = _normalise(log_hash[pre_hash:])
        assert frame_linear == frame_hash, (
            f"frame {_frame}: spatial-hash events diverged from linear scan; "
            f"linear-only={frame_linear - frame_hash}, "
            f"hash-only={frame_hash - frame_linear}"
        )

    # Also verify final per-zone occupancy parity.
    for z in zones_a:
        assert mgr_linear.occupancy(z.name) == mgr_hash.occupancy(z.name), (
            f"final occupancy for {z.name!r} diverged"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_spatial_hash_zero_entities():
    """Empty positions dict is a no-op on the spatial-hash path."""
    mgr = ZoneManager()
    enter_log: list = []
    mgr.add(RectZone(
        name="z", x=0.0, y=0.0, w=10.0, h=10.0,
        on_enter=enter_log.append,
    ))
    # Must not raise + must not fire any events.
    mgr.update({})
    assert enter_log == []
    assert mgr.occupancy("z") == set()


def test_spatial_hash_zero_entities_iterable():
    """Empty iterable is also a no-op."""
    mgr = ZoneManager()
    mgr.add(RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0))
    mgr.update([])
    assert mgr.occupancy("z") == set()


def test_spatial_hash_zone_outside_grid_bounds():
    """Zones (and entities) at negative coordinates still work.

    Python's ``//`` is true floor-div, so negative coordinates produce
    negative cell indices that are valid dict keys — no special-case
    needed, but we lock the behaviour in here.
    """
    mgr = ZoneManager()
    log: list = []
    mgr.add(RectZone(
        name="negz",
        x=-20.0, y=-15.0, w=10.0, h=10.0,
        on_enter=lambda eid: log.append(("enter", eid)),
        on_exit=lambda eid: log.append(("exit", eid)),
    ))

    # Entity inside the zone.
    mgr.update({"p": (-15.0, -10.0)})
    assert log == [("enter", "p")]
    assert mgr.occupancy("negz") == {"p"}

    # Entity moves outside.
    log.clear()
    mgr.update({"p": (50.0, 50.0)})
    assert log == [("exit", "p")]
    assert mgr.occupancy("negz") == set()


def test_spatial_hash_mixed_negative_and_positive_zones():
    """Mix of negative-coord and positive-coord zones in one manager."""
    mgr = ZoneManager()
    mgr.add(RectZone(name="neg", x=-10.0, y=-10.0, w=5.0, h=5.0))
    mgr.add(RectZone(name="pos", x=50.0, y=50.0, w=5.0, h=5.0))

    mgr.update({"a": (-8.0, -8.0), "b": (52.0, 52.0), "c": (0.0, 0.0)})
    assert mgr.occupancy("neg") == {"a"}
    assert mgr.occupancy("pos") == {"b"}


def test_spatial_hash_dynamic_resize():
    """Adding a zone after the first :meth:`update` rebuilds the index.

    Without dirty-flag tracking, the new zone would be invisible to
    subsequent updates (no cell range computed for it).
    """
    mgr = ZoneManager()
    enter_log: list = []
    mgr.add(RectZone(
        name="initial",
        x=0.0, y=0.0, w=10.0, h=10.0,
        on_enter=lambda eid: enter_log.append(("initial", eid)),
    ))

    # First update bakes the index covering only "initial".
    mgr.update({"p": (5.0, 5.0)})
    assert enter_log == [("initial", "p")]

    # Add a brand-new zone elsewhere.
    enter_log.clear()
    mgr.add(RectZone(
        name="added",
        x=50.0, y=50.0, w=10.0, h=10.0,
        on_enter=lambda eid: enter_log.append(("added", eid)),
    ))

    # Drop an entity into the new zone — must fire enter.
    mgr.update({"q": (55.0, 55.0)})
    assert ("added", "q") in enter_log


def test_spatial_hash_dynamic_remove():
    """Removing a zone doesn't leave stale entries in the index."""
    mgr = ZoneManager()
    mgr.add(RectZone(name="a", x=0.0, y=0.0, w=10.0, h=10.0))
    mgr.add(RectZone(name="b", x=20.0, y=20.0, w=10.0, h=10.0))
    mgr.update({"e": (5.0, 5.0)})
    assert mgr.occupancy("a") == {"e"}

    assert mgr.remove("a")
    # The removed zone must not be queried any more.
    mgr.update({"e": (25.0, 25.0)})
    assert mgr.occupancy("b") == {"e"}
    assert mgr.get("a") is None


# ---------------------------------------------------------------------------
# Opt-out toggle
# ---------------------------------------------------------------------------


def test_enable_spatial_hash_default_is_on():
    mgr = ZoneManager()
    assert mgr.spatial_hash_enabled


def test_enable_spatial_hash_can_toggle_off_and_back_on():
    mgr = ZoneManager()
    mgr.enable_spatial_hash(False)
    assert not mgr.spatial_hash_enabled
    mgr.enable_spatial_hash(True)
    assert mgr.spatial_hash_enabled


def test_enable_spatial_hash_rejects_non_bool():
    mgr = ZoneManager()
    with pytest.raises(TypeError, match="enable_spatial_hash"):
        mgr.enable_spatial_hash("yes")  # type: ignore[arg-type]


def test_toggle_mid_session_preserves_occupancy_set_state():
    """Flipping the toggle preserves :meth:`occupancy` (state lives on
    the manager, not on the active path).
    """
    mgr = ZoneManager()
    mgr.add(RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0))
    mgr.update({"p": (5.0, 5.0)})
    assert mgr.occupancy("z") == {"p"}

    mgr.enable_spatial_hash(False)
    # No update yet — set is preserved.
    assert mgr.occupancy("z") == {"p"}
    # Linear scan now sees the same entity, so no exit/enter fires.
    log: list = []
    mgr.get("z").on_exit = lambda eid: log.append(("exit", eid))  # type: ignore[union-attr]
    mgr.update({"p": (5.0, 5.0)})
    assert log == []
