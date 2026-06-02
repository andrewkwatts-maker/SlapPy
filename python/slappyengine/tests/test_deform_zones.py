"""Tests for slappyengine.deform_zones — ZoneMap pixel zone tagging system."""
from __future__ import annotations
import unittest
from unittest.mock import patch, call

import numpy as np

from slappyengine.deform_zones import ZoneMap, ZoneDef


def _make_image(h: int, w: int, alpha: int = 255) -> np.ndarray:
    """Create a (h x w x 4) uint8 image with uniform alpha."""
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[:, :, :3] = 200  # arbitrary RGB
    img[:, :, 3] = alpha
    return img


class TestZoneMapCreation(unittest.TestCase):
    def test_zone_map_creates_zones(self):
        """add_rect_zone returns self for chaining; zone_names lists correct names."""
        zm = ZoneMap(128, 64)
        result = zm.add_rect_zone("front_bumper", x=0, y=16, w=20, h=32, threshold=0.4)
        self.assertIs(result, zm, "add_rect_zone should return self")
        result2 = zm.add_rect_zone("windshield", x=40, y=8, w=48, h=20, threshold=0.2)
        self.assertIs(result2, zm)
        self.assertEqual(zm.zone_names(), ["front_bumper", "windshield"])

    def test_initial_integrity_is_1(self):
        """Fresh ZoneMap reports integrity=1.0 for all zones before any update."""
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("front_bumper", x=0, y=16, w=20, h=32)
        zm.add_rect_zone("windshield", x=40, y=8, w=48, h=20)
        for name in zm.zone_names():
            self.assertAlmostEqual(zm.integrity(name), 1.0, msg=f"{name} integrity should start at 1.0")

    def test_unknown_zone_integrity_returns_1(self):
        """integrity() for an unknown zone name returns 1.0."""
        zm = ZoneMap(64, 32)
        self.assertEqual(zm.integrity("does_not_exist"), 1.0)

    def test_unknown_zone_is_destroyed_returns_false(self):
        """is_destroyed() for an unknown zone name returns False."""
        zm = ZoneMap(64, 32)
        self.assertFalse(zm.is_destroyed("does_not_exist"))


class TestZoneIntegrityFromAlpha(unittest.TestCase):
    def test_zero_alpha_region_reports_zero_integrity(self):
        """Setting alpha=0 in a zone rect causes update() to report integrity=0."""
        img = _make_image(64, 128, alpha=255)
        # Zero out the front_bumper zone rect (x=0..20, y=16..48)
        img[16:48, 0:20, 3] = 0

        zm = ZoneMap(128, 64)
        zm.add_rect_zone("front_bumper", x=0, y=16, w=20, h=32, threshold=0.5)

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertAlmostEqual(zm.integrity("front_bumper"), 0.0, places=5)

    def test_full_alpha_region_reports_full_integrity(self):
        """All-255 alpha region gives integrity~1.0."""
        img = _make_image(64, 128, alpha=255)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("windshield", x=40, y=8, w=48, h=20)

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertAlmostEqual(zm.integrity("windshield"), 1.0, places=5)

    def test_half_alpha_region_reports_half_integrity(self):
        """Alpha=128 in zone rect gives integrity ~0.5."""
        img = _make_image(64, 128, alpha=128)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("panel", x=10, y=10, w=30, h=20)

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertAlmostEqual(zm.integrity("panel"), 128.0 / 255.0, places=3)


class TestZoneDestroyEvents(unittest.TestCase):
    def test_destroy_event_fired_at_threshold(self):
        """When zone alpha drops to threshold, publish is called with correct event."""
        img = _make_image(64, 128, alpha=255)
        # Zone: x=0, y=0, w=20, h=20. Set alpha=0 → integrity=0, threshold=0.3 → should fire.
        img[0:20, 0:20, 3] = 0

        zm = ZoneMap(128, 64)
        zm.add_rect_zone(
            "bumper", x=0, y=0, w=20, h=20,
            threshold=0.3,
            on_destroy="Vehicle.BumperLost",
            material="metal",
        )

        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img, publisher="vehicle_obj")

        mock_pub.assert_called_once_with(
            "Vehicle.BumperLost",
            publisher="vehicle_obj",
            zone="bumper",
            integrity=0.0,
            material="metal",
        )

    def test_destroy_fires_once(self):
        """Calling update() twice with alpha below threshold publishes only once."""
        img = _make_image(64, 128, alpha=0)

        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=0, w=128, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")

        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)
            zm.update(img)  # second call: already destroyed, must not re-fire

        self.assertEqual(mock_pub.call_count, 1,
                         "Destroy event should fire exactly once, not on each frame below threshold")

    def test_no_event_when_above_threshold(self):
        """No publish when zone integrity stays above its threshold."""
        img = _make_image(64, 128, alpha=255)  # full integrity

        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=0, w=64, h=32, threshold=0.3)

        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)

        mock_pub.assert_not_called()


class TestZoneRepair(unittest.TestCase):
    def test_repair_resets_destroyed_flag(self):
        """After destruction, restoring alpha above threshold+0.05 clears is_destroyed."""
        # Start with zero alpha — zone destroyed
        img = _make_image(64, 128, alpha=0)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=0, w=128, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertTrue(zm.is_destroyed("bumper"), "Zone should be destroyed after alpha=0 update")

        # Restore alpha above threshold + 0.05 = 0.35 → use 255 (integrity=1.0)
        img[:, :, 3] = 255
        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertFalse(zm.is_destroyed("bumper"),
                         "is_destroyed should reset after integrity rises above threshold+0.05")

    def test_repair_allows_re_trigger(self):
        """After repair, dropping below threshold again fires the event a second time."""
        img = _make_image(64, 128, alpha=0)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=0, w=128, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")

        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)           # first destroy
            img[:, :, 3] = 255       # repair
            zm.update(img)
            img[:, :, 3] = 0         # destroy again
            zm.update(img)           # second destroy

        self.assertEqual(mock_pub.call_count, 2,
                         "Event should fire again after repair when integrity drops below threshold")


