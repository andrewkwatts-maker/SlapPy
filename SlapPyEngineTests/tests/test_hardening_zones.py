"""Input-validation tests for the public ``slappyengine.zones`` API."""
from __future__ import annotations

import pytest

from slappyengine.zones import RectZone, ThresholdZone, ZoneManager


# ---------------------------------------------------------------------------
# RectZone.__post_init__
# ---------------------------------------------------------------------------


def test_rectzone_rejects_negative_width():
    with pytest.raises(ValueError, match="RectZone: w"):
        RectZone(name="z", x=0.0, y=0.0, w=-1.0, h=2.0)


def test_rectzone_rejects_zero_width():
    with pytest.raises(ValueError, match="RectZone: w"):
        RectZone(name="z", x=0.0, y=0.0, w=0.0, h=2.0)


def test_rectzone_rejects_negative_height():
    with pytest.raises(ValueError, match="RectZone: h"):
        RectZone(name="z", x=0.0, y=0.0, w=2.0, h=-3.0)


def test_rectzone_rejects_zero_height():
    with pytest.raises(ValueError, match="RectZone: h"):
        RectZone(name="z", x=0.0, y=0.0, w=2.0, h=0.0)


def test_rectzone_rejects_non_numeric_x():
    with pytest.raises(TypeError, match="RectZone: x"):
        RectZone(name="z", x="zero", y=0.0, w=2.0, h=2.0)  # type: ignore[arg-type]


def test_rectzone_rejects_nan_y():
    with pytest.raises(ValueError, match="RectZone: y"):
        RectZone(name="z", x=0.0, y=float("nan"), w=2.0, h=2.0)


def test_rectzone_rejects_inf_w():
    with pytest.raises(ValueError, match="RectZone: w"):
        RectZone(name="z", x=0.0, y=0.0, w=float("inf"), h=2.0)


# ---------------------------------------------------------------------------
# ThresholdZone.__post_init__
# ---------------------------------------------------------------------------


def test_thresholdzone_rejects_nan_threshold():
    with pytest.raises(ValueError, match="ThresholdZone: threshold"):
        ThresholdZone(
            name="z", x=0.0, y=0.0, w=2.0, h=2.0,
            threshold=float("nan"),
        )


def test_thresholdzone_rejects_inf_threshold():
    with pytest.raises(ValueError, match="ThresholdZone: threshold"):
        ThresholdZone(
            name="z", x=0.0, y=0.0, w=2.0, h=2.0,
            threshold=float("inf"),
        )


def test_thresholdzone_rejects_negative_hysteresis():
    with pytest.raises(ValueError, match="ThresholdZone: hysteresis"):
        ThresholdZone(
            name="z", x=0.0, y=0.0, w=2.0, h=2.0,
            threshold=0.5, hysteresis=-0.1,
        )


def test_thresholdzone_still_rejects_zero_width():
    # Inherited rect validation must fire too.
    with pytest.raises(ValueError, match="RectZone: w"):
        ThresholdZone(
            name="z", x=0.0, y=0.0, w=0.0, h=2.0, threshold=0.5,
        )


# ---------------------------------------------------------------------------
# ZoneManager.update
# ---------------------------------------------------------------------------


def test_zonemanager_update_rejects_scalar():
    mgr = ZoneManager()
    mgr.add(RectZone(name="z", x=0.0, y=0.0, w=2.0, h=2.0))
    with pytest.raises(TypeError, match="positions"):
        mgr.update(42)  # type: ignore[arg-type]


def test_zonemanager_update_rejects_string():
    mgr = ZoneManager()
    mgr.add(RectZone(name="z", x=0.0, y=0.0, w=2.0, h=2.0))
    with pytest.raises(TypeError, match="positions"):
        mgr.update("not-a-dict")  # type: ignore[arg-type]


def test_zonemanager_update_rejects_none():
    mgr = ZoneManager()
    mgr.add(RectZone(name="z", x=0.0, y=0.0, w=2.0, h=2.0))
    with pytest.raises(TypeError, match="positions"):
        mgr.update(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Positive sanity — validated builders still compose a working manager.
# ---------------------------------------------------------------------------


def test_positive_rectzone_accepts_int_coords():
    # int should be accepted (Python promotes via real-number isinstance).
    z = RectZone(name="z", x=0, y=0, w=10, h=10)
    assert z.contains_point(5, 5)


def test_positive_thresholdzone_constructs():
    z = ThresholdZone(
        name="hood", x=0.0, y=0.0, w=4.0, h=4.0,
        threshold=0.1, hysteresis=0.05,
    )
    assert z.threshold == pytest.approx(0.1)
    assert z.hysteresis == pytest.approx(0.05)


def test_positive_zonemanager_dict_input():
    mgr = ZoneManager()
    z = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
    mgr.add(z)
    mgr.update({"p": (5.0, 5.0)})
    assert "p" in mgr.occupancy("z")


def test_positive_zonemanager_iterable_input():
    mgr = ZoneManager()
    z = RectZone(name="z", x=0.0, y=0.0, w=10.0, h=10.0)
    mgr.add(z)
    mgr.update([("p", (5.0, 5.0))])
    assert "p" in mgr.occupancy("z")
