"""Tests for pharos_engine.zones — generic zone primitive.

Covers the Phase B contract:

* :class:`RectZone.contains_point` for inside / outside / boundary points.
* :class:`ThresholdZone` fires ``on_threshold`` exactly once per crossing
  and re-arms after recovery.
* :class:`ZoneManager.update` emits ``on_enter`` / ``on_exit`` correctly
  for entities moving across zone boundaries between frames.
* Material-tag round-trips through the data model.
* The public surface is reachable via ``from pharos_engine import zones``.
"""
from __future__ import annotations

import pytest

from pharos_engine.zones import RectZone, ThresholdZone, ZoneManager


# ── RectZone geometry ─────────────────────────────────────────────────────


class TestRectZoneContainsPoint:
    """RectZone.contains_point — half-open rect inside/outside checks."""

    def test_point_inside_rect(self):
        zone = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
        assert zone.contains_point(5.0, 5.0)

    def test_point_on_top_left_corner_is_inside(self):
        # Half-open: (x, y) itself is inside.
        zone = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
        assert zone.contains_point(0.0, 0.0)

    def test_point_on_far_edge_is_outside(self):
        # Half-open: (x+w, y+h) is excluded.
        zone = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
        assert not zone.contains_point(10.0, 5.0)
        assert not zone.contains_point(5.0, 10.0)

    def test_point_outside_rect(self):
        zone = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
        assert not zone.contains_point(-1.0, 5.0)
        assert not zone.contains_point(15.0, 5.0)
        assert not zone.contains_point(5.0, -1.0)
        assert not zone.contains_point(5.0, 15.0)

    def test_rect_round_trip_setter(self):
        zone = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
        zone.rect = (2.0, 3.0, 4.0, 5.0)
        assert zone.rect == (2.0, 3.0, 4.0, 5.0)
        assert zone.contains_point(3.0, 4.0)
        assert not zone.contains_point(0.0, 0.0)


# ── ThresholdZone single-shot semantics ───────────────────────────────────


class TestThresholdZoneFiring:
    """ThresholdZone — fires on_threshold exactly once on crossing."""

    def test_fires_once_on_downward_crossing(self):
        events: list[float] = []
        zone = ThresholdZone(
            name="z", x=0.0, y=0.0, w=1.0, h=1.0,
            threshold=0.3,
            on_threshold=events.append,
        )
        mgr = ZoneManager()
        mgr.add(zone)

        mgr.update_threshold("z", 0.5)   # above — no fire
        mgr.update_threshold("z", 0.2)   # crosses — fire
        mgr.update_threshold("z", 0.1)   # still below — no second fire
        mgr.update_threshold("z", 0.05)  # even lower — still no second fire

        assert events == [0.2]
        assert mgr.is_fired("z")

    def test_rearms_after_recovery_and_fires_again(self):
        events: list[float] = []
        zone = ThresholdZone(
            name="z", x=0.0, y=0.0, w=1.0, h=1.0,
            threshold=0.3,
            hysteresis=0.05,
            on_threshold=events.append,
        )
        mgr = ZoneManager()
        mgr.add(zone)

        mgr.update_threshold("z", 0.2)   # fire #1
        mgr.update_threshold("z", 0.4)   # 0.4 > 0.3 + 0.05 → re-arm
        assert not mgr.is_fired("z")
        mgr.update_threshold("z", 0.1)   # fire #2

        assert events == [0.2, 0.1]

    def test_stays_armed_inside_hysteresis_band(self):
        events: list[float] = []
        zone = ThresholdZone(
            name="z", x=0.0, y=0.0, w=1.0, h=1.0,
            threshold=0.3,
            hysteresis=0.05,
            on_threshold=events.append,
        )
        mgr = ZoneManager()
        mgr.add(zone)

        mgr.update_threshold("z", 0.2)   # fire
        mgr.update_threshold("z", 0.33)  # inside hysteresis band → no re-arm
        mgr.update_threshold("z", 0.1)   # would have re-fired if re-armed

        assert events == [0.2]

    def test_update_threshold_no_op_for_rect_zone(self):
        # Plain RectZone — update_threshold should be silently ignored.
        mgr = ZoneManager()
        mgr.add(RectZone(name="r", x=0.0, y=0.0, w=1.0, h=1.0))
        mgr.update_threshold("r", -100.0)
        # No exception, no fired flag set.
        assert not mgr.is_fired("r")

    def test_update_threshold_unknown_zone_is_no_op(self):
        mgr = ZoneManager()
        # Should not raise.
        mgr.update_threshold("missing", 0.0)


# ── ZoneManager enter/exit dispatch ───────────────────────────────────────