class TestZoneMask(unittest.TestCase):
    def test_mask_only_counts_masked_pixels(self):
        """With a mask, only masked pixels contribute to integrity.

        Set left half of zone to alpha=0, right half to alpha=255.
        Mask covers only right half → integrity should be ~1.0, not 0.5.
        """
        img = _make_image(64, 128, alpha=255)
        # Zone: x=0, y=0, w=40, h=40
        # Zero out left 20 columns of zone
        img[0:40, 0:20, 3] = 0
        # Right 20 columns remain 255

        # Mask: only right 20 columns active (cols 20..39 within the 40-wide zone)
        mask = np.zeros((40, 40), dtype=np.uint8)
        mask[:, 20:40] = 255  # only right half is tracked

        zm = ZoneMap(128, 64)
        zm.add_rect_zone("panel", x=0, y=0, w=40, h=40, threshold=0.3, mask=mask)

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        # Masked pixels are all alpha=255, so integrity should be 1.0
        self.assertAlmostEqual(zm.integrity("panel"), 1.0, places=5,
                               msg="Mask should exclude zero-alpha pixels from integrity computation")

    def test_mask_all_zeros_returns_full_integrity(self):
        """A mask of all zeros (no valid pixels) returns integrity=1.0 (safe default)."""
        img = _make_image(32, 64, alpha=0)  # image fully transparent
        mask = np.zeros((16, 16), dtype=np.uint8)  # no valid pixels

        zm = ZoneMap(64, 32)
        zm.add_rect_zone("zone", x=0, y=0, w=16, h=16, threshold=0.5, mask=mask)

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        self.assertAlmostEqual(zm.integrity("zone"), 1.0, places=5,
                               msg="All-zero mask should default to integrity=1.0 (no valid pixels)")


class TestZoneMapReset(unittest.TestCase):
    def test_reset_clears_all_flags(self):
        """After destroying multiple zones, reset() sets all is_destroyed=False and integrity=1.0."""
        img = _make_image(64, 128, alpha=0)  # zero alpha everywhere

        zm = ZoneMap(128, 64)
        zm.add_rect_zone("front_bumper", x=0, y=0, w=20, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")
        zm.add_rect_zone("rear_bumper", x=108, y=0, w=20, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")
        zm.add_rect_zone("cockpit", x=40, y=16, w=48, h=32, threshold=0.1,
                         on_destroy="Vehicle.CockpitDestroyed")

        with patch("slappyengine.deform_zones.publish"):
            zm.update(img)

        # Confirm all are destroyed
        for name in zm.zone_names():
            self.assertTrue(zm.is_destroyed(name), f"{name} should be destroyed before reset")

        zm.reset()

        for name in zm.zone_names():
            self.assertFalse(zm.is_destroyed(name), f"{name} is_destroyed should be False after reset")
            self.assertAlmostEqual(zm.integrity(name), 1.0,
                                   msg=f"{name} integrity should be 1.0 after reset")

    def test_reset_allows_events_to_fire_again(self):
        """After reset(), dropping below threshold fires the destroy event again."""
        img = _make_image(64, 128, alpha=0)
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=0, w=128, h=64, threshold=0.3,
                         on_destroy="Vehicle.BumperLost")

        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)      # destroy → 1 call
            zm.reset()          # reset flags
            zm.update(img)      # destroy again → 2nd call

        self.assertEqual(mock_pub.call_count, 2)


class TestZoneMapEdgeCases(unittest.TestCase):
    def test_update_with_none_image_does_nothing(self):
        """update() with None image_data is a no-op."""
        zm = ZoneMap(64, 32)
        zm.add_rect_zone("zone", x=0, y=0, w=32, h=16)
        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(None)  # type: ignore[arg-type]
        mock_pub.assert_not_called()
        self.assertAlmostEqual(zm.integrity("zone"), 1.0)

    def test_update_with_2d_image_does_nothing(self):
        """update() with a 2-D array (no channels) is a no-op."""
        img = np.zeros((32, 64), dtype=np.uint8)
        zm = ZoneMap(64, 32)
        zm.add_rect_zone("zone", x=0, y=0, w=32, h=16)
        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)  # type: ignore[arg-type]
        mock_pub.assert_not_called()

    def test_get_zone_returns_correct_def(self):
        """get_zone() returns the correct ZoneDef or None for unknown names."""
        zm = ZoneMap(128, 64)
        zm.add_rect_zone("bumper", x=0, y=16, w=20, h=32, threshold=0.4,
                         on_destroy="Vehicle.BumperLost", material="plastic")
        z = zm.get_zone("bumper")
        self.assertIsInstance(z, ZoneDef)
        self.assertEqual(z.name, "bumper")
        self.assertEqual(z.material, "plastic")
        self.assertIsNone(zm.get_zone("nonexistent"))

    def test_out_of_bounds_zone_rect_is_skipped(self):
        """A zone rect fully outside image bounds doesn't crash or mutate integrity."""
        img = _make_image(16, 16, alpha=128)
        zm = ZoneMap(16, 16)
        zm.add_rect_zone("oob", x=100, y=100, w=20, h=20)  # entirely outside 16x16
        with patch("slappyengine.deform_zones.publish") as mock_pub:
            zm.update(img)
        mock_pub.assert_not_called()
        # Integrity stays at initial 1.0 since no region was sampled
        self.assertAlmostEqual(zm.integrity("oob"), 1.0)


if __name__ == "__main__":
    unittest.main()