class TestZoneManagerUpdate:
    """ZoneManager.update emits enter/exit events for moving entities."""

    def _make_mgr(self, log):
        zone = RectZone(
            name="pad",
            x=0.0, y=0.0, w=10.0, h=10.0,
            on_enter=lambda eid: log.append(("enter", eid)),
            on_exit=lambda eid: log.append(("exit", eid)),
        )
        mgr = ZoneManager()
        mgr.add(zone)
        return mgr

    def test_first_frame_inside_fires_enter(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update({"player": (5.0, 5.0)})
        assert log == [("enter", "player")]

    def test_no_event_when_staying_inside(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update({"player": (5.0, 5.0)})
        log.clear()
        mgr.update({"player": (6.0, 6.0)})   # still inside
        assert log == []

    def test_exit_fired_when_leaving(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update({"player": (5.0, 5.0)})
        log.clear()
        mgr.update({"player": (50.0, 50.0)})  # leaves
        assert log == [("exit", "player")]

    def test_re_enter_fires_enter_again(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update({"player": (5.0, 5.0)})    # enter
        mgr.update({"player": (50.0, 50.0)})  # exit
        log.clear()
        mgr.update({"player": (5.0, 5.0)})    # re-enter
        assert log == [("enter", "player")]

    def test_multiple_entities_tracked_independently(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update({"a": (5.0, 5.0), "b": (50.0, 50.0)})
        assert log == [("enter", "a")]
        log.clear()

        mgr.update({"a": (50.0, 50.0), "b": (5.0, 5.0)})
        # Order is set-dependent but contents should be exact.
        assert sorted(log) == sorted([("exit", "a"), ("enter", "b")])

    def test_occupancy_query_returns_current_inside_set(self):
        mgr = ZoneManager()
        mgr.add(RectZone(name="pad", x=0.0, y=0.0, w=10.0, h=10.0))
        mgr.update({"a": (5.0, 5.0), "b": (50.0, 50.0)})
        assert mgr.occupancy("pad") == {"a"}

    def test_update_accepts_iterable_of_pairs(self):
        log: list = []
        mgr = self._make_mgr(log)
        mgr.update([("p", (5.0, 5.0))])
        assert log == [("enter", "p")]


# ── Material tag round trip ───────────────────────────────────────────────


class TestMaterialRoundTrip:
    """Material tag survives through both RectZone and ThresholdZone."""

    def test_rect_zone_material_tag(self):
        zone = RectZone(name="z", x=0.0, y=0.0, w=1.0, h=1.0, material="glass")
        assert zone.material == "glass"

    def test_threshold_zone_material_tag(self):
        zone = ThresholdZone(
            name="z", x=0.0, y=0.0, w=1.0, h=1.0,
            threshold=0.5,
            material="metal",
        )
        assert zone.material == "metal"

    def test_manager_get_preserves_material(self):
        mgr = ZoneManager()
        mgr.add(RectZone(name="bumper", x=0, y=0, w=1, h=1, material="glass"))
        retrieved = mgr.get("bumper")
        assert retrieved is not None
        assert retrieved.material == "glass"

    def test_material_defaults_to_none(self):
        zone = RectZone(name="z", x=0.0, y=0.0, w=1.0, h=1.0)
        assert zone.material is None


# ── Manager bookkeeping edge cases ────────────────────────────────────────


class TestZoneManagerBookkeeping:

    def test_duplicate_zone_name_raises(self):
        mgr = ZoneManager()
        mgr.add(RectZone(name="z", x=0, y=0, w=1, h=1))
        with pytest.raises(ValueError, match="duplicate"):
            mgr.add(RectZone(name="z", x=0, y=0, w=1, h=1))

    def test_remove_returns_true_when_present(self):
        mgr = ZoneManager()
        mgr.add(RectZone(name="z", x=0, y=0, w=1, h=1))
        assert mgr.remove("z")
        assert mgr.get("z") is None

    def test_remove_returns_false_when_absent(self):
        mgr = ZoneManager()
        assert not mgr.remove("missing")

    def test_reset_clears_occupancy_and_fired_flag(self):
        mgr = ZoneManager()
        mgr.add(ThresholdZone(name="t", x=0, y=0, w=10, h=10, threshold=0.5))
        mgr.update({"p": (5, 5)})
        mgr.update_threshold("t", 0.1)
        assert mgr.occupancy("t") == {"p"}
        assert mgr.is_fired("t")

        mgr.reset()

        assert mgr.occupancy("t") == set()
        assert not mgr.is_fired("t")


# ── Public surface reachable from pharos_engine root ───────────────────────


class TestPublicSurface:
    """`from pharos_engine import zones` exposes the canonical types."""

    def test_lazy_import_via_root_package(self):
        import pharos_engine
        zones_mod = pharos_engine.zones
        assert zones_mod.RectZone is RectZone
        assert zones_mod.ThresholdZone is ThresholdZone
        assert zones_mod.ZoneManager is ZoneManager
